import os
import shutil
import psutil

def espacio_disponible():
    # Obtener el espacio disponible en el disco
    espacio_disponible = shutil.disk_usage("/")
    espacio_total = espacio_disponible.total
    espacio_usado = espacio_disponible.used

    # Calcular el porcentaje de espacio libre
    porcentaje_libre = (100 * espacio_disponible.free) / espacio_total

    return porcentaje_libre

# Ejemplo de uso
print(f"Porcentaje de espacio libre: {espacio_disponible()}")


def funcion_inexistente_de_prueba():
    return '¡Función reparada y operativa!'

def funcion_inexistente_de_prueba():
    return 'Funcion reparada y operativa con exito'


def funcion_inexistente_de_prueba():
    return 'Funcion reparada y operativa con exito'