"""
latido.py
---------
Ubicacion: Arche/core/IA/latido.py

Muestra que algo largo sigue vivo. Mientras el bloque 'with' trabaja,
imprime cada pocos segundos un aviso con el tiempo transcurrido. Si el
bloque falla, el error sale igual que siempre (no se traga nada).

Uso:
    from core.IA.latido import latido

    with latido("Reentrenando las redes"):
        aprendizaje.reentrenar_ahora()

Salida:
    Arché: Reentrenando las redes... sigue trabajando (5s)
    Arché: Reentrenando las redes... sigue trabajando (10s)
    Arché: Reentrenando las redes... listo en 12s
"""

import threading
import time
from contextlib import contextmanager

CADA_SEGUNDOS = 5


@contextmanager
def latido(etiqueta, cada=CADA_SEGUNDOS, silencioso=False):
    if silencioso:
        yield
        return

    parar = threading.Event()
    t_ini = time.time()

    def _avisar():
        while not parar.wait(cada):
            print(f"Arché: {etiqueta}... sigue trabajando ({time.time() - t_ini:.0f}s)", flush=True)

    hilo = threading.Thread(target=_avisar, daemon=True)
    hilo.start()
    try:
        yield
    except BaseException:
        parar.set()
        print(f"Arché: {etiqueta}... se detuvo con error a los {time.time() - t_ini:.0f}s", flush=True)
        raise
    else:
        parar.set()
        print(f"Arché: {etiqueta}... listo en {time.time() - t_ini:.0f}s", flush=True)
    finally:
        parar.set()