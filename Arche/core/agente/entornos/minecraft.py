"""
minecraft.py
------------
Ubicacion: Arche/core/agente/entornos/minecraft.py

El entorno de Minecraft (Java). Arché controla a un jugador-bot (Mineflayer,
en Node.js) que entra a tu mundo como un jugador mas. Mineflayer da el estado
del juego de forma estructurada (inventario, vida, bloques y mobs cercanos) y
acciones fiables (caminar con pathfinding, picar, craftear, colocar, atacar),
asi que el agente razona sobre datos reales y no sobre pulsaciones de teclado.

Arquitectura (los dos lados hablan por HTTP en localhost):

   agente (Python)  <-- HTTP JSON -->  puente_minecraft/bot.js (Node + Mineflayer)  <-->  Minecraft

Si el entorno tiene captura_pantalla activada, ademas adjunta una foto de la
pantalla del PC en cada observacion; la capa de percepcion la describe con un
modelo de vision (util si quieres que Arché "vea" tu juego mientras miras).

Para usarlo hace falta: Node.js 18+, "agente instala puente minecraft" (una
vez) y un mundo abierto a LAN o un servidor con online-mode=false.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from core.agente import config
from core.agente.entorno import (Entorno, cuenta_en_inventario, parsear_objetivo_inventario,
                                 registrar_entorno)
from core.agente.percepcion import capturar_pantalla
from core.agente.tipos import Accion, Herramienta, Observacion, Parametro, ResultadoAccion

CARPETA_PUENTE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "puente_minecraft")

_MADERAS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry")
_LOGS = [f"{m}_log" for m in _MADERAS]
_PLANKS = [f"{m}_planks" for m in _MADERAS]
_COLORES = ("white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray",
            "cyan", "purple", "blue", "brown", "green", "red", "black")


def _herramienta(material: str, tipo: str) -> list[str]:
    return [f"{material}_{tipo}"]


# palabra en español -> nombres internos de Minecraft que cuentan
ALIAS = {
    "madera": _LOGS, "tronco": _LOGS, "troncos": _LOGS, "tablones": _PLANKS, "tablon": _PLANKS,
    "palos": ["stick"], "palo": ["stick"],
    "piedra": ["cobblestone", "stone"], "adoquin": ["cobblestone"], "adoquines": ["cobblestone"],
    "carbon": ["coal", "charcoal"], "hierro": ["iron_ingot"], "hierro crudo": ["raw_iron"],
    "lingote de hierro": ["iron_ingot"], "oro": ["gold_ingot"], "diamante": ["diamond"], "diamantes": ["diamond"],
    "tierra": ["dirt"], "arena": ["sand"], "grava": ["gravel"], "vidrio": ["glass"], "ladrillo": ["brick"],
    "mesa de crafteo": ["crafting_table"], "horno": ["furnace"], "cofre": ["chest"], "antorcha": ["torch"],
    "antorchas": ["torch"], "cama": [f"{c}_bed" for c in _COLORES], "lana": [f"{c}_wool" for c in _COLORES],
    "pan": ["bread"], "manzana": ["apple"], "trigo": ["wheat"], "semillas": ["wheat_seeds"], "cubo": ["bucket"],
    "carne": ["beef", "cooked_beef", "porkchop", "cooked_porkchop", "mutton", "cooked_mutton", "chicken", "cooked_chicken"],
    "comida": ["bread", "apple", "cooked_beef", "cooked_porkchop", "cooked_mutton", "cooked_chicken", "carrot", "baked_potato"],
}
for _mat, _nombre in (("wooden", "madera"), ("stone", "piedra"), ("iron", "hierro"), ("golden", "oro"), ("diamond", "diamante")):
    ALIAS[f"pico de {_nombre}"] = _herramienta(_mat, "pickaxe")
    ALIAS[f"espada de {_nombre}"] = _herramienta(_mat, "sword")
    ALIAS[f"hacha de {_nombre}"] = _herramienta(_mat, "axe")
    ALIAS[f"pala de {_nombre}"] = _herramienta(_mat, "shovel")
    ALIAS[f"azada de {_nombre}"] = _herramienta(_mat, "hoe")

DESCRIPCION = (
    "Minecraft Java. Controlas a un jugador real. Usa los NOMBRES INTERNOS en inglés para bloques e items "
    "(oak_log, cobblestone, crafting_table, wooden_pickaxe, iron_ore...). También valen los grupos 'log' (cualquier "
    "tronco), 'planks' (cualquier tablón), 'wool' y 'bed'.\n"
    "Reglas útiles: troncos -> tablones (planks) -> palos (stick) y mesa (crafting_table: 4 planks). Las herramientas "
    "y armas se fabrican en una crafting_table COLOCADA cerca (colocar la mesa y luego craftear); tablones, palos y "
    "la propia mesa no la necesitan. Progresión de picos: wooden -> stone -> iron -> diamond; la piedra (stone) exige "
    "al menos wooden_pickaxe, el hierro (iron_ore) stone_pickaxe, el diamante iron_pickaxe. Picar stone da cobblestone. "
    "'recolectar' ya camina hasta el bloque, lo pica y recoge lo que suelta; no necesitas moverte antes si hay uno cerca "
    "(si no hay ninguno en el radio, explora con ir_a).\n"
    "Si picaste bajo tierra y vas a seguir en la superficie, usa subir_a_superficie. "
    "Seguridad: de noche salen monstruos (come, pelea con espada o aléjate); no caves recto hacia abajo ni cerca de lava; "
    "come si el hambre baja de 14. Si la vida baja de 8, aléjate de los enemigos."
)


class ErrorPuente(Exception):
    pass


class EntornoMinecraft(Entorno):
    nombre = "minecraft"
    descripcion = DESCRIPCION

    def __init__(self, opciones: dict | None = None, lanzar_puente: bool = True):
        cfg = dict(config.cargar()["minecraft"])
        cfg.update(opciones or {})
        self.cfg = cfg
        self.lanzar_puente = lanzar_puente
        self.base = f"http://127.0.0.1:{int(cfg['puerto_puente'])}"
        self._proceso: subprocess.Popen | None = None
        self._conectado = False

    # ------------------------------------------------------------------
    # Comunicacion con el puente
    # ------------------------------------------------------------------
    def _llamar(self, ruta: str, carga=None, timeout: float = 130):
        datos = json.dumps(carga).encode("utf-8") if carga is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos, headers={"Content-Type": "application/json"},
                                     method="POST" if datos is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                raise ErrorPuente(f"el puente respondió HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErrorPuente(f"no se pudo hablar con el puente de Minecraft ({e})") from None
        except ValueError:
            raise ErrorPuente("el puente devolvió algo que no es JSON") from None

    def puente_activo(self) -> bool:
        try:
            return bool(self._llamar("/ping", timeout=2).get("ok"))
        except ErrorPuente:
            return False

    @staticmethod
    def puente_instalado() -> bool:
        return os.path.isdir(os.path.join(CARPETA_PUENTE, "node_modules", "mineflayer"))

    def _asegurar_puente(self):
        if self.puente_activo():
            return
        if not self.lanzar_puente:
            raise ErrorPuente("el puente de Minecraft no está corriendo")
        if not self.puente_instalado():
            raise ErrorPuente("falta instalar el puente de Minecraft (necesita Node.js). Escribe: agente instala puente minecraft")
        try:
            self._proceso = subprocess.Popen(
                ["node", "bot.js", "--puerto", str(int(self.cfg["puerto_puente"]))], cwd=CARPETA_PUENTE,
                stdout=subprocess.DEVNULL, stderr=open(config.ruta("puente_minecraft.log"), "ab"),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise ErrorPuente("no encuentro Node.js. Instálalo desde nodejs.org (versión 18 o más) y vuelve a intentar") from None
        for _ in range(40):
            if self.puente_activo():
                return
            if self._proceso.poll() is not None:
                raise ErrorPuente("el puente se cerró al arrancar; revisa Database/agente/puente_minecraft.log")
            time.sleep(0.25)
        raise ErrorPuente("el puente no respondió a tiempo")

    # ------------------------------------------------------------------
    # Entorno
    # ------------------------------------------------------------------
    def conectar(self, **opciones) -> str:
        self.cfg.update({k: v for k, v in opciones.items() if v not in (None, "")})
        self._asegurar_puente()
        r = self._llamar("/conectar", {k: self.cfg.get(k) for k in ("host", "puerto", "usuario", "version", "auth")}, timeout=70)
        if not r.get("ok"):
            raise ErrorPuente(r.get("mensaje", "no pude entrar al mundo"))
        self._conectado = True
        try:
            self._llamar("/accion", {"nombre": "decir", "args": {"mensaje": "Hola, soy Arché. Dime qué hacer y me pongo a trabajar."}}, timeout=5)
        except ErrorPuente:
            pass
        return r.get("mensaje", "conectado")

    def esta_conectado(self) -> bool:
        if not self._conectado:
            return False
        try:
            return bool(self._llamar("/ping", timeout=3).get("conectado"))
        except ErrorPuente:
            return False

    def cerrar(self) -> None:
        try:
            if self.puente_activo():
                self._llamar("/desconectar", {}, timeout=5)
        except ErrorPuente:
            pass
        if self._proceso and self._proceso.poll() is None:
            self._proceso.terminate()
        self._conectado = False

    def detener(self) -> None:
        try:
            self._llamar("/detener", {}, timeout=3)
        except ErrorPuente:
            pass

    def observar(self, con_imagen: bool = False) -> Observacion:
        try:
            e = self._llamar("/estado", timeout=60)
        except ErrorPuente:
            # el estado completo se atascó: seguimos con lo básico (inventario) en vez de abortar todo
            e = self._llamar("/estado?ligero=1", timeout=15)
            e.update(posicion={"x": "?", "y": "?", "z": "?"}, vida="?", hambre="?",
                     aviso="No pude leer el entorno completo; solo veo el inventario.")
        if not e.get("ok", True) and "mensaje" in e:
            raise ErrorPuente(e["mensaje"])
        inv = e.get("inventario", {})
        lineas = [
            *( [e["aviso"]] if e.get("aviso") else [] ),
            f"Posición: x={e['posicion']['x']} y={e['posicion']['y']} z={e['posicion']['z']} ({e.get('dimension', '?')})",
            f"Momento: {'de día' if e.get('es_dia') else 'de noche'} | Vida: {e.get('vida')}/20 | Hambre: {e.get('hambre')}/20"
            f" | En la mano: {e.get('mano') or 'nada'}",
            "Inventario: " + (", ".join(f"{k} x{v}" for k, v in sorted(inv.items())) or "vacío"),
        ]
        if e.get("bajo_los_pies"):
            lineas.append(f"Bajo los pies: {e['bajo_los_pies']}")
        bloques = e.get("bloques", [])
        if bloques:
            lineas.append("Bloques cercanos (cantidad, el más cercano): " + "; ".join(
                f"{b['nombre']} x{b['cantidad']} (a {b['distancia']} m en {b['x']},{b['y']},{b['z']})" for b in bloques))
        ents = e.get("entidades", [])
        if ents:
            lineas.append("Entidades cercanas: " + "; ".join(f"{x['nombre']} a {x['distancia']} m" + (" [hostil]" if x.get("hostil") else "")
                                                             for x in ents))
        if e.get("eventos"):
            lineas.append("Eventos recientes: " + " | ".join(e["eventos"][-5:]))
        imagen = capturar_pantalla() if (con_imagen and self.cfg.get("captura_pantalla")) else None
        return Observacion("\n".join(lineas), e, imagen)

    def herramientas(self) -> list[Herramienta]:
        P = Parametro
        return [
            Herramienta("buscar_bloque", "Dice dónde está el bloque más cercano de ese tipo (sin moverse).",
                        [P("bloque", "str", "nombre interno, ej. oak_log o iron_ore"), P("radio", "int", "radio de búsqueda, por defecto 64", False)]),
            Herramienta("ir_a", "Camina (con pathfinding) hasta unas coordenadas.",
                        [P("x", "int"), P("y", "int"), P("z", "int"), P("margen", "int", "a cuántos bloques basta llegar, por defecto 1", False)]),
            Herramienta("ir_a_bloque", "Camina hasta quedar junto al bloque más cercano de ese tipo.",
                        [P("bloque", "str", "nombre interno"), P("radio", "int", "por defecto 64", False)]),
            Herramienta("recolectar", "Camina hasta bloques de ese tipo, los pica con la mejor herramienta del inventario y recoge lo que sueltan.",
                        [P("bloque", "str", "nombre interno o grupo (oak_log, log, cobblestone...)"), P("cantidad", "int", "cuántos bloques picar", False)]),
            Herramienta("craftear", "Fabrica un item. Si la receta necesita mesa, usa una crafting_table cercana.",
                        [P("item", "str", "nombre interno, ej. planks, stick, wooden_pickaxe"), P("cantidad", "int", "cuántas unidades quieres obtener", False)]),
            Herramienta("colocar", "Coloca un bloque del inventario (mesa, horno, cofre, antorcha...). Sin coordenadas lo pone a tu lado.",
                        [P("bloque", "str", "nombre interno"), P("x", "int", "", False), P("y", "int", "", False), P("z", "int", "", False)]),
            Herramienta("equipar", "Pone un item en la mano (o armadura).",
                        [P("item", "str", "nombre interno"), P("destino", "str", "hand, head, torso, legs, feet; por defecto hand", False)]),
            Herramienta("atacar", "Ataca a la entidad más cercana de ese tipo hasta derrotarla.",
                        [P("entidad", "str", "ej. zombie, cow, skeleton"), P("cantidad", "int", "cuántas derrotar, por defecto 1", False)]),
            Herramienta("comer", "Come el mejor alimento del inventario.", []),
            Herramienta("dormir", "Duerme en una cama cercana (solo de noche).", []),
            Herramienta("alejarse", "Se aleja de los enemigos cercanos esa distancia.", [P("distancia", "int", "por defecto 20", False)]),
            Herramienta("subir_a_superficie", "Sale de donde esté (cueva, hueco) hasta la superficie, justo encima. Úsala después de picar bajo tierra.", []),
            Herramienta("esperar", "Espera unos segundos.", [P("segundos", "int", "1 a 30")]),
            Herramienta("decir", "Escribe en el chat del juego (los mensajes que empiezan con / se bloquean).", [P("mensaje", "str")]),
        ]

    # Si el modelo escribe un nombre en español en vez del interno, se traduce lo seguro.
    _TRADUCCION_ARGS = {"madera": "log", "tronco": "log", "troncos": "log", "tablones": "planks", "tablon": "planks",
                        "palos": "stick", "palo": "stick", "mesa de crafteo": "crafting_table", "horno": "furnace",
                        "cofre": "chest", "antorcha": "torch", "antorchas": "torch", "carbon": "coal",
                        "diamante": "diamond", "tierra": "dirt", "arena": "sand"}

    def _traducir_args(self, args: dict) -> dict:
        out = dict(args or {})
        for k in ("bloque", "item", "objeto", "nombre"):
            v = out.get(k)
            if isinstance(v, str) and v.strip().lower() in self._TRADUCCION_ARGS:
                out[k] = self._TRADUCCION_ARGS[v.strip().lower()]
        return out

    def ejecutar(self, accion: Accion) -> ResultadoAccion:
        try:
            r = self._llamar("/accion", {"nombre": accion.nombre, "args": self._traducir_args(accion.args)}, timeout=150)
        except ErrorPuente as e:
            return ResultadoAccion(False, str(e))
        return ResultadoAccion(bool(r.get("ok")), str(r.get("mensaje", "")), r.get("datos", {}) or {})

    def _inventario(self) -> dict[str, int]:
        return self._llamar("/estado?ligero=1", timeout=15).get("inventario", {})

    # Cosas que se COLOCAN: una vez puestas ya no estan en el inventario pero siguen "conseguidas".
    _COLOCABLES_ESCANEADOS = {"crafting_table", "furnace", "chest"}      # el escaneo del puente las ve cerca
    _COLOCABLES_SIN_ESCANEO = {"torch"}                                    # no se pueden comprobar: no se opina

    def verificar_objetivo(self, texto: str):
        pedido = parsear_objetivo_inventario(texto, ALIAS)
        if not pedido:
            return None
        nombres_pedidos = {n for nombres, _ in pedido for n in nombres}
        colocable = any(n in self._COLOCABLES_ESCANEADOS or n.endswith("_bed") or n in self._COLOCABLES_SIN_ESCANEO
                        for n in nombres_pedidos)
        try:
            estado = self._llamar("/estado" if colocable else "/estado?ligero=1", timeout=45)
        except ErrorPuente:
            return None
        inv = estado.get("inventario", {})
        cerca = {b["nombre"]: b["cantidad"] for b in estado.get("bloques", [])} if colocable else {}
        incierto = False
        for nombres, cant in pedido:
            tengo = cuenta_en_inventario(inv, nombres) + sum(
                cerca.get(n, 0) for n in nombres if n in self._COLOCABLES_ESCANEADOS or n.endswith("_bed"))
            if tengo >= cant:
                continue
            if any(n in self._COLOCABLES_SIN_ESCANEO for n in nombres):
                incierto = True          # puede estar colocada y no la veo: que decida otro, no un "no" falso
                continue
            return False
        return None if incierto else True

    # ------------------------------------------------------------------
    # Conocimiento del juego (recetas, herramientas): planear sin modelo
    # ------------------------------------------------------------------
    def conocimiento(self):
        """Recetas y herramientas reales del juego: de disco si ya se bajaron, si no, del puente."""
        if getattr(self, "_conocimiento", None) is not None:
            return self._conocimiento
        from core.agente import conocimiento as kn
        version = str(self.cfg.get("version") or "")
        datos = None
        try:
            if self.puente_activo():
                datos = self._llamar("/datos" + (f"?version={version}" if version else ""), timeout=30)
                if datos.get("ok"):
                    kn.guardar_cache(datos)
                else:
                    datos = None
        except ErrorPuente:
            datos = None
        k = kn.Conocimiento.desde_datos(datos) if datos else kn.cargar_cache(version)
        self._conocimiento = k
        return k

    def objetivos_estructurados(self, texto: str):
        """"consigue 5 de madera y un pico de madera" -> [("log", 5), ("wooden_pickaxe", 1)] o None si no se entiende todo."""
        pedido = parsear_objetivo_inventario(texto, ALIAS)
        if not pedido:
            return None
        from core.agente.conocimiento import grupo
        salida = []
        for nombres, cant in pedido:
            conjunto = set(nombres)
            if conjunto == set(_LOGS):
                item = "log"
            elif conjunto == set(_PLANKS):
                item = "planks"
            elif conjunto == {"cobblestone", "stone"}:
                item = "cobblestone"
            elif conjunto == {"coal", "charcoal"}:
                item = "coal"
            elif len(nombres) == 1:
                item = grupo(nombres[0])
            else:
                return None                  # "una cama", "comida": cualquiera de varias cosas; que lo decida un modelo
            salida.append((item, int(cant)))
        return salida

    def huella(self, obs: Observacion) -> str:
        d = obs.datos or {}
        p = d.get("posicion", {})
        return json.dumps([p.get("x"), p.get("y"), p.get("z"), d.get("vida"), d.get("hambre"),
                           sorted((d.get("inventario") or {}).items())], default=str)


def instalar_puente(avisar=print) -> tuple[bool, str]:
    """Corre 'npm install' en la carpeta del puente. Solo se llama cuando el usuario lo pide."""
    npm = "npm.cmd" if sys.platform.startswith("win") else "npm"
    try:
        avisar("Instalando el puente de Minecraft (npm install); puede tardar un par de minutos...")
        r = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=CARPETA_PUENTE,
                           capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        return False, "No encuentro Node.js/npm. Instálalo desde nodejs.org (versión 18 o más) y vuelve a intentar."
    except subprocess.TimeoutExpired:
        return False, "npm tardó demasiado; revisa tu conexión e inténtalo otra vez."
    if r.returncode != 0:
        return False, "npm install falló:\n" + (r.stderr or r.stdout)[-600:]
    return True, "Puente instalado."


registrar_entorno("minecraft", EntornoMinecraft)
