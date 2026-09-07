"""
proponer_cambio_codigo.py
--------------------------
Ubicacion: Arche/core/IA/proponer_cambio_codigo.py

Genera propuestas de cambio para CUALQUIER archivo del proyecto (a
diferencia de propuestas.py, que solo puede tocar preguntas_frecuentes.py).

Cada propuesta es un cambio tipo "buscar y reemplazar": un fragmento
EXACTO de texto que debe existir una sola vez en el archivo, y el texto
que lo reemplaza. Deliberadamente NUNCA se le pide al modelo que
reescriba el archivo entero -- con un modelo local chico (arche-lora)
eso es indefendible: puede truncar, resumir de mas o alucinar partes
que no tocaste. Un buscar/reemplazar acotado es mucho mas verificable
(el diff real muestra exactamente que cambia) y mucho mas confiable
para el modelo.

Dos formas de generar una propuesta:
  1. proponer_cambio_manual(...) -- vos das buscar/reemplazar directo,
     sin usar el modelo. 100% deterministico.
  2. proponer_cambio_ia(...) -- le pasas una instruccion en lenguaje
     natural y el archivo destino; Ollama redacta buscar/reemplazar.

CORREGIDO (v2): proponer_cambio_ia ya NO le pide al modelo un JSON con
el codigo escapado adentro -- eso obliga a un modelo chico a escapar
comillas/saltos de linea correctamente, que es justo donde mas falla
(devuelve JSON invalido, o corrompe el fragmento). Ahora se usa un
formato de delimitadores de texto plano (el mismo enfoque que usan
herramientas como Aider para edicion de codigo con LLMs chicos):
el modelo copia el codigo tal cual, sin escapar nada. Ademas se llama
a conversar() con temperature baja (0.1): copiar texto exacto no debe
depender de la "creatividad" del modelo.

NINGUNA de las dos funciones toca el archivo real. Eso solo pasa en
revisar_cambios_codigo.py, con tu aprobacion explicita cada vez.

LIMITE DURO: no se puede proponer un cambio sobre los archivos que
controlan este mismo sistema (ver ARCHIVOS_PROTEGIDOS). Si necesitas
tocar esos, hacelo vos a mano -- es la unica forma de garantizar que
Arche no pueda aflojar sus propias restricciones desde adentro.
"""

import ast
import json
import re
from datetime import datetime
from pathlib import Path

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

MARCA_INICIO_BUSCAR = "<<<<<<< BUSCAR"
MARCA_SEPARADOR = "======="
MARCA_FIN_REEMPLAZAR = ">>>>>>> REEMPLAZAR"

PATRON_BLOQUE = re.compile(
    re.escape(MARCA_INICIO_BUSCAR) + r"\n(.*?)\n" + re.escape(MARCA_SEPARADOR) +
    r"\n(.*?)\n" + re.escape(MARCA_FIN_REEMPLAZAR),
    re.DOTALL,
)

PATRON_MENCION_FUNCION = re.compile(r"funci[oó]n\s+([a-zA-Z_][a-zA-Z0-9_]*)")


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


def _crear_propuesta(archivo, buscar, reemplazar, que, por_que, como, origen):
    archivo_norm = archivo.replace("\\", "/").strip()

    if archivo_norm in ARCHIVOS_PROTEGIDOS:
        return None, f"'{archivo_norm}' es un archivo protegido; no se puede proponer un cambio ahi."

    try:
        ruta = _ruta_absoluta(archivo_norm)
    except ValueError as e:
        return None, str(e)

    contenido_actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""

    if buscar:
        apariciones = contenido_actual.count(buscar)
        if apariciones == 0:
            return None, "El texto a buscar no existe (exacto, carácter por carácter) en el archivo. No se creó la propuesta."
        if apariciones > 1:
            return None, f"El texto a buscar aparece {apariciones} veces; tiene que ser único. No se creó la propuesta."
        contenido_simulado = contenido_actual.replace(buscar, reemplazar, 1)
    else:
        contenido_simulado = reemplazar  # archivo nuevo

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
        "origen": origen,  # "manual" o "ia"
        "estado": "pendiente",
        "fecha_propuesta": datetime.now().isoformat(),
    }
    pendientes.append(propuesta)
    _guardar_pendientes(pendientes)
    _log_inmutable({"tipo": "propuesta_codigo_generada", "id": propuesta["id"], "archivo": archivo_norm, "origen": origen})
    return propuesta, None


