"""
revisar_cambios_codigo.py
---------------------------
Ubicacion: Arche/core/IA/revisar_cambios_codigo.py

Muestra cada propuesta de cambio de código pendiente (generada por
proponer_cambio_codigo.py) como un diff real -- no solo el resumen de
qué/por qué/cómo -- y pide aprobación explícita [s/n] antes de tocar un
solo archivo.

Mismo flujo de seguridad que revisar_propuestas.py, generalizado a
cualquier archivo:
    1. Backup del archivo completo, con timestamp (nunca se sobreescribe
       un backup viejo).
    2. El cambio se arma primero en memoria.
    3. Si el archivo es .py, se valida que el resultado sea sintácticamente
       válido (ast.parse) ANTES de escribir nada al archivo real.
    4. Si algo falla en el camino, se aborta y NO se toca el archivo real
       (o se restaura el backup si ya se alcanzó a escribir).
    5. Se registra el resultado en el log inmutable (cambios_codigo_log.jsonl).

Uso:
    python core/IA/revisar_cambios_codigo.py
"""

import ast
import difflib
import json
import shutil
from pathlib import Path
from datetime import datetime

RAIZ_APP = Path(__file__).resolve().parents[2]
BASE = Path(__file__).parent

ARCHIVO_PENDIENTES = BASE / "cambios_codigo_pendientes.json"
ARCHIVO_LOG = BASE / "cambios_codigo_log.jsonl"
CARPETA_BACKUPS = BASE / "backups_codigo"


def _cargar_pendientes():
    if not ARCHIVO_PENDIENTES.exists():
        return []
    try:
        return json.loads(ARCHIVO_PENDIENTES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _guardar_pendientes(props):
    ARCHIVO_PENDIENTES.write_text(
        json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _log_inmutable(evento):
    evento["timestamp"] = datetime.now().isoformat()
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _hacer_backup(ruta_real: Path, archivo_norm: str):
    CARPETA_BACKUPS.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    nombre_seguro = archivo_norm.replace("/", "__")
    destino = CARPETA_BACKUPS / f"{nombre_seguro}.bak.{marca}"
    if ruta_real.exists():
        shutil.copy2(ruta_real, destino)
    return destino


def _calcular_contenido_nuevo(propuesta, contenido_actual):
    if propuesta["buscar"]:
        return contenido_actual.replace(propuesta["buscar"], propuesta["reemplazar"], 1)
    return propuesta["reemplazar"]  # archivo nuevo


def _diff(contenido_actual, contenido_nuevo, archivo):
    return "\n".join(difflib.unified_diff(
        contenido_actual.splitlines(),
        contenido_nuevo.splitlines(),
        fromfile=f"{archivo} (actual)",
        tofile=f"{archivo} (propuesto)",
        lineterm="",
    ))


def aplicar_propuesta(propuesta):
    ruta = RAIZ_APP / propuesta["archivo"]
    contenido_actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""

    if propuesta["buscar"] and contenido_actual.count(propuesta["buscar"]) != 1:
        print("Arché: El archivo cambió desde que se generó la propuesta "
              "(el fragmento ya no es único o ya no existe). Aborto sin tocar nada.")
        _log_inmutable({"tipo": "cambio_codigo_fallido", "id": propuesta["id"], "error": "fragmento_no_coincide"})
        return False

    contenido_nuevo = _calcular_contenido_nuevo(propuesta, contenido_actual)

    if ruta.suffix == ".py":
        try:
            ast.parse(contenido_nuevo, filename=str(ruta))
        except SyntaxError as e:
            print(f"Arché: El cambio no genera código Python válido, lo aborto sin tocar nada. Error: {e}")
            _log_inmutable({"tipo": "cambio_codigo_fallido", "id": propuesta["id"], "error": str(e)})
            return False

    backup_path = _hacer_backup(ruta, propuesta["archivo"])

    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido_nuevo, encoding="utf-8")
    except Exception as e:
        print(f"Arché: Error al escribir el archivo, restaurando backup automáticamente. ({e})")
        if backup_path.exists():
            shutil.copy2(backup_path, ruta)
        _log_inmutable({"tipo": "cambio_codigo_fallido_escritura", "id": propuesta["id"], "error": str(e)})
        return False

    print(f"Arché: Listo, apliqué el cambio en {propuesta['archivo']}. Backup guardado en {backup_path.name}.")
    _log_inmutable({
        "tipo": "cambio_codigo_aplicado",
        "id": propuesta["id"],
        "archivo": propuesta["archivo"],
        "backup": backup_path.name,
    })
    return True


def main():
    propuestas = _cargar_pendientes()
    pendientes = [p for p in propuestas if p["estado"] == "pendiente"]

    if not pendientes:
        print("No hay propuestas de código pendientes para revisar.")
        return

    for propuesta in pendientes:
        ruta = RAIZ_APP / propuesta["archivo"]
        contenido_actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
        contenido_nuevo = _calcular_contenido_nuevo(propuesta, contenido_actual)

        print("\n" + "=" * 60)
        print(f"Propuesta {propuesta['id']}  (origen: {propuesta['origen']})")
        print("=" * 60)
        print(f"ARCHIVO:  {propuesta['archivo']}")
        print(f"QUÉ:      {propuesta['que']}")
        print(f"POR QUÉ:  {propuesta['por_que']}")
        print(f"CÓMO:     {propuesta['como']}")
        print("\nDIFF:")
        diff_texto = _diff(contenido_actual, contenido_nuevo, propuesta["archivo"])
        print(diff_texto if diff_texto else "(archivo nuevo, sin contenido previo)")

        resp = input("\n¿Aprobás este cambio? [s/n]: ").strip().lower()

        if resp == "s":
            aplicada = aplicar_propuesta(propuesta)
            propuesta["estado"] = "aplicada" if aplicada else "fallida"
        else:
            propuesta["estado"] = "rechazada"
            _log_inmutable({"tipo": "cambio_codigo_rechazado", "id": propuesta["id"]})
            print("Arché: Entendido, la descarto.")

    _guardar_pendientes(propuestas)


if __name__ == "__main__":
    main()