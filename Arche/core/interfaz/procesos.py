"""
procesos.py
-----------
Ubicacion: Arche/core/interfaz/procesos.py

Lista lo que Arché esta haciendo en segundo plano ahora mismo. No guarda nada
aparte: mira los hilos que de verdad estan vivos y les pone un nombre claro,
asi que lo que ves es la verdad (si algo se detiene, desaparece de la lista).
"""

import threading

# Por nombre del hilo (los que Arché ya nombra)
_POR_NOMBRE = {
    "arche-mejora": ("Piloto automático de mejora", "mejora"),
    "arche-autonomia": ("Autonomía: avisos y hábitos", "autonomia"),
    "alarmas": ("Alarmas y temporizadores", "alarmas"),
    "arche-voz": ("Voz natural", "voz"),
    "arche-voz-sintesis": ("Preparando voz", "sintesis"),
    "aprender-nube": ("Aprendiendo de la nube", "nube"),
    "arche-play": ("Reproduciendo música", "musica"),
    "arche-redes-entrenar": ("Entrenando redes neuronales", "redes_entreno"),
    "arche-redes-agregar": ("Clasificando ejemplos nuevos", "redes_agregar"),
    "arche-redes-agregar-a": ("Guardando ejemplos nuevos", "redes_agregar"),
    "arche-redes-probar": ("Probando una frase en las redes", "redes_probar"),
    "arche-redes-lectura": ("Leyendo las redes neuronales", "redes_lectura"),
    "arche-redes-pesos": ("Cargando pesos de una red", "redes_lectura"),
}

# Por modulo/funcion del hilo (los que no tienen nombre)
_POR_MODULO = (
    ("examen", "Examen automático", "examen"),
    ("estudio", "Modo estudio", None),
    ("autorevision", "Autorevisión del código", None),
    ("entrenador_masivo", "Entrenamiento de la red", None),
    ("archivos", "Indexando archivos", None),
    ("control_pc", "Acción en el PC", None),
    ("autonomia", "Orden automática", None),
)

_IGNORAR_MODULO = ("interfaz", "tkinter", "threading", "queue", "concurrent")


def _detalle(clave):
    try:
        if clave == "mejora":
            from core import mejora_continua as m
            if getattr(m, "_trabajando", False):
                return "mejorándose ahora", True
            return f"vigilando · nivel {m.nivel()}", False
        if clave == "examen":
            from . import datos
            ex = datos.examen()
            return f"nivel {ex.get('nivel', 0)} · {ex.get('listos', 0)}/{len(ex.get('dominios', []))} dominios listos", True
        if clave == "autonomia":
            return "atenta a tu equipo y a tus hábitos", False
        if clave == "alarmas":
            return "vigilando la hora", False
        if clave == "voz":
            return "lista para hablar", False
        if clave == "nube":
            return "preguntando a la nube para aprender", True
        if clave == "musica":
            return "pidiendo la canción", True
        if clave == "redes_entreno":
            from . import redes
            e = redes.estado["entreno"]
            return f"{e['actual'] or '…'} ({e['hecho']}/{e['total']})", True
        if clave == "redes_agregar":
            from . import redes
            return f"{redes.estado['agregando']} frase(s) en cola", True
        if clave in ("redes_probar", "redes_lectura"):
            return "leyendo neuronas reales", True
        if clave == "sintesis":
            return "convirtiendo texto en voz", True
    except Exception:
        pass
    return "", True


def _identificar(hilo):
    nombre = hilo.name or ""
    if nombre in _POR_NOMBRE:
        etiqueta, clave = _POR_NOMBRE[nombre]
        return etiqueta, clave
    destino = getattr(hilo, "_target", None)
    modulo = (getattr(destino, "__module__", "") or "").lower()
    funcion = getattr(destino, "__name__", "") or ""
    if any(x in modulo for x in _IGNORAR_MODULO) or hilo is threading.main_thread():
        return None, None
    for trozo, etiqueta, clave in _POR_MODULO:
        if trozo in modulo:
            return etiqueta, clave
    if modulo.startswith(("core", "__main__", "main")):
        return funcion.strip("_").replace("_", " ").capitalize() or "Tarea interna", None
    return None, None


def listar():
    """[{nombre, detalle, activo, cantidad}] de lo que corre en segundo plano."""
    vistos = {}
    for hilo in threading.enumerate():
        try:
            if not hilo.is_alive() or hilo is threading.main_thread():
                continue
            etiqueta, clave = _identificar(hilo)
            if not etiqueta:
                continue
            if etiqueta in vistos:
                vistos[etiqueta]["cantidad"] += 1
                continue
            detalle, activo = _detalle(clave)
            vistos[etiqueta] = {"nombre": etiqueta, "detalle": detalle, "activo": activo, "cantidad": 1}
        except Exception:
            continue
    return sorted(vistos.values(), key=lambda p: (not p["activo"], p["nombre"]))
