import os
import json
import requests
from datetime import datetime
import pytz
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import api_listohogar

# Carga de variables de entorno
load_dotenv()

app = Flask(__name__)

# Configuración de credenciales de API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHATWOOT_API_URL = "https://app.chatwoot.com/api/v1"
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------------------------------------------------
# MAPEO DE ENRUTAMIENTO OMNICANAL
# -------------------------------------------------------------------
# Relación estática entre el ID de la bandeja (Chatwoot) y la entidad Asesor (AWS)
MAPEO_INBOX_ASESOR = {
    10: {"id_samir": 1, "nombre": "Daniela Cevalloz"},  # FanPage Daniela
    11: {"id_samir": 2, "nombre": "Julio"},             # IG Julio
    "default": {"id_samir": 1, "nombre": "ListoHogar (Central)"} 
}
# -------------------------------------------------------------------

def obtener_hora_ecuador():
    """Ajuste de zona horaria para compensar el offset del servidor (UTC a ECT)."""
    zona_ec = pytz.timezone('America/Guayaquil')
    return datetime.now(zona_ec).strftime("%Y-%m-%d")

def obtener_historial_chatwoot(conversation_id):
    """Recupera el historial de la conversación para mantener el contexto del LLM."""
    if not CHATWOOT_ACCOUNT_ID or not CHATWOOT_API_TOKEN:
        return []

    url = f"{CHATWOOT_API_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        mensajes_crudos = response.json().get("payload", [])
        
        # Ordenar ascendente y mantener un buffer de 6 mensajes
        mensajes_crudos = sorted(mensajes_crudos, key=lambda x: x['created_at'])[-6:]
        
        historial = []
        for m in mensajes_crudos:
            if m.get("message_type") in [0, 1]:
                role = "user" if m.get("message_type") == 0 else "assistant"
                content = m.get("content")
                if content:
                    historial.append({"role": role, "content": content})
        return historial
    except Exception as e:
        print(f"[ERROR_HTTP] Fallo al recuperar historial: {e}")
        return []

def obtener_system_prompt(nombre_asesor):
    """Construye el system prompt inyectando el catálogo de propiedades y directrices."""
    catalogo_actual = api_listohogar.obtener_catalogo_para_ia()
    fecha_hoy = obtener_hora_ecuador()
    
    prompt = f"""Eres el asistente virtual de {nombre_asesor}, de la inmobiliaria ListoHogar (Ecuador).
Tu objetivo es ofrecer opciones del catálogo y LOGRAR AGENDAR UNA VISITA.
La fecha actual del sistema es: {fecha_hoy}. Usa esta fecha base para referencias relativas (ej. 'mañana').

DIRECTRICES DE OPERACIÓN:
1. Mantener un tono profesional, conciso y orientado a conversión (optimizado para mensajería instantánea).
2. Restringir la oferta exclusivamente a los items presentes en el catálogo inyectado.
3. Flujo esperado: Saludo -> Presentación de 1 o 2 propiedades relevantes (ocultando ID) -> CTA para agendar visita.
4. GESTIÓN DE CITAS: Para procesar una solicitud de visita, es obligatorio recopilar: ID de propiedad, fecha (YYYY-MM-DD) y hora (HH:MM). Una vez obtenidos, se debe invocar la función 'agendar_cita'. No confirmar agendamientos sin ejecutar la herramienta.

CATÁLOGO ACTIVO:
{catalogo_actual}
"""
    return prompt

def enviar_mensaje_chatwoot(conversation_id, mensaje_texto):
    """Ejecuta un POST request para despachar mensajes salientes mediante la API de Chatwoot."""
    url = f"{CHATWOOT_API_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "content": mensaje_texto,
        "message_type": "outgoing"
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
    except Exception as e:
        print(f"[ERROR_API] Falla en despacho de mensaje: {e}")

