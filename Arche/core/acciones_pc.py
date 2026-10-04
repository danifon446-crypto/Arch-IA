"""
acciones_pc.py
--------------
Ubicacion: Arche/core/acciones_pc.py

El control "grande" del computador (Windows). Todo entra por UNA funcion,
manejar(comando), que main.py llama antes de caer al clasificador:

  VENTANAS   "pasa a chrome", "minimiza spotify", "maximiza word",
             "cierra discord", "pon chrome a la izquierda", "muestra el escritorio"
  SONIDO     "sube el volumen", "pon el volumen al 40", "silencia",
             "pausa la musica", "siguiente cancion", "cancion anterior"
  PANTALLA   "sube el brillo", "pon el brillo al 60", "toma una captura de pantalla"
  TECLADO    "teclea hola en bloc de notas", "presiona ctrl+t en chrome",
  Y MOUSE    "haz clic", "doble clic", "clic derecho", "baja la pagina"
  EQUIPO     "bloquea el pc", "apaga el pc", "reinicia el pc", "suspende el pc",
             "cancela el apagado", "cuanta bateria tengo"
  OTROS      "que hay en el portapapeles", "copia al portapapeles X",
             "abre la carpeta descargas", "espera 3 segundos"
  VARIOS     "abre chrome y luego busca gatos en youtube" (dividir_pasos)

Cada accion tiene su intencion en el catalogo (core/IA/catalogo.py, dominio
'computador'), asi que tambien se entiende en frases libres con las redes de
Arché ('modo natural on'): el enrutador las convierte en el comando de arriba.

Seguridad: apagar, reiniciar y cerrar sesion SIEMPRE piden confirmacion (y
apagar/reiniciar dan 30 segundos para arrepentirse). Cerrar un programa pide
confirmacion si tiene varias ventanas. Nunca cierra su propia terminal ni
toca procesos del sistema. Lo que teclea o presiona va a la ventana que
nombres, o a la que estabas usando antes de la terminal -- nunca a la
terminal de Arché.

Nada de esto necesita librerias extra: usa ctypes (user32) y PowerShell.
"""

import base64
import ctypes
import os
import re
import struct
import subprocess
import time

try:
    import psutil
except ImportError:
    psutil = None

from core import control_pc


# ------------------------------------------------------------------
# Utilidades de texto
# ------------------------------------------------------------------

def _msg(texto):
    print(f"Arché: {texto}")


def _norm(texto):
    return control_pc._normalizar(texto)


def _limpiar(comando):
    """Minúsculas, sin tildes, sin signos de pregunta/puntuación (deja + y %)."""
    texto = _norm(comando)
    texto = re.sub(r"[¿?¡!,.;:]", " ", texto)
    return " ".join(texto.split())


def _confirmar(pregunta):
    respuesta = _norm(control_pc._preguntar(f"Arché: {pregunta} (s/n)\nTú: "))
    return respuesta in ("s", "si")


def _solo_windows():
    """True (y avisa) si NO estamos en Windows."""
    if not control_pc.ES_WINDOWS:
        _msg("Eso solo lo sé hacer en Windows.")
        return True
    return False


# ------------------------------------------------------------------
# Teclas
# ------------------------------------------------------------------

# nombre -> (código virtual, es tecla "extendida")
TECLAS = {
    "ctrl": (0x11, False), "alt": (0x12, False), "shift": (0x10, False), "win": (0x5B, True),
    "enter": (0x0D, False), "esc": (0x1B, False), "tab": (0x09, False), "space": (0x20, False),
    "backspace": (0x08, False), "delete": (0x2E, True), "insert": (0x2D, True),
    "home": (0x24, True), "end": (0x23, True), "pageup": (0x21, True), "pagedown": (0x22, True),
    "left": (0x25, True), "up": (0x26, True), "right": (0x27, True), "down": (0x28, True),
    "printscreen": (0x2C, True), "capslock": (0x14, False),
    "volume_mute": (0xAD, True), "volume_down": (0xAE, True), "volume_up": (0xAF, True),
    "next": (0xB0, True), "prev": (0xB1, True), "play_pause": (0xB3, True),
}
for _i in range(1, 13):
    TECLAS[f"f{_i}"] = (0x6F + _i, False)

ALIAS_TECLAS = {
    "control": "ctrl", "ctl": "ctrl", "windows": "win", "inicio": "win", "super": "win",
    "mayus": "shift", "mayuscula": "shift", "mayusculas": "shift", "intro": "enter", "entrar": "enter",
    "retorno": "enter", "escape": "esc", "tabulador": "tab", "espacio": "space", "retroceso": "backspace",
    "suprimir": "delete", "supr": "delete", "del": "delete", "arriba": "up", "abajo": "down",
    "izquierda": "left", "derecha": "right", "repag": "pageup", "avpag": "pagedown",
    "inicio_pagina": "home", "fin": "end", "imprpant": "printscreen",
}


def parsear_atajo(texto):
    """'ctrl+shift+t' / 'control c' / 'alt tab' -> ['ctrl','shift','t'], o None
    si alguna tecla no se reconoce."""
    partes = [p for p in re.split(r"\s*\+\s*|\s+(?:mas|y)\s+|\s+", _norm(texto).strip()) if p]
    if not partes or len(partes) > 5:
        return None
    nombres = []
    for p in partes:
        p = ALIAS_TECLAS.get(p, p)
        if p in TECLAS or (len(p) == 1 and p.isalnum()):
            nombres.append(p)
        else:
            return None
    return nombres


def _vk(nombre):
    if nombre in TECLAS:
        return TECLAS[nombre]
    return ord(nombre.upper()), False


# ------------------------------------------------------------------
# Windows de bajo nivel (ctypes). TODO lo que toca el sistema está en
# funciones chicas con prefijo '_' para poder simularlas en las pruebas.
# ------------------------------------------------------------------

_USER32 = None


