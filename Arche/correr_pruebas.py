"""
correr_pruebas.py
-----------------
Corre TODAS las pruebas de Arché de una sola vez y te dice cuáles pasan.
Desde la carpeta Arche (con Arché cerrado):

    python correr_pruebas.py

Úsalo después de copiar archivos nuevos o de aplicar un parche: si todo sale
con ✔, puedes abrir Arché tranquilo.
"""

import glob
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
SALTAR = {
    "prueba_manual.py",     # esa es para usar a mano
    "prueba_raphael.py",    # aplica aplicar_parche_raphael.py a main.py, que ya está parchado: obsoleta
}
TIEMPO_MAXIMO = 300                      # segundos por prueba


def main():
    pruebas = sorted(os.path.basename(p) for p in glob.glob(os.path.join(AQUI, "prueba_*.py")))
    pruebas = [p for p in pruebas if p not in SALTAR]
    fallaron = []
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    for nombre in pruebas:
        inicio = time.time()
        try:
            r = subprocess.run([sys.executable, nombre], cwd=AQUI, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                               timeout=TIEMPO_MAXIMO, env=entorno)
            ok, salida = r.returncode == 0, (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            ok, salida = False, f"tardó más de {TIEMPO_MAXIMO} s"
        print(f"  {'✔' if ok else '✖'} {nombre:34s} {time.time() - inicio:5.1f} s")
        if not ok:
            fallaron.append((nombre, salida))
    print(f"\n{len(pruebas) - len(fallaron)}/{len(pruebas)} archivos de prueba pasaron.")
    for nombre, salida in fallaron:
        print(f"\n--- {nombre} (últimas líneas) ---")
        print("\n".join(salida.strip().splitlines()[-15:]))
    sys.exit(1 if fallaron else 0)


if __name__ == "__main__":
    main()
