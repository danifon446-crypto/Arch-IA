"""
disenador.py
------------
Ubicacion: Arche/core/tres_d/disenador.py

Convierte lo que le dices a Arché en modelos 3D y los guarda.

  "crea una caja de 80x50x30 con tapa"      -> pieza del catálogo, a tus medidas
  "hazla más alta" / "cambia el ancho a 60" -> modifica la última pieza
  "diseña en 3d un llavero con forma de..." -> pieza libre (la arma la IA con formas básicas)
  "analiza el modelo" / "analiza pata.stl"  -> medidas, peso, soportes, orientación
  "escala el modelo al 150%", "rota el modelo 90 en x", "espejo del modelo", "orienta el modelo"

Los modelos quedan en Arche/Modelos3D/ como .stl (listos para el slicer) y al
lado un .json con la "receta" (qué pieza es y con qué medidas) para poder
modificarlos después.
"""

import json
import os
import re
import shutil
import time
import unicodedata

from . import geometria as geo
from . import piezas

AQUI = os.path.dirname(os.path.abspath(__file__))                     # .../Arche/core/tres_d
CARPETA = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "Modelos3D")
_estado = {"ultimo": None, "version": 0}                              # nombre del último modelo tocado


# ------------------------------------------------------------------
# Almacén de modelos
# ------------------------------------------------------------------

def carpeta():
    os.makedirs(CARPETA, exist_ok=True)
    return CARPETA


def _limpio(nombre):
    """Nombre de archivo seguro: sin rutas, sin caracteres raros."""
    base = os.path.splitext(os.path.basename(str(nombre).replace("\\", "/")))[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9_\-]+", "_", base).strip("_")[:60]
    return base or "modelo"


def ruta_stl(nombre):
    return os.path.join(carpeta(), _limpio(nombre) + ".stl")


def _ruta_receta(nombre):
    return os.path.join(carpeta(), _limpio(nombre) + ".json")


def existe(nombre):
    return os.path.isfile(ruta_stl(nombre))


