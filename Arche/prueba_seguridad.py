"""
prueba_seguridad.py
-------------------
Ubicacion: Arche/prueba_seguridad.py

Prueba (sin internet, sin Ollama, sin tocar tu Database ni tus ajustes):

  * core/IA/revisar_propuestas.py: leer el diccionario de preguntas frecuentes ya NO ejecuta
    el archivo (un texto malicioso dentro no corre) y un archivo roto no se confunde con
    "vacio" (porque eso borraria lo que ya habia al aplicar la siguiente propuesta).
  * core/interfaz/remoto.py: el servidor del celular pide PIN, bloquea tras 5 fallos y tras
    demasiados fallos en total, NO acepta desde el celular las ordenes delicadas, y manda
    cabeceras de seguridad. Se levanta un servidor real en 127.0.0.1 con un puerto libre.

Correr:  python prueba_seguridad.py
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from core.IA import revisar_propuestas  # noqa: E402
from core.interfaz import ajustes, datos, en_vivo, entrada, remoto  # noqa: E402

fallos = []


def chequear(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}")
    else:
        print(f"FALLA {nombre}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")
        fallos.append(nombre)


# ---- revisar_propuestas: leer sin ejecutar ---------------------------------------------------
with tempfile.TemporaryDirectory() as carpeta:
    carpeta = Path(carpeta)
    archivo = carpeta / "preguntas_frecuentes.py"
    marca = carpeta / "SE_EJECUTO.txt"

    with mock.patch.object(revisar_propuestas, "ARCHIVO_EDITABLE", archivo):
        archivo.write_text('"""doc"""\n\nPREGUNTAS_FRECUENTES = {\n    # nada aun\n}\n', encoding="utf-8")
        chequear("faq: diccionario vacio", revisar_propuestas.leer_diccionario_actual(), {})

        datos_ok = {"que hora es": "Mira el reloj.", "hola": "Hola, soy Arche."}
        archivo.write_text(revisar_propuestas.generar_codigo_diccionario(datos_ok), encoding="utf-8")
        chequear("faq: lee lo que genero el propio sistema", revisar_propuestas.leer_diccionario_actual(), datos_ok)

        archivo.write_text(
            f'import os\nopen({str(marca)!r}, "w").write("x")\n\nPREGUNTAS_FRECUENTES = {{"a": "b"}}\n',
            encoding="utf-8")
        chequear("faq: lee el diccionario aunque haya otras lineas", revisar_propuestas.leer_diccionario_actual(), {"a": "b"})
        chequear("faq: NO ejecuta el archivo", marca.exists(), False)

        archivo.write_text(
            f'PREGUNTAS_FRECUENTES = {{"a": open({str(marca)!r}, "w").write("x") or "b"}}\n', encoding="utf-8")
        try:
            revisar_propuestas.leer_diccionario_actual()
            lanzo = False
        except (ValueError, SyntaxError):
            lanzo = True
        chequear("faq: algo que no es un literal se rechaza (no se confunde con vacio)", lanzo, True)
        chequear("faq: y tampoco se ejecuto", marca.exists(), False)

        archivo.write_text("PREGUNTAS_FRECUENTES = {\n", encoding="utf-8")
        try:
            revisar_propuestas.leer_diccionario_actual()
            lanzo = False
        except SyntaxError:
            lanzo = True
        chequear("faq: archivo roto lanza error (no devuelve vacio)", lanzo, True)

# ---- remoto: que ordenes no acepta desde el celular --------------------------------------------
bloqueadas = [
    "apaga el pc", "Apaga el PC", "reinicia el computador", "suspende el pc", "cierra la sesión",
    "teclea hola mundo", "presiona enter", "cambia esto: borra algo", "deshaz el ultimo cambio",
    "revísate y arregla todo", "pon la mejora en nivel total", "guarda la clave gsk_123",
    "comparte mi memoria con la nube", "borra todos los archivos de descargas", "elimina la carpeta fotos",
    "instala vlc", "ejecuta el script",
]
permitidas = [
    "pon musica en spotify", "busca el contrato en mis documentos", "que hora es", "sube el volumen",
    "borra la nota 3", "abre youtube", "enciende el pc", "dame las noticias de tecnologia",
    "crea una nota comprar leche", "como esta el clima en bogota",
]
for orden in bloqueadas:
    chequear(f"orden delicada bloqueada: {orden}", remoto.es_orden_solo_pc(orden), True)
for orden in permitidas:
    chequear(f"orden normal permitida: {orden}", remoto.es_orden_solo_pc(orden), False)
with mock.patch.dict(os.environ, {"ARCHE_CELULAR_PERMITE_TODO": "1"}):
    chequear("el interruptor de entorno las permite todas", remoto.es_orden_solo_pc("apaga el pc"), False)

# ---- remoto: servidor real en 127.0.0.1 -----------------------------------------------------------
PIN = "123456"
recibidas = []


def pedir(servidor, metodo, ruta, pin=None, cuerpo=None):
    url = f"http://127.0.0.1:{servidor.server_address[1]}{ruta}"
    peticion = urllib.request.Request(url, method=metodo)
    if pin is not None:
        peticion.add_header("X-Pin", pin)
    datos_ = None
    if cuerpo is not None:
        datos_ = json.dumps(cuerpo).encode()
        peticion.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(peticion, data=datos_, timeout=5) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def reiniciar_fallos():
    remoto._fallos.clear()
    remoto._fallos_globales.clear()


with mock.patch.object(ajustes, "obtener", lambda clave: PIN if clave == "celular_pin" else 8765), \
        mock.patch.object(ajustes, "fijar", lambda *a, **k: None), \
        mock.patch.object(en_vivo, "sondear", lambda: None), \
        mock.patch.object(en_vivo, "estado_visual", lambda: "quieto"), \
        mock.patch.object(datos, "controles", lambda: []), \
        mock.patch.object(entrada, "enviar", lambda texto, origen: recibidas.append((texto, origen))), \
        mock.patch.object(remoto, "_auditar", lambda *a, **k: None):     # no escribir en tu bitacora real

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), remoto._Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        reiniciar_fallos()
        codigo, cuerpo, cab = pedir(servidor, "GET", "/")
        chequear("servidor: la pagina carga sin PIN", codigo, 200)
        chequear("servidor: cabecera nosniff", cab.get("X-Content-Type-Options"), "nosniff")
        chequear("servidor: cabecera no-frame", cab.get("X-Frame-Options"), "DENY")
        chequear("servidor: cabecera sin referrer", cab.get("Referrer-Policy"), "no-referrer")
        chequear("servidor: la pagina avisa si una orden fue rechazada", "d.mensaje" in cuerpo, True)

        chequear("servidor: estado sin PIN -> 401", pedir(servidor, "GET", "/api/estado")[0], 401)
        chequear("servidor: estado con PIN malo -> 401", pedir(servidor, "GET", "/api/estado", "000000")[0], 401)
        reiniciar_fallos()
        chequear("servidor: estado con PIN bueno -> 200", pedir(servidor, "GET", "/api/estado", PIN)[0], 200)

        reiniciar_fallos()
        recibidas.clear()
        codigo, cuerpo, _ = pedir(servidor, "POST", "/api/enviar", PIN, {"texto": "pon musica en spotify"})
        chequear("servidor: orden normal -> ok", (codigo, json.loads(cuerpo)["ok"]), (200, True))
        chequear("servidor: orden normal llega a Arche con origen celular", recibidas, [("pon musica en spotify", "celular")])

        recibidas.clear()
        codigo, cuerpo, _ = pedir(servidor, "POST", "/api/enviar", PIN, {"texto": "apaga el pc"})
        chequear("servidor: orden delicada -> rechazada", json.loads(cuerpo)["ok"], False)
        chequear("servidor: orden delicada trae mensaje", "solo la acepto desde el PC" in json.loads(cuerpo)["mensaje"], True)
        chequear("servidor: orden delicada NO llega a Arche", recibidas, [])

        recibidas.clear()
        pedir(servidor, "POST", "/api/enviar", "000000", {"texto": "hola"})
        chequear("servidor: POST sin PIN valido no llega a Arche", recibidas, [])

        reiniciar_fallos()
        codigos = [pedir(servidor, "GET", "/api/estado", "999999")[0] for _ in range(5)]
        chequear("servidor: 5 PIN malos -> 401 cada vez", codigos, [401] * 5)
        chequear("servidor: el sexto intento -> 429", pedir(servidor, "GET", "/api/estado", "999999")[0], 429)
        chequear("servidor: bloqueada esa direccion, ni con el PIN bueno entra",
                 pedir(servidor, "GET", "/api/estado", PIN)[0], 429)

        # bloqueo global: muchos fallos desde "distintas" direcciones
        reiniciar_fallos()
        remoto._fallos_globales.extend([time.time()] * (remoto.MAX_FALLOS_GLOBALES - 1))
        chequear("global: justo bajo el tope todavia deja entrar", pedir(servidor, "GET", "/api/estado", PIN)[0], 200)
        pedir(servidor, "GET", "/api/estado", "111111")        # el que pasa el tope
        chequear("global: pasado el tope se bloquea a todos", pedir(servidor, "GET", "/api/estado", PIN)[0], 429)
        remoto._fallos_globales[:] = [t - remoto.BLOQUEO_GLOBAL - 5 for t in remoto._fallos_globales]
        chequear("global: el bloqueo termina solo", pedir(servidor, "GET", "/api/estado", PIN)[0], 200)

        reiniciar_fallos()
        for i in range(250):
            remoto._fallos[f"10.0.{i // 250}.{i}"] = [1, 0]     # entradas ya vencidas
        pedir(servidor, "GET", "/api/estado", "222222")
        chequear("registro de fallos: se limpian las vencidas (no crece sin limite)", len(remoto._fallos) < 50, True)
    finally:
        servidor.shutdown()
        servidor.server_close()
        reiniciar_fallos()

print()
print("TODO OK" if not fallos else f"FALLARON {len(fallos)}: " + "; ".join(fallos))
sys.exit(1 if fallos else 0)