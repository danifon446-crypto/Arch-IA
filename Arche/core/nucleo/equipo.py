"""
equipo.py
---------
Ubicacion: Arche/core/nucleo/equipo.py

EL EQUIPO DE ARCHÉ: Arché deja de ser una sola. Tiene miembros especializados y los
coordina como un equipo que trabaja EN PARALELO en una misión.

  estratega    -> parte la misión en tareas, revisa lecciones de fracasos e imagina riesgos
  investigador -> busca en internet, lee páginas y resume con fuentes
  programador  -> escribe el código que pide la misión (en la carpeta de la misión,
                  NUNCA en el código de Arché)
  probador     -> revisa ese código en cuarentena y lo corre aislado para ver si funciona
  cronista     -> escribe el informe final de la misión

NIVELES: cada miembro sube de nivel SOLO con experiencia (2 xp por tarea bien hecha):
    Novato (0 xp) -> Competente (10 xp) -> Experto (30 xp) -> Maestro (80 xp)
Cada nivel le da más capacidad: más búsquedas y páginas leídas, revisar su propio
código, corregirlo con los errores del probador, informes más completos. Además
guardan lo que aprenden de sus errores para la próxima misión.
Si quieres, les pones nombre («nombra al investigador Nova»); es solo para ti, no les da poder.

Comandos:
  misión: <lo que quieres>         equipo: <lo que quieres>
  tu equipo                        misiones
  nombra al <rol> <Nombre>          informe de la misión 3
  abre la misión 3                 cancela la misión
"""

import concurrent.futures
import json
import os
import re
import subprocess
import sys
import threading

from core.nucleo import comun

ARCH = comun.ruta("equipo.json")
CARPETA_MISIONES = os.path.join(comun.CARPETA, "misiones")
os.makedirs(CARPETA_MISIONES, exist_ok=True)

ROLES = {
    "estratega": "planifica y revisa riesgos",
    "investigador": "busca y resume información de internet",
    "programador": "escribe código",
    "probador": "prueba el código de forma aislada",
    "cronista": "escribe el informe final",
}
RANGOS = [("Novato", 0), ("Competente", 10), ("Experto", 30), ("Maestro", 80)]
MAX_PASOS = 7

_lock = threading.RLock()
_cancelar = threading.Event()
_mision_en_curso = {"id": None}


# ------------------------------------------------------------------
# Estado del equipo
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("equipo", {})
    for rol in ROLES:
        e["equipo"].setdefault(rol, {"nombre": None, "xp": 0, "rango": "Novato", "experiencia": [], "tareas": 0})
    e.setdefault("misiones", [])
    return e


def _guardar(e):
    e["misiones"] = e["misiones"][-60:]
    for s in e["equipo"].values():
        s["experiencia"] = s["experiencia"][-12:]
    comun.guardar(ARCH, e)


def rango_de(sub):
    rango = RANGOS[0][0]
    for nombre, xp in RANGOS:
        if sub.get("xp", 0) >= xp:
            rango = nombre
    return rango


def nivel(sub):
    """0 novato, 1 competente, 2 experto, 3 maestro."""
    return [r for r, _ in RANGOS].index(rango_de(sub))


def misiones_completadas():
    return sum(1 for m in _estado()["misiones"] if m.get("estado") == "completada")


def niveles_del_equipo():
    """Suma de los niveles de todos los miembros (0 a 15)."""
    return sum(nivel(s) for s in _estado()["equipo"].values())


def _quien(rol, e=None):
    e = e or _estado()
    s = e["equipo"][rol]
    return f"{s['nombre']} ({rol})" if s.get("nombre") else f"el {rol}"


def nombrar(rol, nombre):
    with _lock:
        e = _estado()
        s = e["equipo"][rol]
        viejo = s.get("nombre")
        s["nombre"] = nombre
        _guardar(e)
    if viejo:
        return f"Listo, {viejo} ahora se llama {nombre}."
    return f"Listo, el {rol} ahora se llama {nombre}. Sigue en nivel {rango_de(s)}: sube con experiencia."


