"""
clasificador_jerarquico.py
---------------------------
Ubicacion: Arche/core/IA/clasificador_jerarquico.py

En vez de UNA red que intenta distinguir TODAS las intenciones a la
vez (lo que hace clasificador.py), entrena en niveles:

  1. Red de DOMINIO: dado un embedding, predice el dominio general
     (sistema, codigo, conversacion, memoria, arche... -- ver
     dominios.py / catalogo.py).
  2. Si ese dominio se partió en SUBDOMINIOS (ej. 'arche' tiene 23
     intenciones, repartidas en 6 sub-temas: ayuda, estudio,
     autoconocimiento, examen, objetivos, entrenamiento -- ver
     catalogo.SUBDOMINIOS_ASIGNADOS), una red del dominio predice el
     SUBDOMINIO, y recien ahi una red MAS CHICA, entrenada solo con
     las pocas intenciones de ESE subdominio, decide la intencion
     exacta -- "miniredes de las miniredes": cada una pelea contra
     muchas menos clases parecidas entre si que una sola red del
     dominio entero.
  3. Si el dominio NO tiene subdominios (la mayoria: notas, archivos,
     calculadora, sistema, configuracion, conversacion, tiempo, web),
     se salta el paso 2 y va directo del dominio a la intencion, como
     siempre -- dos niveles, sin cambios de comportamiento.

Por que aparte de clasificador.py, no adentro: clasificador.py ya
funciona y Arche depende de el en cada comando. Esta version jerarquica
se guarda en sus PROPIOS archivos .pkl, separados de clasificador.pkl
-- entrenar o predecir aca nunca toca ni sobreescribe el modelo actual.

Reutiliza la MISMA logica de validacion que clasificador.py (cross-
validation, no sobreescribir con algo peor salvo que haya MUCHOS mas
datos, umbral minimo de confianza) -- las mismas constantes, importadas
de ahi, no reinventadas.

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
    """Red de intención de un dominio SIN subdominios (dos niveles)."""
    return os.path.join(BASE, f"clasificador_dominio_{dominio_nombre}.pkl")


def _archivo_subdominio(dominio_nombre):
    """Red que, DENTRO de un dominio con subdominios, predice CUÁL
    subdominio (paso intermedio del árbol de tres niveles)."""
    return os.path.join(BASE, f"clasificador_dominio_{dominio_nombre}__subdominios.pkl")


def _archivo_submodelo_sub(dominio_nombre, subdominio_nombre):
    """Red de intención de UN subdominio puntual (tercer nivel)."""
    return os.path.join(BASE, f"clasificador_dominio_{dominio_nombre}__{subdominio_nombre}.pkl")


def _preparar_dataset_dominio(datos):
    """y = DOMINIO de cada ejemplo. Descarta ejemplos cuya acción no
    tenga dominio mapeado (ver dominios.SIN_DOMINIO)."""
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
    """y = INTENCIÓN, solo ejemplos de `dominio_nombre` (dos niveles,
    dominio sin subdominios)."""
    X, y = [], []
    for d in datos:
        if not d.get("embedding"):
            continue
        if dominios.dominio_de(d.get("accion")) != dominio_nombre:
            continue
        X.append(d["embedding"])
        y.append(d["accion"])
    return np.array(X), np.array(y)


def _preparar_dataset_subdominio(datos, dominio_nombre):
    """y = SUBDOMINIO, solo ejemplos de `dominio_nombre` cuya acción
    tiene subdominio asignado (paso intermedio del árbol de tres
    niveles)."""
    X, y = [], []
    for d in datos:
        if not d.get("embedding"):
            continue
        accion = d.get("accion")
        if dominios.dominio_de(accion) != dominio_nombre:
            continue
        sub = dominios.subdominio_de(accion)
        if sub is None:
            continue
        X.append(d["embedding"])
        y.append(sub)
    return np.array(X), np.array(y)


def _preparar_dataset_intencion_en_subdominio(datos, subdominio_nombre):
    """y = INTENCIÓN, solo ejemplos cuya acción pertenece a
    `subdominio_nombre` (tercer nivel, la minired de la minired)."""
    X, y = [], []
    for d in datos:
        if not d.get("embedding"):
            continue
        if dominios.subdominio_de(d.get("accion")) != subdominio_nombre:
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
    Nucleo de entrenamiento compartido por CUALQUIER nivel del árbol
    (dominio, subdominio, o intención): valida con cross-validation,
    balancea clases dentro del pipeline, busca hiperparámetros, y NUNCA
    sobreescribe un modelo mejor con uno peor -- salvo que haya MUCHOS
    más datos que la última vez, en cuyo caso se tolera una caída de
    precisión mayor (un score medido con pocos ejemplos es una
    estimación poco confiable; con varias veces más datos, preferimos
    el modelo nuevo aunque su CV score baje un poco).

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
        # n_jobs=1 A PROPOSITO, no -1: el reentreno automático puede
        # dispararse desde un hilo de fondo (examen automático,
        # entrenamiento masivo, aprendizaje.aprender() al cruzar
        # UMBRAL_REENTRENO) -- en Windows, lanzar procesos en paralelo
        # desde un hilo que no es el principal puede colgarse en
        # silencio, sin error ni aviso, para siempre. La grilla es
        # chica (9 combinaciones), así que perder el paralelismo no
        # se nota en el tiempo, y evita el cuelgue por completo.
        busqueda = GridSearchCV(pipeline, grilla_pipeline, cv=cv, scoring="accuracy", n_jobs=1)
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
    if meta_anterior:
        ejemplos_antes = meta_anterior.get("n_ejemplos", 0)
        crecimiento = (len(X) / ejemplos_antes) if ejemplos_antes else float("inf")
        if crecimiento >= 3 and score_nuevo >= SCORE_MINIMO_UTILIZABLE and score_nuevo >= meta_anterior.get("score", 0) - 0.20:
            pass  # bastantes más datos (3x+): se acepta aunque el score baje algo
        else:
            margen = 0.05 if crecimiento >= 1.3 else 0.01
            if meta_anterior.get("score", 0) > score_nuevo + margen:
                if not silencioso:
                    print(f"Arché: [{etiqueta}] el modelo nuevo ({score_nuevo:.0%}, {len(X)} ejemplos) "
                          f"es peor que el actual ({meta_anterior['score']:.0%}, {ejemplos_antes} ejemplos). "
                          f"Mantengo el actual.")
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
    Entrena TODO el árbol: la red de dominio y, para cada dominio,

      - si tiene subdominios (ver dominios.tiene_subdominios): la red
        de subdominio, y luego una red de intención POR SUBDOMINIO
        (tres niveles, "miniredes de las miniredes").
      - si no: una única red de intención para el dominio entero
        (dos niveles, como siempre).

    Un dominio/subdominio sin datos suficientes simplemente no se
    entrena todavía -- no hace fallar al resto.

    Devuelve un dict {clave: bool} con qué se actualizó en esta corrida.
    """
    from core.IA.aprendizaje import cargar
    datos = cargar()

    resultado = {}

    X_dom, y_dom = _preparar_dataset_dominio(datos)
    resultado["dominio"] = _entrenar_una_red(
        X_dom, y_dom, ARCHIVO_MODELO_DOMINIO, "red de dominio", silencioso
    )

    for nombre_dominio in dominios.nombres_de_dominios():
        if dominios.tiene_subdominios(nombre_dominio):
            X_sub, y_sub = _preparar_dataset_subdominio(datos, nombre_dominio)
            resultado[f"{nombre_dominio} (subdominios)"] = _entrenar_una_red(
                X_sub, y_sub, _archivo_subdominio(nombre_dominio),
                f"subdominios de '{nombre_dominio}'", silencioso
            )
            for subdominio, ids_subdominio in dominios.subdominios_de(nombre_dominio).items():
                if len(ids_subdominio) < 2:
                    continue  # subdominio trivial (una sola intención): no necesita red propia
                X_int, y_int = _preparar_dataset_intencion_en_subdominio(datos, subdominio)
                resultado[f"{nombre_dominio}.{subdominio}"] = _entrenar_una_red(
                    X_int, y_int, _archivo_submodelo_sub(nombre_dominio, subdominio),
                    f"red de '{nombre_dominio}.{subdominio}'", silencioso
                )
        else:
            X_int, y_int = _preparar_dataset_intencion(datos, nombre_dominio)
            resultado[nombre_dominio] = _entrenar_una_red(
                X_int, y_int, _archivo_submodelo(nombre_dominio),
                f"red de '{nombre_dominio}'", silencioso
            )

    if not silencioso:
        huerfanas = dominios.validar({d.get("accion") for d in datos if d.get("accion")})
        if huerfanas:
            print(f"Arché: Ojo, estas intenciones no tienen dominio asignado en "
                  f"catalogo.py, así que no entrenan en el clasificador jerárquico: {huerfanas}")

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


