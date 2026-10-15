"""
editor.py
---------
Ubicacion: Arche/core/interfaz/editor.py

Editor visual de la distribucion. Se entra con «editar diseño», el boton del
Centro o Ctrl+E.

  - arrastra un panel para moverlo (si lo sueltas sobre otro, intercambian sitio)
  - estira la esquina inferior derecha para cambiar el tamaño
  - ✕ oculta el panel (sigue en la bandeja de abajo para traerlo de vuelta)
  - la sombra verde muestra donde quedara; roja = no cabe
  - Deshacer / Rehacer, «Distribución original», Cancelar (vuelve a como estaba al entrar)
  - Enter o «Listo» terminan; Esc cancela

Aqui no hay datos nuevos: solo se llama a las operaciones de layout.py, que
nunca permiten superposiciones.
"""

from . import estado_visual as ev, layout, perfiles, tema


class Editor:
    def __init__(self):
        self.activo = False
        self.inicio = None            # captura al entrar (para Cancelar)
        self.arrastre = None          # {"id", "modo", "off", "fantasma", "valido"}
        self.hover = None
        self.botones = []             # (x0, y0, x1, y1, accion)

    def entrar(self):
        self.activo = True
        self.inicio = ev.capturar(False)
        ev.punto_de_control("editor")
        self.arrastre = None

    def salir(self, cancelar=False):
        if cancelar and self.inicio is not None:
            ev.aplicar(self.inicio)
        self.activo = False
        self.arrastre = None
        perfiles.marcar_sucio()
        perfiles.volcar(forzar=True)

    # ------------------------------------------------------------ geometria
    def _celda(self, v, x, y):
        x0, y0, cw, ch, gap = v.grid
        return (x - x0) / cw, (y - y0) / ch

    def _rect_de(self, v, wid):
        return v.rects.get(wid)

    def _en_widget(self, v, x, y):
        lay = perfiles.layout_actual()
        for w in reversed(lay["widgets"]):          # el de arriba primero
            if not w["visible"] or w.get("ventana"):
                continue
            r = self._rect_de(v, w["id"])
            if r and r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]:
                return w, r
        return None, None

    # ------------------------------------------------------------ eventos
    def mover_mouse(self, v, x, y):
        if self.arrastre:
            self._actualizar(v, x, y)
        else:
            w, _r = self._en_widget(v, x, y)
            self.hover = w["id"] if w else None

    def pulsar(self, v, x, y):
        """Devuelve True si el clic es del editor (siempre, mientras esta activo)."""
        for x0, y0, x1, y1, accion in self.botones:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._boton(v, accion)
                return True
        w, r = self._en_widget(v, x, y)
        if w is None:
            return True
        esc = v._esc()
        if x >= r[0] + r[2] - 26 * esc and y <= r[1] + 26 * esc:      # la ✕
            ev.punto_de_control("ocultar")
            layout.ocultar(perfiles.layout_actual(), w["id"])
            perfiles.marcar_sucio()
            return True
        if x >= r[0] + r[2] - 22 * esc and y >= r[1] + r[3] - 22 * esc:   # la esquina
            self.arrastre = {"id": w["id"], "modo": "tam", "off": (0, 0), "fantasma": None, "valido": True}
        else:
            cx, cy = self._celda(v, x, y)
            gx0, gy0 = self._celda(v, r[0], r[1])
            self.arrastre = {"id": w["id"], "modo": "mover", "off": (int(cx - gx0), int(cy - gy0)), "fantasma": None, "valido": True}
        self._actualizar(v, x, y)
        return True

    def _actualizar(self, v, x, y):
        a = self.arrastre
        lay = perfiles.layout_actual()
        w = layout.buscar(lay, a["id"])
        if w is None:
            self.arrastre = None
            return
        cx, cy = self._celda(v, x, y)
        if a["modo"] == "mover":
            gx = max(0, min(layout.COLS - w["w"], int(round(cx - a["off"][0] - 0.5))))
            gy = max(0, min(layout.FILAS - w["h"], int(round(cy - a["off"][1] - 0.5))))
            r = (gx, gy, gx + w["w"], gy + w["h"])
            chocan = layout.choques(lay, r, w["id"])
            bajo = None                                   # el panel sobre el que esta el cursor
            for o in lay["widgets"]:
                if o["id"] != w["id"] and o["visible"] and not o.get("ventana") and \
                        o["x"] <= cx < o["x"] + o["w"] and o["y"] <= cy < o["y"] + o["h"]:
                    bajo = o
            if chocan and bajo is not None and len(chocan) > 1:
                chocan = [bajo]                           # soltar sobre un panel = intercambiar con ese
            if not chocan:
                a["valido"], a["destino"] = True, None
            elif len(chocan) == 1:
                o = chocan[0]
                i1, i2 = layout.info(w["tipo"]), layout.info(o["tipo"])
                a["valido"] = not (o["w"] < i1[4] or o["h"] < i1[5] or w["w"] < i2[4] or w["h"] < i2[5])
                a["destino"] = o["id"]
            else:
                a["valido"], a["destino"] = False, None
            a["fantasma"] = (gx, gy, w["w"], w["h"])
            a["gx"], a["gy"] = gx, gy
        else:
            i = layout.info(w["tipo"])
            nw = max(i[4], min(layout.COLS - w["x"], int(round(cx - w["x"]))))
            nh = max(i[5], min(layout.FILAS - w["y"], int(round(cy - w["y"]))))
            r = (w["x"], w["y"], w["x"] + nw, w["y"] + nh)
            a["valido"] = not layout.choques(lay, r, w["id"])
            a["fantasma"] = (w["x"], w["y"], nw, nh)
            a["tam"] = (nw, nh)

    def soltar(self, v, x, y):
        a = self.arrastre
        self.arrastre = None
        if not a or not a.get("fantasma"):
            return
        lay = perfiles.layout_actual()
        w = layout.buscar(lay, a["id"])
        if w is None:
            return
        if not a["valido"]:
            v.avisar("No cabe ahí: prueba otro sitio o achica algo.", "info")
            return
        ev.punto_de_control("diseño")
        if a["modo"] == "mover":
            if a.get("destino"):
                ok, msg = layout.intercambiar(lay, a["id"], a["destino"])
            else:
                ok, msg = layout.mover(lay, a["id"], a["gx"], a["gy"])
        else:
            ok, msg = layout.redimensionar(lay, a["id"], *a["tam"])
        if not ok:
            v.avisar(msg.capitalize(), "info")
        perfiles.marcar_sucio()

    def _boton(self, v, accion):
        if accion == "listo":
            v.poner_editor(False)
        elif accion == "cancelar":
            v.poner_editor(False, cancelar=True)
        elif accion == "deshacer":
            ev.deshacer()
        elif accion == "rehacer":
            ev.rehacer()
        elif accion == "original":
            ev.punto_de_control("distribución original")
            perfiles.restablecer_distribucion()
        elif accion == "mas":
            v.poner_editor(False)
            v.abrir_centro("widgets")
        elif isinstance(accion, tuple) and accion[0] == "traer":
            ev.punto_de_control("mostrar")
            ok, msg = layout.mostrar(perfiles.layout_actual(), accion[1]) if accion[2] == "id" else layout.anadir(perfiles.layout_actual(), accion[1])
            if not ok:
                v.avisar(msg.capitalize(), "info")
            perfiles.marcar_sucio()

    # ------------------------------------------------------------ dibujo
    def dibujar(self, v, W, H, esc):
        c = v.canvas
        self.botones = []
        lay = perfiles.layout_actual()
        x0, y0, cw, ch, gap = v.grid
        # rejilla tenue mientras arrastras
        if self.arrastre:
            for gx in range(layout.COLS + 1):
                c.create_line(x0 + gx * cw - gap / 2, y0, x0 + gx * cw - gap / 2, y0 + layout.FILAS * ch, fill=tema.mezclar(tema.FONDO, tema.BORDE, 0.5), dash=(2, 6), tags=v._tag)
            for gy in range(layout.FILAS + 1):
                c.create_line(x0, y0 + gy * ch - gap / 2, x0 + layout.COLS * cw, y0 + gy * ch - gap / 2, fill=tema.mezclar(tema.FONDO, tema.BORDE, 0.5), dash=(2, 6), tags=v._tag)
        for w in lay["widgets"]:
            if not w["visible"] or w.get("ventana"):
                continue
            r = self._rect_de(v, w["id"])
            if not r:
                continue
            activo = self.arrastre and self.arrastre["id"] == w["id"]
            col = tema.MORADO_CLARO if (self.hover == w["id"] or activo) else tema.AZUL_CLARO
            v._redondo(r[0], r[1], r[0] + r[2], r[1] + r[3], 14 * esc, fill="", outline=col, width=2)
            etq = layout.nombre_de(w["tipo"])
            ancho = (len(etq) * 6.8 + 16) * esc
            v._redondo(r[0] + 8 * esc, r[1] + r[3] - 26 * esc, r[0] + 8 * esc + ancho, r[1] + r[3] - 6 * esc, 8 * esc, fill=tema.PANEL_2, outline=col)
            v._texto(r[0] + 16 * esc, r[1] + r[3] - 16 * esc, etq, 8, tema.TEXTO)
            # ✕ y esquina
            xr = r[0] + r[2] - 22 * esc
            v._redondo(xr, r[1] + 6 * esc, xr + 18 * esc, r[1] + 24 * esc, 9 * esc, fill=tema.mezclar(tema.PANEL_2, tema.ROJO, 0.5), outline=tema.ROJO_CLARO)
            v._texto(xr + 9 * esc, r[1] + 15 * esc, "✕", 8, tema.TEXTO, ancla="center")
            ex, ey = r[0] + r[2] - 4 * esc, r[1] + r[3] - 4 * esc
            for k in (6, 12, 18):
                c.create_line(ex - k * esc, ey, ex, ey - k * esc, fill=col, width=2, tags=v._tag)
        a = self.arrastre
        if a and a.get("fantasma"):
            gx, gy, gw, gh = a["fantasma"]
            px = x0 + gx * cw
            py = y0 + gy * ch
            col = tema.AZUL_CLARO if a["valido"] else tema.ROJO_CLARO
            v._redondo(px, py, px + gw * cw - gap, py + gh * ch - gap, 14 * esc, fill=tema.mezclar(tema.FONDO, col, 0.18), outline=col, width=3)
            texto = ("intercambia con «" + layout.nombre_de(layout.buscar(lay, a["destino"])["tipo"]) + "»") if a.get("destino") and a["valido"] \
                else (f"{gw}×{gh}" if a["valido"] else "no cabe")
            v._texto(px + 10 * esc, py + gh * ch - gap - 14 * esc, texto, 9, col, negrita=True)
        self._barra(v, W, H, esc, lay)

    def _barra(self, v, W, H, esc, lay):
        """Botones arriba y bandeja de componentes ocultos abajo."""
        y = 10 * esc
        x = W - 14 * esc
        v.canvas.create_rectangle(0, 0, W, 44 * esc, fill=tema.FONDO, outline="", tags=v._tag)
        for texto, accion, color in (("Listo", "listo", tema.AZUL_CLARO), ("Cancelar", "cancelar", tema.ROJO_CLARO),
                                     ("Distribución original", "original", None), ("Rehacer", "rehacer", None), ("Deshacer", "deshacer", None)):
            ancho = (len(texto) * 7.2 + 24) * esc
            x0 = x - ancho
            v._redondo(x0, y, x, y + 26 * esc, 13 * esc, fill=tema.mezclar(tema.PANEL_2, color or tema.MORADO_CLARO, 0.55 if color else 0.2), outline=color or tema.BORDE)
            v._texto((x0 + x) / 2, y + 13 * esc, texto, 9, tema.TEXTO, ancla="center", negrita=bool(color))
            self.botones.append((x0, y, x, y + 26 * esc, accion))
            x = x0 - 8 * esc
        v._texto(16 * esc, y + 13 * esc, "EDITOR DE DISEÑO · arrastra, estira la esquina o ✕ para ocultar", 9, tema.MORADO_CLARO, negrita=True)
        # bandeja
        ocultos = [w for w in lay["widgets"] if not w["visible"] or w.get("ventana")]
        presentes = {w["tipo"] for w in lay["widgets"]}
        nuevos = [t for t in layout.tipos() if t not in presentes][:6]
        yb = H - 34 * esc
        v._redondo(8 * esc, yb - 6 * esc, W - 8 * esc, H - 6 * esc, 12 * esc, fill=tema.mezclar(tema.FONDO, tema.PANEL, 0.8), outline=tema.BORDE)
        v._texto(18 * esc, yb + 11 * esc, "TRAER:", 8, tema.TENUE, negrita=True)
        x = 70 * esc
        for w in ocultos:
            etq = "+ " + layout.nombre_de(w["tipo"])
            ancho = (len(etq) * 6.6 + 18) * esc
            if x + ancho > W - 110 * esc:
                break
            v._redondo(x, yb, x + ancho, yb + 22 * esc, 11 * esc, fill=tema.PANEL_2, outline=tema.AZUL_CLARO)
            v._texto(x + ancho / 2, yb + 11 * esc, etq, 8, tema.TEXTO, ancla="center")
            self.botones.append((x, yb, x + ancho, yb + 22 * esc, ("traer", w["id"], "id")))
            x += ancho + 6 * esc
        for t in nuevos:
            etq = "+ " + layout.nombre_de(t)
            ancho = (len(etq) * 6.6 + 18) * esc
            if x + ancho > W - 110 * esc:
                break
            v._redondo(x, yb, x + ancho, yb + 22 * esc, 11 * esc, fill=tema.PANEL, outline=tema.BORDE)
            v._texto(x + ancho / 2, yb + 11 * esc, etq, 8, tema.TENUE, ancla="center")
            self.botones.append((x, yb, x + ancho, yb + 22 * esc, ("traer", t, "tipo")))
            x += ancho + 6 * esc
        v._redondo(W - 100 * esc, yb, W - 16 * esc, yb + 22 * esc, 11 * esc, fill=tema.PANEL_2, outline=tema.MORADO_CLARO)
        v._texto(W - 58 * esc, yb + 11 * esc, "Todos…", 8, tema.TEXTO, ancla="center")
        self.botones.append((W - 100 * esc, yb, W - 16 * esc, yb + 22 * esc, "mas"))
