# Ruta: Arche/core/organizador.py
"""
organizador.py
--------------
Arché ordena los archivos del PC en carpetas (no al azar: por materia,
proyecto, tipo y fecha) y lo hace SOLA en segundo plano.

Cómo piensa:
  1. Mira SOLO los archivos sueltos de la carpeta (no se mete en subcarpetas,
     así no rompe proyectos, repos de git ni carpetas que ya ordenaste tú).
  2. Clasifica de lo más específico a lo más general:
       a) Nombre -> materia de la U (Cálculo, C++, Discreta...) o proyecto (robots, Arché)
       b) Patrones -> capturas de pantalla, fotos de celular, WhatsApp (por año-mes)
       c) Extensión -> Documentos/PDF, Imágenes, Videos, Código/Python, Modelos 3D...
  3. Copias idénticas (mismo contenido) van a "Duplicados para revisar". NUNCA borra.
  4. Guarda historial de cada movimiento para poder DESHACER.

Modo automático (arranca con Arché): cada 30 s revisa las carpetas de
CARPETAS_AUTOMATICAS y ordena lo nuevo, esperando a que cada archivo lleve
2 minutos sin cambiar (así no toca descargas a medias).

Lo que NO toca: ocultos/del sistema, descargas incompletas, accesos directos
del escritorio, y archivos abiertos (si Windows no deja moverlos, los salta).

Frases que entiende:
    "ordena mis descargas" / "organiza el escritorio" / "ordena mis documentos"
    "ordena la carpeta C:\\Users\\David\\Universidad"
    "deshaz el orden" / "deshaz el orden de descargas"
    "pausa el orden automático" / "activa el orden automático" / "orden automático"

Desde terminal (dentro de la carpeta Arche):
    python -m core.organizador descargas             -> muestra el plan
    python -m core.organizador descargas --aplicar   -> ordena de verdad
    python -m core.organizador descargas --deshacer  -> devuelve todo como estaba
"""

import re
import threading

try:
    from core.rutas import DATABASE
except ImportError:  # por si se corre suelto
    DATABASE = None

import hashlib
import json
import os
import shutil
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN — edita esto a tu gusto
# ════════════════════════════════════════════════════════════════════

# a) Palabras en el NOMBRE del archivo -> carpeta (se revisan primero).
#    Escríbelas en minúscula y sin tildes.
REGLAS_POR_NOMBRE = {
    "Universidad/Cálculo": ["calculo", "derivada", "limite", "integral"],
    "Universidad/Programación C++": ["c++", "cpp", "programacion"],
    "Universidad/Matemática Discreta": ["discreta", "conjunto", "combinatoria", "venn"],
    "Universidad/Electrónica": ["electronica", "circuito", "compuerta", "protoboard", "logica digital"],
    "Universidad/Paradigmas": ["paradigma"],
    "Universidad/Idiomas": ["ingles", "english", "italiano", "portugues"],
    "Proyectos/Robótica": ["robot", "sumo", "servo", "esp32", "arduino", "line follower", "perro"],
    "Proyectos/Arché": ["arche", "arch-ia"],
    "Personal/Hoja de vida": ["hoja de vida", "curriculum", "cv_", "cv "],
}

# Las reglas por nombre solo aplican a estos tipos (para que una foto llamada
# "robot.jpg" vaya a Imágenes y no se mezcle con documentos).
EXT_QUE_USAN_REGLAS_POR_NOMBRE = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md",
    ".odt", ".csv", ".ino", ".py", ".cpp", ".c", ".h", ".hpp", ".zip", ".rar",
    ".stl", ".3mf", ".gcode", ".step", ".stp", ".fzz",
}

# b) Patrones especiales (inicio del nombre) -> carpeta. "{fecha}" = año/mes.
PATRONES = [
    (["captura de pantalla", "screenshot", "recorte"], "Imágenes/Capturas/{fecha}"),
    (["whatsapp image", "whatsapp video", "whatsapp audio"], "WhatsApp/{fecha}"),
    (["img_", "img-", "dsc", "pxl_"], "Imágenes/Fotos/{fecha}"),
    (["vid_", "vid-"], "Videos/{fecha}"),
]

