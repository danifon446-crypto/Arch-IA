"""
limpieza.py
-----------
Ubicacion: Arche/core/nucleo/limpieza.py

LIMPIEZA SOLA: Arché resuelve por su cuenta lo que su autorevisión encuentra, sin
preguntarte cada vez y sin avisarte al abrir. Te lo cuenta en el resumen de la noche.

Qué hace, cuando llevas un rato sin usar el PC:
  1. Lo seguro (imports sin usar, 'except:' desnudos): pone la mejora continua en nivel
     "total", que ya sabía arreglarlo sola con sus pruebas.
  2. CÓDIGO MUERTO: funciones que nadie llama. Las quita por lotes pequeños (un archivo y
     hasta 6 funciones por lote). Antes de quitarlas guarda una copia en el CEMENTERIO
     (Database/nucleo/cementerio/), así que nada se pierde.
  3. DUPLICADAS: la misma función copiada idéntica en dos archivos. Deja una sola y el
     otro archivo la importa de ahí. Si está repetida en el mismo archivo, borra la copia
     que sobra (Python siempre usaba la última).

Cada lote pasa por lo de siempre: la imaginación (que no rompa nada que se use), la copia
aparte de Arché con todo el autotest, y el autotest otra vez en el código real (si algo
falla, vuelve sola a como estaba). Máximo 4 lotes por día.

Red de seguridad extra: si después de quitar una función aparece un error que la nombra
(NameError, AttributeError, ImportError), Arché la devuelve sola desde el cementerio.

Nunca toca: main.py, el núcleo protegido, core/nucleo, las habilidades fabricadas, las
pruebas, ni funciones que se usan "por nombre" (manejar, iniciar, main, ejecutar, probar...).

Comandos:
  estado de la limpieza · qué limpiaste · límpiate ahora
  devuelve la función <nombre> · limpieza apagada / limpieza encendida
"""

import ast
import builtins
import os
import re
import threading

from core.nucleo import comun

ARCH = comun.ruta("limpieza.json")
CARPETA_CEMENTERIO = os.path.join(comun.CARPETA, "cementerio")
os.makedirs(CARPETA_CEMENTERIO, exist_ok=True)

LOTES_POR_DIA = 4
FUNCIONES_POR_LOTE = 6
MINUTOS_INACTIVO = 20

# funciones que otros módulos usan por nombre (el núcleo, main.py, los ganchos)
NOMBRES_RESERVADOS = {"manejar", "iniciar", "detener", "detener_todo", "main", "ejecutar", "probar", "registrar",
                      "instalar", "revisar", "interpretar", "configurar", "arrancar_si_corresponde", "setup",
                      "teardown", "run", "start", "stop"}
CARPETAS_PROHIBIDAS = ("core/nucleo/", "core/habilidades_auto/", "core/seguridad/", "Perro_robotico/", "arche_ajedrez/",
                       "nube/", ".github/")

_lock = threading.Lock()
_trabajando = threading.Event()


# ------------------------------------------------------------------
# Estado
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activa", True)
    e.setdefault("lotes_por_dia", {})
    e.setdefault("quitadas", [])           # [{archivo, nombre, cuando, cementerio, lote}]
    e.setdefault("unificadas", [])         # [{archivo, nombre, desde, cuando}]
    e.setdefault("no_tocar", [])           # "archivo::nombre" que falló al quitar
    e.setdefault("devueltas", [])
    e.setdefault("ultimo_aviso_autorevision", "")
    e.setdefault("nivel_puesto", False)
    return e


def _guardar(e):
    e["lotes_por_dia"] = dict(sorted(e["lotes_por_dia"].items())[-10:])
    e["quitadas"] = e["quitadas"][-2000:]
    e["unificadas"] = e["unificadas"][-500:]
    e["no_tocar"] = e["no_tocar"][-3000:]
    comun.guardar(ARCH, e)


def lotes_hoy():
    return int(_estado()["lotes_por_dia"].get(comun.hoy(), 0))


# ------------------------------------------------------------------
# Qué se puede tocar
# ------------------------------------------------------------------

def _evo():
    from core import evolucion
    return evolucion


