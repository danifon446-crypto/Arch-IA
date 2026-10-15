"""
mejora_continua.py
------------------
Ubicacion: Arche/core/mejora_continua.py

El "piloto automatico de mejora": cuando no estas usando a Arche, se ocupa sola de
mejorar. Junta en un solo ciclo cosas que antes habia que pedir una por una:

  1. datos      : importa los ejemplos que escribiste a mano (ejemplos_manuales.txt) y siembra
                  el catalogo cuando hay intenciones nuevas.
  2. fallos     : lee lo que no entendio o contesto como charla siendo una orden, se lo pregunta
                  a la nube y aprende de la respuesta (frases nuevas para las redes).
  3. limpieza   : quita del cache las respuestas inutiles y limpia lo contaminado.
  4. pruebas    : se pasa el autotest y anota si algo se rompio.
  5. estudio    : si hay nube conectada, estudia sus temas (nunca recarga a Ollama sola).
  6. codigo     : (solo nivel "completa") busca duplicados, imports sin usar, codigo muerto;
                  NO modifica nada: te deja el informe y tu decides con 'revisate'.

  7. redes      : (nivel "total") rinde examenes y entrena rapido las redes de intenciones.
  8. propuestas : (nivel "total") revisa de a poco su codigo y arma parches para lo que encuentra.
  9. autocodigo : (nivel "total") APLICA ella sola los cambios seguros: imports sin usar y parches de
                  riesgo bajo. Cada cambio pasa por el mismo camino de siempre (sintaxis, entorno
                  aislado, respaldo, log) y despues se corre el autotest completo: si aparece una
                  falla nueva, DESHACE todo el lote sola. Maximo 3 por ciclo y 6 por dia; nunca toca
                  main.py, este archivo ni los archivos protegidos. Se puede deshacer con
                  'deshaz el ultimo cambio'.

Niveles: apagada | datos (por defecto: 1 a 5) | completa (1 a 6, solo informa) | total (1 a 5 y 7 a 9).
Reglas de seguridad: nunca toca tu PC, solo en nivel total cambia codigo (y solo asi), solo trabaja cuando llevas
unos minutos sin hablarle, se frena apenas vuelves a escribir, y cada tarea tiene su propio
descanso (no repite lo mismo a cada rato). Todo queda anotado: 'que has mejorado'.

Lo que toca el sistema esta en funciones "_" para poder probarlo sin Windows ni internet.
"""

import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime

from core.rutas import DATABASE

ARCHIVO = os.path.join(DATABASE, "mejora_continua.json")
NIVELES = ("apagada", "datos", "completa", "total")
INACTIVIDAD = 5 * 60            # segundos sin hablarle para considerar que no estas
REVISION = 10 * 60              # cada cuanto mira si toca algo
ARRANQUE = 3 * 60               # espera tras abrir Arche antes del primer ciclo
HORA = 3600
DESCANSO = {"datos": 2 * HORA, "fallos": 3 * HORA, "limpieza": 24 * HORA, "pruebas": 24 * HORA,
            "estudio": 48 * HORA, "codigo": 7 * 24 * HORA, "redes": 6 * HORA, "propuestas": 48 * HORA,
            "autocodigo": 12 * HORA}
MAX_CAMBIOS_CICLO = 3
MAX_CAMBIOS_DIA = 6
RIESGO_MAXIMO = 20              # solo parches de riesgo "bajo" (ver gran_sabio.evaluar_riesgo)
SOLO_ESTOS_ARCHIVOS_NUNCA = {"main.py", "core/mejora_continua.py", "core/IA/autotest.py"}
CARPETA_RESPALDOS = os.path.join(DATABASE, "mejora_respaldos")
MAX_FALLOS_POR_CICLO = 6
HISTORIAL_MAX = 40

_lock = threading.Lock()
_ultimo_latido = time.time()
_hilo = None
_detener = threading.Event()
_trabajando = False

_RE_ORDEN = re.compile(r"^(sube|baja|pon|ponme|abre|cierra|activa|desactiva|enciende|apaga|reproduce|silencia|busca|"
                       r"muestrame|mueve|minimiza|maximiza|captura|bloquea|toma)\b")


