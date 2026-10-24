"""
recalcular_embeddings.py
------------------------
Elegir (y cambiar sin romper nada) el modelo de embeddings de Arché.

El modelo de embeddings es la base de TODO: el vecino más cercano y las
redes trabajan sobre sus vectores. Un modelo que entiende mejor el
español sube la precisión de todo a la vez. Pero cambiarlo no es solo
cambiar un nombre: los vectores de un modelo no sirven para otro, y cada
modelo da números de parecido distintos. Este script hace todo:

    python -m core.IA.recalcular_embeddings comparar
        Mide, con TUS ejemplos, qué tan bien funciona cada modelo
        (minilm = el actual, e5-small, e5-base, bge-m3, y afinado si
        existe). No cambia nada. Descarga cada modelo la primera vez
        (e5-small ~0.5 GB, e5-base ~1 GB, bge-m3 ~2 GB).

    python -m core.IA.recalcular_embeddings comparar minilm e5-base
        Igual, solo con esos.

    python -m core.IA.recalcular_embeddings usar e5-base
        Cambia al modelo, hace RESPALDO de conocimiento.json y
        respuestas.json, recalcula todos los embeddings, calibra los
        umbrales para ese modelo y reentrena las redes.

    python -m core.IA.recalcular_embeddings calibrar
        Solo recalibra los umbrales del modelo actual (no recalcula).

Cierra Arché antes de usar 'usar' (para que no escriba al mismo tiempo).
Para volver atrás: 'usar minilm'.
"""

import json
import os
import shutil
import sys
import time
from collections import Counter

import numpy as np

from core.IA import embeddings as emb

BASE = os.path.dirname(__file__)
ARCHIVO_CONOCIMIENTO = os.path.join(BASE, "conocimiento.json")
ARCHIVO_RESPUESTAS = os.path.join(BASE, "respuestas.json")
ARCHIVO_INDICE_FUNCIONES = os.path.join(BASE, "indice_funciones_cache.json")

PRECISION_OBJETIVO = 0.95   # el umbral se elige para que el vecino acierte al menos esto
DIFERENCIA_RESPUESTA = 0.12  # respuestas.py exige más parecido que las intenciones (0.90 vs 0.78)