def archivo_tocable(rel):
    rel = rel.replace("\\", "/")
    if not rel.endswith(".py") or rel.endswith("__init__.py"):
        return False
    base = os.path.basename(rel)
    if base.startswith(("prueba", "test_", "diagnostico", "aplicar_parche")) or "copia(" in base:
        return False
    if any(rel.startswith(c) for c in CARPETAS_PROHIBIDAS):
        return False
    try:
        evo = _evo()
        if not evo._ruta_segura(rel):
            return False
    except Exception:
        return False
    try:
        from core.IA.proponer_cambio_codigo import ARCHIVOS_PROTEGIDOS
        if rel in ARCHIVOS_PROTEGIDOS:
            return False
    except Exception:
        pass
    return True


def _leer(rel):
    with open(os.path.join(comun.BASE, rel), "r", encoding="utf-8-sig") as f:
        return f.read()


def _funciones_de_primer_nivel(texto):
    """{nombre: [(inicio, fin), ...]} con líneas (1-based, incluye decoradores) de funciones de nivel módulo."""
    salida = {}
    for nodo in ast.parse(texto).body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inicio = nodo.decorator_list[0].lineno if nodo.decorator_list else nodo.lineno
            salida.setdefault(nodo.name, []).append((inicio, nodo.end_lineno, bool(nodo.decorator_list)))
    return salida


def _modulo(rel):
    m = rel[:-3].replace("/", ".")
    return m[:-len(".__init__")] if m.endswith(".__init__") else m


def quitar_lineas(texto, rangos):
    """Quita los rangos de líneas (1-based, inclusivos) y las líneas en blanco que sobren después."""
    lineas = texto.splitlines(keepends=True)
    borrar = set()
    for ini, fin in rangos:
        borrar.update(range(ini - 1, fin))
        j = fin
        while j < len(lineas) and not lineas[j].strip() and j - fin < 2:     # máximo 2 líneas en blanco detrás
            borrar.add(j)
            j += 1
    return "".join(l for i, l in enumerate(lineas) if i not in borrar)


# ------------------------------------------------------------------
# Comprobaciones extra de seguridad
# ------------------------------------------------------------------

EXTENSIONES_A_REVISAR = (".py", ".pyw", ".js", ".html", ".json", ".txt", ".md", ".yml", ".yaml", ".bat", ".ps1")
_IGNORAR_CARPETAS = {"__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database", "node_modules",
                     "backups_codigo", "backups_autoconocimiento"}
_textos = {"cuando": 0.0, "archivos": {}}


def _todos_los_textos():
    """{rel: texto} de todo Arché (también .pyw, .js, .html, .json...): la autorevisión solo mira .py."""
    import time
    if time.time() - _textos["cuando"] < 60:
        return _textos["archivos"]
    salida = {}
    for raiz, carpetas, archivos in os.walk(comun.BASE):
        carpetas[:] = [c for c in carpetas if c not in _IGNORAR_CARPETAS and not c.startswith(("main_antes", "respaldo"))]
        for nombre in archivos:
            if not nombre.endswith(EXTENSIONES_A_REVISAR) or nombre.startswith("main_antes"):
                continue
            ruta = os.path.join(raiz, nombre)
            try:
                if os.path.getsize(ruta) > 3_000_000:
                    continue
                with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                    salida[os.path.relpath(ruta, comun.BASE).replace(os.sep, "/")] = f.read()
            except OSError:
                continue
    _textos.update(cuando=time.time(), archivos=salida)
    return salida


def se_menciona_fuera(nombre, rel):
    """True si el nombre aparece en cualquier otro archivo de Arché, o más de una vez en el suyo
    (aunque sea en un .pyw, un .js o un texto): entonces no se toca."""
    patron = re.compile(rf"(?<![\w]){re.escape(nombre)}(?![\w])")
    for otro, texto in _todos_los_textos().items():
        n = len(patron.findall(texto))
        if otro == rel:
            if n > 1:
                return True
        elif n:
            return True
    return False


def _globales_que_usa(fn):
    """Nombres libres que usa la función (no son parámetros ni variables propias)."""
    params = {a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs}
    if fn.args.vararg:
        params.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        params.add(fn.args.kwarg.arg)
    locales, usados = set(params), set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            (locales if isinstance(n.ctx, (ast.Store, ast.Del)) else usados).add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not fn:
            locales.add(n.name)
        elif isinstance(n, ast.arg):
            locales.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            locales.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            locales.add(n.name)
    return usados - locales


