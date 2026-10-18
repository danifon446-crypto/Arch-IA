"""
tema.py
-------
Ubicacion: Arche/core/interfaz/tema.py

Paleta unica de Arché para la consola (Rich), la ventana (Tkinter) y el
modo TV. Fondo oscuro con azul, rojo y morado en tonos profundos. Si algun
dia quieres cambiar el aspecto de todo, se cambia SOLO aqui.
"""

# Fondos
FONDO = "#0a0916"        # casi negro azulado
PANEL = "#13102a"        # tarjetas
PANEL_2 = "#1b1638"      # tarjeta resaltada / barra vacia
BORDE = "#2d2457"

# Texto
TEXTO = "#e8e4ff"
TENUE = "#8f89bd"

# Colores de marca (oscuros)
AZUL = "#2f4fd1"
AZUL_CLARO = "#5b7cff"
MORADO = "#6b34c9"
MORADO_CLARO = "#9b6bff"
ROJO = "#b81f45"
ROJO_CLARO = "#e0435f"

# Estados (se leen por color: azul = bien, morado = atencion, rojo = alerta)
OK = AZUL_CLARO
ATENCION = MORADO_CLARO
ALERTA = ROJO_CLARO

# Degradado azul -> morado -> rojo para las ondas de voz
DEGRADADO = (AZUL, MORADO, ROJO)

# Resolucion base del modo TV (la basica)
TV_ANCHO = 1280
TV_ALTO = 720

FUENTE = "Segoe UI"
FUENTE_MONO = "Consolas"


def _a_rgb(hexa):
    hexa = hexa.lstrip("#")
    return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))


def _a_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def mezclar(c1, c2, t):
    """Mezcla dos colores hex. t=0 -> c1, t=1 -> c2."""
    a, b = _a_rgb(c1), _a_rgb(c2)
    return _a_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def degradado(t, colores=None):
    """Color del degradado en la posicion t (0 a 1)."""
    colores = colores or DEGRADADO
    t = max(0.0, min(1.0, t))
    tramos = len(colores) - 1
    pos = t * tramos
    i = min(int(pos), tramos - 1)
    return mezclar(colores[i], colores[i + 1], pos - i)


def color_de_uso(porcentaje):
    """Color segun que tan lleno esta algo (CPU, RAM, disco)."""
    if porcentaje >= 90:
        return ALERTA
    if porcentaje >= 70:
        return ATENCION
    return OK


# ------------------------------------------------------------------
# Temas: de fabrica, creados por ti, y ajustes de accesibilidad
# ------------------------------------------------------------------
import json
import os
import re

# (fondo, texto, tenue, (azul, azul_claro), (morado, morado_claro), (rojo, rojo_claro))
TEMAS = {
    "arche": ("#0a0916", "#e8e4ff", "#8f89bd", ("#2f4fd1", "#5b7cff"), ("#6b34c9", "#9b6bff"), ("#b81f45", "#e0435f")),
    "neon": ("#06060f", "#eafcff", "#7fa3b3", ("#0aa5c9", "#22e5ff"), ("#6a3df0", "#8f6bff"), ("#d41fa8", "#ff3fd0")),
    "ambar": ("#0e0905", "#fff1dc", "#b59a78", ("#c97a00", "#ffb300"), ("#c24a00", "#ff7a1a"), ("#b3262e", "#ff5a4e")),
    "esmeralda": ("#040d0b", "#e3fff6", "#7fb5a5", ("#0f9d8a", "#22d3a0"), ("#1a7fb5", "#38bdf8"), ("#6aa81c", "#a3e635")),
    "azul": ("#060b18", "#eaf2ff", "#8aa0c4", ("#1d6fe0", "#4da3ff"), ("#2b4fb8", "#8fb8ff"), ("#c0392b", "#ff6b5e")),
    "minimalista": ("#101114", "#f0f0f0", "#8a8a90", ("#5a5a66", "#b0b0bd"), ("#4a4a55", "#9a9aa8"), ("#a33a3a", "#e06060")),
    "holografico": ("#05081a", "#e6fbff", "#7fb7c9", ("#18c7d9", "#6ff3ff"), ("#8a5cff", "#c3a6ff"), ("#ff4fa3", "#ff9bd1")),
    "tecnico": ("#07100c", "#d8ffe9", "#6fa88a", ("#18a35c", "#3dff8a"), ("#1c7a8a", "#35d0e8"), ("#b8742a", "#ffb347")),
    "ambiente": ("#060608", "#bdbdc8", "#5d5d6b", ("#2a3355", "#556091"), ("#3a2a55", "#6a5a91"), ("#552a35", "#91566a")),
}
NOMBRES = {"arche": "arché", "neon": "neón", "ambar": "ámbar", "esmeralda": "esmeralda", "azul": "azul tecnológico",
           "minimalista": "minimalista", "holografico": "holográfico", "tecnico": "técnico", "ambiente": "ambiente"}