def proponer_cambio_manual(archivo, buscar, reemplazar, que=""):
    """100% deterministico, no usa Ollama. Vos das el fragmento exacto."""
    return _crear_propuesta(
        archivo=archivo,
        buscar=buscar,
        reemplazar=reemplazar,
        que=que or f"Reemplazar un fragmento en {archivo}.",
        por_que="Cambio especificado directamente, sin pasar por Ollama.",
        como="Reemplazo de texto exacto (buscar -> reemplazar), una sola aparición.",
        origen="manual",
    )


def _armar_prompt(archivo_norm, contenido_relevante, instruccion):
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

Respondé usando EXACTAMENTE el mismo formato del ejemplo de arriba (los tres marcadores tal cual: {MARCA_INICIO_BUSCAR}, {MARCA_SEPARADOR}, {MARCA_FIN_REEMPLAZAR}), sin nada mas antes ni despues.

Reglas estrictas:
- El bloque BUSCAR tiene que ser una copia EXACTA y literal de un fragmento del "Fragmento de código relevante" de arriba (mismos espacios, misma indentación, mismos saltos de línea).
- El bloque REEMPLAZAR es ese mismo fragmento con el cambio pedido, conservando el resto igual.
- Elegí el fragmento BUSCAR más chico posible que alcance para hacer el cambio.
"""


def _armar_prompt_archivo_completo(archivo_norm, contenido_actual, instruccion):
    """Fallback cuando no se pudo aislar una funcion puntual: manda el
    archivo completo (mismo riesgo de antes, pero es mejor que nada
    si la instruccion no menciona una funcion reconocible)."""
    return _armar_prompt(archivo_norm, contenido_actual, instruccion)


def _extraer_bloque(texto_respuesta):
    match = PATRON_BLOQUE.search(texto_respuesta)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def proponer_cambio_ia(archivo, instruccion):
    """
    Le pide a Ollama que redacte un cambio tipo buscar/reemplazar para
    lograr `instruccion` sobre `archivo`, usando un formato de
    delimitadores de texto plano (no JSON) para que el modelo no tenga
    que escapar codigo -- solo copiarlo tal cual. Nunca reescribe el
    archivo entero. Reintenta hasta MAX_INTENTOS_IA veces si el
    formato o el fragmento no son validos.
    """
    from core.IA.ollamaIA import conversar

    archivo_norm = archivo.replace("\\", "/").strip()
    if archivo_norm in ARCHIVOS_PROTEGIDOS:
        return None, f"'{archivo_norm}' es un archivo protegido; no se puede proponer un cambio ahi."

    try:
        ruta = _ruta_absoluta(archivo_norm)
    except ValueError as e:
        return None, str(e)

    if not ruta.exists():
        return None, f"'{archivo_norm}' no existe. Para crear un archivo nuevo usá proponer_cambio_manual con buscar=''."

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

    prompt = _armar_prompt(archivo_norm, contenido_para_prompt, instruccion)

    ultimo_error = "No se obtuvo respuesta del modelo."

    for intento in range(1, MAX_INTENTOS_IA + 1):
        respuesta = conversar(prompt, num_predict=600, temperature=0.1)

        buscar, reemplazar = _extraer_bloque(respuesta)

        if buscar is None:
            ultimo_error = (
                "Ollama no devolvió el formato esperado (BUSCAR/REEMPLAZAR). "
                f"Intento {intento}/{MAX_INTENTOS_IA}."
            )
            continue

        # El modelo a veces agrega una linea en blanco de mas al principio/final
        # del bloque -- eso no cambia la indentacion INTERNA, es seguro recortarlo.
        buscar_candidatos = [buscar, buscar.strip("\n")]

        encontrado = None
        for candidato in buscar_candidatos:
            if candidato and candidato in contenido_actual:
                encontrado = candidato
                break

        if encontrado is None:
            ultimo_error = (
                "El fragmento que propuso Ollama no coincide exactamente con el "
                "archivo real (pasa seguido con modelos chicos ante instrucciones "
                f"amplias). Intento {intento}/{MAX_INTENTOS_IA}."
            )
            continue

        reemplazar_final = reemplazar.strip("\n") if encontrado == buscar.strip("\n") else reemplazar

        return _crear_propuesta(
            archivo=archivo_norm,
            buscar=encontrado,
            reemplazar=reemplazar_final,
            que=f"Modificar un fragmento de {archivo_norm} según: {instruccion}",
            por_que=f"Generado por Ollama (arche-lora) a partir de la instrucción: {instruccion}",
            como="Reemplazo de texto exacto (buscar -> reemplazar), una sola aparición, redactado por Ollama.",
            origen="ia",
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