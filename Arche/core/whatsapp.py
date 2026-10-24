"""
whatsapp.py
-----------
Arché por WhatsApp, con la API oficial (WhatsApp Cloud API de Meta).

Cómo funciona:
  - Arché levanta un pequeño servidor web local (webhook). Meta le avisa ahí
    cuando le escribes al número de WhatsApp de Arché.
  - El mensaje entra por core/canales.py y lo procesa EL MISMO main.py de
    siempre, con todos sus comandos. Lo que Arché responde vuelve por WhatsApp.
  - Meta necesita una URL pública HTTPS para llegar a tu PC: si tienes
    "cloudflared" instalado, Arché lo lanza solo y te da la URL.

Seguridad (Arché controla tu PC, así que esto es lo importante):
  - Solo responde a los números que tú autorices; los demás se ignoran.
  - Si configuras el "App Secret", se verifica la firma de cada aviso de Meta.
  - Hay órdenes que NO se aceptan por WhatsApp (apagar, borrar, instalar,
    tocar el código de Arché, claves...): esas solo desde el PC.

Comandos (desde la consola):
  conectar whatsapp        guía para guardar token, número y tus datos
  iniciar whatsapp         enciende el canal
  detener whatsapp         lo apaga
  estado whatsapp          cómo está
  whatsapp permitir <n>    autoriza otro número (con código de país, sin +)
  whatsapp quitar <n>      le quita el permiso
"""

import atexit
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import canales
from core.rutas import DATABASE

ARCHIVO = os.path.join(DATABASE, "whatsapp.json")
VERSION_API = "v23.0"
PUERTO_POR_DEFECTO = 8765
MAX_CUERPO = 1_000_000
MAX_TEXTO = 3500            # WhatsApp admite ~4096; se parte en trozos más cortos

# Órdenes que no se aceptan por WhatsApp (se comparan sobre el texto sin tildes y en minúsculas).
PROHIBIDOS = re.compile(
    r"\b(apaga|apagar|reinicia|reiniciar|suspende|suspender|hiberna|cierra sesion|"
    r"borra|borrar|elimina|eliminar|formatea|vacia|vaciar|limpieza|limpia|"
    r"instala|instalar|desinstala|desinstalar|"
    r"cambia esto|modifica|modificar|cambia el codigo|edita el codigo|aprueba|aprobar|aplica el cambio|"
    r"revierte|revertir|rollback|"
    r"clave|token|contrasena|password|api key|"
    r"whatsapp)\b"
)

_servidor = None
_hilo = None
_tunel = None
_url_publica = None
_vistos = []                # ids de mensajes ya procesados (Meta reintenta)


def _sin_tildes(texto):
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        texto = texto.replace(a, b)
    return texto


def _solo_digitos(numero):
    return re.sub(r"\D", "", str(numero or ""))


# ------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------

# Campos que son secretos: en el disco van cifrados (core/seguridad/cifrado.py).
CAMPOS_SECRETOS = ("token", "verify_token", "app_secret")


def _cargar():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, dict):
            return {}
    except Exception:
        return {}
    from core.seguridad import cifrado
    habia_plano = False
    for campo in CAMPOS_SECRETOS:
        valor = datos.get(campo)
        if isinstance(valor, str) and valor:
            if cifrado.esta_cifrado(valor):
                try:
                    datos[campo] = cifrado.descifrar(valor)
                except Exception as e:
                    print(f"Arché: (seguridad) No pude abrir el {campo} de WhatsApp: {e}")
                    datos[campo] = ""
            else:
                habia_plano = True
    if habia_plano and cifrado.metodo() != "ninguno":
        try:
            _guardar(datos)          # migracion: el token viejo en texto plano queda cifrado
        except Exception:
            pass
    return datos


def _guardar(datos):
    from core.seguridad import cifrado
    en_disco = dict(datos)
    for campo in CAMPOS_SECRETOS:
        if isinstance(en_disco.get(campo), str) and en_disco[campo]:
            en_disco[campo] = cifrado.cifrar(en_disco[campo])
    tmp = ARCHIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(en_disco, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, ARCHIVO)


def configurada():
    c = _cargar()
    return bool(c.get("token") and c.get("phone_id") and c.get("permitidos"))


def activo():
    return _servidor is not None


# ------------------------------------------------------------------
# Seguridad y lectura de lo que manda Meta
# ------------------------------------------------------------------