# lo que acepta el comando "tema <nombre>" ademas del nombre exacto
ALIAS = {"amber": "ambar", "verde": "esmeralda", "azul tecnologico": "azul", "azul oscuro": "azul",
         "minimal": "minimalista", "holografica": "holografico", "holo": "holografico", "tecnica": "tecnico",
         "clasico": "arche", "arche clasico": "arche", "morado": "arche"}

# Cada color que puedes cambiar a mano, y para que sirve
ROLES = {
    "fondo": "fondo de la ventana", "panel": "paneles", "panel2": "paneles resaltados y barras vacias",
    "borde": "bordes", "texto": "texto", "tenue": "texto secundario", "boton": "botones",
    "azul": "azul (acento 1)", "azul_claro": "azul claro (acento 1, indicadores)",
    "morado": "morado (acento 2)", "morado_claro": "morado claro (acento 2, seleccionado)",
    "rojo": "rojo (acento 3)", "rojo_claro": "rojo claro (acento 3)",
    "ok": "indicador bien", "atencion": "indicador atencion", "alerta": "alertas",
    "grafica_a": "grafica CPU", "grafica_b": "grafica RAM", "seleccion": "elemento seleccionado",
}
ALIAS_ROLES = {"fondo": "fondo", "paneles": "panel", "panel": "panel", "bordes": "borde", "borde": "borde",
               "texto": "texto", "botones": "boton", "boton": "boton", "alertas": "alerta", "alerta": "alerta",
               "indicadores": "ok", "graficas": "grafica_a", "grafica": "grafica_a", "seleccion": "seleccion",
               "seleccionado": "seleccion", "acento": "morado_claro", "azul": "azul_claro", "morado": "morado_claro",
               "rojo": "rojo_claro", "tenue": "tenue", "secundario": "tenue", "ok": "ok", "atencion": "atencion"}

BOTON = SELECCION = GRAFICA_A = GRAFICA_B = "#000000"
_actual = "arche"
_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temas.json")
_personales = None
_HEX = re.compile(r"^#[0-9a-f]{6}$")


def _paleta_base(nombre):
    """Los colores (por rol) de un tema de fabrica."""
    fondo, texto, tenue, azul, morado, rojo = TEMAS[nombre]
    p = {"fondo": fondo, "texto": texto, "tenue": tenue, "azul": azul[0], "azul_claro": azul[1],
         "morado": morado[0], "morado_claro": morado[1], "rojo": rojo[0], "rojo_claro": rojo[1]}
    if nombre == "arche":
        p.update(panel="#13102a", panel2="#1b1638", borde="#2d2457")
    else:
        p.update(panel=mezclar(fondo, morado[0], 0.11), panel2=mezclar(fondo, morado[0], 0.20),
                 borde=mezclar(fondo, morado[1], 0.28))
    return p


def _cargar_personales():
    global _personales
    if _personales is None:
        _personales = {}
        try:
            with open(_ARCHIVO, "r", encoding="utf-8") as f:
                crudo = json.load(f)
            for nombre, t in (crudo if isinstance(crudo, dict) else {}).items():
                ok, limpio = _validar_tema(nombre, t)
                if ok:
                    _personales[limpio["nombre"]] = limpio
        except Exception:
            _personales = {}
    return _personales


def _guardar_personales():
    try:
        tmp = _ARCHIVO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cargar_personales(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, _ARCHIVO)
    except Exception:
        pass


def _hex_ok(v):
    from . import ajustes
    return ajustes.normalizar_hex(v)


