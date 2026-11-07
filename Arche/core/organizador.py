# Ruta: Arche/core/organizador.py
r"""
organizador.py
--------------
Arché ordena los archivos del PC en un ÁRBOL de carpetas, leyendo lo que
dice cada archivo (no solo el título), y te pregunta cuando no está segura.

El árbol (se guarda en Database/organizador_arbol.json y lo puedes editar):

    Documentos\                        <- la raíz (se puede cambiar)
    ├── Universidad\
    │   ├── Cálculo\
    │   │   ├── Parciales y quices\
    │   │   ├── Talleres\
    │   │   ├── Apuntes\
    │   │   └── Laboratorios\
    │   ├── Programación C++\ ...
    │   └── ...
    ├── Proyectos\
    │   ├── Robótica\  (Robot sumo, Perro robótico, Line follower)
    │   └── Arché\
    ├── Personal\  (Hoja de vida, Trabajo, Recibos y facturas)
    ├── Multimedia\  (Capturas\2026\11, Fotos\2026, Videos, Música...)
    ├── Programas\  (Instaladores, Comprimidos...)
    └── Código\  (Python, C y C++, Arduino, Web)

Cómo decide dónde va un archivo:
  1. Fotos, videos, música, instaladores y comprimidos: por su tipo y fecha.
  2. Documentos y código: LEE el contenido (PDF, Word, PowerPoint, Excel,
     texto, código) y lo combina con el nombre. Baja por el árbol nivel por
     nivel: primero elige la rama (Universidad), luego la materia (Cálculo),
     luego el tipo (Talleres), mientras esté segura.
  3. Si no está segura (no encontró tema, o dos ramas empatan), NO lo mueve:
     lo anota y TE PREGUNTA, con sugerencias y un pedacito de lo que leyó.
     Lo que le respondes lo APRENDE: la próxima vez, archivos parecidos los
     ordena sola.

Seguridad: no borra nada; las copias idénticas van a "Duplicados para revisar";
todo queda en un historial y se puede deshacer. No toca subcarpetas, archivos
ocultos, descargas a medias, accesos directos del escritorio ni archivos abiertos.

Frases que entiende:
    "ordena mis descargas" / "organiza el escritorio" / "ordena la carpeta C:\\..."
    "pregúntame los archivos" / "archivos pendientes"
    "muéstrame el árbol" / "muestra las categorías"
    "guarda los archivos de física en Universidad/Física"     (regla nueva)
    "guarda el árbol en C:\\Users\\David\\Universidad"          (cambia la raíz)
    "deshaz el orden"
    "pausa el orden automático" / "activa el orden automático" / "orden automático"

Desde terminal (dentro de la carpeta Arche):
    python -m core.organizador descargas            -> muestra el plan (no mueve nada)
    python -m core.organizador arbol                -> dibuja el árbol
"""

import hashlib
import html
import json
import os
import re
import shutil
import threading
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

try:
    from core.rutas import DATABASE
except ImportError:  # por si se corre suelto
    DATABASE = None

# ════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════

DB = Path(DATABASE) if DATABASE else Path(__file__).parent
ARCHIVO_ARBOL = DB / "organizador_arbol.json"      # el árbol con sus palabras clave
ARCHIVO_ESTADO = DB / "organizador.json"           # raíz, pendientes, modo automático
CARPETA_HISTORIAL = DB / "organizador_historial"   # para "deshaz el orden"

# Carpetas que Arché vigila y ordena sola: "descargas", "escritorio",
# "documentos", "imagenes", o una ruta completa como r"C:\Users\David\Universidad".
CARPETAS_AUTOMATICAS = ["descargas"]
REVISAR_CADA_SEGUNDOS = 30
SEGUNDOS_MINIMOS_SIN_CAMBIOS = 120   # no tocar lo que se acaba de bajar/guardar

CARPETA_DUPLICADOS = "Duplicados para revisar"


def _n(palabras=(), hijos=None):
    return {"palabras": list(palabras), "hijos": hijos or {}}


def _sub_materia():
    """Subcarpetas que tiene cada materia."""
    return {
        "Parciales y quices": _n(["parcial", "examen", "quiz", "quices", "evaluacion", "previo"]),
        "Talleres": _n(["taller", "ejercicios", "guia de ejercicios", "actividad", "tarea"]),
        "Apuntes": _n(["apuntes", "clase", "notas de clase", "resumen", "teoria"]),
        "Laboratorios": _n(["laboratorio", "practica de laboratorio", "informe de laboratorio", "montaje"]),
    }


