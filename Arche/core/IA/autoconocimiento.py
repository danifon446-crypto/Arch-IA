"""
autoconocimiento.py
---------------------
Ubicacion: Arche/core/IA/autoconocimiento.py

Modulo que le permite a Arche responder sobre su propia evolucion
(changelog confirmado) y su nivel real de dependencia de Ollama
(medido por introspeccion.py). Se importa directo desde main.py.
"""

import json
from pathlib import Path
from core.IA.introspeccion import reporte_texto

# Vive en la misma carpeta que generar_changelog.py y su historial
HISTORIAL_PATH = Path(__file__).parent / "historial_versiones.json"

FRASES_CHANGELOG = [
    "en que has mejorado", "en qué has mejorado", "que version tenes",
    "qué versión tenés", "que cambio", "qué cambió", "novedades",
    "que mejoraste", "qué mejoraste", "en que mejoraste",
]
FRASES_DEPENDENCIA = [
    "cuanto dependes de ollama", "cuánto dependes de ollama",
    "que tan autonomo", "qué tan autónomo", "dependencia de ollama",
    "necesitas a ollama", "necesitás a ollama", "que tan independiente",
]


def cargar_cambios_confirmados(n=2):
    if not HISTORIAL_PATH.exists():
        return []
    with open(HISTORIAL_PATH, "r", encoding="utf-8") as f:
        contenido = f.read().strip()
        historial = json.loads(contenido) if contenido else []
    confirmadas = [h for h in historial if h.get("confirmada")]
    return confirmadas[-n:]


def responder_changelog():
    entradas = cargar_cambios_confirmados(n=2)
    if not entradas:
        return "Todavía no tengo un historial de versiones registrado."
    partes = []
    for entrada in reversed(entradas):
        cambios = "; ".join(entrada["cambios"])
        partes.append(f"En mi versión {entrada['version']} ({entrada['fecha']}): {cambios}.")
    return " ".join(partes)


def responder_dependencia_ollama():
    return reporte_texto()


def manejar_autoconocimiento(texto_usuario: str):
    """
    Devuelve una respuesta (str) si el texto matchea alguna de las
    frases conocidas, o None si no matchea nada (para que main.py
    siga su flujo normal hacia analizar()).
    """
    texto = texto_usuario.lower()
    if any(f in texto for f in FRASES_CHANGELOG):
        return responder_changelog()
    if any(f in texto for f in FRASES_DEPENDENCIA):
        return responder_dependencia_ollama()
    return None