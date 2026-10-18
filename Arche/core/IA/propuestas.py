"""
propuestas.py
---------------
Ubicacion: Arche/core/IA/propuestas.py

Nucleo de seguridad de la Fase 3: Arche NUNCA modifica codigo
directamente. Este modulo solo GENERA propuestas (que, por que, como)
y las guarda en propuestas_pendientes.json con estado "pendiente".
La aplicacion real del cambio ocurre en revisar_propuestas.py, y
SOLO despues de tu aprobacion explicita ahi.

LIMITE DURO: Arche unicamente puede proponer cambios al archivo
preguntas_frecuentes.py (agregar entradas al diccionario
PREGUNTAS_FRECUENTES). No puede tocar main.py, ni ningun otro
archivo del proyecto, ni este modulo ni revisar_propuestas.py. Esto
mantiene el radio de impacto minimo: en el peor caso posible, una
entrada mal agregada a un diccionario de texto -- nunca un cambio en
la logica de control del programa.

Uso:
    python core/IA/propuestas.py
"""

import json
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
ARCHIVO_PROPUESTAS = BASE / "propuestas_pendientes.json"
ARCHIVO_LOG = BASE / "propuestas_log.jsonl"  # append-only, nunca se edita ni se borra

# Unico archivo que Arche puede proponer modificar (aplicado en revisar_propuestas.py)
ARCHIVO_EDITABLE = BASE / "preguntas_frecuentes.py"


def cargar_propuestas():
    if not ARCHIVO_PROPUESTAS.exists():
        return []
    with open(ARCHIVO_PROPUESTAS, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def guardar_propuestas(propuestas):
    with open(ARCHIVO_PROPUESTAS, "w", encoding="utf-8") as f:
        json.dump(propuestas, f, ensure_ascii=False, indent=2)


def _log_inmutable(evento):
    evento["timestamp"] = datetime.now().isoformat()
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def generar_propuestas_desde_candidatos(candidatos):
    """
    candidatos: salida de detector_patrones.detectar_candidatos()
    Crea una propuesta nueva por cada candidato que todavia no tenga
    una propuesta pendiente (evita duplicados si se corre mas de una vez).
    """
    pendientes = cargar_propuestas()
    preguntas_ya_propuestas = {p["pregunta"] for p in pendientes}

    nuevas = 0
    for c in candidatos:
        if c["pregunta"] in preguntas_ya_propuestas:
            continue

        propuesta = {
            "id": f"prop_{len(pendientes) + nuevas + 1}",
            "pregunta": c["pregunta"],
            "respuesta": c["respuesta"],
            "veces_usada": c["veces_usada"],
            "archivo_destino": ARCHIVO_EDITABLE.name,
            "que": f"Agregar la pregunta '{c['pregunta']}' al diccionario PREGUNTAS_FRECUENTES en {ARCHIVO_EDITABLE.name}.",
            "por_que": (
                f"Esta pregunta (o una variante muy parecida, detectada por "
                f"similitud semantica) se reutilizo {c['veces_usada']} veces "
                f"desde el cache de respuestas.py. Promoverla evita incluso "
                f"el calculo de embeddings, no solo la llamada a Ollama."
            ),
            "como": (
                f"Se agrega una linea nueva al diccionario PREGUNTAS_FRECUENTES "
                f"en {ARCHIVO_EDITABLE.name}. No se modifica ninguna otra parte "
                f"de ese archivo ni de ningun otro archivo del proyecto."
            ),
            "estado": "pendiente",
            "fecha_propuesta": datetime.now().isoformat(),
        }
        pendientes.append(propuesta)
        nuevas += 1

    if nuevas:
        guardar_propuestas(pendientes)
        _log_inmutable({"tipo": "propuestas_generadas", "cantidad": nuevas})

    return nuevas


if __name__ == "__main__":
    from core.IA.detector_de_patrones import detectar_candidatos

    candidatos = detectar_candidatos()
    nuevas = generar_propuestas_desde_candidatos(candidatos)

    if nuevas == 0:
        print("No hay candidatos nuevos para proponer.")
    else:
        print(f"Generé {nuevas} propuesta(s) nueva(s), en estado 'pendiente'.")
        print("Corré 'python core/IA/revisar_propuestas.py' para revisarlas y aprobarlas.")