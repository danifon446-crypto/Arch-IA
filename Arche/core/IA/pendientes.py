"""
pendientes.py
-------------
Ubicacion: Arche/core/IA/pendientes.py

Arché construye y termina cosas por su cuenta, y comprueba que quedaron bien de verdad.

Que trabaja:
  1. TUS IDEAS: una linea en Database/ideas_arche.txt (o el comando "idea: ...").
         idea: cuenta las vocales de un texto :: hecho cuando: contar_vocales('hola') devuelve 2
         idea: [core/notas.py] resume una nota :: hecho cuando: resumir('') devuelve ''
  2. LO QUE QUEDO A MEDIAS: funciones vacias (pass, ..., NotImplementedError, solo docstring) o con
     un comentario "TODO:" / "FIXME:" / "PENDIENTE:" adentro. Ignora metodos base que otra clase ya
     implementa, archivos protegidos, main.py, pruebas, respaldos, node_modules y el perro robotico.

Lo que hace con cada una (todo por el camino seguro que Arché ya tenia):
  - Busca destino (o usa el archivo que indicaste) y pide el cambio al motor de siempre
    (proponer_cambio_ia / proponer_agregar_funcion_cerca), que ya valida nombres inventados y tipos.
  - CONDICION DE ACEPTACION: lo que escribas despues de "hecho cuando:" se lee con reglas fijas (sin modelo)
    y se EJECUTA contra el codigo nuevo en una copia temporal, antes de aplicar nada. Formas que entiende:
         f(100) devuelve 119.0      f('a') es verdadero      g(0) lanza ValueError      h(1, 2) == [3]
    Separa varias con ";". Si el intento no cumple, se lo reintenta pasando el resultado real de la prueba
    (hasta 3 veces). Una propuesta que no cumple se descarta, nunca se aplica.
  - El guardian de seguridad mira el cambio ANTES de ejecutar codigo nuevo.
  - Si el riesgo es bajo y la mejora automatica esta en "total", lo aplica con las barandas de
    mejora_continua (respaldo, autotest antes y despues, rollback del lote). Si el riesgo es mayor o el destino
    fue una suposicion, deja la propuesta lista para tu aprobacion ('revisate').
  - Al terminar, guarda las condiciones como PRUEBA PERMANENTE en core/IA/pruebas_aprendidas/: el autotest la corre
    siempre, asi lo que Arché aprende a hacer no se rompe despues sin que se note.

Frenos: solo nivel "total", 1 cosa por ciclo, tope diario de mejora_continua, maximo 3 intentos por cosa con
3 dias de descanso, nunca toca archivos protegidos ni este mismo modulo.
"Terminado" significa: cumple tus condiciones + sintaxis + entorno aislado + autotest sin fallas nuevas.
Sin condiciones solo hay validaciones generales (no se sabe si hace lo que querias): por eso conviene ponerlas.

Se conecta con dos lineas en main.py (ver registrar()), sin tocar mejora_continua.py.

Comandos:
    idea: <que quieres> :: hecho cuando: <condiciones>   -> la anota
    ideas / pendientes                                   -> ideas en cola y funciones a medias
    trabaja en mis ideas / termina tus pendientes        -> hace la siguiente ahora mismo
"""

import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import unicodedata
from pathlib import Path

RAIZ_APP = Path(__file__).resolve().parents[2]      # Arche/

DESCANSO_TAREA = 6 * 3600           # cada cuanto toca la tarea dentro del ciclo de mejora
MAX_POR_CICLO = 1                   # pendientes que intenta por ciclo
MAX_INTENTOS = 3                    # intentos por pendiente antes de dejarlo para ti
ESPERA_REINTENTO = 3 * 24 * 3600    # descanso entre intentos del mismo pendiente
RIESGO_MAXIMO_DEFECTO = 20          # solo se aplica sola si el riesgo es "bajo" (igual que autocodigo)
MAX_CARACTERES_ARCHIVO_DEFECTO = 12000   # limite del motor de cambios para archivos largos

CARPETAS_FUERA = {
    "__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database", "backups_codigo",
    "backups_autoconocimiento", "mejora_respaldos", "pruebas_aprendidas", "Perro_robotico",
    "node_modules", "site-packages", "dist", "build",
}
ARCHIVOS_FUERA = {"main.py", "copia(seguridad).py"}
PREFIJOS_FUERA = ("prueba_", "diagnostico_", "main_antes_", "respaldo_")
NUNCA_TOCAR = {"main.py", "core/mejora_continua.py", "core/IA/autotest.py", "core/IA/pendientes.py"}

_R_MARCADOR = re.compile(r"#\s*(TODO|FIXME|XXX|PENDIENTE|HACER)\b\s*[:\-]\s*(.*)")   # mayusculas y con ":" o "-"
_R_HECHO = re.compile(r"hecho\s+cuando\s*:\s*(.+)", re.IGNORECASE)

ARCHIVO_ESTADO = None               # se resuelve la primera vez (ver _ruta_estado)


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------

def _msg(texto):
    print(f"Arché: {texto}")


