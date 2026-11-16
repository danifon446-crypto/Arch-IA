"""
depredador.py
-------------
Ubicacion: Arche/core/nucleo/depredador.py

DEPREDADOR: cuando Arché no logra fabricarse una habilidad sola, sale a CAZARLA.

  1. Detecta qué le falta: las tareas que la fábrica (core/evolucion.py) no pudo resolver,
     o lo que le pidas con «caza <tema>».
  2. Busca presas en GitHub: repositorios de Python con licencia libre (MIT, Apache, BSD...),
     con estrellas, mantenidos y chicos.
  3. Los baja a CUARENTENA (core/nucleo/cuarentena.py): solo texto, nunca se ejecuta nada de ahí.
  4. Los ESCANEA como un antivirus (y con Windows Defender si está). Lo peligroso se bloquea
     para siempre y te avisa; lo sospechoso se suelta.
  5. DIGIERE: lee solo la parte que sirve y escribe una habilidad NUEVA para Arché con esa
     técnica (no copia el repo). Esa habilidad pasa por:
        - la revisión de la cuarentena (sin comandos del sistema, sin borrar, sin eval/exec),
        - el análisis del núcleo (pruebas de verdad, palabras clave razonables),
        - la caja de arena de la evolución (copia de Arché + autotest + su propia prueba).
  6. Si la habilidad necesita LEER ARCHIVOS o INTERNET, no se la queda sola: te pregunta.
        «absorbe presa 3» / «descarta presa 3»

Cuándo caza sola: 1 presa por día con el Núcleo 1.0 (2 con el 2.0, 3 con el 3.0), solo con
internet y cuando llevas un rato sin usar el PC. Se apaga con «depredador apagado».

Para más búsquedas por hora en GitHub puedes darle un token (sin permisos especiales):
    token de github ghp_xxxxx
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from core.nucleo import comun, cuarentena

ARCH = comun.ruta("depredador.json")
CARPETA_CUARENTENA = comun.ruta("cuarentena", ".")

LICENCIAS_LIBRES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "unlicense", "0bsd", "zlib",
                    "mpl-2.0", "python-2.0", "cc0-1.0", "wtfpl"}
MIN_ESTRELLAS = 15
MAX_TAMANO_KB = 3000
MAX_ANTIGUEDAD_DIAS = 4 * 365
MINUTOS_INACTIVO_PARA_CAZAR = 20
INTENTOS_POR_TEMA = 2

_lock_caza = threading.Lock()


# ------------------------------------------------------------------
# Estado
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("presas", [])
    e.setdefault("lista_negra", [])
    e.setdefault("cazas_por_dia", {})
    e.setdefault("intentos", {})
    return e


def _guardar(e):
    e["presas"] = e["presas"][-200:]
    e["cazas_por_dia"] = dict(sorted(e["cazas_por_dia"].items())[-14:])
    comun.guardar(ARCH, e)


def presas_absorbidas():
    return sum(1 for p in _estado()["presas"] if p.get("estado") == "absorbida")


def _cazas_hoy():
    return int(_estado()["cazas_por_dia"].get(comun.hoy(), 0))


def _maximo_por_dia():
    try:
        from core.nucleo import analista
        return analista.version()
    except Exception:
        return 1


_lock_estado = threading.Lock()


def _nueva_presa(**datos):
    with _lock_estado:
        e = _estado()
        datos.setdefault("id", (max((p.get("id", 0) for p in e["presas"]), default=0) + 1))
        datos.setdefault("cuando", comun.ahora_txt())
        e["presas"].append(datos)
        _guardar(e)
    return datos["id"]


def _actualizar_presa(id_presa, **cambios):
    e = _estado()
    for p in e["presas"]:
        if p.get("id") == id_presa:
            p.update(cambios)
    _guardar(e)


def _presa(id_presa):
    return next((p for p in _estado()["presas"] if p.get("id") == id_presa), None)


# ------------------------------------------------------------------
# Red (lo único que sale a internet)
# ------------------------------------------------------------------

def _get(url, binario=False, timeout=25, maximo=20_000_000):
    encabezados = {"User-Agent": "Arche-Depredador/1.0", "Accept": "application/vnd.github+json"}
    token = comun.config("github_token")
    if token and "api.github.com" in url:
        encabezados["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=encabezados)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        datos = r.read(maximo + 1)
    if len(datos) > maximo:
        raise ValueError("la descarga es demasiado grande")
    return datos if binario else json.loads(datos.decode("utf-8", errors="replace"))


def _hay_internet():
    try:
        from core import web
        return web.hay_internet()
    except Exception:
        return False


# ------------------------------------------------------------------
# 2. Buscar presas
# ------------------------------------------------------------------

def busquedas_para(tema):
    """Búsquedas cortas en inglés (GitHub está casi todo en inglés)."""
    r = comun.pensar(
        "Dame 2 búsquedas MUY cortas (2-4 palabras, en inglés) para encontrar en GitHub una librería o script "
        f"de Python que sirva para: «{tema}». Responde solo una lista JSON de textos.",
        max_tokens=80, temperatura=0.2)
    lista = comun.json_de(r)
    salida = [str(x).strip() for x in lista if str(x).strip()][:2] if isinstance(lista, list) else []
    base = " ".join(sorted(comun.palabras(tema), key=len, reverse=True)[:3])
    if base and base not in salida:
        salida.append(base)
    return salida[:3]


def es_buena_presa(repo, lista_negra=()):
    """(bool, motivo) según licencia, tamaño, estrellas y si está viva."""
    if repo.get("full_name") in lista_negra:
        return False, "está en mi lista negra"
    if repo.get("fork"):
        return False, "es una copia (fork)"
    lic = ((repo.get("license") or {}).get("spdx_id") or "").lower()
    if lic not in LICENCIAS_LIBRES:
        return False, f"licencia {lic or 'desconocida'}"
    if int(repo.get("size", 0)) > MAX_TAMANO_KB:
        return False, "demasiado grande"
    if int(repo.get("stargazers_count", 0)) < MIN_ESTRELLAS:
        return False, "pocas estrellas"
    try:
        empuje = datetime.strptime((repo.get("pushed_at") or "")[:10], "%Y-%m-%d")
        if datetime.now() - empuje > timedelta(days=MAX_ANTIGUEDAD_DIAS):
            return False, "abandonado"
    except ValueError:
        return False, "sin fecha"
    return True, "ok"


def buscar_presas(tema, lista_negra=()):
    vistos, buenas = set(), []
    for consulta in busquedas_para(tema):
        q = urllib.parse.quote(f"{consulta} language:python")
        try:
            datos = _get(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=10")
        except (urllib.error.URLError, ValueError, OSError):
            continue
        for repo in datos.get("items", []):
            nombre = repo.get("full_name")
            if nombre in vistos:
                continue
            vistos.add(nombre)
            ok, _ = es_buena_presa(repo, lista_negra)
            if ok:
                buenas.append(repo)
        time.sleep(2)            # sin token GitHub deja ~10 búsquedas por minuto
    buenas.sort(key=lambda r: -int(r.get("stargazers_count", 0)))
    return buenas[:4]


# ------------------------------------------------------------------
# 3-4. Cuarentena y escaneo
# ------------------------------------------------------------------

def _encerrar(repo):
    """Baja el repo a la cuarentena. Devuelve la carpeta o None."""
    rama = repo.get("default_branch") or "main"
    url = f"https://codeload.github.com/{repo['full_name']}/zip/refs/heads/{urllib.parse.quote(rama)}"
    datos = _get(url, binario=True, timeout=60)
    carpeta = os.path.join(CARPETA_CUARENTENA, re.sub(r"[^A-Za-z0-9_.-]", "_", repo["full_name"]))
    cuarentena.vaciar(carpeta)
    if cuarentena.descomprimir_seguro(datos, carpeta) == 0:
        cuarentena.vaciar(carpeta)
        return None
    return carpeta


# ------------------------------------------------------------------
# 5. Digerir
# ------------------------------------------------------------------

def _partes_utiles(carpeta, tema, consultas):
    claves = comun.palabras(tema) | comun.palabras(" ".join(consultas))
    candidatos, readme = [], ""
    for raiz, _, archivos in os.walk(carpeta):
        for nombre in archivos:
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, carpeta).replace("\\", "/")
            try:
                with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                    texto = f.read()
            except OSError:
                continue
            if nombre.lower().startswith("readme") and not readme:
                readme = texto[:1500]
            if not nombre.endswith(".py") or re.search(r"(?i)(^|/)(setup\.py|conftest\.py|__init__\.py)$", rel):
                continue
            t = comun.norm(rel + " " + texto[:20000])
            puntaje = sum(t.count(k) for k in claves) + (2 if "test" not in rel.lower() else 0)
            candidatos.append((puntaje, len(texto), rel, texto))
    candidatos.sort(key=lambda c: (-c[0], c[1]))
    trozos = [f"# ---- {rel} ----\n{texto[:4000]}" for _, _, rel, texto in candidatos[:3]]
    return readme, "\n\n".join(trozos)


_FORMATO = (
    "Formato OBLIGATORIO (un solo módulo Python):\n"
    "  def ejecutar(texto: str) -> str   # recibe la frase de la persona y devuelve la respuesta en español\n"
    "  def probar() -> None              # 4+ asserts que comprueban ejecutar() sin internet\n"
    "  PALABRAS = [...]                  # palabras clave específicas que activan la habilidad\n"
    "  DESCRIPCION = '...'\n"
    "Reglas: nada de subprocess, socket, eval, exec, borrar o escribir archivos. Si la tarea de verdad necesita "
    "LEER archivos escribe en la PRIMERA línea el comentario  # NECESITA: archivos ; si necesita pedir páginas "
    "de internet,  # NECESITA: red  (o ambas). Si no necesita nada de eso, no pongas esa línea."
)


def digerir(repo, carpeta, tema, consultas):
    """Escribe la habilidad nueva. Devuelve (codigo, permisos) o (None, motivo)."""
    readme, codigo_presa = _partes_utiles(carpeta, tema, consultas)
    if not codigo_presa:
        return None, "no tenía código útil"
    lic = ((repo.get("license") or {}).get("spdx_id") or "").upper()
    r = comun.pensar(
        f"Eres el Depredador de Arché, una asistente en Python. Te comiste el repositorio {repo['full_name']} "
        f"(licencia {lic}). Extrae SOLO la técnica que sirve para esta tarea: «{tema}», y escribe una habilidad "
        "NUEVA para Arché, autocontenida (no puede importar el paquete del repositorio porque no está instalado). "
        "Reescríbela con tus palabras; no copies bloques largos.\n\n" + _FORMATO +
        f"\n\nREADME:\n{readme}\n\nCÓDIGO DE LA PRESA:\n{codigo_presa}\n\nSolo el código.",
        temperatura=0.2, codigo=True, max_tokens=1600)
    codigo = re.sub(r"```(?:python)?", "", r or "").strip()
    if not codigo:
        return None, "el modelo no respondió"
    m = re.search(r"(?im)^\s*#\s*NECESITA\s*:\s*(.+)$", codigo[:400])
    permisos = tuple(sorted({p for p in ("archivos", "red") if m and p in comun.norm(m.group(1))}))
    cabecera = (f"# Absorbida por el Depredador de Arché desde {repo.get('html_url', '')} (licencia {lic}).\n"
                "# La técnica se reescribió para Arché; no es una copia del original.\n")
    return cabecera + codigo, permisos


def _registrar(nombre, tema, repo, permisos, item_id=None):
    from core import evolucion as evo
    from core.nucleo import analista
    with evo._lock:
        hab = evo._cargar(evo.ARCH_HABILIDADES, {})
        hab[nombre] = {"tarea": tema, "creada": comun.ahora_txt(), "usos": 0, "origen": "depredador",
                       "fuente": repo.get("html_url", ""), "permisos": list(permisos)}
        evo._guardar(evo.ARCH_HABILIDADES, hab)
    analista.registrar_origen(nombre, "depredador", tarea=tema, fuente=repo.get("html_url", ""))
    if item_id:
        try:
            evo._marcar_no_se(item_id, "habilidad_creada")
        except Exception:
            pass


def _aplicar(nombre, codigo, tema):
    from core import evolucion as evo
    rel = f"core/habilidades_auto/{nombre}.py"
    cambios = {rel: codigo}
    if not os.path.exists(os.path.join(evo.CARPETA_HABILIDADES, "__init__.py")):
        cambios["core/habilidades_auto/__init__.py"] = '"""Habilidades que Arché se fabricó sola."""\n'
    prueba = (f"import sys; sys.path.insert(0, '.')\nfrom core.habilidades_auto import {nombre} as h\n"
              "h.probar()\nprint('ok')\n")
    return evo.aplicar_cambio_autonomo(cambios, f"presa del Depredador: {tema}", prueba_extra=prueba)


# ------------------------------------------------------------------
# La caza completa
# ------------------------------------------------------------------

def cazar(tema, item_id=None, manual=False, avisar=print):
    """Devuelve (ok, explicación). avisar(texto) recibe el progreso."""
    if not _lock_caza.acquire(blocking=False):
        return False, "ya estoy cazando otra cosa"
    try:
        e = _estado()
        if not manual and _cazas_hoy() >= _maximo_por_dia():
            return False, "ya cacé lo de hoy"
        if not _hay_internet():
            return False, "no tengo internet"
        clave = comun.norm(tema)
        e["intentos"][clave] = int(e["intentos"].get(clave, 0)) + 1
        e["cazas_por_dia"][comun.hoy()] = _cazas_hoy() + 1
        _guardar(e)

        consultas = busquedas_para(tema)
        repos = buscar_presas(tema, e["lista_negra"])
        if not repos:
            return False, "no encontré presas con licencia libre y en buen estado"
        from core import evolucion as evo
        from core.nucleo import analista
        motivos = []
        for repo in repos[:3]:
            avisar(f"Presa a la vista: {repo['full_name']} ({repo.get('stargazers_count', 0)}★). La encierro en la cuarentena...")
            try:
                carpeta = _encerrar(repo)
            except (urllib.error.URLError, ValueError, OSError) as err:
                motivos.append(f"{repo['full_name']}: no se pudo bajar ({err})")
                continue
            if not carpeta:
                motivos.append(f"{repo['full_name']}: no tenía código")
                continue
            try:
                revision = cuarentena.escanear(carpeta)
                if revision["veredicto"] == "peligroso":
                    e = _estado()
                    e["lista_negra"].append(repo["full_name"])
                    _guardar(e)
                    razones = "; ".join(h[2] for h in revision["hallazgos"][:3])
                    _nueva_presa(tema=tema, repo=repo["full_name"], url=repo.get("html_url"), estado="peligrosa",
                                 motivo=razones)
                    comun.informe(f"El Depredador encontró código PELIGROSO en {repo['full_name']} ({razones}). "
                                  "No se ejecutó nada, lo borré y quedó en mi lista negra.",
                                  importante=True, nivel="alerta", origen="depredador")
                    continue
                if revision["veredicto"] == "sospechoso":
                    motivos.append(f"{repo['full_name']}: sospechoso ({revision['hallazgos'][0][2]})")
                    _nueva_presa(tema=tema, repo=repo["full_name"], url=repo.get("html_url"), estado="soltada",
                                 motivo="sospechosa")
                    continue
                avisar("Escaneo limpio. Digiriendo...")
                codigo, permisos = digerir(repo, carpeta, tema, consultas)
            finally:
                cuarentena.vaciar(carpeta)
            if not codigo:
                motivos.append(f"{repo['full_name']}: {permisos}")
                continue
            ok, por_que = cuarentena.revisar_habilidad(codigo, permisos)
            if ok:
                ok, por_que, _ = analista.analizar_habilidad(codigo)
            if not ok:
                motivos.append(f"{repo['full_name']}: {por_que}")
                continue
            nombre = ("presa_" + evo._slug(tema))[:46]
            lic = ((repo.get("license") or {}).get("spdx_id") or "")
            if permisos:
                id_p = _nueva_presa(tema=tema, repo=repo["full_name"], url=repo.get("html_url"), licencia=lic,
                                    estado="pendiente_permiso", permisos=list(permisos), nombre=nombre,
                                    codigo=codigo, item_no_se=item_id)
                comun.informe(
                    f"Cacé «{tema}» de {repo['full_name']} (licencia {lic}). Para funcionar necesita "
                    f"{' e '.join('leer archivos' if p == 'archivos' else 'internet' for p in permisos)}. "
                    f"No me la quedo sin tu permiso: di «absorbe presa {id_p}» o «descarta presa {id_p}».",
                    importante=True, origen="depredador")
                return True, f"presa {id_p} esperando tu permiso"
            aplicado, que = _aplicar(nombre, codigo, tema)
            if not aplicado:
                motivos.append(f"{repo['full_name']}: {que}")
                continue
            _registrar(nombre, tema, repo, permisos, item_id)
            _nueva_presa(tema=tema, repo=repo["full_name"], url=repo.get("html_url"), licencia=lic,
                         estado="absorbida", nombre=nombre)
            comun.informe(f"Depredador: absorbí «{tema}» a partir de {repo['full_name']} ({lic}). "
                          "Ya es una habilidad mía (nivel Aprendiz).", importante=True, nivel="logro",
                          origen="depredador")
            return True, "absorbida"
        return False, "ninguna presa sirvió: " + " | ".join(motivos[:3])
    finally:
        _lock_caza.release()


def absorber_pendiente(id_presa):
    p = _presa(id_presa)
    if not p or p.get("estado") != "pendiente_permiso":
        return False, "no tengo esa presa esperando permiso"
    ok, por_que = cuarentena.revisar_habilidad(p["codigo"], tuple(p.get("permisos", ())))
    if not ok:
        return False, por_que
    aplicado, que = _aplicar(p["nombre"], p["codigo"], p["tema"])
    if not aplicado:
        return False, que
    _registrar(p["nombre"], p["tema"], {"html_url": p.get("url", "")}, p.get("permisos", ()), p.get("item_no_se"))
    _actualizar_presa(id_presa, estado="absorbida", codigo="")
    return True, "absorbida"


# ------------------------------------------------------------------
# Caza automática (la llama el reloj del núcleo)
# ------------------------------------------------------------------

def objetivo_siguiente():
    """La tarea que la fábrica no pudo resolver y que todavía no se ha intentado cazar demasiado."""
    try:
        from core import evolucion as evo
        lista = evo._cargar(evo.ARCH_NO_SE, [])
    except Exception:
        return None
    intentos = _estado()["intentos"]
    candidatos = [i for i in lista if i.get("tipo") == "tarea"
                  and (i.get("estado") in ("habilidad_fallida", "habilidad_insegura")
                       or (i.get("estado") == "pendiente" and int(i.get("veces", 0)) >= 3))
                  and int(intentos.get(comun.norm(i.get("tema", "")), 0)) < INTENTOS_POR_TEMA]
    candidatos.sort(key=lambda i: -int(i.get("veces", 0)))
    return candidatos[0] if candidatos else None


def revisar():
    e = _estado()
    if not e["activo"] or _cazas_hoy() >= _maximo_por_dia() or _lock_caza.locked():
        return
    try:
        from core.nucleo import ritmo
        if ritmo.minutos_inactivo() < MINUTOS_INACTIVO_PARA_CAZAR:
            return
    except Exception:
        return
    item = objetivo_siguiente()
    if not item:
        return
    comun.en_hilo(lambda: cazar(item["tema"], item_id=item.get("id"), avisar=lambda t: None),
                  nombre="arche-depredador")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_CAZA = re.compile(r"^(?:caza|cazar|depredador|devora|absorbe(?!\s+presa))\s*:?\s+(.+)$|"
                     r"^busca\s+en\s+github\s+(?:como|algo\s+para|una\s+forma\s+de)\s+(.+)$")
_R_ABSORBE = re.compile(r"^absorbe\s+(?:la\s+)?presa\s+(\d+)$")
_R_DESCARTA = re.compile(r"^(?:descarta|suelta|bota)\s+(?:la\s+)?presa\s+(\d+)$")
_R_TOKEN = re.compile(r"^token\s+de\s+github\s+(\S+)$", re.I)


def manejar(comando):
    texto = (comando or "").strip()
    c = comun.norm(texto)
    m = _R_TOKEN.match(texto)
    if m:
        comun.fijar_config("github_token", m.group(1))
        comun.msg("Guardé el token de GitHub. Ahora puedo buscar más presas por hora.")
        return True
    if c in ("depredador apagado", "apaga el depredador", "no caces", "deja de cazar"):
        e = _estado(); e["activo"] = False; _guardar(e)
        comun.msg("Listo, no cazo sola. Solo cuando me digas «caza <tema>».")
        return True
    if c in ("depredador encendido", "activa el depredador", "caza sola"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg(f"Listo, cazo sola hasta {_maximo_por_dia()} presa(s) por día cuando no estés usando el PC.")
        return True
    if c in ("presas", "tus presas", "tu estomago", "estomago", "que has cazado", "estado del depredador"):
        e = _estado()
        if not e["presas"]:
            comun.msg("Todavía no he cazado nada. Di «caza <lo que quieres que aprenda>».")
            return True
        lineas = [f"  {p['id']}. [{p.get('estado')}] {p.get('tema')} ← {p.get('repo')}" for p in e["presas"][-12:]]
        comun.msg(f"Depredador {'activo' if e['activo'] else 'apagado'} — cacé {_cazas_hoy()} hoy.\n" + "\n".join(lineas))
        return True
    m = _R_ABSORBE.match(c)
    if m:
        ok, por_que = absorber_pendiente(int(m.group(1)))
        comun.msg("Absorbida. Ya es una habilidad mía." if ok else f"No la pude absorber: {por_que}.")
        return True
    m = _R_DESCARTA.match(c)
    if m:
        _actualizar_presa(int(m.group(1)), estado="descartada", codigo="")
        comun.msg("Presa descartada.")
        return True
    m = _R_CAZA.match(c)
    if m:
        tema = (m.group(1) or m.group(2) or "").strip()
        if len(tema) < 4:
            return False
        comun.msg(f"Salgo a cazar «{tema}» en GitHub. Todo pasa por cuarentena antes de tocarme; te aviso.")

        def _caza():
            ok, por_que = cazar(tema, manual=True, avisar=lambda t: comun.msg(t))
            if not ok:
                comun.msg(f"Depredador: no pude absorber «{tema}» — {por_que}.")
        comun.en_hilo(_caza, nombre="arche-depredador")
        return True
    return False