# Palabras en minúscula y sin tildes. Cada carpeta "hereda" las palabras de
# sus hijas: un PDF que habla de derivadas llega a Universidad aunque no diga
# "universidad".
ARBOL_INICIAL = {
    "Universidad": _n(["universidad", "semestre", "docente", "profesor", "asignatura", "facultad", "estudiante"], {
        "Cálculo": _n(["calculo", "derivada", "derivadas", "limite", "limites", "integral", "continuidad",
                       "recta tangente", "regla de la cadena"], _sub_materia()),
        "Programación C++": _n(["c++", "cpp", "iostream", "cout", "cin", "#include", "algoritmo",
                                "programacion"], _sub_materia()),
        "Matemática Discreta": _n(["discreta", "conjuntos", "combinatoria", "diagrama de venn", "permutacion",
                                   "permutaciones", "combinaciones", "inclusion exclusion"], _sub_materia()),
        "Electrónica y Lógica digital": _n(["electronica", "circuito", "compuerta", "compuertas", "protoboard",
                                            "logica digital", "resistencia", "voltaje", "transistor",
                                            "flip flop", "karnaugh", "tabla de verdad"], _sub_materia()),
        "Paradigmas de programación": _n(["paradigma", "paradigmas", "programacion funcional",
                                          "orientada a objetos", "programacion estructurada"], _sub_materia()),
        "Idiomas": _n([], {
            "Inglés": _n(["ingles", "english", "vocabulary", "grammar"]),
            "Italiano": _n(["italiano", "italian"]),
            "Portugués": _n(["portugues", "portuguese"]),
        }),
    }),
    "Proyectos": _n([], {
        "Robótica": _n(["robot", "servo", "servomotor", "esp32", "arduino", "sensor ultrasonico", "motor dc"], {
            "Robot sumo": _n(["sumo", "l298n", "hc sr04", "hc-sr04"]),
            "Perro robótico": _n(["perro", "cuadrupedo", "pata", "patas"]),
            "Line follower": _n(["line follower", "seguidor de linea"]),
        }),
        "Arché": _n(["arche", "arch-ia", "ollama", "supabase", "asistente"]),
    }),
    "Personal": _n([], {
        "Hoja de vida": _n(["hoja de vida", "curriculum", "experiencia laboral", "perfil profesional",
                            "referencias personales"]),
        "Trabajo": _n(["vacante", "entrevista", "contrato laboral", "empleo", "postulacion"]),
        "Recibos y facturas": _n(["factura", "recibo", "total a pagar", "nit", "comprobante de pago"]),
    }),
}

# Tipos que van por tipo/fecha (no hace falta leerlos)
EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".ico", ".tiff"}
EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm"}
EXT_AUDIO = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"}
EXT_PROGRAMAS = {
    "Instaladores": {".exe", ".msi", ".apk", ".dmg"},
    "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Imágenes de disco": {".iso", ".img"},
    "Fuentes": {".ttf", ".otf", ".woff", ".woff2"},
}
# Tipos que se LEEN
EXT_CODIGO = {".py": "Python", ".ipynb": "Python", ".c": "C y C++", ".cpp": "C y C++", ".h": "C y C++",
              ".hpp": "C y C++", ".ino": "Arduino", ".html": "Web", ".css": "Web", ".js": "Web",
              ".ts": "Web", ".java": "Java"}
EXT_TEXTO = {".txt", ".md", ".csv", ".json", ".log", ".rtf"} | set(EXT_CODIGO)
EXT_OFFICE = {".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods"}
EXT_DOCUMENTO = EXT_TEXTO | EXT_OFFICE | {".pdf", ".doc", ".ppt", ".xls"}
EXT_3D = {".stl", ".3mf", ".obj", ".gcode", ".step", ".stp", ".f3d", ".blend"}
EXT_CIRCUITOS = {".fzz", ".sch", ".brd", ".kicad_pcb", ".circ", ".dig"}

IGNORAR_EXTENSIONES = {".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload"}
IGNORAR_NOMBRES = {"desktop.ini", "thumbs.db", ".ds_store"}
ACCESOS_DIRECTOS = {".lnk", ".url"}

# Palabras que no sirven para aprender (muy comunes)
_VACIAS = set("""
el la los las un una unos unas de del al a en y o u que se por para con sin sobre entre como mas
pero sus su es son fue ser esta este esto estos estas ese esa eso lo le les ya muy tambien cuando
donde porque si no ni hay todo todos toda todas cada otro otra otros otras puede pueden debe
final version copia documento archivo nuevo nueva trabajo informe notas apuntes tarea entrega
the and for with this that from
""".split())

_lock = threading.RLock()


# ════════════════════════════════════════════════════════════════════
# Guardar / cargar
# ════════════════════════════════════════════════════════════════════

def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir_json(ruta: Path, datos):
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ruta)
    except OSError:
        pass


def cargar_arbol() -> dict:
    with _lock:
        arbol = _leer_json(ARCHIVO_ARBOL, None)
        if not arbol:
            arbol = json.loads(json.dumps(ARBOL_INICIAL))
            _escribir_json(ARCHIVO_ARBOL, arbol)
        return arbol


def guardar_arbol(arbol: dict):
    with _lock:
        _escribir_json(ARCHIVO_ARBOL, arbol)


def _estado() -> dict:
    with _lock:
        e = _leer_json(ARCHIVO_ESTADO, {})
        e.setdefault("automatico", True)
        e.setdefault("raiz", None)
        e.setdefault("pendientes", {})   # ruta -> {sugerencias, resumen}
        e.setdefault("dejar", [])        # rutas que me pediste no mover
        return e


def _guardar_estado(e: dict):
    with _lock:
        _escribir_json(ARCHIVO_ESTADO, e)


def carpetas_conocidas() -> dict:
    """Descargas, Escritorio, Documentos, Imágenes (detecta si OneDrive las movió)."""
    casa = Path.home()
    onedrive = Path(os.environ.get("OneDrive", casa / "OneDrive"))
    opciones = {
        "descargas": [casa / "Downloads", casa / "Descargas"],
        "escritorio": [onedrive / "Escritorio", onedrive / "Desktop", casa / "Desktop", casa / "Escritorio"],
        "documentos": [onedrive / "Documentos", onedrive / "Documents", casa / "Documents", casa / "Documentos"],
        "imagenes": [onedrive / "Imágenes", onedrive / "Pictures", casa / "Pictures", casa / "Imágenes"],
    }
    return {k: next((p for p in v if p.is_dir()), v[-1]) for k, v in opciones.items()}


def _resolver(carpeta) -> Path:
    return carpetas_conocidas().get(str(carpeta).lower(), Path(str(carpeta)).expanduser())


def raiz() -> Path:
    """Dónde vive el árbol. Por defecto: tu carpeta Documentos."""
    r = _estado().get("raiz")
    return Path(r) if r else carpetas_conocidas()["documentos"]


