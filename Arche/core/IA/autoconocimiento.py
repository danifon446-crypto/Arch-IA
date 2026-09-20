"""
autoconocimiento.py
---------------------
Ubicacion: Arche/core/IA/autoconocimiento.py

Modulo que le permite a Arche responder sobre:
  - su propia evolucion segun el changelog confirmado (basado en commits)
  - su nivel real de dependencia de Ollama (medido por introspeccion.py)
  - los cambios de codigo que se auto-aplico (via proponer_cambio_codigo.py
    + revisar_cambios_codigo.py), SIN esperar a que eso se commitee a git

Se importa directo desde main.py.
"""

import json
from pathlib import Path
from core.IA.introspeccion import reporte_texto

# Vive en la misma carpeta que generar_changelog.py y su historial
HISTORIAL_PATH = Path(__file__).parent / "historial_versiones.json"

# Mismo archivo que usa proponer_cambio_codigo.py / revisar_cambios_codigo.py
CAMBIOS_CODIGO_PATH = Path(__file__).parent / "cambios_codigo_pendientes.json"

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
FRASES_AUTOMODIFICACION = [
    "que te auto modificaste", "qué te auto modificaste",
    "que te autoModificaste", "que cambios te hiciste",
    "qué cambios te hiciste", "que codigo te escribiste",
    "qué código te escribiste", "te modificaste solo",
    "en que te reescribiste", "en qué te reescribiste",
]


def cargar_cambios_confirmados(n=2):
    if not HISTORIAL_PATH.exists():
        return []
    with open(HISTORIAL_PATH, "r", encoding="utf-8") as f:
        contenido = f.read().strip()
        historial = json.loads(contenido) if contenido else []
    confirmadas = [h for h in historial if h.get("confirmada")]
    return confirmadas[-n:]


def cargar_automodificaciones_aplicadas(n=3):
    """
    Lee cambios_codigo_pendientes.json y devuelve las propuestas que
    llegaron a estado "aplicada" -- o sea, cambios que Arche
    efectivamente escribió en su propio código, con tu aprobación.
    No depende de que eso se haya commiteado a git.
    """
    if not CAMBIOS_CODIGO_PATH.exists():
        return []
    with open(CAMBIOS_CODIGO_PATH, "r", encoding="utf-8") as f:
        contenido = f.read().strip()
        propuestas = json.loads(contenido) if contenido else []
    aplicadas = [p for p in propuestas if p.get("estado") == "aplicada"]
    aplicadas.sort(key=lambda p: p.get("fecha_propuesta", ""))
    return aplicadas[-n:]


def novedades_desde(marca_fecha):
    """
    Auto-modificaciones APLICADAS (con tu aprobación) desde marca_fecha
    (exclusive) en adelante -- marca_fecha vacía trae todas. Usado por
    main.py al arrancar para avisar en una frase qué funciones nuevas
    puede hacer desde la última vez, en vez de que quede enterrado y
    solo se sepa si preguntás explícitamente "qué te auto-modificaste".
    """
    todas = cargar_automodificaciones_aplicadas(n=10**9)
    if not marca_fecha:
        return todas
    return [a for a in todas if a.get("fecha_propuesta", "") > marca_fecha]


def responder_changelog():
    entradas = cargar_cambios_confirmados(n=2)
    automods = cargar_automodificaciones_aplicadas(n=2)

    partes = []

    if entradas:
        for entrada in reversed(entradas):
            cambios = "; ".join(entrada["cambios"])
            partes.append(f"En mi versión {entrada['version']} ({entrada['fecha']}): {cambios}.")

    if automods:
        detalle_automods = "; ".join(a["que"] for a in reversed(automods))
        partes.append(f"Además, me auto-modifiqué por mi cuenta (con tu aprobación) en: {detalle_automods}.")

    if not partes:
        return "Todavía no tengo un historial de versiones registrado."

    return " ".join(partes)


def responder_automodificacion():
    automods = cargar_automodificaciones_aplicadas(n=5)
    if not automods:
        return "Todavía no me auto-modifiqué ningún código por mi cuenta."

    partes = []
    for a in reversed(automods):
        partes.append(f"En {a['archivo']}: {a['que']}")
    return "Estos son mis últimos cambios de código auto-aplicados: " + " | ".join(partes)


def responder_dependencia_ollama():
    return reporte_texto()


def manejar_autoconocimiento(texto_usuario: str):
    """
    Devuelve una respuesta (str) si el texto matchea alguna de las
    frases conocidas, o None si no matchea nada (para que main.py
    siga su flujo normal hacia analizar()).
    """
    texto = texto_usuario.lower()
    if any(f in texto for f in FRASES_AUTOMODIFICACION):
        return responder_automodificacion()
    if any(f in texto for f in FRASES_CHANGELOG):
        return responder_changelog()
    if any(f in texto for f in FRASES_DEPENDENCIA):
        return responder_dependencia_ollama()
    return None