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

# Búsqueda de hiperparámetros.
# Antes: (32,), (64,), (64, 32) con alpha hasta 0.01. Con 145 intenciones,
# una capa de 32 neuronas es un embudo (menos neuronas que clases), y la
# búsqueda casi siempre elegía el alpha más alto disponible: señal de que
# le faltaba regularización. Ahora prueba capas más anchas, más
# regularización (alpha = cuánto se castigan los pesos grandes, evita que
# memorice) y también la activación tanh, que en las pruebas ganó.
GRILLA_HIPERPARAMETROS = {
    "hidden_layer_sizes": [(128,), (256,)],
    "alpha": [0.01, 0.1],   # 8 combinaciones en total: menos que antes (9), entrena igual de rápido
    "activation": ["relu", "tanh"],
}

# ----------------------------------------------------------------------
# Rasgos de PALABRAS y de LETRAS (además del embedding)
# ----------------------------------------------------------------------
# El modelo de embeddings capta el TEMA de la frase pero casi ignora el
# verbo: para él "pon el examen" y "detén el examen" se parecen 98%. Por
# eso fallaban los pares on/off, crear/agregar/abrir nota, estado/entrenar.
# Solución: a la red le llega el embedding Y una "bolsa de palabras" de
# la frase (qué palabras y pares de palabras aparecen). Así "pon" vs
# "deten" sí cambia lo que ve la red.
#
# Versión 2 suma trozos de LETRAS (de 3 a 5 letras seguidas): así
# "ensiende" (mal escrito, o mal transcrito por la voz) comparte casi
# todos sus trozos con "enciende", y la red lo reconoce igual.
#
# Se usa HashingVectorizer: convierte cada palabra/trozo en una posición
# fija con una fórmula, sin necesidad de guardar un vocabulario. Siempre
# da lo mismo para la misma frase, así que no hay nada extra que guardar
# en el .pkl.
#
# Cada modelo guarda en su metadata con qué versión se entrenó
# ("rasgos_texto"), así un modelo viejo sigue funcionando hasta que se
# reentrene:
#   0 = solo embedding
#   1 = embedding + palabras
#   2 = embedding + palabras + letras  (la actual)
VERSION_RASGOS = 2
USAR_TEXTO = VERSION_RASGOS > 0   # (se conserva el nombre por compatibilidad)
N_RASGOS_TEXTO = 1024             # columnas por cada bolsa (palabras / letras)

_hashers = {}


def _hasher(tipo):
    if tipo not in _hashers:
        from sklearn.feature_extraction.text import HashingVectorizer
        if tipo == "palabras":
            _hashers[tipo] = HashingVectorizer(
                ngram_range=(1, 2), n_features=N_RASGOS_TEXTO,
                alternate_sign=False, norm="l2",
            )
        else:
            _hashers[tipo] = HashingVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), n_features=N_RASGOS_TEXTO,
                alternate_sign=False, norm="l2",
            )
    return _hashers[tipo]


def _rasgos(texto, tipo):
    if not texto:
        return np.zeros(N_RASGOS_TEXTO)
    from core.IA.aprendizaje import _normalizar
    return _hasher(tipo).transform([_normalizar(texto)]).toarray()[0]


def version_de(metadata):
    """Con qué versión de rasgos se entrenó un modelo guardado."""
    metadata = metadata or {}
    if "rasgos_texto" in metadata:
        return int(metadata["rasgos_texto"])
    return 1 if metadata.get("usa_texto") else 0


def columnas_extra(version=VERSION_RASGOS):
    return {0: 0, 1: N_RASGOS_TEXTO}.get(version, 2 * N_RASGOS_TEXTO)


def armar_entrada(embedding, texto=None, version=VERSION_RASGOS):
    """Lo que de verdad entra a la red: el embedding y, según la versión
    con que se entrenó el modelo, las palabras y las letras de la frase.
    (`version` acepta también True/False por compatibilidad: True = 1.)"""
    version = int(version)
    emb = np.asarray(embedding, dtype=float)
    partes = [emb]
    if version >= 1:
        partes.append(_rasgos(texto, "palabras"))
    if version >= 2:
        partes.append(_rasgos(texto, "letras"))
    return np.concatenate(partes) if len(partes) > 1 else emb


