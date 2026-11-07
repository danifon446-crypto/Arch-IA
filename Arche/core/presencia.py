"""
presencia.py
------------
Ubicacion: Arche/core/presencia.py

Lo que hace que Arché "viva" en el PC aunque no tengas nada abierto.
La arranca arche_fondo.pyw (no main.py), así que con la consola normal no cambia nada.

  1. ATAJOS DE TECLADO (funcionan en cualquier app, incluso en juegos con ventana):
       Ctrl+Alt+A  -> burbuja: una cajita arriba de la pantalla para escribirle
       Ctrl+Alt+I  -> abre la interfaz completa
       Ctrl+Alt+V  -> prende / apaga el micrófono («oye Arché ...»)
  2. BURBUJA: escribes, Enter, y la respuesta sale ahí mismo. Esc la esconde.
     Por dentro es un "canal" igual que Telegram (core/canales.py), así que
     main.py la trata como cualquier otro mensaje y te responde a ti.
  3. ICONO EN LA BANDEJA (junto al reloj): Hablar, Interfaz, Micrófono, Salir.
  4. NOTIFICACIONES DE WINDOWS: cuando Arché dice algo por su cuenta
     (un aviso, una alarma, una mejora que hizo) te llega como notificación.
  5. VOZ: si en CONFIG "escuchar_al_iniciar" es True, el micrófono arranca solo.

Librerías (se instalan solas la primera vez): keyboard, pystray, pillow, winotify.
Si alguna falta o falla, esa parte se apaga y Arché sigue funcionando.
"""

import queue
import sys
import threading
import time

# ------------------------------------------------------------------
# Configuración (cámbiala aquí)
# ------------------------------------------------------------------
CONFIG = {
    "atajo_burbuja": "ctrl+alt+a",
    "atajo_interfaz": "ctrl+alt+i",
    "atajo_microfono": "ctrl+alt+v",
    "escuchar_al_iniciar": True,      # micrófono prendido desde que arranca
    "notificaciones": True,           # avisos de Windows cuando Arché habla sola
    "segundos_entre_avisos": 20,      # para que no te llene de notificaciones
    "esconder_burbuja_tras": 25,      # segundos después de responder (0 = no se esconde sola)
}

_LIBRERIAS = {"keyboard": "keyboard", "pystray": "pystray", "PIL": "pillow", "winotify": "winotify"}

_estado = {"vivo": False, "ultimo_aviso": 0.0, "burbuja_visible": False}
_pedidos_burbuja = queue.Queue()      # lo que la burbuja tiene que hacer (mostrar, respuesta...)
_icono = None


def _log(texto):
    print(f"(presencia) {texto}")


# ------------------------------------------------------------------
# Librerías
# ------------------------------------------------------------------

def _asegurar_librerias():
    try:
        from core import instalador
        instalador.DEPENDENCIAS.update(_LIBRERIAS)
        instalador.verificar_e_instalar(list(_LIBRERIAS))
    except Exception as e:
        _log(f"no pude instalar librerías: {e}")


# ------------------------------------------------------------------
# Hablar con Arché por el "canal" burbuja
# ------------------------------------------------------------------

def _respuesta_de_arche(destino, texto):
    """canales.py llama esto cuando Arché termina de responder algo que vino de la burbuja."""
    _pedidos_burbuja.put(("respuesta", texto))


def _mandar_a_arche(texto):
    from core import canales
    canales.poner("burbuja", "pc", texto)


# ------------------------------------------------------------------
# La burbuja (Tkinter, en su propio hilo)
# ------------------------------------------------------------------

