"""
remoto.py
---------
Ubicacion: Arche/core/interfaz/remoto.py

Control de Arché desde el celular: una paginita web que Arché sirve en tu red
wifi. Abres la direccion en el navegador del celular, pones el PIN y puedes
escribirle, ver la conversacion y prender o apagar sus funciones.

Seguridad:
  * apagado por defecto; pide un PIN de 6 numeros (se ve en AJUSTES), creado
    con `secrets` (aleatorio de verdad, no el `random` de los juegos).
  * tras 5 PIN malos bloquea esa direccion un minuto; y si en total llegan
    MAX_FALLOS_GLOBALES fallos (aunque vengan de muchas direcciones) se bloquea
    a TODOS durante BLOQUEO_GLOBAL segundos.
  * solo responde a tu red de casa, a ti mismo (127.0.0.1) y a Tailscale
    (100.64.0.0/10). Cualquier otra direccion recibe 403.
  * las ordenes delicadas (apagar el PC, borrar archivos, instalar, teclear,
    tocar su propio codigo, claves...) NO se aceptan desde el celular: solo
    desde el PC. Para permitirlas a proposito: variable de entorno
    ARCHE_CELULAR_PERMITE_TODO=1.
  * cabeceras de seguridad para que otra pagina no pueda meter la de Arché
    dentro de un marco ni adivinar tipos de archivo.
No uses esto en una wifi publica.
"""

import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ajustes, datos, en_vivo, entrada

_servidor = None
_hilo = None
_fallos = {}      # ip -> [cuantos, hasta_cuando]
_fallos_globales = []   # momentos (time.time()) de cada PIN malo, venga de donde venga
_lock_fallos = threading.Lock()

MAX_FALLOS_POR_IP = 5
BLOQUEO_IP = 60               # segundos
MAX_FALLOS_GLOBALES = 20
BLOQUEO_GLOBAL = 300          # segundos (5 minutos)

# Redes desde las que se acepta conexion: la de casa, el propio PC y Tailscale.
_REDES_TAILSCALE = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]

CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# Ordenes que SOLO se aceptan desde el PC (se comparan sin tildes y en minusculas).
_ORDENES_SOLO_PC = [re.compile(p) for p in (
    r"\b(apaga|apagar|apagues|reinicia|reiniciar|suspende|suspender|hiberna|hibernar)\b.*"
    r"\b(pc|computador|computadora|equipo|maquina|sistema|portatil|laptop)\b",
    r"\bcierra (la |mi )?sesion\b|\bcerrar (la |mi )?sesion\b|\bbloquea (el pc|la pantalla)\b",
    r"\b(teclea|teclear|tipea|presiona|presionar|pulsa|pulsar|oprime|oprimir)\b",
    r"\bcambia esto\b|\bcambia el codigo\b|\bedita el codigo\b|\bmodifica (el|tu) codigo\b",
    r"\b(deshaz|deshacer|revierte|revertir|rollback)\b",
    r"\brevisate\b|\barreglate\b|\barregla todo\b|\bautorrepar|\bauto ?repar|\baprueba\b|\baplica el cambio\b",
    r"\bmejora\b.*\bnivel\b|\bnivel\b.*\bmejora\b",
    r"\b(clave|claves|token|contrasena|password|api ?key|pin)\b",
    r"\bcomparte\b.*\bmemoria\b|\bmemoria\b.*\bnube\b",
    r"\b(borra|borrar|elimina|eliminar|vacia|vaciar|formatea|formatear|limpia|limpiar|destruye)\b.*"
    r"\b(archivo|archivos|carpeta|carpetas|disco|descargas|documentos|escritorio|fotos|imagenes|"
    r"videos|papelera|todo|todos|duplicados)\b",
    r"\b(instala|instalar|desinstala|desinstalar|descarga e instala)\b",
    r"\b(ejecuta|ejecutar|corre|correr|lanza)\b.*\b(script|comando|codigo|powershell|cmd|terminal|consola|"
    r"\.py|\.bat|\.exe|\.ps1)\b",
    r"\b(whatsapp|celular)\b.*\b(conecta|configura|apaga|desactiva)\b|\b(conecta|configura)\b.*\bwhatsapp\b",
    r"\bseguridad\b.*\b(desactiva|apaga|quita|sella|sellar)\b|\b(desactiva|apaga|quita)\b.*\bseguridad\b",
)]