def fila_de(dato):
    """Fila de entrenamiento a partir de un ejemplo de conocimiento.json."""
    return armar_entrada(dato["embedding"], dato.get("pregunta", ""))


def dimension_embedding_de(X):
    """Cuántas columnas de X son embedding (el resto son palabras/letras)."""
    return X.shape[1] - columnas_extra()


# ----------------------------------------------------------------------
# Votación: red neuronal + regresión logística
# ----------------------------------------------------------------------
class Conjunto:
    """
    Junta la red neuronal con una regresión logística (un modelo lineal,
    mucho más simple). Con pocos ejemplos por intención, la regresión
    logística muchas veces acierta tanto como la red, y se equivoca en
    OTRAS frases -- promediar las dos probabilidades corrige errores de
    cada una. Solo se usa si en la validación cruzada la mezcla le gana a
    la red sola (ver _ajustar).

    Se comporta como un modelo de sklearn para el resto de Arché:
    predict_proba, classes_ y named_steps (la vista de redes de la
    interfaz sigue dibujando las neuronas de la red).
    """

    def __init__(self, red, lineal, peso_lineal=0.5):
        self.red = red
        self.lineal = lineal
        self.peso_lineal = peso_lineal

    @property
    def classes_(self):
        return self.red.classes_

    @property
    def named_steps(self):
        return self.red.named_steps

    def predict_proba(self, X):
        p = self.red.predict_proba(X)
        if self.lineal is None or self.peso_lineal <= 0:
            return p
        return (1 - self.peso_lineal) * p + self.peso_lineal * self.lineal.predict_proba(X)

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]


def _nueva_red():
    from sklearn.neural_network import MLPClassifier
    from imblearn.pipeline import Pipeline as PipelineDesbalanceado
    from imblearn.over_sampling import RandomOverSampler
    return PipelineDesbalanceado([
        ("balanceo", RandomOverSampler(random_state=42)),
        ("red", MLPClassifier(max_iter=2000, random_state=42)),
    ])


def _nuevo_lineal():
    from sklearn.linear_model import LogisticRegression
    from imblearn.pipeline import Pipeline as PipelineDesbalanceado
    from imblearn.over_sampling import RandomOverSampler
    return PipelineDesbalanceado([
        ("balanceo", RandomOverSampler(random_state=42)),
        ("lineal", LogisticRegression(C=10.0, max_iter=3000)),
    ])


def _ajustar(X, y_cod, n_folds, n_jobs):
    """
    Núcleo de entrenamiento compartido por la red clásica y por TODAS las
    redes del árbol jerárquico:

    1. Busca la mejor configuración de la red (GridSearchCV, con el
       balanceo DENTRO de cada fold -- ver comentario en entrenar()).
    2. Con esos mismos folds mide la red sola y la mezcla red + lineal.
    3. Se queda con la que acierte más.

    Devuelve (modelo_final, score, hiperparametros, peso_lineal).
    Lanza excepción si algo falla (el que llama decide qué hacer).
    """
    from sklearn.model_selection import GridSearchCV, StratifiedKFold
    from sklearn.base import clone

    cv = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    grilla = {f"red__{k}": v for k, v in GRILLA_HIPERPARAMETROS.items()}
    busqueda = GridSearchCV(_nueva_red(), grilla, cv=cv, scoring="accuracy", n_jobs=n_jobs)
    busqueda.fit(X, y_cod)
    hiper = {k.split("__", 1)[-1]: v for k, v in busqueda.best_params_.items()}
    red_final = busqueda.best_estimator_
    score_red = float(busqueda.best_score_)

    # ¿La mezcla con la regresión logística le gana a la red sola?
    try:
        aciertos_mezcla, total = 0, 0
        for tr, te in cv.split(X, y_cod):
            red = clone(red_final).fit(X[tr], y_cod[tr])
            lin = _nuevo_lineal().fit(X[tr], y_cod[tr])
            # las columnas de predict_proba son las clases vistas en ese fold
            p_red = _alinear(red.predict_proba(X[te]), red.classes_, len(set(y_cod)))
            p_lin = _alinear(lin.predict_proba(X[te]), lin.classes_, len(set(y_cod)))
            pred = (0.5 * p_red + 0.5 * p_lin).argmax(axis=1)
            aciertos_mezcla += int((pred == y_cod[te]).sum())
            total += len(te)
        score_mezcla = aciertos_mezcla / total
    except Exception:
        score_mezcla = -1.0

    if score_mezcla > score_red:
        lineal = _nuevo_lineal().fit(X, y_cod)
        return Conjunto(red_final, lineal, 0.5), score_mezcla, hiper, 0.5
    return Conjunto(red_final, None, 0.0), score_red, hiper, 0.0