def _u32():
    """user32 con los tipos bien declarados (los HWND son punteros de 64 bits)."""
    global _USER32
    if _USER32 is None:
        c = ctypes
        u = c.windll.user32
        u.IsWindowVisible.argtypes = [c.c_void_p]
        u.IsWindowVisible.restype = c.c_int
        u.IsIconic.argtypes = [c.c_void_p]
        u.IsIconic.restype = c.c_int
        u.GetWindowTextLengthW.argtypes = [c.c_void_p]
        u.GetWindowTextLengthW.restype = c.c_int
        u.GetWindowTextW.argtypes = [c.c_void_p, c.c_wchar_p, c.c_int]
        u.GetWindowTextW.restype = c.c_int
        u.GetWindowThreadProcessId.argtypes = [c.c_void_p, c.POINTER(c.c_ulong)]
        u.GetWindowThreadProcessId.restype = c.c_ulong
        u.GetWindowLongW.argtypes = [c.c_void_p, c.c_int]
        u.GetWindowLongW.restype = c.c_long
        u.GetWindow.argtypes = [c.c_void_p, c.c_uint]
        u.GetWindow.restype = c.c_void_p
        u.ShowWindow.argtypes = [c.c_void_p, c.c_int]
        u.ShowWindow.restype = c.c_int
        u.SetForegroundWindow.argtypes = [c.c_void_p]
        u.SetForegroundWindow.restype = c.c_int
        u.BringWindowToTop.argtypes = [c.c_void_p]
        u.BringWindowToTop.restype = c.c_int
        u.PostMessageW.argtypes = [c.c_void_p, c.c_uint, c.c_size_t, c.c_ssize_t]
        u.PostMessageW.restype = c.c_int
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = c.c_void_p
        _USER32 = u
    return _USER32


# Tamaños fijos (DWORD = 32 bits) para que la estructura mida igual en cualquier sistema.
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class _UNION_INPUT(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _UNION_INPUT)]


KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x10


def _tecla(nombres):
    """Presiona una combinación (todas abajo, luego se sueltan al revés)."""
    pares = [_vk(n) for n in nombres]
    u = _u32()
    for vk, ext in pares:
        u.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY if ext else 0, 0)
    for vk, ext in reversed(pares):
        u.keybd_event(vk, 0, (KEYEVENTF_EXTENDEDKEY if ext else 0) | KEYEVENTF_KEYUP, 0)


def _escribir_texto(texto):
    """Teclea texto Unicode (tildes, ñ, emojis) con SendInput."""
    u = _u32()
    for caracter in texto:
        if caracter == "\n":
            _tecla(["enter"])
            continue
        unidades = struct.unpack(f"<{len(caracter.encode('utf-16-le')) // 2}H", caracter.encode("utf-16-le"))
        entradas = (_INPUT * (len(unidades) * 2))()
        for i, unidad in enumerate(unidades):
            for j, bandera in enumerate((KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
                e = entradas[i * 2 + j]
                e.type = 1  # INPUT_KEYBOARD
                e.ki.wVk = 0
                e.ki.wScan = unidad
                e.ki.dwFlags = bandera
        u.SendInput(len(entradas), entradas, ctypes.sizeof(_INPUT))
        time.sleep(0.005)


def _clic(boton="izquierdo", veces=1):
    """Clic en donde esté el puntero del mouse ahora."""
    u = _u32()
    abajo, arriba = (0x2, 0x4) if boton == "izquierdo" else (0x8, 0x10)
    for _ in range(veces):
        u.mouse_event(abajo, 0, 0, 0, 0)
        u.mouse_event(arriba, 0, 0, 0, 0)
        time.sleep(0.05)


def _pids_propios():
    """Mi proceso y todos sus padres (python -> shell -> terminal): sus
    ventanas son 'la terminal de Arché' y nunca son el destino de nada."""
    pids = {os.getpid()}
    if psutil is not None:
        try:
            pids |= {p.pid for p in psutil.Process().parents()}
        except Exception:
            pass
    return pids


def _ventanas_visibles():
    """
    [{hwnd, titulo, pid, exe, minimizada}] de las ventanas "de verdad" (las que
    salen en la barra de tareas), en orden de apilado: la de arriba primero.
    """
    u = _u32()
    resultado = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def _revisar(hwnd, _):
        try:
            if not u.IsWindowVisible(hwnd):
                return True
            largo = u.GetWindowTextLengthW(hwnd)
            if largo <= 0:
                return True
            estilo = u.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF  # GWL_EXSTYLE
            if (estilo & 0x80) and not (estilo & 0x40000):     # TOOLWINDOW sin APPWINDOW
                return True
            if u.GetWindow(hwnd, 4) and not (estilo & 0x40000):  # tiene dueño (diálogo/auxiliar)
                return True
            cloaked = ctypes.c_int(0)
            try:
                if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                        ctypes.c_void_p(hwnd), 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                    return True  # ventanas "fantasma" de apps UWP
            except Exception:
                pass
            buffer = ctypes.create_unicode_buffer(largo + 1)
            u.GetWindowTextW(hwnd, buffer, largo + 1)
            titulo = buffer.value
            if titulo.strip().lower() in ("program manager",):
                return True
            pid = ctypes.c_ulong(0)
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe = ""
            if psutil is not None:
                try:
                    exe = psutil.Process(pid.value).name().lower()
                except Exception:
                    pass
            resultado.append({"hwnd": hwnd, "titulo": titulo, "pid": pid.value,
                              "exe": exe, "minimizada": bool(u.IsIconic(hwnd))})
        except Exception:
            pass
        return True

    u.EnumWindows(enum_proc(_revisar), 0)
    return resultado


def _enfocar(hwnd):
    """Trae la ventana al frente (restaurándola si estaba minimizada).
    Windows suele bloquear que un programa "robe" el foco; apretar Alt un
    instante antes lo permite. Devuelve True si quedó al frente."""
    u = _u32()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, SW_RESTORE)
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
    u.BringWindowToTop(hwnd)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return u.GetForegroundWindow() == hwnd


def _mostrar_ventana(hwnd, modo):
    _u32().ShowWindow(hwnd, modo)


def _cerrar_ventana_hwnd(hwnd):
    """Cierre educado (como la X): si hay algo sin guardar, el programa pregunta."""
    _u32().PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _powershell(script, espera=30):
    """Corre un script de PowerShell. Devuelve (ok, salida_de_texto)."""
    codificado = base64.b64encode(
        ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;\n" + script).encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", codificado],
            capture_output=True, timeout=espera)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    salida = (r.stdout or b"").decode("utf-8", errors="replace").strip()
    error = (r.stderr or b"").decode("utf-8", errors="replace").strip()
    return r.returncode == 0, salida if r.returncode == 0 else (error or salida)


def _abrir_shell(destino):
    os.startfile(destino)  # 'shell:Downloads' etc. respeta carpetas movidas a OneDrive


def _bloquear_estacion():
    _u32().LockWorkStation()


