"""
avatar.py
---------
Ubicacion: Arche/core/nucleo/avatar.py

PRESENCIA VISUAL: Arché vive en tu escritorio (sin ventana, siempre encima, en una esquina)
aunque no tengas la interfaz abierta. Es EXACTAMENTE la misma figura de tu interfaz:

  * Con la interfaz web (pywebview instalado): el avatar usa el MISMO código de dibujo de
    core/interfaz/web/app.js (la función dibujarOrbe, que se copia sola cada vez que se
    abre), y los MISMOS ajustes y colores del tema. Si en la interfaz cambias la forma
    (esfera, ondas, anillos, núcleo, geométrica), el color, el tamaño, la velocidad, el
    brillo, las chispas o el tema, el avatar cambia solo en menos de un segundo.
  * Sin pywebview: usa el mismo dibujo de la ventana clásica (core/interfaz/ventana.py,
    _dibujar_voz) con los mismos ajustes y tema, también sincronizado.

Lo que muestra es lo mismo que la interfaz: reposo, escuchando, pensando, hablando.
Además, cuando el equipo o el Depredador trabajan, aparece «pensando», y cuando llevas
más de 30 minutos sin usar el PC (o es de madrugada) se atenúa.
Los avisos de Arché salen en un globo a su lado (con borde rojo si es una alerta).
  clic          -> abre la interfaz (o la burbuja para escribirle, si arche_fondo.pyw está corriendo)
  arrastrar     -> la mueves (recuerda dónde la dejaste)

Comandos: muestra el avatar · esconde el avatar · avatar grande · avatar pequeño
(«grande/pequeño» cambia el tamaño de la ventanita; el tamaño de la figura dentro de ella
es el mismo ajuste «Tamaño de la esfera» de tu interfaz.)
"""

import importlib.util
import os
import re
import subprocess
import sys
import time

from core.nucleo import comun

ARCH = comun.ruta("avatar.json")
ARCH_POSICION = comun.ruta("avatar_posicion.json")
TRANSPARENTE = "#010203"
ANCHO_GLOBO = 250
APP_JS = os.path.join(comun.BASE, "core", "interfaz", "web", "app.js")

_control = {"hilo": None, "parar": False, "orden": None, "proceso": None, "servidor_listo": False, "modo": None}


def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("tamano", 200)
    return e


def _guardar(e):
    comun.guardar(ARCH, e)


def _posicion():
    p = comun.cargar(ARCH_POSICION, {})
    return p.get("x"), p.get("y")


# ------------------------------------------------------------------
# Qué estado mostrar (el mismo de la interfaz + lo que hace el núcleo)
# ------------------------------------------------------------------

def estado_actual(base=None, ocupado=None, inactivo=None, hora=None):
    """reposo | escuchando | pensando | hablando | desconectado (atenuada)."""
    if base is None:
        try:
            from core.interfaz import en_vivo
            base = en_vivo.estado_visual()
        except Exception:
            base = "reposo"
    if base in ("hablando", "escuchando", "pensando"):
        if base == "escuchando" and ocupado:
            return "pensando"
        return base
    if ocupado is None:
        ocupado = False
        try:
            from core.nucleo import equipo, depredador
            ocupado = bool(equipo._mision_en_curso["id"]) or depredador._lock_caza.locked()
        except Exception:
            pass
    if ocupado:
        return "pensando"
    if inactivo is None:
        try:
            from core.nucleo import ritmo
            inactivo = ritmo.minutos_inactivo()
        except Exception:
            inactivo = 0
    hora = comun.ahora().hour if hora is None else hora
    if inactivo > 30 or 1 <= hora < 5:
        return "desconectado"
    return "reposo"


def globo_actual():
    g = comun.ultimo_globo()
    edad = time.time() - float(g.get("cuando", 0) or 0)
    texto = (g.get("texto") or "").split("\n")[0]
    return {"texto": texto[:180] + ("…" if len(texto) > 180 else ""), "nivel": g.get("nivel", "info"),
            "edad": round(edad, 1)}


# ------------------------------------------------------------------
# MODO WEB: el mismo dibujo de app.js
# ------------------------------------------------------------------

