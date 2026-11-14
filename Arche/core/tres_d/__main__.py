"""Abre el taller 3D sin arrancar todo Arché:   python -m core.tres_d   (desde la carpeta Arche)"""
import time

from . import servidor

ok, detalle = servidor.iniciar()
if not ok:
    raise SystemExit(f"No pude abrir el taller 3D: {detalle}")
print(f"Taller 3D abierto en {servidor.direccion()} (solo este PC). Ctrl+C para cerrarlo.")
servidor.abrir_navegador()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    servidor.detener()