def nombre_libre(base):
    base = _limpio(base)
    if not existe(base):
        return base
    n = 2
    while existe(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


def listar():
    """[{nombre, bytes, fecha, receta}] del más nuevo al más viejo."""
    salida = []
    for archivo in os.listdir(carpeta()):
        if archivo.lower().endswith(".stl"):
            ruta = os.path.join(CARPETA, archivo)
            nombre = archivo[:-4]
            salida.append({"nombre": nombre, "bytes": os.path.getsize(ruta), "fecha": os.path.getmtime(ruta),
                           "receta": leer_receta(nombre)})
    salida.sort(key=lambda m: -m["fecha"])
    return salida


def leer_receta(nombre):
    try:
        with open(_ruta_receta(nombre), "r", encoding="utf-8") as f:
            datos = json.load(f)
            return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar(nombre, malla, receta):
    """Guarda el STL y su receta, y lo deja como «el modelo» actual."""
    nombre = _limpio(nombre)
    geo.escribir_stl(malla, ruta_stl(nombre), nombre)
    receta = dict(receta or {})
    receta["actualizado"] = time.strftime("%Y-%m-%d %H:%M:%S")
    temporal = _ruta_receta(nombre) + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(receta, f, indent=2, ensure_ascii=False)
    os.replace(temporal, _ruta_receta(nombre))
    _estado["ultimo"] = nombre
    _estado["version"] += 1
    return nombre


def borrar(nombre):
    """No borra: lo pasa a Modelos3D/_papelera (por si te arrepientes)."""
    if not existe(nombre):
        return False
    papelera = os.path.join(carpeta(), "_papelera")
    os.makedirs(papelera, exist_ok=True)
    sello = time.strftime("%Y%m%d_%H%M%S")
    for ruta in (ruta_stl(nombre), _ruta_receta(nombre)):
        if os.path.exists(ruta):
            shutil.move(ruta, os.path.join(papelera, f"{sello}_{os.path.basename(ruta)}"))
    if _estado["ultimo"] == _limpio(nombre):
        _estado["ultimo"] = None
    _estado["version"] += 1
    return True


def ultimo():
    """El modelo sobre el que se está trabajando (o el más reciente de la carpeta)."""
    if _estado["ultimo"] and existe(_estado["ultimo"]):
        return _estado["ultimo"]
    todos = listar()
    return todos[0]["nombre"] if todos else None


def version():
    return _estado["version"]


def abrir(nombre):
    return geo.leer_modelo(ruta_stl(nombre))


def buscar(texto):
    """Encuentra un modelo por nombre aproximado ('la pata', 'pata.stl')."""
    clave = _limpio(_norm(texto)).lower()
    if not clave:
        return None
    nombres = [m["nombre"] for m in listar()]
    for n in nombres:
        if n.lower() == clave:
            return n
    for n in nombres:                      # dijeron parte del nombre: "pata" -> pata_delantera
        if len(clave) >= 3 and clave in n.lower():
            return n
    fichas = clave.split("_")
    if len(fichas) <= 3:                   # "la pata": el nombre entero aparece entre pocas palabras
        for n in nombres:
            if n.lower() in fichas or n.lower() == "_".join(fichas[1:]):
                return n
    return None


# ------------------------------------------------------------------
# Entender las medidas
# ------------------------------------------------------------------

def _norm(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("×", "x").replace("ø", " diametro ")
    return re.sub(r"\s+", " ", t).strip(" .!¡?¿")


_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIDAD = r"\s*(mm|milimetros?|cm|centimetros?|m\b|metros?|pulgadas?|in\b|\")?"


def _valor(numero, unidad):
    v = float(numero.replace(",", "."))
    u = (unidad or "").strip()
    if u.startswith("cm") or u.startswith("centim"):
        return v * 10.0
    if u in ("m",) or u.startswith("metro"):
        return v * 1000.0
    if u.startswith("pulg") or u in ("in", '"'):
        return v * 25.4
    return v


# cómo le dice la gente a cada medida -> nombre de la medida en el catálogo
_NOMBRES = [
    ("diametro_agujero", r"diametro (?:de |del )?(?:los )?agujeros?"),
    ("interior", r"diametro interior|diametro interno|interior|interno|hueco"),
    ("diametro", r"diametro exterior|diametro externo|diametro|de diametro"),
    ("largo", r"largo|longitud|largura"),
    ("ancho", r"ancho|anchura"),
    ("alto", r"alto|altura"),
    ("grosor_celular", r"grosor del celular|grosor de celular"),
    ("grosor", r"grosor|espesor|grueso"),
    ("pared", r"pared|paredes"),
    ("profundidad", r"profundidad|fondo"),
    ("margen", r"margen"),
    ("redondeo", r"redondeo|radio de las esquinas|esquinas redondeadas de"),
    ("inclinacion", r"inclinacion|angulo"),
    ("modulo", r"modulo"),
    ("punta", r"punta|diametro superior|arriba"),
    ("base", r"base|fondo de"),
]
_METRICA = {"2": 2.2, "2.5": 2.7, "3": 3.2, "4": 4.3, "5": 5.3, "6": 6.4, "8": 8.4}

# en qué orden se reparten los números sueltos ("de 80x50x30", "de 20 por 50")
_ORDEN = {
    "caja": ["largo", "ancho", "alto"], "cilindro": ["diametro", "alto"], "tubo": ["diametro", "alto"],
    "esfera": ["diametro"], "cono": ["diametro", "alto"], "placa": ["largo", "ancho", "grosor"],
    "escuadra": ["largo", "alto", "ancho"], "separador": ["alto", "diametro"], "engranaje": [],
    "soporte_servo": [], "vaso": ["diametro", "alto"], "rueda": ["diametro", "ancho"],
    "soporte_celular": ["ancho"], "gancho": ["profundidad", "alto", "ancho"],
}
# alias que traen medidas propias
_PREAJUSTES = {
    "maceta": {"drenaje": 3, "diametro": 90, "alto": 80}, "matera": {"drenaje": 3, "diametro": 90, "alto": 80},
    "arandela": {"alto": 1.5, "diametro": 12, "interior": 5.3}, "anillo": {"alto": 5}, "aro": {"alto": 5},
    "buje": {"alto": 10, "diametro": 10, "interior": 5}, "casquillo": {"alto": 10, "diametro": 10, "interior": 5},
    "portalapices": {"diametro": 75, "alto": 100}, "porta lapices": {"diametro": 75, "alto": 100},
    "eje": {"diametro": 8, "alto": 60}, "varilla": {"diametro": 6, "alto": 100}, "barra": {"diametro": 10, "alto": 100},
    "pasador": {"diametro": 5, "alto": 25}, "polea": {"rayos": 0, "diametro": 40, "ancho": 10},
    "embudo": {"punta": 8}, "estuche": {"tapa": 1}, "carcasa": {"tapa": 1, "postes": 1},
}
# alias que también significan otra cosa: solo cuentan con una medida o diciendo "3d", "imprimir"...
_AMBIGUOS = {"base", "eje", "barra", "aro", "contenedor", "recipiente", "estuche", "plataforma", "angulo", "pelota",
             "bola", "percha", "lamina", "embudo", "anillo", "chapa", "llanta", "tarro", "pasador", "varilla",
             "colgador", "perchero", "carcasa", "vaso", "caja", "cajita", "placa", "rueda", "atril", "arandela", "polea"}

_ALIAS = sorted(((a, nombre) for nombre, d in piezas.CATALOGO.items() for a in d["alias"]),
                key=lambda par: -len(par[0]))


def pieza_en(texto):
    """(nombre del catálogo, alias usado) de la primera pieza que nombra el texto, o (None, None)."""
    t = " " + _norm(texto) + " "
    for alias, nombre in _ALIAS:
        if re.search(rf"\b{re.escape(_norm(alias))}s?\b", t):
            return nombre, alias
    return None, None


def _quitar(texto, tramo):
    return texto[:tramo[0]] + " " * (tramo[1] - tramo[0]) + texto[tramo[1]:]


def medidas_de(texto, nombre):
    """Saca del texto las medidas que sirven para esa pieza. Devuelve un dict."""
    t = _norm(texto)
    validas = piezas.CATALOGO[nombre]["medidas"]
    m = {}

    # --- cosas con nombre propio ---
    if nombre == "soporte_servo":
        for modelo in sorted(piezas.SERVOS, key=len, reverse=True):
            if re.search(rf"\b{modelo}\b", t.replace(" ", "")) or modelo in t.replace("-", "").replace(" ", ""):
                m["modelo"] = modelo
                t = t.replace(modelo, " ")
                break
    if "dientes" in validas:
        r = re.search(rf"{_NUM} dientes", t)
        if r:
            m["dientes"] = float(r.group(1).replace(",", "."))
            t = _quitar(t, r.span())
    if "rayos" in validas:
        r = re.search(rf"(?:{_NUM} rayos|sin rayos|maciza)", t)
        if r:
            m["rayos"] = float(r.group(1).replace(",", ".")) if r.group(1) else 0
            t = _quitar(t, r.span())
    # tornillo métrico: "para tornillo de 3", "m3"
    r = re.search(rf"(?:para )?(?:tornillos?|pernos?) (?:de |del )?(?:m ?)?{_NUM}|\bm ?(2\.5|2,5|[234568])\b", t)
    if r:
        numero = (r.group(1) or r.group(2)).replace(",", ".")
        diametro = _METRICA.get(numero.rstrip("0").rstrip(".") if "." in numero else numero, float(numero) + 0.2)
        for clave in ("agujero", "diametro_agujero"):
            if clave in validas:
                m[clave] = diametro
        t = _quitar(t, r.span())
    # "con 4 agujeros de 3"
    r = re.search(rf"(?:con )?{_NUM} agujeros?(?: de {_NUM}{_UNIDAD})?", t)
    if r and "agujeros_largo" in validas:
        n = int(float(r.group(1).replace(",", ".")))
        reparto = {0: (0, 0), 1: (1, 1), 2: (2, 1), 3: (3, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3), 12: (4, 3)}
        m["agujeros_largo"], m["agujeros_ancho"] = reparto.get(n, (max(1, n // 2), 2 if n > 3 else 1))
        if r.group(2):
            m["diametro_agujero"] = _valor(r.group(2), r.group(3))
        t = _quitar(t, r.span())
    r = re.search(rf"sin agujeros?|(?:con )?(?:un )?agujeros? (?:central |del eje |para el eje |de eje )?de {_NUM}{_UNIDAD}", t)
    if r:
        valor = _valor(r.group(1), r.group(2)) if r.group(1) else 0.0
        for clave in ("agujero", "diametro_agujero"):
            if clave in validas:
                m[clave] = valor
        if not r.group(1) and "agujeros_largo" in validas:
            m["agujeros_largo"] = m["agujeros_ancho"] = 0
        t = _quitar(t, r.span())
    # interruptores
    for clave, si, no in (("tapa", r"con (?:su |una )?tapa", r"sin tapa"), ("postes", r"con postes", r"sin postes"),
                          ("hexagonal", r"hexagonal|hexagono", r"redondo"),
                          ("refuerzo", r"con refuerzos?|reforzada", r"sin refuerzos?"),
                          ("drenaje", r"con drenaje|con huecos de drenaje", r"sin drenaje")):
        if clave in validas:
            if re.search(no, t):
                m[clave] = 0
            elif re.search(si, t):
                m[clave] = 3 if clave == "drenaje" else 1

    # --- medidas con nombre: "40 de largo", "alto de 30", "pared 2" ---
    for clave, patron in _NOMBRES:
        if clave not in validas:
            continue
        r = (re.search(rf"{_NUM}{_UNIDAD} (?:de |del )?(?:{patron})\b", t)
             or re.search(rf"\b(?:{patron})(?: de| del| en| a| =|:)? {_NUM}{_UNIDAD}", t))
        if r:
            m.setdefault(clave, _valor(r.group(1), r.group(2)))
            t = _quitar(t, r.span())

    # --- números sueltos: "80x50x30", "de 20 por 50", "de 30" ---
    sueltos = []
    r = re.search(rf"{_NUM}{_UNIDAD}\s*(?:x|por)\s*{_NUM}{_UNIDAD}(?:\s*(?:x|por)\s*{_NUM}{_UNIDAD})?", t)
    if r:
        g = r.groups()
        unidad = g[5] or g[3] or g[1]                  # "8x5x3 cm": la unidad del final vale para todos
        sueltos = [_valor(g[i], g[i + 1] or unidad) for i in (0, 2, 4) if g[i]]
    else:
        sueltos = [_valor(a, b) for a, b in re.findall(rf"(?:de|del) {_NUM}{_UNIDAD}(?= |$)", t)]
    libres = [c for c in _ORDEN.get(nombre, []) if c not in m]
    for clave, valor in zip(libres, sueltos):
        m[clave] = valor
    return m


def explicar_medidas(nombre, medidas):
    """'largo 80, ancho 50, alto 30 mm' (solo las que no son interruptores en cero)."""
    partes = []
    for clave, valor in medidas.items():
        if isinstance(valor, str):
            partes.append(valor.upper())
        elif clave in ("tapa", "postes", "hexagonal", "refuerzo"):
            if valor:
                partes.append({"tapa": "con tapa", "postes": "con postes", "hexagonal": "hexagonal", "refuerzo": "con refuerzos"}[clave])
        elif clave in ("dientes", "rayos", "agujeros_largo", "agujeros_ancho", "drenaje"):
            if valor:
                partes.append(f"{clave.replace('_', ' ')} {valor:g}")
        elif clave == "inclinacion":
            partes.append(f"inclinación {valor:g}°")
        elif valor:
            partes.append(f"{clave.replace('_', ' ')} {valor:g}")
    return ", ".join(partes)


# ------------------------------------------------------------------
# Crear y modificar
# ------------------------------------------------------------------

def crear_del_catalogo(nombre, medidas, alias=None, como=None):
    """Fabrica y guarda. Devuelve (nombre de archivo, malla, medidas, notas)."""
    medidas = dict(_PREAJUSTES.get(alias or "", {}), **medidas)
    malla, finales, notas = piezas.construir(nombre, medidas)
    archivo = como or nombre_libre(alias.replace(" ", "_") if alias else nombre)
    guardar(archivo, malla, {"pieza": nombre, "medidas": finales, "alias": alias or nombre})
    return archivo, malla, finales, notas


_CAMBIOS = [
    (r"mas (?:alt[ao]|elevad[ao])", ["alto"], 1), (r"mas (?:baj[ao]|bajit[ao]|cort[ao] de alto)", ["alto"], -1),
    (r"mas larg[ao]", ["largo", "profundidad", "alto"], 1), (r"mas cort[ao]", ["largo", "profundidad", "alto"], -1),
    (r"mas anch[ao]", ["ancho", "diametro"], 1), (r"mas (?:angost[ao]|estrech[ao])", ["ancho", "diametro"], -1),
    (r"mas (?:grues[ao]|resistente|fuerte)", ["grosor", "pared"], 1), (r"mas (?:delgad[ao]|fin[ao])", ["grosor", "pared"], -1),
    (r"mas profund[ao]", ["profundidad", "alto"], 1),
    (r"mas inclinad[ao]", ["inclinacion"], -1), (r"mas (?:parad[ao]|vertical)", ["inclinacion"], 1),
]
_TAMANO = ["largo", "ancho", "alto", "diametro", "interior", "profundidad", "punta"]


def modificar(texto):
    """Cambia la última pieza del catálogo según el texto. Devuelve
    (archivo, malla, medidas, notas, qué cambió) o None si el texto no pide un cambio."""
    actual = ultimo()
    if not actual:
        return None
    receta = leer_receta(actual)
    nombre = receta.get("pieza")
    if nombre not in piezas.CATALOGO:
        return None
    t = _norm(texto)
    medidas = dict(receta.get("medidas") or {})
    validas = piezas.CATALOGO[nombre]["medidas"]
    cambios = []

    fuerza = 1.6 if re.search(r"mucho mas|bastante mas|muy", t) else (1.1 if re.search(r"un poco|poquito|apenas|algo mas", t) else 1.25)
    for patron, claves, sentido in _CAMBIOS:
        if re.search(patron, t):
            clave = next((c for c in claves if c in validas), None)
            if clave:
                factor = fuerza if sentido > 0 else 1 / fuerza
                if clave == "inclinacion":
                    medidas[clave] = medidas.get(clave, 65) + (8 if sentido > 0 else -8)
                else:
                    medidas[clave] = round(float(medidas.get(clave, validas[clave]["defecto"])) * factor, 1)
                cambios.append(clave)
    r = re.search(r"mas (grande|pequen[ao]|chic[ao])|al doble|el doble de grande|a la mitad", t)
    if r and not cambios:
        factor = 2.0 if "doble" in r.group(0) else 0.5 if "mitad" in r.group(0) else (fuerza if r.group(1) == "grande" else 1 / fuerza)
        for clave in _TAMANO:
            if clave in validas and clave in medidas:
                medidas[clave] = round(float(medidas[clave]) * factor, 1)
                cambios.append(clave)
    nuevas = medidas_de(texto, nombre)
    # un número suelto sin nombre no es un cambio ("cambia a 50" no dice qué): solo valen las medidas con nombre
    explicitas = {c: v for c, v in nuevas.items()
                  if c not in _ORDEN.get(nombre, []) or re.search(rf"\b{c.split('_')[0]}", t)
                  or any(re.search(p, t) for k, p in _NOMBRES if k == c)}
    for clave, valor in explicitas.items():
        medidas[clave] = valor
        cambios.append(clave)
    # interruptores: "ponle tapa", "quítale los postes", "con drenaje"
    for clave, palabra in (("tapa", "tapa"), ("postes", "postes?"), ("refuerzo", "refuerzos?"), ("drenaje", "drenaje"),
                           ("hexagonal", "hexagonal")):
        if clave not in validas:
            continue
        if re.search(rf"(?:quita(?:le)?|sin|saca(?:le)?)(?: la| el| los| las)? {palabra}\b", t):
            medidas[clave] = 0
            cambios.append(clave)
        elif re.search(rf"(?:ponle|pon|agrega(?:le)?|anade(?:le)?|con|que tenga|hazl[ao])(?: una| un| su| los| la| el)? {palabra}\b", t):
            medidas[clave] = 3 if clave == "drenaje" else 1
            cambios.append(clave)
    if not cambios:
        return None
    malla, finales, notas = piezas.construir(nombre, medidas)
    guardar(actual, malla, {"pieza": nombre, "medidas": finales, "alias": receta.get("alias", nombre)})
    return actual, malla, finales, notas, sorted(set(cambios))


# ------------------------------------------------------------------
# Piezas libres: la IA arma una receta con formas básicas
# ------------------------------------------------------------------

_SISTEMA = """Eres un diseñador de piezas para impresión 3D. Respondes SOLO con un objeto JSON (sin texto, sin ```).
El JSON es un árbol de formas. Medidas en milímetros. Z es hacia arriba.

FORMAS (nacen centradas en X e Y, apoyadas en Z=0):
  {"tipo":"caja","medidas":[x,y,z]}
  {"tipo":"cilindro","diametro":d,"alto":h}          (eje vertical)
  {"tipo":"esfera","diametro":d}
  {"tipo":"cono","diametro":d,"punta":d2,"alto":h}   (punta 0 = cono completo)
  {"tipo":"prisma","lados":n,"diametro":d,"alto":h}  (6 lados = hexágono)
  {"tipo":"extrusion","puntos":[[x,y],...],"alto":h} (contorno 2D levantado en Z)
OPERACIONES:
  {"tipo":"union","de":[...]}        une las partes
  {"tipo":"diferencia","de":[A,B,C]} a A le resta B y C (para agujeros y huecos)
  {"tipo":"interseccion","de":[...]}
  {"tipo":"envolvente","de":[...]}   cáscara convexa que envuelve las partes (formas redondeadas)
EN CUALQUIER NODO (se aplican en este orden): "escalar":[x,y,z], "espejo":"x", "rotar":[rx,ry,rz] en grados, "mover":[x,y,z]

REGLAS: pieza de UNA sola parte conectada, base plana apoyada en Z=0, paredes de 2 mm o más,
sin partes flotando, voladizos de menos de 45 grados si se puede. Los agujeros deben atravesar
(haz el cilindro que resta más largo que la pieza). Tamaño razonable para el objeto pedido.

EJEMPLO. Pedido: "un llavero redondo de 40 mm con agujero para la argolla"
{"tipo":"diferencia","de":[{"tipo":"cilindro","diametro":40,"alto":3},{"tipo":"cilindro","diametro":5,"alto":10,"mover":[0,15,-2]}]}

EJEMPLO. Pedido: "un soporte para audifonos de escritorio"
{"tipo":"union","de":[{"tipo":"cilindro","diametro":90,"alto":6},{"tipo":"caja","medidas":[14,20,200]},{"tipo":"envolvente","de":[{"tipo":"cilindro","diametro":20,"alto":50,"rotar":[90,0,0],"mover":[0,25,200]},{"tipo":"caja","medidas":[14,20,10],"mover":[0,0,190]}]}]}
"""


def _preguntar_ia(pedido):
    """Le pide la receta a la nube (si está conectada) o a Ollama. Devuelve el texto de la respuesta."""
    mensaje = f'Pedido: "{pedido}"\nResponde solo con el JSON.'
    try:
        from core.IA import nube
        if nube.disponible():
            return nube.responder([{"role": "user", "content": mensaje}], sistema=_SISTEMA, max_tokens=1800, temperature=0.2)
    except Exception:
        pass
    from core.IA import ollamaIA
    return ollamaIA.generar_codigo(_SISTEMA + "\n" + mensaje, num_predict=1400, temperature=0.2)


def _json_de(texto):
    texto = str(texto or "")
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        raise ValueError("la IA no devolvió una receta")
    return json.loads(texto[inicio:fin + 1])


def crear_libre(pedido, preguntar=None):
    """Pieza que no está en el catálogo. Devuelve (archivo, malla, receta).
    Intenta dos veces: si la primera receta no arma, le cuenta el error a la IA."""
    preguntar = preguntar or _preguntar_ia
    error, extra = None, ""
    for _ in range(2):
        try:
            respuesta = preguntar(pedido + extra)
            receta = _json_de(respuesta)
            malla = piezas.desde_receta(receta)
            if malla.volumen() < 1.0:
                raise ValueError("la pieza salió sin volumen")
            if max(malla.dimensiones()) > 1000:
                raise ValueError("la pieza salió de más de un metro")
            archivo = nombre_libre("_".join(_norm(pedido).split()[:4]) or "pieza")
            guardar(archivo, malla, {"receta": receta, "pedido": pedido})
            return archivo, malla, receta
        except (ValueError, KeyError, TypeError) as e:
            error = e
            extra = f"\n(Tu receta anterior falló: {e}. Corrígela y responde solo con el JSON.)"
    raise ValueError(f"No logré armar esa pieza ({error}).")
