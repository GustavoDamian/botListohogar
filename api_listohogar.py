import os
import json
import requests
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# URL base de Producción (AWS API Gateway)
BASE_URL = "https://jown604d8j.execute-api.us-east-2.amazonaws.com/api"

# Traemos las credenciales desde el .env
USER_EMAIL = os.getenv("API_LISTOHOGAR_USER")
USER_PASS = os.getenv("API_LISTOHOGAR_PASS")

def obtener_token():
    """
    Se autentica en el endpoint PostLogin para obtener el Bearer Token.
    """
    url = f"{BASE_URL}/auth/login"
    
    payload = {
        "correo": USER_EMAIL,
        "contrasena": USER_PASS
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status() 
        datos = response.json()
        return datos.get("token")
    except Exception as e:
        print(f"[ERROR AUTH] Fallo al obtener el token: {e}")
        return None

def obtener_catalogo_para_ia(id_asesor=None):
    """
    Consulta las propiedades y las formatea en texto plano.
    """
    url = f"{BASE_URL}/propiedad/propiedades-recientes?page=0&size=10"
    
    if id_asesor:
        url += f"&idAsesor={id_asesor}"
        
    headers = {"Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        propiedades = response.json()
        
        catalogo_texto = "CATÁLOGO DE PROPIEDADES DISPONIBLES:\n"
        catalogo_texto += "-" * 40 + "\n"
        
        for prop in propiedades:
            id_prop = prop.get("idPropiedad")
            titulo = prop.get("titulo")
            precio = prop.get("precio")
            ciudad = prop.get("ciudad")
            habs = prop.get("numeroHabitaciones")
            banios = prop.get("numeroBanios")
            desc = prop.get("descripcion")
            
            catalogo_texto += f"ID: {id_prop} | {titulo}\n"
            catalogo_texto += f"Ubicación: {ciudad} | Precio: USD {precio}\n"
            catalogo_texto += f"Detalles: {habs} Habit., {banios} Baños.\n"
            catalogo_texto += f"Descripción: {desc}\n"
            catalogo_texto += "-" * 40 + "\n"
            
        return catalogo_texto

    except Exception as e:
        print(f"[ERROR API] No se pudo obtener el catálogo: {e}")
        return "El catálogo de propiedades no está disponible en este momento."

def limpiar_texto_extremo(texto):
    """
    Sanitiza el texto al extremo para evadir expresiones regulares estrictas en bases de datos.
    Convierte signos comunes a palabras, remueve acentos y elimina toda puntuación.
    Garantiza un resultado estrictamente compuesto por letras, números y espacios.
    """
    if not texto:
        return ""
    
    # Conversión semántica de caracteres conflictivos obligatorios
    texto = texto.replace("@", " arroba ").replace(".", " punto ")
    
    # Normalización manual de caracteres con acentos o diéresis
    reemplazos = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
        'ñ': 'n', 'Ñ': 'N'
    }
    for orig, dest in reemplazos.items():
        texto = texto.replace(orig, dest)
        
    # Filtrar preservando únicamente caracteres alfabéticos ASCII estándar, dígitos y espacios
    texto_filtrado = "".join(c for c in texto if (c.isalpha() and c.isascii()) or c.isdigit() or c.isspace())
    
    # Colapsar espacios múltiples en uno solo
    return " ".join(texto_filtrado.split())

def agendar_cita_backend(id_propiedad, fecha_cita, hora_cita, id_asesor, nombre, telefono, email):
    """
    Envía el POST a la API para registrar la visita confirmada con un blindaje absoluto de datos.
    """
    token = obtener_token()
    if not token:
        return False, "Falla interna de autorización."

    url = f"{BASE_URL}/cita"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    # 1. Filtro defensivo extremo en comentarios
    raw_comentarios = f"Lead de IA Nombre de cliente {nombre} Telefono de contacto {telefono} Email de contacto {email}"
    comentarios_sanos = limpiar_texto_extremo(raw_comentarios)
    
    # 2. Blindaje absoluto de Fecha y Hora contra duplicaciones del LLM o del Frontend
    fecha_str = str(fecha_cita).strip()
    hora_str = str(hora_cita).strip()
    
    # Aislamiento matemático estricto del YYYY-MM-DD
    if "T" in fecha_str:
        fecha_limpia = fecha_str.split("T")[0].strip()
    else:
        fecha_limpia = fecha_str
        
    if "T" in hora_str:
        hora_limpia = hora_str.split("T")[-1].strip()
    else:
        hora_limpia = hora_str

    # Forzamos formato HH:MM (5 caracteres) para la Regex del backend (^\\d{2}:\\d{2}$)
    if len(hora_limpia) > 5:
        hora_limpia = hora_limpia[:5]
        
    # Ensamblamos el formato ISO final perfecto esperado por Spring Boot
    fecha_cita_iso = f"{fecha_limpia}T{hora_limpia}:00"
    
    payload = {
        "idComprador": None,
        "idVendedor": None,
        "idAsesor": id_asesor,
        "estadoCita": 1,
        "idPropiedad": id_propiedad,
        "fechaCita": fecha_cita_iso, 
        "hora": hora_limpia,
        "idTipoCita": 1,
        "lugarReferencia": "Agendado via Motor IA ListoHogar",
        "duracionMinutos": 30,
        "latitud": 10,
        "longitud": 10,
        "confirmadoPorVendedor": False,
        "confirmadoPorComprador": False,
        "calificacion": 3,
        "comentariosAdicionales": comentarios_sanos
    }
    
    # LOG DE EVIDENCIA ARQUITECTÓNICA: Guardamos registro exacto de lo que Python despacha
    print(f"\n[DEBUG OUTBOUND] PAYLOAD ENVIADO EN EL BODY A AWS:")
    print(json.dumps(payload, indent=2))
    print("-" * 50)
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return True, "Cita agendada correctamente."
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR CITA] Status AWS: {e.response.status_code}")
        print(f"[DETALLE RECHAZO AWS]: {e.response.text}")
        return False, "Error al procesar la agenda."
    except Exception as e:
        print(f"[ERROR RED] Falló la conexión: {e}")
        return False, "Error interno de red."

def notificar_asesor_backend(propiedad_id, tipo_escalada, resumen_lead, mensaje_cliente, urgencia, id_asesor):
    """
    Simula la notificación de escalada al asesor humano.
    """
    print(f"[ESCALADA URGENTE] Asesor ID: {id_asesor} | Propiedad: {propiedad_id} | Tipo: {tipo_escalada}")
    print(f"Resumen Lead: {resumen_lead}")
    print(f"Último mensaje cliente: {mensaje_cliente}")
    return True, "Asesor notificado con éxito."

def guardar_lead_backend(propiedad_id, nombre_cliente, telefono_cliente, dias_recordatorio):
    """
    Simula el almacenamiento de un lead frío.
    """
    print(f"[LEAD FRÍO] Guardando seguimiento en {dias_recordatorio} días para {nombre_cliente} ({telefono_cliente}) en prop {propiedad_id}")
    return True, "Lead almacenado."

if __name__ == "__main__":
    print("Probando conexión con AWS y credenciales...")
    token = obtener_token()
    if token:
        print("✅ Autenticación exitosa. Token obtenido.")
    else:
        print("❌ Fallo en la autenticación.")