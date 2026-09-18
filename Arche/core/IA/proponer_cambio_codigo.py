"""
proponer_cambio_codigo.py
--------------------------
Ubicacion: Arche/core/IA/proponer_cambio_codigo.py

Genera propuestas de cambio para CUALQUIER archivo del proyecto (a
diferencia de propuestas.py, que solo puede tocar preguntas_frecuentes.py).

Dos tipos de propuesta:
  1. Editar un archivo existente: un cambio "buscar y reemplazar" --
     un fragmento EXACTO de texto que debe existir una sola vez, y el
     texto que lo reemplaza.
  2. Crear un archivo NUEVO: contenido completo nuevo, para una ruta
     que todavia no existe.

Tres formas de generar una propuesta:
  1. proponer_cambio_manual(...) -- vos das buscar/reemplazar directo
     (o solo reemplazar, para un archivo nuevo), sin usar el modelo.
     100% deterministico.
  2. proponer_cambio_ia(...) -- le pasas una instruccion en lenguaje
     natural y el archivo destino; Ollama redacta buscar/reemplazar
     (si el archivo existe) o el contenido completo (si es nuevo).

NINGUNA de las dos funciones toca el archivo real. Eso solo pasa en
revisar_cambios_codigo.py, con tu aprobacion explicita cada vez.

LIMITE DURO: no se puede proponer un cambio sobre los archivos que
controlan este mismo sistema (ver ARCHIVOS_PROTEGIDOS). Si necesitas
tocar esos, hacelo vos a mano -- es la unica forma de garantizar que
Arche no pueda aflojar sus propias restricciones desde adentro.

VALIDACION DE EXTENSION: cualquier archivo nuevo tiene que tener
extension (ej. ".py") -- esto existe porque una vez se guardo un
archivo nuevo sin extension por error humano al copiarlo a mano, y
quedo huerfano del sistema de imports. Ahora se rechaza en el momento
de proponer, no despues.

"""

import os
import ast
import builtins
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from core.IA.ollamaIA import consultar_ollama

