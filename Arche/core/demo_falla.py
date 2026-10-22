"""
demo_falla.py
-------------
Ubicacion: Arche/core/demo_falla.py

Archivo de PRUEBA para ver la autorreparacion en vivo. Tiene un error a
proposito: promedio() divide por cero cuando la lista esta vacia.

Comando conectado (en core/comandos_extra.py): "promedio de prueba"

Cuando termines de probar, borra este archivo y la linea de
'promedio de prueba' en core/comandos_extra.py.
"""


def promedio(numeros):
    """Promedio de una lista de numeros."""
    total = sum(numeros)
    # Evitar división por cero: si la lista está vacía devolvemos 0,
    # que es un comportamiento razonable para un promedio vacío.
    return total / len(numeros) if numeros else 0


def promedio_de_prueba():
    notas = []          # lista vacia: aqui explota
    return promedio(notas)
