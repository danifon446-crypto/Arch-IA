"""
rendimiento.py
--------------
Ubicacion: Arche/core/interfaz/rendimiento.py

Modo de alto rendimiento: aligera la interfaz sin tocar las funciones del
asistente. Apaga fondos animados, escenas, particulas, transiciones y efectos
caros, baja los cuadros por segundo y hace que los widgets se actualicen
menos.

  - "ahorro": lo aplicas tu.
  - "auto": Arché mide cuanto tarda cada cuadro; si la interfaz va lenta, te
    PROPONE el modo ahorro (nunca lo activa sin preguntarte).
  - Todo lo que cambia el modo ahorro se recuerda: «revertir ahorro» lo deja
    exactamente como estaba.
"""

import collections
import time

from . import ajustes

# lo que se aligera en modo ahorro: ajuste -> valor
AHORRO = {
    "fluidez": "ahorro", "fondo_movimiento": False, "escena": "ninguna", "efecto_particulas": 0,
    "efecto_profundidad": False, "efecto_sombra": 0, "efecto_borde_luminoso": 0, "anim_transiciones": False,
    "fondo_desenfoque": 0, "mascota_reacciones": False, "sistema_actualizacion": 3,
}

_previos = None          # lo que habia antes de aplicar el ahorro
_tiempos = collections.deque(maxlen=90)
_ultimo_aviso = 0.0
_propuesta = False


def activo():
    return _previos is not None


def aplicar():
    """Activa el modo ahorro. Devuelve que cambio."""
    global _previos
    if _previos is not None:
        return {}
    _previos = {k: ajustes.obtener(k) for k in AHORRO}
    cambios = {}
    for k, v in AHORRO.items():
        if ajustes.obtener(k) != v:
            cambios[k] = v
            ajustes.fijar(k, v)
    ajustes.fijar("rendimiento", "ahorro")
    return cambios


def revertir():
    """Deja todo como estaba antes del ahorro. Devuelve True si habia algo que revertir."""
    global _previos
    if _previos is None:
        ajustes.fijar("rendimiento", "normal")
        return False
    for k, v in _previos.items():
        ajustes.fijar(k, v)
    _previos = None
    ajustes.fijar("rendimiento", "normal")
    return True


def medir(segundos_cuadro, intervalo_objetivo):
    """La ventana llama esto en cada cuadro con lo que tardo en dibujarlo."""
    _tiempos.append(segundos_cuadro / max(0.001, intervalo_objetivo))


def conviene_proponer():
    """True una sola vez si en el modo 'auto' la interfaz va claramente lenta."""
    global _ultimo_aviso, _propuesta
    if ajustes.obtener("rendimiento") != "auto" or not ajustes.obtener("rend_sugerir") or activo() or _propuesta:
        return False
    if len(_tiempos) < 60:
        return False
    media = sum(_tiempos) / len(_tiempos)
    if media > 1.15 and time.time() - _ultimo_aviso > 600:
        _ultimo_aviso = time.time()
        _propuesta = True
        return True
    return False


def olvidar_propuesta():
    global _propuesta
    _propuesta = False


def descripcion_ahorro():
    return ", ".join(f"{k}={v}" for k, v in AHORRO.items())
