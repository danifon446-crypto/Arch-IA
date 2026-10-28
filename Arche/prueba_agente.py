"""
prueba_agente.py
----------------
Se corre desde la carpeta Arche:   python prueba_agente.py

Prueba TODO el ciclo del agente (planificar, decidir, ejecutar, verificar,
aprender) sin Minecraft y sin ningun modelo real: usa el mundo de juguete y un
"cerebro" falso que a proposito comete un error la primera vez (intenta fabricar
un pico sin mesa de crafteo). Comprueba que:
  1. el ejecutor rechaza parametros malos y no se cae,
  2. el agente se recupera del error y cumple el objetivo,
  3. guarda una leccion en la memoria,
  4. la segunda vez usa la leccion y NO repite el error,
  5. la repeticion sin cambios y la parada se detectan.
No toca tu Database: usa una carpeta temporal.
"""

import json
import os
import re
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["ARCHE_AGENTE_DIR"] = tempfile.mkdtemp(prefix="arche_agente_")

from core.agente import config                                          # noqa: E402
from core.agente.coordinador import Agente                              # noqa: E402
from core.agente.ejecutor import Ejecutor, Limites                      # noqa: E402
from core.agente.entorno import parsear_objetivo_inventario             # noqa: E402
from core.agente.entornos.simulado import ALIAS, EntornoSimulado       # noqa: E402
from core.agente.memoria_experiencias import MemoriaExperiencias        # noqa: E402
from core.agente.modelos import Enrutador, ErrorModelo, ModeloFalso, extraer_json  # noqa: E402
from core.agente.tipos import Accion                                    # noqa: E402

FALLOS = []


def comprobar(condicion, texto):
    print(("  ok   " if condicion else "  MAL  ") + texto)
    if not condicion:
        FALLOS.append(texto)


# ---------------------------------------------------------------- cerebro falso
def _estado(prompt):
    lugar = re.search(r"Lugar actual: (\w+)", prompt).group(1)
    inv = {k: int(v) for k, v in re.findall(r"(\w+) x(\d+)", prompt.split("Inventario:")[1].split("\n")[0])}
    mesa = re.search(r"Mesa de crafteo colocada en: (\w+)", prompt).group(1)
    return lugar, inv, (None if mesa == "ninguna" else mesa)


def _plan(mensajes, sistema, imagenes):
    return json.dumps({"subobjetivos": [
        {"descripcion": "Consigue 5 madera", "criterio": "5 de madera en el inventario"},
        {"descripcion": "Coloca una mesa de crafteo", "criterio": "mesa colocada"},
        {"descripcion": "Consigue 1 pico de madera"},
        {"descripcion": "Consigue 3 piedra"},
        {"descripcion": "Consigue 1 pico de piedra"}], "notas": ""})


def _decisor(mensajes, sistema, imagenes):
    p = mensajes[-1]["content"]
    lugar, inv, mesa = _estado(p)
    sub = re.search(r"SUBOBJETIVO ACTUAL: (.*)", p).group(1)
    con_leccion = "mesa" in p.split("EXPERIENCIAS PREVIAS RELEVANTES:")[1].split("ÚLTIMOS PASOS")[0].lower()
    ya_fallo = "FALLO" in p and "pico_de_madera" in p
    def act(n, **a):
        return json.dumps({"pensamiento": "paso", "accion": {"nombre": n, "args": a}})
    if "madera" in sub and "pico" not in sub:
        if lugar != "bosque":
            return act("ir_a", lugar="bosque")
        return act("recolectar", recurso="madera", cantidad="5")        # "5" como texto: el ejecutor lo corrige
    if "mesa" in sub:
        if not inv.get("tablones") and not inv.get("mesa_de_crafteo") and not mesa:
            return act("craftear", item="tablones", veces=5)
        if mesa:
            return json.dumps({"estado": "terminado", "razon": "mesa colocada"})
        if inv.get("mesa_de_crafteo"):
            return act("colocar", item="mesa_de_crafteo")
        if not con_leccion and not ya_fallo:
            return act("craftear", item="pico_de_madera")                # el error a proposito
        return act("craftear", item="mesa_de_crafteo")
    if "pico de madera" in sub:
        if not inv.get("palos"):
            return act("craftear", item="palos", veces=2)
        return act("craftear", item="pico_de_madera")
    if "piedra" in sub and "pico" not in sub:
        return act("ir_a", lugar="cueva") if lugar != "cueva" else act("recolectar", recurso="piedra", cantidad=3)
    if "pico de piedra" in sub:
        if lugar != mesa:
            return act("ir_a", lugar=mesa)
        return act("craftear", item="pico_de_piedra")
    return json.dumps({"estado": "bloqueado", "razon": "no sé qué hacer"})


