"""
perfiles.py
-----------
Ubicacion: Arche/core/interfaz/perfiles.py

Perfiles de interfaz: cada uno guarda la distribucion de los paneles y todos
los ajustes visuales (tema, efectos, mascota, chat, fondos...). Cambiar de
perfil cambia toda la cara de Arché de una vez.

  general           la cara de siempre (Arché)
  programar         registro, procesos, mejora continua y chat tecnico
  tecnico           el sistema y la actividad de Arché con todo detalle
  trabajo           conversacion, notas, recordatorios y tareas
  minimalista       solo lo esencial
  ambiente          una esfera discreta con la hora
  entretenimiento   animaciones, fondos y efectos

Lo que cambias mientras un perfil esta activo se guarda en ese perfil. Los
perfiles se pueden crear, duplicar, renombrar, borrar, exportar e importar.
"""

import json
import os
import re
import threading
import time

from . import ajustes, layout, tema

_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfiles.json")
_lock = threading.RLock()
_datos = None
_lay = None
_sucio = False
_ultimo_volcado = 0.0

# Ajustes que viajan dentro de un perfil: todos los visuales menos los del equipo
_FUERA = {"pantallas", "favoritos", "atajos_rapidos", "mascota_nombre", "atajos", "perfil"}


def claves_perfil():
    return [k for k in ajustes.claves_visuales() if k not in _FUERA]


# ------------------------------------------------------------------ perfiles de fabrica
def _fabrica():
    A = layout.armar
    return {
        "general": {
            "descripcion": "La cara de siempre de Arché.",
            "layout": layout.por_defecto(), "ajustes": {},
        },
        "programar": {
            "descripcion": "Para programar: registro, procesos, mejora continua y el modelo a la vista.",
            "layout": A([
                ("registro", 0, 0, 8, 8), ("procesos", 0, 8, 8, 8),
                ("chat", 8, 0, 10, 10), ("voz", 8, 10, 10, 6),
                ("mejora", 18, 0, 6, 5), ("modelo", 18, 5, 6, 3), ("graficas", 18, 8, 6, 4),
                ("estado_asistente", 18, 12, 6, 4),
            ]),
            "ajustes": {"tema": "tecnico", "estilo_voz": "nucleo", "mascota": False, "chat_vista": "tecnica",
                        "chat_tam": 10, "chat_marcas_tiempo": True, "sistema_estilo": "numeros", "escena": "ninguna"},
        },
        "tecnico": {
            "descripcion": "Información detallada del equipo y de la actividad de Arché.",
            "layout": A([
                ("sistema", 0, 0, 6, 8), ("graficas", 0, 8, 6, 4), ("red", 0, 12, 6, 4),
                ("procesos", 6, 0, 6, 8), ("dispositivos", 6, 8, 6, 4), ("registro", 6, 12, 12, 4),
                ("estadisticas", 12, 0, 6, 3), ("redes", 12, 3, 6, 7), ("actividad", 12, 10, 6, 6),
                ("panel", 18, 0, 6, 16),
            ]),
            "ajustes": {"tema": "tecnico", "estilo_voz": "nucleo", "mascota": False, "sistema_estilo": "circular",
                        "chat_vista": "tecnica", "escena": "rejilla", "escena_intensidad": 25, "efecto_particulas": 0},
        },
        "trabajo": {
            "descripcion": "Conversación, notas, recordatorios y tareas pendientes.",
            "layout": A([
                ("chat", 0, 0, 11, 16),
                ("notas", 11, 0, 7, 6), ("recordatorios", 11, 6, 7, 5), ("reloj", 11, 11, 7, 2), ("atajos", 11, 13, 7, 3),
                ("calendario", 18, 0, 6, 7), ("voz", 18, 7, 6, 5), ("notificaciones", 18, 12, 6, 4),
            ]),
            "ajustes": {"tema": "azul", "mascota": False, "chat_vista": "clasica", "chat_tam": 12, "chat_espacio": 12,
                        "escena": "ninguna", "efecto_particulas": 0, "estilo_voz": "esfera"},
        },
        "minimalista": {
            "descripcion": "Solo lo esencial: la esfera y la conversación.",
            "layout": A([("voz", 5, 0, 14, 10), ("chat", 5, 10, 14, 6)], cabecera=True, pie=False, margen=30),
            "ajustes": {"tema": "minimalista", "mascota": False, "escena": "ninguna", "efecto_sombra": 0,
                        "efecto_borde_luminoso": 0, "efecto_particulas": 0, "efecto_brillo": 30,
                        "efecto_profundidad": False, "fondo": "", "chat_vista": "compacta"},
        },
        "ambiente": {
            "descripcion": "Una esfera discreta con la hora.",
            "layout": A([("reloj", 8, 1, 8, 3), ("voz", 8, 4, 8, 9)], cabecera=False, pie=False, margen=30),
            "ajustes": {"tema": "ambiente", "mascota": False, "escena": "ninguna", "efecto_brillo": 35,
                        "efecto_particulas": 0, "fondo": "", "fluidez": "normal", "orbe_tamano": 80},
        },
        "entretenimiento": {
            "descripcion": "Más movimiento: fondos, partículas y efectos.",
            "layout": A([
                ("reloj", 0, 0, 6, 3), ("actividad", 0, 3, 6, 5), ("notificaciones", 0, 8, 6, 8),
                ("voz", 6, 0, 12, 9), ("mascota", 6, 9, 12, 3), ("chat", 6, 12, 12, 4),
                ("panel", 18, 0, 6, 16),
            ]),
            "ajustes": {"tema": "holografico", "escena": "nebulosa", "escena_intensidad": 60, "efecto_particulas": 50,
                        "efecto_profundidad": True, "efecto_borde_luminoso": 60, "efecto_brillo": 80,
                        "mascota": True, "estilo_voz": "esfera"},
        },
    }