# c) Extensión -> carpeta (lo más general).
REGLAS_POR_EXTENSION = {
    "Documentos/PDF": [".pdf"],
    "Documentos/Word": [".doc", ".docx", ".odt", ".rtf"],
    "Documentos/Presentaciones": [".ppt", ".pptx", ".odp", ".key"],
    "Documentos/Hojas de cálculo": [".xls", ".xlsx", ".ods", ".csv"],
    "Documentos/Texto": [".txt", ".md"],
    "Imágenes": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".ico", ".tiff"],
    "Videos": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm"],
    "Música y audio": [".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"],
    "Código/Python": [".py", ".ipynb"],
    "Código/C y C++": [".c", ".cpp", ".h", ".hpp"],
    "Código/Arduino": [".ino"],
    "Código/Web": [".html", ".css", ".js", ".ts", ".json"],
    "Proyectos/Modelos 3D": [".stl", ".3mf", ".obj", ".gcode", ".step", ".stp", ".f3d", ".blend"],
    "Proyectos/Circuitos": [".fzz", ".sch", ".brd", ".kicad_pcb", ".circ", ".dig"],
    "Instaladores": [".exe", ".msi", ".apk", ".dmg"],
    "Comprimidos": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "Imágenes de disco": [".iso", ".img"],
    "Fuentes": [".ttf", ".otf", ".woff", ".woff2"],
}

CARPETA_DUPLICADOS = "Duplicados para revisar"
CARPETA_OTROS = "Otros"
CARPETA_HISTORIAL = ".arche_historial"

IGNORAR_EXTENSIONES = {".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload"}
IGNORAR_NOMBRES = {"desktop.ini", "thumbs.db", ".ds_store"}
ACCESOS_DIRECTOS = {".lnk", ".url"}
SEGUNDOS_MINIMOS_SIN_CAMBIOS = 120  # no tocar lo que se acaba de bajar/guardar


# ════════════════════════════════════════════════════════════════════
# Utilidades
# ════════════════════════════════════════════════════════════════════

def _normalizar(texto: str) -> str:
    """minúsculas y sin tildes, para comparar nombres."""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.replace("_", " ").replace("-", " ") + " " + texto  # ambas versiones


def _fecha(ruta: Path) -> str:
    return datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%Y-%m")