def firma_valida(cuerpo, cabecera, secreto):
    """Verifica X-Hub-Signature-256. Sin secreto configurado no se exige (se avisa en 'estado')."""
    if not secreto:
        return True
    if not cabecera or not cabecera.startswith("sha256="):
        return False
    esperado = hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera.split("=", 1)[1])


def extraer_mensajes(payload):
    """De lo que manda Meta saca [{id, de, tipo, texto}] (un aviso puede traer varios)."""
    salida = []
    try:
        for entrada in payload.get("entry", []):
            for cambio in entrada.get("changes", []):
                for m in cambio.get("value", {}).get("messages", []) or []:
                    texto = ""
                    if m.get("type") == "text":
                        texto = (m.get("text") or {}).get("body", "")
                    elif m.get("type") == "button":
                        texto = (m.get("button") or {}).get("text", "")
                    salida.append({"id": m.get("id", ""), "de": _solo_digitos(m.get("from")),
                                   "tipo": m.get("type", ""), "texto": texto.strip()})
    except Exception:
        pass
    return salida


def es_prohibido(texto):
    return bool(PROHIBIDOS.search(_sin_tildes(texto.lower())))


# ------------------------------------------------------------------
# Enviar
# ------------------------------------------------------------------

def _trozos(texto, largo=MAX_TEXTO):
    texto = texto.strip()
    while len(texto) > largo:
        corte = texto.rfind("\n", 0, largo)
        if corte < largo // 2:
            corte = texto.rfind(" ", 0, largo)
        if corte < largo // 2:
            corte = largo
        yield texto[:corte].strip()
        texto = texto[corte:].strip()
    if texto:
        yield texto


def _post_graph(cfg, cuerpo):
    url = f"https://graph.facebook.com/{VERSION_API}/{cfg['phone_id']}/messages"
    pedido = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=20) as r:
        return r.status


def enviar_texto(numero, texto):
    """Manda un texto por WhatsApp. Devuelve True si Meta lo aceptó."""
    cfg = _cargar()
    if not (cfg.get("token") and cfg.get("phone_id")):
        return False
    ok = True
    for trozo in _trozos(texto):
        try:
            estado = _post_graph(cfg, {"messaging_product": "whatsapp", "to": _solo_digitos(numero),
                                       "type": "text", "text": {"body": trozo, "preview_url": False}})
            print(f"Arché: (WhatsApp: respuesta enviada a …{_solo_digitos(numero)[-4:]}, Meta respondió {estado})")
        except urllib.error.HTTPError as e:
            ok = False
            detalle = ""
            try:
                detalle = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                pass
            print(f"Arché: (WhatsApp rechazó el envío: {e.code} {detalle})".strip())
            break
        except Exception as e:
            ok = False
            print(f"Arché: (no pude enviar por WhatsApp: {e})")
            break
    return ok


# ------------------------------------------------------------------
# Mensajes entrantes
# ------------------------------------------------------------------

def procesar_entrante(msg, cfg=None):
    """Decide qué hacer con un mensaje. Devuelve una etiqueta (útil para probar)."""
    cfg = cfg or _cargar()
    permitidos = {_solo_digitos(n) for n in cfg.get("permitidos", [])}
    if msg["de"] not in permitidos:
        print(f"Arché: (WhatsApp: ignoré un mensaje de un número no autorizado, termina en …{msg['de'][-4:]})")
        return "ignorado"
    if msg["id"] and msg["id"] in _vistos:
        return "repetido"
    if msg["id"]:
        _vistos.append(msg["id"])
        del _vistos[:-200]
    if not msg["texto"]:
        enviar_texto(msg["de"], "Por ahora solo entiendo texto por aquí. Escríbeme lo que necesitas.")
        return "sin_texto"
    if _sin_tildes(msg["texto"].lower()).strip(" .!") in ("adios", "salir", "chao", "hasta luego"):
        enviar_texto(msg["de"], "Hasta luego. Aquí sigo cuando me necesites.")
        return "despedida"
    if es_prohibido(msg["texto"]):
        enviar_texto(msg["de"], "Eso, por seguridad, solo lo hago desde el PC.")
        return "prohibido"
    canales.poner("whatsapp", msg["de"], msg["texto"])
    return "encolado"


