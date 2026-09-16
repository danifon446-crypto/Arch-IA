"""
enrutar_cambio.py
--------------------
Ubicacion: Arche/core/IA/enrutar_cambio.py

Permite pedirle un cambio a Arche SIN decirle en que archivo va --
Arche decide solo donde conviene aplicarlo, comparando tu instruccion
contra un indice semantico de todas las funciones del proyecto
(mismo mecanismo de embeddings que ya usa respuestas.py).

Como funciona:
  1. Se arma (y cachea en indice_funciones.json) un embedding de cada
     funcion del proyecto, a partir de su nombre + primera linea de
     docstring si tiene.
  2. Se calcula el embedding de tu instruccion y se compara contra
     TODAS las funciones -- similitud coseno, la misma metrica que
     usa el cache de respuestas.py.
  3. Si el mejor match supera UMBRAL_MATCH_EXISTENTE: se propone el
     cambio como una EDICION de esa funcion/archivo.
     Si NO supera el umbral (nada se parece lo suficiente): se asume
     que es algo nuevo, y se sugiere un archivo nuevo (nombre y
     carpeta derivados de la instruccion con una heuristica simple).

LIMITACION HONESTA: esto es un heuristico de similitud semantica, no
comprension real del proyecto. Puede elegir un destino equivocado si
la instruccion es ambigua. Por eso SIEMPRE se explica en texto por
que eligio ese destino, antes de generar la propuesta -- para que
puedas cortar a tiempo si no tiene sentido (podes seguir usando
"escribe en <archivo> : ..." a mano si preferis elegir vos el destino).

Uso:
    from core.IA.enrutar_cambio import decidir_destino
    decision = decidir_destino("agregar una funcion que cuente las notas")
"""

import ast
import json
import re
import textwrap
from pathlib import Path

from core.IA.autorevision import _archivos_del_proyecto, _funciones_de

BASE = Path(__file__).parent
ARCHIVO_INDICE = BASE / "indice_funciones_cache.json"

# Que tan parecido tiene que ser el mejor match para asumir que ya
# existe una funcion relacionada. Mas bajo que el 0.90 de
# respuestas.py a proposito: ahi buscamos CASI IDENTICO, aca solo
# buscamos "tema relacionado", el umbral tiene que ser mas permisivo.
UMBRAL_MATCH_EXISTENTE = 0.45

# Por encima de esto, confiamos en el ruteo sin preguntar. Entre
# UMBRAL_MATCH_EXISTENTE y este valor, el match "existe" pero es
# flojo -- se marca como confianza_baja para que quien llame decida
# si preguntar antes de proponer (main.py lo usa para pedir
# confirmación en vez de adivinar directo).
UMBRAL_CONFIANZA_ALTA = 0.60

# Carpetas candidatas para archivos nuevos, con palabras clave que
# inclinan la decision hacia cada una. Heuristica simple, no perfecta.
CARPETA_POR_DEFECTO = "core"
PALABRAS_CLAVE_CARPETA_IA = {
    "ollama", "modelo", "ia", "embeddings", "clasificador", "aprendizaje",
    "entrenar", "red neuronal", "autorevision", "propuesta",
}


def _texto_para_embed(nombre_funcion, codigo):
    """Nombre de la funcion + primera linea de docstring (si tiene),
    para representar de que trata sin mandar el codigo entero.

    Usa textwrap.dedent porque funciones anidadas (ej. una funcion
    interna dentro de otra) se extraen con su indentacion original,
    y ast.parse necesita codigo a nivel de columna 0 para no explotar
    con IndentationError."""
    nombre_legible = nombre_funcion.replace("_", " ")

    try:
        arbol = ast.parse(textwrap.dedent(codigo))
        docstring = ast.get_docstring(arbol.body[0]) if arbol.body else None
    except (SyntaxError, IndexError):
        docstring = None

    primera_linea_doc = docstring.strip().splitlines()[0] if docstring else ""
    return f"{nombre_legible}. {primera_linea_doc}".strip()


def _construir_indice():
    """Recorre todo el proyecto, calcula el embedding de cada funcion,
    y lo guarda en cache (no se recalcula nada que no cambio, mismo
    principio que revision_codigo_cache.json en autorevision.py)."""
    from core.IA.embeddings import calcular_embedding

    indice_previo = _cargar_indice()
    indice_nuevo = {}

    for archivo, rel in _archivos_del_proyecto():
        for fn in _funciones_de(archivo):
            clave = f"{rel}::{fn['nombre']}"
            entrada_previa = indice_previo.get(clave)

            if entrada_previa and entrada_previa.get("codigo_hash") == hash(fn["codigo"]):
                indice_nuevo[clave] = entrada_previa
                continue

            texto = _texto_para_embed(fn["nombre"], fn["codigo"])
            try:
                embedding = calcular_embedding(texto)
            except Exception:
                continue

            indice_nuevo[clave] = {
                "archivo": rel,
                "funcion": fn["nombre"],
                "embedding": embedding,
                "codigo_hash": hash(fn["codigo"]),
            }

    _guardar_indice(indice_nuevo)
    return indice_nuevo