def _predecir_con(archivo):
    """Carga un modelo y predice sobre el embedding que le pases luego
    -- envuelto en una función chica para no repetir el mismo bloque
    try/except en cada nivel del árbol."""
    modelo, metadata, codificador = _cargar_pkl(archivo)
    if modelo is None:
        return None

    def _predecir(embedding):
        if len(embedding) != metadata.get("dimension_embedding"):
            return None
        try:
            probs = modelo.predict_proba([embedding])[0]
            idx = int(probs.argmax())
            etiqueta = codificador.inverse_transform([idx])[0]
            return etiqueta, float(probs[idx])
        except Exception:
            return None

    return _predecir


def predecir_jerarquico(embedding_pregunta):
    """
    Predice bajando por el árbol: dominio, y si ese dominio tiene
    subdominios, subdominio, y recién ahí la intención -- con la red
    más chica y específica disponible en cada paso. Si un subdominio
    tiene una sola intención posible (ver entrenar_jerarquico), no hace
    falta ninguna red ahí: se resuelve directo, sin margen de error en
    ese paso.

    Devuelve (accion, confianza, dominio) o (None, confianza_hasta_ahi,
    dominio_o_None) si la cadena se corta en algún punto por falta de
    modelo entrenado o dimensiones que no calzan.
    """
    predecir_dominio = _predecir_con(ARCHIVO_MODELO_DOMINIO)
    if predecir_dominio is None:
        return None, 0.0, None

    resultado_dominio = predecir_dominio(embedding_pregunta)
    if resultado_dominio is None:
        return None, 0.0, None
    dominio_predicho, confianza_dominio = resultado_dominio

    if not dominios.tiene_subdominios(dominio_predicho):
        predecir_intencion = _predecir_con(_archivo_submodelo(dominio_predicho))
        if predecir_intencion is None:
            return None, confianza_dominio, dominio_predicho
        resultado_intencion = predecir_intencion(embedding_pregunta)
        if resultado_intencion is None:
            return None, confianza_dominio, dominio_predicho
        accion, confianza_intencion = resultado_intencion
        return accion, confianza_intencion, dominio_predicho

    # --- dominio con subdominios: un paso más en el árbol ---
    predecir_subdominio = _predecir_con(_archivo_subdominio(dominio_predicho))
    if predecir_subdominio is None:
        return None, confianza_dominio, dominio_predicho
    resultado_subdominio = predecir_subdominio(embedding_pregunta)
    if resultado_subdominio is None:
        return None, confianza_dominio, dominio_predicho
    subdominio_predicho, confianza_subdominio = resultado_subdominio

    ids_del_subdominio = dominios.subdominios_de(dominio_predicho).get(subdominio_predicho, set())
    if len(ids_del_subdominio) == 1:
        # subdominio trivial: una sola intención posible, se resuelve directo
        return next(iter(ids_del_subdominio)), confianza_subdominio, dominio_predicho

    predecir_intencion = _predecir_con(_archivo_submodelo_sub(dominio_predicho, subdominio_predicho))
    if predecir_intencion is None:
        return None, confianza_subdominio, dominio_predicho
    resultado_intencion = predecir_intencion(embedding_pregunta)
    if resultado_intencion is None:
        return None, confianza_subdominio, dominio_predicho
    accion, confianza_intencion = resultado_intencion
    return accion, confianza_intencion, dominio_predicho


