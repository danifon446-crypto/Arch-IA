"""
remoto.py
---------
Ubicacion: Arche/core/interfaz/remoto.py

Control de Arché desde el celular: una paginita web que Arché sirve en tu red
wifi. Abres la direccion en el navegador del celular, pones el PIN y tienes
cuatro pestañas:

  INICIO     saludo, estado del PC, acciones rápidas (pantalla, abrir apps, mandar un
             enlace al PC, portapapeles, recordatorios, mandar archivo, bloquear) y
             tus archivos recientes.
  CHAT       le escribes a Arché y ves la conversación, con sugerencias.
  ARCHIVOS   ves las carpetas de tu PC (Escritorio, Documentos, Descargas, Imágenes,
             Videos, Música), buscas por nombre, ves lo que tocaste en los últimos
             días y DESCARGAS al celular el archivo que se te quedó. También puedes
             mandar archivos del celular al PC (quedan en Descargas/Desde el celular).
  PC         música y volumen, estado del equipo, programas abiertos, ver o apagar la
             pantalla, bloquear el PC, arrancar Arché con Windows y las funciones de
             Arché (lo que antes era CONTROLES).

Seguridad:
  - Apagado por defecto. Pide un PIN de 6 números (se ve en AJUSTES).
  - Tras 5 PIN malos bloquea esa dirección 1 minuto; si hay demasiados fallos en
    total (de cualquier dirección) bloquea a todos unos minutos.
  - Las órdenes delicadas (apagar el PC, teclear, borrar archivos, instalar,
    tocar el código de Arché, claves...) SOLO se aceptan desde el PC.
  - Los archivos solo se ven dentro de tus carpetas personales: no se puede
    salir de ellas (ni con "..", ni con accesos directos), no se ven archivos
    ocultos y desde el celular no se borra ni se sobrescribe nada.
  - Las descargas usan un permiso de un solo uso por archivo que vence en 5 min.
  - Solo responde a direcciones de tu red de casa o de Tailscale (ver abajo); cualquier
    otra recibe 403. No uses esto en una wifi pública.

Fuera de casa (otra red, datos móviles):
  Instala Tailscale (gratis) en el PC y en el celular y entra con la MISMA cuenta en los
  dos. Tailscale crea una red privada solo tuya: el celular llega al PC desde cualquier
  lugar, sin abrir nada a internet. Arché detecta la dirección de Tailscale (100.x.x.x)
  y te la muestra junto a la de la wifi. Dile a Arché «cómo entro desde afuera».

Variables de entorno (opcionales):
  ARCHE_CELULAR_PERMITE_TODO=1    acepta también las órdenes delicadas (no recomendado)
  ARCHE_CELULAR_SIN_ARCHIVOS=1    apaga la pestaña de archivos
  ARCHE_CELULAR_CARPETAS=C:\\ruta1;D:\\ruta2   carpetas extra que se pueden ver
"""

import hmac
import ipaddress
import json
import mimetypes
import os
import random
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import ajustes, datos, en_vivo, entrada

_servidor = None
_hilo = None
_candado = threading.Lock()

# ---- bloqueos por PIN malo ---------------------------------------------------------------------
MAX_FALLOS_IP = 5            # PIN malos seguidos desde una misma dirección
BLOQUEO_IP = 60              # segundos que queda bloqueada esa dirección
MAX_FALLOS_GLOBALES = 20     # PIN malos en total (todas las direcciones) ...
BLOQUEO_GLOBAL = 300         # ... dentro de esta ventana de segundos -> se bloquea a todos
_fallos = {}                 # ip -> [cuantos, hasta_cuando]
_fallos_globales = []        # momentos de cada PIN malo

# ---- archivos ---------------------------------------------------------------------------------
MAX_SUBIDA = 500 * 1024 * 1024        # 500 MB por archivo que mandas desde el celular
MAX_LISTADO = 400                     # elementos por carpeta
VIDA_PERMISO = 300                    # segundos que vale un permiso de descarga
CARPETA_SUBIDAS = "Desde el celular"  # dentro de Descargas
_permisos = {}                        # token -> {"ruta", "ip", "vence"}
_SALTAR = {"node_modules", "__pycache__", ".git", "appdata", "$recycle.bin", "venv", ".venv",
           "site-packages", "system volume information"}
_OCULTOS_WIN = {"desktop.ini", "thumbs.db", "ntuser.dat"}

# ---- órdenes que desde el celular NO se aceptan ------------------------------------------------
_EQUIPO = r"(?:pc|computador|computadora|compu|equipo|ordenador|maquina|laptop|portatil|sistema)"
ORDENES_SOLO_PC = [
    rf"\b(?:apaga|apagar|apagame|reinicia|reiniciar|reiniciame|suspende|suspender|hiberna|hibernar)\b.*\b{_EQUIPO}\b",
    r"\b(?:cierra|cerrar|termina)\s+(?:la\s+)?sesion\b",
    r"^(?:teclea|teclear|tipea|escribe\s+en\s+(?:el|la|esa|esta)|presiona|presionar|pulsa|pulsar|oprime|oprimir)\b",
    r"^cambia\s+esto\b", r"\b(?:deshaz|deshacer|revierte|revertir)\b.*\bcambio",
    r"\brevisate\b", r"\barreglate\b", r"\barregla\s+todo\b", r"\bautorepar", r"\bautocodific",
    r"\bmejora\b.*\bnivel\b", r"\b(?:modifica|edita|cambia)\s+tu\s+codigo\b",
    r"\b(?:clave|contrasena|password|api\s*key|apikey|token)\b", r"\bgsk_", r"\bsk-[a-z0-9]",
    r"\bcomparte\b.*\bmemoria\b", r"\b(?:borra|olvida)\s+(?:toda\s+)?tu\s+memoria\b",
    r"\b(?:borra|borrar|elimina|eliminar|suprime|vacia|vaciar)\b.*\b(?:archivo|archivos|carpeta|carpetas|"
    r"descargas|documentos|escritorio|disco|papelera|fotos|imagenes|videos|musica)\b",
    r"\bformatea", r"\b(?:instala|instalar|desinstala|desinstalar)\b",
    r"\b(?:ejecuta|ejecutar|corre|correr|lanza)\b.*\b(?:script|comando|programa|codigo|terminal|consola|"
    r"powershell|cmd|bat|exe|py)\b",
    r"\b(?:powershell|cmd\.exe|regedit)\b",
    r"\b(?:abre|abrir|inicia|lanza)\b.*\b(?:cmd|terminal|consola|simbolo del sistema|editor del registro)\b",
]
_RE_SOLO_PC = [re.compile(p) for p in ORDENES_SOLO_PC]


