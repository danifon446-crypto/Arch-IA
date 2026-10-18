"""
sonido.py
---------
Ubicacion: Arche/core/interfaz/sonido.py

Sonidos cortitos de la interfaz (solo Windows, con winsound). Apagados por
defecto: se prenden en AJUSTES. Nunca bloquean ni rompen nada.
"""

import threading

from . import ajustes

try:
    import winsound
except Exception:
    winsound = None

_TONOS = {
    "activar": ((660, 60), (880, 80)),
    "apagar": ((880, 60), (520, 90)),
    "aviso": ((784, 70), (1046, 110)),
    "clic": ((700, 30),),
}


def tocar(nombre):
    if winsound is None or not ajustes.obtener("sonidos") or nombre not in _TONOS:
        return

    def _t():
        try:
            for hz, ms in _TONOS[nombre]:
                winsound.Beep(hz, ms)
        except Exception:
            pass
    threading.Thread(target=_t, daemon=True).start()
