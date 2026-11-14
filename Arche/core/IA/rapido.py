"""
rapido.py
---------
Ubicacion: Arche/core/IA/rapido.py

Hace que Arché ENTIENDA cada orden mucho más rápido, sin cambiar lo que decide.

EL PROBLEMA (medido con 5.000 ejemplos aprendidos)
  En CADA orden, antes de contestar, Arché:
    1. volvía a leer conocimiento.json entero del disco (67 MB: ~0,5 s),
    2. comparaba la frase contra cada ejemplo, uno por uno, en Python,
    3. recompilaba miles de patrones y usaba un comparador de texto lento
       contra todos.
  Resultado: ~1 segundo de espera por orden antes de empezar a pensar, y más
  de 3 segundos cuando además aprendía algo. Y crece con cada cosa que aprende.

LA SOLUCIÓN
  - El archivo se lee UNA vez y queda en memoria; solo se vuelve a leer si
    cambió en el disco (lo modificó el modo estudio, la nube, otro Arché...).
  - Los embeddings se guardan como una sola matriz de numpy: comparar contra
    5.000 ejemplos es una multiplicación (menos de 1 ms).
  - Los patrones se compilan una vez.

Todo lo que entrega este módulo es una COPIA: quien llama puede modificarla
sin dañar lo que está en memoria (igual que cuando se leía del disco).
Si algo no cuadra (archivo raro, embeddings de tamaños distintos), se
devuelve None y el módulo que llama usa su camino de siempre.
"""

import os
import re
import threading

_candado = threading.RLock()
_archivos = {}          # ruta -> {"clave", "maestro", "matriz", "filas", "embs"}
_patrones = {}          # texto del patrón -> patrón compilado


class Datos(list):
    """La lista de siempre, con una marca de qué versión del archivo es."""
    ruta = None
    clave = None


def _clave(ruta):
    try:
        s = os.stat(ruta)
        return (s.st_mtime_ns, s.st_size)
    except OSError:
        return None


def _copia(maestro, ruta, clave):
    datos = Datos(dict(d) if isinstance(d, dict) else d for d in maestro)
    datos.ruta, datos.clave = ruta, clave
    return datos


def cargar(ruta, leer):
    """Devuelve el contenido de `ruta` (una lista de dicts) como copia.
    `leer` es la función del módulo que de verdad lee el archivo: solo se
    llama si el archivo cambió desde la última vez."""
    clave = _clave(ruta)
    with _candado:
        entrada = _archivos.get(ruta)
        if entrada is not None and clave is not None and entrada["clave"] == clave:
            return _copia(entrada["maestro"], ruta, clave)
    datos = leer()
    if not isinstance(datos, list) or clave is None:
        return datos
    with _candado:
        _archivos[ruta] = {"clave": clave, "maestro": datos, "matriz": None, "filas": None, "embs": None}
        return _copia(datos, ruta, clave)


def a_texto(ruta, datos):
    """El JSON de `datos` con UN elemento por línea (sigue siendo JSON normal).
    Devuelve (texto, lineas). Los elementos que no cambiaron desde la última
    vez no se vuelven a convertir: guardar 5.000 ejemplos porque se aprendió
    UNO ya no cuesta convertir los 5.000."""
    import json
    if not isinstance(datos, list):
        return json.dumps(datos, ensure_ascii=False), None
    with _candado:
        entrada = _archivos.get(ruta)
        maestro = entrada["maestro"] if entrada else []
        viejas = (entrada.get("lineas") if entrada else None) or []
    lineas = []
    for i, d in enumerate(datos):
        if i < len(viejas) and viejas[i] is not None and i < len(maestro) and d == maestro[i]:
            lineas.append(viejas[i])
        else:
            lineas.append(json.dumps(d, ensure_ascii=False))
    if not lineas:
        return "[]", lineas
    return "[\n" + ",\n".join(lineas) + "\n]\n", lineas


