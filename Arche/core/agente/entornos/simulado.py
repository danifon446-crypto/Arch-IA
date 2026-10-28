"""
simulado.py
-----------
Ubicacion: Arche/core/agente/entornos/simulado.py

Un mundo de juguete con reglas parecidas a Minecraft, escrito en texto:

  lugares:   base, bosque, cueva
  recursos:  madera (bosque), piedra (cueva, necesita pico_de_madera)
  crafteo:   tablones, palos, mesa_de_crafteo, pico_de_madera, pico_de_piedra
  regla:     las herramientas solo se fabrican con una MESA DE CRAFTEO colocada
             en el lugar donde estas

Sirve para dos cosas:
  1. Probar el agente completo (planificar, decidir, ejecutar, verificar, aprender)
     sin abrir Minecraft: "agente prueba" y prueba_agente.py usan este mundo.
  2. Practicar: un entorno de entrenamiento rapido y gratis donde el agente puede
     cometer errores y guardar lecciones antes de salir al juego real.

Tambien es el ejemplo mas corto de como se escribe un Entorno nuevo.
"""

from __future__ import annotations

import math

from core.agente.entorno import (Entorno, cuenta_en_inventario, parsear_objetivo_inventario,
                                 registrar_entorno)
from core.agente.tipos import Accion, Herramienta, Observacion, Parametro, ResultadoAccion

LUGARES = ("base", "bosque", "cueva")
RECETAS = {
    "tablones": {"entrada": {"madera": 1}, "salida": 2, "mesa": False},
    "palos": {"entrada": {"tablones": 1}, "salida": 2, "mesa": False},
    "mesa_de_crafteo": {"entrada": {"tablones": 4}, "salida": 1, "mesa": False},
    "pico_de_madera": {"entrada": {"tablones": 3, "palos": 2}, "salida": 1, "mesa": True},
    "pico_de_piedra": {"entrada": {"piedra": 3, "palos": 2}, "salida": 1, "mesa": True},
}
RECURSOS = {"madera": ("bosque", None), "piedra": ("cueva", "pico_de_madera")}
ALIAS = {
    "madera": ["madera"], "tablones": ["tablones"], "tablon": ["tablones"], "palos": ["palos"], "palo": ["palos"],
    "piedra": ["piedra"], "mesa de crafteo": ["mesa_de_crafteo"],
    "pico de madera": ["pico_de_madera"], "pico de piedra": ["pico_de_piedra"],
}


