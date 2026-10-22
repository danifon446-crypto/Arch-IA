"""
canales.py
----------
Por dónde le llegan mensajes a Arché y por dónde responde.

Hasta ahora Arché solo escuchaba la consola (input) y solo respondía en ella
(print). Este módulo deja que otros canales (hoy WhatsApp; mañana Telegram,
la ventana, etc.) le manden mensajes SIN tocar el resto del código:

  - sys.stdin se reemplaza por una cola. Cada input() de Arché (el del bucle
    principal y también los de confirmación) recibe el siguiente mensaje que
    llegue, venga de la consola o de otro canal.
  - sys.stdout se reemplaza por un "espejo": todo sigue saliendo por la
    consola igual que siempre, y si el mensaje en curso vino de otro canal,
    lo que Arché imprima en el hilo principal se junta y se le devuelve a
    esa persona por ese mismo canal.

Si la interfaz ya instaló su "puerta de entrada" (core/interfaz/entrada.py, la que
junta consola y ventana), los mensajes de otros canales entran POR ESA puerta
(entrada.enviar). Si no, se usa un reemplazo propio de sys.stdin.
La voz de Arché (core/voz.py, que envuelve print e input) sigue funcionando igual.

Para agregar un canal nuevo basta con:
    canales.registrar_canal("telegram", enviar)     # enviar(destino, texto)
    canales.poner("telegram", destino, "texto")     # cuando llegue un mensaje
"""

import io
import queue
import re
import sys
import threading

_cola = queue.Queue()
_enviadores = {}
_estado = {"canal": "consola", "destino": None, "buffer": [], "instalado": False, "hilo_principal": None, "via_entrada": False}
_candado = threading.Lock()

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROMPT_FINAL = re.compile(r"\s*T[uú]:\s*$")
_PREFIJO = re.compile(r"(?m)^\s*Arch[eé]:\s?")


def registrar_canal(nombre, enviar):
    """enviar(destino, texto) lo llama Arché para devolver la respuesta por ese canal."""
    _enviadores[nombre] = enviar


def poner(canal, destino, texto):
    """Un canal avisa que llegó un mensaje: Arché lo procesa como si lo hubieran escrito."""
    if _estado["via_entrada"]:
        _entrada().enviar(texto, origen=f"{canal}:{destino}")
    else:
        _cola.put((canal, destino, texto))


def _entrada():
    """El módulo entrada de la interfaz, solo si ya está cargado (no lo importamos nosotros)."""
    return sys.modules.get("core.interfaz.entrada")


def _al_recibir(texto, origen):
    """La puerta de entrada nos avisa de cada orden que Arché va a procesar y de dónde vino."""
    with _candado:
        _estado["buffer"] = []
        if ":" in origen and origen.split(":", 1)[0] in _enviadores:
            _estado["canal"], _estado["destino"] = origen.split(":", 1)
        else:
            _estado["canal"], _estado["destino"] = "consola", None


def _limpiar_para_canal(texto):
    texto = _ANSI.sub("", texto)
    texto = _PROMPT_FINAL.sub("", texto)
    texto = _PREFIJO.sub("", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _volcar():
    """Manda a su canal lo que Arché imprimió mientras procesaba el mensaje anterior."""
    with _candado:
        canal, destino = _estado["canal"], _estado["destino"]
        texto = "".join(_estado["buffer"])
        _estado["buffer"] = []
    if canal == "consola":
        return
    enviar = _enviadores.get(canal)
    if not enviar:
        return
    texto = _limpiar_para_canal(texto) or "Hecho."
    try:
        enviar(destino, texto)
    except Exception as e:
        try:
            sys.__stdout__.write(f"Arché: (no pude responder por {canal}: {e})\n")
        except Exception:
            pass


class _Entrada(io.TextIOBase):
    """Reemplaza a sys.stdin: entrega el siguiente mensaje de la cola."""

    def readline(self, size=-1):
        _volcar()
        canal, destino, texto = _cola.get()
        if texto is None:               # fin de la entrada de consola (Ctrl+Z / Ctrl+D)
            _estado["canal"], _estado["destino"] = "consola", None
            return ""
        _estado["canal"], _estado["destino"] = canal, destino
        return texto + "\n"

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation("fileno")

    def readable(self):
        return True


class _Salida:
    """Reemplaza a sys.stdout: todo sale por la consola y, si toca, también se junta para el canal."""

    def __init__(self, real):
        self._real = real

    def write(self, texto):
        n = self._real.write(texto)
        if _estado["canal"] != "consola" and threading.get_ident() == _estado["hilo_principal"]:
            _estado["buffer"].append(texto)
            # el prompt "Tú: " significa que Arché terminó de responder y espera lo siguiente
            if _PROMPT_FINAL.search(texto):
                _volcar()
        return n

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass

    def __getattr__(self, nombre):      # isatty, encoding, reconfigure, fileno...
        return getattr(self._real, nombre)


def _leer_consola():
    real = sys.__stdin__
    while True:
        try:
            linea = real.readline()
        except Exception:
            linea = ""
        if linea == "":
            _cola.put(("consola", None, None))
            return
        _cola.put(("consola", None, linea.rstrip("\r\n")))


def instalar():
    """Se llama una vez, justo antes del bucle principal de main.py. Idempotente."""
    if _estado["instalado"]:
        return
    _estado["hilo_principal"] = threading.get_ident()
    sys.stdout = _Salida(sys.stdout)
    entrada = _entrada()
    if entrada is not None and getattr(entrada, "_instalada", False):
        _estado["via_entrada"] = True
        entrada.al_recibir(_al_recibir)
    else:
        sys.stdin = _Entrada()
        threading.Thread(target=_leer_consola, name="canal-consola", daemon=True).start()
    _estado["instalado"] = True