"""
imaginacion.py
--------------
Ubicacion: Arche/core/nucleo/imaginacion.py

IMAGINACIÓN: Arché piensa ANTES de actuar.

  1. Antes de cambiar su propio código (cualquier cambio de la evolución, la fábrica,
     una fusión o una presa del Depredador), imagina qué puede pasar:
       - qué funciones agrega, cambia o quita (comparando el código viejo y el nuevo),
       - quién más en Arché usa esas funciones (análisis de impacto),
       - si cambia cómo se llama una función que otros usan, o quita una que otros llaman,
       - si se parece a algún fracaso conocido (lecciones del Cronista),
       - y, si el riesgo lo amerita, le pide al modelo 3 futuros posibles.
     Si ve que el cambio rompería algo seguro, lo descarta sin gastar la prueba completa.
     Si no, deja que la caja de arena decida como siempre.
  2. «imagina: <plan>» o «qué pasaría si <algo>» -> futuros posibles de un plan tuyo.
  3. PENSAMIENTO EN PARALELO: «piensa a fondo: <pregunta>» -> piensa con 3 enfoques a la
     vez (5 desde el Núcleo 2.0) y un juez arma la mejor respuesta.
"""

import ast
import concurrent.futures
import os
import re

from core.nucleo import comun

ARCH = comun.ruta("imaginacion.json")
_instalado = False


# ------------------------------------------------------------------
# Comparar código viejo y nuevo
# ------------------------------------------------------------------

def _funciones(texto):
    """{nombre: (firma, volcado)} de funciones de primer nivel y métodos (Clase.metodo)."""
    try:
        arbol = ast.parse(texto or "")
    except SyntaxError:
        return {}
    salida = {}

    def _firma(f):
        a = f.args
        return (tuple(x.arg for x in a.posonlyargs + a.args), a.vararg is not None, tuple(x.arg for x in a.kwonlyargs),
                a.kwarg is not None, len(a.defaults))

    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            salida[nodo.name] = (_firma(nodo), ast.dump(nodo, include_attributes=False))
        elif isinstance(nodo, ast.ImportFrom):
            # «from x import f»: f sigue existiendo en este módulo (la limpieza unifica así las duplicadas)
            for alias in nodo.names:
                if alias.name != "*":
                    salida.setdefault(alias.asname or alias.name, ("alias", ast.dump(nodo, include_attributes=False)))
        elif isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name) and isinstance(nodo.value, (ast.Name, ast.Attribute)):
                    salida.setdefault(t.id, ("alias", ast.dump(nodo, include_attributes=False)))
        elif isinstance(nodo, ast.ClassDef):
            for sub in nodo.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    salida[f"{nodo.name}.{sub.name}"] = (_firma(sub), ast.dump(sub, include_attributes=False))
    return salida


def comparar(viejo, nuevo):
    fv, fn = _funciones(viejo), _funciones(nuevo)
    agregadas = sorted(set(fn) - set(fv))
    quitadas = sorted(set(fv) - set(fn))
    cambiadas = sorted(n for n in set(fv) & set(fn) if fv[n][1] != fn[n][1])
    firma_cambiada = sorted(n for n in cambiadas if fv[n][0] != fn[n][0] and "alias" not in (fv[n][0], fn[n][0]))
    return {"agregadas": agregadas, "quitadas": quitadas, "cambiadas": cambiadas, "firma_cambiada": firma_cambiada}


_IGNORAR = {"__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database", "backups_codigo",
            "backups_autoconocimiento", "node_modules", "habilidades_auto"}


