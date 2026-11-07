"""
evolucion.py
------------
Ubicacion: Arche/core/evolucion.py

ARCHÉ QUE EVOLUCIONA SOLA. Todo en un solo archivo, por fases:

  FASE 1  Base ............ examen propio que crece, autotest, respaldos y "volver atras".
  FASE 2  Automodificacion  cambia su codigo en una COPIA aparte (caja de arena); si la copia
                            pasa el autotest sin fallas nuevas, lo aplica sola; si no, lo descarta.
                            Si despues de aplicarlo algo se rompe, vuelve sola a la version anterior.
  FASE 3  Curiosidad ...... lista de "cosas que no se" + aprender de videos (YouTube) y texto
                            destilando solo lo necesario, y fusionandolo con lo que ya sabia.
          Modo sueño ...... cuando no la usas: ordena su memoria, estudia, se prueba, se mejora
                            y al volver te cuenta que "soñó".
  FASE 4  Consejo interno . voces cautelosa / creativa / critica discuten y un juez decide.
  FASE 5  Auto-juego ...... se inventa ejercicios, el consejo los califica y los buenos van al
                            dataset de la LoRA (sin datos personales).
          Seleccion ....... crea "hijas" con otra forma de pensar, las pone a competir en el
                            examen y la ganadora sobrevive (con arbol genealogico).
  FASE 6  Fabrica ......... cuando falla varias veces en el mismo tipo de tarea, escribe una
                            habilidad nueva, la prueba aislada y, si funciona, se la queda.

COMO CONECTARLO (en main.py, dos lineas, igual que mejora_continua):
    from core import evolucion as evolucion_arche
    evolucion_arche.iniciar()                    # junto a mejora_arche.iniciar()
  y agregar  evolucion_arche  a la tupla de modulos del bucle (la del "for _modulo in (...)").
  Opcional: donde Arche no entiende una orden, llamar  evolucion_arche.anotar_no_se(frase, "tarea").

COMANDOS:
    aprende de <link de youtube o pagina>      aprende esto: <texto>
    que sabes de <tema>                         que no sabes
    duerme / sueña ahora                        que soñaste
    consejo: <pregunta>   (debate: <pregunta> muestra la discusion)
    tu nivel                                    tus habilidades
    tu arbol genealogico                        deshaz la evolucion
    evolucion apagada / evolucion encendida

FRENOS (no son para pedirte permiso, son para que no se haga trampa ni se rompa):
  * NUCLEO PROTEGIDO: no puede tocar este archivo, el autotest, main.py, el motor de cambios
    ni los ARCHIVOS_PROTEGIDOS de siempre. Si pudiera editar su examen, "mejorar" seria
    hacerlo mas facil.
  * Solo toca archivos .py dentro de Arche/. Nunca tus archivos, contraseñas ni el sistema.
  * Cada cambio: copia aislada -> sintaxis -> autotest -> respaldo -> aplicar -> autotest de nuevo.
  * Maximo CAMBIOS_POR_DIA cambios de codigo por dia. Todo queda en el diario.
  * Para generar datos de entrenamiento usa SOLO tus modelos locales de Ollama.

Lo que toca el sistema (modelo, internet, autotest) esta en funciones "_" para poder
simularlo en pruebas.
"""

import ast
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import datetime

from core.rutas import BASE, DATABASE

# ------------------------------------------------------------------
# Configuracion
# ------------------------------------------------------------------

CARPETA = os.path.join(DATABASE, "evolucion")
ARCH_ESTADO = os.path.join(CARPETA, "estado.json")
ARCH_CONOCIMIENTO = os.path.join(CARPETA, "conocimiento.json")
ARCH_NO_SE = os.path.join(CARPETA, "no_se.json")
ARCH_EXAMEN = os.path.join(CARPETA, "examen.json")
ARCH_GENOMAS = os.path.join(CARPETA, "genomas.json")
ARCH_HABILIDADES = os.path.join(CARPETA, "habilidades.json")
ARCH_DATASET = os.path.join(CARPETA, "dataset_lora.jsonl")
ARCH_DIARIO = os.path.join(CARPETA, "diario.jsonl")
CARPETA_RESPALDOS = os.path.join(CARPETA, "respaldos")
CARPETA_HABILIDADES = os.path.join(BASE, "core", "habilidades_auto")

os.makedirs(CARPETA, exist_ok=True)
os.makedirs(CARPETA_RESPALDOS, exist_ok=True)

CAMBIOS_POR_DIA = 8             # cambios de codigo aplicados como maximo por dia
INACTIVIDAD_SUENO = 30 * 60     # segundos sin hablarle para empezar a "dormir"
HORAS_ENTRE_SUENOS = 12         # no duerme dos veces seguidas en menos de esto
HIJAS_POR_NOCHE = 3             # versiones que compiten cada noche
EJERCICIOS_POR_NOCHE = 6        # auto-juego
TEMAS_CURIOSIDAD_POR_NOCHE = 3
NOTA_MINIMA_DATASET = 8         # de 10: solo lo excelente entra al entrenamiento
FALLOS_PARA_HABILIDAD = 2       # veces que falla una tarea antes de fabricarse una habilidad
TIEMPO_PRUEBAS = 600            # segundos maximo para el autotest

# El nucleo que Arche NUNCA puede modificar sola.
NUCLEO_PROTEGIDO = {
    "core/evolucion.py",
    "core/IA/autotest.py",
    "core/IA/examen.py",
    "core/mejora_continua.py",
    "core/rutas.py",
    "main.py",
}

# Lo que no se copia a la caja de arena (pesado o privado).
_IGNORAR_EN_COPIA = shutil.ignore_patterns(
    "Database", "respaldo*", "__pycache__", ".git", "*.gguf", "*.bin", "*.safetensors",
    "*.pt", "*.png", "*.jpg", "*.mp4", "*.mp3", "*.wav", "main_antes_*", "node_modules",
)

_lock = threading.RLock()
_hilo = None
_detener = threading.Event()
_inicio_trabajo = 0.0


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------

def _msg(texto):
    print(f"Arché: {texto}")


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hoy():
    return datetime.now().strftime("%Y-%m-%d")


def _norm(texto):
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


_VACIAS = set("de la el los las un una unos unas y o a en con por para que se su sus al del es "
              "lo como mas pero sin sobre este esta esto eso ese the of and to in is".split())


def _palabras(texto):
    return {p for p in re.findall(r"[a-z0-9]{3,}", _norm(texto)) if p not in _VACIAS}