ALIAS = {"desarrollo": "programar", "dev": "programar", "programacion": "programar", "programador": "programar",
         "tecnica": "tecnico", "normal": "general", "arche": "general", "por defecto": "general",
         "predeterminado": "general", "minimal": "minimalista", "ambiental": "ambiente", "entretener": "entretenimiento",
         "juego": "entretenimiento", "diversion": "entretenimiento"}
INTEGRADOS = tuple(_fabrica().keys())


def _clave(n):
    return re.sub(r"\s+", " ", str(n).strip().lower())


def _perfil_de_fabrica(nombre):
    base = _fabrica()[nombre]
    ajs = {k: ajustes.DEFAULTS[k] for k in claves_perfil()}
    ajs.update(base["ajustes"])
    return {"descripcion": base["descripcion"], "layout": base["layout"], "ajustes": ajs, "integrado": True}


def _cargar():
    global _datos
    if _datos is not None:
        return _datos
    with _lock:
        if _datos is not None:
            return _datos
        crudo = {}
        try:
            with open(_ARCHIVO, "r", encoding="utf-8") as f:
                crudo = json.load(f)
            if not isinstance(crudo, dict):
                raise ValueError("no es un diccionario")
        except FileNotFoundError:
            crudo = {}
        except Exception:
            try:
                os.replace(_ARCHIVO, _ARCHIVO + ".danado-" + time.strftime("%Y%m%d-%H%M%S"))
            except Exception:
                pass
            crudo = {}
        perfiles = {}
        for n, p in (crudo.get("perfiles") or {}).items():
            limpio = _validar_perfil(n, p)
            if limpio:
                perfiles[limpio[0]] = limpio[1]
        for n in INTEGRADOS:
            if n not in perfiles:
                perfiles[n] = _perfil_de_fabrica(n)
            perfiles[n]["integrado"] = True
        activo = crudo.get("activo") if crudo.get("activo") in perfiles else "general"
        _datos = {"activo": activo, "perfiles": perfiles}
        return _datos


def _validar_perfil(nombre, p):
    """(nombre_limpio, perfil) o None. Un perfil defectuoso se descarta, no rompe nada."""
    if not isinstance(p, dict):
        return None
    nombre = re.sub(r"[^\w \-]", "", str(nombre)).strip()[:30]
    if not nombre:
        return None
    ajs = {}
    for k, v in (p.get("ajustes") or {}).items():
        if k in claves_perfil():
            ok, limpio = ajustes.validar(k, v)
            if ok:
                ajs[k] = limpio
    if "tema" in ajs and not tema.existe(ajs["tema"]):
        ajs["tema"] = "arche"
    return nombre, {"descripcion": str(p.get("descripcion") or "")[:120], "layout": layout.validar(p.get("layout")),
                    "ajustes": ajs, "integrado": bool(p.get("integrado"))}


def _guardar():
    try:
        tmp = _ARCHIVO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cargar(), f, indent=1, ensure_ascii=False)
        os.replace(tmp, _ARCHIVO)
    except Exception:
        pass


# ------------------------------------------------------------------ estado
def activo():
    return _cargar()["activo"]


def resolver(nombre):
    n = _clave(nombre)
    n = ALIAS.get(n, n)
    for real in _cargar()["perfiles"]:
        if _clave(real) == n:
            return real
    return None