class _Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _responder(self, codigo, cuerpo=b"", tipo="text/plain"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path.rstrip("/") != "/webhook":
            return self._responder(404)
        q = urllib.parse.parse_qs(url.query)
        cfg = _cargar()
        if q.get("hub.mode", [""])[0] == "subscribe" and cfg.get("verify_token") \
                and hmac.compare_digest(q.get("hub.verify_token", [""])[0], cfg["verify_token"]):
            print("Arché: (WhatsApp: Meta verificó el webhook correctamente)")
            return self._responder(200, q.get("hub.challenge", [""])[0].encode("utf-8"))
        print("Arché: (WhatsApp: alguien intentó verificar el webhook con un token distinto)")
        return self._responder(403)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path.rstrip("/") != "/webhook":
            return self._responder(404)
        try:
            largo = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            largo = 0
        if largo <= 0 or largo > MAX_CUERPO:
            return self._responder(400)
        cuerpo = self.rfile.read(largo)
        cfg = _cargar()
        if not firma_valida(cuerpo, self.headers.get("X-Hub-Signature-256"), cfg.get("app_secret")):
            print("Arché: (WhatsApp: llegó un aviso con firma inválida; lo rechacé. Revisa el App Secret)")
            return self._responder(403)
        self._responder(200, b"ok")             # Meta reintenta si tardamos: se responde ya
        try:
            datos = json.loads(cuerpo.decode("utf-8"))
            mensajes = extraer_mensajes(datos)
            campos = [c.get("field") for e in datos.get("entry", []) for c in e.get("changes", [])]
            print(f"Arché: (WhatsApp: llegó un aviso de Meta, campo(s) {campos}, {len(mensajes)} mensaje(s))")
            for msg in mensajes:
                procesar_entrante(msg, cfg)
        except Exception as e:
            print(f"Arché: (WhatsApp: no pude leer un aviso: {e})")


# ------------------------------------------------------------------
# Servidor y túnel
# ------------------------------------------------------------------

def _iniciar_tunel(puerto):
    global _tunel
    exe = shutil.which("cloudflared")
    if not exe:
        return False
    try:
        _tunel = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{puerto}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except Exception:
        _tunel = None
        return False

    def _leer():
        global _url_publica
        for linea in _tunel.stderr:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", linea)
            if m:
                _url_publica = m.group(0)
                print(f"Arché: Túnel listo. En Meta (WhatsApp > Configuración > Webhook) la URL de devolución es: "
                      f"{_url_publica}/webhook")
                print("Arché: (esa URL cambia cada vez que enciendes el túnel; si cambia, actualízala en Meta.)")
                return
    threading.Thread(target=_leer, name="tunel-whatsapp", daemon=True).start()
    return True


def iniciar(silencioso=False):
    global _servidor, _hilo
    if _servidor is not None:
        if not silencioso:
            print("Arché: WhatsApp ya está encendido.")
        return True
    if not configurada():
        if not silencioso:
            print("Arché: Primero hay que configurarlo. Di 'conectar whatsapp'.")
        return False
    cfg = _cargar()
    puerto = int(cfg.get("puerto", PUERTO_POR_DEFECTO))
    try:
        _servidor = ThreadingHTTPServer(("127.0.0.1", puerto), _Manejador)
    except OSError as e:
        _servidor = None
        print(f"Arché: No pude abrir el puerto {puerto} para WhatsApp ({e}).")
        return False
    _hilo = threading.Thread(target=_servidor.serve_forever, name="webhook-whatsapp", daemon=True)
    _hilo.start()
    canales.registrar_canal("whatsapp", enviar_texto)
    atexit.register(detener, True)
    hay_tunel = _iniciar_tunel(puerto)
    if not silencioso:
        print(f"Arché: WhatsApp encendido (servidor local en el puerto {puerto}).")
        if not hay_tunel:
            print("Arché: No encontré 'cloudflared', así que Meta no puede llegar a tu PC todavía. "
                  "Instálalo (winget install --id Cloudflare.cloudflared) o usa otro túnel (ngrok) hacia "
                  f"http://127.0.0.1:{puerto} y pon esa URL + /webhook en Meta.")
    return True


def detener(silencioso=False):
    global _servidor, _tunel, _url_publica
    if _servidor is None and _tunel is None:
        if not silencioso:
            print("Arché: WhatsApp ya estaba apagado.")
        return
    if _servidor is not None:
        try:
            _servidor.shutdown()
            _servidor.server_close()
        except Exception:
            pass
        _servidor = None
    if _tunel is not None:
        try:
            _tunel.terminate()
        except Exception:
            pass
        _tunel = None
    _url_publica = None
    if not silencioso:
        print("Arché: WhatsApp apagado.")


def arrancar_si_corresponde():
    """Al abrir Arché: si WhatsApp está configurado con arranque automático, lo enciende."""
    cfg = _cargar()
    if cfg.get("auto_inicio") and configurada():
        iniciar(silencioso=True)


def estado_texto():
    cfg = _cargar()
    if not cfg:
        return "WhatsApp: sin configurar. Di 'conectar whatsapp'."
    lineas = [f"WhatsApp: {'encendido' if activo() else 'apagado'}"
              f"{' (arranque automático)' if cfg.get('auto_inicio') else ''}"]
    lineas.append(f"Números autorizados: {len(cfg.get('permitidos', []))}")
    lineas.append("Firma de Meta verificada: " + ("sí" if cfg.get("app_secret") else
                                                  "NO (añade el App Secret en 'conectar whatsapp' para más seguridad)"))
    if _url_publica:
        lineas.append(f"URL del webhook: {_url_publica}/webhook")
    elif activo():
        lineas.append("Sin túnel público (falta cloudflared o URL propia).")
    return "\n".join(lineas)


# ------------------------------------------------------------------
# Configuración guiada (solo desde la consola del PC)
# ------------------------------------------------------------------

GUIA = (
    "Para conectar WhatsApp necesitas una app de Meta (gratis):\n"
    "  1. developers.facebook.com > Crear app (tipo Empresa) > añadir el producto WhatsApp.\n"
    "  2. En WhatsApp > Configuración de la API: copia el 'ID del número de teléfono' y el token.\n"
    "     (el token de prueba dura 24 horas; para uno permanente crea un 'usuario del sistema' en\n"
    "     business.facebook.com y genera un token con permiso whatsapp_business_messaging)\n"
    "  3. Agrega TU número como destinatario de prueba (Meta te manda un código).\n"
    "  4. En Configuración de la app > Básica: copia el 'App Secret' (opcional pero recomendado).\n"
    "  5. Más tarde, en WhatsApp > Configuración > Webhook, pegarás la URL que te dé 'iniciar whatsapp'\n"
    "     y el token de verificación que te muestro ahora, y te suscribes al campo 'messages'."
)


def configurar():
    if canales.canal_actual() != "consola":
        print("Arché: La configuración solo se hace desde el PC.")
        return
    print("Arché: " + GUIA)
    cfg = _cargar()

    def pedir(texto, actual="", secreto=False):
        sufijo = " (Enter para dejar el actual)" if actual else ""
        valor = input(f"Arché: {texto}{sufijo}\nTú: ").strip()
        return valor or actual

    cfg["token"] = pedir("Pega el token de acceso de WhatsApp:", cfg.get("token", ""), secreto=True)
    cfg["phone_id"] = _solo_digitos(pedir("¿Cuál es el 'ID del número de teléfono'?", cfg.get("phone_id", "")))
    mio = _solo_digitos(pedir("¿Cuál es TU número de WhatsApp, con código de país y sin '+'? (ej. 573001234567)",
                              (cfg.get("permitidos") or [""])[0]))
    if mio:
        cfg["permitidos"] = [mio] + [n for n in cfg.get("permitidos", []) if n != mio]
    cfg["app_secret"] = pedir("App Secret de Meta (Enter para omitir):", cfg.get("app_secret", ""), secreto=True)
    if not cfg.get("verify_token"):
        cfg["verify_token"] = secrets.token_urlsafe(12)
    cfg.setdefault("puerto", PUERTO_POR_DEFECTO)
    auto = input("Arché: ¿Lo enciendo solo cada vez que abras Arché? [s/n]\nTú: ").strip().lower()
    cfg["auto_inicio"] = auto in ("s", "si", "sí", "y", "yes")
    _guardar(cfg)
    print("Arché: Guardado. Token de verificación para Meta (cópialo en la pantalla del Webhook): "
          f"{cfg['verify_token']}")
    print("Arché: Ahora di 'iniciar whatsapp'.")


def _permitir(numero, agregar):
    if canales.canal_actual() != "consola":
        print("Arché: Eso solo se cambia desde el PC.")
        return
    n = _solo_digitos(numero)
    cfg = _cargar()
    lista = [x for x in cfg.get("permitidos", []) if x != n]
    if agregar and n:
        lista.append(n)
    cfg["permitidos"] = lista
    _guardar(cfg)
    print(f"Arché: Números autorizados: {len(lista)}.")


def _graph(cfg, ruta, metodo="GET"):
    url = f"https://graph.facebook.com/{VERSION_API}/{ruta}"
    pedido = urllib.request.Request(url, method=metodo, headers={"Authorization": f"Bearer {cfg['token']}"},
                                    data=b"" if metodo == "POST" else None)
    with urllib.request.urlopen(pedido, timeout=20) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _error_graph(e):
    try:
        return json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "") or str(e)
    except Exception:
        return str(e)