# ════════════════════════════════════════════════════════════════════
# Leer el contenido de los archivos
# ════════════════════════════════════════════════════════════════════

MAX_CARACTERES = 40000
_aviso_pdf = {"dado": False}


def _sin_etiquetas(xml: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", xml))


def _leer_office(ruta: Path) -> str:
    """docx, pptx, xlsx, odt... son .zip con XML adentro: no necesita librerías."""
    ext = ruta.suffix.lower()
    partes = []
    with zipfile.ZipFile(ruta) as z:
        nombres = z.namelist()
        if ext == ".docx":
            elegidos = ["word/document.xml"]
        elif ext == ".pptx":
            elegidos = sorted((n for n in nombres if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                              key=lambda n: int(re.findall(r"\d+", n)[-1]))[:20]
        elif ext == ".xlsx":
            elegidos = ["xl/sharedStrings.xml"]
        else:
            elegidos = ["content.xml"]
        for n in elegidos:
            if n in nombres:
                partes.append(_sin_etiquetas(z.read(n)[:3_000_000].decode("utf-8", "ignore")))
    return " ".join(partes)


def _leer_pdf(ruta: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            if not _aviso_pdf["dado"]:
                _aviso_pdf["dado"] = True
                print("Arché: Para leer PDFs me falta 'pypdf' (pip install pypdf). "
                      "Mientras tanto los ordeno solo por el nombre.")
            return ""
    lector = PdfReader(str(ruta))
    if getattr(lector, "is_encrypted", False):
        return ""
    return " ".join((p.extract_text() or "") for p in lector.pages[:8])


def leer_contenido(ruta: Path) -> str:
    """Texto del archivo (las primeras páginas). Si no se puede leer, devuelve ''."""
    ext = ruta.suffix.lower()
    try:
        if ext in EXT_TEXTO:
            with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
                texto = f.read(200_000)
        elif ext in EXT_OFFICE:
            texto = _leer_office(ruta)
        elif ext == ".pdf":
            texto = _leer_pdf(ruta)
        else:
            return ""
    except Exception:
        return ""
    return " ".join(texto.split())[:MAX_CARACTERES]


# ════════════════════════════════════════════════════════════════════
# Clasificar
# ════════════════════════════════════════════════════════════════════

def _norm(texto: str) -> str:
    """minúsculas, sin tildes, separadores como espacios."""
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[_\-.]+", " ", texto)
    return " ".join(texto.split())


@lru_cache(maxsize=4096)
def _patron(palabra: str):
    p = re.escape(_norm(palabra))
    return re.compile(rf"(?<![a-z0-9]){p}(?![a-z0-9])")


def _todas_las_palabras(nodo: dict) -> list:
    palabras = list(nodo.get("palabras", []))
    for hijo in nodo.get("hijos", {}).values():
        palabras += _todas_las_palabras(hijo)
    return palabras


def _puntuar(hijos: dict, nombre: str, contenido: str) -> list:
    """[(puntos, nombre_hijo, palabras_encontradas)] de mayor a menor."""
    resultado = []
    for nom_hijo, nodo in hijos.items():
        puntos, encontradas = 0, []
        for palabra in set(_todas_las_palabras(nodo)):
            pat = _patron(palabra)
            if pat.search(nombre):
                puntos += 3
                encontradas.append(palabra)
            elif contenido:
                veces = len(pat.findall(contenido))
                if veces:
                    puntos += 1 + (1 if veces >= 3 else 0)
                    encontradas.append(palabra)
        resultado.append((puntos, nom_hijo, encontradas))
    resultado.sort(key=lambda x: -x[0])
    return resultado


def _bajar(hijos: dict, nombre: str, contenido: str, primer_umbral: int = 3) -> tuple:
    """Baja por el árbol mientras esté segura. Devuelve (camino, palabras, empate)."""
    camino, palabras, umbral, empate = [], [], primer_umbral, []
    while hijos:
        puntos = _puntuar(hijos, nombre, contenido)
        mejor = puntos[0]
        segundo = puntos[1][0] if len(puntos) > 1 else 0
        if mejor[0] >= umbral and mejor[0] > segundo:
            camino.append(mejor[1])
            palabras += mejor[2]
            hijos = hijos[mejor[1]].get("hijos", {})
            umbral = 2 if len(camino) < 2 else 1   # en subcarpetas (Talleres, Apuntes...) basta una pista
        else:
            if not camino:
                empate = [p for p in puntos if p[0] > 0][:3]
            break
    return camino, palabras, empate


def _fecha(ruta: Path) -> datetime:
    return datetime.fromtimestamp(ruta.stat().st_mtime)


def _por_tipo(ruta: Path) -> list | None:
    """Camino para fotos, videos, música, programas... o None si hay que leerlo."""
    ext, nombre, f = ruta.suffix.lower(), ruta.name.lower(), _fecha(ruta)
    anio, mes = f"{f:%Y}", f"{f:%m}"
    if nombre.startswith(("whatsapp image", "whatsapp video", "whatsapp audio")):
        return ["Multimedia", "WhatsApp", anio, mes]
    if ext in EXT_IMAGEN:
        if nombre.startswith(("captura de pantalla", "screenshot", "recorte")):
            return ["Multimedia", "Capturas", anio, mes]
        if nombre.startswith(("img_", "img-", "dsc", "pxl_")):
            return ["Multimedia", "Fotos", anio]
        return ["Multimedia", "Imágenes", anio]
    if ext in EXT_VIDEO:
        return ["Multimedia", "Videos", anio]
    if ext in EXT_AUDIO:
        return ["Multimedia", "Música y audio"]
    for carpeta, exts in EXT_PROGRAMAS.items():
        if ext in exts:
            return ["Programas", carpeta]
    return None


def clasificar(ruta: Path, arbol: dict) -> dict:
    """
    Decide dónde va un archivo. Devuelve:
      {"camino": [...], "seguro": bool, "motivo": str, "sugerencias": [[...], ...], "resumen": str}
    """
    tipo = _por_tipo(ruta)
    if tipo:
        return {"camino": tipo, "seguro": True, "motivo": "tipo y fecha", "sugerencias": [], "resumen": ""}

    ext = ruta.suffix.lower()
    texto = leer_contenido(ruta) if ext in EXT_DOCUMENTO else ""
    nombre, contenido = _norm(ruta.stem), _norm(texto)
    camino, palabras, empate = _bajar(arbol, nombre, contenido)

    if camino:
        motivo = ("leí " if contenido else "el nombre dice ") + ", ".join(f"'{p}'" for p in palabras[:4])
        return {"camino": camino, "seguro": True, "motivo": motivo, "sugerencias": [], "resumen": ""}

    # Sin tema: código, 3D y circuitos tienen carpeta propia
    if ext in EXT_CODIGO:
        return {"camino": ["Código", EXT_CODIGO[ext]], "seguro": True, "motivo": f"código {ext}",
                "sugerencias": [], "resumen": ""}
    if ext in EXT_3D:
        return {"camino": ["Proyectos", "Modelos 3D"], "seguro": True, "motivo": "modelo 3D",
                "sugerencias": [], "resumen": ""}
    if ext in EXT_CIRCUITOS:
        return {"camino": ["Proyectos", "Circuitos"], "seguro": True, "motivo": "circuito",
                "sugerencias": [], "resumen": ""}
    if ext not in EXT_DOCUMENTO:
        return {"camino": ["Otros"], "seguro": True, "motivo": "tipo no reconocido",
                "sugerencias": [], "resumen": ""}

    # Documento sin tema claro -> preguntar, con sugerencias
    sugerencias = []
    for _, rama, _ in empate:
        sub, _, _ = _bajar(arbol[rama].get("hijos", {}), nombre, contenido, primer_umbral=1)
        sugerencias.append([rama] + sub)
    motivo = "dos temas empatan" if len(empate) > 1 else ("no reconocí el tema" if contenido
                                                          else "no pude leer el contenido")
    return {"camino": None, "seguro": False, "motivo": motivo, "sugerencias": sugerencias,
            "resumen": texto[:180]}


# ════════════════════════════════════════════════════════════════════
# Aprender de tus respuestas
# ════════════════════════════════════════════════════════════════════

def _nodo(arbol: dict, camino: list, crear: bool = False) -> dict | None:
    hijos, nodo = arbol, None
    for parte in camino:
        if parte not in hijos:
            if not crear:
                return None
            hijos[parte] = _n()
        nodo = hijos[parte]
        hijos = nodo.setdefault("hijos", {})
    return nodo


def _palabras_distintivas(nombre: str, contenido: str) -> list:
    del_nombre = [w for w in nombre.split() if len(w) >= 4 and w.isalpha() and w not in _VACIAS][:3]
    cuenta = Counter(w for w in re.findall(r"[a-z]{5,}", contenido) if w not in _VACIAS)
    del_texto = [w for w, c in cuenta.most_common(6) if c >= 3][:4]
    return list(dict.fromkeys(del_nombre + del_texto))


def aprender(camino: list, ruta_archivo: Path | None = None, palabras=None):
    """Crea la carpeta en el árbol (si no existe) y le agrega palabras clave."""
    with _lock:
        arbol = cargar_arbol()
        nodo = _nodo(arbol, camino, crear=True)
        nuevas = list(palabras or [])
        if ruta_archivo is not None:
            nuevas += _palabras_distintivas(_norm(ruta_archivo.stem), _norm(leer_contenido(ruta_archivo)))
        agregadas = []
        for p in nuevas:
            p = _norm(p)
            if p and p not in nodo["palabras"]:
                nodo["palabras"].append(p)
                agregadas.append(p)
        guardar_arbol(arbol)
        return agregadas


# ════════════════════════════════════════════════════════════════════
# Plan, mover, deshacer
# ════════════════════════════════════════════════════════════════════

def _hash(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while bloque := f.read(1024 * 1024):
            h.update(bloque)
    return h.hexdigest()


def _nombre_libre(destino: Path) -> Path:
    if not destino.exists():
        return destino
    n = 2
    while True:
        candidato = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def _ignorar(ruta: Path, es_escritorio: bool, estado: dict) -> bool:
    nombre, ext = ruta.name.lower(), ruta.suffix.lower()
    if nombre.startswith((".", "~$")) or nombre in IGNORAR_NOMBRES or ext in IGNORAR_EXTENSIONES:
        return True
    if es_escritorio and ext in ACCESOS_DIRECTOS:
        return True
    if str(ruta) in estado["dejar"] or str(ruta) in estado["pendientes"]:
        return True  # ya te pregunté por él / me dijiste que lo deje
    try:
        return time.time() - ruta.stat().st_mtime < SEGUNDOS_MINIMOS_SIN_CAMBIOS
    except OSError:
        return True


def crear_plan(carpeta) -> dict:
    """Mira los archivos sueltos de la carpeta y decide. No mueve nada."""
    carpeta = Path(carpeta).expanduser().resolve()
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {carpeta}")
    estado, arbol, base = _estado(), cargar_arbol(), raiz()
    es_escritorio = carpeta.name.lower() in ("desktop", "escritorio")
    archivos = [r for r in carpeta.iterdir() if r.is_file() and not _ignorar(r, es_escritorio, estado)]

    # duplicados (mismo contenido): solo compara archivos del mismo tamaño
    duplicados, por_tamano = set(), defaultdict(list)
    for r in archivos:
        por_tamano[r.stat().st_size].append(r)
    for grupo in (g for g in por_tamano.values() if len(g) > 1):
        por_hash = defaultdict(list)
        for r in grupo:
            try:
                por_hash[_hash(r)].append(r)
            except OSError:
                pass
        for iguales in (v for v in por_hash.values() if len(v) > 1):
            iguales.sort(key=lambda r: (r.stat().st_mtime, len(r.name)))
            duplicados.update(iguales[1:])

    movimientos, dudas = [], []
    for r in sorted(archivos, key=lambda x: x.name.lower()):
        if r in duplicados:
            movimientos.append({"origen": str(r), "camino": [CARPETA_DUPLICADOS],
                                "destino": str(base / CARPETA_DUPLICADOS / r.name),
                                "motivo": "copia idéntica de otro archivo"})
            continue
        d = clasificar(r, arbol)
        if d["seguro"]:
            movimientos.append({"origen": str(r), "camino": d["camino"],
                                "destino": str(base.joinpath(*d["camino"]) / r.name), "motivo": d["motivo"]})
        else:
            dudas.append({"origen": str(r), "sugerencias": d["sugerencias"],
                          "resumen": d["resumen"], "motivo": d["motivo"]})
    return {"carpeta": str(carpeta), "movimientos": movimientos, "dudas": dudas}


def _mover(lista: list) -> tuple:
    """Mueve [(origen, destino)] y guarda el lote en el historial. Devuelve (hechos, errores)."""
    hechos, errores = [], []
    for origen, destino in lista:
        origen = Path(origen)
        if not origen.exists():
            continue
        destino = _nombre_libre(Path(destino))
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
            hechos.append({"origen": str(origen), "destino": str(destino)})
        except OSError as e:
            errores.append(f"{origen.name} ({e.__class__.__name__}, ¿está abierto?)")
    if hechos:
        CARPETA_HISTORIAL.mkdir(parents=True, exist_ok=True)
        nombre = f"orden_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        _escribir_json(CARPETA_HISTORIAL / nombre, hechos)
    return hechos, errores


def aplicar_plan(plan: dict) -> str:
    hechos, errores = _mover([(m["origen"], m["destino"]) for m in plan["movimientos"]])
    texto = f"Moví {len(hechos)} archivos al árbol en {raiz()}."
    if errores:
        texto += f" No pude mover {len(errores)}: " + "; ".join(errores[:4])
    return texto


def deshacer() -> str:
    registros = sorted(CARPETA_HISTORIAL.glob("orden_*.json")) if CARPETA_HISTORIAL.is_dir() else []
    if not registros:
        return "No tengo ningún orden reciente que deshacer."
    ultimo = registros[-1]
    base = raiz()
    devueltos, fallos = 0, 0
    for m in reversed(_leer_json(ultimo, [])):
        actual, original = Path(m["destino"]), Path(m["origen"])
        if actual.exists() and not original.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(actual), str(original))
            devueltos += 1
            padre = actual.parent  # borra solo carpetas del árbol que quedaron vacías
            while padre != base and base in padre.parents and padre.exists() and not any(padre.iterdir()):
                padre.rmdir()
                padre = padre.parent
        else:
            fallos += 1
    ultimo.rename(ultimo.with_suffix(".deshecho"))
    texto = f"Devolví {devueltos} archivos a donde estaban."
    if fallos:
        texto += f" {fallos} ya no estaban donde los dejé, así que no los toqué."
    return texto


# ════════════════════════════════════════════════════════════════════
# Preguntarte por los archivos dudosos
# ════════════════════════════════════════════════════════════════════

def _msg(texto):
    print(f"Arché: {texto}")


def _preguntar(texto) -> str:
    try:
        from core import control_pc
        return control_pc._preguntar(texto)
    except Exception:
        try:
            return input(texto).strip()
        except (EOFError, KeyboardInterrupt):
            return ""


def _partes(texto: str):
    """'Universidad/Física > Talleres' -> ['Universidad', 'Física', 'Talleres']. Ruta absoluta -> Path."""
    texto = texto.strip().strip('"')
    if re.match(r"^[A-Za-z]:[\\/]", texto) or texto.startswith(("/", "\\\\")):
        return Path(texto)
    partes = [p.strip() for p in re.split(r"[\\/>]+", texto) if p.strip()]
    return [p[0].upper() + p[1:] for p in partes]


def _camino_texto(camino) -> str:
    return " / ".join(camino) if isinstance(camino, list) else str(camino)


def agregar_pendientes(dudas: list) -> list:
    """Anota archivos dudosos. Devuelve solo los nuevos."""
    with _lock:
        e = _estado()
        nuevos = [d for d in dudas if d["origen"] not in e["pendientes"]]
        for d in nuevos:
            e["pendientes"][d["origen"]] = {k: d[k] for k in ("sugerencias", "resumen", "motivo")}
        _guardar_estado(e)
        return nuevos


def preguntar_pendientes():
    """Te pregunta, uno por uno, dónde van los archivos que no supe ordenar."""
    e = _estado()
    pendientes = {r: d for r, d in e["pendientes"].items() if Path(r).exists()}
    if not pendientes:
        with _lock:
            e["pendientes"] = {}
            _guardar_estado(e)
        _msg("No tengo archivos pendientes: todo lo que encontré ya está ordenado.")
        return
    _msg(f"Tengo {len(pendientes)} archivo(s) que no sé dónde van. Te pregunto uno por uno.")
    base = raiz()
    for i, (ruta, d) in enumerate(pendientes.items(), start=1):
        archivo = Path(ruta)
        lineas = [f"({i}/{len(pendientes)}) ¿Dónde guardo «{archivo.name}»? ({d.get('motivo', '')})"]
        if d.get("resumen"):
            lineas.append(f"   Lo que leí: “{d['resumen'][:160]}…”")
        for j, s in enumerate(d.get("sugerencias") or [], start=1):
            lineas.append(f"   {j}. {_camino_texto(s)}")
        lineas.append("   Escribe un número, una carpeta (ej: Universidad/Física/Talleres),"
                      " 'saltar', 'dejar' (no lo muevo nunca) o 'parar'.")
        _msg("\n".join(lineas))
        resp = _preguntar("Tú: ")
        r = _norm(resp)

        if r in ("parar", "para", "cancelar", "basta", "despues", "luego"):
            _msg("Listo, paro aquí. Lo que falta te lo pregunto después ('pregúntame los archivos').")
            return
        if r in ("", "saltar", "salta", "siguiente", "no se", "nose"):
            continue
        if r in ("dejar", "dejalo", "no lo muevas", "ahi", "ahi esta bien"):
            with _lock:
                e = _estado()
                e["pendientes"].pop(ruta, None)
                e["dejar"].append(ruta)
                _guardar_estado(e)
            _msg(f"Ok, dejo «{archivo.name}» donde está.")
            continue

        sugerencias = d.get("sugerencias") or []
        if r.isdigit() and 1 <= int(r) <= len(sugerencias):
            destino = sugerencias[int(r) - 1]
        else:
            destino = _partes(resp)
            if not destino:
                _msg("No entendí la carpeta; lo dejo para después.")
                continue

        if isinstance(destino, Path):
            carpeta_final = destino
            aprendidas = []
            if base in destino.parents:
                aprendidas = aprender(list(destino.relative_to(base).parts), archivo)
        else:
            carpeta_final = base.joinpath(*destino)
            aprendidas = aprender(destino, archivo)

        hechos, errores = _mover([(ruta, carpeta_final / archivo.name)])
        with _lock:
            e = _estado()
            e["pendientes"].pop(ruta, None)
            _guardar_estado(e)
        if hechos:
            texto = f"Guardé «{archivo.name}» en {_camino_texto(destino)}."
            if aprendidas:
                texto += f" Aprendí: {', '.join(aprendidas[:5])} → esa carpeta."
            _msg(texto)
        else:
            _msg(f"No pude moverlo: {'; '.join(errores)}")
    _msg("Terminé con los pendientes.")


# ════════════════════════════════════════════════════════════════════
# Dibujar el árbol
# ════════════════════════════════════════════════════════════════════

def _dibujar_disco(carpeta: Path, prefijo="", nivel=0, max_nivel=4, lineas=None):
    lineas = [] if lineas is None else lineas
    try:
        subs = sorted([p for p in carpeta.iterdir() if p.is_dir() and not p.name.startswith(".")],
                      key=lambda p: p.name.lower())
    except OSError:
        return lineas
    visibles = subs[:25]
    for i, sub in enumerate(visibles):
        ultimo = i == len(visibles) - 1 and len(subs) <= 25
        try:
            n = sum(1 for p in sub.iterdir() if p.is_file())
        except OSError:
            n = 0
        cuenta = f"  ({n} archivo{'s' if n != 1 else ''})" if n else ""
        lineas.append(f"{prefijo}{'└── ' if ultimo else '├── '}{sub.name}{cuenta}")
        if nivel + 1 < max_nivel:
            _dibujar_disco(sub, prefijo + ("    " if ultimo else "│   "), nivel + 1, max_nivel, lineas)
    if len(subs) > 25:
        lineas.append(f"{prefijo}└── …y {len(subs) - 25} carpetas más")
    return lineas


def _dibujar_reglas(hijos: dict, prefijo="", lineas=None):
    lineas = [] if lineas is None else lineas
    items = list(hijos.items())
    for i, (nombre, nodo) in enumerate(items):
        ultimo = i == len(items) - 1
        pal = nodo.get("palabras", [])
        extra = f"  [{', '.join(pal[:5])}{'…' if len(pal) > 5 else ''}]" if pal else ""
        lineas.append(f"{prefijo}{'└── ' if ultimo else '├── '}{nombre}{extra}")
        _dibujar_reglas(nodo.get("hijos", {}), prefijo + ("    " if ultimo else "│   "), lineas)
    return lineas


def mostrar_arbol() -> str:
    base = raiz()
    lineas = _dibujar_disco(base)
    if not lineas:
        return f"Todavía no hay carpetas en {base}. Así quedará el árbol:\n{base.name}\n" + \
               "\n".join(_dibujar_reglas(cargar_arbol()))
    return f"{base}\n" + "\n".join(lineas)


def mostrar_categorias() -> str:
    return ("Así decido (carpeta  [palabras que busco en el nombre y en el contenido]):\n"
            + "\n".join(_dibujar_reglas(cargar_arbol()))
            + "\nAdemás: fotos, videos, música y programas van a Multimedia y Programas por tipo y fecha.")


# ════════════════════════════════════════════════════════════════════
# MODO AUTOMÁTICO
# ════════════════════════════════════════════════════════════════════

_detener = threading.Event()
_hilo = None


def ordenar_automatico_una_vez(carpetas=None) -> list:
    """Ordena lo seguro sin preguntar; lo dudoso lo anota para preguntarte. Devuelve avisos."""
    avisos = []
    for c in carpetas or CARPETAS_AUTOMATICAS:
        carpeta = _resolver(c)
        if not carpeta.is_dir():
            continue
        try:
            plan = crear_plan(carpeta)
        except OSError:
            continue
        partes = []
        if plan["movimientos"]:
            hechos, errores = _mover([(m["origen"], m["destino"]) for m in plan["movimientos"]])
            if hechos:
                detalle = [f"  • {Path(m['origen']).name} → {_camino_texto(m['camino'])}"
                           for m in plan["movimientos"][:5]]
                if len(plan["movimientos"]) > 5:
                    detalle.append(f"  • …y {len(plan['movimientos']) - 5} más")
                partes.append(f"Ordené {len(hechos)} archivo(s) de {carpeta.name}:\n" + "\n".join(detalle))
            if errores:
                partes.append(f"No pude mover {len(errores)} (¿abiertos?).")
        nuevos = agregar_pendientes(plan["dudas"])
        if nuevos:
            nombres = ", ".join(Path(d["origen"]).name for d in nuevos[:3])
            partes.append(f"Hay {len(nuevos)} que no sé dónde van ({nombres}). "
                          "Dime 'pregúntame los archivos' cuando puedas.")
        if partes:
            avisos.append("\n".join(partes))
    return avisos


def _bucle(avisar):
    while not _detener.is_set():
        if _estado().get("automatico", True):
            try:
                for aviso in ordenar_automatico_una_vez():
                    avisar(aviso)
            except Exception as e:  # nunca tumbar a Arché por esto
                avisar(f"El organizador tuvo un error: {e}")
        _detener.wait(REVISAR_CADA_SEGUNDOS)


def iniciar(avisar=_msg):
    """Arranca (una sola vez) el hilo que ordena solo. Lo llama main.py al iniciar."""
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    cargar_arbol()  # crea el árbol la primera vez
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, args=(avisar,), name="arche-organizador", daemon=True)
    _hilo.start()


def detener():
    _detener.set()


# ════════════════════════════════════════════════════════════════════
# Comandos (mismo formato que los otros módulos de core/)
# ════════════════════════════════════════════════════════════════════

_ART = r"(?:mis\s+|las\s+|los\s+|el\s+|la\s+|mi\s+)?"
_CARPETAS = {
    "descargas": "descargas", "descarga": "descargas", "downloads": "descargas",
    "escritorio": "escritorio", "desktop": "escritorio",
    "documentos": "documentos", "documents": "documentos",
    "imagenes": "imagenes", "fotos": "imagenes", "pictures": "imagenes",
}
_NOMBRES = "|".join(sorted(_CARPETAS, key=len, reverse=True))

_R_AUTO = re.compile(r"^(?:(activa|enciende|prende|inicia|pausa|desactiva|apaga|deten|detener|para|estado\s+del?)\s+)?"
                     r"(?:el\s+)?orden(?:ado)?\s+automatico$")
_R_DESHACER = re.compile(rf"^(?:deshaz|deshacer|revierte|devuelve)\s+(?:el\s+)?orden(?:\s+(?:de|del|en)\s+{_ART}(?:{_NOMBRES}))?$")
_R_ORDENAR = re.compile(rf"^(?:por\s+favor\s+)?(?:ordena|organiza|acomoda)(?:me)?\s+{_ART}(?:carpeta\s+(?:de\s+)?{_ART})?({_NOMBRES})$")
_R_RUTA = re.compile(r"^(?:por\s+favor\s+)?(?:ordena|organiza|acomoda)(?:me)?\s+(?:la\s+)?carpeta\s+(.+)$", re.I)
_R_PENDIENTES = re.compile(r"^(?:preguntame|pregunta(?:me)?\s+por)\s+(?:los\s+)?archivos(?:\s+pendientes)?$|"
                           r"^(?:mis\s+)?archivos\s+(?:pendientes|sin\s+ordenar|por\s+ordenar|dudosos)$|"
                           r"^donde\s+van\s+los\s+archivos$")
_R_ARBOL = re.compile(r"^(?:muestra(?:me)?|ensena(?:me)?|ver|dibuja(?:me)?)\s+(?:el\s+|mi\s+)?arbol"
                      r"(?:\s+de\s+(?:carpetas|archivos))?$|^(?:mi\s+)?arbol\s+de\s+(?:carpetas|archivos)$")
_R_CATEGORIAS = re.compile(r"^(?:muestra(?:me)?|ver|cuales\s+son)\s+(?:las\s+|mis\s+)?(?:categorias|reglas)"
                           r"(?:\s+(?:del\s+organizador|de\s+orden|del\s+orden))?$|^categorias\s+del\s+organizador$")
_R_REGLA = re.compile(r"^(?:guarda|pon|manda|mueve)\s+(?:siempre\s+)?(?:los\s+)?archivos\s+"
                      r"(?:de|del|sobre|con|que\s+digan)\s+(.+?)\s+en\s+(.+)$", re.I)
_R_RAIZ = re.compile(r"^(?:guarda|pon|crea)\s+(?:el\s+)?[aá]rbol\s+en\s+(.+)$|"
                     r"^(?:cambia|usa)\s+(?:la\s+)?(?:ra[ií]z|carpeta\s+principal)(?:\s+del\s+[aá]rbol)?\s+(?:a|en|por)\s+(.+)$",
                     re.I)


def _limpio(comando):
    t = unicodedata.normalize("NFD", comando.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[¿?¡!.,;]", " ", t).split())


def _confirmar(pregunta):
    try:
        from core import acciones_pc
        return acciones_pc._confirmar(pregunta)
    except Exception:
        return _norm(_preguntar(f"Arché: {pregunta} (s/n)\nTú: ")) in ("s", "si")


def interpretar(comando):
    """(intencion, argumento) o None. No ejecuta nada."""
    t = _limpio(comando)
    if not t:
        return None
    original = comando.strip()
    m = _R_AUTO.match(t)
    if m:
        verbo = m.group(1) or "estado"
        if verbo in ("activa", "enciende", "prende", "inicia"):
            return ("organizador_auto_on", None)
        if verbo.startswith("estado"):
            return ("organizador_auto_estado", None)
        return ("organizador_auto_off", None)
    if _R_DESHACER.match(t):
        return ("organizador_deshacer", None)
    if _R_PENDIENTES.match(t):
        return ("organizador_pendientes", None)
    if _R_ARBOL.match(t):
        return ("organizador_arbol", None)
    if _R_CATEGORIAS.match(t):
        return ("organizador_categorias", None)
    m = _R_RAIZ.match(original)
    if m:
        return ("organizador_raiz", (m.group(1) or m.group(2)).strip().strip('"'))
    m = _R_REGLA.match(original)
    if m:
        return ("organizador_regla", (m.group(1).strip(), m.group(2).strip()))
    m = _R_ORDENAR.match(t)
    if m:
        return ("organizador_ordenar", _CARPETAS[m.group(1)])
    m = _R_RUTA.match(original)
    if m and re.search(r"[\\/:]", m.group(1)):
        return ("organizador_ordenar", m.group(1).strip().strip('"'))
    return None


def _ordenar_con_preguntas(carpeta: Path) -> str:
    try:
        plan = crear_plan(carpeta)
    except FileNotFoundError as e:
        return str(e)
    movs, dudas = plan["movimientos"], plan["dudas"]
    if not movs and not dudas:
        return f"Tu carpeta {carpeta.name} ya está ordenada."
    if movs:
        conteo = Counter(_camino_texto(m["camino"][:2]) for m in movs)
        lineas = [f"En {carpeta.name} encontré {len(movs) + len(dudas)} archivos. "
                  f"Estos {len(movs)} los tengo claros (van a {raiz()}):"]
        for destino, n in conteo.most_common(12):
            ejemplos = [Path(m["origen"]).name for m in movs if _camino_texto(m["camino"][:2]) == destino][:2]
            lineas.append(f"  • {destino}: {n}  (ej: {', '.join(ejemplos)})")
        if dudas:
            lineas.append(f"Y {len(dudas)} no sé dónde van: te pregunto después.")
        _msg("\n".join(lineas))
        if not _confirmar("¿Los muevo?"):
            return "Ok, no muevo nada."
        _msg(aplicar_plan(plan))
    agregar_pendientes(dudas)
    if dudas:
        preguntar_pendientes()
    return "Listo. Si algo no te gusta, dime 'deshaz el orden'."


def manejar(comando):
    """Ejecuta una orden del organizador. (intencion, contenido) o None si no es suya."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual

    if intencion == "organizador_auto_on":
        e = _estado()
        e["automatico"] = True
        _guardar_estado(e)
        iniciar()
        texto = (f"Orden automático activado: reviso {', '.join(CARPETAS_AUTOMATICAS)} cada "
                 f"{REVISAR_CADA_SEGUNDOS} segundos y guardo en {raiz()}.")
    elif intencion == "organizador_auto_off":
        e = _estado()
        e["automatico"] = False
        _guardar_estado(e)
        texto = "Pausé el orden automático. Dime 'activa el orden automático' para volver."
    elif intencion == "organizador_auto_estado":
        e = _estado()
        on = "activado" if e.get("automatico", True) else "en pausa"
        texto = (f"El orden automático está {on}. Vigilo: {', '.join(CARPETAS_AUTOMATICAS)}. "
                 f"El árbol está en {raiz()}. Archivos pendientes de preguntarte: {len(e['pendientes'])}.")
    elif intencion == "organizador_deshacer":
        texto = deshacer()
    elif intencion == "organizador_pendientes":
        preguntar_pendientes()
        return (intencion, "")
    elif intencion == "organizador_arbol":
        texto = mostrar_arbol()
    elif intencion == "organizador_categorias":
        texto = mostrar_categorias()
    elif intencion == "organizador_raiz":
        nueva = _resolver(arg)
        try:
            nueva.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            texto = f"No pude usar esa carpeta: {err}"
        else:
            e = _estado()
            e["raiz"] = str(nueva)
            _guardar_estado(e)
            texto = f"Listo: desde ahora el árbol vive en {nueva}."
    elif intencion == "organizador_regla":
        tema, destino = arg
        camino = _partes(destino)
        if isinstance(camino, Path) or not camino:
            texto = "Dime la carpeta como parte del árbol, por ejemplo: Universidad/Física/Talleres."
        else:
            aprender(camino, palabras=[tema])
            texto = f"Entendido: lo que hable de «{tema}» lo guardo en {_camino_texto(camino)}."
    else:  # organizador_ordenar
        texto = _ordenar_con_preguntas(_resolver(arg))
    _msg(texto)
    return (intencion, texto)


# ════════════════════════════════════════════════════════════════════
# Terminal
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    if sys.argv[1].lower() in ("arbol", "árbol"):
        print(mostrar_arbol())
        sys.exit(0)
    plan = crear_plan(_resolver(sys.argv[1]))
    print(f"Raíz del árbol: {raiz()}\n")
    for m in plan["movimientos"]:
        print(f"  {Path(m['origen']).name:40} -> {_camino_texto(m['camino'])}   ({m['motivo']})")
    for d in plan["dudas"]:
        sug = " | ".join(_camino_texto(s) for s in d["sugerencias"]) or "sin sugerencias"
        print(f"  {Path(d['origen']).name:40} -> ¿? ({d['motivo']}; sugerencias: {sug})")
    print("\n(Esto es solo una vista previa: no moví nada.)")
