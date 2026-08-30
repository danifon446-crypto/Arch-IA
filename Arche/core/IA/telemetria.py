"""
telemetria.py
--------------
Registra qué pasa cada vez que Arché procesa un comando: qué intención
resultó, cuánto tardó cada módulo, y si terminó en "desconocido" (fallo
de clasificación). Con esto se puede ver objetivamente, con datos reales,
dónde vale la pena invertir tiempo — en vez de adivinar.

No decide nada por su cuenta ni cambia el comportamiento de Arché.
Solo observa y guarda.
"""

import json
import os
import time
import threading
from contextlib import contextmanager

BASE = os.path.dirname(__file__)
ARCHIVO_LOG = os.path.join(BASE, "telemetria.jsonl")

_lock = threading.Lock()


def _registrar(evento):
    """Agrega una línea JSON al log. Nunca lanza excepción hacia afuera:
    la telemetría no debe poder romper el flujo real de Arché."""
    evento["timestamp"] = time.time()
    try:
        with _lock:
            with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception:
        pass  # la telemetría nunca debe tumbar el flujo principal


@contextmanager
def medir(modulo):
    """
    Uso:
        with medir("ollama_comprender"):
            resultado = ollamaIA.comprender(texto)

    Registra cuánto tardó ese bloque, y si lanzó una excepción también
    lo deja anotado (sin ocultar el error real -- se re-lanza igual).
    """
    inicio = time.perf_counter()
    error = None
    try:
        yield
    except Exception as e:
        error = str(e)
        raise
    finally:
        duracion = time.perf_counter() - inicio
        _registrar({
            "tipo": "duracion",
            "modulo": modulo,
            "duracion_seg": round(duracion, 4),
            "error": error,
        })


def registrar_comando(comando, intencion, resuelto_por):
    """
    resuelto_por: de dónde vino la respuesta final, por ejemplo:
      "determinístico", "plantilla", "similitud_caracteres",
      "embeddings", "clasificador", "ollama"
    """
    _registrar({
        "tipo": "comando",
        "comando": comando,
        "intencion": intencion,
        "resuelto_por": resuelto_por,
        "fallo": intencion == "desconocido",
    })


# ------------------------------------------------------------------
# Análisis (para el comando "estadisticas" en main.py)
# ------------------------------------------------------------------
def _cargar_eventos():
    if not os.path.exists(ARCHIVO_LOG):
        return []
    eventos = []
    with open(ARCHIVO_LOG, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                eventos.append(json.loads(linea))
            except Exception:
                continue  # línea corrupta, se ignora, no rompe el resto
    return eventos


def resumen():
    """
    Devuelve un diccionario con:
      - total_comandos
      - intenciones_mas_frecuentes: [(intencion, cantidad), ...]
      - tasa_fallo: % que terminó en "desconocido"
      - intenciones_que_mas_fallan: cuáles se preguntan pero rara vez
        se resuelven bien (heurística simple, ver abajo)
      - resuelto_por: cuánto se resuelve en cada capa (determinístico,
        plantilla, embeddings, ollama, etc.) -- clave para saber si
        Ollama se sigue usando demasiado
      - duracion_promedio_por_modulo: para saber qué tarda más
    """
    eventos = _cargar_eventos()

    comandos = [e for e in eventos if e.get("tipo") == "comando"]
    duraciones = [e for e in eventos if e.get("tipo") == "duracion"]

    total = len(comandos)
    if total == 0:
        return None

    conteo_intenciones = {}
    conteo_resuelto_por = {}
    fallos = 0

    for c in comandos:
        intencion = c.get("intencion", "desconocido")
        conteo_intenciones[intencion] = conteo_intenciones.get(intencion, 0) + 1

        resuelto_por = c.get("resuelto_por", "?")
        conteo_resuelto_por[resuelto_por] = conteo_resuelto_por.get(resuelto_por, 0) + 1

        if c.get("fallo"):
            fallos += 1

    duraciones_por_modulo = {}
    for d in duraciones:
        modulo = d.get("modulo", "?")
        duraciones_por_modulo.setdefault(modulo, []).append(d.get("duracion_seg", 0))

    promedio_por_modulo = {
        modulo: round(sum(vals) / len(vals), 3)
        for modulo, vals in duraciones_por_modulo.items()
    }

    return {
        "total_comandos": total,
        "intenciones_mas_frecuentes": sorted(
            conteo_intenciones.items(), key=lambda x: -x[1]
        ),
        "tasa_fallo": round(fallos / total * 100, 1),
        "resuelto_por": sorted(
            conteo_resuelto_por.items(), key=lambda x: -x[1]
        ),
        "duracion_promedio_por_modulo": dict(
            sorted(promedio_por_modulo.items(), key=lambda x: -x[1])
        ),
    }