"""
avatar_dibujo.py
----------------
Ubicacion: Arche/core/nucleo/avatar_dibujo.py

El dibujo de la figura de Arché para el avatar del escritorio. Es una copia, paso por paso,
de dibujarOrbe() y esferaBase() de core/interfaz/web/app.js (la misma forma, los mismos
colores, el mismo halo, las mismas chispas y los mismos tiempos), pero hecha en Python
con numpy + Pillow para poder ponerla en una ventana con TRANSPARENCIA REAL por píxel.

  dibujar(estado, t_ms) -> imagen RGBA (fondo transparente)

Lee en cada cuadro los MISMOS ajustes de la interfaz (forma, color, tamaño, velocidad,
brillo, chispas, acentos) y los colores del tema, así que si cambias algo en la interfaz
el avatar cambia solo.

Se dibuja al doble de tamaño y se reduce al final, para que los bordes queden suaves.
"""

import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ESTILOS = ("esfera", "ondas", "anillos", "nucleo", "geometrica")
RITMO = {"reposo": .5, "escuchando": 1.1, "pensando": 1.6, "hablando": 3.2, "desconectado": .2}
AMP = {"reposo": .03, "escuchando": .06, "pensando": .05, "hablando": .12, "desconectado": 0}
_REJILLAS = {}


def _rgb(hexa, defecto="#888888"):
    h = (hexa or defecto).lstrip("#")
    if len(h) != 6:
        h = defecto.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


# ------------------------------------------------------------------
# Un "canvas" mínimo, con las mismas reglas del canvas del navegador
# ------------------------------------------------------------------