def _hash(ruta: Path, bloque=1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while chunk := f.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def _nombre_libre(destino: Path) -> Path:
    """Si ya existe 'tarea.pdf', devuelve 'tarea (2).pdf', etc."""
    if not destino.exists():
        return destino
    n = 2
    while True:
        candidato = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def carpetas_conocidas() -> dict:
    """Rutas de Descargas, Escritorio, Documentos (detecta si OneDrive las movió)."""
    casa = Path.home()
    onedrive = Path(os.environ.get("OneDrive", casa / "OneDrive"))
    opciones = {
        "descargas": [casa / "Downloads", casa / "Descargas"],
        "escritorio": [onedrive / "Escritorio", onedrive / "Desktop", casa / "Desktop", casa / "Escritorio"],
        "documentos": [onedrive / "Documentos", onedrive / "Documents", casa / "Documents", casa / "Documentos"],
        "imagenes": [onedrive / "Imágenes", onedrive / "Pictures", casa / "Pictures", casa / "Imágenes"],
    }
    return {k: next((p for p in v if p.is_dir()), v[-1]) for k, v in opciones.items()}


# ════════════════════════════════════════════════════════════════════
# Clasificación
# ════════════════════════════════════════════════════════════════════

def clasificar(ruta: Path) -> tuple[str, str]:
    """Devuelve (carpeta_destino_relativa, motivo)."""
    ext = ruta.suffix.lower()
    nombre = _normalizar(ruta.stem)

    # a) por nombre (materias / proyectos)
    if ext in EXT_QUE_USAN_REGLAS_POR_NOMBRE:
        for carpeta, palabras in REGLAS_POR_NOMBRE.items():
            for p in palabras:
                if p in nombre:
                    return carpeta, f"el nombre contiene '{p}'"

    # b) patrones (capturas, fotos de celular, WhatsApp)
    for prefijos, carpeta in PATRONES:
        if any(ruta.name.lower().startswith(p) for p in prefijos):
            return carpeta.replace("{fecha}", _fecha(ruta)), "patrón de nombre"

    # c) por extensión
    for carpeta, extensiones in REGLAS_POR_EXTENSION.items():
        if ext in extensiones:
            if carpeta == "Imágenes":
                return f"Imágenes/{_fecha(ruta)}", f"extensión {ext}"
            return carpeta, f"extensión {ext}"

    return CARPETA_OTROS, "tipo no reconocido"


def _debe_ignorarse(ruta: Path, es_escritorio: bool) -> str | None:
    nombre = ruta.name.lower()
    ext = ruta.suffix.lower()
    if nombre.startswith(".") or nombre.startswith("~$") or nombre in IGNORAR_NOMBRES:
        return "archivo oculto/del sistema"
    if ext in IGNORAR_EXTENSIONES:
        return "descarga incompleta"
    if es_escritorio and ext in ACCESOS_DIRECTOS:
        return "acceso directo del escritorio"
    if time.time() - ruta.stat().st_mtime < SEGUNDOS_MINIMOS_SIN_CAMBIOS:
        return "modificado hace muy poco"
    return None


# ════════════════════════════════════════════════════════════════════
# Plan, aplicar, deshacer
# ════════════════════════════════════════════════════════════════════

def crear_plan(carpeta: Path) -> dict:
    carpeta = Path(carpeta).expanduser().resolve()
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {carpeta}")
    es_escritorio = carpeta.name.lower() in ("desktop", "escritorio")

    archivos, ignorados = [], []
    for ruta in carpeta.iterdir():
        if not ruta.is_file():
            continue  # las subcarpetas se respetan tal cual
        motivo = _debe_ignorarse(ruta, es_escritorio)
        if motivo:
            ignorados.append({"archivo": ruta.name, "motivo": motivo})
        else:
            archivos.append(ruta)

    # Duplicados: solo calcula hash entre archivos del mismo tamaño (rápido)
    duplicados = set()
    por_tamano = defaultdict(list)
    for r in archivos:
        por_tamano[r.stat().st_size].append(r)
    for grupo in por_tamano.values():
        if len(grupo) < 2:
            continue
        por_hash = defaultdict(list)
        for r in grupo:
            try:
                por_hash[_hash(r)].append(r)
            except OSError:
                pass
        for iguales in por_hash.values():
            if len(iguales) > 1:
                # conserva el más antiguo y de nombre más corto (sin "(1)")
                iguales.sort(key=lambda r: (r.stat().st_mtime, len(r.name)))
                duplicados.update(iguales[1:])

    movimientos = []
    for r in sorted(archivos, key=lambda x: x.name.lower()):
        if r in duplicados:
            destino_rel, motivo = CARPETA_DUPLICADOS, "copia idéntica de otro archivo"
        else:
            destino_rel, motivo = clasificar(r)
        movimientos.append({
            "origen": str(r),
            "destino": str(carpeta / destino_rel / r.name),
            "categoria": destino_rel,
            "motivo": motivo,
        })

    return {"carpeta": str(carpeta), "movimientos": movimientos, "ignorados": ignorados}


def resumen_plan(plan: dict, detalle: int = 3) -> str:
    movs = plan["movimientos"]
    if not movs:
        return f"La carpeta {plan['carpeta']} ya está ordenada (no hay archivos sueltos que mover)."
    conteo = Counter(m["categoria"].split("/")[0] for m in movs)
    lineas = [f"Encontré {len(movs)} archivos sueltos en {Path(plan['carpeta']).name}. Así los ordenaría:"]
    for cat, n in conteo.most_common():
        ejemplos = [Path(m["origen"]).name for m in movs if m["categoria"].startswith(cat)][:detalle]
        lineas.append(f"  • {cat}: {n}  (ej: {', '.join(ejemplos)})")
    if plan["ignorados"]:
        lineas.append(f"No tocaré {len(plan['ignorados'])} archivos (ocultos, accesos directos o recién modificados).")
    lineas.append("¿Lo aplico? (sí / no)")
    return "\n".join(lineas)


def aplicar_plan(plan: dict) -> str:
    carpeta = Path(plan["carpeta"])
    hechos, errores = [], []
    for m in plan["movimientos"]:
        origen = Path(m["origen"])
        if not origen.exists():
            continue
        destino = _nombre_libre(Path(m["destino"]))
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
            hechos.append({"origen": str(origen), "destino": str(destino)})
        except (PermissionError, OSError) as e:
            errores.append(f"{origen.name}: {e.__class__.__name__} (¿está abierto?)")

    if hechos:
        hist = carpeta / CARPETA_HISTORIAL
        hist.mkdir(exist_ok=True)
        if os.name == "nt":  # ocultar la carpeta de historial en Windows
            os.system(f'attrib +h "{hist}" >nul 2>&1')
        archivo = hist / f"orden_{datetime.now():%Y%m%d_%H%M%S}.json"
        archivo.write_text(json.dumps(hechos, ensure_ascii=False, indent=2), encoding="utf-8")

    texto = f"Listo, moví {len(hechos)} archivos."
    if errores:
        texto += f" No pude mover {len(errores)}: " + "; ".join(errores[:5])
    if hechos:
        texto += " Si algo no te gusta, dime 'deshaz el orden'."
    return texto


def deshacer(carpeta: Path) -> str:
    hist = Path(carpeta).expanduser().resolve() / CARPETA_HISTORIAL
    registros = sorted(hist.glob("orden_*.json")) if hist.is_dir() else []
    if not registros:
        return "No tengo ningún orden reciente que deshacer en esa carpeta."
    ultimo = registros[-1]
    movimientos = json.loads(ultimo.read_text(encoding="utf-8"))
    devueltos, fallos = 0, 0
    for m in reversed(movimientos):
        actual, original = Path(m["destino"]), Path(m["origen"])
        if actual.exists() and not original.exists():
            shutil.move(str(actual), str(original))
            devueltos += 1
            # borra carpetas que quedaron vacías (solo las que creó el orden)
            padre = actual.parent
            while padre != Path(carpeta).resolve() and padre.exists() and not any(padre.iterdir()):
                padre.rmdir()
                padre = padre.parent
        else:
            fallos += 1
    ultimo.rename(ultimo.with_suffix(".deshecho"))
    texto = f"Devolví {devueltos} archivos a su lugar."
    if fallos:
        texto += f" {fallos} ya no estaban donde los dejé (los moviste tú), así que no los toqué."
    return texto


# ════════════════════════════════════════════════════════════════════
# Integración con Arché (lenguaje natural sencillo)
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
# MODO AUTOMÁTICO — vigila carpetas y ordena lo nuevo sola
# ════════════════════════════════════════════════════════════════════

# Carpetas que Arché ordena sola: "descargas", "escritorio", "documentos",
# "imagenes", o una ruta completa como r"C:\Users\David\Universidad".
CARPETAS_AUTOMATICAS = ["descargas"]
REVISAR_CADA_SEGUNDOS = 30

ARCHIVO_ESTADO = (Path(DATABASE) if DATABASE else Path(__file__).parent) / "organizador.json"

_detener = threading.Event()
_hilo = None


def _msg(texto):
    print(f"Arché: {texto}")


def _leer_estado() -> dict:
    try:
        return json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"automatico": True}  # arranca encendido


