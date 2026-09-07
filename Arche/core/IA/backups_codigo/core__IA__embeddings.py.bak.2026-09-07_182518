"""
embeddings.py
-------------
Capa de embeddings semánticos para la IA propia de Arché.

A diferencia de las plantillas (que generalizan estructura: "abre {X}")
y la similitud por caracteres (que tolera typos leves), este módulo
entiende SIGNIFICADO. Permite que Arché reconozca que "prende spotify"
y "abre spotify" son básicamente lo mismo, aunque compartan pocas
letras en común.

El modelo se carga UNA sola vez (la primera vez que se necesita) y se
mantiene en memoria mientras Arché esté corriendo. La primera ejecución
descarga el modelo (~470 MB) desde HuggingFace; después queda cacheado
localmente y no vuelve a descargar nada.

Requiere:
    pip install sentence-transformers
"""

import numpy as np

MODELO_EMBEDDINGS = "paraphrase-multilingual-MiniLM-L12-v2"

_modelo = None  # singleton, se carga solo una vez


def _cargar_modelo():
    global _modelo

    if _modelo is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "Falta instalar sentence-transformers. "
                "Corre: pip install sentence-transformers"
            )

        print("Arché: Cargando modelo de embeddings (solo la primera vez)...")
        _modelo = SentenceTransformer(MODELO_EMBEDDINGS)
        print("Arché: Modelo de embeddings listo.")

    return _modelo


def calcular_embedding(texto):
    """
    Convierte un texto en un vector numérico (lista de floats) que
    representa su significado. El vector viene normalizado, así que
    la similitud coseno se reduce a un simple producto punto.
    """
    modelo = _cargar_modelo()
    vector = modelo.encode(texto, normalize_embeddings=True)
    return vector.tolist()


def similitud_coseno(vector_a, vector_b):
    """
    Similitud coseno entre dos vectores ya normalizados (rango 0-1,
    donde 1 = significado idéntico).
    """
    a = np.array(vector_a)
    b = np.array(vector_b)
    return float(np.dot(a, b))


def precargar():
    """
    Llamar esto al arrancar Arché (ej. en main.py) si quieres que la
    descarga/carga del modelo ocurra al inicio en vez de en el primer
    comando del usuario (para que el primer "abre spotify" no se sienta
    lento por la carga del modelo).
    """
    _cargar_modelo()