def _ejecutar(argumentos):
    """subprocess.run con lo mínimo; devuelve el código de salida."""
    try:
        return subprocess.run(argumentos, capture_output=True).returncode
    except OSError:
        return 1


# ------------------------------------------------------------------
# Ventanas: buscar, elegir
# ------------------------------------------------------------------

ALIAS_VENTANAS = {
    "chrome": {"chrome.exe"}, "google chrome": {"chrome.exe"}, "edge": {"msedge.exe"},
    "microsoft edge": {"msedge.exe"}, "opera": {"opera.exe"}, "firefox": {"firefox.exe"},
    "brave": {"brave.exe"}, "vivaldi": {"vivaldi.exe"}, "navegador": {"chrome.exe", "msedge.exe", "opera.exe", "firefox.exe", "brave.exe", "vivaldi.exe"},
    "word": {"winword.exe"}, "excel": {"excel.exe"}, "powerpoint": {"powerpnt.exe"},
    "bloc de notas": {"notepad.exe"}, "bloc": {"notepad.exe"}, "notepad": {"notepad.exe"},
    "explorador": {"explorer.exe"}, "archivos": {"explorer.exe"}, "explorador de archivos": {"explorer.exe"},
    "terminal": {"windowsterminal.exe", "cmd.exe", "powershell.exe", "conhost.exe"},
    "visual studio code": {"code.exe"}, "vscode": {"code.exe"}, "vs code": {"code.exe"}, "code": {"code.exe"},
    "spotify": {"spotify.exe"}, "discord": {"discord.exe"}, "whatsapp": {"whatsapp.exe", "whatsapp.root.exe"},
    "teams": {"teams.exe", "ms-teams.exe"}, "zoom": {"zoom.exe"}, "vlc": {"vlc.exe"}, "steam": {"steam.exe"},
}

_ARTICULOS = {"el", "la", "los", "las", "mi", "mis", "un", "una", "ventana", "programa", "aplicacion", "app", "de", "del"}
_SIN_OBJETIVO = {"esto", "eso", "aqui", "actual", "esta", "este", "ahora"}
PROCESOS_PROTEGIDOS = {"system", "svchost", "csrss", "winlogon", "lsass", "wininit", "services", "smss",
                       "explorer", "dwm", "registry", "fontdrvhost", "python", "py", "pythonw"}


def _objetivo(x):
    """'la ventana de chrome' -> 'chrome'. None si no nombra nada ('esto', 'la ventana')."""
    if x is None:
        return None
    palabras = _limpiar(x).split()
    while palabras and palabras[0] in _ARTICULOS:
        palabras.pop(0)
    texto = " ".join(palabras).strip()
    if not texto or texto in _SIN_OBJETIVO:
        return None
    return texto


def buscar_ventanas(nombre, ventanas=None):
    """Ventanas que coinciden con `nombre` (título, programa o alias), en orden de apilado."""
    objetivo = _objetivo(nombre)
    if not objetivo:
        return []
    if ventanas is None:
        ventanas = _ventanas_visibles()
    exes = ALIAS_VENTANAS.get(objetivo, set())
    palabras = objetivo.split()
    coincidentes = []
    for v in ventanas:
        titulo = _norm(v["titulo"])
        programa = _norm(os.path.splitext(v["exe"])[0])
        if (objetivo in titulo or (programa and objetivo in programa) or v["exe"] in exes
                or all(p in titulo for p in palabras)):
            coincidentes.append(v)
    return coincidentes


def _ventana_por_defecto(ventanas=None):
    """La ventana que estabas usando antes de la terminal: la de más arriba que
    no es mía ni está minimizada."""
    if ventanas is None:
        ventanas = _ventanas_visibles()
    propios = _pids_propios()
    for v in ventanas:
        if v["pid"] not in propios and not v["minimizada"]:
            return v
    return None


def _describir(v):
    programa = os.path.splitext(v["exe"])[0] or "?"
    titulo = v["titulo"] if len(v["titulo"]) <= 60 else v["titulo"][:57] + "..."
    return f"{titulo} ({programa})"


def _elegir_ventana(coincidentes):
    """Si todas son del mismo programa usa la de arriba; si no, pregunta cuál."""
    if len({v["pid"] for v in coincidentes}) == 1 or len({v["exe"] for v in coincidentes}) == 1:
        return coincidentes[0]
    _msg("Encontré varias, ¿cuál?")
    mostradas = coincidentes[:8]
    for i, v in enumerate(mostradas, start=1):
        print(f"  {i}. {_describir(v)}")
    respuesta = _norm(control_pc._preguntar("Tú: "))
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(mostradas):
        return mostradas[int(respuesta) - 1]
    return None


def _resolver_destino(x, suave=False):
    """
    Devuelve (ventana, mensaje_de_error). Con nombre: la ventana que coincide.
    Sin nombre ('minimiza esto'): la que usabas antes de la terminal.
    """
    ventanas = _ventanas_visibles()
    objetivo = _objetivo(x)
    if objetivo is None:
        v = _ventana_por_defecto(ventanas)
        return (v, None) if v else (None, "No encuentro ninguna ventana abierta aparte de esta terminal.")
    coincidentes = buscar_ventanas(objetivo, ventanas)
    if not coincidentes:
        return None, f"No veo ninguna ventana de '{objetivo}' abierta."
    v = _elegir_ventana(coincidentes)
    return (v, None) if v else (None, "Cancelado.")


def listar_ventanas_texto(maximo=10):
    """Líneas de texto con las ventanas abiertas (sin la terminal de Arché)."""
    if not control_pc.ES_WINDOWS:
        return []
    try:
        propios = _pids_propios()
        ventanas = [v for v in _ventanas_visibles() if v["pid"] not in propios]
    except Exception:
        return []
    lineas = [f"Ventanas abiertas ({len(ventanas)}):"]
    for v in ventanas[:maximo]:
        lineas.append(f"  - {_describir(v)}" + (" [minimizada]" if v["minimizada"] else ""))
    if len(ventanas) > maximo:
        lineas.append(f"  ... y {len(ventanas) - maximo} más.")
    return lineas if ventanas else []


def imprimir_ventanas():
    for linea in listar_ventanas_texto():
        print(f"  {linea}")


# ------------------------------------------------------------------
# Acciones: ventanas
# ------------------------------------------------------------------

