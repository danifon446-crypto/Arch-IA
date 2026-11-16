"""
aplicar_parche_raphael.py
-------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_raphael.py

Qué hace en main.py (hace copia de respaldo antes y se puede correr dos veces sin problema):
  1. importa core/raphael
  2. lo arranca después de la evolución (Gran Sabio, Depredador, Tempest, Cronista, Guardián,
     conversación viva y avatar quedan funcionando en segundo plano)
  3. con cada orden: anota la hora (para aprender tu ritmo) y le pregunta a Raphael si la
     frase es suya, ANTES de partirla en pasos (así «misión: investiga X y luego Y» no se parte)
  4. al decir «adiós», detiene a Raphael

No toca ningún otro archivo. Para deshacerlo: copia main_antes_raphael_FECHA.py encima de main.py.
"""

import os
import py_compile
import shutil
import sys
import time

MAIN = "main.py"
MARCA = "raphael_arche"
NUEVOS = [os.path.join("core", "raphael", n) for n in (
    "__init__.py", "comun.py", "sabio.py", "depredador.py", "jaula.py", "imaginacion.py", "tempest.py",
    "cronista.py", "fracasos_semilla.py", "ritmo.py", "guardian.py", "voz_viva.py", "avatar.py")]

IMPORT = "from core import raphael as raphael_arche             # Gran Sabio/Raphael, Depredador, Tempest, Cronista, Guardián\n"

ARRANQUE = ("raphael_arche.iniciar()                  # Raphael: rangos, caza, equipo, noticias, guardián, voz viva, avatar\n")

HOOK = (
    "        # RAPHAEL (core/raphael): anota la hora (aprende tu ritmo) y atiende sus órdenes:\n"
    "        # «misión: ...», «caza ...», «ponme al día», «fracaso del día», «estado del guardián»...\n"
    "        # Va antes de partir en pasos para que «misión: X y luego Y» llegue entera.\n"
    "        raphael_arche.registrar_actividad(comando_original)\n"
    "        if raphael_arche.manejar(comando_original):\n"
    "            continue\n"
    "\n"
)

DETENER = "            raphael_arche.detener_todo()   # Raphael se detiene (misiones, avatar, reloj)\n"

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
        sys.exit("Faltan archivos nuevos (copia la carpeta core/raphael completa): " + ", ".join(faltan))
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

    respaldo = "main_antes_raphael_" + time.strftime("%Y%m%d_%H%M%S") + ".py"
    shutil.copy2(MAIN, respaldo)
    try:
        _escribir(MAIN, nuevo)
        py_compile.compile(MAIN, doraise=True)
    except Exception as e:
        _escribir(MAIN, original)
        sys.exit(f"Algo falló y dejé main.py como estaba: {e}")

    print("Listo. main.py quedó conectado a Raphael.")
    print(f"  Copia de respaldo: {respaldo}")
    print("Ahora:")
    print("  1. python prueba_raphael.py      -> debe decir que todo pasó")
    print("  2. python seguridad.py sellar    -> para que el guardián de seguridad apruebe los archivos nuevos")
    print("  3. Abre Arché y di: «qué hay de nuevo»")


if __name__ == "__main__":
    main()