def _saltar_cadena(js, i):
    """i apunta a una comilla; devuelve el índice justo después de la cadena."""
    q = js[i]
    i += 1
    while i < len(js):
        ch = js[i]
        if ch == "\\":
            i += 2
            continue
        if q == "`" and ch == "$" and js[i + 1:i + 2] == "{":
            i = _cerrar(js, i + 1, "{", "}")
            continue
        if ch == q:
            return i + 1
        i += 1
    return i


def _cerrar(js, i, abre, cierra):
    """i apunta a 'abre'; devuelve el índice justo después de su 'cierra' correspondiente."""
    nivel = 0
    while i < len(js):
        ch = js[i]
        if ch in "\"'`":
            i = _saltar_cadena(js, i)
            continue
        if ch == "/" and js[i + 1:i + 2] == "/":
            i = js.find("\n", i)
            i = len(js) if i == -1 else i
            continue
        if ch == "/" and js[i + 1:i + 2] == "*":
            i = js.find("*/", i + 2)
            i = len(js) if i == -1 else i + 2
            continue
        if ch == abre:
            nivel += 1
        elif ch == cierra:
            nivel -= 1
            if nivel == 0:
                return i + 1
        i += 1
    return i


def extraer_funcion(js, nombre):
    m = re.search(r"(?m)^(?:async\s+)?function\s+" + re.escape(nombre) + r"\s*\(", js)
    if not m:
        return None
    fin_params = _cerrar(js, m.end() - 1, "(", ")")
    inicio_cuerpo = js.index("{", fin_params)
    return js[m.start():_cerrar(js, inicio_cuerpo, "{", "}")]


def funciones_de_dibujo(js, raiz="dibujarOrbe"):
    """El código de dibujarOrbe y de todas las funciones de app.js que usa (hexRgb, rgba, esferaBase...)."""
    definidas = set(re.findall(r"(?m)^(?:async\s+)?function\s+(\w+)\s*\(", js))
    pendientes, hechas, trozos = [raiz], set(), []
    while pendientes:
        nombre = pendientes.pop()
        if nombre in hechas or nombre not in definidas:
            continue
        hechas.add(nombre)
        codigo = extraer_funcion(js, nombre)
        if not codigo:
            continue
        trozos.append(codigo)
        for usado in re.findall(r"\b([A-Za-z_]\w*)\s*\(", codigo):
            if usado in definidas and usado not in hechas:
                pendientes.append(usado)
    return "\n\n".join(reversed(trozos)), hechas


_JS_AVATAR = r"""
"use strict";
const LLAVE = (location.hash.match(/llave=([\w\-]+)/) || [])[1] || "";
const S = { ajustes: {}, colores: {}, estado: "reposo", colorEsfera: { a: null, b: null } };
const cv = document.getElementById("orbe");
const O = { cv, grande: cv.width >= 180, chispas: [] };
const globo = document.getElementById("globo");
let fallos = 0, ultimo = 0, error = false;

async function sondear() {
  try {
    const r = await fetch("/api/avatar", { headers: { "X-Llave": LLAVE } });
    const d = await r.json();
    S.ajustes = d.ajustes || {};
    S.colores = (d.tema && d.tema.colores) || {};
    S.colorEsfera = { a: S.ajustes.web_acento_2 || null, b: S.ajustes.web_acento || null };   // igual que aplicarAcentos()
    S.estado = d.estado || "reposo";
    const g = d.globo || {};
    if (g.texto && g.edad < 12) {
      globo.textContent = g.texto;
      globo.className = "visible " + (g.nivel || "");
      globo.style.borderColor = g.nivel === "alerta" ? (S.colores.alerta || "#e0435f") : (S.colores.morado_claro || "#9b6bff");
      globo.style.background = S.colores.panel2 || S.colores.panel || "#1b1f33";
      globo.style.color = S.colores.texto || "#e8e4ff";
    } else {
      globo.className = "";
    }
    fallos = 0;
  } catch (e) {
    fallos++;
    if (fallos > 20) S.estado = "desconectado";
  }
}

function respaldo() {
  const c = cv.getContext("2d"), W = cv.width, H = cv.height;
  c.clearRect(0, 0, W, H);
  c.fillStyle = S.colores.morado_claro || "#9b6bff";
  c.beginPath(); c.arc(W / 2, H / 2, Math.min(W, H) * .25, 0, Math.PI * 2); c.fill();
}

function animar(t) {
  const reducido = S.ajustes.reducir_movimiento;
  if (t - ultimo >= (reducido ? 500 : 33)) {
    ultimo = t;
    try { dibujarOrbe(O, reducido ? 0 : t); }
    catch (e) { if (!error) { error = true; console.error(e); } respaldo(); }
  }
  requestAnimationFrame(animar);
}

cv.addEventListener("click", () => {
  fetch("/api/avatar_clic", { method: "POST", headers: { "X-Llave": LLAVE, "Content-Type": "application/json" }, body: "{}" });
});
sondear(); setInterval(sondear, 700);
requestAnimationFrame(animar);
"""


