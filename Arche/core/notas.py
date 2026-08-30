import os
import time

from core.rutas import DATABASE

carpeta_notas = os.path.join(DATABASE, "Notas")

os.makedirs(carpeta_notas, exist_ok=True)

def crear_nota(nombre):

    nombre = nombre.strip().lower()
    ruta = os.path.join(carpeta_notas, f"{nombre}.txt")

    if os.path.exists(ruta):
        print("Arché: Esa nota ya existe.")
        return

    print("Arché: Escribe la nota.")
    print("Arché: Cuando termines escribe FIN en una línea nueva.\n")

    lineas = []

    while True:

        texto = input()

        if texto.upper() == "FIN":
            break

        lineas.append(texto)

    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(lineas))

    print(f"Arché: Nota '{nombre}' creada.")


def leer_nota(nombre):

    nombre = nombre.strip().lower()
    ruta = os.path.join(carpeta_notas, f"{nombre}.txt")

    if not os.path.exists(ruta):
        print("Arché: Esa nota no existe.")
        return

    print("=" * 40)
    print(nombre.upper())
    print("=" * 40)

    with open(ruta, "r", encoding="utf-8") as archivo:
        print(archivo.read())


def agregar_nota(nombre):

    nombre = nombre.strip().lower()
    ruta = os.path.join(carpeta_notas, f"{nombre}.txt")

    if not os.path.exists(ruta):
        print("Arché: Esa nota no existe.")
        return

    print("Arché: Escribe lo que deseas agregar.")
    print("Arché: Escribe FIN para terminar.\n")

    lineas = []

    while True:

        texto = input()

        if texto.upper() == "FIN":
            break

        lineas.append(texto)

    with open(ruta, "a", encoding="utf-8") as archivo:

        archivo.write("\n")
        archivo.write("\n".join(lineas))

    print("Arché: Nota actualizada.")


def eliminar_nota(nombre):

    nombre = nombre.strip().lower()
    ruta = os.path.join(carpeta_notas, f"{nombre}.txt")

    if not os.path.exists(ruta):
        print("Arché: Esa nota no existe.")
        return

    os.remove(ruta)

    print(f"Arché: Nota '{nombre}' eliminada.")


def abrir_nota(nombre):

    nombre = nombre.strip().lower()
    ruta = os.path.join(carpeta_notas, f"{nombre}.txt")

    if not os.path.exists(ruta):
        print("Arché: Esa nota no existe.")
        return

    print(f"Arché: Abriendo {nombre}...")
    time.sleep(0.5)

    os.startfile(ruta)


def listar_notas():

    archivos = sorted(os.listdir(carpeta_notas))

    if not archivos:
        print("Arché: No tienes notas.")
        return

    print("Arché: Estas son tus notas:\n")

    for archivo in archivos:

        if archivo.endswith(".txt"):
            print("-", archivo[:-4])