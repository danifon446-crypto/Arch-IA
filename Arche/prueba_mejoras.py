"""
prueba_mejoras.py
-----------------
Comprueba las mejoras de robustez (no toca tus datos reales: usa una carpeta
temporal). Desde la carpeta Arche:

    python prueba_mejoras.py
"""

import ast
import io
import json
import os
import shutil
import sys
import tempfile
import threading
from contextlib import redirect_stdout

sys.path.insert(0, ".")
resultados = []


def prueba(nombre, ok, detalle=""):
    resultados.append(bool(ok))
    print(("  ✔ " if ok else "  ✖ ") + nombre + (f"  ({detalle})" if detalle and not ok else ""))


CARPETA = tempfile.mkdtemp(prefix="arche_prueba_")
try:
    # ---------------- guardado atómico ----------------
    from core import guardado

    ruta = os.path.join(CARPETA, "datos.json")
    guardado.guardar_json(ruta, {"a": 1, "ñ": "canción"})
    prueba("guardar y leer", guardado.leer_json(ruta) == {"a": 1, "ñ": "canción"})
    guardado.guardar_json(ruta, {"a": 2})
    prueba("deja copia del anterior (.bak)", json.load(open(ruta + ".bak", encoding="utf-8")) == {"a": 1, "ñ": "canción"})
    prueba("no deja temporales tirados", [n for n in os.listdir(CARPETA) if n.endswith(".tmp")] == [])

    with open(ruta, "w", encoding="utf-8") as f:
        f.write('{"a": 2, "b": ')                      # archivo a medias, como tras un apagón
    with redirect_stdout(io.StringIO()) as salida:
        recuperado = guardado.leer_json(ruta, defecto={})
    prueba("archivo dañado: recupera la copia anterior", recuperado == {"a": 1, "ñ": "canción"})
    prueba("archivo dañado: no lo pisa y guarda una copia", os.path.exists(ruta + ".danado")
           and open(ruta, encoding="utf-8").read() == '{"a": 2, "b": ')
    prueba("archivo dañado: avisa", "dañado" in salida.getvalue())
    prueba("archivo que no existe: devuelve el valor por defecto",
           guardado.leer_json(os.path.join(CARPETA, "nada.json"), defecto=[]) == [])
    with redirect_stdout(io.StringIO()):
        prueba("tipo equivocado cuenta como dañado",
               guardado.leer_json(ruta + ".bak", defecto="x", tipo=list) == "x")

    # muchos hilos guardando a la vez: el archivo siempre queda entero
    ruta2 = os.path.join(CARPETA, "hilos.json")
    errores = []

    def escribir(n):
        try:
            for i in range(30):
                guardado.guardar_json(ruta2, {"hilo": n, "i": i, "relleno": "x" * 2000})
        except Exception as e:
            errores.append(e)

    def leer():
        for _ in range(200):
            if os.path.exists(ruta2):
                try:
                    json.load(open(ruta2, encoding="utf-8"))
                except ValueError as e:
                    errores.append(e)

    hilos = [threading.Thread(target=escribir, args=(n,)) for n in range(6)] + [threading.Thread(target=leer) for _ in range(3)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    prueba("6 hilos guardando y 3 leyendo: nunca se ve un archivo a medias", not errores, str(errores[:1]))

    # ---------------- configuración: un archivo dañado ya no la borra ----------------
    from core import configuracion

    original = configuracion.archivo_configuracion
    try:
        configuracion.archivo_configuracion = os.path.join(CARPETA, "configuracion.json")
        mia = dict(configuracion.CONFIG_DEFAULT)
        mia["_prueba"] = "mi ajuste"
        configuracion.guardar_config(mia)
        configuracion.guardar_config(mia)               # la segunda vez deja el .bak
        with open(configuracion.archivo_configuracion, "w", encoding="utf-8") as f:
            f.write("{ esto no es json")
        with redirect_stdout(io.StringIO()):
            cargada = configuracion.cargar_config()
        prueba("configuración dañada: conserva tus ajustes (antes volvía a fábrica)", cargada.get("_prueba") == "mi ajuste")
    finally:
        configuracion.archivo_configuracion = original

    # ---------------- control desde el celular: seguridad ----------------
    from core.interfaz import remoto

    prueba("celular: el PIN sale del generador seguro", len(remoto._pin_aleatorio()) == 6
           and remoto._pin_aleatorio().isdigit() and "secrets" in open(remoto.__file__, encoding="utf-8").read()
           and "random.randint" not in open(remoto.__file__, encoding="utf-8").read())
    fuente_remoto = open(remoto.__file__, encoding="utf-8").read()
    prueba("celular: PIN malo, red rechazada y orden delicada quedan en la bitácora",
           all(t in fuente_remoto for t in ('_auditar("pin_incorrecto"', '_auditar("conexion_rechazada_red"',
                                            '_auditar("orden_delicada_rechazada"')))

    # ---------------- nube de respaldo ----------------
    from core.IA import nube

    prueba("la nube de la red no se ofrece como respaldo",
           "solo_principal" in open(os.path.join("core", "IA", "cerebro.py"), encoding="utf-8").read()
           and nube.PROVEEDORES.get("red", {}).get("solo_principal") is True)

    # ---------------- parches de main.py (sobre una copia) ----------------
    import aplicar_parche_blindaje as blindaje
    import aplicar_parche_multitarea as multitarea_parche

    fuente = open("main.py", encoding="utf-8", newline="").read()
    for nombre, orden in (("blindaje y luego multitarea", (blindaje, multitarea_parche)),
                          ("multitarea y luego blindaje", (multitarea_parche, blindaje))):
        texto = fuente
        try:
            for parche in orden:
                texto, _ = parche.parchar(texto)
            ast.parse(texto)
            ok = "_error_orden" in texto and "multitarea_arche.manejar(comando_original)" in texto
        except Exception as e:
            ok = False
            nombre += f" -> {e}"
        prueba(f"parches de main.py: {nombre}", ok)

    # el blindaje de verdad atrapa un error y sigue
    mini = ("import time\n_cola_comandos_naturales = []\nvueltas = []\n"
            "while True:\n"
            "    vueltas.append(1)\n"
            "    texto = '''varias\n  líneas'''\n"
            "    if len(vueltas) == 1:\n"
            "        raise ValueError('bum')\n"
            "    if len(vueltas) == 3:\n"
            "        break\n"
            "    continue\n")
    blindado, _ = blindaje.parchar(mini)
    entorno = {}
    with redirect_stdout(io.StringIO()) as salida:
        exec(compile(blindado, "mini", "exec"), entorno)
    prueba("blindaje: una orden que falla no cierra el bucle", len(entorno["vueltas"]) == 3 and "error" in salida.getvalue())
    prueba("blindaje: no altera los textos de varias líneas", entorno["texto"] == "varias\n  líneas")
finally:
    shutil.rmtree(CARPETA, ignore_errors=True)

print(f"\n{sum(resultados)}/{len(resultados)} pruebas pasaron.")
sys.exit(0 if all(resultados) else 1)