def js_avatar():
    try:
        with open(APP_JS, "r", encoding="utf-8") as f:
            app = f.read()
        dibujo, _ = funciones_de_dibujo(app)
    except OSError:
        dibujo = ""
    if "function dibujarOrbe" not in dibujo:
        dibujo = "function dibujarOrbe() { throw new Error('no encontré dibujarOrbe en app.js'); }"
    return "/* Avatar de Arché: el dibujo viene tal cual de app.js */\n" + dibujo + "\n" + _JS_AVATAR


def html_avatar(lado):
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Arché</title>
<style>
  html, body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; user-select: none; }}
  body {{ display: flex; align-items: center; justify-content: flex-end; height: 100vh; font-family: "Segoe UI", sans-serif; }}
  #globo {{ max-width: {ANCHO_GLOBO - 20}px; margin-right: 6px; padding: 9px 12px; border: 2px solid; border-radius: 14px;
           font-size: 13px; line-height: 1.35; opacity: 0; transform: translateX(8px); transition: opacity .3s, transform .3s; }}
  #globo.visible {{ opacity: .97; transform: none; }}
  canvas {{ cursor: pointer; flex: none; }}
</style></head>
<body><div id="globo"></div><canvas id="orbe" width="{lado}" height="{lado}"></canvas>
<script src="/avatar.js"></script></body></html>"""


def datos_web():
    """Lo que la página del avatar pide cada 0,7 s. No consume avisos ni mensajes de la interfaz."""
    from core.interfaz import ajustes
    from core.interfaz import web
    return {"estado": estado_actual(), "tema": web._colores_tema(),
            "ajustes": {k: ajustes.obtener(k) for k in web._AJUSTES_PAGINA}, "globo": globo_actual()}


def _clic():
    if os.environ.get("ARCHE_FONDO") == "1":
        try:
            from core import presencia
            presencia.abrir_burbuja()
            return
        except Exception:
            pass
    try:
        from core.interfaz import web
        web.abrir()
    except Exception:
        pass


def instalar_en_servidor():
    """Agrega /avatar, /avatar.js, /api/avatar y /api/avatar_clic al servidor de la interfaz web
    (sin modificar core/interfaz/web/__init__.py)."""
    if _control["servidor_listo"]:
        return
    from urllib.parse import urlparse
    from core.interfaz import web
    manejador = web._Manejador
    get_original, post_original = manejador.do_GET, manejador.do_POST
    csp = {"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                      "script-src 'self'"}

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta in ("/avatar", "/avatar.js", "/api/avatar"):
            if not self._host_ok():
                return self._responder(403, "{}")
            if ruta == "/avatar":
                return self._responder(200, html_avatar(int(_estado()["tamano"])), "text/html; charset=utf-8", csp)
            if ruta == "/avatar.js":
                return self._responder(200, js_avatar(), "application/javascript; charset=utf-8", csp)
            if not self._llave_ok():
                return self._responder(401, "{}")
            return self._json(datos_web())
        return get_original(self)

    def do_POST(self):
        if urlparse(self.path).path == "/api/avatar_clic":
            if not (self._host_ok() and self._llave_ok()):
                return self._responder(401, "{}")
            comun.en_hilo(_clic, nombre="arche-avatar-clic")
            return self._json({"ok": True})
        return post_original(self)

    manejador.do_GET = do_GET
    manejador.do_POST = do_POST
    _control["servidor_listo"] = True


def _iniciar_web():
    from core.interfaz import web
    instalar_en_servidor()
    web.iniciar()
    url = f"http://127.0.0.1:{web._puerto}/avatar#llave={web._llave}"
    lado = int(_estado()["tamano"])
    x, y = _posicion()
    extra = {"creationflags": 0x08000000} if os.name == "nt" else {}
    _control["proceso"] = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar_ventana.py"),
         url, str(lado + ANCHO_GLOBO), str(lado), "-" if x is None else str(x), "-" if y is None else str(y),
         ARCH_POSICION, str(os.getpid())],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
    return True


# ------------------------------------------------------------------
# MODO CLÁSICO: el mismo dibujo de la ventana Tk
# ------------------------------------------------------------------

def _espejo_clasico(canvas):
    """Un objeto con lo mínimo que necesita VentanaArche._dibujar_voz, usando sus MISMOS métodos."""
    from core.interfaz import ventana as V
    clase = V.VentanaArche
    atributos = {nombre: getattr(clase, nombre) for nombre in
                 ("_dibujar_voz", "_particulas", "_linea", "_ahorro", "_reducido", "etiqueta_estado", "_actualizar_ondas")}
    Espejo = type("EspejoVentana", (), atributos)
    e = Espejo()
    e.canvas, e._tag = canvas, "avatar"
    e.fase, e.nivel = 0.0, 0.0
    e.alturas = [0.0] * V.BARRAS
    e.objetivo = [0.0] * V.BARRAS
    return e, V.ESTADO_BASE


def _correr_clasico():
    import tkinter as tk
    from core.interfaz import ajustes, tema
    lado = int(_estado()["tamano"])
    ancho, alto = lado + ANCHO_GLOBO, lado
    raiz = tk.Tk()
    raiz.overrideredirect(True)
    raiz.attributes("-topmost", True)
    try:
        raiz.attributes("-transparentcolor", TRANSPARENTE)
    except tk.TclError:
        pass
    raiz.configure(bg=TRANSPARENTE)
    x, y = _posicion()
    x = x if x is not None else raiz.winfo_screenwidth() - ancho - 20
    y = y if y is not None else raiz.winfo_screenheight() - alto - 70
    raiz.geometry(f"{ancho}x{alto}+{int(x)}+{int(y)}")
    lienzo = tk.Canvas(raiz, width=ancho, height=alto, bg=TRANSPARENTE, highlightthickness=0)
    lienzo.pack()
    espejo, estado_base = _espejo_clasico(lienzo)
    arrastre = {"x": 0, "y": 0, "movio": False}
    sincro = {"mtime": 0.0, "revisado": 0.0}

    def _presionar(ev):
        arrastre.update(x=ev.x, y=ev.y, movio=False)

    def _mover(ev):
        arrastre["movio"] = True
        raiz.geometry(f"+{raiz.winfo_x() + ev.x - arrastre['x']}+{raiz.winfo_y() + ev.y - arrastre['y']}")

    def _soltar(ev):
        if arrastre["movio"]:
            comun.guardar(ARCH_POSICION, {"x": raiz.winfo_x(), "y": raiz.winfo_y()})
        else:
            comun.en_hilo(_clic, nombre="arche-avatar-clic")

    lienzo.bind("<ButtonPress-1>", _presionar)
    lienzo.bind("<B1-Motion>", _mover)
    lienzo.bind("<ButtonRelease-1>", _soltar)

    def _sincronizar():
        """Si cambiaste algo en la interfaz (aunque sea en otro proceso), se vuelve a leer."""
        if time.time() - sincro["revisado"] < 1:
            return
        sincro["revisado"] = time.time()
        try:
            m = os.path.getmtime(ajustes._ARCHIVO)
            if m != sincro["mtime"]:
                sincro["mtime"] = m
                with ajustes._lock:
                    ajustes._datos = None
        except OSError:
            pass
        deseado = ajustes.obtener("tema")
        if deseado and tema.resolver(deseado) and tema.resolver(deseado) != tema.actual():
            tema.aplicar(deseado)

    def _cuadro():
        orden = _control.get("orden")
        if _control["parar"] or orden in ("esconder", "reiniciar"):
            raiz.destroy()
            return
        _sincronizar()
        estado = estado_actual()
        quieto = estado == "desconectado"
        base = estado_base.get(estado, "reposo")
        hablando = estado == "hablando"
        try:
            espejo._actualizar_ondas(hablando, estado in ("escuchando", "pensando"))
        except Exception:
            pass
        lienzo.delete("all")
        try:
            espejo._dibujar_voz(ANCHO_GLOBO, 0, lado, lado, estado if not quieto else "reposo", base, lado / 300.0,
                                True, quieto)
        except Exception:
            lienzo.create_oval(ANCHO_GLOBO + lado * .25, lado * .25, ANCHO_GLOBO + lado * .75, lado * .75,
                               fill=tema.MORADO_CLARO, outline="")
        g = globo_actual()
        if g["texto"] and g["edad"] < 12:
            item = lienzo.create_text(ANCHO_GLOBO - 16, alto / 2, text=g["texto"], anchor="e", width=ANCHO_GLOBO - 30,
                                      fill=tema.TEXTO, font=(tema.FUENTE, 10))
            x1, y1, x2, y2 = lienzo.bbox(item)
            borde = tema.ALERTA if g["nivel"] == "alerta" else tema.MORADO_CLARO
            lienzo.create_rectangle(x1 - 9, y1 - 7, x2 + 9, y2 + 7, fill=tema.PANEL_2, outline=borde, width=2)
            lienzo.tag_raise(item)
        intervalo = 500 if ajustes.obtener("reducir_movimiento") else 40
        raiz.after(intervalo, _cuadro)

    _cuadro()
    raiz.mainloop()
    if _control.get("orden") == "reiniciar" and not _control["parar"]:
        _control["orden"] = None
        _correr_clasico()


# ------------------------------------------------------------------
# Arranque y comandos
# ------------------------------------------------------------------

def modo():
    """'web' si se puede abrir la ventana transparente con pywebview; si no, 'clasico'."""
    return "web" if importlib.util.find_spec("webview") is not None else "clasico"


def activo():
    if _control["proceso"] is not None and _control["proceso"].poll() is None:
        return True
    return _control["hilo"] is not None and _control["hilo"].is_alive()


def iniciar(forzar=False):
    """Arranca el avatar (solo en Windows, salvo forzar=True). No hace nada si ya está."""
    if activo():
        return True
    if not forzar and (not comun.es_windows() or not _estado()["activo"]):
        return False
    _control.update(parar=False, orden=None)
    _control["modo"] = modo()
    if _control["modo"] == "web":
        try:
            return _iniciar_web()
        except Exception as e:
            comun.anotar(comun.ruta("errores.jsonl"), {"cuando": comun.ahora_txt(), "donde": "avatar_web",
                                                       "error": repr(e)[:300]})
            _control["modo"] = "clasico"
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    _control["hilo"] = comun.en_hilo(_correr_clasico, nombre="arche-avatar")
    return True


def detener():
    _control["parar"] = True
    p = _control.get("proceso")
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    _control["proceso"] = None


def _reiniciar():
    if _control["modo"] == "web":
        detener()
        time.sleep(0.5)
        iniciar(forzar=True)
    else:
        _control["orden"] = "reiniciar"


def manejar(comando):
    c = comun.norm(comando)
    if c in ("muestra el avatar", "muestra tu avatar", "avatar encendido", "aparece en el escritorio", "muestrate"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg("Aquí estoy, en la esquina de tu pantalla, con la misma forma de tu interfaz."
                  if iniciar(forzar=True) else "No pude mostrarme (falta tkinter o pywebview).")
        return True
    if c in ("esconde el avatar", "esconde tu avatar", "avatar apagado", "quitate del escritorio"):
        e = _estado(); e["activo"] = False; _guardar(e)
        _control["orden"] = "esconder"
        detener()
        comun.msg("Me escondo. Di «muestra el avatar» para volver.")
        return True
    if c in ("avatar grande", "avatar mas grande", "hazte mas grande"):
        e = _estado(); e["tamano"] = min(420, int(e["tamano"]) + 40); _guardar(e)
        _reiniciar()
        comun.msg("Más grande.")
        return True
    if c in ("avatar pequeno", "avatar mas pequeno", "hazte mas pequena", "avatar chiquito"):
        e = _estado(); e["tamano"] = max(100, int(e["tamano"]) - 40); _guardar(e)
        _reiniciar()
        comun.msg("Más pequeña.")
        return True
    return False

