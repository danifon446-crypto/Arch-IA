"""
ritmo.py
--------
Ubicacion: Arche/core/raphael/ritmo.py

Arché aprende TU RITMO: a qué hora sueles empezar y terminar el día con el PC
(entre semana y fines de semana por separado), para darte las cosas en el
momento justo en vez de a una hora fija.

De dónde aprende (sin leer nada privado, solo HORAS):
  * cada orden que le das a Arché (main.py llama registrar()),
  * cada 5 minutos mira si estás usando el PC (teclado/mouse, con la función
    GetLastInputInfo de Windows). No mira QUÉ haces, solo SI estás.

Con eso sabe:
  * presente()            -> si estás frente al PC ahora
  * minutos_inactivo()    -> cuánto llevas sin tocarlo
  * inicio_habitual()     -> mediana de la hora en que empiezas (últimos 21 días)
  * fin_habitual()        -> mediana de la hora en que terminas
  * momento_para('matutino' | 'nocturno')

Con menos de 3 días aprendidos usa: empezar 7:00 entre semana / 9:00 fin de semana,
terminar 22:00. Si prefieres una hora fija: «dame las noticias a las 7» (o «a las 6:30»).
"""

import ctypes
import os
import statistics
import threading
import time
from datetime import timedelta

from core.raphael import comun

ARCH = comun.ruta("ritmo.json")
DIAS_GUARDADOS = 35
DIAS_PARA_APRENDER = 21
MINIMO_DIAS = 3
MINUTOS_PRESENTE = 5

_lock = threading.Lock()
_ultima_orden = {"cuando": 0.0}


# ------------------------------------------------------------------
# Registro
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("dias", {})
    e.setdefault("entregas", {})        # {"matutino": "2026-11-15", "nocturno": "..."}
    e.setdefault("hora_fija", {})       # {"matutino": "07:00"}
    return e


def _guardar(e):
    dias = sorted(e["dias"])
    for viejo in dias[:-DIAS_GUARDADOS]:
        e["dias"].pop(viejo, None)
    comun.guardar(ARCH, e)


def _dia_logico(momento):
    """Lo que haces a las 2 a.m. cuenta como parte del día anterior."""
    return (momento - timedelta(hours=4)).strftime("%Y-%m-%d")


def _minutos_del_dia(momento):
    """Minutos desde medianoche; lo de madrugada (antes de las 4) cuenta como 24h+."""
    m = momento.hour * 60 + momento.minute
    return m + 24 * 60 if momento.hour < 4 else m


def anotar_actividad(momento=None):
    momento = momento or comun.ahora()
    clave = _dia_logico(momento)
    minutos = _minutos_del_dia(momento)
    with _lock:
        e = _estado()
        d = e["dias"].setdefault(clave, {"primera": minutos, "ultima": minutos, "muestras": 0,
                                         "finde": momento.weekday() >= 5 if momento.hour >= 4
                                         else (momento - timedelta(days=1)).weekday() >= 5})
        d["primera"] = min(d["primera"], minutos)
        d["ultima"] = max(d["ultima"], minutos)
        d["muestras"] = int(d.get("muestras", 0)) + 1
        _guardar(e)


def registrar(comando=None):
    """main.py la llama con cada orden."""
    _ultima_orden["cuando"] = time.time()
    try:
        anotar_actividad()
    except Exception:
        pass


# ------------------------------------------------------------------
# ¿Estás?
# ------------------------------------------------------------------

def _segundos_sin_tocar_pc():
    """Segundos desde la última tecla/movimiento de mouse (solo Windows). None si no se puede saber."""
    if os.name != "nt":
        return None
    try:
        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    except Exception:
        return None


def minutos_inactivo():
    sin_pc = _segundos_sin_tocar_pc()
    sin_orden = time.time() - _ultima_orden["cuando"] if _ultima_orden["cuando"] else None
    valores = [v for v in (sin_pc, sin_orden) if v is not None]
    if not valores:
        return 0.0
    return min(valores) / 60.0


def presente():
    return minutos_inactivo() < MINUTOS_PRESENTE


def muestrear():
    """Cada pocos minutos: si estás usando el PC, cuenta como actividad de hoy."""
    if presente():
        anotar_actividad()


# ------------------------------------------------------------------
# Lo aprendido
# ------------------------------------------------------------------

