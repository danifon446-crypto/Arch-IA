"""
simbolico.py
------------
Ubicacion: Arche/core/agente/simbolico.py

Planificar y decidir SIN ningun modelo de IA lo que el juego ya sabe resolver:
si el objetivo es "consigue X", se calculan los materiales con las recetas reales,
se ordenan los pasos y cada paso se traduce directo en una accion del puente.

Asi Arché no gasta nube (ni depende de ella) para lo conocido: la nube solo entra
cuando algo es nuevo (combate, fundir, explorar, un error raro).
"""

from __future__ import annotations

from core.agente.conocimiento import NoSeResolver, agrupar_inventario, grupo, nombre_es
from core.agente.tipos import Accion, Decision, Observacion, Plan, Subobjetivo

MAX_PASOS_PLAN = 40


class Simbolico:
    def __init__(self, entorno):
        self.entorno = entorno

    def _conocimiento(self):
        try:
            return self.entorno.conocimiento()
        except Exception:
            return None

    # ------------------------------------------------------------------ plan
    def crear_plan(self, objetivo: str, datos: dict, version: int = 1) -> Plan | None:
        """Plan calculado con las recetas del juego, o None si esto no se puede resolver asi."""
        k = self._conocimiento()
        if k is None:
            return None
        try:
            pedido = self.entorno.objetivos_estructurados(objetivo)
        except Exception:
            pedido = None
        if not pedido:
            return None
        inv = (datos or {}).get("inventario") or {}
        mesa = any(b.get("nombre") == "crafting_table" for b in (datos or {}).get("bloques", []) or [])
        try:
            pasos = k.calcular(pedido, inv, mesa)
        except NoSeResolver:
            return None
        if len(pasos) > MAX_PASOS_PLAN:
            return None
        subs = [Subobjetivo(p.descripcion(), p.criterio(), False, p.meta()) for p in pasos]
        return Plan(objetivo, subs, version, "Calculado con las recetas del propio juego (sin consultar ningún modelo).", "simbolico")

    # ------------------------------------------------------------------ estado de un paso
    @staticmethod
    def cumplido(sub: Subobjetivo, obs: Observacion) -> bool | None:
        """True si el paso ya se cumple segun lo que se ve; None si este paso no es simbolico."""
        m = sub.meta
        if not m:
            return None
        datos = obs.datos or {}
        if m.get("tipo") == "colocar":
            bloques = datos.get("bloques")
            if bloques is None:
                return None
            return any(b.get("nombre") == m.get("item") for b in bloques)
        inv = agrupar_inventario(datos.get("inventario") or {})
        return inv.get(grupo(m.get("item", "")), 0) >= int(m.get("cantidad", 1))

    # ------------------------------------------------------------------ decision
    @staticmethod
    def _explorar(sub: Subobjetivo, obs: Observacion, historial) -> Decision | None:
        """Si el bloque no esta a la vista, camina en cuadro cada vez mas lejos hasta encontrarlo (unas 5 veces)."""
        if not historial or sub.meta.get("modo") != "minar":
            return None
        ultimo = historial[-1]
        msg = ultimo.resultado.mensaje or ""
        if ultimo.resultado.ok or not msg.startswith("No hay") or not ("a la vista" in msg or "a la redonda" in msg):
            return None
        pos = (obs.datos or {}).get("posicion") or {}
        try:
            x, y, z = int(pos["x"]), int(pos["y"]), int(pos["z"])
        except (KeyError, TypeError, ValueError):
            return None
        hechas = sum(1 for p in historial if p.accion.nombre == "ir_a" and p.accion.razon.startswith("explorar"))
        if hechas >= 5:
            return None
        dx, dz = [(1, 0), (0, 1), (-1, 0), (0, -1)][hechas % 4]
        d = 45 + 20 * hechas
        return Decision("accion", Accion("ir_a", {"x": x + dx * d, "y": y, "z": z + dz * d, "margen": 4},
                                         f"explorar para encontrar {nombre_es(sub.meta.get('item', ''))}"),
                        "No lo veo cerca: exploro.", origen="simbolico")

    def decidir(self, sub: Subobjetivo, obs: Observacion, historial=()) -> Decision | None:
        """La siguiente accion para un paso calculado, o None si hay que preguntarle a un modelo."""
        m = sub.meta
        if not m:
            return None
        datos = obs.datos or {}
        if "inventario" not in datos:
            return None
        inv = agrupar_inventario(datos["inventario"])
        item = m.get("item", "")
        g = grupo(item)
        if m.get("tipo") == "colocar":
            if inv.get(g, 0) > 0:
                return Decision("accion", Accion("colocar", {"bloque": item}, "poner la mesa para poder fabricar"),
                                f"Coloco {nombre_es(item)}.", origen="simbolico")
            return None
        falta = int(m.get("cantidad", 1)) - inv.get(g, 0)
        if falta <= 0:
            return Decision("terminado", razon="ya lo tengo", origen="simbolico")
        if m.get("modo") == "minar":
            e = self._explorar(sub, obs, historial)
            if e is not None:
                return e
            if historial and historial[-1].accion.nombre == "ir_a" and not historial[-1].resultado.ok and \
                    historial[-1].accion.razon.startswith("explorar"):
                return None                            # no pude ni caminar: que piense un modelo
            return Decision("accion", Accion("recolectar", {"bloque": m["bloque"], "cantidad": falta}, f"necesito {falta} más"),
                            f"Pico {nombre_es(item)}.", origen="simbolico")
        if m.get("modo") == "craftear":
            return Decision("accion", Accion("craftear", {"item": g, "cantidad": falta}, f"necesito {falta} más"),
                            f"Fabrico {nombre_es(item)}.", origen="simbolico")
        return None
