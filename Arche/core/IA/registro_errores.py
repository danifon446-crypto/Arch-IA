"""
registro_errores.py
-------------------
Ubicacion: Arche/core/IA/registro_errores.py

Los "ojos" de la autorreparacion: cada vez que algo de Arché falla de verdad
mientras la usas (un comando que explota, un hilo en segundo plano que se cae,
una tarea de la mejora continua que revienta), aqui queda anotado con todo lo
necesario para arreglarlo despues sin ti:

  - tipo y mensaje del error, y el traceback
  - archivo, funcion, numero y texto de la linea DEL PROYECTO donde ocurrio
    (la ultima linea de codigo de Arché en el traceback, no la de una libreria)
  - los valores de las variables locales en ese punto (recortados, y sin nada
    que parezca una clave o contraseña)
  - la frase que escribiste cuando paso

Los errores iguales se agrupan por "firma" (tipo + archivo + funcion + texto de
la linea) y se cuentan, asi un error que se repite no llena el archivo.

Estados de un error:
  pendiente        -> la autorreparacion lo va a intentar
  resuelto         -> se reparo (con prueba que lo demuestra)
  no_pude          -> se intento varias veces sin exito; queda para ti
  necesita_humano  -> esta en un archivo que Arché no puede tocar sola
  obsoleto         -> la linea ya no existe (alguien lo cambio a mano)

Si un error "resuelto" vuelve a aparecer, pasa de nuevo a "pendiente".

Uso:
    from core.IA import registro_errores
    registro_errores.instalar()                 # una vez, al arrancar
    try: ...
    except Exception as e:
        registro_errores.registrar(e, frase=comando)
"""

import hashlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from core.rutas import DATABASE

RAIZ_APP = Path(__file__).resolve().parents[2]          # Arche/
ARCHIVO = os.path.join(DATABASE, "errores_reales.json")
MAX_ERRORES = 80                 # se guardan los mas recientes
MAX_LOCALES = 12
MAX_REPR = 240
MAX_TRACEBACK = 4000

CARPETAS_IGNORADAS = {"backups_codigo", "__pycache__", "site-packages", "dist-packages",
                      "pruebas_aprendidas", "respaldo_antes_canales_20261020_193722"}
_PALABRAS_SECRETAS = ("clave", "key", "token", "secret", "secreto", "password", "contrasena",
                      "contraseña", "pass", "auth", "bearer")

_lock = threading.RLock()
_instalado = False


# ------------------------------------------------------------------
# Archivo
# ------------------------------------------------------------------

def _cargar():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, list) else []
    except (OSError, ValueError):
        return []


def _guardar(errores):
    try:
        os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
        tmp = ARCHIVO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(errores[-MAX_ERRORES:], f, indent=2, ensure_ascii=False)
        os.replace(tmp, ARCHIVO)
    except OSError:
        pass


# ------------------------------------------------------------------
# Analisis del traceback
# ------------------------------------------------------------------

def _rel_del_proyecto(nombre_archivo):
    """'core/notas.py' si el archivo es de Arché (y no de una libreria ni un respaldo), si no None."""
    try:
        ruta = Path(nombre_archivo).resolve()
        rel = ruta.relative_to(RAIZ_APP)
    except (ValueError, OSError):
        return None
    if ruta.suffix != ".py" or any(p in CARPETAS_IGNORADAS for p in rel.parts):
        return None
    return rel.as_posix()


def _parece_secreto(nombre):
    n = str(nombre).lower()
    return any(p in n for p in _PALABRAS_SECRETAS)


def _locales_seguros(frame):
    salida = {}
    try:
        for nombre, valor in list(frame.f_locals.items())[:40]:
            if nombre.startswith("__") or _parece_secreto(nombre):
                continue
            if callable(valor) or type(valor).__name__ == "module":
                continue
            try:
                texto = repr(valor)
            except Exception:
                texto = f"<{type(valor).__name__} sin repr>"
            if len(texto) > MAX_REPR:
                texto = texto[:MAX_REPR] + "…"
            salida[nombre] = texto
            if len(salida) >= MAX_LOCALES:
                break
    except Exception:
        pass
    return salida


def _frame_del_proyecto(tb):
    """El ultimo frame del traceback que pertenece a un archivo de Arché, o None."""
    elegido = None
    while tb is not None:
        rel = _rel_del_proyecto(tb.tb_frame.f_code.co_filename)
        if rel:
            elegido = (tb.tb_frame, tb.tb_lineno, rel)
        tb = tb.tb_next
    return elegido


def _texto_linea(rel, numero):
    try:
        lineas = (RAIZ_APP / rel).read_text(encoding="utf-8-sig").splitlines()
        return lineas[numero - 1].strip() if 0 < numero <= len(lineas) else ""
    except OSError:
        return ""


