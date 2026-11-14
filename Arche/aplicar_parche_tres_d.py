"""
aplicar_parche_tres_d.py
------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_tres_d.py

Qué hace (hace copia de respaldo antes y se puede correr dos veces sin problema):
  main.py: conecta Arché 3D (carpeta core/tres_d/):
    1. un import,
    2. un hook en el ciclo de comandos, junto al de mapa mental
       (solo reacciona a frases de 3D: «crea una caja de 80x50x30», «abre el
       taller 3d», «analiza el modelo», «ayuda 3d»...),
    3. al decir "adiós", cierra el taller 3D,
    4. si ya tienes la multitarea, agrega el 3D a sus herramientas (para poder
       decir «en segundo plano diseña en 3d un llavero»).

Sirve tengas o no los parches de blindaje y multitarea, y en cualquier orden.
Si algo falla, deja main.py como estaba.
"""

import os
import py_compile
import shutil
import sys
import time

MAIN = "main.py"
CARPETA = os.path.join("core", "tres_d")
MARCA = "tres_d_arche"

IMPORT = "from core import tres_d as tres_d_arche            # Arché 3D: piezas a medida, análisis para imprimir y taller\n"
# (sin sangría: se les pone la misma que tenga la línea de referencia)
HOOK = (
    "# ARCHÉ 3D (core/tres_d): \"crea una caja de 80x50x30 con tapa\", \"analiza el modelo\", \"abre el taller 3d\".\n"
    "if tres_d_arche.manejar(comando_original):\n"
    "    continue\n"
)
SALIDA = "tres_d_arche.detener_todo()       # se cierra el taller 3D\n"
HERRAMIENTA = "    (\"3d\", tres_d_arche.manejar),\n"

ANCLA_IMPORT = "from core import agente as agente_arche"
ANCLA_HOOK = "if mapa_mental_arche.manejar(comando_original):"
ANCLA_SALIDA = "detener_robot()   # el perro se queda quieto y se apaga el modo perro"
ANCLA_MULTITAREA = "    (\"mapa mental\", mapa_mental_arche.manejar),"


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _linea_con(texto, contenido, nombre):
    """La línea completa cuyo contenido (sin sangría) empieza con 'contenido', y su sangría."""
    lineas = [l for l in texto.splitlines(keepends=True) if l.lstrip().startswith(contenido)]
    if len(lineas) != 1:
        raise RuntimeError(f"No encontré (o hay varias) la línea de referencia de «{nombre}» en main.py. "
                           "No se tocó nada.")
    linea = lineas[0]
    return linea, linea[:len(linea) - len(linea.lstrip())]


def _sangrar(bloque, sangria):
    return "".join((sangria + l) if l.strip() else l for l in bloque.splitlines(keepends=True))


def _una_vez(texto, ancla, nuevo, nombre):
    if texto.count(ancla) != 1:
        raise RuntimeError(f"No encontré (o hay varias) la línea de referencia de «{nombre}» en main.py. "
                           "No se tocó nada.")
    return texto.replace(ancla, nuevo)


def parchar(texto):
    if MARCA in texto:
        return texto, False
    nl = "\r\n" if "\r\n" in texto else "\n"
    n = lambda s: s.replace("\n", nl)

    linea, _ = _linea_con(texto, ANCLA_IMPORT, "import del agente")
    texto = _una_vez(texto, linea, linea + n(IMPORT), "import")

    linea, sangria = _linea_con(texto, ANCLA_HOOK, "hook de comandos")
    texto = _una_vez(texto, linea, n(_sangrar(HOOK, sangria)) + linea, "hook de comandos")

    linea, sangria = _linea_con(texto, ANCLA_SALIDA, "salida")
    texto = _una_vez(texto, linea, linea + n(_sangrar(SALIDA, sangria)), "salida")

    if "multitarea_arche.configurar([" in texto and texto.count(n(ANCLA_MULTITAREA + "\n")) == 1:
        texto = texto.replace(n(ANCLA_MULTITAREA + "\n"), n(ANCLA_MULTITAREA + "\n") + n(HERRAMIENTA))
    return texto, True


def main():
    if not os.path.exists(MAIN):
        sys.exit("Corre esto desde la carpeta Arche (donde está main.py).")
    necesarios = [os.path.join(CARPETA, n) for n in
                  ("__init__.py", "geometria.py", "piezas.py", "disenador.py", "servidor.py",
                   os.path.join("web", "index.html"), os.path.join("web", "lib", "three.module.min.js"))]
    faltan = [r for r in necesarios if not os.path.exists(r)]
    if faltan:
        sys.exit("Faltan archivos de Arché 3D en core/tres_d/: " + ", ".join(faltan))

    original = _leer(MAIN)
    try:
        nuevo, cambio = parchar(original)
    except RuntimeError as e:
        sys.exit(str(e))
    if not cambio:
        print("main.py ya tenía Arché 3D conectado. No hice nada.")
        return
    respaldo = f"main_antes_tres_d_{time.strftime('%Y%m%d_%H%M%S')}.py"
    shutil.copy2(MAIN, respaldo)
    _escribir(MAIN, nuevo)
    try:
        py_compile.compile(MAIN, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(respaldo, MAIN)
        sys.exit(f"El main.py nuevo no compila; lo dejé como estaba.\n{e}")
    print(f"Listo. Copia de respaldo: {respaldo}")
    print("Ahora corre:  python prueba_tres_d.py   y luego abre Arché y di «abre el taller 3d».")


if __name__ == "__main__":
    main()