def listar():
    """[(nombre, descripcion, integrado)]"""
    d = _cargar()
    return [(n, p["descripcion"], p["integrado"]) for n, p in d["perfiles"].items()]


def layout_actual():
    """El layout del perfil activo (el mismo objeto: los cambios se guardan con marcar_sucio())."""
    global _lay
    if _lay is None:
        d = _cargar()
        _lay = d["perfiles"][d["activo"]]["layout"]
    return _lay


def poner_layout(lay):
    global _lay
    _lay = layout.validar(lay)
    marcar_sucio()
    return _lay


def marcar_sucio(*_):
    global _sucio
    _sucio = True


ajustes.suscribir(lambda k, n, v: marcar_sucio() if k in claves_perfil() else None)


def volcar(forzar=False):
    """Guarda en el perfil activo lo que hay ahora (ajustes + distribucion). Se llama cada pocos segundos."""
    global _sucio, _ultimo_volcado
    if not (_sucio or forzar):
        return False
    with _lock:
        d = _cargar()
        p = d["perfiles"][d["activo"]]
        p["ajustes"] = {k: ajustes.obtener(k) for k in claves_perfil()}
        p["layout"] = layout_actual()
        _guardar()
        _sucio = False
        _ultimo_volcado = time.time()
    return True


def activar(nombre):
    """Cambia de perfil. Devuelve (ok, mensaje)."""
    real = resolver(nombre)
    if real is None:
        return False, f"no encuentro el perfil «{nombre}»"
    global _lay
    with _lock:
        volcar(forzar=True)                      # lo que cambiaste se queda en el perfil que dejas
        d = _cargar()
        p = d["perfiles"][real]
        d["activo"] = real
        _lay = layout.validar(p["layout"])
        p["layout"] = _lay
        base = {k: ajustes.DEFAULTS[k] for k in claves_perfil()}
        base.update(p["ajustes"])
        if not tema.existe(base.get("tema", "arche")):
            base["tema"] = "arche"
        for k, v in base.items():
            ajustes.fijar(k, v)
        ajustes.fijar("perfil", real)
        _guardar()
    return True, f"perfil «{real}» activado"


def crear(nombre, desde=None, descripcion=""):
    ok = _validar_perfil(nombre, {"layout": layout.por_defecto()})
    if not ok:
        return False, "ese nombre no sirve"
    nombre = ok[0]
    if resolver(nombre):
        return False, f"ya existe un perfil «{nombre}»"
    import copy
    with _lock:
        volcar(forzar=True)
        d = _cargar()
        origen = d["perfiles"][resolver(desde) or d["activo"]]
        d["perfiles"][nombre] = {"descripcion": descripcion or origen["descripcion"], "layout": copy.deepcopy(origen["layout"]),
                                 "ajustes": dict(origen["ajustes"]), "integrado": False}
        _guardar()
    return True, nombre


def guardar_como(nombre):
    """Guarda la configuracion actual como un perfil nuevo (y lo deja activo)."""
    ok, res = crear(nombre)
    if not ok:
        return False, res
    d = _cargar()
    d["activo"] = res
    global _lay
    _lay = d["perfiles"][res]["layout"]
    ajustes.fijar("perfil", res)
    volcar(forzar=True)
    return True, res


def renombrar(nombre, nuevo):
    real = resolver(nombre)
    if real is None:
        return False, f"no encuentro el perfil «{nombre}»"
    d = _cargar()
    if d["perfiles"][real]["integrado"]:
        return False, "los perfiles de fábrica no se renombran (duplícalo y renombra la copia)"
    limpio = _validar_perfil(nuevo, {"layout": layout.por_defecto()})
    if not limpio or resolver(limpio[0]):
        return False, "ese nombre no sirve o ya existe"
    d["perfiles"][limpio[0]] = d["perfiles"].pop(real)
    if d["activo"] == real:
        d["activo"] = limpio[0]
        ajustes.fijar("perfil", limpio[0])
    _guardar()
    return True, limpio[0]


def borrar(nombre):
    real = resolver(nombre)
    if real is None:
        return False, f"no encuentro el perfil «{nombre}»"
    d = _cargar()
    if d["perfiles"][real]["integrado"]:
        return False, "los perfiles de fábrica no se borran (puedes restablecerlos)"
    if d["activo"] == real:
        activar("general")
    d["perfiles"].pop(real, None)
    _guardar()
    return True, real