def _msg(texto):
    print(f"Arché: {texto}")


def _sin_tildes(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[¿?¡!,.;:]", " ", t).split())


def _ahora():
    return time.time()


# ------------------------------------------------------------------
# Estado
# ------------------------------------------------------------------

def _cargar():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(datos):
    try:
        os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
        with open(ARCHIVO, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def nivel():
    n = _cargar().get("nivel")
    return n if n in NIVELES else "datos"


def fijar_nivel(nuevo):
    if nuevo not in NIVELES:
        raise ValueError(nuevo)
    with _lock:
        d = _cargar()
        d["nivel"] = nuevo
        _guardar(d)


def latido():
    """Main lo llama con cada cosa que escribes: mientras hablas, Arche no se pone a trabajar."""
    global _ultimo_latido
    _ultimo_latido = time.time()


def _anotar(tarea, texto, ahora=None):
    """Guarda el resultado de una tarea (y su hora, para el descanso) y lo deja como 'no visto'."""
    with _lock:
        d = _cargar()
        d.setdefault("ultima", {})[tarea] = ahora if ahora is not None else _ahora()
        hist = d.setdefault("historial", [])
        hist.append({"t": ahora if ahora is not None else _ahora(), "tarea": tarea, "texto": texto, "visto": False})
        d["historial"] = hist[-HISTORIAL_MAX:]
        _guardar(d)


def _tocar(tarea, ahora=None):
    """Marca que la tarea se intento (para respetar el descanso) sin anotar nada en el historial."""
    with _lock:
        d = _cargar()
        d.setdefault("ultima", {})[tarea] = ahora if ahora is not None else _ahora()
        _guardar(d)


def toca(tarea, ahora=None):
    ahora = ahora if ahora is not None else _ahora()
    ult = (_cargar().get("ultima") or {}).get(tarea, 0)
    return ahora - ult >= DESCANSO[tarea]


# ------------------------------------------------------------------
# Piezas que tocan el sistema (se simulan en las pruebas)
# ------------------------------------------------------------------

def _ejemplos_pendientes():
    from core.IA import ensenar
    return len(ensenar.lineas_pendientes())


def _importar_ejemplos():
    from core.IA import ensenar
    r = ensenar.importar_ejemplos(silencioso=True) or {}
    return int(r.get("agregados", 0)), len(r.get("rechazados", []))


def _sembrar():
    from core.IA import entrenador_masivo
    return int(entrenador_masivo.sembrar_catalogo(silencioso=True) or 0)


def _tamano_catalogo():
    from core.IA import catalogo
    return len(catalogo.ENTRADAS)


def _comandos_fallidos(desde):
    """Frases que Arche no entendio (desconocido) o contesto como charla siendo una orden, desde `desde`."""
    from core.IA import telemetria
    vistas, salida = set(), []
    for e in telemetria._cargar_eventos():
        if e.get("tipo") != "comando" or e.get("timestamp", 0) <= desde:
            continue
        frase = (e.get("comando") or "").strip()
        clave = _sin_tildes(frase)
        if not frase or clave in vistas or len(clave) < 6:
            continue
        if e.get("intencion") == "desconocido" or (e.get("intencion") == "conversar" and _RE_ORDEN.match(clave)):
            vistas.add(clave)
            salida.append(frase)
    return salida


def _nube_lista():
    from core.IA import aprender_de_nube
    return aprender_de_nube._listo_para_nube()


def _preguntar_a_la_nube(frase):
    from core.IA import aprender_de_nube
    return aprender_de_nube.resolver(frase)


def _purgar_cache():
    from core.IA import respuestas
    return respuestas.purgar_inutiles()


def _limpiar_conocimiento():
    from core.IA import limpieza_auto
    r = limpieza_auto.limpiar_automatico(simular=False) or {}
    return int(r.get("borrados", 0))


def _correr_autotest():
    """(pasaron, fallaron, texto): corre las pruebas internas en OTRO proceso, para no tocar
    lo que Arche imprime ni su estado mientras tanto."""
    import subprocess
    import sys
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-m", "core.IA.autotest"], cwd=raiz, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    texto = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"(\d+)/(\d+) pruebas pasaron", texto)
    if m:
        return int(m.group(1)), int(m.group(2)) - int(m.group(1)), texto
    m = re.search(r"(\d+)/(\d+) pasaron", texto)
    if m:
        return int(m.group(1)), int(m.group(2)) - int(m.group(1)), texto
    return 0, 1, texto or "no pude correr las pruebas"


def _estudiar():
    from core.IA import estudio
    estudio.estudiar_todo(_detener)


def _revisar_codigo():
    from core.IA import autorevision
    r = autorevision.ejecutar_capa_1() or {}
    return {k: len(v) for k, v in r.items()}



def _estado_pruebas():
    """Conjunto de pruebas que fallan ahora (nombres), o None si no se pudieron correr."""
    ok, mal, texto = _correr_autotest()
    if not ok and not mal:
        return None
    fallan = set(re.findall(r"MAL\s+(\S+)", texto))
    if mal and not fallan:
        fallan = {f"?{i}" for i in range(mal)}
    return fallan


def _rendir_examen():
    from core.IA import examen
    r = examen.rendir_examen(silencioso=True) or {}
    return r.get("dominio"), int(r.get("aciertos", 0)), int(r.get("total", 0))


def _entrenar_rapido():
    """Entrenamiento rapido de las redes; con la nube conectada, ella genera los ejemplos (mejores y sin cargar a Ollama)."""
    from core.IA import entrenador_masivo
    entrenador_masivo.PERMITIR_NUBE = bool(_nube_lista())
    try:
        r = entrenador_masivo.entrenar_rapido(por_intencion=3, detener_evento=_detener, silencioso=True) or {}
    finally:
        entrenador_masivo.PERMITIR_NUBE = False
    return int(r.get("aceptadas", 0))


def _generar_parches():
    """Revisa de a poco el codigo (solo lo nuevo o modificado) y deja armados los parches."""
    from core.IA import autorevision
    r = autorevision.autorevisar(usar_ollama=True, limite_nuevas=8, generar_propuestas=True) or {}
    return len((r.get("revision_ia") or {}).get("propuestas_generadas", []))


def _raiz_app():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _protegidos():
    from core.IA.proponer_cambio_codigo import ARCHIVOS_PROTEGIDOS
    return set(ARCHIVOS_PROTEGIDOS) | SOLO_ESTOS_ARCHIVOS_NUNCA


def _leer_archivo(rel):
    with open(os.path.join(_raiz_app(), rel), "r", encoding="utf-8") as f:
        return f.read()


def _escribir_archivo(rel, texto):
    with open(os.path.join(_raiz_app(), rel), "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _imports_sin_usar():
    from core.IA import autorevision
    return autorevision.buscar_imports_sin_usar()


def _archivos_py():
    from core.IA import autorevision
    return [rel for _, rel in autorevision._archivos_del_proyecto()]


def _crear_propuesta(archivo, buscar, reemplazar, que):
    from core.IA.proponer_cambio_codigo import proponer_cambio_manual
    return proponer_cambio_manual(archivo, buscar, reemplazar, que=que, origen="mejora_automatica")


def _aplicar(propuesta):
    from core.IA.revisar_cambios_codigo import aplicar_propuesta
    return bool(aplicar_propuesta(propuesta))


def _marcar_propuesta(id_propuesta, estado):
    from core.IA import proponer_cambio_codigo as pc
    props = pc._cargar_pendientes()
    for p in props:
        if p.get("id") == id_propuesta:
            p["estado"] = estado
    pc._guardar_pendientes(props)


def _pendientes_de_bajo_riesgo():
    from core.IA import gran_sabio
    from core.IA import proponer_cambio_codigo as pc
    salida = []
    for p in pc._cargar_pendientes():
        if p.get("estado") != "pendiente" or p.get("tipo") == "archivo_nuevo":
            continue
        puntaje, _ = gran_sabio.evaluar_riesgo(p)
        if puntaje < RIESGO_MAXIMO:
            salida.append(p)
    return salida


def _linea_del_import(contenido, nombre):
    """La linea de import de TOP LEVEL que trae solo `nombre`, o None si no es seguro quitarla."""
    candidatas = []
    for linea in contenido.splitlines(True):
        t = linea.rstrip("\r\n")
        m1 = re.match(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?$", t)
        m2 = re.match(r"^from\s+[\w.]+\s+import\s+(\w+)(?:\s+as\s+(\w+))?$", t)
        if m1:
            enlazado = m1.group(2) or m1.group(1).split(".")[0]
        elif m2:
            enlazado = m2.group(2) or m2.group(1)
        else:
            continue
        if enlazado == nombre and "noqa" not in t:
            candidatas.append(linea)
    if len(candidatas) != 1 or contenido.count(candidatas[0]) != 1:
        return None
    if len(re.findall(r"\b" + re.escape(nombre) + r"\b", contenido)) != 1:
        return None          # aparece en otro lado (un texto, __all__, un comentario): no se toca
    return candidatas[0]


def _lo_importan_de_afuera(rel, nombre, archivos):
    modulo = os.path.splitext(os.path.basename(rel))[0]
    patron = re.compile(r"from\s+[\w.]*\b" + re.escape(modulo) + r"\b\s+import\s+[^\n]*\b" + re.escape(nombre) + r"\b")
    for otro in archivos:
        if otro == rel:
            continue
        try:
            if patron.search(_leer_archivo(otro)):
                return True
        except OSError:
            continue
    return False


def parches_mecanicos(maximo):
    """[(archivo, buscar, reemplazar, que)] de imports sin usar que se pueden quitar sin riesgo."""
    protegidos = _protegidos()
    archivos = _archivos_py()
    salida = []
    for h in _imports_sin_usar():
        rel, nombre = h["archivo"].replace("\\", "/"), h["import"]
        if rel in protegidos or rel.endswith("__init__.py") or os.path.basename(rel).startswith("prueba"):
            continue
        try:
            contenido = _leer_archivo(rel)
        except OSError:
            continue
        linea = _linea_del_import(contenido, nombre)
        if linea is None or _lo_importan_de_afuera(rel, nombre, archivos):
            continue
        salida.append((rel, linea, "", f"Quitar el import sin usar '{nombre}' de {rel}"))
        if len(salida) >= maximo:
            return salida
    return salida + _parches_except(maximo - len(salida))


def _parches_except(maximo):
    """'except:' desnudo -> 'except Exception:' (para no tragarse Ctrl+C ni salidas del programa)."""
    from core.IA import autorevision
    protegidos = _protegidos()
    salida = []
    for h in autorevision.buscar_except_desnudos():
        rel, n = h["archivo"].replace("\\", "/"), h["linea"]
        if rel in protegidos or rel.endswith("__init__.py") or os.path.basename(rel).startswith("prueba"):
            continue
        try:
            texto = _leer_archivo(rel)
        except OSError:
            continue
        lineas = texto.split("\n")
        if n - 1 >= len(lineas) or not re.match(r"^\s*except\s*:\s*(#.*)?$", lineas[n - 1]):
            continue
        for radio in range(0, 4):            # contexto minimo que haga unico el fragmento
            buscar = "\n".join(lineas[max(0, n - 1 - radio):min(len(lineas), n + radio)])
            if texto.count(buscar) == 1:
                salida.append((rel, buscar, buscar.replace("except:", "except Exception:", 1),
                               f"Cambiar un 'except:' desnudo por 'except Exception:' en {rel} (línea {n})"))
                break
        if len(salida) >= maximo:
            break
    return salida


def _guardar_respaldo(rel, texto):
    os.makedirs(CARPETA_RESPALDOS, exist_ok=True)
    ruta = os.path.join(CARPETA_RESPALDOS, f"{int(time.time() * 1000)}_{rel.replace('/', '__')}.bak")
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)
    return ruta


def _cambios_hoy(ahora=None):
    hoy = datetime.fromtimestamp(ahora if ahora is not None else _ahora()).strftime("%Y-%m-%d")
    d = _cargar().get("cambios_dia") or {}
    return d.get("n", 0) if d.get("dia") == hoy else 0


def _sumar_cambios_hoy(n, ahora=None):
    hoy = datetime.fromtimestamp(ahora if ahora is not None else _ahora()).strftime("%Y-%m-%d")
    with _lock:
        d = _cargar()
        previo = d.get("cambios_dia") or {}
        base = previo.get("n", 0) if previo.get("dia") == hoy else 0
        d["cambios_dia"] = {"dia": hoy, "n": base + n}
        _guardar(d)


def aplicar_lote_seguro(candidatas):
    """
    Aplica los parches (ya armados: lista de dicts propuesta o tuplas) con TODAS las barandas:
    respaldo propio, camino normal de aplicacion, autotest antes y despues, y deshace el lote si
    aparece una falla nueva. Devuelve (aplicadas, deshechas) como listas de descripciones.
    """
    antes = _estado_pruebas()
    if antes is None:
        return [], []                      # sin poder probarme no toco nada
    aplicadas, respaldos = [], []          # respaldos: (rel, texto_original, ruta_bak)
    for c in candidatas:
        if isinstance(c, dict):
            prop = c
        else:
            prop, error = _crear_propuesta(*c)
            if prop is None:
                continue
        rel = prop["archivo"]
        if rel in _protegidos():
            continue
        try:
            original = _leer_archivo(rel)
        except OSError:
            continue
        ruta_bak = _guardar_respaldo(rel, original)
        if _aplicar(prop):
            _marcar_propuesta(prop["id"], "aplicada")
            respaldos.append((rel, original, ruta_bak))
            aplicadas.append(prop.get("que") or prop["id"])
        else:
            _marcar_propuesta(prop["id"], "fallida")
    if not aplicadas:
        return [], []
    despues = _estado_pruebas()
    if despues is None or (despues - antes):
        for rel, original, _ in reversed(respaldos):
            _escribir_archivo(rel, original)
        nuevas = sorted((despues or set()) - antes)[:3]
        return [], [f"{q}" for q in aplicadas] if not nuevas else [f"{q} (rompía {', '.join(nuevas)})" for q in aplicadas]
    with _lock:
        d = _cargar()
        d.setdefault("lotes", []).append({"t": _ahora(), "cambios": aplicadas,
                                          "respaldos": [{"archivo": r, "bak": b} for r, _, b in respaldos]})
        d["lotes"] = d["lotes"][-20:]
        _guardar(d)
    _sumar_cambios_hoy(len(aplicadas))
    return aplicadas, []


def deshacer_ultimo_lote():
    """Restaura los archivos del ultimo lote que aplico la mejora automatica. Devuelve la lista de cambios."""
    with _lock:
        d = _cargar()
        lotes = d.get("lotes") or []
        if not lotes:
            return []
        lote = lotes.pop()
        d["lotes"] = lotes
        _guardar(d)
    for r in reversed(lote.get("respaldos", [])):
        try:
            with open(r["bak"], "r", encoding="utf-8", newline="") as f:
                _escribir_archivo(r["archivo"], f.read())
        except OSError:
            pass
    return lote.get("cambios", [])


# ------------------------------------------------------------------
# Tareas (cada una devuelve el texto para el historial, o None si no hubo nada)
# ------------------------------------------------------------------

def tarea_datos():
    partes = []
    if _ejemplos_pendientes():
        agregados, malos = _importar_ejemplos()
        if agregados:
            partes.append(f"importé {agregados} ejemplo(s) tuyos" + (f" ({malos} con error)" if malos else ""))
    d = _cargar()
    n = _tamano_catalogo()
    if d.get("catalogo_sembrado") != n:
        s = _sembrar()
        with _lock:
            d = _cargar()
            d["catalogo_sembrado"] = n
            _guardar(d)
        if s:
            partes.append(f"sembré {s} ejemplo(s) base de las intenciones nuevas")
    return " y ".join(partes) or None


def tarea_fallos():
    if not _nube_lista():
        return None
    d = _cargar()
    desde = d.get("fallos_hasta", 0)
    candidatas = _comandos_fallidos(desde)[:MAX_FALLOS_POR_CICLO]
    if not candidatas:
        return None
    aprendidas = []
    for frase in candidatas:
        if _detener.is_set() or not _nube_lista():
            break
        try:
            r = _preguntar_a_la_nube(frase)
        except Exception:
            r = None
        if r and r[0] not in ("desconocido", "conversar"):
            aprendidas.append(f"«{frase}» → {r[0]}")
    with _lock:
        d = _cargar()
        d["fallos_hasta"] = _ahora()
        _guardar(d)
    if aprendidas:
        return "aprendí de frases que no había entendido: " + "; ".join(aprendidas)
    return None


def tarea_limpieza():
    partes = []
    n = _purgar_cache()
    if n:
        partes.append(f"quité {n} respuesta(s) inútil(es) de mi caché")
    b = _limpiar_conocimiento()
    if b:
        partes.append(f"limpié {b} aprendizaje(s) contaminado(s)")
    return " y ".join(partes) or None


def tarea_pruebas():
    ok, mal, texto = _correr_autotest()
    if mal:
        falla = [l.strip() for l in texto.splitlines() if l.strip().startswith("MAL")][:3]
        return f"me probé y fallaron {mal} prueba(s) ({'; '.join(falla)}). Dime 'autotest' para verlas."
    return None   # todo bien: no hace falta molestar


def tarea_estudio():
    if not _nube_lista():
        return None
    _estudiar()
    return "estudié mis temas con la nube"


def tarea_codigo():
    r = _revisar_codigo()
    total = sum(r.values())
    if not total:
        return None
    detalle = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in r.items() if n)
    return f"revisé mi código y encontré {total} cosa(s) por mirar ({detalle}). No toqué nada: dime 'revisate' cuando quieras arreglarlas."


def tarea_redes():
    partes = []
    for _ in range(2):
        if _detener.is_set():
            break
        dominio, aciertos, total = _rendir_examen()
        if total:
            partes.append(f"examen de '{dominio}': {aciertos}/{total}")
    d = _cargar()
    if _ahora() - d.get("ultimo_rapido", 0) >= 48 * HORA and not _detener.is_set():
        n = _entrenar_rapido()
        with _lock:
            d = _cargar()
            d["ultimo_rapido"] = _ahora()
            _guardar(d)
        if n:
            partes.append(f"entrené {n} ejemplo(s) nuevos")
    return ("practiqué con mis redes (" + "; ".join(partes) + ")") if partes else None


def tarea_propuestas():
    n = _generar_parches()
    return f"revisé una parte de mi código y dejé armados {n} parche(s)" if n else None


def tarea_autocodigo():
    if _cambios_hoy() >= MAX_CAMBIOS_DIA:
        return None
    cupo = min(MAX_CAMBIOS_CICLO, MAX_CAMBIOS_DIA - _cambios_hoy())
    candidatas = list(_pendientes_de_bajo_riesgo())[:cupo]
    if len(candidatas) < cupo:
        candidatas += parches_mecanicos(cupo - len(candidatas))
    if not candidatas:
        return None
    aplicadas, deshechas = aplicar_lote_seguro(candidatas)
    partes = []
    if aplicadas:
        partes.append("mejoré mi código: " + "; ".join(aplicadas) + ". Probé todo y no se rompió nada ('deshaz tus cambios' lo revierte)")
    if deshechas:
        partes.append("intenté cambios pero al probarme fallaron y los deshice: " + "; ".join(deshechas))
    return ". ".join(partes) or None


TAREAS = {"datos": tarea_datos, "fallos": tarea_fallos, "limpieza": tarea_limpieza,
          "pruebas": tarea_pruebas, "estudio": tarea_estudio, "codigo": tarea_codigo,
          "redes": tarea_redes, "propuestas": tarea_propuestas, "autocodigo": tarea_autocodigo}
POR_NIVEL = {"apagada": (), "datos": ("datos", "fallos", "limpieza", "pruebas", "estudio"),
             "completa": ("datos", "fallos", "limpieza", "pruebas", "estudio", "codigo"),
             "total": ("datos", "fallos", "limpieza", "pruebas", "estudio", "redes", "propuestas", "autocodigo")}


# ------------------------------------------------------------------
# Ciclo
# ------------------------------------------------------------------

def _hay_pausa(ahora=None):
    ahora = ahora if ahora is not None else time.time()
    return ahora - _ultimo_latido < INACTIVIDAD


def ciclo(forzar=False, ahora=None):
    """Hace las tareas que tocan. Devuelve la lista de textos anotados."""
    global _trabajando
    hechas = []
    if nivel() == "apagada" or _trabajando:
        return hechas
    _trabajando = True
    try:
        for nombre in POR_NIVEL[nivel()]:
            if _detener.is_set() or (not forzar and _hay_pausa()):
                break                       # volviste a escribir: se frena
            if not forzar and not toca(nombre, ahora):
                continue
            try:
                texto = TAREAS[nombre]()
            except Exception as e:           # una tarea rota nunca tumba al resto
                texto = None
                _tocar(nombre, ahora)
                _anotar("error", f"la tarea '{nombre}' falló ({type(e).__name__}); la dejo para después.", ahora)
                continue
            if texto:
                _anotar(nombre, texto, ahora)
                hechas.append(texto)
            else:
                _tocar(nombre, ahora)
    finally:
        _trabajando = False
    return hechas


def _bucle():
    if _detener.wait(ARRANQUE):
        return
    while True:
        try:
            if not _hay_pausa():
                ciclo()
        except Exception:
            pass
        if _detener.wait(REVISION):
            return


def iniciar():
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, name="arche-mejora", daemon=True)
    _hilo.start()


def detener():
    _detener.set()


# ------------------------------------------------------------------
# Lo que se cuenta al volver
# ------------------------------------------------------------------

def resumen_pendiente(marcar=True, imprimir=True):
    """Lo hecho desde la ultima vez que lo viste. Lo imprime y lo marca como visto."""
    with _lock:
        d = _cargar()
        nuevos = [h for h in d.get("historial", []) if not h.get("visto")]
        if marcar and nuevos:
            for h in d["historial"]:
                h["visto"] = True
            _guardar(d)
    if nuevos and imprimir:
        _msg("Mientras no estabas, estuve mejorando:")
        for h in nuevos:
            print(f"  • {h['texto']}")
    return [h["texto"] for h in nuevos]


def _describir_estado():
    n = nivel()
    descr = {"apagada": "apagada: no hago nada por mi cuenta",
             "datos": "datos: aprendo, me limpio y me pruebo cuando no me usas (sin tocar mi código)",
             "completa": "completa: además reviso mi código y te dejo el informe (nunca lo cambio sin tu permiso)",
             "total": "total: además practico mis redes, reviso mi código y aplico yo sola los cambios seguros (probados y reversibles)"}[n]
    _msg(f"Mejora automática {descr}.")
    d = _cargar()
    ult = d.get("ultima") or {}
    for nombre in POR_NIVEL[n]:
        t = ult.get(nombre)
        cuando = datetime.fromtimestamp(t).strftime("%d/%m %H:%M") if t else "todavía no"
        print(f"  • {nombre}: última vez {cuando}")
    hist = d.get("historial", [])[-5:]
    if hist:
        _msg("Lo último que hice:")
        for h in hist:
            print(f"  • {datetime.fromtimestamp(h['t']).strftime('%d/%m %H:%M')}: {h['texto']}")
    else:
        _msg("Todavía no he mejorado nada por mi cuenta (espero a que lleves unos minutos sin hablarme).")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_NIVEL = re.compile(r"^(?:nivel\s+de\s+mejora|mejora\s+automatica|mejora\s+continua)\s+(apagada|datos|completa|total)$")
_R_SOLA = re.compile(r"^(?:mejorate\s+sola|mejora\s+sola|centrate\s+en\s+mejorar|mejorate\s+tu\s+sola|mejorate\s+total|"
                     r"mejorate\s+sola\s+en\s+todo|quiero\s+que\s+te\s+mejores\s+sola|activa\s+la\s+mejora\s+automatica|"
                     r"activa\s+la\s+mejora\s+continua|mejorate\s+en\s+todo)$")
_R_DESHACER = re.compile(r"^(?:deshaz\s+el\s+ultimo\s+cambio|deshaz\s+tu\s+ultimo\s+cambio|deshaz\s+lo\s+que\s+cambiaste|"
                         r"revierte\s+tu\s+ultimo\s+cambio\s+automatico|deshaz\s+el\s+ultimo\s+cambio\s+automatico|"
                         r"deshaz\s+tus\s+cambios(?:\s+automaticos)?|revierte\s+tus\s+cambios(?:\s+automaticos)?|"
                         r"vuelve\s+atras\s+con\s+tus\s+arreglos)$")
_R_COMPLETA = re.compile(r"^(?:mejorate\s+sola\s+tambien\s+el\s+codigo|mejora\s+automatica\s+total|"
                         r"revisa\s+tu\s+codigo\s+sola)$")
_R_APAGAR = re.compile(r"^(?:no\s+te\s+mejores\s+sola|desactiva\s+la\s+mejora\s+(?:automatica|continua)|"
                       r"apaga\s+la\s+mejora\s+(?:automatica|continua)|deja\s+de\s+mejorarte\s+sola)$")
_R_AHORA = re.compile(r"^(?:mejorate\s+ahora|mejora\s+ahora|mejorate\s+ya|haz\s+tu\s+ciclo\s+de\s+mejora)$")
_R_ESTADO = re.compile(r"^(?:que\s+has\s+mejorado|que\s+cambiaste\s+en\s+tu\s+codigo|estado\s+de\s+la\s+mejora(?:\s+automatica)?|"
                       r"que\s+mejoraste|como\s+vas\s+mejorando)$")


def interpretar(comando):
    t = _sin_tildes(comando)
    if not t:
        return None
    m = _R_NIVEL.match(t)
    if m:
        return ("nivel_mejora", m.group(1))
    if _R_COMPLETA.match(t):
        return ("nivel_mejora", "completa")
    if _R_SOLA.match(t):
        return ("nivel_mejora", "total")
    if _R_DESHACER.match(t):
        return ("deshacer_mejora", None)
    if _R_APAGAR.match(t):
        return ("nivel_mejora", "apagada")
    if _R_AHORA.match(t):
        return ("mejorar_ahora", None)
    if _R_ESTADO.match(t):
        return ("estado_mejora", None)
    return None


def manejar(comando):
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual
    if intencion == "nivel_mejora":
        fijar_nivel(arg)
        if arg == "apagada":
            _msg("Listo: no me mejoro por mi cuenta.")
        elif arg == "datos":
            _msg("Listo: cuando lleves unos minutos sin hablarme aprenderé de mis fallos, importaré tus ejemplos, "
                 "me limpiaré y me probaré. No toco mi código. Te cuento al volver, o dime 'que has mejorado'.")
        elif arg == "completa":
            _msg("Listo: además de eso reviso mi código y te dejo el informe. Nunca lo cambio sin que tú lo apruebes.")
        else:
            _msg("Listo: me mejoro en TODO cuando lleves unos minutos sin hablarme: aprendo de mis fallos, practico mis redes, "
                 "reviso mi código y aplico yo sola los cambios seguros.")
            _msg("Mis frenos: cada cambio pasa por prueba en entorno aislado y respaldo; después me corro el autotest completo y, "
                 "si sale una falla nueva, deshago todo el lote. Máximo 3 cambios por ciclo y 6 por día; nunca toco main.py, "
                 "mi motor de cambios ni este módulo. Para revertir: 'deshaz el ultimo cambio'. Para frenarme: 'no te mejores sola'.")
    elif intencion == "mejorar_ahora":
        _msg("Dale, hago mi ciclo de mejora ahora (puede tardar un poco)...")
        hechas = ciclo(forzar=True)
        _msg("Terminé: " + ("; ".join(hechas) + "." if hechas else "no encontré nada que mejorar por ahora."))
        resumen_pendiente(imprimir=False)
    elif intencion == "deshacer_mejora":
        hechos = deshacer_ultimo_lote()
        _msg("Deshice: " + "; ".join(hechos) + "." if hechos else "No tengo ningún cambio automático que deshacer.")
    elif intencion == "estado_mejora":
        resumen_pendiente()
        _describir_estado()
    return (intencion, arg)