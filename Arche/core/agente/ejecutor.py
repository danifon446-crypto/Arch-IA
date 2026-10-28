"""
ejecutor.py
-----------
Ubicacion: Arche/core/agente/ejecutor.py

La mano del agente. Recibe una Accion ya decidida y la ejecuta en el entorno.
NO usa ningun modelo de IA y no decide nada: solo valida y ejecuta. Eso es lo
que separa "pensar" de "hacer":

  1. La herramienta tiene que existir en el entorno.
  2. Los parametros se validan y se convierten al tipo correcto (el modelo a
     veces manda "5" en vez de 5). Lo que sobra se ignora; lo que falta se
     devuelve como error para que el decisor se corrija.
  3. Las herramientas marcadas como peligrosas solo corren con autorizacion
     (una funcion `confirmar` que pregunta al usuario) o si los limites lo
     permiten.
  4. Si el usuario pidio parar, no se ejecuta nada mas.
  5. Cualquier error de la herramienta se atrapa y se devuelve como fallo
     legible, nunca tumba al agente.

Limites tambien vive aqui: los topes de seguridad de una sesion.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from core.agente import config
from core.agente.tipos import Accion, Herramienta, ResultadoAccion


@dataclass
class Limites:
    max_pasos: int = 60
    max_segundos: int = 900
    max_fallos_seguidos: int = 5
    max_repeticiones: int = 3
    max_replanificaciones: int = 3
    permitir_peligrosas: bool = False

    @classmethod
    def desde_config(cls, datos: dict | None = None) -> "Limites":
        d = datos if datos is not None else config.cargar().get("limites", {})
        base = cls()
        for k in base.__dict__:
            if k in d:
                setattr(base, k, type(getattr(base, k))(d[k]))
        return base


def _convertir(valor, tipo: str):
    if tipo == "int":
        if isinstance(valor, bool):
            raise ValueError("no es un número entero")
        return int(round(float(valor)))
    if tipo == "float":
        if isinstance(valor, bool):
            raise ValueError("no es un número")
        return float(valor)
    if tipo == "bool":
        if isinstance(valor, bool):
            return valor
        return str(valor).strip().lower() in ("true", "1", "si", "sí", "yes")
    return str(valor)


class Ejecutor:
    def __init__(self, entorno, limites: Limites | None = None, confirmar=None,
                 parada: threading.Event | None = None):
        self.entorno = entorno
        self.limites = limites or Limites()
        self.confirmar = confirmar
        self.parada = parada or threading.Event()

    def herramientas(self) -> dict[str, Herramienta]:
        return {h.nombre: h for h in self.entorno.herramientas()}

    def ejecutar(self, accion: Accion) -> ResultadoAccion:
        if self.parada.is_set():
            return ResultadoAccion(False, "Detenido por el usuario.")
        herramientas = self.herramientas()
        h = herramientas.get(accion.nombre)
        if h is None:
            return ResultadoAccion(False, f"No existe la herramienta '{accion.nombre}'. "
                                          f"Usa una de: {', '.join(sorted(herramientas))}.")
        args, ignorados = {}, []
        conocidos = {p.nombre: p for p in h.parametros}
        for k in accion.args:
            if k not in conocidos:
                ignorados.append(k)
        for p in h.parametros:
            if p.nombre not in accion.args or accion.args[p.nombre] in (None, ""):
                if p.requerido:
                    return ResultadoAccion(False, f"Falta el parámetro '{p.nombre}' de {h.nombre}. "
                                                  f"Forma correcta: {h.firma()}.")
                continue
            try:
                args[p.nombre] = _convertir(accion.args[p.nombre], p.tipo)
            except (ValueError, TypeError):
                return ResultadoAccion(False, f"El parámetro '{p.nombre}' de {h.nombre} debe ser {p.tipo} "
                                              f"(recibí {accion.args[p.nombre]!r}).")
        if h.peligrosa and not self.limites.permitir_peligrosas:
            autorizada = False
            if self.confirmar is not None:
                try:
                    autorizada = bool(self.confirmar(accion))
                except Exception:
                    autorizada = False
            if not autorizada:
                return ResultadoAccion(False, f"La acción '{h.nombre}' necesita autorización del usuario y no se dio. "
                                              "Busca otra manera o declara el subobjetivo bloqueado.")
        inicio = time.time()
        try:
            resultado = self.entorno.ejecutar(Accion(h.nombre, args, accion.razon))
        except Exception as e:  # una herramienta que falla no debe tumbar al agente
            return ResultadoAccion(False, f"Error al ejecutar {h.nombre}: {type(e).__name__}: {e}")
        if not isinstance(resultado, ResultadoAccion):
            resultado = ResultadoAccion(True, str(resultado))
        resultado.datos.setdefault("segundos", round(time.time() - inicio, 2))
        if ignorados:
            resultado.datos["ignorados"] = ignorados
        return resultado