def _redondear_esquinas(raiz):
    """Windows 11: esquinas redondeadas y sombra de verdad en la burbuja (en Windows 10 no hace nada)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(raiz.winfo_id()) or raiz.winfo_id()
        valor = ctypes.c_int(2)                                   # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(valor), ctypes.sizeof(valor))
    except Exception:
        pass


def _hilo_burbuja():
    import tkinter as tk
    import tkinter.font as tkfont

    C = {"fondo": "#12101d", "caja": "#1d1a2e", "caja_foco": "#25213b", "borde": "#2c2745", "texto": "#ededf4",
         "suave": "#8d8aa3", "tenue": "#5d5a73", "acento": "#8b7cff", "pensando": "#c39bff", "ok": "#4fd08b",
         "error": "#ff7088"}
    ANCHO, ALTO_RESP_MAX = 640, 260
    MARCADOR = "Pregúntale algo a Arché…"

    raiz = tk.Tk()
    raiz.withdraw()
    raiz.overrideredirect(True)
    raiz.attributes("-topmost", True)
    raiz.configure(bg=C["borde"])                         # 1 px de borde alrededor

    letra = "Segoe UI Variable Text" if "Segoe UI Variable Text" in tkfont.families() else "Segoe UI"
    F_CAJA, F_RESP, F_CHICA, F_NOMBRE = (letra, 14), (letra, 11), (letra, 9), (letra, 9, "bold")

    marco = tk.Frame(raiz, bg=C["fondo"], padx=16, pady=14)
    marco.pack(fill="both", expand=True, padx=1, pady=1)

    # --- fila de arriba: esfera + caja de texto + botón enviar ---
    fila = tk.Frame(marco, bg=C["caja"], padx=12, pady=8)
    fila.pack(fill="x")
    esfera = tk.Canvas(fila, width=26, height=26, bg=C["caja"], highlightthickness=0)
    esfera.pack(side="left")
    caja = tk.Entry(fila, bg=C["caja"], fg=C["suave"], insertbackground=C["texto"], relief="flat",
                    font=F_CAJA, highlightthickness=0, bd=0)
    caja.pack(side="left", fill="x", expand=True, padx=(10, 8), ipady=4)
    enviar_btn = tk.Label(fila, text="↵", fg=C["tenue"], bg=C["caja"], font=(letra, 15), cursor="hand2")
    enviar_btn.pack(side="right")

    # --- respuesta (se puede seleccionar y copiar) ---
    zona = tk.Frame(marco, bg=C["fondo"])
    nombre = tk.Label(zona, text="ARCHÉ", fg=C["acento"], bg=C["fondo"], font=F_NOMBRE, anchor="w")
    nombre.pack(fill="x", pady=(12, 4))
    resp = tk.Text(zona, bg=C["fondo"], fg=C["texto"], font=F_RESP, wrap="word", relief="flat", bd=0,
                   highlightthickness=0, height=1, padx=0, pady=0, cursor="arrow",
                   selectbackground=C["caja_foco"], spacing2=3, spacing3=6)
    resp.pack(fill="x")

    # --- pie: ayudas + estado del micrófono ---
    pie = tk.Frame(marco, bg=C["fondo"])
    pie.pack(fill="x", pady=(10, 0))
    tk.Label(pie, text="Enter enviar   ↑↓ historial   Esc esconder", fg=C["tenue"], bg=C["fondo"],
             font=F_CHICA).pack(side="left")
    micro_txt = tk.Label(pie, text="", fg=C["tenue"], bg=C["fondo"], font=F_CHICA)
    micro_txt.pack(side="right")

    estado = {"modo": "quieto", "fase": 0, "esconder_en": 0.0, "historial": [], "pos": None,
              "marcador": True, "puntos": 0}

    # ---------------- esfera animada ----------------
    def dibujar_esfera():
        modo = estado["modo"]
        color = {"quieto": C["acento"], "pensando": C["pensando"], "listo": C["ok"], "error": C["error"]}[modo]
        estado["fase"] = (estado["fase"] + 1) % 40
        import math
        latido = (math.sin(estado["fase"] / 40 * 2 * math.pi) + 1) / 2         # 0..1
        r = 7 + (3 * latido if modo == "pensando" else 1 * latido)
        esfera.delete("all")
        for i, alfa in ((r + 5, C["caja_foco"]), (r + 2, C["borde"])):             # halo suave
            esfera.create_oval(13 - i, 13 - i, 13 + i, 13 + i, fill=alfa, outline="")
        esfera.create_oval(13 - r, 13 - r, 13 + r, 13 + r, fill=color, outline="")
        esfera.create_oval(13 - r / 2.6 - 1, 13 - r / 2.6 - 1, 13 - r / 2.6 + 2, 13 - r / 2.6 + 2,
                           fill="#ffffff", outline="")                             # brillo
        if modo == "pensando":
            estado["puntos"] = (estado["puntos"] + 1) % 24
            if resp.get("1.0", "end").strip().startswith("Pensando"):
                poner_texto("Pensando" + "." * (1 + estado["puntos"] // 8), ajustar=False)

    # ---------------- marcador (texto gris cuando está vacía) ----------------
    def poner_marcador():
        if not caja.get():
            estado["marcador"] = True
            caja.config(fg=C["tenue"])
            caja.insert(0, MARCADOR)
            caja.icursor(0)

    def quitar_marcador(_e=None):
        if estado["marcador"]:
            estado["marcador"] = False
            caja.delete(0, "end")
            caja.config(fg=C["texto"])

    def al_teclear(evento):
        if estado["marcador"] and evento.char and evento.char.isprintable():
            quitar_marcador()
        enviar_btn.config(fg=C["acento"] if (evento.char or caja.get()) and not estado["marcador"] else C["tenue"])

    def texto_caja():
        return "" if estado["marcador"] else caja.get().strip()

    # ---------------- mostrar / esconder ----------------
    def acomodar():
        raiz.update_idletasks()
        alto = raiz.winfo_reqheight()
        x = (raiz.winfo_screenwidth() - ANCHO) // 2
        y = int(raiz.winfo_screenheight() * 0.16)
        raiz.geometry(f"{ANCHO}x{alto}+{x}+{y}")

    def mostrar():
        micro_txt.config(text="● escuchando «oye Arché»" if microfono_activo() else "micrófono apagado",
                         fg=C["ok"] if microfono_activo() else C["tenue"])
        acomodar()
        raiz.attributes("-alpha", 0.0)
        raiz.deiconify()
        _redondear_esquinas(raiz)
        raiz.lift()
        raiz.focus_force()
        caja.focus_set()
        if not estado["marcador"]:
            caja.select_range(0, "end")
        _estado["burbuja_visible"] = True
        estado["esconder_en"] = 0.0
        aparecer(0.0)

    def aparecer(a):
        a = min(1.0, a + 0.2)
        raiz.attributes("-alpha", a)
        if a < 1.0:
            raiz.after(15, aparecer, a)

    def esconder(_e=None):
        raiz.withdraw()
        _estado["burbuja_visible"] = False
        estado["pos"] = None

    def al_perder_foco(_e=None):
        # clic afuera: se esconde (a menos que siga pensando; la respuesta la verás al volver)
        raiz.after(150, lambda: (raiz.focus_get() is None and estado["modo"] != "pensando") and esconder())

    # ---------------- respuesta ----------------
    def poner_texto(texto, ajustar=True):
        resp.config(state="normal")
        resp.delete("1.0", "end")
        resp.insert("1.0", texto)
        resp.config(state="disabled")
        if not zona.winfo_ismapped():
            zona.pack(fill="x", before=pie)
        if ajustar:
            raiz.update_idletasks()
            cuenta = resp.count("1.0", "end", "displaylines")
            lineas = int((cuenta[0] if isinstance(cuenta, tuple) else cuenta) or 1)
            alto_linea = tkfont.Font(font=F_RESP).metrics("linespace") + 4
            resp.config(height=max(1, min(lineas, ALTO_RESP_MAX // alto_linea)))
            if _estado["burbuja_visible"]:
                acomodar()

    def poner_respuesta(texto):
        estado["modo"] = "listo"
        raiz.after(1500, lambda: estado["modo"] == "listo" and estado.update(modo="quieto"))
        poner_texto(texto.strip() or "Hecho.")
        if CONFIG["esconder_burbuja_tras"]:
            estado["esconder_en"] = time.time() + CONFIG["esconder_burbuja_tras"]

    def enviar(_e=None):
        texto = texto_caja()
        if not texto:
            return
        estado["historial"] = [h for h in estado["historial"] if h != texto][-29:] + [texto]
        estado["pos"] = None
        caja.delete(0, "end")
        enviar_btn.config(fg=C["tenue"])
        estado["modo"] = "pensando"
        estado["esconder_en"] = 0.0
        poner_texto("Pensando.")
        try:
            _mandar_a_arche(texto)
        except Exception as e:
            estado["modo"] = "error"
            poner_texto(f"No pude mandarle eso a Arché ({e}).")

    # ---------------- historial con flechas ----------------
    def historial(paso):
        h = estado["historial"]
        if not h:
            return "break"
        quitar_marcador()
        pos = len(h) if estado["pos"] is None else estado["pos"]
        pos = max(0, min(len(h), pos + paso))
        estado["pos"] = pos
        caja.delete(0, "end")
        if pos < len(h):
            caja.insert(0, h[pos])
        caja.icursor("end")
        return "break"

    caja.bind("<FocusIn>", lambda e: estado["marcador"] and caja.icursor(0))
    caja.bind("<Key>", al_teclear)
    caja.bind("<BackSpace>", lambda e: "break" if estado["marcador"] else None)
    caja.bind("<KeyRelease>", lambda e: poner_marcador() if not caja.get() else None)
    caja.bind("<<Paste>>", quitar_marcador)
    caja.bind("<Return>", enviar)
    caja.bind("<Escape>", esconder)
    caja.bind("<Up>", lambda e: historial(-1))
    caja.bind("<Down>", lambda e: historial(1))
    resp.bind("<Escape>", esconder)
    raiz.bind("<FocusOut>", al_perder_foco)
    enviar_btn.bind("<Button-1>", enviar)
    for w in (fila, esfera):                       # clic en la fila = escribir
        w.bind("<Button-1>", lambda e: caja.focus_set())
    poner_marcador()

    # ---------------- bucle ----------------
    def revisar():
        try:
            while True:
                accion, dato = _pedidos_burbuja.get_nowait()
                if accion == "mostrar":
                    mostrar()
                elif accion == "alternar":
                    esconder() if _estado["burbuja_visible"] else mostrar()
                elif accion == "respuesta":
                    poner_respuesta(dato)
                elif accion == "salir":
                    raiz.destroy()
                    return
        except queue.Empty:
            pass
        if estado["esconder_en"] and time.time() > estado["esconder_en"]:
            estado["esconder_en"] = 0.0
            if raiz.focus_get() is None:            # solo si no la estás usando
                esconder()
        dibujar_esfera()
        raiz.after(45, revisar)

    raiz.after(45, revisar)
    raiz.mainloop()


def abrir_burbuja():
    _pedidos_burbuja.put(("alternar", None))


# ------------------------------------------------------------------
# Acciones (las usan los atajos y el icono)
# ------------------------------------------------------------------

def abrir_interfaz():
    try:
        from core.interfaz import web
        if web.abierta():
            return
        web.iniciar()
        web.abrir()
    except Exception:
        _mandar_a_arche("abre la interfaz")      # plan B: que Arché lo haga con su propio comando


def microfono_activo():
    try:
        from core.interfaz import micro
        return micro.activa()
    except Exception:
        return False


def alternar_microfono():
    try:
        from core.interfaz import micro
        if micro.activa():
            micro.detener()
            notificar("Micrófono apagado", "Ya no te escucho. Ctrl+Alt+V para volver a prenderlo.", forzar=True)
        else:
            micro.iniciar()
            notificar("Te escucho", "Di «oye Arché» y lo que necesites.", forzar=True)
    except Exception as e:
        _log(f"micrófono: {e}")


def salir():
    """Le dice a Arché «salir» para que cierre como siempre (guarda todo)."""
    try:
        _mandar_a_arche("salir")
    except Exception:
        pass

    def _forzar():
        time.sleep(15)
        import os
        os._exit(0)
    threading.Thread(target=_forzar, daemon=True).start()


# ------------------------------------------------------------------
# Notificaciones de Windows
# ------------------------------------------------------------------

def notificar(titulo, texto, forzar=False):
    if not CONFIG["notificaciones"] and not forzar:
        return
    try:
        from winotify import Notification
        Notification(app_id="Arché", title=titulo, msg=str(texto)[:250], duration="short").show()
    except Exception as e:
        _log(f"no pude notificar: {e}")


def aviso_de_fondo(texto):
    """arche_fondo.pyw llama esto cuando Arché dice algo desde un hilo de fondo
    (o sea, sin que nadie le haya preguntado)."""
    if not _estado["vivo"] or not texto or _estado["burbuja_visible"]:
        return
    ahora = time.time()
    if ahora - _estado["ultimo_aviso"] < CONFIG["segundos_entre_avisos"]:
        return
    _estado["ultimo_aviso"] = ahora
    threading.Thread(target=notificar, args=("Arché", texto), daemon=True).start()


# ------------------------------------------------------------------
# Icono en la bandeja
# ------------------------------------------------------------------

def _subir_desde_icono():
    """Sube a GitHub sin abrir nada y te cuenta el resultado con una notificación."""
    def trabajo():
        try:
            from core.IA import git_arche
            ok, texto = git_arche.subir()
        except Exception as e:
            ok, texto = False, str(e)
        notificar("Subido a GitHub" if ok else "No pude subir a GitHub", texto, forzar=True)
    threading.Thread(target=trabajo, name="arche-subir", daemon=True).start()


def _iniciar_bandeja():
    global _icono
    import pystray
    from PIL import Image, ImageDraw

    imagen = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.ellipse((6, 6, 58, 58), fill=(139, 124, 255), outline=(106, 168, 255), width=4)
    dibujo.ellipse((22, 22, 42, 42), fill=(106, 168, 255))

    menu = pystray.Menu(
        pystray.MenuItem(f"Hablar con Arché  ({CONFIG['atajo_burbuja']})",
                         lambda *a: abrir_burbuja(), default=True),
        pystray.MenuItem(f"Abrir interfaz  ({CONFIG['atajo_interfaz']})", lambda *a: abrir_interfaz()),
        pystray.MenuItem("Micrófono", lambda *a: alternar_microfono(),
                         checked=lambda item: microfono_activo()),
        pystray.MenuItem("Notificaciones", lambda *a: CONFIG.update(notificaciones=not CONFIG["notificaciones"]),
                         checked=lambda item: CONFIG["notificaciones"]),
        pystray.MenuItem("Subir cambios a GitHub", lambda *a: _subir_desde_icono()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Cerrar Arché", lambda *a: salir()),
    )
    _icono = pystray.Icon("arche", imagen, "Arché", menu)
    _icono.run_detached()


# ------------------------------------------------------------------
# Atajos de teclado globales
# ------------------------------------------------------------------

def _iniciar_atajos():
    import keyboard
    keyboard.add_hotkey(CONFIG["atajo_burbuja"], abrir_burbuja, suppress=False)
    keyboard.add_hotkey(CONFIG["atajo_interfaz"], abrir_interfaz, suppress=False)
    keyboard.add_hotkey(CONFIG["atajo_microfono"], alternar_microfono, suppress=False)


# ------------------------------------------------------------------
# Arranque y cierre
# ------------------------------------------------------------------

def _parte(nombre, funcion):
    try:
        funcion()
        _log(f"{nombre}: listo")
    except Exception as e:
        _log(f"{nombre}: apagado ({e})")


def _arrancar_todo():
    _asegurar_librerias()
    from core import canales
    canales.registrar_canal("burbuja", _respuesta_de_arche)
    threading.Thread(target=_hilo_burbuja, name="arche-burbuja", daemon=True).start()
    _parte("bandeja", _iniciar_bandeja)
    _parte("atajos", _iniciar_atajos)
    if CONFIG["escuchar_al_iniciar"]:
        time.sleep(8)                           # que Arché termine de cargar antes de prender el micrófono
        _parte("micrófono", lambda: __import__("core.interfaz.micro", fromlist=["x"]).iniciar())
    _estado["vivo"] = True
    notificar("Arché está lista",
              f"{CONFIG['atajo_burbuja'].title()} para escribirme · di «oye Arché» para hablarme.", forzar=True)


def iniciar():
    """La llama arche_fondo.pyw antes de main.py. No bloquea."""
    if sys.platform != "win32":
        _log("solo funciona en Windows; sigo sin atajos ni bandeja")
        return
    threading.Thread(target=_arrancar_todo, name="arche-presencia", daemon=True).start()


def detener():
    _estado["vivo"] = False
    _pedidos_burbuja.put(("salir", None))
    try:
        if _icono is not None:
            _icono.stop()
    except Exception:
        pass
    try:
        import keyboard
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass
