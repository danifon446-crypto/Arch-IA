"""
exportar_dataset.py
--------------------
Convierte conocimiento.json (comandos) y respuestas.json (conversación)
en un dataset único de entrenamiento, formato instrucción -> respuesta,
listo para fine-tuning con LoRA.

Uso:
    py exportar_dataset.py
Genera: dataset_entrenamiento.jsonl
"""

import json
import os

BASE = os.path.dirname(__file__)
ARCHIVO_CONOCIMIENTO = os.path.join(BASE, "conocimiento.json")
ARCHIVO_RESPUESTAS = os.path.join(BASE, "respuestas.json")
SALIDA = os.path.join(BASE, "dataset_entrenamiento.jsonl")


def cargar(ruta):
    if not os.path.exists(ruta):
        return []
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def main():
    comandos = cargar(ARCHIVO_CONOCIMIENTO)
    respuestas = cargar(ARCHIVO_RESPUESTAS)

    ejemplos = []

    for c in comandos:
        pregunta = c.get("pregunta", "").strip()
        accion = c.get("accion", "").strip()
        contenido = c.get("contenido", "")
        if not pregunta or not accion:
            continue
        salida = json.dumps({"intencion": accion, "contenido": contenido}, ensure_ascii=False)
        ejemplos.append({
            "instruction": "Clasifica la intención del siguiente comando y responde solo con JSON.",
            "input": pregunta,
            "output": salida,
        })

    for r in respuestas:
        pregunta = r.get("pregunta", "").strip()
        respuesta = r.get("respuesta", "").strip()
        if not pregunta or not respuesta:
            continue
        ejemplos.append({
            "instruction": "Responde la siguiente pregunta de forma natural, como lo haría Arché.",
            "input": pregunta,
            "output": respuesta,
        })

    with open(SALIDA, "w", encoding="utf-8") as f:
        for ej in ejemplos:
            f.write(json.dumps(ej, ensure_ascii=False) + "\n")

    print(f"Total de ejemplos exportados: {len(ejemplos)}")
    print(f"  - de comandos (conocimiento.json): {len(comandos)}")
    print(f"  - de conversación (respuestas.json): {len(respuestas)}")
    print(f"Guardado en: {SALIDA}")

    if len(ejemplos) < 200:
        print("\n⚠ Con menos de ~200 ejemplos, un fine-tuning todavía va a dar")
        print("  resultados pobres o inconsistentes. Recomiendo seguir juntando")
        print("  datos con el modo estudio antes de entrenar en serio.")
    elif len(ejemplos) < 500:
        print("\nTenés un volumen mínimo viable, pero más datos van a mejorar")
        print("bastante la calidad del resultado.")
    else:
        print("\nVolumen razonable para un primer intento de fine-tuning con LoRA.")


if __name__ == "__main__":
    main()