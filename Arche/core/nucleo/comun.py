"""
comun.py
--------
Ubicacion: Arche/core/nucleo/comun.py

Lo que comparten todas las partes del núcleo:

  * informe()   -> la forma en que Arché te avisa SOLA (consola, voz, notificación,
                   avatar y cualquier canal extra que se registre, p. ej. Telegram).
  * pensar()    -> preguntarle al modelo: la nube si está configurada, si no Ollama.
  * leer/guardar JSON de forma segura, normalizar texto, tu nombre, la carpeta de datos.

Nada de aquí rompe a Arché si falla: todo devuelve un valor por defecto.
"""

import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime

from core.rutas import BASE, DATABASE

CARPETA = os.path.join(DATABASE, "nucleo")
os.makedirs(CARPETA, exist_ok=True)

ARCH_INFORMES = os.path.join(CARPETA, "informes.jsonl")
ARCH_CONFIG = os.path.join(CARPETA, "config.json")

_lock = threading.RLock()
_salidas_extra = []          # funciones(texto) que reciben cada informe (Telegram, etc.)
_ultimo_globo = {"texto": "", "cuando": 0.0, "nivel": "info"}

CONFIG_DEFECTO = {
    "horas_silencio": [23, 6],        # entre estas horas no habla ni manda notificaciones (solo escribe)
    "informes_con_voz": True,         # los avisos importantes se dicen en voz alta (si la voz está activa)
}


# ------------------------------------------------------------------
# Archivos
# ------------------------------------------------------------------

def ruta(*partes):
    r = os.path.join(CARPETA, *partes)
    os.makedirs(os.path.dirname(r), exist_ok=True)
    return r


def cargar(ruta_archivo, defecto):
    try:
        with open(ruta_archivo, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, type(defecto)) else defecto
    except (OSError, ValueError):
        return defecto


def guardar(ruta_archivo, datos):
    with _lock:
        os.makedirs(os.path.dirname(ruta_archivo), exist_ok=True)
        tmp = ruta_archivo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta_archivo)


