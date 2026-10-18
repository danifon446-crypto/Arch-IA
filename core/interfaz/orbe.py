"""
orbe.py
-------
Ubicacion: Arche/core/interfaz/orbe.py

La esfera de Arché (estilo asistente): una masa de luz que respira en reposo,
se agita cuando habla, gira cuando piensa y late cuando escucha.

  reposo     azul y morado, respira despacio
  escuchando azul claro, anillo que late
  pensando   morado, puntos que giran alrededor
  hablando   rojo y magenta, se deforma con la voz

Solo dibuja: recibe el canvas y los colores de tema.py.
"""

import math

from . import tema

try:                                    # con Pillow la esfera es luz de verdad (brillo, mezcla y transparencia)
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk
except Exception:
    Image = None

_ref = None                             # la imagen de Tk debe seguir viva mientras se muestra
forzado = None                          # HEX: color que sustituye al del estado (lo pone la ventana)
luz = 1.0                            # 0 a 1.5: fuerza del resplandor
_mascaras = {}
_ok_pil = True

COLORES = {   # estado -> (color A, color B)
    "reposo": ("AZUL_CLARO", "MORADO_CLARO"),
    "escuchando": ("AZUL_CLARO", "AZUL_CLARO"),
    "pensando": ("MORADO_CLARO", "AZUL_CLARO"),
    "hablando": ("ROJO_CLARO", "MORADO_CLARO"),
}


def _paleta(estado):
    a, b = COLORES.get(estado, COLORES["reposo"])
    a, b = getattr(tema, a), getattr(tema, b)
    if forzado:
        return forzado, tema.mezclar(forzado, b, 0.4)
    return a, b


def _blob(cx, cy, radio, amp, fase, lobulos, giro):
    pts = []
    paso = 360 // 36
    for k in range(0, 360, paso):
        th = math.radians(k)
        d = (math.sin(lobulos * th + fase) * 0.55 + math.sin((lobulos + 2) * th - fase * 1.3 + giro) * 0.45)
        rr = radio * (1 + amp * d)
        pts += [cx + rr * math.cos(th), cy + rr * math.sin(th)]
    return pts


# ---------------------------------------------------------------- esfera con Pillow
_TRIOS = {   # estado -> (principal, secundario, tercero, luz del borde)
    "reposo": ("AZUL_CLARO", "MORADO_CLARO", "AZUL"),
    "escuchando": ("AZUL_CLARO", "AZUL", "MORADO_CLARO"),
    "pensando": ("MORADO_CLARO", "AZUL_CLARO", "MORADO"),
    "hablando": ("ROJO_CLARO", "MORADO_CLARO", "AZUL_CLARO"),
}


def _rgb(hexa):
    h = hexa.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mask_fijas(n):
    """Mascaras que no cambian con el tiempo (esfera, resplandor, borde, brillo), una vez por tamano."""
    if n in _mascaras:
        return _mascaras[n]
    c = n / 2
    R = n * 0.285
    esfera = Image.new("L", (n, n), 0)
    ImageDraw.Draw(esfera).ellipse((c - R, c - R, c + R, c + R), fill=255)
    esfera = esfera.filter(ImageFilter.GaussianBlur(n * 0.006))
    grad = Image.radial_gradient("L").resize((n, n), Image.BILINEAR)          # 0 centro -> 255 borde
    resplandor = grad.point(lambda v: int(255 * max(0.0, 1 - v / 255 / 0.98) ** 2.6))
    borde = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(borde)
    d.ellipse((c - R, c - R, c + R, c + R), outline=255, width=max(2, int(n * 0.014)))
    borde = borde.filter(ImageFilter.GaussianBlur(n * 0.008))
    brillo = Image.new("L", (n, n), 0)
    ImageDraw.Draw(brillo).ellipse((c - R * 0.62, c - R * 0.80, c - R * 0.05, c - R * 0.38), fill=210)
    brillo = brillo.filter(ImageFilter.GaussianBlur(n * 0.022))
    _mascaras[n] = (esfera, resplandor, borde, brillo)
    return _mascaras[n]


