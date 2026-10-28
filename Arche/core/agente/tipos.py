"""
tipos.py
--------
Ubicacion: Arche/core/agente/tipos.py

Las piezas de datos que se pasan entre los modulos del agente. No hacen nada
por si solas: solo describen que es una herramienta, una accion, una
observacion, un plan, etc. Asi cada modulo (planificar, decidir, ejecutar,
verificar) se puede cambiar sin tocar a los demas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Parametro:
    nombre: str
    tipo: str = "str"            # "str", "int", "float" o "bool"
    descripcion: str = ""
    requerido: bool = True


@dataclass
class Herramienta:
    """Algo que el agente puede hacer en un entorno (ir a un sitio, recolectar, craftear...)."""
    nombre: str
    descripcion: str
    parametros: list[Parametro] = field(default_factory=list)
    peligrosa: bool = False      # si es True, solo se ejecuta con autorizacion

    def firma(self) -> str:
        partes = []
        for p in self.parametros:
            partes.append(f"{p.nombre}: {p.tipo}" + ("" if p.requerido else " (opcional)"))
        return f"{self.nombre}({', '.join(partes)})"

    def ayuda(self) -> str:
        detalle = "; ".join(f"{p.nombre}: {p.descripcion}" for p in self.parametros if p.descripcion)
        return f"- {self.firma()} -> {self.descripcion}" + (f" [{detalle}]" if detalle else "")


@dataclass
class Accion:
    nombre: str
    args: dict[str, Any] = field(default_factory=dict)
    razon: str = ""

    def corta(self) -> str:
        if not self.args:
            return f"{self.nombre}()"
        cuerpo = ", ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.nombre}({cuerpo})"


@dataclass
class ResultadoAccion:
    ok: bool
    mensaje: str = ""
    datos: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observacion:
    texto: str                                   # lo que el modelo lee
    datos: dict[str, Any] = field(default_factory=dict)   # lo mismo en estructura
    imagen: bytes | None = None                  # captura (JPEG/PNG) si el entorno la da
    descripcion_visual: str = ""                 # lo que el modelo de vision vio en la imagen


@dataclass
class Subobjetivo:
    descripcion: str
    criterio: str = ""           # como saber que ya esta cumplido
    hecho: bool = False
    meta: dict = field(default_factory=dict)   # si no esta vacio, es un paso calculado sin modelo (ver simbolico.py)


@dataclass
class Plan:
    objetivo: str
    pasos: list[Subobjetivo] = field(default_factory=list)
    version: int = 1
    notas: str = ""
    origen: str = "modelo"       # "simbolico" si lo calculo el agente con las recetas del juego, sin ningun modelo

    def pendientes(self) -> list[Subobjetivo]:
        return [p for p in self.pasos if not p.hecho]

    def resumen(self) -> str:
        lineas = []
        for i, p in enumerate(self.pasos, 1):
            marca = "x" if p.hecho else " "
            lineas.append(f"{i}. [{marca}] {p.descripcion}")
        return "\n".join(lineas)


@dataclass
class Decision:
    tipo: str                     # "accion", "terminado" o "bloqueado"
    accion: Accion | None = None
    razon: str = ""
    siguientes: list[Accion] = field(default_factory=list)   # acciones extra de la misma consulta
    origen: str = "modelo"        # "simbolico" (sin modelo) o "habilidad" (algo que ya me salio antes)


@dataclass
class Paso:
    """Una linea del historial: que se hizo y que paso."""
    accion: Accion
    resultado: ResultadoAccion
    pensamiento: str = ""

    def corto(self, max_chars: int = 220) -> str:
        estado = "OK" if self.resultado.ok else "FALLO"
        msg = (self.resultado.mensaje or "").replace("\n", " ")
        if len(msg) > max_chars:
            msg = msg[:max_chars] + "..."
        return f"{self.accion.corta()} -> {estado}: {msg}"


@dataclass
class Informe:
    objetivo: str
    exito: bool
    motivo: str
    pasos_totales: int
    segundos: float
    plan: Plan | None = None
    replanificaciones: int = 0
    fallos: int = 0
    recuperable: bool = False     # se corto por algo externo (nube, parada): se puede retomar con "agente continua"
