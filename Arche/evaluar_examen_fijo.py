"""
evaluar_examen_fijo.py
----------------------
Mide al clasificador de intenciones de Arché contra un EXAMEN FIJO y guarda el
resultado en un historial, para saber con números si Arché mejora o empeora.

Uso (desde la carpeta Arche, con Arché cerrado):

    python evaluar_examen_fijo.py              # mide y guarda en el historial
    python evaluar_examen_fijo.py --congelar   # crea el examen fijo (una sola vez)
    python evaluar_examen_fijo.py --ver        # muestra la evolución guardada
    python evaluar_examen_fijo.py --sin-guardar

Por qué un examen FIJO:
  Si el examen cambia cada vez, no se puede comparar un día con otro. El examen
  se congela una vez (core/IA/examen_fijo.jsonl) y no se toca más. Para que la
  nota sea honesta, el script también cuenta cuántas frases del examen YA están
  en lo que Arché estudia (conocimiento.json): esas se "memorizan" y inflan la
  nota. La cifra que importa es la de "frases no vistas".

Código de salida (sirve para frenar un cambio malo, por ejemplo en CI):
  0 = todo bien (o no hay modelo todavía)
  1 = la precisión bajó más de CAIDA_MAXIMA puntos frente a la última medición
"""

import argparse
import json
import os
import sys
import time
import unicodedata
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

CARPETA_IA = os.path.join(AQUI, "core", "IA")
ARCHIVO_EXAMEN = os.path.join(CARPETA_IA, "examen_fijo.jsonl")
ARCHIVO_HISTORIAL = os.path.join(CARPETA_IA, "historial_precision.jsonl")
ARCHIVO_CONOCIMIENTO = os.path.join(CARPETA_IA, "conocimiento.json")
FUENTE_PARA_CONGELAR = os.path.join(AQUI, "modelos", "validacion-v2.jsonl")

CAIDA_MAXIMA = 2.0          # puntos porcentuales que se toleran entre mediciones
MINIMO_POR_INTENCION = 1    # intenciones con menos frases se ignoran al congelar


def _normalizar(texto):
    t = unicodedata.normalize("NFD", str(texto).lower().strip())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _leer_jsonl(ruta):
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                try:
                    filas.append(json.loads(linea))
                except json.JSONDecodeError:
                    pass
    return filas


def congelar():
    if os.path.exists(ARCHIVO_EXAMEN):
        print(f"Ya existe {ARCHIVO_EXAMEN}. Un examen fijo no se rehace "
              "(si lo cambias, las notas viejas dejan de compararse). Bórralo a mano si de verdad quieres.")
        return 1
    if not os.path.exists(FUENTE_PARA_CONGELAR):
        print(f"No encuentro {FUENTE_PARA_CONGELAR}.")
        return 1
    vistos, salida = set(), []
    for fila in _leer_jsonl(FUENTE_PARA_CONGELAR):
        frase, intencion = fila.get("frase"), fila.get("intencion")
        clave = _normalizar(frase or "")
        if not frase or not intencion or clave in vistos:
            continue
        vistos.add(clave)
        salida.append({"frase": frase, "intencion": intencion, "dominio": fila.get("dominio", "")})
    with open(ARCHIVO_EXAMEN, "w", encoding="utf-8") as f:
        for fila in salida:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    print(f"Examen fijo creado: {len(salida)} frases en {ARCHIVO_EXAMEN}")
    print("Súbelo a GitHub y NO lo edites. Tampoco lo uses para entrenar.")
    return 0


