"""
datos.py  (Fase 4: el dataset de arche-lora)
--------------------------------------------
Arma el dataset de entrenamiento a partir de lo que Arché guardó en
Supabase (tabla arche_ejemplos). Solo libreria estandar: se prueba sin GPU.

  1. LIMPIAR: quita duplicados, frases "contaminadas" (cuando el modelo
     devolvia el prompt como si fuera un ejemplo), frases ambiguas (la
     misma frase con dos intenciones distintas) e intenciones que ya no
     existen en el catalogo.
  2. PARTIR: 10% para VALIDACION que nunca se entrena. La particion es
     ESTABLE (por el hash de la frase): una frase que cayo en validacion
     en la v1 sigue en validacion en la v2, v3... asi el examen siempre
     es sobre ejemplos que ningun modelo vio.
  3. EQUILIBRAR: tope de ejemplos por intencion para que las que tienen
     muchos no tapen a las demas.
  4. REPASO: preguntas de charla general. En Kaggle el modelo base las
     contesta ANTES de entrenar y esas respuestas se mezclan con el
     entrenamiento, para que no olvide conversar.
"""

import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ_ARCHE = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "Arche")
if RAIZ_ARCHE not in sys.path:
    sys.path.insert(0, RAIZ_ARCHE)

from core.IA import catalogo, formato_lora     # noqa: E402

TOPE_POR_INTENCION = 80
MIN_POR_INTENCION = 3          # menos que esto no se puede aprender ni examinar en serio
PORCENTAJE_VALIDACION = 10

# Huellas de un prompt devuelto como si fuera una frase (no palabras normales como "ejemplo" o "contenido")
_MARCAS_CONTAMINACION = ("intencion:", 'intencion"', "intención:", "contenido:", "json", "ejercicio:", "frase:",
                         "{", "}", "<dato>", "respuesta:", "usuario:", "asistente:", "genera ", "escribe una frase")

PREGUNTAS_REPASO = [
    "que es la fotosintesis", "explicame que es una variable en programacion", "como funciona un motor electrico",
    "dame un consejo para concentrarme al estudiar", "que es un numero primo", "por que el cielo es azul",
    "cual es la diferencia entre ram y disco duro", "como se calcula el area de un circulo",
    "que es la inteligencia artificial", "cuentame un dato curioso del espacio", "que es un sensor ultrasonico",
    "para que sirve un transistor", "como se hace una arepa", "que es la ley de ohm",
    "explicame que es una derivada", "que diferencia hay entre un virus y una bacteria",
    "como puedo organizar mejor mi tiempo", "que es un algoritmo", "que es una base de datos",
    "como funciona internet en pocas palabras", "que es la energia solar", "dame una idea para un proyecto con arduino",
    "que significa python en programacion", "como se dice gracias en ingles", "que es un for en c++",
    "por que la luna cambia de forma", "que es un conjunto en matematicas", "que hago si estoy aburrido",
    "como se cuida una planta", "cual es el planeta mas grande", "que es la memoria cache",
    "explicame la diferencia entre and y or", "que es una compuerta logica", "como funciona un servo motor",
    "recomiendame como aprender a programar", "que es la gravedad", "que es un limite en calculo",
    "como se hace un cafe bueno", "que es la nube en informatica", "que es un sistema operativo",
    "hola como estas", "quien eres", "que puedes hacer", "gracias por la ayuda", "buenas noches arche",
    "estoy cansado", "me ayudas con algo", "que opinas de los robots", "cuentame un chiste corto",
    "como te sientes hoy",
]
REPASO_VALIDACION = 8          # las ultimas N preguntas de repaso no se entrenan: sirven para examinar la charla


def normalizar(texto):
    return catalogo.normalizar(texto or "")


def contaminada(frase):
    f = frase.lower()
    return any(m in f for m in _MARCAS_CONTAMINACION) or len(f) > 150 or len(f.split()) > 18


