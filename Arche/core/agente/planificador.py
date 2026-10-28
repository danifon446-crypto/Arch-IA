"""
planificador.py
---------------
Ubicacion: Arche/core/agente/planificador.py

Divide un objetivo grande en subobjetivos pequeños, ordenados y verificables,
y vuelve a planificar cuando algo falla. No ejecuta nada: solo piensa el plan.

  crear_plan(...)     objetivo -> lista de subobjetivos (mira entorno, estado y experiencias previas)
  replanificar(...)   conserva lo ya hecho y rehace lo que falta, sabiendo POR QUE fallo el intento anterior

Si ningun modelo responde bien, devuelve un plan de un solo paso (el objetivo
entero) para que el decisor lo intente directamente.
"""

from __future__ import annotations

from core.agente.modelos import ErrorModelo, pedir_json
from core.agente.tipos import Plan, Subobjetivo

SISTEMA = (
    "Eres el planificador de Arché, un agente autónomo. Conviertes un objetivo en una lista corta de "
    "subobjetivos concretos, en el orden correcto, para un entorno y unas herramientas concretas. "
    "Piensas en requisitos previos (materiales, herramientas, lugares) y los pones ANTES de lo que dependen de ellos. "
    "Respondes únicamente con JSON."
)

FORMATO = (
    'Responde SOLO con este JSON: {"subobjetivos": [{"descripcion": "...", "criterio": "cómo saber que ya está cumplido"}], '
    '"notas": "obstáculos o riesgos previstos"}\n'
    "Reglas: de 1 a 8 subobjetivos; el primero se puede empezar ahora mismo; cada descripción empieza con un verbo "
    "en imperativo y se puede comprobar. Si el subobjetivo es conseguir algo del inventario, escríbelo así: "
    '"Consigue 5 madera" (verbo + cantidad + nombre), para poder comprobarlo con datos reales. '
    "Cada subobjetivo es un RESULTADO (tener algo, colocar algo, llegar con algo hecho), nunca un simple desplazamiento: "
    "NO pongas pasos como 'ir al bosque' o 'ir a la base' (el decisor ya sabe moverse cuando lo necesita). "
    "Incluye TODOS los materiales: calcula cuánta madera, piedra, palos y tablones hacen falta en total. "
    "El último subobjetivo debe ser el objetivo mismo. "
    "Usa las experiencias previas para evitar errores ya cometidos."
)


def _validar(d: dict):
    sub = d.get("subobjetivos")
    if not isinstance(sub, list) or not sub:
        return "falta la lista 'subobjetivos'"
    for s in sub:
        if not isinstance(s, dict) or not str(s.get("descripcion", "")).strip():
            return "cada subobjetivo necesita 'descripcion'"
    return None


def _plan_desde(d: dict, objetivo: str, version: int) -> Plan:
    pasos = [Subobjetivo(str(s["descripcion"]).strip(), str(s.get("criterio", "")).strip())
             for s in d["subobjetivos"][:8]]
    return Plan(objetivo, pasos, version, str(d.get("notas", "")).strip())


class Planificador:
    def __init__(self, router, memoria):
        self.router = router
        self.memoria = memoria

    @staticmethod
    def _contexto_entorno(entorno, estado_texto: str) -> str:
        herramientas = "\n".join(h.ayuda() for h in entorno.herramientas())
        return (f"ENTORNO: {entorno.nombre}\nREGLAS Y CONSEJOS DEL ENTORNO:\n{entorno.descripcion_completa() or '(ninguno)'}\n\n"
                f"HERRAMIENTAS DISPONIBLES:\n{herramientas}\n\nSITUACIÓN ACTUAL:\n{estado_texto}\n")

    def crear_plan(self, objetivo: str, entorno, estado_texto: str) -> Plan:
        lecciones = self.memoria.buscar(entorno.nombre, objetivo, k=5)
        texto_lecc = self.memoria.formatear(lecciones) or "(ninguna todavía)"
        prompt = (f"{self._contexto_entorno(entorno, estado_texto)}\n"
                  f"EXPERIENCIAS PREVIAS RELEVANTES:\n{texto_lecc}\n\nOBJETIVO: {objetivo}\n\n{FORMATO}")
        try:
            d = pedir_json(self.router, "planificador", [{"role": "user", "content": prompt}],
                           sistema=SISTEMA, validar=_validar, max_tokens=900)
        except ErrorModelo:
            raise
        if d is None:
            return Plan(objetivo, [Subobjetivo(objetivo)], 1, "El planificador no respondió bien; se intenta directo.")
        return _plan_desde(d, objetivo, 1)

    def replanificar(self, plan: Plan, fallido: Subobjetivo, motivo: str, rastro: str,
                     entorno, estado_texto: str) -> Plan:
        hechos = [p.descripcion for p in plan.pasos if p.hecho]
        lecciones = self.memoria.buscar(entorno.nombre, f"{fallido.descripcion} {motivo}", k=4)
        texto_lecc = self.memoria.formatear(lecciones) or "(ninguna todavía)"
        prompt = (f"{self._contexto_entorno(entorno, estado_texto)}\n"
                  f"OBJETIVO GENERAL: {plan.objetivo}\n"
                  f"YA HECHO: {'; '.join(hechos) if hechos else '(nada todavía)'}\n"
                  f"SUBOBJETIVO QUE FALLÓ: {fallido.descripcion}\nMOTIVO: {motivo}\n"
                  f"ÚLTIMOS INTENTOS:\n{rastro}\n\nEXPERIENCIAS PREVIAS RELEVANTES:\n{texto_lecc}\n\n"
                  "Cambia de estrategia: plantea los subobjetivos que FALTAN (no repitas lo ya hecho) de modo que "
                  "se resuelva la causa del fallo (falta un material, una herramienta, un lugar, un paso previo...).\n"
                  f"{FORMATO}")
        d = pedir_json(self.router, "planificador", [{"role": "user", "content": prompt}],
                       sistema=SISTEMA, validar=_validar, max_tokens=900)
        if d is None:
            return plan   # sin respuesta util: se conserva el plan y el decisor lo vuelve a intentar
        nuevo = _plan_desde(d, plan.objetivo, plan.version + 1)
        nuevo.pasos = [Subobjetivo(h, hecho=True) for h in hechos] + nuevo.pasos
        return nuevo