def generar_propuesta_codigo(prompt_instruccion, ruta_archivo):
    """
    Lee el archivo objetivo, construye la solicitud estructurada
    y devuelve el código generado libre de texto explicativo.
    """
    codigo_actual = ""
    if os.path.exists(ruta_archivo):
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            codigo_actual = f.read()

    system_prompt = (
        "Eres el motor de desarrollo interno de Arché. Tu tarea es escribir o refactorizar código en Python.\n"
        "REGLAS CRÍTICAS:\n"
        "1. Devuelve ÚNICAMENTE el código Python completo dentro de un bloque ```python ... ```.\n"
        "2. No agregues explicaciones, introducciones ni saludos.\n"
        "3. El código debe ser completamente funcional, eficiente y sin errores de sintaxis.\n"
    )

    user_prompt = f"""
Instrucción de mejora: {prompt_instruccion}

Código actual del archivo ({os.path.basename(ruta_archivo)}):
```python
{codigo_actual}

_NOMBRES_BUILTIN = set(dir(builtins)) | {"self", "cls"}

# Este archivo vive en Arche/core/IA/, dos niveles abajo de la raiz real
RAIZ_APP = Path(__file__).resolve().parents[2]
BASE = Path(__file__).parent

ARCHIVO_PENDIENTES = BASE / "cambios_codigo_pendientes.json"
ARCHIVO_LOG = BASE / "cambios_codigo_log.jsonl"

# Archivos que Arche NUNCA puede proponer modificar: son los que
# controlan el propio sistema de propuestas/revision. Si estos se
# pudieran tocar, Arche podria en teoria aflojar sus propias reglas.
ARCHIVOS_PROTEGIDOS = {
    "core/IA/proponer_cambio_codigo.py",
    "core/IA/revisar_cambios_codigo.py",
    "core/IA/revertir_cambio_codigo.py",
    "core/IA/evaluar_confianza.py",
}

# Un modelo local chico no puede trabajar de forma confiable con
# archivos muy largos como contexto completo (mas probabilidad de que
# "olvide" partes o transcriba mal el fragmento a buscar).
MAX_CARACTERES_ARCHIVO = 12000

# Reintentos si el modelo no devuelve el formato esperado o el
# fragmento no coincide -- un modelo chico a veces acierta a la
# segunda sin cambiar nada mas que el prompt de sistema (temperatura
# baja igual deja algo de variabilidad).
MAX_INTENTOS_IA = 2

# Esta ruta especifica (funcion aislada) es barata por intento (poco
# contexto, num_predict chico) y ahora tiene retroalimentacion real
# del error exacto -- vale la pena darle mas margen para autocorregirse.
MAX_INTENTOS_FUNCION_AISLADA = 3

MARCA_INICIO_BUSCAR = "<<<<<<< BUSCAR"
MARCA_SEPARADOR = "======="
MARCA_FIN_REEMPLAZAR = ">>>>>>> REEMPLAZAR"

MARCA_INICIO_CONTENIDO = "<<<<<<< CONTENIDO"
MARCA_FIN_CONTENIDO = ">>>>>>> FIN"

PATRON_BLOQUE = re.compile(
    r"<{3,}\s*BUSCAR\s*\n(.*?)\n\s*={3,}\s*\n(.*?)\n\s*>{3,}\s*REEMPLAZAR",
    re.DOTALL,
)

PATRON_BLOQUE_CONTENIDO = re.compile(
    r"<{3,}\s*CONTENIDO\s*\n(.*?)\n\s*>{3,}\s*FIN",
    re.DOTALL,
)

PATRON_MENCION_FUNCION = re.compile(r"funci[oó]n\s+['\"]?([a-zA-Z_][a-zA-Z0-9_]*)")


def _extraer_funcion(contenido, nombre_funcion):
    """
    Busca la funcion `nombre_funcion` en `contenido` (via ast) y
    devuelve solo su codigo fuente exacto (con decoradores si los
    tiene), o None si no la encuentra. Reduce drasticamente el
    contexto que se le manda al modelo -- de un archivo entero a
    unas pocas lineas.
    """
    try:
        arbol = ast.parse(contenido)
    except SyntaxError:
        return None

    lineas = contenido.splitlines(keepends=True)

    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre_funcion:
            inicio = nodo.decorator_list[0].lineno if nodo.decorator_list else nodo.lineno
            fin = nodo.end_lineno
            return "".join(lineas[inicio - 1:fin])

    return None


def _ruta_absoluta(archivo: str) -> Path:
    """Normaliza y valida que la ruta quede DENTRO de la carpeta del proyecto."""
    destino = (RAIZ_APP / archivo).resolve()
    if destino != RAIZ_APP and RAIZ_APP not in destino.parents:
        raise ValueError(f"'{archivo}' queda fuera de la carpeta del proyecto.")
    return destino


def _cargar_pendientes():
    if not ARCHIVO_PENDIENTES.exists():
        return []
    try:
        return json.loads(ARCHIVO_PENDIENTES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _guardar_pendientes(props):
    ARCHIVO_PENDIENTES.write_text(
        json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _log_inmutable(evento):
    evento["timestamp"] = datetime.now().isoformat()
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _validar_sintaxis_si_python(ruta: Path, codigo: str):
    if ruta.suffix != ".py":
        return True, None
    try:
        ast.parse(codigo, filename=str(ruta))
        return True, None
    except SyntaxError as e:
        return False, str(e)


def _validar_extension(archivo_norm: str, es_archivo_nuevo: bool):
    """
    Rechaza archivos NUEVOS sin extension (el error real que causo
    que un archivo quedara guardado como 'evaluar_confianza' en vez
    de 'evaluar_confianza.py', huerfano del sistema de imports).
    """
    if not es_archivo_nuevo:
        return True, None
    sufijo = Path(archivo_norm).suffix
    if not sufijo:
        return False, (
            f"'{archivo_norm}' no tiene extensión (ej. '.py'). Un archivo "
            f"nuevo sin extensión queda huérfano del sistema de imports. "
            f"No se creó la propuesta -- especificá la extensión."
        )
    return True, None


def _crear_propuesta(archivo, buscar, reemplazar, que, por_que, como, origen):
    archivo_norm = archivo.replace("\\", "/").strip()

    if archivo_norm in ARCHIVOS_PROTEGIDOS:
        return None, f"'{archivo_norm}' es un archivo protegido; no se puede proponer un cambio ahi."

    try:
        ruta = _ruta_absoluta(archivo_norm)
    except ValueError as e:
        return None, str(e)

    es_archivo_nuevo = not ruta.exists()

    ok_ext, error_ext = _validar_extension(archivo_norm, es_archivo_nuevo)
    if not ok_ext:
        return None, error_ext

    contenido_actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""

    if buscar:
        apariciones = contenido_actual.count(buscar)
        if apariciones == 0:
            return None, "El texto a buscar no existe (exacto, carácter por carácter) en el archivo. No se creó la propuesta."
        if apariciones > 1:
            return None, f"El texto a buscar aparece {apariciones} veces; tiene que ser único. No se creó la propuesta."
        contenido_simulado = contenido_actual.replace(buscar, reemplazar, 1)
    else:
        contenido_simulado = reemplazar  # archivo nuevo, o reemplazo total

    ok, error = _validar_sintaxis_si_python(ruta, contenido_simulado)
    if not ok:
        return None, f"El cambio generado no produce código Python válido, no se creó la propuesta. Error: {error}"

    pendientes = _cargar_pendientes()
    propuesta = {
        "id": f"cod_{len(pendientes) + 1}",
        "archivo": archivo_norm,
        "buscar": buscar,
        "reemplazar": reemplazar,
        "que": que,
        "por_que": por_que,
        "como": como,
        "origen": origen,
        "tipo": "archivo_nuevo" if es_archivo_nuevo else "edicion",
        "estado": "pendiente",
        "fecha_propuesta": datetime.now().isoformat(),
    }
    pendientes.append(propuesta)
    _guardar_pendientes(pendientes)
    _log_inmutable({"tipo": "propuesta_codigo_generada", "id": propuesta["id"], "archivo": archivo_norm, "origen": origen, "tipo_propuesta": propuesta["tipo"]})
    return propuesta, None


def proponer_cambio_manual(archivo, buscar, reemplazar, que="", origen="usuario_directo"):
    """100% deterministico, no usa Ollama. Vos das el fragmento exacto
    (o dejás buscar="" para crear un archivo nuevo con `reemplazar`
    como contenido completo)."""
    return _crear_propuesta(
        archivo=archivo,
        buscar=buscar,
        reemplazar=reemplazar,
        que=que or f"Reemplazar un fragmento en {archivo}.",
        por_que="Cambio especificado directamente, sin pasar por Ollama.",
        como="Reemplazo de texto exacto (buscar -> reemplazar), una sola aparición.",
        origen=origen,
    )


def _armar_prompt(archivo_norm, contenido_relevante, instruccion, pista_definiciones="", intento_anterior=None):
    bloque_correccion = ""
    if intento_anterior:
        respuesta_previa, error_previo = intento_anterior
        bloque_correccion = f"""
Tu intento anterior fue este:
---
{respuesta_previa}
---
Y tuvo este problema EXACTO: {error_previo}
Corregí específicamente eso en tu nueva respuesta.
"""

    return f"""Copiá un fragmento EXACTO de código y mostrá su versión modificada. No sos un chatbot: no expliques nada, no agregues texto fuera del formato pedido, no uses backticks de markdown.

EJEMPLO de como se ve una respuesta correcta (con OTRO codigo, solo para que veas el formato):

<<<<<<< BUSCAR
def saludar(nombre):
    print("Hola")
=======
def saludar(nombre):
    print("Hola")
    print(f"Bienvenido, {{nombre}}")
