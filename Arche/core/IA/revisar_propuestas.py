"""
revisar_propuestas.py
------------------------
Ubicacion: Arche/core/IA/revisar_propuestas.py

Te muestra cada propuesta pendiente generada por propuestas.py, con
el que/por que/como completo, y pide aprobacion explicita [s/n] antes
de tocar un solo archivo.

Flujo al aprobar una propuesta:
    1. Backup del archivo editable con timestamp (nunca se sobreescribe
       un backup viejo).
    2. El cambio se arma primero en memoria (el diccionario completo,
       con la entrada nueva agregada).
    3. Smoke test: se valida que el codigo generado sea sintacticamente
       valido (ast.parse) ANTES de escribir nada al archivo real.
    4. Si pasa, se reemplaza el archivo real. Si algo falla en el
       camino, se aborta y se restaura el backup automaticamente.
    5. Se registra el resultado en el log inmutable (propuestas_log.jsonl).

Uso:
    python core/IA/revisar_propuestas.py
"""

import ast
import json
import shutil
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
ARCHIVO_PROPUESTAS = BASE / "propuestas_pendientes.json"
ARCHIVO_LOG = BASE / "propuestas_log.jsonl"
ARCHIVO_EDITABLE = BASE / "preguntas_frecuentes.py"
CARPETA_BACKUPS = BASE / "backups_autoconocimiento"


def cargar_propuestas():
    if not ARCHIVO_PROPUESTAS.exists():
        return []
    with open(ARCHIVO_PROPUESTAS, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_propuestas(propuestas):
    with open(ARCHIVO_PROPUESTAS, "w", encoding="utf-8") as f:
        json.dump(propuestas, f, ensure_ascii=False, indent=2)


def _log_inmutable(evento):
    evento["timestamp"] = datetime.now().isoformat()
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def hacer_backup():
    CARPETA_BACKUPS.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino = CARPETA_BACKUPS / f"preguntas_frecuentes.py.bak.{marca}"
    shutil.copy2(ARCHIVO_EDITABLE, destino)
    return destino


def leer_diccionario_actual():
    """Lee PREGUNTAS_FRECUENTES ejecutando el archivo en un espacio de
    nombres aislado (no via import normal, para no depender de que el
    resto del paquete 'core' este en sys.path)."""
    codigo = ARCHIVO_EDITABLE.read_text(encoding="utf-8")
    espacio = {}
    exec(compile(codigo, str(ARCHIVO_EDITABLE), "exec"), espacio)
    return espacio.get("PREGUNTAS_FRECUENTES", {})


def generar_codigo_diccionario(diccionario):
    lineas = [
        '"""',
        "preguntas_frecuentes.py",
        "-------------------------",
        "Generado/editado por el sistema de propuestas de Arche.",
        "Cada entrada fue aprobada explicitamente por vos. Ver",
        "propuestas_log.jsonl para el historial completo de cambios.",
        '"""',
        "",
        "PREGUNTAS_FRECUENTES = {",
    ]
    for pregunta, respuesta in diccionario.items():
        lineas.append(f"    {pregunta!r}: {respuesta!r},")
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def validar_sintaxis(codigo, nombre_archivo):
    try:
        ast.parse(codigo, filename=nombre_archivo)
        return True, None
    except SyntaxError as e:
        return False, str(e)


def aplicar_propuesta(propuesta):
    diccionario_actual = leer_diccionario_actual()

    if propuesta["pregunta"] in diccionario_actual:
        print("Arché: Esa pregunta ya está en el diccionario, no hay nada que aplicar.")
        return False

    diccionario_nuevo = dict(diccionario_actual)
    diccionario_nuevo[propuesta["pregunta"]] = propuesta["respuesta"]

    codigo_nuevo = generar_codigo_diccionario(diccionario_nuevo)

    ok, error = validar_sintaxis(codigo_nuevo, str(ARCHIVO_EDITABLE))
    if not ok:
        print(f"Arché: El cambio propuesto no genera código válido, lo aborto sin tocar nada. Error: {error}")
        _log_inmutable({"tipo": "propuesta_fallida", "id": propuesta["id"], "error": error})
        return False

    backup_path = hacer_backup()

    try:
        ARCHIVO_EDITABLE.write_text(codigo_nuevo, encoding="utf-8")
    except Exception as e:
        print(f"Arché: Error al escribir el archivo, restaurando backup automáticamente. ({e})")
        shutil.copy2(backup_path, ARCHIVO_EDITABLE)
        _log_inmutable({"tipo": "propuesta_fallida_escritura", "id": propuesta["id"], "error": str(e)})
        return False

    print(f"Arché: Listo, agregué la pregunta a {ARCHIVO_EDITABLE.name}. Backup guardado en {backup_path.name}.")
    _log_inmutable({
        "tipo": "propuesta_aplicada",
        "id": propuesta["id"],
        "pregunta": propuesta["pregunta"],
        "backup": backup_path.name,
    })
    return True


def main():
    propuestas = cargar_propuestas()
    pendientes = [p for p in propuestas if p["estado"] == "pendiente"]

    if not pendientes:
        print("No hay propuestas pendientes para revisar.")
        return

    for propuesta in pendientes:
        print("\n" + "=" * 60)
        print(f"Propuesta {propuesta['id']}")
        print("=" * 60)
        print(f"QUÉ:     {propuesta['que']}")
        print(f"POR QUÉ: {propuesta['por_que']}")
        print(f"CÓMO:    {propuesta['como']}")
        print(f"\nPregunta:  {propuesta['pregunta']}")
        print(f"Respuesta: {propuesta['respuesta'][:200]}")
        print(f"Repeticiones registradas: {propuesta['veces_usada']}")

        resp = input("\n¿Aprobás esta propuesta? [s/n]: ").strip().lower()

        if resp == "s":
            aplicada = aplicar_propuesta(propuesta)
            propuesta["estado"] = "aplicada" if aplicada else "fallida"
        else:
            propuesta["estado"] = "rechazada"
            _log_inmutable({"tipo": "propuesta_rechazada", "id": propuesta["id"]})
            print("Arché: Entendido, la descarto.")

    guardar_propuestas(propuestas)


if __name__ == "__main__":
    main()