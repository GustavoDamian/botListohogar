# 🤖 Motor IA Multi-Asesor - ListoHogar

Este repositorio contiene el código fuente del motor de Inteligencia Artificial desarrollado para la inmobiliaria ListoHogar. Funciona como el "cerebro" orquestador que conecta los canales de comunicación de los clientes con el backend de gestión de citas de la empresa.

## 🚀 Arquitectura del Sistema

El sistema utiliza una arquitectura híbrida de tres nodos principales:
1. **Chatwoot (Frontend/Omnicanal):** Centraliza los mensajes de múltiples redes sociales (Facebook, Instagram, WhatsApp) mediante "Inboxes" independientes para cada asesor.
2. **Motor Flask (Middleware IA):** Escucha los webhooks de Chatwoot, procesa el lenguaje natural con OpenAI (GPT-4o-mini) y determina la intención del cliente basándose en el historial de chat.
3. **AWS API (Backend ListoHogar):** Provee el catálogo inmobiliario en tiempo real y registra las citas confirmadas directamente en la base de datos de producción.

## ⚙️ Características Principales

* **Enrutamiento Multi-Asesor Inteligente:** El script lee el `inbox_id` de origen y adapta dinámicamente la "personalidad" del bot (ej. Asistente de Daniela, Asistente de Julio) y asigna las citas al ID correcto en la base de datos.
* **Function Calling (Ejecución de Código):** La IA no solo genera texto, sino que tiene la capacidad estructurada de extraer parámetros (ID Propiedad, Fecha, Hora) y disparar la función de agendamiento.
* **Control de Zona Horaria:** Implementación de `pytz` forzando la zona horaria de Ecuador (America/Guayaquil) para evitar desfasajes en fechas relativas ("mañana", "el martes") al estar alojado en servidores internacionales.
* **Handoff a Humano:** El bot verifica el estado de la conversación en Chatwoot. Si un humano interviene y la conversación deja de estar "Open", el bot se silencia automáticamente.

## 📁 Estructura del Proyecto

* `app.py`: Archivo principal. Contiene el servidor Flask, el receptor de webhooks, el panel de configuración del mapeo de Inboxes y la lógica central de OpenAI.
* `api_listohogar.py`: Módulo de conexión con la infraestructura de AWS de ListoHogar. Maneja la autenticación por token, la extracción del catálogo y el POST de reservas.
* `requirements.txt`: Listado de dependencias para el despliegue en producción.
* `.gitignore`: Filtros de seguridad para evitar la exposición de credenciales y archivos temporales.

## 🔐 Variables de Entorno Necesarias

Para que el sistema funcione en producción, es obligatorio configurar las siguientes variables de entorno en el servidor de despliegue (nunca en el código fuente):

* `OPENAI_API_KEY`: Clave de acceso a la API de OpenAI.
* `CHATWOOT_ACCOUNT_ID`: ID numérico de la cuenta en Chatwoot (ej. 1).
* `CHATWOOT_API_TOKEN`: Token de acceso del perfil administrador en Chatwoot.

## ☁️ Instrucciones de Despliegue (Render)

Este proyecto está optimizado para ser desplegado en servicios cloud como Render como un "Web Service".

1. Conectar este repositorio de GitHub al Web Service.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `gunicorn --bind 0.0.0.0:5000 app:app`
4. Cargar las Variables de Entorno en el panel de configuración del hosting.
5. Copiar la URL pública asignada (ej. `https://listohogar-ia.onrender.com`) y configurarla dentro de Chatwoot en: *Ajustes > Integraciones > Webhooks* (añadiendo `/webhook` al final de la URL).

## 🛠️ Mantenimiento Operativo

Cuando se incorpore un nuevo asesor o se conecte una nueva red social, se generará un nuevo Inbox en Chatwoot. Para que la IA lo reconozca, simplemente se debe editar el diccionario `MAPEO_INBOX_ASESOR` en la cabecera del archivo `app.py`:

```python
MAPEO_INBOX_ASESOR = {
    # ID Inbox Chatwoot : {"id_samir": ID AWS, "nombre": "Nombre Asesor"}
    10: {"id_samir": 1, "nombre": "Daniela Cevalloz"},
    11: {"id_samir": 2, "nombre": "Julio"},
    "default": {"id_samir": 1, "nombre": "ListoHogar (Central)"} 
}