def indice_de_llamadas():
    """{nombre_funcion: [{"archivo", "desde"}]} de todo Arché, leyendo cada archivo UNA vez (igual idea que
    el análisis de impacto de core/IA/gran_sabio.py, pero sin recorrer el proyecto por cada función)."""
    indice = {}
    for raiz, carpetas, archivos in os.walk(comun.BASE):
        carpetas[:] = [c for c in carpetas if c not in _IGNORAR and not c.startswith("main_antes")]
        for nombre in archivos:
            if not nombre.endswith(".py"):
                continue
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, comun.BASE).replace("\\", "/")
            try:
                with open(ruta, "r", encoding="utf-8-sig") as f:
                    arbol = ast.parse(f.read())
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                continue
            for top in arbol.body:
                desde = top.name if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "nivel de módulo"
                for n in ast.walk(top):
                    if isinstance(n, ast.Call):
                        f = n.func
                        llamado = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                        if llamado and llamado != desde:
                            lista = indice.setdefault(llamado, [])
                            if not lista or lista[-1] != {"archivo": rel, "desde": desde}:
                                lista.append({"archivo": rel, "desde": desde})
    return indice


_textos = {}


def _menciona_modulo(rel_llamador, rel_propio):
    """Muchas funciones se llaman igual en varios módulos (manejar, iniciar...). Solo cuenta como
    usuario un archivo que de verdad nombra al módulo cambiado."""
    modulo = os.path.splitext(os.path.basename(rel_propio))[0]
    if rel_llamador not in _textos:
        try:
            with open(os.path.join(comun.BASE, rel_llamador), "r", encoding="utf-8-sig") as f:
                _textos[rel_llamador] = f.read()
        except OSError:
            _textos[rel_llamador] = ""
    return re.search(rf"\b{re.escape(modulo)}\b", _textos[rel_llamador]) is not None


def _llamadores(nombre, rel_propio, indice):
    """Lugares de Arché (fuera del mismo archivo) que llaman a esa función."""
    corto = nombre.split(".")[-1]
    if corto.startswith("__"):
        return []
    return [l for l in indice.get(corto, []) if l["archivo"] != rel_propio and _menciona_modulo(l["archivo"], rel_propio)]


# ------------------------------------------------------------------
# 1. Imaginar un cambio de código
# ------------------------------------------------------------------

