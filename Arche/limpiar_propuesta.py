"""
limpiar_propuestas.py
---------------------
Ubicacion: Arche/limpiar_propuestas.py (raiz del proyecto)

Limpia core/IA/cambios_codigo_pendientes.json:
  - Hace backup (.bak.json) antes de tocar nada.
  - Quita propuestas PENDIENTES repetidas (mismo archivo + buscar + reemplazar).
  - Quita propuestas PENDIENTES sobre archivos que ya no existen.
  - Quita propuestas PENDIENTES de "Eliminar la función ..." (casi todas eran
    falsas; se pueden volver a generar a pedido).
  - NO toca las ya aplicadas/rechazadas (las necesita revertir_cambio_codigo).
  - NO renumera ids.

Uso (desde la raiz del proyecto):
    py limpiar_propuestas.py                       (limpieza general)
    py limpiar_propuestas.py --conservar cod_246   (deja PENDIENTES solo esas
                                                    propuestas; borra el resto
                                                    de las pendientes)
"""

import json
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARCHIVO = RAIZ / "core" / "IA" / "cambios_codigo_pendientes.json"


def main():
    if not ARCHIVO.exists():
        print("No hay archivo de propuestas, nada que limpiar.")
        return

    propuestas = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    shutil.copy2(ARCHIVO, ARCHIVO.with_suffix(".bak.json"))

    conservar = set()
    if "--conservar" in sys.argv:
        conservar = set(sys.argv[sys.argv.index("--conservar") + 1:])

    vistas = set()
    resultado = []
    quitadas = {"repetidas": 0, "archivo_inexistente": 0, "borrado_de_funcion": 0, "fuera_de_la_lista": 0}

    for p in propuestas:
        if p.get("estado") != "pendiente":
            resultado.append(p)
            continue

        if conservar and p.get("id") not in conservar:
            quitadas["fuera_de_la_lista"] += 1
            continue

        if p.get("tipo") != "archivo_nuevo" and not (RAIZ / p.get("archivo", "")).exists():
            quitadas["archivo_inexistente"] += 1
            continue

        if str(p.get("que", "")).startswith("Eliminar la función"):
            quitadas["borrado_de_funcion"] += 1
            continue

        clave = (p.get("archivo"), p.get("buscar"), p.get("reemplazar"))
        if clave in vistas:
            quitadas["repetidas"] += 1
            continue
        vistas.add(clave)
        resultado.append(p)

    ARCHIVO.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    pendientes = sum(1 for p in resultado if p.get("estado") == "pendiente")
    print(f"Antes: {len(propuestas)} | Después: {len(resultado)} ({pendientes} pendientes)")
    for motivo, n in quitadas.items():
        print(f"  quitadas por {motivo}: {n}")
    print(f"Backup: {ARCHIVO.with_suffix('.bak.json').name}")


if __name__ == "__main__":
    main()