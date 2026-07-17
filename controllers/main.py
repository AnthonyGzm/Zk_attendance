# -*- coding: utf-8 -*-
import logging
from urllib.parse import parse_qs

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


def parse_devicecmd_line(line):
    """Parsea una línea de confirmación que el reloj envía a /iclock/devicecmd,
    con formato tipo query-string: 'ID=3&Return=0&CMD=REBOOT'.
    Es una función pura (sin dependencias de Odoo) para poder testearla aislada.
    Devuelve un dict simple, p.ej. {'ID': '3', 'Return': '0', 'CMD': 'REBOOT'}."""
    line = (line or '').strip()
    if not line:
        return {}
    parsed = parse_qs(line, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


class ZkTecoController(http.Controller):
    def _get_or_create_device(self, serial_number):
        Device = request.env['zk.device'].sudo().with_context(active_test=False)
        device = Device.search([('serial_number', '=', serial_number)], limit=1)
        vals = {
            'last_communication': fields.Datetime.now(),
            'ip_address': request.httprequest.remote_addr,
            'state': 'connected',
        }
        if not device:
            vals.update({
                'name': 'Dispositivo %s' % serial_number,
                'serial_number': serial_number,
                'connection_mode': 'adms',
            })
            device = Device.create(vals)
        else:
            if not device.active:
                vals['active'] = True
            device.write(vals)
        return device

    def _plain(self, text):
        return request.make_response(text, headers=[('Content-Type', 'text/plain')])

    def _process_attlog(self, device, body):
        Log = request.env['zk.attendance.log'].sudo()
        Employee = request.env['hr.employee'].sudo()
        created = 0

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) < 2:
                continue

            pin = parts[0].strip()
            time_str = parts[1].strip()
            status = parts[2].strip() if len(parts) > 2 else '0'
            verify = parts[3].strip() if len(parts) > 3 else ''

            try:
                naive_dt = fields.Datetime.to_datetime(time_str)
            except Exception:
                _logger.warning('ZKTeco: no se pudo interpretar la fecha "%s"', time_str)
                continue
            punch_dt = device._localize_naive_datetime(naive_dt)

            # Evitar duplicados si el equipo reenvía el mismo dato
            exists = Log.search_count([
                ('device_id', '=', device.id),
                ('device_pin', '=', pin),
                ('punch_datetime', '=', punch_dt),
            ])
            if exists:
                continue

            employee = Employee.search([('zk_pin', '=', pin)], limit=1)
            Log.create({
                'device_id': device.id,
                'device_pin': pin,
                'employee_id': employee.id if employee else False,
                'punch_datetime': punch_dt,
                'punch_type': status if status in ('0', '1', '2', '3', '4', '5') else '0',
                'verify_type': verify,
                'raw_data': line,
            })
            created += 1

        if created:
            pending = Log.search([
                ('device_id', '=', device.id),
                ('processed', '=', False),
            ], order='punch_datetime asc')
            pending.action_process()

        return created

    # ------------------------------------------------------------------
    # Rutas del protocolo ADMS
    # ------------------------------------------------------------------
    @http.route('/iclock/cdata', type='http', auth='none', methods=['GET', 'POST'], csrf=False)
    def iclock_cdata(self, **kwargs):
        serial_number = kwargs.get('SN') or kwargs.get('sn')
        if not serial_number:
            return self._plain('ERROR: SN requerido')

        device = self._get_or_create_device(serial_number)

        if request.httprequest.method == 'GET':
            att_stamp = device.adms_stamp or '9999'
            response_lines = [
                'GET OPTION FROM: %s' % serial_number,
                'Stamp=9999',
                'OpStamp=9999',
                'ATTLOGStamp=%s' % att_stamp,
                'ErrorDelay=30',
                'Delay=10',
                'TransFlag=1111000000',
                'TransInterval=1',
                'TransTimes=00:00;14:05',
                'Realtime=1',
                'Encrypt=0',
            ]
            return self._plain('\n'.join(response_lines) + '\n')

        # POST: el equipo está subiendo datos (tabla ATTLOG, OPERLOG, etc.)
        table = (kwargs.get('table') or '').upper()
        body = request.httprequest.get_data(as_text=True) or ''
        stamp = kwargs.get('Stamp') or kwargs.get('stamp')

        if table == 'ATTLOG':
            count = self._process_attlog(device, body)
            if stamp:
                device.write({'adms_stamp': stamp})
            return self._plain('OK: %s' % count)


        _logger.info('ZKTeco: tabla "%s" recibida y no procesada (SN=%s)', table, serial_number)
        return self._plain('OK')

    @http.route('/iclock/getrequest', type='http', auth='none', methods=['GET'], csrf=False)
    def iclock_getrequest(self, **kwargs):
        serial_number = kwargs.get('SN') or kwargs.get('sn')
        if not serial_number:
            return self._plain('OK')

        device = self._get_or_create_device(serial_number)

        Command = request.env['zk.device.command'].sudo()
        pending = Command.search([
            ('device_id', '=', device.id),
            ('state', '=', 'pending'),
        ], order='create_date asc', limit=20)

        if not pending:
            return self._plain('OK')

        # Formato estándar ADMS: una línea por comando, "C:<id>:<comando>"
        # El <id> lo elegimos nosotros (usamos el id del propio registro) y el
        # reloj lo devolverá tal cual al confirmar en /iclock/devicecmd, lo que
        # nos permite emparejar la confirmación sin ambigüedad.
        lines = ['C:%s:%s' % (cmd.id, cmd.command_text) for cmd in pending]
        pending.write({'state': 'sent', 'sent_date': fields.Datetime.now()})
        _logger.info('ZKTeco: %s comando(s) enviados a %s', len(pending), serial_number)
        return self._plain('\n'.join(lines) + '\n')

    @http.route('/iclock/devicecmd', type='http', auth='none', methods=['POST'], csrf=False)
    def iclock_devicecmd(self, **kwargs):
        serial_number = kwargs.get('SN') or kwargs.get('sn')
        if serial_number:
            self._get_or_create_device(serial_number)

        body = request.httprequest.get_data(as_text=True) or ''
        Command = request.env['zk.device.command'].sudo()

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            data = parse_devicecmd_line(line)
            cmd_id = data.get('ID')
            if not cmd_id or not cmd_id.isdigit():
                continue

            command = Command.browse(int(cmd_id)).exists()
            if not command:
                continue

            return_code = data.get('Return', '')
            command.write({
                'return_code': return_code,
                'state': 'done' if return_code == '0' else 'error',
                'done_date': fields.Datetime.now(),
            })

        return self._plain('OK')

    @http.route('/iclock/fdata', type='http', auth='none', methods=['POST'], csrf=False)
    def iclock_fdata(self, **kwargs):
        # Datos biométricos binarios (fotos, plantillas). No se procesan aquí.
        return self._plain('OK')
