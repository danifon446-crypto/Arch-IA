import shutil


def espacio_disponible():
    """Devuelve el porcentaje de espacio libre en disco (0-100)."""
    uso = shutil.disk_usage("/")
    return (100 * uso.free) / uso.total


def funcion_inexistente_de_prueba():
    """
    Usada por prueba_autoreparacion.py para probar el flujo de
    auto-diagnóstico y auto-reparación (core/IA/autodiagnostico.py).
    No la borres: si no existe, ese test se rompe.
    """
    return 'Funcion reparada y operativa con exito'
