"""
clasificador_jerarquico.py
---------------------------
Ubicacion: Arche/core/IA/clasificador_jerarquico.py

Pieza 2 del Aula de Entrenamiento Progresivo: en vez de UNA red que
intenta distinguir TODAS las intenciones a la vez (lo que hace hoy
clasificador.py), dos niveles:

  1. Red de dominio: dado un embedding, predice el dominio general
     (sistema, codigo, conversacion, memoria -- ver dominios.py).
  2. Red del dominio: una vez identificado el dominio, una red mas
     chica y afinada -- entrenada SOLO con ejemplos de ese dominio --
     decide la intencion exacta entre pocas clases parecidas.

Por que aparte de clasificador.py, no adentro:
  clasificador.py ya funciona y Arche depende de el en cada comando.
  Esta version jerarquica se guarda en sus PROPIOS archivos .pkl,
  separados de clasificador.pkl -- entrenar o predecir aca nunca toca
  ni sobreescribe el modelo actual. Mientras este modulo no se conecte
  a comprender()/cerebroIA.py (esa conexion es un paso aparte y
  deliberado), Arche sigue exactamente igual que hoy.

Reutiliza la MISMA logica de validacion que clasificador.py (cross-
validation, no sobreescribir con algo peor, umbral minimo de
confianza) -- son las mismas constantes, importadas de ahi, no
reinventadas.

Requiere lo mismo que clasificador.py:
    pip install scikit-learn numpy imbalanced-learn
"""

import os
import pickle
from collections import Counter

import numpy as np

from core.IA import dominios
from core.IA.clasificador import (
    MIN_EJEMPLOS_POR_CLASE, MIN_CLASES, SCORE_MINIMO_UTILIZABLE,
    GRILLA_HIPERPARAMETROS, _hay_datos_suficientes,
)

BASE = os.path.dirname(__file__)
ARCHIVO_MODELO_DOMINIO = os.path.join(BASE, "clasificador_dominio.pkl")


def _archivo_submodelo(dominio_nombre):
    return os.path.join(BASE, f"clasificador_dominio_{dominio_nombre}.pkl")


def _preparar_dataset_dominio(datos):
    """Como _preparar_dataset de clasificador.py, pero la etiqueta `y`
    es el DOMINIO de cada acción (no la acción en sí). Descarta
    ejemplos cuya acción no tenga dominio mapeado (ver dominios.SIN_DOMINIO)."""
    X, y = [], []
    for d in datos:
        if not d.get("embedding"):
            continue
        dom = dominios.dominio_de(d.get("accion"))
        if dom is None:
            continue
        X.append(d["embedding"])
        y.append(dom)
    return np.array(X), np.array(y)


def _preparar_dataset_intencion(datos, dominio_nombre):
    """Como _preparar_dataset de clasificador.py, pero SOLO con los
    ejemplos cuya acción pertenece a `dominio_nombre`."""
    X, y = [], []
    for d in datos:
        if not d.get("embedding"):
            continue
        if dominios.dominio_de(d.get("accion")) != dominio_nombre:
            continue
        X.append(d["embedding"])
        y.append(d["accion"])
    return np.array(X), np.array(y)


def _metadata_anterior(archivo):
    if not os.path.exists(archivo):
        return None
    try:
        with open(archivo, "rb") as f:
            return pickle.load(f).get("metadata")
    except Exception:
        return None


def _entrenar_una_red(X, y, archivo_destino, etiqueta, silencioso):
    """
    Nucleo de entrenamiento compartido por la red de dominio y cada red
    de intención: valida con cross-validation, balancea clases dentro
    del pipeline (no antes, por la misma razón documentada en
    clasificador.py: balancear antes de la validación infla el score
    sin que el modelo generalice mejor de verdad), busca
    hiperparámetros, y NUNCA sobreescribe un modelo mejor con uno peor.

    Devuelve True si guardó un modelo nuevo/actualizado, False si no.
    """
    try:
        from sklearn.neural_network import MLPClassifier
        from sklearn.model_selection import GridSearchCV, StratifiedKFold
        from sklearn.preprocessing import LabelEncoder
        from imblearn.pipeline import Pipeline as PipelineDesbalanceado
        from imblearn.over_sampling import RandomOverSampler
    except ImportError as e:
        if not silencioso:
            print(f"Arché: Falta una dependencia para el clasificador jerárquico ({e}).")
        return False

    if len(X) == 0:
        return False

    suficiente, conteo = _hay_datos_suficientes(y)
    if not suficiente:
        if not silencioso:
            print(f"Arché: [{etiqueta}] todavía no hay suficientes ejemplos "
                  f"(se necesitan al menos {MIN_EJEMPLOS_POR_CLASE} por clase, "
                  f"{MIN_CLASES}+ clases). Progreso: {dict(conteo)}")
        return False

    dimension_embedding = X.shape[1]
    codificador = LabelEncoder()
    y_cod = codificador.fit_transform(y)

    pipeline = PipelineDesbalanceado([
        ("balanceo", RandomOverSampler(random_state=42)),
        ("red", MLPClassifier(max_iter=2000, random_state=42)),
    ])
    grilla_pipeline = {f"red__{clave}": valores for clave, valores in GRILLA_HIPERPARAMETROS.items()}

    n_folds = max(min(3, min(conteo.values())), 2)

    try:
        cv = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
        busqueda = GridSearchCV(pipeline, grilla_pipeline, cv=cv, scoring="accuracy", n_jobs=-1)
        busqueda.fit(X, y_cod)
    except Exception as e:
        if not silencioso:
            print(f"Arché: [{etiqueta}] el entrenamiento falló ({e}).")
        return False

    score_nuevo = busqueda.best_score_
    modelo_nuevo = busqueda.best_estimator_

    if score_nuevo < SCORE_MINIMO_UTILIZABLE:
        if not silencioso:
            print(f"Arché: [{etiqueta}] entrenó, pero su precisión ({score_nuevo:.0%}) "
                  f"es demasiado baja para confiar en ella todavía.")
        return False

    meta_anterior = _metadata_anterior(archivo_destino)
    if meta_anterior and meta_anterior.get("score", 0) > score_nuevo + 0.01:
        if not silencioso:
            print(f"Arché: [{etiqueta}] el modelo nuevo ({score_nuevo:.0%}) es peor "
                  f"que el actual ({meta_anterior['score']:.0%}). Mantengo el actual.")
        return False

    hiperparametros_limpios = {
        clave.split("__", 1)[-1]: valor for clave, valor in busqueda.best_params_.items()
    }
    metadata = {
        "score": score_nuevo,
        "n_ejemplos": len(X),
        "dimension_embedding": dimension_embedding,
        "hiperparametros": hiperparametros_limpios,
        "clases": sorted(set(y.tolist())),
    }
    with open(archivo_destino, "wb") as f:
        pickle.dump({"modelo": modelo_nuevo, "metadata": metadata, "codificador": codificador}, f)

    if not silencioso:
        print(f"Arché: [{etiqueta}] actualizado. Precisión: {score_nuevo:.0%} "
              f"({len(X)} ejemplos, {len(metadata['clases'])} clases).")
    return True


