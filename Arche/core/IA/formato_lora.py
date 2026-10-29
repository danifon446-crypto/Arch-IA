"""
formato_lora.py
---------------
Ubicacion: Arche/core/IA/formato_lora.py

El "idioma" en que se entrena y se usa arche-lora para entender órdenes.
Lo comparten tres lugares, por eso vive en un solo archivo:

  * nube/entrenador/datos.py   arma el dataset con este formato
  * el notebook de Kaggle       entrena con él (lo recibe dentro del dataset)
  * enrutador_natural.py        le pregunta así al modelo cuando el
                                arche-lora activo fue entrenado con este formato

Formato CORTO: el modelo aprendio las intenciones durante el
entrenamiento, así que no hace falta pegarle el catálogo entero en cada
pregunta (el prompt viejo tenía ~5.000 tokens: lento en CPU y Ollama lo
cortaba). Aquí cada pregunta es solo la frase.

Solo libreria estandar.
"""

import json
import os

VERSION_FORMATO = 1

SISTEMA_CLASIFICAR = (
    "Eres el clasificador de intenciones de Arché, un asistente en español. "
    "Lee la frase de la persona y responde SOLO con un JSON de una línea: "
    '{"intencion": "<id de la intencion>", "contenido": "<dato variable o vacio>"}'
)

# El mismo SYSTEM de modelos/Modelfile: asi se entrena la charla de repaso
SISTEMA_CHARLA = "Eres Arche, un asistente inteligente. Responde de forma clara, precisa y util."


def salida(intencion, contenido=""):
    return json.dumps({"intencion": intencion, "contenido": contenido or ""}, ensure_ascii=False)


def mensajes_clasificar(frase):
    return [{"role": "system", "content": SISTEMA_CLASIFICAR},
            {"role": "user", "content": str(frase).strip()}]


def parsear(texto):
    """(intencion, contenido) de la respuesta del modelo, o None si no es un JSON valido."""
    texto = (texto or "").strip()
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        datos = json.loads(texto[inicio:fin + 1])
    except ValueError:
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("intencion"), str):
        return None
    contenido = datos.get("contenido")
    return datos["intencion"].strip(), (contenido if isinstance(contenido, str) else "").strip()


# ------------------------------------------------------------------
# Que formato usa el arche-lora instalado en ESTE PC
# ------------------------------------------------------------------
def _archivo_modelo_activo():
    from core.rutas import DATABASE
    return os.path.join(DATABASE, "modelo_activo.json")


def modelo_activo():
    """{"version": N, "formato": "corto"} si arche-lora vino del entrenador automatico; {} si es el de siempre."""
    try:
        with open(_archivo_modelo_activo(), "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def usa_formato_corto():
    return modelo_activo().get("formato") == "corto"
