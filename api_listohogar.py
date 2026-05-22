import os
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

def agendar_cita_backend(id_propiedad, fecha_cita, hora_cita, id_asesor, nombre, telefono, email):
    """
    Envía el POST a la API para registrar la visita confirmada.
    """
    token = obtener_token()
    if not token:
        return False, "Falla interna de autorización."

    url = f"{BASE_URL}/cita"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    # IMPORTANTE: Texto plano limpio sin caracteres especiales como '|' o ':' para evitar bloqueos de AWS
    comentarios_limpios = f"Lead de IA. Nombre de cliente {nombre}. Telefono de contacto {telefono}. Email de contacto {email}."
    
    payload = {
        "idComprador": None,
        "idVendedor": None,
        "idAsesor": id_asesor,
        "estadoCita": 1,
        "idPropiedad": id_propiedad,
        "fechaCita": fecha_cita,
        "hora": hora_cita,
        "idTipoCita": 1,
        "lugarReferencia": "Agendado via Motor IA ListoHogar",
        "duracionMinutos": 30,
        "latitud": 10,
        "longitud": 10,
        "confirmadoPorVendedor": False,
        "confirmadoPorComprador": False,
        "calificacion": 3,
        "comentariosAdicionales": comentarios_limpios
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return True, "Cita agendada correctamente."
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR CITA] Status AWS: {e.response.status_code}")
        print(f"[DETALLE RECHAZO AWS]: {e.response.text}")
        return False, "Error al procesar la agenda."
    except Exception as e:
        print(f"[ERROR RED] Fallo la conexion: {e}")
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