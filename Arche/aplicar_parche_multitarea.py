"""
aplicar_parche_multitarea.py
----------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_multitarea.py

Qué hace (hace copia de respaldo antes y se puede correr dos veces sin problema):
  main.py: conecta la multitarea (core/multitarea.py):
    1. un import,
    2. le pasa la lista de herramientas (los mismos manejar() que usa el bucle),
    3. un hook al principio del bucle, ANTES de partir "X y luego Y" en pasos
       (solo reacciona a "en segundo plano ...", "a la vez ...", "tareas",
       "para la tarea N", "tarea N sí/no"...),
    4. al decir "adiós", pide parar a las tareas de fondo.

No cambia nada más: si no usas esas frases, Arché funciona exactamente igual.
Si algo falla, deja main.py como estaba.
"""

import os
import py_compile
import shutil
import sys
import time

MAIN = "main.py"
MODULO = os.path.join("core", "multitarea.py")
MARCA = "multitarea_arche"

IMPORT = "from core import multitarea as multitarea_arche    # varias herramientas a la vez (tareas de fondo)\n"

CONFIGURAR = (
    "\n"
    "# MULTITAREA (core/multitarea.py): las mismas herramientas del bucle, en el mismo\n"
    "# orden, para poder correrlas de fondo y varias a la vez.\n"
    "multitarea_arche.configurar([\n"
    "    (\"mapa mental\", mapa_mental_arche.manejar),\n"
    "    (\"seguridad\", seguridad_arche.manejar),\n"
    "    (\"agente\", agente_arche.manejar),\n"
    "    (\"perro robot\", manejar_robot),\n"
    "    (\"memoria nube\", memoria_nube_arche.manejar),\n"
    "    (\"modelo nuevo\", modelo_nuevo_arche.manejar),\n"
    "    (\"mejora continua\", mejora_arche.manejar),\n"
    "    (\"pendientes\", pendientes_arche.manejar),\n"
    "    (\"autonomia\", autonomia_arche.manejar),\n"
    "    (\"voz\", voz_arche.manejar),\n"
    "    (\"alarmas\", alarmas_arche.manejar),\n"
    "    (\"rutinas\", rutinas_arche.manejar),\n"
    "    (\"pc avanzado\", pc_avanzado.manejar),\n"
    "    (\"interfaz\", interfaz_arche.manejar),\n"
    "    (\"internet y nube\", cerebro_nube.manejar),\n"
    "    (\"aprender de la nube\", aprender_de_nube.manejar),\n"
    "    (\"red de aprendizaje\", red_arche.manejar),\n"
    "    (\"github\", git_arche.manejar),\n"
    "    (\"control del pc\", acciones_pc.manejar),\n"
    "    (\"comandos extra\", comandos_extra.manejar),\n"
    "])\n"
)

# (sin sangría: se les pone la misma que tenga la línea de referencia)
HOOK = (
    "# MULTITAREA: \"en segundo plano ...\", \"a la vez X y Y\", \"tareas\", \"para la tarea 2\".\n"
    "# Va antes de partir en pasos: \"a la vez X y Y\" es en paralelo, no uno tras otro.\n"
    "if multitarea_arche.manejar(comando_original):\n"
    "    continue\n"
    "\n"
)
SALIDA = "multitarea_arche.detener_todo()   # las tareas de fondo paran\n"

ANCLA_IMPORT = "from core import agente as agente_arche"
ANCLA_CONFIG = "canales_arche.instalar()"
ANCLA_HOOK = "# VARIOS PASOS: \"abre chrome y luego busca gatos en youtube\" -> se parte en"
ANCLA_SALIDA = "detener_robot()   # el perro se queda quieto y se apaga el modo perro"


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _linea_que_empieza(texto, inicio, nombre):
    """Devuelve la línea completa (con su salto) que empieza con 'inicio'. Debe haber una sola."""
    lineas = [l for l in texto.splitlines(keepends=True) if l.startswith(inicio)]
    if len(lineas) != 1:
        raise RuntimeError(f"No encontré (o hay varias) la línea de referencia de «{nombre}» en main.py. "
                           "No se tocó nada.")
    return lineas[0]


def _linea_con(texto, contenido, nombre):
    """La línea completa cuyo contenido (sin sangría) empieza con 'contenido', y su sangría.
    Así el parche sirve tenga el bucle la sangría que tenga."""
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

    linea_import = _linea_que_empieza(texto, ANCLA_IMPORT, "import del agente")
    texto = _una_vez(texto, linea_import, linea_import + n(IMPORT), "import")

    linea_config = _linea_que_empieza(texto, ANCLA_CONFIG, "canales_arche.instalar()")
    texto = _una_vez(texto, linea_config, linea_config + n(CONFIGURAR), "configurar")

    linea_hook, sangria = _linea_con(texto, ANCLA_HOOK, "hook de comandos")
    texto = _una_vez(texto, linea_hook, n(_sangrar(HOOK, sangria)) + linea_hook, "hook de comandos")

    linea_salida, sangria = _linea_con(texto, ANCLA_SALIDA, "salida")
    texto = _una_vez(texto, linea_salida, linea_salida + n(_sangrar(SALIDA, sangria)), "salida")
    return texto, True


def main():
    if not os.path.exists(MAIN):
        sys.exit("Corre esto desde la carpeta Arche (donde está main.py).")
    if not os.path.exists(MODULO):
        sys.exit("Falta core/multitarea.py. Cópialo primero dentro de Arche/core/.")

    original = _leer(MAIN)
    try:
        nuevo, cambio = parchar(original)
    except RuntimeError as e:
        sys.exit(str(e))
    if not cambio:
        print("main.py ya tenía la multitarea conectada. No hice nada.")
        return

    respaldo = f"main_antes_multitarea_{time.strftime('%Y%m%d_%H%M%S')}.py"
    shutil.copy2(MAIN, respaldo)
    _escribir(MAIN, nuevo)
    try:
        py_compile.compile(MAIN, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(respaldo, MAIN)
        sys.exit(f"El main.py nuevo no compila; lo dejé como estaba.\n{e}")
    print(f"Listo. Copia de respaldo: {respaldo}")
    print("Ahora corre:  python prueba_multitarea.py")


if __name__ == "__main__":
    main()
