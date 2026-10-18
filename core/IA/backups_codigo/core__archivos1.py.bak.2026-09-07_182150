import os
import json
import time


# RUTAS


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE = os.path.join(BASE, "Database")

ARCHIVO_CACHE = os.path.join(DATABASE, "archivos.json")

if not os.path.exists(DATABASE):
    os.makedirs(DATABASE)

if not os.path.exists(ARCHIVO_CACHE):
    with open(ARCHIVO_CACHE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=4, ensure_ascii=False)


# CARPETAS A BUSCAR


USUARIO = os.path.expanduser("~")

CARPETAS = [

    os.path.join(USUARIO, "Desktop"),
    os.path.join(USUARIO, "Documents"),
    os.path.join(USUARIO, "Downloads"),
    os.path.join(USUARIO, "Pictures"),
    os.path.join(USUARIO, "Music"),
    os.path.join(USUARIO, "Videos"),

    os.path.join(USUARIO, "OneDrive"),
    os.path.join(USUARIO, "OneDrive", "Desktop"),
    os.path.join(USUARIO, "OneDrive", "Documents"),
    os.path.join(USUARIO, "OneDrive", "Downloads")

]


# CACHE


def cargar_cache():

    try:

        with open(ARCHIVO_CACHE, "r", encoding="utf-8") as f:

            return json.load(f)

    except:

        return {}


def guardar_cache(cache):

    with open(ARCHIVO_CACHE, "w", encoding="utf-8") as f:

        json.dump(cache, f, indent=4, ensure_ascii=False)


# BUSCAR


def buscar_archivo(nombre):

    nombre = nombre.lower().strip()

    cache = cargar_cache()

    # Primero revisar si ya lo conoce

    if nombre in cache:

        if os.path.exists(cache[nombre]):

            return [cache[nombre]]

    resultados = []

    for carpeta in CARPETAS:

        if not os.path.exists(carpeta):

            continue

        for raiz, _, archivos in os.walk(carpeta):

            for archivo in archivos:

                if nombre in archivo.lower():

                    ruta = os.path.join(raiz, archivo)

                    resultados.append(ruta)

    return resultados


# ABRIR


def abrir_archivo(nombre):

    resultados = buscar_archivo(nombre)

    if len(resultados) == 0:

        print("Arché: No encontré ese archivo.")

        return

    if len(resultados) == 1:

        ruta = resultados[0]

        cache = cargar_cache()

        cache[nombre.lower()] = ruta

        guardar_cache(cache)

        print("Arché: Abriendo archivo...")

        time.sleep(1)

        os.startfile(ruta)

        return

    print("\nArché: Encontré varios archivos:\n")

    for i, ruta in enumerate(resultados, start=1):

        print(f"{i}. {os.path.basename(ruta)}")

    try:

        opcion = int(input("\nNúmero: "))

        ruta = resultados[opcion - 1]

        cache = cargar_cache()

        cache[nombre.lower()] = ruta

        guardar_cache(cache)

        print("Arché: Abriendo archivo...")

        time.sleep(1)

        os.startfile(ruta)

    except:

        print("Arché: Opción inválida.")