def _sin_tildes(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def _protegidos():
    try:
        from core.IA.proponer_cambio_codigo import ARCHIVOS_PROTEGIDOS
        base = set(ARCHIVOS_PROTEGIDOS)
    except Exception:
        base = set()
    return base | NUNCA_TOCAR


def _limite_archivo():
    try:
        from core.IA.proponer_cambio_codigo import MAX_CARACTERES_ARCHIVO
        return int(MAX_CARACTERES_ARCHIVO)
    except Exception:
        return MAX_CARACTERES_ARCHIVO_DEFECTO


def _ruta_estado():
    global ARCHIVO_ESTADO
    if ARCHIVO_ESTADO is None:
        try:
            from core.rutas import DATABASE
            base = DATABASE
        except Exception:
            base = str(RAIZ_APP / "Database")
        os.makedirs(base, exist_ok=True)
        ARCHIVO_ESTADO = os.path.join(base, "pendientes_arche.json")
    return ARCHIVO_ESTADO


def _cargar_estado():
    try:
        with open(_ruta_estado(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("intentos", {})
            d.setdefault("terminadas", [])
            return d
    except (OSError, ValueError):
        pass
    return {"intentos": {}, "terminadas": []}


def _guardar_estado(d):
    try:
        with open(_ruta_estado(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------------
# Inventario (solo ast y tokenize: rapido, gratis, sin modelo)
# ------------------------------------------------------------------

def _archivos():
    for ruta in RAIZ_APP.rglob("*.py"):
        rel = ruta.relative_to(RAIZ_APP).as_posix()
        if any(p in CARPETAS_FUERA for p in ruta.parts):
            continue
        if ruta.name in ARCHIVOS_FUERA or ruta.name.startswith(PREFIJOS_FUERA):
            continue
        yield ruta, rel


def _tipo_de_cuerpo(fn):
    """'solo_docstring', 'vacia' o None si la funcion tiene cuerpo real."""
    cuerpo = list(fn.body)
    if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(getattr(cuerpo[0], "value", None), ast.Constant) \
            and isinstance(cuerpo[0].value.value, str):
        cuerpo = cuerpo[1:]
        if not cuerpo:
            return "solo_docstring"
    if not cuerpo:
        return None
    for nodo in cuerpo:
        if isinstance(nodo, ast.Pass):
            continue
        if isinstance(nodo, ast.Expr) and isinstance(getattr(nodo, "value", None), ast.Constant) \
                and nodo.value.value is Ellipsis:
            continue
        if isinstance(nodo, ast.Raise) and nodo.exc is not None:
            exc = nodo.exc.func if isinstance(nodo.exc, ast.Call) else nodo.exc
            if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                continue
        return None
    return "vacia"


def _es_abstracta(fn, clase):
    for d in fn.decorator_list:
        nombre = d.attr if isinstance(d, ast.Attribute) else getattr(d, "id", "")
        if nombre in ("abstractmethod", "overload"):
            return True
    if clase is not None:
        for b in clase.bases:
            nombre = b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
            if nombre in ("ABC", "Protocol"):
                return True
    return False


def _comentarios(texto):
    """[(linea, texto)] de todos los comentarios del archivo."""
    salida = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(texto).readline):
            if tok.type == tokenize.COMMENT:
                salida.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return salida


def _funciones(arbol):
    """(nodo_funcion, nodo_clase_o_None, nombre_completo) de cada funcion o metodo."""
    def visitar(nodo, clase, prefijo):
        for hijo in ast.iter_child_nodes(nodo):
            if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nombre = f"{prefijo}{hijo.name}"
                yield hijo, clase, nombre
                yield from visitar(hijo, None, nombre + ".")
            elif isinstance(hijo, ast.ClassDef):
                yield from visitar(hijo, hijo, f"{prefijo}{hijo.name}.")
            else:
                yield from visitar(hijo, clase, prefijo)
    yield from visitar(arbol, None, "")


def _llamadas_del_archivo(arbol, lineas, rel, destino):
    """destino[nombre] = lista de (archivo, linea, texto) con las llamadas a esa funcion."""
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            nombre = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if nombre:
                lista = destino.setdefault(nombre, [])
                lista.append((rel, nodo.lineno, lineas[nodo.lineno - 1].strip() if nodo.lineno <= len(lineas) else ""))


def inventario():
    """
    Lista ordenada (lo mas facil e importante primero) de lo que esta a medias.
    Cada item: clave, archivo, funcion, linea, tipo, spec, hecho_cuando, llamadas,
    ejemplo, accionable, motivo_no, prioridad.
    """
    protegidos = _protegidos()
    limite = _limite_archivo()
    items = []
    llamadas = {}
    implementados = {}      # nombre de metodo -> clases que SI lo implementan (para detectar metodos base)
    for ruta, rel in _archivos():
        try:
            texto = ruta.read_text(encoding="utf-8-sig")
            arbol = ast.parse(texto, filename=str(ruta))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        lineas = texto.splitlines()
        _llamadas_del_archivo(arbol, lineas, rel, llamadas)
        comentarios = _comentarios(texto)
        for fn, clase, nombre in _funciones(arbol):
            if fn.name.startswith("__") and fn.name.endswith("__"):
                continue
            if _es_abstracta(fn, clase):
                continue
            fin = getattr(fn, "end_lineno", fn.lineno)
            tipo = _tipo_de_cuerpo(fn)
            propios = [(n, c) for n, c in comentarios if fn.lineno <= n <= fin]
            todos = [m for m in (_R_MARCADOR.match(c) for _, c in propios) if m]
            if tipo is None and clase is not None:
                implementados.setdefault(fn.name, set()).add(f"{rel}::{clase.name}")
            if tipo is None and not todos:
                continue
            doc = ast.get_docstring(fn) or ""
            texto_todo = " ".join(m.group(2).strip() for m in todos if m.group(2).strip())
            hecho = ""
            for fuente in [doc] + [c for _, c in propios]:
                m = _R_HECHO.search(fuente)
                if m:
                    hecho = m.group(1).strip()
                    break
            spec = " ".join(x for x in (doc.strip().splitlines()[0] if doc.strip() else "", texto_todo) if x).strip()
            motivo_no = ""
            if rel in protegidos:
                motivo_no = "archivo protegido"
            elif len(texto) > limite:
                motivo_no = f"archivo largo ({len(texto)} caracteres; el motor de cambios acepta hasta {limite})"
            llamadas_fn = llamadas.get(fn.name, [])
            items.append({
                "clave": f"{rel}::{nombre}", "archivo": rel, "funcion": nombre, "nombre_corto": fn.name,
                "linea": fn.lineno, "tipo": tipo or "todo", "_clase": f"{rel}::{clase.name}" if clase is not None else "", "spec": spec, "hecho_cuando": hecho,
                "_llamadas_fn": fn.name, "accionable": not motivo_no, "motivo_no": motivo_no,
            })
    # las llamadas se cuentan al final, con todo el proyecto ya recorrido
    for it in items:
        lista = [c for c in llamadas.get(it["_llamadas_fn"], []) if not (c[0] == it["archivo"] and c[1] == it["linea"])]
        it["llamadas"] = len(lista)
        it["ejemplo"] = lista[0][2][:160] if lista else ""
        del it["_llamadas_fn"]
        it["prioridad"] = (
            (30 if it["hecho_cuando"] else 0)
            + (20 if it["spec"] else 0)
            + min(it["llamadas"], 5) * 4
            + (10 if it["tipo"] in ("vacia", "solo_docstring") else 0)
        )
    # un metodo vacio que otra clase ya implementa es un metodo base (interfaz), no algo a medias
    items = [i for i in items if not (i["tipo"] != "todo" and i["_clase"]
                                      and implementados.get(i["nombre_corto"], set()) - {i["_clase"]})]
    for i in items:
        del i["_clase"]
    # una funcion vacia sin docstring, sin TODO y que nadie llama es casi seguro un "no hacer nada"
    # a proposito (ej. silenciar un log): no cuenta como pendiente
    items = [i for i in items if i["spec"] or i["hecho_cuando"] or i["llamadas"] or i["tipo"] == "todo"]
    items.sort(key=lambda i: (-i["prioridad"], i["clave"]))
    return items


# ------------------------------------------------------------------
# Terminar un pendiente
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Condiciones de aceptacion: "Hecho cuando: f(2) devuelve 4; f(0) devuelve 0"
# Se leen con reglas fijas (sin modelo), se ejecutan de verdad y quedan como prueba permanente.
# ------------------------------------------------------------------

_R_LANZA = re.compile(r"^(?P<llamada>.+?)\s+(?:lanza|levanta)\s+(?P<exc>[A-Za-z_]\w*)$", re.IGNORECASE)
_R_IGUAL = re.compile(r"^(?P<llamada>.+?)\s+(?:devuelve|retorna|regresa|da|es\s+igual\s+a|es|==)\s+(?P<valor>.+)$",
                      re.IGNORECASE)
_VALORES_ES = {"verdadero": True, "true": True, "falso": False, "false": False, "nada": None, "none": None}
_PERMITIDOS = (ast.Expression, ast.Call, ast.Name, ast.Attribute, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set,
               ast.UnaryOp, ast.BinOp, ast.keyword, ast.Load, ast.USub, ast.UAdd, ast.Add, ast.Sub, ast.Mult,
               ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.Subscript, ast.Slice)


def _llamada_segura(texto):
    """Devuelve el arbol de la llamada si es una expresion f(...) sin nada raro, o None."""
    try:
        arbol = ast.parse(texto.strip(), mode="eval")
    except SyntaxError:
        return None
    if not isinstance(arbol.body, ast.Call):
        return None
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, _PERMITIDOS):
            return None
        if isinstance(nodo, ast.Attribute) and nodo.attr.startswith("__"):
            return None
        if isinstance(nodo, ast.Name) and nodo.id.startswith("__"):
            return None
    return arbol


def _valor_de(texto):
    t = texto.strip().rstrip(".").strip()
    if t.lower() in _VALORES_ES:
        return True, _VALORES_ES[t.lower()]
    try:
        return True, ast.literal_eval(t)
    except (ValueError, SyntaxError):
        return False, None


def parse_criterios(texto):
    """
    'f(100) devuelve 119.0; g(0) lanza ValueError' -> (criterios, no_entendidos).
    Cada criterio: {tipo: 'igual'|'lanza', llamada, valor|exc, texto}.
    """
    criterios, no_entendidos = [], []
    for trozo in re.split(r";|\sy\s(?=\w+\()", texto or ""):
        trozo = trozo.strip()
        if not trozo:
            continue
        m = _R_LANZA.match(trozo)
        if m and _llamada_segura(m.group("llamada")):
            criterios.append({"tipo": "lanza", "llamada": m.group("llamada").strip(), "exc": m.group("exc"),
                              "texto": trozo})
            continue
        m = _R_IGUAL.match(trozo)
        if m and _llamada_segura(m.group("llamada")):
            ok, valor = _valor_de(m.group("valor"))
            if ok:
                criterios.append({"tipo": "igual", "llamada": m.group("llamada").strip(), "valor": valor,
                                  "texto": trozo})
                continue
        no_entendidos.append(trozo)
    return criterios, no_entendidos


def _nombres_usados(criterios):
    """Nombres (no builtin) que las llamadas necesitan importar del modulo."""
    import builtins
    nombres = []
    for c in criterios:
        for nodo in ast.walk(ast.parse(c["llamada"], mode="eval")):
            if isinstance(nodo, ast.Name) and not hasattr(builtins, nodo.id) and nodo.id not in nombres:
                nombres.append(nodo.id)
    return nombres


_IGUAL_SRC = (
    "def _igual(a, b):\n"
    "    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):\n"
    "        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)\n"
    "    return a == b\n"
)


def _lineas_de(c, modo):
    """Codigo de un criterio. modo 'sandbox' acumula fallos; modo 'prueba' usa assert."""
    if modo == "prueba":
        if c["tipo"] == "igual":
            return [f"    assert _igual({c['llamada']}, {c['valor']!r}), {c['texto']!r}"]
        return ["    try:", f"        {c['llamada']}",
                f"        raise AssertionError({('no lanzo ' + c['exc'])!r})",
                f"    except {c['exc']}:", "        pass"]
    if c["tipo"] == "igual":
        return ["try:", f"    _r = {c['llamada']}", f"    if not _igual(_r, {c['valor']!r}):",
                f"        _fallos.append({c['texto']!r} + '  ->  devolvio ' + repr(_r))",
                "except Exception as _e:",
                f"    _fallos.append({c['texto']!r} + '  ->  fallo con ' + type(_e).__name__ + ': ' + str(_e))"]
    return ["try:", f"    {c['llamada']}", f"    _fallos.append({c['texto']!r} + '  ->  no lanzo nada')",
            f"except {c['exc']}:", "    pass", "except Exception as _e:",
            f"    _fallos.append({c['texto']!r} + '  ->  lanzo ' + type(_e).__name__ + ' en vez de {c['exc']}')"]


def _codigo_sandbox(modulo, criterios):
    lineas = ["import math, importlib, sys", f"_m = importlib.import_module({modulo!r})",
              "globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})",
              _IGUAL_SRC, "_fallos = []"]
    for c in criterios:
        lineas += _lineas_de(c, "sandbox")
    lineas += ["if _fallos:", "    print('NO CUMPLE:'); print('\\n'.join(_fallos)); sys.exit(1)", "print('CUMPLE')"]
    return "\n".join(lineas) + "\n"


def _ruta_a_modulo(archivo):
    return (archivo[:-3] if archivo.endswith(".py") else archivo).replace("/", ".")


def _copiar_proyecto(destino):
    for ruta in RAIZ_APP.rglob("*.py"):
        if any(p in CARPETAS_FUERA - {"pruebas_aprendidas", "Perro_robotico"} for p in ruta.parts):
            continue
        rel = ruta.relative_to(RAIZ_APP)
        (destino / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ruta, destino / rel)


def correr_criterios(archivo, contenido_nuevo, criterios, timeout=20):
    """Prueba los criterios contra el codigo NUEVO en una copia temporal (el real no se toca).
    Devuelve (ok, detalle)."""
    if not criterios:
        return True, "sin condicion automatica"
    entorno = Path(tempfile.mkdtemp(prefix="arche_aceptacion_"))
    try:
        _copiar_proyecto(entorno)
        destino = entorno / archivo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido_nuevo, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, "-c", _codigo_sandbox(_ruta_a_modulo(archivo), criterios)],
                               capture_output=True, text=True, cwd=str(entorno), timeout=timeout,
                               encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return False, f"se colgó más de {timeout}s al probar la condición"
        salida = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode == 0:
            return True, "cumple todas las condiciones"
        return False, salida[-700:] or "falló sin dar detalle"
    finally:
        shutil.rmtree(entorno, ignore_errors=True)


def guardar_prueba_permanente(archivo, criterios, descripcion):
    """Deja las condiciones como prueba aprendida: el autotest la corre siempre. Devuelve la ruta relativa o None."""
    if not criterios:
        return None
    modulo = _ruta_a_modulo(archivo)
    firma = hashlib.sha1((modulo + "|" + "|".join(c["texto"] for c in criterios)).encode("utf-8")).hexdigest()[:10]
    rel = f"core/IA/pruebas_aprendidas/prueba_{firma}.py"
    ruta = RAIZ_APP / rel
    cuerpo = [
        '"""',
        f"Prueba de aceptacion creada por Arché al terminar: {descripcion}",
        "Condiciones que dejó su dueño: " + "; ".join(c["texto"] for c in criterios),
        "Si esta prueba falla, la función dejó de cumplir lo que se pidió. No la borres sin revisar.",
        '"""',
        "import math",
        f"from {modulo} import {', '.join(_nombres_usados(criterios))}",
        "",
        _IGUAL_SRC,
        "def prueba():",
    ]
    for c in criterios:
        cuerpo += _lineas_de(c, "prueba")
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("\n".join(cuerpo) + "\n", encoding="utf-8")
    except OSError:
        return None
    try:
        from core.seguridad import guardian
        guardian.registrar_cambio_propio(rel, motivo="prueba de aceptacion de pendientes")
    except Exception:
        pass
    return rel


# ------------------------------------------------------------------
# Cola de ideas: lo que quieres que Arché construya, escrito en una linea
#   idea: <que debe hacer> :: hecho cuando: f(2) devuelve 4; f(0) devuelve 0
#   idea: [core/notas.py] <que debe hacer> :: hecho cuando: ...      (si quieres elegir el archivo)
# ------------------------------------------------------------------

def _ruta_ideas():
    _ruta_estado()
    return os.path.join(os.path.dirname(ARCHIVO_ESTADO), "ideas_arche.txt")


_R_SEPARA_HECHO = re.compile(r"\s*(?:::\s*)?hecho\s+cuando\s*:\s*", re.IGNORECASE)
_R_ARCHIVO = re.compile(r"^\[([\w./\\\-]+\.py)\]\s*(.*)$")


def _leer_ideas():
    """[{clave, id, linea, descripcion, archivo, hecho_cuando}] desde el archivo de ideas."""
    try:
        with open(_ruta_ideas(), "r", encoding="utf-8") as f:
            lineas = f.read().splitlines()
    except OSError:
        return []
    salida = []
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        partes = _R_SEPARA_HECHO.split(linea, maxsplit=1)
        desc = partes[0].strip().rstrip(":").strip()
        hecho = partes[1].strip() if len(partes) > 1 else ""
        archivo = None
        m = _R_ARCHIVO.match(desc)
        if m:
            archivo, desc = m.group(1).replace("\\", "/"), m.group(2).strip()
        if not desc:
            continue
        ident = hashlib.sha1(linea.encode("utf-8")).hexdigest()[:8]
        salida.append({"clave": f"idea::{ident}", "id": ident, "linea": linea, "descripcion": desc,
                       "archivo": archivo, "hecho_cuando": hecho, "tipo": "idea", "accionable": True,
                       "motivo_no": "", "funcion": desc[:60], "prioridad": 1000})
    return salida


def agregar_idea(texto):
    """Agrega una linea al archivo de ideas. Devuelve (id, criterios, no_entendidos)."""
    texto = " ".join(str(texto).split())
    with open(_ruta_ideas(), "a", encoding="utf-8") as f:
        f.write(texto + "\n")
    partes = _R_SEPARA_HECHO.split(texto, maxsplit=1)
    criterios, no_ent = parse_criterios(partes[1]) if len(partes) > 1 else ([], [])
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:8], criterios, no_ent


# ------------------------------------------------------------------
# Trabajar un pendiente o una idea (con reintentos que aprenden del error real)
# ------------------------------------------------------------------

MAX_INTENTOS_CON_FEEDBACK = 3


def _instruccion(it):
    """Texto para el modelo: que hacer, y cuando se considera terminado."""
    criterios, _ = parse_criterios(it.get("hecho_cuando", ""))
    nombres = []
    for c in criterios:
        for nodo in ast.walk(ast.parse(c["llamada"], mode="eval")):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id not in nombres:
                nombres.append(nodo.func.id)
    if it["tipo"] == "idea":
        partes = [f"Agrega esta funcionalidad: {it['descripcion'].rstrip('. ')}."]
        if nombres:
            partes.append("La función debe llamarse exactamente: " + ", ".join(nombres) + ".")
    else:
        estado = {"vacia": "esta vacia (solo pass o NotImplementedError)",
                  "solo_docstring": "solo tiene docstring, sin codigo",
                  "todo": "tiene un TODO sin resolver"}[it["tipo"]]
        partes = [f"Completa la funcion '{it['nombre_corto']}': hoy {estado}."]
        if it.get("spec"):
            partes.append(f"Debe hacer: {it['spec'].rstrip('. ')}.")
        if it.get("ejemplo"):
            partes.append(f"Asi se la llama en el proyecto: {it['ejemplo']}")
    if it.get("hecho_cuando"):
        partes.append(f"Esta terminada cuando: {it['hecho_cuando']}.")
    partes.append("Cambia solo lo necesario, no uses nombres que no existan en el archivo ni en la libreria "
                  "estandar, y no dejes pass ni TODO.")
    return " ".join(partes)


def _sigue_pendiente(it):
    """True si esa funcion todavia aparece a medias (se vuelve a leer el archivo del disco)."""
    return any(x["clave"] == it["clave"] for x in inventario())


def _riesgo_maximo():
    try:
        from core import mejora_continua as m
        return int(getattr(m, "RIESGO_MAXIMO", RIESGO_MAXIMO_DEFECTO))
    except Exception:
        return RIESGO_MAXIMO_DEFECTO


def _nivel_total():
    try:
        from core import mejora_continua as m
        return m.nivel() == "total"
    except Exception:
        return False


def _hay_cupo():
    try:
        from core import mejora_continua as m
        return m._cambios_hoy() < m.MAX_CAMBIOS_DIA
    except Exception:
        return True


def _detenida():
    try:
        from core import mejora_continua as m
        return m._detener.is_set()
    except Exception:
        return False


def _anotar_intento(clave, resultado, definitivo=False, extra=None):
    """definitivo=True: no se reintenta sola (ej. ya dejo una propuesta esperando tu revision).
    extra: datos de la propuesta que quedo esperando (para cerrar el ciclo cuando la apruebes)."""
    d = _cargar_estado()
    previo = d["intentos"].get(clave, {})
    n = MAX_INTENTOS if definitivo else int(previo.get("n", 0)) + 1
    entrada = {"n": n, "t": time.time(), "ultimo": resultado}
    if extra:
        entrada.update(extra)
    d["intentos"][clave] = entrada
    _guardar_estado(d)


def _anotar_terminada(it, como):
    d = _cargar_estado()
    d["terminadas"].append({"clave": it["clave"], "t": time.time(), "como": como})
    d["terminadas"] = d["terminadas"][-100:]
    d["intentos"].pop(it["clave"], None)
    _guardar_estado(d)


def _toca_intentar(it, ahora, estado):
    if it["clave"] in {t["clave"] for t in estado.get("terminadas", [])}:
        return False
    previo = estado["intentos"].get(it["clave"])
    if not previo:
        return True
    return previo.get("n", 0) < MAX_INTENTOS and ahora - previo.get("t", 0) >= ESPERA_REINTENTO


def _marcar_propuesta(id_propuesta, estado):
    try:
        from core.IA import proponer_cambio_codigo as pc
        props = pc._cargar_pendientes()
        for p in props:
            if p.get("id") == id_propuesta:
                p["estado"] = estado
        pc._guardar_pendientes(props)
    except Exception:
        pass


def _contenido_nuevo(prop, actual):
    if prop.get("buscar"):
        return actual.replace(prop["buscar"], prop["reemplazar"], 1)
    return prop["reemplazar"]


def _ultima_funcion(contenido):
    try:
        arbol = ast.parse(contenido)
    except SyntaxError:
        return None
    nombres = [n.name for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return nombres[-1] if nombres else None


def _generar(it, instruccion):
    """Pide el cambio al motor de siempre. Devuelve (propuesta, error, confianza_alta, archivo)."""
    from core.IA.proponer_cambio_codigo import (proponer_cambio_ia, proponer_agregar_funcion_cerca,
                                                _extraer_funcion)
    if it["tipo"] != "idea":
        prop, error = proponer_cambio_ia(it["archivo"], instruccion, origen="mejora_automatica")
        return prop, error, True, it["archivo"]
    if it.get("archivo"):
        archivo = it["archivo"]
        decision = {"tipo": "editar_existente" if (RAIZ_APP / archivo).is_file() else "crear_nuevo",
                    "archivo": archivo, "funcion": None, "confianza_alta": True}
    else:
        from core.IA.enrutar_cambio import decidir_destino
        decision = decidir_destino(it["descripcion"])
    archivo = decision["archivo"]
    if archivo in _protegidos():
        return None, f"el destino '{archivo}' es un archivo protegido", True, archivo
    confianza = bool(decision.get("confianza_alta", True))
    ruta = RAIZ_APP / archivo
    if decision["tipo"] == "editar_existente" and ruta.is_file():
        contenido = ruta.read_text(encoding="utf-8")
        if len(contenido) > _limite_archivo():
            return None, f"'{archivo}' es muy largo para mi motor de cambios", confianza, archivo
        ancla = decision.get("funcion") or _ultima_funcion(contenido)
        codigo_ancla = _extraer_funcion(contenido, ancla) if ancla else None
        if codigo_ancla:
            prop, error = proponer_agregar_funcion_cerca(archivo, codigo_ancla, instruccion, "mejora_automatica")
            return prop, error, confianza, archivo
    prop, error = proponer_cambio_ia(archivo, instruccion, origen="mejora_automatica")
    return prop, error, confianza, archivo


def _guardian_bloquea(actual, nuevo):
    """True si el guardian de seguridad ve algo raro (o no pudo mirar). Va ANTES de ejecutar codigo nuevo."""
    try:
        from core.seguridad import guardian
        return bool(guardian.escanear_cambio(actual, nuevo))
    except Exception:
        return True


def trabajar(it):
    """Termina un pendiente o una idea. Devuelve (resultado, texto):
    'aplicada' | 'propuesta' | 'fallida' | 'deshecha' | 'bloqueada'."""
    nombre = it["funcion"]
    criterios, no_entendidos = parse_criterios(it.get("hecho_cuando", ""))
    base = _instruccion(it)
    feedback, ultimo_error, prop, archivo, confianza = "", "", None, it.get("archivo"), True
    for intento in range(1, MAX_INTENTOS_CON_FEEDBACK + 1):
        if _detenida():
            return "fallida", f"me frené antes de terminar '{nombre}' (volviste a hablarme)"
        try:
            prop, error, confianza, archivo = _generar(it, base + feedback)
        except Exception as e:
            prop, error = None, f"{type(e).__name__}: {e}"
        if prop is None:
            ultimo_error = str(error)
            feedback = f" Intento anterior sin propuesta: {str(error)[:200]}."
            continue
        ruta = RAIZ_APP / prop["archivo"]
        actual = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
        nuevo = _contenido_nuevo(prop, actual)
        if _guardian_bloquea(actual, nuevo):
            _marcar_propuesta(prop["id"], "fallida")
            _anotar_intento(it["clave"], "bloqueado por seguridad", definitivo=True)
            return "bloqueada", f"el cambio para '{nombre}' lo frenó mi guardián de seguridad; no lo apliqué"
        ok, detalle = correr_criterios(prop["archivo"], nuevo, criterios)
        if not ok:
            _marcar_propuesta(prop["id"], "fallida")
            ultimo_error = detalle
            feedback = f" Tu intento anterior NO cumplió la condición. Resultado real al probarlo: {detalle[:500]}. Corrígelo."
            prop = None
            continue
        break
    if prop is None:
        _anotar_intento(it["clave"], f"no cumplió tras {MAX_INTENTOS_CON_FEEDBACK} intentos: {ultimo_error[:120]}")
        return "fallida", f"no logré que '{nombre}' cumpla lo pedido ({ultimo_error[:140]})"

    prueba_txt = "cumple tu condición" if criterios else "sin condición automática (solo validaciones normales)"
    if no_entendidos:
        prueba_txt += f"; no entendí: {'; '.join(no_entendidos)[:80]}"
    try:
        from core.IA import gran_sabio
        puntaje, _ = gran_sabio.evaluar_riesgo(prop)
    except Exception:
        puntaje = 100                    # sin poder medir el riesgo, no se aplica sola
    if puntaje >= _riesgo_maximo() or not confianza or not _nivel_total():
        _anotar_intento(it["clave"], f"propuesta {prop.get('id')} esperando revision", definitivo=True,
                        extra={"propuesta": prop.get("id"), "archivo": prop["archivo"],
                               "hecho": it.get("hecho_cuando", ""), "desc": it.get("descripcion") or nombre})
        return "propuesta", (f"dejé lista la propuesta {prop.get('id')} para '{nombre}' en {archivo} ({prueba_txt}); "
                             f"dime 'revisate' o 'revisar cambios de codigo' para aprobarla")

    from core import mejora_continua as m
    try:
        resultado = m.aplicar_lote_seguro([prop])
        aplicadas, deshechas = resultado[0], resultado[1]
    except Exception as e:
        _anotar_intento(it["clave"], f"error al aplicar: {e}")
        return "fallida", f"falló al aplicar '{nombre}' ({e})"
    if deshechas:
        _anotar_intento(it["clave"], "deshecha: rompia pruebas")
        return "deshecha", f"terminé '{nombre}' pero al probarme rompía algo y lo deshice"
    if not aplicadas:
        _anotar_intento(it["clave"], "no se aplico")
        return "fallida", f"el cambio para '{nombre}' no pasó mis validaciones"
    if it["tipo"] != "idea" and _sigue_pendiente(it):
        _anotar_intento(it["clave"], "aplicada pero sigue a medias")
        return "fallida", f"apliqué un cambio en '{nombre}' pero sigue a medias; lo reintento más adelante"
    _anotar_terminada(it, "aplicada")
    prueba = guardar_prueba_permanente(prop["archivo"], criterios, it.get("descripcion") or nombre)
    extra = f" y dejé una prueba permanente ({os.path.basename(prueba)})" if prueba else ""
    return "aplicada", (f"terminé '{nombre}' en {prop['archivo']}: {prueba_txt}, probado en entorno aislado "
                        f"y con mis pruebas{extra} (reversible con 'deshaz tus cambios')")


terminar_uno = trabajar     # nombre anterior


def conciliar():
    """Cierra el ciclo de lo que dejé esperando tu aprobacion: si ya la aprobaste (con 'revisar cambios de
    codigo') guarda la prueba permanente y marca la idea como hecha; si la rechazaste, la deja de lado.
    Devuelve la lista de textos de lo que cerró."""
    estado = _cargar_estado()
    esperando = {}
    conocidas = None
    for k, v in estado["intentos"].items():
        if v.get("propuesta"):
            esperando[k] = v
            continue
        # anotaciones de la version anterior: solo traian el texto "propuesta cod_278 esperando revision"
        m = re.match(r"propuesta (\S+) esperando revision", v.get("ultimo", ""))
        if m:
            if conocidas is None:
                conocidas = {i["clave"]: i for i in _leer_ideas()}
            it = conocidas.get(k, {})
            esperando[k] = dict(v, propuesta=m.group(1), archivo=it.get("archivo") or "",
                                hecho=it.get("hecho_cuando", ""), desc=it.get("descripcion", k))
    if not esperando:
        return []
    try:
        from core.IA import proponer_cambio_codigo as pc
        props = {x.get("id"): x for x in pc._cargar_pendientes()}
    except Exception:
        return []
    textos = []
    for clave, v in esperando.items():
        prop = props.get(v["propuesta"])
        if not prop or prop.get("estado") not in ("aplicada", "rechazada", "fallida"):
            continue
        d = _cargar_estado()
        if prop["estado"] == "aplicada":
            criterios, _ = parse_criterios(v.get("hecho", ""))
            prueba = guardar_prueba_permanente(prop.get("archivo") or v.get("archivo"), criterios, v.get("desc", clave))
            d["terminadas"].append({"clave": clave, "t": time.time(), "como": "aprobada por ti"})
            d["terminadas"] = d["terminadas"][-100:]
            d["intentos"].pop(clave, None)
            extra = f" y dejé una prueba permanente ({os.path.basename(prueba)})" if prueba else ""
            textos.append(f"vi que aprobaste '{v.get('desc', clave)}': la marqué como hecha{extra}")
        else:
            d["intentos"][clave] = {"n": MAX_INTENTOS, "t": time.time(),
                                    "ultimo": f"propuesta {v['propuesta']} {prop['estado']}; la dejo quieta"}
            textos.append(f"la propuesta para '{v.get('desc', clave)}' quedó {prop['estado']}; no insisto")
        _guardar_estado(d)
    return textos


def tarea_pendientes(forzar=False):
    """Tarea del piloto automatico: primero tus ideas, despues lo que quedo a medias. Texto o None."""
    cerradas = conciliar()
    if not forzar and (not _nivel_total() or not _hay_cupo()):
        return ("pendientes: " + "; ".join(cerradas)) if cerradas else None
    estado = _cargar_estado()
    ahora = time.time()
    cola = _leer_ideas() + [i for i in inventario() if i["accionable"]]
    candidatos = [i for i in cola if forzar or _toca_intentar(i, ahora, estado)]
    if forzar:
        hechas = {t["clave"] for t in estado.get("terminadas", [])}
        candidatos = [i for i in candidatos if i["clave"] not in hechas]
    textos = []
    for it in candidatos[:MAX_POR_CICLO]:
        if _detenida():
            break
        _, texto = trabajar(it)
        textos.append(texto)
    textos = cerradas + textos
    return ("pendientes: " + "; ".join(textos)) if textos else None


# ------------------------------------------------------------------
# Conexion con el piloto automatico (mejora_continua.py no se modifica)
# ------------------------------------------------------------------

def registrar():
    """Agrega la tarea 'pendientes' al piloto automatico (nivel total, antes de 'autocodigo').
    Es idempotente: llamarla varias veces no la duplica."""
    from core import mejora_continua as m
    m.TAREAS["pendientes"] = tarea_pendientes
    m.DESCANSO["pendientes"] = DESCANSO_TAREA
    actual = tuple(m.POR_NIVEL.get("total", ()))
    if "pendientes" not in actual:
        i = actual.index("autocodigo") if "autocodigo" in actual else len(actual)
        m.POR_NIVEL["total"] = actual[:i] + ("pendientes",) + actual[i:]


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_VER = re.compile(r"^(?:pendientes|que tienes a medias|que dejaste a medias|busca pendientes|"
                    r"funciones pendientes|que te falta terminar|que tienes pendiente|mis ideas|ideas)$")
_R_TERMINAR = re.compile(r"^(?:termina tus pendientes|termina (?:un )?pendiente|termina lo que dejaste a medias|"
                         r"termina tus funciones a medias|trabaja en mis ideas|haz mis ideas|construye mis ideas)$")
_R_IDEA = re.compile(r"^\s*idea\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)


def interpretar(comando):
    m = _R_IDEA.match(comando or "")
    if m:
        return ("idea_agregar", m.group(1).strip())
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", _sin_tildes(comando))).strip()
    if _R_VER.match(t):
        return ("pendientes_ver", None)
    if _R_TERMINAR.match(t):
        return ("pendientes_terminar", None)
    return None


def reporte(maximo=8):
    for t in conciliar():
        _msg(t[0].upper() + t[1:] + ".")
    estado = _cargar_estado()
    hechas = {t["clave"] for t in estado.get("terminadas", [])}
    ideas = [i for i in _leer_ideas()]
    items = inventario()
    if not ideas and not items:
        _msg("No tengo ideas en cola ni nada a medias en mi código. Dime 'idea: <qué quieres> :: hecho cuando: "
             "f(2) devuelve 4' y lo construyo.")
        return items
    if ideas:
        _msg(f"Tus ideas en cola ({sum(1 for i in ideas if i['clave'] not in hechas)} por hacer, "
             f"{sum(1 for i in ideas if i['clave'] in hechas)} hechas):")
        for i in ideas[:maximo]:
            previo = estado["intentos"].get(i["clave"], {})
            if i["clave"] in hechas:
                marca = "✓ hecha"
            elif previo.get("propuesta"):
                marca = f"propuesta {previo['propuesta']} lista: aprueba con 'revisar cambios de codigo'"
            elif previo:
                marca = f"intento {previo['n']}: {previo.get('ultimo', '')}"
            else:
                marca = "en cola"
            meta = f" · hecho cuando: {i['hecho_cuando']}" if i["hecho_cuando"] else " · sin condición (agrégala con ':: hecho cuando: ...')"
            print(f"  • {i['descripcion'][:90]}{meta} [{marca}]")
    if items:
        accion = [i for i in items if i["accionable"]]
        _msg(f"Funciones a medias: {len(items)} ({len(accion)} que puedo terminar sola).")
        for i in items[:maximo]:
            previo = estado["intentos"].get(i["clave"], {})
            nota = (f" · propuesta {previo['propuesta']} esperando tu aprobación" if previo.get("propuesta")
                    else f" · intentos: {previo['n']} ({previo.get('ultimo', '')})" if previo else "")
            if not i["accionable"]:
                nota += f" · no la toco: {i['motivo_no']}"
            meta = f" · hecho cuando: {i['hecho_cuando']}" if i["hecho_cuando"] else ""
            print(f"  • {i['archivo']} → {i['funcion']} (línea {i['linea']}, {i['tipo'].replace('_', ' ')}, "
                  f"{i['llamadas']} llamada(s)){meta}{nota}")
    if estado.get("terminadas"):
        print(f"  Ya terminé {len(estado['terminadas'])} por mi cuenta.")
    return items


def manejar(comando):
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual
    if intencion == "idea_agregar":
        ident, criterios, no_ent = agregar_idea(arg)
        _msg(f"Anotada (idea {ident}). La construyo cuando lleves unos minutos sin hablarme, o dime 'trabaja en mis ideas'.")
        if criterios:
            _msg(f"Entendí {len(criterios)} condición(es) que voy a probar de verdad antes de aplicar nada.")
        if no_ent:
            _msg("No pude leer como prueba: " + "; ".join(no_ent) + ". Usa el formato 'f(2) devuelve 4' o 'f(0) lanza ValueError'.")
        if not criterios and not no_ent:
            _msg("Tip: si agregas ':: hecho cuando: f(2) devuelve 4' puedo comprobar sola que quedó bien.")
    elif intencion == "pendientes_ver":
        reporte()
    else:
        _msg("Dale, busco lo siguiente de mi lista y lo termino (puede tardar un poco)...")
        texto = tarea_pendientes(forzar=True)
        _msg(texto if texto else "No tengo ideas ni pendientes que pueda terminar ahora.")
    return cual