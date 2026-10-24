"""
prueba_celular_archivos.py
--------------------------
Ubicacion: Arche/prueba_celular_archivos.py

Prueba la pestaña ARCHIVOS del celular (core/interfaz/remoto.py) SIN tocar tus
carpetas de verdad: crea una "casa" falsa en una carpeta temporal con Escritorio,
Documentos y Descargas, levanta el servidor en 127.0.0.1 y revisa que:

  * se listan tus carpetas y sus archivos (sin los ocultos),
  * NO se puede salir de ellas (.., rutas absolutas, accesos directos hacia afuera),
  * el buscador y "recientes" encuentran el archivo,
  * la descarga necesita un permiso, el permiso sirve y uno inventado no,
  * la descarga por partes (Range) funciona (para ver videos en el celular),
  * lo que mandas del celular llega a Descargas/Desde el celular sin sobrescribir nada,
  * sin PIN no se puede nada de esto.

Correr:  python prueba_celular_archivos.py
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from core.interfaz import ajustes, datos, en_vivo, entrada, remoto  # noqa: E402

fallos = []


def chequear(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}")
    else:
        print(f"FALLA {nombre}: esperaba {esperado!r}, salio {obtenido!r}")
        fallos.append(nombre)


PIN = "654321"
casa = tempfile.mkdtemp(prefix="casa_falsa_")
afuera = tempfile.mkdtemp(prefix="afuera_")
for c in ("Desktop", "Documents", "Downloads"):
    os.makedirs(os.path.join(casa, c))
os.makedirs(os.path.join(casa, "Documents", "Tareas"))
with open(os.path.join(casa, "Documents", "Tareas", "informe final.txt"), "w", encoding="utf-8") as f:
    f.write("0123456789" * 10)
with open(os.path.join(casa, "Documents", ".secreto"), "w") as f:
    f.write("no")
with open(os.path.join(afuera, "privado.txt"), "w") as f:
    f.write("no deberias verme")
with open(os.path.join(casa, "secreto_de_casa.txt"), "w") as f:
    f.write("tampoco")
try:
    os.symlink(afuera, os.path.join(casa, "Desktop", "atajo_afuera"))
    hay_symlink = True
except (OSError, NotImplementedError):
    hay_symlink = False           # en Windows crear symlinks pide permisos; se salta esa parte


def pedir(servidor, metodo, ruta, pin=PIN, cuerpo=None, cabeceras=None):
    url = f"http://127.0.0.1:{servidor.server_address[1]}{ruta}"
    p = urllib.request.Request(url, method=metodo)
    if pin is not None:
        p.add_header("X-Pin", pin)
    for k, v in (cabeceras or {}).items():
        p.add_header(k, v)
    datos_ = None
    if isinstance(cuerpo, (bytes, bytearray)):
        datos_ = bytes(cuerpo)
    elif cuerpo is not None:
        datos_ = json.dumps(cuerpo).encode()
        p.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(p, data=datos_, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def js(respuesta):
    return json.loads(respuesta[1] or b"{}")


entorno = {"HOME": casa, "USERPROFILE": casa, "OneDrive": os.path.join(casa, "no_existe")}
with mock.patch.dict(os.environ, entorno), \
        mock.patch.object(ajustes, "obtener", lambda clave: PIN if clave == "celular_pin" else 8765), \
        mock.patch.object(ajustes, "fijar", lambda *a, **k: None), \
        mock.patch.object(en_vivo, "sondear", lambda: None), \
        mock.patch.object(en_vivo, "estado_visual", lambda: "quieto"), \
        mock.patch.object(en_vivo, "avisar", lambda *a, **k: None), \
        mock.patch.object(datos, "controles", lambda: []), \
        mock.patch.object(entrada, "enviar", lambda *a, **k: None):

    remoto._fallos.clear()
    remoto._fallos_globales.clear()
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), remoto._Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        # --- listar ---
        raiz = js(pedir(servidor, "GET", "/api/archivos?ruta="))
        chequear("inicio: muestra escritorio, documentos y descargas",
                 sorted(i["ruta"] for i in raiz["items"]), ["descargas", "documentos", "escritorio"])
        docs = js(pedir(servidor, "GET", "/api/archivos?ruta=documentos"))
        chequear("documentos: ve la carpeta Tareas y NO el archivo oculto",
                 [i["nombre"] for i in docs["items"]], ["Tareas"])
        tareas = js(pedir(servidor, "GET", "/api/archivos?ruta=documentos/Tareas"))
        chequear("tareas: ve el informe con su tamaño", [(i["nombre"], i["tam"]) for i in tareas["items"]],
                 [("informe final.txt", 100)])

        # --- no salirse ---
        for mala in ("documentos/..", "documentos/../secreto_de_casa.txt", "../", afuera, "c:/windows",
                     "documentos/.secreto", "inventada"):
            chequear(f"bloqueado: {mala}", remoto.resolver(mala), None)
            chequear(f"bloqueado por la red: {mala}",
                     pedir(servidor, "GET", "/api/archivos?ruta=" + urllib.request.quote(mala))[0], 404)
        if hay_symlink:
            esc = js(pedir(servidor, "GET", "/api/archivos?ruta=escritorio"))
            chequear("acceso directo hacia afuera: no aparece", esc["items"], [])
            chequear("acceso directo hacia afuera: no se abre",
                     remoto.resolver("escritorio/atajo_afuera/privado.txt"), None)

        # --- buscar y recientes ---
        b = js(pedir(servidor, "GET", "/api/buscar?q=" + urllib.request.quote("Informe FINAL")))
        chequear("buscar: encuentra el informe (sin importar mayusculas)",
                 [i["ruta"] for i in b["items"]], ["documentos/Tareas/informe final.txt"])
        r = js(pedir(servidor, "GET", "/api/recientes"))
        chequear("recientes: aparece el informe", "documentos/Tareas/informe final.txt" in [i["ruta"] for i in r["items"]], True)
        chequear("recientes: no aparece lo de afuera", any("privado" in i["nombre"] for i in r["items"]), False)

        # --- descargar ---
        chequear("descarga sin permiso -> 404", pedir(servidor, "GET", "/api/descargar?t=inventado", pin=None)[0], 404)
        chequear("permiso para algo de afuera -> no", js(pedir(servidor, "POST", "/api/permiso", cuerpo={"ruta": "documentos/../secreto_de_casa.txt"}))["ok"], False)
        p = js(pedir(servidor, "POST", "/api/permiso", cuerpo={"ruta": "documentos/Tareas/informe final.txt"}))
        chequear("permiso para el informe -> ok", p["ok"], True)
        cod, cuerpo, cab = pedir(servidor, "GET", "/api/descargar?t=" + p["token"], pin=None)
        chequear("descarga con permiso -> el archivo completo", (cod, len(cuerpo)), (200, 100))
        chequear("descarga: se baja como archivo con su nombre",
                 cab.get("Content-Disposition"), "attachment; filename*=UTF-8''informe%20final.txt")
        cod, cuerpo, cab = pedir(servidor, "GET", "/api/descargar?t=" + p["token"], pin=None, cabeceras={"Range": "bytes=10-19"})
        chequear("descarga por partes (Range)", (cod, cuerpo, cab.get("Content-Range")), (206, b"0123456789", "bytes 10-19/100"))
        cod, cuerpo, cab = pedir(servidor, "GET", "/api/descargar?ver=1&t=" + p["token"], pin=None)
        chequear("ver: un .txt se muestra en el navegador", cab.get("Content-Disposition", "").startswith("inline"), True)
        chequear("sin PIN no se pide permiso", pedir(servidor, "POST", "/api/permiso", pin="000000", cuerpo={"ruta": "documentos"})[0], 401)
        remoto._fallos.clear()
        remoto._fallos_globales.clear()

        # --- subir ---
        destino = os.path.join(casa, "Downloads", remoto.CARPETA_SUBIDAS)
        s1 = js(pedir(servidor, "POST", "/api/subir", cuerpo=b"foto1", cabeceras={"X-Nombre": "foto.jpg"}))
        s2 = js(pedir(servidor, "POST", "/api/subir", cuerpo=b"foto2", cabeceras={"X-Nombre": "foto.jpg"}))
        chequear("subir: llega con su nombre", s1, {"ok": True, "nombre": "foto.jpg"})
        chequear("subir: el segundo NO sobrescribe", s2, {"ok": True, "nombre": "foto (2).jpg"})
        with open(os.path.join(destino, "foto.jpg"), "rb") as f:
            chequear("subir: el primero sigue intacto", f.read(), b"foto1")
        s3 = js(pedir(servidor, "POST", "/api/subir", cuerpo=b"x", cabeceras={"X-Nombre": urllib.request.quote("../../malo.txt")}))
        chequear("subir: un nombre con ../ se queda en su carpeta", (s3["ok"], os.path.exists(os.path.join(destino, "malo.txt"))), (True, True))
        chequear("subir: no se escribio afuera", os.path.exists(os.path.join(casa, "malo.txt")), False)
        chequear("subir: sin PIN no se puede", pedir(servidor, "POST", "/api/subir", pin="000000", cuerpo=b"x",
                                                     cabeceras={"X-Nombre": "y.txt"})[0], 401)
        remoto._fallos.clear()
        remoto._fallos_globales.clear()

        # --- interruptor de entorno ---
        with mock.patch.dict(os.environ, {"ARCHE_CELULAR_SIN_ARCHIVOS": "1"}):
            chequear("archivos apagados -> 403", pedir(servidor, "GET", "/api/archivos?ruta=")[0], 403)

        # --- entrar: abrir la pagina sin PIN no gasta intentos; el bloqueo dice cuanto esperar ---
        remoto._fallos.clear()
        remoto._fallos_globales.clear()
        for _ in range(10):
            pedir(servidor, "GET", "/api/estado", pin="")
        chequear("sin PIN (pagina recien abierta) no cuenta como intento", len(remoto._fallos_globales), 0)
        chequear("...y luego el PIN bueno entra", pedir(servidor, "GET", "/api/estado")[0], 200)
        for _ in range(6):
            r6 = pedir(servidor, "GET", "/api/estado", pin="999999")
        chequear("bloqueado: dice cuantos segundos esperar", (r6[0], 0 < int(r6[2].get("Retry-After", 0)) <= 61), (429, True))
        remoto._fallos.clear()
        remoto._fallos_globales.clear()

        # --- solo red de casa y Tailscale ---
        for ip, ok in (("192.168.1.20", True), ("10.0.0.5", True), ("100.88.1.2", True), ("127.0.0.1", True),
                       ("8.8.8.8", False), ("181.50.3.4", False)):
            chequear(f"red permitida {ip}", remoto.red_permitida(ip), ok)

        # --- funciones nuevas ---
        abiertos = []
        with mock.patch("webbrowser.open", lambda u: abiertos.append(u)):
            chequear("enlace: javascript: no se abre", js(pedir(servidor, "POST", "/api/enlace", cuerpo={"url": "javascript:alert(1)"}))["ok"], False)
            chequear("enlace: file:// no se abre", js(pedir(servidor, "POST", "/api/enlace", cuerpo={"url": "file:///C:/Windows"}))["ok"], False)
            chequear("enlace: https si", js(pedir(servidor, "POST", "/api/enlace", cuerpo={"url": "https://youtube.com"}))["ok"], True)
            import time as _t; _t.sleep(0.2)
            chequear("enlace: llego al navegador", abiertos, ["https://youtube.com"])
        chequear("procesos: responde una lista", isinstance(js(pedir(servidor, "GET", "/api/procesos"))["items"], list), True)
        chequear("enlace sin PIN -> 401", pedir(servidor, "POST", "/api/enlace", pin="000000", cuerpo={"url": "https://x.com"})[0], 401)
        remoto._fallos.clear()
        remoto._fallos_globales.clear()
        chequear("abrir la terminal desde el celular: bloqueado", remoto.es_orden_solo_pc("abre la terminal"), True)

        # --- atajos de la pagina no deben quedar bloqueados ---
        for atajo in ("pausa la musica", "siguiente cancion", "cancion anterior", "sube el volumen", "baja el volumen", "silencia"):
            chequear(f"atajo permitido: {atajo}", remoto.es_orden_solo_pc(atajo), False)
    finally:
        servidor.shutdown()
        servidor.server_close()
        shutil.rmtree(casa, ignore_errors=True)
        shutil.rmtree(afuera, ignore_errors=True)

print()
print("TODO OK" if not fallos else f"FALLARON {len(fallos)}: " + "; ".join(fallos))