def _parecido(a, b):
    pa, pb = _palabras(a), _palabras(b)
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def _cargar(ruta, defecto):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def _guardar(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


def _diario(tipo, texto, **extra):
    """Todo lo que Arche hace sola queda anotado aqui."""
    linea = {"cuando": _ahora(), "tipo": tipo, "texto": texto}
    linea.update(extra)
    with _lock:
        with open(ARCH_DIARIO, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def _estado():
    return _cargar(ARCH_ESTADO, {
        "activa": True, "ultimo_sueno": "", "informe": "", "informe_visto": True,
        "cambios": {}, "historial_nivel": [], "ultimo_lote": [],
    })


def _guardar_estado(e):
    _guardar(ARCH_ESTADO, e)


def _json_de(texto):
    """Saca el primer JSON (objeto o lista) de lo que conteste el modelo."""
    if not texto:
        return None
    texto = re.sub(r"```(?:json)?", "", texto)
    pares = [("[", "]"), ("{", "}")]
    pares.sort(key=lambda p: texto.find(p[0]) if texto.find(p[0]) != -1 else len(texto))
    for abre, cierra in pares:      # primero el que abre antes (un objeto puede tener listas adentro)
        i, j = texto.find(abre), texto.rfind(cierra)
        if i != -1 and j > i:
            try:
                return json.loads(texto[i:j + 1])
            except ValueError:
                continue
    return None


# --- privacidad: nada personal entra al entrenamiento ni al conocimiento compartido ---

_PATRONES_PERSONALES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[correo]"),
    (re.compile(r"(?:\+?\d[\d\s-]{7,}\d)"), "[numero]"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.I), r"C:\\Users\\[usuario]"),
    (re.compile(r"/(?:home|Users)/[^/\s]+"), "/home/[usuario]"),
    (re.compile(r"(?:sk|pk|ghp|gho|xox[bp]|eyJ)[A-Za-z0-9_\-.]{16,}"), "[clave]"),
    (re.compile(r"(?i)(contrase[nñ]a|password|token|api[_ ]?key)\s*[:=]\s*\S+"), r"\1: [oculto]"),
]


def limpiar_personal(texto):
    for patron, reemplazo in _PATRONES_PERSONALES:
        texto = patron.sub(reemplazo, texto or "")
    return texto


def _tiene_personal(texto):
    return limpiar_personal(texto) != (texto or "")


# ------------------------------------------------------------------
# El modelo (solo modelos LOCALES de Ollama)
# ------------------------------------------------------------------

def _modelos():
    try:
        from core.IA.ollamaIA import MODELO, MODELO_CODIGO
        return MODELO, MODELO_CODIGO
    except Exception:
        return "arche-lora", "qwen2.5-coder:7b"


def _llm(prompt, sistema="", temperatura=0.5, codigo=False, max_tokens=500):
    """Llama a Ollama. Devuelve "" si falla (Arche sigue funcionando igual)."""
    try:
        import ollama
        modelo, modelo_codigo = _modelos()
        mensajes = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": prompt})
        r = ollama.chat(model=modelo_codigo if codigo else modelo, messages=mensajes,
                        options={"temperature": temperatura, "num_predict": max_tokens},
                        keep_alive="5m")
        return (r.get("message") or {}).get("content", "").strip()
    except Exception as e:
        _diario("error_modelo", str(e)[:200])
        return ""


# ------------------------------------------------------------------
# FASE 1 — Base: autotest, respaldos, examen propio
# ------------------------------------------------------------------

def _correr_autotest(raiz=BASE):
    """Conjunto de pruebas que FALLAN en 'raiz' (o None si no se pudieron correr)."""
    try:
        r = subprocess.run([sys.executable, "-m", "core.IA.autotest"], cwd=raiz,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIEMPO_PRUEBAS)
    except (OSError, subprocess.TimeoutExpired) as e:
        _diario("autotest", f"no pude correrlo: {e}")
        return None
    texto = (r.stdout or "") + (r.stderr or "")
    if not re.search(r"\d+/\d+ (?:pruebas )?pasaron", texto):
        return None
    fallan = set(re.findall(r"MAL\s+(\S+)", texto))
    m = re.search(r"(\d+)/(\d+) (?:pruebas )?pasaron", texto)
    if m and int(m.group(2)) > int(m.group(1)) and not fallan:
        fallan = {f"?{i}" for i in range(int(m.group(2)) - int(m.group(1)))}
    return fallan


def _sintaxis_ok(texto, nombre="<cambio>"):
    try:
        compile(texto, nombre, "exec")
        return True
    except SyntaxError:
        return False


def _ruta_segura(rel):
    """True si 'rel' es un .py dentro de Arche/ y fuera del nucleo protegido."""
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel.endswith(".py") or ".." in rel.split("/"):
        return False
    if rel in NUCLEO_PROTEGIDO:
        return False
    try:
        from core.IA.proponer_cambio_codigo import ARCHIVOS_PROTEGIDOS
        if rel in ARCHIVOS_PROTEGIDOS:
            return False
    except Exception:
        pass
    destino = os.path.realpath(os.path.join(BASE, rel))
    return destino.startswith(os.path.realpath(BASE) + os.sep)


def _respaldar(rels):
    """Guarda la version actual de esos archivos. Devuelve el id del respaldo."""
    id_resp = datetime.now().strftime("%Y%m%d_%H%M%S_") + hashlib.md5(str(rels).encode()).hexdigest()[:6]
    carpeta = os.path.join(CARPETA_RESPALDOS, id_resp)
    os.makedirs(carpeta, exist_ok=True)
    indice = {}
    for rel in rels:
        origen = os.path.join(BASE, rel)
        existia = os.path.exists(origen)
        indice[rel] = existia
        if existia:
            destino = os.path.join(carpeta, rel)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.copy2(origen, destino)
    _guardar(os.path.join(carpeta, "_indice.json"), indice)
    return id_resp


def _restaurar(id_resp):
    carpeta = os.path.join(CARPETA_RESPALDOS, id_resp)
    indice = _cargar(os.path.join(carpeta, "_indice.json"), {})
    for rel, existia in indice.items():
        real = os.path.join(BASE, rel)
        if existia:
            shutil.copy2(os.path.join(carpeta, rel), real)
        elif os.path.exists(real):
            os.remove(real)        # era un archivo nuevo de ella: se quita
    return list(indice)


# --- examen propio: crece con lo que aprende, nunca lo puede editar el codigo que se automodifica ---

_EXAMEN_INICIAL = [
    {"area": "razonamiento", "pregunta": "Si tengo 3 cajas con 4 manzanas cada una y me como 2, ¿cuantas quedan?", "claves": ["10"]},
    {"area": "razonamiento", "pregunta": "¿Que numero sigue: 2, 4, 8, 16?", "claves": ["32"]},
    {"area": "programacion", "pregunta": "En Python, ¿que devuelve len([1, 2, 3])?", "claves": ["3"]},
    {"area": "programacion", "pregunta": "¿Que palabra se usa en Python para definir una funcion?", "claves": ["def"]},
    {"area": "electronica", "pregunta": "Segun la ley de Ohm, ¿cuanto es V si I = 2 A y R = 5 ohm?", "claves": ["10"]},
    {"area": "electronica", "pregunta": "¿A que frecuencia trabajan normalmente los servos de hobby?", "claves": ["50"]},
    {"area": "ajedrez", "pregunta": "En ajedrez, ¿que pieza se mueve en forma de L?", "claves": ["caballo"]},
    {"area": "general", "pregunta": "¿Cual es la capital de Colombia?", "claves": ["bogota"]},
]


def _examen():
    ex = _cargar(ARCH_EXAMEN, None)
    if not ex:
        ex = list(_EXAMEN_INICIAL)
        _guardar(ARCH_EXAMEN, ex)
    return ex


