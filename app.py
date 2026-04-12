import os
import json
from datetime import datetime
import pytz
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import api_listohogar

# Carga de variables de entorno
load_dotenv()

app = Flask(__name__)

# Configuración de credenciales seguras
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Token de seguridad para blindar nuestro servidor de peticiones externas no autorizadas
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "listohogar_seguro_123") 

client = OpenAI(api_key=OPENAI_API_KEY)

def obtener_hora_ecuador():
    """Ajuste de zona horaria para compensar el offset del servidor en la nube (UTC a ECT)."""
    zona_ec = pytz.timezone('America/Guayaquil')
    return datetime.now(zona_ec).strftime("%Y-%m-%d")

def obtener_system_prompt(nombre_asesor, id_asesor):
    """Construye el system prompt consultando el catálogo dinámico según el asesor."""
    catalogo_actual = api_listohogar.obtener_catalogo_para_ia(id_asesor=id_asesor)
    fecha_hoy = obtener_hora_ecuador()
    
    prompt = f"""Eres el asistente virtual de {nombre_asesor}, de la inmobiliaria ListoHogar (Ecuador).
Tu objetivo es ofrecer opciones del catálogo y LOGRAR AGENDAR UNA VISITA.
La fecha actual del sistema es: {fecha_hoy}. Usa esta fecha base para referencias relativas (ej. 'mañana').

DIRECTRICES DE OPERACIÓN:
1. Mantener un tono profesional, amable y orientado a conversión.
2. Restringir la oferta exclusivamente a los items presentes en el catálogo inyectado. NUNCA inventes propiedades.
3. Flujo esperado: Saludo -> Presentación de 1 o 2 propiedades relevantes (ocultando ID) -> CTA para agendar visita.
4. GESTIÓN DE CITAS: Para procesar una solicitud de visita, es obligatorio recopilar: ID de propiedad, fecha (YYYY-MM-DD) y hora (HH:MM). Una vez obtenidos, se debe invocar la función 'agendar_cita'. No confirmar agendamientos sin ejecutar la herramienta.

CATÁLOGO ACTIVO:
{catalogo_actual}
"""
    return prompt

@app.route('/webhook', methods=['POST'])
def webhook_backend():
    """
    Endpoint nativo que recibe payloads directamente del backend de Samir (AWS).
    Espera un JSON con: id_asesor, nombre_asesor, mensaje, y opcionalmente historial.
    """
    # 1. Blindaje de Seguridad
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {API_SECRET_TOKEN}":
        print("[ALERTA SEGURIDAD] Intento de acceso no autorizado al webhook.")
        return jsonify({"error": "No autorizado", "status": "fail"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "No se recibió payload JSON", "status": "fail"}), 400

    # 2. Extracción de datos del Contrato JSON
    id_asesor_actual = data.get('id_asesor')
    nombre_asesor_actual = data.get('nombre_asesor', 'Asesor ListoHogar')
    mensaje_cliente = data.get('mensaje')
    historial = data.get('historial', []) # El backend debe enviarlo como: [{"role": "user", "content": "..."}]

    # Validación de integridad de datos
    if not mensaje_cliente or not id_asesor_actual:
        print("[ERROR_PAYLOAD] Faltan datos obligatorios en la petición de Samir.")
        return jsonify({"error": "Parámetros obligatorios faltantes: id_asesor, mensaje", "status": "fail"}), 400

    print(f"\n[INFERENCIA IA] Solicitud entrante para Asesor ID: {id_asesor_actual} | Payload: {mensaje_cliente}")
    
    try:
        # 3. Construcción del contexto para el LLM
        mensajes_api = [{"role": "system", "content": obtener_system_prompt(nombre_asesor_actual, id_asesor_actual)}]
        
        if historial:
            mensajes_api.extend(historial)
            
        mensajes_api.append({"role": "user", "content": mensaje_cliente})

        herramientas = [
            {
                "type": "function",
                "function": {
                    "name": "agendar_cita",
                    "description": "Agenda una visita a la propiedad en el sistema de la inmobiliaria.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id_propiedad": {"type": "integer", "description": "ID numérico de la propiedad"},
                            "fecha_cita": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"},
                            "hora_cita": {"type": "string", "description": "Hora en formato HH:MM"}
                        },
                        "required": ["id_propiedad", "fecha_cita", "hora_cita"]
                    }
                }
            }
        ]

        # 4. Ejecución de Inferencia
        respuesta_ia = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=mensajes_api,
            tools=herramientas,
            tool_choice="auto",
            temperature=0.3
        )
        
        mensaje_respuesta = respuesta_ia.choices[0].message
        
        # 5. Evaluación de Ejecución de Código (Function Calling)
        if mensaje_respuesta.tool_calls:
            for tool_call in mensaje_respuesta.tool_calls:
                if tool_call.function.name == "agendar_cita":
                    argumentos = json.loads(tool_call.function.arguments)
                    id_prop = argumentos.get("id_propiedad")
                    fecha = argumentos.get("fecha_cita")
                    hora = argumentos.get("hora_cita")
                    
                    print(f"[SYS_ACTION] Ejecutando agendar_cita_backend -> Asesor: {id_asesor_actual} | Propiedad: {id_prop} | Fecha: {fecha}")
                    
                    exito, mensaje_backend = api_listohogar.agendar_cita_backend(id_prop, fecha, hora, id_asesor=id_asesor_actual)
                    
                    if exito:
                        texto_final = f"¡Excelente! Tu visita ha sido agendada con éxito para el {fecha} a las {hora}. {nombre_asesor_actual} o un miembro de nuestro equipo te contactará pronto."
                    else:
                        texto_final = f"Uy, hubo un pequeño problema técnico al registrar la cita: {mensaje_backend}. Por favor, aguarda un momento y te atenderemos manualmente."
                    
                    print(f"[OUTPUT_GENERADO]: Cita Procesada.")
                    # Devolvemos el JSON al servidor de Samir
                    return jsonify({"respuesta": texto_final, "status": "success", "accion": "cita_agendada"}), 200

        # 6. Procesamiento de respuesta conversacional estándar
        texto_final = mensaje_respuesta.content
        if texto_final:
            print(f"[OUTPUT_GENERADO]: Respuesta Plana.")
            return jsonify({"respuesta": texto_final, "status": "success", "accion": "mensaje"}), 200
        
    except Exception as e:
        print(f"[CRITICAL_ERROR] Fallo en la ejecución del pipeline: {e}")
        return jsonify({"error": str(e), "status": "fail"}), 500
        
    return jsonify({"error": "No se generó respuesta", "status": "fail"}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "Microservicio IA ListoHogar: Operativo 🚀", 200

if __name__ == '__main__':
    print("[INFO] Inicializando Microservicio Flask en puerto 5000...")
    app.run(host='0.0.0.0', port=5000)