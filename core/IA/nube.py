"""
nube.py
-------
Ubicacion: Arche/core/IA/nube.py

Cliente de un modelo en la nube para que Arché piense con algo mucho mas
grande que lo que entra en tu PC. Ollama NO se va: queda de respaldo
(sin internet, sin clave, o si la nube falla, Arché sigue como siempre).

PROVEEDORES (se elige con "usa la nube de groq|gemini|anthropic"):
  * groq       -> gratis con limites (gpt-oss-120b: 30 pedidos/min, 1.000/dia
                  segun su documentacion). Es el predeterminado.
  * gemini     -> Google; tiene capa gratuita con limites que se ven en su panel.
  * anthropic  -> Claude; de pago, por uso.
  Groq y Gemini hablan el formato "OpenAI-compatible", asi que un solo cliente
  sirve para los dos. Los nombres de modelo cambian con el tiempo: se pueden
  ver con "que modelos hay en la nube" y cambiar con "usa el modelo <nombre>".

  * Las claves NUNCA van en el codigo: se leen de una variable de entorno
    (GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY) o de un archivo en
    Database/ (que esta en .gitignore, asi que no se sube a GitHub).
  * modo "auto"   -> nube si hay clave e internet, si no Ollama (default)
    modo "nube"   -> solo nube (si falla, avisa)
    modo "ollama" -> nunca usa la nube
  * Usa solo la libreria estandar (urllib): no hay que instalar nada.

Privacidad: en las cuentas gratuitas de algunos proveedores el contenido que
mandas puede usarse para mejorar sus productos (revisa sus terminos). Por eso
lo que Arché sabe de ti (su memoria) solo se manda a la nube si lo permites
("comparte mi memoria con la nube"); con Anthropic viene permitido.

Lo unico que toca la red esta en _post() y hay_internet() (en web.py),
para poder probar todo sin conexion.
"""

import json
import os
import re
import urllib.error
import urllib.request

from core.rutas import DATABASE

ARCHIVO_CONFIG = os.path.join(DATABASE, "nube.json")
ARCHIVO_CLAVE = os.path.join(DATABASE, "nube_clave.txt")   # el de siempre: la clave de Anthropic

VERSION_API_ANTHROPIC = "2023-06-01"
MODOS = ("auto", "nube", "ollama")
TIMEOUT_SEGUNDOS = 60
MARGEN_RAZONAMIENTO = 700   # los modelos que "piensan" gastan tokens antes de contestar

PROVEEDORES = {
    "groq": {
        "nombre": "Groq (gratis, con límites)", "formato": "openai",
        "url": "https://api.groq.com/openai/v1", "modelo": "openai/gpt-oss-120b",
        "env": "GROQ_API_KEY", "donde": "https://console.groq.com/keys",
        "gratis": True, "razona": True, "prefijo": "gsk_",
    },
    # Segundo modelo de Groq: misma clave, pero Groq cuenta el cupo gratis por modelo, asi que
    # sirve de respaldo sin crear nada nuevo. Solo entra cuando falla el principal.
    "groq_b": {
        "nombre": "Groq segundo modelo (gratis, con límites)", "formato": "openai",
        "url": "https://api.groq.com/openai/v1", "modelo": "openai/gpt-oss-20b",
        "env": "GROQ_API_KEY", "donde": "https://console.groq.com/keys",
        "gratis": True, "razona": True, "prefijo": "gsk_", "respaldo_de": "groq",
    },
    "gemini": {
        "nombre": "Google Gemini (capa gratuita, con límites)", "formato": "openai",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai", "modelo": "gemini-3.8-flash",
        "env": "GEMINI_API_KEY", "donde": "https://aistudio.google.com/apikey",
        "gratis": True, "razona": True, "prefijo": "AIza",
    },
    "anthropic": {
        "nombre": "Claude de Anthropic (de pago)", "formato": "anthropic",
        "url": "https://api.anthropic.com/v1/messages", "modelo": "claude-sonnet-5-5",
        "env": "ANTHROPIC_API_KEY", "donde": "https://console.anthropic.com",
        "gratis": False, "razona": False, "prefijo": "sk-ant-",
    },
}
PROVEEDOR_POR_DEFECTO = "groq"
URL_MODELOS_ANTHROPIC = "https://api.anthropic.com/v1/models"
# Algunos servicios (Groq esta detras de Cloudflare) rechazan el identificador por defecto de Python.
USER_AGENT = "Arche/1.0 (asistente personal)"


