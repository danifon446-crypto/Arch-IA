"""
limpiar.py
----------
Revisión interactiva de conocimiento.json y respuestas.json: te muestra
cada entrada y decidís si se queda o se borra. Hace un backup (.bak)
antes de tocar nada.

Uso:
    py limpiar.py
"""

import json
import os
import shutil

BASE = os.path.dirname(__file__)
ARCHIVO_CONOCIMIENTO = os.path.join(BASE, "conocimiento.json")
ARCHIVO_RESPUESTAS = os.path.join(BASE, "respuestas.json")


def cargar(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar(path, datos):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


def backup(path):
    if os.path.exists(path):
        destino = path + ".bak"
        shutil.copy(path, destino)
        print(f"Backup creado: {destino}")


def revisar_conocimiento():
    datos = cargar(ARCHIVO_CONOCIMIENTO)
    if not datos:
        print("conocimiento.json está vacío o no existe.")
        return

    backup(ARCHIVO_CONOCIMIENTO)
    conservar = []

    for i, d in enumerate(datos):
        print(f"\n[{i + 1}/{len(datos)}]")
        print(f"  pregunta:  {d['pregunta']!r}")
        print(f"  accion:    {d['accion']}")
        print(f"  contenido: {d.get('contenido')!r}")
        print(f"  fuente:    {d.get('fuente', '?')}")

        resp = input("  ¿Conservar? (Enter=sí / n=borrar / q=terminar y guardar lo revisado) ").strip().lower()

        if resp == "q":
            conservar.extend(datos[i:])  # conserva sin revisar lo que falta
            break
        if resp != "n":
            conservar.append(d)

    guardar(ARCHIVO_CONOCIMIENTO, conservar)
    print(f"\nListo. {len(conservar)}/{len(datos)} entradas conservadas en conocimiento.json.")


def revisar_respuestas():
    datos = cargar(ARCHIVO_RESPUESTAS)
    if not datos:
        print("respuestas.json está vacío o no existe.")
        return

    backup(ARCHIVO_RESPUESTAS)
    conservar = []

    for i, d in enumerate(datos):
        print(f"\n[{i + 1}/{len(datos)}]")
        print(f"  pregunta:  {d['pregunta']!r}")
        print(f"  respuesta: {d['respuesta'][:150]!r}")

        resp = input("  ¿Conservar? (Enter=sí / n=borrar / q=terminar y guardar lo revisado) ").strip().lower()

        if resp == "q":
            conservar.extend(datos[i:])
            break
        if resp != "n":
            conservar.append(d)

    guardar(ARCHIVO_RESPUESTAS, conservar)
    print(f"\nListo. {len(conservar)}/{len(datos)} entradas conservadas en respuestas.json.")


if __name__ == "__main__":
    print("¿Qué querés revisar?")
    print("  1. conocimiento.json (comandos aprendidos)")
    print("  2. respuestas.json (respuestas de conversar)")
    opcion = input("> ").strip()

    if opcion == "1":
        revisar_conocimiento()
    elif opcion == "2":
        revisar_respuestas()
    else:
        print("Opción no válida.")