def _no(mensajes, sistema, imagenes):
    raise ErrorModelo("sin modelo en la prueba")


def router(decisor=_decisor):
    return Enrutador({"planificador": ModeloFalso(_plan), "decisor": ModeloFalso(decisor),
                      "verificador": ModeloFalso(_no), "reflexion": ModeloFalso(_no), "vision": ModeloFalso(_no)})


# ---------------------------------------------------------------- pruebas
print("1. Piezas sueltas")
comprobar(extraer_json('Claro:\n```json\n{"a": 1,}\n```') == {"a": 1}, "extrae JSON entre ``` y con coma de sobra")
comprobar(parsear_objetivo_inventario("fabrica y coloca una mesa de crafteo", ALIAS) is None, "no confunde 'coloca una mesa' con tener una")
comprobar(parsear_objetivo_inventario("Consigue cinco de madera", ALIAS) == [(["madera"], 5)], "entiende 'cinco de madera'")

ej = Ejecutor(EntornoSimulado(), Limites())
comprobar(not ej.ejecutar(Accion("volar")).ok, "herramienta inexistente -> fallo legible")
r = ej.ejecutar(Accion("ir_a", {}))
comprobar(not r.ok and "lugar" in r.mensaje, "parametro faltante -> dice cual")
comprobar(ej.ejecutar(Accion("ir_a", {"lugar": "bosque", "basura": 1})).ok, "parametros de mas se ignoran")
comprobar(ej.ejecutar(Accion("recolectar", {"recurso": "madera", "cantidad": "3"})).ok, "'3' texto se convierte en entero")
ev = EntornoSimulado()
ej2 = Ejecutor(ev, Limites()); ej2.parada.set()
comprobar(not ej2.ejecutar(Accion("ir_a", {"lugar": "cueva"})).ok and ev.lugar == "base", "con parada activa no ejecuta nada")

print("2. Primera vez: comete el error, se recupera, aprende")
mem = MemoriaExperiencias()
a1 = Agente(EntornoSimulado(), router(), mem, Limites(), avisar=lambda t: None, usar_vision=False)
inf1 = a1.ejecutar("consigue 1 pico de piedra")
comprobar(inf1.exito, f"cumplio el objetivo ({inf1.motivo})")
comprobar(inf1.fallos >= 1, f"hubo un fallo real que superar (fallos={inf1.fallos})")
comprobar(mem.total("simulado") >= 1, f"guardo experiencia(s) (total={mem.total('simulado')})")
print("     leccion:", mem.buscar("simulado", "coloca una mesa de crafteo", k=1)[0]["leccion"][:150])

print("3. Segunda vez: usa la leccion y no repite el error")
mem2 = MemoriaExperiencias()                                  # recarga desde disco
comprobar(mem2.total("simulado") == mem.total("simulado"), "la memoria persiste en disco")
a2 = Agente(EntornoSimulado(), router(), mem2, Limites(), avisar=lambda t: None, usar_vision=False)
inf2 = a2.ejecutar("consigue 1 pico de piedra")
comprobar(inf2.exito and inf2.fallos < inf1.fallos, f"menos fallos que la primera vez ({inf2.fallos} < {inf1.fallos})")

print("4. Protecciones")
def terco(mensajes, sistema, imagenes):
    return json.dumps({"accion": {"nombre": "ir_a", "args": {"lugar": "base"}}})
a3 = Agente(EntornoSimulado(), router(terco), MemoriaExperiencias(), Limites(max_replanificaciones=0),
            avisar=lambda t: None, usar_vision=False)
inf3 = a3.ejecutar("consigue 1 pico de piedra")
comprobar(not inf3.exito and "repitiendo" in inf3.motivo + " ".join(a3.eventos), "detecta que repite lo mismo sin cambios")
comprobar(inf3.pasos_totales <= 4, f"y se detiene pronto ({inf3.pasos_totales} acciones)")

def sin_modelo(mensajes, sistema, imagenes):
    raise ErrorModelo("caido")
a4 = Agente(EntornoSimulado(), Enrutador({r: ModeloFalso(sin_modelo) for r in
            ("planificador", "decisor", "verificador", "reflexion", "vision")}), MemoriaExperiencias(), Limites(),
            avisar=lambda t: None, usar_vision=False)
inf4 = a4.ejecutar("consigue 1 pico de piedra")
comprobar(not inf4.exito and "modelo" in inf4.motivo.lower(), "sin ningun modelo: falla con mensaje claro, sin caerse")

print("5. Parada desde otro hilo")
paso = threading.Event()
def lento(mensajes, sistema, imagenes):
    paso.set()
    return json.dumps({"accion": {"nombre": "ir_a", "args": {"lugar": "bosque"}}})
