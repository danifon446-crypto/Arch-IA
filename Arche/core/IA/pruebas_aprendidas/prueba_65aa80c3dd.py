"""
Prueba de aceptacion creada por Arché al terminar: cuenta cuántas veces aparece cada palabra de un texto
Condiciones que dejó su dueño: contar_palabras('a b a') devuelve {'a': 2, 'b': 1}
Si esta prueba falla, la función dejó de cumplir lo que se pidió. No la borres sin revisar.
"""
import math
from core.utiles_prueba import contar_palabras

def _igual(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b

def prueba():
    assert _igual(contar_palabras('a b a'), {'a': 2, 'b': 1}), "contar_palabras('a b a') devuelve {'a': 2, 'b': 1}"
