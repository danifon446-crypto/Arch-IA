"""
aplicar_parche_memoria_nube.py
------------------------------
Conecta core/memoria_nube.py (memoria en la nube, Fase 2) a main.py.
Hace 3 cambios pequeños y guarda una copia de main.py antes de tocar nada.

Uso (desde la carpeta Arche):   py aplicar_parche_memoria_nube.py
Se puede correr dos veces: si ya está puesto, no hace nada.
"""

import os
import shutil
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(AQUI, "main.py")

CAMBIOS = [
    # (texto que debe existir, texto nuevo que lo reemplaza, que hace)
    ("from core import compartir as red_arche",
     "from core import memoria_nube as memoria_nube_arche  # memoria en la nube (Supabase) + turnos sin PC\n"
     "from core import compartir as red_arche",
     "importar el módulo"),
    ("for _modulo in (mejora_arche,",
     "for _modulo in (memoria_nube_arche, mejora_arche,",
     "agregar sus comandos"),
    ("red_arche.iniciar()",
     "red_arche.iniciar()\n"
     "memoria_nube_arche.iniciar()             # sube/baja lo aprendido a tu Supabase en segundo plano",
     "arrancarlo al iniciar"),
]


def main():
    if not os.path.exists(os.path.join(AQUI, "core", "memoria_nube.py")):
        print("Falta core/memoria_nube.py. Cópialo primero a Arche/core/.")
        return 1
    with open(MAIN, "r", encoding="utf-8") as f:
        codigo = f.read()
    if "memoria_nube_arche" in codigo:
        print("main.py ya tiene la memoria en la nube. No cambié nada.")
        return 0
    for viejo, _nuevo, que in CAMBIOS:
        if codigo.count(viejo) != 1:
            print(f"No encontré dónde {que} (busqué: {viejo!r}). No cambié nada.")
            print("Mándame tu main.py y lo ajusto.")
            return 1
    copia = os.path.join(AQUI, f"main_antes_memoria_nube_{datetime.now():%Y%m%d_%H%M%S}.py")
    shutil.copy2(MAIN, copia)
    for viejo, nuevo, _que in CAMBIOS:
        codigo = codigo.replace(viejo, nuevo, 1)
    compile(codigo, MAIN, "exec")   # si algo quedara mal escrito, falla aquí y no se guarda
    with open(MAIN, "w", encoding="utf-8") as f:
        f.write(codigo)
    print(f"Listo. main.py ya usa la memoria en la nube (copia de seguridad: {os.path.basename(copia)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
