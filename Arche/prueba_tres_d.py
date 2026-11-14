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
    codigo, cuerpo = pedir("/api/cerebro", L)
    prueba("el mapa del cerebro trae los archivos de Arché", codigo == 200 and len(json.loads(cuerpo)["nodos"]) > 50)
    codigo, cuerpo = pedir("/api/perro", L)
    prueba("el perro trae sus movimientos", codigo == 200 and (not json.loads(cuerpo)["hay"] or "pararse" in json.loads(cuerpo)["secuencias"]))
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
