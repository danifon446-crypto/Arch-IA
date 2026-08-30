import time
import os
import json
import subprocess

from core.rutas import DATABASE

archivo_programas = os.path.join(
    DATABASE,
    "programas.json"
)


# PROGRAMAS POR DEFECTO

PROGRAMAS_POR_DEFECTO = {

    "calculadora": {
        "tipo": "exe",
        "ruta": "calc.exe"
    },
    "bloc": {
        "tipo": "exe",
        "ruta": "notepad.exe"
    },
    "bloc de notas": {
        "tipo": "exe",
        "ruta": "notepad.exe"
    },
    "paint": {
        "tipo": "exe",
        "ruta": "mspaint.exe"
    },
    "explorador": {
        "tipo": "exe",
        "ruta": "explorer.exe"
    },
    "cmd": {
        "tipo": "exe",
        "ruta": "cmd.exe"
    },
    "terminal": {
        "tipo": "exe",
        "ruta": "cmd.exe"
    },
    "powershell": {
        "tipo": "exe",
        "ruta": "powershell.exe"
    },
    "administrador de tareas": {
        "tipo": "exe",
        "ruta": "taskmgr.exe"
    },
    "panel de control": {
        "tipo": "exe",
        "ruta": "control.exe"
    },
    "configuracion": {
        "tipo": "exe",
        "ruta": "ms-settings:"
    },
    "recortes": {
        "tipo": "exe",
        "ruta": "snippingtool.exe"
    }
}
ALIAS = {
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "code": "visual studio code",
    "cmd": "terminal",
    "chat": "chatgpt",
    "ia": "chatgpt"
}


# CARGAR BASE DE DATOS

def cargar_programas():
    if not os.path.exists(archivo_programas):
        with open(archivo_programas, "w", encoding="utf-8") as archivo:
            json.dump(PROGRAMAS_POR_DEFECTO, archivo, indent=4, ensure_ascii=False)
        return PROGRAMAS_POR_DEFECTO.copy()
    try:
        with open(archivo_programas, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
        if isinstance(datos, dict):
            return datos
    except:
        pass
    with open(archivo_programas, "w", encoding="utf-8") as archivo:
        json.dump(PROGRAMAS_POR_DEFECTO, archivo, indent=4, ensure_ascii=False)
    return PROGRAMAS_POR_DEFECTO.copy()
programas = cargar_programas()

# GUARDAR BASE DE DATOS

def guardar_programas():
    with open(archivo_programas, "w", encoding="utf-8") as archivo:
        json.dump(
            programas,
            archivo,
            indent=4,
            ensure_ascii=False
        )


# ABRIR PROGRAMA


def abrir_programa(nombre):
    nombre = nombre.lower()
    if nombre not in programas:
        print("Arché: No conozco ese programa.")
        return
    info = programas[nombre]
    print(f"Arché: Abriendo {nombre}...")
    time.sleep(0.7)
    try:
        if info["tipo"] == "exe":
            os.startfile(info["ruta"])
        elif info["tipo"] == "app":
            os.system(
                f'explorer.exe shell:AppsFolder\\{info["ruta"]}'
            )
    except Exception:
        print("Arché: No pude abrir ese programa.")


# BUSCAR .EXE


def buscar_exe(nombre):
    nombre = nombre.lower()
    carpetas = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.path.join(
            os.environ["USERPROFILE"],
            "AppData",
            "Local",
            "Programs"
        ),
        os.path.join(
            os.environ["USERPROFILE"],
            "AppData",
            "Local"
        )
    ]
    for carpeta in carpetas:
        if not carpeta:
            continue
        if not os.path.exists(carpeta):
            continue
        for raiz, _, archivos in os.walk(carpeta):
            for archivo in archivos:
                if archivo.lower() == nombre + ".exe":
                    return {
                        "tipo": "exe",
                        "ruta": os.path.join(
                            raiz,
                            archivo
                        )
                    }
                if (
                    nombre in archivo.lower()
                    and archivo.lower().endswith(".exe")
                ):
                    return {
                        "tipo": "exe",
                        "ruta": os.path.join(
                            raiz,
                            archivo
                        )
                    }
    return None