def _mancha(n, radio, amp, fase, lobulos, giro, cx, cy):
    """Una masa de luz deformada (mascara L) que se desvanece suavemente."""
    pts = []
    for k in range(0, 360, 6):
        th = math.radians(k)
        d = math.sin(lobulos * th + fase) * 0.6 + math.sin((lobulos + 2) * th - fase * 1.3 + giro) * 0.4
        rr = radio * (1 + amp * d)
        pts.append((cx + rr * math.cos(th), cy + rr * math.sin(th)))
    m = Image.new("L", (n, n), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m.filter(ImageFilter.GaussianBlur(n * 0.045))


def _render(n, estado, nivel, fase):
    esfera, resplandor, borde, brillo = _mask_fijas(n)
    c = n / 2
    R = n * 0.285
    cA, cB, cC = (_rgb(getattr(tema, x)) for x in _TRIOS.get(estado, _TRIOS["reposo"]))
    if forzado:
        f_ = _rgb(forzado)
        cA = f_
        cB = tuple(int(f_[i] * 0.6 + cB[i] * 0.4) for i in range(3))
        cC = tuple(int(f_[i] * 0.3 + cC[i] * 0.7) for i in range(3))
    hablando = estado == "hablando"
    vel = {"reposo": 0.8, "escuchando": 1.2, "pensando": 2.4, "hablando": 2.0}.get(estado, 1.0)
    amp = 0.10 + (0.30 * min(1.0, nivel * 2.4) if hablando else 0.05 * math.sin(fase * 0.9))
    f = fase * vel

    acc = Image.new("RGB", (n, n), (0, 0, 0))
    for color, esc_, off, lob in ((cA, 0.78, 0.0, 3), (cB, 0.70, 2.1, 4), (cC, 0.62, 4.2, 3)):
        dx = R * 0.22 * math.cos(f * 0.9 + off)
        dy = R * 0.22 * math.sin(f * 0.7 + off * 1.3)
        masa = _mancha(n, R * esc_, amp, f + off, lob, f * 0.3, c + dx, c + dy)
        masa = masa.point(lambda v: int(v * 0.62))
        capa = Image.composite(Image.new("RGB", (n, n), color), Image.new("RGB", (n, n), (0, 0, 0)), masa)
        acc = ImageChops.add(acc, capa)               # suma de luz: donde se cruzan brilla mas
    # base oscura-azulada para que no quede vacia la esfera
    base = Image.composite(Image.new("RGB", (n, n), tuple(int(v * 0.14) for v in cB)),
                           Image.new("RGB", (n, n), (0, 0, 0)), esfera)
    acc = ImageChops.add(acc, base)
    blanco = Image.new("RGB", (n, n), (255, 255, 255))
    acc = ImageChops.add(acc, Image.composite(blanco, Image.new("RGB", (n, n), (0, 0, 0)),
                                              borde.point(lambda v: int(v * 0.45))))
    acc = ImageChops.add(acc, Image.composite(blanco, Image.new("RGB", (n, n), (0, 0, 0)), brillo.point(lambda v: int(v * 0.45))))
    esfera_rgba = acc.convert("RGBA")
    esfera_rgba.putalpha(esfera)

    # resplandor exterior (alpha) con el color secundario; respira con la voz
    fuerza = 0.40 + 0.5 * min(1.0, nivel * 2.0) + (0.15 if estado in ("escuchando", "pensando") else 0.0)
    glow_a = resplandor.point(lambda v: int(v * min(1.0, fuerza * luz)))
    glow = Image.new("RGBA", (n, n), cB + (0,))
    glow.putalpha(glow_a)

    # anillo que late al escuchar / puntos que giran al pensar
    extra = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    de = ImageDraw.Draw(extra)
    if estado == "escuchando":
        p = (fase * 0.9) % 1.0
        rr = R * (1.08 + 0.55 * p)
        de.ellipse((c - rr, c - rr, c + rr, c + rr), outline=cA + (int(200 * (1 - p)),), width=max(2, int(n * 0.012)))
    if estado == "pensando":
        for i in range(8):
            ang = fase * 1.8 + i * math.pi / 4
            rr = R * 1.28
            px, py = c + rr * math.cos(ang), c + rr * math.sin(ang)
            t = 0.5 + 0.5 * math.sin(fase * 3 + i)
            tam = n * (0.008 + 0.010 * t)
            de.ellipse((px - tam, py - tam, px + tam, py + tam), fill=cA + (int(110 + 140 * t),))

    out = Image.alpha_composite(glow, extra)
    out = Image.alpha_composite(out, esfera_rgba)
    return out


def _dibujar_pil(c, cx, cy, r, estado, nivel, fase, tag):
    global _ref
    lado = int(max(120, min(420, r / 0.285 * 1.0)))         # lado total de la imagen (la esfera ocupa ~57%)
    n = max(60, lado // 2)                                  # se renderiza a media resolucion y se estira
    im = _render(n, estado, nivel, fase).resize((lado, lado), Image.BILINEAR)
    foto = ImageTk.PhotoImage(im)
    _ref = foto
    c.create_image(cx, cy, image=foto, tags=tag)


def dibujar(c, cx, cy, r, estado, nivel, fase, tag, fondo_tarjeta=None, transparente=False):
    """Dibuja la esfera centrada en (cx, cy) con radio base r."""
    global _ok_pil
    if Image is not None and _ok_pil:
        try:
            _dibujar_pil(c, cx, cy, r, estado, nivel, fase, tag)
            return
        except Exception:
            _ok_pil = False                         # sin ImageTk u otro fallo: se usa la esfera de siempre
    ca, cb = _paleta(estado)
    base = fondo_tarjeta or tema.FONDO
    hablando = estado == "hablando"
    amp = 0.035 + (0.22 * min(1.0, nivel * 2.2) if hablando else 0.03 * math.sin(fase * 0.8) + 0.02)
    respira = 1 + 0.035 * math.sin(fase * (1.1 if estado == "reposo" else 2.2))
    r = r * respira

    # resplandor (anillos que se desvanecen hacia el fondo)
    if not transparente:
        for k in range(10, 0, -1):
            rr = r * (1.0 + k * 0.06)
            fuerza = (0.012 + 0.05 * (1 if hablando else 0.5)) * (11 - k) / 10
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=tema.mezclar(base, cb, min(0.5, fuerza * 2)),
                          outline="", tags=tag)
    else:
        for k in range(5, 0, -1):
            rr = r * (1.0 + k * 0.10)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=tema.mezclar(base, cb, 0.10 + 0.05 * (6 - k)),
                          width=1, tags=tag)

    # anillo que late al escuchar
    if estado == "escuchando":
        pulso = (fase * 1.4) % 1.0
        rr = r * (1.05 + 0.5 * pulso)
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=tema.mezclar(base, ca, 0.7 * (1 - pulso)),
                      width=2, tags=tag)

    # capas de luz deformadas (la de atras mas grande y tenue)
    capas = (
        (1.00, 0.18, ca, 2, 0.0, 1.0),
        (0.90, 0.32, cb, 3, 1.7, -1.1),
        (0.80, 0.50, ca, 4, 3.1, 1.3),
        (0.68, 0.70, cb, 3, 4.6, -0.9),
    )
    for escala, brillo, col, lobulos, desfase, vel in capas:
        pts = _blob(cx, cy, r * escala, amp * (0.8 + 0.4 * escala), fase * vel + desfase, lobulos, fase * 0.2)
        c.create_polygon(pts, smooth=True, fill=tema.mezclar(base, col, brillo * 0.55),
                         outline=tema.mezclar(base, col, min(1.0, brillo + 0.25)), width=2, tags=tag)

    # nucleo luminoso
    n = r * 0.34 * (1 + 0.12 * nivel)
    c.create_oval(cx - n, cy - n, cx + n, cy + n, fill=tema.mezclar(ca, tema.TEXTO, 0.55), outline="", tags=tag)
    h = n * 0.45
    c.create_oval(cx - n * 0.55, cy - n * 0.62, cx - n * 0.55 + h, cy - n * 0.62 + h * 0.8,
                  fill=tema.mezclar(tema.TEXTO, "#ffffff", 0.5), outline="", tags=tag)

    # puntos que giran al pensar
    if estado == "pensando":
        for i in range(8):
            ang = fase * 1.8 + i * math.pi / 4
            rr = r * 1.22
            px, py = cx + rr * math.cos(ang), cy + rr * math.sin(ang)
            tam = 3 + 2 * (0.5 + 0.5 * math.sin(fase * 3 + i))
            c.create_oval(px - tam, py - tam, px + tam, py + tam,
                          fill=tema.mezclar(base, ca, 0.5 + 0.5 * math.sin(fase * 3 + i)), outline="", tags=tag)