class Lienzo:
    def __init__(self, W, H, escala=2):
        self.W, self.H, self.s = W, H, escala
        self.w, self.h = W * escala, H * escala
        self.px = np.zeros((self.h, self.w, 4), np.float32)          # RGBA premultiplicado
        clave = (W, H, escala)
        if clave not in _REJILLAS:                                  # las coordenadas se calculan una sola vez
            yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
            _REJILLAS.clear()
            _REJILLAS[clave] = ((xx + .5) / escala, (yy + .5) / escala)
        self.x, self.y = _REJILLAS[clave]                           # coordenadas en "px de la página"
        self.ox = self.oy = 0                                       # origen (para las ventanas recortadas)

    def ventana(self, x0, y0, x1, y1):
        """Un trozo del lienzo (comparte los píxeles): dibujar algo chico no recorre toda la imagen."""
        a = max(0, int(math.floor(x0 * self.s)) - 1)
        b = min(self.w, int(math.ceil(x1 * self.s)) + 1)
        c = max(0, int(math.floor(y0 * self.s)) - 1)
        d = min(self.h, int(math.ceil(y1 * self.s)) + 1)
        v = object.__new__(Lienzo)
        v.W, v.H, v.s = self.W, self.H, self.s
        v.w, v.h = max(0, b - a), max(0, d - c)
        v.px = self.px[c:d, a:b]
        v.x, v.y = self.x[c:d, a:b], self.y[c:d, a:b]
        v.ox, v.oy = self.ox + a, self.oy + c
        return v

    def _encima(self, capa):
        """Operador «source-over» del canvas."""
        if self.px.size:
            self.px[...] = capa + self.px * (1.0 - capa[..., 3:4])

    def _color(self, color, alfa, mascara):
        r, g, b = _rgb(color)
        a = (alfa * mascara).astype(np.float32)
        return np.stack([r * a, g * a, b * a, a], -1)

    # --- degradados (misma matemática que createRadialGradient / createLinearGradient) ---

    @staticmethod
    def _paradas(t, paradas):
        """paradas: [(pos, (r,g,b,a))]. Interpola en premultiplicado, como el navegador."""
        pos = [p for p, _ in paradas]
        pre = [(r * a, g * a, b * a, a) for _, (r, g, b, a) in paradas]
        escalones = np.linspace(0.0, 1.0, 257)
        tabla = np.stack([np.interp(escalones, pos, [c[k] for c in pre]) for k in range(4)], -1).astype(np.float32)
        indice = (np.clip(np.nan_to_num(t), 0.0, 1.0) * 256).astype(np.int32)
        return tabla[indice]

    def radial(self, x0, y0, r0, x1, y1, r1, paradas):
        dx, dy, dr = x1 - x0, y1 - y0, r1 - r0
        qx, qy = self.x - x0, self.y - y0
        A = dx * dx + dy * dy - dr * dr
        B = qx * dx + qy * dy + r0 * dr
        C = qx * qx + qy * qy - r0 * r0
        if abs(A) < 1e-6:
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.where(np.abs(B) > 1e-9, C / (2 * B), -1.0)
            valido = (r0 + t * dr) >= 0
        else:
            disc = B * B - A * C
            valido = disc >= 0
            raiz = np.sqrt(np.maximum(disc, 0))
            t1, t2 = (B + raiz) / A, (B - raiz) / A
            alto, bajo = np.maximum(t1, t2), np.minimum(t1, t2)
            t = np.where(r0 + alto * dr >= 0, alto, bajo)
            valido &= (r0 + t * dr) >= 0
        color = self._paradas(t, paradas)
        return color * valido[..., None]

    def lineal(self, x0, y0, x1, y1, paradas):
        dx, dy = x1 - x0, y1 - y0
        largo = dx * dx + dy * dy or 1e-9
        t = ((self.x - x0) * dx + (self.y - y0) * dy) / largo
        return self._paradas(t, paradas)

    # --- figuras con bordes suaves ---

    def circulo(self, cx, cy, r):
        d = np.hypot(self.x - cx, self.y - cy)
        return np.clip((r - d) * self.s + .5, 0, 1)

    def aro(self, cx, cy, r, ancho):
        d = np.hypot(self.x - cx, self.y - cy)
        return np.clip((ancho / 2 - np.abs(d - r)) * self.s + .5, 0, 1)

    def trazo(self, puntos, ancho, cerrado=False, redondo=False):
        img = Image.new("L", (max(1, self.w), max(1, self.h)), 0)
        d = ImageDraw.Draw(img)
        pts = [(x * self.s - self.ox, y * self.s - self.oy) for x, y in puntos]
        if cerrado:
            pts = pts + [pts[0], pts[1]]
        w = max(1, int(round(ancho * self.s)))
        d.line(pts, fill=255, width=w, joint="curve")
        if redondo:
            for x, y in (pts[0], pts[-1]):
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
        return np.asarray(img, np.float32) / 255.0

    def poligono(self, puntos):
        img = Image.new("L", (max(1, self.w), max(1, self.h)), 0)
        ImageDraw.Draw(img).polygon([(x * self.s - self.ox, y * self.s - self.oy) for x, y in puntos], fill=255)
        return np.asarray(img, np.float32) / 255.0

    def pintar(self, color, alfa, mascara):
        self._encima(self._color(color, alfa, mascara))

    def punto(self, color, alfa, cx, cy, r):
        v = self.ventana(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1)
        if v.px.size:
            v.pintar(color, alfa, v.circulo(cx, cy, r))

    def anillo(self, color, alfa, cx, cy, r, ancho):
        m = r + ancho
        v = self.ventana(cx - m, cy - m, cx + m, cy + m)
        if v.px.size:
            v.pintar(color, alfa, v.aro(cx, cy, r, ancho))

    def pintar_degradado(self, degradado, mascara):
        self._encima(degradado * mascara[..., None])

    def imagen(self, alfa_global=1.0):
        """Reduce al tamaño real y devuelve una imagen RGBA normal (no premultiplicada)."""
        p = self.px.reshape(self.H, self.s, self.W, self.s, 4).mean(axis=(1, 3)) * alfa_global
        a = p[..., 3:4]
        with np.errstate(divide="ignore", invalid="ignore"):
            rgb = np.where(a > 1e-4, p[..., :3] / np.maximum(a, 1e-4), 0)
        salida = np.concatenate([rgb, a], -1)
        return Image.fromarray((np.clip(salida, 0, 1) * 255 + .5).astype(np.uint8), "RGBA")


# ------------------------------------------------------------------
# esferaBase() y dibujarOrbe() de app.js
# ------------------------------------------------------------------

