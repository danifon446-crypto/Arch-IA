"""
mascota.py
----------
Ubicacion: Arche/core/interfaz/mascota.py

La mascota de Arché: un personaje que vive en la ventana, dibujado con codigo
(no usa imagenes). Tres personajes: chispa, robot y gato. Reacciona a lo que
Arché hace de verdad:

  hablando    mueve la boca
  pensando    mira hacia arriba, con puntitos
  estudiando  lee un libro (examen o estudio activos)
  sudando     el equipo esta muy cargado
  durmiendo   nadie le habla hace rato (o es de madrugada)
  celebrando  cuando prendes algo, aprende o termina un examen

Ademas da consejos con comandos reales y hace un recorrido corto la primera vez.
"""

import math
import random
import time

from . import tema

PERSONAJES = ("chispa", "robot", "gato")

TIPS = (
    "Dime «panel» y te muestro mi estado en la consola.",
    "¿Curiosa? Di «procesos» y veo lo que hago en segundo plano.",
    "Di «qué has mejorado» y te cuento lo que aprendí sola.",
    "Con «modo tv» me pongo a pantalla completa.",
    "Puedes pedirme «pon una canción en spotify».",
    "Prueba «busca gatos en youtube»: busco directo en el sitio.",
    "Si me enseñas una frase nueva: «enseñar <frase> => <intención>».",
    "En AJUSTES puedes cambiar mi esfera, el fondo y hasta mi nombre.",
    "En CONTROLES enciendo o apago mis funciones al toque.",
    "Di «comandos» y te enseño lo que sé hacer.",
    "Dime «estado examen» y te cuento cómo voy aprendiendo.",
    "Puedes ponerme un fondo con imágenes, GIF o videos.",
)

RECORRIDO = (
    ("¡Hola! Soy {nombre}, tu guía. Te enseño la ventana en un momento.", None, None),
    ("Aquí me escribes: teclea y pulsa Enter. También puedes hablarme en la consola.", "caja", None),
    ("Esta esfera soy yo: azul cuando escucho, morada cuando pienso y roja cuando hablo.", "esfera", None),
    ("Aquí enciendes y apagas mis funciones, y lo ves en vivo.", "derecha", "controles"),
    ("En AJUSTES cambias la esfera, los colores, el fondo y hasta mi aspecto. ¡Listo!", "derecha", "ajustes"),
)