def _cargar_indice():
    if not ARCHIVO_INDICE.exists():
        return {}
    try:
        return json.loads(ARCHIVO_INDICE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _guardar_indice(indice):
    ARCHIVO_INDICE.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")


def _sugerir_nombre_archivo_nuevo(instruccion):
    """Heuristica simple: toma las 3-4 palabras significativas de la
    instruccion, arma un nombre snake_case, y elige carpeta segun
    palabras clave. Es un PUNTO DE PARTIDA -- vos podes rechazar la
    propuesta y pedirlo de nuevo con 'escribe en <tu archivo> : ...'
    si el nombre/carpeta sugerido no te convence."""
    instruccion_lower = instruccion.lower()

    palabras_vacias = {
        "que", "para", "una", "un", "el", "la", "los", "las", "de", "del",
        "en", "con", "y", "o", "a", "se", "su", "sus", "esto", "esta",
        "funcion", "función", "archivo", "crear", "creá", "crea", "agregar",
        "agregá", "agrega",
    }
    palabras = [
        p for p in re.findall(r"[a-záéíóúñ]+", instruccion_lower)
        if p not in palabras_vacias
    ][:4]

    if not palabras:
        palabras = ["nueva_funcionalidad"]

    nombre_archivo = "_".join(palabras) + ".py"

    carpeta = CARPETA_POR_DEFECTO
    for palabra_clave in PALABRAS_CLAVE_CARPETA_IA:
        if palabra_clave in instruccion_lower:
            carpeta = "core/IA"
            break

    return f"{carpeta}/{nombre_archivo}"


PALABRAS_DE_AGREGADO = ["agreg", "creá", "crea ", "sumá", "suma ", "nueva función", "nueva funcion"]


def es_pedido_de_agregado(instruccion):
    """True si la instrucción suena a 'agregar algo nuevo' (no a
    'modificar lo que ya existe'). Se usa para decidir si conviene la
    ruta de proponer_agregar_funcion_cerca (mucho mas confiable para
    esto) en vez de proponer_cambio_ia genérico."""
    return any(p in instruccion.lower() for p in PALABRAS_DE_AGREGADO)


def construir_instruccion_final(decision, instruccion_original):
    """
    Arma la instruccion final para el caso de EDICION real (modificar
    una funcion existente, no agregar una nueva -- para eso está
    proponer_agregar_funcion_cerca, mas confiable).
    """
    if decision["tipo"] != "editar_existente" or not decision["funcion"]:
        return instruccion_original

    return f"En la función '{decision['funcion']}': {instruccion_original}"


def decidir_destino(instruccion, recalcular_indice=False):
    """
    Devuelve un diccionario con la decision:
        {
            "tipo": "editar_existente" | "crear_nuevo",
            "archivo": ruta relativa,
            "funcion": nombre (solo si tipo == "editar_existente"),
            "score": similitud (0 a 1),
            "explicacion": texto para mostrarle al usuario,
        }
    """
    from core.IA.embeddings import calcular_embedding, similitud_coseno

    indice = _construir_indice() if recalcular_indice else (_cargar_indice() or _construir_indice())

    if not indice:
        archivo_sugerido = _sugerir_nombre_archivo_nuevo(instruccion)
        return {
            "tipo": "crear_nuevo",
            "archivo": archivo_sugerido,
            "funcion": None,
            "score": 0.0,
            "explicacion": "No encontré funciones existentes en el proyecto para comparar, así que sugiero crear un archivo nuevo.",
        }

    embedding_instruccion = calcular_embedding(instruccion)

    mejor_score = -1.0
    mejor_entrada = None
    for entrada in indice.values():
        score = similitud_coseno(embedding_instruccion, entrada["embedding"])
        if score > mejor_score:
            mejor_score = score
            mejor_entrada = entrada

    if mejor_entrada and mejor_score >= UMBRAL_MATCH_EXISTENTE:
        confianza_alta = mejor_score >= UMBRAL_CONFIANZA_ALTA
        return {
            "tipo": "editar_existente",
            "archivo": mejor_entrada["archivo"],
            "funcion": mejor_entrada["funcion"],
            "score": round(mejor_score, 2),
            "confianza_alta": confianza_alta,
            "explicacion": (
                f"Esto se parece más a la función '{mejor_entrada['funcion']}' "
                f"en {mejor_entrada['archivo']} (similitud {round(mejor_score, 2)}) "
                f"que a cualquier otra cosa del proyecto, así que voy a proponer "
                f"el cambio ahí." + ("" if confianza_alta else " (ojo: la similitud es baja, no estoy muy seguro de este destino)")
            ),
        }

    archivo_sugerido = _sugerir_nombre_archivo_nuevo(instruccion)
    return {
        "tipo": "crear_nuevo",
        "archivo": archivo_sugerido,
        "funcion": None,
        "score": round(max(mejor_score, 0.0), 2),
        "explicacion": (
            f"No encontré nada suficientemente parecido en el código existente "
            f"(lo más cercano fue '{mejor_entrada['funcion']}' en {mejor_entrada['archivo']}, "
            f"pero con poca similitud: {round(mejor_score, 2)}), así que te propongo "
            f"crear un archivo nuevo: {archivo_sugerido}"
        ) if mejor_entrada else "No encontré nada relacionado, te propongo crear un archivo nuevo.",
    }