def guardado(ruta, datos, lineas=None):
    """El módulo avisa que acaba de escribir `datos` en `ruta`: así no hay
    que volver a leer del disco lo que ya tenemos en memoria."""
    clave = _clave(ruta)
    if clave is None or not isinstance(datos, list):
        olvidar(ruta)
        return
    maestro = [dict(d) if isinstance(d, dict) else d for d in datos]
    with _candado:
        vieja = _archivos.get(ruta)
        nueva = {"clave": clave, "maestro": maestro, "matriz": None, "filas": None, "embs": None,
                 "lineas": lineas if lineas is not None and len(lineas) == len(maestro) else None}
        # si los embeddings de antes siguen igual (lo normal: solo se agregó un
        # ejemplo al final), se aprovecha la matriz ya armada
        if vieja is not None and vieja.get("matriz") is not None and vieja["matriz"] is not False:
            try:
                import numpy as np
                filas, embs = _filas(maestro)
                viejos = vieja["embs"]
                n = len(viejos)
                if len(embs) >= n and filas[:n] == vieja["filas"] and all(embs[i] is viejos[i] for i in range(n)):
                    extra = embs[n:]
                    ancho = vieja["matriz"].shape[1]
                    if all(len(e) == ancho for e in extra):
                        matriz = vieja["matriz"] if not extra else np.vstack(
                            [vieja["matriz"], np.asarray(extra, dtype=np.float64)])
                        nueva.update(matriz=matriz, filas=filas, embs=embs)
            except Exception:
                pass
        _archivos[ruta] = nueva


def olvidar(ruta=None):
    """Tira lo que hay en memoria (de un archivo o de todos)."""
    with _candado:
        if ruta is None:
            _archivos.clear()
        else:
            _archivos.pop(ruta, None)


def _filas(maestro):
    filas, embs = [], []
    for i, d in enumerate(maestro):
        e = d.get("embedding") if isinstance(d, dict) else None
        if e:
            filas.append(i)
            embs.append(e)
    return filas, embs


def puntajes(datos, vector):
    """Parecido (producto punto) de `vector` con el embedding de cada ejemplo.
    Devuelve (indices, puntajes): indices[k] es la posición en `datos` y
    puntajes[k] su parecido. None si no se puede hacer rápido (y entonces el
    que llama compara uno por uno, como siempre)."""
    if not isinstance(datos, Datos) or datos.ruta is None:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    with _candado:
        entrada = _archivos.get(datos.ruta)
        if entrada is None or entrada["clave"] != datos.clave or len(entrada["maestro"]) != len(datos):
            return None
        if entrada["matriz"] is None:
            filas, embs = _filas(entrada["maestro"])
            try:
                if not embs or len({len(e) for e in embs}) != 1:
                    raise ValueError("embeddings de tamaños distintos")
                matriz = np.asarray(embs, dtype=np.float64)
                if matriz.ndim != 2:
                    raise ValueError("forma rara")
            except Exception:
                entrada.update(matriz=False, filas=None, embs=None)
                return None
            entrada.update(matriz=matriz, filas=filas, embs=embs)
        if entrada["matriz"] is False:
            return None
        matriz, filas, embs = entrada["matriz"], entrada["filas"], entrada["embs"]
    # la copia que nos pasan debe seguir teniendo los mismos embeddings
    for k, i in enumerate(filas):
        d = datos[i]
        if not isinstance(d, dict) or d.get("embedding") is not embs[k]:
            return None
    if sum(1 for d in datos if isinstance(d, dict) and d.get("embedding")) != len(filas):
        return None
    try:
        v = np.asarray(vector, dtype=np.float64)
        if v.ndim != 1 or v.shape[0] != matriz.shape[1]:
            return None
        return filas, matriz @ v
    except Exception:
        return None


def patron(texto):
    """re.compile con memoria sin límite (re solo recuerda 512 patrones y con
    miles de ejemplos los recompilaba en cada orden)."""
    p = _patrones.get(texto)
    if p is None:
        p = re.compile(texto)
        if len(_patrones) > 50000:
            _patrones.clear()
        _patrones[texto] = p
    return p


def puede_cubrir(frase, parte, umbral):
    """True si `parte` PODRÍA aparecer en `frase` con cobertura >= umbral
    (un trozo seguido de ese largo). Es un filtro rapidísimo: si da False,
    el comparador lento daría menos que el umbral, así que ni se llama."""
    if not parte:
        return False
    largo = len(parte)
    # el menor número de letras seguidas con el que (letras / largo) llega al umbral,
    # calculado con la MISMA división que usa el comparador (sin errores de redondeo)
    minimo = max(0, int(umbral * largo) - 1)
    while minimo / largo < umbral and minimo <= largo:
        minimo += 1
    if minimo > largo:
        return False
    if minimo <= 0:
        return True
    if minimo > len(frase):
        return False
    for i in range(largo - minimo + 1):
        if parte[i:i + minimo] in frase:
            return True
    return False