def _esfera_base(L, cx, cy, R, cA, cB, cC, tt, ritmo, onda=0.03):
    L = L.ventana(cx - R * 1.3, cy - R * 1.3, cx + R * 1.3, cy + R * 1.3)
    if not L.px.size:
        return
    pts = []
    for i in range(91):
        ang = i / 90 * math.pi * 2
        rr = R * (1 + math.sin(ang * 3 + tt * ritmo * 2.2) * onda * .6 + math.sin(ang * 5 - tt * ritmo * 1.7) * onda * .4)
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    clip = L.poligono(pts)
    # cuerpo: azul -> morado -> rojo girando despacio
    ca, sa = math.cos(tt * .4), math.sin(tt * .4)
    g = L.lineal(cx + ca * R, cy + sa * R, cx - ca * R, cy - sa * R,
                 [(0, (*_rgb(cA), 1)), (.55, (*_rgb(cB), 1)), (1, (*_rgb(cC), 1))])
    L.pintar_degradado(g, clip)
    # bandas internas
    for k in range(3):
        y = cy + math.sin(tt * ritmo * .7 + k * 2) * R * .5
        b = L.radial(cx + math.cos(tt * .6 + k) * R * .4, y, 0, cx, y, R * .9,
                     [(0, (1, 1, 1, .18)), (1, (1, 1, 1, 0))])
        L.pintar_degradado(b, clip)
    # luz y sombra (volumen)
    luz = L.radial(cx - R * .35, cy - R * .4, R * .05, cx, cy, R * 1.05,
                   [(0, (1, 1, 1, .55)), (.35, (1, 1, 1, .05)), (1, (0, 0, 0, .45))])
    L.pintar_degradado(luz, clip)


class Dibujante:
    """Guarda las chispas entre cuadros, como el objeto `o` de app.js."""

    def __init__(self, lado):
        self.lado = lado
        self.grande = lado >= 180
        self.chispas = []

    def dibujar(self, estado, t_ms, ajustes, colores, alfa_extra=1.0):
        W = H = self.lado
        a = ajustes or {}
        col = colores or {}
        est = estado if estado in RITMO else "reposo"
        estilo = a.get("estilo_voz") or "esfera"
        vel = (a.get("orbe_velocidad") or 100) / 100
        brillo = (60 if a.get("efecto_brillo") is None else a.get("efecto_brillo")) / 100
        tam = (a.get("orbe_tamano") or 100) / 100
        ritmo, amp = RITMO[est], AMP[est]
        tt = t_ms / 1000 * vel
        pa_a, pa_b = a.get("web_acento_2") or None, a.get("web_acento") or None
        cA = a.get("orbe_color") or pa_a or col.get("azul") or "#2f4fd1"
        cB = pa_b or col.get("morado") or "#6b34c9"
        cC = col.get("rojo") or "#b81f45"
        cAc = a.get("orbe_color") or pa_a or col.get("azul_claro") or "#5b7cff"
        cBc = pa_b or col.get("morado_claro") or "#9b6bff"
        cx, cy = W / 2, H / 2
        R = min(W, H) * .30 * min(1.25, tam) * (1 + math.sin(tt * ritmo * 2) * amp)
        L = Lienzo(W, H)

        # halo
        color_halo = cC if est == "hablando" else (cBc if est == "pensando" else cAc)
        halo = L.radial(cx, cy, R * .6, cx, cy, R * 1.65,
                        [(0, (*_rgb(color_halo), .35 * brillo)), (1, (*_rgb(cB), 0))])
        L.pintar_degradado(halo, L.circulo(cx, cy, R * 1.65))

        if estilo == "ondas":
            for k in range(3):
                pts = []
                x = 0.0
                while x <= W + 1e-6:
                    u = (x - cx) / (R * 1.4)
                    env = max(0.0, 1 - u * u)
                    y = cy + math.sin(x / W * 12 + tt * ritmo * 3 + k * 2) * R * (.12 + amp * 4) * env * (1 - k * .25)
                    pts.append((x, y))
                    x += W / 120
                L.pintar([cAc, cBc, cC][k], .85 - k * .2, L.trazo(pts, (4 if self.grande else 2.5) - k * .6))
        elif estilo == "anillos":
            for k in range(4):
                f = (tt * ritmo * .4 + k / 4) % 1
                L.anillo(cBc if k % 2 else cAc, (1 - f) * .9, cx, cy, R * (.35 + f * .9), 3 if self.grande else 2)
            _esfera_base(L, cx, cy, R * .38, cA, cB, cC, tt, ritmo)
        elif estilo == "nucleo":
            _esfera_base(L, cx, cy, R * .45, cA, cB, cC, tt, ritmo)
            for k in range(9):
                ang = tt * ritmo * (1 if k % 2 else -1) * .8 + k * 2.1
                rr = R * (.7 + (k % 3) * .17)
                x, y = cx + math.cos(ang) * rr, cy + math.sin(ang) * rr * .55
                color = cC if k % 3 == 0 else (cAc if k % 3 == 1 else cBc)
                L.punto(color, .9, x, y, (4 if self.grande else 2.5) * (1 + (y - cy) / (R * 2)))
        elif estilo == "geometrica":
            for k in range(3):
                pts = []
                for i in range(7):
                    ang = i / 6 * math.pi * 2 + tt * ritmo * .3 * (-1 if k % 2 else 1)
                    rr = R * (1 - k * .25) * (1 + math.sin(tt * ritmo * 2 + i) * amp)
                    pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
                L.pintar([cAc, cBc, cC][k], .9, L.trazo(pts, 2.5 if self.grande else 1.8, cerrado=True))
        else:
            _esfera_base(L, cx, cy, R, cA, cB, cC, tt, ritmo, amp if est == "hablando" else amp * .6)
            if est == "pensando":
                pts = [(cx + math.cos(tt * 3 + math.pi * .6 * i / 30) * R * 1.18,
                        cy + math.sin(tt * 3 + math.pi * .6 * i / 30) * R * 1.18) for i in range(31)]
                L.pintar(cBc, .9, L.trazo(pts, 3 if self.grande else 2, redondo=True))
            if est == "escuchando":
                f = (tt * 1.2) % 1
                L.anillo(cAc, (1 - f) * .7, cx, cy, R * (1.05 + f * .5), 2)

        # chispas
        n = round(((a.get("efecto_particulas") or 0) / 100) * (40 if self.grande else 10))
        while len(self.chispas) < n:
            self.chispas.append({"a": random.random() * 6.28, "r": 1.1 + random.random() * .6,
                                 "v": .2 + random.random() * .6, "s": random.random()})
        del self.chispas[n:]
        for p in self.chispas:
            p["a"] += .004 * p["v"] * ritmo * vel * 4
            x, y = cx + math.cos(p["a"]) * R * p["r"], cy + math.sin(p["a"]) * R * p["r"]
            L.punto(cAc if p["s"] > .5 else cBc, .5 + .5 * math.sin(tt * 3 + p["s"] * 9), x, y,
                    2 if self.grande else 1.2)

        return L.imagen((.45 if est == "desconectado" else 1.0) * alfa_extra)