def imaginar_cambio(cambios, motivo="", usar_modelo=None):
    """
    cambios: {"core/x.py": "texto nuevo"}. Devuelve
      {"riesgo": 0-100, "decision": "aplicar"|"descartar", "por_que": str, "detalle": {...}, "futuros": [...], "leccion": str|None}
    """
    riesgo = 0
    detalle = {}
    rompe = []
    indice = None
    for rel, nuevo in (cambios or {}).items():
        rel = rel.replace("\\", "/")
        if not rel.endswith(".py"):
            continue
        ruta = os.path.join(comun.BASE, rel)
        try:
            with open(ruta, "r", encoding="utf-8-sig") as f:
                viejo = f.read()
        except OSError:
            viejo = ""
        d = comparar(viejo, nuevo)
        d["usuarios"] = {}
        if (d["quitadas"] or d["cambiadas"]) and indice is None:
            _textos.clear()
            indice = indice_de_llamadas()
        for nombre in d["quitadas"] + d["cambiadas"]:
            ll = _llamadores(nombre, rel, indice)
            if ll:
                d["usuarios"][nombre] = [f"{l['desde']} ({l['archivo']})" for l in ll[:6]]
        for nombre in d["quitadas"]:
            if d["usuarios"].get(nombre):
                rompe.append(f"quita {nombre}() pero la usan {', '.join(d['usuarios'][nombre][:3])}")
        for nombre in d["firma_cambiada"]:
            if d["usuarios"].get(nombre):
                riesgo += 35
        riesgo += 6 * len(d["cambiadas"]) + 3 * sum(len(v) for v in d["usuarios"].values()) + 2 * len(d["agregadas"])
        if not viejo:
            riesgo += 5            # archivo nuevo: poco riesgo para lo demás
        detalle[rel] = d
    riesgo = min(100, riesgo + (100 if rompe else 0))

    leccion = None
    try:
        from core.nucleo import cronista
        leccion = cronista.advertir(motivo)
    except Exception:
        pass

    if usar_modelo is None:
        try:
            from core.nucleo import analista
            usar_modelo = analista.version() >= 2 or riesgo >= 30
        except Exception:
            usar_modelo = riesgo >= 30
    futuros = []
    if usar_modelo and not rompe:
        resumen = "; ".join(f"{rel}: agrega {d['agregadas'][:5]}, cambia {d['cambiadas'][:5]}, quita {d['quitadas'][:5]}, "
                            f"usadas por {list(d['usuarios'].items())[:4]}" for rel, d in detalle.items())
        r = comun.pensar(
            f"Arché (una asistente en Python) va a cambiar su propio código. Motivo: «{motivo}». Cambios: {resumen}.\n"
            "Imagina 3 futuros posibles después de aplicarlo (uno bueno, uno malo, uno inesperado). Responde SOLO JSON: "
            "[{\"futuro\": \"...\", \"probabilidad\": 0-100, \"gravedad\": 0-10}]",
            max_tokens=400, temperatura=0.5, preferir_nube=False)
        lista = comun.json_de(r)
        if isinstance(lista, list):
            for f in lista[:3]:
                if isinstance(f, dict) and f.get("futuro"):
                    try:
                        p, g = int(f.get("probabilidad", 0)), int(f.get("gravedad", 0))
                    except (TypeError, ValueError):
                        p, g = 0, 0
                    futuros.append({"futuro": str(f["futuro"])[:200], "probabilidad": max(0, min(100, p)),
                                    "gravedad": max(0, min(10, g))})
            peor = max((f["probabilidad"] * f["gravedad"] for f in futuros), default=0)
            riesgo = min(100, riesgo + peor // 25)

    if rompe:
        decision, por_que = "descartar", "rompería algo seguro: " + "; ".join(rompe[:3])
    elif riesgo >= 85:
        decision, por_que = "descartar", f"riesgo imaginado demasiado alto ({riesgo}/100)"
    else:
        decision, por_que = "aplicar", f"riesgo {riesgo}/100; la caja de arena decide"
    resultado = {"cuando": comun.ahora_txt(), "motivo": motivo[:200], "riesgo": riesgo, "decision": decision,
                 "por_que": por_que, "detalle": detalle, "futuros": futuros, "leccion": leccion}
    historial = comun.cargar(ARCH, [])
    historial.append(resultado)
    comun.guardar(ARCH, historial[-30:])
    return resultado


def instalar():
    """Se pone delante de evolucion.aplicar_cambio_autonomo (sin modificar ese archivo)."""
    global _instalado
    if _instalado:
        return
    from core import evolucion as evo
    original = evo.aplicar_cambio_autonomo

    def aplicar_con_imaginacion(cambios, motivo, prueba_extra=None):
        try:
            vision = imaginar_cambio(cambios, motivo)
        except Exception:
            vision = None
        if vision:
            try:
                evo._diario("imaginacion", f"{vision['decision']}: {vision['por_que']}", motivo=motivo)
            except Exception:
                pass
            if vision["decision"] == "descartar":
                comun.informe(f"Imaginé el cambio «{motivo[:80]}» y lo descarté antes de probarlo: {vision['por_que']}.",
                              origen="imaginacion")
                return False, "la imaginación lo descartó: " + vision["por_que"]
        return original(cambios, motivo, prueba_extra=prueba_extra)

    evo.aplicar_cambio_autonomo = aplicar_con_imaginacion
    _instalado = True


# ------------------------------------------------------------------
# 2. Imaginar un plan
# ------------------------------------------------------------------

def imaginar_plan(objetivo, pasos=None, rapido=False):
    """Texto con futuros posibles y advertencias, o None si el modelo no respondió."""
    leccion = None
    try:
        from core.nucleo import cronista
        leccion = cronista.advertir(objetivo + " " + " ".join(pasos or []))
    except Exception:
        pass
    n = 2 if rapido else 4
    r = comun.pensar(
        f"Plan de {comun.nombre_usuario()}: «{objetivo}»."
        + (f" Pasos: {pasos}." if pasos else "")
        + f"\nImagina {n} futuros posibles si se hace así (incluye al menos uno que salga mal y por qué). Para cada uno: "
          "qué pasa, qué tan probable (baja/media/alta) y cómo prevenir lo malo. Sé concreto y breve.",
        max_tokens=300 if rapido else 600, temperatura=0.6)
    if not r and not leccion:
        return None
    return ((r or "").strip() + (f"\n⚠ {leccion}" if leccion else "")).strip()


# ------------------------------------------------------------------
# 3. Pensamiento en paralelo
# ------------------------------------------------------------------

ENFOQUES = [
    ("directo", 0.3, "Responde de la forma más clara y directa posible."),
    ("crítico", 0.4, "Busca qué podría estar mal, los riesgos y las trampas antes de responder."),
    ("creativo", 0.9, "Busca una solución poco obvia o ingeniosa."),
    ("práctico", 0.4, "Responde con pasos concretos que se puedan hacer hoy con poco dinero."),
    ("contrario", 0.7, "Defiende la postura opuesta a la obvia y mira si tiene razón."),
]


def pensamiento_en_paralelo(pregunta):
    try:
        from core.nucleo import analista
        n = 5 if analista.version() >= 2 else 3
    except Exception:
        n = 3
    enfoques = ENFOQUES[:n]

    def _una(enfoque):
        nombre, temp, instruccion = enfoque
        return nombre, comun.pensar(f"{instruccion}\n\nPregunta: {pregunta}", max_tokens=450, temperatura=temp)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        respuestas = [r for r in pool.map(_una, enfoques) if r[1]]
    if not respuestas:
        return "No pude pensar: ningún modelo respondió (¿está Ollama encendido?)."
    if len(respuestas) == 1:
        return respuestas[0][1]
    juez = comun.pensar(
        f"Pregunta: {pregunta}\n\nVarias líneas de pensamiento respondieron:\n\n" +
        "\n\n".join(f"[{n}] {t}" for n, t in respuestas) +
        "\n\nComo juez, arma LA mejor respuesta final: quédate con lo correcto de cada una, descarta lo que esté mal "
        "y dilo en español claro. Al final, en una línea, qué línea aportó más.",
        max_tokens=700, temperatura=0.2)
    return juez or respuestas[0][1]


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_IMAGINA = re.compile(r"^(?:imagina|imaginate)\s*:?\s+(.{6,})$|^que pasaria si\s+(.{6,})$")
_R_PARALELO = re.compile(r"^(?:piensa a fondo|piensa en paralelo|pensamiento en paralelo|piensalo bien|analiza a fondo)\s*:?\s+(.{4,})$")


def manejar(comando):
    texto = (comando or "").strip()
    c = comun.norm(texto)
    m = _R_PARALELO.match(c)
    if m:
        pregunta = texto.split(":", 1)[1].strip() if ":" in texto else m.group(1)
        comun.msg("Pienso en paralelo con varios enfoques...")
        comun.en_hilo(lambda: comun.msg(pensamiento_en_paralelo(pregunta)), nombre="arche-paralelo")
        return True
    m = _R_IMAGINA.match(c)
    if m:
        plan = texto.split(":", 1)[1].strip() if ":" in texto else (m.group(1) or m.group(2))
        comun.msg("Imaginando futuros...")
        comun.en_hilo(lambda: comun.msg(imaginar_plan(plan) or "No pude imaginar nada (¿hay modelo disponible?)."),
                      nombre="arche-imaginacion")
        return True
    if c in ("que imaginaste", "tus imaginaciones", "que cambios imaginaste"):
        hist = comun.cargar(ARCH, [])
        if not hist:
            comun.msg("Todavía no he imaginado ningún cambio de mi código.")
        else:
            comun.msg("Lo último que imaginé antes de cambiarme:\n" + "\n".join(
                f"  • {h['cuando'][:16]} — {h['motivo'][:60]} → {h['decision']} ({h['por_que'][:80]})" for h in hist[-6:]))
        return True
    return False