def _leer_json(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _escribir_json(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)
    os.replace(tmp, ruta)


def _config_de(nombre):
    if nombre not in emb.MODELOS:
        raise SystemExit(f"Modelo desconocido '{nombre}'. Opciones: {', '.join(emb.MODELOS)}")
    cfg = {"nombre": nombre, **emb.MODELOS[nombre]}
    if nombre == "afinado":
        info = os.path.join(emb.CARPETA_AFINADO, "arche_info.json")
        if not os.path.exists(info):
            raise SystemExit("Todavía no hay modelo afinado. Corre primero: python -m core.IA.afinar_embeddings")
        with open(info, "r", encoding="utf-8") as f:
            cfg["prefijo"] = json.load(f).get("prefijo", "")
    return cfg


def _ejemplos():
    """(frases, intenciones) de conocimiento.json, con intenciones unificadas."""
    from core.IA import aprendizaje
    datos = [d for d in aprendizaje.cargar() if d.get("pregunta") and d.get("accion")]
    return [d["pregunta"] for d in datos], np.array([d["accion"] for d in datos])


# ----------------------------------------------------------------------
# Medir
# ----------------------------------------------------------------------
def _vecino_dejando_uno_afuera(E, y):
    """Para cada ejemplo: el más parecido de los DEMÁS. Devuelve
    (similitud, acierto) por ejemplo -- es exactamente lo que hace el
    paso 3 de aprendizaje.resolver con una frase nueva."""
    S = E @ E.T
    np.fill_diagonal(S, -1.0)
    j = S.argmax(axis=1)
    return S[np.arange(len(y)), j], (y[j] == y)


def calibrar_umbral(sims, aciertos):
    """El umbral más bajo con el que el vecino acierta >= PRECISION_OBJETIVO
    de las frases que acepta (más bajo = acepta más frases sin preguntar)."""
    mejor_t, mejor_precision = 0.95, -1.0
    for t in np.arange(0.50, 0.99, 0.01):
        aceptadas = sims >= t
        if aceptadas.sum() < 20:
            continue
        precision = aciertos[aceptadas].mean()
        if precision >= PRECISION_OBJETIVO:
            return round(float(t), 2)
        if precision > mejor_precision:
            mejor_t, mejor_precision = float(t), precision
    # Ningún umbral llega al objetivo: el más preciso que se encontró.
    # (Con la segunda opinión de la red, igual no se ejecutan dudosos.)
    print(f"   Ojo: con este modelo ningún umbral llega a {PRECISION_OBJETIVO:.0%} de acierto; "
          f"uso el más preciso ({mejor_t:.2f}).")
    return round(mejor_t, 2)


def _red_rapida(E, frases, y):
    """Precisión aproximada de las redes: regresión logística con 5
    partes, con las mismas entradas (embedding + palabras + letras).
    Es mucho más rápida que entrenar todas las redes y sirve para
    COMPARAR modelos."""
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from core.IA.clasificador import armar_entrada, _nuevo_lineal
    conteo = Counter(y)
    m = np.array([conteo[c] >= 5 for c in y])
    X = np.array([armar_entrada(e, f) for e, f, ok in zip(E, frases, m) if ok])
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    return float(cross_val_score(_nuevo_lineal(), X, y[m], cv=cv).mean())


def medir(nombre, frases, y):
    cfg = _config_de(nombre)
    print(f"\n== {nombre}  ({cfg['modelo']})")
    t = time.time()
    modelo = emb.cargar_modelo_por_nombre(cfg["modelo"])
    E = emb.calcular_embeddings(frases, modelo=modelo, prefijo=cfg["prefijo"], mostrar_progreso=True)
    seg_por_frase = (time.time() - t) / max(len(frases), 1)
    sims, aciertos = _vecino_dejando_uno_afuera(E, y)
    umbral = calibrar_umbral(sims, aciertos)
    acepta = float((sims >= umbral).mean())
    red = _red_rapida(E, frases, y)
    print(f"   vecino más cercano: acierta {aciertos.mean():.1%} | "
          f"umbral calibrado {umbral} (acepta sin dudar {acepta:.0%} de las frases)")
    print(f"   red rápida (aprox. de tus redes): {red:.1%}")
    return {"nombre": nombre, "vecino": float(aciertos.mean()), "red": red,
            "umbral": umbral, "acepta": acepta}


def comparar(nombres):
    nombres_pedidos = list(nombres)
    frases, y = _ejemplos()
    if len(frases) < 50:
        raise SystemExit("Arché: muy pocos ejemplos para comparar modelos.")
    print(f"Arché: comparando con {len(frases)} ejemplos de {len(set(y))} intenciones...")
    resultados = []
    if "afinado" in nombres:
        nombres = [n for n in nombres if n != "afinado"]
        try:
            info = _info_afinado()
            antes, despues = info["examen_antes"], info["examen_despues"]
            print(f"\n== afinado (de '{info['base_nombre']}', {info['fecha']})")
            print("   No se mide acá: ya vio todos tus ejemplos y saldría inflado. En su examen,")
            print(f"   con frases que no había visto: red {antes['red']:.1%} -> {despues['red']:.1%}, "
                  f"vecino {antes['vecino']:.1%} -> {despues['vecino']:.1%}.")
            print("   Para usarlo: python -m core.IA.recalcular_embeddings usar afinado")
        except Exception:
            print("\n== afinado: todavía no existe (python -m core.IA.afinar_embeddings)")
    for nombre in nombres:
        try:
            resultados.append(medir(nombre, frases, y))
        except SystemExit as e:
            print(f"   (saltado: {e})")
        except Exception as e:
            print(f"   (no se pudo medir: {type(e).__name__}: {e})")
    if not resultados:
        return
    actual = emb.leer_config()["nombre"]
    print("\nResumen (más alto = mejor):")
    for r in sorted(resultados, key=lambda r: -r["red"]):
        marca = "  <- el que usas ahora" if r["nombre"] == actual else ""
        print(f"   {r['nombre']:9s} red {r['red']:.1%}   vecino {r['vecino']:.1%}{marca}")
    mejor = max(resultados, key=lambda r: r["red"])
    if "afinado" in nombres_pedidos:
        print("\n(El afinado no entra en este resumen: júzgalo por su examen, arriba.)")
    if mejor["nombre"] != actual:
        print(f"\nArché: el mejor con tus datos es '{mejor['nombre']}'. Para cambiar:")
        print(f"   python -m core.IA.recalcular_embeddings usar {mejor['nombre']}")
    else:
        print("\nArché: el modelo que ya usas es el mejor con tus datos. No hace falta cambiar.")


# ----------------------------------------------------------------------
# Cambiar de modelo
# ----------------------------------------------------------------------
def usar(nombre):
    cfg = _config_de(nombre)
    print(f"Arché: cambiando al modelo '{nombre}' ({cfg['modelo']}).")
    print("       (Arché debe estar CERRADO mientras tanto.)")
    modelo = emb.cargar_modelo_por_nombre(cfg["modelo"])

    sello = time.strftime("%Y%m%d_%H%M%S")
    for ruta in (ARCHIVO_CONOCIMIENTO, ARCHIVO_RESPUESTAS):
        if os.path.exists(ruta):
            respaldo = ruta.replace(".json", f".antes_de_recalcular_{sello}.json")
            shutil.copy2(ruta, respaldo)
            print(f"   respaldo: {os.path.basename(respaldo)}")

    from core.IA import aprendizaje
    with aprendizaje._lock:
        datos = aprendizaje.cargar(estricto=True)
        con_frase = [d for d in datos if d.get("pregunta")]
        print(f"   recalculando {len(con_frase)} ejemplos...")
        E = emb.calcular_embeddings([d["pregunta"] for d in con_frase], modelo=modelo,
                                    prefijo=cfg["prefijo"], mostrar_progreso=True)
        for d, v in zip(con_frase, E):
            d["embedding"] = v.tolist()
        aprendizaje.guardar(datos)

    respuestas = _leer_json(ARCHIVO_RESPUESTAS)
    if respuestas:
        print(f"   recalculando {len(respuestas)} respuestas guardadas...")
        R = emb.calcular_embeddings([r["pregunta"] for r in respuestas], modelo=modelo,
                                    prefijo=cfg["prefijo"], mostrar_progreso=True)
        for r, v in zip(respuestas, R):
            r["embedding"] = v.tolist()
        _escribir_json(ARCHIVO_RESPUESTAS, respuestas)

    if os.path.exists(ARCHIVO_INDICE_FUNCIONES):
        os.remove(ARCHIVO_INDICE_FUNCIONES)  # se rearma solo con el modelo nuevo

    # Las redes viejas se entrenaron con vectores del modelo ANTERIOR: no
    # sirven con el nuevo, aunque tengan el mismo tamaño (el afinado mide
    # igual que su base). Se apartan a un respaldo para que se entrenen
    # todas de nuevo y ninguna vieja quede activa por "ser mejor".
    import glob
    viejas = glob.glob(os.path.join(BASE, "clasificador*.pkl"))
    if viejas:
        carpeta = os.path.join(BASE, f"redes_antes_de_recalcular_{sello}")
        os.makedirs(carpeta, exist_ok=True)
        for ruta in viejas:
            shutil.move(ruta, os.path.join(carpeta, os.path.basename(ruta)))
        print(f"   {len(viejas)} redes viejas apartadas en {os.path.basename(carpeta)}")

    emb.guardar_config(cfg)
    if nombre == "afinado":
        _usar_umbral_del_examen()
    else:
        calibrar()

    print("   reentrenando las redes con los vectores nuevos (puede tardar)...")
    aprendizaje.reentrenar_ahora()
    print(f"Arché: listo, ahora uso '{nombre}'. Mide con: python -m core.IA.evaluar_redes")


def _info_afinado():
    ruta = os.path.join(emb.CARPETA_AFINADO, "arche_info.json")
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _usar_umbral_del_examen():
    """El modelo afinado ya vio todos tus ejemplos: calibrarlo con ellos
    daría un umbral demasiado bajo (todo le parecería seguro). Se usa el
    que se midió en su examen, con frases que no había visto."""
    umbral = _info_afinado().get("umbral_semantico")
    if umbral is None:
        print("   (el modelo afinado no trae umbral de examen; dejo los de siempre)")
        return
    cfg = emb.leer_config()
    cfg["umbral_semantico"] = umbral
    cfg["umbral_respuesta"] = round(min(0.98, umbral + DIFERENCIA_RESPUESTA), 2)
    emb.guardar_config(cfg)
    print(f"   umbral de parecido (medido en el examen del afinado): {umbral} "
          f"(respuestas: {cfg['umbral_respuesta']})")


def calibrar():
    """Calcula y guarda los umbrales de parecido para el modelo actual."""
    if emb.leer_config()["nombre"] == "afinado":
        _usar_umbral_del_examen()
        return
    from core.IA import aprendizaje
    datos = [d for d in aprendizaje.cargar() if d.get("embedding") and d.get("accion")]
    if len(datos) < 50:
        print("Arché: muy pocos ejemplos para calibrar; dejo los umbrales de siempre.")
        return
    E = np.array([d["embedding"] for d in datos], dtype=float)
    y = np.array([d["accion"] for d in datos])
    sims, aciertos = _vecino_dejando_uno_afuera(E, y)
    umbral = calibrar_umbral(sims, aciertos)
    cfg = emb.leer_config()
    cfg["umbral_semantico"] = umbral
    cfg["umbral_respuesta"] = round(min(0.98, umbral + DIFERENCIA_RESPUESTA), 2)
    emb.guardar_config(cfg)
    print(f"   umbral de parecido calibrado: {umbral} (respuestas: {cfg['umbral_respuesta']}) "
          f"-- con él, el vecino acierta {aciertos[sims >= umbral].mean():.1%} "
          f"de lo que acepta sin preguntar.")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    args = sys.argv[1:]
    if not args or args[0] not in ("comparar", "usar", "calibrar"):
        print(__doc__)
    elif args[0] == "comparar":
        nombres = args[1:] or [n for n in emb.MODELOS
                               if n != "afinado" or os.path.isdir(emb.CARPETA_AFINADO)]
        comparar(nombres)
    elif args[0] == "usar":
        if len(args) < 2:
            print("Uso: python -m core.IA.recalcular_embeddings usar <modelo>")
        else:
            usar(args[1])
    else:
        calibrar()