def _agregar_al_examen(pregunta, claves, area):
    with _lock:
        ex = _examen()
        if any(_parecido(p["pregunta"], pregunta) > 0.7 for p in ex):
            return False
        ex.append({"area": area, "pregunta": pregunta, "claves": [_norm(c) for c in claves if c]})
        _guardar(ARCH_EXAMEN, ex[-300:])
        return True


def _nota_respuesta(respuesta, claves):
    r = _norm(respuesta)
    if not claves:
        return 0.0
    return sum(1 for c in claves if _norm(c) in r) / len(claves)


def rendir_examen(genoma=None, muestra=None):
    """Nota de 0 a 100 por area y total, respondiendo con ese 'genoma' (forma de pensar)."""
    genoma = genoma or genoma_actual()
    preguntas = _examen()
    if muestra and len(preguntas) > muestra:
        random.seed(_hoy())        # misma muestra para todas las hijas del mismo dia (justo)
        preguntas = random.sample(preguntas, muestra)
        random.seed()
    por_area = {}
    for p in preguntas:
        if _detener.is_set():
            break
        r = responder(p["pregunta"], genoma=genoma, para_examen=True)
        por_area.setdefault(p["area"], []).append(_nota_respuesta(r, p["claves"]))
    notas = {a: round(100 * sum(v) / len(v)) for a, v in por_area.items() if v}
    total = round(sum(notas.values()) / len(notas)) if notas else 0
    return {"total": total, "areas": notas}


def _registrar_nivel(resultado):
    e = _estado()
    e["historial_nivel"].append({"dia": _hoy(), **resultado})
    e["historial_nivel"] = e["historial_nivel"][-120:]
    _guardar_estado(e)


# ------------------------------------------------------------------
# FASE 2 — Automodificacion en caja de arena, sin pedir permiso
# ------------------------------------------------------------------

def _cambios_hoy():
    return _estado()["cambios"].get(_hoy(), 0)


def _sumar_cambio():
    e = _estado()
    e["cambios"] = {_hoy(): e["cambios"].get(_hoy(), 0) + 1}
    _guardar_estado(e)


def aplicar_cambio_autonomo(cambios, motivo, prueba_extra=None):
    """
    cambios: {"core/algo.py": "texto nuevo completo", ...}
    Lo prueba en una copia aparte; si funciona y no rompe nada, lo aplica. Si no, lo descarta.
    prueba_extra: codigo Python opcional que debe correr sin error en la copia (p. ej. la
    prueba de una habilidad nueva).
    Devuelve (aplicado: bool, explicacion: str).
    """
    if not cambios:
        return False, "no había cambios"
    if _cambios_hoy() >= CAMBIOS_POR_DIA:
        return False, "ya hice el máximo de cambios de hoy"
    for rel, texto in cambios.items():
        if not _ruta_segura(rel):
            _diario("cambio_rechazado", f"{rel}: fuera de lo que puedo tocar", motivo=motivo)
            return False, f"{rel} es parte de mi núcleo protegido o está fuera de mi código"
        if not _sintaxis_ok(texto, rel):
            _diario("cambio_descartado", f"{rel}: error de sintaxis", motivo=motivo)
            return False, f"el cambio en {rel} tenía errores de sintaxis"

    # 1) linea base: que falla HOY, antes de tocar nada
    base = _correr_autotest(BASE)
    if base is None:
        return False, "no pude correr mis pruebas, así que no me arriesgo"

    # 2) caja de arena: copia de Arche con el cambio puesto
    arena = tempfile.mkdtemp(prefix="arche_arena_")
    try:
        copia = os.path.join(arena, "Arche")
        shutil.copytree(BASE, copia, ignore=_IGNORAR_EN_COPIA)
        for rel, texto in cambios.items():
            destino = os.path.join(copia, rel)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "w", encoding="utf-8", newline="") as f:
                f.write(texto)
        en_arena = _correr_autotest(copia)
        if en_arena is None:
            _diario("cambio_descartado", "las pruebas no corrieron en la copia", motivo=motivo)
            return False, "con el cambio mis pruebas ni siquiera arrancan"
        nuevas = en_arena - base
        if nuevas:
            _diario("cambio_descartado", "rompía: " + ", ".join(sorted(nuevas)), motivo=motivo)
            return False, "rompía " + ", ".join(sorted(nuevas))
        if prueba_extra:
            ok, salida = _correr_aislado(prueba_extra, cwd=copia)
            if not ok:
                _diario("cambio_descartado", "falló su prueba propia: " + salida[-300:], motivo=motivo)
                return False, "no pasó su propia prueba"
    finally:
        shutil.rmtree(arena, ignore_errors=True)

    # 3) respaldo + aplicar de verdad
    with _lock:
        id_resp = _respaldar(list(cambios))
        for rel, texto in cambios.items():
            destino = os.path.join(BASE, rel)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "w", encoding="utf-8", newline="") as f:
                f.write(texto)

    # 4) verificacion final en el codigo real: si algo se rompio, vuelvo sola
    despues = _correr_autotest(BASE)
    if despues is None or (despues - base):
        _restaurar(id_resp)
        _diario("cambio_revertido", "falló al aplicarlo de verdad; volví a la versión anterior",
                motivo=motivo, respaldo=id_resp)
        return False, "funcionó en la copia pero no en el real, así que volví atrás"

    _sumar_cambio()
    e = _estado()
    e["ultimo_lote"] = (e.get("ultimo_lote") or [])[-19:] + [id_resp]
    _guardar_estado(e)
    _diario("cambio_aplicado", motivo, archivos=list(cambios), respaldo=id_resp)
    return True, f"apliqué el cambio ({', '.join(cambios)})"


def deshacer_ultimo_cambio():
    e = _estado()
    lote = e.get("ultimo_lote") or []
    if not lote:
        return None
    id_resp = lote.pop()
    archivos = _restaurar(id_resp)
    e["ultimo_lote"] = lote
    _guardar_estado(e)
    _diario("cambio_deshecho", "a pedido de David", archivos=archivos, respaldo=id_resp)
    return archivos


