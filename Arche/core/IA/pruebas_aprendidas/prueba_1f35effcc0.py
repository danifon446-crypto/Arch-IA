"""
Prueba aprendida por la autorreparación de Arché (2026-10-22 14:04).
Reproduce: ZeroDivisionError: division by zero
En: core/demo_falla.py -> promedio (línea 19)
Si esta prueba falla, ese error volvió. No la borres sin revisar.
"""
from core.demo_falla import promedio

def prueba():
    # Caso que provocaba el error: lista vacía
    assert promedio([]) == 0

    # Caso normal: lista con varios números
    assert promedio([2, 4, 6]) == 4.0
