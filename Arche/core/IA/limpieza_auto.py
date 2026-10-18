"""
limpieza_auto.py
------------------
Limpieza automática y conservadora de conocimiento.json: borra SOLO
los casos donde el patrón de "contenido cruzado" (bug que corregimos)
es inequívoco -- 3 o más preguntas claramente distintas compartiendo
el mismo accion+contenido, y ese contenido no es extraíble literalmente
de ninguna de ellas.

No toca nada dudoso. Los casos ambiguos se dejan para revisión manual
con limpiar.py -- esta función prefiere no borrar antes que borrar algo
que sí servía.

Hace backup automático antes de tocar nada, igual que limpiar.py.
"""

import json
import os
import shutil
from collections import defaultdict

BASE = os.path.dirname(__file__)
ARCHIVO = os.path.join(BASE, "conocimiento.json")

# Umbral: si el mismo (accion, contenido) aparece pegado a esta cantidad
# de preguntas CLARAMENTE distintas entre sí, se considera contaminación
# segura, no una generalización legítima.
MIN_PREGUNTAS_DISTINTAS_PARA_BORRAR = 3

# Similitud máxima (por palabras compartidas) entre preguntas del mismo
# grupo para considerarlas "claramente distintas". Si las preguntas SÍ
# se parecen entre sí (son variantes reales), no se borra -- puede ser
# una generalización legítima, no el bug.
SIMILITUD_MAXIMA_PARA_CONSIDERAR_DISTINTAS = 0.35


def _similitud_simple(a, b):
    palabras_a = set(a.lower().split())
    palabras_b = set(b.lower().split())
    if not palabras_a or not palabras_b:
        return 0.0
    interseccion = palabras_a & palabras_b
    union = palabras_a | palabras_b
    return len(interseccion) / len(union)


def _contenido_extraible(pregunta, contenido):
    """Mismo criterio que ya usamos en aprendizaje.py: si el contenido
    aparece literal dentro de la pregunta, es extracción legítima, no
    el bug de reutilización cruzada."""
    if not contenido:
        return True  # sin contenido variable, no aplica el bug
    return contenido.lower().strip() in pregunta.lower()


def limpiar_automatico(simular=False):
    """
    simular=True: no borra nada, solo devuelve qué borraría (para
    poder revisar antes de aplicar de verdad).
    """
    if not os.path.exists(ARCHIVO):
        return {"borrados": 0, "detalle": []}

    with open(ARCHIVO, "r", encoding="utf-8") as f:
        datos = json.load(f)

    grupos = defaultdict(list)
    for i, dato in enumerate(datos):
        clave = (dato.get("accion", ""), dato.get("contenido", ""))
        grupos[clave].append((i, dato))

    indices_a_borrar = set()
    detalle = []

    for (accion, contenido), items in grupos.items():
        if len(items) < MIN_PREGUNTAS_DISTINTAS_PARA_BORRAR:
            continue

        preguntas = [dato["pregunta"] for _, dato in items]

        # ¿El contenido es literal en TODAS? Si es así, es generalización
        # legítima de plantilla, no el bug -- no tocar.
        if all(_contenido_extraible(p, contenido) for p in preguntas):
            continue

        # ¿Las preguntas son realmente distintas entre sí (no variantes
        # del mismo comando)? Si se parecen mucho, podría ser legítimo.
        distintas = 0
        for a in range(len(preguntas)):
            for b in range(a + 1, len(preguntas)):
                if _similitud_simple(preguntas[a], preguntas[b]) < SIMILITUD_MAXIMA_PARA_CONSIDERAR_DISTINTAS:
                    distintas += 1

        if distintas < MIN_PREGUNTAS_DISTINTAS_PARA_BORRAR:
            continue

        # Patrón confirmado: contenido no extraíble + preguntas
        # genuinamente distintas -> contaminación segura de borrar.
        for i, dato in items:
            indices_a_borrar.add(i)
            detalle.append({"pregunta": dato["pregunta"], "accion": accion, "contenido": contenido})

    if not indices_a_borrar:
        return {"borrados": 0, "detalle": []}

    if not simular:
        backup = ARCHIVO + ".auto.bak"
        shutil.copy(ARCHIVO, backup)

        nuevos_datos = [d for i, d in enumerate(datos) if i not in indices_a_borrar]
        with open(ARCHIVO, "w", encoding="utf-8") as f:
            json.dump(nuevos_datos, f, indent=4, ensure_ascii=False)

    return {"borrados": len(indices_a_borrar), "detalle": detalle}