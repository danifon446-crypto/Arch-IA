"""
aplicar_parche_red.py
---------------------
Conecta core/compartir.py (red de aprendizaje) a main.py. Hace 3 cambios
pequeños y guarda una copia de main.py antes de tocar nada.

Uso (desde la carpeta Arche):   python aplicar_parche_red.py
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
    ("from core import mapa_mental as mapa_mental_arche",
     "from core import compartir as red_arche              # red de aprendizaje entre varios PC\n"
     "from core import mapa_mental as mapa_mental_arche",
     "importar el módulo"),
    ("cerebro_nube, aprender_de_nube):",
     "cerebro_nube, aprender_de_nube, red_arche):",
     "agregar sus comandos"),
    ("whatsapp_arche.arrancar_si_corresponde()",
     "whatsapp_arche.arrancar_si_corresponde()\n"
     "red_arche.iniciar()                      # sincroniza con la red de aprendizaje en segundo plano",
     "arrancarlo al iniciar"),
]


def main():
    if not os.path.exists(os.path.join(AQUI, "core", "compartir.py")):
        print("Falta core/compartir.py. Cópialo primero a Arche/core/.")
        return 1
    with open(MAIN, "r", encoding="utf-8") as f:
        codigo = f.read()
    if "red_arche" in codigo:
        print("main.py ya tiene la red de aprendizaje. No cambié nada.")
        return 0
    for viejo, _nuevo, que in CAMBIOS:
        if codigo.count(viejo) != 1:
            print(f"No encontré dónde {que} (busqué: {viejo!r}). No cambié nada.")
            print("Hazlo a mano siguiendo las instrucciones, o mándame tu main.py.")
            return 1
    copia = os.path.join(AQUI, f"main_antes_red_{datetime.now():%Y%m%d_%H%M%S}.py")
    shutil.copy2(MAIN, copia)
    for viejo, nuevo, _que in CAMBIOS:
        codigo = codigo.replace(viejo, nuevo, 1)
    compile(codigo, MAIN, "exec")   # si algo quedara mal escrito, falla aquí y no se guarda
    with open(MAIN, "w", encoding="utf-8") as f:
        f.write(codigo)
    print(f"Listo. main.py ya usa la red de aprendizaje (copia de seguridad: {os.path.basename(copia)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())