>>>>>>> REEMPLAZAR

Ahora hacé lo mismo para este caso real:

Archivo: {archivo_norm}

Fragmento de código relevante (SOLO esto, copiá de acá, no inventes nada que no este aca):
---
{contenido_relevante}
---

Instrucción: {instruccion}
{pista_definiciones}{bloque_correccion}
Respondé usando EXACTAMENTE el mismo formato del ejemplo de arriba (los tres marcadores tal cual: {MARCA_INICIO_BUSCAR}, {MARCA_SEPARADOR}, {MARCA_FIN_REEMPLAZAR}), sin nada mas antes ni despues.

Reglas estrictas:
- El bloque BUSCAR tiene que ser una copia EXACTA y literal de un fragmento del "Fragmento de código relevante" de arriba (mismos espacios, misma indentación, mismos saltos de línea).
- El bloque REEMPLAZAR es ese mismo fragmento con el cambio pedido, conservando el resto igual.
- Elegí el fragmento BUSCAR más chico posible que alcance para hacer el cambio.
- No inventes variables que no existen -- si necesitás datos que ya existen en el archivo, fijate en la lista de nombres reales de arriba.
"""


def _armar_prompt_archivo_nuevo(archivo_norm, instruccion):
    return f'''Vas a crear el contenido completo de un archivo Python NUEVO. No sos un chatbot: no expliques nada, no agregues texto fuera del formato pedido, no uses backticks de markdown (```), nunca.

EJEMPLO de como se ve una respuesta correcta (con OTRO caso, solo para que veas el formato):

Instrucción de ejemplo: crear un archivo con una función restar(a, b)

{MARCA_INICIO_CONTENIDO}
"""
Funciones de resta simples.
"""


def restar(a, b):
    return a - b
{MARCA_FIN_CONTENIDO}

Ahora hacé lo mismo para este caso real:

Archivo a crear: {archivo_norm}

Instrucción: {instruccion}

Respondé usando EXACTAMENTE el mismo formato del ejemplo de arriba: empezá la respuesta con la línea "{MARCA_INICIO_CONTENIDO}" (tal cual, es la primera línea de tu respuesta, no la olvides), después el código completo, y terminá con la línea "{MARCA_FIN_CONTENIDO}". Nada de texto antes del primer marcador ni después del segundo. Sin backticks de markdown en ningún lado.
'''


def _extraer_bloque(texto_respuesta):
    match = PATRON_BLOQUE.search(texto_respuesta)
    if not match:
        return None, None
    return match.group(1), match.group(2)


PATRON_FALLBACK_MARKDOWN = re.compile(r"```(?:python)?\s*\n(.*?)\n```", re.DOTALL)


def _extraer_contenido_nuevo(texto_respuesta):
    match = PATRON_BLOQUE_CONTENIDO.search(texto_respuesta)
    if match:
        contenido = match.group(1)
        # Red de seguridad: si el modelo igual deslizo backticks de markdown
        # (```python ... ```) alrededor del codigo, los sacamos.
        contenido = re.sub(r"^```(?:python)?\n", "", contenido.strip())
        contenido = re.sub(r"\n```$", "", contenido)
        return contenido

    # Plan B: el modelo ignoro nuestros marcadores por completo y
    # devolvio SOLO un bloque de markdown -- lo tomamos igual, en vez
    # de fallar. Esto pasa seguido con instrucciones simples, donde
    # el modelo "cae" a su formato por defecto.
    match_markdown = PATRON_FALLBACK_MARKDOWN.search(texto_respuesta)
    if match_markdown:
        return match_markdown.group(1)

    # Plan C: modelos especializados en codigo (ej. qwen2.5-coder)
    # suelen devolver el codigo "pelado", sin marcadores NI backticks,
    # cuando se les pide codigo de forma directa. Si la respuesta
    # entera, limpia de espacios, ya es Python valido por si sola y
    # arranca como una definicion de funcion, la aceptamos tal cual.
    candidato = texto_respuesta.strip()
    if candidato.startswith("def ") or candidato.startswith("async def "):
        try:
            ast.parse(candidato)
            return candidato
        except SyntaxError:
            pass

    return None


def _proponer_archivo_nuevo_ia(archivo_norm, instruccion, origen):
    from core.IA.ollamaIA import generar_codigo

    ok_ext, error_ext = _validar_extension(archivo_norm, es_archivo_nuevo=True)
    if not ok_ext:
        return None, error_ext

    prompt = _armar_prompt_archivo_nuevo(archivo_norm, instruccion)

    ultimo_error = "No se obtuvo respuesta del modelo."

    for intento in range(1, MAX_INTENTOS_IA + 1):
        respuesta = generar_codigo(prompt, num_predict=800, temperature=0.2)
        contenido = _extraer_contenido_nuevo(respuesta)

        if contenido is None:
            ultimo_error = (
                "Ollama no devolvió el formato esperado (CONTENIDO/FIN). "
                f"Intento {intento}/{MAX_INTENTOS_IA}."
            )
            continue

        return _crear_propuesta(
            archivo=archivo_norm,
            buscar="",
            reemplazar=contenido.strip("\n") + "\n",
            que=f"Crear el archivo {archivo_norm} según: {instruccion}",
            por_que=f"Generado por Ollama (arche-lora) a partir de la instrucción: {instruccion}",
            como="Archivo nuevo, contenido completo redactado por Ollama.",
            origen=origen,
        )

    return None, (
        ultimo_error + " Probá con una instrucción más simple/corta, "
        "o usá proponer_cambio_manual con el contenido vos mismo."
    )


def _nombres_globales_reales(contenido_archivo):
    """
    Todos los nombres DEFINIDOS a nivel de módulo en el archivo real:
    imports, asignaciones globales, funciones, clases. Estos son los
    nombres que una función nueva SÍ podría usar de verdad (además de
    los builtins de Python).
    """
    return set(_definiciones_reales(contenido_archivo).keys())


def _ejemplos_de_uso_reales(contenido_archivo, nombres):
    """
    Para cada nombre en `nombres`, busca la PRIMERA linea del archivo
    (fuera de su propia definicion) donde se usa de verdad dentro de
    una funcion -- esto muestra el patron real de uso (ej. si
    'archivo_recordatorios' siempre se usa con open(...) en vez de
    os.listdir(...), eso deja clarisimo que es un archivo unico, no
    una carpeta con muchos archivos).

    Es MAS contexto que solo la definicion, a proposito: el modelo
    solo tiene que LEER esto, no reproducirlo exacto, asi que no
    reintroduce el riesgo de "copiar mal" que tuvimos con el enfoque
    de reproducir funciones enteras.

    Devuelve {nombre: linea_de_ejemplo_o_None}.
    """
    try:
        arbol = ast.parse(contenido_archivo)
    except SyntaxError:
        return {}

    lineas_archivo = contenido_archivo.splitlines()
    ejemplos = {}

    for nodo_top in arbol.body:
        if not isinstance(nodo_top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for nodo in ast.walk(nodo_top):
            if isinstance(nodo, ast.Name) and isinstance(nodo.ctx, ast.Load) and nodo.id in nombres:
                if nodo.id not in ejemplos:
                    ejemplos[nodo.id] = lineas_archivo[nodo.lineno - 1].strip()

    return ejemplos


def _definiciones_reales(contenido_archivo):
    """
    Igual que _nombres_globales_reales, pero en vez de solo el nombre,
    devuelve un dict {nombre: {"linea": texto de la definicion exacta,
    "es_string": True/False}}.

    El "linea" le da al modelo contexto semantico real (ej. ver
    "carpeta_notas = os.path.join(DATABASE, 'Notas')" deja claro que
    es una RUTA, no una lista) sin mandarle el archivo entero.

    "es_string" marca variables que claramente son texto (asignadas
    con os.path.join, f-strings, o literales de texto) -- se usa para
    detectar el error especifico de aplicar len() como si contara
    elementos de una lista cuando en realidad cuenta caracteres.
    """
    try:
        arbol = ast.parse(contenido_archivo)
    except SyntaxError:
        return {}

    lineas_archivo = contenido_archivo.splitlines()
    definiciones = {}

    for nodo in arbol.body:
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                nombre = (alias.asname or alias.name).split(".")[0]
                definiciones[nombre] = {"linea": lineas_archivo[nodo.lineno - 1].strip(), "es_string": False}
        elif isinstance(nodo, ast.ImportFrom):
            for alias in nodo.names:
                if alias.name != "*":
                    nombre = alias.asname or alias.name
                    definiciones[nombre] = {"linea": lineas_archivo[nodo.lineno - 1].strip(), "es_string": False}
        elif isinstance(nodo, ast.Assign):
            es_string = isinstance(nodo.value, (ast.JoinedStr,)) or (
                isinstance(nodo.value, ast.Call)
                and isinstance(nodo.value.func, ast.Attribute)
                and nodo.value.func.attr == "join"
            ) or isinstance(nodo.value, ast.Constant) and isinstance(getattr(nodo.value, "value", None), str)
            for objetivo in nodo.targets:
                if isinstance(objetivo, ast.Name):
                    definiciones[objetivo.id] = {
                        "linea": lineas_archivo[nodo.lineno - 1].strip(),
                        "es_string": es_string,
                    }
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definiciones[nodo.name] = {"linea": lineas_archivo[nodo.lineno - 1].strip(), "es_string": False}

    return definiciones


def _nombres_de_target(nodo_target):
    """Un 'target' de asignación puede ser un Name simple (x = ...) o
    una tupla/lista para desempaquetado (a, b = ... / for a, b in ...).
    Devuelve todos los nombres involucrados, sea cual sea la forma."""
    nombres = []
    if isinstance(nodo_target, ast.Name):
        nombres.append(nodo_target.id)
    elif isinstance(nodo_target, (ast.Tuple, ast.List)):
        for elemento in nodo_target.elts:
            nombres.extend(_nombres_de_target(elemento))
    return nombres


def _nombres_externos_de_funcion(codigo_funcion):
    """
    Nombres que la función USA (ast.Name en contexto Load) pero que
    NO son: parámetros propios, variables asignadas dentro de la
    función, ni builtins de Python. Estos son los candidatos a ser
    "alucinados" -- cosas que el modelo asumió que existían sin
    verificarlo.
    """
    try:
        arbol = ast.parse(codigo_funcion)
    except SyntaxError:
        return set()

    if not arbol.body or not isinstance(arbol.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()

    funcion = arbol.body[0]

    definidos_localmente = set(_NOMBRES_BUILTIN)
    for arg in funcion.args.args + funcion.args.kwonlyargs:
        definidos_localmente.add(arg.arg)
    if funcion.args.vararg:
        definidos_localmente.add(funcion.args.vararg.arg)
    if funcion.args.kwarg:
        definidos_localmente.add(funcion.args.kwarg.arg)

    for nodo in ast.walk(funcion):
        if isinstance(nodo, ast.Assign):
            for objetivo in nodo.targets:
                definidos_localmente.update(_nombres_de_target(objetivo))
        elif isinstance(nodo, (ast.For, ast.AsyncFor)):
            definidos_localmente.update(_nombres_de_target(nodo.target))
        elif isinstance(nodo, ast.comprehension):
            # Variables de comprensiones ([x for x in ...], {x for x in ...},
            # generadores) -- tienen su propio alcance, NO son "externas".
            # Este es el bug que causaba falsos positivos con listas por
            # comprension (ej. [nombre for nombre in os.listdir(...)]).
            definidos_localmente.update(_nombres_de_target(nodo.target))
        elif isinstance(nodo, ast.withitem) and isinstance(nodo.optional_vars, ast.Name):
            definidos_localmente.add(nodo.optional_vars.id)
        elif isinstance(nodo, ast.ExceptHandler) and nodo.name:
            definidos_localmente.add(nodo.name)
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo is not funcion:
            definidos_localmente.add(nodo.name)

    usados = {
        nodo.id for nodo in ast.walk(funcion)
        if isinstance(nodo, ast.Name) and isinstance(nodo.ctx, ast.Load)
    }

    return usados - definidos_localmente


def _detectar_nombre_duplicado(codigo_funcion, definiciones_reales):
    """
    Si la función que generó el modelo tiene el mismo nombre que algo
    que YA EXISTE en el archivo (otra función, una variable, un
    import), eso crea una definición duplicada -- Python no tira
    error, pero la segunda definición "tapa" silenciosamente a la
    primera, lo cual es confuso y probablemente no es lo que querías.

    Devuelve el nombre duplicado, o None si no hay colisión.
    """
    try:
        arbol = ast.parse(codigo_funcion)
    except SyntaxError:
        return None

    if not arbol.body or not isinstance(arbol.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    nombre_nuevo = arbol.body[0].name
    if nombre_nuevo in definiciones_reales:
        return nombre_nuevo

    return None


def _validar_sin_alucinaciones(codigo_funcion, contenido_archivo):
    """
    Devuelve (ok: bool, nombres_alucinados: set). ok=False si la
    función usa algún nombre que no existe ni en el archivo real ni
    en Python mismo -- señal fuerte de que el modelo inventó una
    variable/función que no existe (ej. 'notas' cuando el archivo
    real usa 'carpeta_notas').
    """
    nombres_reales = _nombres_globales_reales(contenido_archivo)
    nombres_usados = _nombres_externos_de_funcion(codigo_funcion)
    alucinados = nombres_usados - nombres_reales
    return (len(alucinados) == 0, alucinados)


def _detectar_len_sobre_string(codigo_funcion, definiciones_reales):
    """
    Detecta el patron especifico que causo el bug real: len(X) donde
    X es una variable que sabemos (por su definicion real) que es un
    string/ruta, no una lista -- len() sobre un string cuenta
    caracteres, no elementos, y es casi siempre un error cuando la
    instruccion original pedia "contar" algo.

    Devuelve el nombre de la variable mal usada, o None si no detecta
    el patron.
    """
    try:
        arbol = ast.parse(codigo_funcion)
    except SyntaxError:
        return None

    for nodo in ast.walk(arbol):
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "len"
            and len(nodo.args) == 1
            and isinstance(nodo.args[0], ast.Name)
        ):
            nombre_arg = nodo.args[0].id
            info = definiciones_reales.get(nombre_arg)
            if info and info["es_string"]:
                return nombre_arg

    return None


def _armar_prompt_funcion_nueva_aislada(instruccion, pista_nombres="", intento_anterior=None):
    bloque_correccion = ""
    if intento_anterior:
        respuesta_previa, error_previo = intento_anterior
        bloque_correccion = f"""
