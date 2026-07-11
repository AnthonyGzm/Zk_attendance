# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ZkAttendanceLog(models.Model):
    _name = 'zk.attendance.log'
    _description = 'Registro Crudo de Marcación ZKTeco'
    _order = 'punch_datetime desc'

    device_id = fields.Many2one('zk.device', string='Dispositivo', required=True,
                                 ondelete='cascade', index=True)
    device_pin = fields.Char(string='PIN del Dispositivo', required=True, index=True,
                              help='Identificador del usuario configurado en el equipo ZKTeco.')
    employee_id = fields.Many2one('hr.employee', string='Empleado', ondelete='set null', index=True)
    punch_datetime = fields.Datetime(string='Fecha/Hora Marcación', required=True, index=True)
    punch_type = fields.Selection([
        ('0', 'Entrada'),
        ('1', 'Salida'),
        ('2', 'Salida a Descanso'),
        ('3', 'Entrada de Descanso'),
        ('4', 'Entrada Horas Extra'),
        ('5', 'Salida Horas Extra'),
    ], string='Tipo', default='0')
    verify_type = fields.Char(string='Método de Verificación',
                               help='0=Password 1=Huella 2=Tarjeta 15=Rostro, según el equipo.')
    raw_data = fields.Char(string='Línea Cruda', help='Línea original recibida del dispositivo.')
    processed = fields.Boolean(string='Procesado', default=False, index=True)
    attendance_id = fields.Many2one('hr.attendance', string='Asistencia', readonly=True)
    attendance_display = fields.Char(string='Asistencia Generada', compute='_compute_attendance_display')

    _sql_constraints = [
        ('punch_unique', 'unique(device_id, device_pin, punch_datetime)',
         'Esta marcación ya fue registrada (duplicado del dispositivo).'),
    ]

    @api.depends('attendance_id', 'attendance_id.check_in', 'attendance_id.check_out',
                 'attendance_id.worked_hours')
    def _compute_attendance_display(self):
        for log in self:
            att = log.attendance_id
            if not att:
                log.attendance_display = ''
                continue
            worked = att.worked_hours or 0.0
            hours = int(worked)
            minutes = int(round((worked - hours) * 60))
            check_in = fields.Datetime.context_timestamp(log, att.check_in) if att.check_in else False
            check_out = fields.Datetime.context_timestamp(log, att.check_out) if att.check_out else False
            in_str = check_in.strftime('%H:%M:%S') if check_in else '--:--:--'
            out_str = check_out.strftime('%H:%M:%S') if check_out else '--:--:--'
            log.attendance_display = '%02d:%02d (%s-%s)' % (hours, minutes, in_str, out_str)

    def action_process(self):
        """Convierte los logs crudos en registros de hr.attendance (check-in / check-out),
        alternando según si el empleado tiene una asistencia abierta."""
        Attendance = self.env['hr.attendance']
        for log in self.sorted(key=lambda l: l.punch_datetime):
            if log.processed:
                continue
            if not log.employee_id:
                # Intentar volver a mapear por si el PIN se asignó después
                employee = self.env['hr.employee'].search([('zk_pin', '=', log.device_pin)], limit=1)
                if employee:
                    log.employee_id = employee.id
                else:
                    continue  # sin empleado mapeado, se deja pendiente

            open_attendance = Attendance.search([
                ('employee_id', '=', log.employee_id.id),
                ('check_out', '=', False),
            ], order='check_in desc', limit=1)

            if open_attendance and log.punch_datetime > open_attendance.check_in:
                open_attendance.write({'check_out': log.punch_datetime})
                log.write({'attendance_id': open_attendance.id, 'processed': True})
            elif not open_attendance:
                new_attendance = Attendance.create({
                    'employee_id': log.employee_id.id,
                    'check_in': log.punch_datetime,
                })
                log.write({'attendance_id': new_attendance.id, 'processed': True})
            else:
                # La marcación es anterior al check_in abierto: se ignora (log desordenado)
                log.write({'processed': True})

    def action_force_reprocess(self):
        """Botón 'Reprocesar' de la lista: fuerza el recálculo aunque el
        registro ya estuviera marcado como procesado."""
        for log in self:
            if log.attendance_id and not log.attendance_id.check_out:
                # Si el check-out todavía depende de este log, no lo tocamos
                pass
            log.write({'processed': False})
        self.action_process()

    @api.model
    def cron_process_pending(self):
        pending = self.search([('processed', '=', False)], order='punch_datetime asc', limit=2000)
        pending.action_process()
