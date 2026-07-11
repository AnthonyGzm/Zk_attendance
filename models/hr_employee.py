# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    zk_pin = fields.Char(
        string='UID ZKTeco',
        copy=False,
        help='ID de usuario configurado en el dispositivo de asistencia ZKTeco. '
             'Debe coincidir exactamente con el PIN/UID registrado en el equipo.'
    )

    _sql_constraints = [
        ('zk_pin_unique', 'unique(zk_pin)',
         'Ya existe otro empleado con este PIN de ZKTeco.'),
    ]
