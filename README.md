# Asistencia ZKTeco (ADMS Push) — Odoo 18

Módulo para Odoo 18 que integra dispositivos biométricos **ZKTeco** (huella,
tarjeta o rostro) con el módulo nativo de Asistencias (`hr_attendance`),
generando registros de **check-in / check-out** automáticamente a partir de
las marcaciones del equipo.

Soporta dos modos de conexión:

| Modo | Cómo funciona | Cuándo usarlo |
|---|---|---|
| **ADMS / Push** (recomendado) | El reloj envía las marcaciones directamente a Odoo por HTTP (protocolo estándar iClock/ADMS). No requiere librerías extra ni que Odoo tenga acceso de red al equipo. | Servidor accesible desde la red del reloj (o vía túnel/VPN). |
| **SDK / pyzk** | Odoo se conecta activamente al reloj por su IP para descargar las marcaciones. | El reloj no soporta ADMS, o prefieres sincronización manual/bajo demanda. |

---

## Funcionalidades

- Registro automático de dispositivos ZKTeco al conectarse (modo ADMS).
- Recepción de marcaciones en tiempo real vía protocolo iClock/ADMS.
- Sincronización manual/bajo demanda vía SDK (`pyzk`) como alternativa.
- Mapeo del PIN/UID del dispositivo a empleados de Odoo (`hr.employee`).
- Creación y cierre automático de asistencias (`hr.attendance`), alternando
  check-in / check-out según el estado del empleado.
- Bitácora completa de marcaciones crudas, con estado (procesado / pendiente)
  y reprocesamiento manual por registro o masivo.
- Barra de estado por dispositivo: **Sin conectar → Conectado → Error**.
- Botón para forzar el reenvío completo del historial del reloj.

---

##  Requisitos

- Odoo **18.0**
- Módulo `hr_attendance` (dependencia estándar de Odoo, se instala solo)
- Para el modo **SDK**: librería [`pyzk`](https://pypi.org/project/pyzk/)
  instalada en el entorno Python del servidor:

  ```bash
  pip install pyzk
  ```

  (No es necesaria si solo usarás el modo ADMS/Push).

---

## Instalación

1. Copia la carpeta `zk_attendance` dentro de tu ruta de addons, por ejemplo:
   ```
   <ruta-odoo>/server/odoo/addons/zk_attendance
   ```
   o en tu carpeta de addons personalizados si la tienes configurada en
   `addons_path` dentro de `odoo.conf`.
2. Reinicia el servicio de Odoo por completo (los cambios en archivos `.py`
   solo se cargan al reiniciar el proceso).
3. En Odoo: **Ajustes → Apps → Actualizar Lista de Aplicaciones**.
4. Quita el filtro "Apps" en el buscador (este módulo no es una app
   principal), busca **"ZKTeco"** e instálalo.

>  Si actualizas el código luego de una instalación previa, recuerda
> siempre **detener el servicio de Odoo antes de reemplazar los archivos**,
> y volver a iniciarlo antes de darle "Actualizar" al módulo desde Apps.
> Actualizar solo desde la interfaz no recarga el código Python si el
> proceso del servidor ya está corriendo.

---

##  Configuración — Modo ADMS / Push (recomendado)

1. Ve a **Asistencias → ZKTeco → Dispositivos → Nuevo**.
2. Elige el modo de conexión **"ADMS / Push — Reloj conecta a Odoo"**.
3. (Opcional) Ingresa el **Número de Serie** del equipo si ya lo conoces —
   si lo dejas vacío, el dispositivo se registrará solo apenas se conecte.
4. En el reloj ZKTeco, ve a:

   **Menú → Comunicación → Nube / ADMS**
   - **Server Address:** IP o dominio donde corre tu Odoo
   - **Server Port:** `8069` (o el puerto que uses; `443` si tienes HTTPS
     detrás de un proxy)
   - Activa **Enable ADMS** / **Enable Domain Name** según tu equipo
   - El número de serie aparece en **Menú → Sistema → Información del
     dispositivo**

5. Guarda. Cuando el reloj se conecte, el estado del dispositivo en Odoo
   pasará a **"Conectado"** automáticamente.

### Endpoints implementados (protocolo iClock/ADMS)

| Ruta | Método | Uso |
|---|---|---|
| `/iclock/cdata` | GET | Handshake / entrega de configuración al reloj |
| `/iclock/cdata` | POST | Recepción de marcaciones (tabla `ATTLOG`) |
| `/iclock/getrequest` | GET | Polling del reloj por comandos pendientes |
| `/iclock/devicecmd` | POST | Resultado de comandos ejecutados por el reloj |
| `/iclock/fdata` | POST | Datos biométricos binarios (no se procesan) |

---

##  Configuración — Modo SDK / pyzk

1. Instala `pyzk` en el servidor (ver [Requisitos](#-requisitos)).
2. Ve a **Asistencias → ZKTeco → Dispositivos → Nuevo**.
3. Elige el modo de conexión **"SDK / pyzk — Odoo conecta al reloj"**.
4. Completa la **Dirección IP**, **Puerto** (por defecto `4370`) y
   **Timeout** del equipo.
5. Usa el botón **"Reenviar Todos los Registros"** para conectarte al reloj
   y traer todas las marcaciones bajo demanda.

> Este modo requiere que el servidor de Odoo tenga acceso de red directo al
> reloj (misma LAN o VPN).

---

##  Vincular empleados con el reloj

1. Abre la ficha del empleado en **Empleados**.
2. Ve a la pestaña **ZKTeco**.
3. En **Reloj Checador → UID ZKTeco**, ingresa el mismo PIN/UID configurado
   para ese usuario en el equipo biométrico.

Las marcaciones cuyo PIN no coincida con ningún empleado quedarán guardadas
como **pendientes** (visibles en el filtro "Sin Empleado Asignado") hasta
que asignes el UID correspondiente; luego puedes reprocesarlas manualmente.

---

## Dónde ver todo

- **Asistencias → ZKTeco → Dispositivos**: estado, configuración y
  sincronización de cada reloj.
- **Asistencias → ZKTeco → Registros**: bitácora cruda de marcaciones, con
  el tipo (entrada/salida), si fue procesada, y la asistencia generada.
- **Asistencias → Información general / Gestión**: las asistencias
  generadas se integran de forma nativa con las vistas estándar de
  `hr_attendance`.

---

## Estructura del módulo

```
zk_attendance/
├── controllers/
│   └── main.py              # Endpoints del protocolo ADMS/iClock
├── models/
│   ├── zk_device.py         # Dispositivos (ADMS y SDK)
│   ├── zk_attendance_log.py # Bitácora cruda + lógica check-in/check-out
│   └── hr_employee.py       # Campo UID ZKTeco en el empleado
├── views/
│   ├── zk_device_views.xml
│   ├── zk_attendance_log_views.xml
│   ├── hr_employee_views.xml
│   └── menu.xml
├── security/
│   └── ir.model.access.csv
├── data/
│   └── ir_cron.xml          # Reproceso automático de pendientes cada 10 min
└── __manifest__.py
```

---


##  Contribuciones

Los *pull requests* son bienvenidos. Para cambios grandes, abre primero un
*issue* para discutir qué te gustaría modificar.

## Autor
Creado por Anthony Guzman 