def _a_enfocar(d):
    v, error = _resolver_destino(d.get("x"))
    if v is None:
        return False  # suave: "ve a youtube" no es una ventana -> que siga el flujo normal
    _msg(f"Pasando a {_describir(v)}...")
    if not _enfocar(v["hwnd"]):
        _msg("No pude traerla al frente (a veces Windows lo bloquea). Prueba otra vez.")
    return True


def _a_minimizar(d):
    v, error = _resolver_destino(d.get("x"))
    if v is None:
        _msg(error)
        return True
    _mostrar_ventana(v["hwnd"], SW_MINIMIZE)
    _msg(f"Minimicé {_describir(v)}.")
    return True


def _a_maximizar(d):
    v, error = _resolver_destino(d.get("x"))
    if v is None:
        _msg(error)
        return True
    _mostrar_ventana(v["hwnd"], SW_MAXIMIZE)
    _enfocar(v["hwnd"])
    _msg(f"Maximicé {_describir(v)}.")
    return True


def _a_mostrar_escritorio(d):
    _tecla(["win", "d"])
    _msg("Listo, te muestro el escritorio.")
    return True


def _a_acomodar(d):
    v, error = _resolver_destino(d.get("x"))
    if v is None:
        return False  # suave
    lado = "left" if d.get("lado") == "izquierda" else "right"
    _enfocar(v["hwnd"])
    time.sleep(0.2)
    _tecla(["win", lado])
    _msg(f"Puse {_describir(v)} a la {d.get('lado')}.")
    return True


def _procesos_por_nombre(objetivo):
    """Procesos (psutil) cuyo programa se llama exactamente `objetivo` (o su alias)."""
    if psutil is None:
        return []
    exes = ALIAS_VENTANAS.get(objetivo, set())
    propios = _pids_propios()
    encontrados = []
    for p in psutil.process_iter(["name"]):
        try:
            nombre = (p.info.get("name") or "").lower()
            if p.pid in propios:
                continue
            if nombre in exes or os.path.splitext(nombre)[0] == objetivo.replace(" ", ""):
                encontrados.append(p)
        except Exception:
            continue
    return encontrados


def _a_cerrar(d):
    objetivo = _objetivo(d.get("x"))
    if objetivo is None:
        _msg("¿Cuál cierro? Dime por ejemplo 'cierra chrome'.")
        return True
    ventanas = _ventanas_visibles()
    coincidentes = buscar_ventanas(objetivo, ventanas)

    if not coincidentes:
        # sin ventana: puede ser un programa que vive en segundo plano
        procesos = [p for p in _procesos_por_nombre(objetivo)
                    if (p.info.get("name") or "").lower().rsplit(".", 1)[0] not in PROCESOS_PROTEGIDOS]
        if not procesos:
            _msg(f"No veo ninguna ventana ni programa de '{objetivo}' abierto.")
            return True
        if not _confirmar(f"'{objetivo}' no tiene ventana pero está corriendo ({len(procesos)} proceso/s). ¿Lo termino?"):
            _msg("Cancelado.")
            return True
        for p in procesos:
            try:
                p.terminate()
            except Exception:
                pass
        _msg(f"Terminé {objetivo}.")
        return True

    v = _elegir_ventana(coincidentes)
    if v is None:
        _msg("Cancelado.")
        return True
    if v["pid"] in _pids_propios():
        _msg("Esa es la terminal donde estoy corriendo; ciérrala tú si quieres.")
        return True
    del_programa = [w for w in coincidentes if w["pid"] == v["pid"]] or [v]
    if len(del_programa) > 1:
        if not _confirmar(f"{os.path.splitext(v['exe'])[0] or objetivo} tiene {len(del_programa)} ventanas abiertas. ¿Las cierro todas?"):
            _msg("Cancelado.")
            return True
    for w in del_programa:
        _cerrar_ventana_hwnd(w["hwnd"])
    _msg(f"Cerré {len(del_programa)} ventana(s) de {os.path.splitext(v['exe'])[0] or objetivo}.")
    return True


# ------------------------------------------------------------------
# Acciones: sonido y reproducción
# ------------------------------------------------------------------

def _pulsar_veces(tecla, veces):
    for _ in range(veces):
        _tecla([tecla])
        time.sleep(0.01)


def _porcentaje(d, por_defecto):
    if d.get("n"):
        return max(0, min(100, int(d["n"])))
    palabra = d.get("w")
    if palabra:
        return {"maximo": 100, "minimo": 0, "mitad": 50}[palabra]
    if "un poco" in d.get("t", ""):
        return 4
    return por_defecto


def _a_subir_volumen(d):
    pct = _porcentaje(d, 10)
    _pulsar_veces("volume_up", max(1, round(pct / 2)))  # cada pulsación = 2%
    _msg(f"Subí el volumen (~{pct}%).")
    return True


def _a_bajar_volumen(d):
    pct = _porcentaje(d, 10)
    _pulsar_veces("volume_down", max(1, round(pct / 2)))
    _msg(f"Bajé el volumen (~{pct}%).")
    return True


def _a_volumen_a(d):
    pct = _porcentaje(d, 50)
    _pulsar_veces("volume_down", 50)   # al fondo...
    _pulsar_veces("volume_up", round(pct / 2))  # ...y subo hasta donde pediste
    _msg(f"Dejé el volumen en ~{pct}%.")
    return True


def _a_silenciar(d):
    _tecla(["volume_mute"])
    _msg("Listo (alterné el silencio: si estaba sonando, ahora está en silencio, y al revés).")
    return True


def _a_pausar(d):
    _tecla(["play_pause"])
    _msg("Listo (pausa/reproducir).")
    return True


def _a_siguiente(d):
    _tecla(["next"])
    _msg("Siguiente canción.")
    return True


def _a_anterior(d):
    _tecla(["prev"])
    _msg("Canción anterior.")
    return True


# ------------------------------------------------------------------
# Acciones: pantalla (brillo, captura)
# ------------------------------------------------------------------

def _brillo_actual():
    ok, salida = _powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness")
    if ok and salida.strip().splitlines():
        try:
            return int(salida.strip().splitlines()[0])
        except ValueError:
            return None
    return None


def _poner_brillo(n):
    ok, _ = _powershell(
        "Invoke-CimMethod -InputObject (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods) "
        f"-MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={int(n)}}} | Out-Null")
    return ok