def _guardar_estado(estado: dict):
    try:
        ARCHIVO_ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVO_ESTADO.write_text(json.dumps(estado), encoding="utf-8")
    except OSError:
        pass


def _resolver(carpeta) -> Path:
    return carpetas_conocidas().get(str(carpeta).lower(), Path(carpeta))


def ordenar_automatico_una_vez(carpetas=None) -> list:
    """Ordena lo nuevo sin preguntar. Devuelve los avisos (vacío si no había nada)."""
    avisos = []
    for c in carpetas or CARPETAS_AUTOMATICAS:
        carpeta = _resolver(c)
        if not carpeta.is_dir():
            continue
        try:
            plan = crear_plan(carpeta)
        except OSError:
            continue
        if not plan["movimientos"]:
            continue
        resultado = aplicar_plan(plan)
        detalle = [f"  • {Path(m['origen']).name} → {m['categoria']}" for m in plan["movimientos"][:5]]
        extra = len(plan["movimientos"]) - 5
        if extra > 0:
            detalle.append(f"  • …y {extra} más")
        avisos.append(f"Ordené {carpeta.name}:\n" + "\n".join(detalle) + f"\n{resultado}")
    return avisos


def _bucle(avisar):
    while not _detener.is_set():
        if _leer_estado().get("automatico", True):
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
_R_DESHACER = re.compile(rf"^(?:deshaz|deshacer|revierte|devuelve)\s+(?:el\s+)?orden(?:\s+(?:de|del|en)\s+{_ART}({_NOMBRES}))?$")
_R_ORDENAR = re.compile(rf"^(?:por\s+favor\s+)?(?:ordena|organiza|acomoda)(?:me)?\s+{_ART}(?:carpeta\s+(?:de\s+)?{_ART})?({_NOMBRES})$")
_R_RUTA = re.compile(r"^(?:por\s+favor\s+)?(?:ordena|organiza|acomoda)(?:me)?\s+(?:la\s+)?carpeta\s+(.+)$", re.IGNORECASE)


