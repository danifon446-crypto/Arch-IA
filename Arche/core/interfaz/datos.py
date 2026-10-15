"""
datos.py
--------
Ubicacion: Arche/core/interfaz/datos.py

Junta en un solo diccionario lo que muestran la consola y la ventana:
estado del equipo, voz, nube, red neuronal y progreso del examen. Todo
esta protegido con try/except: si algo falla, ese dato simplemente queda
vacio y la interfaz sigue funcionando (nunca debe tumbar a Arché).
"""

import json
import os
import time

_BASE_IA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "IA")
_ARCHIVO_EXAMEN = os.path.join(_BASE_IA, "examen_progreso.json")

# lo que cuesta mas (leer disco, cargar el modelo) se guarda unos segundos
_cache = {}


def _con_cache(clave, segundos, funcion):
    ahora = time.time()
    previo = _cache.get(clave)
    if previo and ahora - previo[0] < segundos:
        return previo[1]
    try:
        valor = funcion()
    except Exception:
        valor = previo[1] if previo else None
    _cache[clave] = (ahora, valor)
    return valor


def equipo():
    """CPU, RAM, disco y bateria."""
    try:
        import psutil
    except Exception:
        return {}
    d = {}
    try:
        d["cpu"] = float(psutil.cpu_percent(interval=None))
        d["ram"] = float(psutil.virtual_memory().percent)
        d["disco"] = float(psutil.disk_usage(os.path.abspath(os.sep)).percent)
        b = psutil.sensors_battery()
        if b is not None:
            d["bateria"] = float(b.percent)
            d["enchufado"] = bool(b.power_plugged)
    except Exception:
        pass
    return d


def voz():
    try:
        from core import voz as v
        return {"activa": bool(v.activa()), "hablando": bool(v.hablando()),
                "ultimo": (v.ultimo_mensaje() or "")}
    except Exception:
        return {"activa": False, "hablando": False, "ultimo": ""}


def nube():
    def _leer():
        from core.IA import nube as n
        return {"modo": n.modo(), "proveedor": n.proveedor(), "modelo": n.modelo(),
                "configurada": bool(n.configurada())}
    return _con_cache("nube", 5, _leer) or {}


def red():
    def _leer():
        from core.IA.clasificador import info_modelo
        i = info_modelo() or {}
        return {"activo": bool(i.get("activo")), "precision": float(i.get("precision", 0.0)),
                "ejemplos": int(i.get("num_ejemplos", 0)), "intenciones": len(i.get("clases", []))}
    return _con_cache("red", 15, _leer) or {"activo": False}


def redes():
    """Todas las redes neuronales: la general y las de cada dominio (precision, ejemplos, clases)."""
    def _leer():
        from core.IA.clasificador_jerarquico import info_jerarquico
        sal = []
        for nombre, i in (info_jerarquico() or {}).items():
            nombre = "general (dominios)" if nombre == "dominio" else nombre
            sal.append({"nombre": nombre, "activa": bool(i.get("activo")), "trivial": bool(i.get("trivial")),
                        "precision": float(i.get("precision", 0.0)), "ejemplos": int(i.get("n_ejemplos", 0)),
                        "clases": len(i.get("clases", []))})
        return sal
    return _con_cache("redes", 20, _leer) or []


def examen():
    def _leer():
        with open(_ARCHIVO_EXAMEN, "r", encoding="utf-8") as f:
            p = json.load(f)
        try:
            from core.IA.examen import UMBRAL_RACHA
        except Exception:
            UMBRAL_RACHA = 4
        doms = []
        for nombre, info in (p.get("dominios") or {}).items():
            doms.append({"nombre": nombre, "racha": int(info.get("racha", 0)),
                         "listo": bool(info.get("listo"))})
        doms.sort(key=lambda x: (not x["listo"], -x["racha"], x["nombre"]))
        auto = bool(p.get("automatico_corriendo"))
        if auto and time.time() - float(p.get("automatico_actualizado_ts", 0)) > 600:
            auto = False   # se corto sin avisar
        return {"nivel": int(p.get("nivel_grupal", 1)), "umbral": UMBRAL_RACHA,
                "automatico": auto, "dominios": doms,
                "listos": sum(1 for x in doms if x["listo"])}
    return _con_cache("examen", 4, _leer) or {"dominios": [], "nivel": 0, "umbral": 4,
                                              "automatico": False, "listos": 0}


def procesos():
    def _leer():
        from . import procesos as p
        return p.listar()
    return _con_cache("procesos", 1.5, _leer) or []


def controles():
    def _leer():
        from . import controles as c
        return c.leer()
    return _con_cache("controles", 1.0, _leer) or []


def hoy():
    """Lo ultimo que hizo el piloto de mejora y las proximas alarmas."""
    def _leer():
        out = {"mejora": [], "alarmas": []}
        try:
            from core import mejora_continua as m
            for h in (m._cargar().get("historial") or [])[-4:]:
                out["mejora"].append((h.get("t", 0), h.get("texto", "")))
        except Exception:
            pass
        try:
            from core import alarmas
            for a in alarmas.pendientes()[:3]:
                out["alarmas"].append((a.get("cuando", ""), a.get("texto", "")))
        except Exception:
            pass
        return out
    return _con_cache("hoy", 5, _leer) or {"mejora": [], "alarmas": []}


def instantanea():
    return {"equipo": equipo(), "voz": voz(), "nube": nube(), "red": red(), "redes": redes(), "examen": examen(),
            "procesos": procesos(), "controles": controles(), "hoy": hoy()}
