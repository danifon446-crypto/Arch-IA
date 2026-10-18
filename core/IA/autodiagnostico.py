"""
autodiagnostico.py
--------------------
Ubicación: Arche/core/IA/autodiagnostico.py

Decorador para capturar errores no controlados en funciones de Arché
y activar un intento de auto-reparación -- SIEMPRE con tu aprobación
antes de aplicar nada (ver orquestador_autonomo.py).

REESCRITO respecto a la version anterior, que llamaba directo a la
API de Ollama con urllib (duplicando lo que ya hace core/IA/ollamaIA.py)
y activaba el arreglo SIN pedir aprobacion. Ahora:
  - Usa conversar() de ollamaIA.py para la narracion, no una llamada
    HTTP cruda aparte.
  - El arreglo en si pasa por OrquestadorAutonomo, que ya tiene el
    gate de aprobacion incorporado (ver orquestador_autonomo.py).

NOTA: existia una copia duplicada y mal ubicada de este archivo en
Arche/core/autodiagnostico.py (fuera de core/IA/) -- convendria
borrarla para no tener dos versiones que puedan divergir.
"""

import sys
import traceback
from functools import wraps
from pathlib import Path

_RAIZ_APP = Path(__file__).resolve().parents[2]
if str(_RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP))

from core.IA.orquestador_autonomo import OrquestadorAutonomo


def _avisar_que_hay_un_problema(archivo: str, tipo_error: str, mensaje_error: str):
    """Le avisa al usuario en lenguaje natural que algo falló, ANTES
    de intentar nada -- para que no se sorprenda con preguntas de
    aprobación sin contexto."""
    print(f"\nArché: Che, me encontré con un problema en {archivo} "
          f"({tipo_error}: {mensaje_error}). Voy a intentar arreglarlo, "
          f"pero te aviso antes de tocar nada.")


def capturar_y_reparar(func):
    """
    Decorador para envolver funciones de Arché. Si la función tira una
    excepción no controlada, arma una descripción del problema y se la
    pasa al orquestador autónomo -- que va a generar una propuesta de
    arreglo y pedirte aprobación en lenguaje natural antes de aplicar
    nada (podés aprobar, rechazar, o sugerir un ajuste).
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            ultimo_marco = tb[-1]
            archivo_fallido = Path(ultimo_marco.filename).name
            linea_error = ultimo_marco.lineno
            tipo_error = type(e).__name__
            mensaje_error = str(e)

            _avisar_que_hay_un_problema(archivo_fallido, tipo_error, mensaje_error)

            meta_autonoma = (
                f"En el archivo {archivo_fallido}, línea {linea_error}, "
                f"pasó este error: {tipo_error}: {mensaje_error}. "
                f"Corregilo para que vuelva a funcionar bien."
            )

            orquestador = OrquestadorAutonomo()
            exito = orquestador.ejecutar_meta(meta_autonoma)

            if not exito:
                print(f"\nArché: Por ahora quedó sin resolver, avisame si querés que lo intentemos de otra forma.")

            return None
    return wrapper


if __name__ == "__main__":
    @capturar_y_reparar
    def _funcion_de_prueba():
        return variable_que_no_existe + 10  # NameError intencional, para probar el flujo

    print("Probando el módulo de autodiagnóstico...")
    _funcion_de_prueba()