a5 = Agente(EntornoSimulado(), router(lento), MemoriaExperiencias(), Limites(), avisar=lambda t: None, usar_vision=False)
a5.detener()                                                  # parada antes de empezar el bucle
inf5 = a5.ejecutar("consigue 1 pico de piedra")               # ejecutar() limpia la parada: debe terminar por si solo
comprobar(isinstance(inf5.exito, bool), "el ciclo termina siempre con un informe")

print("6. Varias acciones por consulta al modelo (menos llamadas)")
llamadas = {"decisor": 0}
def en_lote(mensajes, sistema, imagenes):
    llamadas["decisor"] += 1
    p = mensajes[-1]["content"]
    lugar, inv, mesa = _estado(p)
    sub = re.search(r"SUBOBJETIVO ACTUAL: (.*)", p).group(1)
    if "madera" in sub and "pico" not in sub:
        return json.dumps({"acciones": [{"nombre": "ir_a", "args": {"lugar": "bosque"}},
                                         {"nombre": "recolectar", "args": {"recurso": "madera", "cantidad": 5}},
                                         {"nombre": "craftear", "args": {"item": "pico_de_piedra"}},    # fallara: corta el lote
                                         {"nombre": "ir_a", "args": {"lugar": "cueva"}}]})
    return _decisor(mensajes, sistema, imagenes)
envl = EntornoSimulado()
a6 = Agente(envl, router(en_lote), MemoriaExperiencias(), Limites(), avisar=lambda t: None, usar_vision=False)
inf6 = a6.ejecutar("consigue 1 pico de piedra")
comprobar(inf6.exito, f"cumple el objetivo usando lotes ({inf6.motivo})")
comprobar(envl.inventario.get("pico_de_piedra", 0) >= 1, "el pico de piedra existe de verdad en el mundo")
comprobar(llamadas["decisor"] < inf6.pasos_totales, f"menos consultas al decisor ({llamadas['decisor']}) que acciones ({inf6.pasos_totales})")

print("7. Verificar objetivos compuestos y cosas ya colocadas (Minecraft)")
from core.agente.entornos import minecraft as mc                       # noqa: E402
comp = parsear_objetivo_inventario("consigue una mesa de crafteo y un pico de madera", mc.ALIAS)
comprobar(comp == [(["crafting_table"], 1), (["wooden_pickaxe"], 1)], f"entiende las DOS cosas ({comp})")
comprobar(parsear_objetivo_inventario("junta 5 de madera, 3 de piedra", mc.ALIAS) is not None, "entiende 'A, B'")
comprobar(parsear_objetivo_inventario("consigue una mesa y explora la cueva", mc.ALIAS) is None, "si una parte no se entiende, no opina")

class _Falso(mc.EntornoMinecraft):
    def __init__(self, estado):
        super().__init__(lanzar_puente=False); self.estado = estado
    def _llamar(self, ruta, carga=None, timeout=0):
        return self.estado
mesa_puesta = {"inventario": {"wooden_pickaxe": 1}, "bloques": [{"nombre": "crafting_table", "cantidad": 1}]}
comprobar(_Falso(mesa_puesta).verificar_objetivo("consigue una mesa de crafteo y un pico de madera") is True,
          "mesa YA COLOCADA + pico en inventario -> cumplido (el caso que fallaba)")
sin_mesa = {"inventario": {"wooden_pickaxe": 1}, "bloques": []}
comprobar(_Falso(sin_mesa).verificar_objetivo("consigue una mesa de crafteo y un pico de madera") is False,
          "sin mesa en ningun lado -> no cumplido")
sin_pico = {"inventario": {}, "bloques": [{"nombre": "crafting_table", "cantidad": 1}]}
comprobar(_Falso(sin_pico).verificar_objetivo("consigue una mesa de crafteo y un pico de madera") is False,
          "mesa pero sin pico -> no cumplido")
comprobar(_Falso({"inventario": {}, "bloques": []}).verificar_objetivo("consigue 2 antorchas") is None,
          "antorchas (colocables no vistas) -> no opina en vez de dar un 'no' falso")

print("8. La nube: espera y reintenta los limites por minuto")
from core.IA import nube                                                # noqa: E402
from core.agente import modelos as mod                                  # noqa: E402
mod.ESPERAS_LIMITE = (0.01, 0.01, 0.01)
original = nube.responder
cuenta = {"n": 0}
def limitada_dos_veces(msgs, sistema=None, max_tokens=500, temperature=0.7):
    cuenta["n"] += 1
    if cuenta["n"] <= 2:
        raise nube.ErrorNube("llegué al límite gratuito", codigo=429)
    return "listo"