def _que_gana(rol, niv):
    mejoras = {
        "investigador": ["busca 2 veces y lee 2 páginas", "busca 3 veces y lee 3 páginas",
                         "busca 3 veces, lee 4 páginas y contrasta fuentes", "investiga a fondo: 4 búsquedas y 5 páginas"],
        "programador": ["escribe el código y lo corrige una vez si el probador encuentra errores",
                        "revisa su propio código antes de entregarlo y corrige una vez",
                        "revisa su código y corrige hasta dos veces", "revisa dos veces y corrige hasta tres veces"],
        "probador": ["revisa el código en cuarentena y lo corre aislado", "además explica cada fallo",
                     "además propone cómo arreglarlo", "además prueba casos raros"],
        "estratega": ["planea y revisa lecciones de fracasos", "además imagina riesgos del plan",
                      "además pone un plan B", "planea con riesgos, plan B y prioridades"],
        "cronista": ["hace un informe con fuentes", "además pone próximos pasos",
                     "además explica las decisiones tomadas", "informe completo con decisiones y lecciones"],
    }
    lista = mejoras.get(rol, [""])
    return lista[min(niv, len(lista) - 1)] + "."


def _ganar_xp(rol, puntos, leccion=None):
    with _lock:
        e = _estado()
        s = e["equipo"][rol]
        antes = rango_de(s)
        s["xp"] = s.get("xp", 0) + puntos
        s["tareas"] = s.get("tareas", 0) + 1
        if leccion:
            s["experiencia"].append(leccion[:200])
        s["rango"] = rango_de(s)
        _guardar(e)
    if s["rango"] != antes:
        comun.informe(f"{_quien(rol)} subió de nivel: {antes} → {s['rango']}. Ahora {_que_gana(rol, nivel(s))}",
                      nivel="logro", origen="equipo")


def _sistema(rol, e):
    s = e["equipo"][rol]
    nombre = s.get("nombre") or f"el {rol}"
    exp = "\n".join(f"- {x}" for x in s.get("experiencia", [])[-6:])
    return (f"Eres {nombre}, miembro del equipo de Arché. Tu rol: {ROLES[rol]}. Nivel: {rango_de(s)}. "
            f"Trabajas para {comun.nombre_usuario()}. Responde en español, directo y útil."
            + (f"\nLo que aprendiste en misiones anteriores:\n{exp}" if exp else ""))


# ------------------------------------------------------------------
# Misiones
# ------------------------------------------------------------------

def _carpeta(id_mision):
    c = os.path.join(CARPETA_MISIONES, f"mision_{id_mision}")
    os.makedirs(c, exist_ok=True)
    return c


def _registrar_mision(objetivo):
    with _lock:
        e = _estado()
        id_m = max((m["id"] for m in e["misiones"]), default=0) + 1
        e["misiones"].append({"id": id_m, "objetivo": objetivo, "estado": "en curso", "inicio": comun.ahora_txt(),
                              "pasos": []})
        _guardar(e)
    return id_m


def _actualizar_mision(id_m, **cambios):
    with _lock:
        e = _estado()
        for m in e["misiones"]:
            if m["id"] == id_m:
                m.update(cambios)
        _guardar(e)


def planificar(objetivo, e=None):
    """Lista de pasos [{"rol", "tarea", "depende": [índices]}]."""
    e = e or _estado()
    est = e["equipo"]["estratega"]
    avisos = []
    if True:
        try:
            from core.nucleo import cronista
            a = cronista.advertir(objetivo)
            if a:
                avisos.append(a)
        except Exception:
            pass
    r = comun.pensar(
        f"Misión de {comun.nombre_usuario()}: «{objetivo}».\n"
        "Parte la misión en 2 a 6 tareas para el equipo. Roles disponibles: investigador (busca en internet), "
        "programador (escribe código Python), probador (prueba el código del programador), cronista (informe final; "
        "siempre va al final y depende de todo). Usa solo los roles que hagan falta.\n"
        "Responde SOLO JSON: [{\"rol\": \"...\", \"tarea\": \"...\", \"depende\": [números de tareas anteriores, desde 0]}]"
        + (f"\nTen en cuenta esta advertencia: {avisos[0]}" if avisos else ""),
        sistema=_sistema("estratega", e), max_tokens=600, temperatura=0.3)
    plan = comun.json_de(r)
    pasos = []
    if isinstance(plan, list):
        for i, p in enumerate(plan[:MAX_PASOS]):
            if not isinstance(p, dict) or p.get("rol") not in ROLES or p.get("rol") == "estratega":
                continue
            deps = [int(d) for d in (p.get("depende") or []) if str(d).isdigit() and int(d) < i]
            pasos.append({"rol": p["rol"], "tarea": str(p.get("tarea", ""))[:400], "depende": deps})
    if not pasos:      # plan de respaldo si el modelo no respondió bien
        pasos = [{"rol": "investigador", "tarea": objetivo, "depende": []}]
        if re.search(r"\b(programa|codigo|código|script|app|funcion|función|calcula|automatiza|bot)\b", objetivo.lower()):
            pasos += [{"rol": "programador", "tarea": objetivo, "depende": [0]},
                      {"rol": "probador", "tarea": "probar el código", "depende": [1]}]
    if pasos[-1]["rol"] != "cronista":
        pasos.append({"rol": "cronista", "tarea": "informe final", "depende": list(range(len(pasos)))})
    # el probador siempre depende del programador anterior
    for i, p in enumerate(pasos):
        if p["rol"] == "probador":
            prog = [j for j in range(i) if pasos[j]["rol"] == "programador"]
            p["depende"] = sorted(set(p["depende"]) | set(prog[-1:]))
    if nivel(est) >= 1:
        try:
            from core.nucleo import imaginacion
            riesgos = imaginacion.imaginar_plan(objetivo, [p["tarea"] for p in pasos], rapido=True)
            if riesgos:
                avisos.append(riesgos)
        except Exception:
            pass
    return pasos, avisos


