# -*- coding: utf-8 -*-
from odoo import _, fields, models


class ZkDeviceCommand(models.Model):
    _name = 'zk.device.command'
    _description = 'Comando Pendiente para Dispositivo ZKTeco (ADMS/Push)'
    _order = 'create_date asc'

    device_id = fields.Many2one('zk.device', string='Dispositivo', required=True,
                                 ondelete='cascade', index=True)
    command_type = fields.Selection([
        ('custom', 'Comando Personalizado'),
        ('reboot', 'Reiniciar Dispositivo'),
        ('clear_log', 'Borrar Registros de Asistencia del Reloj'),
        ('update_userinfo', 'Actualizar Datos de Empleado'),
        ('delete_user', 'Eliminar Usuario del Reloj'),
    ], string='Tipo', default='custom', required=True)
    command_text = fields.Text(
        string='Comando (texto ADMS)', required=True,
        help='Texto exacto que se enviará al dispositivo tal cual lo espera el '
             'protocolo ADMS, por ejemplo:\n'
             'REBOOT\n'
             'CLEAR LOG\n'
             'DATA UPDATE USERINFO PIN=1\tName=Juan Perez\tPri=0\tPasswd=\tCard=\tGrp=1\tTZ=0000000100000000\tVerify=0\n'
             'DATA DELETE USERINFO PIN=1')
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('sent', 'Enviado (esperando confirmación)'),
        ('done', 'Confirmado por el Dispositivo'),
        ('error', 'Error'),
    ], string='Estado', default='pending', required=True, index=True, copy=False)
    return_code = fields.Char(string='Código de Retorno', copy=False, readonly=True,
                               help='Valor "Return" reportado por el dispositivo. 0 = éxito, '
                                    'negativo = error (ver manual del protocolo ADMS del fabricante).')
    sent_date = fields.Datetime(string='Fecha de Envío', readonly=True, copy=False)
    done_date = fields.Datetime(string='Fecha de Confirmación', readonly=True, copy=False)

    def action_cancel(self):
        """Cancela comandos que aún no fueron enviados al dispositivo."""
        self.filtered(lambda c: c.state == 'pending').write({
            'state': 'error',
            'return_code': 'CANCELLED',
        })

    def action_retry(self):
        """Vuelve a poner en cola un comando que falló o quedó atascado en 'sent'."""
        self.write({
            'state': 'pending',
            'return_code': False,
            'sent_date': False,
            'done_date': False,
        })