nube.responder = limitada_dos_veces
avisos = []
r = Enrutador({"decisor": mod.ModeloNubeArche()})
r._fijos["decisor"].enrutador = r; r.avisar = avisos.append
comprobar(r.responder("decisor", [{"role": "user", "content": "hola"}]) == "listo" and cuenta["n"] == 3,
          f"2 rechazos y a la tercera responde ({cuenta['n']} intentos)")
comprobar(len(avisos) == 2, "avisa que esta esperando")
nube.responder = lambda *a, **k: (_ for _ in ()).throw(nube.ErrorNube("tope", codigo=429))
try:
    r.responder("decisor", [{"role": "user", "content": "hola"}]); ok = False
except ErrorModelo as e:
    ok = "diario" in str(e)
comprobar(ok, "si el limite no se va, dice que es el tope diario")
nube.responder = lambda *a, **k: (_ for _ in ()).throw(nube.ErrorNube("clave mala", codigo=401))
t0 = __import__("time").time()
try:
    r.responder("decisor", [{"role": "user", "content": "hola"}]); ok = False
except ErrorModelo:
    ok = True
comprobar(ok, "otros errores (clave, internet) NO esperan: fallan al instante")
nube.responder = original

print("9. 'agente nube' y aviso de respaldo")
from core.agente import comandos as cmd                                 # noqa: E402
_pr, _bk, _ra, _mo, _pb = nube.proveedor, nube.proveedores_de_respaldo, nube.respaldo_activo, nube.modelo, nube.probar
nube.proveedor = lambda: "groq"
nube.proveedores_de_respaldo = lambda p=None: ["groq_b"]
nube.respaldo_activo = lambda: True
nube.probar = lambda prov=None: (True, "ok") if prov == "groq_b" else (False, "llegué al límite gratuito")
texto = cmd._estado_nubes()
comprobar("PRINCIPAL" in texto and "FALLA" in texto and "respaldo" in texto and "FUNCIONA" in texto,
          "reporta la principal (con su fallo) y el respaldo (funciona)")
nube.respaldo_activo = lambda: False
comprobar("APAGADO" in cmd._estado_nubes(), "avisa si el respaldo esta apagado")
nube.proveedor, nube.proveedores_de_respaldo, nube.respaldo_activo, nube.modelo, nube.probar = _pr, _bk, _ra, _mo, _pb

avisos2 = []
nube.ultimo_uso = lambda: {"proveedor": "groq_b", "aviso": "Groq falló (límite)"}
nube.responder = lambda *a, **k: "ok"
m = mod.ModeloNubeArche(); r2 = Enrutador({"decisor": m}); m.enrutador = r2; r2.avisar = avisos2.append
r2.responder("decisor", [{"role": "user", "content": "x"}]); r2.responder("decisor", [{"role": "user", "content": "x"}])
comprobar(len(avisos2) == 1 and "RESPALDO" in avisos2[0], "avisa UNA vez cuando contesta el respaldo")
nube.responder = original

print("10. Retomar un plan a medias y diagnostico")
from core.agente.tipos import Informe, Plan, Subobjetivo               # noqa: E402
_dir = tempfile.mkdtemp()
os.environ["ARCHE_AGENTE_DIR"] = _dir
plan_med = Plan("consigue 5 de madera y una mesa", [Subobjetivo("Consigue 5 madera", "", True),
                Subobjetivo("Coloca una mesa de crafteo", "mesa colocada")], 2, "nota")
cmd._guardar_pendiente("simulado", Informe("consigue 5 de madera y una mesa", False, "limite nube", 3, 1.0, plan_med, recuperable=True))
ent, obj, plan_c, motivo = cmd._cargar_pendiente()
comprobar(ent == "simulado" and len(plan_c.pasos) == 2 and plan_c.pasos[0].hecho and not plan_c.pasos[1].hecho and motivo == "limite nube",
          "el plan a medias se guarda y se lee igual (con lo ya hecho)")
comprobar("agente continua" in cmd._texto_pendiente(), "explica como retomarlo")
cmd._guardar_pendiente("simulado", Informe("x", False, "m", 1, 1.0, Plan("x", [Subobjetivo("a", "", True)]), recuperable=True))
comprobar(cmd._cargar_pendiente() is not None, "un plan ya completo no pisa el pendiente existente")
cmd._borrar_pendiente()
comprobar(cmd._cargar_pendiente() is None, "se borra al terminar")

# retomar: el planificador NO se vuelve a llamar y se salta lo hecho
llamadas = {"plan": 0}
def _plan_cuenta(m, s, i):
    llamadas["plan"] += 1
    return _plan(m, s, i)
