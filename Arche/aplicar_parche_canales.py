"""
aplicar_parche_canales.py
-------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_canales.py

Qué hace (hace copia de respaldo antes y se puede correr dos veces sin problema):
  1. main.py: conecta el canal de WhatsApp (core/canales.py, core/whatsapp.py) y el
     mapa mental real (core/mapa_mental.py).
  2. core/IA/cerebro.py: le prohíbe a la nube decir que abrió/dibujó cosas en el PC, y
     agrega un filtro: si aun así lo dice, Arché lo reemplaza por una respuesta honesta.

Antes de correrlo, los archivos nuevos deben estar en core/: canales.py, whatsapp.py, mapa_mental.py
"""

import os
import py_compile
import shutil
import sys
import time

MAIN = "main.py"
CEREBRO = os.path.join("core", "IA", "cerebro.py")
NUEVOS = [os.path.join("core", n) for n in ("canales.py", "whatsapp.py", "mapa_mental.py")]
MARCA_MAIN = "canales_arche"
MARCA_CEREBRO = "_afirma_accion_falsa"

IMPORTS = (
    "from core import canales as canales_arche            # mensajes por consola y por otros canales\n"
    "from core import whatsapp as whatsapp_arche          # Arché por WhatsApp\n"
    "from core import mapa_mental as mapa_mental_arche    # mapas mentales hechos por Arché\n"
)

ARRANQUE = (
    "canales_arche.instalar()                 # a partir de aquí input() recibe consola y WhatsApp\n"
    "whatsapp_arche.arrancar_si_corresponde()\n"
    "\n"
)

HOOK = (
    "    # MAPA MENTAL y CANAL DE WHATSAPP: los hace Arché de verdad, no la nube.\n"
    "    if mapa_mental_arche.manejar(comando_original):\n"
    "        continue\n"
    "    if whatsapp_arche.manejar(comando_original):\n"
    "        continue\n"
    "\n"
)

REGLA_NUBE = (
    '        "REGLA IMPORTANTE: tú solo conversas. Nunca digas ni insinúes que acabas de abrir una ventana, dibujar, '
    'crear un archivo, mover algo o hacer cualquier cosa en el computador, y no ofrezcas hacerlo '
    '(nada de \'¿quieres que lo dibuje?\'). Esas acciones las ejecuta Arché con órdenes concretas; si te piden algo '
    'que no sea una orden que existe, di con claridad que todavía no sabes hacerlo y que pueden decir \'comandos\'. "\n'
)

FILTRO = '''

# ----------------------------------------------------------------------
# Filtro anti-"hice algo en el PC": la nube SOLO conversa. Si en su texto afirma
# que abrió/dibujó/creó algo en el equipo, es mentira (ella no controla nada):
# Arché lo reemplaza por una respuesta honesta y no la guarda ni aprende de ella.
# ----------------------------------------------------------------------

_CONTEXTO_PC = re.compile(r"\\b(ventana|lienzo|aplicacion de dibujo|programa de dibujo|paint|pantalla|"
                          r"archivo|carpeta|navegador|la imagen|el mapa|el lienzo)\\b")
_YO_LO_HICE = re.compile(r"\\b(abro|abri|abrire|creo|cree|dibujo|dibuje|trazo|trace|genero|genere|guardo|guarde|"
                         r"muestro|mostre|coloco|llevo|maximizo|"
                         r"ya (?:esta|tienes|puedes ver)|(?:esta|queda) (?:abierta|abierto|lista|listo)|"
                         r"deberias verl[ao])\\b")


def _afirma_accion_falsa(texto):
    t = _sin_tildes((texto or "").lower())
    t = re.sub(r"\\bcreo que\\b", "", t)
    return bool(_CONTEXTO_PC.search(t) and _YO_LO_HICE.search(t))


_MENSAJE_HONESTO = ("No hice eso: la parte de mí que conversa solo puede hablar, no abrir ventanas ni dibujar. "
                    "Si es una acción del PC, necesito una orden que Arché ya tenga (di 'comandos'); "
                    "si todavía no existe, dímelo y la agregamos.")


def responder(pregunta):
    """Igual que antes, pero sin dejar pasar respuestas que afirman acciones que no ocurrieron."""
    r = _responder_sin_filtro(pregunta)
    if _afirma_accion_falsa(r.get("texto", "")):
        if r.get("fuente") == "nube" and len(_historial) >= 2:
            del _historial[-2:]              # que la nube no aprenda de su propia mentira
        r = dict(r, texto=_MENSAJE_HONESTO, fuente="arche", aviso="", cacheable=False, web=False)
    return r
'''


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _reemplazar_una_vez(texto, ancla, nuevo, nombre):
    if texto.count(ancla) != 1:
        raise RuntimeError(f"No encontré (o hay varias) la línea de referencia de «{nombre}» en el archivo. "
                           "No se tocó nada.")
    return texto.replace(ancla, nuevo)


