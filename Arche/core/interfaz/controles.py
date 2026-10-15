"""
controles.py
------------
Ubicacion: Arche/core/interfaz/controles.py

Lo que se puede prender y apagar desde la ventana (y verse en vivo). Cada
control lee su estado REAL de Arché y, al tocarlo, manda a Arché la misma
orden que escribirias a mano ("activa la voz", "detener examen automatico"...).
Asi nada se hace por un camino distinto y la consola muestra lo que pasa.

Para agregar uno nuevo basta con sumarlo a CONTROLES.
"""

import time


def _voz():
    from core import voz
    on = bool(voz.activa())
    return on, ("hablando ahora" if voz.hablando() else ("lee en voz alta lo que digo" if on else "solo texto")), bool(voz.hablando())


def _mejora():
    from core import mejora_continua as m
    n = m.nivel()
    trabajando = bool(getattr(m, "_trabajando", False))
    detalle = "mejorándose ahora" if trabajando else {"apagada": "no hace nada sola", "datos": "aprende y se limpia cuando no la usas",
                                                       "completa": "además revisa su código (informa, no cambia)"}.get(n, n)
    return n, detalle, trabajando


def _autonomia():
    from core import autonomia as a
    n = a.nivel()
    return n, {"apagada": "sin avisos ni iniciativa", "avisos": "te avisa lo que nota",
               "proactiva": "además hace lo seguro por ti"}.get(n, n), False


def _nube():
    from core.IA import aprender_de_nube as a
    on = bool(a.activo())
    return on, ("aprende intenciones y datos de la nube" if on else "no aprende de la nube"), False


def _examen():
    from . import datos
    ex = datos.examen()
    on = bool(ex.get("automatico"))
    return on, (f"nivel {ex.get('nivel', 0)} · {ex.get('listos', 0)}/{len(ex.get('dominios', []))} listos" if on
                else "se examina cuando lo activas"), on


def _estudio():
    from core.IA import estudio
    e = estudio._cargar_estado() or {}
    on = bool(e.get("corriendo")) and (time.time() - e.get("actualizado_ts", 0)) < estudio._UMBRAL_DESACTUALIZADO_SEG
    return on, ("estudiando temas en segundo plano" if on else "no está estudiando"), on


def _interfaz():
    from core import interfaz
    on = bool(interfaz.automatica())
    return on, ("esta ventana se abre al iniciar" if on else "la abres tú con 'abre la interfaz'"), False


def _escucha():
    from . import ajustes, micro
    on = bool(ajustes.obtener("escucha")) and micro.activa()
    return on, ("te oye: di «oye asistente» y tu orden" if on else "no usa el micrófono"), False


def _celular():
    from . import ajustes, remoto
    on = remoto.activo()
    return on, (f"{remoto.direccion()}  PIN {ajustes.obtener('celular_pin')}" if on else "controlarme desde el celular"), False


# tipo "switch": valor True/False.  tipo "niveles": valor = nombre del nivel.
CONTROLES = [
    {"id": "voz", "nombre": "Voz", "tipo": "switch", "leer": _voz,
     "on": "activa la voz", "off": "desactiva la voz"},
    {"id": "mejora", "nombre": "Piloto de mejora", "tipo": "niveles", "leer": _mejora,
     "niveles": [("apagada", "nivel de mejora apagada"), ("datos", "nivel de mejora datos"),
                 ("completa", "nivel de mejora completa")]},
    {"id": "autonomia", "nombre": "Autonomía", "tipo": "niveles", "leer": _autonomia,
     "niveles": [("apagada", "nivel de autonomia apagada"), ("avisos", "nivel de autonomia avisos"),
                 ("proactiva", "nivel de autonomia proactiva")]},
    {"id": "nube", "nombre": "Aprender de la nube", "tipo": "switch", "leer": _nube,
     "on": "activa el aprendizaje de la nube", "off": "desactiva el aprendizaje de la nube"},
    {"id": "examen", "nombre": "Examen automático", "tipo": "switch", "leer": _examen,
     "on": "iniciar examen automatico", "off": "detener examen automatico"},
    {"id": "estudio", "nombre": "Estudio automático", "tipo": "switch", "leer": _estudio,
     "on": "iniciar estudio automatico", "off": "detener estudio"},
    {"id": "escucha", "nombre": "Escuchar (micrófono)", "tipo": "switch", "leer": _escucha,
     "on": "activa la escucha", "off": "desactiva la escucha"},
    {"id": "celular", "nombre": "Control por celular", "tipo": "switch", "leer": _celular,
     "on": "activa el control del celular", "off": "desactiva el control del celular"},
    {"id": "interfaz", "nombre": "Ventana al iniciar", "tipo": "switch", "leer": _interfaz,
     "on": "activa la interfaz automatica", "off": "desactiva la interfaz automatica"},
]


def leer():
    """Estado real de cada control: [{id, nombre, tipo, valor, detalle, trabajando, ...}]."""
    salida = []
    for c in CONTROLES:
        try:
            valor, detalle, trabajando = c["leer"]()
        except Exception:
            valor, detalle, trabajando = None, "sin datos", False
        item = {k: c[k] for k in c if k != "leer"}
        item.update(valor=valor, detalle=detalle, trabajando=trabajando)
        salida.append(item)
    return salida