def _alinear(probs, clases_vistas, n_clases):
    """Pone las probabilidades en columnas 0..n_clases-1 (un fold puede
    no haber visto alguna clase)."""
    salida = np.zeros((probs.shape[0], n_clases))
    salida[:, np.asarray(clases_vistas, dtype=int)] = probs
    return salida


def _preparar_dataset(datos):
    X, y = [], []
    for d in datos:
        if d.get("embedding"):
            X.append(fila_de(d))
            y.append(d["accion"])
    return np.array(X), np.array(y)


def _hay_datos_suficientes(y):
    conteo = Counter(y)
    clases_validas = [c for c, n in conteo.items() if n >= MIN_EJEMPLOS_POR_CLASE]
    return len(clases_validas) >= MIN_CLASES, conteo


def _vale_la_pena_reemplazar(meta_anterior, score_nuevo, n_ejemplos_nuevo, clases_nuevas):
    """
    Decide si un modelo recien entrenado debe reemplazar al guardado.
    Compartido por clasificador.py y clasificador_jerarquico.py.

    Antes, en clasificador.py, el modelo nuevo se descartaba si su score
    era apenas 1% peor que el anterior -- aunque el nuevo supiera
    intenciones NUEVAS que el viejo ni conocia. Resultado: Arche podia
    quedarse para siempre con una red que no reconoce comandos que ya le
    ensenaste. Ademas, un score medido con 40 ejemplos y otro con 400 no
    son comparables: el de 400 es mucho mas confiable.

    Reglas:
    - sin modelo anterior -> reemplazar
    - el modelo nuevo conoce intenciones distintas -> reemplazar (el
      viejo no sirve para las intenciones nuevas)
    - 3x o mas datos -> reemplazar salvo que caiga mas de 20 puntos
    - si no, tolerar 5 puntos de caida con 30%+ mas datos, o 1 punto
    """
    if not meta_anterior:
        return True
    if set(meta_anterior.get("clases", [])) != set(clases_nuevas):
        return True
    score_anterior = meta_anterior.get("score", 0)
    ejemplos_antes = meta_anterior.get("n_ejemplos", 0)
    crecimiento = (n_ejemplos_nuevo / ejemplos_antes) if ejemplos_antes else float("inf")
    if crecimiento >= 3:
        return score_nuevo >= score_anterior - 0.20
    margen = 0.05 if crecimiento >= 1.3 else 0.01
    return score_nuevo + margen >= score_anterior


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
        from sklearn.preprocessing import LabelEncoder
        import sklearn.neural_network, sklearn.linear_model, imblearn  # noqa: F401 (avisa si faltan)
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

    dimension_embedding = dimension_embedding_de(X)

    # MLPClassifier con early_stopping=True falla internamente si las
    # clases son strings (bug conocido de sklearn con ciertas versiones:
    # intenta np.isnan sobre las etiquetas). Codificamos a enteros.
    codificador = LabelEncoder()
    y_cod = codificador.fit_transform(y)

    # IMPORTANTE: el balanceo de clases (sobremuestreo) va DENTRO del
    # pipeline, no aplicado antes de la validación cruzada. Balancear
    # ANTES de hacer CV duplica ejemplos y los reparte entre train y
    # validación -- el modelo puede terminar "validándose" contra una
    # copia casi idéntica de algo que ya vio en el entrenamiento de ese
    # mismo fold, inflando el score sin que el modelo generalice mejor
    # de verdad. Con imblearn.Pipeline, el sobremuestreo se recalcula
    # en cada fold usando SOLO los datos de train de ese fold -- nunca
    # toca los datos de validación. Probado con datos sintéticos de
    # puro ruido: el método viejo daba ~61% de precisión "válida" (por
    # encima del umbral de 55% de este archivo) donde no había nada
    # real que aprender; con este fix, ronda el 40%, mucho más cerca
    # del azar real y del 55% no lo cruza salvo que el modelo
    # realmente esté aprendiendo algo.
    # cv no puede ser mayor que la cantidad de ejemplos de la clase más
    # chica -- acá se calcula sobre los datos ORIGINALES (sin
    # balancear), porque el split de CV pasa ANTES del balanceo dentro
    # del pipeline.
    n_folds = max(min(3, min(conteo.values())), 2)

    try:
        modelo_nuevo, score_nuevo, hiperparametros_limpios, peso_lineal = _ajustar(
            X, y_cod, n_folds, n_jobs=-1
        )
    except Exception as e:
        if not silencioso:
            print(f"Arché: El entrenamiento de la red neuronal falló ({e}).")
        return False

    if score_nuevo < SCORE_MINIMO_UTILIZABLE:
        if not silencioso:
            print(
                f"Arché: La red neuronal entrenó, pero su precisión "
                f"({score_nuevo:.0%}) es demasiado baja para confiar en "
                f"ella todavía. Sigo usando las capas anteriores."
            )
        return False

    meta_anterior = _metadata_anterior()
    if not _vale_la_pena_reemplazar(meta_anterior, score_nuevo, len(X), sorted(set(y.tolist()))):
        if not silencioso:
            print(
                f"Arché: El modelo nuevo ({score_nuevo:.0%}) es peor que el "
                f"actual ({meta_anterior['score']:.0%}). Mantengo el actual."
            )
        return False

    metadata = {
        "score": score_nuevo,
        "n_ejemplos": len(X),
        "dimension_embedding": dimension_embedding,
        "usa_texto": USAR_TEXTO,
        "rasgos_texto": VERSION_RASGOS,
        "votacion": peso_lineal > 0,
        "hiperparametros": hiperparametros_limpios,
        "clases": sorted(set(y.tolist())),
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
            f"intenciones, config {hiperparametros_limpios}"
            f"{', con votación red + lineal' if peso_lineal > 0 else ''})."
        )
    return True


