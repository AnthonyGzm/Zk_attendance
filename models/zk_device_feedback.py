# -*- coding: utf-8 -*-
from odoo import fields, models


class ZkDeviceFeedback(models.TransientModel):
    _name = 'zk.device.feedback'
    _description = 'Aviso de Resultado de Operación ZKTeco'

    title = fields.Char(string='Título', default='Caremax Attendance')
    message = fields.Text(string='Mensaje')
    feedback_type = fields.Selection([
        ('success', 'Éxito'),
        ('warning', 'Advertencia'),
        ('danger', 'Error'),
        ('info', 'Información'),
    ], string='Tipo', default='success', required=True)
    device_id = fields.Many2one('zk.device', string='Dispositivo')
