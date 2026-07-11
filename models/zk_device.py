# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ZkDevice(models.Model):
    _name = 'zk.device'
    _description = 'Dispositivo de Asistencia ZKTeco'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True, default='Nuevo Dispositivo')
    active = fields.Boolean(default=True)
    connection_mode = fields.Selection([
        ('adms', 'ADMS / Push — Reloj conecta a Odoo'),
        ('sdk', 'SDK / pyzk — Odoo conecta al reloj'),
    ], string='Modo de Conexión', default='adms', required=True)

    state = fields.Selection([
        ('not_connected', 'Sin conectar'),
        ('connected', 'Conectado'),
        ('error', 'Error'),
    ], string='Estado', default='not_connected', copy=False)

    # --- ADMS / Push ---
    serial_number = fields.Char(string='Número de Serie', copy=False, index=True,
                                 help='Debe coincidir con el número de serie configurado en el reloj '
                                      '(Menú → Sistema → Información del dispositivo).')
    adms_stamp = fields.Char(string='ADMS Stamp', readonly=True, copy=False,
                              help='Marca de sincronización incremental que usa el reloj para saber '
                                   'qué marcaciones ya fueron entregadas a Odoo.')
    last_communication = fields.Datetime(string='Última Sincronización', readonly=True, copy=False)

    # --- SDK / pyzk ---
    ip_address = fields.Char(string='Dirección IP', help='IP del reloj en la red local (requerida en modo SDK).')
    port = fields.Integer(string='Puerto', default=4370)
    sdk_timeout = fields.Integer(string='Timeout (segundos)', default=5)

    location = fields.Char(string='Ubicación')
    log_count = fields.Integer(string='Registros', compute='_compute_log_count')
    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('serial_number_unique', 'unique(serial_number)',
         'Ya existe un dispositivo registrado con este número de serie.'),
    ]

    def _compute_log_count(self):
        Log = self.env['zk.attendance.log']
        for device in self:
            device.log_count = Log.search_count([('device_id', '=', device.id)])

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registros de %s' % self.name,
            'res_model': 'zk.attendance.log',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
            'context': {'default_device_id': self.id},
        }

    # ------------------------------------------------------------------
    # Procesar pendientes (ambos modos)
    # ------------------------------------------------------------------
    def action_reprocess_pending(self):
        """Reintenta el paso de logs -> hr.attendance para las marcaciones
        aún no procesadas (útil si el PIN se asignó al empleado después)."""
        logs = self.env['zk.attendance.log'].search([
            ('device_id', 'in', self.ids),
            ('processed', '=', False),
        ], order='punch_datetime asc')
        logs.action_process()
        return self._notify(_('Se procesaron %s marcaciones pendientes.') % len(logs))

    # ------------------------------------------------------------------
    # Reenviar todos los registros
    # ------------------------------------------------------------------
    def action_resend_all_records(self):
        """En modo SDK: se conecta ahora mismo al reloj y trae todas las
        marcaciones. En modo ADMS: reinicia el stamp para que, en la
        siguiente conexión del reloj, éste reenvíe todo su historial."""
        self.ensure_one()
        if self.connection_mode == 'sdk':
            return self.action_sdk_sync()

        self.write({'adms_stamp': '0'})
        return self._notify(
            _('Se solicitó el reenvío completo. En la próxima conexión del '
              'reloj (según su intervalo de sincronización), Odoo recibirá '
              'nuevamente todo el historial de marcaciones.')
        )

    # ------------------------------------------------------------------
    # Modo SDK / pyzk
    # ------------------------------------------------------------------
    def action_sdk_sync(self):
        self.ensure_one()
        if self.connection_mode != 'sdk':
            raise UserError(_('Este dispositivo no está configurado en modo SDK / pyzk.'))
        if not self.ip_address:
            raise UserError(_('Indica la dirección IP del reloj para poder conectarte por SDK.'))

        try:
            from zk import ZK
        except ImportError:
            raise UserError(_(
                "La librería 'pyzk' no está instalada en el servidor de Odoo.\n"
                "Instálala ejecutando en la terminal del servidor:\n\n"
                "    pip install pyzk"
            ))

        Log = self.env['zk.attendance.log'].sudo()
        Employee = self.env['hr.employee'].sudo()
        zk_instance = ZK(self.ip_address, port=self.port or 4370,
                          timeout=self.sdk_timeout or 5, force_udp=False, ommit_ping=False)
        conn = None
        try:
            conn = zk_instance.connect()
            conn.disable_device()
            records = conn.get_attendance()
            created = 0
            for rec in records:
                pin = str(rec.user_id)
                punch_dt = fields.Datetime.to_string(rec.timestamp)
                exists = Log.search_count([
                    ('device_id', '=', self.id),
                    ('device_pin', '=', pin),
                    ('punch_datetime', '=', punch_dt),
                ])
                if exists:
                    continue
                employee = Employee.search([('zk_pin', '=', pin)], limit=1)
                Log.create({
                    'device_id': self.id,
                    'device_pin': pin,
                    'employee_id': employee.id if employee else False,
                    'punch_datetime': punch_dt,
                    'punch_type': str(getattr(rec, 'punch', 0)) if str(getattr(rec, 'punch', 0)) in
                                  ('0', '1', '2', '3', '4', '5') else '0',
                    'verify_type': str(getattr(rec, 'status', '')),
                    'raw_data': 'SDK PIN=%s TS=%s' % (pin, punch_dt),
                })
                created += 1
            conn.enable_device()
            self.write({'state': 'connected', 'last_communication': fields.Datetime.now()})
        except UserError:
            raise
        except Exception as exc:
            self.write({'state': 'error'})
            raise UserError(_('No se pudo conectar con el dispositivo %s:%s → %s')
                             % (self.ip_address, self.port or 4370, exc))
        finally:
            if conn:
                try:
                    conn.disconnect()
                except Exception:
                    pass

        if created:
            pending = Log.search([('device_id', '=', self.id), ('processed', '=', False)],
                                  order='punch_datetime asc')
            pending.action_process()

        return self._notify(_('Sincronización exitosa: %s marcaciones nuevas.') % created)

    def _notify(self, message, title=None, msg_type='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title or _('ZKTeco'),
                'message': message,
                'type': msg_type,
                'sticky': False,
            },
        }