def _cambiar_brillo(d, signo):
    actual = _brillo_actual()
    if actual is None:
        _msg("No pude leer el brillo. Esto solo funciona con la pantalla del portátil (no con un monitor externo).")
        return True
    nuevo = max(0, min(100, actual + signo * _porcentaje(d, 20)))
    if _poner_brillo(nuevo):
        _msg(f"Brillo: {actual}% -> {nuevo}%.")
    else:
        _msg("No pude cambiar el brillo.")
    return True


def _a_subir_brillo(d):
    return _cambiar_brillo(d, +1)


def _a_bajar_brillo(d):
    return _cambiar_brillo(d, -1)


def _a_brillo_a(d):
    n = _porcentaje(d, 50)
    if _poner_brillo(n):
        _msg(f"Dejé el brillo en {n}%.")
    else:
        _msg("No pude cambiar el brillo. Esto solo funciona con la pantalla del portátil (no con un monitor externo).")
    return True


_SCRIPT_CAPTURA = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System.Runtime.InteropServices;
public class DpiAware { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
"@
[DpiAware]::SetProcessDPIAware() | Out-Null
$carpeta = Join-Path ([Environment]::GetFolderPath('MyPictures')) 'Capturas de Arche'
New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
$ruta = Join-Path $carpeta ('captura ' + (Get-Date -Format 'yyyy-MM-dd HH-mm-ss') + '.png')
$pantalla = [System.Windows.Forms.SystemInformation]::VirtualScreen
$imagen = New-Object System.Drawing.Bitmap $pantalla.Width, $pantalla.Height
$g = [System.Drawing.Graphics]::FromImage($imagen)
$g.CopyFromScreen($pantalla.Left, $pantalla.Top, 0, 0, $imagen.Size)
$imagen.Save($ruta, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $imagen.Dispose()
Write-Output $ruta
"""


def _a_captura(d):
    _msg("Tomando la captura...")
    ok, salida = _powershell(_SCRIPT_CAPTURA)
    lineas = [l for l in salida.splitlines() if l.strip()]
    if ok and lineas:
        _msg(f"Listo, la guardé en: {lineas[-1]}")
    else:
        _msg(f"No pude tomar la captura ({salida[:120] or 'sin detalle'}).")
    return True


# ------------------------------------------------------------------
# Acciones: teclado y mouse
# ------------------------------------------------------------------

def _preparar_destino(nombre_ventana):
    """Enfoca la ventana nombrada (o la que usabas antes de la terminal).
    Devuelve la ventana, o None (y avisa) si no hay a dónde mandar las teclas."""
    ventanas = _ventanas_visibles()
    if nombre_ventana:
        coincidentes = buscar_ventanas(nombre_ventana, ventanas)
        v = _elegir_ventana(coincidentes) if coincidentes else None
    else:
        v = _ventana_por_defecto(ventanas)
    if v is None:
        _msg("No encuentro la ventana donde mandarlo. Dime a cuál, por ejemplo 'teclea hola en bloc de notas'.")
        return None
    if not _enfocar(v["hwnd"]):
        _msg("No pude pasar a esa ventana (Windows a veces lo bloquea); no mandé nada.")
        return None
    time.sleep(0.3)
    return v


def _separar_destino(x, es_valido_el_resto):
    """'hola en bloc de notas' -> ('hola', 'bloc de notas') solo si lo de la
    derecha es una ventana abierta y lo de la izquierda es válido."""
    if " en " in x:
        izquierda, _, derecha = x.rpartition(" en ")
        if izquierda.strip() and es_valido_el_resto(izquierda) and buscar_ventanas(derecha):
            return izquierda.strip(), derecha.strip()
    return x.strip(), None


def _a_teclear(d):
    texto, destino = _separar_destino(d.get("x", ""), lambda s: True)
    if not texto:
        _msg("¿Qué quieres que teclee?")
        return True
    if len(texto) > 500:
        _msg("Es demasiado texto para teclearlo (máximo 500 caracteres).")
        return True
    v = _preparar_destino(destino)
    if v is None:
        return True
    _msg(f"Tecleando en {_describir(v)}...")
    _escribir_texto(texto)
    return True


def _a_presionar(d):
    atajo_texto, destino = _separar_destino(d.get("x", ""), lambda s: parsear_atajo(s) is not None)
    teclas = parsear_atajo(atajo_texto)
    if teclas is None:
        _msg(f"No reconozco esa tecla: '{atajo_texto}'. Prueba con cosas como enter, esc, ctrl+c, alt+tab, f5.")
        return True
    v = _preparar_destino(destino)
    if v is None:
        return True
    _tecla(teclas)
    _msg(f"Presioné {'+'.join(teclas)} en {_describir(v)}.")
    return True


def _a_clic(d):
    _clic("izquierdo", 1)
    _msg("Clic (donde está el puntero del mouse).")
    return True


def _a_clic_derecho(d):
    _clic("derecho", 1)
    _msg("Clic derecho (donde está el puntero del mouse).")
    return True


def _a_doble_clic(d):
    _clic("izquierdo", 2)
    _msg("Doble clic (donde está el puntero del mouse).")
    return True


def _desplazar(tecla, texto):
    v = _preparar_destino(None)
    if v is None:
        return True
    _tecla([tecla])
    _msg(f"{texto} en {_describir(v)}.")
    return True


def _a_desplazar_abajo(d):
    return _desplazar("pagedown", "Bajé una página")


def _a_desplazar_arriba(d):
    return _desplazar("pageup", "Subí una página")


# ------------------------------------------------------------------
# Acciones: el equipo
# ------------------------------------------------------------------

def _a_bloquear(d):
    _msg("Bloqueando el equipo...")
    _bloquear_estacion()
    return True


def _programar(que, banderas, ya):
    if not _confirmar(f"¿Seguro que {que} el equipo?"):
        _msg("Cancelado, no toqué nada.")
        return True
    codigo = _ejecutar(["shutdown", *banderas, "/t", "30"])
    if codigo == 0:
        _msg(f"Listo, {ya} en 30 segundos. Si te arrepientes, dime 'cancela el apagado'.")
    else:
        _msg("No pude programarlo (¿ya hay uno programado? prueba 'cancela el apagado').")
    return True


def _a_apagar(d):
    return _programar("apago", ["/s"], "se apaga")


def _a_reiniciar(d):
    return _programar("reinicio", ["/r"], "se reinicia")


def _a_cerrar_sesion(d):
    if not _confirmar("¿Seguro que cierro tu sesión de Windows? Lo que no hayas guardado se puede perder."):
        _msg("Cancelado, no toqué nada.")
        return True
    _ejecutar(["shutdown", "/l"])
    return True


def _a_suspender(d):
    _msg("Suspendiendo el equipo...")
    _ejecutar(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return True


def _a_cancelar_apagado(d):
    if _ejecutar(["shutdown", "/a"]) == 0:
        _msg("Listo, cancelé el apagado/reinicio.")
    else:
        _msg("No había ningún apagado ni reinicio programado.")
    return True


def _a_bateria(d):
    bateria = psutil.sensors_battery() if psutil is not None else None
    if bateria is None:
        _msg("Este equipo no reporta batería (¿es de escritorio?).")
        return True
    cargando = "conectado al cargador" if bateria.power_plugged else "con batería"
    texto = f"Tienes {bateria.percent:.0f}% de batería, {cargando}."
    if not bateria.power_plugged and isinstance(bateria.secsleft, (int, float)) and bateria.secsleft > 0:
        horas, resto = divmod(int(bateria.secsleft), 3600)
        texto += f" Te quedan unos {horas} h {resto // 60} min."
    _msg(texto)
    return True


def _a_ver_portapapeles(d):
    ok, salida = _powershell("Get-Clipboard -Raw")
    if not ok:
        _msg("No pude leer el portapapeles.")
    elif not salida.strip():
        _msg("El portapapeles está vacío (o tiene algo que no es texto).")
    else:
        _msg("En el portapapeles tienes:")
        print(salida[:500] + ("..." if len(salida) > 500 else ""))
    return True


def _a_copiar_portapapeles(d):
    texto = d.get("x", "").strip()
    if not texto:
        _msg("¿Qué copio?")
        return True
    codificado = base64.b64encode(texto.encode("utf-8")).decode("ascii")
    ok, _ = _powershell(
        f"Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{codificado}')))")
    _msg("Copiado al portapapeles." if ok else "No pude copiar al portapapeles.")
    return True


CARPETAS = {
    "descargas": "shell:Downloads", "escritorio": "shell:Desktop", "documentos": "shell:Personal",
    "imagenes": "shell:My Pictures", "fotos": "shell:My Pictures", "musica": "shell:My Music",
    "videos": "shell:My Video",
}


def _a_abrir_carpeta(d):
    nombre = d.get("x", "")
    destino = CARPETAS.get(nombre)
    if destino is None:
        _msg(f"No conozco la carpeta '{nombre}'. Las que sé: {', '.join(sorted(set(CARPETAS)))}.")
        return True
    try:
        _abrir_shell(destino)
        _msg(f"Abrí tu carpeta de {nombre}.")
    except OSError as e:
        _msg(f"No pude abrirla ({e}).")
    return True


def _a_esperar(d):
    segundos = max(0, min(60, int(d.get("n") or 1)))
    time.sleep(segundos)
    return True


def _a_listar_ventanas(d):
    lineas = listar_ventanas_texto(maximo=30)
    if lineas:
        for linea in lineas:
            print(f"Arché: {linea}" if linea is lineas[0] else linea)
    else:
        _msg("No veo ventanas abiertas.")
    return True


# ------------------------------------------------------------------
# Interpretar: frase -> (intención, datos)
# ------------------------------------------------------------------

_EQ = r"(?:pc|computador|computadora|compu|equipo|portatil|laptop|ordenador)"
_SIGN = r"(?:volumen|sonido)"

# (intención, regex, usa_texto_original). El ORDEN importa: lo más específico primero.
_REGLAS = [
    ("esperar", r"^(?:espera|esperar|aguarda|aguardar)\s+(?P<n>\d{1,2})\s*(?:s|seg|segs|segundos?)?$", False),

    # sonido
    ("volumen_a", rf"^(?:(?:(?:pon|ponme|pone|ajusta|deja|cambia|fija|coloca)\s+)?(?:el\s+)?{_SIGN}\s+(?:a|al|en|a\s+la)"
                  rf"|(?:sube|baja)\s+(?:el\s+)?{_SIGN}\s+(?:a|al|a\s+la))\s+"
                  r"(?:(?P<n>\d{1,3})\s*(?:%|por\s*ciento)?|(?P<w>maximo|minimo|mitad))$", False),
    ("subir_volumen", rf"^(?:(?:sube|subele|aumenta|incrementa)(?:\s+un\s+poco)?(?:\s+(?:el|al))?\s+{_SIGN}"
                      r"(?:\s+(?:en\s+)?(?P<n>\d{1,3}))?(?:\s+un\s+poco)?" rf"|mas\s+{_SIGN})$", False),
    ("bajar_volumen", rf"^(?:(?:baja|bajale|disminuye|reduce)(?:\s+un\s+poco)?(?:\s+(?:el|al))?\s+{_SIGN}"
                      r"(?:\s+(?:en\s+)?(?P<n>\d{1,3}))?(?:\s+un\s+poco)?" rf"|menos\s+{_SIGN})$", False),
    ("silenciar", rf"^(?:silencia|silenciar|mutea|mutear|silencio|quita\s+el\s+sonido|pon(?:lo)?\s+en\s+silencio|"
                  rf"activa\s+el\s+sonido|desactiva\s+el\s+silencio|quita\s+el\s+silencio)(?:\s+(?:el\s+)?(?:sonido|volumen|{_EQ}))?$", False),
    ("siguiente_cancion", r"^(?:(?:pasa|salta|cambia|pon)\s+(?:a\s+)?(?:la\s+)?(?:siguiente|proxima)\s+(?:cancion|tema|pista)"
                          r"|(?:siguiente|proxima)\s+(?:cancion|tema|pista)|next|salta\s+(?:esta|la)\s+(?:cancion|tema|pista)"
                          r"|cambia\s+de\s+(?:cancion|tema|pista))$", False),
    ("cancion_anterior", r"^(?:(?:pon|regresa|vuelve\s+a)\s+(?:la\s+)?(?:cancion|tema|pista)\s+anterior"
                         r"|(?:cancion|tema|pista)\s+anterior|previous|regresa\s+(?:la\s+)?(?:cancion|tema|pista))$", False),
    ("pausar_reproducir", r"^(?:pausa|pausar|pon\s+pausa|dale\s+(?:play|pausa)|play|reanuda|reanudar|continua|continuar|"
                          r"reproduce|reproducir)(?:\s+(?:la|el)\s+(?:musica|cancion|video|reproduccion|pelicula))?$", False),

    # pantalla
    ("brillo_a", r"^(?:(?:(?:pon|ponme|pone|ajusta|deja|cambia|fija|coloca)\s+)?(?:el\s+)?brillo\s+(?:a|al|en|a\s+la)"
                 r"|(?:sube|baja)\s+(?:el\s+)?brillo\s+(?:a|al|a\s+la))\s+"
                 r"(?:(?P<n>\d{1,3})\s*(?:%|por\s*ciento)?|(?P<w>maximo|minimo|mitad))$", False),
    ("subir_brillo", r"^(?:(?:sube|subele|aumenta|incrementa)(?:\s+un\s+poco)?(?:\s+(?:el|al))?\s+brillo(?:\s+(?:en\s+)?(?P<n>\d{1,3}))?"
                     r"(?:\s+un\s+poco)?|mas\s+brillo)$", False),
    ("bajar_brillo", r"^(?:(?:baja|bajale|disminuye|reduce)(?:\s+un\s+poco)?(?:\s+(?:el|al))?\s+brillo(?:\s+(?:en\s+)?(?P<n>\d{1,3}))?"
                     r"(?:\s+un\s+poco)?|menos\s+brillo)$", False),
    ("captura_pantalla", r"^(?:(?:toma|tomar|haz|hacer|hazme|saca|sacar|guarda|guardar)\s+(?:una\s+)?)?"
                         r"(?:captura(?:\s+de(?:\s+la)?\s+pantalla)?|screenshot|pantallazo)$|^captura\s+(?:la\s+)?pantalla$", False),
    ("mostrar_escritorio", r"^(?:minimiza|minimizar|oculta|esconde)\s+(?:todo|todas\s+las\s+ventanas)$"
                           r"|^(?:muestra|mostrar|ver|ve\s+al|ir\s+al)\s+(?:el\s+)?escritorio$|^despeja\s+(?:la\s+)?pantalla$", False),

    # equipo
    ("cerrar_sesion", r"^(?:cierra|cerrar)\s+(?:(?:la|mi)\s+)?sesion(?:\s+de\s+windows)?$", False),
    ("cancelar_apagado", r"^(?:cancela|cancelar|deten|detener|aborta|abortar)\s+(?:el\s+)?(?:apagado|reinicio)$"
                         r"|^no\s+apagues(?:\s+el\s+\w+)?$", False),
    ("bloquear_pc", rf"^(?:bloquea|bloquear)(?:\s+(?:el|la|mi))?(?:\s+(?:pantalla|sesion|{_EQ}))?$", False),
    ("apagar_pc", rf"^(?:apaga|apagar)\s+(?:(?:el|la|mi)\s+)?(?:{_EQ}|todo)$", False),
    ("reiniciar_pc", rf"^(?:reinicia|reiniciar)\s+(?:(?:el|la|mi)\s+)?(?:{_EQ}|todo)$", False),
    ("suspender_pc", rf"^(?:suspende|suspender|duerme|dormir|hiberna|hibernar)\s+(?:(?:el|la|mi)\s+)?{_EQ}$", False),
    ("ver_bateria", r"^(?:cuanta\s+bateria\s+(?:tengo|me\s+queda|queda)|como\s+esta\s+la\s+bateria|estado\s+de\s+la\s+bateria"
                    r"|nivel\s+de\s+(?:la\s+)?bateria|bateria)$", False),
    ("ver_portapapeles", r"^(?:que\s+hay\s+en\s+el\s+portapapeles|muestra\s+el\s+portapapeles|lee\s+el\s+portapapeles|portapapeles)$", False),
    ("copiar_portapapeles", r"^copia(?:r)?\s+(?:al|en\s+el)\s+portapapeles\s*:?\s*(?P<x>.+)$", True),
    ("copiar_portapapeles", r"^copia(?:r)?\s+(?P<x>.+?)\s+al\s+portapapeles$", True),
    ("abrir_carpeta", r"^(?:abre|abrir|muestra|mostrar|muestrame|quiero\s+ver)\s+(?:(?:la|el|mi|mis|los|las)\s+)?"
                      r"(?:carpeta\s+(?:de\s+)?(?:(?:mi|mis|los|las)\s+)?)?"
                      r"(?P<x>descargas|escritorio|documentos|imagenes|fotos|musica|videos)$", False),
    ("listar_ventanas", r"^(?:mis\s+ventanas|ventanas|lista\s+de\s+ventanas|que\s+ventanas\s+hay|lista\s+las\s+ventanas)$", False),

    # teclado y mouse
    ("teclear_texto", r"^(?:teclea|tipea|digita|escribe\s+por\s+mi)\s+(?P<x>.+)$", True),
    ("presionar_tecla", r"^(?:presiona|pulsa|oprime|aprieta|manda)\s+(?:(?:la|las|el)\s+(?:tecla|teclas|atajo)\s+)?(?P<x>.+)$", False),
    ("doble_clic", r"^(?:(?:haz|da|hazme|dame)\s+)?(?:un\s+)?doble\s+cl(?:ic|ick)(?:\s+aqui)?$|^cl(?:ic|ick)\s+doble$", False),
    ("clic_derecho", r"^(?:(?:haz|da|hazme|dame)\s+)?(?:un\s+)?cl(?:ic|ick)\s+derecho(?:\s+aqui)?$|^boton\s+derecho(?:\s+del\s+mouse)?$", False),
    ("hacer_clic", r"^(?:(?:haz|da|hazme|dame)\s+)?(?:un\s+)?cl(?:ic|ick)(?:\s+izquierdo)?(?:\s+aqui)?$", False),
    ("desplazar_abajo", r"^(?:baja|bajar|desplaza|desplazar|avanza|avanzar)\s+(?:la\s+)?(?:pagina|pantalla)(?:\s+hacia\s+abajo)?$"
                        r"|^(?:desplaza\s+hacia\s+abajo|scroll\s+abajo|pagina\s+siguiente)$", False),
    ("desplazar_arriba", r"^(?:sube|subir|retrocede)\s+(?:la\s+)?(?:pagina|pantalla)(?:\s+hacia\s+arriba)?$"
                         r"|^(?:desplaza\s+hacia\s+arriba|scroll\s+arriba|pagina\s+anterior)$", False),

    # ventanas (con nombre)
    ("acomodar_ventana", r"^(?:acomoda|ubica|ancla|pon|ponme|pega|mueve)\s+(?P<x>.+?)\s+a\s+la\s+(?P<lado>izquierda|derecha)$", False),
    ("maximizar_ventana", r"^(?:maximiza|maximizar|agranda|expande)\s+(?P<x>.+)$", False),
    ("maximizar_ventana", r"^pon\s+(?P<x>.+?)\s+en\s+pantalla\s+completa$", False),
    ("minimizar_ventana", r"^(?:minimiza|minimizar|oculta|esconde|manda\s+a\s+la\s+barra)\s+(?P<x>.+)$", False),
    ("cerrar_ventana", r"^(?:cierra|cerrar|termina|terminar)\s+(?P<x>.+)$", False),
    ("enfocar_ventana", r"^(?:pasa|cambia|salta|ve|vuelve|regresa|ir)\s+(?:a|al|a\s+la)\s+(?:la\s+ventana\s+(?:de\s+)?)?(?P<x>.+)$", False),
    ("enfocar_ventana", r"^(?:enfoca|enfocar|trae|activa|selecciona|muestrame|muestra)\s+(?:la\s+ventana\s+(?:de\s+)?)?(?P<x>.+?)(?:\s+al\s+frente)?$", False),
]
_REGLAS = [(id_, re.compile(patron, re.IGNORECASE), original) for id_, patron, original in _REGLAS]

ACCIONES = {
    "esperar": _a_esperar,
    "listar_ventanas": _a_listar_ventanas,
    "subir_volumen": _a_subir_volumen, "bajar_volumen": _a_bajar_volumen, "volumen_a": _a_volumen_a,
    "silenciar": _a_silenciar, "pausar_reproducir": _a_pausar,
    "siguiente_cancion": _a_siguiente, "cancion_anterior": _a_anterior,
    "subir_brillo": _a_subir_brillo, "bajar_brillo": _a_bajar_brillo, "brillo_a": _a_brillo_a,
    "captura_pantalla": _a_captura, "mostrar_escritorio": _a_mostrar_escritorio,
    "enfocar_ventana": _a_enfocar, "minimizar_ventana": _a_minimizar, "maximizar_ventana": _a_maximizar,
    "cerrar_ventana": _a_cerrar, "acomodar_ventana": _a_acomodar,
    "teclear_texto": _a_teclear, "presionar_tecla": _a_presionar,
    "hacer_clic": _a_clic, "clic_derecho": _a_clic_derecho, "doble_clic": _a_doble_clic,
    "desplazar_abajo": _a_desplazar_abajo, "desplazar_arriba": _a_desplazar_arriba,
    "bloquear_pc": _a_bloquear, "apagar_pc": _a_apagar, "reiniciar_pc": _a_reiniciar,
    "cerrar_sesion": _a_cerrar_sesion, "suspender_pc": _a_suspender, "cancelar_apagado": _a_cancelar_apagado,
    "ver_bateria": _a_bateria, "ver_portapapeles": _a_ver_portapapeles, "copiar_portapapeles": _a_copiar_portapapeles,
    "abrir_carpeta": _a_abrir_carpeta,
}

# Si no hay ventana con ese nombre, NO es para mí: que siga el flujo normal
# ("ve a youtube" debe abrir YouTube, no quejarse de que no hay una ventana).
SUAVES = {"enfocar_ventana", "acomodar_ventana"}
# Estas funcionan en cualquier sistema; el resto necesita Windows.
SIN_WINDOWS = {"esperar", "ver_bateria"}


def interpretar(comando):
    """(intención, datos) o None. `datos` trae x/n/w/lado, 't' (frase limpia) y
    'contenido' (lo que se aprende en las redes)."""
    limpio = _limpiar(comando)
    original = " ".join((comando or "").strip().split())
    if not limpio:
        return None
    for id_, regex, usa_original in _REGLAS:
        m = regex.match(original if usa_original else limpio)
        if m:
            datos = {k: v for k, v in m.groupdict().items() if v is not None}
            datos["t"] = limpio
            datos["contenido"] = datos.get("x") or datos.get("n") or datos.get("w") or ""
            return id_, datos
    return None


def manejar(comando):
    """
    Si `comando` es una acción del PC, la ejecuta y devuelve (intención, contenido).
    Si no lo es -- o es una orden "suave" (pasa a / pon X a la izquierda) que no
    nombra una ventana abierta -- devuelve None y main.py sigue con su flujo.
    """
    interpretado = interpretar(comando)
    if interpretado is None:
        return None
    intencion, datos = interpretado

    if intencion not in SIN_WINDOWS and not control_pc.ES_WINDOWS:
        if intencion in SUAVES:
            return None
        _solo_windows()
        return intencion, datos["contenido"]

    try:
        resultado = ACCIONES[intencion](datos)
    except Exception as e:  # una acción que falla nunca debe tirar abajo a Arché
        _msg(f"No pude hacerlo ({type(e).__name__}: {e}).")
        return intencion, datos["contenido"]
    if resultado is False and intencion in SUAVES:
        return None
    return intencion, datos["contenido"]


# ------------------------------------------------------------------
# Varios pasos: "abre chrome y luego busca gatos en youtube"
# ------------------------------------------------------------------

_RE_CONECTORES = re.compile(r"\s*;\s*|\s+(?:y\s+(?:luego|despues|después|entonces)|luego|despues|después|entonces)\s+", re.IGNORECASE)
VERBOS_DE_PASO = {
    "abre", "abrir", "busca", "buscame", "buscar", "sube", "baja", "pon", "ponme", "minimiza", "maximiza",
    "cierra", "teclea", "presiona", "pulsa", "captura", "toma", "haz", "silencia", "pausa", "reproduce",
    "bloquea", "espera", "pasa", "cambia", "enfoca", "trae", "ve", "copia", "acomoda", "muestra",
    "apaga", "reinicia", "suspende", "aprende", "usa", "salta", "siguiente", "play", "next", "mutea",
}


def dividir_pasos(comando):
    """['abre chrome', 'busca gatos en youtube'] si la frase encadena VARIOS
    pasos con 'y luego' / 'después' / ';' y cada pedazo empieza como una orden;
    si no, [comando]. (Así 'crea una nota X y luego Y' no se parte por error.)"""
    partes = [p.strip() for p in _RE_CONECTORES.split(comando or "") if p and p.strip()]
    if len(partes) < 2:
        return [comando]
    for parte in partes:
        primera = _limpiar(parte).split(" ")[0] if _limpiar(parte) else ""
        if primera not in VERBOS_DE_PASO:
            return [comando]
    return partes