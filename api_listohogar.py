import requests

# URL base de Producción
BASE_URL = "https://jown604d8j.execute-api.us-east-2.amazonaws.com/api"

def obtener_token():
    """
    Se autentica en el endpoint PostLogin para obtener el Bearer Token.
    """
    url = f"{BASE_URL}/auth/login"
    
    # IMPORTANTE: Usamos las keys exactas que vimos en el Postman de Samir
    payload = {
        "correo": "daniela.cevalloz@gmail.com",
        "contrasena": "Usuario123*"
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status() # Lanza error si el status no es 200 OK
        datos = response.json()
        return datos.get("token")
    except Exception as e:
        print(f"[ERROR AUTH] Fallo al obtener el token: {e}")
        return None

def obtener_catalogo_para_ia():
    """
    Consulta las propiedades y las formatea en texto plano 
    para el System Prompt de la IA.
    """
    url = f"{BASE_URL}/propiedad/propiedades-recientes?page=0&size=10"
    headers = {"Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        propiedades = response.json()
        
        catalogo_texto = "CATÁLOGO DE PROPIEDADES DISPONIBLES:\n"
        catalogo_texto += "-" * 40 + "\n"
        
        for prop in propiedades:
            # Extraemos los datos basándonos en el JSON que mandó Samir
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

def agendar_cita_backend(id_propiedad, fecha_cita, hora_cita, id_asesor=1):
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
    
    # Estructura de payload estricta basada en el JSON de Citas
    payload = {
        "idComprador": None,
        "idVendedor": None,
        "idAsesor": id_asesor,
        "estadoCita": 1,
        "idPropiedad": id_propiedad,
        "fechaCita": fecha_cita,
        "hora": hora_cita,
        "idTipoCita": 1,
        "lugarReferencia": "Agendado vía Bot de WhatsApp",
        "duracionMinutos": 30,
        "latitud": 10,
        "longitud": 10,
        "confirmadoPorVendedor": False,
        "confirmadoPorComprador": False,
        "calificacion": 3,
        "comentariosAdicionales": "Lead generado automáticamente por IA"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return True, "Cita agendada correctamente."
    except Exception as e:
        print(f"[ERROR CITA] Falló el registro: {e}")
        return False, "Error al procesar la agenda."

# --- TEST LOCAL DE INTEGRIDAD ---
if __name__ == "__main__":
    print("Probando conexión con AWS y credenciales...")
    
    # 1. Probamos el token
    token = obtener_token()
    if token:
        print("✅ Autenticación exitosa. Token obtenido.")
    else:
        print("❌ Fallo en la autenticación.")
        
    # 2. Probamos el catálogo
    print("\nObteniendo Catálogo...")
    catalogo = obtener_catalogo_para_ia()
    print(catalogo)