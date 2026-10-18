"""
micro.py
--------
Ubicacion: Arche/core/interfaz/micro.py

Enciende y apaga la escucha por microfono que Arché ya tiene (core/IA/voz.py:
"oye asistente ..."). Lo que oye entra por la misma puerta que lo que
escribes, asi que sale en el chat y en la consola como cualquier orden.

Los modulos de voz (sounddevice, faster-whisper) pesan, por eso solo se cargan
cuando prendes la escucha, y si faltan algo se avisa en vez de romper.
"""

import threading

from . import ajustes, en_vivo, entrada

_hilo = None
_parar = None


def activa():
    return _hilo is not None and _hilo.is_alive()


def _correr(parar):
    try:
        from core.IA import voz as oido
        en_vivo.avisar("Te escucho: di «oye asistente» y tu orden.", "info")
        oido.escuchar_continuo(lambda texto: entrada.enviar(texto, "voz"), detener_evento=parar)
    except Exception as e:
        en_vivo.avisar(f"No pude usar el micrófono ({str(e)[:70]}).", "error")
        ajustes.fijar("escucha", False)


def iniciar():
    global _hilo, _parar
    if activa():
        return True
    _parar = threading.Event()
    _hilo = threading.Thread(target=_correr, args=(_parar,), name="arche-escucha", daemon=True)
    _hilo.start()
    ajustes.fijar("escucha", True)
    return True


def detener():
    global _hilo
    if _parar is not None:
        _parar.set()
    ajustes.fijar("escucha", False)
    _hilo = None
    return True