class EntornoSimulado(Entorno):
    nombre = "simulado"
    descripcion = (
        "Mundo de juguete parecido a Minecraft. Lugares: base, bosque, cueva. La madera está en el bosque; la piedra "
        "en la cueva y solo se recoge con un pico de madera. 'craftear' usa veces (cada vez produce varias unidades: "
        "1 madera -> 2 tablones, 1 tablones -> 2 palos). Las herramientas (picos) solo se fabrican si hay una "
        "mesa de crafteo COLOCADA en el mismo lugar donde estás. La mesa se fabrica con 4 tablones y se coloca con 'colocar'."
    )

    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.lugar = "base"
        self.inventario: dict[str, int] = {}
        self.mesa: str | None = None

    # ------------------------------------------------------------------
    def observar(self, con_imagen: bool = False) -> Observacion:
        inv = ", ".join(f"{k} x{v}" for k, v in sorted(self.inventario.items())) or "vacío"
        aqui = [r for r, (donde, _) in RECURSOS.items() if donde == self.lugar]
        texto = (f"Lugar actual: {self.lugar}\nLugares: {', '.join(LUGARES)}\nInventario: {inv}\n"
                 f"Mesa de crafteo colocada en: {self.mesa or 'ninguna'}\n"
                 f"Recursos aquí: {', '.join(aqui) or 'ninguno'}")
        return Observacion(texto, {"lugar": self.lugar, "inventario": dict(self.inventario), "mesa": self.mesa})

    def herramientas(self) -> list[Herramienta]:
        return [
            Herramienta("ir_a", "Viaja a un lugar.", [Parametro("lugar", "str", "base, bosque o cueva")]),
            Herramienta("recolectar", "Recoge un recurso del lugar actual.",
                        [Parametro("recurso", "str", "madera o piedra"), Parametro("cantidad", "int", "cuántas unidades", False)]),
            Herramienta("craftear", "Fabrica un objeto (repite la receta 'veces' veces).",
                        [Parametro("item", "str", "tablones, palos, mesa_de_crafteo, pico_de_madera, pico_de_piedra"),
                         Parametro("veces", "int", "cuántas veces", False)]),
            Herramienta("colocar", "Coloca un objeto del inventario en el lugar actual (solo mesa_de_crafteo).",
                        [Parametro("item", "str", "mesa_de_crafteo")]),
        ]

    def ejecutar(self, accion: Accion) -> ResultadoAccion:
        a = accion.args
        if accion.nombre == "ir_a":
            destino = str(a["lugar"]).lower()
            if destino not in LUGARES:
                return ResultadoAccion(False, f"No existe el lugar '{destino}'. Lugares: {', '.join(LUGARES)}.")
            self.lugar = destino
            return ResultadoAccion(True, f"Llegaste a {destino}.")
        if accion.nombre == "recolectar":
            recurso = str(a["recurso"]).lower()
            cantidad = max(1, int(a.get("cantidad", 1)))
            if recurso not in RECURSOS:
                return ResultadoAccion(False, f"'{recurso}' no es un recurso. Recursos: {', '.join(RECURSOS)}.")
            donde, requiere = RECURSOS[recurso]
            if self.lugar != donde:
                return ResultadoAccion(False, f"Aquí ({self.lugar}) no hay {recurso}. Se encuentra en: {donde}.")
            if requiere and not self.inventario.get(requiere):
                return ResultadoAccion(False, f"Necesitas {requiere} para recoger {recurso}.")
            self.inventario[recurso] = self.inventario.get(recurso, 0) + cantidad
            return ResultadoAccion(True, f"Recogiste {cantidad} de {recurso}.")
        if accion.nombre == "craftear":
            item = str(a["item"]).lower()
            veces = max(1, int(a.get("veces", 1)))
            receta = RECETAS.get(item)
            if not receta:
                return ResultadoAccion(False, f"No conozco la receta de '{item}'. Recetas: {', '.join(RECETAS)}.")
            if receta["mesa"] and self.mesa != self.lugar:
                extra = f" La mesa está en {self.mesa}." if self.mesa else ""
                return ResultadoAccion(False, f"Necesitas una mesa de crafteo colocada aquí ({self.lugar}) para fabricar {item}.{extra}")
            faltan = {k: v * veces - self.inventario.get(k, 0) for k, v in receta["entrada"].items()
                      if self.inventario.get(k, 0) < v * veces}
            if faltan:
                detalle = ", ".join(f"{v} más de {k}" for k, v in faltan.items())
                return ResultadoAccion(False, f"Te faltan materiales para {item}: necesitas {detalle}.")
            for k, v in receta["entrada"].items():
                self.inventario[k] -= v * veces
                if not self.inventario[k]:
                    del self.inventario[k]
            producido = receta["salida"] * veces
            self.inventario[item] = self.inventario.get(item, 0) + producido
            return ResultadoAccion(True, f"Fabricaste {producido} de {item}.")
        if accion.nombre == "colocar":
            item = str(a["item"]).lower()
            if item != "mesa_de_crafteo":
                return ResultadoAccion(False, "Solo se puede colocar mesa_de_crafteo.")
            if not self.inventario.get(item):
                return ResultadoAccion(False, "No tienes una mesa_de_crafteo en el inventario.")
            self.inventario[item] -= 1
            if not self.inventario[item]:
                del self.inventario[item]
            self.mesa = self.lugar
            return ResultadoAccion(True, f"Colocaste la mesa de crafteo en {self.lugar}.")
        return ResultadoAccion(False, f"Herramienta desconocida: {accion.nombre}")

    def verificar_objetivo(self, texto: str):
        t = texto.lower()
        if "mesa" in t and any(v in t for v in ("coloca", "pon ", "instala")):
            return self.mesa is not None
        pedido = parsear_objetivo_inventario(texto, ALIAS)
        if not pedido:
            return None
        return all(cuenta_en_inventario(self.inventario, nombres) >= cant for nombres, cant in pedido)


registrar_entorno("simulado", EntornoSimulado)
