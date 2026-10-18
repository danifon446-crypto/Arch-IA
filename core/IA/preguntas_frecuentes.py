"""
preguntas_frecuentes.py
-------------------------
Ubicacion: Arche/core/IA/preguntas_frecuentes.py

Este es el UNICO archivo que Arche tiene permitido modificarse a si
mismo (ver propuestas.py y revisar_propuestas.py). Contiene pares
pregunta-respuesta que se repitieron tantas veces (ver
detector_patrones.py) que se promovieron a un lookup fijo: se
resuelven con una comparacion de texto exacta, sin pasar por
embeddings ni por Ollama.

Formato: clave = pregunta normalizada (minusculas, sin tildes, sin
espacios de mas -- misma normalizacion que usa respuestas.py), valor
= la respuesta ya redactada.

Cada entrada nueva se agrega SOLO a traves de propuestas.py +
revisar_propuestas.py, con tu aprobacion explicita cada vez. Arche
nunca escribe directamente en este archivo por su cuenta.
"""

PREGUNTAS_FRECUENTES = {
    # "pregunta normalizada": "respuesta fija",
}