def es_validacion(frase):
    return int(hashlib.sha1(frase.encode("utf-8")).hexdigest()[:8], 16) % 100 < PORCENTAJE_VALIDACION


def limpiar(filas):
    """filas: dicts {frase, intencion, contenido, origen}. Devuelve (limpias, informe)."""
    informe = Counter()
    por_frase = defaultdict(set)
    vistos = {}
    for fila in filas:
        if fila.get("retirado"):
            informe["retirados"] += 1
            continue
        frase = normalizar(fila.get("frase"))
        intencion = catalogo.unificar(fila.get("intencion") or "")
        contenido = normalizar(fila.get("contenido") or "")
        if not frase or intencion not in catalogo.POR_ID:
            informe["intencion_inexistente"] += 1
            continue
        if contaminada(frase):
            informe["contaminadas"] += 1
            continue
        if contenido and contenido not in frase:
            informe["contenido_no_esta_en_la_frase"] += 1
            continue
        por_frase[frase].add(intencion)
        clave = (frase, intencion)
        if clave in vistos:
            informe["duplicadas"] += 1
            continue
        vistos[clave] = {"frase": frase, "intencion": intencion, "contenido": contenido,
                         "origen": fila.get("origen", ""), "dominio": catalogo.POR_ID[intencion]["dominio"]}
    ambiguas = {f for f, ids in por_frase.items() if len(ids) > 1}
    limpias = [v for v in vistos.values() if v["frase"] not in ambiguas]
    informe["ambiguas"] = len(vistos) - len(limpias)
    return limpias, dict(informe)


def partir_y_equilibrar(limpias, semilla=0):
    rng = random.Random(semilla)
    cuenta = Counter(e["intencion"] for e in limpias)
    utiles = [e for e in limpias if cuenta[e["intencion"]] >= MIN_POR_INTENCION]
    entrenamiento, validacion = [], []
    for e in utiles:
        (validacion if es_validacion(e["frase"]) else entrenamiento).append(e)
    por_intencion = defaultdict(list)
    for e in entrenamiento:
        por_intencion[e["intencion"]].append(e)
    equilibrado = []
    for intencion, lista in sorted(por_intencion.items()):
        rng.shuffle(lista)
        equilibrado += lista[:TOPE_POR_INTENCION]
    rng.shuffle(equilibrado)
    return equilibrado, validacion


def construir(filas, version, semilla=0):
    """Devuelve dict con todo lo que necesita Kaggle (se guarda como archivos en el dataset)."""
    limpias, informe = limpiar(filas)
    entrenamiento, validacion = partir_y_equilibrar(limpias, semilla)
    repaso = list(PREGUNTAS_REPASO) + [normalizar(s) for s in catalogo.POR_ID["conversar"]["semillas"]]
    meta = {
        "version": version,
        "version_formato": formato_lora.VERSION_FORMATO,
        "sistema_clasificar": formato_lora.SISTEMA_CLASIFICAR,
        "sistema_charla": formato_lora.SISTEMA_CHARLA,
        "entrenamiento": len(entrenamiento),
        "validacion": len(validacion),
        "intenciones": len({e["intencion"] for e in entrenamiento}),
        "informe_limpieza": informe,
    }
    return {
        "meta": meta,
        "entrenamiento": entrenamiento,
        "validacion": validacion,
        "repaso_entrenar": repaso[:-REPASO_VALIDACION],
        "repaso_validar": repaso[-REPASO_VALIDACION:],
    }


def guardar(paquete, carpeta):
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(paquete["meta"], f, ensure_ascii=False, indent=2)
    for nombre in ("entrenamiento", "validacion"):
        with open(os.path.join(carpeta, f"{nombre}.jsonl"), "w", encoding="utf-8") as f:
            for e in paquete[nombre]:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(carpeta, "repaso.json"), "w", encoding="utf-8") as f:
        json.dump({"entrenar": paquete["repaso_entrenar"], "validar": paquete["repaso_validar"]},
                  f, ensure_ascii=False, indent=2)
