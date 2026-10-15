"""
ventana.py
----------
Ubicacion: Arche/core/interfaz/ventana.py

La ventana de Arché (Tkinter, viene con Python en Windows). Se abre sola cuando
arranca Arché y se queda ahi. Es completamente modular:

  - La distribucion (layout.py) decide que widgets hay, donde, de que tamaño y
    con que transparencia; los widgets (widgets.py) dibujan su tarjeta.
  - El Centro de personalizacion (centro.py) vive en la pestaña PERSONALIZA.
  - Editor de diseño (editor.py): arrastrar, estirar, ocultar, deshacer.
  - Buscador de comandos (Ctrl+Espacio), atajos configurables, navegacion con teclado.
  - Esfera flotante, ventana compacta o superpuesta, widgets en ventanas aparte.
  - Escenas, fondos (imagen, GIF, video), mascota, temas, accesibilidad y modo ahorro.

Reglas de Tkinter que se respetan aqui: TODO lo grafico vive en un solo hilo
(el de la ventana). Desde fuera solo se pide algo con pedir() (una cola).
"""

import collections
import json
import math
import os
import random
import textwrap
import threading
import time

from . import (ajustes, buscador, centro, datos, editor as editor_mod, en_vivo, entrada, escenas, estado_visual as ev,
               extensiones, fondos, layout, lenguaje, mascota as mascota_mod, orbe, perfiles, rendimiento, sonido,
               tema, vista_redes, widgets)

try:
    import tkinter as tk
except Exception:        # Python sin Tk (ej. Raspberry sin python3-tk)
    tk = None

_hilo = None
_ventana = None
_bloqueo = threading.Lock()
BARRAS = 48
MUESTRAS = 60            # puntos de las graficas de actividad (1 por segundo)
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
PESTANAS = centro.PESTANAS_BASE
NOMBRES_TEMA = tema.NOMBRES
ESTADO_BASE = {"reposo": "reposo", "escuchando": "escuchando", "pensando": "pensando", "generando": "pensando",
               "hablando": "hablando", "ejecutando": "pensando", "buscando": "pensando",
               "confirmando": "escuchando", "alerta": "hablando", "error": "hablando"}
ICONOS_ESTADO = {"reposo": "☾", "escuchando": "♪", "pensando": "⋯", "generando": "✎", "hablando": "◖)", "ejecutando": "⚙",
                 "buscando": "⌕", "confirmando": "?", "alerta": "!", "error": "✕"}
_PALABRAS_BUSQUEDA = ("busca", "buscar", "youtube", "google", "internet", "web", "investiga")


def disponible():
    return tk is not None


def _secuencia(texto):
    """'Ctrl+Espacio' -> '<Control-space>'. None si no se entiende."""
    if not texto:
        return None
    mods, tecla = [], None
    nombres = {"espacio": "space", "esc": "Escape", "escape": "Escape", "enter": "Return", "intro": "Return",
               "tab": "Tab", "borrar": "BackSpace", "supr": "Delete", "arriba": "Up", "abajo": "Down",
               "izquierda": "Left", "derecha": "Right"}
    for p in str(texto).replace(" ", "").split("+"):
        pl = p.lower()
        if pl in ("ctrl", "control"):
            mods.append("Control")
        elif pl in ("alt",):
            mods.append("Alt")
        elif pl in ("shift", "mayus"):
            mods.append("Shift")
        elif pl:
            tecla = nombres.get(pl, p.upper() if (len(p) > 1 and pl[0] == "f" and pl[1:].isdigit()) else pl)
    if not tecla:
        return None
    return "<" + "-".join(mods + [tecla]) + ">"


