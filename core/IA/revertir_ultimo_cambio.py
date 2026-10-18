"""
revertir_ultimo_cambio.py
----------------------------
Ubicacion: Arche/core/IA/revertir_ultimo_cambio.py

Restaura preguntas_frecuentes.py al backup mas reciente. Un solo
comando, sin preguntas, para cuando algo salio mal despues de aprobar
una propuesta.

Uso:
    python core/IA/revertir_ultimo_cambio.py
"""

import shutil
from pathlib import Path

BASE = Path(__file__).parent
ARCHIVO_EDITABLE = BASE / "preguntas_frecuentes.py"
CARPETA_BACKUPS = BASE / "backups_autoconocimiento"


def main():
    if not CARPETA_BACKUPS.exists():
        print("No hay backups disponibles todavía.")
        return

    backups = sorted(CARPETA_BACKUPS.glob("preguntas_frecuentes.py.bak.*"))
    if not backups:
        print("No hay backups disponibles todavía.")
        return

    ultimo = backups[-1]
    shutil.copy2(ultimo, ARCHIVO_EDITABLE)
    print(f"Arché: Restauré {ARCHIVO_EDITABLE.name} desde el backup {ultimo.name}.")


if __name__ == "__main__":
    main()