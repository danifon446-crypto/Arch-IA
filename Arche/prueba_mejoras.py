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

    # ---------------- velocidad: mismo resultado, mucho más rápido ----------------
    import hashlib
    import random
    import time
    import numpy as np
    from core.IA import aprendizaje, catalogo, embeddings, rapido, respuestas

    def emb_falso(texto):
        rng = np.random.RandomState(int(hashlib.md5(texto.encode()).hexdigest()[:8], 16))
        v = rng.randn(64)
        return (v / np.linalg.norm(v)).tolist()

    guardados = (aprendizaje.ARCHIVO, respuestas.ARCHIVO, embeddings.calcular_embedding,
                 aprendizaje._predecir_con_clasificador, aprendizaje._reentrenar_si_corresponde)
    try:
        aprendizaje.ARCHIVO = os.path.join(CARPETA, "conocimiento.json")
        respuestas.ARCHIVO = os.path.join(CARPETA, "respuestas.json")
        embeddings.calcular_embedding = emb_falso
        aprendizaje._predecir_con_clasificador = lambda v, texto=None: (None, 0.0)
        aprendizaje._reentrenar_si_corresponde = lambda: None
        rng, ejemplos, vistos = random.Random(3), [], set()
        entradas = list(catalogo.POR_ID.values())
        while len(ejemplos) < 600:
            e = rng.choice(entradas)
            for frase, contenido in catalogo.expandir_semillas(e, max_por_semilla=2, rng=rng):
                f = aprendizaje._normalizar(frase)
                if f in vistos:
                    continue
                vistos.add(f)
                c = aprendizaje._normalizar(contenido) if contenido else ""
                t = aprendizaje._extraer_template(f, c) or f
                ejemplos.append({"pregunta": f, "accion": e["id"], "contenido": contenido or "", "fuente": "prueba",
                                 "template": t, "regex": aprendizaje._template_a_regex(t), "embedding": emb_falso(f)})
        aprendizaje.guardar(ejemplos)
        respuestas.guardar([{"pregunta": f"pregunta {i}", "respuesta": "una respuesta larga que sirve de verdad " * 2,
                             "embedding": emb_falso(f"pregunta {i}"), "veces_usada": 1} for i in range(80)])
        frases = [ejemplos[5]["pregunta"], ejemplos[300]["pregunta"] + " ya", "cuentame algo de los agujeros negros",
                  "abreme el navegador porfa", "pon una alarma mañana temprano", "pregunta 7", "organiza mis descargas ya"]

        def correr():
            with redirect_stdout(io.StringIO()):
                return [(aprendizaje.resolver(f), respuestas.buscar_respuesta(f)) for f in frases]

        rapido.olvidar()
        t0 = time.perf_counter(); con_rapido = correr(); t_rapido = time.perf_counter() - t0
        # el camino de siempre: sin memoria, sin matriz, sin filtro (así era antes)
        originales = (rapido.cargar, rapido.puntajes, rapido.puede_cubrir)
        rapido.cargar = lambda ruta, leer: leer()
        rapido.puntajes = lambda datos, vector: None
        rapido.puede_cubrir = lambda frase, parte, umbral: True
        try:
            respuestas.guardar(respuestas.cargar())          # deja el archivo como estaba antes de los aciertos
            t0 = time.perf_counter(); sin_rapido = correr(); t_lento = time.perf_counter() - t0
        finally:
            rapido.cargar, rapido.puntajes, rapido.puede_cubrir = originales
        prueba("entender una orden: el camino rápido decide EXACTAMENTE lo mismo", con_rapido == sin_rapido)
        prueba("y alguna de las frases de prueba sí se resolvió", any(r for r, _ in con_rapido) and any(b for _, b in con_rapido))
        prueba(f"es más rápido ({t_lento / max(t_rapido, 1e-9):.0f} veces con 600 ejemplos)", t_rapido < t_lento)
        with redirect_stdout(io.StringIO()):
            aprendizaje.aprender("frase recien aprendida de prueba", "hora", "")
            nuevo = aprendizaje.resolver("frase recien aprendida de prueba")
        prueba("lo recién aprendido se usa enseguida", nuevo == {"accion": "hora", "contenido": ""})
        prueba("el archivo guardado sigue siendo JSON normal", len(json.load(open(aprendizaje.ARCHIVO, encoding="utf-8"))) == len(ejemplos) + 1)
        # si OTRO programa cambia el archivo, se nota y se vuelve a leer
        otros = json.load(open(aprendizaje.ARCHIVO, encoding="utf-8"))[:10]
        time.sleep(0.02)
        with open(aprendizaje.ARCHIVO, "w", encoding="utf-8") as f:
            json.dump(otros, f)
        prueba("si el archivo cambia por fuera, se vuelve a leer", len(aprendizaje.cargar()) == 10)
        copia = aprendizaje.cargar()
        copia[0]["accion"] = "cambiada"
        prueba("lo que entrega es una copia (modificarla no daña la memoria)", aprendizaje.cargar()[0]["accion"] != "cambiada")
    finally:
        (aprendizaje.ARCHIVO, respuestas.ARCHIVO, embeddings.calcular_embedding,
         aprendizaje._predecir_con_clasificador, aprendizaje._reentrenar_si_corresponde) = guardados
        rapido.olvidar()

    class _ModeloFalso:
        llamadas = 0

        def encode(self, texto, normalize_embeddings=True):
            _ModeloFalso.llamadas += 1
            return np.ones(4, dtype=np.float32)

    modelo_antes, config_antes = embeddings._modelo, embeddings._config
    try:
        embeddings._modelo, embeddings._config = _ModeloFalso(), {"nombre": "prueba", "modelo": "prueba", "prefijo": ""}
        embeddings._recientes.clear()
        uno = embeddings.calcular_embedding("hola"); uno.append(9)
        dos = embeddings.calcular_embedding("hola")
        prueba("la misma frase no se convierte dos veces (y se entrega copia)", _ModeloFalso.llamadas == 1 and len(dos) == 4)
    finally:
        embeddings._modelo, embeddings._config = modelo_antes, config_antes
        embeddings._recientes.clear()

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
