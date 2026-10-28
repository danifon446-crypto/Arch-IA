"""
aplicar_parche_agente.py
------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_agente.py

Qué hace (hace copia de respaldo antes y se puede correr dos veces sin problema):
  main.py: conecta el agente autónomo (carpeta core/agente/):
    1. un import,
    2. un hook en el ciclo de comandos, junto al de WhatsApp y mapa mental
       (solo reacciona a frases que empiezan con "agente ..." o "en minecraft ..."),
    3. al decir "adiós", detiene al agente y cierra Minecraft.

No cambia nada más: si no usas el agente, Arché funciona exactamente igual.
Si algo falla, deja main.py como estaba.
"""

import os
import py_compile
import shutil
import sys
import time

MAIN = "main.py"
CARPETA = os.path.join("core", "agente")
MARCA = "agente_arche"

IMPORT = "from core import agente as agente_arche          # agente autónomo (Minecraft y más entornos)\n"
HOOK = (
    "    # AGENTE AUTÓNOMO (core/agente): \"en minecraft consigue madera\", \"agente para\", \"agente ayuda\".\n"
    "    if agente_arche.manejar(comando_original):\n"
    "        continue\n"
    "\n"
)
SALIDA = "        agente_arche.detener_todo()   # el agente se detiene y se cierra Minecraft\n"

ANCLA_IMPORT = "from core.IA import enrutador_natural\n"
ANCLA_HOOK = '    if comando in ["adiós", "adios", "salir"]:\n'
ANCLA_SALIDA = "        detener_robot()   # el perro se queda quieto y se apaga el modo perro\n"


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


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
    texto = _una_vez(texto, n(ANCLA_IMPORT), n(ANCLA_IMPORT) + n(IMPORT), "import")
    texto = _una_vez(texto, n(ANCLA_HOOK), n(HOOK) + n(ANCLA_HOOK), "hook de comandos")
    texto = _una_vez(texto, n(ANCLA_SALIDA), n(ANCLA_SALIDA) + n(SALIDA), "salida")
    return texto, True


def main():
    if not os.path.exists(MAIN):
        sys.exit("Corre esto desde la carpeta Arche (donde está main.py).")
    necesarios = [os.path.join(CARPETA, n) for n in
                  ("__init__.py", "comandos.py", "coordinador.py", "modelos.py", "entornos/minecraft.py")]
    faltan = [r for r in necesarios if not os.path.exists(r)]
    if faltan:
        sys.exit("Faltan archivos del agente en core/agente/: " + ", ".join(faltan))

    original = _leer(MAIN)
    try:
        nuevo, cambio = parchar(original)
    except RuntimeError as e:
        sys.exit(str(e))
    if not cambio:
        print("Ya estaba aplicado; no cambié nada.")
        return

    respaldo = "respaldo_antes_agente_" + time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(respaldo, exist_ok=True)
    shutil.copy2(MAIN, os.path.join(respaldo, MAIN))
    try:
        _escribir(MAIN, nuevo)
        py_compile.compile(MAIN, doraise=True)
        for raiz, _, archivos in os.walk(CARPETA):
            for a in archivos:
                if a.endswith(".py"):
                    py_compile.compile(os.path.join(raiz, a), doraise=True)
    except Exception as e:
        _escribir(MAIN, original)
        sys.exit(f"Algo falló y dejé main.py como estaba: {e}")

    print("Listo. main.py conectado al agente.")
    print(f"  Copia de respaldo en: {respaldo}")
    print("Abre Arché y prueba:  agente prueba   (practica en un mundo de juguete, sin Minecraft)")
    print("Para Minecraft mira core/agente/LEEME.md  (necesitas Node.js 18+).")


if __name__ == "__main__":
    main()
