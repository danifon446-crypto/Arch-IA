"""
escenas.py
----------
Ubicacion: Arche/core/interfaz/escenas.py

Escenas ambientales ligeras que se dibujan detras de los paneles: gradiente,
particulas, ondas, rejilla y nebulosa. Todas se calculan con unas pocas
lineas y ovalos (nada pesado), y respetan la intensidad, la velocidad y el
brillo de Ajustes. Con "reducir movimiento" o el modo ahorro quedan quietas
o se reducen a un gradiente.
"""

import math
import random

from . import ajustes, tema

ESCENAS = ("ninguna", "gradiente", "particulas", "ondas", "rejilla", "nebulosa")

_particulas = []
_semilla = random.Random(7)


def _color(brillo):
    """Color del trazo: del tema, mas o menos presente segun el brillo."""
    return tema.mezclar(tema.FONDO, tema.MORADO_CLARO, 0.08 + 0.45 * brillo / 100.0)


def _reiniciar(n, W, H):
    global _particulas
    _particulas = [[_semilla.random() * W, _semilla.random() * H, _semilla.uniform(0.2, 1.0),
                    _semilla.uniform(-0.3, 0.3), _semilla.uniform(0.2, 1.0)] for _ in range(n)]


def dibujar(v, W, H, fase, quieto=False):
    """Dibuja la escena con el tag actual de v (se borra y redibuja cada cuadro). Devuelve cuantos items dibujo."""
    escena = ajustes.obtener("escena")
    if escena in ("ninguna", "gradiente"):
        return 0                                    # el gradiente es parte del fondo estatico
    c = v.canvas
    tag = v._tag
    inten = ajustes.obtener("escena_intensidad") / 100.0
    brillo = ajustes.obtener("escena_brillo")
    vel = ajustes.obtener("escena_velocidad") / 100.0 * (0.0 if quieto else 1.0)
    tope = max(1, int(ajustes.obtener("efectos_simultaneos")))
    t = fase * vel
    col = _color(brillo)
    n = 0
    if escena == "particulas":
        cant = int((10 + 70 * inten) * (0.4 + 0.6 * tope / 10))
        if len(_particulas) != cant:
            _reiniciar(cant, W, H)
        for p in _particulas:
            p[1] -= p[2] * 0.7 * vel * (0.6 + p[4])
            p[0] += p[3] * vel + math.sin(t * 0.5 + p[4] * 6) * 0.15 * vel
            if p[1] < -6:
                p[0], p[1] = _semilla.random() * W, H + 6
            if p[0] < -6 or p[0] > W + 6:
                p[0] = _semilla.random() * W
            r = 1 + 2.2 * p[2]
            c.create_oval(p[0] - r, p[1] - r, p[0] + r, p[1] + r, fill=tema.mezclar(tema.FONDO, tema.MORADO_CLARO, (0.15 + 0.5 * p[4]) * brillo / 100.0 + 0.05),
                          outline="", tags=tag)
            n += 1
    elif escena == "ondas":
        capas = max(1, min(5, int(1 + 4 * inten * tope / 10)))
        pasos = 28
        for k in range(capas):
            base = H * (0.62 + 0.09 * k)
            amp = H * (0.025 + 0.02 * inten) * (1 + 0.25 * k)
            pts = []
            for i in range(pasos + 1):
                x = W * i / pasos
                pts += [x, base + amp * math.sin(x / (W / (2.2 + k * 0.7)) + t * (0.8 + 0.3 * k) + k)]
            c.create_line(*pts, fill=tema.mezclar(tema.FONDO, tema.AZUL_CLARO if k % 2 else tema.MORADO_CLARO,
                                                 (0.10 + 0.4 * brillo / 100.0) * (1 - k * 0.12)), width=2, smooth=True, tags=tag)
            n += 1
    elif escena == "rejilla":
        horizonte = H * 0.55
        lineas_v = int(6 + 10 * inten)
        for i in range(-lineas_v, lineas_v + 1):
            x_base = W / 2 + i * (W / lineas_v) * 0.9
            c.create_line(W / 2 + (x_base - W / 2) * 0.05, horizonte, x_base, H, fill=col, tags=tag)
            n += 1
        filas = 7
        for j in range(filas):
            f = ((j + (t * 0.35) % 1.0) / filas) ** 2
            y = horizonte + (H - horizonte) * f
            c.create_line(0, y, W, y, fill=col, tags=tag)
            n += 1
    elif escena == "nebulosa":
        manchas = max(2, min(6, int(2 + 4 * inten * tope / 10)))
        for k in range(manchas):
            ang = t * (0.12 + 0.03 * k) + k * 2.1
            cx = W * (0.5 + 0.34 * math.cos(ang))
            cy = H * (0.5 + 0.30 * math.sin(ang * 1.3))
            for anillo in range(4, 0, -1):
                r = min(W, H) * (0.07 + 0.05 * anillo + 0.01 * k)
                mezcla = (0.03 + 0.06 * (5 - anillo)) * brillo / 100.0 * (0.7 + 0.6 * inten)
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              fill=tema.mezclar(tema.FONDO, tema.AZUL if k % 2 else tema.MORADO, mezcla), outline="", tags=tag)
                n += 1
    return n


def gradiente(c, W, H):
    """Gradiente de fondo (parte estatica). Con la escena 'gradiente' es mas marcado."""
    fuerte = ajustes.obtener("escena") == "gradiente"
    bandas = 40
    arriba = tema.mezclar(tema.FONDO, tema.MORADO, 0.30 if fuerte else 0.12)
    abajo = tema.mezclar(tema.FONDO, tema.AZUL, 0.22) if fuerte else tema.FONDO
    for i in range(bandas):
        t = i / (bandas - 1)
        c.create_rectangle(0, H * i / bandas, W, H * (i + 1) / bandas + 1, fill=tema.mezclar(arriba, abajo, t),
                           outline="", tags="fondo")