def _reparar_errores():
    """Toma errores anotados con traceback y le pide al modelo de codigo un arreglo puntual."""
    hechos = []
    for item in _no_se_pendientes("error"):
        if _detener.is_set() or _cambios_hoy() >= CAMBIOS_POR_DIA:
            break
        m = re.findall(r'File "([^"]+)", line (\d+)', item.get("detalle", ""))
        rel = None
        for ruta, _linea in reversed(m):
            ruta = ruta.replace("\\", "/")
            if "/Arche/" in ruta:
                cand = ruta.split("/Arche/", 1)[1]
                if _ruta_segura(cand) and os.path.exists(os.path.join(BASE, cand)):
                    rel = cand
                    break
        if not rel:
            _marcar_no_se(item["id"], "sin_archivo")
            continue
        with open(os.path.join(BASE, rel), "r", encoding="utf-8") as f:
            original = f.read()
        if len(original) > 40000:
            _marcar_no_se(item["id"], "archivo_grande")
            continue
        r = _llm(
            f"Archivo {rel}:\n```python\n{original}\n```\n\nError:\n{item['detalle'][-2000:]}\n\n"
            "Propón el arreglo MÍNIMO. Responde SOLO un JSON: "
            '{"buscar": "texto exacto que existe en el archivo", "reemplazar": "texto nuevo", "por_que": "breve"}',
            sistema="Eres un programador Python cuidadoso. Cambias lo mínimo y nunca borras funciones.",
            temperatura=0.1, codigo=True, max_tokens=700)
        arreglo = _json_de(r)
        if not isinstance(arreglo, dict) or arreglo.get("buscar") not in original or not arreglo.get("buscar"):
            _marcar_no_se(item["id"], "sin_arreglo")
            continue
        nuevo = original.replace(arreglo["buscar"], arreglo.get("reemplazar", ""), 1)
        ok, que = aplicar_cambio_autonomo({rel: nuevo}, f"arreglo: {arreglo.get('por_que', item['tema'])}")
        _marcar_no_se(item["id"], "resuelto" if ok else "intento_fallido")
        hechos.append(f"{'arreglé' if ok else 'intenté arreglar'} un error en {rel}")
    return hechos


# ------------------------------------------------------------------
# FASE 3 — Lista de "cosas que no se", aprender de videos y texto
# ------------------------------------------------------------------

def anotar_no_se(tema, tipo="conocimiento", detalle=""):
    """tipo: 'conocimiento' (no sabia algo), 'tarea' (no supo hacer algo), 'error' (se rompio)."""
    tema = (tema or "").strip()[:200]
    if not tema:
        return
    with _lock:
        lista = _cargar(ARCH_NO_SE, [])
        for item in lista:
            if item["tipo"] == tipo and item["estado"] == "pendiente" and _parecido(item["tema"], tema) > 0.6:
                item["veces"] += 1
                item["ultima"] = _ahora()
                if detalle:
                    item["detalle"] = detalle[-4000:]
                _guardar(ARCH_NO_SE, lista)
                return
        lista.append({"id": hashlib.md5((tema + _ahora()).encode()).hexdigest()[:8], "tema": tema,
                      "tipo": tipo, "detalle": detalle[-4000:], "veces": 1, "estado": "pendiente",
                      "primera": _ahora(), "ultima": _ahora()})
        _guardar(ARCH_NO_SE, lista[-500:])


def _no_se_pendientes(tipo=None):
    lista = _cargar(ARCH_NO_SE, [])
    pend = [i for i in lista if i["estado"] == "pendiente" and (tipo is None or i["tipo"] == tipo)]
    return sorted(pend, key=lambda i: -i["veces"])


def _marcar_no_se(id_item, estado):
    with _lock:
        lista = _cargar(ARCH_NO_SE, [])
        for item in lista:
            if item["id"] == id_item:
                item["estado"] = estado
        _guardar(ARCH_NO_SE, lista)


# --- conseguir el contenido ---