def _normalizar(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def es_orden_solo_pc(texto):
    """True si la orden es delicada y desde el celular no se acepta."""
    if os.environ.get("ARCHE_CELULAR_PERMITE_TODO") == "1":
        return False
    t = _normalizar(texto)
    return any(r.search(t) for r in _RE_SOLO_PC)


# =================================================================================================
# Archivos
# =================================================================================================

def archivos_activos():
    return os.environ.get("ARCHE_CELULAR_SIN_ARCHIVOS") != "1"


def _raices():
    """{id: (nombre bonito, ruta real)} de las carpetas que se pueden ver desde el celular."""
    casa = os.path.expanduser("~")
    nube = os.environ.get("OneDrive") or os.path.join(casa, "OneDrive")
    candidatas = [
        ("escritorio", "Escritorio", ["Desktop", "Escritorio"]),
        ("documentos", "Documentos", ["Documents", "Documentos"]),
        ("descargas", "Descargas", ["Downloads", "Descargas"]),
        ("imagenes", "Imágenes", ["Pictures", "Imágenes", "Imagenes"]),
        ("videos", "Videos", ["Videos", "Vídeos"]),
        ("musica", "Música", ["Music", "Música", "Musica"]),
    ]
    raices = {}
    for clave, nombre, nombres in candidatas:
        for base in (casa, nube):          # si Windows las movió a OneDrive, también sirven
            hallada = next((os.path.join(base, n) for n in nombres if os.path.isdir(os.path.join(base, n))), None)
            if hallada:
                raices[clave] = (nombre, os.path.realpath(hallada))
                break
    for i, ruta in enumerate(p for p in os.environ.get("ARCHE_CELULAR_CARPETAS", "").split(os.pathsep) if p.strip()):
        ruta = os.path.realpath(os.path.expanduser(ruta.strip()))
        if os.path.isdir(ruta):
            raices[f"extra{i + 1}"] = (os.path.basename(ruta) or ruta, ruta)
    return raices


def _oculto(nombre, ruta=None):
    if nombre.startswith(".") or nombre.startswith("~$") or nombre.lower() in _OCULTOS_WIN:
        return True
    if ruta is not None and sys.platform == "win32":
        try:
            atrib = os.stat(ruta, follow_symlinks=False).st_file_attributes
            return bool(atrib & 0x2 or atrib & 0x4)         # oculto o de sistema
        except (OSError, AttributeError):
            return False
    return False


def _dentro(ruta, raiz):
    try:
        return os.path.commonpath([os.path.normcase(ruta), os.path.normcase(raiz)]) == os.path.normcase(raiz)
    except ValueError:                                     # otra unidad de disco
        return False


def resolver(virtual):
    """'descargas/tareas/informe.pdf' -> ruta real, o None si no se puede (fuera de tus carpetas, oculto...)."""
    partes = [p for p in str(virtual or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if not partes or ".." in partes:
        return None
    raiz = _raices().get(partes[0])
    if not raiz:
        return None
    base = raiz[1]
    if any(_oculto(p) for p in partes[1:]) or any(":" in p for p in partes[1:]):
        return None
    ruta = os.path.realpath(os.path.join(base, *partes[1:]))
    if not _dentro(ruta, base) or not os.path.exists(ruta):
        return None
    return ruta


def _virtual(ruta):
    """Ruta real -> ruta virtual ('descargas/...'), o None."""
    for clave, (_, base) in _raices().items():
        if _dentro(ruta, base):
            rel = os.path.relpath(ruta, base)
            return clave if rel == "." else clave + "/" + rel.replace(os.sep, "/")
    return None


def _info(ruta, nombre):
    try:
        st = os.stat(ruta)
    except OSError:
        return None
    es_dir = os.path.isdir(ruta)
    return {"nombre": nombre, "dir": es_dir, "tam": 0 if es_dir else st.st_size, "fecha": int(st.st_mtime)}


def listar(virtual):
    """Contenido de una carpeta. '' = las carpetas raíz."""
    if not virtual:
        return {"ruta": "", "items": [{"nombre": n, "dir": True, "tam": 0, "fecha": 0, "ruta": k}
                                      for k, (n, _) in _raices().items()]}
    ruta = resolver(virtual)
    if not ruta or not os.path.isdir(ruta):
        return None
    base = _raices()[virtual.split("/")[0]][1]
    items = []
    try:
        with os.scandir(ruta) as it:
            for e in it:
                if _oculto(e.name, e.path):
                    continue
                real = os.path.realpath(e.path)
                if not _dentro(real, base):
                    continue                               # acceso directo que se sale de tus carpetas
                i = _info(real, e.name)
                if i:
                    i["ruta"] = virtual.rstrip("/") + "/" + e.name
                    items.append(i)
    except OSError:
        return None
    items.sort(key=lambda i: (not i["dir"], -i["fecha"] if not i["dir"] else 0, i["nombre"].lower()))
    return {"ruta": virtual, "items": items[:MAX_LISTADO], "mas": max(0, len(items) - MAX_LISTADO)}


def _recorrer(profundidad_max, tiempo_max):
    """Camina por todas tus carpetas (sin entrar a las pesadas) y entrega (ruta_virtual, ruta, nombre)."""
    limite = time.time() + tiempo_max
    for clave, (_, base) in _raices().items():
        pila = [(base, clave, 0)]
        while pila:
            if time.time() > limite:
                return
            carpeta, virtual, prof = pila.pop()
            try:
                with os.scandir(carpeta) as it:
                    entradas = list(it)
            except OSError:
                continue
            for e in entradas:
                if _oculto(e.name, e.path) or e.name.lower() in _SALTAR:
                    continue
                v = virtual + "/" + e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if prof < profundidad_max:
                            pila.append((e.path, v, prof + 1))
                        yield v, e.path, e.name, True
                    elif e.is_file(follow_symlinks=False):
                        yield v, e.path, e.name, False
                except OSError:
                    continue


def buscar(texto, maximo=60):
    palabras = _normalizar(texto).split()
    if not palabras:
        return []
    hallados = []
    for v, ruta, nombre, es_dir in _recorrer(7, 5.0):
        n = _normalizar(nombre)
        if all(p in n for p in palabras):
            i = _info(ruta, nombre)
            if i:
                i["ruta"] = v
                hallados.append(i)
                if len(hallados) >= maximo:
                    break
    hallados.sort(key=lambda i: -i["fecha"])
    return hallados


def recientes(dias=7, maximo=40):
    """Los archivos que modificaste en los últimos días: lo más probable es que 'se te quedó' uno de estos."""
    desde = time.time() - dias * 86400
    hallados = []
    for v, ruta, nombre, es_dir in _recorrer(4, 4.0):
        if es_dir:
            continue
        try:
            st = os.stat(ruta)
        except OSError:
            continue
        if st.st_mtime >= desde:
            hallados.append({"nombre": nombre, "dir": False, "tam": st.st_size, "fecha": int(st.st_mtime), "ruta": v})
    hallados.sort(key=lambda i: -i["fecha"])
    return hallados[:maximo]


def dar_permiso(virtual, ip):
    """Permiso de descarga para un archivo: un código largo que vale VIDA_PERMISO segundos y solo para esa IP."""
    ruta = resolver(virtual)
    if not ruta or not os.path.isfile(ruta):
        return None
    ahora = time.time()
    with _candado:
        for t in [t for t, p in _permisos.items() if p["vence"] < ahora]:
            _permisos.pop(t, None)
        token = secrets.token_urlsafe(24)
        _permisos[token] = {"ruta": ruta, "ip": ip, "vence": ahora + VIDA_PERMISO}
    return token


def _usar_permiso(token, ip):
    with _candado:
        p = _permisos.get(token or "")
        if not p or p["vence"] < time.time() or p["ip"] != ip:
            return None
        return p["ruta"]


def _nombre_seguro(nombre):
    nombre = os.path.basename(str(nombre).replace("\\", "/"))
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre).strip(" .")
    if not nombre or _oculto(nombre) or nombre.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}:
        nombre = "archivo_del_celular"
    return nombre[:150]


def carpeta_subidas():
    raiz = _raices().get("descargas") or _raices().get("documentos")
    base = raiz[1] if raiz else os.path.expanduser("~")
    carpeta = os.path.join(base, CARPETA_SUBIDAS)
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def _destino_libre(carpeta, nombre):
    base, ext = os.path.splitext(nombre)
    destino, n = os.path.join(carpeta, nombre), 2
    while os.path.exists(destino):
        destino = os.path.join(carpeta, f"{base} ({n}){ext}")
        n += 1
    return destino


# =================================================================================================
# PC: pantalla, bloquear, portapapeles
# =================================================================================================

def captura_pantalla(ancho_max=1600):
    """JPEG de la pantalla (bytes) o None."""
    try:
        from PIL import ImageGrab
        import io
        try:
            img = ImageGrab.grab(all_screens=True)
        except TypeError:
            img = ImageGrab.grab()
        if img.width > ancho_max:
            img = img.resize((ancho_max, int(img.height * ancho_max / img.width)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=70)
        return buf.getvalue()
    except Exception:
        return None


def bloquear_pc():
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.LockWorkStation())
    except Exception:
        return False


def _win_portapapeles():
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = wintypes.LPVOID
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    return ctypes, u, k


def _abrir_portapapeles(u):
    for _ in range(10):                    # otra app puede tenerlo abierto un instante
        if u.OpenClipboard(None):
            return True
        time.sleep(0.05)
    return False


def leer_portapapeles():
    if sys.platform != "win32":
        return None
    try:
        ctypes, u, k = _win_portapapeles()
        if not _abrir_portapapeles(u):
            return None
        try:
            h = u.GetClipboardData(13)     # CF_UNICODETEXT
            if not h:
                return ""
            p = k.GlobalLock(h)
            try:
                return ctypes.wstring_at(p)[:20000]
            finally:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()
    except Exception:
        return None


def poner_portapapeles(texto):
    if sys.platform != "win32":
        return False
    try:
        ctypes, u, k = _win_portapapeles()
        datos_ = str(texto).encode("utf-16-le") + b"\x00\x00"
        h = k.GlobalAlloc(0x0002, len(datos_))          # GMEM_MOVEABLE
        if not h:
            return False
        p = k.GlobalLock(h)
        ctypes.memmove(p, datos_, len(datos_))
        k.GlobalUnlock(h)
        if not _abrir_portapapeles(u):
            k.GlobalFree(h)
            return False
        try:
            u.EmptyClipboard()
            if not u.SetClipboardData(13, h):
                k.GlobalFree(h)
                return False
            return True
        finally:
            u.CloseClipboard()
    except Exception:
        return False


def procesos(n=8):
    """Los programas que más memoria usan ahora (solo para ver; desde el celular no se cierran)."""
    try:
        import psutil
    except Exception:
        return []
    suma = {}
    for pr in psutil.process_iter(["name", "memory_info"]):
        try:
            nombre = (pr.info["name"] or "").rsplit(".", 1)[0]
            mem = pr.info["memory_info"].rss if pr.info["memory_info"] else 0
        except Exception:
            continue
        if not nombre or nombre.lower() in ("system", "registry", "memory compression", "idle", "svchost"):
            continue
        suma[nombre] = suma.get(nombre, 0) + mem
    orden = sorted(suma.items(), key=lambda x: -x[1])[:n]
    return [{"nombre": k, "ram": v} for k, v in orden]


_RE_URL = re.compile(r"^https?://[^\s<>\"]{1,2000}$", re.I)


def abrir_enlace(url):
    """Abre un link http(s) en el navegador del PC. Devuelve (ok, mensaje)."""
    url = str(url or "").strip()
    if not _RE_URL.match(url):
        return False, "Solo enlaces que empiecen por http:// o https://"
    try:
        import webbrowser
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return True, ""
    except Exception as e:
        return False, str(e)


def apagar_pantalla():
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        # WM_SYSCOMMAND / SC_MONITORPOWER / 2 = apagar. PostMessage para no quedarse esperando.
        return bool(ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2))
    except Exception:
        return False


def _archivo_arranque():
    appdata = os.environ.get("APPDATA")
    if sys.platform != "win32" or not appdata:
        return None
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Arche.bat")


def arranque_activo():
    ruta = _archivo_arranque()
    return bool(ruta and os.path.isfile(ruta))