def anotar(ruta_archivo, registro, maximo_bytes=2_000_000):
    """Agrega una línea JSON al final (bitácoras). Si crece mucho, se queda con la mitad nueva."""
    with _lock:
        try:
            if os.path.exists(ruta_archivo) and os.path.getsize(ruta_archivo) > maximo_bytes:
                with open(ruta_archivo, "r", encoding="utf-8") as f:
                    lineas = f.readlines()
                with open(ruta_archivo, "w", encoding="utf-8") as f:
                    f.writelines(lineas[len(lineas) // 2:])
            with open(ruta_archivo, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except OSError:
            pass


def leer_bitacora(ruta_archivo, desde=None):
    """Lista de registros (dict). desde: 'YYYY-MM-DD' -> solo de ese día en adelante."""
    salida = []
    try:
        with open(ruta_archivo, "r", encoding="utf-8") as f:
            for linea in f:
                try:
                    r = json.loads(linea)
                except ValueError:
                    continue
                if desde and str(r.get("cuando", ""))[:10] < desde:
                    continue
                salida.append(r)
    except OSError:
        pass
    return salida


def config(clave):
    datos = cargar(ARCH_CONFIG, {})
    return datos.get(clave, CONFIG_DEFECTO.get(clave))


def fijar_config(clave, valor):
    datos = cargar(ARCH_CONFIG, {})
    datos[clave] = valor
    guardar(ARCH_CONFIG, datos)


# ------------------------------------------------------------------
# Texto y tiempo
# ------------------------------------------------------------------

def ahora():
    return datetime.now()


def ahora_txt():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoy():
    return datetime.now().strftime("%Y-%m-%d")


def norm(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¿?¡!,;:\"“”«»()]", " ", t)
    return " ".join(t.split()).strip(" .")


_VACIAS = set("de la el los las un una unos unas y o a en con por para que se su sus al del es lo como mas "
              "pero sin sobre este esta esto eso ese hay muy ya me mi te tu le les nos the of and to in is for "
              "on with it this that be are was".split())


def palabras(texto):
    return {p for p in re.findall(r"[a-z0-9]{3,}", norm(texto)) if p not in _VACIAS}


def parecido(a, b):
    pa, pb = palabras(a), palabras(b)
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def nombre_usuario():
    """Como te llama Arché (lo que está en su configuración; si no hay, Daniel)."""
    try:
        from core import configuracion
        n = (configuracion.obtener("nombre_usuario") or "").strip()
        if n and n.lower() != "usuario":
            return n
    except Exception:
        pass
    return "Daniel"


def es_windows():
    return os.name == "nt"


def en_horas_de_silencio(momento=None):
    momento = momento or ahora()
    desde, hasta = config("horas_silencio") or [23, 6]
    h = momento.hour
    return (h >= desde or h < hasta) if desde > hasta else (desde <= h < hasta)


def json_de(texto):
    """Saca el primer JSON (objeto o lista) de lo que conteste un modelo."""
    if not texto:
        return None
    texto = re.sub(r"```(?:json)?", "", texto)
    candidatos = []
    for abre, cierra in (("[", "]"), ("{", "}")):
        i, j = texto.find(abre), texto.rfind(cierra)
        if i != -1 and j > i:
            candidatos.append((i, texto[i:j + 1]))
    for _, trozo in sorted(candidatos):
        try:
            return json.loads(trozo)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------
# Informes: cuando Arché habla sola
# ------------------------------------------------------------------

def registrar_salida(funcion):
    """funcion(texto) recibe cada informe. Para conectar Telegram u otro canal más adelante."""
    if funcion not in _salidas_extra:
        _salidas_extra.append(funcion)


def prefijo_informe():
    """«Respuesta:» con el Núcleo 1.0, «Informe:» desde el Núcleo 2.0."""
    try:
        from core.nucleo import analista
        return "Informe: " if analista.version() >= 2 else "Respuesta: "
    except Exception:
        return "Informe: "


def informe(texto, titulo="Arché", importante=False, nivel="info", origen="", con_prefijo=True):
    """
    Arché te avisa algo por su cuenta.
      importante -> además lo dice en voz alta (si la voz está activa) y manda notificación
                    de Windows (fuera de las horas de silencio).
      nivel      -> 'info' | 'alerta' (el avatar se pone rojo) | 'logro'.
    """
    texto = sin_markdown((texto or "").strip())
    if not texto:
        return
    linea = (prefijo_informe() if con_prefijo else "") + texto
    print(f"Arché: {linea}")
    anotar(ARCH_INFORMES, {"cuando": ahora_txt(), "texto": texto, "origen": origen, "nivel": nivel,
                           "importante": bool(importante)})
    _ultimo_globo.update(texto=texto, cuando=time.time(), nivel=nivel)

    silencio = en_horas_de_silencio()
    if not silencio and (importante or config("informes_con_voz")):
        if config("informes_con_voz"):
            try:
                from core import voz
                if voz.activa():
                    voz.decir(linea if threading.current_thread() is not threading.main_thread() else "")
            except Exception:
                pass
    if importante and not silencio:
        # Con arche_fondo.pyw lo que se imprime desde un hilo de fondo ya sale como notificación.
        if os.environ.get("ARCHE_FONDO") != "1":
            try:
                from core import presencia
                presencia.notificar(titulo, texto.split("\n")[0][:240])
            except Exception:
                pass
    for salida in list(_salidas_extra):
        try:
            salida(linea)
        except Exception:
            pass


def ultimo_globo():
    return dict(_ultimo_globo)


def sin_markdown(texto):
    """Quita los ** __ # y las líneas de tabla que el modelo a veces pone: en la consola se ven feas
    y la voz las lee mal."""
    t = str(texto or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*\|?\s*:?-{3,}.*$\n?", "", t)                       # separadores de tabla
    t = re.sub(r"(?m)^\s*\|(.+)\|\s*$", lambda m: "  " + " · ".join(c.strip() for c in m.group(1).split("|")), t)
    return t


def decir_en_voz(texto):
    """Lee en voz alta (si la voz está activa) lo que se dice desde un hilo de fondo: la voz de Arché
    solo lee sola lo que sale del hilo principal."""
    if threading.current_thread() is threading.main_thread():
        return                                         # eso ya lo lee core/voz.py solo
    try:
        from core import voz
        if voz.activa():
            voz.decir(texto)
    except Exception:
        pass


def msg(texto, voz=True):
    """Respuesta normal a una orden (sin prefijo de informe). voz=False para mensajes de progreso."""
    texto = sin_markdown(texto)
    print(f"Arché: {texto}")
    if voz:
        decir_en_voz(texto)


# ------------------------------------------------------------------
# Pensar: nube si está, si no Ollama
# ------------------------------------------------------------------

def _ollama(prompt, sistema="", temperatura=0.5, codigo=False, max_tokens=600):
    try:
        from core import evolucion
        return evolucion._llm(prompt, sistema=sistema, temperatura=temperatura, codigo=codigo,
                              max_tokens=max_tokens) or ""
    except Exception:
        return ""


def nube_lista():
    try:
        from core.IA import nube
        return nube.disponible()
    except Exception:
        return False


_TEXTO_PLANO = ("Escribe en texto plano: sin Markdown (nada de **, #, ni tablas con |). "
                "Usa frases cortas y viñetas con «•» si hace falta.")


def pensar(prompt, sistema="", max_tokens=600, temperatura=0.4, codigo=False, preferir_nube=True):
    """Devuelve texto ('' si ningún modelo respondió). El código lo escribe el modelo de código local
    salvo que la nube esté disponible y preferir_nube=True (la nube suele programar mejor)."""
    if not codigo and "JSON" not in prompt and "Markdown" not in prompt:
        sistema = (sistema + "\n" if sistema else "") + _TEXTO_PLANO
    if preferir_nube and nube_lista():
        try:
            from core.IA import nube
            texto = nube.responder([{"role": "user", "content": prompt}], sistema=sistema or None,
                                   max_tokens=max_tokens, temperature=temperatura)
            if texto and texto.strip():
                return texto.strip()
        except Exception:
            pass
    return _ollama(prompt, sistema=sistema, temperatura=temperatura, codigo=codigo, max_tokens=max_tokens)


_INICIO_CODIGO = re.compile(r"""^(?:import |from |def |class |async def |@|#|[A-Z_][A-Z0-9_]*\s*=|"|')""")


def extraer_codigo(texto):
    """Saca SOLO el código Python de lo que respondió un modelo (que a veces lo envuelve en explicaciones).
    Prefiere el bloque ``` más largo con 'def'. Si no hay bloques, quita el texto de antes y de después."""
    import ast
    texto = (texto or "").replace("\r\n", "\n")
    bloques = re.findall(r"```[ \t]*(?:python|py|python3)?[ \t]*\n(.*?)```", texto, re.S | re.I)
    if bloques:
        con_def = [b for b in bloques if "def " in b] or bloques
        return max(con_def, key=len).strip()
    if texto.count("```") == 1:                       # bloque que abrió y nunca cerró (respuesta cortada)
        texto = re.split(r"```[ \t]*(?:python|py)?[ \t]*\n?", texto, maxsplit=1, flags=re.I)[1]
    lineas = texto.split("\n")
    while lineas and lineas[0].strip() and not _INICIO_CODIGO.match(lineas[0].strip()):
        lineas.pop(0)                                 # «Aquí está la habilidad:» y cosas así
    codigo = "\n".join(lineas).strip()
    # si al final quedó texto suelto, se va quitando de abajo hacia arriba mientras no compile
    lineas = codigo.split("\n")
    for _ in range(min(15, len(lineas))):
        try:
            ast.parse("\n".join(lineas))
            return "\n".join(lineas).strip()
        except SyntaxError:
            ultima = lineas[-1] if lineas else ""
            if ultima.startswith((" ", "\t")):
                break
            lineas.pop()
    return codigo


def en_hilo(funcion, *args, nombre="arche-nucleo", **kwargs):
    """Corre algo en segundo plano sin que un error tumbe a Arché."""
    def _envuelta():
        try:
            funcion(*args, **kwargs)
        except Exception as e:
            anotar(ruta("errores.jsonl"), {"cuando": ahora_txt(), "donde": nombre, "error": repr(e)[:400]})
    hilo = threading.Thread(target=_envuelta, name=nombre, daemon=True)
    hilo.start()
    return hilo


__all__ = ["BASE", "DATABASE", "CARPETA"]
