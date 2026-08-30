"""
integracion_autoconocimiento.py
---------------------------------
Este NO es un archivo nuevo para dejar suelto en el proyecto: es una guia
de que copiar dentro de main.py.

Pasos:
  1. Copia las funciones de mas abajo dentro de main.py (o en un archivo
     nuevo, ej. autoconocimiento.py, e importalas desde main.py).
  2. En el lugar donde ya evaluas los comandos deterministas (notas,
     calculadora, archivos, config) ANTES de llamar a analizar(), agrega
     la llamada a manejar_autoconocimiento() como uno mas de esos
     comandos deterministas.

Requiere en el mismo directorio:
    - historial_versiones.json  (Fase 1, paso 1)
    - introspeccion.py          (Fase 1, paso 3)
"""

import json
from pathlib import Path
from introspeccion import reporte_texto

HISTORIAL_PATH = Path(__file__).parent / "historial_versiones.json"

FRASES_CHANGELOG = [
    "en que has mejorado", "en qué has mejorado", "que version tenes",
    "qué versión tenés", "que cambio", "qué cambió", "novedades",
    "que mejoraste", "qué mejoraste",
]
FRASES_DEPENDENCIA = [
    "cuanto dependes de ollama", "cuánto dependes de ollama",
    "que tan autonomo", "qué tan autónomo", "dependencia de ollama",
    "necesitas a ollama", "necesitás a ollama",
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
        return "Todavia no tengo un historial de versiones registrado."
    partes = []
    for entrada in reversed(entradas):
        cambios = "; ".join(entrada["cambios"])
        partes.append(f"En mi version {entrada['version']} ({entrada['fecha']}): {cambios}.")
    return " ".join(partes)


def responder_dependencia_ollama():
    return reporte_texto(directorio=str(Path(__file__).parent))


def manejar_autoconocimiento(texto_usuario: str):
    """
    Devuelve una respuesta (str) si el texto matchea, o None si no,
    para que el flujo normal de main.py siga su curso hacia analizar().
    """
    texto = texto_usuario.lower()
    if any(f in texto for f in FRASES_CHANGELOG):
        return responder_changelog()
    if any(f in texto for f in FRASES_DEPENDENCIA):
        return responder_dependencia_ollama()
    return None


# --- EJEMPLO de como quedaria en el flujo principal de main.py ---
#
# respuesta = manejar_autoconocimiento(texto_usuario)
# if respuesta is not None:
#     print(respuesta)
# else:
#     analizar(texto_usuario)  # tu flujo existente