def fijar_arranque(activo):
    """Arché se abre solo al iniciar sesión en Windows (un .bat en la carpeta Inicio). Devuelve True si quedó como se pidió."""
    ruta = _archivo_arranque()
    if not ruta:
        return False
    if not activo:
        try:
            os.remove(ruta)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True
    carpeta_arche = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    python = sys.executable or "python"
    if os.path.basename(python).lower() == "pythonw.exe":
        python = os.path.join(os.path.dirname(python), "python.exe")
    contenido = ("@echo off\r\n"
                 "rem Lo creó Arché (control del celular). Bórralo para que no arranque solo.\r\n"
                 f'cd /d "{carpeta_arche}"\r\n'
                 f'start "Arche" /min "{python}" main.py\r\n')
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="mbcs" if sys.platform == "win32" else "utf-8") as fh:
            fh.write(contenido)
        return True
    except OSError:
        return False


# =================================================================================================
# Página
# =================================================================================================

PAGINA = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<meta name="theme-color" content="#0c0c14"><meta name="apple-mobile-web-app-capable" content="yes"><title>Arché</title><style>
:root{--bg:#0c0c14;--s1:#15151f;--s2:#1e1e2c;--s3:#272738;--ln:rgba(255,255,255,.06);--t:#ededf4;--t2:#9494a8;--t3:#5f5f74;
--ac:#8b7cff;--ac2:rgba(139,124,255,.15);--rj:#ff7088;--ok:#4fd08b;--am:#ffc65c;--az:#6aa8ff;--ro:#ff8ad8;--ve:#5fd3c4}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;margin:0}
html,body{height:100%}body{background:var(--bg);color:var(--t);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;display:flex;flex-direction:column;overflow:hidden}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
input,textarea{font:inherit;color:var(--t);background:var(--s2);border:1px solid transparent;border-radius:12px;padding:12px 14px;width:100%;outline:none;font-size:16px}
input:focus,textarea:focus{border-color:var(--ac)}
svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.orbe{width:30px;height:30px;border-radius:50%;flex:none;background:radial-gradient(circle at 35% 30%,#fff9,var(--c,var(--ac)) 58%,transparent 72%);
box-shadow:0 0 18px -2px var(--c,var(--ac));animation:resp 3.4s ease-in-out infinite}
.hablando{--c:#ff7a9a;animation-duration:.8s}.pensando{--c:#b48cff;animation-duration:1.3s}.escuchando{--c:#6aa8ff;animation-duration:1.7s}
@keyframes resp{50%{transform:scale(1.1)}}
.sub{color:var(--t2);font-size:13px}
/* entrar */
#login{flex:1;display:none;flex-direction:column;align-items:center;justify-content:center;padding:32px;gap:14px;text-align:center}
#login .orbe{width:64px;height:64px;margin-bottom:8px}#login h1{font-size:22px;font-weight:600}
#pi{width:220px;text-align:center;font-size:28px;letter-spacing:.5em;padding:14px 0 14px .5em;border-radius:16px;margin-top:8px}
.prim{background:var(--ac);color:#fff;border-radius:14px;padding:13px 28px;font-weight:600}
#pe{color:var(--rj);font-size:14px;min-height:20px}
/* app */
#app{flex:1;display:none;flex-direction:column;min-height:0}
header{display:flex;align-items:center;gap:12px;padding:calc(12px + env(safe-area-inset-top)) 18px 8px}
header b{font-weight:600;font-size:17px}
#conex{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--t2);background:var(--s1);padding:5px 10px;border-radius:999px}
#conex i{width:7px;height:7px;border-radius:50%;background:var(--ok)}#conex.off i{background:var(--rj)}
.vista{flex:1;overflow:auto;display:none;min-height:0;padding:6px 18px 28px}.vista.on{display:block}
#v-chat.on{display:flex;flex-direction:column;padding:0}
.sec{display:flex;align-items:baseline;justify-content:space-between;margin:22px 4px 10px}
.sec h2{font-size:13px;font-weight:600;color:var(--t2);text-transform:uppercase;letter-spacing:.06em}
.sec button{color:var(--ac);font-size:13px}
.card{background:var(--s1);border-radius:18px;padding:4px 16px}
/* inicio */
.hola{font-size:24px;font-weight:600;margin:6px 4px 2px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
.stat{background:var(--s1);border-radius:16px;padding:12px 10px 10px;text-align:center}
.stat b{display:block;font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}.stat span{font-size:11px;color:var(--t2)}
.anillo{width:44px;height:44px;margin:0 auto 4px;display:block}.anillo circle{fill:none;stroke-width:4}.anillo .f{stroke:var(--s3)}.anillo .v{stroke:var(--col);stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%}.stat{position:relative}.stat b{position:absolute;left:0;right:0;top:24px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.acc{display:flex;flex-direction:column;align-items:center;gap:7px;padding:12px 2px;border-radius:16px;font-size:12px;color:var(--t2);text-align:center;line-height:1.2}
.acc:active{background:var(--s1)}
.acc .ico{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:color-mix(in srgb,var(--k,var(--ac)) 16%,transparent);color:var(--k,var(--ac))}
.acc .ico svg{width:22px;height:22px}
/* filas */
.fila{display:flex;align-items:center;gap:14px;padding:11px 0;width:100%;text-align:left}
.fila+.fila{border-top:1px solid var(--ln)}
.lista .fila{padding:10px 4px;border-top:0;border-radius:12px}.lista .fila:active{background:var(--s1)}
.fila .nm{flex:1;min-width:0}.fila .nm>div:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fila .der{color:var(--t2);font-size:13px;font-variant-numeric:tabular-nums}.fila .chev{color:var(--t3)}
.tile{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-size:10px;font-weight:700;letter-spacing:.03em;flex:none;background:var(--s2);color:var(--t2)}
.tile.dir{background:var(--ac2);color:var(--ac)}
.vacio{color:var(--t3);text-align:center;padding:28px 12px;font-size:14px}
/* chat */
#chat{flex:1;overflow:auto;padding:8px 18px 12px;display:flex;flex-direction:column;gap:10px}
.m{max-width:85%;white-space:pre-wrap;word-wrap:break-word}
.m.tu{align-self:flex-end;background:var(--ac2);color:#dcd6ff;padding:9px 14px;border-radius:18px 18px 4px 18px}
.m.arche{align-self:flex-start;background:var(--s1);padding:9px 14px;border-radius:18px 18px 18px 4px}
.sugs{display:flex;gap:8px;overflow-x:auto;padding:4px 14px 2px;scrollbar-width:none}.sugs::-webkit-scrollbar{display:none}
.chip{flex:none;background:var(--s1);color:var(--t2);border-radius:999px;padding:7px 13px;font-size:13px;white-space:nowrap}
.chip.on{background:var(--ac2);color:var(--ac)}
.comp{display:flex;gap:8px;align-items:center;padding:8px 14px 12px}
.comp input{border-radius:22px;background:var(--s1)}
.ib{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;color:var(--t2);flex:none}
.ib.env{background:var(--ac);color:#fff}
/* archivos */
.buscar{position:relative;margin:4px 0 12px}.buscar svg{position:absolute;left:14px;top:13px;color:var(--t3)}
.buscar input{padding-left:42px;border-radius:14px;background:var(--s1)}
.chips{display:flex;gap:8px;overflow-x:auto;margin:0 -18px 12px;padding:0 18px;scrollbar-width:none}.chips::-webkit-scrollbar{display:none}
.migas{display:flex;align-items:center;gap:2px;flex-wrap:wrap;font-size:13px;color:var(--t3);margin:0 0 4px}
.migas button{color:var(--t2);padding:4px}.migas button:last-child{color:var(--t)}
.fab{position:fixed;right:18px;bottom:calc(78px + env(safe-area-inset-bottom));width:54px;height:54px;border-radius:18px;background:var(--ac);color:#fff;
display:none;place-items:center;box-shadow:0 8px 24px -6px rgba(139,124,255,.6)}.fab.on{display:grid}
/* pc */
.met{display:flex;align-items:center;gap:12px;padding:11px 0}.met+.met{border-top:1px solid var(--ln)}
.met span:first-child{width:62px;color:var(--t2);font-size:14px}.met span:last-child{width:58px;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.barra{flex:1;height:5px;background:var(--s2);border-radius:3px;overflow:hidden}.barra i{display:block;height:100%;background:var(--ac);border-radius:3px}
.barra i.alto{background:var(--rj)}
.vol{display:flex;align-items:center;gap:12px;padding:12px 0}
input[type=range]{-webkit-appearance:none;appearance:none;background:none;padding:0;height:28px;flex:1}
input[type=range]::-webkit-slider-runnable-track{height:5px;background:var(--s3);border-radius:3px}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:22px;height:22px;border-radius:50%;background:#fff;margin-top:-8.5px;box-shadow:0 2px 6px #0008}
input[type=range]::-moz-range-track{height:5px;background:var(--s3);border-radius:3px}
input[type=range]::-moz-range-thumb{width:22px;height:22px;border-radius:50%;background:#fff;border:0}
.media{display:flex;justify-content:space-around;padding:6px 0 10px}
.media button{width:50px;height:50px;border-radius:50%;display:grid;place-items:center;color:var(--t)}
.media button.grande{background:var(--ac);color:#fff;width:58px;height:58px}
.media button:active{background:var(--s2)}
.sw{display:flex;align-items:center;gap:12px;padding:13px 0;width:100%;text-align:left}.card>*+*{border-top:1px solid var(--ln)}
.sw .nm{flex:1}.tg{width:46px;height:28px;border-radius:14px;background:var(--s3);position:relative;transition:.2s;flex:none}
.tg::after{content:"";position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:var(--t2);transition:.2s}
.tg.on{background:var(--ac)}.tg.on::after{left:21px;background:#fff}
.niv{padding:12px 0}.niv .seg{display:flex;background:var(--s2);border-radius:10px;padding:3px;margin-top:8px}
.niv .seg button{flex:1;padding:7px 4px;border-radius:8px;font-size:13px;color:var(--t2)}.niv .seg button.on{background:var(--s3);color:var(--t)}
.rojo{color:var(--rj)}
/* nav */
nav{display:grid;grid-template-columns:repeat(4,1fr);padding:6px 6px calc(6px + env(safe-area-inset-bottom));border-top:1px solid var(--ln);background:var(--bg)}
nav button{display:flex;flex-direction:column;align-items:center;gap:3px;padding:6px 0;color:var(--t3);font-size:11px}
nav button.on{color:var(--t)}nav button.on svg{color:var(--ac)}
/* hoja y aviso */
#velo{position:fixed;inset:0;background:rgba(0,0,0,.55);opacity:0;pointer-events:none;transition:.2s;z-index:5}#velo.on{opacity:1;pointer-events:auto}
#hoja{visibility:hidden;position:fixed;left:0;right:0;bottom:0;background:var(--s1);border-radius:24px 24px 0 0;padding:10px 20px calc(22px + env(safe-area-inset-bottom));
transform:translateY(105%);transition:transform .25s ease,visibility .25s;z-index:6;max-height:88vh;overflow:auto}
#hoja.on{transform:none;visibility:visible}#hoja .asa{width:36px;height:4px;border-radius:2px;background:var(--s3);margin:0 auto 16px}
#hoja h3{font-size:18px;font-weight:600;word-break:break-word}
#hoja .card{background:var(--s2)}
.botones{display:flex;gap:10px;margin-top:16px}.botones button{flex:1;padding:13px;border-radius:14px;background:var(--s2);display:flex;align-items:center;justify-content:center;gap:8px}
.botones button.prim{background:var(--ac);color:#fff}.botones button.rojo{background:rgba(255,112,136,.15);color:var(--rj)}
#hoja img{width:100%;border-radius:12px;margin-top:14px;display:block}
.apps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
.apps button{background:var(--s2);border-radius:14px;padding:12px 4px;font-size:12px;color:var(--t2);display:flex;flex-direction:column;align-items:center;gap:6px}
.apps button b{font-size:18px;color:var(--t);font-weight:600}
#aviso{position:fixed;left:50%;top:calc(12px + env(safe-area-inset-top));transform:translate(-50%,calc(-100% - 40px));visibility:hidden;background:var(--s3);color:var(--t);
padding:10px 16px;border-radius:14px;font-size:14px;max-width:90vw;transition:transform .25s,visibility .25s;z-index:9;box-shadow:0 10px 30px -10px #000}
#aviso.on{transform:translate(-50%,0);visibility:visible}#aviso.mal{color:var(--rj)}
</style></head><body>
<svg style="display:none"><defs>
<symbol id="i-casa" viewBox="0 0 24 24"><path d="M3 11 12 4l9 7M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9"/></symbol>
<symbol id="i-chat" viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></symbol>
<symbol id="i-dir" viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></symbol>
<symbol id="i-pc" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></symbol>
<symbol id="i-bus" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></symbol>
<symbol id="i-mus" viewBox="0 0 24 24"><path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/></symbol>
<symbol id="i-env" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
<symbol id="i-mas" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
<symbol id="i-sube" viewBox="0 0 24 24"><path d="M12 20V9M7 14l5-5 5 5M5 4h14"/></symbol>
<symbol id="i-baj" viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></symbol>
<symbol id="i-ver" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></symbol>
<symbol id="i-cand" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></symbol>
<symbol id="i-img" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/></symbol>
<symbol id="i-copi" viewBox="0 0 24 24"><rect x="8" y="4" width="12" height="16" rx="2"/><path d="M16 4V3H5a1 1 0 0 0-1 1v13h4"/></symbol>
<symbol id="i-chev" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></symbol>
<symbol id="i-ant" viewBox="0 0 24 24"><path d="M19 5 9 12l10 7zM5 5v14"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></symbol>
<symbol id="i-sig" viewBox="0 0 24 24"><path d="m5 5 10 7-10 7zM19 5v14"/></symbol>
<symbol id="i-vol" viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4zM15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></symbol>
<symbol id="i-mute" viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4zM16 9l5 6M21 9l-5 6"/></symbol>
<symbol id="i-link" viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></symbol>
<symbol id="i-apps" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/></symbol>
<symbol id="i-campana" viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4"/></symbol>
<symbol id="i-nota" viewBox="0 0 24 24"><path d="M5 4h14v16H5zM9 9h6M9 13h6M9 17h3"/></symbol>
<symbol id="i-luna" viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/></symbol>
<symbol id="i-rayo" viewBox="0 0 24 24"><path d="M13 3 5 14h6l-1 7 8-11h-6z"/></symbol>
</defs></svg>

<div id="login"><div class="orbe"></div><h1>Arché</h1><p class="sub">Escribe tu PIN de 6 números</p>
<input id="pi" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code">
<p id="pe"></p><button class="prim" onclick="entrar()">Entrar</button>
<p class="sub" style="max-width:280px;margin-top:10px">Lo ves en la ventana de Arché (Ajustes › Celular) o diciéndole «pin del celular».</p></div>

<div id="app">
<header><div id="o" class="orbe"></div><div style="flex:1"><b>Arché</b><div class="sub" id="e">conectando…</div></div><div id="conex"><i></i><span>PC</span></div></header>

<section class="vista on" id="v-ini">
<div class="hola" id="hola">Hola</div><div class="sub" style="margin:0 4px" id="fecha"></div>
<div class="stats" id="stats"></div>
<div class="sec"><h2>Acciones rápidas</h2></div>
<div class="grid" id="rapidas"></div>
<div class="sec"><h2>Archivos recientes</h2><button onclick="irA('arch');modo('rec')">Ver todos</button></div>
<div class="card lista" id="ini-rec"><div class="vacio">Buscando…</div></div>
</section>

<section class="vista" id="v-chat"><div id="chat"></div>
<div class="sugs" id="sugs"></div>
<form class="comp" onsubmit="return enviar()"><input id="t" placeholder="Escríbele a Arché" autocomplete="off" enterkeyhint="send">
<button class="ib env" aria-label="Enviar"><svg><use href="#i-env"/></svg></button></form></section>

<section class="vista" id="v-arch">
<form class="buscar" onsubmit="return buscarA()"><svg><use href="#i-bus"/></svg><input id="q" placeholder="Buscar en tu PC" autocomplete="off" enterkeyhint="search"></form>
<div class="chips" id="chips"></div>
<div class="migas" id="migas"></div><div class="lista" id="lista"></div></section>

<section class="vista" id="v-pc">
<div class="sec" style="margin-top:8px"><h2>Sonido</h2></div>
<div class="card"><div class="media"><button onclick="cmd('cancion anterior')" aria-label="Anterior"><svg><use href="#i-ant"/></svg></button>
<button class="grande" onclick="cmd('pausa la musica')" aria-label="Pausa"><svg><use href="#i-play"/></svg></button>
<button onclick="cmd('siguiente cancion')" aria-label="Siguiente"><svg><use href="#i-sig"/></svg></button></div>
<div class="vol"><button onclick="cmd('silencia')" aria-label="Silenciar" style="color:var(--t2)"><svg><use href="#i-mute"/></svg></button>
<input type="range" min="0" max="100" step="5" value="50" id="volr" onchange="volumen(this.value)"><span id="volv" class="sub" style="width:38px;text-align:right">50%</span></div></div>
<div class="sec"><h2>Equipo</h2></div><div class="card" id="met"></div>
<div class="sec"><h2>Programas abiertos</h2><button onclick="procesos()">Actualizar</button></div><div class="card" id="procs"><div class="vacio">Cargando…</div></div>
<div class="sec"><h2>Pantalla</h2></div><div class="card">
<button class="fila" onclick="captura()"><svg><use href="#i-img"/></svg><span class="nm">Ver la pantalla</span><svg class="chev"><use href="#i-chev"/></svg></button>
<button class="fila" onclick="apagarPantalla()"><svg><use href="#i-luna"/></svg><span class="nm">Apagar la pantalla</span><svg class="chev"><use href="#i-chev"/></svg></button>
<button class="fila rojo" onclick="bloquear()"><svg><use href="#i-cand"/></svg><span class="nm">Bloquear el PC</span></button></div>
<div class="sec"><h2>Arché</h2></div><div class="card"><button class="sw" onclick="arranque()"><span class="nm">Arrancar con Windows<div class="sub">Se abre solo al prender el PC</div></span><span class="tg" id="tg-arr"></span></button></div>
<div class="card" id="ctl" style="margin-top:10px"></div>
</section>

<nav><button class="on" data-v="ini" onclick="tab(this)"><svg><use href="#i-casa"/></svg>Inicio</button>
<button data-v="chat" onclick="tab(this)"><svg><use href="#i-chat"/></svg>Chat</button>
<button data-v="arch" onclick="tab(this)"><svg><use href="#i-dir"/></svg>Archivos</button>
<button data-v="pc" onclick="tab(this)"><svg><use href="#i-pc"/></svg>PC</button></nav>
<button class="fab" id="fab" onclick="$('sub').click()" aria-label="Mandar archivo al PC"><svg><use href="#i-sube"/></svg></button>
<input type="file" id="sub" multiple hidden>
</div>
<div id="velo" onclick="cerrar()"></div><div id="hoja"><div class="asa"></div><div id="hc"></div></div><div id="aviso"></div>
<script>
let pin=localStorage.getItem('arche_pin')||'',ruta='',vista='ini',archivos=true,dentro=false,reloj=null,firma='',turno=0,nombresRaiz={},enLinea=true;
const $=id=>document.getElementById(id);
const H=x=>Object.assign({'X-Pin':pin},x||{});
const ic=n=>'<svg><use href="#i-'+n+'"/></svg>';
function el(tag,props,...h){const e=document.createElement(tag);Object.assign(e,props||{});h.forEach(x=>e.append(x));return e}
function sv(n){const s=el('span');s.innerHTML=ic(n);return s.firstChild}
let tAviso;function aviso(txt,mal){const a=$('aviso');a.textContent=txt;a.className='on'+(mal?' mal':'');clearTimeout(tAviso);tAviso=setTimeout(()=>a.className=mal?'mal':'',3200)}
function hoja(nodos){const c=$('hc');c.innerHTML='';[].concat(nodos).forEach(n=>c.append(n));$('velo').classList.add('on');$('hoja').classList.add('on')}
function cerrar(){$('velo').classList.remove('on');$('hoja').classList.remove('on')}
function botones(...b){return el('div',{className:'botones'},...b.map(([txt,f,clase,icono])=>{const x=el('button',{className:clase||'',onclick:f});if(icono)x.append(sv(icono));x.append(txt);return x}))}
const post=(url,obj)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj||{})}).then(r=>r.json());
// ---------- entrar ----------
function mostrarLogin(msg){dentro=false;clearInterval(reloj);reloj=null;$('app').style.display='none';$('login').style.display='flex';$('pe').textContent=msg||'';setTimeout(()=>$('pi').focus(),50)}
function entrar(){const v=$('pi').value.replace(/\D/g,'');if(v.length!=6){$('pe').textContent='Son 6 números.';return}pin=v;$('pe').textContent='';cargar(true)}
$('pi').addEventListener('input',e=>{e.target.value=e.target.value.replace(/\D/g,'');if(e.target.value.length==6)entrar()});
$('pi').addEventListener('keydown',e=>{if(e.key=='Enter')entrar()});
async function api(url,op){let r;try{r=await fetch(url,Object.assign({},op,{headers:H(op&&op.headers)}))}catch(e){conexion(false);throw e}
 conexion(true);
 if(r.status==401){localStorage.removeItem('arche_pin');mostrarLogin(pin?'PIN incorrecto.':'');throw new Error('pin')}
 if(r.status==429){const s=parseInt(r.headers.get('Retry-After')||'60');mostrarLogin('Demasiados intentos. Espera '+(s>90?Math.ceil(s/60)+' min':s+' s')+'.');throw new Error('pin')}
 return r}
function conexion(ok){if(ok==enLinea)return;enLinea=ok;$('conex').classList.toggle('off',!ok);$('conex').lastChild.textContent=ok?'PC':'Sin conexión'}
function irA(v){tab(document.querySelector('nav button[data-v='+v+']'))}
function tab(b){document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x==b));vista=b.dataset.v;
 document.querySelectorAll('.vista').forEach(v=>v.classList.toggle('on',v.id=='v-'+vista));
 $('fab').classList.toggle('on',vista=='arch'&&archivos);
 if(vista=='arch'&&!$('lista').childElementCount)abrir('');if(vista=='pc'){procesos();estadoArranque()}
 if(vista=='chat'){const c=$('chat');c.scrollTop=c.scrollHeight}}
// ---------- estado ----------
async function cargar(primera){
 if(!pin){mostrarLogin('');return}
 try{const r=await api('/api/estado');const d=await r.json();
  if(!dentro){dentro=true;localStorage.setItem('arche_pin',pin);$('login').style.display='none';$('app').style.display='flex';$('pi').value='';inicio()}
  if(!reloj)reloj=setInterval(()=>{if(!document.hidden&&dentro)cargar()},2000);
  archivos=d.archivos;$('o').className='orbe '+d.estado;$('e').textContent={quieto:'en reposo',reposo:'en reposo'}[d.estado]||d.estado;
  const f=JSON.stringify(d.chat);if(f!=firma){firma=f;const c=$('chat'),abajo=c.scrollTop+c.clientHeight>=c.scrollHeight-60;c.innerHTML='';
   if(!d.chat.length)c.append(el('div',{className:'vacio',textContent:'Escríbele algo a Arché o toca una sugerencia.'}));
   d.chat.forEach(m=>c.append(el('div',{className:'m '+(m.q=='tu'?'tu':'arche'),textContent:m.t})));if(abajo||primera)c.scrollTop=c.scrollHeight}
  pintarCtl(d.controles);pintarEquipo(d.equipo||{});
 }catch(e){if(e.message!='pin')$('e').textContent='sin conexión con el PC'}}
function pintarEquipo(q){const st=$('stats'),m=$('met');st.innerHTML='';m.innerHTML='';
 [['CPU','cpu','--az'],['RAM','ram','--ac'],['Disco','disco','--ve'],['Batería','bateria','--ok']].forEach(([n,k,col])=>{if(q[k]==null)return;
  const v=Math.round(q[k]),alto=k=='bateria'?v<20:v>85;
  const an=document.createElementNS('http://www.w3.org/2000/svg','svg');an.setAttribute('viewBox','0 0 44 44');an.setAttribute('class','anillo');an.style.setProperty('--col','var('+(alto?'--rj':col)+')');an.innerHTML='<circle class="f" cx="22" cy="22" r="18"/><circle class="v" cx="22" cy="22" r="18" stroke-dasharray="'+(1.131*Math.min(100,v)).toFixed(1)+' 200"/>';st.append(el('div',{className:'stat'},an,el('b',{textContent:v+'%'}),el('span',{textContent:n+(k=='bateria'&&q.enchufado?' ⚡':'')})));
  m.append(el('div',{className:'met'},el('span',{textContent:n}),el('div',{className:'barra'},el('i',{className:alto?'alto':'',style:'width:'+Math.min(100,v)+'%'})),
   el('span',{textContent:v+'%'+(k=='bateria'&&q.enchufado?' ⚡':'')})))});
 if(!m.childElementCount)m.append(el('div',{className:'vacio',textContent:'Sin datos del equipo.'}))}
function pintarCtl(lista){const c=$('ctl');c.innerHTML='';c.style.display=lista.length?'':'none';
 lista.forEach(x=>{if(x.tipo=='switch')c.append(el('button',{className:'sw',onclick:()=>cmd(x.valor?x.off:x.on)},el('span',{className:'nm',textContent:x.nombre}),el('span',{className:'tg'+(x.valor?' on':'')})));
  else c.append(el('div',{className:'niv'},el('div',{textContent:x.nombre}),el('div',{className:'seg'},...x.niveles.map(n=>el('button',{className:x.valor==n[0]?'on':'',textContent:n[0],onclick:()=>cmd(n[1])})))))})}
// ---------- inicio ----------
const RAPIDAS=[['Pantalla','img','--az',captura],['Música','mus','--ro',()=>irA('pc')],['Abrir app','apps','--ac',hojaApps],['Enlace al PC','link','--ve',hojaEnlace],
 ['Portapapeles','copi','--am',portapapeles],['Recordar','campana','--ok',hojaRecordar],['Mandar archivo','sube','--az',()=>$('sub').click()],['Bloquear','cand','--rj',bloquear]];
RAPIDAS.forEach(([n,i,k,f])=>{const ico=el('div',{className:'ico'});ico.append(sv(i));$('rapidas').append(el('button',{className:'acc',style:'--k:var('+k+')',onclick:f},ico,n))});
function inicio(){const h=new Date().getHours();$('hola').textContent=(h<12?'Buenos días':h<19?'Buenas tardes':'Buenas noches');
 $('fecha').textContent=new Date().toLocaleDateString('es',{weekday:'long',day:'numeric',month:'long'});
 if(!archivos){$('ini-rec').innerHTML='<div class="vacio">Archivos apagados en este PC.</div>';return}
 api('/api/archivos?ruta=').then(r=>r.json()).then(d=>d.items.forEach(i=>nombresRaiz[i.ruta]=i.nombre)).catch(()=>{})
 .then(()=>api('/api/recientes')).then(r=>r.json()).then(d=>{const c=$('ini-rec');c.innerHTML='';
  if(!d.items.length){c.append(el('div',{className:'vacio',textContent:'Nada reciente.'}));return}
  d.items.slice(0,4).forEach(it=>c.append(filaArchivo(it,true)))}).catch(()=>{})}
// ---------- chat ----------
async function cmd(t,silencio){try{const d=await post('/api/enviar',{texto:t});if(!d.ok)aviso(d.mensaje||'No se pudo.',1);else if(!silencio&&vista!='chat')aviso('Listo: '+t);setTimeout(cargar,350)}catch(e){}}
function enviar(){const i=$('t');if(i.value.trim())cmd(i.value.trim(),1);i.value='';return false}
['¿Qué hora es?','Dame las noticias','¿Cómo está el clima?','Crea una nota','Mis recordatorios','¿Qué puedes hacer?'].forEach(t=>
 $('sugs').append(el('button',{className:'chip',textContent:t,onclick:()=>{if(t=='Crea una nota'){$('t').value='crea una nota ';$('t').focus()}else cmd(t.replace(/[¿?]/g,'').toLowerCase(),1)}})));
// ---------- archivos ----------
const TIPOS={pdf:'#ff7088',doc:'#6aa8ff',docx:'#6aa8ff',xls:'#4fd08b',xlsx:'#4fd08b',csv:'#4fd08b',ppt:'#ffa463',pptx:'#ffa463',
 jpg:'#c38cff',jpeg:'#c38cff',png:'#c38cff',gif:'#c38cff',webp:'#c38cff',heic:'#c38cff',mp4:'#ff8ad8',mov:'#ff8ad8',mkv:'#ff8ad8',mp3:'#5fd3c4',wav:'#5fd3c4',
 zip:'#ffc65c',rar:'#ffc65c','7z':'#ffc65c',py:'#ffc65c',cpp:'#6aa8ff',ino:'#5fd3c4',txt:'#9494a8'};
function tile(it){if(it.dir){const t=el('div',{className:'tile dir'});t.append(sv('dir'));return t}
 const e=(it.nombre.includes('.')?it.nombre.split('.').pop():'').toLowerCase().slice(0,4);
 const t=el('div',{className:'tile',textContent:(e||'·').toUpperCase()});if(TIPOS[e]){t.style.color=TIPOS[e];t.style.background=TIPOS[e]+'22'}return t}
function tam(n){if(n<1024)return n+' B';const u=['KB','MB','GB','TB'];let i=-1;do{n/=1024;i++}while(n>=1024&&i<3);return n.toFixed(n<10?1:0)+' '+u[i]}
function fecha(s){if(!s)return'';const d=new Date(s*1000),h=new Date(),ay=new Date(h-864e5),hm=d.toTimeString().slice(0,5);
 if(d.toDateString()==h.toDateString())return'hoy, '+hm;if(d.toDateString()==ay.toDateString())return'ayer, '+hm;return d.toLocaleDateString('es',{day:'numeric',month:'short'})}
const bonita=r=>r.split('/').slice(0,-1).map((x,i)=>i==0&&nombresRaiz[x]?nombresRaiz[x]:x).join(' / ');
function filaArchivo(it,donde){const meta=it.dir?(it.fecha?fecha(it.fecha):''):(tam(it.tam)+' · '+fecha(it.fecha));const lugar=donde?bonita(it.ruta):'';
 return el('button',{className:'fila',onclick:()=>it.dir?(irA('arch'),abrir(it.ruta)):detalle(it,lugar)},tile(it),
  el('div',{className:'nm'},el('div',{textContent:it.nombre}),el('div',{className:'sub',textContent:lugar?lugar+' · '+meta:meta})))}
function chips(activo){const c=$('chips');c.innerHTML='';
 c.append(el('button',{className:'chip'+(activo=='rec'?' on':''),textContent:'Recientes',onclick:()=>modo('rec')}));
 Object.entries(nombresRaiz).forEach(([k,n])=>c.append(el('button',{className:'chip'+(activo==k?' on':''),textContent:n,onclick:()=>abrir(k)})))}
function modo(m){m=='rec'?verRecientes():abrir(ruta)}
function migas(){const r=$('migas');r.innerHTML='';const p=ruta?ruta.split('/'):[];if(!p.length)return;
 r.append(el('button',{textContent:'Inicio',onclick:()=>abrir('')}));
 p.forEach((x,i)=>{r.append(el('span',{textContent:'/'}));r.append(el('button',{textContent:i==0&&nombresRaiz[x]?nombresRaiz[x]:x,onclick:()=>abrir(p.slice(0,i+1).join('/'))}))})}
function pintar(items,titulo,donde,mas){const l=$('lista');l.innerHTML='';
 if(titulo)l.append(el('div',{className:'sub',textContent:titulo,style:'margin:2px 4px 6px'}));
 if(!items.length){l.append(el('div',{className:'vacio',textContent:'No hay nada aquí.'}));return}
 items.forEach(it=>l.append(filaArchivo(it,donde)));
 if(mas)l.append(el('div',{className:'sub',textContent:'Y '+mas+' más. Usa el buscador.',style:'margin:10px 4px'}))}
function detalle(it,donde){hoja([el('h3',{textContent:it.nombre}),el('div',{className:'sub',textContent:tam(it.tam)+' · '+fecha(it.fecha)+(donde?' · '+donde:''),style:'margin-top:4px'}),
 botones(['Abrir',()=>bajar(it.ruta,1),'','ver'],['Descargar',()=>bajar(it.ruta,0),'prim','baj'])])}
async function abrir(r){const yo=++turno;if(!archivos){$('lista').innerHTML='<div class="vacio">Los archivos están apagados en este PC.</div>';return}
 try{const x=await api('/api/archivos?ruta='+encodeURIComponent(r));if(!x.ok){aviso('No pude abrir esa carpeta.',1);return}
  const d=await x.json();if(yo!=turno)return;ruta=d.ruta;if(!ruta)d.items.forEach(i=>nombresRaiz[i.ruta]=i.nombre);
  chips(ruta.split('/')[0]||'');migas();pintar(d.items,ruta?'':'Tus carpetas',false,d.mas)}catch(e){}}
async function verRecientes(){const yo=++turno;chips('rec');$('migas').innerHTML='';$('lista').innerHTML='<div class="vacio">Buscando…</div>';
 try{const d=await (await api('/api/recientes')).json();if(yo==turno)pintar(d.items,'Lo que tocaste en los últimos 7 días',true)}catch(e){}}
function buscarA(){const q=$('q').value.trim();if(!q)return false;const yo=++turno;$('q').blur();chips('');$('migas').innerHTML='';$('lista').innerHTML='<div class="vacio">Buscando…</div>';
 api('/api/buscar?q='+encodeURIComponent(q)).then(r=>r.json()).then(d=>yo==turno&&pintar(d.items,d.items.length+' resultado'+(d.items.length==1?'':'s')+' para «'+q+'»',true)).catch(()=>{});return false}
async function bajar(r,ver){cerrar();try{const d=await post('/api/permiso',{ruta:r});if(!d.ok){aviso('No pude preparar ese archivo.',1);return}
 const url='/api/descargar?t='+encodeURIComponent(d.token)+(ver?'&ver=1':'');
 if(ver)window.open(url,'_blank');else{const a=el('a',{href:url,download:''});document.body.append(a);a.click();a.remove();aviso('Descargando…')}}catch(e){}}
$('sub').onchange=async e=>{const fs=[...e.target.files];for(const f of fs){aviso('Mandando '+f.name+'…');
 try{const x=await api('/api/subir',{method:'POST',headers:{'X-Nombre':encodeURIComponent(f.name)},body:f});const d=await x.json();
  d.ok?aviso('Listo: '+d.nombre+' está en Descargas / Desde el celular'):aviso(d.mensaje||'No se pudo.',1)}catch(err){if(err.message!='pin')aviso('Falló '+f.name,1)}}
 e.target.value=''};
// ---------- PC ----------
function volumen(v){$('volv').textContent=v+'%';cmd('pon el volumen al '+v,1)}
$('volr').oninput=e=>$('volv').textContent=e.target.value+'%';
async function procesos(){try{const d=await (await api('/api/procesos')).json();const c=$('procs');c.innerHTML='';
 if(!d.items.length){c.append(el('div',{className:'vacio',textContent:'Sin datos.'}));return}
 d.items.forEach(p=>c.append(el('div',{className:'fila'},el('span',{className:'nm',textContent:p.nombre}),el('span',{className:'der',textContent:tam(p.ram)}))))}catch(e){}}
async function estadoArranque(){try{const d=await (await api('/api/arranque')).json();$('tg-arr').classList.toggle('on',!!d.activo);$('tg-arr').closest('.card').style.display=d.disponible?'':'none'}catch(e){}}
async function arranque(){const on=!$('tg-arr').classList.contains('on');try{const d=await post('/api/arranque',{activo:on});
 $('tg-arr').classList.toggle('on',!!d.activo);aviso(d.ok?(d.activo?'Arché arrancará con Windows':'Ya no arranca con Windows'):'No pude cambiarlo',!d.ok)}catch(e){}}
async function captura(){hoja([el('h3',{textContent:'Pantalla del PC'}),el('div',{className:'vacio',textContent:'Tomando captura…'})]);
 try{const x=await api('/api/pantalla');if(!x.ok){hoja([el('h3',{textContent:'Pantalla del PC'}),el('div',{className:'vacio',textContent:'No pude ver la pantalla.'})]);return}
  const u=URL.createObjectURL(await x.blob());hoja([el('h3',{textContent:'Pantalla del PC'}),el('img',{src:u,alt:'Pantalla del PC'}),botones(['Otra vez',captura,'','img'])])}catch(e){}}
async function apagarPantalla(){try{const d=await post('/api/apagar_pantalla');aviso(d.ok?'Pantalla apagada (se prende al mover el mouse)':'No pude apagarla',!d.ok)}catch(e){}}
function bloquear(){hoja([el('h3',{textContent:'¿Bloquear el PC?'}),el('div',{className:'sub',textContent:'Para volver a usarlo hay que poner la clave de Windows.',style:'margin-top:4px'}),
 botones(['Cancelar',cerrar],['Bloquear',async()=>{try{const d=await post('/api/bloquear');cerrar();aviso(d.ok?'PC bloqueado':'No pude bloquearlo.',!d.ok)}catch(e){}},'rojo','cand'])])}
function portapapeles(){const ta=el('textarea',{rows:4,placeholder:'Texto para pasar entre el celular y el PC',style:'margin-top:14px'});
 hoja([el('h3',{textContent:'Portapapeles'}),ta,botones(['Traer del PC',async()=>{try{const d=await (await api('/api/portapapeles')).json();
   if(!d.ok){aviso('No pude leerlo.',1);return}ta.value=d.texto;try{await navigator.clipboard.writeText(d.texto);aviso('Copiado en el celular')}catch(e){aviso('Traído del PC')}}catch(e){}},'','copi'],
  ['Mandar al PC',async()=>{if(!ta.value)return;try{const d=await post('/api/portapapeles',{texto:ta.value});
   aviso(d.ok?'Listo: pégalo en el PC con Ctrl+V':'No pude ponerlo en el PC',!d.ok);if(d.ok)cerrar()}catch(e){}},'prim','env'])])}
function hojaApps(){const otra=el('input',{placeholder:'Otra app, ej: word',style:'margin-top:14px'});
 const APPS=[['Spotify','S'],['YouTube','Y'],['Chrome','C'],['VS Code','V'],['WhatsApp','W'],['Explorador','E'],['Calculadora','='],['Arduino','A']];
 hoja([el('h3',{textContent:'Abrir en el PC'}),el('div',{className:'apps'},...APPS.map(([n,l])=>el('button',{onclick:()=>{cmd('abre '+n.toLowerCase());cerrar()}},el('b',{textContent:l}),n))),
  otra,botones(['Abrir',()=>{if(otra.value.trim()){cmd('abre '+otra.value.trim());cerrar()}},'prim','apps'])])}
function hojaEnlace(){const u=el('input',{type:'url',placeholder:'https://…',style:'margin-top:14px',inputMode:'url'});
 hoja([el('h3',{textContent:'Abrir un enlace en el PC'}),el('div',{className:'sub',textContent:'Pega un link del celular y se abre en el navegador del PC.',style:'margin-top:4px'}),u,
  botones(['Pegar',async()=>{try{u.value=await navigator.clipboard.readText()}catch(e){aviso('Pégalo a mano',1)}},'','copi'],
   ['Abrir en el PC',async()=>{let v=u.value.trim();if(!v)return;if(!/^https?:\/\//i.test(v))v='https://'+v;try{const d=await post('/api/enlace',{url:v});aviso(d.ok?'Abierto en el PC':(d.mensaje||'No pude abrirlo'),!d.ok);if(d.ok)cerrar()}catch(e){}},'prim','link'])])}
function hojaRecordar(){const t=el('input',{placeholder:'¿Qué te recuerdo?',style:'margin-top:14px'});let cuando='10 minutos';
 const ops=['10 minutos','30 minutos','1 hora','2 horas'];const fila=el('div',{className:'chips',style:'margin:12px 0 0;padding:0'});
 const pintarOps=()=>{fila.innerHTML='';ops.forEach(o=>fila.append(el('button',{className:'chip'+(o==cuando?' on':''),textContent:'en '+o,onclick:()=>{cuando=o;pintarOps()}})))};pintarOps();
 hoja([el('h3',{textContent:'Recordatorio'}),el('div',{className:'sub',textContent:'Arché te avisa en el PC.',style:'margin-top:4px'}),t,fila,
  botones(['Crear',()=>{if(!t.value.trim())return;cmd('recuerdame en '+cuando+' que '+t.value.trim());cerrar()},'prim','campana'])])}
pin?cargar(true):mostrarLogin('');
</script></body></html>"""


_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def red_permitida(ip):
    """Solo tu red de casa (direcciones privadas), el propio PC y Tailscale."""
    try:
        d = ipaddress.ip_address(ip)
        if getattr(d, "ipv4_mapped", None):
            d = d.ipv4_mapped
    except ValueError:
        return False
    return d.is_loopback or d.is_private or d.is_link_local or (d.version == 4 and d in _TAILSCALE)


def _exe_tailscale():
    import shutil
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        ruta = os.path.join(base, "Tailscale", "tailscale.exe") if base else ""
        if ruta and os.path.isfile(ruta):
            return ruta
    return None


def ip_tailscale():
    """La dirección 100.x.x.x de Tailscale si está instalado y conectado; si no, None."""
    try:
        import psutil
        for direcciones_ in psutil.net_if_addrs().values():
            for a in direcciones_:
                if a.family == socket.AF_INET and ipaddress.ip_address(a.address) in _TAILSCALE:
                    return a.address
    except Exception:
        pass
    exe = _exe_tailscale()                 # sin psutil: se lo preguntamos a Tailscale
    if exe:
        try:
            import subprocess
            r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for linea in r.stdout.split():
                if ipaddress.ip_address(linea.strip()) in _TAILSCALE:
                    return linea.strip()
        except Exception:
            pass
    return None


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _pin():
    pin = str(ajustes.obtener("celular_pin") or "")
    if len(pin) != 6 or not pin.isdigit():
        pin = "%06d" % random.randint(0, 999999)
        ajustes.fijar("celular_pin", pin)
    return pin


def nuevo_pin():
    ajustes.fijar("celular_pin", "%06d" % random.randint(0, 999999))
    with _candado:
        _permisos.clear()                  # los permisos de descarga viejos ya no sirven
    return ajustes.obtener("celular_pin")


def activo():
    return _servidor is not None


def _puerto():
    return _servidor.server_address[1] if _servidor is not None else ajustes.obtener("celular_puerto")


def direccion():
    """La dirección en la wifi de casa."""
    return f"http://{ip_local()}:{_puerto()}"


def direccion_afuera():
    """La dirección para entrar desde cualquier red (Tailscale), o None si no está."""
    ip = ip_tailscale()
    return f"http://{ip}:{_puerto()}" if ip else None


def instrucciones_afuera():
    afuera = direccion_afuera()
    pin = ajustes.obtener("celular_pin")
    if afuera:
        return (f"Desde cualquier red: abre {afuera} en el celular (con Tailscale encendido en el celular "
                f"y la misma cuenta). PIN: {pin}. Si no carga, falta permitir el puerto en el firewall "
                f"de Windows: abre PowerShell como administrador y pega:\n" + regla_firewall())
    if _exe_tailscale():
        return ("Tailscale está instalado en el PC pero no está conectado. Abre Tailscale (el ícono junto al "
                "reloj de Windows), toca «Log in» / «Connect» y entra con tu cuenta. Luego, en el celular, abre "
                "Tailscale con la MISMA cuenta y actívalo. Después dime otra vez «cómo entro desde afuera».")
    return ("Para entrar desde otra red: 1) instala Tailscale en el PC (tailscale.com/download) y en el "
            "celular (Play Store / App Store); 2) entra con la MISMA cuenta en los dos; 3) dime otra vez "
            "«cómo entro desde afuera» y te doy la dirección. No abre nada a internet: es una red privada "
            "solo entre tus aparatos.")


def regla_firewall():
    return (f'New-NetFirewallRule -DisplayName "Arche celular" -Direction Inbound -Protocol TCP '
            f'-LocalPort {_puerto()} -RemoteAddress LocalSubnet,100.64.0.0/10 -Action Allow')


class _Manejador(BaseHTTPRequestHandler):
    server_version = "Arche"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _cabeceras_seguridad(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "img-src 'self' blob: data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8", extra=None):
        datos_ = cuerpo if isinstance(cuerpo, bytes) else cuerpo.encode("utf-8")
        self.send_response(codigo)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos_)))
        self._cabeceras_seguridad()
        self.end_headers()
        self.wfile.write(datos_)

    def _json(self, obj, codigo=200):
        self._responder(codigo, json.dumps(obj, ensure_ascii=False))

    def _leer_json(self, tope=25000):
        try:
            largo = min(int(self.headers.get("Content-Length", "0")), tope)
            return json.loads(self.rfile.read(largo) or b"{}")
        except Exception:
            return {}

    def _autorizado(self):
        ip = self.client_address[0]
        ahora = time.time()
        with _candado:
            _fallos_globales[:] = [t for t in _fallos_globales if ahora - t < BLOQUEO_GLOBAL]
            bloqueado_todos = len(_fallos_globales) >= MAX_FALLOS_GLOBALES
            f = _fallos.get(ip)
            bloqueado_ip = bool(f and f[0] >= MAX_FALLOS_IP and ahora < f[1])
        if bloqueado_todos or bloqueado_ip:
            espera = (min(_fallos_globales) + BLOQUEO_GLOBAL - ahora) if bloqueado_todos else (f[1] - ahora)
            self._responder(429, "{}", extra={"Retry-After": str(max(1, int(espera) + 1))})
            return False
        enviado = self.headers.get("X-Pin", "")
        if not enviado:                    # sin PIN (página recién abierta): no cuenta como intento
            self._responder(401, "{}")
            return False
        if hmac.compare_digest(enviado.encode("utf-8", "replace"), _pin().encode()):
            with _candado:
                _fallos.pop(ip, None)
            return True
        with _candado:
            for vieja in [k for k, v in _fallos.items() if v[1] < ahora]:     # que no crezca sin limite
                _fallos.pop(vieja, None)
            f = _fallos.setdefault(ip, [0, 0])
            f[0] += 1
            f[1] = ahora + BLOQUEO_IP
            _fallos_globales.append(ahora)
        self._responder(401, "{}")
        return False

    # ---------------------------------------------------------------- GET
    def _red_ok(self):
        if red_permitida(self.client_address[0]):
            return True
        self._responder(403, "Solo desde tu red o Tailscale.", "text/plain; charset=utf-8")
        return False

    def do_GET(self):
        if not self._red_ok():
            return
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        ruta = url.path
        if ruta in ("/", "/index.html"):
            return self._responder(200, PAGINA, "text/html; charset=utf-8")
        if ruta == "/api/descargar":                     # usa un permiso, no el PIN (para que el celular lo baje solo)
            return self._descargar(q.get("t", [""])[0], q.get("ver", ["0"])[0] == "1")
        if not ruta.startswith("/api/"):
            return self._responder(404, "{}")
        if not self._autorizado():
            return
        if ruta == "/api/estado":
            return self._estado()
        if ruta == "/api/pantalla":
            img = captura_pantalla()
            if img is None:
                return self._json({"ok": False}, 503)
            return self._responder(200, img, "image/jpeg")
        if ruta == "/api/procesos":
            return self._json({"items": procesos()})
        if ruta == "/api/arranque":
            return self._json({"activo": arranque_activo(), "disponible": _archivo_arranque() is not None})
        if ruta == "/api/portapapeles":
            texto = leer_portapapeles()
            return self._json({"ok": texto is not None, "texto": texto or ""})
        if not archivos_activos() and ruta in ("/api/archivos", "/api/buscar", "/api/recientes"):
            return self._json({"ok": False, "mensaje": "Archivos apagados en este PC."}, 403)
        if ruta == "/api/archivos":
            d = listar(q.get("ruta", [""])[0])
            return self._json(d) if d is not None else self._json({"ok": False}, 404)
        if ruta == "/api/buscar":
            return self._json({"items": buscar(q.get("q", [""])[0][:100])})
        if ruta == "/api/recientes":
            return self._json({"items": recientes()})
        self._responder(404, "{}")

    def do_HEAD(self):
        self._responder(405, b"")

    def _estado(self):
        en_vivo.sondear()
        ctl = []
        for c in datos.controles():
            item = {k: c[k] for k in ("id", "nombre", "tipo", "valor", "detalle")}
            if c["tipo"] == "switch":
                item.update(on=c["on"], off=c["off"])
            else:
                item["niveles"] = c["niveles"]
            ctl.append(item)
        chat = [{"q": m["q"], "t": m["t"]} for m in list(en_vivo.chat)[-30:]]
        try:
            equipo = datos.equipo()
        except Exception:
            equipo = {}
        self._json({"estado": en_vivo.estado_visual(), "chat": chat, "controles": ctl,
                    "equipo": equipo, "archivos": archivos_activos()})

    def _descargar(self, token, ver):
        ruta = _usar_permiso(token, self.client_address[0])
        if not ruta or not os.path.isfile(ruta) or not archivos_activos():
            return self._responder(404, "No encontrado (o el permiso venció; vuelve a tocar el archivo).",
                                   "text/plain; charset=utf-8")
        tam = os.path.getsize(ruta)
        nombre = os.path.basename(ruta)
        tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
        inicio, fin = 0, tam - 1
        rango = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        if rango and tam:
            a, b = rango.groups()
            if a:
                inicio, fin = int(a), min(int(b), tam - 1) if b else tam - 1
            elif b:
                inicio = max(0, tam - int(b))
            if inicio > fin or inicio >= tam:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{tam}")
                self._cabeceras_seguridad()
                self.end_headers()
                return
        # 'ver' solo abre en el navegador lo que es seguro mostrar; el resto (html, svg...) se descarga
        seguro = (tipo.startswith(("image/", "video/", "audio/")) and tipo != "image/svg+xml") \
            or tipo in ("application/pdf", "text/plain")
        disp = "inline" if ver and seguro else "attachment"
        self.send_response(206 if rango and tam else 200)
        self.send_header("Content-Type", tipo if disp == "inline" else "application/octet-stream")
        self.send_header("Content-Length", str(fin - inicio + 1 if tam else 0))
        self.send_header("Accept-Ranges", "bytes")
        if rango and tam:
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{tam}")
        self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{quote(nombre)}")
        self._cabeceras_seguridad()
        self.end_headers()
        try:
            with open(ruta, "rb") as fh:
                fh.seek(inicio)
                falta = fin - inicio + 1 if tam else 0
                while falta > 0:
                    trozo = fh.read(min(256 * 1024, falta))
                    if not trozo:
                        break
                    self.wfile.write(trozo)
                    falta -= len(trozo)
        except (OSError, ConnectionError):
            pass

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if not self._red_ok():
            return
        ruta = urlsplit(self.path).path
        if ruta not in ("/api/enviar", "/api/permiso", "/api/subir", "/api/bloquear", "/api/portapapeles",
                        "/api/enlace", "/api/apagar_pantalla", "/api/arranque"):
            return self._responder(404, "{}")
        if not self._autorizado():
            return
        if ruta == "/api/enviar":
            texto = str(self._leer_json(2000).get("texto", ""))[:500]
            if es_orden_solo_pc(texto):
                return self._json({"ok": False, "mensaje":
                                   f"«{texto[:60]}» solo la acepto desde el PC, por seguridad."})
            entrada.enviar(texto, "celular")
            return self._json({"ok": True})
        if ruta == "/api/bloquear":
            return self._json({"ok": bloquear_pc()})
        if ruta == "/api/apagar_pantalla":
            return self._json({"ok": apagar_pantalla()})
        if ruta == "/api/enlace":
            ok, msg = abrir_enlace(self._leer_json(4000).get("url", ""))
            return self._json({"ok": ok, "mensaje": msg})
        if ruta == "/api/arranque":
            pedido = bool(self._leer_json(500).get("activo"))
            ok = fijar_arranque(pedido)
            return self._json({"ok": ok, "activo": arranque_activo()})
        if ruta == "/api/portapapeles":
            texto = str(self._leer_json().get("texto", ""))[:20000]
            return self._json({"ok": bool(texto) and poner_portapapeles(texto)})
        if not archivos_activos():
            return self._json({"ok": False, "mensaje": "Archivos apagados en este PC."}, 403)
        if ruta == "/api/permiso":
            token = dar_permiso(self._leer_json(4000).get("ruta", ""), self.client_address[0])
            return self._json({"ok": bool(token), "token": token or ""})
        if ruta == "/api/subir":
            return self._subir()

    def _subir(self):
        try:
            largo = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            largo = -1
        if largo < 0:
            return self._json({"ok": False, "mensaje": "Falta el tamaño."}, 411)
        if largo > MAX_SUBIDA:
            return self._json({"ok": False, "mensaje": f"Muy grande (máximo {MAX_SUBIDA // 1048576} MB)."}, 413)
        nombre = _nombre_seguro(unquote(self.headers.get("X-Nombre", "")))
        carpeta = carpeta_subidas()
        fd, temporal = tempfile.mkstemp(prefix=".subiendo-", dir=carpeta)
        try:
            with os.fdopen(fd, "wb") as fh:
                falta = largo
                while falta > 0:
                    trozo = self.rfile.read(min(256 * 1024, falta))
                    if not trozo:
                        raise ConnectionError("se cortó")
                    fh.write(trozo)
                    falta -= len(trozo)
            with _candado:
                destino = _destino_libre(carpeta, nombre)
                os.replace(temporal, destino)
        except Exception:
            try:
                os.remove(temporal)
            except OSError:
                pass
            return self._json({"ok": False, "mensaje": "Se cortó la subida."}, 400)
        try:
            en_vivo.avisar(f"📲 Llegó del celular: {os.path.basename(destino)} (en Descargas › {CARPETA_SUBIDAS})")
        except Exception:
            pass
        return self._json({"ok": True, "nombre": os.path.basename(destino)})


class _Servidor(ThreadingHTTPServer):
    # En Windows, "reusar la dirección" deja que DOS programas abran el mismo puerto y las
    # peticiones caen en cualquiera (por eso a veces "no dejaba entrar": respondía el de WhatsApp).
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def _puertos_ocupados_por_arche():
    """Puertos que ya usa otra parte de Arché (el webhook de WhatsApp)."""
    ocupados = {8765}
    try:
        from core import whatsapp
        ocupados.add(int(whatsapp._cargar().get("puerto", whatsapp.PUERTO_POR_DEFECTO)))
    except Exception:
        pass
    return ocupados


def iniciar():
    """Enciende la pagina del celular. Devuelve (ok, mensaje)."""
    global _servidor, _hilo
    if _servidor is not None:
        return True, direccion()
    _pin()
    ocupados = _puertos_ocupados_por_arche()
    try:
        preferido = int(ajustes.obtener("celular_puerto"))
    except (TypeError, ValueError):
        preferido = 8766
    candidatos = [p for p in [preferido] + list(range(8766, 8776)) if p not in ocupados]
    error = None
    for puerto in dict.fromkeys(candidatos):
        try:
            _servidor = _Servidor(("0.0.0.0", puerto), _Manejador)
            break
        except OSError as e:
            _servidor, error = None, e
    if _servidor is None:
        return False, f"No pude abrir el puerto ({error})."
    if _servidor.server_address[1] != preferido:
        ajustes.fijar("celular_puerto", _servidor.server_address[1])
    _hilo = threading.Thread(target=_servidor.serve_forever, name="arche-celular", daemon=True)
    _hilo.start()
    ajustes.fijar("celular", True)
    return True, direccion()


def detener():
    global _servidor
    if _servidor is not None:
        try:
            _servidor.shutdown()
            _servidor.server_close()
        except Exception:
            pass
    _servidor = None
    with _candado:
        _permisos.clear()
    ajustes.fijar("celular", False)
