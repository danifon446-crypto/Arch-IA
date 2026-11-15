"""
prueba_tres_d.py
----------------
Comprueba Arché 3D sin abrir Arché ni tocar tus modelos (usa una carpeta
temporal). Desde la carpeta Arche:

    python prueba_tres_d.py
"""

import io
import json
import math
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import redirect_stdout

sys.path.insert(0, ".")
resultados = []


def prueba(nombre, ok, detalle=""):
    resultados.append(bool(ok))
    print(("  ✔ " if ok else "  ✖ ") + nombre + (f"  ({detalle})" if not ok and str(detalle) else ""))


def _sh_node():
    import shutil
    return shutil.which("node")


def _sp_run(cmd):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def callado(funcion, *a):
    salida = io.StringIO()
    with redirect_stdout(salida):
        r = funcion(*a)
    return r, salida.getvalue()


from core import tres_d
from core.tres_d import disenador as dis, geometria as geo, piezas, servidor

CARPETA = tempfile.mkdtemp(prefix="arche3d_prueba_")
original = dis.CARPETA
dis.CARPETA = CARPETA
try:
    print("GEOMETRÍA")
    cubo, _, _ = piezas.construir("caja", {"largo": 20, "ancho": 20, "alto": 20, "pared": 2, "redondeo": 0})
    macizo = piezas.desde_receta({"tipo": "caja", "medidas": [20, 30, 10]})
    prueba("un bloque de 20×30×10 mide 6 cm³", abs(macizo.volumen() - 6000) < 1e-6, macizo.volumen())
    prueba("y sus medidas son exactas", [round(v, 6) for v in macizo.dimensiones()] == [20, 30, 10])
    prueba("queda apoyado en la cama y centrado", abs(macizo.limites()[0][2]) < 1e-9 and abs(macizo.limites()[0][0] + 10) < 1e-9)
    ruta = os.path.join(CARPETA, "ida.stl")
    geo.escribir_stl(macizo, ruta)
    vuelta = geo.leer_modelo(ruta)
    prueba("guardar y abrir un STL conserva el volumen", abs(vuelta.volumen() - 6000) < 0.01 and vuelta.cerrada())
    with open(os.path.join(CARPETA, "texto.stl"), "w") as f:
        f.write("solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid t\n")
    abierta = geo.leer_modelo(os.path.join(CARPETA, "texto.stl"))
    prueba("abre STL de texto y detecta que NO está cerrado", len(abierta.caras) == 1 and not abierta.cerrada())
    with open(os.path.join(CARPETA, "c.obj"), "w") as f:
        f.write("v 0 0 0\nv 10 0 0\nv 10 10 0\nv 0 10 0\nv 0 0 5\nv 10 0 5\nv 10 10 5\nv 0 10 5\n"
                "f 1 4 3 2\nf 5 6 7 8\nf 1 2 6 5\nf 2 3 7 6\nf 3 4 8 7\nf 4 1 5 8\n")
    obj = geo.leer_modelo(os.path.join(CARPETA, "c.obj"))
    prueba("abre OBJ (caras de 4 lados) y mide bien", obj.cerrada() and abs(obj.volumen() - 500) < 1e-6)
    try:
        geo.leer_bytes(b"esto no es un modelo", ".stl")
        prueba("un archivo que no es STL se rechaza", False)
    except ValueError:
        prueba("un archivo que no es STL se rechaza", True)
    esp = geo.espejo(cubo, "x")
    prueba("el espejo conserva volumen y sigue cerrado", abs(esp.volumen() - cubo.volumen()) < 1e-6 and esp.cerrada())
    prueba("escalar al doble da 8 veces el volumen", abs(geo.escalar(macizo, 2).volumen() - 48000) < 1e-3)
    prueba("girar 90° en X cambia alto por ancho", [round(v, 4) for v in geo.rotar(macizo, "x", 90).dimensiones()] == [20, 10, 30])

    print("ANÁLISIS PARA IMPRIMIR")
    a = geo.analizar(macizo)
    prueba("bloque: cerrado, cabe y sin voladizos", a["cerrada"] and a["cabe"] and a["soporte_pct"] < 0.01 and not a["avisos"])
    prueba("el peso estimado es menor que macizo y mayor que cero", 0 < a["gramos"] < 6.0 * 1.24)
    mesa = piezas.desde_receta({"tipo": "union", "de": [{"tipo": "caja", "medidas": [60, 60, 4], "mover": [0, 0, 40]},
                                                         {"tipo": "cilindro", "diametro": 8, "alto": 40}]})
    am = geo.analizar(mesa)
    prueba("una mesa de una pata: detecta el voladizo", am["soporte_pct"] > 20, am["soporte_pct"])
    prueba("y recomienda voltearla", am["conviene_girar"] and am["mejor_orientacion"]["grados"] == 180)
    grande = piezas.desde_receta({"tipo": "caja", "medidas": [300, 20, 20]})
    prueba("avisa si no cabe en la impresora", not geo.analizar(grande)["cabe"])
    prueba("pero una de 250 de alto acostada sí cabe en diagonal de ejes", geo.analizar(geo.rotar(piezas.desde_receta({"tipo": "caja", "medidas": [20, 20, 200]}), "x", 90))["cabe"])

    print("CATÁLOGO")
    malas = []
    for nombre in piezas.CATALOGO:
        malla, _, _ = piezas.construir(nombre)
        if not malla.cerrada() or malla.volumen() <= 0:
            malas.append(nombre)
    prueba(f"las {len(piezas.CATALOGO)} piezas salen cerradas (imprimibles)", not malas, malas)
    eng, med, _ = piezas.construir("engranaje", {"dientes": 20, "modulo": 2})
    prueba("engranaje de 20 dientes módulo 2: diámetro exterior 44 mm", abs(max(eng.dimensiones()[:2]) - 44) < 0.2, eng.dimensiones())
    _, med, notas = piezas.construir("tubo", {"diametro": 10, "interior": 30})
    prueba("medidas imposibles se corrigen y se avisa", med["interior"] < 10 and notas)
    _, med, _ = piezas.construir("caja", {"largo": 1e9, "alto": "hola", "pared": float("nan")})
    prueba("medidas absurdas se recortan", med["largo"] == 400 and med["alto"] == 30 and med["pared"] == 2)
    servo, med, _ = piezas.construir("soporte_servo", {"modelo": "mg996r"})
    prueba("soporte de servo MG996R: 4 tornillos a 49,5 mm", abs(servo.dimensiones()[0] - (49.5 + 4.3 + 12)) < 0.01)
    try:
        piezas.desde_receta({"tipo": "diferencia", "de": [{"tipo": "caja", "medidas": [5, 5, 5]}, {"tipo": "caja", "medidas": [9, 9, 9], "mover": [0, 0, -1]}]})
        prueba("una receta que deja la pieza vacía se rechaza", False)
    except ValueError:
        prueba("una receta que deja la pieza vacía se rechaza", True)
    try:
        piezas.desde_receta({"tipo": "union", "de": [{"tipo": "caja"}] * 400})
        prueba("una receta gigante se rechaza", False)
    except ValueError:
        prueba("una receta gigante se rechaza", True)

    print("ENTENDER LO QUE PIDES")
    casos = [
        ("crea una caja de 80x50x30 con tapa", "caja", {"largo": 80, "ancho": 50, "alto": 30, "tapa": 1}),
        ("haz un tubo de 2 cm de diametro, 16 interior y 4cm de alto", "tubo", {"diametro": 20, "interior": 16, "alto": 40}),
        ("crea un engranaje de 24 dientes modulo 1.5 con agujero de 6", "engranaje", {"dientes": 24, "modulo": 1.5, "agujero": 6}),
        ("necesito una placa de 100 por 60 de 4 de grosor con 6 agujeros de 4", "placa",
         {"largo": 100, "ancho": 60, "grosor": 4, "agujeros_largo": 3, "agujeros_ancho": 2, "diametro_agujero": 4}),
        ("crea un separador de 12 de alto para tornillo m3 hexagonal", "separador", {"alto": 12, "agujero": 3.2, "hexagonal": 1}),
        ("hazme un soporte para servo MG996R", "soporte_servo", {"modelo": "mg996r"}),
        ("crea un cilindro de 8x5 cm", "cilindro", {"diametro": 80, "alto": 50}),
        ("crea una rueda de 80 de diámetro con 6 rayos y agujero de 8", "rueda", {"diametro": 80, "rayos": 6, "agujero": 8}),
    ]
    for frase, pieza, esperadas in casos:
        nombre, alias = dis.pieza_en(frase)
        medidas = dis.medidas_de(frase, nombre) if nombre else {}
        ok = nombre == pieza and all(abs(float(medidas.get(c, -1)) - v) < 1e-6 if not isinstance(v, str) else medidas.get(c) == v
                                     for c, v in esperadas.items())
        prueba(f"«{frase}»", ok, f"{nombre} {medidas}")

    r, _ = callado(tres_d.manejar, "crea una caja de 80x50x30")
    prueba("crear guarda el .stl y su receta", r and dis.existe("caja") and dis.leer_receta("caja")["medidas"]["largo"] == 80)
    callado(tres_d.manejar, "hazla más alta")
    prueba("«hazla más alta» sube el alto", dis.leer_receta("caja")["medidas"]["alto"] == 37.5)
    callado(tres_d.manejar, "cambia el ancho a 60")
    callado(tres_d.manejar, "ponle tapa")
    receta = dis.leer_receta("caja")["medidas"]
    prueba("«cambia el ancho a 60» y «ponle tapa»", receta["ancho"] == 60 and receta["tapa"] == 1)
    _, texto = callado(tres_d.manejar, "analiza el modelo")
    prueba("«analiza el modelo» da medidas, gramos y tiempo", all(t in texto for t in ("Mide", " g ", "impresión")))
    r, _ = callado(tres_d.manejar, "espejo del modelo")
    prueba("«espejo del modelo» crea la pieza del otro lado", dis.existe("caja_espejo"))
    callado(tres_d.manejar, "usa el modelo caja")
    r, _ = callado(tres_d.manejar, "escala el modelo al 50%")
    prueba("«escala el modelo al 50%»", abs(dis.abrir("caja").dimensiones()[2] - 18.75) < 0.01)
    callado(tres_d.manejar, "mi impresora es de 100x100x100")
    prueba("recuerda el tamaño de tu impresora", tres_d.ajustes()["cama"] == [100.0, 100.0, 100.0])
    ajenas = ["crea una nota comprar leche", "crea una caja", "haz una base de datos", "cambia el volumen a 50", "abre chrome",
              "analiza mi pc", "hazme un resumen", "pon musica", "rota la pantalla", "crea un recordatorio para mañana",
              "que hora es", "busca gatos en youtube", "mas volumen", "ahora abre spotify", "escala de grises"]
    coladas = [f for f in ajenas if callado(tres_d.manejar, f)[0] is not None]
    prueba("las órdenes que NO son de 3D pasan de largo", not coladas, coladas)

    respuestas = ['{"tipo":"cosa rara"}', '```json\n{"tipo":"diferencia","de":[{"tipo":"cilindro","diametro":40,"alto":3},'
                  '{"tipo":"cilindro","diametro":5,"alto":10,"mover":[0,15,-2]}]}\n```']
    archivo, malla, _ = dis.crear_libre("un llavero redondo", preguntar=lambda p: respuestas.pop(0))
    prueba("pieza libre: si la primera receta de la IA falla, corrige y arma la segunda", malla.cerrada() and dis.existe(archivo))
    prueba("los nombres de archivo no pueden salirse de la carpeta",
           dis._limpio("../../windows/system32/x.stl") == "x" and os.path.dirname(dis.ruta_stl("..\\..\\a")) == CARPETA)

    print("ARCHÉ AYUDA DE VERDAD")
    from core.tres_d import asistente
    mesa = piezas.desde_receta({"tipo": "union", "de": [{"tipo": "caja", "medidas": [60, 60, 4], "mover": [0, 0, 40]},
                                                        {"tipo": "cilindro", "diametro": 8, "alto": 40}]})
    dis.guardar("mesa", mesa, {"importado": "mesa.stl"})
    lista = asistente.sugerencias("mesa")["sugerencias"]
    prueba("mesa de una pata: propone voltearla, con números reales", lista and lista[0]["id"] == "orientar"
           and "cm²" in lista[0]["antes"] and lista[0]["orden"])
    callado(tres_d.manejar, "usa el modelo mesa")
    _, texto = callado(tres_d.manejar, "arregla la pieza")
    prueba("«arregla la pieza» lo aplica y el voladizo de verdad baja", geo.analizar(dis.abrir("mesa"))["soporte_pct"] < 1, texto[:120])
    prueba("después ya no propone arreglos", not [x for x in asistente.sugerencias("mesa")["sugerencias"] if x["tipo"] == "arreglo"])
    callado(tres_d.manejar, "crea una caja de 300x40x30 con pared de 0.8")
    nueva_caja = dis.ultimo()
    ids = [x["id"] for x in asistente.sugerencias(nueva_caja)["sugerencias"]]
    prueba("caja que no cabe y de pared fina: propone escalar y engrosar", "escalar_para_caber" in ids and "pared" in ids, ids)
    callado(tres_d.manejar, "aplica la sugerencia 1")
    prueba("«aplica la sugerencia 1» la deja cabiendo en la impresora", geo.analizar(dis.abrir(nueva_caja), cama=tres_d.ajustes()["cama"])["cabe"])
    largo = piezas.desde_receta({"tipo": "caja", "medidas": [20, 20, 200]})
    dis.guardar("larga", geo.rotar(largo, "x", 90), {"importado": "larga.stl"})
    callado(tres_d.manejar, "mi impresora es de 220x220x150")
    dis.guardar("alta", largo, {"importado": "alta.stl"})
    ids = [x["id"] for x in asistente.sugerencias("alta")["sugerencias"]]
    prueba("si girándola cabe, propone girar (no achicarla)", "girar_para_caber" in ids and "escalar_para_caber" not in ids, ids)
    callado(tres_d.manejar, "mi impresora es de 220x220x250")
    callado(tres_d.manejar, "crea un engranaje de 20 dientes modulo 2")
    _, texto = callado(tres_d.manejar, "hazle un compañero de 40 dientes")
    comp = dis.leer_receta(dis.ultimo())["medidas"]
    prueba("engranaje compañero: mismo módulo y te dice a cuánto poner los ejes",
           comp["dientes"] == 40 and comp["modulo"] == 2 and "60.0 mm" in texto)
    import numpy as np
    sopa = mesa.vertices[mesa.caras].reshape(-1, 3) + np.random.RandomState(1).uniform(-2e-4, 2e-4, (len(mesa.caras) * 3, 3))
    dis.guardar("rota", geo.Malla(sopa, np.arange(len(sopa)).reshape(-1, 3)), {"importado": "rota.stl"})
    prueba("una malla con puntos sueltos se detecta y se ofrece reparar",
           not dis.abrir("rota").cerrada() and "reparar" in [x["id"] for x in asistente.sugerencias("rota")["sugerencias"]])
    callado(tres_d.manejar, "repara el modelo rota")
    prueba("«repara el modelo» la deja cerrada", dis.abrir("rota").cerrada())
    agujereada = geo.Malla(mesa.vertices, mesa.caras[:-2])
    dis.guardar("agujero", agujereada, {"importado": "a.stl"})
    _, texto = callado(tres_d.manejar, "repara el modelo agujero")
    prueba("si no se puede reparar lo dice (y no daña el archivo)", "No pude" in texto and not dis.abrir("agujero").cerrada())
    ele = piezas.desde_receta({"tipo": "union", "de": [{"tipo": "caja", "medidas": [40, 10, 5]}, {"tipo": "caja", "medidas": [10, 30, 5], "mover": [15, 10, 0]}]})
    dis.guardar("ele", ele, {"importado": "ele.stl"})
    prueba("ofrece el espejo solo si la pieza no es simétrica",
           "espejo" in [x["id"] for x in asistente.sugerencias("ele")["sugerencias"]]
           and "espejo" not in [x["id"] for x in asistente.sugerencias("mesa")["sugerencias"]])

    print("CONSTRUIR (armar piezas con partes)")
    from core.tres_d import construir as con
    soporte = [{"id": "base", "forma": "caja", "medidas": {"x": 50, "y": 30, "z": 4}, "pos": [0, 0, 0]},
               {"id": "pared", "forma": "caja", "medidas": {"x": 4, "y": 30, "z": 40}, "pos": [-23, 0, 4]},
               {"id": "ag1", "forma": "cilindro", "restar": True, "medidas": {"diametro": 4.3, "alto": 10}, "pos": [10, 0, -3]},
               {"id": "ag2", "forma": "cilindro", "restar": True, "medidas": {"diametro": 4.3, "alto": 10}, "pos": [-27, 0, 28], "rot": [0, 90, 0]}]
    malla, info = con.construir(soporte)
    caja_llena = 50 * 30 * 4 + 4 * 30 * 40
    agujeros = math.pi * (4.3 / 2) ** 2 * 4 * 2
    prueba("soporte en L con 2 agujeros: una sola pieza cerrada", malla.cerrada() and info["trozos"] == 1 and not info["avisos"], info["avisos"])
    prueba("el volumen es exacto (bloques menos agujeros)", abs(malla.volumen() - (caja_llena - agujeros)) < caja_llena * 0.01,
           f"{malla.volumen():.0f} vs {caja_llena - agujeros:.0f}")
    prueba("las medidas totales son las de las partes", [round(v, 3) for v in info["dimensiones"]] == [50, 30, 44], info["dimensiones"])
    _, info = con.construir(soporte + [{"id": "m3", "forma": "cilindro", "restar": True, "medidas": {"diametro": 3, "alto": 10}, "pos": [-10, 0, -3]}])
    av = [a for a in info["avisos"] if a["id"] == "tornillo_m3"]
    prueba("un agujero de 3 mm justos: avisa y propone 3,2 para un M3", av and av[0]["cambio"]["valor"] == 3.2)
    lejos = soporte + [{"id": "bola", "forma": "esfera", "medidas": {"diametro": 12}, "pos": [90, 0, 0]}]
    _, info = con.construir(lejos)
    prueba("una parte suelta: dice en cuántos trozos queda y cuál es", info["trozos"] == 2 and "suelta" in info["problemas"].get("bola", []))
    mov = info["juntar"].get("bola")
    lejos[-1]["pos"] = [a + b for a, b in zip(lejos[-1]["pos"], mov)]
    _, info = con.construir(lejos)
    prueba("«Juntarlas» calcula cuánto moverla y queda una sola pieza", info["trozos"] == 1, info["avisos"])
    _, info = con.construir(soporte + [{"id": "fuera", "forma": "cilindro", "restar": True, "medidas": {"diametro": 5, "alto": 5}, "pos": [150, 0, 0]}])
    prueba("un agujero que no corta nada: avisa", "no_corta" in info["problemas"].get("fuera", []))
    try:
        con.construir([{"forma": "cilindro", "restar": True, "medidas": {"diametro": 5, "alto": 5}}])
        prueba("solo agujeros: lo rechaza con un mensaje claro", False)
    except ValueError as e:
        prueba("solo agujeros: lo rechaza con un mensaje claro", "sólida" in str(e))
    try:
        con.construir([{"forma": "caja", "medidas": {"x": 10, "y": 10, "z": 10}}] * 100)
        prueba("demasiadas partes: lo rechaza", False)
    except ValueError:
        prueba("demasiadas partes: lo rechaza", True)
    girada = [{"forma": "caja", "medidas": {"x": 40, "y": 10, "z": 10}, "pos": [0, 0, 0], "rot": [0, 0, 90]}]
    prueba("girar 90° en Z cambia largo por ancho", [round(v, 3) for v in con.construir(girada)[1]["dimensiones"]] == [10, 40, 10])
    dis.guardar("bloque", piezas.desde_receta({"tipo": "caja", "medidas": [20, 20, 20]}), {"importado": "bloque.stl"})
    _, info = con.construir([{"forma": "modelo", "modelo": "bloque", "medidas": {"escala": 1}, "pos": [0, 0, 0]},
                             {"forma": "cilindro", "restar": True, "medidas": {"diametro": 8, "alto": 30}, "pos": [0, 0, -2]}])
    prueba("se puede usar una pieza guardada como parte (y agujerearla)", info["trozos"] == 1 and info["volumen_cm3"] < 8.0)

    print("MODELAR (estilo Blender)")
    def _cubo(x0, lado=10):
        v = [[x0 + i * lado, j * lado, k * lado] for i in (0, 1) for j in (0, 1) for k in (0, 1)]
        f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]
        return {"v": [c for p in v for c in p], "f": [i for t in f for i in t]}
    m, info = con.unir_mallas([_cubo(0), _cubo(5)])
    prueba("unir objetos que se tocan: una sola pieza con el volumen justo", info["trozos"] == 1 and abs(m.volumen() - 1500) < 1, info)
    m, info = con.unir_mallas([_cubo(0), _cubo(50)])
    prueba("objetos separados: avisa que salen en 2 trozos", info["trozos"] == 2 and any("2" in a for a in info["avisos"]), info["avisos"])
    abierto = _cubo(0); abierto["f"] = abierto["f"][:-3]
    try:
        con.unir_mallas([abierto])
        prueba("una malla abierta sola: lo rechaza con un mensaje claro", False)
    except ValueError:
        prueba("una malla abierta sola: lo rechaza con un mensaje claro", True)
    if _sh_node():
        r = _sp_run(["node", os.path.join("core", "tres_d", "web", "pruebas", "prueba_mallas.mjs")])
        ultima = (r.stdout.strip().splitlines() or ["?"])[-1]
        prueba(f"editar mallas (extruir, esculpir, modificadores): {ultima}", r.returncode == 0, r.stdout[-600:])

    print("GESTOS (con manos simuladas)")
    import shutil as _sh, subprocess as _sp
    if _sh.which("node"):
        r = _sp.run(["node", os.path.join("core", "tres_d", "web", "pruebas", "prueba_gestos.mjs")], capture_output=True, text=True, encoding="utf-8")
        ultima = (r.stdout.strip().splitlines() or ["?"])[-1]
        prueba(f"gestos de la mano: {ultima}", r.returncode == 0, r.stdout[-600:])
    else:
        print("  · (no tienes Node.js: me salto las pruebas de gestos; el taller funciona igual)")

    print("EL TALLER (servidor)")
    ok, _ = servidor.iniciar()
    base = servidor.direccion()

    def pedir(ruta, llave=None, datos=None, anfitrion=None):
        cab = {}
        if llave:
            cab["X-Arche-Llave"] = llave
        if anfitrion:
            cab["Host"] = anfitrion
        cuerpo = None if datos is None else (datos if isinstance(datos, bytes) else json.dumps(datos).encode())
        try:
            with urllib.request.urlopen(urllib.request.Request(base + ruta, data=cuerpo, headers=cab), timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    L = servidor._llave
    prueba("arranca solo en este PC (127.0.0.1)", ok and servidor._servidor.server_address[0] == "127.0.0.1")
    prueba("la página carga", pedir("/")[0] == 200 and b"three" in pedir("/")[1])
    prueba("sin llave no entrega datos", pedir("/api/modelos")[0] == 401 and pedir("/api/modelo?n=caja")[0] == 401)
    prueba("con llave equivocada tampoco", pedir("/api/modelos", "x" * 32)[0] == 401)
    prueba("sin llave no acepta órdenes", pedir("/api/orden", None, {"texto": "crea una esfera de 30"})[0] == 401 and not dis.existe("esfera"))
    prueba("un pedido dirigido a otro nombre de sitio se rechaza", pedir("/api/modelos", L, anfitrion="sitio-malo.com")[0] == 403)
    prueba("con llave entrega la lista", pedir("/api/modelos", L)[0] == 200)
    codigo, cuerpo = pedir("/api/orden", L, {"texto": "crea una esfera de 30"})
    prueba("con llave acepta órdenes de 3D", codigo == 200 and json.loads(cuerpo)["ok"] and dis.existe("esfera"))
    codigo, cuerpo = pedir("/api/orden", L, {"texto": "apaga el pc"})
    prueba("lo que no es 3D no pasa de la página", codigo == 200 and not json.loads(cuerpo)["ok"])
    prueba("no entrega archivos fuera del taller", pedir("/../../main.py", L)[0] == 404 and pedir("/api/modelo?n=../../main", L)[0] == 404)
    codigo, cuerpo = pedir("/api/medidas", L, {"n": "esfera", "medidas": {"diametro": 50}})
    prueba("los deslizadores rehacen la pieza", codigo == 200 and abs(dis.abrir("esfera").dimensiones()[0] - 50) < 0.01)
    with open(dis.ruta_stl("esfera"), "rb") as f:
        codigo, cuerpo = pedir("/api/subir?n=..%2F..%2Fmala.stl", L, f.read())
    prueba("subir un STL lo guarda dentro de la carpeta de modelos", codigo == 200 and dis.existe("mala") and not os.path.exists(os.path.join(os.path.dirname(CARPETA), "mala.stl")))
    prueba("subir basura se rechaza", pedir("/api/subir?n=x.stl", L, b"no soy un stl")[0] == 400 and pedir("/api/subir?n=x.exe", L, b"MZ")[0] == 400)
    codigo, cuerpo = pedir("/api/sugerencias?n=mesa", L)
    prueba("la página recibe las sugerencias de Arché", codigo == 200 and "sugerencias" in json.loads(cuerpo))
    prueba("las sugerencias también piden la llave", pedir("/api/sugerencias?n=mesa")[0] == 401)
    codigo, cuerpo = pedir("/api/construir", L, {"partes": soporte})
    r = json.loads(cuerpo)
    prueba("Construir: la página recibe la vista previa exacta", codigo == 200 and r["ok"] and len(r["stl"]) > 1000)
    codigo, cuerpo = pedir("/api/construir", L, {"partes": soporte, "guardar": "../soporte l"})
    r = json.loads(cuerpo)
    prueba("Construir: guarda la pieza (con nombre seguro) y sus partes para editarla", r.get("nombre") == "soporte_l"
           and len(json.loads(pedir("/api/partes?n=soporte_l", L)[1])["partes"]) == 4)
    prueba("Construir: sin llave no arma ni guarda nada", pedir("/api/construir", None, {"partes": soporte, "guardar": "x"})[0] == 401
           and not dis.existe("x"))
    prueba("Construir: un pedido mal hecho da un error claro, no tumba el servidor",
           pedir("/api/construir", L, {"partes": [{"forma": "dragon"}]})[0] == 400 and pedir("/", None)[0] == 200)
    codigo, cuerpo = pedir("/api/modelar", L, {"nombre": "../mi escultura", "objetos": [_cubo(0), _cubo(5)], "escena": {"version": 1, "objetos": []}})
    r = json.loads(cuerpo)
    prueba("Modelar: guarda la pieza unida (nombre seguro) y la escena para seguir editando",
           codigo == 200 and r.get("nombre") == "mi_escultura" and dis.existe("mi_escultura")
           and json.loads(pedir("/api/escena?n=mi_escultura", L)[1])["escena"]["version"] == 1, cuerpo[:300])
    codigo, cuerpo = pedir("/api/modelar", L, {"nombre": "mi escultura", "reemplazar": True, "objetos": [_cubo(0, 20)], "escena": {}})
    prueba("Modelar: «guardar cambios» reemplaza la misma pieza", codigo == 200 and json.loads(cuerpo)["nombre"] == "mi_escultura"
           and abs(dis.abrir("mi_escultura").volumen() - 8000) < 1)
    prueba("Modelar: sin llave no guarda", pedir("/api/modelar", None, {"nombre": "y", "objetos": [_cubo(0)]})[0] == 401 and not dis.existe("y"))
    prueba("Modelar: basura da error claro", pedir("/api/modelar", L, {"nombre": "z", "objetos": [{"v": [1, 2], "f": [0, 9, 9]}]})[0] == 400
           and pedir("/modelar.js")[0] == 200 and pedir("/malla_edit.js")[0] == 200)
    codigo, cuerpo = pedir("/api/cerebro", L)
    prueba("el mapa del cerebro trae los archivos de Arché", codigo == 200 and len(json.loads(cuerpo)["nodos"]) > 50)
    codigo, cuerpo = pedir("/api/perro", L)
    prueba("el perro trae sus movimientos", codigo == 200 and (not json.loads(cuerpo)["hay"] or "pararse" in json.loads(cuerpo)["secuencias"]))
    print("CONTROL CON LAS MANOS")
    codigo, cuerpo = pedir("/manos.js")
    prueba("la página trae el control con las manos", codigo == 200 and b"getUserMedia" in cuerpo and pedir("/gestos.js")[0] == 200)
    codigo, cuerpo = pedir("/lib/manos/hands_solution_simd_wasm_bin.wasm")
    prueba("el detector de manos viene incluido (funciona sin internet)", codigo == 200 and cuerpo[:4] == b"\0asm"
           and pedir("/lib/manos/hand_landmark_full.tflite")[0] == 200)
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        politica = r.headers.get("Content-Security-Policy", "")
        permisos = r.headers.get("Permissions-Policy", "")
    prueba("la página puede usar la cámara, pero no el micrófono ni la ubicación",
           "wasm-unsafe-eval" in politica and "camera=(self)" in permisos and "microphone=()" in permisos)
    abiertas = []
    servidor.abrir_navegador, abrir_original = (lambda pestana="taller": abiertas.append(pestana)), servidor.abrir_navegador
    try:
        r, _ = callado(tres_d.manejar, "controla con las manos")
        prueba("«controla con las manos» abre el taller con la cámara", r == ("tres_d", "manos") and abiertas == ["taller+manos"])
        pedir("/api/estado", L)                                      # una página abierta pregunta
        antes = json.loads(pedir("/api/estado", L)[1])["pedidos"]["manos"]
        callado(tres_d.manejar, "activa el control con las manos")
        despues = json.loads(pedir("/api/estado", L)[1])["pedidos"]["manos"]
        prueba("con el taller ya abierto, la enciende ahí (no abre otra pestaña)", despues == antes + 1 and len(abiertas) == 1)
        antes = json.loads(pedir("/api/estado", L)[1])["pedidos"]["ir"]
        r, _ = callado(tres_d.manejar, "quiero esculpir")
        e = json.loads(pedir("/api/estado", L)[1])["pedidos"]
        prueba("«quiero esculpir» abre Modelar en la página", r == ("tres_d", "modelar") and e["ir"] == antes + 1 and e["ir_a"]["vista"] == "modelar")
        r, _ = callado(tres_d.manejar, "edita mi escultura en modelar")
        prueba("«edita X en modelar» la abre ahí", r == ("tres_d", "modelar") and json.loads(pedir("/api/estado", L)[1])["pedidos"]["ir_a"]["modelo"] == "mi_escultura")
        prueba("«estilo blender» también", callado(tres_d.manejar, "estilo blender")[0] == ("tres_d", "modelar"))
        prueba("«lávate las manos» no es una orden de 3D", callado(tres_d.manejar, "lavate las manos")[0] is None)
    finally:
        servidor.abrir_navegador = abrir_original
    servidor.detener()
    prueba("al cerrarlo deja de responder", not servidor.activo())

    print("CONEXIÓN CON main.py (sobre una copia)")
    import aplicar_parche_tres_d as parche
    fuente = open("main.py", encoding="utf-8", newline="").read()
    nuevo, _ = parche.parchar(fuente)
    import ast
    ast.parse(nuevo)
    prueba("el parche conecta el 3D y main.py sigue compilando",
           "tres_d_arche.manejar(comando_original)" in nuevo and "tres_d_arche.detener_todo()" in nuevo)
    prueba("aplicarlo dos veces no cambia nada", parche.parchar(nuevo) == (nuevo, False))
finally:
    servidor.detener()
    dis.CARPETA = original
    shutil.rmtree(CARPETA, ignore_errors=True)

print(f"\n{sum(resultados)}/{len(resultados)} pruebas pasaron.")
sys.exit(0 if all(resultados) else 1)
