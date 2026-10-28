"""
Prueba de aceptacion creada por Arché al terminar: suma dos numeros
Condiciones que dejó su dueño: sumar_dos(2, 3) devuelve 5; sumar_dos(-1, 1) devuelve 0; sumar_dos(0.1, 0.2) devuelve 0.3
Si esta prueba falla, la función dejó de cumplir lo que se pidió. No la borres sin revisar.
"""
import math
from core.utiles_prueba import sumar_dos

def _igual(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b

def prueba():
    assert _igual(sumar_dos(2, 3), 5), 'sumar_dos(2, 3) devuelve 5'
    assert _igual(sumar_dos(-1, 1), 0), 'sumar_dos(-1, 1) devuelve 0'
    assert _igual(sumar_dos(0.1, 0.2), 0.3), 'sumar_dos(0.1, 0.2) devuelve 0.3'
