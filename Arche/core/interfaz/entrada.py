"""
entrada.py
----------
Ubicacion: Arche/core/interfaz/entrada.py

Una sola "puerta de entrada" para lo que le dices a Arché: lo que escribes en
la consola Y lo que escribes (o los botones que tocas) en la ventana llegan a
la misma cola, y input() las entrega en orden. Asi main.py no cambia y todo
lo que Arché pregunta (confirmaciones, etc.) tambien se puede contestar
desde la ventana.

Seguridad: si algo falla al instalarla, input() queda como estaba.
Para apagarla: pon  {"entrada_ventana": false}  en core/interfaz/config.json
"""

import atexit
import builtins
import os
import queue
import sys
import threading

_cola = queue.Queue()
_oyentes = []                    # funciones que quieren enterarse de cada orden (la ventana)
_input_real = None
_lector = None
_lector_vivo = False
_instalada = False


def al_recibir(funcion):
    _oyentes.append(funcion)


def _avisar(texto, origen):
    for f in list(_oyentes):
        try:
            f(texto, origen)
        except Exception:
            pass


def enviar(texto, origen="ventana"):
    """Manda una orden a Arché como si la hubieras escrito en la consola."""
    texto = str(texto).strip()
    if texto:
        _cola.put((origen, texto))


def _leer_consola():
    global _lector_vivo
    try:
        while True:
            linea = _input_real("")
            _cola.put(("consola", linea))
    except (EOFError, OSError, ValueError):
        pass
    finally:
        _lector_vivo = False


def _ventana_abierta():
    try:
        from . import ventana
        return ventana.abierta()
    except Exception:
        return False


def _input_unificado(prompt=""):
    global _lector, _lector_vivo
    if prompt:
        sys.stdout.write(str(prompt))
        sys.stdout.flush()
    if _lector is None or (not _lector.is_alive() and _lector_vivo):
        _lector_vivo = True
        _lector = threading.Thread(target=_leer_consola, name="arche-entrada", daemon=True)
        _lector.start()
    while True:
        try:
            origen, texto = _cola.get(timeout=0.2)
        except queue.Empty:
            # sin consola (stdin cerrado) y sin ventana: no quedarse esperando para siempre
            if not _lector_vivo and not _ventana_abierta() and _cola.empty():
                raise EOFError
            continue
        if origen != "consola":
            sys.stdout.write(texto + "\n")        # que la consola muestre lo que mandaste desde la ventana
            sys.stdout.flush()
        _avisar(texto, origen)
        return texto


def _salir_sin_trabarse():
    """Al cerrar Arché, el hilo que espera la consola sigue dentro de input() y Python 3.12
    se queja ("Fatal Python error ... stdin") al apagarse. Cerramos limpio a mano."""
    if _lector is not None and _lector.is_alive():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)


def instalar():
    """Cambia input() por la version unificada (idempotente)."""
    global _input_real, _instalada
    if _instalada:
        return True
    try:
        voz = None
        real = None
        try:
            from core import voz as _voz          # voz.py envuelve input() para leer las preguntas en voz alta
            voz, real = _voz, _voz._input_original
        except Exception:
            pass
        if real is None:
            real = builtins.input
        if real is _input_unificado:
            return True
        _input_real = real
        if voz is not None:
            voz._input_original = _input_unificado      # la voz ahora envuelve a la entrada unificada
        if voz is None or builtins.input is not voz._input_con_voz:
            builtins.input = _input_unificado
        _instalada = True
        atexit.register(_salir_sin_trabarse)
        return True
    except Exception:
        return False
