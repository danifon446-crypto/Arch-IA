"""
entornos
--------
Cada archivo de esta carpeta es un mundo donde el agente puede actuar y se
registra solo al importarse. Para sumar uno nuevo (otro juego, el navegador,
un robot), crea el archivo, define una subclase de Entorno y registrala; luego
agrega su nombre a IMPORTAR.
"""

import importlib

IMPORTAR = ("simulado", "minecraft")


def cargar_todos():
    errores = {}
    for nombre in IMPORTAR:
        try:
            importlib.import_module(f"core.agente.entornos.{nombre}")
        except Exception as e:           # un entorno roto no debe tumbar a los demas
            errores[nombre] = str(e)
    return errores
