"""
revertir_cambio_codigo.py
---------------------------
Ubicacion: Arche/core/IA/revertir_cambio_codigo.py

Restaura un archivo modificado por revisar_cambios_codigo.py a su
backup mas reciente. A diferencia de revertir_ultimo_cambio.py (que
solo maneja preguntas_frecuentes.py), este acepta cualquier archivo,
porque ahora el radio de accion es el proyecto entero.

Uso:
    python core/IA/revertir_cambio_codigo.py                     (lista archivos con backups)
    python core/IA/revertir_cambio_codigo.py <ruta/relativa.py>   (revierte ese archivo)
"""

import shutil
import sys
from pathlib import Path

RAIZ_APP = Path(__file__).resolve().parents[2]
BASE = Path(__file__).parent
CARPETA_BACKUPS = BASE / "backups_codigo"


def _archivos_con_backup():
    if not CARPETA_BACKUPS.exists():
        return {}
    mapa = {}
    for backup in CARPETA_BACKUPS.glob("*.bak.*"):
        nombre_seguro = backup.name.split(".bak.")[0]
        archivo_norm = nombre_seguro.replace("__", "/")
        mapa.setdefault(archivo_norm, []).append(backup)
    for archivo in mapa:
        mapa[archivo].sort()  # el timestamp en el nombre ordena cronológicamente
    return mapa


def revertir(archivo_norm: str):
    mapa = _archivos_con_backup()
    if archivo_norm not in mapa:
        print(f"No encontré backups para '{archivo_norm}'.")
        return False

    ultimo = mapa[archivo_norm][-1]
    destino = RAIZ_APP / archivo_norm
    shutil.copy2(ultimo, destino)
    print(f"Arché: Restauré {archivo_norm} desde el backup {ultimo.name}.")
    return True


def main():
    mapa = _archivos_con_backup()
    if not mapa:
        print("No hay backups de código disponibles todavía.")
        return

    if len(sys.argv) < 2:
        print("Archivos con backups disponibles:")
        for archivo in sorted(mapa):
            print(f"  • {archivo}  ({len(mapa[archivo])} backup(s))")
        print("\nUso: python core/IA/revertir_cambio_codigo.py <archivo>")
        return

    revertir(sys.argv[1].replace("\\", "/"))


if __name__ == "__main__":
    main()