def _normalizar(texto):
    texto = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def es_orden_solo_pc(texto):
    """True si la orden es delicada y por eso solo se acepta escrita/dicha en el PC."""
    if os.environ.get("ARCHE_CELULAR_PERMITE_TODO") == "1":
        return False
    t = _normalizar(texto)
    return any(p.search(t) for p in _ORDENES_SOLO_PC)


def ip_permitida(ip):
    """Solo la red de casa, el propio PC y Tailscale."""
    try:
        d = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(d, "ipv4_mapped", None):
        d = d.ipv4_mapped
    return d.is_loopback or d.is_private or d.is_link_local or any(d in r for r in _REDES_TAILSCALE)

PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Arché</title><style>
:root{--f:#0a0916;--p:#13102a;--b:#2d2457;--t:#e8e4ff;--s:#8f89bd;--a:#5b7cff;--m:#9b6bff;--r:#e0435f}
*{box-sizing:border-box}body{margin:0;background:var(--f);color:var(--t);font:15px system-ui,sans-serif;
min-height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid var(--b)}
.orbe{width:38px;height:38px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff8,var(--c,var(--a)) 55%,#0000 72%);
box-shadow:0 0 22px var(--c,var(--a));animation:resp 3s ease-in-out infinite}
.hablando{--c:var(--r);animation-duration:.7s}.pensando{--c:var(--m);animation-duration:1.2s}.escuchando{--c:var(--a);animation-duration:1.6s}
@keyframes resp{50%{transform:scale(1.12)}}
h1{font-size:17px;margin:0;letter-spacing:.2em}small{color:var(--s)}
main{flex:1;overflow:auto;padding:12px 16px}
.m{margin:8px 0;padding:9px 12px;border-radius:14px;max-width:88%;background:var(--p);border:1px solid var(--b);word-wrap:break-word}
.m.tu{margin-left:auto;color:var(--a)}.m.arche{border-left:3px solid var(--m)}
.ctl{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;padding:0 16px 8px}
.ctl button{background:var(--p);color:var(--s);border:1px solid var(--b);border-radius:12px;padding:10px;font-size:13px;text-align:left}
.ctl button.on{color:var(--t);border-color:var(--m);background:#241c4a}
form{display:flex;gap:8px;padding:10px 16px calc(12px + env(safe-area-inset-bottom));border-top:1px solid var(--b)}
input{flex:1;background:var(--p);color:var(--t);border:1px solid var(--b);border-radius:12px;padding:12px;font-size:16px}
.go{background:var(--m);color:#fff;border:0;border-radius:12px;padding:0 18px;font-size:16px}
#pin{margin:auto;text-align:center;padding:24px}#pin input{width:180px;text-align:center;letter-spacing:.4em;margin:12px 0}
</style></head><body>
<div id="pin" hidden><h1>ARCHÉ</h1><p><small>Escribe el PIN que ves en la ventana de Arché</small></p>
<input id="pi" inputmode="numeric" maxlength="6" autocomplete="off"><br><button class="go" style="padding:12px 24px" onclick="entrar()">Entrar</button>
<p id="pe" style="color:var(--r)"></p></div>
<div id="app" hidden style="display:none;flex-direction:column;flex:1;min-height:0">
<header><div id="o" class="orbe"></div><div><h1>ARCHÉ</h1><small id="e">conectando…</small></div></header>
<main id="chat"></main><div class="ctl" id="ctl"></div>
<form onsubmit="return enviar()"><input id="t" placeholder="Escríbele a Arché…" autocomplete="off"><button class="go">▶</button></form></div>
<script>
let pin=localStorage.getItem('arche_pin')||'';
const H=()=>({'X-Pin':pin,'Content-Type':'application/json'});
function entrar(){pin=document.getElementById('pi').value.trim();localStorage.setItem('arche_pin',pin);cargar()}
async function cargar(){
 try{const r=await fetch('/api/estado',{headers:H()});
  if(r.status==401||r.status==429){document.getElementById('pin').hidden=false;document.getElementById('app').style.display='none';
   document.getElementById('pe').textContent=r.status==429?'Demasiados intentos, espera un minuto.':(pin?'PIN incorrecto':'');return}
  const d=await r.json();document.getElementById('pin').hidden=true;const a=document.getElementById('app');a.style.display='flex';a.hidden=false;
  document.getElementById('o').className='orbe '+d.estado;document.getElementById('e').textContent=d.estado;
  const c=document.getElementById('chat'),abajo=c.scrollTop+c.clientHeight>=c.scrollHeight-40;
  c.innerHTML=d.chat.map(m=>'<div class="m '+m.q+'">'+m.t.replace(/[<>&]/g,x=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[x]))+'</div>').join('');
  if(abajo)c.scrollTop=c.scrollHeight;
  pintarAviso();
  document.getElementById('ctl').innerHTML=d.controles.map(x=>{
   if(x.tipo=='switch')return '<button class="'+(x.valor?'on':'')+'" onclick="cmd(\\''+(x.valor?x.off:x.on)+'\\')">'+(x.valor?'● ':'○ ')+x.nombre+'</button>';
   return x.niveles.map(n=>'<button class="'+(x.valor==n[0]?'on':'')+'" onclick="cmd(\\''+n[1]+'\\')">'+x.nombre+': '+n[0]+'</button>').join('')}).join('');
 }catch(e){document.getElementById('e').textContent='sin conexión'}}
async function cmd(t){
 try{const r=await fetch('/api/enviar',{method:'POST',headers:H(),body:JSON.stringify({texto:t})});
  const d=await r.json().catch(()=>({}));
  if(d.mensaje){aviso='🔒 '+d.mensaje;avisoHasta=Date.now()+8000}
 }catch(e){}
 setTimeout(cargar,400)}
let aviso='',avisoHasta=0;
function pintarAviso(){const c=document.getElementById('chat');if(Date.now()>avisoHasta)return;
 const m=document.createElement('div');m.className='m arche';m.style.borderLeftColor='var(--r)';m.textContent=aviso;
 c.appendChild(m);c.scrollTop=c.scrollHeight}
function enviar(){const i=document.getElementById('t');if(i.value.trim())cmd(i.value.trim());i.value='';return false}
cargar();setInterval(cargar,1500);
</script></body></html>"""


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _pin_aleatorio():
    return "%06d" % secrets.randbelow(1_000_000)


def _pin():
    pin = str(ajustes.obtener("celular_pin") or "")
    if len(pin) != 6 or not pin.isdigit():
        pin = _pin_aleatorio()
        ajustes.fijar("celular_pin", pin)
    return pin


def nuevo_pin():
    ajustes.fijar("celular_pin", _pin_aleatorio())
    return ajustes.obtener("celular_pin")


def activo():
    return _servidor is not None


def direccion():
    return f"http://{ip_local()}:{ajustes.obtener('celular_puerto')}"


def _auditar(evento, **detalle):
    """Deja constancia en la bitacora encadenada (si el modulo de seguridad esta)."""
    try:
        from core.seguridad import guardian
        guardian.auditar(evento, origen="celular", **detalle)
    except Exception:
        pass


def _limpiar_fallos(ahora):
    """Quita los registros vencidos para que la tabla no crezca sin limite."""
    for ip in [ip for ip, f in _fallos.items() if f[1] <= ahora]:
        _fallos.pop(ip, None)
    _fallos_globales[:] = [t for t in _fallos_globales if ahora - t < BLOQUEO_GLOBAL]


class _Manejador(BaseHTTPRequestHandler):
    server_version = "Arche"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos_ = cuerpo if isinstance(cuerpo, bytes) else cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos_)))
        self.send_header("Cache-Control", "no-store")
        for k, v in CABECERAS_SEGURIDAD.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos_)

    def _red_permitida(self):
        if ip_permitida(self.client_address[0]):
            return True
        _auditar("conexion_rechazada_red", ip=self.client_address[0])
        self._responder(403, "{}")
        return False

    def _autorizado(self):
        ip = self.client_address[0]
        ahora = time.time()
        with _lock_fallos:
            _limpiar_fallos(ahora)
            if len(_fallos_globales) >= MAX_FALLOS_GLOBALES:
                self._responder(429, "{}")
                return False
            fallos = _fallos.get(ip)
            if fallos and fallos[0] >= MAX_FALLOS_POR_IP and ahora < fallos[1]:
                self._responder(429, "{}")
                return False
            enviado = self.headers.get("X-Pin", "")
            if hmac.compare_digest(enviado.encode(), _pin().encode()):
                _fallos.pop(ip, None)
                return True
            f = _fallos.setdefault(ip, [0, 0])
            f[0] += 1
            f[1] = ahora + BLOQUEO_IP
            _fallos_globales.append(ahora)
            n_ip, n_global = f[0], len(_fallos_globales)
        _auditar("pin_incorrecto", ip=ip, fallos_ip=n_ip, fallos_globales=n_global)
        self._responder(401, "{}")
        return False

    def do_GET(self):
        if not self._red_permitida():
            return
        if self.path in ("/", "/index.html"):
            return self._responder(200, PAGINA, "text/html; charset=utf-8")
        if self.path.startswith("/api/estado"):
            if not self._autorizado():
                return
            en_vivo.sondear()
            ctl = []
            for c in datos.controles():
                item = {k: c[k] for k in ("id", "nombre", "tipo", "valor", "detalle")}
                if c["tipo"] == "switch":
                    item.update(on=c["on"], off=c["off"])
                else:
                    item["niveles"] = c["niveles"]
                ctl.append(item)
            chat = [{"q": m["q"], "t": m["t"]} for m in list(en_vivo.chat)[-30:]]
            return self._responder(200, json.dumps({"estado": en_vivo.estado_visual(), "chat": chat,
                                                    "controles": ctl}, ensure_ascii=False))
        self._responder(404, "{}")

    def do_POST(self):
        if not self._red_permitida():
            return
        if self.path != "/api/enviar":
            return self._responder(404, "{}")
        if not self._autorizado():
            return
        try:
            largo = min(int(self.headers.get("Content-Length", "0")), 2000)
            texto = json.loads(self.rfile.read(largo) or b"{}").get("texto", "")
        except Exception:
            texto = ""
        texto = str(texto)[:500]
        if es_orden_solo_pc(texto):
            _auditar("orden_delicada_rechazada", ip=self.client_address[0], texto=texto[:120])
            return self._responder(200, json.dumps({
                "ok": False,
                "mensaje": "Esa orden es delicada: solo la acepto desde el PC, no desde el celular."},
                ensure_ascii=False))
        entrada.enviar(texto, "celular")
        self._responder(200, '{"ok":true}')

    # Cualquier otro metodo (PUT, DELETE, ...) se rechaza.
    def _no_permitido(self):
        self._responder(405, "{}")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _no_permitido


def iniciar():
    """Enciende la pagina del celular. Devuelve (ok, mensaje)."""
    global _servidor, _hilo
    if _servidor is not None:
        return True, direccion()
    _pin()
    try:
        _servidor = ThreadingHTTPServer(("0.0.0.0", int(ajustes.obtener("celular_puerto"))), _Manejador)
    except Exception as e:
        _servidor = None
        return False, f"No pude abrir el puerto ({e})."
    _hilo = threading.Thread(target=_servidor.serve_forever, name="arche-celular", daemon=True)
    _hilo.start()
    ajustes.fijar("celular", True)
    return True, direccion()


def detener():
    global _servidor
    if _servidor is not None:
        try:
            _servidor.shutdown()
            _servidor.server_close()
        except Exception:
            pass
    _servidor = None
    ajustes.fijar("celular", False)