def firma_de(tipo, rel, funcion, codigo_linea):
    base = f"{tipo}|{rel}|{funcion}|{codigo_linea}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]


def _es_protegido(rel):
    try:
        from core.IA.proponer_cambio_codigo import es_protegido
        return es_protegido(rel, automatico=True)
    except Exception:
        return False


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

def registrar(exc, frase="", origen="comando"):
    """
    Anota un error real. Devuelve el registro (dict) o None si el error no
    ocurrio dentro del codigo de Arché. Nunca lanza.
    """
    try:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            return None
        tb = exc.__traceback__
        punto = _frame_del_proyecto(tb)
        if punto is None:
            return None
        frame, numero, rel = punto
        funcion = frame.f_code.co_name
        codigo_linea = _texto_linea(rel, numero)
        tipo = type(exc).__name__
        firma = firma_de(tipo, rel, funcion, codigo_linea)
        texto_tb = "".join(traceback.format_exception(type(exc), exc, tb))[-MAX_TRACEBACK:]
        ahora = time.time()

        with _lock:
            errores = _cargar()
            for e in errores:
                if e.get("firma") == firma:
                    e["veces"] = int(e.get("veces", 1)) + 1
                    e["ultima"] = ahora
                    e["mensaje"] = str(exc)[:500]
                    e["traceback"] = texto_tb
                    e["linea"] = numero
                    e["locales"] = _locales_seguros(frame)
                    if frase:
                        e["frase"] = str(frase)[:300]
                    if e.get("estado") in ("resuelto", "obsoleto"):
                        e["nota"] = "volvió a aparecer después de marcarse como " + e["estado"]
                        e["estado"] = "pendiente"          # volvio a pasar: hay que mirarlo otra vez
                        e["intentos"] = 0
                    errores.remove(e)
                    errores.append(e)                     # el mas reciente al final
                    _guardar(errores)
                    return e

            registro = {
                "firma": firma,
                "tipo": tipo,
                "mensaje": str(exc)[:500],
                "archivo": rel,
                "linea": numero,
                "funcion": funcion,
                "codigo_linea": codigo_linea,
                "traceback": texto_tb,
                "locales": _locales_seguros(frame),
                "frase": str(frase)[:300],
                "origen": origen,
                "veces": 1,
                "primera": ahora,
                "ultima": ahora,
                "estado": "necesita_humano" if _es_protegido(rel) else "pendiente",
                "intentos": 0,
                "nota": "está en un archivo protegido: Arché no lo toca sola" if _es_protegido(rel) else "",
            }
            errores.append(registro)
            _guardar(errores)
            return registro
    except Exception:
        return None


def todos():
    with _lock:
        return _cargar()


def pendientes():
    """Errores que la autorreparacion todavia tiene que intentar, los mas repetidos primero."""
    with _lock:
        lista = [e for e in _cargar() if e.get("estado") == "pendiente"]
    return sorted(lista, key=lambda e: (-int(e.get("veces", 1)), -float(e.get("ultima", 0))))


def buscar(firma):
    with _lock:
        for e in _cargar():
            if e.get("firma") == firma:
                return e
    return None


def actualizar(firma, **cambios):
    with _lock:
        errores = _cargar()
        for e in errores:
            if e.get("firma") == firma:
                e.update(cambios)
                _guardar(errores)
                return e
    return None


def marcar(firma, estado, nota=""):
    return actualizar(firma, estado=estado, nota=nota, cambiado=time.time())


def sumar_intento(firma, nota=""):
    with _lock:
        errores = _cargar()
        for e in errores:
            if e.get("firma") == firma:
                e["intentos"] = int(e.get("intentos", 0)) + 1
                if nota:
                    e["nota"] = nota
                _guardar(errores)
                return e["intentos"]
    return 0


# ------------------------------------------------------------------
# Ganchos globales
# ------------------------------------------------------------------

def instalar():
    """Engancha los errores que nadie atrapo (en el hilo principal y en los hilos de fondo)."""
    global _instalado
    if _instalado:
        return
    _instalado = True

    anterior_sys = sys.excepthook

    def _gancho_sys(tipo, valor, tb):
        try:
            if valor is not None and valor.__traceback__ is None:
                valor = valor.with_traceback(tb)
            registrar(valor, origen="sin_atrapar")
        finally:
            anterior_sys(tipo, valor, tb)

    sys.excepthook = _gancho_sys

    anterior_hilos = threading.excepthook

    def _gancho_hilos(args):
        try:
            if args.exc_value is not None:
                nombre = args.thread.name if args.thread else "?"
                registrar(args.exc_value, origen=f"hilo:{nombre}")
        finally:
            anterior_hilos(args)

    threading.excepthook = _gancho_hilos
