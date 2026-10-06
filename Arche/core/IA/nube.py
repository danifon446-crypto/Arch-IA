"""
nube.py
-------
Ubicacion: Arche/core/IA/nube.py

Cliente de un modelo en la nube para que Arché piense con algo mucho mas
grande que lo que entra en tu PC. Ollama NO se va: queda de respaldo
(sin internet, sin clave, o si la nube falla, Arché sigue como siempre).

  * La clave NUNCA va en el codigo: se lee de la variable de entorno
    ANTHROPIC_API_KEY o del archivo Database/nube_clave.txt. La carpeta
    Database/ esta en .gitignore, asi que no se sube a GitHub.
  * modo "auto"   -> nube si hay clave e internet, si no Ollama (default)
    modo "nube"   -> solo nube (si falla, avisa)
    modo "ollama" -> nunca usa la nube
  * Usa solo la libreria estandar (urllib): no hay que instalar nada.

Lo unico que toca la red esta en _post() y hay_internet() (en web.py),
para poder probar todo sin conexion.
"""

import json
import os
import urllib.error
import urllib.request

from core.rutas import DATABASE

ARCHIVO_CONFIG = os.path.join(DATABASE, "nube.json")
ARCHIVO_CLAVE = os.path.join(DATABASE, "nube_clave.txt")

URL_API = "https://api.anthropic.com/v1/messages"
VERSION_API = "2023-06-01"
MODELO_POR_DEFECTO = "claude-sonnet-5-5"
MODOS = ("auto", "nube", "ollama")
TIMEOUT_SEGUNDOS = 60


class ErrorNube(Exception):
    """La nube no pudo responder (clave mala, sin internet, limite, etc.)."""


# ------------------------------------------------------------------
# Configuracion
# ------------------------------------------------------------------

def _leer_config():
    try:
        with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
            datos = json.load(f)
            return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar_config(datos):
    os.makedirs(DATABASE, exist_ok=True)
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def modo():
    m = _leer_config().get("modo", "auto")
    return m if m in MODOS else "auto"


def fijar_modo(nuevo):
    if nuevo not in MODOS:
        raise ValueError(nuevo)
    datos = _leer_config()
    datos["modo"] = nuevo
    _guardar_config(datos)


def modelo():
    return _leer_config().get("modelo") or MODELO_POR_DEFECTO


def fijar_modelo(nombre):
    datos = _leer_config()
    datos["modelo"] = nombre.strip()
    _guardar_config(datos)


def clave():
    """La clave de la API, o '' si no hay."""
    de_entorno = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if de_entorno:
        return de_entorno
    try:
        with open(ARCHIVO_CLAVE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def guardar_clave(texto):
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("clave vacia")
    os.makedirs(DATABASE, exist_ok=True)
    with open(ARCHIVO_CLAVE, "w", encoding="utf-8") as f:
        f.write(texto)
    try:
        os.chmod(ARCHIVO_CLAVE, 0o600)
    except OSError:
        pass


def borrar_clave():
    try:
        os.remove(ARCHIVO_CLAVE)
        return True
    except OSError:
        return False


def configurada():
    return bool(clave())


def disponible():
    """True si AHORA se puede usar la nube: hay clave, el modo lo permite y hay internet."""
    if modo() == "ollama" or not configurada():
        return False
    from core import web
    return web.hay_internet()


# ------------------------------------------------------------------
# Llamada a la API
# ------------------------------------------------------------------

def _post(payload, api_key):
    """POST a la API. Devuelve el JSON de respuesta. Unico punto de red."""
    peticion = urllib.request.Request(
        URL_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": VERSION_API,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        cuerpo = ""
        try:
            cuerpo = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise ErrorNube(_explicar_http(e.code, cuerpo))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorNube(f"no pude conectarme a la nube ({e})")
    except ValueError:
        raise ErrorNube("la nube respondió algo que no entendí")


def _explicar_http(codigo, cuerpo=""):
    detalle = ""
    try:
        detalle = json.loads(cuerpo).get("error", {}).get("message", "")
    except Exception:
        pass
    if codigo in (401, 403):
        return "la clave de la nube no sirve (revísala con 'conecta la nube')"
    if codigo == 404:
        return f"la nube no conoce el modelo '{modelo()}' (cámbialo con 'usa el modelo <nombre>')"
    if codigo == 429:
        return "la nube me pide ir más despacio (límite de uso)"
    if codigo >= 500:
        return "la nube está con problemas ahora mismo"
    return f"error {codigo} de la nube" + (f": {detalle}" if detalle else "")


def responder(mensajes, sistema=None, max_tokens=500, temperature=0.7):
    """
    mensajes: [{"role": "user"|"assistant", "content": "..."}] (el ultimo, del usuario).
    Devuelve el texto. Lanza ErrorNube si no se pudo.
    """
    api_key = clave()
    if not api_key:
        raise ErrorNube("no hay clave de la nube (usa 'conecta la nube')")
    payload = {
        "model": modelo(),
        "max_tokens": int(max_tokens),
        "temperature": temperature,
        "messages": mensajes,
    }
    if sistema:
        payload["system"] = sistema
    datos = _post(payload, api_key)
    partes = [b.get("text", "") for b in (datos.get("content") or []) if b.get("type") == "text"]
    texto = "".join(partes).strip()
    if not texto:
        raise ErrorNube("la nube no devolvió texto")
    return texto


def probar():
    """(ok, mensaje): una llamada minima para confirmar clave y modelo."""
    try:
        responder([{"role": "user", "content": "Responde solo: ok"}], max_tokens=10, temperature=0)
        return True, "La nube respondió bien."
    except ErrorNube as e:
        return False, str(e)


def estado_texto():
    from core import web
    partes = [
        f"Modo: {modo()}.",
        f"Clave: {'guardada' if configurada() else 'no hay'}.",
        f"Modelo: {modelo()}.",
        f"Internet: {'sí' if web.hay_internet() else 'no'}.",
    ]
    if modo() == "ollama":
        partes.append("Estoy pensando solo con Ollama.")
    elif disponible():
        partes.append("Estoy pensando con la nube (Ollama queda de respaldo).")
    else:
        partes.append("Ahora mismo pienso con Ollama.")
    return " ".join(partes)