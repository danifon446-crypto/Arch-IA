"""
auditar.py
----------
Diagnóstico de calidad de lo que Arché aprendió, SIN modificar nada.

Corre esto primero para ver el panorama completo antes de decidir qué
limpiar con limpiar.py.

Uso:
    py auditar.py
"""

import json
import os
from collections import Counter

BASE = os.path.dirname(__file__)
ARCHIVO_CONOCIMIENTO = os.path.join(BASE, "conocimiento.json")
ARCHIVO_RESPUESTAS = os.path.join(BASE, "respuestas.json")


def cargar(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] No se pudo leer {path}: {e}")
        return []


def es_sospechoso(texto):
    """Heurística simple para detectar texto probablemente basura."""
    if not texto or len(texto.strip()) < 3:
        return True
    signos = sum(texto.count(c) for c in "¡!¿?")
    if signos >= 2:
        return True
    palabras = texto.split()
    if len(palabras) <= 1 and len(texto) < 5:
        return True
    return False


def main():
    conocimiento = cargar(ARCHIVO_CONOCIMIENTO)
    respuestas = cargar(ARCHIVO_RESPUESTAS)

    print("=" * 60)
    print(f"conocimiento.json: {len(conocimiento)} entradas")
    print(f"respuestas.json:   {len(respuestas)} entradas")
    print("=" * 60)

    if conocimiento:
        print("\n--- conocimiento.json por acción ---")
        for accion, n in Counter(d["accion"] for d in conocimiento).most_common():
            print(f"  {accion}: {n}")

        print("\n--- conocimiento.json por fuente ---")
        for fuente, n in Counter(d.get("fuente", "?") for d in conocimiento).most_common():
            print(f"  {fuente}: {n}")

    # --- Entradas con pinta de basura (texto muy corto, muy raro, etc.) ---
    print("\n--- Entradas sospechosas en conocimiento.json (texto raro/corto) ---")
    sospechosas_c = [
        d for d in conocimiento
        if es_sospechoso(d["pregunta"]) or es_sospechoso(d.get("contenido", ""))
    ]
    if sospechosas_c:
        for d in sospechosas_c:
            print(f"  pregunta={d['pregunta']!r}  accion={d['accion']}  contenido={d.get('contenido')!r}  fuente={d.get('fuente')}")
    else:
        print("  (ninguna)")

    print("\n--- Entradas sospechosas en respuestas.json (texto raro/corto) ---")
    sospechosas_r = [d for d in respuestas if es_sospechoso(d["pregunta"])]
    if sospechosas_r:
        for d in sospechosas_r:
            print(f"  pregunta={d['pregunta']!r}  respuesta={d['respuesta'][:60]!r}...")
    else:
        print("  (ninguna)")

    # --- El patrón exacto del bug que reportaste: mismo contenido, ---
    # --- distintas preguntas -> señal de que quedó "pegado" un valor viejo ---
    print("\n--- Mismo (acción, contenido) usado por preguntas DISTINTAS ---")
    print("    (esto es exactamente el patrón del bug de contenido cruzado)")
    por_contenido = {}
    for d in conocimiento:
        clave = (d["accion"], d.get("contenido", ""))
        por_contenido.setdefault(clave, []).append(d["pregunta"])

    encontrado = False
    for (accion, contenido), preguntas in por_contenido.items():
        if len(preguntas) > 1:
            encontrado = True
            print(f"\n  accion={accion}  contenido={contenido!r}")
            print(f"  usado por {len(preguntas)} preguntas distintas:")
            for p in preguntas:
                print(f"    - {p!r}")
    if not encontrado:
        print("  (ninguna encontrada -> buena señal)")

    print("\n" + "=" * 60)
    print("Corré 'py limpiar.py' para revisar y borrar entradas una por una.")


if __name__ == "__main__":
    main()