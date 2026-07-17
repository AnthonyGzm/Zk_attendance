# -*- coding: utf-8 -*-
import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _tz_get(self):
    return [(tz, tz) for tz in sorted(pytz.common_timezones)]


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
    command_count = fields.Integer(string='Comandos Pendientes', compute='_compute_command_count')
    notes = fields.Text(string='Notas')

    tz = fields.Selection(_tz_get, string='Zona Horaria del Reloj',
                           default=lambda self: self.env.user.tz or 'UTC',
                           help='Zona horaria configurada FÍSICAMENTE en el reloj (Menú → Sistema → Fecha/Hora). '
                                'No siempre coincide con la de la compañía en Odoo, sobre todo si el equipo '
                                'está en una sucursal con otro huso horario. Se usa para convertir las marcaciones '
                                '(que el reloj reporta en su hora local) a UTC antes de guardarlas.')

    _sql_constraints = [
        ('serial_number_unique', 'unique(serial_number)',
         'Ya existe un dispositivo registrado con este número de serie.'),
    ]

    @api.depends()
    def _compute_log_count(self):
        Log = self.env['zk.attendance.log']
        for device in self:
            device.log_count = Log.search_count([('device_id', '=', device.id)])

    @api.depends()
    def _compute_command_count(self):
        Command = self.env['zk.device.command']
        for device in self:
            device.command_count = Command.search_count([
                ('device_id', '=', device.id), ('state', '=', 'pending'),
            ])

    def action_view_commands(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Comandos de %s' % self.name,
            'res_model': 'zk.device.command',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
            'context': {'default_device_id': self.id},
        }

    # ------------------------------------------------------------------
    # Probar conexión
    # ------------------------------------------------------------------
    def action_test_connection(self):
        """En SDK, se conecta ahora mismo al reloj (ping real). En ADMS,
        Odoo NO puede iniciar la conexión hacia el reloj —el protocolo es
        al revés, el reloj es quien llama a Odoo— así que en su lugar
        evalúa qué tan reciente fue la última comunicación recibida."""
        self.ensure_one()
        if self.connection_mode == 'sdk':
            return self._test_connection_sdk()
        return self._test_connection_adms()

    def _test_connection_sdk(self):
        if not self.ip_address:
            raise UserError(_('Indica la dirección IP del reloj para poder probar la conexión.'))

        try:
            from zk import ZK
        except ImportError:
            raise UserError(_(
                "La librería 'pyzk' no está instalada en el servidor de Odoo.\n"
                "Instálala ejecutando en la terminal del servidor:\n\n"
                "    pip install pyzk"
            ))

        zk_instance = ZK(self.ip_address, port=self.port or 4370,
                          timeout=self.sdk_timeout or 5, force_udp=False, ommit_ping=False)
        conn = None
        try:
            conn = zk_instance.connect()
            try:
                firmware = conn.get_firmware_version()
            except Exception:
                firmware = _('no disponible')
            try:
                serial = conn.get_serialnumber()
            except Exception:
                serial = self.serial_number or _('no disponible')

            self.write({'state': 'connected', 'last_communication': fields.Datetime.now()})
            message = _(
                'Se estableció conexión con %(ip)s:%(port)s\n\n'
                'Firmware: %(firmware)s\n'
                'Número de serie reportado: %(serial)s'
            ) % {
                'ip': self.ip_address,
                'port': self.port or 4370,
                'firmware': firmware,
                'serial': serial,
            }
            return self._notify(message, title=_('Conexión Exitosa'), msg_type='success')
        except Exception as exc:
            self.write({'state': 'error'})
            message = _(
                'No se pudo conectar con %(ip)s:%(port)s\n\nDetalle: %(error)s'
            ) % {'ip': self.ip_address, 'port': self.port or 4370, 'error': exc}
            return self._notify(message, title=_('Error de Conexión'), msg_type='danger')
        finally:
            if conn:
                try:
                    conn.disconnect()
                except Exception:
                    pass

    def _test_connection_adms(self):
        if not self.last_communication:
            message = _(
                'Este dispositivo todavía no se ha comunicado con Odoo.\n\n'
                'Revisa en el reloj: Comunicación → Cloud/ADMS → que la IP/puerto '
                'apunten a este servidor, y que el número de serie coincida '
                'exactamente con "%s".'
            ) % (self.serial_number or _('(sin número de serie configurado)'))
            return self._notify(message, title=_('Sin Comunicación'), msg_type='warning')

        delta = fields.Datetime.now() - self.last_communication
        minutes = delta.total_seconds() / 60

        if minutes <= 5:
            message = _(
                'El dispositivo se comunicó con Odoo hace %.0f minuto(s).\n'
                'La conexión ADMS está activa.'
            ) % minutes
            return self._notify(message, title=_('Dispositivo Activo'), msg_type='success')

        if minutes <= 60:
            message = _(
                'El dispositivo no se ha comunicado en los últimos %.0f minutos.\n\n'
                'Puede ser normal según el intervalo de sincronización configurado '
                'en el reloj. Si esperabas datos más recientes, revisa su red.'
            ) % minutes
            return self._notify(message, title=_('Sin Actividad Reciente'), msg_type='warning')

        hours = minutes / 60
        message = _(
            'El dispositivo no se ha comunicado en %.1f horas.\n\n'
            'Recuerda: en modo ADMS, Odoo no puede llamar al reloj —solo puede '
            'esperar a que el reloj llame—. Verifica que esté encendido, con red, '
            'y con la configuración de servidor correcta en Comunicación → Cloud/ADMS.'
        ) % hours
        return self._notify(message, title=_('Sin Comunicación Reciente'), msg_type='danger')

    def _queue_command(self, command_type, command_text):
        self.ensure_one()
        if self.connection_mode != 'adms':
            raise UserError(_(
                'La cola de comandos solo aplica al modo ADMS/Push: el reloj la '
                'consulta cada vez que hace polling a /iclock/getrequest. '
                'En modo SDK/pyzk, Odoo se conecta directamente y no necesita cola.'
            ))
        return self.env['zk.device.command'].create({
            'device_id': self.id,
            'command_type': command_type,
            'command_text': command_text,
        })

    def action_queue_reboot(self):
        self.ensure_one()
        self._queue_command('reboot', 'REBOOT')
        return self._notify(_(
            'Reinicio encolado. Se ejecutará en la próxima vez que el reloj '
            'consulte comandos pendientes (según su intervalo de Delay/TransInterval).'
        ))

    def action_queue_clear_log(self):
        self.ensure_one()
        self._queue_command('clear_log', 'CLEAR LOG')
        return self._notify(_(
            'Limpieza de registros encolada. ⚠️ Esto borra las marcaciones '
            'almacenadas EN LA MEMORIA DEL RELOJ (no las ya recibidas en Odoo).'
        ))

    # ------------------------------------------------------------------
    # Conversión de zona horaria
    # ------------------------------------------------------------------
    def _localize_naive_datetime(self, naive_dt):
        """El reloj reporta la marcación en su hora LOCAL (naive, sin tz).
        Odoo guarda todo en UTC. Esta función localiza ese datetime según
        la zona horaria configurada en el dispositivo (o, si no está
        definida, la de la compañía) y lo convierte a UTC naive, listo
        para guardar en un campo Datetime de Odoo."""
        self.ensure_one()
        if not naive_dt:
            return naive_dt
        tz_name = self.tz or self.env.user.tz or 'UTC'
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.UTC
        try:
            localized = tz.localize(naive_dt, is_dst=None)
        except pytz.exceptions.AmbiguousTimeError:
            # Hora ambigua por cambio de horario (fall-back): asumimos DST activo
            localized = tz.localize(naive_dt, is_dst=True)
        except pytz.exceptions.NonExistentTimeError:
            # Hora inexistente por cambio de horario (spring-forward): la desplazamos 1h
            localized = tz.localize(naive_dt, is_dst=False)
        return localized.astimezone(pytz.UTC).replace(tzinfo=None)

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
                # rec.timestamp es un datetime naive con la hora LOCAL del reloj
                # (igual que en el push ADMS): se convierte con el mismo método.
                punch_dt = self._localize_naive_datetime(rec.timestamp)
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
        """Abre el diálogo de feedback con diseño propio (insignia de color +
        mensaje), en vez del toast genérico de Odoo (display_notification)."""
        feedback = self.env['zk.device.feedback'].create({
            'title': title or _('Caremax Attendance'),
            'message': message,
            'feedback_type': msg_type if msg_type in ('success', 'warning', 'danger', 'info') else 'info',
            'device_id': self.id if self else False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zk.device.feedback',
            'view_mode': 'form',
            'res_id': feedback.id,
            'target': 'new',
            'name': title or _('Caremax Attendance'),
        }