# BUSCAR APP WINDOWS


def buscar_app_windows(nombre):
    try:
        resultado = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-StartApps | ConvertTo-Json -Depth 2"
            ],
            capture_output=True,
            text=True,
            encoding="cp1252",
            errors="ignore"
        )
        apps = json.loads(resultado.stdout)
        if isinstance(apps, dict):
            apps = [apps]
        # Normalizar el nombre buscado
        nombre_busqueda = (
            nombre.lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
        )
        for app in apps:
            nombre_app = (
                app["Name"]
                .lower()
                .replace(" ", "")
                .replace("-", "")
                .replace("_", "")
            )
            if nombre_busqueda in nombre_app:
                return {
                    "tipo": "app",
                    "ruta": app["AppID"]
                }
    except Exception as e:
        print(e)
    return None


# BUSCAR PROGRAMA


def buscar_programa(nombre):
    resultado = buscar_exe(nombre)
    if resultado:
        return resultado
    resultado = buscar_app_windows(nombre)
    if resultado:
        return resultado
    resultado = buscar_acceso_directo(nombre)
    if resultado:
        return resultado
    return None


# APRENDER PROGRAMA


def aprender_programa(nombre):
    nombre = nombre.lower().strip()
    if nombre in ALIAS:
            nombre = ALIAS[nombre]
    if nombre in programas:
        abrir_programa(nombre)
        return
    print(f"Arché: Buscando {nombre}...")
    datos = buscar_programa(nombre)
    if datos:
        programas[nombre] = datos
        guardar_programas()
        print(f"Arché: He aprendido a abrir {nombre}.")
        abrir_programa(nombre)
        return
    print("Arché: No pude encontrar ese programa.")
    respuesta = input(
        "¿Quieres enseñármelo? (sí/no)\nTú: "
    ).lower()
    if respuesta not in ["si", "sí", "s"]:
        return
    ruta = input(
        "Arrastra el ejecutable (.exe) aquí y presiona Enter:\nTú: "
    ).strip('"')
    if not os.path.exists(ruta):
        print("Arché: Esa ruta no existe.")
        return
    programas[nombre] = {
        "tipo": "exe",
        "ruta": ruta
    }
    guardar_programas()
    print(f"Arché: Perfecto, ya aprendí {nombre}.")


# OBTENER NOMBRE


def obtener_programa(comando):
    palabras = comando.lower().split()
    for palabra in ["abre", "abrir", "ejecuta", "inicia"]:
        if palabra in palabras:
            posicion = palabras.index(palabra)
            if posicion + 1 < len(palabras):
                return " ".join(
                    palabras[posicion + 1:]
                )
    return None


# BUSCAR ACCESO DIRECTO


def buscar_acceso_directo(nombre):
    nombre = nombre.lower()
    carpetas = [
        os.path.join(
            os.environ["ProgramData"],
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs"
        ),
        os.path.join(
            os.environ["APPDATA"],
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs"
        )
    ]
    for carpeta in carpetas:
        if not os.path.exists(carpeta):
            continue
        for raiz, _, archivos in os.walk(carpeta):
            for archivo in archivos:
                if not archivo.lower().endswith(".lnk"):
                    continue
                archivo_sin_extension = archivo[:-4].lower()
                if nombre == archivo_sin_extension:
                    return {
                        "tipo": "exe",
                        "ruta": os.path.join(
                            raiz,
                            archivo
                        )
                    }
                if nombre in archivo_sin_extension:
                    return {
                        "tipo": "exe",
                        "ruta": os.path.join(
                            raiz,
                            archivo
                        )
                    }
    return None