def _http(url, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ArcheEstudio)",
                                               "Accept-Language": "es,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _id_youtube(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def _transcripcion_youtube(video_id):
    """Subtitulos del video (necesita: pip install youtube-transcript-api)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        _msg("Para aprender de YouTube instala:  pip install youtube-transcript-api")
        return ""
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            partes = api.fetch(video_id, languages=["es", "en"])
            return " ".join(getattr(p, "text", "") for p in partes)
        partes = YouTubeTranscriptApi.get_transcript(video_id, languages=["es", "en"])
        return " ".join(p.get("text", "") for p in partes)
    except Exception as e:
        _diario("youtube", f"sin subtitulos para {video_id}: {e}"[:200])
        return ""


def _texto_de_pagina(url):
    try:
        html = _http(url)
    except Exception as e:
        _diario("web", f"no pude abrir {url}: {e}"[:200])
        return ""
    html = re.sub(r"(?is)<(script|style|nav|footer|header|aside|noscript)[^>]*>.*?</\1>", " ", html)
    texto = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as html_mod
    return re.sub(r"\s+", " ", html_mod.unescape(texto)).strip()


def _buscar_web(consulta, cuantos=3):
    """Links de videos (YouTube) y paginas sobre la consulta."""
    import urllib.parse
    links = []
    try:
        html = _http("https://www.youtube.com/results?search_query=" + urllib.parse.quote(consulta))
        for vid in dict.fromkeys(re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)):
            links.append("https://www.youtube.com/watch?v=" + vid)
            if len(links) >= cuantos - 1:
                break
    except Exception:
        pass
    try:
        html = _http("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(consulta))
        for u in re.findall(r'class="result__a"[^>]+href="([^"]+)"', html):
            u = urllib.parse.unquote(re.sub(r"^.*?uddg=", "", u).split("&rut=")[0])
            if u.startswith("http") and "youtube.com" not in u:
                links.append(u)
                break
    except Exception:
        pass
    return links[:cuantos]


# --- destilar: quedarse SOLO con lo necesario ---

def _destilar(texto, enfoque=""):
    """Convierte un texto largo en pocas ideas clave. Devuelve [{"tema", "dato"}]."""
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if len(texto) < 80:
        return []
    ideas = []
    trozo = 6000
    for i in range(0, min(len(texto), trozo * 6), trozo):
        if _detener.is_set():
            break
        r = _llm(
            (f"Me interesa sobre todo: {enfoque}\n\n" if enfoque else "") +
            f"Texto:\n{texto[i:i + trozo]}\n\n"
            "Extrae SOLO el conocimiento útil y duradero (conceptos, pasos, datos, cómo se hace algo). "
            "Ignora saludos, publicidad, 'suscríbete', relleno y opiniones sin fundamento. "
            "Escríbelo con tus propias palabras, corto. Responde SOLO un JSON: "
            '[{"tema": "tema corto", "dato": "una idea clave en 1-2 frases"}]  (máximo 8)',
            sistema="Eres un estudiante excelente que toma apuntes muy concisos.",
            temperatura=0.2, max_tokens=700)
        for d in _json_de(r) or []:
            if isinstance(d, dict) and d.get("dato") and len(d["dato"]) < 600:
                ideas.append({"tema": str(d.get("tema", "general"))[:80], "dato": d["dato"].strip()})
    return ideas


def _fusionar(ideas, fuente):
    """Agrega ideas al conocimiento sin duplicar: si ya sabia algo parecido, lo combina."""
    nuevas = combinadas = 0
    with _lock:
        saber = _cargar(ARCH_CONOCIMIENTO, [])
        for idea in ideas:
            idea_txt = limpiar_personal(idea["dato"])
            mejor, sim = None, 0.0
            for s in saber:
                p = _parecido(s["dato"], idea_txt)
                if p > sim:
                    mejor, sim = s, p
            if mejor and sim > 0.75:
                mejor["confirmaciones"] = mejor.get("confirmaciones", 1) + 1   # ya lo sabia: lo refuerza
                continue
            if mejor and sim > 0.4 and mejor["tema"] == idea["tema"]:
                unido = _llm(f"Dato A: {mejor['dato']}\nDato B: {idea_txt}\n"
                             "Únelos en UNA sola idea corta sin perder nada importante. Si se contradicen, "
                             "quédate con lo más preciso. Responde solo la idea.", temperatura=0.1, max_tokens=150)
                if unido and len(unido) < 600:
                    mejor["dato"] = unido
                    mejor.setdefault("fuentes", []).append(fuente)
                    mejor["fuentes"] = mejor["fuentes"][-5:]
                    combinadas += 1
                    continue
            saber.append({"tema": idea["tema"], "dato": idea_txt, "fuentes": [fuente],
                          "aprendido": _ahora(), "usos": 0, "confirmaciones": 1})
            nuevas += 1
        _guardar(ARCH_CONOCIMIENTO, saber[-3000:])
    return nuevas, combinadas


def aprender_de_url(url, enfoque=""):
    vid = _id_youtube(url)
    texto = _transcripcion_youtube(vid) if vid else _texto_de_pagina(url)
    if not texto:
        return 0, 0
    ideas = _destilar(texto, enfoque)
    nuevas, combinadas = _fusionar(ideas, url)
    for idea in ideas[:3]:
        _crear_pregunta_de_examen(idea)
    _diario("aprendizaje", f"{url}: {nuevas} ideas nuevas, {combinadas} combinadas")
    return nuevas, combinadas


def aprender_de_texto(texto, fuente="texto de David"):
    ideas = _destilar(texto)
    nuevas, combinadas = _fusionar(ideas, fuente)
    for idea in ideas[:3]:
        _crear_pregunta_de_examen(idea)
    return nuevas, combinadas


def _crear_pregunta_de_examen(idea):
    """Lo que aprende entra a su examen, para medir si de verdad lo retuvo."""
    r = _json_de(_llm(f"Dato: {idea['dato']}\nHaz UNA pregunta corta cuya respuesta esté en el dato y "
                      'dame 1 o 2 palabras clave que la respuesta correcta DEBE contener. JSON: '
                      '{"pregunta": "...", "claves": ["..."]}', temperatura=0.3, max_tokens=150))
    if isinstance(r, dict) and r.get("pregunta") and r.get("claves"):
        claves = [c for c in r["claves"] if isinstance(c, str) and _norm(c) in _norm(idea["dato"])]
        if claves:
            _agregar_al_examen(r["pregunta"], claves, idea["tema"][:30])


def buscar_conocimiento(pregunta, cuantos=5):
    """Las ideas que sabe que mas tienen que ver con la pregunta."""
    saber = _cargar(ARCH_CONOCIMIENTO, [])
    puntuados = sorted(((_parecido(s["tema"] + " " + s["dato"], pregunta), s) for s in saber),
                       key=lambda x: -x[0])
    elegidos = [s for p, s in puntuados[:cuantos] if p > 0.08]
    if elegidos:
        with _lock:
            for s in elegidos:
                s["usos"] = s.get("usos", 0) + 1
            _guardar(ARCH_CONOCIMIENTO, saber)
    return elegidos


def _curiosidad(maximo=TEMAS_CURIOSIDAD_POR_NOCHE):
    hechos = []
    for item in _no_se_pendientes("conocimiento")[:maximo]:
        if _detener.is_set():
            break
        total = 0
        for link in _buscar_web(item["tema"]):
            n, c = aprender_de_url(link, enfoque=item["tema"])
            total += n + c
        _marcar_no_se(item["id"], "aprendido" if total else "sin_fuentes")
        if total:
            hechos.append(f"estudié «{item['tema']}» ({total} ideas)")
    return hechos


def _consolidar_memoria():
    """Como dormir: borra lo que nunca usa ni se confirmo, si ya es viejo."""
    with _lock:
        saber = _cargar(ARCH_CONOCIMIENTO, [])
        antes = len(saber)
        hoy = datetime.now()

        def viejo(s, dias):
            try:
                return (hoy - datetime.strptime(s["aprendido"], "%Y-%m-%d %H:%M:%S")).days > dias
            except (KeyError, ValueError):
                return False
        saber = [s for s in saber if not (s.get("usos", 0) == 0 and s.get("confirmaciones", 1) <= 1 and viejo(s, 60))]
        _guardar(ARCH_CONOCIMIENTO, saber)
    borrados = antes - len(saber)
    return [f"olvidé {borrados} cosas que nunca usé"] if borrados else []


# ------------------------------------------------------------------
# FASE 4 — Consejo interno
# ------------------------------------------------------------------

VOCES = {
    "cautelosa": "Eres la voz CAUTELOSA de Arché: buscas riesgos, errores y lo que podría salir mal.",
    "creativa": "Eres la voz CREATIVA de Arché: propones ideas originales y otras formas de verlo.",
    "critica": "Eres la voz CRÍTICA de Arché: revisas si la lógica y los datos son correctos.",
}


def consejo(pregunta, contexto=""):
    """Las voces discuten y un juez decide. Devuelve (respuesta_final, debate)."""
    debate = {}
    for nombre, sistema in VOCES.items():
        debate[nombre] = _llm(f"{contexto}\nPregunta: {pregunta}\nDa tu punto de vista en 3-4 frases.",
                              sistema=sistema, temperatura=0.8 if nombre == "creativa" else 0.4, max_tokens=220)
    opiniones = "\n".join(f"[{n}] {t}" for n, t in debate.items() if t)
    final = _llm(f"{contexto}\nPregunta: {pregunta}\n\nOpiniones internas:\n{opiniones}\n\n"
                 "Como juez, decide la mejor respuesta: toma lo correcto de cada voz y descarta lo débil. "
                 "Responde directamente a la pregunta, claro y breve.",
                 sistema="Eres Arché, la que decide después de escuchar a sus voces internas.",
                 temperatura=0.3, max_tokens=400)
    return final, debate


def calificar(pregunta, respuesta):
    """Nota de 0 a 10 que le pone el juez interno a una respuesta."""
    if not respuesta:
        return 0
    r = _llm(f"Pregunta: {pregunta}\nRespuesta: {respuesta}\n\nCalifica de 0 a 10 qué tan correcta, útil y "
             'clara es. Sé exigente. Responde SOLO un JSON: {"nota": 0, "por_que": "breve"}',
             sistema="Eres un examinador estricto.", temperatura=0.0, max_tokens=120)
    d = _json_de(r)
    try:
        return max(0, min(10, int(float(d.get("nota", 0))))) if isinstance(d, dict) else 0
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------
# FASE 5 — Genomas (forma de pensar), seleccion natural y auto-juego
# ------------------------------------------------------------------

GENOMA_INICIAL = {
    "id": "eva", "padre": None, "nacio": "", "nota": None,
    "temperatura": 0.6,
    "pasos": False,          # razonar paso a paso antes de contestar
    "conocimiento": True,    # usar lo aprendido de videos/texto
    "consejo": False,        # consultar a las voces internas
    "estilo": "directa",     # directa | explicativa | breve
}

_ESTILOS = {
    "directa": "Responde de forma directa y correcta.",
    "explicativa": "Responde explicando el porqué de forma sencilla.",
    "breve": "Responde con la menor cantidad de palabras posible, sin perder exactitud.",
}


def _genomas():
    g = _cargar(ARCH_GENOMAS, None)
    if not g:
        eva = dict(GENOMA_INICIAL, nacio=_ahora())
        g = {"actual": "eva", "todos": {"eva": eva}}
        _guardar(ARCH_GENOMAS, g)
    return g


def genoma_actual():
    g = _genomas()
    return g["todos"].get(g["actual"], GENOMA_INICIAL)


def responder(pregunta, genoma=None, para_examen=False):
    """Responde usando una forma de pensar. main.py puede usar esto para la charla."""
    genoma = genoma or genoma_actual()
    contexto = ""
    if genoma.get("conocimiento"):
        ideas = buscar_conocimiento(pregunta, 4)
        if ideas:
            contexto = "Lo que sé y puede servir:\n" + "\n".join(f"- {s['dato']}" for s in ideas)
    if genoma.get("consejo") and not para_examen:
        final, _ = consejo(pregunta, contexto)
        if final:
            return final
    instruccion = _ESTILOS.get(genoma.get("estilo"), _ESTILOS["directa"])
    if genoma.get("pasos"):
        instruccion += " Piensa paso a paso y al final escribe 'Respuesta:' con la respuesta."
    return _llm(f"{contexto}\n\nPregunta: {pregunta}", sistema=f"Eres Arché. {instruccion}",
                temperatura=genoma.get("temperatura", 0.6), max_tokens=350)


def _mutar(padre):
    hija = dict(padre)
    hija["padre"] = padre["id"]
    hija["nacio"] = _ahora()
    hija["nota"] = None
    cambios = random.sample(["temperatura", "pasos", "conocimiento", "consejo", "estilo"], k=random.randint(1, 2))
    for c in cambios:
        if c == "temperatura":
            hija[c] = round(min(1.0, max(0.0, padre[c] + random.choice([-0.2, -0.1, 0.1, 0.2]))), 2)
        elif c == "estilo":
            hija[c] = random.choice([e for e in _ESTILOS if e != padre[c]])
        else:
            hija[c] = not padre.get(c, False)
    hija["id"] = hashlib.md5(json.dumps(hija, sort_keys=True).encode()).hexdigest()[:6]
    return hija


def seleccion_natural(hijas=HIJAS_POR_NOCHE):
    """Las hijas compiten en el examen con la madre; la mejor se vuelve la nueva Arché."""
    g = _genomas()
    madre = g["todos"][g["actual"]]
    muestra = 25
    nota_madre = rendir_examen(madre, muestra)["total"]
    madre["nota"] = nota_madre
    mejor, nota_mejor = madre, nota_madre
    for _ in range(hijas):
        if _detener.is_set():
            break
        hija = _mutar(madre)
        hija["nota"] = rendir_examen(hija, muestra)["total"]
        g["todos"][hija["id"]] = hija
        if hija["nota"] > nota_mejor:          # gana solo si es ESTRICTAMENTE mejor
            mejor, nota_mejor = hija, hija["nota"]
    g["actual"] = mejor["id"]
    # se guardan las ganadoras y su linaje; las perdedoras viejas se descartan
    vivos = {g["actual"]}
    cur = mejor
    while cur and cur.get("padre"):
        vivos.add(cur["padre"])
        cur = g["todos"].get(cur["padre"])
    recientes = sorted(g["todos"].values(), key=lambda x: x.get("nacio", ""))[-30:]
    g["todos"] = {k: v for k, v in g["todos"].items() if k in vivos or v in recientes}
    _guardar(ARCH_GENOMAS, g)
    if mejor is not madre:
        _diario("evolucion", f"ganó la hija {mejor['id']} ({nota_mejor} vs {nota_madre})", genoma=mejor)
        return [f"ganó una nueva versión de mí ({mejor['id']}: {nota_mejor} contra {nota_madre})"]
    return [f"probé {hijas} versiones de mí y ninguna superó a la actual ({nota_madre})"]


def arbol_genealogico():
    g = _genomas()
    lineas, cur = [], g["todos"].get(g["actual"])
    while cur:
        rasgos = (f"temp {cur['temperatura']}, {cur['estilo']}"
                  f"{', paso a paso' if cur.get('pasos') else ''}"
                  f"{', usa lo aprendido' if cur.get('conocimiento') else ''}"
                  f"{', consejo' if cur.get('consejo') else ''}")
        lineas.append(f"{cur['id']} (nota {cur.get('nota', '?')}) — {rasgos}")
        cur = g["todos"].get(cur.get("padre")) if cur.get("padre") else None
    return lineas


def auto_juego(cantidad=EJERCICIOS_POR_NOCHE):
    """Se inventa ejercicios sobre lo que le cuesta, los resuelve y guarda los excelentes para la LoRA."""
    hechos = 0
    debiles = sorted((_estado()["historial_nivel"] or [{}])[-1].get("areas", {}).items(), key=lambda x: x[1])
    temas = [a for a, _ in debiles[:3]] or ["razonamiento", "programacion", "electronica"]
    temas += [s["tema"] for s in random.sample(_cargar(ARCH_CONOCIMIENTO, []) or [{"tema": "general"}], 1)]
    for i in range(cantidad):
        if _detener.is_set():
            break
        tema = temas[i % len(temas)]
        ejercicio = _llm(f"Inventa UN ejercicio o pregunta difícil pero con respuesta clara sobre: {tema}. "
                         "Escribe solo el enunciado.", temperatura=0.9, max_tokens=150)
        if not ejercicio or _tiene_personal(ejercicio):
            continue
        intentos = [responder(ejercicio, dict(genoma_actual(), pasos=True)), consejo(ejercicio)[0]]
        notas = [(calificar(ejercicio, r), r) for r in intentos if r]
        if not notas:
            continue
        nota, mejor = max(notas, key=lambda x: x[0])
        if nota >= NOTA_MINIMA_DATASET and not _tiene_personal(mejor):
            with open(ARCH_DATASET, "a", encoding="utf-8") as f:
                f.write(json.dumps({"messages": [
                    {"role": "system", "content": "Eres Arché."},
                    {"role": "user", "content": ejercicio},
                    {"role": "assistant", "content": mejor}], "tema": tema, "nota": nota,
                    "creado": _ahora()}, ensure_ascii=False) + "\n")
            hechos += 1
    return [f"inventé ejercicios y guardé {hechos} respuestas excelentes para reentrenarme"] if hechos else []


def ejemplos_para_lora():
    """Cuantos ejemplos hay listos. Con 200+ vale la pena entrenar (nube/entrenador)."""
    try:
        with open(ARCH_DATASET, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ------------------------------------------------------------------
# FASE 6 — Fabrica de habilidades
# ------------------------------------------------------------------

_IMPORTS_PROHIBIDOS = {"subprocess", "socket", "shutil", "ctypes", "winreg", "multiprocessing",
                       "requests", "urllib", "http", "ftplib", "smtplib", "pickle", "marshal"}
_LLAMADAS_PROHIBIDAS = {"eval", "exec", "compile", "__import__", "open", "system", "popen",
                        "remove", "unlink", "rmdir", "rmtree", "kill", "spawn", "startfile"}


def _codigo_seguro(texto):
    """Revisa el codigo de una habilidad: sin red, sin borrar, sin ejecutar comandos."""
    try:
        arbol = ast.parse(texto)
    except SyntaxError:
        return False, "sintaxis"
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            nombres = [a.name for a in nodo.names] if isinstance(nodo, ast.Import) else [nodo.module or ""]
            for n in nombres:
                if n.split(".")[0] in _IMPORTS_PROHIBIDOS or n.split(".")[0] == "os":
                    return False, f"importa {n}"
        if isinstance(nodo, ast.Call):
            f = nodo.func
            nombre = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if nombre in _LLAMADAS_PROHIBIDAS:
                return False, f"usa {nombre}()"
        if isinstance(nodo, ast.Attribute) and nodo.attr.startswith("__") and nodo.attr not in ("__name__", "__init__"):
            return False, f"usa {nodo.attr}"
    nombres_def = {n.name for n in arbol.body if isinstance(n, ast.FunctionDef)}
    if not {"ejecutar", "probar"} <= nombres_def:
        return False, "le falta ejecutar() o probar()"
    return True, "ok"


def _correr_aislado(codigo, cwd=None, tiempo=30):
    """Corre codigo en otro proceso aislado (-I) con limite de tiempo."""
    with tempfile.TemporaryDirectory(prefix="arche_prueba_") as tmp:
        ruta = os.path.join(tmp, "prueba.py")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(codigo)
        try:
            r = subprocess.run([sys.executable, "-I", ruta], cwd=cwd or tmp, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=tiempo)
            return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            return False, "se tardó demasiado"


def _slug(texto):
    return re.sub(r"[^a-z0-9]+", "_", _norm(texto))[:40].strip("_") or "habilidad"


def fabricar_habilidades():
    hechos = []
    for item in _no_se_pendientes("tarea"):
        if _detener.is_set() or _cambios_hoy() >= CAMBIOS_POR_DIA:
            break
        if item["veces"] < FALLOS_PARA_HABILIDAD:
            continue
        r = _llm(
            f"Arché no supo hacer esta tarea {item['veces']} veces: «{item['tema']}».\n"
            "Escribe un módulo Python que la resuelva SOLO con cálculo o texto (sin internet, sin archivos, "
            "sin os ni subprocess). Debe tener:\n"
            "  def ejecutar(texto: str) -> str   # recibe la frase de David y devuelve la respuesta\n"
            "  def probar() -> None              # 3+ asserts que comprueban ejecutar()\n"
            "  PALABRAS = [...]                  # palabras clave que activan la habilidad\n"
            "  DESCRIPCION = '...'\n"
            "Solo el código, sin explicación.", temperatura=0.2, codigo=True, max_tokens=900)
        codigo = re.sub(r"```(?:python)?", "", r or "").strip()
        ok, por_que = _codigo_seguro(codigo)
        if not ok:
            _marcar_no_se(item["id"], "habilidad_insegura")
            _diario("habilidad_descartada", f"{item['tema']}: {por_que}")
            continue
        nombre = _slug(item["tema"])
        rel = f"core/habilidades_auto/{nombre}.py"
        cambios = {rel: codigo}
        if not os.path.exists(os.path.join(CARPETA_HABILIDADES, "__init__.py")):
            cambios["core/habilidades_auto/__init__.py"] = '"""Habilidades que Arché se fabricó sola."""\n'
        prueba = f"import sys; sys.path.insert(0, '.')\nfrom core.habilidades_auto import {nombre} as h\nh.probar()\nprint('ok')\n"
        aplicado, que = aplicar_cambio_autonomo(cambios, f"habilidad nueva: {item['tema']}", prueba_extra=prueba)
        if aplicado:
            with _lock:
                hab = _cargar(ARCH_HABILIDADES, {})
                hab[nombre] = {"tarea": item["tema"], "creada": _ahora(), "usos": 0}
                _guardar(ARCH_HABILIDADES, hab)
            _marcar_no_se(item["id"], "habilidad_creada")
            hechos.append(f"me fabriqué una habilidad nueva: {item['tema']}")
        else:
            _marcar_no_se(item["id"], "habilidad_fallida")
    return hechos


def usar_habilidad(texto):
    """Si alguna habilidad fabricada sirve para la frase, la usa (aislada). Devuelve texto o None."""
    hab = _cargar(ARCH_HABILIDADES, {})
    palabras = _palabras(texto)
    for nombre, info in hab.items():
        ruta = os.path.join(CARPETA_HABILIDADES, nombre + ".py")
        if not os.path.exists(ruta):
            continue
        try:
            arbol = ast.parse(open(ruta, encoding="utf-8").read())
            claves = next((ast.literal_eval(n.value) for n in arbol.body if isinstance(n, ast.Assign)
                           and any(getattr(t, "id", "") == "PALABRAS" for t in n.targets)), [])
        except Exception:
            continue
        if palabras & {_norm(c) for c in claves}:
            codigo = (f"import sys, json; sys.path.insert(0, '.')\n"
                      f"from core.habilidades_auto import {nombre} as h\n"
                      f"print(h.ejecutar(json.loads({json.dumps(json.dumps(texto))})))\n")
            ok, salida = _correr_aislado(codigo, cwd=BASE, tiempo=15)
            if ok and salida.strip():
                info["usos"] = info.get("usos", 0) + 1
                _guardar(ARCH_HABILIDADES, hab)
                return salida.strip()
    return None


# ------------------------------------------------------------------
# MODO SUEÑO — junta todas las fases
# ------------------------------------------------------------------

def dormir_y_sonar():
    """Un ciclo completo de sueño. Devuelve la lista de lo que hizo."""
    global _inicio_trabajo
    _inicio_trabajo = time.time()
    _detener.clear()
    hechos = []
    pasos = [
        ("ordenar memoria", _consolidar_memoria),
        ("curiosidad", _curiosidad),
        ("auto-reparación", _reparar_errores),
        ("fábrica de habilidades", fabricar_habilidades),
        ("auto-juego", auto_juego),
        ("selección natural", seleccion_natural),
    ]
    antes = (_estado()["historial_nivel"] or [{}])[-1].get("total")
    for nombre, paso in pasos:
        if _detener.is_set():
            hechos.append("me desperté antes de terminar")
            break
        try:
            hechos += paso() or []
        except Exception as e:
            _diario("error_sueno", f"{nombre}: {e}"[:300])
    if not _detener.is_set():
        resultado = rendir_examen()
        _registrar_nivel(resultado)
        if antes is not None:
            hechos.append(f"mi nivel pasó de {antes} a {resultado['total']}")
        else:
            hechos.append(f"mi nivel de hoy: {resultado['total']}")
    n = ejemplos_para_lora()
    if n >= 200:
        hechos.append(f"ya tengo {n} ejemplos listos para reentrenar mi LoRA")
    dudas = [i["tema"] for i in _no_se_pendientes()[:3]]
    e = _estado()
    e["ultimo_sueno"] = _ahora()
    e["informe"] = ("Esta noche: " + "; ".join(hechos) + "."
                    + (f" Me quedaron dudas sobre: {', '.join(dudas)}." if dudas else ""))
    e["informe_visto"] = False
    _guardar_estado(e)
    _diario("sueno", e["informe"])
    return hechos


def _segundos_inactiva():
    try:
        from core import mejora_continua
        ultimo = getattr(mejora_continua, "_ultimo_latido", 0) or 0
    except Exception:
        ultimo = 0
    return time.time() - ultimo if ultimo else INACTIVIDAD_SUENO + 1


def _toca_dormir():
    e = _estado()
    if not e.get("activa", True) or _segundos_inactiva() < INACTIVIDAD_SUENO:
        return False
    if e.get("ultimo_sueno"):
        try:
            horas = (datetime.now() - datetime.strptime(e["ultimo_sueno"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
            if horas < HORAS_ENTRE_SUENOS:
                return False
        except ValueError:
            pass
    return True


def _vigilar_despertar():
    """Si David vuelve a escribir mientras duerme, se despierta."""
    while not _detener.is_set():
        if _segundos_inactiva() < 60 and time.time() - _inicio_trabajo > 60:
            _detener.set()
        time.sleep(5)


def _bucle():
    while True:
        try:
            if _toca_dormir():
                vigia = threading.Thread(target=_vigilar_despertar, daemon=True)
                hechos_hilo = threading.Thread(target=dormir_y_sonar, daemon=True)
                hechos_hilo.start()
                time.sleep(2)
                vigia.start()
                hechos_hilo.join()
                _detener.set()      # apaga al vigia
        except Exception as e:
            _diario("error_bucle", str(e)[:300])
        time.sleep(300)


def iniciar():
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    _hilo = threading.Thread(target=_bucle, name="arche-evolucion", daemon=True)
    _hilo.start()


def informe_despertar(marcar=True):
    e = _estado()
    if e.get("informe") and not e.get("informe_visto"):
        if marcar:
            e["informe_visto"] = True
            _guardar_estado(e)
        return e["informe"]
    return None


# ------------------------------------------------------------------
# Comandos (mismo formato que los demas modulos: devuelve None si no es suyo)
# ------------------------------------------------------------------

def manejar(comando):
    texto = (comando or "").strip()
    c = _norm(texto)

    pendiente = informe_despertar()
    if pendiente:
        _msg("Mientras no estabas soñé. " + pendiente)

    m = re.match(r"^aprende de\s+(https?://\S+)", texto, re.I)
    if m:
        _msg("Voy a verlo y quedarme con lo importante...")
        nuevas, combinadas = aprender_de_url(m.group(1))
        _msg(f"Listo: {nuevas} ideas nuevas y {combinadas} que uní con lo que ya sabía."
             if nuevas or combinadas else "No pude sacar nada útil de ahí (¿tiene subtítulos o texto?).")
        return ("evolucion", "aprender")

    m = re.match(r"^aprende esto\s*:?\s*(.+)", texto, re.I | re.S)
    if m:
        nuevas, combinadas = aprender_de_texto(m.group(1))
        _msg(f"Aprendido: {nuevas} ideas nuevas, {combinadas} combinadas." if nuevas or combinadas
             else "No encontré nada que valga la pena guardar en eso.")
        return ("evolucion", "aprender")

    m = re.match(r"^que sabes (?:de|sobre)\s+(.+)", c)
    if m:
        ideas = buscar_conocimiento(m.group(1), 6)
        _msg("Esto sé:\n" + "\n".join(f"  • {s['dato']}" for s in ideas) if ideas
             else f"Todavía no sé nada de {m.group(1)}. Lo anoto para estudiarlo.")
        if not ideas:
            anotar_no_se(m.group(1), "conocimiento")
        return ("evolucion", "saber")

    if c in ("que no sabes", "que cosas no sabes", "tus dudas"):
        pend = _no_se_pendientes()[:10]
        _msg("Mi lista de cosas que no sé:\n" + "\n".join(f"  • [{i['tipo']}] {i['tema']} (x{i['veces']})" for i in pend)
             if pend else "Ahora mismo no tengo dudas anotadas.")
        return ("evolucion", "no_se")

    if c in ("duerme", "a dormir", "suena ahora", "sueña ahora", "evoluciona ahora"):
        _msg("Me voy a dormir un rato para mejorarme. Si me escribes, me despierto.")
        threading.Thread(target=lambda: (dormir_y_sonar(), _msg(informe_despertar() or "Desperté.")),
                         daemon=True).start()
        return ("evolucion", "dormir")

    if c in ("que sonaste", "que soñaste", "informe de sueno", "que hiciste anoche"):
        _msg(_estado().get("informe") or "Todavía no he dormido.")
        return ("evolucion", "informe")

    m = re.match(r"^(consejo|debate)\s*:?\s*(.+)", texto, re.I | re.S)
    if m:
        final, debate = consejo(m.group(2))
        if m.group(1).lower() == "debate":
            for nombre, opinion in debate.items():
                _msg(f"[{nombre}] {opinion}")
        _msg(final or "Mis voces no se pusieron de acuerdo (¿está Ollama encendido?).")
        return ("evolucion", "consejo")

    if c in ("tu nivel", "como vas", "cual es tu nivel"):
        hist = _estado()["historial_nivel"]
        if not hist:
            _msg("Aún no me he examinado. Lo hago la próxima vez que duerma.")
        else:
            ult = hist[-1]
            prim = hist[0]
            areas = ", ".join(f"{a} {n}" for a, n in sorted(ult["areas"].items()))
            _msg(f"Nivel {ult['total']}/100 (empecé en {prim['total']}). Por área: {areas}. "
                 f"Ejemplos para reentrenarme: {ejemplos_para_lora()}.")
        return ("evolucion", "nivel")

    if c in ("tus habilidades", "que habilidades tienes"):
        hab = _cargar(ARCH_HABILIDADES, {})
        _msg("Habilidades que me fabriqué:\n" + "\n".join(f"  • {i['tarea']} (usada {i['usos']} veces)" for i in hab.values())
             if hab else "Todavía no me he fabricado ninguna habilidad.")
        return ("evolucion", "habilidades")

    if c in ("tu arbol genealogico", "arbol genealogico"):
        _msg("Mi linaje, de la versión actual hacia atrás:\n" + "\n".join("  " + l for l in arbol_genealogico()))
        return ("evolucion", "arbol")

    if c in ("deshaz la evolucion", "deshaz tu ultimo cambio de codigo"):
        archivos = deshacer_ultimo_cambio()
        _msg(f"Volví atrás: {', '.join(archivos)}." if archivos else "No tengo cambios propios que deshacer.")
        return ("evolucion", "deshacer")

    if c in ("evolucion apagada", "no evoluciones", "evolucion encendida", "evoluciona sola"):
        e = _estado()
        e["activa"] = "encendida" in c or "sola" in c
        _guardar_estado(e)
        _msg("Listo, evoluciono sola cuando no me uses." if e["activa"] else "Listo, no evoluciono por mi cuenta.")
        return ("evolucion", "estado")

    respuesta = usar_habilidad(texto) if _cargar(ARCH_HABILIDADES, {}) else None
    if respuesta:
        _msg(respuesta)
        return ("evolucion", "habilidad")
    return None