def _imports_de_modulo(arbol):
    """{nombre_ligado: texto_del_import} de los imports de nivel módulo."""
    salida = {}
    for n in arbol.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                salida[(a.asname or a.name).split(".")[0]] = f"import {a.name}"
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                salida[a.asname or a.name] = f"from {'.' * n.level}{n.module} import {a.name}"
    return salida


def es_pura_en_ambos(nombre, texto_queda, texto_importa):
    """True si la función solo usa cosas que significan LO MISMO en los dos archivos
    (builtins o los mismos imports). Si usa una variable o función propia de su archivo
    (una ruta, una config), importarla del otro cambiaría lo que hace."""
    try:
        a, b = ast.parse(texto_queda), ast.parse(texto_importa)
    except SyntaxError:
        return False
    fn = next((n for n in a.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nombre), None)
    if fn is None:
        return False
    imports_a, imports_b = _imports_de_modulo(a), _imports_de_modulo(b)
    for g in _globales_que_usa(fn):
        if g == nombre:
            return False                                 # recursiva: mejor no
        if g in imports_a and imports_a.get(g) == imports_b.get(g):
            continue
        if hasattr(builtins, g) and g not in imports_a and not _definido_en(a, g):
            continue
        return False
    return True


def _definido_en(arbol, nombre):
    for n in arbol.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nombre:
            return True
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nombre for t in n.targets):
            return True
    return False


# ------------------------------------------------------------------
# Candidatos
# ------------------------------------------------------------------

def candidatos_muertos(reporte=None):
    """{archivo: [nombre, ...]} de funciones de nivel módulo sin uso, que se pueden quitar."""
    if reporte is None:
        from core.IA import autorevision
        reporte = autorevision.buscar_codigo_muerto()
    no_tocar = set(_estado()["no_tocar"])
    por_archivo = {}
    for h in reporte.get("alta_confianza", []):
        rel, nombre = h["archivo"].replace("\\", "/"), h["nombre"]
        if nombre in NOMBRES_RESERVADOS or nombre.startswith(("test_", "cmd_", "comando_")):
            continue
        if f"{rel}::{nombre}" in no_tocar or not archivo_tocable(rel):
            continue
        if se_menciona_fuera(nombre, rel):
            continue
        por_archivo.setdefault(rel, []).append(nombre)
    return por_archivo


def candidatos_duplicados(lista=None):
    """[(archivo_que_queda, archivo_que_importa, nombre)] o (rel, rel, nombre) si está repetida en el mismo archivo."""
    if lista is None:
        from core.IA import autorevision
        lista = autorevision.buscar_funciones_duplicadas()
    no_tocar = set(_estado()["no_tocar"])
    salida = []
    for d in lista:
        a, b = d["archivo_a"].replace("\\", "/"), d["archivo_b"].replace("\\", "/")
        if d["funcion_a"] != d["funcion_b"]:
            continue                    # con el mismo cuerpo la línea 'def' también es igual: mismo nombre
        nombre = d["funcion_a"]
        if a != b and ("/" not in a or "/" not in b):
            continue                    # una copia en la raíz de Arche y otra en core/: suelen ser versiones viejas
        if a != b and os.path.dirname(a).split("/")[0] != os.path.dirname(b).split("/")[0]:
            continue
        if f"{b}::{nombre}" in no_tocar or not archivo_tocable(b):
            continue
        salida.append((a, b, nombre))
    return salida


def _importa_a(rel_origen, rel_destino):
    """True si rel_origen importa (de cualquier forma) el módulo de rel_destino: importarlo al revés
    crearía un import circular."""
    try:
        texto = _leer(rel_origen)
        arbol = ast.parse(texto)
    except (OSError, SyntaxError):
        return True
    destino = _modulo(rel_destino)
    corto = destino.rsplit(".", 1)[-1]
    paquete_origen = _modulo(rel_origen).rsplit(".", 1)[0] if not rel_origen.endswith("__init__.py") else _modulo(rel_origen)
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            if any(a.name == destino or a.name.startswith(destino + ".") for a in n.names):
                return True
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                partes = paquete_origen.split(".")
                partes = partes[:len(partes) - (n.level - 1)] if n.level > 1 else partes
                base = ".".join(p for p in partes + ([n.module] if n.module else []) if p)
            if base == destino or base.startswith(destino + "."):
                return True
            if any(f"{base}.{a.name}" == destino for a in n.names):
                return True
    return bool(re.search(rf"[\"']{re.escape(destino)}[\"']|[\"']{re.escape(corto)}[\"']", texto))


