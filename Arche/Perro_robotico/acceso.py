"""acceso.py  Clave del banco de pruebas cuando se entra por internet (tunel cloudflared).

Por que existe:
  El tunel publico deja que cualquiera en internet que tenga el enlace llegue al banco.
  Sin clave, esa persona podria mover el perro. Por eso, TODO lo que entra por el tunel
  pide la clave antes de mostrar o mover nada. En tu WiFi / Tailscale no cambia nada.

  * La clave son 8 letras y numeros (ej. K7P2-QX9M). Se guarda en certificados/acceso.json
    (esa carpeta no se sube a GitHub).
  * Al acertarla, el navegador/app queda recordado 1 anio con una cookie segura.
  * 5 intentos fallidos desde un mismo lugar -> bloqueado 15 min.
    20 fallidos en una hora en total -> el tunel se bloquea 1 hora para todos.
  * "cambia la clave del perro" crea una clave nueva y saca a todos los que hayan entrado.
"""

import hmac
import json
import os
import secrets
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(HERE, "certificados", "acceso.json")
COOKIE = "perro_sesion"
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"     # sin 0/O ni 1/I/L para no confundirse

_lock = threading.Lock()
_fallos = {}            # ip -> [tiempos de intentos fallidos]
_fallos_total = []
_bloqueo_total_hasta = 0.0


def _nueva_clave():
    return "".join(secrets.choice(ALFABETO) for _ in range(8))


def _cargar():
    try:
        with open(RUTA, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("clave") and d.get("sesion"):
            return d
    except (OSError, ValueError):
        pass
    return None


def _guardar(d):
    os.makedirs(os.path.dirname(RUTA), exist_ok=True)
    gi = os.path.join(os.path.dirname(RUTA), ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write("# llaves privadas y claves: nunca a GitHub\n*\n")
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    try:
        os.chmod(RUTA, 0o600)
    except OSError:
        pass


def datos():
    with _lock:
        d = _cargar()
        if d is None:
            d = {"clave": _nueva_clave(), "sesion": secrets.token_hex(32)}
            _guardar(d)
        return d


def clave_bonita():
    c = datos()["clave"]
    return c[:4] + "-" + c[4:]


def cambiar_clave():
    """Clave nueva y sesion nueva: todos los que habian entrado tienen que volver a escribirla."""
    with _lock:
        _guardar({"clave": _nueva_clave(), "sesion": secrets.token_hex(32)})
    return clave_bonita()


def _normalizar(texto):
    return "".join(ch for ch in (texto or "").upper() if ch.isalnum())


def bloqueado(ip):
    """Segundos que le faltan de bloqueo a esa ip (0 = puede intentar)."""
    ahora = time.time()
    with _lock:
        if ahora < _bloqueo_total_hasta:
            return int(_bloqueo_total_hasta - ahora) + 1
        recientes = [t for t in _fallos.get(ip, []) if ahora - t < 900]
        _fallos[ip] = recientes
        if len(recientes) >= 5:
            return int(900 - (ahora - recientes[-5])) + 1
    return 0


def probar_clave(ip, texto):
    """True si la clave es correcta. Cuenta los fallos para bloquear a quien adivine."""
    global _bloqueo_total_hasta
    if bloqueado(ip):
        return False
    ok = hmac.compare_digest(_normalizar(texto).encode(), datos()["clave"].encode())
    if not ok:
        ahora = time.time()
        with _lock:
            _fallos.setdefault(ip, []).append(ahora)
            _fallos_total.append(ahora)
            _fallos_total[:] = [t for t in _fallos_total if ahora - t < 3600]
            if len(_fallos_total) >= 20:
                _bloqueo_total_hasta = ahora + 3600
    return ok


def sesion_valida(valor_cookie):
    if not valor_cookie:
        return False
    return hmac.compare_digest(valor_cookie.encode(), datos()["sesion"].encode())


def valor_sesion():
    return datos()["sesion"]
