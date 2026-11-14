"""
limpiar_repo.py
---------------
Saca del proyecto los archivos que ya no se usan (respaldos viejos, copias
duplicadas, salidas de búsquedas). Desde la carpeta Arche:

    python limpiar_repo.py

NO BORRA NADA: te muestra la lista, te pregunta, y si dices que sí los MUEVE a
la carpeta _papelera_arche/ (al lado de la carpeta Arche), por si quieres
recuperar algo. Cuando estés seguro, borra esa carpeta a mano.

Por qué conviene: tu repositorio de GitHub es público y cada respaldo de
main.py es otra copia entera del código; además confunden a la autorevisión
de Arché (revisa archivos que ya no corren).
"""

import glob
import os
import shutil
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))        # .../Arche
RAIZ = os.path.dirname(AQUI)                              # carpeta del repositorio

# (patrón relativo a la raíz del repo, por qué sobra)
SOBRAN = [
    ("Arche/main_antes_*.py", "respaldo viejo de main.py"),
    ("Arche/respaldo_antes_*", "respaldo viejo (carpeta)"),
    ("Arche/copia(seguridad).py", "copia vieja suelta"),
    ("Arche/busqueda.txt", "salida de una búsqueda (1,4 MB), no es código"),
    ("Arche_completo.zip", "zip de una instalación anterior"),
    ("arche_ajedrez.py", "copia idéntica de Arche/arche_ajedrez/arche_ajedrez.py"),
    ("Arche/nube", "copia mal ubicada: el entrenador que corre GitHub es nube/ (en la raíz)"),
    ("Arche/core/programas.py", "reemplazado por core/programaV2.py (nadie lo importa)"),
    ("Arche/core/prueba.py", "prueba suelta rota (usa una función que no existe)"),
    ("__pycache__", "caché de Python"),
]


def encontrar():
    hallados = []
    for patron, motivo in SOBRAN:
        for ruta in sorted(glob.glob(os.path.join(RAIZ, *patron.split("/")))):
            hallados.append((ruta, motivo))
    return hallados


def main():
    # el entrenador mal ubicado solo se quita si el bueno (raíz) ya está al día
    hallados = encontrar()
    mal = os.path.join(RAIZ, "Arche", "nube", "entrenador", "ciclo.py")
    bien = os.path.join(RAIZ, "nube", "entrenador", "ciclo.py")
    if os.path.exists(mal) and os.path.exists(bien):
        if open(mal, encoding="utf-8").read() != open(bien, encoding="utf-8").read():
            print("OJO: Arche/nube/entrenador es distinto de nube/entrenador (el que usa GitHub).")
            print("     Copia primero los archivos nuevos de nube/entrenador que venían en el zip. No toco Arche/nube.\n")
            hallados = [(r, m) for r, m in hallados if os.path.join("Arche", "nube") not in r]
    if not hallados:
        print("No hay nada que limpiar.")
        return
    print("Esto ya no se usa:\n")
    for ruta, motivo in hallados:
        print(f"  {os.path.relpath(ruta, RAIZ):55s} {motivo}")
    if "--si" not in sys.argv:
        try:
            r = input("\n¿Los muevo a _papelera_arche/? [s/n]: ").strip().lower()
        except EOFError:
            r = "n"
        if r not in ("s", "si", "sí"):
            print("No moví nada.")
            return
    papelera = os.path.join(RAIZ, "_papelera_arche", time.strftime("%Y%m%d_%H%M%S"))
    movidos = 0
    for ruta, _ in hallados:
        destino = os.path.join(papelera, os.path.relpath(ruta, RAIZ))
        try:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.move(ruta, destino)
            movidos += 1
        except OSError as e:
            print(f"  no pude mover {os.path.relpath(ruta, RAIZ)}: {e}")
    print(f"\nListo: moví {movidos} a {os.path.relpath(papelera, RAIZ)}.")
    print("Corre «python prueba_mejoras.py» y abre Arché; si todo anda, sube los cambios a GitHub.")


if __name__ == "__main__":
    main()
