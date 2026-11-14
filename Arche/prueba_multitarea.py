"""
prueba_multitarea.py
--------------------
Comprueba la multitarea SIN abrir Arché, con herramientas de juguete
(no toca tu PC, ni internet, ni Ollama). Desde la carpeta Arche:

    python prueba_multitarea.py

Al final dice cuántas pruebas pasaron.
"""

import builtins
import io
import sys
import threading
import time

sys.path.insert(0, ".")
from core import multitarea as mt

resultados = []


def prueba(nombre, ok, detalle=""):
    resultados.append(ok)
    print(("  ✔ " if ok else "  ✖ ") + nombre + (f"  ({detalle})" if detalle and not ok else ""))


def esperar(condicion, seg=10):
    limite = time.time() + seg
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


# ---------------- herramientas de juguete ----------------
hechos = []
en_pantalla = {"ahora": 0, "maximo": 0}
candado_prueba = threading.Lock()


def herramienta_lenta(orden):
    if orden.startswith("investiga"):
        time.sleep(1.0)
        print(f"Arché: Investigué {orden[10:]}")
        hechos.append(orden)
        return ("investigar", orden)
    return None


def herramienta_pantalla(orden):
    if orden.startswith("abre") or orden.startswith("minimiza"):
        with candado_prueba:
            en_pantalla["ahora"] += 1
            en_pantalla["maximo"] = max(en_pantalla["maximo"], en_pantalla["ahora"])
        time.sleep(0.6)
        with candado_prueba:
            en_pantalla["ahora"] -= 1
        hechos.append(orden)
        print(f"Arché: Hecho: {orden}")
        return ("accion_pc", orden)
    return None


def herramienta_que_pregunta(orden, confirmar=input):
    if orden.startswith("borra"):
        r = confirmar("Arché: ¿Seguro que borro los temporales? [s/n]\nTú: ")
        hechos.append(f"borra:{r}")
        print("Arché: Borrados." if r == "s" else "Arché: No borré nada.")
        return ("borrar", orden)
    return None


def herramienta_rutina(orden):
    if orden == "modo estudio":
        return ("ejecutar_rutina", {"pasos": ["abre chrome", "espera 1", "minimiza spotify"]})
    return None


def herramienta_falla(orden):
    if orden.startswith("explota"):
        raise ValueError("falla de prueba")
    return None


pasadas_al_bucle = []
mt._al_bucle = lambda orden: pasadas_al_bucle.append(orden)

# capturar la consola
consola = io.StringIO()
real = sys.stdout
sys.stdout = consola

mt.configurar([
    ("investigar", herramienta_lenta),
    ("rutinas", herramienta_rutina),
    ("control del pc", herramienta_pantalla),
    ("borrar", herramienta_que_pregunta),
    ("falla", herramienta_falla),
])


def salida():
    return consola.getvalue()


def log(*a):
    real.write(" ".join(str(x) for x in a) + "\n")


sys.stdout = consola
try:
    # 1. frases que reconoce
    ok_partir = mt.partir_ordenes("investiga arduino y abre chrome") == ["investiga arduino", "abre chrome"]
    no_partir = mt.partir_ordenes("busca gatos y perros") == ["busca gatos y perros"]
    no_es = not mt.manejar("abre chrome") and not mt.manejar("hola como estas")

    # 2. dos tareas lentas a la vez: tardan ~1 s en total, no ~2 s
    t0 = time.time()
    mt.manejar("a la vez: investiga arduino y investiga python")
    hilo_libre = time.time() - t0 < 0.3          # el bucle no se quedó esperando
    termino = esperar(lambda: len([h for h in hechos if h.startswith("investiga")]) == 2, 5)
    paralelo = time.time() - t0 < 1.8

    # 3. salida con etiqueta
    etiqueta = "[tarea 1] Investigué" in salida() or "[tarea 2] Investigué" in salida()

    # 4. la pantalla se turna
    mt.manejar("al mismo tiempo abre chrome y abre spotify")
    esperar(lambda: hechos.count("abre chrome") + hechos.count("abre spotify") == 2, 5)
    turnos = en_pantalla["maximo"] == 1

    # 5. una investigación NO espera a la pantalla ocupada
    hechos.clear()
    mt.manejar("en segundo plano abre word")
    time.sleep(0.1)
    t0 = time.time()
    mt.manejar("de fondo investiga robots")
    esperar(lambda: "investiga robots" in hechos, 5)
    no_bloquea = time.time() - t0 < 1.4 and "abre word" in hechos  # word termina a los ~0.6 s
    esperar(lambda: not mt.tareas_vivas(), 5)

    # 6. pregunta: no roba el input; se responde con "tarea N sí"
    original_input = builtins.input
    robado = []
    mt._input_previo[0] = lambda p="": robado.append(p) or "x"
    tarea = mt.lanzar("borra temporales")
    pregunto = esperar(lambda: tarea.pregunta is not None, 5)
    mt.manejar(f"tarea {tarea.id} sí")
    respondio = esperar(lambda: "borra:s" in hechos, 5)
    no_robo = robado == []

    # 7. rutina de fondo: corre sus pasos
    hechos.clear()
    mt.manejar("busca... ")  # nada
    t = mt.lanzar("modo estudio")
    rutina = esperar(lambda: hechos == ["abre chrome", "minimiza spotify"], 6)

    # 8. una orden que ninguna herramienta reconoce pasa al bucle normal
    t = mt.lanzar("cuentame un chiste")
    al_bucle = esperar(lambda: pasadas_al_bucle == ["cuentame un chiste"], 5)

    # 9. un error no tumba nada
    t = mt.lanzar("explota ya")
    fallo = esperar(lambda: t.estado == "falló", 5)

    # 10. cancelar
    t = mt.lanzar("investiga algo largo")
    time.sleep(0.1)
    mt.manejar(f"para la tarea {t.id}")
    cancelada = esperar(lambda: t.estado == "cancelada", 5)

    # 11. listar
    antes = len(salida())
    mt.manejar("tareas")
    lista = "tarea 1:" in salida()[antes:]
finally:
    sys.stdout = real

print("PRUEBA DE MULTITAREA")
prueba("parte 'X y Y' cuando son dos órdenes", ok_partir)
prueba("no parte 'busca gatos y perros'", no_partir)
prueba("las órdenes normales siguen igual", no_es)
prueba("el bucle queda libre al mandar tareas", hilo_libre)
prueba("dos tareas lentas terminan", termino)
prueba("corren a la vez (no una tras otra)", paralelo)
prueba("lo que dice cada tarea sale con su etiqueta", etiqueta)
prueba("las que usan la pantalla se turnan", turnos, f"máximo a la vez: {en_pantalla['maximo']}")
prueba("investigar no espera a que se libere la pantalla", no_bloquea)
prueba("una tarea que pregunta avisa", pregunto)
prueba("'tarea N sí' le llega a la tarea", respondio)
prueba("la pregunta no se robó lo que escribes", no_robo)
prueba("una rutina corre sus pasos de fondo", rutina)
prueba("lo que no se puede de fondo pasa al bucle normal", al_bucle)
prueba("un error en una tarea no tumba a Arché", fallo)
prueba("'para la tarea N' la cancela", cancelada)
prueba("'tareas' muestra la lista", lista)
print(f"\n{sum(resultados)}/{len(resultados)} pruebas pasaron.")
if not all(resultados):
    print("\n--- consola de la prueba ---\n" + consola.getvalue())
    sys.exit(1)
