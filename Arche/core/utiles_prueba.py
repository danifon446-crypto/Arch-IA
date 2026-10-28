"""
Utilidades de prueba.
"""

def sumar_dos(a, b):
    return a + b


def contar_palabras(texto):
    if not texto:
        return {}
    palabras = texto.split()
    contador = {}
    for palabra in palabras:
        contador[palabra] = contador.get(palabra, 0) + 1
    return contador