class Mascota:
    def __init__(self):
        self.mensaje = ""
        self.mensaje_hasta = 0.0
        self.celebra_hasta = 0.0
        self.salto_ts = -10.0
        self.proximo_parpadeo = time.time() + 3
        self.parpadeo_ts = -1.0
        self.proximo_consejo = time.time() + 25
        self._ultimo_consejo = -1
        self.paso = None            # paso del recorrido en curso (None = no hay)
        self.cadencia = 1.0         # >1: consejos mas espaciados, <1: mas seguidos

    # ---- mensajes ----
    def decir(self, texto, seg=9):
        self.mensaje, self.mensaje_hasta = texto, time.time() + seg

    def hay_mensaje(self, ahora=None):
        return bool(self.mensaje) and (self.paso is not None or (ahora or time.time()) < self.mensaje_hasta)

    def celebrar(self, seg=2.2):
        self.celebra_hasta = time.time() + seg
        self.salto_ts = time.time()

    def clic(self, nombre):
        self.salto_ts = time.time()
        self.decir(random.choice((f"¡Hola! Soy {nombre}.", "¿Me llamabas?",
                                  "Aquí estoy.", "¡Eso hizo cosquillas!")), 4)

    def consejo(self):
        i = random.randrange(len(TIPS))
        if i == self._ultimo_consejo:
            i = (i + 1) % len(TIPS)
        self._ultimo_consejo = i
        self.decir(TIPS[i], 11)

    def tick(self, consejos, ocupada, dormida):
        ahora = time.time()
        if ahora > self.proximo_parpadeo:
            self.parpadeo_ts = ahora
            self.proximo_parpadeo = ahora + random.uniform(2.5, 6.0)
        if consejos and not ocupada and not dormida and self.paso is None and ahora > self.proximo_consejo:
            if not self.hay_mensaje(ahora):
                self.consejo()
            self.proximo_consejo = ahora + random.uniform(45, 80) * self.cadencia

    # ---- recorrido ----
    def iniciar_recorrido(self, nombre):
        self.paso = 0
        self.decir(RECORRIDO[0][0].format(nombre=nombre), 3600)

    def avanzar_recorrido(self, nombre):
        """Devuelve True si el recorrido termino."""
        if self.paso is None:
            return True
        self.paso += 1
        if self.paso >= len(RECORRIDO):
            self.paso = None
            self.mensaje_hasta = 0
            self.celebrar()
            return True
        self.decir(RECORRIDO[self.paso][0].format(nombre=nombre), 3600)
        return False

    def saltar_recorrido(self):
        self.paso = None
        self.mensaje_hasta = 0

    # ---- estado visible ----
    def estado(self, hablando, pensando, cpu, estudiando, inactivo_seg, hora):
        ahora = time.time()
        if hablando:
            return "hablando"
        if pensando:
            return "pensando"
        if ahora < self.celebra_hasta:
            return "celebrando"
        if cpu is not None and cpu >= 90:
            return "sudando"
        if estudiando:
            return "estudiando"
        if inactivo_seg > 600 or (hora < 6 and inactivo_seg > 120):
            return "dormida"
        return "feliz"

    # ---- dibujo ----
    def dibujar(self, c, x, y, s, personaje, estado, t, mirar, nivel, tag):
        """(x, y) = centro del cuerpo; s = tamano (mitad del ancho aprox)."""
        ahora = time.time()
        salto = ahora - self.salto_ts
        rebote = -abs(math.sin(salto * 7)) * s * 0.5 * max(0.0, 1 - salto / 0.8) if salto < 0.8 else 0.0
        flota = math.sin(t * 2.0) * s * 0.05 * (0.3 if estado == "dormida" else 1.0)
        y = y + flota + rebote
        parp = 1.0 if 0 <= ahora - self.parpadeo_ts < 0.14 else 0.0
        # sombra en el suelo
        c.create_oval(x - s * 0.8, y + s * 1.05 - rebote * 0.2, x + s * 0.8, y + s * 1.2,
                      fill=tema.mezclar(tema.PANEL, tema.FONDO, 0.6), outline="", tags=tag)
        {"chispa": self._chispa, "robot": self._robot, "gato": self._gato}.get(personaje, self._chispa)(
            c, x, y, s, estado, t, mirar, nivel, parp, tag)
        self._accesorios(c, x, y, s, estado, t, tag)

    # -- piezas comunes --
    def _ojo(self, c, cx, cy, rx, ry, estado, mirar, parp, tag, color="#ffffff", pupila="#15122e"):
        if estado == "dormida" or parp:
            c.create_line(cx - rx, cy, cx + rx, cy, fill=pupila, width=max(2, rx * 0.35), capstyle="round", tags=tag)
            return
        if estado == "celebrando":
            c.create_arc(cx - rx, cy - ry * 0.2, cx + rx, cy + ry * 1.5, start=20, extent=140, style="arc",
                         outline=pupila, width=max(2, rx * 0.4), tags=tag)
            return
        if estado == "alerta":
            ry *= 1.25
        c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, fill=color, outline="", tags=tag)
        dx, dy = mirar
        if estado == "pensando":
            dx, dy = 0.55, -0.7
        elif estado == "estudiando":
            dx, dy = math.sin(time.time() * 1.2) * 0.5, 0.65
        px, py = cx + dx * rx * 0.4, cy + dy * ry * 0.4
        pr = rx * 0.55
        c.create_oval(px - pr, py - pr * 1.15, px + pr, py + pr * 1.15, fill=pupila, outline="", tags=tag)
        c.create_oval(px - pr * 0.1, py - pr * 0.75, px + pr * 0.45, py - pr * 0.15, fill="#ffffff", outline="", tags=tag)

    def _boca(self, c, cx, cy, w, estado, nivel, tag, color="#15122e"):
        if estado == "hablando":
            ab = w * (0.18 + 0.5 * min(1.0, nivel * 2 + 0.3 * abs(math.sin(time.time() * 11))))
            c.create_oval(cx - w * 0.4, cy - ab * 0.2, cx + w * 0.4, cy + ab, fill=color, outline="", tags=tag)
            c.create_oval(cx - w * 0.22, cy + ab * 0.45, cx + w * 0.22, cy + ab * 0.95,
                          fill=tema.ROJO_CLARO, outline="", tags=tag)
        elif estado == "celebrando":
            c.create_arc(cx - w * 0.6, cy - w * 0.45, cx + w * 0.6, cy + w * 0.5, start=190, extent=160,
                         style="chord", fill=color, outline=color, tags=tag)
        elif estado in ("sudando", "alerta"):
            c.create_arc(cx - w * 0.4, cy, cx + w * 0.4, cy + w * 0.5, start=20, extent=140, style="arc",
                         outline=color, width=max(2, w * 0.12), tags=tag)
        elif estado in ("pensando", "estudiando", "dormida"):
            c.create_line(cx - w * 0.25, cy + w * 0.1, cx + w * 0.25, cy + w * 0.1, fill=color,
                          width=max(2, w * 0.12), capstyle="round", tags=tag)
        else:
            c.create_arc(cx - w * 0.5, cy - w * 0.35, cx + w * 0.5, cy + w * 0.35, start=200, extent=140,
                         style="arc", outline=color, width=max(2, w * 0.12), tags=tag)

    # -- personajes --
    def _chispa(self, c, x, y, s, estado, t, mirar, nivel, parp, tag):
        cuerpo = tema.mezclar(tema.MORADO_CLARO, "#ffffff", 0.12)
        claro = tema.mezclar(cuerpo, "#ffffff", 0.35)
        # antena con chispa
        c.create_line(x, y - s * 0.95, x + s * 0.12 * math.sin(t * 2), y - s * 1.35, fill=tema.MORADO, width=3,
                      capstyle="round", tags=tag)
        b = 0.7 + 0.3 * math.sin(t * 5)
        ax, ay, r = x + s * 0.12 * math.sin(t * 2), y - s * 1.45, s * 0.22 * b
        c.create_polygon(ax, ay - r, ax + r * 0.3, ay - r * 0.3, ax + r, ay, ax + r * 0.3, ay + r * 0.3,
                         ax, ay + r, ax - r * 0.3, ay + r * 0.3, ax - r, ay, ax - r * 0.3, ay - r * 0.3,
                         fill=tema.AZUL_CLARO, outline="", tags=tag)
        # cuerpo en forma de gota
        pts = []
        for k in range(0, 360, 10):
            th = math.radians(k)
            rr = s * (1 + 0.04 * math.sin(3 * th + t * 2))
            pts += [x + rr * math.cos(th) * 1.05, y + rr * math.sin(th) * (1.0 if math.sin(th) < 0 else 0.95)]
        c.create_polygon(pts, smooth=True, fill=cuerpo, outline=tema.MORADO, width=2, tags=tag)
        c.create_oval(x - s * 0.62, y - s * 0.78, x - s * 0.1, y - s * 0.4, fill=claro, outline="", tags=tag)
        for sx in (-1, 1):
            self._ojo(c, x + sx * s * 0.36, y - s * 0.12, s * 0.2, s * 0.24, estado, mirar, parp, tag)
            c.create_oval(x + sx * s * 0.66 - s * 0.12, y + s * 0.12, x + sx * s * 0.66 + s * 0.12, y + s * 0.26,
                          fill=tema.mezclar(cuerpo, tema.ROJO_CLARO, 0.55), outline="", tags=tag)
        self._boca(c, x, y + s * 0.3, s * 0.4, estado, nivel, tag)

    def _robot(self, c, x, y, s, estado, t, mirar, nivel, parp, tag):
        metal = tema.mezclar(tema.AZUL_CLARO, "#ffffff", 0.25)
        oscuro = tema.mezclar(tema.FONDO, tema.AZUL, 0.25)
        c.create_line(x, y - s * 0.85, x, y - s * 1.25, fill=metal, width=3, tags=tag)
        glow = 0.6 + 0.4 * math.sin(t * 4)
        c.create_oval(x - s * 0.13, y - s * 1.42, x + s * 0.13, y - s * 1.16,
                      fill=tema.mezclar(tema.AZUL, tema.ROJO_CLARO, glow), outline="", tags=tag)
        for sx in (-1, 1):                                     # orejas
            c.create_rectangle(x + sx * s * 1.0 - s * 0.1, y - s * 0.2, x + sx * s * 1.0 + s * 0.1, y + s * 0.3,
                               fill=tema.AZUL, outline="", tags=tag)
        r = s * 0.28
        x0, y0, x1, y1 = x - s, y - s * 0.85, x + s, y + s * 0.85
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
               x0, y1 - r, x0, y0 + r, x0, y0]
        c.create_polygon(pts, smooth=True, fill=metal, outline=tema.AZUL, width=2, tags=tag)
        c.create_rectangle(x - s * 0.78, y - s * 0.58, x + s * 0.78, y + s * 0.5, fill=oscuro, outline="", tags=tag)
        led = tema.AZUL_CLARO if estado != "alerta" else tema.ROJO_CLARO
        for sx in (-1, 1):
            cx, cy = x + sx * s * 0.36, y - s * 0.22
            if estado == "dormida" or parp:
                c.create_line(cx - s * 0.18, cy, cx + s * 0.18, cy, fill=led, width=4, capstyle="round", tags=tag)
            elif estado == "celebrando":
                c.create_arc(cx - s * 0.2, cy - s * 0.05, cx + s * 0.2, cy + s * 0.4, start=20, extent=140,
                             style="arc", outline=led, width=4, tags=tag)
            else:
                dx, dy = mirar
                if estado == "pensando":
                    dx, dy = 0.6, -0.7
                elif estado == "estudiando":
                    dx, dy = math.sin(time.time() * 1.2) * 0.5, 0.6
                ey = s * (0.24 if estado != "alerta" else 0.3)
                c.create_rectangle(cx - s * 0.17 + dx * s * 0.05, cy - ey + dy * s * 0.05,
                                   cx + s * 0.17 + dx * s * 0.05, cy + ey + dy * s * 0.05,
                                   fill=led, outline="", tags=tag)
        self._boca(c, x, y + s * 0.2, s * 0.5, estado, nivel, tag, color=led)

    def _gato(self, c, x, y, s, estado, t, mirar, nivel, parp, tag):
        pelo = tema.mezclar(tema.ROJO_CLARO, tema.TEXTO, 0.22)
        oscuro = tema.mezclar(pelo, tema.FONDO, 0.45)
        for sx in (-1, 1):                                       # orejas
            c.create_polygon(x + sx * s * 0.95, y - s * 0.2, x + sx * s * 0.78, y - s * 1.2, x + sx * s * 0.2,
                             y - s * 0.78, fill=pelo, outline=oscuro, width=2, tags=tag)
            c.create_polygon(x + sx * s * 0.78, y - s * 0.4, x + sx * s * 0.72, y - s * 0.95, x + sx * s * 0.4,
                             y - s * 0.72, fill=tema.mezclar(pelo, "#ff9ab0", 0.5), outline="", tags=tag)
        c.create_oval(x - s * 1.05, y - s * 0.85, x + s * 1.05, y + s * 0.9, fill=pelo, outline=oscuro, width=2, tags=tag)
        for k in (-1, 0, 1):                                     # rayitas de la frente
            c.create_line(x + k * s * 0.22, y - s * 0.82, x + k * s * 0.18, y - s * 0.55, fill=oscuro, width=3,
                          capstyle="round", tags=tag)
        for sx in (-1, 1):
            self._ojo(c, x + sx * s * 0.42, y - s * 0.12, s * 0.2, s * 0.26, estado, mirar, parp, tag,
                      color=tema.mezclar("#c8ff9a", "#ffffff", 0.4))
            for k in (-1, 1):                                    # bigotes
                c.create_line(x + sx * s * 0.62, y + s * 0.3 + k * s * 0.05, x + sx * s * 1.25,
                              y + s * 0.3 + k * s * 0.22, fill=oscuro, width=2, tags=tag)
        c.create_polygon(x - s * 0.1, y + s * 0.1, x + s * 0.1, y + s * 0.1, x, y + s * 0.22,
                         fill=tema.ROJO, outline="", tags=tag)
        self._boca(c, x, y + s * 0.3, s * 0.34, estado, nivel, tag, color=oscuro)

    # -- cosas que lleva o le pasan --
    def _accesorios(self, c, x, y, s, estado, t, tag):
        if estado == "dormida":
            for i in range(3):
                f = (t * 0.6 + i / 3) % 1.0
                c.create_text(x + s * (0.9 + f * 0.7), y - s * (0.5 + f * 1.0), text="z", anchor="center",
                              fill=tema.mezclar(tema.PANEL, tema.TEXTO, 1 - f), font=(tema.FUENTE, int(s * (0.28 + 0.2 * f)), "bold"),
                              tags=tag)
        elif estado == "estudiando":
            lx, ly = x, y + s * 0.85
            c.create_polygon(lx - s * 0.8, ly - s * 0.05, lx, ly - s * 0.25, lx + s * 0.8, ly - s * 0.05,
                             lx + s * 0.8, ly + s * 0.45, lx, ly + s * 0.25, lx - s * 0.8, ly + s * 0.45,
                             fill=tema.mezclar(tema.AZUL, tema.TEXTO, 0.15), outline=tema.AZUL_CLARO, width=2, tags=tag)
            c.create_line(lx, ly - s * 0.22, lx, ly + s * 0.25, fill=tema.AZUL_CLARO, width=2, tags=tag)
            for k in range(3):
                c.create_line(lx - s * 0.65, ly + k * s * 0.1, lx - s * 0.1, ly + k * s * 0.1 - s * 0.05,
                              fill=tema.TENUE, width=1, tags=tag)
        elif estado == "sudando":
            g = (t * 1.5) % 1.0
            gx, gy = x + s * 1.05, y - s * 0.5 + g * s * 0.9
            c.create_polygon(gx, gy - s * 0.18, gx + s * 0.1, gy, gx, gy + s * 0.1, gx - s * 0.1, gy,
                             smooth=True, fill=tema.AZUL_CLARO, outline="", tags=tag)
        elif estado == "pensando":
            for i in range(3):
                on = int(t * 3) % 4 > i
                r = s * (0.07 + 0.03 * i)
                px, py = x + s * (0.95 + i * 0.28), y - s * (0.75 + i * 0.28)
                c.create_oval(px - r, py - r, px + r, py + r,
                              fill=tema.TEXTO if on else tema.mezclar(tema.PANEL, tema.TENUE, 0.5), outline="", tags=tag)
        elif estado == "celebrando":
            for i in range(6):
                ang = t * 3 + i * math.pi / 3
                rr = s * (1.35 + 0.15 * math.sin(t * 6 + i))
                px, py = x + rr * math.cos(ang), y + rr * math.sin(ang) * 0.9
                q = s * 0.1
                c.create_polygon(px, py - q * 1.6, px + q * 0.5, py - q * 0.5, px + q * 1.6, py, px + q * 0.5,
                                 py + q * 0.5, px, py + q * 1.6, px - q * 0.5, py + q * 0.5, px - q * 1.6, py,
                                 px - q * 0.5, py - q * 0.5,
                                 fill=(tema.AZUL_CLARO, tema.MORADO_CLARO, tema.ROJO_CLARO)[i % 3], outline="", tags=tag)
