import time
import os
import json
import subprocess

from core.rutas import DATABASE

ARCHIVO_PROGRAMAS = os.path.join(
    DATABASE,
    "programas.json"
)

PROGRAMAS_POR_DEFECTO = {
    "calculadora": "calc.exe",
    "bloc": "notepad.exe",
    "bloc de notas": "notepad.exe",
    "paint": "mspaint.exe",
    "explorador": "explorer.exe",
    "cmd": "cmd.exe",
    "terminal": "cmd.exe",
    "powershell": "powershell.exe",
    "administrador de tareas": "taskmgr.exe",
    "panel de control": "control.exe",
    "configuracion": "ms-settings:",
    "wordpad": "write.exe",
    "lupa": "magnify.exe",
    "teclado": "osk.exe",
    "recortes": "snippingtool.exe",
    "camara": "microsoft.windows.camera:",
    "calculadora cientifica": "calc.exe"
}

def guardar_programas():
    with open(ARCHIVO_PROGRAMAS, "w", encoding="utf-8") as archivo:
        json.dump(programa, archivo, indent=4, ensure_ascii=False)

# Cargar programas
if os.path.exists(ARCHIVO_PROGRAMAS):
    try:
        with open(ARCHIVO_PROGRAMAS, "r", encoding="utf-8") as archivo:
            programa = json.load(archivo)
        if not isinstance(programa, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        programa = PROGRAMAS_POR_DEFECTO.copy()
        guardar_programas()
else:
    programa = PROGRAMAS_POR_DEFECTO.copy()
    guardar_programas()

def abrir_programa(nombre):
    nombre = nombre.lower()
    if nombre in programa:
        print(f"Arché: Abriendo {nombre}...")
        time.sleep(1)
        ruta = programa[nombre]
        if ruta.startswith("APP:"):
            os.system(f'explorer.exe shell:AppsFolder\\{ruta[4:]}')
        else:
            os.startfile(ruta)
    else:
        print("Arché: No conozco ese programa.")

def buscar_programa(nombre):
    nombre = nombre.lower()
    carpetas = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.path.join(os.environ["USERPROFILE"], "AppData", "Local", "Programs"),
        os.path.join(os.environ["USERPROFILE"], "AppData", "Local"),
        os.environ.get("WINDIR")
    ]
    for carpeta in carpetas:
        if not carpeta or not os.path.exists(carpeta):
            continue
        for raiz, _, archivos in os.walk(carpeta):
            for archivo in archivos:
                if archivo.lower() == nombre + ".exe":
                    return os.path.join(raiz, archivo)
                if nombre in archivo.lower() and archivo.lower().endswith(".exe"):
                    return os.path.join(raiz, archivo)
    return None

def aprender_programa(nombre):
        print("Arché: Buscando el programa...")
        # Buscar .exe
        ruta = buscar_programa(nombre)
        # Si no encuentra un .exe, buscar aplicación de Windows
        if not ruta:
            ruta = buscar_app_windows(nombre)
        if ruta:
            programa[nombre] = ruta
            guardar_programas()
            print("Arché: ¡Lo encontré!")
            return
        print("Arché: No pude encontrarlo automáticamente.")
        ruta = input("Arché: Arrastra el programa aquí o pega la ruta:\nTú: ")
        ruta = ruta.strip('"')
        if os.path.exists(ruta):
            programa[nombre] = ruta
            guardar_programas()
            print(f"Arché: He aprendido a abrir {nombre}.")
        else:
            print("Arché: Esa ruta no existe.")

def obtener_programa(comando):
    partes = comando.split()
    for i in range(len(partes)):
        if partes[i] in ["abre", "abrir"]:
            if i + 1 < len(partes):
                return " ".join(partes[i + 1:])
    return None

def buscar_app_windows(nombre):
    try:
        resultado = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-StartApps | ConvertTo-Json"
            ],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        datos = json.loads(resultado.stdout)
        if isinstance(datos, dict):
            datos = [datos]
        for app in datos:
            if nombre.lower() in app["Name"].lower():
                return "APP:" + app["AppID"]
    except Exception:
        return None
    return None