# ------------------------------------------------------------------
# Globo de texto (avisos), encima de la figura
# ------------------------------------------------------------------

def _fuente(tam):
    for nombre in ("segoeui.ttf", "seguisb.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def poner_globo(imagen, texto, colores, alerta=False):
    if not texto:
        return imagen
    W, H = imagen.size
    fuente = _fuente(max(10, W // 17))
    capa = Image.new("RGBA", imagen.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    ancho_max = W - 28
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = (actual + " " + palabra).strip()
        if d.textlength(prueba, font=fuente) <= ancho_max:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    if len(lineas) > 3:
        lineas = lineas[:3]
        lineas[-1] = lineas[-1][:max(1, len(lineas[-1]) - 2)] + "…"
    alto_linea = fuente.size + 3 if hasattr(fuente, "size") else 14
    alto = alto_linea * len(lineas) + 12
    fondo = tuple(int(c * 255) for c in _rgb(colores.get("panel2") or colores.get("panel"), "#1b1f33")) + (245,)
    borde = tuple(int(c * 255) for c in _rgb(colores.get("alerta") if alerta else colores.get("morado_claro"),
                                             "#e0435f" if alerta else "#9b6bff")) + (255,)
    texto_col = tuple(int(c * 255) for c in _rgb(colores.get("texto"), "#e8e4ff")) + (255,)
    d.rounded_rectangle((6, 4, W - 6, 4 + alto), radius=10, fill=fondo, outline=borde, width=2)
    for i, linea in enumerate(lineas):
        d.text((14, 10 + i * alto_linea), linea, font=fuente, fill=texto_col)
    return Image.alpha_composite(imagen, capa)
