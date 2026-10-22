"""
estado_visual.py
----------------
Ubicacion: Arche/core/interfaz/estado_visual.py

Historial visual y recuperacion de configuraciones.

  - deshacer / rehacer de cualquier cambio de aspecto (ajustes, temas, distribucion, perfil)
  - puntos de restauracion con nombre (y automaticos antes de cambios grandes)
  - comparar dos configuraciones
  - copias de seguridad exportables / importables (validadas antes de aplicarse)
  - sincronizacion opcional por una carpeta (OneDrive, Dropbox, un pendrive...), sin servicios externos

Una "captura" es todo el aspecto: ajustes visuales, temas propios, perfiles y distribucion.
"""

import collections
import json
import os
import re
import threading
import time

from . import ajustes, layout, perfiles, tema

_PUNTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "puntos.json")
_lock = threading.RLock()
_deshacer = collections.deque(maxlen=60)
_rehacer = collections.deque(maxlen=60)
_MAX_AUTO = 15


def capturar(volcar=True):
    return {"v": 1, "ts": time.time(), "ajustes": ajustes.captura(), "temas": tema.todos_los_propios(),
            "perfiles": perfiles.todo(volcar), "activo": perfiles.activo()}


def empujar(captura, motivo=""):
    """Guarda una captura tomada ANTES de un cambio, solo si el cambio ocurrio de verdad."""
    with _lock:
        if _firma(captura) == _firma(capturar(False)):
            return False
        if _deshacer and _firma(_deshacer[-1][1]) == _firma(captura):
            return False
        _deshacer.append((motivo, captura))
        _rehacer.clear()
        return True


def _firma(c):
    return json.dumps({k: c[k] for k in ("ajustes", "temas", "perfiles", "activo")}, sort_keys=True, default=str)


def aplicar(c):
    """Restaura una captura. Devuelve cuantos ajustes cambiaron."""
    with _lock:
        tema.reemplazar_propios(c.get("temas"))
        perfiles.reemplazar_todo(c.get("perfiles"))
        n = ajustes.aplicar_captura(c.get("ajustes"))
        ajustes.fijar("perfil", perfiles.activo())
        perfiles.marcar_sucio()
        tema.aplicar(ajustes.obtener("tema"))
        return n


# ------------------------------------------------------------------ deshacer / rehacer
def punto_de_control(motivo=""):
    """Llamar justo ANTES de un cambio. Asi 'deshacer' vuelve a este estado."""
    with _lock:
        c = capturar()
        if _deshacer and _firma(_deshacer[-1][1]) == _firma(c):
            return False
        _deshacer.append((motivo, c))
        _rehacer.clear()
        return True


def puede_deshacer():
    return bool(_deshacer)


def puede_rehacer():
    return bool(_rehacer)


def deshacer():
    with _lock:
        if not _deshacer:
            return False, "no hay nada que deshacer"
        motivo, previo = _deshacer.pop()
        _rehacer.append((motivo, capturar()))
        aplicar(previo)
        return True, "deshice" + (f": {motivo}" if motivo else "")


def rehacer():
    with _lock:
        if not _rehacer:
            return False, "no hay nada que rehacer"
        motivo, sig = _rehacer.pop()
        _deshacer.append((motivo, capturar()))
        aplicar(sig)
        return True, "rehice" + (f": {motivo}" if motivo else "")


def layout_anterior():
    """Vuelve a la ultima distribucion distinta de la actual (sin tocar los demas ajustes)."""
    with _lock:
        actual = json.dumps(perfiles.layout_actual(), sort_keys=True)
        for motivo, c in reversed(_deshacer):
            p = (c.get("perfiles") or {}).get("perfiles", {}).get(c.get("activo"), {})
            lay = p.get("layout")
            if lay and json.dumps(layout.validar(lay), sort_keys=True) != actual and c.get("activo") == perfiles.activo():
                punto_de_control("recuperar distribución anterior")
                perfiles.poner_layout(lay)
                return True, "recuperé tu distribución anterior"
        return False, "no tengo una distribución anterior distinta de la actual en esta sesión (prueba con un punto de restauración)"


# ------------------------------------------------------------------ puntos de restauracion
def _leer_puntos():
    try:
        with open(_PUNTOS, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _guardar_puntos(lista):
    try:
        tmp = _PUNTOS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False)
        os.replace(tmp, _PUNTOS)
    except Exception:
        pass


def crear_punto(nombre="", auto=False):
    nombre = re.sub(r"\s+", " ", str(nombre)).strip()[:40] or time.strftime("%d/%m %H:%M")
    with _lock:
        lista = _leer_puntos()
        if not auto:
            lista = [p for p in lista if p["nombre"].lower() != nombre.lower()]
        lista.append({"nombre": nombre, "auto": bool(auto), "ts": time.time(), "captura": capturar()})
        autos = [p for p in lista if p["auto"]]
        for viejo in autos[:-_MAX_AUTO]:
            lista.remove(viejo)
        _guardar_puntos(lista)
    return nombre


def listar_puntos():
    """[(nombre, auto, ts)] del mas nuevo al mas viejo."""
    return [(p["nombre"], p["auto"], p["ts"]) for p in reversed(_leer_puntos())]


def _buscar_punto(nombre):
    lista = _leer_puntos()
    n = str(nombre).strip().lower()
    if n in ("ultimo", "ultima", "anterior", "previo", "previa") and lista:
        return lista[-1]
    for p in reversed(lista):
        if p["nombre"].lower() == n:
            return p
    for p in reversed(lista):
        if n and n in p["nombre"].lower():
            return p
    return None


