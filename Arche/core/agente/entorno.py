"""
entorno.py
----------
Ubicacion: Arche/core/agente/entorno.py

El contrato que cumple cualquier "mundo" donde el agente pueda actuar: un
videojuego, el navegador, el PC o, mas adelante, un robot. El agente nunca
sabe de Minecraft: solo sabe que un Entorno puede

  - observar()          decir que esta pasando ahora (texto, datos, imagen opcional)
  - herramientas()      decir que acciones ofrece, con sus parametros
  - ejecutar(accion)    hacer una de ellas y contar como salio
  - verificar_objetivo  (opcional) comprobar con datos reales si algo ya se cumplio
  - detener()           frenar de inmediato lo que este haciendo

Para sumar un juego o entorno nuevo: crea una subclase, y registrala con
registrar_entorno("nombre", lambda: MiEntorno()). Ver entornos/simulado.py
(el mas corto) y entornos/minecraft.py.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod

from core.agente.tipos import Accion, Herramienta, Observacion, ResultadoAccion


class Entorno(ABC):
    nombre = "entorno"
    descripcion = ""          # reglas y consejos del mundo, se le muestran al modelo

    # --- ciclo de vida ----------------------------------------------
    def conectar(self, **opciones) -> str:
        """Prepara/une el entorno. Devuelve un texto corto de estado. Lanza excepcion si no puede."""
        return "listo"

    def cerrar(self) -> None:
        pass

    def esta_conectado(self) -> bool:
        return True

    # --- lo que el agente usa ---------------------------------------
    @abstractmethod
    def observar(self, con_imagen: bool = False) -> Observacion:
        ...

    @abstractmethod
    def herramientas(self) -> list[Herramienta]:
        ...

    @abstractmethod
    def ejecutar(self, accion: Accion) -> ResultadoAccion:
        ...

    def verificar_objetivo(self, texto: str) -> bool | None:
        """True/False si el entorno puede comprobarlo con datos reales; None si no sabe."""
        return None

    def huella(self, obs: Observacion) -> str:
        """Resumen corto del estado, para notar si algo cambio entre dos pasos."""
        return obs.texto

    def descripcion_completa(self) -> str:
        """La descripcion fija del entorno + las reglas que Arché aprendio investigando (reglas.py)."""
        try:
            from core.agente import reglas
            extra = reglas.texto_para_modelo(self.nombre)
        except Exception:
            extra = ""
        return self.descripcion + (("\n\n" + extra) if extra else "")

    # --- Opcionales: si el entorno los da, el agente planea y decide sin modelo lo que ya sabe ---
    def conocimiento(self):
        """Un core.agente.conocimiento.Conocimiento (recetas, herramientas) o None si no hay."""
        return None

    def objetivos_estructurados(self, texto: str):
        """El objetivo como [(item, cantidad)] si es de tipo "consigue X", o None si no se entiende del todo."""
        return None

    def detener(self) -> None:
        """Parada inmediata de lo que este en curso (movimiento, ataque...)."""
        pass


# ------------------------------------------------------------------
# Registro de entornos
# ------------------------------------------------------------------

_REGISTRO: dict = {}


def registrar_entorno(nombre: str, fabrica) -> None:
    _REGISTRO[nombre] = fabrica


def crear_entorno(nombre: str) -> Entorno:
    if nombre not in _REGISTRO:
        raise KeyError(f"No conozco el entorno '{nombre}'. Disponibles: {', '.join(sorted(_REGISTRO)) or 'ninguno'}")
    return _REGISTRO[nombre]()


def entornos_disponibles() -> list[str]:
    return sorted(_REGISTRO)


# ------------------------------------------------------------------
# Ayuda para verificar objetivos tipo "consigue 5 de madera"
# ------------------------------------------------------------------

_NUMEROS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
            "ocho": 8, "nueve": 9, "diez": 10, "doce": 12, "quince": 15, "veinte": 20}
_VERBOS = r"(?:consigue|conseguir|obten|obtener|recolecta|recolectar|junta|juntar|reune|reunir|fabrica|fabricar|" \
          r"craftea|craftear|crea|crear|ten|tener|necesito|quiero|saca|sacar|mina|minar|pica|talar|tala)"


def sin_tildes(texto: str) -> str:
    d = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def _parsear_item(resto: str, alias: dict[str, list[str]]):
    """Un solo item: "5 de madera", "un pico de piedra". Devuelve [(nombres, cantidad)] o None."""
    resto = resto.strip(" .,:;")
    resto = re.sub(r"^de\s+", "", resto)
    cantidad = 1
    numeros = "|".join(sorted(_NUMEROS, key=len, reverse=True))
    n = re.match(rf"^(\d+|{numeros})\b\s*(?:de\s+)?(.*)$", resto)
    if n:
        cantidad = int(n.group(1)) if n.group(1).isdigit() else _NUMEROS[n.group(1)]
        resto = n.group(2)
    resto = re.sub(r"\b(?:unidades?|piezas?|items?)\b", "", resto).strip()
    resto = re.sub(r"^(?:el|la|los|las)\s+", "", resto)
    # El nombre debe estar AL PRINCIPIO de lo que queda ("fabrica y coloca una mesa" no es "tener una mesa").
    # El nombre mas largo que coincida gana ("pico de piedra" antes que "piedra").
    for palabra in sorted(alias, key=len, reverse=True):
        p = sin_tildes(palabra).replace("_", " ")
        if re.match(rf"{re.escape(p)}s?\b", resto.replace("_", " ")):
            return [(alias[palabra], cantidad)]
    return None


def parsear_objetivo_inventario(texto: str, alias: dict[str, list[str]]):
    """
    Entiende "consigue 5 de madera", "obtén un pico de piedra", y tambien varias cosas juntas:
    "consigue una mesa de crafteo y un pico de madera", "junta 5 de madera, 3 de piedra".
    alias: {palabra_en_español: [nombres_internos_que_cuentan]}.
    Devuelve [(nombres_internos, cantidad), ...] o None si NO TODAS las partes son de ese tipo
    (asi nunca se da un si/no por una parte que no se entiende).
    """
    t = sin_tildes(texto)
    m = re.search(rf"\b{_VERBOS}\b\s+(.+)$", t)
    if not m:
        return None
    partes = [p for p in re.split(r"\s*(?:,|\by\b|\be\b)\s*", m.group(1).strip(" .,:;")) if p.strip()]
    if not partes:
        return None
    pedido = []
    for p in partes:
        r = _parsear_item(p, alias)
        if r is None:
            return None
        pedido.extend(r)
    return pedido


def cuenta_en_inventario(inventario: dict[str, int], nombres: list[str]) -> int:
    return sum(inventario.get(n, 0) for n in nombres)