r3 = Enrutador({"planificador": ModeloFalso(_plan_cuenta), "decisor": ModeloFalso(_decisor),
                "verificador": ModeloFalso(_no), "reflexion": ModeloFalso(_no), "vision": ModeloFalso(_no)})
env3 = EntornoSimulado(); env3.conectar(); env3.inventario["madera"] = 5
plan_r = Plan("Coloca una mesa de crafteo", [Subobjetivo("Consigue 5 madera", "", True),
              Subobjetivo("Coloca una mesa de crafteo", "mesa colocada")])
inf = Agente(env3, router=r3, memoria=MemoriaExperiencias(os.path.join(_dir, "e.jsonl")), avisar=lambda *_: None, usar_vision=False).ejecutar(
    "Coloca una mesa de crafteo", plan_r)
comprobar(llamadas["plan"] == 0, "al retomar no vuelve a planificar")
comprobar(plan_r.pasos[0].hecho, "no rehace lo que ya estaba hecho")

texto_d = cmd._diagnostico()
comprobar("Node" in texto_d and "modelo" in texto_d.lower(), "el diagnostico informa Node y modelos")
os.environ.pop("ARCHE_AGENTE_DIR", None)

print("11. Conocimiento del juego: materiales calculados con las recetas (sin modelo)")
from core.agente.conocimiento import Conocimiento, NoSeResolver, grupo   # noqa: E402
DATOS = {"version": "test", "recetas": {
    "oak_planks": [{"ing": {"oak_log": 1}, "sal": 4, "mesa": False}],
    "birch_planks": [{"ing": {"birch_log": 1}, "sal": 4, "mesa": False}],
    "stick": [{"ing": {"oak_planks": 2}, "sal": 4, "mesa": False}, {"ing": {"bamboo": 2}, "sal": 1, "mesa": False}],
    "crafting_table": [{"ing": {"oak_planks": 4}, "sal": 1, "mesa": False}],
    "wooden_pickaxe": [{"ing": {"oak_planks": 3, "stick": 2}, "sal": 1, "mesa": True}],
    "stone_pickaxe": [{"ing": {"cobblestone": 3, "stick": 2}, "sal": 1, "mesa": True}],
    "iron_ingot": [{"ing": {"iron_nugget": 9}, "sal": 1, "mesa": False}],
    "iron_nugget": [{"ing": {"iron_ingot": 1}, "sal": 9, "mesa": False}]},
  "bloques": {
    "oak_log": {"dureza": 2, "herr": None, "suelta": ["oak_log"]}, "birch_log": {"dureza": 2, "herr": None, "suelta": ["birch_log"]},
    "oak_planks": {"dureza": 2, "herr": None, "suelta": ["oak_planks"]},
    "crafting_table": {"dureza": 2.5, "herr": None, "suelta": ["crafting_table"]},
    "stone": {"dureza": 1.5, "herr": ["wooden_pickaxe", "stone_pickaxe", "golden_pickaxe"], "suelta": ["cobblestone"]},
    "cobblestone": {"dureza": 2, "herr": ["wooden_pickaxe", "stone_pickaxe"], "suelta": ["cobblestone"]},
    "podzol": {"dureza": 0.5, "herr": None, "suelta": ["dirt"]}, "dirt": {"dureza": 0.5, "herr": None, "suelta": ["dirt"]},
    "dead_bush": {"dureza": 0, "herr": None, "suelta": ["stick"]}}}
K = Conocimiento.desde_datos(DATOS)
pasos = K.calcular([("wooden_pickaxe", 1)], {}, False)
tipos = [(p.tipo, p.item, p.modo) for p in pasos]
comprobar(tipos[0] == ("obtener", "log", "minar") and pasos[0].cantidad == 3, "primero junta TODA la madera (3 troncos), no viaja varias veces")
comprobar(("colocar", "crafting_table", "") in tipos and tipos.index(("colocar", "crafting_table", "")) < tipos.index(("obtener", "wooden_pickaxe", "craftear")),
          "pone la mesa antes de fabricar el pico")
comprobar(tipos[-1] == ("obtener", "wooden_pickaxe", "craftear"), "el pico es lo ultimo")
comprobar(all(p.item != "bamboo" for p in pasos), "elige la receta barata de palos (tablones) y no la de bambu")
pasos2 = K.calcular([("cobblestone", 5)], {}, False)
comprobar(pasos2[-1].modo == "minar" and pasos2[-1].bloque == "stone" and pasos2[-1].cantidad == 5,
          "para la piedra pica 'stone' (no busca bloques de cobblestone sueltos)")