class Secundaria:
    """Un widget en su propia ventana (desacoplado). Conserva tamaño y posicion."""

    def __init__(self, v, wd):
        self.v, self.wd = v, wd
        info = wd.get("ventana") or {"x": 200, "y": 150, "w": 420, "h": 320}
        self.top = tk.Toplevel(v.root)
        self.top.title("Arché · " + layout.nombre_de(wd["tipo"]))
        self.top.geometry(f"{info['w']}x{info['h']}+{info['x']}+{info['y']}")
        self.top.configure(bg=tema.FONDO)
        self.top.minsize(160, 120)
        self.canvas = tk.Canvas(self.top, bg=tema.FONDO, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.zonas = []
        self.top.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.canvas.bind("<Button-1>", self._clic)
        self.canvas.bind("<Button-3>", self._derecho)
        self.top.bind("<Configure>", self._cambio)
        self._guardado = 0.0
        try:
            self.top.attributes("-topmost", bool(wd["opts"].get("siempre_visible")))
        except Exception:
            pass

    def _clic(self, e):
        for x0, y0, x1, y1, accion in self.zonas:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                self.v._despachar(accion)
                return

    def _derecho(self, e):
        on = not self.wd["opts"].get("siempre_visible")
        self.wd["opts"]["siempre_visible"] = on
        try:
            self.top.attributes("-topmost", on)
        except Exception:
            pass
        self.v.avisar("Esta ventana " + ("se queda siempre visible." if on else "ya no se queda siempre visible."), "info")
        perfiles.marcar_sucio()

    def _cambio(self, e):
        if e.widget is not self.top or time.time() - self._guardado < 0.8:
            return
        self._guardado = time.time()
        try:
            self.wd["ventana"] = {"x": self.top.winfo_x(), "y": self.top.winfo_y(), "w": self.top.winfo_width(),
                                  "h": self.top.winfo_height()}
            perfiles.marcar_sucio()
        except Exception:
            pass

    def cerrar(self, devolver=True):
        if devolver:
            self.v._volver_al_panel(self.wd)
        try:
            self.top.destroy()
        except Exception:
            pass

    def dibujar(self):
        v = self.v
        W, H = max(80, self.canvas.winfo_width()), max(60, self.canvas.winfo_height())
        c = self.canvas
        c.delete("din")
        viejo = (v.canvas, v.zonas, v._tag)
        v.canvas, v.zonas, v._tag = c, [], "din"
        try:
            self.canvas.configure(bg=tema.FONDO)
            v._pintar_widget(self.wd, 6, 6, W - 12, H - 12)
            self.zonas = v.zonas
        finally:
            v.canvas, v.zonas, v._tag = viejo


class VentanaArche:
    def __init__(self, tv=False, foco=True):
        self.tv = False
        self.pedir_cerrar = False
        self.pedir_tv = None
        self.peticiones = collections.deque()
        self.fase = 0.0
        self.nivel = 0.0                      # energia suavizada de la voz (0 a 1)
        self.alturas = [0.0] * BARRAS
        self.objetivo = [0.0] * BARRAS
        self.snap = {"equipo": {}, "voz": {"activa": False, "hablando": False, "ultimo": ""},
                     "nube": {}, "red": {}, "examen": {"dominios": [], "nivel": 0, "umbral": 4,
                                                        "automatico": False, "listos": 0},
                     "procesos": [], "controles": [], "hoy": {"mejora": [], "alarmas": []}}
        self.pestana = "controles"
        self.pendiente = {}
        self.cmd_hist = []
        self.cmd_pos = 0
        self.hist_cpu = collections.deque(maxlen=MUESTRAS)
        self.hist_ram = collections.deque(maxlen=MUESTRAS)
        self.ultimo_snap = 0.0
        self.t0 = time.time()
        self.zonas = []                        # (x0, y0, x1, y1, accion)
        self.regiones = {}                     # nombre -> (x0, y0, x1, y1), para el recorrido
        self.rects = {}                        # id de widget -> (x, y, w, h) en pixeles
        self.grid = (0, 0, 1, 1, 0)
        self.hover = None
        self.mouse = (0, 0)
        self.scroll = {}
        self._scroll_reg = {}
        self.tam_fondo = None
        self._tag = "din"
        self._wd = None
        self.geo_normal = ajustes.obtener("ventana_geometria") or "1100x660"
        self.ancho = self.alto = self.ancho_real = self.alto_real = 1
        self.ambiente = False
        self.toasts = []
        self.historial_notif = collections.deque(maxlen=40)
        self.eventos = collections.deque(maxlen=60)
        self.fondo = None
        self._foto = None
        self._fondo_item = None
        self._prev_listos = self._prev_nivel = self._prev_mejora = None
        self.mascota = mascota_mod.Mascota()
        self._prev_ordenes = 0
        self._red_prev = None
        self._red_vel = (0.0, 0.0)
        self.ms_cuadro = 0.0
        self.centro_cat = "apariencia"
        self.centro_busqueda = ""
        self.centro_sel = None
        self.editor = editor_mod.Editor()
        self.editando = False
        self.menu_nav = False
        self.kb = -1                           # elemento enfocado con Tab
        self.bus_activo = False
        self.bus_res = []
        self.bus_sel = 0
        self._vis = {}
        self._fantasmas = {}
        self._visibles_antes = set()
        self._errores_w = set()
        self._esc_c = 1.0
        self._fx = {}
        self._fuente = tema.FUENTE
        self._sig_tema = None
        self._atajos_vinculados = {}
        self._sig_atajos = None
        self._sig_ventana = None
        self._ultima_clase = None
        self._ultimo_vistazo = 0.0
        self._ultimo_chat = 0
        self._ultimo_n_int = 0
        self._arrastre_ventana = None
        self._sin_foco_desde = None
        self._geo_guardada = 0.0
        self._color_pedido = None
        self._temp = None                      # ventanita temporal de resultados
        self.secundarias = {}
        self.flotante = None
        self._bandeja_aviso = False
        self._propuesta_rend = False
        self._ult_lay_compacto = None
        self._cuadro_ini = 0.0
        self._buscando_hasta = 0.0
        self._masc_hasta = 0.0
        self._img_masc = None
        self._bandeja = None
        self._vis_listo = False
        self.centro_bw = 280

        self.root = tk.Tk()
        self.root.title("Arché")
        self.root.configure(bg=tema.FONDO)
        self.root.minsize(640, 380)
        self.root.geometry(self.geo_normal)
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.canvas = tk.Canvas(self.root, bg=tema.FONDO, highlightthickness=0, takefocus=1)
        self.canvas.pack(fill="both", expand=True)
        self._cv0 = self.canvas

        # caja para escribirle a Arché desde la ventana
        self.entry = self._nueva_entrada(11)
        self.entry_id = self.canvas.create_window(0, 0, window=self.entry, anchor="nw", tags="entrada")
        self.entry.bind("<Return>", self._enviar)
        self.entry.bind("<Up>", lambda e: self._historial_cmd(-1))
        self.entry.bind("<Down>", lambda e: self._historial_cmd(1))
        # buscador de ajustes (dentro de PERSONALIZA)
        self.busca = self._nueva_entrada(10)
        self.busca_id = self.canvas.create_window(0, 0, window=self.busca, anchor="nw", tags="busca", state="hidden")
        self.busca.bind("<KeyRelease>", lambda e: setattr(self, "centro_busqueda", self.busca.get()))
        # cajas de la vista de redes neuronales (agregar ejemplos y probar frases)
        self.red_add = self._nueva_entrada(10)
        self.red_add_id = self.canvas.create_window(0, 0, window=self.red_add, anchor="nw", tags="red_add", state="hidden")
        self.red_add.bind("<Return>", lambda e: vista_redes.enter_en(self, "add"))
        self.red_test = self._nueva_entrada(10)
        self.red_test_id = self.canvas.create_window(0, 0, window=self.red_test, anchor="nw", tags="red_test", state="hidden")
        self.red_test.bind("<Return>", lambda e: vista_redes.enter_en(self, "test"))
        # barra de comandos (Ctrl+Espacio)
        self.bus_entry = self._nueva_entrada(13)
        self.bus_id = self.canvas.create_window(0, 0, window=self.bus_entry, anchor="nw", tags="bus", state="hidden")
        self.bus_entry.bind("<KeyRelease>", self._bus_teclas)
        self.bus_entry.bind("<Return>", lambda e: self._bus_ejecutar())
        self.bus_entry.bind("<Up>", lambda e: self._bus_mover(-1))
        self.bus_entry.bind("<Down>", lambda e: self._bus_mover(1))

        self.root.bind_all("<Escape>", self._tecla)
        self.root.bind_all("<Key>", self._cualquier_tecla, add="+")
        self.root.bind_all("<Tab>", lambda e: self._tab(1))
        self.root.bind_all("<Shift-Tab>", lambda e: self._tab(-1))
        self.root.bind_all("<ISO_Left_Tab>", lambda e: self._tab(-1))
        self.root.bind_all("<Return>", self._enter_global, add="+")
        self.canvas.bind("<Button-1>", self._clic)
        self.canvas.bind("<ButtonRelease-1>", self._soltar)
        self.canvas.bind("<B1-Motion>", self._mover)
        self.canvas.bind("<Double-Button-1>", self._doble_clic)
        self.canvas.bind("<Motion>", self._mover)
        self.canvas.bind("<Leave>", lambda e: setattr(self, "hover", None))
        self.canvas.bind("<MouseWheel>", self._rueda)
        self.canvas.bind("<Button-4>", lambda e: self._rueda(e, 120))
        self.canvas.bind("<Button-5>", lambda e: self._rueda(e, -120))

        en_vivo.instalar()
        try:
            extensiones.escanear()
        except Exception:
            pass
        self._aplicar_tema(forzar=True)
        self._vincular_atajos()
        self.root.update_idletasks()
        self.poner_tv(tv)
        self._aplicar_ventana(forzar=True)
        self.root.after(33, self.cuadro)
        if foco:
            self.root.after(150, self._dar_foco)

    def _nueva_entrada(self, tam):
        return tk.Entry(self.root, bg=tema.PANEL_2, fg=tema.TEXTO, insertbackground=tema.MORADO_CLARO,
                        relief="flat", highlightthickness=1, highlightbackground=tema.BORDE,
                        highlightcolor=tema.MORADO_CLARO, selectbackground=tema.MORADO, font=(tema.FUENTE, tam))

    # ---------------- foco, teclado y atajos ----------------
    def _dar_foco(self):
        """Trae la ventana al frente y le da el teclado (sin esto F11/Esc se van a la consola)."""
        try:
            self.root.lift()
            if not ajustes.obtener("ventana_siempre_visible"):
                self.root.attributes("-topmost", True)
                self.root.after(250, lambda: self.root.attributes("-topmost", bool(ajustes.obtener("ventana_siempre_visible"))))
            self.root.focus_force()
            (self.bus_entry if self.bus_activo else (self.red_add if vista_redes.ui["grande"] else self.entry)).focus_set()
        except Exception:
            pass

    def _vincular_atajos(self):
        """Los atajos configurables (Ajustes > Accesibilidad). Se revinculan cuando cambian."""
        for seq in list(self._atajos_vinculados):
            try:
                self.root.unbind_all(seq)
            except Exception:
                pass
        self._atajos_vinculados = {}
        base = dict(ajustes.DEFAULTS["atajos"])
        base.update(ajustes.obtener("atajos") or {})
        for accion, texto in base.items():
            seq = _secuencia(texto)
            if seq:
                self.root.bind_all(seq, lambda e, a=accion: self._atajo(a))
                self._atajos_vinculados[seq] = accion
        self._sig_atajos = json.dumps(base, sort_keys=True)

    def _atajo(self, accion):
        if accion == "buscador":
            self.poner_buscador(not self.bus_activo)
        elif accion == "editor":
            self.poner_editor(not self.editando)
        elif accion == "tv":
            self.poner_tv(not self.tv)
        elif accion == "deshacer":
            ok, msg = ev.deshacer()
            self.avisar(msg.capitalize(), "exito" if ok else "info")
        elif accion == "rehacer":
            ok, msg = ev.rehacer()
            self.avisar(msg.capitalize(), "exito" if ok else "info")
        return "break"

    def _tecla(self, evento):
        if self.ambiente:
            self.ambiente = False
            en_vivo.ultima_orden = time.time()
            return "break"
        if self.bus_activo:
            self.poner_buscador(False)
        elif vista_redes.ui["grande"]:
            vista_redes.ui["grande"] = False
            self.entry.focus_set()
        elif self.editando:
            self.poner_editor(False, cancelar=True)
        elif self.menu_nav:
            self.menu_nav = False
        elif self.tv:
            self.poner_tv(False)
        else:
            self.entry.delete(0, "end")
            self.kb = -1
        return "break"

    def _cualquier_tecla(self, evento):
        if self.ambiente and evento.keysym not in ("Escape",):
            self.ambiente = False
            en_vivo.ultima_orden = time.time()

    def _enter_global(self, evento):
        if self.editando:
            self.poner_editor(False)
            return "break"
        if self.kb >= 0 and ajustes.obtener("teclado_nav") and self.root.focus_get() not in (self.entry, self.busca, self.bus_entry, self.red_add, self.red_test):
            zs = self._zonas_teclado()
            if self.kb < len(zs):
                self._despachar(zs[self.kb][4])
                return "break"

    def _zonas_teclado(self):
        return [z for z in self.zonas if (z[2] - z[0]) > 6 and (z[3] - z[1]) > 6]

    def _tab(self, paso):
        """Tab / Shift+Tab: recorre los elementos clicables (accesibilidad por teclado)."""
        if not ajustes.obtener("teclado_nav") or self.editando or self.bus_activo:
            return None
        zs = self._zonas_teclado()
        if not zs:
            return None
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        self.kb = (self.kb + paso) % len(zs)
        return "break"

    def _zona(self, x, y):
        for x0, y0, x1, y1, accion in reversed(self.zonas):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return accion
        return None

    def _rueda(self, evento, delta=None):
        d = delta if delta is not None else evento.delta
        for clave, reg in self._scroll_reg.items():
            if reg[0] <= evento.x <= reg[2] and reg[1] <= evento.y <= reg[3]:
                self.scroll[clave] = max(0, self.scroll.get(clave, 0) - (1 if d > 0 else -1) * 44)
                return

    # ---------------- clics ----------------
    def _clic(self, evento):
        self._dar_foco() if not self.editando else None
        if self.ambiente:
            self.ambiente = False
            en_vivo.ultima_orden = time.time()
            return
        if self.bus_activo:
            accion = self._zona(evento.x, evento.y)
            if isinstance(accion, tuple) and accion and accion[0] == "bus":
                self.bus_sel = accion[1]
                self._bus_ejecutar()
            elif accion is None:
                self.poner_buscador(False)
            return
        if self.editando:
            self.editor.pulsar(self, evento.x, evento.y)
            return
        if self.menu_nav and not (isinstance(self._zona(evento.x, evento.y), tuple) and self._zona(evento.x, evento.y)[0] == "pestana"):
            self.menu_nav = False
        accion = self._zona(evento.x, evento.y)
        if accion is None:
            if self._sin_borde() and evento.y < 70 * self._esc_c:
                self._arrastre_ventana = (evento.x_root - self.root.winfo_x(), evento.y_root - self.root.winfo_y())
            return
        self._despachar(accion)

    def _soltar(self, evento):
        self._arrastre_ventana = None
        if self.editando:
            self.editor.soltar(self, evento.x, evento.y)

    def _despachar(self, accion):
        if accion == "tv":
            self.poner_tv(not self.tv)
        elif accion == "cerrar":
            self.cerrar()
        elif accion == "ambiente":
            self.ambiente = True
        elif accion == "buscador":
            self.poner_buscador(True)
        elif accion == "editor":
            self.poner_editor(True)
        elif isinstance(accion, tuple):
            self._accion(accion)

    def _accion(self, accion):
        tipo = accion[0]
        nombre = ajustes.obtener("mascota_nombre")
        if tipo == "pestana":
            self.pestana = accion[1]
            self.menu_nav = False
            sonido.tocar("clic")
        elif tipo == "menu_nav":
            self.menu_nav = not self.menu_nav
        elif tipo == "cmd":                           # ("cmd", orden, clave, valor_esperado)
            _, orden, clave, esperado = accion
            self.pendiente[clave] = (esperado, time.time() + 90)
            entrada.enviar(orden, "ventana")
        elif tipo == "mascota":
            self.mascota.clic(nombre)
        elif tipo == "tour":
            if accion[1] == "sig":
                fin = self.mascota.avanzar_recorrido(nombre)
                if fin:
                    ajustes.fijar("recorrido_hecho", True)
                else:
                    self._pestana_del_paso()
            else:
                self.mascota.saltar_recorrido()
                ajustes.fijar("recorrido_hecho", True)
        elif tipo == "fondo":
            if accion[1] == "ninguno":
                ajustes.fijar("fondo", "")
            else:
                ajustes.fijar("fondo", fondos.siguiente(ajustes.obtener("fondo"), 1 if accion[1] == "sig" else -1))
        elif tipo == "osc":
            ajustes.fijar("fondo_oscuridad", max(0, min(90, int(ajustes.obtener("fondo_oscuridad")) + accion[1])))
        elif tipo == "nombre":
            self.rellenar_entrada("nombre de la mascota ")
        elif tipo == "pin":
            try:
                from . import remoto
                remoto.nuevo_pin()
            except Exception:
                pass
        elif tipo == "confirmar":
            self.enviar_orden("si")
        elif tipo == "cancelar":
            self.enviar_orden("no")
        elif tipo == "bus":
            self.bus_sel = accion[1]
            self._bus_ejecutar()
        elif tipo == "redes":
            vista_redes.accion(self, accion)
        else:
            centro.ejecutar(self, accion)

    def _pestana_del_paso(self):
        paso = self.mascota.paso
        if paso is not None and mascota_mod.RECORRIDO[paso][2]:
            self.pestana = mascota_mod.RECORRIDO[paso][2]

    def _doble_clic(self, evento):
        if self._zona(evento.x, evento.y) is None and not self.ambiente and not self.editando and not self.bus_activo:
            self.poner_tv(not self.tv)

    def _mover(self, evento):
        self.mouse = (evento.x, evento.y)
        if self._arrastre_ventana:
            try:
                self.root.geometry(f"+{evento.x_root - self._arrastre_ventana[0]}+{evento.y_root - self._arrastre_ventana[1]}")
            except Exception:
                pass
            return
        if self.editando:
            self.editor.mover_mouse(self, evento.x, evento.y)
            return
        accion = self._zona(evento.x, evento.y)
        self.hover = accion
        try:
            self.canvas.config(cursor="hand2" if accion else "")
        except Exception:
            pass

    # ---------------- escribirle a Arché ----------------
    def enviar_orden(self, texto):
        texto = str(texto).strip()
        if texto:
            self.cmd_hist.append(texto)
            self.cmd_pos = len(self.cmd_hist)
            entrada.enviar(texto, "ventana")

    def rellenar_entrada(self, texto):
        try:
            self.entry.delete(0, "end")
            self.entry.insert(0, texto)
            self.entry.focus_set()
            self.entry.icursor("end")
        except Exception:
            pass

    def _enviar(self, evento=None):
        texto = self.entry.get().strip()
        if not texto:
            return "break"
        self.entry.delete(0, "end")
        self.enviar_orden(texto)
        return "break"

    def _historial_cmd(self, paso):
        if not self.cmd_hist:
            return "break"
        self.cmd_pos = max(0, min(len(self.cmd_hist), self.cmd_pos + paso))
        self.entry.delete(0, "end")
        if self.cmd_pos < len(self.cmd_hist):
            self.entry.insert(0, self.cmd_hist[self.cmd_pos])
        return "break"

    def avisar(self, texto, tipo="info"):
        en_vivo.avisar(texto, tipo)

    # ---------------- buscador de comandos (Ctrl+Espacio) ----------------
    def poner_buscador(self, activo):
        self.bus_activo = bool(activo) and not self.editando
        if self.bus_activo:
            self.bus_entry.delete(0, "end")
            self.bus_res = buscador.buscar("", 7, self)
            self.bus_sel = 0
            self.canvas.itemconfigure(self.bus_id, state="normal")
            self.root.after(30, self.bus_entry.focus_set)
        else:
            self.canvas.itemconfigure(self.bus_id, state="hidden")
            self.entry.focus_set()

    def _bus_teclas(self, evento):
        if evento.keysym in ("Up", "Down", "Return", "Escape"):
            return
        self.bus_res = buscador.buscar(self.bus_entry.get(), 7, self)
        self.bus_sel = 0

    def _bus_mover(self, paso):
        if self.bus_res:
            self.bus_sel = (self.bus_sel + paso) % len(self.bus_res)
        return "break"

    def _bus_ejecutar(self):
        texto = self.bus_entry.get().strip()
        if self.bus_res and (self.bus_sel < len(self.bus_res)):
            accion = self.bus_res[self.bus_sel]["accion"]
            self.poner_buscador(False)
            self._ejecutar_buscador(accion)
        elif texto:
            self.poner_buscador(False)
            self.enviar_orden(texto)
        return "break"

    def _ejecutar_buscador(self, a):
        if a == "tv":
            self.poner_tv(not self.tv)
        elif a == "ambiente":
            self.ambiente = True
        elif isinstance(a, tuple) and a[0] == "editor":
            self.poner_editor(True)
        elif isinstance(a, tuple) and a[0] == "centro_ir":
            self.abrir_centro(a[1])
        else:
            centro.ejecutar(self, a)

    # ---------------- editor y centro ----------------
    def poner_editor(self, activo, cancelar=False):
        activo = bool(activo)
        if activo and not self.editando:
            self.poner_buscador(False)
            self.ambiente = False
            self.editor.entrar()
            self.editando = True
        elif not activo and self.editando:
            self.editor.salir(cancelar)
            self.editando = False
            self.avisar("Diseño cancelado: volvió a como estaba." if cancelar else "Diseño guardado.", "info" if cancelar else "exito")

    def abrir_centro(self, categoria=None):
        lay = perfiles.layout_actual()
        panel = next((w for w in lay["widgets"] if w["tipo"] == "panel"), None)
        if panel is None or not panel["visible"] or panel.get("ventana"):
            ok, msg = layout.anadir(lay, "panel") if panel is None else layout.mostrar(lay, panel["id"])
            if not ok:
                self.avisar("No hay lugar para el panel: " + msg, "error")
            perfiles.marcar_sucio()
        self.pestana = "ajustes"
        if categoria:
            self.centro_cat = categoria
            self.centro_busqueda = ""
            self.busca.delete(0, "end")
        self.scroll["ajustes"] = 0

    def buscar_ajuste(self, texto):
        self.abrir_centro()
        self.busca.delete(0, "end")
        self.busca.insert(0, texto)
        self.centro_busqueda = texto

    def pedir_color(self, que):
        """Abre el selector de colores del sistema para 'rol:x', 'ajuste:x', 'estado:x' o 'widget:x'."""
        try:
            from tkinter import colorchooser
            actual = None
            tipo, _, clave = que.partition(":")
            if tipo == "rol":
                actual = tema.colores_de(tema.actual()).get(clave)
            elif tipo == "ajuste":
                actual = ajustes.obtener(clave) or None
            elif tipo == "estado":
                actual = ajustes.obtener("estado_colores").get(clave)
            res = colorchooser.askcolor(color=actual or tema.MORADO_CLARO, title="Elige un color", parent=self.root)
            hexa = res[1] if res else None
        except Exception:
            hexa = None
        if not hexa:
            return
        tipo, _, clave = que.partition(":")
        ev.punto_de_control("color")
        if tipo == "rol":
            if not tema.es_propio(tema.actual()):
                ok, nombre = tema.crear("Mi " + tema.NOMBRES.get(tema.actual(), tema.actual()), tema.actual())
                if not ok:
                    nombre = nombre if isinstance(nombre, str) else ""
                    self.avisar(str(nombre), "error")
                    return
                ajustes.fijar("tema", nombre)
                tema.aplicar(nombre)
            ok, msg = tema.fijar_color(tema.actual(), clave, hexa)
            self.avisar(("Color cambiado: " + tema.ROLES.get(clave, clave)) if ok else msg, "exito" if ok else "error")
        elif tipo == "ajuste":
            ajustes.fijar(clave, hexa)
        elif tipo == "estado":
            d = dict(ajustes.obtener("estado_colores"))
            d[clave] = hexa
            ajustes.fijar("estado_colores", d)
        elif tipo == "widget":
            layout.opcion(perfiles.layout_actual(), clave, "color", hexa)
            perfiles.marcar_sucio()

    # ---------------- ventana: tv, modos, geometria ----------------
    def poner_tv(self, valor):
        valor = bool(valor)
        if valor == self.tv and self.tam_fondo is not None:
            return
        if valor and not self.tv:
            try:
                self.geo_normal = self.root.geometry()
            except Exception:
                pass
        self.tv = valor
        try:
            if valor:
                self.root.attributes("-fullscreen", True)
            else:
                self.root.attributes("-fullscreen", False)
                self.root.geometry(self.geo_normal)
            self.root.update_idletasks()
            self.root.after(100, self._dar_foco)
        except Exception:
            pass

    def _sin_borde(self):
        return bool(ajustes.obtener("ventana_sin_borde")) or ajustes.obtener("ventana_modo") == "superpuesta"

    def _aplicar_ventana(self, forzar=False):
        """Modo (normal/compacta/superpuesta), siempre visible, transparencia y sin borde."""
        modo = ajustes.obtener("ventana_modo")
        sig = (modo, bool(ajustes.obtener("ventana_siempre_visible")), int(ajustes.obtener("ventana_opacidad")),
               bool(ajustes.obtener("ventana_sin_borde")))
        if sig == self._sig_ventana and not forzar:
            return
        previo = self._sig_ventana
        self._sig_ventana = sig
        r = self.root
        try:
            if modo == "compacta" and (previo is None or previo[0] != "compacta"):
                if previo is not None and not self.tv:
                    self.geo_normal = r.geometry()
                r.minsize(300, 260)
                r.geometry("460x440")
            elif modo != "compacta" and previo is not None and previo[0] == "compacta":
                r.minsize(640, 380)
                r.geometry(self.geo_normal if "x" in self.geo_normal else "1100x660")
            sin_borde = self._sin_borde()
            r.overrideredirect(sin_borde)
            r.attributes("-topmost", bool(sig[1]) or modo == "superpuesta")
            alfa = sig[2] if modo != "superpuesta" else min(sig[2], 85)
            r.attributes("-alpha", max(0.3, min(1.0, alfa / 100.0)))
            if sin_borde:
                self.root.after(50, self._dar_foco)
        except Exception:
            pass

    def _guardar_geometria(self):
        if self.tv or ajustes.obtener("ventana_modo") != "normal" or time.time() - self._geo_guardada < 3:
            return
        self._geo_guardada = time.time()
        try:
            geo = self.root.geometry()
            if geo != ajustes.obtener("ventana_geometria") and "x" in geo:
                ajustes.fijar("ventana_geometria", geo)
                self.geo_normal = geo
        except Exception:
            pass

    def mostrar_principal(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def cerrar(self):
        try:
            for s in list(self.secundarias.values()):
                s.cerrar(devolver=False)
            if self.flotante is not None:
                self.flotante.cerrar()
            if self.fondo is not None:
                self.fondo.cerrar()
            self.root.destroy()
        except Exception:
            pass

    # ---------------- peticiones desde otros hilos ----------------
    def _procesar_peticiones(self):
        while self.peticiones:
            accion, dato = self.peticiones.popleft()
            try:
                if accion == "editor":
                    self.poner_editor(bool(dato))
                elif accion == "centro":
                    self.abrir_centro()
                elif accion == "buscar_ajuste":
                    self.buscar_ajuste(str(dato))
                elif accion == "desacoplar":
                    self._desacoplar(str(dato))
                elif accion == "buscador":
                    self.poner_buscador(bool(dato))
                elif accion == "mostrar":
                    self.mostrar_principal()
                elif accion == "pestana":
                    self.pestana = str(dato)
                elif accion == "ambiente":
                    self.ambiente = bool(dato)
                elif accion == "bandeja_salir":
                    self.cerrar()
                elif accion == "redes":
                    vista_redes.ui["grande"] = bool(dato)
            except Exception as e:
                print(f"[interfaz] petición «{accion}» falló: {e}")

    def pedir(self, accion, dato=None):          # llamado dentro del hilo de la ventana (centro.py)
        self.peticiones.append((accion, dato))
        return True

    # ---------------- widgets en ventanas aparte ----------------
    def _desacoplar(self, wid):
        lay = perfiles.layout_actual()
        w = layout.buscar(lay, wid)
        if w is None or w["tipo"] == "chat":
            return
        ev.punto_de_control("ventana aparte")
        if not w.get("ventana"):
            w["ventana"] = {"x": self.root.winfo_x() + 80, "y": self.root.winfo_y() + 80, "w": 420, "h": 320}
        w["visible"] = True
        perfiles.marcar_sucio()

    def _volver_al_panel(self, wd):
        lay = perfiles.layout_actual()
        wd["ventana"] = None
        self.secundarias.pop(wd["id"], None)
        if layout.choques(lay, layout.rect(wd), wd["id"]):
            wd["visible"] = False
            ok, msg = layout.mostrar(lay, wd["id"])
            if not ok:
                self.avisar(msg.capitalize(), "info")
        perfiles.marcar_sucio()

    def _sincronizar_secundarias(self):
        lay = perfiles.layout_actual()
        deseadas = {w["id"]: w for w in lay["widgets"] if w.get("ventana") and w["visible"]}
        for wid in list(self.secundarias):
            if wid not in deseadas or self.secundarias[wid].wd is not deseadas[wid]:
                self.secundarias.pop(wid).cerrar(devolver=False)
        for wid, w in deseadas.items():
            if wid not in self.secundarias:
                try:
                    self.secundarias[wid] = Secundaria(self, w)
                except Exception as e:
                    print(f"[interfaz] no pude abrir la ventana de {wid}: {e}")
                    w["ventana"] = None
        for s in self.secundarias.values():
            s.dibujar()

    # ---------------- tema ----------------
    def _firma_tema(self):
        nombre = ajustes.obtener("tema")
        extra = ""
        if tema.es_propio(nombre):
            extra = json.dumps(tema._cargar_personales().get(nombre), sort_keys=True)
        return (nombre, bool(ajustes.obtener("alto_contraste")), extra)

    def _aplicar_tema(self, forzar=False):
        sig = self._firma_tema()
        if sig == self._sig_tema and not forzar:
            return
        self._sig_tema = sig
        if not tema.aplicar(sig[0]):
            tema.aplicar("arche")
        self.tam_fondo = None
        try:
            self.root.configure(bg=tema.FONDO)
            self.canvas.configure(bg=tema.FONDO)
            for e in (self.entry, self.busca, self.bus_entry):
                e.configure(bg=tema.PANEL_2, fg=tema.TEXTO, insertbackground=tema.MORADO_CLARO,
                            selectbackground=tema.MORADO, highlightbackground=tema.BORDE,
                            highlightcolor=tema.MORADO_CLARO)
        except Exception:
            pass

    # ---------------- utilidades de dibujo ----------------
    def _esc(self):
        return max(0.6, min(2.6, self.alto / 720.0)) * ajustes.obtener("ui_escala") / 100.0

    def _reducido(self):
        return bool(ajustes.obtener("reducir_movimiento"))

    def _ahorro(self):
        return ajustes.obtener("rendimiento") == "ahorro" or rendimiento.activo()

    def _texto(self, x, y, txt, tam, color, ancla="w", negrita=False, mono=False, ancho=None):
        t = ajustes.obtener("texto_escala") / 100.0
        fuente = (tema.FUENTE_MONO if mono else self._fuente, max(7, int(tam * self._esc() * t)),
                  "bold" if negrita else "normal")
        kw = {"width": ancho} if ancho else {}
        if ancho and ancla == "w":            # texto de varias lineas: que crezca hacia abajo, no hacia los dos lados
            ancla, y = "nw", y - fuente[1] * 0.75
        return self.canvas.create_text(x, y, text=txt, fill=color, font=fuente, anchor=ancla, tags=self._tag, **kw)

    def _redondo(self, x0, y0, x1, y1, r, **kw):
        r = max(1, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        p = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
             x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(p, smooth=True, tags=self._tag, **kw)

    def _linea(self, pts, color, ancho, redondo=True, suave=False):
        return self.canvas.create_line(*pts, fill=color, width=ancho, tags=self._tag, smooth=suave,
                                       capstyle="round" if redondo else "butt", joinstyle="round")

    def _con_fondo(self):
        return (self.fondo is not None and self._fondo_item is not None) or ajustes.obtener("escena") not in ("ninguna", "gradiente")

    def _relleno(self, color, op=None):
        """(fill, stipple) de un panel con la transparencia del widget que se esta dibujando."""
        if op is None:
            op = (self._wd or {}).get("opacidad", 100)
        if op >= 98:
            return color, ""
        if self._con_fondo():                       # sobre imagen o escena: trama (el canvas no tiene alfa)
            if op >= 80:
                return color, "gray75"
            if op >= 50:
                return color, "gray50"
            if op >= 20:
                return color, "gray25"
            return "", ""
        return tema.mezclar(tema.FONDO, color, max(0.0, op / 100.0)), ""

    def _tarjeta(self, x, y, w, h, titulo, color):
        """Tarjeta de un widget: sombra, borde luminoso, profundidad y transparencia segun Ajustes."""
        esc = self._esc()
        op = (self._wd or {}).get("opacidad", 100)
        fill, stip = self._relleno(tema.PANEL, op)
        A = ajustes.obtener
        ligero = self._ahorro()
        sombra = 0 if ligero else A("efecto_sombra")
        if sombra and op >= 40:
            d = 4 * esc * sombra / 100.0 + 1
            self._redondo(x + d, y + d * 1.4, x + w + d, y + h + d * 1.4, 14 * esc,
                          fill=tema.mezclar(tema.FONDO, "#000000", min(0.85, 0.25 + sombra / 140.0)), outline="")
        lum = 0 if ligero else A("efecto_borde_luminoso")
        if lum:
            self._redondo(x - 2, y - 2, x + w + 2, y + h + 2, 15 * esc, fill="", outline=tema.mezclar(tema.FONDO, color, 0.10 + 0.30 * lum / 100.0), width=2)
        kw = {"fill": fill, "outline": tema.mezclar(tema.BORDE, color, 0.35 * lum / 100.0) if lum else tema.BORDE, "width": 1}
        if stip:
            kw["stipple"] = stip
        self._redondo(x, y, x + w, y + h, 14 * esc, **kw)
        if A("efecto_profundidad") and not ligero and op >= 60:       # reflejo de arriba y borde inferior mas oscuro
            self.canvas.create_line(x + 14 * esc, y + 2, x + w - 14 * esc, y + 2, fill=tema.mezclar(tema.PANEL, tema.TEXTO, 0.10), tags=self._tag)
            self.canvas.create_line(x + 14 * esc, y + h - 2, x + w - 14 * esc, y + h - 2, fill=tema.mezclar(tema.PANEL, "#000000", 0.5), tags=self._tag)
        if titulo:
            self.canvas.create_oval(x + 16 * esc, y + 16 * esc, x + 24 * esc, y + 24 * esc, fill=color, outline="", tags=self._tag)
            self._texto(x + 32 * esc, y + 20 * esc, titulo, 10, color, negrita=True)

    def _tarjeta_simple(self, x, y, w, h, wd=None):
        self._tarjeta(x, y, w, h, "", (wd or {}).get("color") or tema.MORADO_CLARO)

    def _interruptor_color(self, encendido, pasa):
        return tema.mezclar(tema.BOTON, tema.SELECCION, 0.85 if encendido else (0.3 if pasa else 0.0))

    # ---------------- estado extendido, etiquetas, navegacion ----------------
    def estado_extendido(self):
        """Uno de centro.ESTADOS. Aproximado a partir de lo que Arché de verdad esta haciendo."""
        base = en_vivo.estado_visual()
        ahora = time.time()
        if any(a["tipo"] == "error" and ahora - a["ts"] < 8 for a in list(self.historial_notif)[-3:]):
            return "error"
        if lenguaje.hay_pendiente():
            return "confirmando"
        eq = self.snap.get("equipo", {})
        if (eq.get("cpu", 0) >= ajustes.obtener("limite_cpu") or eq.get("ram", 0) >= ajustes.obtener("limite_ram")) and base == "reposo":
            return "alerta"
        if base == "pensando":
            ultimo = next((m for m in reversed(list(en_vivo.chat)) if m["q"] == "tu"), None)
            if ultimo and ahora - ultimo["ts"] < 15 and any(p in ultimo["t"].lower() for p in _PALABRAS_BUSQUEDA):
                self._buscando_hasta = ahora + 25
                return "buscando"
            if en_vivo.pensando_desde and ahora - en_vivo.pensando_desde > 5:
                return "generando"
            return "pensando"
        if base == "reposo" and any(p["activo"] and p["nombre"] in ("Acción en el PC", "Orden automática")
                                    for p in self.snap.get("procesos", [])):
            return "ejecutando"
        return base

    def etiqueta_estado(self, est):
        defecto = {"reposo": tema.TENUE, "escuchando": tema.AZUL_CLARO, "pensando": tema.MORADO_CLARO,
                   "generando": tema.MORADO_CLARO, "hablando": tema.ROJO_CLARO, "ejecutando": tema.AZUL_CLARO,
                   "buscando": tema.AZUL_CLARO, "confirmando": tema.ATENCION, "alerta": tema.ALERTA,
                   "error": tema.ROJO_CLARO}
        propio = (ajustes.obtener("estado_colores") or {}).get(est)
        col = ajustes.normalizar_hex(propio) if propio else None
        return centro.NOMBRES_ESTADO.get(est, est), (col or defecto.get(est, tema.TENUE))

    def pestanas_ordenadas(self, todas=False):
        """[(clave, nombre, color_attr)] segun el orden y lo oculto que elegiste (PERSONALIZA nunca se oculta)."""
        base = {c: (c, n, col) for c, n, col in PESTANAS}
        orden = [c for c in ajustes.obtener("nav_orden") if c in base] + [c for c in base if c not in ajustes.obtener("nav_orden")]
        ocultas = set(ajustes.obtener("nav_ocultas")) - {"ajustes"}
        return [base[c] for c in orden if todas or c not in ocultas]

    def intervalo_objetivo(self):
        return {"alta": 33, "normal": 50, "ahorro": 83}.get(ajustes.obtener("fluidez"), 33)

    def clase_pantalla(self):
        w = self.ancho_real
        return "pequena" if w < 900 else ("amplia" if w > 1600 else "normal")

    def _layout_activo(self):
        if ajustes.obtener("ventana_modo") == "compacta" and not self.tv:
            if self._ult_lay_compacto is None:
                self._ult_lay_compacto = layout.armar([("voz", 0, 0, 24, 8), ("mascota", 0, 8, 24, 3), ("chat", 0, 11, 24, 5)],
                                                      margen=14, separacion=10, pie=False)
            return self._ult_lay_compacto
        return perfiles.layout_actual()

    # ---------------- animacion de la voz ----------------
    def _actualizar_ondas(self, hablando, activa):
        vel = ajustes.obtener("anim_velocidad") / 100.0
        if self._reducido():
            self.fase += 0.006
            self.nivel *= 0.8
            for i in range(BARRAS):
                self.alturas[i] *= 0.8
            return
        self.fase += (0.14 if hablando else 0.05) * vel
        for i in range(BARRAS):
            x = i / (BARRAS - 1)
            envolvente = math.sin(x * math.pi) ** 1.2
            base = 0.07 + 0.05 * math.sin(self.fase + i * 0.38) + 0.03 * math.sin(self.fase * 0.6 - i * 0.2)
            if hablando:
                if random.random() < 0.4:
                    self.objetivo[i] = random.uniform(0.25, 1.0) * envolvente
            else:
                self.objetivo[i] = base * envolvente * (1.7 if activa else 1.0)
            self.alturas[i] += (self.objetivo[i] - self.alturas[i]) * 0.33
        media = sum(self.alturas) / BARRAS
        self.nivel += (media - self.nivel) * 0.2

    # ---------------- ciclo ----------------
    def cuadro(self):
        if self.pedir_cerrar:
            return self.cerrar()
        t_ini = time.time()
        if self.pedir_tv is not None:
            self.poner_tv(self.pedir_tv)
            self.pedir_tv = None
        self._procesar_peticiones()
        ahora = t_ini
        en_vivo.sondear()
        try:
            self._tareas_periodicas(ahora)
        except tk.TclError:
            return
        except Exception as e:
            self._una_vez("periodicas", e)
        ahorro = self._ahorro()
        intervalo = self.intervalo_objetivo()
        refresco = max(1, int(ajustes.obtener("sistema_actualizacion"))) if not ahorro else max(2, int(ajustes.obtener("sistema_actualizacion")))
        if ahora - self.ultimo_snap > refresco and ahora - self.t0 > 3.0:
            self.ultimo_snap = ahora
            try:
                self.snap = datos.instantanea()
                self._registrar_muestras()
            except Exception:
                pass
        try:
            self._vigilar_cambios()
        except Exception as e:
            self._una_vez("vigilar", e)
        try:
            self.dibujar()
            self._animar_fondo()
            self._sincronizar_secundarias()
            self._sincronizar_extras()
        except tk.TclError:
            return
        except Exception as e:
            self._una_vez("dibujar", e)
        dur = time.time() - t_ini
        self.ms_cuadro = dur * 1000.0
        rendimiento.medir(dur, intervalo / 1000.0)
        if rendimiento.conviene_proponer():
            self._proponer_ahorro()
        try:
            self.root.after(max(1, int(intervalo - dur * 1000)), self.cuadro)
        except tk.TclError:
            return

    def _una_vez(self, clave, e):
        if clave not in self._errores_w:
            self._errores_w.add(clave)
            print(f"[interfaz] error en «{clave}» (sigo funcionando): {e}")

    def _tareas_periodicas(self, ahora):
        """Cosas que se revisan de vez en cuando: tema, atajos, ventana, perfil por pantalla, hora, guardado."""
        self._aplicar_tema()
        firma_at = json.dumps({**ajustes.DEFAULTS["atajos"], **(ajustes.obtener("atajos") or {})}, sort_keys=True)
        if firma_at != self._sig_atajos:
            self._vincular_atajos()
        self._aplicar_ventana()
        self._guardar_geometria()
        if ahora - self._ultimo_vistazo > 3.0:
            self._ultimo_vistazo = ahora
            perfiles.volcar()
            if ajustes.obtener("tema_horario"):
                deseado = ajustes.obtener("tema_dia") if tema.tema_por_hora() == "dia" else ajustes.obtener("tema_noche")
                if tema.existe(deseado) and ajustes.obtener("tema") != tema.resolver(deseado):
                    ajustes.fijar("tema", tema.resolver(deseado))
        clase = self.clase_pantalla()
        if clase != self._ultima_clase and ahora - self.t0 > 2:
            primera = self._ultima_clase is None
            self._ultima_clase = clase
            destino = (ajustes.obtener("pantallas") or {}).get(clase)
            if destino and not primera and perfiles.resolver(destino) and perfiles.activo() != perfiles.resolver(destino):
                ok, msg = perfiles.activar(destino)
                if ok:
                    self.avisar(f"Pantalla {clase}: usé el perfil «{perfiles.activo()}».", "info")

    def _registrar_muestras(self):
        eq = self.snap.get("equipo", {})
        if "cpu" in eq:
            self.hist_cpu.append(eq["cpu"])
            self.hist_ram.append(eq["ram"])

    def _proponer_ahorro(self):
        def aplicar():
            cambios = rendimiento.aplicar()
            return ("Listo, activé el modo ahorro (cambié: " + ", ".join(cambios) + "). Di «revertir ahorro» para dejarlo como estaba."
                    if cambios else "Ya estaba en modo ahorro.")
        resumen = ["menos cuadros por segundo", "sin fondos animados ni escenas", "sin sombras ni partículas", "widgets se actualizan menos"]
        msg = lenguaje._pide_confirmacion("modo ahorro", resumen, aplicar)
        en_vivo.avisar("La interfaz va lenta. " + msg, "info")
        self.mascota.decir("Voy lenta… ¿activo el modo ahorro? Di «sí» o toca Aplicar.", 15)

    def _vigilar_cambios(self):
        """Avisos, ambiente automatico, comportamiento de la mascota y contexto (una vez por cuadro)."""
        ahora = time.time()
        A = ajustes.obtener
        for a in en_vivo.tomar_avisos():
            self.historial_notif.append(a)
            permitido = (not A("notif_silencio")) and A({"exito": "notif_exito", "error": "notif_error"}.get(a["tipo"], "notif_info"))
            if permitido:
                self.toasts.append(a)
                sonido.tocar("aviso")
            if A("mascota") and A("mascota_reacciones"):
                if a["tipo"] == "exito":
                    self.mascota.celebrar()
                self.mascota.decir(a["texto"], 8)
        dur = max(2, int(A("notif_segundos")))
        self.toasts = [t for t in self.toasts if ahora - t["ts"] < dur][-3:]
        # ambiente automatico (o "reducirse a la esfera" si lo permitiste)
        if (A("ambiente_auto") or A("ctx_reposo")) and not self.ambiente and not self.editando:
            if en_vivo.segundos_sin_actividad() > max(1, int(A("ambiente_minutos"))) * 60:
                self.ambiente = True
        if self.ambiente and en_vivo.ordenes != self._prev_ordenes:
            self.ambiente = False
        self._prev_ordenes = en_vivo.ordenes
        # resultados de busqueda en ventana temporal (si lo permitiste)
        n = len(en_vivo.chat)
        if n != self._ultimo_chat:
            nuevos = list(en_vivo.chat)[-(n - self._ultimo_chat):] if n > self._ultimo_chat else []
            self._ultimo_chat = n
            if A("ctx_resultados") and ahora < self._buscando_hasta:
                for m in nuevos:
                    if m["q"] == "arche" and len(m["t"]) > 60:
                        self._ventana_temporal("Resultado de la búsqueda", m["t"])
                        self._buscando_hasta = 0
                        break
        # recorrido la primera vez
        if (A("mascota") and not A("recorrido_hecho") and self.mascota.paso is None
                and ahora - self.t0 > 6 and not self.ambiente):
            self.mascota.iniciar_recorrido(A("mascota_nombre"))
            self._pestana_del_paso()
        self.mascota.cadencia = {"poca": 1.8, "normal": 1.0, "mucha": 0.5}.get(A("mascota_frecuencia"), 1.0)
        est = self._estado_mascota()
        if self.mascota.hay_mensaje() or est in ("hablando", "pensando"):
            self._masc_hasta = ahora + 10
        self.mascota.tick(A("consejos") and A("mascota"), est in ("hablando", "pensando"), est == "dormida")
        # el color del orbe y su luz siguen los ajustes
        orbe.luz = A("efecto_brillo") / 60.0 * (0.4 if self._ahorro() else 1.0)

    def _estado_mascota(self):
        vis = en_vivo.estado_visual()
        if not ajustes.obtener("mascota_reacciones"):
            return self.mascota.estado(False, False, None, False, 0, 12)
        eq = self.snap.get("equipo", {})
        ex = self.snap.get("examen", {})
        estudiando = bool(ex.get("automatico")) or any(
            c["id"] == "estudio" and c["valor"] for c in self.snap.get("controles", []))
        return self.mascota.estado(vis == "hablando", vis == "pensando", eq.get("cpu"), estudiando,
                                   en_vivo.segundos_sin_actividad(), time.localtime().tm_hour)

    def _ventana_temporal(self, titulo, texto):
        """Ventanita que se cierra sola con resultados (solo si activaste «resultados en ventana temporal»)."""
        try:
            if self._temp is not None:
                self._temp.destroy()
            top = tk.Toplevel(self.root)
            top.title("Arché · " + titulo)
            top.configure(bg=tema.PANEL)
            top.geometry("460x260+%d+%d" % (self.root.winfo_x() + 60, self.root.winfo_y() + 60))
            top.attributes("-topmost", True)
            tk.Label(top, text=texto[:900], bg=tema.PANEL, fg=tema.TEXTO, justify="left", wraplength=430,
                     font=(self._fuente, 11), anchor="nw").pack(fill="both", expand=True, padx=14, pady=12)
            top.after(25000, lambda: top.destroy() if top.winfo_exists() else None)
            self._temp = top
        except Exception:
            pass

    # ---------------- fondo ----------------
    def _fondo(self, W, H):
        c = self.canvas
        c.delete("fondo")
        self._tag = "fondo"
        nombre = ajustes.obtener("fondo")
        if self.fondo is not None:
            self.fondo.cerrar()
            self.fondo = None
        self._fondo_item = None
        if nombre:
            self.fondo = fondos.Fondo(tk, nombre, W, H, ajustes.obtener("fondo_oscuridad"), tema.FONDO)
            self.fondo.desenfoque = int(ajustes.obtener("fondo_desenfoque"))
            self.fondo.quieto = self._fondo_quieto()
            foto = self.fondo.cuadro()
            if self.fondo.error:
                en_vivo.avisar(self.fondo.error, "error")
                self.fondo = None
            elif foto is not None:
                self._foto = foto
                self._fondo_item = c.create_image(0, 0, image=foto, anchor="nw", tags="fondo")
        if self._fondo_item is None:
            escenas.gradiente(c, W, H)
        c.tag_lower("fondo")
        self._tag = "din"

    def _fondo_quieto(self):
        return (not ajustes.obtener("fondo_movimiento")) or self._reducido() or self._ahorro()

    def _animar_fondo(self):
        if self.fondo is not None and self._fondo_item is not None:
            self.fondo.quieto = self._fondo_quieto()
            if self.fondo.animado:
                foto = self.fondo.cuadro()
                if foto is not None:
                    self._foto = foto
                    self.canvas.itemconfigure(self._fondo_item, image=foto)
                if self.fondo.error:
                    en_vivo.avisar(self.fondo.error, "error")
                    self.tam_fondo = None

    # ---------------- dibujo principal ----------------
    def dibujar(self):
        c = self.canvas
        self.ancho_real, self.alto_real = c.winfo_width(), c.winfo_height()
        self.ancho = max(320, self.ancho_real)
        self.alto = max(200, self.alto_real)
        W, H = self.ancho, self.alto
        A = ajustes.obtener
        clave = (W, H, self._sig_tema, A("fondo"), A("fondo_oscuridad"), A("fondo_desenfoque"), A("escena") == "gradiente")
        if self.tam_fondo != clave:
            self.tam_fondo = clave
            self._fondo(W, H)
        self._fuente = A("fuente") or tema.FUENTE
        c.delete("din")
        for iid in (self.entry_id, self.busca_id, self.bus_id, self.red_add_id, self.red_test_id):
            c.itemconfigure(iid, state="hidden")
        self.zonas = []
        self.regiones = {}
        self._scroll_reg = {}
        self._tag = "din"
        self._wd = None
        esc = self._esc()
        self._esc_c = esc
        vz = self.snap["voz"]
        estado = self.estado_extendido()
        base = ESTADO_BASE.get(estado, "reposo")
        hablando = base == "hablando"
        activa = bool(vz.get("activa")) or base == "escuchando"
        self._actualizar_ondas(hablando, activa)
        if not self._ahorro():
            escenas.dibujar(self, W, H, self.fase, quieto=self._reducido())

        if self.ambiente:
            self._modo_ambiente(W, H, int(22 * esc), esc, estado)
            self._toasts(W, int(22 * esc), esc)
            return
        if vista_redes.ui["grande"] and not self.editando:
            try:
                vista_redes.dibujar_grande(self, W, H, esc)
            except Exception as e:
                if isinstance(e, tk.TclError):
                    raise
                self._una_vez("vista_redes", e)
                vista_redes.ui["grande"] = False
            else:
                self._toasts(W, int(16 * esc), esc)
                if self.bus_activo:
                    self._dibujar_buscador(W, H, esc)
                return
        lay = self._layout_activo()
        m = int(lay["margen"] * esc)
        if lay.get("cabecera", True):
            self._encabezado(W, m, esc, estado)
        top = m + (58 * esc if lay.get("cabecera", True) else 0)
        pie = 34 * esc if lay.get("pie", True) else 0
        bajo = H - m - pie
        gap = lay["separacion"] * esc
        cw = (W - 2 * m) / layout.COLS
        ch = max(1.0, (bajo - top) / layout.FILAS)
        self.grid = (m, top, cw, ch, gap)
        objetivos = {}
        for wd in lay["widgets"]:
            if wd["visible"] and not wd.get("ventana"):
                objetivos[wd["id"]] = (m + wd["x"] * cw + gap / 2, top + wd["y"] * ch + gap / 2,
                                       wd["w"] * cw - gap, wd["h"] * ch - gap)
        self.rects = objetivos
        self._pintar_layout(lay, objetivos)
        if self.editando:
            self.editor.dibujar(self, W, H, esc)
        else:
            self._recorrido_resalte(esc)
            if lay.get("pie", True):
                self._pie(W, H, m, esc)
            self._overlay_progreso(W, H, esc, lay)
        self._toasts(W, m, esc)
        if self.menu_nav:
            pass
        if self.bus_activo:
            self._dibujar_buscador(W, H, esc)
        self._anillo_teclado(esc)

    def _pintar_layout(self, lay, objetivos):
        """Dibuja cada widget; los que cambian de sitio o tamaño se deslizan (si las transiciones estan activas)."""
        anim = ajustes.obtener("anim_transiciones") and not self._reducido() and not self._ahorro()
        k = min(0.9, 0.34 * ajustes.obtener("anim_velocidad") / 100.0)
        vis = self._vis
        for wd in lay["widgets"]:
            tgt = objetivos.get(wd["id"])
            if tgt is None:
                continue
            cur = vis.get(wd["id"])
            if cur is None:
                cur = (tgt[0] + tgt[2] / 2, tgt[1] + tgt[3] / 2, 0.0, 0.0) if (anim and self._vis_listo) else tgt
            if anim:
                cur = tuple(a + (b - a) * k for a, b in zip(cur, tgt))
                if max(abs(a - b) for a, b in zip(cur, tgt)) < 1.2:
                    cur = tgt
            else:
                cur = tgt
            vis[wd["id"]] = cur
            if cur == tgt:
                self._pintar_widget(wd, *cur)
            elif cur[2] > 8 and cur[3] > 8:
                self._wd = wd
                self._tarjeta_simple(*cur, wd)
                self._wd = None
        # los que se ocultaron se encogen hasta desaparecer
        for wid in [i for i in vis if i not in objetivos]:
            x, y, w, h = vis[wid]
            if not anim or w < 10 or h < 10:
                vis.pop(wid, None)
                continue
            nw, nh = w * (1 - k), h * (1 - k)
            nx, ny = x + (w - nw) / 2, y + (h - nh) / 2
            vis[wid] = (nx, ny, nw, nh)
            self._tarjeta_simple(nx, ny, nw, nh)
        self._vis_listo = True

    def _pintar_widget(self, wd, x, y, w, h):
        """Dibuja UN widget en (x, y, w, h). Un error en un widget nunca tumba a los demas."""
        self._wd = wd
        esc = self._esc()
        tipo = wd["tipo"]
        try:
            if tipo == "voz":
                self._w_voz(wd, x, y, w, h, esc)
            elif tipo == "mascota":
                self._w_mascota(wd, x, y, w, h, esc)
            elif tipo == "chat":
                self._w_chat(wd, x, y, w, h, esc)
            elif tipo == "panel":
                self._w_panel(wd, x, y, w, h, esc)
            elif tipo.startswith("ext:"):
                extensiones.dibujar(self, wd, x, y, w, h, esc)
            else:
                fn = widgets.TABLA.get(tipo)
                if fn is None:
                    self._tarjeta(x, y, w, h, layout.nombre_de(tipo).upper(), tema.TENUE)
                    self._texto(x + 16 * esc, y + 50 * esc, "Widget sin dibujo.", 9, tema.TENUE)
                else:
                    fn(self, wd, x, y, w, h, esc)
        except tk.TclError:
            raise
        except Exception as e:
            self._una_vez("widget:" + wd["id"], e)
            self._tarjeta(x, y, w, h, layout.nombre_de(tipo).upper(), tema.ROJO_CLARO)
            self._texto(x + 16 * esc, y + 50 * esc, "Este widget tuvo un error (los demás siguen).", 9, tema.TENUE)
        finally:
            self._wd = None

    # ---------------- encabezado y pie ----------------
    def _encabezado(self, W, m, esc, estado):
        c = self.canvas
        self._texto(m, m + 12 * esc, "A R C H É", 22, tema.TEXTO, negrita=True)
        self._texto(m + 2, m + 36 * esc, "asistente autónomo", 9, tema.TENUE)
        lt = time.localtime()
        nombre, col = self.etiqueta_estado(estado)
        modo = ajustes.obtener("estado_indicador")
        icono = (ICONOS_ESTADO.get(estado, "") + " ") if modo in ("icono", "combinado") else ""
        txt = icono + nombre
        pw = max(130, len(txt) * 7.4 + 44) * esc
        ph = 28 * esc
        x1 = W - m
        x0 = x1 - pw
        y0 = m + 2 * esc
        yc_p = y0 + ph / 2
        self._linea((x0 + ph / 2, yc_p, x1 - ph / 2, yc_p), col, ph)
        self._linea((x0 + ph / 2, yc_p, x1 - ph / 2, yc_p), tema.mezclar(tema.PANEL, col, 0.12), ph - 2)
        pulso = (0.5 + 0.5 * math.sin(self.fase * 2)) if (estado != "reposo" and not self._reducido()) else 0.3
        r = 4 * esc
        c.create_oval(x0 + 14 * esc - r, y0 + ph / 2 - r, x0 + 14 * esc + r, y0 + ph / 2 + r,
                      fill=tema.mezclar(tema.PANEL, col, 0.4 + 0.6 * pulso), outline="", tags=self._tag)
        self._texto(x0 + 28 * esc, y0 + ph / 2, txt, 10, col, negrita=True)
        self._texto(x0 - 18 * esc, m + 12 * esc, time.strftime("%H:%M", lt), 20, tema.TEXTO, ancla="e", negrita=True)
        self._texto(x0 - 18 * esc, m + 36 * esc, f"{DIAS[lt.tm_wday]} {time.strftime('%d/%m/%Y', lt)}", 9, tema.TENUE, ancla="e")
        c.create_line(m, m + 52 * esc, W - m, m + 52 * esc, fill=tema.BORDE, tags=self._tag)

    def _pie(self, W, H, m, esc):
        yb = H - m * 0.55
        sig = self._boton(W - m, yb, "Salir de pantalla completa" if self.tv else "Pantalla completa", "tv", tema.MORADO_CLARO)
        sig = self._boton(sig, yb, "Ambiente", "ambiente", tema.AZUL_CLARO)
        sig = self._boton(sig, yb, "Diseño", "editor", tema.MORADO_CLARO)
        sig = self._boton(sig, yb, "Buscar", "buscador", tema.AZUL_CLARO)
        if not self.tv:
            sig = self._boton(sig, yb, "Cerrar", "cerrar", tema.ROJO_CLARO)
        favs = [f for f in ajustes.obtener("favoritos") if isinstance(f, str)][:5]
        x = m
        if favs:
            self._texto(x, yb - 13 * esc, "FAVORITOS", 7, tema.TENUE)
            x += 70 * esc
            for f in favs:
                ancho = (len(f) * 6.6 + 20) * esc
                if x + ancho > sig - 10 * esc:
                    break
                x = self._chip(x, yb - 24 * esc, f, ("orden", f), False, tema.MORADO_CLARO, ancho) + 6 * esc
        else:
            self._texto(m, yb - 13 * esc, "Ctrl+Espacio busca cualquier cosa  ·  F11 pantalla completa  ·  Esc salir", 8, tema.TENUE)

    # ---------------- widget: esfera de voz ----------------
    def _w_voz(self, wd, x, y, w, h, esc):
        A = ajustes.obtener
        estado = self.estado_extendido()
        base = ESTADO_BASE.get(estado, "reposo")
        con_fondo = self._con_fondo()
        col = wd.get("color") or tema.MORADO_CLARO
        self._tarjeta(x, y, w, h, wd.get("titulo") or "", col)
        self.regiones["esfera"] = (x, y, x + w, y + h)
        modo = A("estado_indicador")
        quieto = modo in ("icono", "texto") or self._reducido()
        alto_texto = (24 * esc) if modo in ("texto", "combinado") else 0
        zona_y, zona_h = y + 26 * esc, h - 40 * esc - alto_texto
        if zona_h > 30 * esc:
            self._dibujar_voz(x, zona_y, w, zona_h, estado, base, esc, con_fondo, quieto)
        nombre, colr = self.etiqueta_estado(estado)
        if modo in ("texto", "combinado") and h > 80 * esc:
            self._texto(x + w / 2, y + h - 22 * esc, nombre, 11, colr, ancla="center", negrita=True)
        if modo in ("icono", "combinado") and h > 60 * esc:
            self._texto(x + w - 22 * esc, y + 22 * esc, ICONOS_ESTADO.get(estado, "•"), 16, colr, ancla="center", negrita=True)
        nivel_info = {"minimo": 0, "normal": 1, "detallado": 2}.get(wd.get("nivel"), 1)
        if nivel_info >= 1 and h > 120 * esc:
            nb, rd = self.snap.get("nube", {}), self.snap.get("red", {})
            cerebro = f"{nb.get('proveedor', 'ollama')} · {nb.get('modelo', 'local')}" if nb else "Ollama local"
            self._texto(x + 18 * esc, y + 16 * esc, "CEREBRO", 7, tema.TENUE)
            self._texto(x + 18 * esc, y + 30 * esc, cerebro[:max(8, int((w / 2 - 30 * esc) / (9 * esc * 0.6)))], 9, tema.MORADO_CLARO)
            if modo not in ("icono", "combinado"):
                self._texto(x + w - 18 * esc, y + 16 * esc, "RED NEURONAL", 7, tema.TENUE, ancla="e")
                self._texto(x + w - 18 * esc, y + 30 * esc,
                            f"{rd['precision'] * 100:.1f}% · {rd['intenciones']} intenciones" if rd.get("activo") else "inactiva",
                            9, tema.AZUL_CLARO if rd.get("activo") else tema.TENUE, ancla="e")

    def _dibujar_voz(self, x, y, w, h, estado, base, esc, transparente, quieto=False):
        """La representacion de Arché: esfera, ondas, anillos, nucleo o forma geometrica."""
        c = self.canvas
        A = ajustes.obtener
        estilo = A("estilo_voz")
        cx, cy = x + w / 2, y + h / 2
        nivel = 0.0 if quieto else self.nivel
        fase = (0.0 if quieto else self.fase) * A("orbe_velocidad") / 100.0
        _n, col_estado = self.etiqueta_estado(estado)
        propio = ajustes.normalizar_hex(A("orbe_color")) if A("orbe_color") else None
        forzado = propio or ((A("estado_colores") or {}).get(estado) and ajustes.normalizar_hex(A("estado_colores").get(estado)))
        escala = A("orbe_tamano") / 100.0
        if estilo == "esfera":
            r = max(20, min(h * 0.30, w * 0.22)) * escala
            fondo_t = tema.mezclar(tema.FONDO, tema.PANEL, 0.55)
            orbe.forzado = forzado or None
            try:
                orbe.dibujar(c, cx, cy, r, base, nivel, fase, self._tag, fondo_t, transparente)
            finally:
                orbe.forzado = None
            self._particulas(cx, cy, r, forzado or tema.MORADO_CLARO, fase)
            return
        ca = forzado or (tema.ROJO_CLARO if base == "hablando" else tema.AZUL_CLARO if base == "escuchando" else tema.MORADO_CLARO)
        cb = tema.mezclar(ca, tema.AZUL_CLARO, 0.5)
        if estilo == "ondas":
            margen = 26 * esc
            ax0, ax1 = x + margen, x + w - margen
            paso = (ax1 - ax0) / BARRAS
            ancho_b = max(3, paso * 0.58)
            c.create_line(ax0, cy, ax1, cy, fill=tema.BORDE, tags=self._tag)
            maxh = h * 0.80 * escala
            for i, a in enumerate(self.alturas):
                if quieto:
                    a = 0.05
                mitad = max(ancho_b / 2, a * maxh / 2)
                px = ax0 + paso * (i + 0.5)
                color = forzado or tema.degradado(i / (BARRAS - 1))
                halo = tema.mezclar(tema.PANEL, color, 0.28)
                self._linea((px, cy - mitad - 3, px, cy + mitad + 3), halo, ancho_b + 5 * esc)
                self._linea((px, cy - mitad + ancho_b / 2, px, cy + mitad - ancho_b / 2), color, ancho_b)
            return
        r = max(20, min(h * 0.30, w * 0.22)) * escala
        brillo = A("efecto_brillo") / 100.0 * (0.3 if self._ahorro() else 1.0)
        if estilo == "anillos":
            for k in range(4):
                rr = r * (0.45 + 0.2 * k) * (1 + 0.10 * nivel * (k + 1) + 0.03 * math.sin(fase * 1.5 + k))
                col = tema.mezclar(tema.FONDO, ca if k % 2 == 0 else cb, 0.35 + 0.15 * k)
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=col, width=max(2, int((3 - k * 0.4) * esc)), tags=self._tag)
                c.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=(fase * 40 * (1 if k % 2 else -1) + k * 70) % 360, extent=70,
                             style="arc", outline=ca, width=max(2, int(4 * esc)), tags=self._tag)
            n = r * 0.2 * (1 + nivel)
            c.create_oval(cx - n, cy - n, cx + n, cy + n, fill=tema.mezclar(ca, tema.TEXTO, 0.5), outline="", tags=self._tag)
        elif estilo == "nucleo":
            for k in range(6, 0, -1):
                rr = r * (0.3 + 0.12 * k) * (1 + 0.1 * nivel)
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=tema.mezclar(tema.PANEL, ca, 0.06 * (7 - k) * (0.4 + brillo)), outline="", tags=self._tag)
            n = r * 0.38 * (1 + 0.25 * nivel)
            c.create_oval(cx - n, cy - n, cx + n, cy + n, fill=tema.mezclar(ca, tema.TEXTO, 0.55), outline=ca, width=2, tags=self._tag)
            ext = 300 if base in ("pensando",) else 120
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(fase * 120) % 360, extent=ext, style="arc", outline=cb, width=max(3, int(5 * esc)), tags=self._tag)
        else:  # geometrica
            lados = 6
            for capa, (esc_r, col) in enumerate(((1.0, ca), (0.66, cb), (0.34, tema.TEXTO))):
                pts = []
                for i in range(lados):
                    ang = math.radians(60 * i) + fase * (0.4 if capa % 2 == 0 else -0.6)
                    rr = r * esc_r * (1 + 0.12 * nivel * math.sin(i * 2 + fase * 3))
                    pts += [cx + rr * math.cos(ang), cy + rr * math.sin(ang)]
                c.create_polygon(pts, fill=tema.mezclar(tema.PANEL, col, 0.10 + 0.06 * capa) if capa else "", outline=col, width=max(2, int(2.5 * esc)), tags=self._tag)
        self._particulas(cx, cy, r, ca, fase)

    def _particulas(self, cx, cy, r, color, fase):
        """Chispas alrededor de la esfera (cantidad segun Ajustes; ninguna con movimiento reducido o ahorro)."""
        A = ajustes.obtener
        cant = int(A("efecto_particulas") / 100.0 * 16 * A("efectos_simultaneos") / 10.0)
        if cant <= 0 or self._reducido() or self._ahorro():
            return
        for i in range(cant):
            ang = fase * (0.5 + 0.08 * (i % 5)) + i * 2.399
            rr = r * (1.25 + 0.35 * math.sin(fase * 0.9 + i))
            px, py = cx + rr * math.cos(ang), cy + rr * math.sin(ang) * 0.8
            tam = 1.5 + 1.8 * (0.5 + 0.5 * math.sin(fase * 2 + i))
            self.canvas.create_oval(px - tam, py - tam, px + tam, py + tam, fill=tema.mezclar(tema.FONDO, color, 0.35 + 0.5 * (i % 3) / 2), outline="", tags=self._tag)

    # ---------------- widget: mascota ----------------
    def _w_mascota(self, wd, x, y, w, h, esc):
        estado = self.estado_extendido()
        self._tarjeta_simple(x, y, w, h, wd)
        self._mascota_franja(x, y, w, h, esc, estado)

    def _imagen_mascota(self, lado):
        """Imagen propia de la mascota (Database/mascotas/*). None si no hay o no se puede."""
        try:
            from core.rutas import DATABASE
            carpeta = os.path.join(DATABASE, "mascotas")
            if not os.path.isdir(carpeta):
                return None
            archivos = sorted(f for f in os.listdir(carpeta) if f.lower().endswith((".png", ".gif", ".jpg", ".jpeg")))
            if not archivos:
                return None
            clave = (archivos[0], lado)
            if self._img_masc and self._img_masc[0] == clave:
                return self._img_masc[1]
            from PIL import Image, ImageTk
            im = Image.open(os.path.join(carpeta, archivos[0])).convert("RGBA")
            im.thumbnail((lado, lado))
            foto = ImageTk.PhotoImage(im)
            self._img_masc = (clave, foto)
            return foto
        except Exception:
            return None

    def _dibujar_personaje(self, mx, my, s, personaje, estado, mirar):
        c = self.canvas
        tags = (self._tag, "masc")
        if personaje == "esfera":
            orbe.dibujar(c, mx, my, s * 1.1, ESTADO_BASE.get(self.estado_extendido(), "reposo"), self.nivel, self.fase, self._tag, None, True)
        elif personaje == "minimal":
            col = tema.MORADO_CLARO
            c.create_oval(mx - s, my - s, mx + s, my + s, fill=tema.mezclar(tema.PANEL, col, 0.35), outline=col, width=2, tags=tags)
            for dx in (-0.35, 0.35):
                c.create_oval(mx + s * dx - s * 0.12, my - s * 0.2 - s * 0.12, mx + s * dx + s * 0.12, my - s * 0.2 + s * 0.12, fill=tema.TEXTO, outline="", tags=tags)
            c.create_arc(mx - s * 0.4, my - s * 0.1, mx + s * 0.4, my + s * 0.5, start=200, extent=140, style="arc", outline=tema.TEXTO, width=2, tags=tags)
        elif personaje == "imagen":
            foto = self._imagen_mascota(int(s * 2.6))
            if foto is not None:
                c.create_image(mx, my, image=foto, tags=tags)
            else:
                self._una_vez("sin_imagen_mascota", "pon una imagen en Database/mascotas")
                self.mascota.dibujar(c, mx, my, s, "chispa", estado, self.fase, mirar, self.nivel, tags)
        else:
            self.mascota.dibujar(c, mx, my, s, personaje, estado, self.fase, mirar, self.nivel, tags)
        op = ajustes.obtener("mascota_opacidad")
        if op < 98:
            stip = "gray75" if op >= 70 else ("gray50" if op >= 40 else "gray25")
            for iid in c.find_withtag("masc"):
                if c.type(iid) in ("polygon", "oval", "rectangle"):
                    try:
                        c.itemconfigure(iid, stipple=stip)
                    except Exception:
                        pass
        c.dtag("masc", "masc")

    def _mascota_franja(self, x, y, w, h, esc, estado, ambiente=False):
        """Mascota (izquierda) y su globo de texto o la intencion en vivo (derecha)."""
        c = self.canvas
        A = ajustes.obtener
        ahora = time.time()
        quiere = A("mascota") and (A("mascota_visibilidad") == "siempre" or ahora < self._masc_hasta or self.mascota.paso is not None)
        nombre = A("mascota_nombre")
        s = (30 if ambiente else 22) * esc * A("mascota_tamano") / 100.0
        s = max(8, min(s, (h - 10 * esc) / 2.7, w / 8))
        mx, my = x + s * 1.9, y + h - s * 1.5
        bx0 = x + s * 3.9 if quiere else x + 16 * esc
        if quiere:
            dx, dy = self.mouse[0] - mx, self.mouse[1] - my
            dist = max(1.0, math.hypot(dx, dy))
            f = min(1.0, dist / 180.0)
            self._dibujar_personaje(mx, my, s, A("mascota_personaje"), self._estado_mascota(), (dx / dist * f, dy / dist * f))
            self.zonas.append((mx - s * 1.3, my - s * 1.6, mx + s * 1.3, my + s * 1.3, ("mascota",)))
        ancho_t = x + w - 14 * esc - bx0
        if ancho_t < 40 * esc:
            return
        if quiere and self.mascota.hay_mensaje():
            texto = self.mascota.mensaje
            chars = max(12, int((ancho_t - 24 * esc) / (10 * esc * 0.62)))
            lineas = textwrap.wrap(texto, chars)[:3]
            tour = self.mascota.paso is not None
            alto_b = min(h - 8 * esc, (len(lineas) * 15 + 16 + (24 if tour else 0)) * esc)
            by1 = y + h - 8 * esc
            by0 = by1 - alto_b
            self._redondo(bx0, by0, x + w - 14 * esc, by1, 12 * esc, fill=tema.mezclar(tema.PANEL_2, tema.MORADO_CLARO, 0.12), outline=tema.MORADO_CLARO)
            c.create_polygon(bx0 + 1, by1 - 22 * esc, bx0 - 10 * esc, by1 - 14 * esc, bx0 + 1, by1 - 8 * esc,
                             fill=tema.mezclar(tema.PANEL_2, tema.MORADO_CLARO, 0.12), outline="", tags=self._tag)
            for i, l in enumerate(lineas):
                self._texto(bx0 + 12 * esc, by0 + (10 + 15 * i) * esc + 7 * esc, l, 10, tema.TEXTO)
            if tour:
                yb = by1 - 6 * esc
                sig = self._chip(x + w - 14 * esc - 92 * esc, yb - 22 * esc, "Siguiente ▸", ("tour", "sig"), True, tema.AZUL_CLARO, 84 * esc)
                self._chip(sig - 160 * esc, yb - 22 * esc, "Saltar", ("tour", "saltar"), False, None, 60 * esc)
        elif A("intencion_en_vivo") and en_vivo.intenciones:
            i = en_vivo.intenciones[-1]
            edad = ahora - i["ts"]
            if edad < 90:
                col = tema.mezclar(tema.MORADO_CLARO, tema.TENUE, min(1.0, edad / 90))
                yy = y + h - 22 * esc
                self._texto(bx0, yy - 16 * esc, "ENTENDÍ", 7, tema.TENUE)
                self._texto(bx0, yy, f"{i['intencion']}"[:max(6, int(ancho_t / (11 * esc * 0.6)))], 11, col, negrita=True)
                via = f"{i['via']} · {i['seg']}s" if i["via"] else f"{i['seg']}s"
                self._texto(x + w - 14 * esc, yy, via, 8, tema.TENUE, ancla="e")
                prev = [p["intencion"] for p in list(en_vivo.intenciones)[-4:-1]]
                if prev:
                    self._texto(x + w - 14 * esc, yy - 16 * esc, "  ›  ".join(prev)[-34:], 8, tema.mezclar(tema.TENUE, tema.PANEL, 0.4), ancla="e")

    # ---------------- widget: conversacion ----------------
    def _w_chat(self, wd, x, y, w, h, esc):
        c = self.canvas
        A = ajustes.obtener
        col = wd.get("color") or tema.AZUL_CLARO
        self._tarjeta(x, y, w, h, wd.get("titulo") or "CONVERSACIÓN", col)
        alto_in = max(24, min(A("chat_entrada_alto"), h * 0.5 / esc)) * esc
        arriba = A("chat_entrada_arriba")
        ex0, ex1 = x + 14 * esc, x + w - 14 * esc
        if arriba:
            ey0 = y + 36 * esc
            ey1 = ey0 + alto_in
            tope_y, fondo_y = ey1 + 10 * esc, y + h - 10 * esc
        else:
            ey1 = y + h - 12 * esc
            ey0 = ey1 - alto_in
            tope_y, fondo_y = y + 40 * esc, ey0 - 8 * esc
        self._redondo(ex0, ey0, ex1, ey1, 10 * esc, fill=tema.PANEL_2, outline=tema.BORDE)
        self.regiones["caja"] = (ex0, ey0, ex1, ey1)
        alto_e = max(18, int(min(alto_in - 8 * esc, 34 * esc)))
        c.coords(self.entry_id, ex0 + 12 * esc, ey0 + (alto_in - alto_e) / 2)
        c.itemconfigure(self.entry_id, width=max(60, int(ex1 - ex0 - 24 * esc)), height=alto_e, state="normal")
        t_esc = A("texto_escala") / 100.0
        self.entry.configure(font=(self._fuente, max(9, int(11 * esc * t_esc))), highlightthickness=0, bd=0)
        c.tag_raise(self.entry_id)
        try:
            con_foco = self.root.focus_get() is self.entry
        except Exception:
            con_foco = False
        if not self.entry.get() and not con_foco:
            self._texto(ex0 + 14 * esc, (ey0 + ey1) / 2, "Escríbele a Arché aquí…  (Enter envía, ↑ repite)", 10, tema.TENUE)
        vista = A("chat_vista")
        tam = A("chat_tam") if vista != "compacta" else max(8, A("chat_tam") - 1)
        ancho_col = (w - 40 * esc) * A("chat_ancho") / 100.0
        alin = A("chat_alineacion")
        mono = vista == "tecnica"
        factor = 0.62 if mono else 0.72
        chars = max(14, int(ancho_col / (tam * esc * t_esc * factor)))
        linea_h = tam * esc * t_esc * (1.35 if vista == "compacta" else 1.55)
        sep = (A("chat_espacio") if vista != "compacta" else min(3, A("chat_espacio"))) * esc
        izq = x + 20 * esc
        der = x + w - 20 * esc
        y_actual = fondo_y
        pensando = A("chat_indicador") and en_vivo.esta_pensando()
        if pensando:
            pts = "." * (1 + int(time.time() * 2) % 3)
            self._texto(izq, y_actual - linea_h / 2, "Arché está pensando" + pts, tam - 1, tema.MORADO_CLARO)
            y_actual -= linea_h + 4 * esc
        mensajes = list(en_vivo.chat)[-int(A("chat_historial")):]
        if not mensajes:
            self._texto(izq, tope_y + 8 * esc, "Aquí verás lo que hablamos.", 11, tema.TENUE)
            return
        for idx in range(len(mensajes) - 1, -1, -1):
            msg = mensajes[idx]
            es_tu = msg["q"] == "tu"
            marca = time.strftime("%H:%M:%S ", time.localtime(msg["ts"])) if (A("chat_marcas_tiempo") or mono) and msg.get("ts") else ""
            if mono:
                texto = marca + ("tú> " if es_tu else "arche> ") + msg["t"]
            else:
                texto = marca + (("› " if es_tu else "") + msg["t"])
            nuevo = idx >= len(mensajes) - 2
            maxl = 4 if nuevo or vista == "tecnica" else (1 if vista == "compacta" else 2)
            lineas = textwrap.wrap(texto, chars)[:maxl] or [""]
            if len(textwrap.wrap(texto, chars)) > maxl:
                lineas[-1] = lineas[-1].rstrip(" .,") + "…"
            alto_msg = len(lineas) * linea_h
            if y_actual - alto_msg < tope_y:
                break
            propio = A("chat_color_usuario") if es_tu else A("chat_color_arche")
            base = propio or (tema.AZUL_CLARO if es_tu else tema.TEXTO)
            color = base if nuevo else tema.mezclar(tema.TENUE, tema.PANEL, 0.25)
            yy = y_actual - alto_msg
            derecha = alin == "derecha" or (alin == "alternada" and es_tu)
            px = der if derecha else izq
            if msg["q"] == "arche" and nuevo and not derecha:
                self._linea((px - 10 * esc, yy + 2, px - 10 * esc, y_actual - 2), tema.MORADO_CLARO, 3)
            for linea in lineas:
                self._texto(px, yy + linea_h / 2, linea, tam, color, ancla="e" if derecha else "w", mono=mono)
                yy += linea_h
            y_actual -= alto_msg + sep

    # ---------------- widget: panel de pestañas ----------------
    def _w_panel(self, wd, x, y, w, h, esc):
        c = self.canvas
        A = ajustes.obtener
        self._tarjeta_simple(x, y, w, h, wd)
        self.regiones["derecha"] = (x, y, x + w, y + h)
        tabs = self.pestanas_ordenadas()
        if self.pestana not in [t[0] for t in tabs]:
            self.pestana = tabs[0][0] if tabs else "ajustes"
        nav = A("navegacion")
        tam_i = A("nav_iconos_tam") / 100.0
        etiquetas = A("nav_etiquetas")
        cx, cy, cw, ch = x, y, w, h
        if nav == "pestanas":
            tx = x + 16 * esc
            for clave, nombre, ccol in tabs:
                color = getattr(tema, ccol)
                activa = self.pestana == clave
                ancho_t = (len(nombre) * 7.4 + 6) * esc
                tc = color if activa else (tema.mezclar(tema.TENUE, color, 0.35) if self.hover == ("pestana", clave) else tema.TENUE)
                self._texto(tx, y + 22 * esc, nombre, 9, tc, negrita=activa)
                if activa:
                    c.create_line(tx, y + 34 * esc, tx + ancho_t - 6 * esc, y + 34 * esc, fill=color, width=2, tags=self._tag)
                self.zonas.append((tx - 4, y + 8 * esc, tx + ancho_t, y + 38 * esc, ("pestana", clave)))
                tx += ancho_t + 9 * esc
            c.create_line(x + 12 * esc, y + 36 * esc, x + w - 12 * esc, y + 36 * esc, fill=tema.BORDE, tags=self._tag)
            cy, ch = y + 40 * esc, h - 40 * esc
        elif nav == "iconos":
            lado = 30 * esc * tam_i
            alto_f = lado + (14 * esc if etiquetas else 0) + 14 * esc
            tx = x + 14 * esc
            for clave, nombre, ccol in tabs:
                color = getattr(tema, ccol)
                activa = self.pestana == clave
                self._redondo(tx, y + 8 * esc, tx + lado, y + 8 * esc + lado, lado / 3, fill=tema.mezclar(tema.BOTON, color, 0.5 if activa else 0.0),
                              outline=color if activa else tema.BORDE)
                self._texto(tx + lado / 2, y + 8 * esc + lado / 2, centro.ICONOS_PESTANA.get(clave, "•"), 12 * tam_i, tema.TEXTO if activa else tema.TENUE, ancla="center")
                if etiquetas:
                    self._texto(tx + lado / 2, y + 12 * esc + lado + 4 * esc, nombre[:8].lower(), 7, color if activa else tema.TENUE, ancla="center")
                self.zonas.append((tx, y + 8 * esc, tx + lado, y + alto_f, ("pestana", clave)))
                tx += lado + 8 * esc
            c.create_line(x + 12 * esc, y + alto_f, x + w - 12 * esc, y + alto_f, fill=tema.BORDE, tags=self._tag)
            cy, ch = y + alto_f + 4 * esc, h - alto_f - 4 * esc
        elif nav == "lateral":
            lado = 30 * esc * tam_i
            ancho_b = lado + (62 * esc if etiquetas else 0) + 14 * esc
            ty = y + 12 * esc
            for clave, nombre, ccol in tabs:
                color = getattr(tema, ccol)
                activa = self.pestana == clave
                self._redondo(x + 8 * esc, ty, x + ancho_b - 6 * esc, ty + lado, lado / 3, fill=tema.mezclar(tema.BOTON, color, 0.45 if activa else 0.0),
                              outline=color if activa else tema.BORDE)
                self._texto(x + 8 * esc + lado / 2, ty + lado / 2, centro.ICONOS_PESTANA.get(clave, "•"), 12 * tam_i, tema.TEXTO if activa else tema.TENUE, ancla="center")
                if etiquetas:
                    self._texto(x + 12 * esc + lado, ty + lado / 2, nombre[:9].title(), 8, tema.TEXTO if activa else tema.TENUE, negrita=activa)
                self.zonas.append((x + 8 * esc, ty, x + ancho_b - 6 * esc, ty + lado, ("pestana", clave)))
                ty += lado + 6 * esc
            c.create_line(x + ancho_b, y + 10 * esc, x + ancho_b, y + h - 10 * esc, fill=tema.BORDE, tags=self._tag)
            cx, cw = x + ancho_b, w - ancho_b
        else:  # menu desplegable
            nombre_act = next((n for k, n, _c in tabs if k == self.pestana), "")
            self._texto(x + 16 * esc, y + 22 * esc, "☰  " + nombre_act, 9, tema.SELECCION, negrita=True)
            self.zonas.append((x + 8 * esc, y + 8 * esc, x + w - 8 * esc, y + 38 * esc, ("menu_nav",)))
            c.create_line(x + 12 * esc, y + 36 * esc, x + w - 12 * esc, y + 36 * esc, fill=tema.BORDE, tags=self._tag)
            cy, ch = y + 40 * esc, h - 40 * esc
        constructor = {"controles": self._bloques_controles, "ajustes": self._bloques_centro,
                       "hoy": self._bloques_hoy, "aprende": self._bloques_aprende}[self.pestana]
        self._pintar_bloques(cx, cy, cw, ch, constructor(esc), esc)
        if nav == "menu" and self.menu_nav:
            yy = y + 40 * esc
            fila = 26 * esc
            self._redondo(x + 10 * esc, yy, x + w - 10 * esc, yy + fila * len(tabs) + 8 * esc, 10 * esc, fill=tema.PANEL_2, outline=tema.SELECCION)
            for clave, nombre, ccol in tabs:
                self._texto(x + 24 * esc, yy + fila / 2 + 4 * esc, centro.ICONOS_PESTANA.get(clave, "•") + "  " + nombre, 9,
                            tema.TEXTO if clave == self.pestana else tema.TENUE, negrita=clave == self.pestana)
                self.zonas.append((x + 10 * esc, yy, x + w - 10 * esc, yy + fila, ("pestana", clave)))
                yy += fila

    def _pintar_bloques(self, x, y, w, h, bloques, esc):
        """Dibuja una lista de (alto, funcion(px, yy, bw)) con desplazamiento con la rueda del mouse."""
        px, bw = x + 18 * esc, w - 36 * esc
        self.centro_bw = bw
        total = sum(b[0] for b in bloques) + 24 * esc
        maxs = max(0, total - h)
        off = min(self.scroll.get(self.pestana, 0), maxs)
        self.scroll[self.pestana] = off
        self._scroll_reg[self.pestana] = (x, y, x + w, y + h)
        yy = y + 8 * esc - off
        for alto, fn in bloques:
            if yy >= y - 1 and yy + alto <= y + h - 14 * esc:
                fn(px, yy, bw)
            yy += alto
        if maxs > 0:
            self._texto(x + w - 14 * esc, y + h - 10 * esc, "rueda del mouse ▾" if off < maxs else "▴", 7, tema.TENUE, ancla="e")

    def _bloques_centro(self, esc):
        """PERSONALIZA: buscador, categorias y los ajustes de la categoria (todo en vivo)."""
        c = self.canvas

        def buscador(px, yy, bw):
            c.coords(self.busca_id, px, yy + 2 * esc)
            c.itemconfigure(self.busca_id, width=int(bw), height=max(20, int(24 * esc)), state="normal")
            c.tag_raise(self.busca_id)
            try:
                foco = self.root.focus_get() is self.busca
            except Exception:
                foco = False
            if not self.busca.get() and not foco:
                self._texto(px + 8 * esc, yy + 14 * esc, "Buscar un ajuste…", 9, tema.TENUE)

        def _cols_cat(bw):
            mayor = max(len(n) for _c, n in centro.CATEGORIAS) * 6.6 + 20
            return max(2, min(3, int((bw + 6 * esc) // ((mayor + 6) * esc))))

        def fila_categorias(f):
            def dibujar(px, yy, bw):
                # cuadricula pareja: todas las categorias del mismo ancho, en columnas
                cols = _cols_cat(bw)
                hueco = 6 * esc
                ancho = (bw - hueco * (cols - 1)) / cols
                for col in range(cols):
                    i = f * cols + col
                    if i >= len(centro.CATEGORIAS):
                        break
                    clave, nombre = centro.CATEGORIAS[i]
                    self._chip(px + col * (ancho + hueco), yy, nombre, ("cat", clave),
                               clave == self.centro_cat and not self.centro_busqueda.strip(), tema.MORADO_CLARO, ancho)
            return dibujar

        cols = _cols_cat(getattr(self, "centro_bw", 280))
        filas = -(-len(centro.CATEGORIAS) // cols)
        # una fila por bloque: al desplazar con la rueda, cada fila entra y sale sola (un bloque grande desaparece entero)
        bloques = [(32 * esc, buscador)] + [(30 * esc, fila_categorias(f)) for f in range(filas)] + [(14 * esc, lambda px, yy, bw: None)]
        bloques += centro.construir(self, esc, self.centro_cat, self.centro_busqueda)
        return bloques

    def _barra(self, x, y, w, etiqueta, valor, color, texto=None):
        esc = self._esc()
        h = max(6, int(8 * esc))
        self._texto(x, y, etiqueta, 10, tema.TENUE)
        self._texto(x + w, y, texto if texto is not None else f"{valor:.0f}%", 10, tema.TEXTO, ancla="e")
        yb = y + 20 * esc
        self._linea((x + h / 2, yb, x + w - h / 2, yb), tema.PANEL_2, h)
        v = max(0.0, min(1.0, valor / 100.0))
        fin = x + h / 2 + (w - h) * v
        self._linea((x + h / 2, yb, max(fin, x + h / 2 + 0.1), yb), color, h)
        return y + 44 * esc

    def _grafica(self, x, y, w, h, series):
        c = self.canvas
        for k in range(1, 4):
            yy = y + h * k / 4
            c.create_line(x, yy, x + w, yy, fill=tema.mezclar(tema.PANEL, tema.BORDE, 0.6), tags=self._tag)
        for valores, color in series:
            if len(valores) < 2:
                continue
            n = len(valores)
            pts = []
            for i, v in enumerate(valores):
                pts += [x + w * i / (MUESTRAS - 1) + w * (MUESTRAS - n) / (MUESTRAS - 1),
                        y + h - h * max(0.0, min(100.0, v)) / 100.0]
            self._linea(pts, color, max(2, int(2 * self._esc())), suave=True)

    def _boton(self, x1, y1, texto, accion, color):
        """Boton clicable anclado por su esquina inferior derecha (x1, y1)."""
        esc = self._esc()
        ancho = (len(texto) * 7.2 + 28) * esc
        alto = 26 * esc
        x0, y0 = x1 - ancho, y1 - alto
        sobre = self.hover == accion
        self._redondo(x0, y0, x1, y1, 13 * esc, fill=tema.mezclar(tema.BOTON, color, 0.45 if sobre else 0.15),
                      outline=color if sobre else tema.BORDE)
        self._texto((x0 + x1) / 2, (y0 + y1) / 2, texto, 9, tema.TEXTO, ancla="center")
        self.zonas.append((x0, y0, x1, y1, accion))
        return x0 - 8 * esc

    def _chip(self, x, y, texto, accion, activo, color=None, ancho=None):
        """Pastilla de opcion. (x, y) = esquina superior izquierda. Devuelve el x del borde derecho."""
        esc = self._esc()
        color = color or tema.MORADO_CLARO
        w = ancho or (len(texto) * 6.6 + 20) * esc
        h = 22 * esc
        pasa = self.hover == accion
        self._redondo(x, y, x + w, y + h, 11 * esc,
                      fill=tema.mezclar(tema.BOTON, color, 0.75 if activo else (0.25 if pasa else 0.0)),
                      outline=color if activo else tema.BORDE)
        self._texto(x + w / 2, y + h / 2, texto, 9, tema.TEXTO if activo else tema.TENUE, ancla="center",
                    negrita=activo)
        self.zonas.append((x, y, x + w, y + h, accion))
        return x + w

    def _valor_mostrado(self, ctl):
        pend = self.pendiente.get(ctl["id"])
        if pend:
            esperado, hasta = pend
            if ctl["valor"] == esperado:
                self.pendiente.pop(ctl["id"], None)
                self.mascota.celebrar(1.4)
                sonido.tocar("activar" if esperado not in (False, "apagada") else "apagar")
            elif time.time() > hasta:
                self.pendiente.pop(ctl["id"], None)
            else:
                return esperado, True
        return ctl["valor"], False

    def _bloques_controles(self, esc):
        controles = self.snap.get("controles", [])
        if not controles:
            return [(30 * esc, lambda px, yy, bw: self._texto(px, yy + 10 * esc, "Cargando controles…", 10, tema.TENUE))]
        bloques = []
        for ctl in controles:
            alto = 46 * esc if ctl["tipo"] == "switch" else 72 * esc
            bloques.append((alto, lambda px, yy, bw, ctl=ctl, alto=alto: self._fila_control(px, yy, bw, ctl, alto, esc)))
        bloques.append((20 * esc, lambda px, yy, bw: self._texto(px, yy + 6 * esc, "Toca para activar o apagar · se ve en vivo", 8, tema.TENUE)))
        return bloques

    def _fila_control(self, px, yy, bw, ctl, alto, esc):
        c = self.canvas
        pulso = 0.5 + 0.5 * math.sin(self.fase * 2.2)
        valor, aplicando = self._valor_mostrado(ctl)
        encendido = bool(valor) if ctl["tipo"] == "switch" else valor not in ("apagada", None)
        if ctl.get("trabajando"):
            col_p = tema.mezclar(tema.PANEL, tema.MORADO_CLARO, 0.5 + 0.5 * pulso)
        else:
            col_p = tema.OK if encendido else tema.mezclar(tema.PANEL, tema.TENUE, 0.6)
        r = 4 * esc
        c.create_oval(px, yy + 8 * esc - r, px + 2 * r, yy + 8 * esc + r, fill=col_p, outline="", tags=self._tag)
        self._texto(px + 16 * esc, yy + 8 * esc, ctl["nombre"], 10, tema.TEXTO if encendido else tema.TENUE, negrita=encendido)
        detalle = "aplicando…" if aplicando else (ctl["detalle"] or "")
        maxc = int((bw - 70 * esc) / (8 * esc * 0.6))
        self._texto(px + 16 * esc, yy + 24 * esc, detalle[:maxc], 8, tema.MORADO_CLARO if aplicando else tema.TENUE)
        if ctl["tipo"] == "switch":
            accion = ("cmd", ctl["off"] if encendido else ctl["on"], ctl["id"], not encendido)
            self._interruptor(px + bw, yy + 14 * esc, encendido, accion, esc)
            self.zonas.append((px, yy, px + bw, yy + alto - 4 * esc, accion))
        else:
            n = len(ctl["niveles"])
            gap = 6 * esc
            pw = (bw - gap * (n - 1)) / n
            for i, (nivel, orden) in enumerate(ctl["niveles"]):
                self._chip(px + i * (pw + gap), yy + 38 * esc, nivel, ("cmd", orden, ctl["id"], nivel), valor == nivel,
                           None, pw)
        c.create_line(px, yy + alto - 3 * esc, px + bw, yy + alto - 3 * esc,
                      fill=tema.mezclar(tema.PANEL, tema.BORDE, 0.5), tags=self._tag)

    def _interruptor(self, x1, cy, encendido, accion, esc):
        c = self.canvas
        tw, th = 38 * esc, 18 * esc
        tx0 = x1 - tw
        pasa = self.hover == accion
        col_t = self._interruptor_color(encendido, pasa)
        self._linea((tx0 + th / 2, cy, x1 - th / 2, cy), col_t, th)
        kx = (x1 - th / 2) if encendido else (tx0 + th / 2)
        kr = th / 2 - 3 * esc
        c.create_oval(kx - kr, cy - kr, kx + kr, cy + kr, fill=tema.TEXTO if encendido else tema.TENUE,
                      outline="", tags=self._tag)

    def _bloques_hoy(self, esc):
        bloques = []
        hoy = self.snap.get("hoy", {})

        def cab(txt, color):
            bloques.append((26 * esc, lambda px, yy, bw: self._texto(px, yy + 12 * esc, txt, 8, color, negrita=True)))

        def linea(txt, color=None, sub=None, alto=22):
            def f(px, yy, bw):
                maxc = int(bw / (9 * esc * 0.6))
                self._texto(px, yy + 9 * esc, txt[:maxc], 9, color or tema.TEXTO)
                if sub:
                    self._texto(px + bw, yy + 9 * esc, sub, 8, tema.TENUE, ancla="e")
            bloques.append((alto * esc, f))

        def grande(px, yy, bw):
            self._texto(px, yy + 16 * esc, str(en_vivo.ordenes), 26, tema.TEXTO, negrita=True)
            self._texto(px + 62 * esc, yy + 14 * esc, "órdenes en esta sesión", 9, tema.TENUE)
            self._texto(px + 62 * esc, yy + 28 * esc,
                        f"última hace {int(en_vivo.segundos_sin_actividad())} s" if en_vivo.ordenes else "aún sin órdenes", 8, tema.TENUE)
        bloques.append((46 * esc, grande))
        cab("LO QUE ENTENDÍ", tema.MORADO_CLARO)
        ints = list(en_vivo.intenciones)[-5:][::-1]
        if ints:
            for i in ints:
                linea(f"{i['intencion']}", tema.TEXTO, f"{i['via']}"[:14])
        else:
            linea("Nada todavía: escríbeme algo.", tema.TENUE)
        cab("LO QUE MEJORÉ SOLA", tema.AZUL_CLARO)
        mej = hoy.get("mejora", [])
        if mej:
            for t, txt in mej[::-1]:
                try:
                    hora = time.strftime("%d/%m %H:%M", time.localtime(t))
                except Exception:
                    hora = ""
                linea(txt, tema.TEXTO, hora)
        else:
            linea("Aún nada (trabajo cuando no me usas).", tema.TENUE)
        cab("PRÓXIMAS ALARMAS", tema.ROJO_CLARO)
        al = hoy.get("alarmas", [])
        if al:
            for cuando, txt in al:
                linea(txt or "aviso", tema.TEXTO, str(cuando)[5:16])
        else:
            linea("Sin alarmas pendientes.", tema.TENUE)
        return bloques

    def _bloques_aprende(self, esc):
        ex = self.snap.get("examen", {})
        doms = ex.get("dominios", [])
        listos = ex.get("listos", 0)
        umbral = max(1, ex.get("umbral", 4))
        bloques = []

        def cab(px, yy, bw):
            self._texto(px, yy + 10 * esc, f"Nivel {ex.get('nivel', 0)}", 15, tema.TEXTO, negrita=True)
            self._texto(px + bw, yy + 10 * esc, f"{listos}/{len(doms)} listos", 10, tema.MORADO_CLARO, ancla="e")
            h_b = max(6, int(8 * esc))
            yb = yy + 34 * esc
            self._linea((px + h_b / 2, yb, px + bw - h_b / 2, yb), tema.PANEL_2, h_b)
            if doms and listos:
                self._linea((px + h_b / 2, yb, px + h_b / 2 + (bw - h_b) * listos / len(doms), yb), tema.SELECCION, h_b)
        bloques.append((50 * esc, cab))
        if not doms:
            bloques.append((24 * esc, lambda px, yy, bw: self._texto(px, yy + 8 * esc, "Aún sin datos del examen", 10, tema.TENUE)))
        for dom in doms:
            def fila(px, yy, bw, dom=dom):
                pct = 1.0 if dom["listo"] else min(1.0, dom["racha"] / umbral)
                color = tema.AZUL_CLARO if dom["listo"] else (tema.MORADO_CLARO if dom["racha"] else tema.ROJO_CLARO)
                self._texto(px, yy + 10 * esc, dom["nombre"][:13], 9, tema.TEXTO if dom["listo"] else tema.TENUE)
                bx0, bx1 = px + 100 * esc, px + bw - 34 * esc
                hb = max(5, int(6 * esc))
                self._linea((bx0 + hb / 2, yy + 10 * esc, bx1 - hb / 2, yy + 10 * esc), tema.PANEL_2, hb)
                if pct > 0:
                    self._linea((bx0 + hb / 2, yy + 10 * esc, bx0 + hb / 2 + (bx1 - bx0 - hb) * pct, yy + 10 * esc), color, hb)
                self._texto(px + bw, yy + 10 * esc, "listo" if dom["listo"] else f"{dom['racha']}/{umbral}", 8,
                            tema.AZUL_CLARO if dom["listo"] else tema.TENUE, ancla="e")
            bloques.append((26 * esc, fila))
        return bloques

    # ---------------- avisos, confirmaciones y capas encima ----------------
    def _toasts(self, W, m, esc):
        A = ajustes.obtener
        abajo = A("notif_posicion") == "abajo"
        y = (self.alto - m - 50 * esc) if abajo else (m + 60 * esc)
        paso = -38 * esc if abajo else 38 * esc
        dur = max(2, int(A("notif_segundos")))
        for t in self.toasts:
            edad = time.time() - t["ts"]
            col = {"exito": tema.AZUL_CLARO, "error": tema.ROJO_CLARO}.get(t["tipo"], tema.MORADO_CLARO)
            simbolo = {"exito": "✓ ", "error": "! "}.get(t["tipo"], "")        # no depende solo del color
            txt = (simbolo + t["texto"])[:90]
            w = (len(txt) * 6.8 + 44) * esc
            x0 = W / 2 - w / 2
            fade = max(0.0, min(1.0, dur - edad, edad / 0.25 + 0.2))
            self._redondo(x0, y, x0 + w, y + 30 * esc, 15 * esc, fill=tema.mezclar(tema.FONDO, tema.PANEL_2, fade),
                          outline=tema.mezclar(tema.FONDO, col, fade))
            self.canvas.create_oval(x0 + 12 * esc, y + 11 * esc, x0 + 20 * esc, y + 19 * esc,
                                    fill=tema.mezclar(tema.FONDO, col, fade), outline="", tags=self._tag)
            self._texto(x0 + 28 * esc, y + 15 * esc, txt, 10, tema.mezclar(tema.FONDO, tema.TEXTO, fade))
            y += paso
        p = lenguaje.hay_pendiente()
        if p and not self.editando:
            cuerpo = "; ".join(p["resumen"][:3])[:110]
            ancho = min(W - 2 * m, 560 * esc)
            x0 = W / 2 - ancho / 2
            y0 = self.alto - m - 96 * esc if not abajo else m + 60 * esc
            self._redondo(x0, y0, x0 + ancho, y0 + 62 * esc, 14 * esc, fill=tema.PANEL_2, outline=tema.ATENCION, width=2)
            self._texto(x0 + 16 * esc, y0 + 18 * esc, "¿Aplico estos cambios?", 10, tema.ATENCION, negrita=True)
            self._texto(x0 + 16 * esc, y0 + 40 * esc, cuerpo or "cambios de la interfaz", 9, tema.TEXTO)
            bx = x0 + ancho - 14 * esc
            bx = self._boton(bx, y0 + 26 * esc, "Aplicar", ("confirmar",), tema.AZUL_CLARO)
            self._boton(bx, y0 + 26 * esc, "Cancelar", ("cancelar",), tema.ROJO_CLARO)

    def _recorrido_resalte(self, esc):
        paso = self.mascota.paso
        if paso is None:
            return
        reg = self.regiones.get(mascota_mod.RECORRIDO[paso][1] or "")
        if reg:
            pulso = 0.5 + 0.5 * math.sin(self.fase * 3)
            self._redondo(reg[0] - 3, reg[1] - 3, reg[2] + 3, reg[3] + 3, 16 * esc, fill="",
                          outline=tema.mezclar(tema.MORADO, tema.MORADO_CLARO, pulso), width=3)

    def _overlay_progreso(self, W, H, esc, lay):
        """Si lo permitiste (ctx_progreso): un panel de progreso temporal mientras hay una tarea larga. No cambia tu diseño."""
        if not ajustes.obtener("ctx_progreso") or any(w["tipo"] == "progreso" and w["visible"] for w in lay["widgets"]):
            return
        activos = [p for p in self.snap.get("procesos", []) if p["activo"] and p["nombre"] not in ("Voz natural",)]
        if not activos and not self.snap.get("examen", {}).get("automatico"):
            return
        ancho, alto = min(W * 0.4, 320 * esc), 86 * esc
        wd = {"id": "_progreso", "tipo": "progreso", "opacidad": 95, "color": "", "titulo": "", "nivel": "normal", "opts": {}}
        self._wd = wd
        try:
            widgets.w_progreso(self, wd, W - ancho - 20 * esc, H - alto - 60 * esc, ancho, alto, esc)
        finally:
            self._wd = None

    def _anillo_teclado(self, esc):
        if self.kb < 0 or not ajustes.obtener("teclado_nav") or self.editando or self.bus_activo:
            return
        zs = self._zonas_teclado()
        if not zs:
            return
        x0, y0, x1, y1, _a = zs[self.kb % len(zs)]
        self._redondo(x0 - 3, y0 - 3, x1 + 3, y1 + 3, 8 * esc, fill="", outline=tema.TEXTO, width=2)

    def _dibujar_buscador(self, W, H, esc):
        """La barra de comandos (Ctrl+Espacio): un cuadro arriba y los resultados debajo."""
        c = self.canvas
        ancho = min(W - 40, 580 * esc)
        x0 = W / 2 - ancho / 2
        y0 = H * 0.14
        n = len(self.bus_res)
        alto = (56 + 34 * max(1, n) + 12) * esc
        c.create_rectangle(0, 0, W, H, fill=tema.FONDO, stipple="gray50", outline="", tags=self._tag)
        self._redondo(x0 - 4, y0 - 4, x0 + ancho + 4, y0 + alto + 4, 18 * esc, fill="", outline=tema.mezclar(tema.FONDO, tema.SELECCION, 0.4), width=3)
        self._redondo(x0, y0, x0 + ancho, y0 + alto, 16 * esc, fill=tema.PANEL, outline=tema.SELECCION, width=2)
        self._texto(x0 + 18 * esc, y0 + 22 * esc, "⌕", 14, tema.SELECCION)
        c.coords(self.bus_id, x0 + 44 * esc, y0 + 10 * esc)
        c.itemconfigure(self.bus_id, width=int(ancho - 64 * esc), height=int(26 * esc), state="normal")
        c.tag_raise(self.bus_id)
        yy = y0 + 52 * esc
        if not self.bus_res:
            self._texto(x0 + 20 * esc, yy + 14 * esc, "Sin coincidencias: Enter lo envía a Arché como orden.", 9, tema.TENUE)
        for i, r in enumerate(self.bus_res):
            sel = i == self.bus_sel
            if sel:
                self._redondo(x0 + 8 * esc, yy, x0 + ancho - 8 * esc, yy + 32 * esc, 10 * esc, fill=tema.mezclar(tema.PANEL_2, tema.SELECCION, 0.35), outline=tema.SELECCION)
            self._texto(x0 + 22 * esc, yy + 16 * esc, r["texto"][:int((ancho * 0.6) / (10 * esc * 0.6))], 10, tema.TEXTO if sel else tema.TENUE, negrita=sel)
            if r.get("detalle"):
                self._texto(x0 + ancho - 20 * esc, yy + 16 * esc, r["detalle"][:30], 8, tema.TENUE, ancla="e")
            self.zonas.append((x0 + 8 * esc, yy, x0 + ancho - 8 * esc, yy + 32 * esc, ("bus", i)))
            yy += 34 * esc
        self.zonas.append((0, 0, W, 0.0, None))

    # ---------------- modo ambiente ----------------
    def _modo_ambiente(self, W, H, m, esc, estado):
        c = self.canvas
        lt = time.localtime()
        self._texto(W / 2, H * 0.17, time.strftime("%H:%M", lt), 64, tema.TEXTO, ancla="center", negrita=True)
        self._texto(W / 2, H * 0.17 + 56 * esc, f"{DIAS[lt.tm_wday]} {lt.tm_mday}/{lt.tm_mon}/{lt.tm_year}", 14, tema.TENUE, ancla="center")
        self._dibujar_voz(m, H * 0.30, W - 2 * m, H * 0.42, estado, ESTADO_BASE.get(estado, "reposo"), esc, self._con_fondo())
        self._mascota_franja(m, int(H * 0.60), W - 2 * m, H * 0.38 - m, esc, estado, ambiente=True)
        ult = [mm for mm in en_vivo.chat if mm["q"] == "arche"]
        if ult:
            self._texto(W / 2, H * 0.80, ult[-1]["t"][:90], 13, tema.mezclar(tema.TEXTO, tema.TENUE, 0.4), ancla="center")
        self._texto(W / 2, H - m * 0.7, "toca la pantalla o pulsa una tecla para volver", 9, tema.TENUE, ancla="center")

    # ---------------- esfera flotante y bandeja ----------------
    def _sincronizar_extras(self):
        A = ajustes.obtener
        if A("flotante") and self.flotante is None:
            try:
                self.flotante = Flotante(self)
            except Exception as e:
                print(f"[interfaz] no pude abrir la esfera flotante: {e}")
                ajustes.fijar("flotante", False)
        elif not A("flotante") and self.flotante is not None:
            self.flotante.cerrar()
            self.flotante = None
        if self.flotante is not None:
            self.flotante.dibujar()
        if A("bandeja") and self._bandeja is None and not self._bandeja_aviso:
            self._iniciar_bandeja()
        elif not A("bandeja") and self._bandeja is not None:
            try:
                self._bandeja.stop()
            except Exception:
                pass
            self._bandeja = None
            self._bandeja_aviso = False
        # minimizar la ventana al usar otra app (solo si hay con que traerla de vuelta)
        if A("minimizar_sin_foco") and (self.flotante is not None or self._bandeja is not None) and not self.tv:
            try:
                tiene = self.root.focus_displayof() is not None
                if tiene:
                    self._sin_foco_desde = None
                elif self._sin_foco_desde is None:
                    self._sin_foco_desde = time.time()
                elif time.time() - self._sin_foco_desde > 2.0 and self.root.state() == "normal":
                    self.root.iconify()
            except Exception:
                pass

    def _iniciar_bandeja(self):
        """Icono en la bandeja del sistema (necesita pystray y Pillow; si faltan, lo digo y no insisto)."""
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            self._bandeja_aviso = True
            self.avisar("La bandeja necesita «pip install pystray pillow». Lo apagué hasta que lo instales.", "error")
            ajustes.fijar("bandeja", False)
            return
        try:
            im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.ellipse((6, 6, 58, 58), fill=tema.MORADO, outline=tema.AZUL_CLARO, width=4)
            d.ellipse((22, 22, 42, 42), fill=tema.AZUL_CLARO)
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar Arché", lambda *a: self.peticiones.append(("mostrar", None)), default=True),
                pystray.MenuItem("Esfera flotante", lambda *a: ajustes.alternar("flotante")),
                pystray.MenuItem("Cerrar la ventana", lambda *a: self.peticiones.append(("bandeja_salir", None))))
            self._bandeja = pystray.Icon("arche", im, "Arché", menu)
            self._bandeja.run_detached()
        except Exception as e:
            self._bandeja = None
            self._bandeja_aviso = True
            self.avisar(f"No pude abrir la bandeja ({e}).", "error")
            ajustes.fijar("bandeja", False)


class Flotante:
    """La esfera (o la mascota) en una ventanita sin borde que se queda sobre las demas apps."""

    def __init__(self, v):
        self.v = v
        self.top = tk.Toplevel(v.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.clave = "#010203"
        try:
            self.top.attributes("-transparentcolor", self.clave)
            fondo = self.clave
        except Exception:
            fondo = tema.FONDO               # sin transparencia real (Linux/Mac): queda un cuadro oscuro
        self.top.configure(bg=fondo)
        self.canvas = tk.Canvas(self.top, bg=fondo, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.tam = 0
        self._arr = None
        self._movio = False
        pos = ajustes.obtener("flotante_pos")
        self._poner_tam(int(ajustes.obtener("flotante_tam")), pos)
        self.canvas.bind("<ButtonPress-1>", self._pulsar)
        self.canvas.bind("<B1-Motion>", self._arrastrar)
        self.canvas.bind("<ButtonRelease-1>", self._soltar)
        self.canvas.bind("<Double-Button-1>", lambda e: v.mostrar_principal())
        self.canvas.bind("<Button-3>", lambda e: ajustes.fijar("flotante_contenido", "mascota" if ajustes.obtener("flotante_contenido") == "esfera" else "esfera"))

    def _poner_tam(self, tam, pos=""):
        self.tam = tam
        try:
            if pos and "," in pos:
                x, y = (int(p) for p in pos.split(",")[:2])
            else:
                x = self.top.winfo_screenwidth() - tam - 40
                y = self.top.winfo_screenheight() - tam - 100
            self.top.geometry(f"{tam}x{tam}+{x}+{y}")
        except Exception:
            self.top.geometry(f"{tam}x{tam}")

    def _pulsar(self, e):
        self._arr = (e.x_root - self.top.winfo_x(), e.y_root - self.top.winfo_y())
        self._movio = False

    def _arrastrar(self, e):
        if self._arr:
            self._movio = True
            self.top.geometry(f"+{e.x_root - self._arr[0]}+{e.y_root - self._arr[1]}")

    def _soltar(self, e):
        if self._movio:
            ajustes.fijar("flotante_pos", f"{self.top.winfo_x()},{self.top.winfo_y()}")
        self._arr = None

    def dibujar(self):
        v = self.v
        tam = int(ajustes.obtener("flotante_tam"))
        if tam != self.tam:
            self._poner_tam(tam, f"{self.top.winfo_x()},{self.top.winfo_y()}")
        c = self.canvas
        c.delete("all")
        estado = v.estado_extendido()
        base = ESTADO_BASE.get(estado, "reposo")
        if ajustes.obtener("flotante_contenido") == "mascota":
            antes = (v.canvas, v._tag)
            v.canvas, v._tag = c, "all"
            try:
                v._dibujar_personaje(tam / 2, tam / 2, tam * 0.26, ajustes.obtener("mascota_personaje"), v._estado_mascota(), (0, 0))
            finally:
                v.canvas, v._tag = antes
        else:
            r = tam * 0.27
            orbe.forzado = ajustes.normalizar_hex(ajustes.obtener("orbe_color")) if ajustes.obtener("orbe_color") else None
            try:
                orbe.dibujar(c, tam / 2, tam / 2, r, base, 0.0 if v._reducido() else v.nivel, v.fase, "all", None, True)
            finally:
                orbe.forzado = None
        nombre, col = v.etiqueta_estado(estado)
        c.create_text(tam / 2, tam - 10, text=nombre, fill=col, font=(tema.FUENTE, 8, "bold"))

    def cerrar(self):
        try:
            self.top.destroy()
        except Exception:
            pass


# ---------------- control desde fuera ----------------
def _correr(tv, foco):
    global _ventana
    try:
        _ventana = VentanaArche(tv=tv, foco=foco)
        _ventana.root.mainloop()
    except Exception as e:
        if "display" not in str(e).lower():          # sin pantalla (ej. Raspberry por SSH) no es un error que mostrar
            print(f"Arché: La ventana se cerró por un error ({e}).")
    finally:
        try:
            if _ventana is not None:
                try:
                    perfiles.volcar(forzar=True)
                except Exception:
                    pass
                if _ventana._bandeja is not None:
                    _ventana._bandeja.stop()
                _ventana.canvas = None
                _ventana.root = None
        except Exception:
            pass
        _ventana = None
        import gc
        gc.collect()


def abierta():
    return _hilo is not None and _hilo.is_alive() and _ventana is not None


def abrir(tv=False, foco=True):
    """Abre la ventana (o la cambia de modo si ya esta abierta)."""
    global _hilo
    if tk is None:
        return False
    with _bloqueo:
        if abierta():
            _ventana.pedir_tv = bool(tv)
            return True
        _hilo = threading.Thread(target=_correr, args=(tv, foco), daemon=True)
        _hilo.start()
        return True


def cerrar():
    if abierta():
        _ventana.pedir_cerrar = True
        return True
    return False


def poner_ambiente(valor=True):
    if abierta():
        _ventana.ambiente = bool(valor)
        return True
    return False


def ir_a_pestana(nombre):
    if abierta():
        _ventana.pestana = nombre
        return True
    return False


def pedir(accion, dato=None):
    """Pide a la ventana abierta que haga algo (editor, centro, desacoplar...). False si no esta abierta."""
    if abierta():
        _ventana.peticiones.append((accion, dato))
        return True
    return False
