"""
decisor.py
----------
Ubicacion: Arche/core/agente/decisor.py

El que decide la SIGUIENTE accion. Ve el subobjetivo actual, lo que esta
pasando en el entorno, lo que acaba de intentar (y como le fue) y las
experiencias previas relevantes, y elige UNA accion entre las herramientas del
entorno. No ejecuta nada: eso es del ejecutor. Tambien puede decir que el
subobjetivo ya esta cumplido ("terminado") o que no hay forma de lograrlo con
lo que tiene ("bloqueado"); el coordinador comprueba esas afirmaciones.
"""

from __future__ import annotations

from core.agente.modelos import pedir_json
from core.agente.tipos import Accion, Decision, Paso

SISTEMA = (
    "Eres el decisor de Arché, un agente autónomo que actúa en un entorno. En cada turno eliges UNA sola acción "
    "para acercarte al subobjetivo actual, usando únicamente las herramientas listadas y sus parámetros exactos. "
    "Lees el resultado de tus acciones anteriores: si algo falló, entiendes por qué y cambias de enfoque en vez de "
    "repetirlo. Aprovechas las experiencias previas. Si el subobjetivo ya se cumplió, lo dices. "
    "Si es imposible con lo que tienes, lo dices. Respondes únicamente con JSON."
)

FORMATO = (
    "Responde SOLO con un JSON de una de estas tres formas:\n"
    '{"pensamiento": "razón breve (1-2 frases)", "acciones": [{"nombre": "herramienta", "args": {"parametro": valor}}]}\n'
    "En 'acciones' pon de 1 a 3 acciones que quieras hacer EN ORDEN sin necesitar ver el resultado de la anterior "
    "(por ejemplo ir_a y luego recolectar). Si una falla, las demás no se ejecutan. Si dudas, pon solo una.\n"
    '{"estado": "terminado", "razon": "por qué ya se cumplió"}\n'
    '{"estado": "bloqueado", "razon": "por qué no se puede avanzar"}'
)


def _validar(d: dict):
    if isinstance(d.get("acciones"), list) and d["acciones"]:
        for a in d["acciones"]:
            if not isinstance(a, dict) or not isinstance(a.get("nombre"), str) or not a["nombre"].strip():
                return "cada elemento de 'acciones' necesita 'nombre'"
            if a.get("args") is not None and not isinstance(a.get("args"), dict):
                return "'args' debe ser un objeto"
        return None
    if isinstance(d.get("accion"), dict):
        a = d["accion"]
        if not isinstance(a.get("nombre"), str) or not a["nombre"].strip():
            return "'accion' necesita 'nombre'"
        if "args" in a and a["args"] is not None and not isinstance(a["args"], dict):
            return "'args' debe ser un objeto"
        return None
    if d.get("estado") in ("terminado", "bloqueado"):
        return None
    return "falta 'accion' o 'estado'"


class Decisor:
    def __init__(self, router):
        self.router = router

    def decidir(self, objetivo: str, subobjetivo, estado_texto: str, herramientas, historial: list[Paso],
                lecciones: str, avisos: list[str], descripcion_entorno: str = "") -> Decision:
        partes = []
        if descripcion_entorno:
            partes.append(f"REGLAS Y CONSEJOS DEL ENTORNO:\n{descripcion_entorno}")
        partes.append("HERRAMIENTAS:\n" + "\n".join(h.ayuda() for h in herramientas))
        partes.append(f"OBJETIVO GENERAL: {objetivo}")
        partes.append(f"SUBOBJETIVO ACTUAL: {subobjetivo.descripcion}"
                      + (f"\nCRITERIO DE ÉXITO: {subobjetivo.criterio}" if subobjetivo.criterio else ""))
        partes.append(f"SITUACIÓN ACTUAL:\n{estado_texto}")
        partes.append("EXPERIENCIAS PREVIAS RELEVANTES:\n" + (lecciones or "(ninguna)"))
        if historial:
            partes.append("ÚLTIMOS PASOS:\n" + "\n".join(p.corto(150) for p in historial[-6:]))
        if avisos:
            partes.append("AVISOS:\n" + "\n".join(f"- {a}" for a in avisos[-3:]))
        partes.append(FORMATO)
        d = pedir_json(self.router, "decisor", [{"role": "user", "content": "\n\n".join(partes)}],
                       sistema=SISTEMA, validar=_validar, max_tokens=500, temperatura=0.2)
        if d is None:
            return Decision("bloqueado", razon="El modelo no dio una respuesta JSON utilizable.")
        lista = d.get("acciones") if isinstance(d.get("acciones"), list) and d["acciones"] else \
            ([d["accion"]] if isinstance(d.get("accion"), dict) else [])
        if lista:
            razon = str(d.get("pensamiento", ""))[:300]
            acciones = [Accion(a["nombre"].strip(), a.get("args") if isinstance(a.get("args"), dict) else {}, razon)
                        for a in lista[:3]]
            return Decision("accion", acciones[0], razon, acciones[1:])
        return Decision(d["estado"], razon=str(d.get("razon", "")))