Tu intento anterior fue este:
---
{respuesta_previa}
---
Y tuvo este problema EXACTO: {error_previo}
Corregí específicamente eso en tu nueva respuesta.
"""

    return f'''Escribí el código de UNA función Python nueva. No sos un chatbot: no expliques nada, no agregues texto fuera del código, no uses backticks de markdown (```), nunca.

EJEMPLO de como se ve una respuesta correcta (con OTRO caso, solo para que veas el formato):

Instrucción de ejemplo: agregá una función que sume dos números

{MARCA_INICIO_CONTENIDO}
def sumar(a, b):
    return a + b
{MARCA_FIN_CONTENIDO}

Ahora hacé lo mismo para este caso real:

Instrucción: {instruccion}
{pista_nombres}{bloque_correccion}
Respondé usando EXACTAMENTE el mismo formato del ejemplo de arriba: empezá con la línea "{MARCA_INICIO_CONTENIDO}", después el código de la función, y terminá con "{MARCA_FIN_CONTENIDO}". Nada de texto antes ni después. Sin backticks de markdown en ningún lado. No inventes variables que no existen -- si la función necesita datos, recibilos como parámetros O usá los nombres reales listados arriba si los hay.

Reglas estrictas:
- Solo el código de la función nueva, nada más.
- Elegí un nombre de función corto y descriptivo, snake_case, en español.
- Código Python simple, sin dependencias externas salvo que la instrucción las pida.
'''


def _formatear_pista_definiciones(contenido_archivo, definiciones_reales, nombres_a_incluir=None):
    """Arma el texto de pista con la DEFINICIÓN real de cada nombre
    Y un ejemplo de cómo se USA de verdad en otra parte del archivo
    (cuando existe) -- esto es lo que distingue, por ejemplo, una
    variable que es una carpeta (se usa con os.listdir) de una que es
    un archivo único (se usa con open())."""
    nombres = nombres_a_incluir if nombres_a_incluir is not None else definiciones_reales.keys()
    nombres_validos = [n for n in sorted(nombres) if n in definiciones_reales]
    if not nombres_validos:
        return ""

    ejemplos = _ejemplos_de_uso_reales(contenido_archivo, set(nombres_validos))

    lineas = []
    for nombre in nombres_validos:
        definicion = definiciones_reales[nombre]["linea"]
        ejemplo = ejemplos.get(nombre)
        if ejemplo:
            lineas.append(f"  {nombre}\n    definido como: {definicion}\n    usado en el resto del archivo así: {ejemplo}")
        else:
            lineas.append(f"  {nombre}\n    definido como: {definicion}")

    return (
        "\nNombres reales que ya existen en el archivo, con su definición y "
        "un ejemplo real de cómo se usan (fijate bien el patrón de uso antes "
        "de escribir tu función, sobre todo si es carpeta vs archivo único, "
        "lista vs texto):\n" + "\n".join(lineas) + "\n"
    )


def _requiere_argumentos(codigo_funcion):
    """True si la función necesita parámetros obligatorios para
    llamarse (sin valores por defecto, sin *args/**kwargs)."""
    try:
        arbol = ast.parse(codigo_funcion)
    except SyntaxError:
        return True
    if not arbol.body or not isinstance(arbol.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return True
    args = arbol.body[0].args
    obligatorios = len(args.args) - len(args.defaults)
    return obligatorios > 0


def _nombre_de_funcion(codigo_funcion):
    try:
        arbol = ast.parse(codigo_funcion)
        return arbol.body[0].name
    except (SyntaxError, IndexError, AttributeError):
        return None


def _ejecutar_prueba_real(archivo_norm, contenido_simulado, nombre_funcion):
    """
    Ejecuta la función DE VERDAD (no solo import) en un módulo
    temporal, dentro de la carpeta real del proyecto (para que los
    imports relativos funcionen), y devuelve (ok, resultado_o_error).

    Esto atrapa cosas que ni la sintaxis ni el chequeo de nombres
    puede: errores de tipo en tiempo de ejecución (ej. sumar un texto
    con un numero), excepciones reales al tocar archivos, etc. Es la
    verificacion mas fuerte que se puede hacer sin pedirte que lo
    corras vos mismo.

    El archivo temporal se borra siempre, haya salido bien o mal.
    """
    directorio = _ruta_absoluta(archivo_norm).parent
    nombre_temporal = f"_arche_prueba_tmp_{nombre_funcion}"
    ruta_temporal = directorio / f"{nombre_temporal}.py"

    modulo_relativo = archivo_norm.rsplit("/", 1)[0].replace("/", ".") if "/" in archivo_norm else ""
    modulo_completo = f"{modulo_relativo}.{nombre_temporal}" if modulo_relativo else nombre_temporal

    try:
        ruta_temporal.write_text(contenido_simulado, encoding="utf-8")

        codigo_prueba = (
            f"import {modulo_completo} as _m\n"
            f"resultado = _m.{nombre_funcion}()\n"
            f"print('RESULTADO_OK:', repr(resultado))\n"
        )

        resultado = subprocess.run(
            [sys.executable, "-c", codigo_prueba],
            capture_output=True, text=True, cwd=str(RAIZ_APP),
            timeout=15, encoding="utf-8", errors="replace",
        )

        if resultado.returncode != 0:
            return False, resultado.stderr.strip()[-500:]

        return True, resultado.stdout.strip()

    except subprocess.TimeoutExpired:
        return False, "La ejecución de prueba se colgó más de 15 segundos."
    finally:
        if ruta_temporal.exists():
            ruta_temporal.unlink()
        # Limpiar el .pyc que Python pudo haber generado del temporal
        pycache = directorio / "__pycache__"
        if pycache.exists():
            for pyc in pycache.glob(f"{nombre_temporal}*.pyc"):
                pyc.unlink()


def proponer_agregar_funcion_cerca(archivo_norm, codigo_funcion_ancla, instruccion, origen):
    """
    Genera una propuesta que agrega una funcion NUEVA justo despues de
    una funcion existente, SIN pedirle al modelo que reproduzca esa
    funcion existente -- eso es lo que fallaba en la practica (el
    modelo a veces le cambia el nombre o altera la funcion ancla al
    intentar copiarla junto con la nueva).

    En cambio: el "buscar" es el texto EXACTO que ya se extrajo del
    archivo real via ast (codigo_funcion_ancla, garantizado presente,
    cero riesgo de no-match), y el modelo SOLO tiene que generar la
    funcion nueva de forma aislada -- una tarea mucho mas simple y
    confiable que "reproduci esto Y agregá aquello".

    Ademas, valida automaticamente (sin IA, con ast) que la funcion
    generada no use nombres "alucinados" -- variables o funciones que
    no existen ni en el archivo real ni en Python. Si los detecta, en
    el siguiente intento le pasa al modelo la lista de nombres REALES
    disponibles como pista puntual (no el codigo entero, solo los
    nombres -- mucho mas seguro que darle contexto completo). Si
    despues de todos los intentos sigue alucinando, NO genera la
    propuesta -- prefiere fallar con un mensaje honesto antes que
    dejarte algo roto para que lo detectes vos.
    """
    from core.IA.ollamaIA import generar_codigo

    try:
        ruta = _ruta_absoluta(archivo_norm)
        contenido_archivo = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    except ValueError as e:
        return None, str(e)

    definiciones_reales = _definiciones_reales(contenido_archivo)
    # Desde el PRIMER intento ya le damos la definicion real de los
    # nombres del archivo (no solo el nombre suelto) -- esto es lo que
    # le permite distinguir "carpeta_notas es una ruta" de "es una lista".
    pista_nombres = _formatear_pista_definiciones(contenido_archivo, definiciones_reales)
    intento_anterior = None  # (respuesta_cruda, error_especifico) del intento previo
    ultimo_error = "No se obtuvo respuesta del modelo."

    for intento in range(1, MAX_INTENTOS_FUNCION_AISLADA + 1):
        prompt = _armar_prompt_funcion_nueva_aislada(instruccion, pista_nombres, intento_anterior)
        respuesta = generar_codigo(prompt, num_predict=400, temperature=0.2)
        codigo_nuevo = _extraer_contenido_nuevo(respuesta)

        if codigo_nuevo is None:
            ultimo_error = f"Ollama no devolvió el formato esperado (faltan los marcadores {MARCA_INICIO_CONTENIDO}/{MARCA_FIN_CONTENIDO}). Intento {intento}/{MAX_INTENTOS_FUNCION_AISLADA}."
            intento_anterior = (respuesta, f"No incluiste los marcadores {MARCA_INICIO_CONTENIDO} y {MARCA_FIN_CONTENIDO} tal cual se pidió.")
            continue

        try:
            ast.parse(codigo_nuevo)
        except SyntaxError as e:
            error_especifico = f"Error de sintaxis en la línea {e.lineno}: {e.msg}"
            ultimo_error = f"El código de la función nueva no es válido: {error_especifico}. Intento {intento}/{MAX_INTENTOS_FUNCION_AISLADA}."
            intento_anterior = (respuesta, error_especifico)
            continue

        ok_semantico, alucinados = _validar_sin_alucinaciones(codigo_nuevo, contenido_archivo)
        if not ok_semantico:
            error_especifico = f"Usaste estos nombres que no existen: {', '.join(sorted(alucinados))}."
            ultimo_error = (
                f"La función generada usa nombres que no existen en el archivo "
                f"ni en Python: {', '.join(sorted(alucinados))}. Intento {intento}/{MAX_INTENTOS_FUNCION_AISLADA}."
            )
            intento_anterior = (respuesta, error_especifico)
            continue

        nombre_duplicado = _detectar_nombre_duplicado(codigo_nuevo, definiciones_reales)
        if nombre_duplicado:
            error_especifico = (
                f"Ya existe algo llamado '{nombre_duplicado}' en el archivo (definido como: "
                f"{definiciones_reales[nombre_duplicado]['linea']}). Elegí un nombre DISTINTO "
                f"para tu función nueva, que no choque con nada que ya exista."
            )
            ultimo_error = f"{error_especifico} Intento {intento}/{MAX_INTENTOS_FUNCION_AISLADA}."
            intento_anterior = (respuesta, error_especifico)
            continue

        variable_mal_usada = _detectar_len_sobre_string(codigo_nuevo, definiciones_reales)
        if variable_mal_usada:
            definicion = definiciones_reales[variable_mal_usada]["linea"]
            error_especifico = (
                f"Usaste len({variable_mal_usada}) pero '{variable_mal_usada}' es una ruta/texto "
                f"(definido como: {definicion}), no una lista -- len() sobre eso cuenta caracteres, "
                f"no elementos. Si necesitás contar archivos en esa ruta, usá "
                f"len(os.listdir({variable_mal_usada})) en su lugar."
            )
            ultimo_error = f"{error_especifico} Intento {intento}/{MAX_INTENTOS_FUNCION_AISLADA}."
            intento_anterior = (respuesta, error_especifico)
            continue

        reemplazo = codigo_funcion_ancla.rstrip("\n") + "\n\n\n" + codigo_nuevo.strip("\n") + "\n"

        nombre_funcion_nueva = _nombre_de_funcion(codigo_nuevo)
        resultado_prueba = None

        if nombre_funcion_nueva and not _requiere_argumentos(codigo_nuevo):
            # Solo podemos ejecutar de verdad funciones sin argumentos
            # obligatorios (no sabemos qué valores inventar para el resto).
            # Esto es la verificacion MAS fuerte posible: correrla de
            # verdad, no solo mirarla.
            contenido_simulado = contenido_archivo.replace(codigo_funcion_ancla, reemplazo, 1)
            ok_ejecucion, salida = _ejecutar_prueba_real(archivo_norm, contenido_simulado, nombre_funcion_nueva)

            if not ok_ejecucion:
                error_especifico = f"Al EJECUTAR la función de verdad, falló con este error real: {salida}"
                ultimo_error = f"{error_especifico} Intento {intento}/{MAX_INTENTOS_FUNCION_AISLADA}."
                intento_anterior = (respuesta, error_especifico)
                continue

            resultado_prueba = salida  # ej. "RESULTADO_OK: 3"

        por_que = "Generado por Ollama (arche-lora), como función aislada, verificada automáticamente contra nombres reales del archivo (sin variables inventadas)."
        if resultado_prueba:
            por_que += f" Además, se EJECUTÓ de verdad antes de proponerla, y esto fue lo que devolvió: {resultado_prueba}"

        return _crear_propuesta(
            archivo=archivo_norm,
            buscar=codigo_funcion_ancla,
            reemplazar=reemplazo,
            que=f"Agregar una función nueva en {archivo_norm} según: {instruccion}",
            por_que=por_que,
            como="Se agrega la función nueva después de una función existente verificada, sin modificar esa función existente.",
            origen=origen,
        )

    return None, ultimo_error + " Probá con una instrucción más simple, o usá proponer_cambio_manual."


def proponer_cambio_ia(archivo, instruccion, origen="usuario_directo"):
    """
    Le pide a Ollama que redacte un cambio para `archivo` según
    `instruccion`. Si el archivo YA EXISTE, genera un buscar/reemplazar
    acotado (formato de delimitadores, sin JSON). Si el archivo NO
    existe, genera el contenido completo de un archivo nuevo. Nunca
    reescribe un archivo existente entero. Reintenta hasta
    MAX_INTENTOS_IA veces si el formato o el fragmento no son validos.

    origen: "usuario_directo" (pedido en el chat, vía "escribe en ...")
    o "autorevision" (Arché lo generó solo). Ver docstring de
    proponer_cambio_manual.
    """
    archivo_norm = archivo.replace("\\", "/").strip()
    if archivo_norm in ARCHIVOS_PROTEGIDOS:
        return None, f"'{archivo_norm}' es un archivo protegido; no se puede proponer un cambio ahi."

    try:
        ruta = _ruta_absoluta(archivo_norm)
    except ValueError as e:
        return None, str(e)

    if not ruta.exists():
        return _proponer_archivo_nuevo_ia(archivo_norm, instruccion, origen)

    from core.IA.ollamaIA import generar_codigo

    contenido_actual = ruta.read_text(encoding="utf-8")
    if len(contenido_actual) > MAX_CARACTERES_ARCHIVO:
        return None, (
            f"El archivo tiene {len(contenido_actual)} caracteres, más del límite "
            f"({MAX_CARACTERES_ARCHIVO}) para pedirle un cambio a un modelo local chico "
            f"de forma confiable. Usá proponer_cambio_manual con un buscar/reemplazar "
            f"acotado vos mismo, o pedí el cambio sobre una función más puntual."
        )

    # Si la instruccion menciona una funcion puntual, aislarla via ast
    # reduce muchisimo el contexto que ve el modelo -- mejora notable
    # en modelos chicos, que se "pierden" con archivos completos.
    match_funcion = PATRON_MENCION_FUNCION.search(instruccion)
    contenido_para_prompt = contenido_actual
    if match_funcion:
        fragmento_funcion = _extraer_funcion(contenido_actual, match_funcion.group(1))
        if fragmento_funcion:
            contenido_para_prompt = fragmento_funcion

    definiciones_reales = _definiciones_reales(contenido_actual)
    pista_definiciones = _formatear_pista_definiciones(contenido_actual, definiciones_reales)

    intento_anterior = None  # (respuesta_cruda, error_especifico)
    ultimo_error = "No se obtuvo respuesta del modelo."

    for intento in range(1, MAX_INTENTOS_IA + 1):
        prompt = _armar_prompt(archivo_norm, contenido_para_prompt, instruccion, pista_definiciones, intento_anterior)
        respuesta = generar_codigo(prompt, num_predict=600, temperature=0.1)

        buscar, reemplazar = _extraer_bloque(respuesta)

        if buscar is None:
            error_especifico = f"No incluiste los marcadores {MARCA_INICIO_BUSCAR}/{MARCA_SEPARADOR}/{MARCA_FIN_REEMPLAZAR} tal cual se pidió."
            ultimo_error = f"Ollama no devolvió el formato esperado (BUSCAR/REEMPLAZAR). Intento {intento}/{MAX_INTENTOS_IA}."
            intento_anterior = (respuesta, error_especifico)
            continue

        buscar_candidatos = [buscar, buscar.strip("\n")]

        encontrado = None
        for candidato in buscar_candidatos:
            if candidato and candidato in contenido_actual:
                encontrado = candidato
                break

        if encontrado is None:
            error_especifico = "El texto que pusiste en BUSCAR no coincide exacto con el archivo real -- tiene que ser una copia literal, carácter por carácter."
            ultimo_error = (
                "El fragmento que propuso Ollama no coincide exactamente con el "
                "archivo real (pasa seguido con modelos chicos ante instrucciones "
                f"amplias). Intento {intento}/{MAX_INTENTOS_IA}."
            )
            intento_anterior = (respuesta, error_especifico)
            continue

        reemplazar_final = reemplazar.strip("\n") if encontrado == buscar.strip("\n") else reemplazar

        # Misma bateria de validaciones que ya probamos con funciones
        # nuevas: sin nombres inventados, sin confundir string/lista.
        ok_semantico, alucinados = _validar_sin_alucinaciones(reemplazar_final, contenido_actual)
        if not ok_semantico:
            error_especifico = f"Usaste estos nombres que no existen: {', '.join(sorted(alucinados))}."
            ultimo_error = f"{error_especifico} Intento {intento}/{MAX_INTENTOS_IA}."
            intento_anterior = (respuesta, error_especifico)
            continue

        variable_mal_usada = _detectar_len_sobre_string(reemplazar_final, definiciones_reales)
        if variable_mal_usada:
            definicion = definiciones_reales[variable_mal_usada]["linea"]
            error_especifico = (
                f"Usaste len({variable_mal_usada}) pero '{variable_mal_usada}' es una ruta/texto "
                f"(definido como: {definicion}), no una lista. Si necesitás contar elementos, "
                f"usá algo como len(os.listdir({variable_mal_usada}))."
            )
            ultimo_error = f"{error_especifico} Intento {intento}/{MAX_INTENTOS_IA}."
            intento_anterior = (respuesta, error_especifico)
            continue

        # Si el resultado es una funcion completa sin argumentos obligatorios,
        # la ejecutamos de verdad antes de proponerla -- la verificacion mas
        # fuerte posible, atrapa errores de tipo en tiempo de ejecucion.
        nombre_funcion_editada = _nombre_de_funcion(reemplazar_final)
        resultado_prueba = None
        if nombre_funcion_editada and not _requiere_argumentos(reemplazar_final):
            contenido_simulado = contenido_actual.replace(encontrado, reemplazar_final, 1)
            ok_ejecucion, salida = _ejecutar_prueba_real(archivo_norm, contenido_simulado, nombre_funcion_editada)
            if not ok_ejecucion:
                error_especifico = f"Al EJECUTAR la función corregida de verdad, falló con este error real: {salida}"
                ultimo_error = f"{error_especifico} Intento {intento}/{MAX_INTENTOS_IA}."
                intento_anterior = (respuesta, error_especifico)
                continue
            resultado_prueba = salida

        por_que = f"Generado por Ollama a partir de: {instruccion}. Verificado sin nombres inventados ni confusión de tipos."
        if resultado_prueba:
            por_que += f" Se ejecutó de verdad antes de proponerlo, y devolvió: {resultado_prueba}"

        return _crear_propuesta(
            archivo=archivo_norm,
            buscar=encontrado,
            reemplazar=reemplazar_final,
            que=f"Modificar un fragmento de {archivo_norm} según: {instruccion}",
            por_que=por_que,
            como="Reemplazo de texto exacto (buscar -> reemplazar), una sola aparición, redactado por Ollama.",
            origen=origen,
        )

    return None, (
        ultimo_error + " Probá con una instrucción más puntual (una función "
        "específica, un cambio de 1-2 líneas) o usá proponer_cambio_manual."
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Uso: python core/IA/proponer_cambio_codigo.py <archivo> <instrucción>")
        sys.exit(1)

    propuesta, error = proponer_cambio_ia(sys.argv[1], " ".join(sys.argv[2:]))
    if error:
        print(f"Error: {error}")
    else:
        print(f"Propuesta {propuesta['id']} generada para {propuesta['archivo']}.")
        print("Corré 'python core/IA/revisar_cambios_codigo.py' para verla y aprobarla.")