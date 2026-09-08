import json  # import que nunca se usa en este archivo


def calcular_descuento(precio, porcentaje):
    """Bug real a propósito: divide por 100 dos veces, el descuento
    queda mal calculado."""
    descuento = precio * (porcentaje / 100) / 100
    return precio - descuento


def funcion_que_nadie_usa():
    """Código muerto real: no la llama nada en todo el proyecto."""
    return "esto no lo usa nadie"


def leer_config_riesgosa(ruta):
    try:
        with open(ruta) as f:
            return f.read()
    except:  # except desnudo a propósito
        return None