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
import shutil
import sys
import time

MAIN = "main.py"
MARCA = "nucleo_arche"
NUEVOS = [os.path.join("core", "nucleo", n) for n in (
    "__init__.py", "comun.py", "analista.py", "depredador.py", "cuarentena.py", "imaginacion.py", "equipo.py",
    "cronista.py", "fracasos_semilla.py", "ritmo.py", "guardian.py", "voz_viva.py", "avatar.py", "avatar_ventana.py")]

IMPORT = "from core import nucleo as nucleo_arche             # núcleo: habilidades, Depredador, equipo, Cronista, Guardián\n"

ARRANQUE = ("nucleo_arche.iniciar()                  # núcleo: niveles, caza, equipo, noticias, guardián, voz viva, avatar\n")

HOOK = (
    "        # NÚCLEO (core/nucleo): anota la hora (aprende tu ritmo) y atiende sus órdenes:\n"
    "        # «misión: ...», «caza ...», «ponme al día», «fracaso del día», «estado del guardián»...\n"
    "        # Va antes de partir en pasos para que «misión: X y luego Y» llegue entera.\n"
    "        nucleo_arche.registrar_actividad(comando_original)\n"
    "        if nucleo_arche.manejar(comando_original):\n"
    "            continue\n"
    "\n"
)

DETENER = "            nucleo_arche.detener_todo()   # el núcleo se detiene (misiones, avatar, reloj)\n"

# (ancla preferida, alternativas) — si tu main.py cambió un poco, se prueban las otras.
ANCLAS_IMPORT = ["from core import mapa_mental as mapa_mental_arche    # mapas mentales hechos por Arché\n",
                 "from core import evolucion as evolucion_arche    # evoluciona sola: sueño, curiosidad, se automodifica, reentrena\n"]
ANCLAS_ARRANQUE = ["evolucion_arche.iniciar()\n"]
ANCLAS_HOOK = ["        # VARIOS PASOS:", "        _pasos = [] if re.match("]
ANCLAS_DETENER = ["            agente_arche.detener_todo()", "            multitarea_arche.detener_todo()",
                  "            detener_robot()"]


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _una(texto, anclas, nombre):
    for a in anclas:
        if texto.count(a) == 1:
            return a
    raise RuntimeError(f"No encontré el lugar para «{nombre}» en main.py (o aparece más de una vez). "
                       "No se tocó nada. Mándale a Claude tu main.py y lo ajusta.")


def parchar(texto):
    if MARCA in texto:
        return texto, False
    nl = "\r\n" if "\r\n" in texto else "\n"
    n = lambda s: s.replace("\n", nl)

    a = n(_una(texto, [n(x) for x in ANCLAS_IMPORT], "imports"))
    texto = texto.replace(a, a + n(IMPORT))

    a = n(_una(texto, [n(x) for x in ANCLAS_ARRANQUE], "arranque"))
    texto = texto.replace(a, a + n(ARRANQUE))

    a = _una(texto, [n(x) for x in ANCLAS_HOOK], "gancho de órdenes")
    texto = texto.replace(a, n(HOOK) + a)

    a = _una(texto, [n(x) for x in ANCLAS_DETENER], "adiós")
    i = texto.index(a)
    fin = texto.index(nl, i) + len(nl)
    texto = texto[:fin] + n(DETENER) + texto[fin:]
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
