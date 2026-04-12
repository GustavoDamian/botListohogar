import os
import json
import requests
from datetime import datetime
import pytz
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import api_listohogar

# 1. Cargamos las variables de entorno
load_dotenv()

app = Flask(__name__)

# 2. Credenciales Seguras
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHATWOOT_API_URL = "https://app.chatwoot.com/api/v1"
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# ⚙️ PANEL DE CONTROL: MAPEO MULTI-ASESOR
# ==========================================
# Aquí relacionamos el ID del Inbox de Chatwoot con el Asesor de la API de Samir
# Cuando Gustavo conecte las cuentas, actualizaremos los IDs de la izquierda.
MAPEO_INBOX_ASESOR = {
    # inbox_id_chatwoot : {"id_samir": ID_BaseDatos, "nombre": "Nombre Asesor"}
    10: {"id_samir": 1, "nombre": "Daniela Cevalloz"},  # Ejemplo: Facebook Daniela
    11: {"id_samir": 2, "nombre": "Julio"},             # Ejemplo: Instagram Julio
    # Si entra por un inbox no registrado, usamos este por defecto:
    "default": {"id_samir": 1, "nombre": "ListoHogar (Central)"} 
}
# ==========================================

def obtener_hora_ecuador():
    """Garantiza que la fecha sea siempre la de Ecuador, sin importar el servidor de Render"""
    zona_ec = pytz.timezone('America/Guayaquil')
    return datetime.now(zona_ec).strftime("%Y-%m-%d")

def obtener_historial_chatwoot(conversation_id):
    """Obtiene los últimos mensajes de la conversación para dar contexto a la IA"""
    if not CHATWOOT_ACCOUNT_ID or not CHATWOOT_API_TOKEN:
        return []

    url = f"{CHATWOOT_API_URL}/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        mensajes_crudos = response.json().get("payload", [])
        
        # Ordenamos del más viejo al más nuevo y tomamos los últimos 6
        mensajes_crudos = sorted(mensajes_crudos, key=lambda x: x['created_at'])[-6:]
        
        historial = []
        for m in mensajes_crudos:
            # message_type: 0 (incoming/cliente), 1 (outgoing/bot o agente)
            if m.get("message_type") in [0, 1]:
                role = "user" if m.get("message_type") == 0 else "assistant"
                content = m.get("content")
                if content:
                    historial.append({"role": role, "content": content})
        return historial
    except Exception as e:
        print(f"[ERROR HISTORIAL] No se pudo obtener contexto: {e}")
        return []

def obtener_system_prompt(nombre_asesor):
    """Genera el prompt dinámico según el asesor que reciba el mensaje"""
    catalogo_actual = api_listohogar.obtener_catalogo_para_ia()
    fecha_hoy = obtener_hora_ecuador()
    
    prompt = f"""Eres el asistente virtual de {nombre_asesor}, de la inmobiliaria ListoHogar (Ecuador).
Tu objetivo es ofrecer opciones del catálogo y LOGRAR AGENDAR UNA VISITA.
La fecha de hoy es: {fecha_hoy}. Usa esto como referencia si el cliente dice "mañana" o fechas relativas.

REGLAS ESTRICTAS:
1. Tono amable, corto y persuasivo (optimizado para WhatsApp y Messenger).
2. NUNCA inventes propiedades. Usa solo el catálogo abajo.
3. Embudo: Saluda -> Ofrece 1 o 2 opciones con su ID oculto -> Pide agendar visita.
4. CUANDO EL CLIENTE QUIERA AGENDAR: Averigua para qué propiedad, qué fecha (YYYY-MM-DD) y qué hora (HH:MM). Una vez que tengas esos 3 datos claros, DEBES ejecutar la herramienta 'agendar_cita'. No intentes agendar confirmando solo con texto.

CATÁLOGO ACTUALIZADO:
{catalogo_actual}
"""
    return prompt

