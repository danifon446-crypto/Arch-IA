import os
import json


# RUTAS


from core.rutas import DATABASE

archivo_configuracion = os.path.join(
    DATABASE,
    "configuracion.json"
)



# CONFIGURACIÓN POR DEFECTO


CONFIG_DEFAULT = {
    "version": "2.0",
    "nombre_asistente": "Arché",
    "nombre_usuario": "Usuario",
    "voz": False,
    "saludo_inicial": True,
    "mostrar_estado": True,
    "mostrar_recordatorios": True,
    "buscar_programas_automaticamente": True,
    "actualizar_indice_automaticamente": False,
    "velocidad_respuesta": 1.0

}

def hablar(texto):
    print(f"{obtener('nombre_asistente')}: {texto}")

# CARGAR CONFIGURACIÓN


def cargar_config():
    if not os.path.exists(archivo_configuracion):
        guardar_config(CONFIG_DEFAULT)
        return CONFIG_DEFAULT.copy()
    try:
        with open(
            archivo_configuracion,
            "r",
            encoding="utf-8"
        ) as archivo:
            config = json.load(archivo)
        # Agrega automáticamente nuevas opciones
        for clave, valor in CONFIG_DEFAULT.items():
            if clave not in config:
                config[clave] = valor
        guardar_config(config)
        return config
    except:
        guardar_config(CONFIG_DEFAULT)
        return CONFIG_DEFAULT.copy()


# GUARDAR CONFIGURACIÓN


def guardar_config(config):
    with open(
        archivo_configuracion,
        "w",
        encoding="utf-8"
    ) as archivo:
        json.dump(
            config,
            archivo,
            indent=4,
            ensure_ascii=False
        )


# OBTENER CONFIGURACIÓN

config = cargar_config()


# FUNCIONES


def obtener(clave):
    return config.get(clave)

def cambiar(clave, valor):
    config[clave] = valor
    guardar_config(config)

def restaurar():
    global config
    config = CONFIG_DEFAULT.copy()
    guardar_config(config)

def mostrar():
    print()
    print("=" * 45)
    print("CONFIGURACIÓN DE ARCHÉ")
    print("=" * 45)
    for clave, valor in config.items():
        print(f"{clave}: {valor}")
    print("=" * 45)