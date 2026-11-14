import os
import json


# RUTAS


from core.rutas import DATABASE
from core.guardado import guardar_json, leer_json

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
    "actualizar_indice_automaticamente": True,
    "velocidad_respuesta": 1.0,
    "autorevision_automatica": True,
    "autorevision_intervalo_horas": 6,
    "ultima_automod_avisada": ""

}

def hablar(texto):
    print(f"{obtener('nombre_asistente')}: {texto}")

# CARGAR CONFIGURACIÓN


def cargar_config():
    if not os.path.exists(archivo_configuracion):
        guardar_config(CONFIG_DEFAULT)
        return CONFIG_DEFAULT.copy()
    # Si el archivo está dañado NO se pisa con los valores de fábrica: leer_json
    # guarda el dañado aparte y recupera la copia anterior (configuracion.json.bak).
    config = leer_json(archivo_configuracion, defecto=None, tipo=dict)
    if config is None:
        config = CONFIG_DEFAULT.copy()
    # Agrega automáticamente nuevas opciones (y solo guarda si de verdad cambió algo)
    faltaban = False
    for clave, valor in CONFIG_DEFAULT.items():
        if clave not in config:
            config[clave] = valor
            faltaban = True
    if faltaban:
        guardar_config(config)
    return config


# GUARDAR CONFIGURACIÓN


def guardar_config(config):
    guardar_json(archivo_configuracion, config)      # atómico: nunca queda a medias


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
    print("CONFIGURACIÓN DE ARCHÉ")
    for clave, valor in config.items():
        print(f"{clave}: {valor}")
