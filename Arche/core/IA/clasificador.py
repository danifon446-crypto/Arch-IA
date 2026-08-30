"""
clasificador.py
----------------
Red neuronal (MLPClassifier de scikit-learn) entrenada sobre los
embeddings acumulados en conocimiento.json, para reconocer patrones de
intención más sutiles que la búsqueda por vecino más cercano (capa 3 de
aprendizaje.py) o una regresión logística simple podrían captar.

Diseñado para minimizar fallos silenciosos:
- Valida con cross-validation ANTES de confiar en el modelo (no se usa
    a ciegas nunca).
- Balancea clases (sobremuestreo) para no sesgarse hacia la intención
    más común.- Prueba varias configuraciones de la red (búsqueda de hiperparámetros)
    y se queda con la mejor, en vez de una fija a ojo.
    - Nunca reemplaza un modelo bueno por uno peor: guarda el score de
    validación junto al modelo, y solo sobreescribe si el nuevo es
    igual o mejor.
- Detecta si las dimensiones de embedding cambiaron (ej. cambiaste de
    modelo de embeddings) y se desactiva en vez de dar resultados
    basura o explotar.

Requiere:
    pip install scikit-learn numpy
"""

import os
import json
import pickle
from collections import Counter

import numpy as np

BASE = os.path.dirname(__file__)
ARCHIVO_MODELO = os.path.join(BASE, "clasificador.pkl")

# No tiene sentido entrenar una red neuronal con muy pocos ejemplos: se
# necesita más data que para una regresión logística simple, si no,
# memoriza en vez de generalizar. Ajusta hacia arriba a medida que
# confíes más en el volumen de datos.
MIN_EJEMPLOS_POR_CLASE = 5
MIN_CLASES = 2

# Score mínimo de validación cruzada para considerar el modelo utilizable.
# Por debajo de esto, mejor no confiar en sus predicciones.
SCORE_MINIMO_UTILIZABLE = 0.55

# Búsqueda de hiperparámetros: espacio chico a propósito (los datos son
# pocos, no vale la pena tardar mucho en la búsqueda).
GRILLA_HIPERPARAMETROS = {
    "hidden_layer_sizes": [(32,), (64,), (64, 32)],
    "alpha": [0.0001, 0.001, 0.01],
}


def _preparar_dataset(datos):
    X, y = [], []
    for d in datos:
        if d.get("embedding"):
            X.append(d["embedding"])
            y.append(d["accion"])
    return np.array(X), np.array(y)


def _hay_datos_suficientes(y):
    conteo = Counter(y)
    clases_validas = [c for c, n in conteo.items() if n >= MIN_EJEMPLOS_POR_CLASE]
    return len(clases_validas) >= MIN_CLASES, conteo


def _balancear_clases(X, y):
    """
    Sobremuestreo simple: duplica ejemplos de las clases minoritarias al
    azar hasta igualar a la clase mayoritaria. Evita que la red se
    sesgue hacia la intención más común solo por tener más ejemplos.
    """
    from sklearn.utils import resample

    conteo = Counter(y)
    n_mayoritaria = max(conteo.values())

    X_balanceado, y_balanceado = [], []
    for clase in conteo:
        idx_clase = np.where(y == clase)[0]
        X_clase, y_clase = X[idx_clase], y[idx_clase]

        if len(idx_clase) < n_mayoritaria:
            X_clase, y_clase = resample(
                X_clase, y_clase,
                replace=True,
                n_samples=n_mayoritaria,
                random_state=42,
            )

        X_balanceado.append(X_clase)
        y_balanceado.append(y_clase)

    return np.vstack(X_balanceado), np.concatenate(y_balanceado)


def _metadata_anterior():
    if not os.path.exists(ARCHIVO_MODELO):
        return None
    try:
        with open(ARCHIVO_MODELO, "rb") as f:
            paquete = pickle.load(f)
        return paquete.get("metadata")
    except Exception:
        return None


