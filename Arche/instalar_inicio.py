"""
instalar_inicio.py
------------------
Ubicacion: Arche/instalar_inicio.py

Hace que Arché arranque sola, en segundo plano, cada vez que prendes el PC.

    python instalar_inicio.py          -> activar
    python instalar_inicio.py quitar   -> desactivar

(Crea o borra Arche.bat en la carpeta Inicio de Windows; es el mismo archivo
que usa el interruptor «arranque» del celular, así que los dos quedan de acuerdo.)
"""

import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
os.chdir(AQUI)

from core.interfaz import remoto  # noqa: E402

if __name__ == "__main__":
    quitar = len(sys.argv) > 1 and sys.argv[1].lower() in ("quitar", "no", "off", "desactivar")
    if remoto.fijar_arranque(not quitar):
        if quitar:
            print("Listo: Arché ya no arranca sola con Windows.")
        else:
            print("Listo: Arché va a arrancar sola, en segundo plano, al iniciar sesión en Windows.")
            print("Para probar ya mismo sin reiniciar: doble clic a arche_fondo.pyw")
    else:
        print("No pude cambiar el arranque (¿estás en Windows?).")
