"""
respuestas.py
-------------
Banco de respuestas propio de Arché para la intención "conversar".

A diferencia de aprendizaje.py (que aprende INTENCIÓN, nunca contenido
ajeno para preguntas nuevas), este módulo aprende RESPUESTAS COMPLETAS,
con una regla mucho más estricta: solo se reutiliza una respuesta
guardada si la pregunta nueva es CASI IDÉNTICA en significado a una ya
respondida (umbral alto). Si es genuinamente distinta, no se inventa
nada -> se consulta a Ollama, y esa respuesta nueva se guarda para la
próxima vez.

Con el uso, Arché depende cada vez menos de Ollama para preguntas
repetidas o cercanas, sin arriesgarse a devolver una respuesta que no
corresponde a la pregunta real (el bug que motivó este módulo).

MODIFICADO: cada entrada ahora lleva "veces_usada", que se incrementa
cada vez que se reutiliza (no solo cuando se crea). Esto es lo que le
permite a detector_patrones.py saber, de forma real y no estimada,
qué preguntas se repiten lo suficiente como para promoverlas a un
lookup fijo en preguntas_frecuentes.py.

Requiere lo mismo que aprendizaje.py: sentence-transformers instalado
(core/IA/embeddings.py). Si no está disponible, este módulo se salta
solo y Arché sigue funcionando (todo va a Ollama, como antes).
"""

import json
import os
import threading
import unicodedata

BASE = os.path.dirname(__file__)
ARCHIVO = os.path.join(BASE, "respuestas.json")

_lock = threading.Lock()  # protege respuestas.json de escrituras concurrentes (ej. modo estudio en background)

# Deliberadamente MÁS ALTO que el umbral de intención (0.78). Acá nos
# jugamos reutilizar una RESPUESTA COMPLETA, no solo una clasificación
# -> el margen de error tiene que ser mucho más chico.
UMBRAL_RESPUESTA = 0.90


def _normalizar(texto):
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def cargar():
    if not os.path.exists(ARCHIVO):
        return []
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def guardar(datos):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


def guardar_respuesta(pregunta, respuesta):
    """
    Guarda una pregunta + la respuesta que dio Ollama, junto con su
    embedding, para poder reconocerla (o algo casi idéntico) después
    sin volver a consultar a Ollama.
    """
    pregunta_norm = _normalizar(pregunta)

    try:
        from core.IA.embeddings import calcular_embedding
        embedding = calcular_embedding(pregunta_norm)
    except Exception as e:
        print(f"Arché: No se pudo guardar embedding de la respuesta ({e}).")
        return  # sin embedding no hay forma de reconocerla después, no vale la pena guardar

    with _lock:
        datos = cargar()

        for dato in datos:
            if dato["pregunta"] == pregunta_norm:
                dato["respuesta"] = respuesta
                dato["embedding"] = embedding
                # no reseteamos veces_usada: sigue siendo la misma pregunta de siempre
                guardar(datos)
                return

        datos.append({
            "pregunta": pregunta_norm,
            "respuesta": respuesta,
            "embedding": embedding,
            "veces_usada": 1,
        })
        guardar(datos)


def buscar_respuesta(pregunta, umbral=UMBRAL_RESPUESTA):
    """
    Busca una respuesta ya conocida para una pregunta CASI IDÉNTICA en
    significado. Devuelve el texto de la respuesta, o None si no hay
    nada suficientemente parecido (en ese caso, hay que preguntarle a
    Ollama y luego llamar a guardar_respuesta()).

    Cada vez que hay un match, incrementa "veces_usada" de esa entrada
    y lo persiste -- es el dato real que usa detector_patrones.py.
    """
    try:
        from core.IA.embeddings import calcular_embedding, similitud_coseno
    except Exception:
        return None  # sin embeddings no hay forma segura de comparar

    with _lock:
        datos = cargar()
        if not datos:
            return None

        pregunta_norm = _normalizar(pregunta)

        try:
            vector_pregunta = calcular_embedding(pregunta_norm)
        except Exception:
            return None

        mejor_score = 0.0
        mejor_dato = None

        for dato in datos:
            if not dato.get("embedding"):
                continue
            score = similitud_coseno(vector_pregunta, dato["embedding"])
            if score > mejor_score:
                mejor_score = score
                mejor_dato = dato

        if mejor_score >= umbral and mejor_dato is not None:
            mejor_dato["veces_usada"] = mejor_dato.get("veces_usada", 1) + 1
            guardar(datos)
            return mejor_dato["respuesta"]

    return None