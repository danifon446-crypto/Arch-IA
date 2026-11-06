"""tailscale_perro.py  Publica el banco de pruebas dentro de tu Tailscale con una direccion FIJA.

Con "tailscale serve" el banco queda en:
    https://<nombre-del-pc>.<tu-tailnet>.ts.net:8443/app

Ventajas frente a usar la IP 100.x o el tunel de Cloudflare:
  * La direccion nunca cambia: la app del iPhone se agrega UNA vez y sirve siempre.
  * El certificado lo pone Tailscale (es valido): no hay que instalar nada en el iPhone.
  * Solo entran tus aparatos de Tailscale: nadie de internet puede llegar.
  * Va directo del iPhone al PC (sin pasar por Cloudflare): menos lag.

Se configura una sola vez y Tailscale lo recuerda aunque reinicies el PC.
Usa el puerto 8443 para no pisar otras cosas que tengas publicadas en Tailscale.

Antes (una sola vez) en https://login.tailscale.com/admin/dns hay que tener activado
"MagicDNS" y "HTTPS Certificates".
"""

import json
import os
import shutil
import subprocess

PUERTO_TS = 8443
PANEL_DNS = "https://login.tailscale.com/admin/dns"


def exe():
    e = shutil.which("tailscale")
    if e:
        return e
    for r in (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
        if os.path.exists(r):
            return r
    return None


def _correr(args, timeout=20):
    e = exe()
    if not e:
        return None, "No encontré Tailscale en este PC."
    try:
        r = subprocess.run([e] + args, capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return None, "Tailscale tardó demasiado en responder."
    except OSError as err:
        return None, f"No pude ejecutar Tailscale ({err})."
    return r, (r.stdout or "") + (r.stderr or "")


def nombre_dns():
    """(nombre 'pc.tailnet.ts.net' | None, mensaje)."""
    r, salida = _correr(["status", "--json"], timeout=8)
    if r is None:
        return None, salida
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return None, "Tailscale no respondió bien. ¿Está abierto e iniciado sesión?"
    if d.get("BackendState") != "Running":
        return None, "Tailscale está apagado en el PC. Ábrelo y conéctate."
    dns = ((d.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not dns:
        return None, f"Tu Tailscale no tiene MagicDNS. Actívalo en {PANEL_DNS} (MagicDNS y HTTPS Certificates)."
    return dns, "ok"


def url():
    dns, _ = nombre_dns()
    return f"https://{dns}:{PUERTO_TS}" if dns else None


def esta_publicado(puerto_banco):
    r, salida = _correr(["serve", "status", "--json"], timeout=8)
    if r is None or r.returncode != 0:
        return False
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        return False
    for host, web in (d.get("Web") or {}).items():
        if not host.endswith(f":{PUERTO_TS}"):
            continue
        for h in (web.get("Handlers") or {}).values():
            if f":{puerto_banco}" in (h.get("Proxy") or ""):
                return True
    return False


def publicar(puerto_banco):
    """Publica el banco en Tailscale. Devuelve (url | None, mensaje para David)."""
    dns, msg = nombre_dns()
    if not dns:
        return None, msg
    if esta_publicado(puerto_banco):
        return f"https://{dns}:{PUERTO_TS}", "ya estaba"
    # https+insecure: el banco usa su certificado propio; ese tramo es dentro del mismo PC
    r, salida = _correr(["serve", "--bg", f"--https={PUERTO_TS}", f"https+insecure://127.0.0.1:{puerto_banco}"], timeout=40)
    if r is None:
        return None, salida
    if r.returncode != 0:
        s = salida.lower()
        if "https" in s and ("enable" in s or "not enabled" in s or "certificates" in s):
            return None, f"Falta activar los certificados HTTPS de Tailscale: entra a {PANEL_DNS} y activa 'HTTPS Certificates'."
        if "access denied" in s or "permission" in s or "operator" in s or "administrator" in s:
            return None, ("Windows no dejó configurar Tailscale. Abre la terminal como administrador y escribe: "
                          f'tailscale serve --bg --https={PUERTO_TS} https+insecure://127.0.0.1:{puerto_banco}')
        return None, "Tailscale dijo: " + salida.strip()[:300]
    return f"https://{dns}:{PUERTO_TS}", "publicado"


def quitar():
    r, salida = _correr(["serve", f"--https={PUERTO_TS}", "off"], timeout=15)
    if r is None:
        return False, salida
    return r.returncode == 0, salida.strip()