comprobar(any(p.item == "wooden_pickaxe" for p in pasos2), "y antes se fabrica el pico que hace falta")
comprobar(K.calcular([("wooden_pickaxe", 1)], {"wooden_pickaxe": 1}, False) == [], "si ya lo tengo no hay nada que hacer")
comprobar(not any(p.tipo == "colocar" for p in K.calcular([("wooden_pickaxe", 1)], {"oak_planks": 8, "stick": 4}, True)),
          "con mesa cerca no coloca otra")
pasos3 = K.calcular([("log", 5), ("wooden_pickaxe", 1)], {}, False)
comprobar(pasos3[0].item == "log" and pasos3[0].cantidad == 8, "pedir 5 de madera Y un pico: junta 8 para que sobren los 5")
try:
    K.calcular([("iron_ingot", 2)], {}, False); comprobar(False, "lo que necesita horno no se inventa")
except NoSeResolver:
    comprobar(True, "lo que necesita horno no se inventa (se lo deja a un modelo)")
comprobar(K.fuente("dirt").bloque == "dirt", "para tierra pica 'dirt' y no podzol")
comprobar(grupo("birch_log") == "log" and grupo("dark_oak_planks") == "planks", "cualquier tronco/tablon vale")

print("12. Agente completo SIN ningun modelo (mundo estilo Minecraft de mentira)")
from core.agente.entorno import Entorno, cuenta_en_inventario            # noqa: E402
from core.agente.entornos import minecraft as mc                          # noqa: E402
from core.agente.habilidades import Habilidades                            # noqa: E402
from core.agente.tipos import Herramienta, Observacion, Parametro, ResultadoAccion  # noqa: E402


