"""
orquestador_autonomo.py
-------------------------
Ubicación: Arche/core/IA/orquestador_autonomo.py

Motor de Autonomía de Arché:
Modifica archivos directamente usando la API de Ollama, respaldado por 
un sistema de backups preventivos y Smoke Tests (AST) con auto-rollback.


REGLAS DE REPARACIÓN:
1. Si falta una función o variable (NameError), DEBES definir la función directamente en el archivo fallido.
2. NO agregues sentencias 'import' hacia funciones que no existan previamente en otros módulos.
3. Genera código Python válido en UTF-8 puro, sin usar caracteres especiales o acentos en cadenas de texto si no es necesario.


Motor de auto-reparación de Arché. Se dispara cuando algo falla en
tiempo de ejecución (ver autodiagnostico.py) y trata de arreglarlo
solo -- pero SIEMPRE pidiendo tu aprobación antes de tocar un archivo
real, en lenguaje natural, y dándote la posibilidad de sugerir un
ajuste antes de que se aplique.

REESCRITO por completo respecto a la version anterior. La version
vieja tenia dos problemas graves de seguridad:
  1. Reescribia el archivo ENTERO pidiendole a Ollama el contenido
     completo modificado -- el mismo enfoque de alto riesgo que se
     evito deliberadamente en todo el resto del sistema (un modelo
     chico puede truncar, resumir de mas, o alucinar partes que no
     tocaste).
  2. Aplicaba el cambio directo al archivo real, SIN pedir ninguna
     aprobacion -- rompia la regla de seguridad mas importante de
     todo el proyecto.

Ahora reutiliza el MISMO pipeline validado que usa el resto de Arche
(proponer_cambio_codigo.py: fragmentos chicos, sin alucinaciones, sin
confundir tipos, ejecucion real cuando es posible) y el MISMO paso de
aplicacion segura que usa revisar_cambios_codigo.py (backup + smoke
test + log inmutable) -- nada de codigo duplicado ni caminos nuevos
sin las mismas protecciones.
"""

import sys
from pathlib import Path

_RAIZ_APP = Path(__file__).resolve().parents[2]
if str(_RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP))

from core.IA.enrutar_cambio import decidir_destino, es_pedido_de_agregado
from core.IA.proponer_cambio_codigo import (
    proponer_cambio_ia, proponer_agregar_funcion_cerca, _extraer_funcion,
    _cargar_pendientes, _guardar_pendientes,
)
from core.IA.revisar_cambios_codigo import aplicar_propuesta, _area_natural, _log_inmutable


class OrquestadorAutonomo:
    """
    Intenta reparar un problema por su cuenta, pero SIEMPRE pasa por
    el mismo gate de aprobación que cualquier otro cambio de código
    en Arché -- esto no es una excepción a la regla, es una aplicación
    más de la misma regla.
    """

    def __init__(self, reintentos_max=2):
        self.reintentos_max = reintentos_max

    def _generar_propuesta(self, orden_usuario, sugerencia_extra=None):
        """
        Genera una propuesta de arreglo usando el mismo pipeline
        confiable de siempre (routing + generación aislada/acotada +
        validaciones). Si `sugerencia_extra` viene de vos (una vuelta
        de corrección), se le suma a la instrucción original.
        """
        instruccion = orden_usuario
        if sugerencia_extra:
            instruccion = f"{orden_usuario} Además, quien te pidió esto agregó: {sugerencia_extra}"

        decision = decidir_destino(instruccion)

        if decision["tipo"] == "editar_existente" and decision["funcion"] and es_pedido_de_agregado(instruccion):
            ruta = _RAIZ_APP / decision["archivo"]
            contenido = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
            ancla = _extraer_funcion(contenido, decision["funcion"])
            if ancla:
                return proponer_agregar_funcion_cerca(decision["archivo"], ancla, instruccion, origen="autodiagnostico")

        return proponer_cambio_ia(decision["archivo"], instruccion, origen="autodiagnostico")

    def ejecutar_meta(self, orden_usuario: str):
        """
        Genera una propuesta de arreglo y la lleva por un ciclo de
        aprobación EN LENGUAJE NATURAL: podés aprobarla, descartarla,
        o escribir una sugerencia de qué cambiar -- en ese caso se
        regenera con tu sugerencia sumada, hasta reintentos_max veces.

        Devuelve True si el arreglo quedó aplicado, False si no.
        """
        propuesta, error = self._generar_propuesta(orden_usuario)

        if error:
            print(f"\nArché: Intenté armar un arreglo, pero no lo logré: {error}")
            return False

        intentos_usados = 1
        while True:
            area = _area_natural(propuesta["archivo"])
            print(f"\nArché: Tuve un problema en {area}. Esto es lo que se me ocurre para arreglarlo:")
            print(f"       {propuesta['que'].split('según:', 1)[-1].strip()}")
            if propuesta.get("por_que"):
                print(f"       {propuesta['por_que']}")

            respuesta = input(
                "\nArché: ¿Lo aplico? Decime 's' para aprobar, 'n' para descartar, "
                "o contame directamente qué te gustaría que ajuste.\nTú: "
            ).strip()

            if respuesta.lower() in ("s", "si", "sí"):
                aplicado = aplicar_propuesta(propuesta)
                if aplicado:
                    print(f"\nArché: Listo, ya quedó aplicado en {area}.")
                else:
                    print(f"\nArché: Lo intenté pero no pasó una verificación final, así que no quedó aplicado -- no se rompió nada, se restauró solo.")
                return aplicado

            if respuesta.lower() in ("n", "no"):
                pendientes = _cargar_pendientes()
                for p in pendientes:
                    if p["id"] == propuesta["id"]:
                        p["estado"] = "rechazada"
                _guardar_pendientes(pendientes)
                _log_inmutable({"tipo": "cambio_codigo_rechazado", "id": propuesta["id"]})
                print(f"\nArché: Entendido, no toco nada en {area}.")
                return False

            # Cualquier otra cosa se toma como una sugerencia para regenerar
            if intentos_usados >= self.reintentos_max:
                print(f"\nArché: Ya lo intenté un par de veces con tus sugerencias y no logro cerrarlo bien. "
                      f"Mejor lo dejamos así por ahora -- podés pedírmelo de nuevo más adelante, o hacerlo vos con 'escribe en {propuesta['archivo']} : ...'.")
                return False

            print("\nArché: Dale, lo intento de nuevo con eso en cuenta...")
            nueva_propuesta, nuevo_error = self._generar_propuesta(orden_usuario, sugerencia_extra=respuesta)
            intentos_usados += 1

            if nuevo_error:
                print(f"\nArché: No pude regenerarlo con tu sugerencia: {nuevo_error}")
                return False

            propuesta = nueva_propuesta


if __name__ == "__main__":
    if len(sys.argv) > 1:
        meta = " ".join(sys.argv[1:])
        orquestador = OrquestadorAutonomo()
        orquestador.ejecutar_meta(meta)
    else:
        print('Uso: python core/IA/orquestador_autonomo.py "<instrucción>"')