def restablecer(nombre=None):
    """Vuelve un perfil de fabrica a como venia. Sin nombre: el activo."""
    real = resolver(nombre) if nombre else activo()
    if real is None or real not in INTEGRADOS:
        return False, "solo los perfiles de fábrica se pueden restablecer"
    global _lay
    d = _cargar()
    d["perfiles"][real] = _perfil_de_fabrica(real)
    if d["activo"] == real:
        _lay = None
        activar(real)
    else:
        _guardar()
    return True, f"perfil «{real}» restablecido"


def restablecer_distribucion():
    """Solo la distribucion del perfil activo vuelve a la de fabrica (o a la general en perfiles propios)."""
    global _lay
    real = activo()
    base = _fabrica()["general" if real not in INTEGRADOS else real]["layout"]
    _lay = layout.validar(base)
    _cargar()["perfiles"][real]["layout"] = _lay
    marcar_sucio()
    volcar(forzar=True)
    return True, "distribución restablecida"


# ------------------------------------------------------------------ exportar / importar
def exportar(nombre, carpeta):
    real = resolver(nombre) if nombre else activo()
    if real is None:
        return False, f"no encuentro el perfil «{nombre}»"
    volcar(forzar=True)
    p = _cargar()["perfiles"][real]
    t = tema.resolver(p["ajustes"].get("tema", "arche"))
    temas = {t: tema.todos_los_propios()[t]} if t and tema.es_propio(t) else {}
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, re.sub(r"[^\w\-]+", "_", real) + ".perfil.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"arche_perfil": 1, "nombre": real, "descripcion": p["descripcion"], "layout": p["layout"],
                   "ajustes": p["ajustes"], "temas": temas}, f, indent=1, ensure_ascii=False)
    return True, ruta


def importar(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        return False, f"no pude leer el archivo ({e})"
    if not isinstance(crudo, dict) or "layout" not in crudo:
        return False, "el archivo no parece un perfil de Arché"
    # los temas propios que trae se validan y se agregan (si ya existe uno igual, se usa ese)
    renombres = {}
    for nombre, t in (crudo.get("temas") or {}).items():
        ok, limpio = tema._validar_tema(nombre, t)
        if ok and limpio["colores"]:
            destino = limpio["nombre"]
            if tema.resolver(destino) and tema.colores_de(tema.resolver(destino)) != {**tema.colores_de(limpio["base"]), **limpio["colores"]}:
                destino, k = f"{limpio['nombre']} (importado)", 2
                while tema.resolver(destino):
                    destino = f"{limpio['nombre']} (importado {k})"
                    k += 1
            if not tema.resolver(destino):
                limpio["nombre"] = destino
                tema._cargar_personales()[destino] = limpio
                tema._guardar_personales()
            renombres[nombre] = destino
    ajs = dict(crudo.get("ajustes") or {})
    if ajs.get("tema") in renombres:
        ajs["tema"] = renombres[ajs["tema"]]
    limpio = _validar_perfil(crudo.get("nombre", "importado"), {"descripcion": crudo.get("descripcion"),
                                                                   "layout": crudo["layout"], "ajustes": ajs})
    if not limpio:
        return False, "el perfil no es válido"
    nombre, k = limpio[0], 2
    while resolver(nombre):
        nombre = f"{limpio[0]} {k}"
        k += 1
    with _lock:
        _cargar()["perfiles"][nombre] = limpio[1]
        _guardar()
    return True, nombre


def todo(con_volcado=True):
    """Copia de todos los perfiles (para puntos de restauracion y sincronizacion)."""
    if con_volcado:
        volcar(forzar=True)
    else:                                   # copia en memoria: el perfil activo con lo que hay ahora
        d = _cargar()
        d["perfiles"][d["activo"]]["ajustes"] = {k: ajustes.obtener(k) for k in claves_perfil()}
        d["perfiles"][d["activo"]]["layout"] = layout_actual()
    return json.loads(json.dumps(_cargar()))


def reemplazar_todo(datos):
    """Restaura todos los perfiles desde una copia (validando cada uno)."""
    global _datos, _lay
    if not isinstance(datos, dict):
        return False
    perfiles = {}
    for n, p in (datos.get("perfiles") or {}).items():
        limpio = _validar_perfil(n, p)
        if limpio:
            perfiles[limpio[0]] = limpio[1]
    for n in INTEGRADOS:
        perfiles.setdefault(n, _perfil_de_fabrica(n))
        perfiles[n]["integrado"] = True
    activo_ = datos.get("activo") if datos.get("activo") in perfiles else "general"
    _datos = {"activo": activo_, "perfiles": perfiles}
    _lay = None
    _guardar()
    return True