# ------------------------------------------------------------------
# Construir los cambios
# ------------------------------------------------------------------

def plan_muertas(rel, nombres):
    """(texto_nuevo, [(nombre, codigo)]) quitando esas funciones de nivel módulo, o (None, [])."""
    texto = _leer(rel)
    funciones = _funciones_de_primer_nivel(texto)
    lineas = texto.splitlines(keepends=True)
    rangos, quitadas = [], []
    for nombre in nombres:
        if nombre not in funciones or len(funciones[nombre]) != 1:
            continue
        ini, fin, decorada = funciones[nombre][0]
        if decorada:
            continue
        rangos.append((ini, fin))
        quitadas.append((nombre, "".join(lineas[ini - 1:fin])))
        if len(quitadas) >= FUNCIONES_POR_LOTE:
            break
    if not quitadas:
        return None, []
    nuevo = quitar_lineas(texto, rangos)
    try:
        ast.parse(nuevo)
    except SyntaxError:
        return None, []
    return nuevo, quitadas


def plan_duplicada(queda, importa, nombre):
    """(texto_nuevo_de_'importa', explicación) o (None, motivo)."""
    texto = _leer(importa)
    funciones = _funciones_de_primer_nivel(texto)
    if nombre not in funciones:
        return None, "no es de nivel módulo"
    lineas = texto.splitlines(keepends=True)
    if queda == importa:
        if len(funciones[nombre]) < 2:
            return None, "ya no está repetida"
        ini, fin, _ = funciones[nombre][0]          # la primera copia nunca se usaba: Python usa la última
        nuevo = quitar_lineas(texto, [(ini, fin)])
        return nuevo, f"quité la copia repetida de {nombre}() en {importa}"
    if len(funciones[nombre]) != 1:
        return None, "está repetida dentro del archivo"
    try:
        if nombre not in _funciones_de_primer_nivel(_leer(queda)):
            return None, "en el otro archivo no es de nivel módulo"
    except (OSError, SyntaxError):
        return None, "no pude leer el otro archivo"
    if _importa_a(queda, importa):
        return None, "importarla crearía un import circular"
    if not es_pura_en_ambos(nombre, _leer(queda), texto):
        return None, "usa cosas propias de su archivo (rutas, configuración): importarla cambiaría lo que hace"
    ini, fin, decorada = funciones[nombre][0]
    if decorada:
        return None, "tiene decorador"
    sangria = re.match(r"[ \t]*", lineas[ini - 1]).group(0)
    nl = "\r\n" if lineas[ini - 1].endswith("\r\n") else "\n"
    reemplazo = f"{sangria}from {_modulo(queda)} import {nombre}  # era una copia idéntica: se usa la de {queda}{nl}"
    nuevo = "".join(lineas[:ini - 1]) + reemplazo + "".join(lineas[fin:])
    try:
        ast.parse(nuevo)
    except SyntaxError:
        return None, "quedaba con error de sintaxis"
    return nuevo, f"{nombre}() de {importa} ahora usa la de {queda}"


def _guardar_en_cementerio(rel, quitadas, texto_antes):
    lote = comun.ahora().strftime("%Y%m%d_%H%M%S")
    carpeta = os.path.join(CARPETA_CEMENTERIO, lote)
    os.makedirs(carpeta, exist_ok=True)
    nombre_seguro = rel.replace("/", "__")
    with open(os.path.join(carpeta, nombre_seguro + ".antes"), "w", encoding="utf-8", newline="") as f:
        f.write(texto_antes)
    with open(os.path.join(carpeta, nombre_seguro), "w", encoding="utf-8", newline="") as f:
        f.write(f"# Funciones que Arché quitó de {rel} el {comun.ahora_txt()} porque nadie las usaba.\n"
                "# Para devolver una: «devuelve la función <nombre>».\n\n")
        for nombre, codigo in quitadas:
            f.write(codigo.rstrip() + "\n\n\n")
    return lote


# ------------------------------------------------------------------
# Un lote
# ------------------------------------------------------------------

def _aplicar(cambios, motivo):
    return _evo().aplicar_cambio_autonomo(cambios, motivo)


