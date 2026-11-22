"""
aplicar_parche_nucleo.py
------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_nucleo.py

Qué hace en main.py (hace copia de respaldo antes y se puede correr dos veces sin problema):
  1. importa core/nucleo
  2. lo arranca después de la evolución (núcleo, Depredador, equipo, Cronista, Guardián,
     conversación viva y avatar quedan funcionando en segundo plano)
  3. con cada orden: anota la hora (para aprender tu ritmo) y le pregunta al núcleo si la
     frase es suya, ANTES de partirla en pasos (así «misión: investiga X y luego Y» no se parte)
  4. al decir «adiós», detiene el núcleo

No toca ningún otro archivo. Para deshacerlo: copia main_antes_nucleo_FECHA.py encima de main.py.
"""

import os
import py_compile
import re
import shutil
import sys
import time

MAIN = "main.py"
MARCA = "nucleo_arche"
NUEVOS = [os.path.join("core", "nucleo", n) for n in (
    "__init__.py", "comun.py", "analista.py", "depredador.py", "cuarentena.py", "imaginacion.py", "equipo.py",
    "cronista.py", "fracasos_semilla.py", "ritmo.py", "guardian.py", "voz_viva.py", "avatar.py", "avatar_dibujo.py", "limpieza.py", "resolver.py")]

IMPORT = "from core import nucleo as nucleo_arche             # núcleo: habilidades, Depredador, equipo, Cronista, Guardián\n"

ARRANQUE = ("nucleo_arche.iniciar()                  # núcleo: niveles, caza, equipo, noticias, guardián, voz viva, avatar\n")

# El gancho y el «adiós» se escriben con la MISMA sangría que tenga tu main.py
# (hay versiones con el bucle dentro de un try y otras sin él).
HOOK = (
    "# NÚCLEO (core/nucleo): anota la hora (aprende tu ritmo) y atiende sus órdenes:\n"
    "# «misión: ...», «caza ...», «ponme al día», «fracaso del día», «estado del guardián»...\n"
    "# Va antes de partir en pasos para que «misión: X y luego Y» llegue entera.\n"
    "nucleo_arche.registrar_actividad(comando_original)\n"
    "if nucleo_arche.manejar(comando_original):\n"
    "    continue\n"
    "\n"
)

DETENER = "nucleo_arche.detener_todo()   # el núcleo se detiene (misiones, avatar, reloj)\n"

ANCLAS_IMPORT = ["from core import mapa_mental as mapa_mental_arche",
                 "from core import evolucion as evolucion_arche",
                 "from core.IA import enrutador_natural"]
ANCLAS_ARRANQUE = ["evolucion_arche.iniciar()"]
# Regex (en orden de preferencia). El grupo 1 es la sangría de esa línea.
ANCLAS_HOOK = [r"^([ \t]+)# VARIOS PASOS:", r"^([ \t]+)_pasos = \[\] if re\.match\(",
               r"^([ \t]+)if not comando:\s*$"]
ANCLAS_DETENER = [r"^([ \t]+)agente_arche\.detener_todo\(\)", r"^([ \t]+)multitarea_arche\.detener_todo\(\)",
                  r"^([ \t]+)detener_robot\(\)", r"^([ \t]+)responder_conversacion\(\"adios\"\)"]


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _error(nombre):
    raise RuntimeError(f"No encontré el lugar para «{nombre}» en main.py (o aparece más de una vez). "
                       "No se tocó nada. Mándale a Claude tu main.py y lo ajusta.")


def _linea_completa(texto, inicio_linea, nombre):
    """La línea (sin el salto) que empieza exactamente con 'inicio_linea', si hay una sola."""
    lineas = [l for l in texto.splitlines() if l.startswith(inicio_linea)]
    if len(lineas) != 1:
        return None
    return lineas[0]


def _con_sangria(bloque, sangria, nl):
    return "".join((sangria + l if l.strip() else "") + nl for l in bloque.split("\n")[:-1])


def parchar(texto):
    if MARCA in texto:
        return texto, False
    nl = "\r\n" if "\r\n" in texto else "\n"

    # 1. import (después de una línea de import conocida)
    linea = next((l for a in ANCLAS_IMPORT for l in [_linea_completa(texto, a, "imports")] if l), None)
    if not linea:
        _error("imports")
    texto = texto.replace(linea + nl, linea + nl + IMPORT.replace("\n", nl), 1)

    # 2. arranque (después de evolucion_arche.iniciar(), sin sangría)
    linea = _linea_completa(texto, ANCLAS_ARRANQUE[0], "arranque")
    if not linea:
        _error("arranque")
    texto = texto.replace(linea + nl, linea + nl + ARRANQUE.replace("\n", nl), 1)

    # 3. gancho de órdenes (antes de partir en pasos), con la sangría del bucle
    for patron in ANCLAS_HOOK:
        encontrados = list(re.finditer(patron, texto, re.M))
        if len(encontrados) == 1:
            m = encontrados[0]
            sangria = m.group(1)
            if patron.endswith(r"if not comando:\s*$"):
                # va DESPUÉS de "if not comando: continue"
                fin = texto.index(nl, texto.index(nl, m.end()) + len(nl)) + len(nl)
                texto = texto[:fin] + nl + _con_sangria(HOOK, sangria, nl) + texto[fin:]
            else:
                texto = texto[:m.start()] + _con_sangria(HOOK, sangria, nl) + texto[m.start():]
            break
    else:
        _error("gancho de órdenes")

    # 4. al decir «adiós»
    for patron in ANCLAS_DETENER:
        encontrados = list(re.finditer(patron, texto, re.M))
        if len(encontrados) == 1:
            m = encontrados[0]
            fin = texto.index(nl, m.start()) + len(nl)
            texto = texto[:fin] + m.group(1) + DETENER.replace("\n", nl) + texto[fin:]
            break
    else:
        _error("adiós")
    return texto, True


def main():
    if not os.path.exists(MAIN):
        sys.exit("Corre esto desde la carpeta Arche (donde está main.py).")
    faltan = [f for f in NUEVOS if not os.path.exists(f)]
    if faltan:
        sys.exit("Faltan archivos nuevos (copia la carpeta core/nucleo completa): " + ", ".join(faltan))
    for f in NUEVOS:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            sys.exit(f"{f} tiene un error: {e}")

    original = _leer(MAIN)
    try:
        nuevo, cambio = parchar(original)
    except RuntimeError as e:
        sys.exit(str(e))
    if not cambio:
        print("Ya estaba aplicado; no cambié nada.")
        return

    respaldo = "main_antes_nucleo_" + time.strftime("%Y%m%d_%H%M%S") + ".py"
    shutil.copy2(MAIN, respaldo)
    try:
        _escribir(MAIN, nuevo)
        py_compile.compile(MAIN, doraise=True)
    except Exception as e:
        _escribir(MAIN, original)
        sys.exit(f"Algo falló y dejé main.py como estaba: {e}")

    print("Listo. main.py quedó conectado al núcleo.")
    print(f"  Copia de respaldo: {respaldo}")
    print("Ahora:")
    print("  1. python prueba_nucleo.py       -> debe decir que todo pasó")
    print("  2. python seguridad.py sellar    -> para que el guardián de seguridad apruebe los archivos nuevos")
    print("  3. Abre Arché y di: «qué hay de nuevo»")


if __name__ == "__main__":
    main()