def suscribir_app(waba_id=None):
    """Suscribe tu cuenta de WhatsApp a tu app: sin esto Meta NO manda los mensajes reales al webhook."""
    if canales.canal_actual() != "consola":
        print("Arché: Eso solo se hace desde el PC.")
        return
    cfg = _cargar()
    if not cfg.get("token"):
        print("Arché: Primero di 'conectar whatsapp'.")
        return
    waba = _solo_digitos(waba_id or cfg.get("waba_id"))
    if not waba:
        waba = _solo_digitos(input("Arché: Pega el 'Identificador de la cuenta de mensajes' (está en Meta, "
                                   "Paso 1 > Pruébalo, junto al Phone Number ID):\nTú: "))
    if not waba:
        print("Arché: Cancelado.")
        return
    try:
        _graph(cfg, f"{waba}/subscribed_apps", "POST")
        cfg["waba_id"] = waba
        _guardar(cfg)
        apps = _graph(cfg, f"{waba}/subscribed_apps").get("data", [])
        nombres = [a.get("whatsapp_business_api_data", {}).get("name") or a.get("name") or "?" for a in apps]
        print(f"Arché: Listo, tu cuenta de WhatsApp quedó suscrita a tu app ({', '.join(nombres) or 'ok'}). "
              "Ahora escríbele 'hola' al número de prueba.")
    except urllib.error.HTTPError as e:
        print(f"Arché: Meta rechazó la suscripción ({e.code}): {_error_graph(e)}")
        print("Arché: Si dice que el token expiró, genera uno nuevo en Meta y di 'conectar whatsapp' otra vez.")
    except Exception as e:
        print(f"Arché: No pude suscribir: {e}")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_RE_ACCION = re.compile(
    r"^(iniciar|inicia|activar|activa|enciende|encender|prende|detener|deten|desactivar|desactiva|"
    r"conectar|conecta|configurar|configura|estado)\s+(?:el\s+|de\s+)?(?:canal\s+)?(?:de\s+)?whatsapp$")
