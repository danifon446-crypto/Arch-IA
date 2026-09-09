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


def _extraer_contenido_nuevo(texto_respuesta):
    match = PATRON_BLOQUE_CONTENIDO.search(texto_respuesta)
    if not match:
        return None
    contenido = match.group(1)
    # Red de seguridad: si el modelo igual deslizo backticks de markdown
    # (```python ... ```) alrededor del codigo, los sacamos.
    contenido = re.sub(r"^```(?:python)?\n", "", contenido.strip())
    contenido = re.sub(r"\n```$", "", contenido)
    return contenido


def _proponer_archivo_nuevo_ia(archivo_norm, instruccion, origen):
    from core.IA.ollamaIA import conversar

    ok_ext, error_ext = _validar_extension(archivo_norm, es_archivo_nuevo=True)
    if not ok_ext:
        return None, error_ext

    prompt = _armar_prompt_archivo_nuevo(archivo_norm, instruccion)

    ultimo_error = "No se obtuvo respuesta del modelo."

    for intento in range(1, MAX_INTENTOS_IA + 1):
        respuesta = conversar(prompt, num_predict=800, temperature=0.2)
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

    from core.IA.ollamaIA import conversar

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