class ErrorNube(Exception):
    """La nube no pudo responder (clave mala, sin internet, limite, etc.)."""

    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.codigo = codigo


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


def proveedor():
    p = _leer_config().get("proveedor")
    return p if p in PROVEEDORES else PROVEEDOR_POR_DEFECTO


def fijar_proveedor(nuevo):
    if nuevo not in PROVEEDORES:
        raise ValueError(nuevo)
    datos = _leer_config()
    datos["proveedor"] = nuevo
    _guardar_config(datos)


def info(prov=None):
    return PROVEEDORES[prov or proveedor()]


def modelo(prov=None):
    prov = prov or proveedor()
    datos = _leer_config()
    elegido = (datos.get("modelos") or {}).get(prov)
    if not elegido and prov == "anthropic":
        elegido = datos.get("modelo")          # formato viejo: un solo modelo
    return elegido or PROVEEDORES[prov]["modelo"]


def fijar_modelo(nombre):
    datos = _leer_config()
    modelos = datos.get("modelos") if isinstance(datos.get("modelos"), dict) else {}
    modelos[proveedor()] = nombre.strip()
    datos["modelos"] = modelos
    _guardar_config(datos)


def envia_memoria():
    """True si a la nube se le puede contar lo que Arché sabe de ti."""
    valor = _leer_config().get("enviar_memoria")
    if valor is None:
        return not info()["gratis"]        # de pago: si; gratis: solo si lo permites
    return bool(valor)


def fijar_envia_memoria(valor):
    datos = _leer_config()
    datos["enviar_memoria"] = bool(valor)
    _guardar_config(datos)


# ------------------------------------------------------------------
# Claves
# ------------------------------------------------------------------

def _archivo_clave(prov):
    if prov == "anthropic":
        return ARCHIVO_CLAVE
    return os.path.join(DATABASE, f"nube_clave_{prov}.txt")


def clave(prov=None):
    """La clave de la API del proveedor, o '' si no hay."""
    prov = prov or proveedor()
    de_entorno = (os.environ.get(PROVEEDORES[prov]["env"]) or "").strip()
    if de_entorno:
        return de_entorno
    try:
        with open(_archivo_clave(prov), "r", encoding="utf-8") as f:
            propia = f.read().strip()
            if propia:
                return propia
    except OSError:
        pass
    madre = PROVEEDORES[prov].get("respaldo_de")      # el segundo modelo usa la clave de su proveedor
    return clave(madre) if madre else ""


def limpiar_clave(texto):
    """Quita lo que se cuela al pegar: espacios, saltos de linea, comillas, 'Bearer ' y caracteres invisibles."""
    t = str(texto or "").strip().strip("\"'`").strip()
    if t.lower().startswith("bearer "):
        t = t[7:]
    return "".join(c for c in t if c.isprintable() and not c.isspace()).strip("\"'`")


def describir_clave(texto, prov=None):
    """Frase para que veas QUE recibio Arché (sin mostrar la clave entera) y si el inicio es el esperado."""
    prov = prov or proveedor()
    k = limpiar_clave(texto)
    if not k:
        return "No recibí nada."
    frase = f"Recibí una clave de {len(k)} caracteres que empieza por «{k[:4]}»."
    prefijo = PROVEEDORES[prov].get("prefijo", "")
    if prefijo and not k.startswith(prefijo):
        frase += (f" Ojo: las claves de {prov} empiezan por «{prefijo}», así que quizá pegaste otra cosa "
                  f"o no se pegó completa.")
    return frase


def guardar_clave(texto, prov=None):
    prov = prov or proveedor()
    texto = limpiar_clave(texto)
    if not texto:
        raise ValueError("clave vacia")
    os.makedirs(DATABASE, exist_ok=True)
    ruta = _archivo_clave(prov)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass


def borrar_clave(prov=None):
    try:
        os.remove(_archivo_clave(prov or proveedor()))
        return True
    except OSError:
        return False


def configurada(prov=None):
    return bool(clave(prov))


def disponible():
    """True si AHORA se puede usar la nube: hay clave, el modo lo permite y hay internet."""
    if modo() == "ollama" or not configurada():
        return False
    from core import web
    return web.hay_internet()


# ------------------------------------------------------------------
# Llamada a la API (_post es lo unico que toca la red)
# ------------------------------------------------------------------

