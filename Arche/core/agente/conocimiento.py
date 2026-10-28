"""
conocimiento.py
---------------
Ubicacion: Arche/core/agente/conocimiento.py

Lo que el propio juego sabe de si mismo: que se fabrica con que, que herramienta
hace falta para picar cada bloque y que suelta cada uno. Con eso se puede calcular
un plan de materiales SIN preguntarle nada a ningun modelo de IA: es aritmetica.

Los datos los entrega el puente de Minecraft (minecraft-data, que viene con
Mineflayer) y se guardan en disco, asi que despues funcionan sin internet.

Lo que NO sabe resolver todavia (fundir en horno, cultivar, combatir) devuelve
None, y entonces el agente le pregunta a un modelo como siempre.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from core.agente import config

# --------------------------------------------------------------------------
# Grupos: "cualquier tronco" y "cualquier tablon" valen igual para planear.
# --------------------------------------------------------------------------
_SUFIJOS_GRUPO = (("_planks", "planks"), ("_log", "log"))

TIERS = {"wooden": 0, "stone": 1, "iron": 2, "diamond": 4, "netherite": 5}   # el dorado se ignora a proposito

_MATERIAL_ES = {"wooden": "madera", "stone": "piedra", "iron": "hierro", "diamond": "diamante",
                "golden": "oro", "netherite": "netherita"}
_TIPO_ES = {"pickaxe": "pico", "axe": "hacha", "sword": "espada", "shovel": "pala", "hoe": "azada"}
_NOMBRES_ES = {
    "log": "troncos", "planks": "tablones", "stick": "palos", "crafting_table": "mesa de crafteo",
    "cobblestone": "piedra (cobblestone)", "coal": "carbón", "furnace": "horno", "chest": "cofre",
    "torch": "antorchas", "dirt": "tierra", "sand": "arena", "raw_iron": "hierro crudo",
    "iron_ingot": "lingotes de hierro", "diamond": "diamantes", "bread": "pan", "apple": "manzana",
}


# De donde sacar cada cosa cuando hay varias opciones (las comunes del mundo normal).
_PREFERIDO = {"cobblestone": "stone", "dirt": "dirt", "coal": "coal_ore", "raw_iron": "iron_ore", "raw_copper": "copper_ore",
              "raw_gold": "gold_ore", "diamond": "diamond_ore", "redstone": "redstone_ore", "lapis_lazuli": "lapis_ore",
              "emerald": "emerald_ore", "clay_ball": "clay", "flint": "gravel"}
_NO_FUENTE = ("deepslate_", "nether_", "infested_", "podzol", "mycelium", "rooted_", "farmland", "dirt_path", "coarse_",
              "mud", "moss", "sculk", "suspicious_", "budding_", "warped_", "crimson_", "soul_")


def grupo(nombre: str) -> str:
    for sufijo, g in _SUFIJOS_GRUPO:
        if nombre.endswith(sufijo):
            return g
    return nombre


def nombre_es(item: str) -> str:
    if item in _NOMBRES_ES:
        return _NOMBRES_ES[item]
    partes = item.split("_", 1)
    if len(partes) == 2 and partes[0] in _MATERIAL_ES and partes[1] in _TIPO_ES:
        return f"{_TIPO_ES[partes[1]]} de {_MATERIAL_ES[partes[0]]}"
    return item.replace("_", " ")


def agrupar_inventario(inventario: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in (inventario or {}).items():
        g = grupo(k)
        out[g] = out.get(g, 0) + int(v)
    return out


def _nivel(herramienta: str) -> int:
    return TIERS.get(herramienta.split("_", 1)[0], 99)


# --------------------------------------------------------------------------
# Resultado del calculo
# --------------------------------------------------------------------------
@dataclass
class PasoMaterial:
    """tipo: 'obtener' (modo 'minar' o 'craftear') o 'colocar'."""
    tipo: str
    item: str
    cantidad: int = 1            # cuanto debe haber en el inventario al terminar este paso
    modo: str = ""
    bloque: str = ""             # que bloque picar (modo minar)
    delta: int = 0               # cuantas unidades aporta este paso (para juntar los de picar madera)
    a_mano: bool = False         # se pica sin herramienta: se puede adelantar y juntar

    def descripcion(self) -> str:
        n = nombre_es(self.item)
        if self.tipo == "colocar":
            return f"Coloca la {n}" if self.item == "crafting_table" else f"Coloca {n}"
        if self.modo == "minar":
            return f"Consigue {self.cantidad} de {n}"
        return f"Fabrica {self.cantidad} de {n}"

    def criterio(self) -> str:
        if self.tipo == "colocar":
            return f"{self.item} puesta cerca"
        return f"{self.cantidad} de {self.item} en el inventario"

    def meta(self) -> dict:
        return {"tipo": self.tipo, "item": self.item, "cantidad": self.cantidad, "modo": self.modo, "bloque": self.bloque}


class NoSeResolver(Exception):
    """Con lo que se, no puedo calcular esto (ej. necesita un horno). Se usa un modelo."""


@dataclass
class _Fuente:
    bloque: str
    herramienta: str | None      # la mas barata que sirve, o None si se pica a mano
    dureza: float = 0.0


@dataclass
class Conocimiento:
    version: str
    recetas: dict[str, list[dict]] = field(default_factory=dict)     # por grupo
    bloques: dict[str, dict] = field(default_factory=dict)
    _fuentes: dict[str, list[_Fuente]] = field(default_factory=dict, repr=False)

    # ---------------------------------------------------------------- carga
    @classmethod
    def desde_datos(cls, datos: dict) -> "Conocimiento":
        recetas: dict[str, list[dict]] = {}
        for item, lista in (datos.get("recetas") or {}).items():
            g = grupo(item)
            for r in lista:
                ing: dict[str, int] = {}
                for k, v in (r.get("ing") or {}).items():
                    ing[grupo(k)] = ing.get(grupo(k), 0) + int(v)
                if not ing or g in ing:
                    continue
                nueva = {"ing": ing, "sal": max(1, int(r.get("sal", 1))), "mesa": bool(r.get("mesa"))}
                if nueva not in recetas.setdefault(g, []):
                    recetas[g].append(nueva)
        for g, lista in recetas.items():
            # la mas barata por unidad obtenida primero (2 tablones -> 4 palos antes que bambu -> 1 palo)
            lista.sort(key=lambda r: (sum(r["ing"].values()) / r["sal"], r["mesa"]))
        c = cls(str(datos.get("version", "?")), recetas, datos.get("bloques") or {})
        c._indexar_fuentes()
        return c

    def _indexar_fuentes(self):
        fuentes: dict[str, list[_Fuente]] = {}
        for nombre, b in self.bloques.items():
            if (b.get("dureza") or 0) < 0.5 or nombre.startswith(_NO_FUENTE):
                continue                           # hojas, hierba, plantas y bloques raros: no cuentan como "fuente"
            herr = b.get("herr")
            tool = min((h for h in herr if _nivel(h) < 99), key=_nivel, default=None) if herr else None
            if herr and tool is None:
                continue
            for suelto in b.get("suelta") or []:
                g = grupo(suelto)
                if suelto == nombre and g in self.recetas:
                    continue                       # la mesa suelta una mesa: eso no es "conseguirla"
                fuentes.setdefault(g, []).append(_Fuente(grupo(nombre), tool, float(b.get("dureza") or 0)))
        for g, lista in fuentes.items():
            # 1) la fuente comun conocida (cobblestone -> stone); 2) el bloque con el mismo nombre; 3) la mas barata
            lista.sort(key=lambda f: (f.bloque != _PREFERIDO.get(g), f.bloque != g,
                                      _nivel(f.herramienta) if f.herramienta else -1, f.dureza))
        self._fuentes = fuentes

    def fuente(self, item: str) -> _Fuente | None:
        lista = self._fuentes.get(grupo(item))
        return lista[0] if lista else None

    def sabe(self, item: str) -> bool:
        g = grupo(item)
        return g in self._fuentes or g in self.recetas

    # ---------------------------------------------------------------- calculo
    def calcular(self, pedido: list[tuple[str, int]], inventario: dict[str, int], mesa_cerca: bool = False) -> list[PasoMaterial]:
        """
        pedido: [(item, cantidad_total_que_debe_haber)]. Devuelve los pasos en orden.
        Lanza NoSeResolver si algo no se puede planear con lo que se.
        """
        inv = agrupar_inventario(inventario)
        pasos: list[PasoMaterial] = []
        estado = {"mesa": mesa_cerca}
        for item, n in pedido:
            if not self.sabe(item):
                raise NoSeResolver(f"no tengo datos de cómo conseguir {item}")
            self._necesito(grupo(item), int(n), inv, pasos, estado, set())
        # un segundo repaso: fabricar una cosa pudo gastar algo que tambien se pidio (madera para el pico, por ejemplo)
        for item, n in pedido:
            self._necesito(grupo(item), int(n), inv, pasos, estado, set())
        return self._juntar_picados(pasos, agrupar_inventario(inventario))

    @staticmethod
    def _juntar_picados(pasos: list[PasoMaterial], inv0: dict[str, int]) -> list[PasoMaterial]:
        """Todo lo que se pica a mano (troncos, tierra...) se hace de una vez al principio: menos viajes."""
        juntos: dict[tuple[str, str], PasoMaterial] = {}
        resto: list[PasoMaterial] = []
        for p in pasos:
            if p.tipo == "obtener" and p.modo == "minar" and p.a_mano:
                clave = (p.item, p.bloque)
                if clave in juntos:
                    juntos[clave].delta += p.delta
                else:
                    juntos[clave] = PasoMaterial("obtener", p.item, 0, "minar", p.bloque, p.delta, True)
            else:
                resto.append(p)
        for (item, _), p in juntos.items():
            p.cantidad = inv0.get(item, 0) + p.delta
        return list(juntos.values()) + resto

    def _necesito(self, g: str, n: int, inv: dict, pasos: list, estado: dict, visitando: set):
        falta = n - inv.get(g, 0)
        if falta <= 0:
            return
        if g in visitando:
            raise NoSeResolver(f"{g} depende de sí mismo")
        visitando = visitando | {g}
        src = self.fuente(g)
        if src is not None:
            if src.herramienta and not self._tengo_alguna(src, inv):
                self._necesito(grupo(src.herramienta), 1, inv, pasos, estado, visitando)
            inv[g] = inv.get(g, 0) + falta
            pasos.append(PasoMaterial("obtener", g, inv[g], "minar", src.bloque, falta, src.herramienta is None))
            return
        ultimo: NoSeResolver | None = None
        for r in self.recetas.get(g, []):
            copia_inv, copia_pasos, copia_estado = dict(inv), list(pasos), dict(estado)
            try:
                veces = math.ceil(falta / r["sal"])
                if r["mesa"] and not copia_estado["mesa"]:
                    self._necesito("crafting_table", 1, copia_inv, copia_pasos, copia_estado, visitando)
                    copia_pasos.append(PasoMaterial("colocar", "crafting_table"))
                    copia_estado["mesa"] = True          # (la mesa puesta sigue "conseguida": no se fabrica otra)
                for ing, c in r["ing"].items():
                    self._necesito(ing, c * veces, copia_inv, copia_pasos, copia_estado, visitando)
                    copia_inv[ing] = copia_inv.get(ing, 0) - c * veces      # se reservan: ya no estan libres
                copia_inv[g] = copia_inv.get(g, 0) + r["sal"] * veces
                copia_pasos.append(PasoMaterial("obtener", g, copia_inv[g], "craftear"))
            except NoSeResolver as e:
                ultimo = e
                continue
            inv.clear(); inv.update(copia_inv)
            pasos[:] = copia_pasos
            estado.clear(); estado.update(copia_estado)
            return
        raise ultimo or NoSeResolver(f"no sé cómo conseguir {g}")

    def _tengo_alguna(self, src: _Fuente, inv: dict) -> bool:
        b = self.bloques.get(src.bloque) or {}
        herr = b.get("herr") or ([src.herramienta] if src.herramienta else [])
        return any(inv.get(grupo(h), 0) > 0 for h in herr)


# --------------------------------------------------------------------------
# Cache en disco
# --------------------------------------------------------------------------
def _archivo(version: str) -> str:
    seguro = "".join(c for c in version if c.isalnum() or c in "._-") or "x"
    return f"conocimiento_{seguro}.json"


def guardar_cache(datos: dict) -> None:
    config.guardar_json(_archivo(str(datos.get("version", "x"))), datos)


def cargar_cache(version: str) -> Conocimiento | None:
    if not version or not os.path.exists(config.ruta(_archivo(version))):
        return None
    datos = config.leer_json(_archivo(version), None)
    return Conocimiento.desde_datos(datos) if datos else None
