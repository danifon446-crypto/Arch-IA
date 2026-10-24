"""
cifrado.py
----------
Ubicacion: Arche/core/seguridad/cifrado.py

Cifra los secretos de Arché (claves de la nube, token de WhatsApp, la llave del
guardian) para que NO queden como texto plano en el disco.

Como funciona:
  * En Windows usa DPAPI (la misma proteccion que usan Chrome y Edge para tus
    contrasenas guardadas). El secreto queda atado a TU usuario de Windows:
    si alguien copia la carpeta Database/ a otro PC, o un programa corre con
    otro usuario, no puede descifrarlo. No hay que instalar nada ni guardar
    ninguna llave aparte: Windows la custodia.
  * Fuera de Windows (o si DPAPI falla) usa Fernet (AES-128 + HMAC-SHA256) de la
    libreria `cryptography`, con una llave guardada en Database/.llave_arche
    (permisos 600). Si `cryptography` no esta instalada, avisa y guarda en
    texto plano como antes (nunca deja a Arché sin poder funcionar).

Formato de lo guardado:   arche:dpapi:v1:<base64>   o   arche:fernet:v1:<token>
Un texto SIN ese prefijo se considera "viejo, en texto plano": descifrar()
lo devuelve tal cual, para que las claves que ya tenias sigan sirviendo, y
quien lo lea puede volver a guardarlo ya cifrado (migracion automatica).

Uso:
    from core.seguridad import cifrado
    guardado = cifrado.cifrar("gsk_...")
    clave = cifrado.descifrar(guardado)
"""

import base64
import os
import sys

from core.rutas import DATABASE

PREFIJO = "arche:"
_DPAPI = "arche:dpapi:v1:"
_FERNET = "arche:fernet:v1:"
_ENTROPIA = b"Arche|secretos|v1"   # "sal" extra para DPAPI: otro programa no puede pedir lo mismo
ARCHIVO_LLAVE = os.path.join(DATABASE, ".llave_arche")


class ErrorCifrado(Exception):
    pass


# ------------------------------------------------------------------
# DPAPI (Windows)
# ------------------------------------------------------------------

def _dpapi_disponible():
    return sys.platform == "win32"


def _dpapi(datos, proteger):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    entrada, _b1 = _blob(datos)
    entropia, _b2 = _blob(_ENTROPIA)
    salida = BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if proteger:
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), "Arche", ctypes.byref(entropia),
                                      None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia),
                                        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
    if not ok:
        raise ErrorCifrado(f"DPAPI fallo (codigo {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        kernel32.LocalFree(salida.pbData)


# ------------------------------------------------------------------
# Fernet (respaldo multiplataforma)
# ------------------------------------------------------------------

def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    if not os.path.exists(ARCHIVO_LLAVE):
        os.makedirs(DATABASE, exist_ok=True)
        llave = Fernet.generate_key()
        # O_EXCL: si dos hilos llegan a la vez, solo uno crea la llave
        try:
            fd = os.open(ARCHIVO_LLAVE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(llave)
        except FileExistsError:
            pass
    with open(ARCHIVO_LLAVE, "rb") as f:
        return Fernet(f.read().strip())


# ------------------------------------------------------------------
# API publica
# ------------------------------------------------------------------

def esta_cifrado(texto):
    return isinstance(texto, str) and texto.startswith(PREFIJO)


def metodo():
    """Que proteccion se va a usar en este equipo: 'dpapi', 'fernet' o 'ninguno'."""
    if _dpapi_disponible():
        return "dpapi"
    try:
        import cryptography  # noqa: F401
        return "fernet"
    except ImportError:
        return "ninguno"


def cifrar(texto):
    """Devuelve el texto cifrado (con prefijo). Si ya venia cifrado, lo deja igual."""
    texto = "" if texto is None else str(texto)
    if not texto or esta_cifrado(texto):
        return texto
    datos = texto.encode("utf-8")
    if _dpapi_disponible():
        try:
            return _DPAPI + base64.b64encode(_dpapi(datos, True)).decode("ascii")
        except Exception as e:
            print(f"Arché: (seguridad) DPAPI no funcionó ({e}); uso Fernet.")
    f = _fernet()
    if f is not None:
        return _FERNET + f.encrypt(datos).decode("ascii")
    print("Arché: (seguridad) No hay cifrado disponible: instala 'cryptography' "
          "(pip install cryptography). Guardé el secreto sin cifrar.")
    return texto


def descifrar(texto):
    """Devuelve el texto original. Un texto sin prefijo (viejo) se devuelve tal cual."""
    if not esta_cifrado(texto):
        return texto or ""
    if texto.startswith(_DPAPI):
        if not _dpapi_disponible():
            raise ErrorCifrado("Este secreto se cifró con Windows (DPAPI) y solo se puede abrir allí.")
        return _dpapi(base64.b64decode(texto[len(_DPAPI):]), False).decode("utf-8")
    if texto.startswith(_FERNET):
        f = _fernet()
        if f is None:
            raise ErrorCifrado("Falta la libreria 'cryptography' para abrir este secreto.")
        try:
            return f.decrypt(texto[len(_FERNET):].encode("ascii")).decode("utf-8")
        except Exception as e:
            raise ErrorCifrado("El secreto está dañado o la llave no corresponde.") from e
    raise ErrorCifrado("Formato de secreto desconocido.")


def guardar_secreto(ruta, texto):
    """Escribe el secreto cifrado en `ruta` (solo legible por tu usuario)."""
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(cifrar(texto))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, ruta)          # se reemplaza de golpe: nunca queda un archivo a medias


def leer_secreto(ruta, migrar=True):
    """
    Lee y descifra el secreto de `ruta` ('' si no existe). Si estaba en texto
    plano (de antes), lo vuelve a guardar cifrado cuando migrar=True.
    """
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = f.read().strip()
    except OSError:
        return ""
    if not crudo:
        return ""
    if not esta_cifrado(crudo):
        if migrar and metodo() != "ninguno":
            try:
                guardar_secreto(ruta, crudo)
            except OSError:
                pass
        return crudo
    return descifrar(crudo)
