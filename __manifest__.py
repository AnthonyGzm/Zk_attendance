# -*- coding: utf-8 -*-
{
    'name': 'Asistencia ZKTeco (ADMS Push)',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Attendances',
    'summary': 'Integra dispositivos biométricos ZKTeco con Odoo Attendance vía protocolo push (ADMS/iClock)',
    'description': """
Asistencia ZKTeco (ADMS Push)
==============================
Este módulo permite que los dispositivos de asistencia ZKTeco (huella,
tarjeta o rostro) envíen las marcaciones directamente a Odoo mediante el
protocolo estándar iClock/ADMS (push), sin necesidad de instalar software
adicional en el servidor ni consultar el equipo por red.

Funcionalidades:
----------------
* Registro automático de dispositivos que se conectan.
* Recepción de marcaciones (check-in / check-out) en tiempo real.
* Mapeo de PIN del dispositivo a empleados de Odoo (hr.employee).
* Creación automática de registros en hr.attendance.
* Bitácora de marcaciones crudas para auditoría y reprocesamiento.
""",
    'author': 'Tu Empresa',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['hr_attendance'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/hr_employee_views.xml',
        'views/zk_device_views.xml',
        'views/zk_attendance_log_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