class FakeMC(Entorno):
    nombre = "fakemc"
    descripcion = "mundo de prueba"
    def __init__(self, sin_arboles=0):
        self.inv, self.mesa, self.pos, self.sin_arboles, self.acciones = {}, False, [0, 64, 0], sin_arboles, []
    def conectar(self, **o): return "ok"
    def cerrar(self): pass
    def esta_conectado(self): return True
    def conocimiento(self): return K
    def objetivos_estructurados(self, t): return mc.EntornoMinecraft.objetivos_estructurados(self, t)
    def observar(self, con_imagen=False):
        d = {"inventario": dict(self.inv), "posicion": {"x": self.pos[0], "y": self.pos[1], "z": self.pos[2]},
             "bloques": [{"nombre": "crafting_table", "cantidad": 1}] if self.mesa else []}
        return Observacion("Inventario: " + (", ".join(f"{k} x{v}" for k, v in self.inv.items()) or "vacío"), d)
    def herramientas(self):
        P = Parametro
        return [Herramienta("recolectar", "", [P("bloque"), P("cantidad", "int", "", False)]),
                Herramienta("craftear", "", [P("item"), P("cantidad", "int", "", False)]),
                Herramienta("colocar", "", [P("bloque")]),
                Herramienta("ir_a", "", [P("x", "int"), P("y", "int"), P("z", "int"), P("margen", "int", "", False)])]
    def ejecutar(self, a):
        self.acciones.append(a.corta())
        n, g = a.args, a.args
        if a.nombre == "ir_a":
            self.pos = [n["x"], n["y"], n["z"]]
            return ResultadoAccion(True, "llegué")
        if a.nombre == "recolectar":
            if n["bloque"] == "log":
                if self.sin_arboles > 0:
                    self.sin_arboles -= 1
                    return ResultadoAccion(False, "No hay log a la vista en 48 bloques. Explora con ir_a hacia otro lado.")
                self.inv["oak_log"] = self.inv.get("oak_log", 0) + n.get("cantidad", 1)
                return ResultadoAccion(True, "piqué")
            if n["bloque"] == "stone":
                if not self.inv.get("wooden_pickaxe"):
                    return ResultadoAccion(False, "necesitas wooden_pickaxe")
                self.inv["cobblestone"] = self.inv.get("cobblestone", 0) + n.get("cantidad", 1)
                return ResultadoAccion(True, "piqué")
        if a.nombre == "craftear":
            it, cant = n["item"], n.get("cantidad", 1)
            rec = {"planks": ({"oak_log": 1}, 4, False), "stick": ({"oak_planks": 2}, 4, False),
                   "crafting_table": ({"oak_planks": 4}, 1, False), "wooden_pickaxe": ({"oak_planks": 3, "stick": 2}, 1, True),
                   "stone_pickaxe": ({"cobblestone": 3, "stick": 2}, 1, True)}.get(it)
            if not rec:
                return ResultadoAccion(False, "no sé fabricar " + it)
            ing, sal, mesa = rec
            if mesa and not self.mesa:
                return ResultadoAccion(False, "necesitas una crafting_table")
            veces = -(-cant // sal)
            if any(self.inv.get(k, 0) < v * veces for k, v in ing.items()):
                return ResultadoAccion(False, "faltan ingredientes")
            for k, v in ing.items():
                self.inv[k] -= v * veces
            destino = "oak_planks" if it == "planks" else it
            self.inv[destino] = self.inv.get(destino, 0) + sal * veces
            return ResultadoAccion(True, "fabriqué")
        if a.nombre == "colocar":
            if not self.inv.get("crafting_table"):
                return ResultadoAccion(False, "no tienes mesa")
            self.inv["crafting_table"] -= 1
            self.mesa = True
            return ResultadoAccion(True, "puesta")
        return ResultadoAccion(False, "acción desconocida")
    def verificar_objetivo(self, t):
        pedido = parsear_objetivo_inventario(t, mc.ALIAS)
        if not pedido:
            return None
        return all(cuenta_en_inventario(self.inv, nombres) + (1 if self.mesa and "crafting_table" in nombres else 0) >= c
                   for nombres, c in pedido)


llamadas_modelo = []
def _prohibido(m, s, i):
    llamadas_modelo.append(1)
    raise ErrorModelo("no se debe llamar a un modelo")
def _sin_reflexion(m, s, i):
    raise ErrorModelo("sin nube")                 # la reflexion es opcional: sin nube se queda con la leccion simple
def sin_nube():
    r = {k: ModeloFalso(_prohibido) for k in ("planificador", "decisor", "verificador", "vision")}
    r["reflexion"] = ModeloFalso(_sin_reflexion)
    return Enrutador(r)

_dir12 = tempfile.mkdtemp()
env = FakeMC()
inf = Agente(env, router=sin_nube(), memoria=MemoriaExperiencias(os.path.join(_dir12, "e.jsonl")), avisar=lambda *_: None,
             usar_vision=False, habilidades=Habilidades(os.path.join(_dir12, "h.jsonl"))).ejecutar("consigue un pico de madera")
comprobar(inf.exito, f"consigue el pico de madera ({inf.motivo})")
comprobar(not llamadas_modelo, f"sin llamar a ningun modelo ({len(llamadas_modelo)} llamadas)")
comprobar(env.inv.get("wooden_pickaxe") == 1 and env.mesa, "tiene el pico y la mesa quedo puesta")
comprobar(inf.plan is not None and inf.plan.origen == "simbolico", "el plan lo calculo el propio agente")
env = FakeMC()
inf = Agente(env, router=sin_nube(), memoria=MemoriaExperiencias(os.path.join(_dir12, "e2.jsonl")), avisar=lambda *_: None,
             usar_vision=False, habilidades=Habilidades(os.path.join(_dir12, "h.jsonl"))).ejecutar("consigue 5 de piedra")
comprobar(inf.exito and env.inv.get("cobblestone", 0) >= 5 and not llamadas_modelo, f"5 de piedra desde cero, incluido el pico, sin modelo ({inf.motivo})")
env = FakeMC(sin_arboles=2)
inf = Agente(env, router=sin_nube(), memoria=MemoriaExperiencias(os.path.join(_dir12, "e3.jsonl")), avisar=lambda *_: None,
             usar_vision=False, habilidades=Habilidades(os.path.join(_dir12, "h.jsonl"))).ejecutar("consigue 3 de madera")
comprobar(inf.exito and not llamadas_modelo and sum(1 for a in env.acciones if a.startswith("ir_a")) == 2,
          f"si no ve arboles, explora caminando y los encuentra, sin modelo ({[a for a in env.acciones if a.startswith('ir_a')]})")
env = FakeMC(sin_arboles=99)
inf = Agente(env, router=sin_nube(), memoria=MemoriaExperiencias(os.path.join(_dir12, "e4.jsonl")), avisar=lambda *_: None,
             usar_vision=False, habilidades=Habilidades(os.path.join(_dir12, "h.jsonl"))).ejecutar("consigue 3 de madera")
comprobar(not inf.exito and llamadas_modelo, "si explorar no basta, entonces si pide ayuda a un modelo (aqui no hay: falla con mensaje)")

print("13. Habilidades: lo que ya salio bien se repite sin modelo")
cuentas = {"plan": 0, "decisor": 0}
def plan_h(m, s, i):
    cuentas["plan"] += 1
    return json.dumps({"subobjetivos": [{"descripcion": "Fabrica 4 tablones con la madera", "criterio": "4 tablones"}]})
def decisor_h(m, s, i):
    cuentas["decisor"] += 1
    return json.dumps({"pensamiento": "madera y tablones", "acciones": [
        {"nombre": "recolectar", "args": {"bloque": "log", "cantidad": 1}}, {"nombre": "craftear", "args": {"item": "planks", "cantidad": 4}}]})
def router_h():
    return Enrutador({"planificador": ModeloFalso(plan_h), "decisor": ModeloFalso(decisor_h), "verificador": ModeloFalso(_no),
                      "reflexion": ModeloFalso(_no), "vision": ModeloFalso(_no)})
hab = Habilidades(os.path.join(_dir12, "h2.jsonl"))
class FakeSinPlan(FakeMC):                # sin conocimiento: todo pasa por el modelo
    def conocimiento(self): return None
env = FakeSinPlan()
Agente(env, router=router_h(), memoria=MemoriaExperiencias(os.path.join(_dir12, "e5.jsonl")), avisar=lambda *_: None,
       usar_vision=False, habilidades=hab).ejecutar("consigue 4 de tablones")
d1 = cuentas["decisor"]
comprobar(d1 >= 1 and hab.total() == 1, f"la primera vez razona con el modelo y guarda la habilidad ({d1} consulta(s))")
env = FakeSinPlan()
inf = Agente(env, router=router_h(), memoria=MemoriaExperiencias(os.path.join(_dir12, "e5.jsonl")), avisar=lambda *_: None,
             usar_vision=False, habilidades=hab).ejecutar("consigue 4 de tablones")
comprobar(inf.exito and cuentas["decisor"] == d1, f"la segunda vez lo hace sin consultar al decisor ({cuentas['decisor']} consultas en total)")
h = hab.buscar("fakemc", "fabrica 4 tablones con la madera!")
comprobar(h is not None and h["aciertos"] >= 2, "y la habilidad sube de puntaje")
hab.marcar(h["id"], False); hab.marcar(h["id"], False)
comprobar(hab.buscar("fakemc", "Fabrica 4 tablones con la madera") is None, "si falla dos veces seguidas se descarta")
comprobar(not Habilidades.servible([Accion("ir_a", {"x": 1, "y": 2, "z": 3})]), "no guarda acciones con coordenadas")

print("14. Reglas que investiga solo")
from core.agente import reglas                                              # noqa: E402
os.environ["ARCHE_AGENTE_DIR"] = tempfile.mkdtemp()
comprobar(reglas.debe_investigar("minecraft") and not reglas.debe_investigar("simulado"), "la primera vez investiga (solo juegos con wiki)")
def wiki_falsa(entorno, tema):
    if tema == "Mining":
        raise OSError("sin internet")
    return tema, f"Texto de la wiki sobre {tema}. Los creepers explotan. Sin pico no se pica piedra."
def modelo_reglas(m, s, i):
    return json.dumps({"reglas": ["Los creepers explotan: alejarse al oír su siseo.", "La piedra pide pico de madera o mejor.", "x"]})
r_reglas = Enrutador({"reflexion": ModeloFalso(modelo_reglas)})
n, msg = reglas.investigar("minecraft", r_reglas, descargar=wiki_falsa)
comprobar(n == 2 and "Aprendí" in msg, f"lee la wiki (aunque una pagina falle) y guarda reglas ({msg})")
comprobar(not reglas.debe_investigar("minecraft"), "ya no vuelve a investigar solo")
comprobar("creepers" in FakeMC.__mro__[1].descripcion_completa(type("E", (), {"nombre": "minecraft", "descripcion": "base"})()), "las reglas llegan al modelo")
comprobar(reglas.anadir("minecraft", "Dormir salta la noche; Las camas necesitan lana") == 2 and reglas.anadir("minecraft", "dormir salta la noche") == 0,
          "agregar reglas a mano, sin repetidas")
n0, msg0 = reglas.investigar("minecraft", Enrutador({"reflexion": ModeloFalso(_no)}), descargar=lambda e, t: (_ for _ in ()).throw(OSError("x")))
comprobar(n0 == 0 and "No pude leer la wiki" in msg0, "sin internet lo dice y sigue funcionando")
orig_get = reglas._get_json
reglas._get_json = lambda url, timeout=20: {"query": {"pages": {"1": {"title": "Creeper", "extract": "Explota cerca de ti."}}}}
comprobar(reglas.descargar_wiki("minecraft", "creeper") == ("Creeper", "Explota cerca de ti."), "lee el formato de la API de la wiki")
reglas._get_json = orig_get
reglas.borrar_todo("minecraft")
comprobar(reglas.listar("minecraft") == [], "se pueden borrar")
os.environ.pop("ARCHE_AGENTE_DIR", None)

print()
print("TODO BIEN." if not FALLOS else f"FALLARON {len(FALLOS)} comprobaciones:\n - " + "\n - ".join(FALLOS))
sys.exit(1 if FALLOS else 0)