def _post(url, payload, encabezados, metodo="POST"):
    """Pide `url` y devuelve el JSON de la respuesta. Unico punto de red."""
    cuerpo = json.dumps(payload).encode("utf-8") if payload is not None else None
    cabeceras = {"content-type": "application/json", "user-agent": USER_AGENT}
    cabeceras.update(encabezados)
    peticion = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        texto = ""
        try:
            texto = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise ErrorNube(_explicar_http(e.code, texto), codigo=e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorNube(f"no pude conectarme a la nube ({e})")
    except ValueError:
        raise ErrorNube("la nube respondió algo que no entendí")


def _mensaje_de_error(cuerpo):
    """El motivo que da el servidor (o el principio de lo que respondio, si no es JSON)."""
    try:
        datos = json.loads(cuerpo)
        if isinstance(datos, list) and datos:
            datos = datos[0]
        error = datos.get("error", {})
        mensaje = error.get("message", "") if isinstance(error, dict) else str(error)
        if mensaje:
            return mensaje
    except Exception:
        pass
    plano = " ".join(re.sub(r"<[^>]+>", " ", str(cuerpo or "")).split())
    return plano[:140]


def _explicar_http(codigo, cuerpo=""):
    detalle = _mensaje_de_error(cuerpo)
    if codigo == 401:
        return ("la nube dice que la clave no es válida (401)" + (f": {detalle}" if detalle else "")
                + ". Revisa que sea la clave completa con 'conecta la nube'")
    if codigo == 403:
        return ("la nube rechazó el acceso (403)" + (f": {detalle}" if detalle else "")
                + ". Puede ser la clave, o que algo en tu red (VPN, antivirus, firewall) lo bloquee")
    if codigo == 404:
        return f"la nube no conoce el modelo '{modelo()}' (mira cuáles hay con 'que modelos hay en la nube')"
    if codigo == 429:
        if info()["gratis"]:
            return "llegué al límite gratuito de la nube (espera un rato o hasta mañana)"
        return "la nube me pide ir más despacio (límite de uso)"
    if codigo >= 500:
        return "la nube está con problemas ahora mismo"
    return f"error {codigo} de la nube" + (f": {detalle}" if detalle else "")


def _encabezados(prov, api_key):
    if PROVEEDORES[prov]["formato"] == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": VERSION_API_ANTHROPIC}
    return {"authorization": f"Bearer {api_key}"}


_RE_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.S | re.I)


def _responder_anthropic(mensajes, sistema, max_tokens, temperature, api_key, prov="anthropic"):
    payload = {"model": modelo(prov), "max_tokens": int(max_tokens),
               "temperature": temperature, "messages": mensajes}
    if sistema:
        payload["system"] = sistema
    datos = _post(info(prov)["url"], payload, _encabezados("anthropic", api_key))
    partes = [b.get("text", "") for b in (datos.get("content") or []) if b.get("type") == "text"]
    return "".join(partes)