def _frases_de_estudio():
    """Frases que Arché ya estudia (para detectar memorización)."""
    try:
        with open(ARCHIVO_CONOCIMIENTO, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return set()
    if isinstance(datos, dict):
        datos = list(datos.values())
    return {_normalizar(d.get("pregunta", "")) for d in datos if isinstance(d, dict)}


def _ultima_medicion():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return None
    filas = _leer_jsonl(ARCHIVO_HISTORIAL)
    return filas[-1] if filas else None


def medir(guardar=True):
    if not os.path.exists(ARCHIVO_EXAMEN):
        print("Todavía no hay examen fijo. Primero corre:  python evaluar_examen_fijo.py --congelar")
        return 0

    from core.IA import clasificador, embeddings   # import tardío: carga numpy/sklearn

    if not os.path.exists(clasificador.ARCHIVO_MODELO):
        print("Todavía no hay clasificador entrenado (clasificador.pkl). Nada que medir.")
        return 0

    examen = _leer_jsonl(ARCHIVO_EXAMEN)
    estudiadas = _frases_de_estudio()
    aciertos = total = ac_nuevas = tot_nuevas = sin_respuesta = 0
    por_dominio = defaultdict(lambda: [0, 0])
    por_intencion = defaultdict(lambda: [0, 0])
    fallos = []

    for fila in examen:
        frase, real = fila["frase"], fila["intencion"]
        emb = embeddings.calcular_embedding(frase)
        pred, conf = clasificador.predecir(emb, frase)
        ok = pred == real
        if pred is None:
            sin_respuesta += 1
        total += 1
        aciertos += ok
        dom = fila.get("dominio") or "?"
        por_dominio[dom][0] += ok
        por_dominio[dom][1] += 1
        por_intencion[real][0] += ok
        por_intencion[real][1] += 1
        if _normalizar(frase) not in estudiadas:
            tot_nuevas += 1
            ac_nuevas += ok
        if not ok:
            fallos.append((frase, real, pred, conf))

    pct = lambda a, b: round(100.0 * a / b, 2) if b else None
    resultado = {
        "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": total,
        "precision": pct(aciertos, total),
        "frases_no_vistas": tot_nuevas,
        "precision_no_vistas": pct(ac_nuevas, tot_nuevas),
        "sin_respuesta": sin_respuesta,
        "por_dominio": {d: pct(a, b) for d, (a, b) in sorted(por_dominio.items())},
    }

    anterior = _ultima_medicion()

    print(f"Examen fijo: {total} frases")
    print(f"  Precisión total .......... {resultado['precision']} %")
    if tot_nuevas:
        print(f"  Precisión NO vistas ...... {resultado['precision_no_vistas']} %  ({tot_nuevas} frases)  <- la honesta")
    else:
        print("  Todas las frases del examen ya están en el estudio: la nota está inflada.")
    if sin_respuesta:
        print(f"  Sin respuesta (modelo desactualizado o sin confianza): {sin_respuesta}")
    print("  Por dominio:")
    for d, v in resultado["por_dominio"].items():
        print(f"    {d:18s} {v} %")
    peores = sorted(((a / b, i, b) for i, (a, b) in por_intencion.items() if b >= 2))[:5]
    if peores:
        print("  Intenciones más débiles:")
        for tasa, i, b in peores:
            print(f"    {i:28s} {round(tasa * 100)} %  ({b} frases)")
    if fallos:
        print("  Algunos fallos (frase -> esperaba / dijo):")
        for frase, real, pred, conf in fallos[:8]:
            print(f"    «{frase[:50]}» -> {real} / {pred} ({conf:.2f})")

    codigo = 0
    if anterior:
        clave = "precision_no_vistas" if (tot_nuevas and anterior.get("precision_no_vistas") is not None) else "precision"
        antes, ahora = anterior.get(clave), resultado.get(clave)
        if antes is not None and ahora is not None:
            cambio = round(ahora - antes, 2)
            signo = "+" if cambio >= 0 else ""
            print(f"  Frente a la medición anterior ({anterior['fecha']}): {signo}{cambio} puntos")
            if cambio < -CAIDA_MAXIMA:
                print(f"  ⚠ BAJÓ más de {CAIDA_MAXIMA} puntos. Revisa lo último que cambiaste o aprendiste.")
                codigo = 1

    if guardar:
        with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(resultado, ensure_ascii=False) + "\n")
    return codigo


def ver():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        print("Aún no hay historial. Corre  python evaluar_examen_fijo.py  primero.")
        return 0
    for fila in _leer_jsonl(ARCHIVO_HISTORIAL):
        nv = fila.get("precision_no_vistas")
        print(f"{fila['fecha']}  total {fila['precision']} %   no vistas {nv if nv is not None else '-'} %")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--congelar", action="store_true", help="crea el examen fijo (una sola vez)")
    ap.add_argument("--ver", action="store_true", help="muestra el historial de precisión")
    ap.add_argument("--sin-guardar", action="store_true", help="mide pero no escribe en el historial")
    args = ap.parse_args()
    if args.congelar:
        return congelar()
    if args.ver:
        return ver()
    return medir(guardar=not args.sin_guardar)


if __name__ == "__main__":
    sys.exit(main())
