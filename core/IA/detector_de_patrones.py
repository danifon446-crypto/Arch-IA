"""
detector_patrones.py
----------------------
Ubicacion: Arche/core/IA/detector_patrones.py

Analiza respuestas.json (cache de preguntas/respuestas de Ollama) y
telemetria.jsonl (registro de uso real) para encontrar preguntas que
se repitieron tantas veces que vale la pena promoverlas a un lookup
fijo en preguntas_frecuentes.py -- sin pasar mas por embeddings ni
por Ollama.

UMBRAL_MINIMO: definido en 5 (conservador, segun lo acordado). Una
pregunta necesita haberse reutilizado al menos esa cantidad de veces
desde el cache antes de considerarse candidata.

Uso:
    python core/IA/detector_patrones.py
"""

import json
from pathlib import Path

BASE = Path(__file__).parent
ARCHIVO_RESPUESTAS = BASE / "respuestas.json"
ARCHIVO_TELEMETRIA = BASE / "telemetria.jsonl"

UMBRAL_MINIMO = 5


def cargar_respuestas():
    if not ARCHIVO_RESPUESTAS.exists():
        return []
    with open(ARCHIVO_RESPUESTAS, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def cargar_eventos_telemetria():
    if not ARCHIVO_TELEMETRIA.exists():
        return []
    eventos = []
    with open(ARCHIVO_TELEMETRIA, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                eventos.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
    return eventos


def ya_promovida(pregunta_norm):
    try:
        from core.IA.preguntas_frecuentes import PREGUNTAS_FRECUENTES
    except ImportError:
        return False
    return pregunta_norm in PREGUNTAS_FRECUENTES


def detectar_candidatos(umbral=UMBRAL_MINIMO):
    """
    Devuelve una lista de candidatos a promover, ordenada de mas a
    menos repetida:
        [{"pregunta": ..., "respuesta": ..., "veces_usada": N}, ...]
    Solo incluye preguntas que:
      - se usaron al menos `umbral` veces (campo veces_usada, real,
        no estimado -- ver respuestas.py)
      - todavia NO estan en preguntas_frecuentes.py
    """
    datos = cargar_respuestas()
    candidatos = []

    for dato in datos:
        veces = dato.get("veces_usada", 1)
        if veces < umbral:
            continue
        if ya_promovida(dato["pregunta"]):
            continue
        candidatos.append({
            "pregunta": dato["pregunta"],
            "respuesta": dato["respuesta"],
            "veces_usada": veces,
        })

    candidatos.sort(key=lambda c: -c["veces_usada"])
    return candidatos


def resumen_dependencia_conversar():
    """
    Del lado de telemetria: de todas las veces que la intencion fue
    "conversar", que porcentaje se resolvio con cache_respuestas o
    preguntas_frecuentes (sin Ollama) vs ollama_conversar (llamada
    nueva). Requiere que main.py registre esto (ver integracion en
    el bloque 'conversar').
    """
    eventos = cargar_eventos_telemetria()
    comandos = [
        e for e in eventos
        if e.get("tipo") == "comando" and e.get("intencion") == "conversar"
    ]
    if not comandos:
        return None

    total = len(comandos)
    conteo = {}
    for c in comandos:
        capa = c.get("resuelto_por", "?")
        conteo[capa] = conteo.get(capa, 0) + 1

    sin_ollama = sum(v for k, v in conteo.items() if k != "ollama_conversar")

    return {
        "total": total,
        "detalle": conteo,
        "porcentaje_sin_ollama": round(100 * sin_ollama / total, 1) if total else 0.0,
    }


if __name__ == "__main__":
    candidatos = detectar_candidatos()
    resumen = resumen_dependencia_conversar()

    print(f"Umbral minimo de repeticiones: {UMBRAL_MINIMO}\n")

    if resumen:
        print(f"De {resumen['total']} conversaciones registradas en telemetria:")
        for capa, cant in sorted(resumen["detalle"].items(), key=lambda x: -x[1]):
            print(f"  - {capa}: {cant}")
        print(f"  -> {resumen['porcentaje_sin_ollama']}% ya se resuelve sin llamar a Ollama\n")
    else:
        print("Todavia no hay suficiente telemetria de 'conversar' registrada.")
        print("(Revisa que main.py ya registre resuelto_por en el bloque conversar.)\n")

    if not candidatos:
        print("No encontre candidatos nuevos para promover todavia.")
    else:
        print(f"Encontre {len(candidatos)} candidato(s) a promover:\n")
        for c in candidatos:
            resumen_resp = c["respuesta"][:80] + ("..." if len(c["respuesta"]) > 80 else "")
            print(f"  [{c['veces_usada']}x] {c['pregunta']}")
            print(f"        -> {resumen_resp}")