def _responder_openai(mensajes, sistema, max_tokens, temperature, api_key, prov=None):
    prov = prov or proveedor()
    cfg = PROVEEDORES[prov]
    todos = ([{"role": "system", "content": sistema}] if sistema else []) + list(mensajes)
    payload = {"model": modelo(prov), "messages": todos, "temperature": temperature,
               "max_tokens": int(max_tokens) + (MARGEN_RAZONAMIENTO if cfg["razona"] else 0)}
    url = cfg["url"].rstrip("/") + "/chat/completions"
    if cfg["razona"]:
        # que piense poco: la charla debe ser rapida y no gastar el limite gratuito
        con_razonamiento = dict(payload, reasoning_effort="low")
        try:
            datos = _post(url, con_razonamiento, _encabezados(prov, api_key))
        except ErrorNube as e:
            if e.codigo != 400:
                raise
            datos = _post(url, payload, _encabezados(prov, api_key))   # ese modelo no lo acepta
    else:
        datos = _post(url, payload, _encabezados(prov, api_key))
    try:
        contenido = datos["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        contenido = None
    if isinstance(contenido, list):
        contenido = "".join(p.get("text", "") for p in contenido if isinstance(p, dict))
    return _RE_PENSAMIENTO.sub("", contenido or "")


_ultimo_uso = {"proveedor": None, "aviso": ""}


def ultimo_uso():
    """{'proveedor': quien contesto la ultima vez, 'aviso': por que se uso el de respaldo o ''}."""
    return dict(_ultimo_uso)


def respaldo_activo():
    """Si la nube principal falla, probar con la otra nube gratis que tenga clave (por defecto si)."""
    v = _leer_config().get("respaldo")
    return True if v is None else bool(v)


def fijar_respaldo(valor):
    datos = _leer_config()
    datos["respaldo"] = bool(valor)
    _guardar_config(datos)


def proveedores_de_respaldo(principal=None):
    """Otras nubes GRATIS con clave guardada, en orden. Anthropic (de pago) nunca entra sola de respaldo."""
    principal = principal or proveedor()
    return [p for p, c in PROVEEDORES.items() if p != principal and c["gratis"] and configurada(p)]


def _responder_con(prov, mensajes, sistema, max_tokens, temperature):
    api_key = clave(prov)
    if not api_key:
        raise ErrorNube("no hay clave de la nube (usa 'conecta la nube')")
    if PROVEEDORES[prov]["formato"] == "anthropic":
        texto = _responder_anthropic(mensajes, sistema, max_tokens, temperature, api_key, prov)
    else:
        texto = _responder_openai(mensajes, sistema, max_tokens, temperature, api_key, prov)
    texto = (texto or "").strip()
    if not texto:
        raise ErrorNube("la nube no devolvió texto")
    return texto


def responder(mensajes, sistema=None, max_tokens=500, temperature=0.7):
    """
    mensajes: [{"role": "user"|"assistant", "content": "..."}] (el ultimo, del usuario).
    Devuelve el texto. Lanza ErrorNube si no se pudo.
    Si la nube principal falla y hay otra nube gratis con clave, prueba con esa.
    """
    principal = proveedor()
    try:
        texto = _responder_con(principal, mensajes, sistema, max_tokens, temperature)
        _ultimo_uso.update(proveedor=principal, aviso="")
        return texto
    except ErrorNube as error:
        if not respaldo_activo():
            raise
        for otro in proveedores_de_respaldo(principal):
            try:
                texto = _responder_con(otro, mensajes, sistema, max_tokens, temperature)
            except ErrorNube:
                continue
            _ultimo_uso.update(proveedor=otro, aviso=f"{PROVEEDORES[principal]['nombre'].split(' (')[0]} falló ({error})")
            return texto
        raise


def modelos_disponibles():
    """Lista de ids de modelos que ofrece el proveedor actual. Lanza ErrorNube si no se pudo."""
    api_key = clave()
    if not api_key:
        raise ErrorNube("no hay clave de la nube (usa 'conecta la nube')")
    prov = proveedor()
    cfg = PROVEEDORES[prov]
    url = URL_MODELOS_ANTHROPIC if cfg["formato"] == "anthropic" else cfg["url"].rstrip("/") + "/models"
    datos = _post(url, None, _encabezados(prov, api_key), metodo="GET")
    ids = []
    for m in (datos.get("data") or datos.get("models") or []):
        if isinstance(m, dict) and m.get("id"):
            ids.append(str(m["id"]).replace("models/", "", 1))
    return sorted(set(ids))


def probar(prov=None):
    """(ok, mensaje): una llamada minima para confirmar clave y modelo de UN proveedor
    (sin respaldo: si la clave de este esta mala, que lo diga)."""
    try:
        _responder_con(prov or proveedor(), [{"role": "user", "content": "Responde solo: ok"}], None, 10, 0)
        return True, "La nube respondió bien."
    except ErrorNube as e:
        mensaje = str(e)
        if e.codigo == 404:
            try:
                ids = modelos_disponibles()
                if ids:
                    mensaje += ". Algunos que hay: " + ", ".join(ids[:8]) + ". Cambia con 'usa el modelo <nombre>'."
            except ErrorNube:
                pass
        return False, mensaje


def estado_texto():
    from core import web
    cfg = info()
    partes = [
        f"Modo: {modo()}.",
        f"Proveedor: {cfg['nombre']}.",
        f"Clave: {'guardada' if configurada() else 'no hay'}.",
        f"Modelo: {modelo()}.",
        f"Internet: {'sí' if web.hay_internet() else 'no'}.",
        f"Mi memoria {'se comparte' if envia_memoria() else 'NO se comparte'} con la nube.",
    ]
    otras = proveedores_de_respaldo()
    if otras and respaldo_activo():
        partes.append("Nube de respaldo: " + ", ".join(PROVEEDORES[o]["nombre"].split(" (")[0] for o in otras) + ".")
    elif not respaldo_activo():
        partes.append("La nube de respaldo está apagada.")
    if modo() == "ollama":
        partes.append("Estoy pensando solo con Ollama.")
    elif disponible():
        partes.append("Estoy pensando con la nube (Ollama queda de respaldo).")
    else:
        partes.append("Ahora mismo pienso con Ollama.")
    return " ".join(partes)