_RE_SUSCRIBIR = re.compile(r"^(?:suscribir|suscribe|suscribirse|subscribe)\s+(?:a\s+|de\s+)?whatsapp(?:\s+(\d{8,}))?$|"
                           r"^whatsapp\s+(?:suscribir|suscribe)(?:\s+(\d{8,}))?$")
_RE_PERMISO = re.compile(r"^whatsapp\s+(permitir|autorizar|quitar)\s+(\+?[\d\s\-]{7,})$")


def manejar(comando):
    """True si el comando era de WhatsApp (y ya lo atendió)."""
    c = _sin_tildes(comando.lower()).strip()
    m = _RE_ACCION.match(c)
    if c == "whatsapp estado":
        print("Arché: " + estado_texto())
        return True
    sus = _RE_SUSCRIBIR.match(c)
    if sus:
        suscribir_app(sus.group(1) or sus.group(2))
        return True
    p = _RE_PERMISO.match(c)
    if p:
        _permitir(p.group(2), p.group(1) in ("permitir", "autorizar"))
        return True
    if not m:
        return False
    accion = m.group(1)
    if accion == "estado":
        print("Arché: " + estado_texto())
    elif accion in ("iniciar", "inicia", "activar", "activa", "enciende", "encender", "prende"):
        iniciar()
    elif accion in ("detener", "deten", "desactivar", "desactiva"):
        detener()
    else:
        configurar()
    return True