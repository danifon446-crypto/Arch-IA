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
    GRILLA_HIPERPARAMETROS, _hay_datos_suficientes, _vale_la_pena_reemplazar,
    USAR_TEXTO, armar_entrada, fila_de, dimension_embedding_de,
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
        X.append(fila_de(d))
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
        X.append(fila_de(d))
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
        X.append(fila_de(d))
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
        X.append(fila_de(d))
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

    dimension_embedding = dimension_embedding_de(X)
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
    if not _vale_la_pena_reemplazar(meta_anterior, score_nuevo, len(X), sorted(set(y.tolist()))):
        if not silencioso:
            print(f"Arché: [{etiqueta}] el modelo nuevo ({score_nuevo:.0%}, {len(X)} ejemplos) "
                  f"es peor que el actual ({meta_anterior['score']:.0%}, "
                  f"{meta_anterior.get('n_ejemplos', 0)} ejemplos). Mantengo el actual.")
        return False

    hiperparametros_limpios = {
        clave.split("__", 1)[-1]: valor for clave, valor in busqueda.best_params_.items()
    }
    metadata = {
        "score": score_nuevo,
        "n_ejemplos": len(X),
        "dimension_embedding": dimension_embedding,
        "usa_texto": USAR_TEXTO,
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


# Cache de modelos ya cargados: {archivo: (fecha_modificacion, paquete)}.
# Antes CADA comando volvia a leer del disco 2-3 archivos .pkl; ahora se
# leen una sola vez y solo se recargan si el archivo cambio (reentreno).
_cache_pkl = {}


def _cargar_pkl(archivo):
    try:
        fecha = os.path.getmtime(archivo)
    except OSError:
        return None, None, None
    guardado = _cache_pkl.get(archivo)
    if guardado and guardado[0] == fecha:
        return guardado[1]
    try:
        with open(archivo, "rb") as f:
            paquete = pickle.load(f)
        resultado = (paquete["modelo"], paquete["metadata"], paquete["codificador"])
    except Exception:
        return None, None, None
    _cache_pkl[archivo] = (fecha, resultado)
    return resultado


def _distribucion(archivo, embedding, texto=None):
    """
    Probabilidades COMPLETAS de una red: [(etiqueta, prob), ...] de
    mayor a menor. None si la red no existe todavia o las dimensiones
    del embedding no calzan.
    """
    modelo, metadata, codificador = _cargar_pkl(archivo)
    if modelo is None:
        return None
    if len(embedding) != metadata.get("dimension_embedding"):
        return None
    try:
        entrada = armar_entrada(embedding, texto, metadata.get("usa_texto", False))
        probs = modelo.predict_proba([entrada])[0]
        # modelo.classes_ son los enteros del LabelEncoder, en el mismo
        # orden que las columnas de predict_proba.
        etiquetas = codificador.inverse_transform(modelo.classes_)
        pares = [(str(e), float(p)) for e, p in zip(etiquetas, probs)]
        return sorted(pares, key=lambda par: -par[1])
    except Exception:
        return None


def _predecir_con(archivo):
    """Igual que antes (se conserva por compatibilidad): devuelve una
    funcion que predice (etiqueta, confianza) con la red de `archivo`."""
    if _cargar_pkl(archivo)[0] is None:
        return None

    def _predecir(embedding, texto=None):
        dist = _distribucion(archivo, embedding, texto)
        return dist[0] if dist else None

    return _predecir


# Cuantos caminos se exploran en cada nivel del arbol, y desde que
# probabilidad vale la pena explorar una rama.
CAMINOS_POR_NIVEL = 2
PROB_MINIMA_RAMA = 0.05


def _intenciones_dentro_de(dominio, embedding, texto=None):
    """[(intencion, prob DENTRO del dominio)] bajando por subdominios si
    los hay. Lista vacia si falta alguna red en ese camino."""
    if not dominios.tiene_subdominios(dominio):
        ids = dominios.intenciones_de(dominio)
        if len(ids) == 1:
            return [(next(iter(ids)), 1.0)]
        return _distribucion(_archivo_submodelo(dominio), embedding, texto) or []

    dist_sub = _distribucion(_archivo_subdominio(dominio), embedding, texto)
    if not dist_sub:
        return []
    resultado = []
    for sub, p_sub in dist_sub[:CAMINOS_POR_NIVEL]:
        if p_sub < PROB_MINIMA_RAMA:
            continue
        ids = dominios.subdominios_de(dominio).get(sub, set())
        if len(ids) == 1:
            resultado.append((next(iter(ids)), p_sub))
            continue
        dist_int = _distribucion(_archivo_submodelo_sub(dominio, sub), embedding, texto) or []
        resultado.extend((accion, p_sub * p_int) for accion, p_int in dist_int)
    return resultado


def predecir_jerarquico(embedding_pregunta, texto=None):
    """
    Predice bajando por el arbol (dominio -> subdominio -> intencion).

    MEJORA DE PRECISION (antes vs ahora):
    - Antes seguia SOLO el dominio mas probable. Si la red de dominio se
      equivocaba (ej. dudaba 48% / 45% entre dos), todo lo de abajo ya
      estaba perdido. Ahora explora los CAMINOS_POR_NIVEL mejores
      dominios (y subdominios) y se queda con la intencion de mayor
      probabilidad TOTAL.
    - Antes la confianza devuelta era solo la de la ultima red, aunque
      el dominio hubiera salido con 40%. Ahora es la probabilidad del
      camino completo (P(dominio) x P(subdominio) x P(intencion)), que
      es lo que de verdad mide que tan seguro esta el arbol.

    Pasa tambien el `texto` de la frase: las redes nuevas usan sus
    palabras ademas del embedding (ver clasificador.armar_entrada).

    Devuelve (accion, confianza, dominio) o (None, confianza_hasta_ahi,
    dominio_o_None) si falta algun modelo entrenado.
    """
    dist_dom = _distribucion(ARCHIVO_MODELO_DOMINIO, embedding_pregunta, texto)
    if not dist_dom:
        return None, 0.0, None

    mejor = (None, 0.0, None)
    for dominio, p_dom in dist_dom[:CAMINOS_POR_NIVEL]:
        if p_dom < PROB_MINIMA_RAMA:
            continue
        for accion, p_int in _intenciones_dentro_de(dominio, embedding_pregunta, texto):
            total = p_dom * p_int
            if total > mejor[1]:
                mejor = (accion, total, dominio)

    if mejor[0] is None:
        dominio_top, p_top = dist_dom[0]
        return None, p_top, dominio_top
    return mejor


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