# --- lo que hace cada rol ---

def _investigar(tarea, contexto, e):
    from core import web
    s = e["equipo"]["investigador"]
    n = nivel(s)
    busquedas, paginas = [(2, 2), (3, 3), (3, 4), (4, 5)][n]
    if not web.hay_internet():
        return "No había internet para investigar.", []
    consultas = [tarea]
    if busquedas > 1:
        r = comun.json_de(comun.pensar(f"Dame {busquedas} búsquedas web cortas (JSON lista de textos) para investigar: "
                                       f"{tarea}", max_tokens=120, temperatura=0.2))
        if isinstance(r, list) and r:
            consultas = [str(x) for x in r[:busquedas]]
    resultados, fuentes = [], []
    for q in consultas:
        for res in web.buscar(q, 4):
            if res["url"] not in fuentes:
                fuentes.append(res["url"])
                resultados.append(res)
    textos = []
    for res in resultados[:paginas]:
        cuerpo = web.leer_pagina(res["url"], maximo=2500)
        textos.append(f"[{res['titulo']}] {res['url']}\n{cuerpo or res.get('resumen', '')}")
    for res in resultados[paginas:paginas + 4]:
        textos.append(f"[{res['titulo']}] {res['url']}\n{res.get('resumen', '')}")
    resumen = comun.pensar(
        f"Tarea: {tarea}\nContexto de la misión: {contexto[:1500]}\n\nCon SOLO esta información, escribe un resumen útil "
        "(8-12 líneas) y cita las fuentes por número de corchete.\n\n" + "\n\n".join(textos)[:9000],
        sistema=_sistema("investigador", e), max_tokens=700, temperatura=0.3)
    return resumen or "No pude resumir lo que encontré.", fuentes[:paginas + 4]


def _extraer_archivos(texto):
    """De la respuesta del modelo a {nombre: contenido}. Acepta JSON o bloques ```python con # archivo: x.py"""
    datos = comun.json_de(texto)
    if isinstance(datos, dict) and datos and all(isinstance(v, str) for v in datos.values()):
        return {os.path.basename(k): v for k, v in datos.items() if k.endswith((".py", ".txt", ".md", ".json"))}
    archivos = {}
    for i, bloque in enumerate(re.findall(r"```(?:python|py)?\s*\n(.*?)```", texto or "", re.S)):
        m = re.match(r"\s*#\s*(?:archivo|file)\s*:\s*([\w.\-]+\.py)", bloque)
        nombre = m.group(1) if m else ("main.py" if i == 0 else f"parte_{i}.py")
        archivos[nombre] = bloque
    if not archivos and texto and ("def " in texto or "import " in texto):
        archivos["main.py"] = texto
    return archivos