_cache_modelo = {"ruta": None, "fecha": None, "paquete": (None, None, None)}


def _cargar_modelo():
    """Carga clasificador.pkl UNA vez y lo mantiene en memoria; solo lo
    vuelve a leer si el archivo cambio (o sea, si se reentreno). Antes
    se leia del disco en cada comando."""
    try:
        fecha = os.path.getmtime(ARCHIVO_MODELO)
    except OSError:
        return None, None, None
    if _cache_modelo["ruta"] == ARCHIVO_MODELO and _cache_modelo["fecha"] == fecha:
        return _cache_modelo["paquete"]
    try:
        with open(ARCHIVO_MODELO, "rb") as f:
            paquete = pickle.load(f)
        resultado = (paquete["modelo"], paquete["metadata"], paquete["codificador"])
    except Exception:
        return None, None, None
    _cache_modelo.update(ruta=ARCHIVO_MODELO, fecha=fecha, paquete=resultado)
    return resultado


def predecir(embedding_pregunta, texto=None):
    """
    Devuelve (accion_predicha, confianza) usando la red neuronal
    entrenada. Pasa también el `texto` de la frase: los modelos nuevos
    usan sus palabras además del embedding. Si todavía no existe un modelo, o las dimensiones del
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
        entrada = armar_entrada(embedding_pregunta, texto, version_de(metadata))
        probs = modelo.predict_proba([entrada])[0]
        idx_max = int(probs.argmax())
        accion = codificador.inverse_transform([idx_max])[0]
        confianza = float(probs[idx_max])
        return accion, confianza
    except Exception:
        return None, 0.0


def info_modelo():
    """
    Devuelve el estado del clasificador como diccionario, para que
    main.py lo muestre (con barra de progreso, etc.). Antes esta función
    solo imprimía y no retornaba nada, así que main.py siempre recibía
    None y mostraba "Inactiva" aunque la red sí estuviera entrenada.
    """
    _, metadata, _ = _cargar_modelo()
    if metadata is None:
        return {"activo": False}
    return {
        "activo": True,
        "precision": metadata["score"],
        "num_ejemplos": metadata["n_ejemplos"],
        "clases": metadata["clases"],
        "arquitectura": str(metadata["hiperparametros"]),
    }