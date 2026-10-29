"""
instalar_mejoras.py
-------------------
Instala las mejoras de las redes SIN pisar los cambios que hayas hecho
a tus archivos después de la última vez que subiste Arché a GitHub.

Por cada archivo:
  - si no lo tocaste desde entonces -> pone la versión nueva;
  - si lo tocaste -> MEZCLA tus cambios con los nuevos (con git);
  - si la mezcla choca (los dos cambiaron las mismas líneas) -> NO toca
    tu archivo; deja la versión nueva al lado como <archivo>.nuevo y te
    avisa.
Antes de cambiar cualquier cosa guarda una copia en
Arche\\_respaldo_mejoras_<fecha>\\.

Uso: descomprime el zip dentro de la carpeta que contiene a Arche\\ y corre
    python instalar_mejoras.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
MEJORAS = os.path.join(AQUI, "_mejoras")
NUEVO = os.path.join(MEJORAS, "nuevo")
BASE = os.path.join(MEJORAS, "base")


def _leer(ruta):
    with open(ruta, "rb") as f:
        return f.read()


def _sin_crlf(datos):
    return datos.replace(b"\r\n", b"\n")


def _escribir(ruta, datos, crlf):
    if crlf:
        datos = _sin_crlf(datos).replace(b"\n", b"\r\n")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "wb") as f:
        f.write(datos)


def _hay_git():
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _mezclar(actual, base, nuevo):
    """3-way merge con git. Devuelve (bytes_mezclados, sin_conflictos)."""
    with tempfile.TemporaryDirectory() as tmp:
        rutas = []
        for nombre, datos in (("actual", actual), ("base", base), ("nuevo", nuevo)):
            r = os.path.join(tmp, nombre)
            with open(r, "wb") as f:
                f.write(_sin_crlf(datos))
            rutas.append(r)
        p = subprocess.run(["git", "merge-file", "-p", "-L", "tuyo", "-L", "base", "-L", "nuevo", *rutas],
                           capture_output=True)
        return p.stdout, p.returncode == 0


def main():
    if not os.path.isdir(os.path.join(AQUI, "Arche")):
        print("No encuentro la carpeta Arche junto a este archivo. Descomprime el zip en la carpeta "
              "que CONTIENE a Arche (ej. C:\\Users\\danif\\Downloads\\proyectos\\Arché) y vuelve a correrlo.")
        return 1

    archivos = []
    for raiz, _, nombres in os.walk(NUEVO):
        for n in nombres:
            archivos.append(os.path.relpath(os.path.join(raiz, n), NUEVO))
    archivos.sort()

    sello = time.strftime("%Y%m%d_%H%M%S")
    respaldo = os.path.join(AQUI, "Arche", f"_respaldo_mejoras_{sello}")
    git = _hay_git()
    nuevos, reemplazados, mezclados, iguales, choques = [], [], [], [], []

    for rel in archivos:
        destino = os.path.join(AQUI, rel)
        nuevo = _leer(os.path.join(NUEVO, rel))
        ruta_base = os.path.join(BASE, rel)

        if not os.path.exists(destino):
            _escribir(destino, nuevo, crlf=False)
            nuevos.append(rel)
            continue

        actual = _leer(destino)
        crlf = b"\r\n" in actual
        if _sin_crlf(actual) == _sin_crlf(nuevo):
            iguales.append(rel)
            continue

        os.makedirs(os.path.dirname(os.path.join(respaldo, rel)), exist_ok=True)
        shutil.copy2(destino, os.path.join(respaldo, rel))

        base = _leer(ruta_base) if os.path.exists(ruta_base) else None
        if base is not None and _sin_crlf(actual) == _sin_crlf(base):
            _escribir(destino, nuevo, crlf)
            reemplazados.append(rel)
            continue

        if base is not None and git:
            mezcla, limpio = _mezclar(actual, base, nuevo)
            if limpio:
                _escribir(destino, mezcla, crlf)
                mezclados.append(rel)
                continue

        _escribir(destino + ".nuevo", nuevo, crlf)
        choques.append(rel)

    print("\n=== Instalación de mejoras ===")
    for titulo, lista in (("Nuevos", nuevos), ("Actualizados", reemplazados),
                          ("Mezclados con tus cambios", mezclados), ("Ya estaban al día", iguales)):
        if lista:
            print(f"\n{titulo} ({len(lista)}):")
            for rel in lista:
                print(f"   {rel}")
    if reemplazados or mezclados or choques:
        print(f"\nCopia de tus archivos anteriores: {respaldo}")
    if choques:
        print(f"\n⚠️  NO pude mezclar solo ({len(choques)}). Tu archivo quedó igual y la versión nueva quedó "
              f"al lado como .nuevo:")
        for rel in choques:
            print(f"   {rel}  ->  {rel}.nuevo")
        if not git:
            print("   (No encontré git instalado; con git se mezclan solos la mayoría.)")
        print("   Pásale ambos archivos a Claude y te los une.")
        return 2
    print("\nListo. Sigue con el PASO 2 de GUIA_MEJORAS_REDES.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