def hacer_un_lote(avisar=None):
    """Hace UN lote (duplicadas primero, luego código muerto). Devuelve (hecho: bool, texto)."""
    avisar = avisar or (lambda t: None)
    e = _estado()
    with _lock:
        # 1) duplicadas
        for queda, importa, nombre in candidatos_duplicados():
            try:
                nuevo, que = plan_duplicada(queda, importa, nombre)
            except (OSError, SyntaxError):
                continue
            if not nuevo:
                e["no_tocar"].append(f"{importa}::{nombre}")
                continue
            avisar(f"Limpieza: unifico {nombre}()...")
            ok, por_que = _aplicar({importa: nuevo}, f"limpieza: {que}")
            e = _estado()
            if ok:
                e["unificadas"].append({"archivo": importa, "nombre": nombre, "desde": queda, "cuando": comun.ahora_txt()})
                _guardar(e)
                return True, que
            e["no_tocar"].append(f"{importa}::{nombre}")
            _guardar(e)
            return False, f"no pude unificar {nombre}(): {por_que}"
        _guardar(e)

        # 2) código muerto
        for rel, nombres in candidatos_muertos().items():
            try:
                antes = _leer(rel)
                nuevo, quitadas = plan_muertas(rel, nombres)
            except (OSError, SyntaxError):
                continue
            if not nuevo:
                e = _estado()
                e["no_tocar"] += [f"{rel}::{n}" for n in nombres]
                _guardar(e)
                continue
            lista = ", ".join(n for n, _ in quitadas)
            avisar(f"Limpieza: quito de {rel} lo que nadie usa ({lista})...")
            ok, por_que = _aplicar({rel: nuevo}, f"limpieza: quitar funciones sin uso de {rel}: {lista}")
            e = _estado()
            if ok:
                lote = _guardar_en_cementerio(rel, quitadas, antes)
                for n, _ in quitadas:
                    e["quitadas"].append({"archivo": rel, "nombre": n, "cuando": comun.ahora_txt(), "lote": lote})
                _guardar(e)
                return True, f"quité {len(quitadas)} función(es) sin uso de {rel} ({lista})"
            e["no_tocar"] += [f"{rel}::{n}" for n, _ in quitadas]
            _guardar(e)
            return False, f"no pude limpiar {rel}: {por_que}"
    return False, "no hay nada más para limpiar"


def _ciclo(maximo_lotes=1, avisar=None):
    if _trabajando.is_set():
        return
    _trabajando.set()
    try:
        for _ in range(maximo_lotes):
            if lotes_hoy() >= LOTES_POR_DIA:
                break
            try:
                if _evo()._cambios_hoy() >= _evo().CAMBIOS_POR_DIA:
                    break
            except Exception:
                pass
            hecho, texto = hacer_un_lote(avisar)
            e = _estado()
            e["lotes_por_dia"][comun.hoy()] = lotes_hoy() + 1
            _guardar(e)
            comun.anotar(comun.ruta("limpieza_diario.jsonl"), {"cuando": comun.ahora_txt(), "hecho": hecho, "texto": texto})
            if not hecho and texto == "no hay nada más para limpiar":
                break
    finally:
        _trabajando.clear()


def _poner_mejora_en_total():
    """Lo seguro (imports y except) lo arregla la mejora continua en nivel 'total'. Una sola vez."""
    e = _estado()
    if e["nivel_puesto"]:
        return
    try:
        from core import mejora_continua
        if mejora_continua.nivel() != "total":
            mejora_continua.fijar_nivel("total")
        e["nivel_puesto"] = True
        _guardar(e)
    except Exception:
        pass


def revisar():
    """La llama el reloj del núcleo cada minuto."""
    e = _estado()
    if not e["activa"] or _trabajando.is_set():
        return
    _poner_mejora_en_total()
    if lotes_hoy() >= LOTES_POR_DIA:
        return
    try:
        from core.nucleo import ritmo
        if ritmo.minutos_inactivo() < MINUTOS_INACTIVO:
            return
    except Exception:
        return
    comun.en_hilo(_ciclo, 1, nombre="arche-limpieza")


# ------------------------------------------------------------------
# Red de seguridad: si una función quitada hacía falta, se devuelve sola
# ------------------------------------------------------------------

