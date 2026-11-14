"""
servidor.py
-----------
Ubicacion: Arche/core/tres_d/servidor.py

La página del taller 3D. Es un servidor pequeñito que SOLO atiende a este PC:

  - escucha en 127.0.0.1 (nadie de tu red ni de internet puede entrar),
  - cada dato y cada orden exige una llave secreta que se crea al arrancar y
    que solo conoce la página que Arché te abre (así otra página web abierta
    en tu navegador no puede mandarle órdenes a Arché a escondidas),
  - revisa que el pedido venga dirigido a 127.0.0.1 / localhost,
  - solo entrega los archivos del taller y los modelos de Modelos3D/.
"""

import ast
import hmac
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import disenador as dis
from . import geometria as geo

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, "web")
PUERTO_INICIAL = 8770
MAX_SUBIDA = geo.MAX_BYTES

_servidor = None
_hilo = None
_llave = secrets.token_urlsafe(24)
_puerto = None

# archivo que se puede pedir -> (ruta dentro de web/, tipo)
_ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/estilo.css": ("estilo.css", "text/css; charset=utf-8"),
    "/taller.js": ("taller.js", "text/javascript; charset=utf-8"),
    "/nucleo.js": ("nucleo.js", "text/javascript; charset=utf-8"),
    "/perro.js": ("perro.js", "text/javascript; charset=utf-8"),
    "/cerebro.js": ("cerebro.js", "text/javascript; charset=utf-8"),
    "/lib/three.module.min.js": ("lib/three.module.min.js", "text/javascript; charset=utf-8"),
    "/lib/OrbitControls.js": ("lib/OrbitControls.js", "text/javascript; charset=utf-8"),
    "/lib/STLLoader.js": ("lib/STLLoader.js", "text/javascript; charset=utf-8"),
}


def activo():
    return _servidor is not None


def direccion():
    return f"http://127.0.0.1:{_puerto}" if _puerto else ""


def direccion_con_llave(pestana="taller"):
    return f"{direccion()}/?k={_llave}#{pestana}"


# ------------------------------------------------------------------
# Datos que muestra la página
# ------------------------------------------------------------------

def _estado_arche():
    """Qué está haciendo Arché ahora (si el taller corre dentro de Arché)."""
    estado = {"dentro_de_arche": False, "visual": "reposo", "tareas": []}
    en_vivo = sys.modules.get("core.interfaz.en_vivo")
    if en_vivo is not None:
        estado["dentro_de_arche"] = True
        try:
            estado["visual"] = en_vivo.estado_visual()
        except Exception:
            pass
    multitarea = sys.modules.get("core.multitarea")
    if multitarea is not None:
        try:
            estado["tareas"] = [{"id": t.id, "orden": t.orden, "estado": t.estado} for t in multitarea.tareas_vivas()]
        except Exception:
            pass
    return estado


def _robot():
    """El módulo del perro, si está (dentro de Arché ya viene cargado)."""
    modulo = sys.modules.get("acciones_robot")
    if modulo is None:
        carpeta = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "Perro_robotico")
        if os.path.isfile(os.path.join(carpeta, "acciones_robot.py")):
            if carpeta not in sys.path:
                sys.path.append(carpeta)
            try:
                import acciones_robot as modulo
            except Exception:
                modulo = None
    return modulo


def _pose_perro():
    ar = sys.modules.get("acciones_robot")
    if ar is None:
        return None
    try:
        pose = list(getattr(ar, "_ultima_pose", []))
        return pose if len(pose) == 12 and any(a is not None for a in pose) else None
    except Exception:
        return None


