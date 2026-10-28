"""
verificador.py
--------------
Ubicacion: Arche/core/agente/verificador.py

Comprueba si algo se cumplio de verdad, sin fiarse de lo que el decisor
"cree". Va en este orden:

  1. Datos reales del entorno (por ejemplo, el inventario de Minecraft): si el
     entorno puede responder si/no, esa respuesta manda.
  2. Si el entorno no sabe, un modelo juzga con la evidencia (estado actual y
     ultimos pasos), con instruccion de ser esceptico.
  3. Si tampoco hay modelo, se considera NO cumplido (nunca se da por bueno
     sin evidencia).
"""

from __future__ import annotations

from core.agente.modelos import ErrorModelo, pedir_json
from core.agente.tipos import Paso

SISTEMA = (
    "Eres el verificador de Arché. Juzgas con evidencia si un subobjetivo se cumplió. "
    "Eres escéptico: sin evidencia clara en el estado actual, dices que NO. Respondes únicamente con JSON."
)


def _validar(d: dict):
    return None if isinstance(d.get("cumplido"), bool) else "falta 'cumplido' (true/false)"


class Verificador:
    def __init__(self, entorno, router):
        self.entorno = entorno
        self.router = router

    def rapido(self, texto: str):
        """True/False con datos del entorno, o None si el entorno no puede comprobarlo."""
        try:
            return self.entorno.verificar_objetivo(texto)
        except Exception:
            return None

    def evaluar(self, descripcion: str, criterio: str, estado_texto: str, historial: list[Paso]) -> tuple[bool, str]:
        objetivo = self.rapido(descripcion)
        if objetivo is not None:
            return objetivo, "comprobado con datos reales del entorno"
        prompt = (f"SUBOBJETIVO: {descripcion}\n" + (f"CRITERIO: {criterio}\n" if criterio else "")
                  + f"\nESTADO ACTUAL:\n{estado_texto}\n\nÚLTIMOS PASOS:\n"
                  + "\n".join(p.corto() for p in historial[-6:])
                  + '\n\nResponde SOLO con JSON: {"cumplido": true|false, "motivo": "evidencia concreta en una frase"}')
        try:
            d = pedir_json(self.router, "verificador", [{"role": "user", "content": prompt}],
                           sistema=SISTEMA, validar=_validar, max_tokens=250, temperatura=0.0)
        except ErrorModelo as e:
            return False, f"no pude verificarlo (sin modelo: {e})"
        if d is None:
            return False, "no pude verificarlo (respuesta inválida)"
        return bool(d["cumplido"]), str(d.get("motivo", ""))[:300]