def enviar_mensaje_chatwoot(conversation_id, mensaje_texto):
    """Envía la respuesta al cliente vía Chatwoot"""
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
        print(f"[ERROR CHATWOOT] Falla al enviar: {e}")

@app.route('/webhook', methods=['POST'])
def webhook_chatwoot():
    data = request.json
    
    # 1. Filtro estricto: Solo respondemos a mensajes nuevos de clientes
    if data.get('event') == 'message_created' and data.get('message_type') == 'incoming':
        
        # Extraemos la data vital
        mensaje_cliente = data.get('content')
        conversation_id = data.get('conversation', {}).get('id')
        inbox_id = data.get('inbox', {}).get('id')
        
        # Verificamos si la conversación está asignada a un agente humano y pausamos el bot
        estado_conversacion = data.get('conversation', {}).get('status')
        if estado_conversacion != 'open':
             print(f"[INFO] Conversación {conversation_id} no está 'open'. El bot se silencia.")
             return jsonify({"status": "ignorado_por_estado"}), 200

        print(f"\n[CLIENTE] (Conv {conversation_id} | Inbox {inbox_id}): {mensaje_cliente}")
        
        # 2. LÓGICA MULTI-ASESOR: Buscamos quién es el dueño de este Inbox
        asesor_data = MAPEO_INBOX_ASESOR.get(inbox_id, MAPEO_INBOX_ASESOR["default"])
        nombre_asesor_actual = asesor_data["nombre"]
        id_samir_actual = asesor_data["id_samir"]
        
        try:
            # 3. Armamos el cerebro de la IA
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

            # 4. Petición a OpenAI
            respuesta_ia = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=mensajes_api,
                tools=herramientas,
                tool_choice="auto",
                temperature=0.3
            )
            
            mensaje_respuesta = respuesta_ia.choices[0].message
            
            # 5. Si la IA decide agendar (Function Calling)
            if mensaje_respuesta.tool_calls:
                for tool_call in mensaje_respuesta.tool_calls:
                    if tool_call.function.name == "agendar_cita":
                        argumentos = json.loads(tool_call.function.arguments)
                        id_prop = argumentos.get("id_propiedad")
                        fecha = argumentos.get("fecha_cita")
                        hora = argumentos.get("hora_cita")
                        
                        print(f"[*] Agendando para Asesor ID: {id_samir_actual} ({nombre_asesor_actual})")
                        print(f"[*] Propiedad: {id_prop} | Fecha: {fecha} | Hora: {hora}")
                        
                        # Pasamos el ID dinámico a la función de tu api_listohogar
                        exito, mensaje_backend = api_listohogar.agendar_cita_backend(id_prop, fecha, hora, id_asesor=id_samir_actual)
                        
                        if exito:
                            texto_final = f"¡Excelente! Tu visita ha sido agendada con éxito para el {fecha} a las {hora}. {nombre_asesor_actual} o un miembro de nuestro equipo te contactará pronto."
                        else:
                            texto_final = f"Uy, hubo un pequeño problema técnico al registrar la cita: {mensaje_backend}. Por favor, aguarda y te atenderemos manualmente."
                        
                        print(f"[IA {nombre_asesor_actual}]: {texto_final}")
                        enviar_mensaje_chatwoot(conversation_id, texto_final)
                        return jsonify({"status": "procesado"}), 200

            # 6. Si es charla normal
            texto_final = mensaje_respuesta.content
            if texto_final:
                print(f"[IA {nombre_asesor_actual}]: {texto_final}")
                enviar_mensaje_chatwoot(conversation_id, texto_final)
            
        except Exception as e:
            print(f"[ERROR SISTEMA]: {e}")
            
    return jsonify({"status": "procesado"}), 200

@app.route('/', methods=['GET'])
def health_check():
    return "API Multi-Asesor de ListoHogar Activa 🚀", 200

if __name__ == '__main__':
    print("Levantando servidor Flask End-to-End en puerto 5000...")
    app.run(host='0.0.0.0', port=5000)