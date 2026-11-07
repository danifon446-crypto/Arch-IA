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

Librerías (se instalan solas la primera vez): pystray, pillow, winotify.
Los atajos usan RegisterHotKey de Windows (no la librería keyboard: su gancho
se cae solo cuando Arché está ocupada cargando modelos).
Si alguna falta o falla, esa parte se apaga y Arché sigue funcionando.
"""

import os
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
    "preguntar_subir": True,          # Arché te pregunta si sube a GitHub cuando hay cambios
    "minutos_entre_preguntas": 30,    # cada cuánto revisa si hay algo sin subir
    "minutos_tras_ahora_no": 120,     # si dices «Ahora no», cuánto espera para volver a preguntar
    "minutos_sin_tocar": 10,          # no pregunta mientras sigues editando archivos
}

_LIBRERIAS = {"pystray": "pystray", "PIL": "pillow", "winotify": "winotify"}

_estado = {"vivo": False, "ultimo_aviso": 0.0, "burbuja_visible": False, "proxima_pregunta": 0.0,
           "subiendo": False}
_pedidos_burbuja = queue.Queue()      # lo que la burbuja tiene que hacer (mostrar, respuesta...)
_icono = None
_candado_subir = threading.Lock()


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
    try:                                                          # sombra suave alrededor (CS_DROPSHADOW)
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(raiz.winfo_id()) or raiz.winfo_id()
        leer = getattr(ctypes.windll.user32, "GetClassLongPtrW", ctypes.windll.user32.GetClassLongW)
        poner = getattr(ctypes.windll.user32, "SetClassLongPtrW", ctypes.windll.user32.SetClassLongW)
        poner(hwnd, -26, leer(hwnd, -26) | 0x00020000)
    except Exception:
        pass


def _ruta_posicion():
    import os
    carpeta = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Arche")
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, "burbuja.json")


def _leer_posicion():
    import json
    try:
        with open(_ruta_posicion(), encoding="utf-8") as f:
            d = json.load(f)
        return int(d["x"]), int(d["y"])
    except Exception:
        return None


def _guardar_posicion(pos):
    import json
    try:
        with open(_ruta_posicion(), "w", encoding="utf-8") as f:
            json.dump({"x": pos[0], "y": pos[1]} if pos else {}, f)
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

    # --- línea de color arriba (degradado morado -> azul -> rosa) ---
    linea = tk.Canvas(raiz, height=3, bg=C["fondo"], highlightthickness=0)
    linea.pack(fill="x", padx=1, pady=(1, 0))

    def pintar_linea(_e=None):
        linea.delete("all")
        w = max(linea.winfo_width(), ANCHO)
        paradas = [(0x8b, 0x7c, 0xff), (0x6a, 0xa8, 0xff), (0xff, 0x8a, 0xd8)]
        for x in range(0, w, 2):
            t = x / w * (len(paradas) - 1)
            a, b = paradas[int(t)], paradas[min(int(t) + 1, len(paradas) - 1)]
            f = t - int(t)
            color = "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3))
            linea.create_line(x, 0, x, 3, fill=color, width=2)
    linea.bind("<Configure>", pintar_linea)

    marco = tk.Frame(raiz, bg=C["fondo"], padx=16, pady=10)
    marco.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    # --- encabezado: de aquí la arrastras ---
    cabeza = tk.Frame(marco, bg=C["fondo"], cursor="fleur")
    cabeza.pack(fill="x", pady=(0, 8))
    titulo = tk.Label(cabeza, text="Arché", fg=C["suave"], bg=C["fondo"], font=(letra, 9, "bold"), cursor="fleur")
    titulo.pack(side="left")
    agarre = tk.Label(cabeza, text="• • •", fg=C["tenue"], bg=C["fondo"], font=(letra, 8), cursor="fleur")
    agarre.place(relx=0.5, rely=0.5, anchor="center")
    cerrar_btn = tk.Label(cabeza, text="×", fg=C["tenue"], bg=C["fondo"], font=(letra, 13), cursor="hand2", padx=4)
    cerrar_btn.pack(side="right")
    cerrar_btn.bind("<Enter>", lambda e: cerrar_btn.config(fg=C["texto"]))
    cerrar_btn.bind("<Leave>", lambda e: cerrar_btn.config(fg=C["tenue"]))

    # --- caja de texto redondeada: esfera + texto + enviar ---
    ALTO_CAJA = 52
    pastilla = tk.Canvas(marco, height=ALTO_CAJA, bg=C["fondo"], highlightthickness=0)
    pastilla.pack(fill="x")
    esfera = tk.Canvas(pastilla, width=26, height=26, bg=C["caja"], highlightthickness=0)
    caja = tk.Entry(pastilla, bg=C["caja"], fg=C["suave"], insertbackground=C["texto"], relief="flat",
                    font=F_CAJA, highlightthickness=0, bd=0)
    enviar_btn = tk.Label(pastilla, text="↵", fg=C["tenue"], bg=C["caja"], font=(letra, 15), cursor="hand2")
    foco = {"si": False}

    def redondeado(cv, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return cv.create_polygon(pts, smooth=True, **kw)

    def pintar_pastilla(_e=None):
        pastilla.delete("fondo")
        w = pastilla.winfo_width()
        if w < 50:
            return
        redondeado(pastilla, 1, 1, w - 2, ALTO_CAJA - 2, 18, fill=C["caja"],
                   outline=C["acento"] if foco["si"] else C["borde"], width=1.5, tags="fondo")
        pastilla.tag_lower("fondo")
        pastilla.coords("w_esfera", 30, ALTO_CAJA / 2)
        pastilla.coords("w_caja", 52, ALTO_CAJA / 2)
        pastilla.itemconfigure("w_caja", width=max(50, w - 52 - 46))
        pastilla.coords("w_enviar", w - 26, ALTO_CAJA / 2)

    pastilla.create_window(30, ALTO_CAJA / 2, window=esfera, tags="w_esfera")
    pastilla.create_window(52, ALTO_CAJA / 2, window=caja, anchor="w", tags="w_caja")
    pastilla.create_window(ANCHO - 26, ALTO_CAJA / 2, window=enviar_btn, tags="w_enviar")
    pastilla.bind("<Configure>", pintar_pastilla)

    def cambiar_foco(valor):
        foco["si"] = valor
        pintar_pastilla()
    caja.bind("<FocusIn>", lambda e: cambiar_foco(True), add="+")
    caja.bind("<FocusOut>", lambda e: cambiar_foco(False), add="+")
    fila = pastilla                                   # (nombre que usa el resto del código)

    # --- arrastrar la burbuja (y recordar dónde la dejaste) ---
    arrastre = {"dx": 0, "dy": 0}

    def empezar_arrastre(e):
        arrastre["dx"], arrastre["dy"] = e.x_root - raiz.winfo_x(), e.y_root - raiz.winfo_y()

    def arrastrar(e):
        x = min(max(e.x_root - arrastre["dx"], -ANCHO + 80), raiz.winfo_screenwidth() - 80)
        y = min(max(e.y_root - arrastre["dy"], 0), raiz.winfo_screenheight() - 60)
        raiz.geometry(f"+{x}+{y}")

    def soltar(_e):
        _guardar_posicion((raiz.winfo_x(), raiz.winfo_y()))

    def volver_al_centro(_e):
        _guardar_posicion(None)
        acomodar()

    for w in (cabeza, titulo, agarre, linea, marco):
        w.bind("<ButtonPress-1>", empezar_arrastre)
        w.bind("<B1-Motion>", arrastrar)
        w.bind("<ButtonRelease-1>", soltar)
        w.bind("<Double-Button-1>", volver_al_centro)

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
    tk.Label(pie, text="Enter enviar · ↑↓ historial · Esc esconder",
             fg=C["tenue"], bg=C["fondo"], font=F_CHICA).pack(side="left")
    micro_txt = tk.Label(pie, text="", fg=C["tenue"], bg=C["fondo"], font=F_CHICA)
    micro_txt.pack(side="right")
    github_btn = tk.Label(pie, text="", fg=C["acento"], bg=C["fondo"], font=(letra, 9, "bold"), cursor="hand2")
    github_btn.bind("<Enter>", lambda e: github_btn.config(fg="#b3a8ff"))
    github_btn.bind("<Leave>", lambda e: github_btn.config(fg=C["acento"]))
    github_btn.pack(side="right", padx=(0, 14))

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
        guardada = _leer_posicion()
        if guardada:
            x, y = guardada
        else:
            x = (raiz.winfo_screenwidth() - ANCHO) // 2
            y = int(raiz.winfo_screenheight() * 0.16)
        raiz.geometry(f"{ANCHO}x{alto}+{x}+{y}")

    def mostrar():
        threading.Thread(target=lambda: _pedidos_burbuja.put(("contar_git", _contar_pendientes())),
                         daemon=True).start()
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
            import math
            medida = tkfont.Font(font=F_RESP)
            util = ANCHO - 2 - 32 - 8                       # ancho de la ventana menos márgenes
            lineas = sum(max(1, math.ceil(medida.measure(par) / util)) for par in texto.split("\n"))
            alto_linea = medida.metrics("linespace") + 4
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
    cerrar_btn.bind("<Button-1>", esconder)
    for w in (fila, esfera):                       # clic en la fila = escribir
        w.bind("<Button-1>", lambda e: caja.focus_set())
    poner_marcador()

    # ---------------- GitHub: botón de la burbuja ----------------
    def subir_desde_burbuja(_e=None):
        if _estado["subiendo"]:
            return
        estado["modo"] = "pensando"
        poner_texto("Subiendo a GitHub…")
        _subir_en_hilo(lambda ok, texto: _pedidos_burbuja.put(("respuesta", texto)))
        threading.Thread(target=lambda: (time.sleep(3), _pedidos_burbuja.put(("contar_git", _contar_pendientes()))),
                         daemon=True).start()

    github_btn.bind("<Button-1>", subir_desde_burbuja)

    # ---------------- GitHub: la pregunta (ventanita abajo a la derecha) ----------------
    aviso = tk.Toplevel(raiz)
    aviso.withdraw()
    aviso.overrideredirect(True)
    aviso.attributes("-topmost", True)
    aviso.configure(bg=C["borde"])
    a_linea = tk.Canvas(aviso, height=3, bg=C["fondo"], highlightthickness=0)
    a_linea.pack(fill="x", padx=1, pady=(1, 0))
    a_linea.bind("<Configure>", lambda e: [a_linea.create_line(x, 0, x, 3, width=2, fill=linea.itemcget(
        linea.find_all()[min(len(linea.find_all()) - 1, x * len(linea.find_all()) // max(1, e.width))], "fill"))
        for x in range(0, e.width, 2)] if linea.find_all() else None)
    a_marco = tk.Frame(aviso, bg=C["fondo"], padx=16, pady=14)
    a_marco.pack(fill="both", expand=True, padx=1, pady=(0, 1))
    tk.Label(a_marco, text="ARCHÉ  ·  GitHub", fg=C["acento"], bg=C["fondo"], font=F_NOMBRE,
             anchor="w").pack(fill="x")
    a_texto = tk.Label(a_marco, text="", fg=C["texto"], bg=C["fondo"], font=F_RESP, justify="left",
                       anchor="w", wraplength=330)
    a_texto.pack(fill="x", pady=(6, 12))
    a_botones = tk.Frame(a_marco, bg=C["fondo"])
    a_botones.pack(fill="x")

    def boton(padre, texto, fondo, color, accion):
        b = tk.Label(padre, text=texto, bg=fondo, fg=color, font=(letra, 10, "bold"), padx=16, pady=7,
                     cursor="hand2")
        b.bind("<Button-1>", lambda e: accion())
        b.bind("<Enter>", lambda e: b.config(bg=C["caja_foco"] if fondo != C["acento"] else "#9d90ff"))
        b.bind("<Leave>", lambda e: b.config(bg=fondo))
        return b

    def colocar_aviso():
        aviso.update_idletasks()
        w, h = 370, aviso.winfo_reqheight()
        aviso.geometry(f"{w}x{h}+{aviso.winfo_screenwidth() - w - 20}+{aviso.winfo_screenheight() - h - 64}")

    def esconder_aviso():
        aviso.withdraw()

    def ahora_no():
        _estado["proxima_pregunta"] = time.time() + CONFIG["minutos_tras_ahora_no"] * 60
        esconder_aviso()

    def si_subir():
        a_texto.config(text="Subiendo a GitHub…")
        for w in a_botones.winfo_children():
            w.pack_forget()
        colocar_aviso()
        _subir_en_hilo(lambda ok, texto: _pedidos_burbuja.put(("resultado_subir", (ok, texto))))

    b_subir = boton(a_botones, "Subir", C["acento"], "#ffffff", si_subir)
    b_no = boton(a_botones, "Ahora no", C["caja"], C["texto"], ahora_no)

    def preguntar_subir(lista):
        if not lista or _estado["subiendo"]:
            return
        nombres = [os.path.basename(r.rstrip("/")) or r for _, r in lista]
        muestra = ", ".join(nombres[:4]) + (f" y {len(nombres) - 4} más" if len(nombres) > 4 else "")
        a_texto.config(text=f"Tengo {len(lista)} archivo(s) sin subir a GitHub:\n{muestra}\n\n¿Los subo?")
        for w in a_botones.winfo_children():
            w.pack_forget()
        b_subir.pack(side="left")
        b_no.pack(side="left", padx=(8, 0))
        colocar_aviso()
        aviso.deiconify()
        aviso.lift()

    NOMBRE_CAMBIO = {"cambiados": "cambió", "nuevos": "nuevo", "borrados": "borrado"}

    def preguntar_sellar(r):
        for w in a_botones.winfo_children():
            w.pack_forget()
        if not r.get("firma_valida", True):
            a_texto.config(text="⚠ El registro de seguridad tiene una firma que NO es de Arché.\n"
                                "No subo nada. Pasa Windows Defender (escaneo completo) y, si todo está "
                                "bien, aprueba en la terminal:  python seguridad.py sellar")
            boton(a_botones, "Cerrar", C["caja"], C["texto"], esconder_aviso).pack(side="left")
        else:
            lista = [(rel, NOMBRE_CAMBIO[k]) for k in ("cambiados", "nuevos", "borrados") for rel in r.get(k, [])]
            lineas = "\n".join(f"  • {os.path.basename(rel)}  ({tipo})" for rel, tipo in lista[:6])
            if len(lista) > 6:
                lineas += f"\n  … y {len(lista) - 6} más"
            a_texto.config(text=f"Antes de subir: {len(lista)} archivo(s) cambiaron y el guardián no los "
                                f"ha aprobado:\n{lineas}\n\n¿Los cambiaste tú?")

            def si_fui_yo():
                a_texto.config(text="Aprobando y subiendo a GitHub…")
                for w in a_botones.winfo_children():
                    w.pack_forget()
                colocar_aviso()
                _aprobar_y_subir(lambda ok, texto: _pedidos_burbuja.put(("resultado_subir", (ok, texto))))

            def no_fui_yo():
                mostrar_resultado(False, "Bien, no subo nada. Pasa Windows Defender (escaneo completo) "
                                         "y revisa esos archivos antes de aprobarlos.")

            boton(a_botones, "Sí, aprobar y subir", C["acento"], "#ffffff", si_fui_yo).pack(side="left")
            boton(a_botones, "No fui yo", C["caja"], C["texto"], no_fui_yo).pack(side="left", padx=(8, 0))
        colocar_aviso()
        aviso.deiconify()
        aviso.lift()

    def mostrar_resultado(ok, texto):
        if ok is None:            # se quedó esperando tu aprobación: la ventanita ya te está preguntando
            return
        a_texto.config(text=("✓ " if ok else "✗ ") + texto)
        for w in a_botones.winfo_children():
            w.pack_forget()
        boton(a_botones, "Cerrar", C["caja"], C["texto"], esconder_aviso).pack(side="left")
        colocar_aviso()
        aviso.deiconify()
        if ok:
            raiz.after(8000, esconder_aviso)

    # ---------------- bucle ----------------
    def revisar():
        try:
            while True:
                accion, dato = _pedidos_burbuja.get_nowait()
                if accion == "mostrar":
                    mostrar()
                elif accion == "alternar":
                    esconder() if _estado["burbuja_visible"] else mostrar()
                elif accion == "preguntar_subir":
                    preguntar_subir(dato)
                elif accion == "preguntar_sellar":
                    preguntar_sellar(dato)
                elif accion == "resultado_subir":
                    mostrar_resultado(*dato)
                elif accion == "contar_git":
                    github_btn.config(text=f"⇪ Subir a GitHub ({dato})" if dato else "")
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


def _contar_pendientes():
    try:
        from core.IA import git_arche
        return len(git_arche.pendientes()) if git_arche.raiz_repo() else 0
    except Exception:
        return 0


def _subir_en_hilo(al_terminar):
    """Sube a GitHub sin trabar nada y llama al_terminar(ok, texto)."""
    with _candado_subir:
        if _estado["subiendo"]:
            return
        _estado["subiendo"] = True

    def trabajo():
        try:
            r = _cambios_sin_aprobar()
            if r is not None:
                # el guardián ve cambios sin aprobar: te pregunta con botones en vez de subir
                _pedidos_burbuja.put(("preguntar_sellar", r))
                al_terminar(None, "Antes de subir necesito que apruebes unos cambios: "
                                  "mira la ventanita de abajo a la derecha.")
                return
            from core.IA import git_arche
            ok, texto = git_arche.subir()
        except Exception as e:
            ok, texto = False, f"No pude subir ({e})."
        finally:
            _estado["subiendo"] = False
        _estado["proxima_pregunta"] = time.time() + CONFIG["minutos_entre_preguntas"] * 60
        al_terminar(ok, texto)
    threading.Thread(target=trabajo, name="arche-subir", daemon=True).start()


def _cambios_sin_aprobar():
    """El resultado del guardián si hay archivos cambiados que nadie aprobó; si no, None."""
    try:
        from core.seguridad import guardian
        r = guardian.verificar()
        return r if guardian.hay_alerta(r) else None
    except Exception:
        return None


def _aprobar_y_subir(al_terminar):
    """Botón «Sí, fui yo»: sella el código (como «python seguridad.py sellar») y sube."""
    def trabajo():
        try:
            from core.seguridad import guardian
            n = guardian.sellar("aprobado por David con el botón de Arché")
            _log(f"guardián: sellé {n} archivos (aprobado con el botón)")
        except Exception as e:
            al_terminar(False, f"No pude aprobar los cambios ({e}).")
            return
        _subir_en_hilo(al_terminar)
    threading.Thread(target=trabajo, name="arche-aprobar", daemon=True).start()


def _vigilar_github():
    """Cada rato mira si hay archivos sin subir. Si los hay (y ya no los estás editando), pregunta."""
    try:
        from core.IA import git_arche
    except Exception:
        return
    if git_arche.raiz_repo() is None:
        _log("GitHub: la carpeta no es un clon de git; no pregunto por subidas")
        return
    _estado["proxima_pregunta"] = time.time() + 5 * 60          # la primera, 5 min después de arrancar
    while True:
        time.sleep(60)
        if not CONFIG["preguntar_subir"] or time.time() < _estado["proxima_pregunta"] or _estado["subiendo"]:
            continue
        _estado["proxima_pregunta"] = time.time() + CONFIG["minutos_entre_preguntas"] * 60
        try:
            lista = git_arche.pendientes()
            if not lista:
                continue
            raiz = git_arche.raiz_repo()
            ultimo = max((os.path.getmtime(raiz / r.rstrip("/")) for _, r in lista
                          if os.path.exists(raiz / r.rstrip("/"))), default=0)
            if time.time() - ultimo < CONFIG["minutos_sin_tocar"] * 60:
                _estado["proxima_pregunta"] = time.time() + CONFIG["minutos_sin_tocar"] * 60
                continue                                         # sigues editando: espero
            _pedidos_burbuja.put(("preguntar_subir", lista))
        except Exception as e:
            _log(f"GitHub: {e}")


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


def reiniciar():
    """Abre una Arché nueva (que espera a que esta se cierre) y cierra esta. Sirve para cargar archivos nuevos."""
    import os
    import subprocess
    arranque = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "arche_fondo.pyw")
    python = sys.executable
    if os.path.basename(python).lower() == "python.exe":
        python = os.path.join(os.path.dirname(python), "pythonw.exe")
    try:
        subprocess.Popen([python, arranque, "--reinicio"], cwd=os.path.dirname(arranque),
                         creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    except Exception as e:
        notificar("No pude reiniciar", str(e), forzar=True)
        return
    notificar("Reiniciando Arché", "Vuelvo en unos segundos con los archivos nuevos.", forzar=True)
    salir()


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
    """Sube a GitHub desde el icono y muestra el resultado en la ventanita de abajo a la derecha."""
    _subir_en_hilo(lambda ok, texto: _pedidos_burbuja.put(("resultado_subir", (ok, texto))))


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
        pystray.MenuItem("Reiniciar Arché", lambda *a: reiniciar()),
        pystray.MenuItem("Cerrar Arché", lambda *a: salir()),
    )
    _icono = pystray.Icon("arche", imagen, "Arché", menu)
    _icono.run_detached()


# ------------------------------------------------------------------
# Atajos de teclado globales
# ------------------------------------------------------------------

_TECLAS_MOD = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "mayus": 0x4, "win": 0x8}
_TECLAS_ESP = {"space": 0x20, "espacio": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09,
               **{f"f{n}": 0x6F + n for n in range(1, 13)}}
_hilo_atajos = {"id": None}


def _traducir_atajo(texto):
    """'ctrl+alt+a' -> (modificadores, codigo de tecla) para RegisterHotKey."""
    mods, tecla = 0x4000, None                     # 0x4000 = MOD_NOREPEAT (dejarla apretada no repite)
    for parte in texto.lower().replace(" ", "").split("+"):
        if parte in _TECLAS_MOD:
            mods |= _TECLAS_MOD[parte]
        elif parte in _TECLAS_ESP:
            tecla = _TECLAS_ESP[parte]
        elif len(parte) == 1 and parte.isalnum():
            tecla = ord(parte.upper())
        else:
            raise ValueError(f"no entiendo la tecla «{parte}» en {texto}")
    if tecla is None:
        raise ValueError(f"al atajo {texto} le falta la tecla")
    return mods, tecla


def _bucle_atajos(listo):
    """Hilo propio: registra los atajos y espera los mensajes WM_HOTKEY de Windows.
    Aunque Arché esté ocupada, Windows guarda el mensaje en la fila y nunca se pierde el atajo."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    _hilo_atajos["id"] = ctypes.windll.kernel32.GetCurrentThreadId()
    acciones = {1: ("atajo_burbuja", abrir_burbuja), 2: ("atajo_interfaz", abrir_interfaz),
                3: ("atajo_microfono", alternar_microfono)}
    funcionan, fallaron = [], []
    for num, (clave, _) in acciones.items():
        try:
            mods, tecla = _traducir_atajo(CONFIG[clave])
            if user32.RegisterHotKey(None, num, mods, tecla):
                funcionan.append(CONFIG[clave])
            else:
                fallaron.append(CONFIG[clave])
        except ValueError as e:
            _log(str(e))
            fallaron.append(CONFIG[clave])
    listo.append((funcionan, fallaron))
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == 0x0312 and msg.wParam in acciones:          # WM_HOTKEY
            threading.Thread(target=acciones[msg.wParam][1], daemon=True).start()
    for num in acciones:
        user32.UnregisterHotKey(None, num)


def _iniciar_atajos():
    listo = []
    threading.Thread(target=_bucle_atajos, args=(listo,), name="arche-atajos", daemon=True).start()
    for _ in range(50):
        if listo:
            break
        time.sleep(0.1)
    funcionan, fallaron = listo[0] if listo else ([], ["(no arrancó)"])
    if fallaron:
        notificar("Un atajo no funciona",
                  f"Otro programa ya usa: {', '.join(fallaron)}. Cámbialo en core/presencia.py (CONFIG).",
                  forzar=True)
        if not funcionan:
            raise RuntimeError("ningún atajo quedó registrado: " + ", ".join(fallaron))
    _log("atajos activos: " + ", ".join(funcionan))


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
    threading.Thread(target=_vigilar_github, name="arche-vigila-github", daemon=True).start()
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
        if _hilo_atajos["id"]:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(_hilo_atajos["id"], 0x0012, 0, 0)    # WM_QUIT
    except Exception:
        pass