def _dias_recientes(finde):
    e = _estado()
    limite = (comun.ahora() - timedelta(days=DIAS_PARA_APRENDER)).strftime("%Y-%m-%d")
    hoy = _dia_logico(comun.ahora())
    return [d for k, d in e["dias"].items() if limite <= k < hoy and bool(d.get("finde")) == finde
            and int(d.get("muestras", 0)) >= 2]


def _mediana(valores):
    return int(statistics.median(valores)) if valores else None


def inicio_habitual(momento=None):
    """Minutos desde medianoche."""
    momento = momento or comun.ahora()
    finde = momento.weekday() >= 5
    dias = _dias_recientes(finde)
    if len(dias) < MINIMO_DIAS:
        return 9 * 60 if finde else 7 * 60
    # lo de "primera" < 4:00 viene de trasnochar del día anterior: no cuenta como inicio
    return _mediana([d["primera"] for d in dias if d["primera"] >= 4 * 60]) or 7 * 60


def fin_habitual(momento=None):
    momento = momento or comun.ahora()
    finde = momento.weekday() >= 5
    dias = _dias_recientes(finde)
    if len(dias) < MINIMO_DIAS:
        return 22 * 60
    return _mediana([d["ultima"] for d in dias]) or 22 * 60


def aprendido():
    e = _estado()
    return len([d for d in e["dias"].values() if int(d.get("muestras", 0)) >= 2])


def _hhmm(minutos):
    minutos = int(minutos) % (24 * 60)
    h, m = divmod(minutos, 60)
    return f"{h}:{m:02d}"


def describir():
    hoy = comun.ahora()
    entre = hoy if hoy.weekday() < 5 else hoy - timedelta(days=hoy.weekday() - 4)
    finde = hoy if hoy.weekday() >= 5 else hoy + timedelta(days=5 - hoy.weekday())
    n = aprendido()
    e = _estado()
    fijas = e.get("hora_fija", {})
    texto = (f"Llevo {n} día(s) aprendiendo tu ritmo. "
             f"Entre semana sueles empezar ~{_hhmm(inicio_habitual(entre))} y terminar ~{_hhmm(fin_habitual(entre))}; "
             f"el fin de semana ~{_hhmm(inicio_habitual(finde))} y ~{_hhmm(fin_habitual(finde))}.")
    if n < MINIMO_DIAS:
        texto += f" (Todavía uso horas por defecto: necesito {MINIMO_DIAS} días.)"
    if fijas.get("matutino"):
        texto += f" Las noticias te las doy a hora fija: {fijas['matutino']}."
    if fijas.get("nocturno"):
        texto += f" El resumen de la noche, a las {fijas['nocturno']}."
    return texto


# ------------------------------------------------------------------
# ¿Es el momento?
# ------------------------------------------------------------------

def ya_entregado(tipo, momento=None):
    momento = momento or comun.ahora()
    return _estado()["entregas"].get(tipo) == _dia_logico(momento)


def marcar_entregado(tipo, momento=None):
    momento = momento or comun.ahora()
    with _lock:
        e = _estado()
        e["entregas"][tipo] = _dia_logico(momento)
        _guardar(e)


def fijar_hora(tipo, hhmm):
    with _lock:
        e = _estado()
        if hhmm:
            e["hora_fija"][tipo] = hhmm
        else:
            e["hora_fija"].pop(tipo, None)
        _guardar(e)


def _hora_fija(tipo):
    v = _estado()["hora_fija"].get(tipo)
    if not v:
        return None
    h, m = (v.split(":") + ["0"])[:2]
    return int(h) * 60 + int(m)


def momento_para(tipo, momento=None, esta_presente=None):
    """
    'matutino': la primera vez que estés en el PC desde ~30 min antes de tu hora habitual de empezar
                (nunca antes de las 5:00). Si ese día no apareces hasta tarde, igual te lo da al llegar
                (hasta las 15:00).
    'nocturno': cuando estés en el PC desde ~30 min antes de tu hora habitual de terminar
                (nunca antes de las 19:00).
    """
    momento = momento or comun.ahora()
    if ya_entregado(tipo, momento):
        return False
    esta = presente() if esta_presente is None else esta_presente
    if not esta:
        return False
    ahora_min = _minutos_del_dia(momento)
    fija = _hora_fija(tipo)
    if tipo == "matutino":
        desde = fija if fija is not None else max(5 * 60, inicio_habitual(momento) - 30)
        return desde <= ahora_min <= 15 * 60
    if tipo == "nocturno":
        desde = fija if fija is not None else max(19 * 60, fin_habitual(momento) - 30)
        return ahora_min >= desde
    return False