def devolver(nombre, rel=None):
    """Devuelve una función quitada (la agrega al final de su archivo). (ok, texto)."""
    e = _estado()
    registro = next((q for q in reversed(e["quitadas"]) if q["nombre"] == nombre and (rel is None or q["archivo"] == rel)), None)
    if not registro:
        return False, f"no tengo «{nombre}» en el cementerio"
    ruta_cem = os.path.join(CARPETA_CEMENTERIO, registro["lote"], registro["archivo"].replace("/", "__"))
    try:
        with open(ruta_cem, "r", encoding="utf-8") as f:
            guardado = f.read()
        codigo = next((c for n, c in _funciones_de_texto(guardado) if n == nombre), None)
        if not codigo:
            return False, "no encontré su código en el cementerio"
        destino = os.path.join(comun.BASE, registro["archivo"])
        with open(destino, "r", encoding="utf-8-sig") as f:
            actual = f.read()
        if re.search(rf"(?m)^def\s+{re.escape(nombre)}\s*\(", actual):
            return False, "ya está otra vez en su archivo"
        nuevo = actual.rstrip() + "\n\n\n" + codigo.rstrip() + "\n"
        ast.parse(nuevo)
        with open(destino, "w", encoding="utf-8", newline="") as f:
            f.write(nuevo)
    except (OSError, SyntaxError) as err:
        return False, f"no pude devolverla ({err})"
    e["quitadas"] = [q for q in e["quitadas"] if q is not registro and not (q["nombre"] == nombre and q["archivo"] == registro["archivo"])]
    e["devueltas"].append({"archivo": registro["archivo"], "nombre": nombre, "cuando": comun.ahora_txt()})
    e["no_tocar"].append(f"{registro['archivo']}::{nombre}")
    _guardar(e)
    return True, f"devolví {nombre}() a {registro['archivo']}"


