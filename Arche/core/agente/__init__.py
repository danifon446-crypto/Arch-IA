"""
agente
------
Ubicacion: Arche/core/agente/

El sistema de autonomia de Arché: recibe un objetivo, observa un entorno
(Minecraft primero), razona, planifica, actua, verifica y aprende de lo que le
pasa. Es independiente de core/autonomia.py (los avisos tipo Jarvis del PC).

Modulos:
  tipos, config               datos y configuracion
  modelos                     capa de modelos de IA intercambiables, por rol
  entorno + entornos/         el contrato de un "mundo" y los mundos concretos
  percepcion                  observar (y ver imagenes con un modelo de vision)
  planificador                objetivo -> subobjetivos (y replanificar)
  decisor                     siguiente accion (solo propone)
  ejecutor                    valida y ejecuta (sin IA, con limites de seguridad)
  verificador                 comprueba con datos reales antes de dar algo por hecho
  memoria_experiencias        lecciones de exitos y fracasos, que se reusan
  coordinador                 el ciclo completo y la reflexion
  comandos                    la entrada desde el chat de Arché

Uso desde main.py:  from core import agente as agente_arche ; agente_arche.manejar(frase)
Ver core/agente/LEEME.md.
"""

VERSION = "1.1.0"

from core.agente.comandos import detener_todo, estado_texto, manejar   # noqa: E402

__all__ = ["manejar", "detener_todo", "estado_texto", "VERSION"]