def entrenar_jerarquico(silencioso=False):
    """
    Entrena la red de dominio y, para cada dominio con datos
    suficientes, su red de intención. Un dominio sin datos suficientes
    simplemente no se entrena todavía -- no hace fallar al resto.

    Devuelve un dict {"dominio": bool, "sistema": bool, ...} con qué se
    actualizó en esta corrida.
    """
    from core.IA.aprendizaje import cargar
    datos = cargar()

    resultado = {}

    X_dom, y_dom = _preparar_dataset_dominio(datos)
    resultado["dominio"] = _entrenar_una_red(
        X_dom, y_dom, ARCHIVO_MODELO_DOMINIO, "red de dominio", silencioso
    )

    for nombre_dominio in dominios.nombres_de_dominios():
        X_int, y_int = _preparar_dataset_intencion(datos, nombre_dominio)
        resultado[nombre_dominio] = _entrenar_una_red(
            X_int, y_int, _archivo_submodelo(nombre_dominio),
            f"red de '{nombre_dominio}'", silencioso
        )

    if not silencioso:
        huerfanas = dominios.validar({d.get("accion") for d in datos if d.get("accion")})
        if huerfanas:
            print(f"Arché: Ojo, estas intenciones no tienen dominio asignado en "
                  f"dominios.py, así que no entrenan en el clasificador jerárquico: {huerfanas}")

    return resultado


def _cargar_pkl(archivo):
    if not os.path.exists(archivo):
        return None, None, None
    try:
        with open(archivo, "rb") as f:
            paquete = pickle.load(f)
        return paquete["modelo"], paquete["metadata"], paquete["codificador"]
    except Exception:
        return None, None, None


def predecir_jerarquico(embedding_pregunta):
    """
    Dos pasos: primero predice el DOMINIO, después -- con la red propia
    de ese dominio -- predice la INTENCIÓN exacta. Devuelve
    (accion, confianza, dominio) o (None, 0.0, None) si algo en la
    cadena no está disponible o las dimensiones no calzan (mismo
    criterio de seguridad que clasificador.predecir()).
    """
    modelo_dom, meta_dom, cod_dom = _cargar_pkl(ARCHIVO_MODELO_DOMINIO)
    if modelo_dom is None:
        return None, 0.0, None
    if len(embedding_pregunta) != meta_dom.get("dimension_embedding"):
        return None, 0.0, None

    try:
        probs_dom = modelo_dom.predict_proba([embedding_pregunta])[0]
        idx_dom = int(probs_dom.argmax())
        dominio_predicho = cod_dom.inverse_transform([idx_dom])[0]
        confianza_dom = float(probs_dom[idx_dom])
    except Exception:
        return None, 0.0, None

    modelo_int, meta_int, cod_int = _cargar_pkl(_archivo_submodelo(dominio_predicho))
    if modelo_int is None:
        # Sabemos el dominio pero todavía no hay red entrenada para él
        return None, confianza_dom, dominio_predicho
    if len(embedding_pregunta) != meta_int.get("dimension_embedding"):
        return None, confianza_dom, dominio_predicho

    try:
        probs_int = modelo_int.predict_proba([embedding_pregunta])[0]
        idx_int = int(probs_int.argmax())
        accion = cod_int.inverse_transform([idx_int])[0]
        confianza_int = float(probs_int[idx_int])
    except Exception:
        return None, confianza_dom, dominio_predicho

    return accion, confianza_int, dominio_predicho


def info_jerarquico():
    """Como clasificador.info_modelo(), pero para toda la jerarquía --
    útil para un futuro comando 'estado red jerarquica'."""
    info = {}
    _, meta_dom, _ = _cargar_pkl(ARCHIVO_MODELO_DOMINIO)
    info["dominio"] = {"activo": meta_dom is not None}
    if meta_dom:
        info["dominio"].update({
            "precision": meta_dom["score"], "n_ejemplos": meta_dom["n_ejemplos"],
            "clases": meta_dom["clases"],
        })
    for nombre_dominio in dominios.nombres_de_dominios():
        _, meta, _ = _cargar_pkl(_archivo_submodelo(nombre_dominio))
        info[nombre_dominio] = {"activo": meta is not None}
        if meta:
            info[nombre_dominio].update({
                "precision": meta["score"], "n_ejemplos": meta["n_ejemplos"],
                "clases": meta["clases"],
            })
    return info