def datos_perro():
    ar = _robot()
    if ar is None:
        return {"hay": False}
    try:
        secuencias = {}
        for nombre, sec in getattr(ar, "SECUENCIAS", {}).items():
            frames = [[float(v) if v is not None else None for v in f] for f in sec.get("frames", []) if len(f) >= 13]
            if frames:
                secuencias[nombre] = {"frames": frames, "repetir": sec.get("repetir")}
        return {"hay": True, "muslo": float(ar.LARGO_MUSLO), "pierna": float(ar.LARGO_PIERNA),
                "rodillas": ar.RODILLAS, "rodilla_en_90": float(ar.RODILLA_EN_90),
                "servos": list(ar.SERVOS), "nombres": dict(ar.NOMBRE_SERVO), "secuencias": secuencias,
                "neutro": [float(v) for v in ar.NEUTRO]}
    except Exception as e:
        return {"hay": False, "error": str(e)}


_cerebro_cache = {"t": 0.0, "datos": None}


def datos_cerebro():
    """El mapa de Arché: cada archivo de core/ es un nodo; las líneas son quién usa a quién."""
    if _cerebro_cache["datos"] and time.time() - _cerebro_cache["t"] < 300:
        return _cerebro_cache["datos"]
    core = os.path.dirname(AQUI)                                   # .../Arche/core
    nodos, indice = [], {}
    for raiz, carpetas, archivos in os.walk(core):
        carpetas[:] = [c for c in carpetas if c not in ("__pycache__", "web", "galeria", "pruebas_aprendidas", "puente_minecraft")]
        for archivo in sorted(archivos):
            if not archivo.endswith(".py"):
                continue
            ruta = os.path.join(raiz, archivo)
            rel = os.path.relpath(ruta, os.path.dirname(core)).replace(os.sep, "/")
            modulo = rel[:-3].replace("/", ".")
            if modulo.endswith(".__init__"):
                modulo = modulo[:-9]
            partes = modulo.split(".")
            grupo = partes[1] if len(partes) > 2 else "nucleo"
            try:
                with open(ruta, "r", encoding="utf-8-sig") as f:
                    fuente = f.read()
            except OSError:
                continue
            indice[modulo] = len(nodos)
            nodos.append({"id": modulo, "nombre": partes[-1], "grupo": grupo, "lineas": fuente.count("\n") + 1,
                          "_fuente": fuente, "_paquete": modulo if archivo == "__init__.py" else ".".join(partes[:-1])})
    enlaces = set()
    for i, nodo in enumerate(nodos):
        try:
            arbol = ast.parse(nodo["_fuente"])
        except SyntaxError:
            continue
        resumen = ast.get_docstring(arbol) or ""
        utiles = [l.strip() for l in resumen.splitlines()
                  if l.strip() and not set(l.strip()) <= set("-=") and not l.strip().lower().startswith(("ubicacion", "ubicación", "ruta:", "carpeta:"))
                  and not (l.strip().endswith(".py") and " " not in l.strip())]
        nodo["resumen"] = " ".join(utiles)[:240]
        for n in ast.walk(arbol):
            destinos = []
            if isinstance(n, ast.Import):
                destinos = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    padre = nodo["_paquete"].split(".")
                    padre = padre[:len(padre) - (n.level - 1)] if n.level > 1 else padre
                    base = ".".join(padre + ([n.module] if n.module else []))
                destinos = [base] + [f"{base}.{a.name}" for a in n.names]
            for d in destinos:
                j = indice.get(d)
                if j is not None and j != i:
                    enlaces.add((i, j))
    for nodo in nodos:
        for clave in ("_fuente", "_paquete"):
            nodo.pop(clave, None)
    datos = {"nodos": nodos, "enlaces": sorted(enlaces), "total_lineas": sum(n["lineas"] for n in nodos)}
    _cerebro_cache.update(t=time.time(), datos=datos)
    return datos


def _lista_modelos():
    salida = []
    for m in dis.listar():
        r = m["receta"]
        que = r.get("alias") or ("pieza libre" if r.get("receta") else "espejo" if r.get("espejo_de") else "importado")
        salida.append({"nombre": m["nombre"], "que": que, "kb": round(m["bytes"] / 1024), "fecha": m["fecha"],
                       "editable": r.get("pieza") in dis.piezas.CATALOGO, "medidas": r.get("medidas") if r.get("pieza") else None,
                       "pieza": r.get("pieza")})
    return salida


