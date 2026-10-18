"""
remoto.py
---------
Ubicacion: Arche/core/interfaz/remoto.py

Control de Arché desde el celular: una paginita web que Arché sirve en tu red
wifi. Abres la direccion en el navegador del celular, pones el PIN y puedes
escribirle, ver la conversacion y prender o apagar sus funciones.

Seguridad: apagado por defecto; pide un PIN de 6 numeros (se ve en AJUSTES);
tras 5 PIN malos bloquea esa direccion un minuto, y si en total hay demasiados
fallos (desde cualquier direccion) bloquea a todos un rato; solo escucha en la
IP de tu red local (no en todas las interfaces); y desde el celular NO se
aceptan las ordenes delicadas (apagar, teclear, borrar archivos, tocar el
codigo o las claves...): esas solo se dan desde el PC.
No uses esto en una wifi publica: la conexion es HTTP sin cifrar, asi que
cualquiera que pueda espiar esa wifi podria ver el PIN. Para usarlo fuera de
casa, entra por una VPN (por ejemplo Tailscale) en vez de abrir el puerto.

Variables de entorno (opcionales):
  ARCHE_CELULAR_HOST=0.0.0.0        escuchar en todas las interfaces (como antes)
  ARCHE_CELULAR_PERMITE_TODO=1      aceptar tambien las ordenes delicadas desde el celular
"""

import hmac
import json
import os
import random
import re
import socket
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ajustes, datos, en_vivo, entrada

_servidor = None
_hilo = None
_fallos = {}      # ip -> [cuantos, hasta_cuando]
_fallos_globales = []   # marcas de tiempo de PIN malos de cualquier direccion
MAX_FALLOS_GLOBALES = 40          # en la ventana de abajo, se bloquea a todos
VENTANA_FALLOS_GLOBALES = 600     # segundos
BLOQUEO_GLOBAL = 300              # segundos

# Ordenes que Arche NO acepta desde el celular (si desde el PC): quien tenga el PIN no debe
# poder apagarte el equipo, teclear en tu lugar, borrar archivos, tocar el codigo ni las claves.
_ORDENES_SOLO_PC = re.compile(
    r"\b(apaga|apagar|reinicia|reiniciar|suspende|suspender|hiberna|cierra la sesion|"
    r"teclea|presiona|formatea|instala|desinstala|ejecuta|"
    r"cambia esto|autocodigo|aplica|aprueba|deshaz|revierte|restaura|revisate y arregla|"
    r"nivel total|clave|comparte mi memoria)\b"
    r"|\b(borra|borrar|elimina|eliminar)\b.*\b(archivo|archivos|carpeta|carpetas|documento|documentos|"
    r"foto|fotos|descargas|disco|todo)\b"
)


def _normalizar(texto):
    sin_tildes = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn").strip()


def es_orden_solo_pc(texto):
    """True si la orden es de las que el celular no puede dar."""
    if os.environ.get("ARCHE_CELULAR_PERMITE_TODO") == "1":
        return False
    return bool(_ORDENES_SOLO_PC.search(_normalizar(texto)))


def _bloqueo_global():
    ahora = time.time()
    _fallos_globales[:] = [t for t in _fallos_globales if ahora - t < VENTANA_FALLOS_GLOBALES]
    return len(_fallos_globales) >= MAX_FALLOS_GLOBALES


def _limpiar_fallos():
    """Que el registro de direcciones no crezca sin limite."""
    if len(_fallos) > 200:
        ahora = time.time()
        for ip in [i for i, f in _fallos.items() if f[1] < ahora]:
            _fallos.pop(ip, None)

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
  document.getElementById('ctl').innerHTML=d.controles.map(x=>{
   if(x.tipo=='switch')return '<button class="'+(x.valor?'on':'')+'" onclick="cmd(\\''+(x.valor?x.off:x.on)+'\\')">'+(x.valor?'● ':'○ ')+x.nombre+'</button>';
   return x.niveles.map(n=>'<button class="'+(x.valor==n[0]?'on':'')+'" onclick="cmd(\\''+n[1]+'\\')">'+x.nombre+': '+n[0]+'</button>').join('')}).join('');
 }catch(e){document.getElementById('e').textContent='sin conexión'}}
async function cmd(t){const r=await fetch('/api/enviar',{method:'POST',headers:H(),body:JSON.stringify({texto:t})});
 try{const d=await r.json();if(d&&d.mensaje)alert(d.mensaje)}catch(e){}
 setTimeout(cargar,400)}
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


def _pin():
    pin = str(ajustes.obtener("celular_pin") or "")
    if len(pin) != 6 or not pin.isdigit():
        pin = "%06d" % random.randint(0, 999999)
        ajustes.fijar("celular_pin", pin)
    return pin


def nuevo_pin():
    ajustes.fijar("celular_pin", "%06d" % random.randint(0, 999999))
    return ajustes.obtener("celular_pin")


def activo():
    return _servidor is not None


def direccion():
    return f"http://{ip_local()}:{ajustes.obtener('celular_puerto')}"


class _Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos_ = cuerpo if isinstance(cuerpo, bytes) else cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos_)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(datos_)

    def _autorizado(self):
        ip = self.client_address[0]
        if _bloqueo_global():
            self._responder(429, "{}")
            return False
        fallos = _fallos.get(ip)
        if fallos and fallos[0] >= 5 and time.time() < fallos[1]:
            self._responder(429, "{}")
            return False
        enviado = self.headers.get("X-Pin", "")
        if hmac.compare_digest(enviado.encode(), _pin().encode()):
            _fallos.pop(ip, None)
            return True
        _limpiar_fallos()
        f = _fallos.setdefault(ip, [0, 0])
        f[0] += 1
        f[1] = time.time() + 60
        ahora = time.time()
        _fallos_globales.append(ahora)
        if _bloqueo_global():
            # Al saltar el tope global, el bloqueo dura BLOQUEO_GLOBAL: se alarga la ventana
            # de las marcas para que no se libere a los pocos segundos.
            _fallos_globales[:] = [ahora + BLOQUEO_GLOBAL - VENTANA_FALLOS_GLOBALES] * MAX_FALLOS_GLOBALES
        self._responder(401, "{}")
        return False

    def do_GET(self):
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
        if self.path != "/api/enviar" or not self._autorizado():
            if self.path != "/api/enviar":
                self._responder(404, "{}")
            return
        try:
            largo = min(int(self.headers.get("Content-Length", "0")), 2000)
            texto = json.loads(self.rfile.read(largo) or b"{}").get("texto", "")
        except Exception:
            texto = ""
        texto = str(texto)[:500]
        if es_orden_solo_pc(texto):
            return self._responder(200, json.dumps(
                {"ok": False, "mensaje": "Esa orden solo la acepto desde el PC, no desde el celular."},
                ensure_ascii=False))
        entrada.enviar(texto, "celular")
        self._responder(200, '{"ok":true}')


def iniciar():
    """Enciende la pagina del celular. Devuelve (ok, mensaje)."""
    global _servidor, _hilo
    if _servidor is not None:
        return True, direccion()
    _pin()
    # Solo en la IP de la red local (la que usa el celular para llegar), no en todas las
    # interfaces. Sin red, ip_local() da 127.0.0.1 y queda solo accesible desde este PC.
    host = os.environ.get("ARCHE_CELULAR_HOST") or ip_local()
    try:
        _servidor = ThreadingHTTPServer((host, int(ajustes.obtener("celular_puerto"))), _Manejador)
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