def parchar_main(texto):
    if MARCA_MAIN in texto:
        return texto, False
    nl = "\r\n" if "\r\n" in texto else "\n"
    n = lambda s: s.replace("\n", nl)
    texto = _reemplazar_una_vez(texto, n("from core.IA import enrutador_natural\n"),
                                n("from core.IA import enrutador_natural\n") + n(IMPORTS), "imports")
    texto = _reemplazar_una_vez(texto, n("_cola_comandos_naturales = []\n\nwhile True:\n"),
                                n("_cola_comandos_naturales = []\n\n") + n(ARRANQUE) + n("while True:\n"), "arranque")
    ancla = n('    if comando in ["adiós", "adios", "salir"]:\n')
    texto = _reemplazar_una_vez(texto, ancla, n(HOOK) + ancla, "hook de comandos")
    return texto, True


def parchar_cerebro(texto):
    if MARCA_CEREBRO in texto:
        return texto, False
    nl = "\r\n" if "\r\n" in texto else "\n"
    n = lambda s: s.replace("\n", nl)
    ancla = '        "No inventes cómo funciona Arché por dentro; si no lo sabes, dilo. "\n'
    texto = _reemplazar_una_vez(texto, n(ancla), n(ancla) + n(REGLA_NUBE), "regla del prompt")
    texto = _reemplazar_una_vez(texto, "def responder(pregunta):", "def _responder_sin_filtro(pregunta):", "responder")
    if not texto.endswith(nl):
        texto += nl
    texto += n(FILTRO)
    return texto, True


def main():
    if not (os.path.exists(MAIN) and os.path.exists(CEREBRO)):
        sys.exit("Corre esto desde la carpeta Arche (donde está main.py).")
    faltan = [n for n in NUEVOS if not os.path.exists(n)]
    if faltan:
        sys.exit("Faltan archivos nuevos en core/: " + ", ".join(os.path.basename(f) for f in faltan))

    originales = {ruta: _leer(ruta) for ruta in (MAIN, CEREBRO)}
    try:
        nuevo_main, cambio_main = parchar_main(originales[MAIN])
        nuevo_cerebro, cambio_cerebro = parchar_cerebro(originales[CEREBRO])
    except Exception as e:
        sys.exit(str(e))

    if not (cambio_main or cambio_cerebro):
        print("Ya estaba aplicado; no cambié nada.")
        return

    respaldo = "respaldo_antes_canales_" + time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(respaldo, exist_ok=True)
    for ruta in (MAIN, CEREBRO):
        shutil.copy2(ruta, os.path.join(respaldo, os.path.basename(ruta)))

    try:
        if cambio_main:
            _escribir(MAIN, nuevo_main)
        if cambio_cerebro:
            _escribir(CEREBRO, nuevo_cerebro)
        for ruta in (MAIN, CEREBRO) + tuple(NUEVOS):
            py_compile.compile(ruta, doraise=True)
    except Exception as e:
        for ruta, contenido in originales.items():
            _escribir(ruta, contenido)
        sys.exit(f"Algo falló y dejé todo como estaba: {e}")

    print("Listo.")
    print(f"  main.py: {'modificado' if cambio_main else 'ya estaba'}")
    print(f"  cerebro.py: {'modificado' if cambio_cerebro else 'ya estaba'}")
    print(f"  Copia de respaldo en: {respaldo}")
    print("Abre Arché y prueba: 'mapa mental de fuerzas' y 'conectar whatsapp'.")


if __name__ == "__main__":
    main()