def _validar_tema(nombre, t):
    """(True, {"nombre", "base", "colores"}) o (False, motivo). Un tema solo lleva colores: nada ejecutable."""
    if not isinstance(t, dict):
        return False, "el tema no es un diccionario"
    nombre = re.sub(r"[^\w \-]", "", str(t.get("nombre") or nombre)).strip()[:30]
    if not nombre:
        return False, "falta el nombre"
    base = t.get("base", "arche")
    if base not in TEMAS:
        base = "arche"
    cols = {}
    for rol, v in (t.get("colores") or {}).items():
        if rol in ROLES:
            h = _hex_ok(v)
            if h:
                cols[rol] = h
    return True, {"nombre": nombre, "base": base, "colores": cols}


def _clave(nombre):
    return re.sub(r"\s+", " ", str(nombre).strip().lower())


def existe(nombre):
    return resolver(nombre) is not None


def resolver(nombre):
    """Nombre exacto del tema (de fabrica o tuyo) o None."""
    n = _clave(nombre)
    n = ALIAS.get(n, n)
    if n in TEMAS:
        return n
    for propio in _cargar_personales():
        if _clave(propio) == n:
            return propio
    return None


def listar():
    """[(nombre, texto_para_mostrar, es_propio)]"""
    sal = [(n, NOMBRES.get(n, n), False) for n in TEMAS]
    sal += [(n, n, True) for n in sorted(_cargar_personales())]
    return sal


def es_propio(nombre):
    return nombre in _cargar_personales()


def actual():
    return _actual


def colores_de(nombre):
    """Colores por rol de cualquier tema, con sus cambios aplicados."""
    propios = _cargar_personales()
    if nombre in propios:
        p = _paleta_base(propios[nombre]["base"])
        p.update(propios[nombre]["colores"])
        # lo que no definiste se deriva de lo que si definiste
        c = propios[nombre]["colores"]
        if "panel" not in c and "fondo" in c:
            p["panel"] = mezclar(p["fondo"], p["morado"], 0.11)
        if "panel2" not in c and "fondo" in c:
            p["panel2"] = mezclar(p["fondo"], p["morado"], 0.20)
        if "borde" not in c and "fondo" in c:
            p["borde"] = mezclar(p["fondo"], p["morado_claro"], 0.28)
        return p
    return _paleta_base(nombre if nombre in TEMAS else "arche")


def _contraste(p):
    """Alto contraste: texto casi blanco, fondo casi negro y bordes bien visibles."""
    p = dict(p)
    p["fondo"] = mezclar(p["fondo"], "#000000", 0.7)
    p["panel"] = mezclar(p["fondo"], "#ffffff", 0.07)
    p["panel2"] = mezclar(p["fondo"], "#ffffff", 0.14)
    p["borde"] = "#c8c8d8"
    p["texto"] = "#ffffff"
    p["tenue"] = "#d0d0e0"
    for r in ("azul_claro", "morado_claro", "rojo_claro"):
        p[r] = mezclar(p[r], "#ffffff", 0.35)
    return p


def aplicar(nombre):
    """Cambia los colores de todo (consola y ventana leen estas variables)."""
    global FONDO, PANEL, PANEL_2, BORDE, TEXTO, TENUE, BOTON, SELECCION, GRAFICA_A, GRAFICA_B
    global AZUL, AZUL_CLARO, MORADO, MORADO_CLARO, ROJO, ROJO_CLARO
    global OK, ATENCION, ALERTA, DEGRADADO, _actual
    real = resolver(nombre)
    if real is None:
        return False
    p = colores_de(real)
    try:
        from . import ajustes
        if ajustes.obtener("alto_contraste"):
            p = _contraste(p)
    except Exception:
        pass
    FONDO, TEXTO, TENUE = p["fondo"], p["texto"], p["tenue"]
    PANEL, PANEL_2, BORDE = p["panel"], p["panel2"], p["borde"]
    AZUL, AZUL_CLARO, MORADO, MORADO_CLARO, ROJO, ROJO_CLARO = (
        p["azul"], p["azul_claro"], p["morado"], p["morado_claro"], p["rojo"], p["rojo_claro"])
    OK = p.get("ok", AZUL_CLARO)
    ATENCION = p.get("atencion", MORADO_CLARO)
    ALERTA = p.get("alerta", ROJO_CLARO)
    BOTON = p.get("boton", PANEL_2)
    SELECCION = p.get("seleccion", MORADO_CLARO)
    GRAFICA_A = p.get("grafica_a", AZUL_CLARO)
    GRAFICA_B = p.get("grafica_b", MORADO_CLARO)
    DEGRADADO = (AZUL, MORADO, ROJO)
    _actual = real
    return True