def _programar(tarea, contexto, carpeta, e, errores=""):
    pedido = (f"Tarea: {tarea}\nContexto (lo que ya averiguó el equipo):\n{contexto[:3500]}\n"
              + (f"\nEl probador encontró estos errores en tu versión anterior; corrígelos:\n{errores[:1500]}\n" if errores else "")
              + "\nEscribe el código en Python. Si son varios archivos, responde JSON {\"archivo.py\": \"contenido\"}. "
                "Si es uno, un bloque ```python. Incluye un bloque if __name__ == '__main__': que demuestre que funciona "
                "sin pedir nada por teclado. No borres archivos ni ejecutes comandos del sistema.")
    r = comun.pensar(pedido, sistema=_sistema("programador", e), codigo=True, max_tokens=1800, temperatura=0.2)
    archivos = _extraer_archivos(r)
    if archivos and nivel(e["equipo"]["programador"]) >= 1 and not errores:
        revisado = comun.pensar(
            "Revisa este código: busca errores, casos que fallan y cosas sin terminar. Devuélvelo corregido con el "
            "mismo formato (JSON por archivo o un bloque ```python).\n\n" +
            "\n\n".join(f"# archivo: {k}\n{v}" for k, v in archivos.items())[:7000],
            sistema=_sistema("programador", e), codigo=True, max_tokens=1800, temperatura=0.1)
        archivos = _extraer_archivos(revisado) or archivos
    destino = os.path.join(carpeta, "codigo")
    os.makedirs(destino, exist_ok=True)
    for nombre, contenido in archivos.items():
        with open(os.path.join(destino, nombre), "w", encoding="utf-8") as f:
            f.write(contenido)
    return archivos


def _probar(carpeta, e):
    """Revisa en cuarentena y corre aislado. Devuelve (ok, informe)."""
    from core.nucleo import cuarentena
    destino = os.path.join(carpeta, "codigo")
    if not os.path.isdir(destino) or not os.listdir(destino):
        return False, "No había código que probar."
    revision = cuarentena.escanear(destino, usar_defender=False)
    graves = [h for h in revision["hallazgos"] if h[0] >= 2 or "borra" in h[2]]
    if revision["veredicto"] != "limpio" or graves:
        return False, ("No lo corrí porque la cuarentena encontró algo que no me gusta: " +
                       "; ".join(h[2] for h in (graves or revision["hallazgos"])[:3]))
    principal = "main.py" if os.path.exists(os.path.join(destino, "main.py")) else \
        sorted(f for f in os.listdir(destino) if f.endswith(".py"))[0]
    try:
        r = subprocess.run([sys.executable, "-I", principal], cwd=destino, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL)
        salida = ((r.stdout or "") + (r.stderr or ""))[-2500:]
        ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        return False, "El código se quedó colgado más de 30 segundos."
    return ok, (("Funciona. Salida:\n" if ok else "Falla. Salida:\n") + salida.strip())


def _informe(objetivo, resultados, avisos, e):
    partes = "\n\n".join(f"## {r['quien']} — {r['tarea']}\n{r['resultado']}" for r in resultados)
    n = nivel(e["equipo"]["cronista"])
    extra = ["Incluye las fuentes.", "Incluye fuentes y próximos pasos.",
             "Incluye fuentes, decisiones tomadas y próximos pasos.",
             "Incluye fuentes, decisiones, próximos pasos y lecciones."][n]
    r = comun.pensar(
        f"Escribe el informe final (en Markdown, en español) de la misión «{objetivo}» para {comun.nombre_usuario()}. "
        f"Empieza con un resumen de 3 líneas. {extra}\n\n" + partes[:10000] +
        ("\n\nAdvertencias del estratega:\n" + "\n".join(avisos) if avisos else ""),
        sistema=_sistema("cronista", e), max_tokens=1200, temperatura=0.3)
    return r or ("# Misión: " + objetivo + "\n\n" + partes)