@app.route('/webhook', methods=['POST'])
def webhook_chatwoot():
    data = request.json
    
    # Validación de eventos: Procesar únicamente mensajes entrantes de usuarios
    if data.get('event') == 'message_created' and data.get('message_type') == 'incoming':
        
        mensaje_cliente = data.get('content')
        conversation_id = data.get('conversation', {}).get('id')
        inbox_id = data.get('inbox', {}).get('id')
        
        # Manejo de Handoff: Ignorar webhooks si la conversación no tiene estado 'open'
        estado_conversacion = data.get('conversation', {}).get('status')
        if estado_conversacion != 'open':
             print(f"[HANDOFF] Conversación {conversation_id} en estado '{estado_conversacion}'. Ejecución de script pausada.")
             return jsonify({"status": "ignorado_por_estado"}), 200

        print(f"\n[INCOMING_MSG] Conv: {conversation_id} | Inbox: {inbox_id} | Payload: {mensaje_cliente}")
        
        # Resolución dinámica del agente en base al inbox_id
        asesor_data = MAPEO_INBOX_ASESOR.get(inbox_id, MAPEO_INBOX_ASESOR["default"])
        nombre_asesor_actual = asesor_data["nombre"]
        id_samir_actual = asesor_data["id_samir"]
        
        try:
            # Construcción del payload para inferencia
            mensajes_api = [{"role": "system", "content": obtener_system_prompt(nombre_asesor_actual)}]
            historial = obtener_historial_chatwoot(conversation_id)
            
            if historial:
                mensajes_api.extend(historial)
            else:
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
                                "id_propiedad": {"type": "integer", "description": "ID de la propiedad"},
                                "fecha_cita": {"type": "string", "description": "Fecha (YYYY-MM-DD)"},
                                "hora_cita": {"type": "string", "description": "Hora (HH:MM)"}
                            },
                            "required": ["id_propiedad", "fecha_cita", "hora_cita"]
                        }
                    }
                }
            ]

            # Ejecución de inferencia LLM
            respuesta_ia = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=mensajes_api,
                tools=herramientas,
                tool_choice="auto",
                temperature=0.3
            )
            
            mensaje_respuesta = respuesta_ia.choices[0].message
            
            # Evaluación de tool_calls para ejecución de funciones (Function Calling)
            if mensaje_respuesta.tool_calls:
                for tool_call in mensaje_respuesta.tool_calls:
                    if tool_call.function.name == "agendar_cita":
                        argumentos = json.loads(tool_call.function.arguments)
                        id_prop = argumentos.get("id_propiedad")
                        fecha = argumentos.get("fecha_cita")
                        hora = argumentos.get("hora_cita")
                        
                        print(f"[SYS_ACTION] Ejecutando agendar_cita_backend -> Asesor: {id_samir_actual} | Propiedad: {id_prop} | Fecha: {fecha}")
                        
                        exito, mensaje_backend = api_listohogar.agendar_cita_backend(id_prop, fecha, hora, id_asesor=id_samir_actual)
                        
                        if exito:
                            texto_final = f"¡Excelente! Tu visita ha sido agendada con éxito para el {fecha} a las {hora}. {nombre_asesor_actual} o un miembro de nuestro equipo te contactará pronto."
                        else:
                            texto_final = f"Uy, hubo un pequeño problema técnico al registrar la cita: {mensaje_backend}. Por favor, aguarda y te atenderemos manualmente."
                        
                        print(f"[OUTGOING_MSG_BOT - {nombre_asesor_actual}]: {texto_final}")
                        enviar_mensaje_chatwoot(conversation_id, texto_final)
                        return jsonify({"status": "procesado"}), 200

            # Procesamiento de respuesta estándar (texto plano)
            texto_final = mensaje_respuesta.content
            if texto_final:
                print(f"[OUTGOING_MSG_BOT - {nombre_asesor_actual}]: {texto_final}")
                enviar_mensaje_chatwoot(conversation_id, texto_final)
            
        except Exception as e:
            print(f"[CRITICAL_ERROR] Fallo en la ejecución del pipeline: {e}")
            
    return jsonify({"status": "procesado"}), 200

@app.route('/', methods=['GET'])
def health_check():
    return "Servicio de Orquestación ListoHogar Activo", 200

if __name__ == '__main__':
    print("[INFO] Inicializando servicio Flask en puerto 5000...")
    app.run(host='0.0.0.0', port=5000)