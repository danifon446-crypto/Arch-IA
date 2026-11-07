"""
diagnostico_atajos.py
---------------------
Ubicacion: Arche/diagnostico_atajos.py

Si los atajos (Ctrl+Alt+A, Ctrl+Alt+I...) no hacen nada, corre esto:
    python diagnostico_atajos.py
y mándale a Claude lo que salga.
"""

import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
CARPETA_LOGS = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Arche", "logs")
LOG = os.path.join(CARPETA_LOGS, "arche_fondo.log")
LOCK = os.path.join(CARPETA_LOGS, "arche_fondo.lock")


def titulo(t):
    print("\n=== " + t + " ===")


def arche_corriendo():
    if not os.path.exists(LOCK):
        return False
    try:
        import msvcrt
        with open(LOCK, "a+") as f:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                return False                  # pude tomar el candado: nadie lo tiene
            except OSError:
                return True
    except ImportError:
        return None


titulo("1. ¿Arché está corriendo en segundo plano?")
c = arche_corriendo()
print({True: "Sí (arche_fondo.pyw está vivo).",
       False: "NO. Ábrela con doble clic a arche_fondo.pyw (no con main.py: main.py no trae atajos).",
       None: "No sé (no es Windows)."}[c])

titulo("2. ¿Los atajos están tomados?")
if sys.platform == "win32":
    import ctypes
    from core import presencia
    for clave in ("atajo_burbuja", "atajo_interfaz", "atajo_microfono"):
        combo = presencia.CONFIG[clave]
        mods, tecla = presencia._traducir_atajo(combo)
        if ctypes.windll.user32.RegisterHotKey(None, 99, mods, tecla):
            ctypes.windll.user32.UnregisterHotKey(None, 99)
            print(f"{combo}: LIBRE -> nadie lo está usando" + (" (Arché NO lo registró)" if c else ""))
        else:
            print(f"{combo}: ocupado" + (" (seguramente por Arché: bien)" if c else " por OTRO programa"))
else:
    print("Solo se puede revisar en Windows.")

titulo("3. ¿Python abre los .pyw?")
if sys.platform == "win32":
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    print(f"pythonw.exe: {'existe' if os.path.exists(pyw) else 'NO EXISTE'} ({pyw})")

titulo("4. Lo último que dijo la presencia (%LOCALAPPDATA%\\Arche\\logs\\arche_fondo.log)")
if os.path.exists(LOG):
    with open(LOG, encoding="utf-8", errors="replace") as f:
        lineas = f.readlines()
    importantes = [l.rstrip() for l in lineas if "(presencia)" in l or "(arche_fondo)" in l
                   or "Traceback" in l or "Error" in l or "=====" in l]
    print("\n".join(importantes[-25:]) or "(nada de la presencia todavía)")
else:
    print("No hay registro: arche_fondo.pyw nunca arrancó.")

input("\nEnter para cerrar...")