def ejecutar_mision(objetivo):
    """Corre una misión completa. Devuelve (id, ruta_del_informe)."""
    _cancelar.clear()
    id_m = _registrar_mision(objetivo)
    _mision_en_curso["id"] = id_m
    carpeta = _carpeta(id_m)
    e = _estado()
    try:
        pasos, avisos = planificar(objetivo, e)
        _actualizar_mision(id_m, pasos=pasos, avisos=avisos)
        comun.informe(f"Equipo — misión {id_m} en marcha: «{objetivo}». Plan: " +
                      " → ".join(f"{_quien(p['rol'], e)}" for p in pasos) +
                      (f"\n  ⚠ {avisos[0]}" if avisos else ""), origen="equipo")
        resultados = [None] * len(pasos)
        try:
            from core.nucleo import analista
            maximo = 2 + analista.version()
        except Exception:
            maximo = 3

        def _contexto(i):
            return "\n\n".join(f"[{resultados[d]['quien']}] {resultados[d]['resultado'][:2500]}"
                               for d in pasos[i]["depende"] if resultados[d])

        def _hacer(i):
            if _cancelar.is_set():
                return
            p = pasos[i]
            rol, tarea = p["rol"], p["tarea"]
            e_local = _estado()
            ctx = _contexto(i)
            fuentes = []
            ok = True
            if rol == "investigador":
                texto, fuentes = _investigar(tarea, ctx, e_local)
            elif rol == "programador":
                archivos = _programar(tarea, ctx, carpeta, e_local)
                ok = bool(archivos)
                texto = ("Escribí: " + ", ".join(archivos)) if archivos else "No logré escribir el código."
            elif rol == "probador":
                ok, texto = _probar(carpeta, e_local)
                prog = next((j for j in reversed(p["depende"]) if pasos[j]["rol"] == "programador"), None)
                intentos = [1, 1, 2, 3][nivel(e_local["equipo"]["programador"])]
                while not ok and prog is not None and intentos > 0 and not _cancelar.is_set():
                    intentos -= 1
                    _programar(pasos[prog]["tarea"], _contexto(prog), carpeta, _estado(), errores=texto)
                    ok, texto = _probar(carpeta, _estado())
            else:      # cronista
                texto = _informe(objetivo, [r for r in resultados if r], avisos, e_local)
            resultados[i] = {"quien": _quien(rol, e_local), "rol": rol, "tarea": tarea, "resultado": texto,
                             "ok": ok, "fuentes": fuentes}
            leccion = None
            if not ok:
                leccion = comun.pensar(f"En una frase: ¿qué debo hacer distinto la próxima vez? Falló: {texto[:600]}",
                                       max_tokens=60, temperatura=0.2) or None
            _ganar_xp(rol, 2 if ok else 0, leccion)

        hechos_idx = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=maximo) as pool:
            en_vuelo = {}
            while len(hechos_idx) < len(pasos) and not _cancelar.is_set():
                for i, p in enumerate(pasos):
                    if i in hechos_idx or i in en_vuelo.values():
                        continue
                    if all(d in hechos_idx for d in p["depende"]):
                        en_vuelo[pool.submit(_hacer, i)] = i
                if not en_vuelo:
                    break
                listos, _ = concurrent.futures.wait(list(en_vuelo), timeout=5,
                                                    return_when=concurrent.futures.FIRST_COMPLETED)
                for f in listos:
                    i = en_vuelo.pop(f)
                    try:
                        f.result()
                    except Exception as err:
                        resultados[i] = {"quien": _quien(pasos[i]["rol"]), "rol": pasos[i]["rol"],
                                         "tarea": pasos[i]["tarea"], "resultado": f"Error: {err}", "ok": False,
                                         "fuentes": []}
                    hechos_idx.add(i)
        if _cancelar.is_set():
            _actualizar_mision(id_m, estado="cancelada", fin=comun.ahora_txt())
            comun.informe(f"Equipo — misión {id_m} cancelada.", origen="equipo")
            return id_m, None
        informe = next((r["resultado"] for r in reversed(resultados) if r and r["rol"] == "cronista"), "")
        ruta = os.path.join(carpeta, "informe.md")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(informe)
        with open(os.path.join(carpeta, "detalle.json"), "w", encoding="utf-8") as f:
            json.dump({"objetivo": objetivo, "pasos": pasos, "resultados": resultados}, f, ensure_ascii=False, indent=2)
        bien = sum(1 for r in resultados if r and r["ok"])
        _actualizar_mision(id_m, estado="completada", fin=comun.ahora_txt(), informe=ruta,
                           resumen=informe.strip().split("\n")[0][:200])
        comun.informe(f"Equipo — misión {id_m} terminada ({bien}/{len(pasos)} tareas bien). "
                      f"Di «informe de la misión {id_m}» o «abre la misión {id_m}».",
                      importante=True, nivel="logro", origen="equipo")
        return id_m, ruta
    except Exception as err:
        _actualizar_mision(id_m, estado="falló", fin=comun.ahora_txt(), error=str(err)[:300])
        comun.informe(f"Equipo — la misión {id_m} falló: {err}", origen="equipo")
        return id_m, None
    finally:
        _mision_en_curso["id"] = None


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_MISION = re.compile(r"^(?:mision|equipo|mandale a tu equipo|manda a tu equipo a|que tu equipo)\s*:?\s+(.{8,})$")
_R_NOMBRA = re.compile(r"^(?:nombra|ponle(?: de nombre)?|bautiza)\s+(?:al?\s+)?(estratega|investigador|programador|probador|cronista)"
                       r"\s+(?:como\s+)?([a-z][\w\-]{1,30})$|"
                       r"^(?:ponle|ponle de nombre)\s+([a-z][\w\-]{1,30})\s+al\s+(estratega|investigador|programador|probador|cronista)$")
