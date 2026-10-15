"""
en_vivo.py
----------
Ubicacion: Arche/core/interfaz/en_vivo.py

Lo que pasa "ahora" en Arché y que varias partes quieren ver: la conversacion,
que entendio de cada orden, si esta pensando, y los avisos cortos. La ventana y
la pagina del celular leen de aqui, asi ven lo mismo.
"""

import collections
import threading
import time

_lock = threading.Lock()
chat = collections.deque(maxlen=80)            # {"q": "tu"|"arche", "t": texto, "ts": hora}
intenciones = collections.deque(maxlen=12)     # {"cmd", "intencion", "via", "ts", "seg"}
_avisos = collections.deque(maxlen=20)         # [{"texto", "tipo", "ts"}]
ordenes = 0                                    # ordenes recibidas en esta sesion
ultima_orden = time.time()
pensando_desde = 0.0
_ultimo_arche = ""
_ts_orden = 0.0


def orden_recibida(texto, origen="consola"):
    global ordenes, ultima_orden, pensando_desde, _ts_orden
    with _lock:
        ordenes += 1
        ultima_orden = pensando_desde = _ts_orden = time.time()
        chat.append({"q": "tu", "t": str(texto), "ts": time.time(), "origen": origen})


def registrar_intencion(comando, intencion, via=""):
    with _lock:
        intenciones.append({"cmd": str(comando), "intencion": str(intencion), "via": str(via or ""),
                            "ts": time.time(), "seg": round(time.time() - _ts_orden, 2) if _ts_orden else 0.0})


def sondear():
    """Recoge el ultimo mensaje de Arché (core/voz.py lo guarda) y lo suma al chat sin repetirlo."""
    global _ultimo_arche, pensando_desde
    try:
        from core import voz
        txt = (voz.ultimo_mensaje() or "").replace("\n", " ").strip()
    except Exception:
        return
    if txt.lower().startswith(("arché:", "arche:")):
        txt = txt.split(":", 1)[1].strip()
    if txt and txt != _ultimo_arche:
        with _lock:
            _ultimo_arche = txt
            pensando_desde = 0.0
            chat.append({"q": "arche", "t": txt, "ts": time.time(), "origen": "arche"})


def esta_pensando(ahora=None):
    ahora = ahora or time.time()
    return bool(pensando_desde) and ahora - pensando_desde < 12


def estado_visual():
    """reposo | escuchando | pensando | hablando  (lo que muestran la esfera y la mascota)."""
    try:
        from core import voz
        if voz.hablando():
            return "hablando"
    except Exception:
        pass
    if esta_pensando():
        return "pensando"
    try:
        from . import ajustes, micro
        if ajustes.obtener("escucha") and micro.activa():
            return "escuchando"
    except Exception:
        pass
    return "reposo"


def avisar(texto, tipo="info"):
    """Aviso corto que la ventana muestra un momento (y la mascota comenta)."""
    with _lock:
        _avisos.append({"texto": str(texto), "tipo": tipo, "ts": time.time()})


def tomar_avisos():
    with _lock:
        sal = list(_avisos)
        _avisos.clear()
    return sal


def segundos_sin_actividad():
    return time.time() - ultima_orden


_instalado = False


def instalar():
    """Engancha las ordenes (entrada.py) y la intencion que detecta Arché (telemetria)."""
    global _instalado
    if _instalado:
        return
    _instalado = True
    try:
        from . import entrada
        entrada.al_recibir(lambda texto, origen: orden_recibida(texto, origen))
    except Exception:
        pass
    try:
        from core.IA import telemetria
        original = telemetria.registrar_comando

        def _con_aviso(comando, intencion, resuelto_por=""):
            try:
                registrar_intencion(comando, intencion, resuelto_por)
            except Exception:
                pass
            return original(comando, intencion, resuelto_por)

        telemetria.registrar_comando = _con_aviso
    except Exception:
        pass
