"""
evaluar_redes.py
----------------
Diagnóstico de PRECISIÓN de las redes de Arché, con tus datos reales
(conocimiento.json). No cambia nada: solo mide y te dice dónde se
equivoca, para que sepas qué ejemplos agregar o corregir.

Muestra:
  1. Precisión real estimada (validación cruzada de 5 partes).
  2. Las intenciones con peor acierto (las que más fallan).
  3. Los pares de intenciones que más se confunden entre sí.
  4. Ejemplos sospechosos: frases casi idénticas guardadas con
     intenciones DISTINTAS. Esto es lo que más daña la precisión: la
     red recibe dos respuestas contradictorias para lo mismo.

Uso (desde la carpeta Arche):
    python -m core.IA.evaluar_redes
"""

from collections import Counter

import numpy as np

SIMILITUD_SOSPECHOSA = 0.95  # frases así de parecidas deberían tener la misma intención


def _datos():
    from core.IA.aprendizaje import cargar
    filas = [d for d in cargar() if d.get("embedding") and d.get("accion")]
    frases = [d.get("pregunta") or d.get("frase") or "?" for d in filas]
    from core.IA.clasificador import fila_de
    E = np.array([d["embedding"] for d in filas], dtype=float)  # solo embedding (para buscar contradicciones)
    X = np.array([fila_de(d) for d in filas], dtype=float)        # lo que de verdad ve la red
    y = np.array([d["accion"] for d in filas])
    return frases, E, X, y


def _hiperparametros_actuales():
    """La config de la red guardada, si ya se entrenó con palabras. Si no
    (modelo viejo), usa una config razonable de la grilla nueva."""
    from core.IA.clasificador import _cargar_modelo, version_de, VERSION_RASGOS
    _, meta, _ = _cargar_modelo()
    if meta and version_de(meta) == VERSION_RASGOS:
        return meta["hiperparametros"]
    return {"hidden_layer_sizes": (128,), "alpha": 0.01, "activation": "tanh"}


def evaluar(folds=5):
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.preprocessing import LabelEncoder
    from core.IA.clasificador import _nueva_red, _nuevo_lineal

    frases, E, X, y = _datos()
    conteo = Counter(y)
    validas = {c for c, n in conteo.items() if n >= folds}
    mascara = np.array([c in validas for c in y])
    if mascara.sum() == 0 or len(validas) < 2:
        print("Arché: todavía no hay suficientes ejemplos para evaluar.")
        return

    Xv, yv = X[mascara], y[mascara]
    cod = LabelEncoder().fit(yv)
    yc = cod.transform(yv)
    hp = _hiperparametros_actuales()
    red = _nueva_red().set_params(**{f"red__{k}": v for k, v in hp.items()})
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    print(f"Arché: evaluando {len(yv)} ejemplos de {len(validas)} intenciones (config {hp})...")
    p_red = cross_val_predict(red, Xv, yc, cv=cv, method="predict_proba")
    p_lin = cross_val_predict(_nuevo_lineal(), Xv, yc, cv=cv, method="predict_proba")
    p_mez = (p_red + p_lin) / 2
    print(f"   red sola {(p_red.argmax(1) == yc).mean():.1%} | regresión logística "
          f"{(p_lin.argmax(1) == yc).mean():.1%} | votación de las dos {(p_mez.argmax(1) == yc).mean():.1%}")
    mejor = p_mez if (p_mez.argmax(1) == yc).mean() > (p_red.argmax(1) == yc).mean() else p_red
    pred = cod.inverse_transform(mejor.argmax(1))
    confianza = mejor.max(1)

    acierto = (pred == yv)
    print(f"\n1) Precisión real estimada: {acierto.mean():.1%}")
    for umbral in (0.6, 0.8):
        m = confianza >= umbral
        if m.any():
            print(f"   cuando está {umbral:.0%}+ segura ({m.mean():.0%} de las frases): acierta {acierto[m].mean():.1%}")
    omitidas = len(conteo) - len(validas)
    if omitidas:
        print(f"   ({omitidas} intenciones con menos de {folds} ejemplos no se evaluaron)")

    print("\n2) Intenciones que más fallan:")
    por_int = []
    for c in sorted(validas):
        m = yv == c
        por_int.append((acierto[m].mean(), c, int(m.sum())))
    for prec, c, n in sorted(por_int)[:10]:
        print(f"   {prec:5.0%}  {c}  ({n} ejemplos)")

    print("\n3) Confusiones más comunes (real -> la red dijo):")
    pares = Counter((r, p) for r, p in zip(yv, pred) if r != p)
    for (r, p), n in pares.most_common(10):
        print(f"   {n:3d}x  {r} -> {p}")

    print(f"\n4) Ejemplos contradictorios (similitud >= {SIMILITUD_SOSPECHOSA}, intención distinta):")
    print("   (Las frases de abajo se parecen mucho en SIGNIFICADO. Si son de verdad la misma")
    print("    orden, une las intenciones. Si son órdenes opuestas, ahora las palabras las separan.)")
    Xn = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
    sim = Xn @ Xn.T
    encontrados = 0
    for i in range(len(y)):
        for j in range(i + 1, len(y)):
            if sim[i, j] >= SIMILITUD_SOSPECHOSA and y[i] != y[j]:
                print(f"   '{frases[i]}' [{y[i]}]  vs  '{frases[j]}' [{y[j]}]  ({sim[i, j]:.2f})")
                encontrados += 1
                if encontrados >= 20:
                    print("   ... (hay más)")
                    return
    if not encontrados:
        print("   Ninguno. Bien.")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    evaluar()