def _sin_tildes(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _limpio(comando):
    return " ".join(re.sub(r"[¿?¡!.,;]", " ", _sin_tildes(comando)).split())


def _confirmar(pregunta):
    try:
        from core import acciones_pc
        return acciones_pc._confirmar(pregunta)
    except Exception:
        return input(f"Arché: {pregunta} (s/n)\nTú: ").strip().lower() in ("s", "si", "sí")


def interpretar(comando):
    """(intencion, argumento) o None. No ejecuta nada."""
    t = _limpio(comando)
    if not t:
        return None
    m = _R_AUTO.match(t)
    if m:
        verbo = m.group(1) or "estado"
        if verbo in ("activa", "enciende", "prende", "inicia"):
            return ("organizador_auto_on", None)
        if verbo.startswith("estado"):
            return ("organizador_auto_estado", None)
        return ("organizador_auto_off", None)
    m = _R_DESHACER.match(t)
    if m:
        return ("organizador_deshacer", _CARPETAS.get(m.group(1) or "", None))
    m = _R_ORDENAR.match(t)
    if m:
        return ("organizador_ordenar", _CARPETAS[m.group(1)])
    m = _R_RUTA.match(comando.strip())  # con el texto original, para no dañar la ruta
    if m and re.search(r"[\\/:]", m.group(1)):
        return ("organizador_ordenar", m.group(1).strip().strip('"'))
    return None


_ultima_carpeta = {"valor": None}


def manejar(comando):
    """Ejecuta una orden del organizador. (intencion, contenido) o None si no es suya."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual

    if intencion == "organizador_auto_on":
        estado = _leer_estado()
        estado["automatico"] = True
        _guardar_estado(estado)
        iniciar()
        texto = (f"Orden automático activado: reviso {', '.join(CARPETAS_AUTOMATICAS)} "
                 f"cada {REVISAR_CADA_SEGUNDOS} segundos.")
    elif intencion == "organizador_auto_off":
        estado = _leer_estado()
        estado["automatico"] = False
        _guardar_estado(estado)
        texto = "Pausé el orden automático. Dime 'activa el orden automático' para volver."
    elif intencion == "organizador_auto_estado":
        on = "activado" if _leer_estado().get("automatico", True) else "en pausa"
        texto = f"El orden automático está {on} (vigilo: {', '.join(CARPETAS_AUTOMATICAS)})."
    elif intencion == "organizador_deshacer":
        carpeta = _resolver(arg) if arg else (_ultima_carpeta["valor"] or _resolver(CARPETAS_AUTOMATICAS[0]))
        texto = deshacer(carpeta)
    else:  # organizador_ordenar
        carpeta = _resolver(arg)
        _ultima_carpeta["valor"] = carpeta
        try:
            plan = crear_plan(carpeta)
        except FileNotFoundError as e:
            _msg(str(e))
            return (intencion, str(e))
        if not plan["movimientos"]:
            texto = f"Tu carpeta {carpeta.name} ya está ordenada."
        else:
            _msg(resumen_plan(plan).replace("\n¿Lo aplico? (sí / no)", ""))
            if _confirmar("¿Lo aplico?"):
                texto = aplicar_plan(plan)
            else:
                texto = "Ok, no muevo nada."
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
    carpeta = _resolver(sys.argv[1])
    if "--deshacer" in sys.argv:
        print(deshacer(carpeta))
    else:
        plan = crear_plan(carpeta)
        if "--aplicar" in sys.argv:
            print(aplicar_plan(plan))
        else:
            print(resumen_plan(plan, detalle=5).replace(
                "¿Lo aplico? (sí / no)", f"Para aplicarlo: python -m core.organizador {sys.argv[1]} --aplicar"))
            print("\nDetalle:")
            for m in plan["movimientos"]:
                print(f"  {Path(m['origen']).name:45} -> {m['categoria']}   ({m['motivo']})")
