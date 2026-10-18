"""
prueba_autoreparacion.py
--------------------------
Script de prueba para verificar el flujo de auto-diagnóstico, 
reparación con AST y rendición de cuentas en lenguaje natural.
"""

import sys
import os

# Ajustar la ruta ANTES de importar módulos internos
RAIZ_PROYECTO = os.path.dirname(os.path.abspath(__file__))
if RAIZ_PROYECTO not in sys.path:
    sys.path.insert(0, RAIZ_PROYECTO)

# Importación de módulos locales tras ajustar el path
from core.IA.autodiagnostico import capturar_y_reparar
from core.utilidades import funcion_inexistente_de_prueba


@capturar_y_reparar
def ejecutar_tarea_con_error():
    print("🚀 [PRUEBA] Iniciando ejecución de tarea...")
    
    # Cambiamos la llamada a la función inexistente por la función correcta
    resultado = funcion_inexistente_de_prueba()
    
    print(f"Resultado: {resultado}")


if __name__ == "__main__":
    ejecutar_tarea_con_error()
