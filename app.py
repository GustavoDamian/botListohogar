import os
import json
from datetime import datetime
import pytz
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import api_listohogar
from flask_cors import CORS

# Carga de variables de entorno
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuración de credenciales seguras
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "listohogar_seguro_123") 

client = OpenAI(api_key=OPENAI_API_KEY)

def obtener_hora_ecuador():
    zona_ec = pytz.timezone('America/Guayaquil')
    return datetime.now(zona_ec).strftime("%Y-%m-%d")

def obtener_system_prompt(nombre_asesor, id_asesor, propiedad_id, historial_chat):
    """Construye el system prompt consultando el catálogo y formateando las directrices de la v2.0."""
    catalogo_actual = api_listohogar.obtener_catalogo_para_ia(id_asesor=id_asesor)
    fecha_hoy = obtener_hora_ecuador()
    
    # Procesar historial para inyectarlo en el prompt maestro
    if isinstance(historial_chat, list):
        historial_str = "\n".join([f"{msg.get('role', 'Usuario')}: {msg.get('content', '')}" for msg in historial_chat])
    else:
        historial_str = "Sin historial previo."
    
    prompt = f"""
Eres el asistente virtual de {nombre_asesor}, de la inmobiliaria ListoHogar (Ecuador).
Tu nombre visible es: Asistente ListoHogar AI Core.
La fecha actual del sistema es: {fecha_hoy}. Usa esta fecha base para referencias relativas.

OBJETIVO PRINCIPAL:
Resolver dudas del comprador sobre la propiedad activa y LOGRAR AGENDAR UNA VISITA con {nombre_asesor}.

ESTÁS ATENDIENDO LA PROPIEDAD ID: {propiedad_id}

DIRECTRICES DE OPERACIÓN:
1. Tono profesional, cálido y orientado a conversión. Máximo 5 líneas por respuesta. Emojis con moderación.
2. NUNCA inventes propiedades ni precios. Usa solo el catálogo inyectado. Si el precio no es visible en el catálogo, no lo menciones.
3. Flujo: Saludo -> Calificación (financiamiento + urgencia) -> Información -> CTA visita -> Escalar si aplica.
4. GESTIÓN DE CITAS: Antes de invocar agendar_cita, obtén OBLIGATORIAMENTE: nombre, teléfono, fecha (YYYY-MM-DD) y hora (HH:MM). NUNCA agendes sin nombre y teléfono.
5. ESCALADA: Si el cliente pregunta precio, negocia, menciona defectos, expresa miedo o hace consultas legales -> transfiere inmediatamente a {nombre_asesor} via notificar_asesor.
6. Antes de escalar, captura: tipo financiamiento + urgencia de compra + temperatura del lead (Caliente/Tibio/Frío).
7. SEÑALES DE ESCALADA AUTOMÁTICA: 'cuánto cuesta', 'negociar', 'descuento', 'contrato', 'firmar', 'desistir', 'miedo', 'no entiendo', 'grieta', 'humedad', 'confiable', 'estafa'.

PREGUNTAS QUE RESPONDES AUTÓNOMAMENTE:
Entrada BIESS, cuota mensual, diferencia BIESS/banco, aportaciones requeridas, gastos adicionales, tiempos del proceso, documentos a pedir, promesa de compraventa, alcabala, extranjeros, nueva vs. usada, predial, servicios de la zona, características de la propiedad, alícuota, checklist de visita, declaratoria propiedad horizontal.

PREGUNTAS QUE ESCALAN AL ASESOR (Usa la función notificar_asesor):
Precio exacto, negociación, confiabilidad del vendedor, revisión de contrato, defectos físicos, plusvalía como inversión, acompañamiento a visita, desistimiento, titularidad conyugal, señales emocionales de miedo o duda.

CATÁLOGO ACTIVO:
{catalogo_actual}

HISTORIAL DE CONVERSACIÓN RECIENTE:
{historial_str}
"""
    return prompt