_R_INFORME = re.compile(r"^(?:informe|resultado)\s+de\s+la\s+mision\s+(\d+)$")
_R_ABRE = re.compile(r"^abre\s+la\s+mision\s+(\d+)$")


def _nombre_bonito(nombre_norm, original):
    m = re.search(re.escape(nombre_norm), comun.norm(original))
    if m:
        # recupera mayúsculas/tildes como las escribiste
        palabras = original.split()
        for p in palabras:
            if comun.norm(p) == nombre_norm:
                return p.strip(".,;:!¡¿?")
    return nombre_norm.capitalize()


def manejar(comando):
    texto = (comando or "").strip()
    c = comun.norm(texto)
    if c in ("tu equipo", "equipo", "tus miembros", "estado del equipo", "mi equipo"):
        e = _estado()
        lineas = []
        for rol, s in e["equipo"].items():
            nom = s.get("nombre") or "(sin nombre)"
            lineas.append(f"  • {rol}: {nom} — {rango_de(s)}, {s.get('xp', 0)} xp, {s.get('tareas', 0)} tareas. "
                          f"{_que_gana(rol, nivel(s))}")
        en_curso = _mision_en_curso["id"]
        comun.msg("Equipo de Arché:\n" + "\n".join(lineas) +
                  (f"\nAhora mismo: misión {en_curso} en curso." if en_curso else "") +
                  "\nSuben de nivel con experiencia. Di «misión: <lo que quieres>» para ponerlos a trabajar.")
        return True
    m = _R_NOMBRA.match(c)
    if m:
        rol = m.group(1) or m.group(4)
        nombre_n = m.group(2) or m.group(3)
        comun.msg(nombrar(rol, _nombre_bonito(nombre_n, texto)))
        return True
    if c in ("misiones", "tus misiones", "misiones del equipo"):
        e = _estado()
        if not e["misiones"]:
            comun.msg("El equipo no ha tenido misiones. Di «misión: <lo que quieres>».")
        else:
            comun.msg("Misiones:\n" + "\n".join(f"  {m['id']}. [{m['estado']}] {m['objetivo']}" for m in e["misiones"][-10:]))
        return True
    m = _R_INFORME.match(c)
    if m:
        ruta = os.path.join(_carpeta(int(m.group(1))), "informe.md")
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                comun.msg(f.read()[:6000])
        except OSError:
            comun.msg("Esa misión no tiene informe (¿sigue en curso o falló?).")
        return True
    m = _R_ABRE.match(c)
    if m:
        carpeta = _carpeta(int(m.group(1)))
        if comun.es_windows():
            os.startfile(carpeta)
            comun.msg("Abrí la carpeta de la misión.")
        else:
            comun.msg(f"La misión está en: {carpeta}")
        return True
    if c in ("cancela la mision", "para la mision", "deten la mision", "cancela la mision del equipo"):
        if _mision_en_curso["id"]:
            _cancelar.set()
            comun.msg("Le digo al equipo que pare. Terminan lo que tienen en la mano y se detienen.")
        else:
            comun.msg("No hay ninguna misión en curso.")
        return True
    m = _R_MISION.match(c)
    if m:
        if _mision_en_curso["id"]:
            comun.msg(f"El equipo ya está en la misión {_mision_en_curso['id']}. Espera a que termine o di «cancela la misión».")
            return True
        objetivo = texto.split(":", 1)[1].strip() if ":" in texto else m.group(1)
        comun.msg(f"Entendido. Reúno al equipo para: «{objetivo}». Sigue usándome normal; te aviso cuando terminen.")
        comun.en_hilo(ejecutar_mision, objetivo, nombre="arche-equipo")
        return True
    return False


def detener():
    _cancelar.set()
