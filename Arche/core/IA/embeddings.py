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
descarga el modelo desde HuggingFace; después queda cacheado localmente
y no vuelve a descargar nada.

QUÉ MODELO SE USA
-----------------
Lo decide embeddings_config.json (si no existe, el de siempre). No lo
cambies a mano: usa

    python -m core.IA.recalcular_embeddings comparar      (mide cuál conviene)
    python -m core.IA.recalcular_embeddings usar e5-base  (cambia y recalcula todo)

porque al cambiar de modelo hay que recalcular los embeddings de TODOS
los ejemplos guardados (los de un modelo no sirven para otro) y ajustar
el umbral de parecido (cada modelo da números distintos).

Requiere:
    pip install sentence-transformers
"""

import json
import os

import numpy as np

BASE = os.path.dirname(__file__)
ARCHIVO_CONFIG = os.path.join(BASE, "embeddings_config.json")
CARPETA_AFINADO = os.path.join(BASE, "modelo_afinado")

# Modelos conocidos. "prefijo" = texto que el modelo espera delante de
# cada frase (los e5 se entrenaron así; sin él, rinden peor).
MODELOS = {
    "minilm":   {"modelo": "paraphrase-multilingual-MiniLM-L12-v2", "prefijo": ""},
    "e5-small": {"modelo": "intfloat/multilingual-e5-small", "prefijo": "query: "},
    "e5-base":  {"modelo": "intfloat/multilingual-e5-base", "prefijo": "query: "},
    "bge-m3":   {"modelo": "BAAI/bge-m3", "prefijo": ""},
    # el que deja afinar_embeddings.py (tu modelo ajustado con tus ejemplos)
    "afinado":  {"modelo": CARPETA_AFINADO, "prefijo": None},  # None = el del modelo base, ver config
}
POR_DEFECTO = "minilm"

# (se conserva el nombre de siempre por compatibilidad)
MODELO_EMBEDDINGS = MODELOS[POR_DEFECTO]["modelo"]

_modelo = None   # singleton, se carga solo una vez
_config = None


def leer_config():
    """{'nombre', 'modelo', 'prefijo', 'umbral_semantico'?} del modelo elegido."""
    global _config
    if _config is not None:
        return _config
    cfg = {"nombre": POR_DEFECTO, **MODELOS[POR_DEFECTO]}
    try:
        with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
            guardado = json.load(f)
        if isinstance(guardado, dict) and guardado.get("modelo"):
            cfg.update(guardado)
    except (OSError, ValueError):
        pass
    if cfg.get("prefijo") is None:
        cfg["prefijo"] = ""
    if cfg.get("nombre") == "afinado":
        cfg["modelo"] = CARPETA_AFINADO  # siempre la carpeta de esta copia de Arché, aunque la muevas
    _config = cfg
    return cfg


def guardar_config(cfg):
    """Guarda la elección de modelo y olvida el que estaba cargado."""
    global _config, _modelo
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _config = None
    _modelo = None


def umbral_configurado(por_defecto):
    """Umbral de parecido calibrado para el modelo actual, si hay uno."""
    try:
        return float(leer_config().get("umbral_semantico", por_defecto))
    except (TypeError, ValueError):
        return por_defecto


def cargar_modelo_por_nombre(nombre_o_ruta):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "Falta instalar sentence-transformers. "
            "Corre: pip install sentence-transformers"
        )
    return SentenceTransformer(nombre_o_ruta)


def _cargar_modelo():
    global _modelo

    if _modelo is None:
        cfg = leer_config()
        print(f"Arché: Cargando modelo de embeddings '{cfg['nombre']}' (solo la primera vez)...")
        _modelo = cargar_modelo_por_nombre(cfg["modelo"])
        print("Arché: Modelo de embeddings listo.")

    return _modelo


def calcular_embedding(texto):
    """
    Convierte un texto en un vector numérico (lista de floats) que
    representa su significado. El vector viene normalizado, así que
    la similitud coseno se reduce a un simple producto punto.
    """
    modelo = _cargar_modelo()
    vector = modelo.encode(leer_config()["prefijo"] + texto, normalize_embeddings=True)
    return vector.tolist()


def calcular_embeddings(textos, modelo=None, prefijo=None, mostrar_progreso=False):
    """Muchos textos de una vez (mucho más rápido que de a uno).
    Devuelve una matriz numpy (n_textos x dimension)."""
    if modelo is None:
        modelo = _cargar_modelo()
    if prefijo is None:
        prefijo = leer_config()["prefijo"]
    return modelo.encode([prefijo + t for t in textos], normalize_embeddings=True,
                         batch_size=64, show_progress_bar=mostrar_progreso)


def similitud_coseno(vector_a, vector_b):
    """
    Similitud coseno entre dos vectores ya normalizados (rango 0-1,
    donde 1 = significado idéntico).
    """
    a = np.array(vector_a)
    b = np.array(vector_b)
    return float(np.dot(a, b))