@app.route('/webhook', methods=['POST'])
def webhook_backend():
    # 1. Blindaje de Seguridad
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {API_SECRET_TOKEN}":
        print("[ALERTA SEGURIDAD] Intento de acceso no autorizado al webhook.")
        return jsonify({"error": "No autorizado", "status": "fail"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "No se recibió payload JSON", "status": "fail"}), 400

    # 2. Extracción de datos
    id_asesor_actual = data.get('id_asesor')
    nombre_asesor_actual = data.get('nombre_asesor', 'Asesor ListoHogar')
    mensaje_cliente = data.get('mensaje')
    historial = data.get('historial', []) 
    propiedad_id = data.get('propiedad_id', 'No especificada') # Parámetro nuevo según la v2.0

    if not mensaje_cliente or not id_asesor_actual:
        return jsonify({"error": "Parámetros obligatorios faltantes: id_asesor, mensaje", "status": "fail"}), 400

    print(f"\n[INFERENCIA IA] Solicitud entrante para Asesor ID: {id_asesor_actual} | Payload: {mensaje_cliente}")
    
    try:
        # 3. Construcción del contexto para el LLM
        mensajes_api = [{"role": "system", "content": obtener_system_prompt(nombre_asesor_actual, id_asesor_actual, propiedad_id, historial)}]
        
        if historial:
            mensajes_api.extend(historial)
            
        mensajes_api.append({"role": "user", "content": mensaje_cliente})

        # Herramientas del Prompt Maestro v2.0
        herramientas = [
            {
                "type": "function",
                "function": {
                    "name": "agendar_cita",
                    "description": "Agenda una visita a la propiedad. OBLIGATORIO recopilar antes: nombre, teléfono, fecha y hora.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id_propiedad": {"type": "integer"},
                            "fecha_cita": {"type": "string", "description": "YYYY-MM-DD"},
                            "hora_cita": {"type": "string", "description": "HH:MM"},
                            "nombre_cliente": {"type": "string"},
                            "telefono_cliente": {"type": "string"}
                        },
                        "required": ["id_propiedad", "fecha_cita", "hora_cita", "nombre_cliente", "telefono_cliente"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "notificar_asesor",
                    "description": "Escala la conversación al asesor humano inmediatamente ante dudas legales, de precio o emocionales.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "propiedad_id": {"type": "integer"},
                            "tipo_escalada": {"type": "string", "description": "precio, negociacion, legal, emocional, otro"},
                            "resumen_lead": {"type": "string", "description": "Financiamiento + urgencia + temperatura"},
                            "mensaje_cliente": {"type": "string", "description": "Último mensaje del cliente"},
                            "urgencia": {"type": "string", "description": "alta, media, baja"}
                        },
                        "required": ["propiedad_id", "tipo_escalada", "resumen_lead", "mensaje_cliente", "urgencia"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "guardar_lead",
                    "description": "Guarda el interés de un cliente frío para recordatorio posterior.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "propiedad_id": {"type": "integer"},
                            "nombre_cliente": {"type": "string"},
                            "telefono_cliente": {"type": "string"},
                            "dias_recordatorio": {"type": "integer"}
                        },
                        "required": ["propiedad_id", "nombre_cliente", "telefono_cliente"]
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
        
        # 5. Evaluación de Ejecución de Código (Function Calling Múltiple)
        if mensaje_respuesta.tool_calls:
            for tool_call in mensaje_respuesta.tool_calls:
                nombre_funcion = tool_call.function.name
                argumentos = json.loads(tool_call.function.arguments)
                
                if nombre_funcion == "agendar_cita":
                    id_prop = argumentos.get("id_propiedad")
                    fecha = argumentos.get("fecha_cita")
                    hora = argumentos.get("hora_cita")
                    nombre = argumentos.get("nombre_cliente")
                    telefono = argumentos.get("telefono_cliente")
                    
                    print(f"[SYS_ACTION] Agendando cita -> Asesor: {id_asesor_actual} | Cliente: {nombre}")
                    exito, mensaje_backend = api_listohogar.agendar_cita_backend(id_prop, fecha, hora, id_asesor_actual, nombre, telefono)
                    
                    if exito:
                        texto_final = f"¡Excelente! Tu visita ha sido agendada con éxito para el {fecha} a las {hora}. {nombre_asesor_actual} te contactará pronto al {telefono}."
                    else:
                        texto_final = f"Hubo un problema técnico al registrar la cita: {mensaje_backend}. Te atenderemos manualmente."
                    
                    return jsonify({"respuesta": texto_final, "status": "success", "accion": "cita_agendada"}), 200

                elif nombre_funcion == "notificar_asesor":
                    print(f"[SYS_ACTION] Escalando a Humano -> Asesor: {id_asesor_actual}")
                    api_listohogar.notificar_asesor_backend(
                        argumentos.get("propiedad_id"), argumentos.get("tipo_escalada"), 
                        argumentos.get("resumen_lead"), argumentos.get("mensaje_cliente"), 
                        argumentos.get("urgencia"), id_asesor_actual
                    )
                    texto_final = f"Entiendo perfectamente tu consulta. Esa información te la puede confirmar directamente {nombre_asesor_actual}. En este momento le estoy enviando una notificación para que revise tu caso y te contacte a la brevedad."
                    return jsonify({"respuesta": texto_final, "status": "success", "accion": "escalada_humano"}), 200

                elif nombre_funcion == "guardar_lead":
                    print(f"[SYS_ACTION] Guardando Lead Frío -> Cliente: {argumentos.get('nombre_cliente')}")
                    api_listohogar.guardar_lead_backend(
                        argumentos.get("propiedad_id"), argumentos.get("nombre_cliente"), 
                        argumentos.get("telefono_cliente"), argumentos.get("dias_recordatorio", 3)
                    )
                    texto_final = "¡Genial que estés explorando! He guardado tu interés. Te recordaremos sobre esta propiedad más adelante. Si cambias de opinión y deseas visitarla, solo avísame."
                    return jsonify({"respuesta": texto_final, "status": "success", "accion": "lead_guardado"}), 200

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
    return "Microservicio IA ListoHogar: Operativo 🚀 v2.0", 200

if __name__ == '__main__':
    print("[INFO] Inicializando Microservicio Flask en puerto 5000...")
    app.run(host='0.0.0.0', port=5000)