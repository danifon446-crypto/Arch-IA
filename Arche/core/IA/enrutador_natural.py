"""
enrutador_natural.py
---------------------
Ubicacion: Arche/core/IA/enrutador_natural.py

El cambio central: hoy, cuando escribís algo que no coincide con
ningún comando fijo de main.py, Ollama lo clasifica con comprender()
-- un prompt que solo conoce ~17 intenciones (saludo, buscar, abrir,
recordar...). Todo lo demás (notas, calculadora, archivos, sistema,
configuración, Gran Sabio, examen...) SOLO se activa si escribís la
frase exacta ("crea una nota X", no "anotame que compre X").

Este módulo reemplaza esa clasificación por una que conoce TODO el
catálogo (catalogo.py, ~40 intenciones en ~10 dominios), y con dos
capas, de más barata a más cara:

  1. CACHÉ (aprendizaje.resolver): si ya se aprendió una frase
     parecida, resuelve al instante, sin llamar a Ollama.
  2. OLLAMA, con un prompt armado dinámicamente desde el catálogo
     (ids + descripciones + dominio), no una lista fija escrita a mano.

Cada vez que Ollama resuelve algo con éxito, se aprende automáticamente
(aprendizaje.aprender) -- así el sistema se auto-refuerza con el uso
normal, no solo con el ciclo de examen: cuantas más veces uses una
frase parecida, más rápido (y más barato) responde la próxima vez.

Es OPCIONAL y apagado por defecto ("modo natural on"/"off" en main.py)
-- mientras esté apagado, Arché se comporta exactamente igual que
siempre (comandos fijos + comprender() de toda la vida).
"""

import json
import os
import re
import unicodedata

from core.IA import catalogo

BASE = os.path.dirname(__file__)
ARCHIVO_CONFIG = os.path.join(BASE, "enrutador_natural_config.json")

CONFIANZA_CACHE = 1.0     # la caché (regex/similitud/embeddings) ya viene filtrada, se confía
CONFIANZA_OLLAMA = 0.75   # Ollama puede equivocarse -- se usa como umbral en main.py


def _cargar_config():
    if not os.path.exists(ARCHIVO_CONFIG):
        return {"activo": False}
    try:
        with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"activo": False}


def _guardar_config(cfg):
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def activo():
    return _cargar_config().get("activo", False)


def activar(valor):
    cfg = _cargar_config()
    cfg["activo"] = valor
    _guardar_config(cfg)


# --------------------------------------------------------------------
# Prompt armado DINÁMICAMENTE desde el catálogo -- si mañana agregás
# una intención nueva en catalogo.py, este prompt la incluye solo, sin
# tocar este archivo.
# --------------------------------------------------------------------

def _armar_prompt(texto):
    bloques = []
    for dominio, ids in catalogo.dominios_del_catalogo().items():
        lineas_dominio = []
        for id_intencion in ids:
            entrada = catalogo.POR_ID[id_intencion]
            pista_arg = f" (contenido: el/la {entrada['argumento']})" if entrada.get("argumento") else ""
            lineas_dominio.append(f'  - "{id_intencion}": {entrada["descripcion"]}{pista_arg}')
        bloques.append(f"# {dominio}\n" + "\n".join(lineas_dominio))

    catalogo_texto = "\n\n".join(bloques)

    return f"""Sos el clasificador de intenciones de un asistente virtual llamado Arché.
Tu única tarea es identificar cuál de estas intenciones representa mejor lo que pide la persona.

INTENCIONES DISPONIBLES (agrupadas por dominio):

{catalogo_texto}

REGLAS:
- Respondé SOLO con un JSON, sin texto antes ni después, sin backticks.
- El campo "intencion" tiene que ser EXACTAMENTE uno de los ids de la lista de arriba (el texto entre comillas antes de los ":"), tal cual, sin inventar ninguno nuevo.
- El campo "contenido" es el dato variable de la frase (lo que va en el "{{X}}" de la descripción), o "" si la intención no lleva ninguno.
- Si la frase no encaja bien con NINGUNA intención de la lista, usá "intencion": "desconocido".

Formato exacto:
{{"intencion": "id_exacto_de_la_lista", "contenido": "dato variable o vacío"}}

Frase de la persona: {texto}
"""


def _normalizar(texto):
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def _resolver_con_ollama(texto):
    """Llama a Ollama con el prompt armado desde el catálogo. Devuelve
    (id_intencion, contenido) o None si no pudo parsear una respuesta
    válida o el modelo no reconoció ninguna intención."""
    from core.IA import ollamaIA

    prompt = _armar_prompt(texto)
    try:
        respuesta = ollamaIA.ollama.chat(
            model=ollamaIA.MODELO,
            format="json",
            keep_alive=ollamaIA.KEEP_ALIVE,
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": 80, "temperature": 0.1},
        )
        texto_crudo = respuesta["message"]["content"].strip()
        inicio, fin = texto_crudo.find("{"), texto_crudo.rfind("}") + 1
        datos = json.loads(texto_crudo[inicio:fin])
    except Exception:
        return None

    id_intencion = datos.get("intencion")
    if id_intencion not in catalogo.POR_ID:
        return None
    return id_intencion, (datos.get("contenido") or "").strip()


def enrutar(texto):
    """
    Punto de entrada principal. Devuelve (id_intencion, contenido,
    confianza) o None si:
      - el texto ya es un comando fijo que main.py maneja tal cual
        (no hay que interferir con eso), o
      - no se pudo resolver ninguna intención del catálogo.

    Aprende automáticamente de cada resolución exitosa por Ollama
    (pieza de refuerzo continuo, aparte del ciclo de examen).
    """
    if not texto or not texto.strip():
        return None
    if catalogo.es_comando_fijo(texto):
        return None  # ya lo maneja el flujo determinístico de siempre

    from core.IA import aprendizaje

    resultado_cache = aprendizaje.resolver(texto)
    if resultado_cache and resultado_cache.get("accion") in catalogo.POR_ID:
        return resultado_cache["accion"], resultado_cache.get("contenido") or "", CONFIANZA_CACHE

    resultado_ollama = _resolver_con_ollama(texto)
    if resultado_ollama is None:
        return None

    id_intencion, contenido = resultado_ollama
    if id_intencion == "desconocido":
        return None

    # Refuerzo automático: la próxima vez que llegue algo parecido, lo
    # resuelve la caché (paso 1) sin volver a llamar a Ollama.
    try:
        aprendizaje.aprender(texto, id_intencion, contenido, fuente="enrutador_natural")
    except Exception:
        pass  # que falle el aprendizaje no debe tirar abajo la respuesta de este turno

    return id_intencion, contenido, CONFIANZA_OLLAMA