def info_jerarquico():
    """Como clasificador.info_modelo(), pero para todo el árbol --
    incluye subdominios cuando el dominio los tiene."""
    info = {}
    _, meta_dom, _ = _cargar_pkl(ARCHIVO_MODELO_DOMINIO)
    info["dominio"] = {"activo": meta_dom is not None}
    if meta_dom:
        info["dominio"].update({
            "precision": meta_dom["score"], "n_ejemplos": meta_dom["n_ejemplos"],
            "clases": meta_dom["clases"],
        })

    for nombre_dominio in dominios.nombres_de_dominios():
        if dominios.tiene_subdominios(nombre_dominio):
            _, meta_sub, _ = _cargar_pkl(_archivo_subdominio(nombre_dominio))
            clave_sub = f"{nombre_dominio} (subdominios)"
            info[clave_sub] = {"activo": meta_sub is not None}
            if meta_sub:
                info[clave_sub].update({
                    "precision": meta_sub["score"], "n_ejemplos": meta_sub["n_ejemplos"],
                    "clases": meta_sub["clases"],
                })
            for subdominio, ids_subdominio in dominios.subdominios_de(nombre_dominio).items():
                clave = f"{nombre_dominio}.{subdominio}"
                if len(ids_subdominio) == 1:
                    info[clave] = {"activo": True, "trivial": True}
                    continue
                _, meta, _ = _cargar_pkl(_archivo_submodelo_sub(nombre_dominio, subdominio))
                info[clave] = {"activo": meta is not None}
                if meta:
                    info[clave].update({
                        "precision": meta["score"], "n_ejemplos": meta["n_ejemplos"],
                        "clases": meta["clases"],
                    })
        else:
            _, meta, _ = _cargar_pkl(_archivo_submodelo(nombre_dominio))
            info[nombre_dominio] = {"activo": meta is not None}
            if meta:
                info[nombre_dominio].update({
                    "precision": meta["score"], "n_ejemplos": meta["n_ejemplos"],
                    "clases": meta["clases"],
                })
    return info