# --------------------------- temas propios ---------------------------
def crear(nombre, base=None):
    """Crea un tema propio a partir de otro. Devuelve (ok, nombre_o_motivo)."""
    ok, t = _validar_tema(nombre, {"nombre": nombre, "base": "arche", "colores": {}})
    if not ok:
        return False, t
    nombre = t["nombre"]
    if resolver(nombre) is not None:
        return False, f"ya existe un tema llamado «{nombre}»"
    origen = resolver(base) if base else _actual
    cols = {} if origen is None else dict(colores_de(origen))
    _cargar_personales()[nombre] = {"nombre": nombre, "base": origen if origen in TEMAS else
                                    _cargar_personales().get(origen, {}).get("base", "arche"), "colores": cols}
    _guardar_personales()
    return True, nombre


def duplicar(nombre, nuevo):
    real = resolver(nombre)
    if real is None:
        return False, f"no encuentro el tema «{nombre}»"
    return crear(nuevo, real)


def borrar(nombre):
    real = resolver(nombre)
    if real is None or real in TEMAS:
        return False, "solo puedo borrar temas creados por ti"
    _cargar_personales().pop(real, None)
    _guardar_personales()
    return True, real


def renombrar(nombre, nuevo):
    real = resolver(nombre)
    if real is None or real in TEMAS:
        return False, "solo puedo renombrar temas creados por ti"
    if resolver(nuevo):
        return False, f"ya existe «{nuevo}»"
    ok, t = _validar_tema(nuevo, {"nombre": nuevo})
    if not ok:
        return False, t
    d = _cargar_personales()
    d[t["nombre"]] = dict(d.pop(real), nombre=t["nombre"])
    _guardar_personales()
    return True, t["nombre"]


def fijar_color(nombre, rol, valor):
    """Cambia un color de un tema propio. Devuelve (ok, hex_o_motivo)."""
    if nombre not in _cargar_personales():
        return False, "ese tema no es tuyo: crea uno primero (se hace solo al cambiar un color)"
    if rol not in ROLES:
        return False, "no conozco ese color; los que hay: " + ", ".join(ROLES)
    h = _hex_ok(valor)
    if not h:
        return False, "no es un color valido (usa #RRGGBB o R,G,B)"
    _cargar_personales()[nombre]["colores"][rol] = h
    _guardar_personales()
    return True, h


def restablecer_colores(nombre):
    if nombre in _cargar_personales():
        _cargar_personales()[nombre]["colores"] = {}
        _guardar_personales()
        return True
    return False


def exportar(nombre, carpeta):
    real = resolver(nombre)
    if real is None:
        return False, f"no encuentro el tema «{nombre}»"
    os.makedirs(carpeta, exist_ok=True)
    datos = {"arche_tema": 1, "nombre": real, "base": "arche", "colores": colores_de(real)}
    ruta = os.path.join(carpeta, re.sub(r"[^\w\-]+", "_", real) + ".tema.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    return True, ruta


def importar(ruta):
    """Lee un .tema.json, lo valida y lo agrega con un nombre libre."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        return False, f"no pude leer el archivo ({e})"
    if not isinstance(crudo, dict) or "colores" not in crudo:
        return False, "el archivo no parece un tema de Arché"
    ok, t = _validar_tema(crudo.get("nombre", "importado"), crudo)
    if not ok:
        return False, t
    if not t["colores"]:
        return False, "el tema no trae ningun color valido"
    nombre, k = t["nombre"], 2
    while resolver(nombre) is not None:
        nombre = f"{t['nombre']} {k}"
        k += 1
    t["nombre"] = nombre
    _cargar_personales()[nombre] = t
    _guardar_personales()
    return True, nombre


def todos_los_propios():
    return json.loads(json.dumps(_cargar_personales()))


def reemplazar_propios(datos):
    """Usado al restaurar copias: reemplaza los temas propios (validandolos)."""
    nuevo = {}
    for n, t in (datos or {}).items():
        ok, limpio = _validar_tema(n, t)
        if ok:
            nuevo[limpio["nombre"]] = limpio
    _cargar_personales().clear()
    _cargar_personales().update(nuevo)
    _guardar_personales()


def tema_por_hora(hora=None):
    """Para el cambio automatico: 'dia' de 7 a 19, 'noche' el resto."""
    import time as _t
    h = _t.localtime().tm_hour if hora is None else hora
    return "dia" if 7 <= h < 19 else "noche"