def restaurar_punto(nombre):
    p = _buscar_punto(nombre)
    if p is None:
        return False, f"no encuentro un punto de restauración «{nombre}»"
    punto_de_control("restaurar «" + p["nombre"] + "»")
    aplicar(_validada(p["captura"]))
    return True, f"restauré «{p['nombre']}»"


def borrar_punto(nombre):
    p = _buscar_punto(nombre)
    if p is None:
        return False, "no encuentro ese punto"
    lista = [q for q in _leer_puntos() if q is not p and not (q["ts"] == p["ts"] and q["nombre"] == p["nombre"])]
    _guardar_puntos(lista)
    return True, f"borré «{p['nombre']}»"


def _validada(c):
    """Deja solo lo que se entiende de una captura (por si vino de fuera o esta danada)."""
    if not isinstance(c, dict):
        return {"ajustes": {}, "temas": {}, "perfiles": {}}
    sal = {"ajustes": {}, "temas": c.get("temas") if isinstance(c.get("temas"), dict) else {},
           "perfiles": c.get("perfiles") if isinstance(c.get("perfiles"), dict) else {}}
    for k, v in (c.get("ajustes") or {}).items():
        if k in ajustes.claves_visuales():
            ok, limpio = ajustes.validar(k, v)
            if ok:
                sal["ajustes"][k] = limpio
    return sal


def comparar(a, b="actual"):
    """Frases con lo que cambia entre dos puntos (o un punto y lo actual)."""
    def _cap(x):
        if str(x).lower() in ("actual", "ahora", "hoy"):
            return "actual", capturar()
        p = _buscar_punto(x)
        return (p["nombre"], p["captura"]) if p else (None, None)
    na, ca = _cap(a)
    nb, cb = _cap(b)
    if ca is None or cb is None:
        return None
    sal = []
    for k in sorted(set(ca["ajustes"]) | set(cb["ajustes"])):
        va, vb = ca["ajustes"].get(k), cb["ajustes"].get(k)
        if va != vb:
            sal.append(f"{k}: {_corto(va)} → {_corto(vb)}")
    if ca.get("activo") != cb.get("activo"):
        sal.append(f"perfil: {ca.get('activo')} → {cb.get('activo')}")
    la = ((ca.get("perfiles") or {}).get("perfiles") or {}).get(ca.get("activo"), {}).get("layout")
    lb = ((cb.get("perfiles") or {}).get("perfiles") or {}).get(cb.get("activo"), {}).get("layout")
    if la and lb:
        sal += ["distribución: " + s for s in layout.resumen_diferencias(layout.validar(la), layout.validar(lb))]
    return na, nb, sal


def _corto(v):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 24 else s[:21] + "…"


# ------------------------------------------------------------------ copias y sincronizacion
def exportar_copia(carpeta):
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "arche_interfaz_" + time.strftime("%Y%m%d_%H%M%S") + ".copia.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"arche_copia": 1, "captura": capturar()}, f, ensure_ascii=False, indent=1)
    return True, ruta


def importar_copia(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        return False, f"no pude leer el archivo ({e})"
    if not isinstance(crudo, dict) or not isinstance(crudo.get("captura"), dict):
        return False, "el archivo no parece una copia de Arché"
    cap = crudo["captura"]
    if not (isinstance(cap.get("ajustes"), dict) and isinstance(cap.get("perfiles"), dict)):
        return False, "la copia está incompleta"
    crear_punto("antes de importar", auto=True)
    punto_de_control("importar copia")
    aplicar(_validada(cap) | {"activo": cap.get("activo")})
    return True, "copia importada (puedes deshacer)"


def sincronizar(direccion, carpeta=None, incluir=None):
    """'subir' copia tu aspecto a la carpeta; 'bajar' lo trae. Solo preferencias de interfaz, nunca datos del asistente."""
    carpeta = carpeta or ajustes.obtener("sync_carpeta")
    if not carpeta:
        return False, "falta la carpeta: di «sincronizar con <carpeta>»"
    incluir = incluir or ajustes.obtener("sync_incluir")
    archivo = os.path.join(carpeta, "arche_interfaz_sync.json")
    if direccion == "subir":
        try:
            os.makedirs(carpeta, exist_ok=True)
            cap = capturar()
            paquete = {"arche_sync": 1, "ts": time.time()}
            if "ajustes" in incluir:
                paquete["ajustes"] = cap["ajustes"]
            if "temas" in incluir:
                paquete["temas"] = cap["temas"]
            if "perfiles" in incluir:
                paquete["perfiles"] = cap["perfiles"]
            with open(archivo, "w", encoding="utf-8") as f:
                json.dump(paquete, f, ensure_ascii=False)
        except Exception as e:
            return False, f"no pude escribir en esa carpeta ({e})"
        return True, "subí " + ", ".join(i for i in ("ajustes", "temas", "perfiles") if i in incluir)
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            p = json.load(f)
    except Exception as e:
        return False, f"no encuentro datos de sincronización en esa carpeta ({e})"
    if not isinstance(p, dict) or p.get("arche_sync") != 1:
        return False, "ese archivo no es de Arché"
    crear_punto("antes de sincronizar", auto=True)
    punto_de_control("sincronizar")
    actual = capturar()
    if "ajustes" in incluir and isinstance(p.get("ajustes"), dict):
        actual["ajustes"] = _validada({"ajustes": p["ajustes"]})["ajustes"] | {}
        actual["ajustes"] = {**capturar()["ajustes"], **actual["ajustes"]}
    if "temas" in incluir and isinstance(p.get("temas"), dict):
        actual["temas"] = p["temas"]
    if "perfiles" in incluir and isinstance(p.get("perfiles"), dict):
        actual["perfiles"] = p["perfiles"]
    aplicar(actual)
    return True, "bajé " + ", ".join(i for i in ("ajustes", "temas", "perfiles") if i in incluir)
