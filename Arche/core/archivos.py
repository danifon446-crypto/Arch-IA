import os
import json
import threading
import time
from datetime import datetime
from core.rutas import DATABASE

archivo_indice = os.path.join(
    DATABASE,
    "indice_archivos.json"
)

CARPETAS = []

USUARIO = os.path.expanduser("~")

RUTAS = [
    "Desktop",
    "Documents",
    "Downloads",
    "Pictures",
    "Music",
    "Videos"
]

for carpeta in RUTAS:
    ruta = os.path.join(USUARIO, carpeta)
    if os.path.exists(ruta):
        CARPETAS.append(ruta)
onedrive = os.path.join(USUARIO, "OneDrive")
if os.path.exists(onedrive):
    CARPETAS.append(onedrive)
    for carpeta in RUTAS:
        ruta = os.path.join(onedrive, carpeta)
        if os.path.exists(ruta):
            CARPETAS.append(ruta)


def guardar_indice(indice):
    with open(
        archivo_indice,
        "w",
        encoding="utf-8"
    ) as archivo:
        json.dump(
            indice,
            archivo,
            indent=4,
            ensure_ascii=False
        )


def cargar_indice():
    if not os.path.exists(archivo_indice):
        return []
    try:
        with open(
            archivo_indice,
            "r",
            encoding="utf-8"
        ) as archivo:
            return json.load(archivo)
    except:
        return []


# INDEXAR ARCHIVOS


def indexar_archivos():
    indice = []
    total = 0
    inicio = time.time()
    for pasta in CARPETAS:
        for raiz, carpetas, archivos in os.walk(pasta):
            # Guardar carpetas
            for carpeta in carpetas:
                ruta = os.path.join(raiz, carpeta)
                try:
                    datos = {
                        "nombre": carpeta.lower(),
                        "ruta": ruta,
                        "tipo": "carpeta",
                        "extension": "",
                        "peso": 0,
                        "modificado": datetime.fromtimestamp(
                            os.path.getmtime(ruta)
                        ).strftime("%Y-%m-%d %H:%M")
                    }
                    indice.append(datos)
                    total += 1
                except:
                    pass
            # Guardar archivos
            for archivo in archivos:
                ruta = os.path.join(raiz, archivo)
                try:
                    nombre, extension = os.path.splitext(archivo)
                    datos = {
                        "nombre": nombre.lower(),
                        "ruta": ruta,
                        "tipo": "archivo",
                        "extension": extension.lower(),
                        "peso": os.path.getsize(ruta),
                        "modificado": datetime.fromtimestamp(
                            os.path.getmtime(ruta)
                        ).strftime("%Y-%m-%d %H:%M")
                    }
                    indice.append(datos)
                    total += 1
                except:
                    pass
    guardar_indice(indice)
    segundos = round(time.time() - inicio, 2)
    print()
    print("=" * 40)
    print("Arché: Indexación finalizada.")
    print(f"Arché: {total} elementos indexados.")
    print(f"Arché: Tiempo: {segundos} segundos.")
    print("=" * 40)


# INDEXAR EN SEGUNDO PLANO


def actualizar_indice():
    hilo = threading.Thread(
        target=indexar_archivos,
        daemon=True
    )
    hilo.start()
    print("Arché: Actualizando índice en segundo plano...")


# BUSCAR EN EL ÍNDICE


def buscar(nombre):
    nombre = nombre.lower().strip()
    indice = cargar_indice()
    resultados = []
    for elemento in indice:
        if nombre in elemento["nombre"]:
            resultados.append(elemento)
    resultados.sort(key=lambda x: len(x["nombre"]))
    return resultados



# MOSTRAR RESULTADOS


def mostrar_resultados(resultados):
    if not resultados:
        print("Arché: No encontré resultados.")
        return
    print("\nArché: Encontré estos resultados:\n")
    for i, r in enumerate(resultados, start=1):
        print(f"{i}. {os.path.basename(r['ruta'])}")
        print(f"   Tipo : {r['tipo']}")
        print(f"   Ruta : {r['ruta']}")
        print()



# ABRIR


def abrir_resultado(resultado):
    try:
        os.startfile(resultado["ruta"])
        print(f"Arché: Abriendo {os.path.basename(resultado['ruta'])}...")
    except:
        print("Arché: No pude abrir ese elemento.")



# BUSCAR Y ABRIR


def buscar_y_abrir(nombre):
    resultados = buscar(nombre)
    if len(resultados) == 0:
        print("Arché: No encontré ese archivo.")
        return
    if len(resultados) == 1:
        abrir_resultado(resultados[0])
        return
    mostrar_resultados(resultados)
    try:
        opcion = int(input("Número: "))
        abrir_resultado(resultados[opcion - 1])
    except:
        print("Arché: Opción inválida.")