# ------------------------------------------------------------------
# El servidor
# ------------------------------------------------------------------

class _Manejador(BaseHTTPRequestHandler):
    server_version = "Arche3D"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):                 # sin llenar la consola de Arché
        pass

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8", cache=False):
        if isinstance(cuerpo, str):
            cuerpo = cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, datos, codigo=200):
        self._responder(codigo, json.dumps(datos, ensure_ascii=False))

    def _de_este_pc(self):
        """El pedido debe venir de este PC y dirigido a 127.0.0.1/localhost (corta el 'DNS rebinding')."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return False
        anfitrion = (self.headers.get("Host") or "").lower()
        return anfitrion in (f"127.0.0.1:{_puerto}", f"localhost:{_puerto}")

    def _con_llave(self):
        enviada = self.headers.get("X-Arche-Llave", "")
        return hmac.compare_digest(enviada.encode("utf-8", "replace"), _llave.encode())

    def _modelo(self, q):
        nombre = (q.get("n") or [""])[0]
        return dis._limpio(nombre) if nombre and dis.existe(nombre) else None

    def do_GET(self):
        if not self._de_este_pc():
            return self._responder(403, "{}")
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        if url.path in _ESTATICOS:
            archivo, tipo = _ESTATICOS[url.path]
            try:
                with open(os.path.join(WEB, *archivo.split("/")), "rb") as f:
                    return self._responder(200, f.read(), tipo, cache=url.path.startswith("/lib/"))
            except OSError:
                return self._responder(404, "{}")
        if not url.path.startswith("/api/"):
            return self._responder(404, "{}")
        if not self._con_llave():
            return self._responder(401, "{}")
        try:
            if url.path == "/api/estado":
                from . import ajustes
                return self._json({"version": dis.version(), "ultimo": dis.ultimo(), "arche": _estado_arche(),
                                   "pose_perro": _pose_perro(), "ajustes": ajustes()})
            if url.path == "/api/modelos":
                return self._json({"modelos": _lista_modelos(), "ultimo": dis.ultimo(), "carpeta": dis.carpeta()})
            if url.path == "/api/modelo":
                nombre = self._modelo(q)
                if not nombre:
                    return self._responder(404, "{}")
                with open(dis.ruta_stl(nombre), "rb") as f:
                    return self._responder(200, f.read(), "model/stl")
            if url.path == "/api/analisis":
                nombre = self._modelo(q)
                if not nombre:
                    return self._responder(404, "{}")
                from . import analizar
                a = analizar(nombre)
                a["frases"] = geo.resumen(a)
                a["tiempo"] = geo.tiempo_legible(a["horas"])
                return self._json(a)
            if url.path == "/api/perro":
                return self._json(datos_perro())
            if url.path == "/api/cerebro":
                return self._json(datos_cerebro())
            if url.path == "/api/catalogo":
                return self._json({n: {"descripcion": d["descripcion"], "ejemplo": d["ejemplo"],
                                       "medidas": d["medidas"]} for n, d in dis.piezas.CATALOGO.items()})
        except Exception as e:
            return self._json({"error": str(e)[:300]}, 500)
        return self._responder(404, "{}")

    def do_POST(self):
        if not self._de_este_pc():
            return self._responder(403, "{}")
        if not self._con_llave():
            return self._responder(401, "{}")
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        try:
            largo = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            largo = 0
        try:
            if url.path == "/api/orden":
                if not 0 < largo <= 4000:
                    return self._json({"ok": False, "lineas": ["Orden vacía o demasiado larga."]}, 400)
                texto = str(json.loads(self.rfile.read(largo)).get("texto", ""))[:500]
                from . import ejecutar_desde_pagina
                lineas, entendida = ejecutar_desde_pagina(texto)
                if not entendida:
                    lineas = ["Eso no es una orden de 3D. Escribe «ayuda 3d» para ver lo que puedo hacer aquí."]
                return self._json({"ok": entendida, "lineas": lineas, "ultimo": dis.ultimo(), "version": dis.version()})
            if url.path == "/api/medidas":
                # los deslizadores de la página: reconstruye la pieza con medidas nuevas
                if not 0 < largo <= 4000:
                    return self._json({"ok": False}, 400)
                datos = json.loads(self.rfile.read(largo))
                nombre = dis._limpio(datos.get("n", ""))
                receta = dis.leer_receta(nombre) if dis.existe(nombre) else {}
                pieza = receta.get("pieza")
                if pieza not in dis.piezas.CATALOGO or not isinstance(datos.get("medidas"), dict):
                    return self._json({"ok": False, "error": "Ese modelo no se puede editar con medidas."}, 400)
                from . import _candado
                with _candado:
                    malla, finales, notas = dis.piezas.construir(pieza, dict(receta.get("medidas") or {}, **datos["medidas"]))
                    dis.guardar(nombre, malla, {"pieza": pieza, "medidas": finales, "alias": receta.get("alias", pieza)})
                return self._json({"ok": True, "medidas": finales, "notas": notas, "version": dis.version()})
            if url.path == "/api/subir":
                if not 0 < largo <= MAX_SUBIDA:
                    return self._json({"ok": False, "error": "Archivo vacío o de más de 80 MB."}, 400)
                original = (q.get("n") or ["modelo.stl"])[0]
                extension = os.path.splitext(original)[1].lower()
                if extension not in (".stl", ".obj"):
                    return self._json({"ok": False, "error": "Solo acepto archivos .stl y .obj."}, 400)
                malla = geo.apoyar(geo.leer_bytes(self.rfile.read(largo), extension))
                from . import _candado
                with _candado:
                    nombre = dis.guardar(dis.nombre_libre(original), malla, {"importado": os.path.basename(original)[:80]})
                return self._json({"ok": True, "nombre": nombre, "version": dis.version()})
            if url.path == "/api/usar":
                # el modelo elegido en la página pasa a ser «el modelo» para las órdenes
                datos = json.loads(self.rfile.read(largo)) if 0 < largo <= 2000 else {}
                nombre = dis._limpio(datos.get("n", ""))
                if dis.existe(nombre):
                    dis._estado["ultimo"] = nombre
                return self._json({"ok": dis.existe(nombre)})
            if url.path == "/api/borrar":
                datos = json.loads(self.rfile.read(largo)) if 0 < largo <= 2000 else {}
                return self._json({"ok": dis.borrar(datos.get("n", "")), "version": dis.version()})
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)[:300], "lineas": [str(e)[:300]]}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:300], "lineas": [f"Algo falló: {str(e)[:200]}"]}, 500)
        return self._responder(404, "{}")


def iniciar():
    """Arranca el servidor (si no estaba). Devuelve (ok, detalle)."""
    global _servidor, _hilo, _puerto
    if _servidor is not None:
        return True, direccion()
    if not os.path.isfile(os.path.join(WEB, "index.html")):
        return False, "faltan los archivos de core/tres_d/web/"
    ultimo_error = None
    for puerto in range(PUERTO_INICIAL, PUERTO_INICIAL + 20):
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", puerto), _Manejador)
        except OSError as e:
            ultimo_error = e
            continue
        servidor.daemon_threads = True
        _servidor, _puerto = servidor, puerto
        _hilo = threading.Thread(target=servidor.serve_forever, name="arche-taller-3d", daemon=True)
        _hilo.start()
        return True, direccion()
    return False, f"no encontré un puerto libre ({ultimo_error})"


def detener():
    global _servidor, _hilo, _puerto
    if _servidor is not None:
        try:
            _servidor.shutdown()
            _servidor.server_close()
        except Exception:
            pass
    _servidor = _hilo = _puerto = None


def abrir_navegador(pestana="taller"):
    try:
        webbrowser.open(direccion_con_llave(pestana))
    except Exception:
        pass