def entrenar(silencioso=False):
    """
    Reentrena la red neuronal desde cero usando todo lo aprendido hasta
    ahora. Solo GUARDA el modelo nuevo si:
    - hay datos suficientes (ver MIN_EJEMPLOS_POR_CLASE / MIN_CLASES)
    - su score de validación cruzada supera SCORE_MINIMO_UTILIZABLE
    - su score es igual o mejor que el del modelo anterior (si había uno)

    Devuelve True si guardó un modelo nuevo, False en cualquier otro caso.
    """
    try:
        from core.IA.aprendizaje import cargar
        from sklearn.neural_network import MLPClassifier
        from sklearn.model_selection import GridSearchCV, StratifiedKFold
    except ImportError as e:
        if not silencioso:
            print(f"Arché: Falta una dependencia para el clasificador ({e}).")
        return False

    datos = cargar()
    X, y = _preparar_dataset(datos)

    if len(X) == 0:
        return False

    suficiente, conteo = _hay_datos_suficientes(y)
    if not suficiente:
        if not silencioso:
            print(
                f"Arché: Todavía no hay suficientes ejemplos para entrenar "
                f"la red neuronal (se necesitan al menos "
                f"{MIN_EJEMPLOS_POR_CLASE} ejemplos en {MIN_CLASES}+ "
                f"intenciones distintas)."
            )
            print(f"       Progreso actual por intención: {dict(conteo)}")
        return False

    dimension_embedding = X.shape[1]

    X_bal, y_bal = _balancear_clases(X, y)

    # MLPClassifier con early_stopping=True falla internamente si las
    # clases son strings (bug conocido de sklearn con ciertas versiones:
    # intenta np.isnan sobre las etiquetas). Codificamos a enteros.
    from sklearn.preprocessing import LabelEncoder
    codificador = LabelEncoder()
    y_bal_cod = codificador.fit_transform(y_bal)

    # cv no puede ser mayor que la cantidad de ejemplos de la clase más
    # chica (post-balanceo esto ya no aplica, pero por las dudas con
    # datasets raros lo acotamos igual).
    n_folds = min(3, min(Counter(y_bal).values()))
    n_folds = max(n_folds, 2)

    try:
        cv = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)

        busqueda = GridSearchCV(
            MLPClassifier(max_iter=2000, random_state=42),
            GRILLA_HIPERPARAMETROS,
            cv=cv,
            scoring="accuracy",
            n_jobs=-1,
        )
        busqueda.fit(X_bal, y_bal_cod)

    except Exception as e:
        if not silencioso:
            print(f"Arché: El entrenamiento de la red neuronal falló ({e}).")
        return False

    score_nuevo = busqueda.best_score_
    modelo_nuevo = busqueda.best_estimator_

    if score_nuevo < SCORE_MINIMO_UTILIZABLE:
        if not silencioso:
            print(
                f"Arché: La red neuronal entrenó, pero su precisión "
                f"({score_nuevo:.0%}) es demasiado baja para confiar en "
                f"ella todavía. Sigo usando las capas anteriores."
            )
        return False

    meta_anterior = _metadata_anterior()
    if meta_anterior and meta_anterior.get("score", 0) > score_nuevo + 0.01:
        if not silencioso:
            print(
                f"Arché: El modelo nuevo ({score_nuevo:.0%}) es peor que el "
                f"actual ({meta_anterior['score']:.0%}). Mantengo el actual."
            )
        return False

    metadata = {
        "score": score_nuevo,
        "n_ejemplos": len(X),
        "n_ejemplos_balanceados": len(X_bal),
        "dimension_embedding": dimension_embedding,
        "hiperparametros": busqueda.best_params_,
        "clases": sorted(set(y_bal.tolist())),
    }

    with open(ARCHIVO_MODELO, "wb") as f:
        pickle.dump(
            {"modelo": modelo_nuevo, "metadata": metadata, "codificador": codificador},
            f,
        )

    if not silencioso:
        print(
            f"Arché: Red neuronal actualizada. Precisión de validación: "
            f"{score_nuevo:.0%} ({len(X)} ejemplos, {len(metadata['clases'])} "
            f"intenciones, config {busqueda.best_params_})."
        )
    return True


def _cargar_modelo():
    if not os.path.exists(ARCHIVO_MODELO):
        return None, None, None
    try:
        with open(ARCHIVO_MODELO, "rb") as f:
            paquete = pickle.load(f)
        return paquete["modelo"], paquete["metadata"], paquete["codificador"]
    except Exception:
        return None, None, None


def predecir(embedding_pregunta):
    """
    Devuelve (accion_predicha, confianza) usando la red neuronal
    entrenada. Si todavía no existe un modelo, o las dimensiones del
    embedding no coinciden con las que se usaron para entrenar (ej.
    cambiaste el modelo de embeddings), devuelve (None, 0.0) en vez de
    fallar o dar un resultado sin sentido.
    """
    modelo, metadata, codificador = _cargar_modelo()
    if modelo is None:
        return None, 0.0

    if len(embedding_pregunta) != metadata.get("dimension_embedding"):
        # Las dimensiones no calzan -> el modelo quedó desactualizado
        # respecto al modelo de embeddings actual. No confiamos en él.
        return None, 0.0

    try:
        probs = modelo.predict_proba([embedding_pregunta])[0]
        idx_max = int(probs.argmax())
        accion = codificador.inverse_transform([idx_max])[0]
        confianza = float(probs[idx_max])
        return accion, confianza
    except Exception:
        return None, 0.0


def info_modelo():
    """Muestra el estado actual del clasificador (para debug/curiosidad)."""
    _, metadata, _ = _cargar_modelo()
    if metadata is None:
        print("Arché: Todavía no hay una red neuronal entrenada.")
        return
    print("Arché: Estado de la red neuronal:")
    print(f"  Precisión de validación: {metadata['score']:.0%}")
    print(f"  Ejemplos de entrenamiento: {metadata['n_ejemplos']} (balanceados a {metadata['n_ejemplos_balanceados']})")
    print(f"  Intenciones: {', '.join(metadata['clases'])}")
    print(f"  Configuración: {metadata['hiperparametros']}")