def _funciones_de_texto(texto):
    lineas = texto.splitlines(keepends=True)
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return []
    return [(n.name, "".join(lineas[(n.decorator_list[0].lineno if n.decorator_list else n.lineno) - 1:n.end_lineno]))
            for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


_PATRON_FALTA = re.compile(r"name '(\w+)' is not defined|has no attribute '(\w+)'|cannot import name '(\w+)'")


def revisar_error(exc):
    """Si el error nombra una función que quitamos, la devuelve y avisa. Devuelve el nombre o None."""
    m = _PATRON_FALTA.search(str(exc))
    if not m:
        return None
    nombre = next(g for g in m.groups() if g)
    if not any(q["nombre"] == nombre for q in _estado()["quitadas"]):
        return None
    ok, texto = devolver(nombre)
    if ok:
        comun.informe(f"Me equivoqué al limpiar: {nombre}() sí se usaba. Ya la devolví a su archivo y no la vuelvo "
                      "a tocar. Si esa orden falló, repítela.", importante=True, nivel="alerta", origen="limpieza",
                      con_prefijo=False)
        return nombre
    return None


_ganchos = {"listo": False}


def instalar():
    """Conecta la red de seguridad y silencia el aviso de la autorevisión al abrir."""
    if _ganchos["listo"]:
        return
    _ganchos["listo"] = True
    try:
        from core.IA import registro_errores
        original = registro_errores.registrar

        def registrar_y_revisar(exc, *a, **k):
            try:
                revisar_error(exc)
            except Exception:
                pass
            return original(exc, *a, **k)
        registro_errores.registrar = registrar_y_revisar
    except Exception:
        pass
    try:
        from core.IA import autorevision
        original_bg = autorevision.iniciar_autorevision_en_background

        def en_background_callada(*a, **k):
            avisar_original = k.get("avisar")

            def guardar_para_la_noche(texto):
                e = _estado()
                if e["activa"]:
                    e["ultimo_aviso_autorevision"] = str(texto)[:400]
                    _guardar(e)
                elif avisar_original:
                    avisar_original(texto)
            if "avisar" in k:
                k["avisar"] = guardar_para_la_noche
            return original_bg(*a, **k)
        autorevision.iniciar_autorevision_en_background = en_background_callada
    except Exception:
        pass


# ------------------------------------------------------------------
# Para el resumen de la noche
# ------------------------------------------------------------------

def pendientes():
    """(funciones sin uso que puede quitar, duplicadas que puede unificar). Solo cuenta lo que de verdad
    haría: lo que tocaría el nombre en otro archivo, crearía un import circular o cambiaría lo que hace, no."""
    try:
        muertas = 0
        for rel, nombres in candidatos_muertos().items():
            try:
                funciones = _funciones_de_primer_nivel(_leer(rel))
            except (OSError, SyntaxError):
                continue
            muertas += sum(1 for n in nombres if n in funciones and len(funciones[n]) == 1 and not funciones[n][0][2])
        duplicadas = 0
        for queda, importa, nombre in candidatos_duplicados():
            try:
                if plan_duplicada(queda, importa, nombre)[0]:
                    duplicadas += 1
            except (OSError, SyntaxError):
                continue
        return muertas, duplicadas
    except Exception:
        return None, None


def resumen_de_hoy():
    e = _estado()
    hoy = comun.hoy()
    quitadas = [q for q in e["quitadas"] if q["cuando"].startswith(hoy)]
    unificadas = [u for u in e["unificadas"] if u["cuando"].startswith(hoy)]
    devueltas = [d for d in e["devueltas"] if d["cuando"].startswith(hoy)]
    if not (quitadas or unificadas or devueltas):
        return None
    partes = []
    if quitadas:
        partes.append(f"quité {len(quitadas)} función(es) que nadie usaba (están en el cementerio)")
    if unificadas:
        partes.append(f"unifiqué {len(unificadas)} función(es) duplicada(s)")
    if devueltas:
        partes.append(f"devolví {len(devueltas)} que sí hacían falta")
    return "Limpieza de mi código: " + ", ".join(partes) + "."


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_DEVUELVE = re.compile(r"^(?:devuelve|restaura|recupera)\s+la\s+funcion\s+(\w+)$")


def manejar(comando):
    c = comun.norm(comando)
    if c in ("estado de la limpieza", "limpieza", "como va la limpieza", "limpieza de codigo"):
        e = _estado()
        muertas, duplicadas = pendientes()
        comun.msg(f"Limpieza sola {'encendida' if e['activa'] else 'apagada'}. Hoy hice {lotes_hoy()}/{LOTES_POR_DIA} lotes. "
                  f"En total quité {len(e['quitadas'])} funciones sin uso y unifiqué {len(e['unificadas'])} duplicadas"
                  f" (devolví {len(e['devueltas'])}). Me faltan: "
                  + (f"{muertas} sin uso y {duplicadas} duplicadas." if muertas is not None else "no pude contarlas ahora.")
                  + " Trabajo cuando llevas 20 minutos sin usar el PC.")
        return True
    if c in ("que limpiaste", "que has limpiado", "que quitaste de tu codigo", "cementerio"):
        e = _estado()
        filas = [f"  • {q['cuando'][:16]} quité {q['nombre']}() de {q['archivo']}" for q in e["quitadas"][-8:]]
        filas += [f"  • {u['cuando'][:16]} {u['nombre']}() de {u['archivo']} ahora usa la de {u['desde']}" for u in e["unificadas"][-4:]]
        comun.msg("Lo último que limpié:\n" + "\n".join(filas) if filas else "Todavía no he limpiado nada.")
        return True
    if c in ("limpiate ahora", "limpia tu codigo ahora", "limpieza ahora", "haz un lote de limpieza"):
        if _trabajando.is_set():
            comun.msg("Ya estoy limpiando. Te aviso cuando termine.")
            return True
        comun.msg("Hago un lote de limpieza ahora. Lo pruebo todo en una copia aparte, así que tarda unos minutos.")

        def _ahora():
            if _trabajando.is_set():
                return
            _trabajando.set()
            try:
                hecho, texto = hacer_un_lote(avisar=lambda t: comun.msg(t, voz=False))
                e = _estado()
                e["lotes_por_dia"][comun.hoy()] = lotes_hoy() + 1
                _guardar(e)
                comun.msg(("Listo: " if hecho else "Limpieza: ") + texto + ".")
            finally:
                _trabajando.clear()
        comun.en_hilo(_ahora, nombre="arche-limpieza")
        return True
    m = _R_DEVUELVE.match(c)
    if m:
        ok, texto = devolver(m.group(1))
        comun.msg(("Listo, " if ok else "No pude: ") + texto + ".")
        return True
    if c in ("limpieza apagada", "no te limpies sola", "apaga la limpieza"):
        e = _estado(); e["activa"] = False; _guardar(e)
        comun.msg("Listo, ya no limpio mi código sola. Vuelvo a avisarte lo que encuentre al abrir.")
        return True
    if c in ("limpieza encendida", "limpiate sola", "activa la limpieza"):
        e = _estado(); e["activa"] = True; _guardar(e)
        comun.msg("Listo, limpio mi código sola cuando no estés usando el PC y te lo cuento en la noche.")
        return True
    return False
