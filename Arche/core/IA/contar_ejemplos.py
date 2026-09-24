"""
Cuenta cuántos ejemplos REALES hay en conocimiento.json -- no confundir
con el número de línea del archivo. Cada ejemplo guarda su embedding
completo (un vector de varios cientos de números, uno por línea con el
formato indentado), así que el archivo tiene muchísimas más líneas que
ejemplos: unos pocos cientos de ejemplos ya explican decenas de miles
de líneas.

Uso, desde la carpeta Arche/:
    python3 core/IA/contar_ejemplos.py

No necesita que Ollama esté corriendo ni pasa por main.py -- lee el
JSON directo, así que es rápido y no interfiere con nada que esté
corriendo en background (examen/estudio automático).
"""
import json
import os
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(BASE, "conocimiento.json")


def main():
    if not os.path.exists(ARCHIVO):
        print("No existe conocimiento.json todavía -- Arché no aprendió nada aún.")
        return

    with open(ARCHIVO, "r", encoding="utf-8") as f:
        datos = json.load(f)

    print(f"Total de ejemplos: {len(datos)}")

    sin_embedding = sum(1 for d in datos if not d.get("embedding"))
    if sin_embedding:
        print(f"  (de los cuales {sin_embedding} no tienen embedding y NO cuentan para entrenar el clasificador)")

    print()
    print("Por dominio > intención:")
    try:
        import dominios
    except ImportError:
        from core.IA import dominios

    por_dominio = {}
    for d in datos:
        accion = d.get("accion", "???")
        dom = dominios.dominio_de(accion) or "(sin dominio)"
        por_dominio.setdefault(dom, Counter())[accion] += 1

    for dom in sorted(por_dominio):
        total_dom = sum(por_dominio[dom].values())
        print(f"  {dom} ({total_dom} ejemplos):")
        for accion, n in por_dominio[dom].most_common():
            marca = "" if n >= 5 else "  ⚠️ menos de 5"
            print(f"    - {accion}: {n}{marca}")

    print()
    print("Por fuente:")
    por_fuente = Counter(d.get("fuente", "???") for d in datos)
    for fuente, n in por_fuente.most_common():
        print(f"  {fuente}: {n}")


if __name__ == "__main__":
    main()