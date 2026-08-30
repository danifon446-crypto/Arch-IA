import os
import json

from datetime import datetime
from core.rutas import DATABASE

archivo_recordatorios = os.path.join(
    DATABASE,
    "recordatorios.json"
)
if not os.path.exists(archivo_recordatorios):
    with open(
        archivo_recordatorios,
        "w",
        encoding="utf-8"
    ) as archivo:
        json.dump(
            [],
            archivo,
            indent=4,
            ensure_ascii=False
        )

if not os.path.exists(archivo_recordatorios):
    with open(archivo_recordatorios, "w", encoding="utf-8") as archivo:
        json.dump([], archivo, indent=4, ensure_ascii=False)

def cargar_recordatorios():
    try:
        with open(archivo_recordatorios, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except:
        return []

def guardar_recordatorios(recordatorios):
    with open(archivo_recordatorios, "w", encoding="utf-8") as archivo:
        json.dump(recordatorios, archivo, indent=4, ensure_ascii=False)

def crear_recordatorio(texto=None):
    if texto:
        titulo = texto.strip()
    else:
        titulo = input("Arché: ¿Qué debo recordarte?\nTú: ").strip()
    fecha = input("Arché: Fecha (AAAA-MM-DD):\nTú: ").strip()
    hora = input("Arché: Hora (HH:MM):\nTú: ").strip()
    prioridad = input(
        "Arché: Prioridad (baja/media/alta):\nTú: "
    ).lower().strip()
    if prioridad not in ["baja", "media", "alta"]:
        prioridad = "media"
    recordatorios = cargar_recordatorios()
    recordatorios.append({
        "titulo": titulo,
        "fecha": fecha,
        "hora": hora,
        "prioridad": prioridad,
        "estado": "pendiente"
    })
    guardar_recordatorios(recordatorios)
    print("Arché: Recordatorio guardado.")

def mostrar_recordatorios():
    recordatorios = cargar_recordatorios()
    if not recordatorios:
        print("Arché: No tienes recordatorios.")
        return
    print("=" * 50)
    print("        RECORDATORIOS")
    print("=" * 50)
    for i, r in enumerate(recordatorios, start=1):
        print(f"\n{i}. {r['titulo']}")
        print(f"   Fecha      : {r['fecha']}")
        print(f"   Hora       : {r['hora']}")
        print(f"   Prioridad  : {r['prioridad']}")
        print(f"   Estado     : {r['estado']}")

def eliminar_recordatorio():
    recordatorios = cargar_recordatorios()
    if not recordatorios:
        print("Arché: No hay recordatorios.")
        return
    mostrar_recordatorios()
    try:
        numero = int(
            input("\nNúmero del recordatorio a eliminar:\nTú: ")
        )
        if numero < 1 or numero > len(recordatorios):
            print("Arché: Número inválido.")
            return
        eliminado = recordatorios.pop(numero - 1)
        guardar_recordatorios(recordatorios)
        print(
            f"Arché: Eliminé '{eliminado['titulo']}'."
        )
    except:
        print("Arché: Entrada inválida.")

def completar_recordatorio():
    recordatorios = cargar_recordatorios()
    if not recordatorios:
        print("Arché: No hay recordatorios.")
        return
    mostrar_recordatorios()
    try:
        numero = int(
            input(
                "\nNúmero del recordatorio completado:\nTú: "
            )
        )
        if numero < 1 or numero > len(recordatorios):
            print("Arché: Número inválido.")
            return
        recordatorios[numero - 1]["estado"] = "completado"
        guardar_recordatorios(recordatorios)
        print("Arché: Recordatorio completado.")
    except:
        print("Arché: Entrada inválida.")

def revisar_recordatorios():
    ahora = datetime.now()
    recordatorios = cargar_recordatorios()
    pendientes = []
    for r in recordatorios:
        if r["estado"] != "pendiente":
            continue
        try:
            fecha_hora = datetime.strptime(
                r["fecha"] + " " + r["hora"],
                "%Y-%m-%d %H:%M"
            )
            if fecha_hora <= ahora:
                pendientes.append(r)
        except:
            pass
    if pendientes:
        
        print("        RECORDATORIOS PENDIENTES")
        print("=" * 50)
        for r in pendientes:
            print(f"\n• {r['titulo']}")
            print(f"  Prioridad: {r['prioridad']}")
            print(f"  Fecha: {r['fecha']} {r['hora']}")
        print("=" * 50)