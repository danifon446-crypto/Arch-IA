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

NINGUNA de las dos funciones toca el archivo real. Eso solo pasa en
revisar_cambios_codigo.py, con tu aprobacion explicita cada vez.

LIMITE DURO: no se puede proponer un cambio sobre los archivos que
controlan este mismo sistema (ver ARCHIVOS_PROTEGIDOS). Si necesitas
tocar esos, hacelo vos a mano -- es la unica forma de garantizar que
Arche no pueda aflojar sus propias restricciones desde adentro.
"""

import ast
import json
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


def proponer_cambio_ia(archivo, instruccion):
    """
    Le pide a Ollama que redacte un cambio tipo buscar/reemplazar para
    lograr `instruccion` sobre `archivo`. Nunca reescribe el archivo
    entero: se le pide explícitamente un fragmento acotado, y se valida
    que ese fragmento exista tal cual en el archivo real antes de
    aceptar la propuesta.
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

    prompt = f"""Sos un asistente que propone UN SOLO cambio puntual de código, nunca reescribe archivos completos.

Archivo: {archivo_norm}
Contenido actual completo:
---
{contenido_actual}
---

Instrucción: {instruccion}

Respondé SOLO con un JSON con este formato exacto, sin texto adicional ni backticks:
{{"buscar": "<fragmento EXACTO y literal que existe en el archivo de arriba, copiado carácter por carácter incluyendo indentación>", "reemplazar": "<ese mismo fragmento ya modificado>", "explicacion": "<una frase corta de qué cambia y por qué>"}}

Reglas estrictas:
- "buscar" tiene que ser una copia EXACTA de un fragmento contiguo del archivo de arriba. Si no podés garantizar una copia exacta, elegí un fragmento más chico y simple (por ejemplo una sola línea o un bloque corto).
- Elegí el fragmento más chico posible que resuelva la instrucción. No reescribas el archivo completo.
- No agregues nada fuera del JSON.
"""

    respuesta = conversar(prompt, num_predict=1200)

    inicio = respuesta.find("{")
    fin = respuesta.rfind("}") + 1
    try:
        datos = json.loads(respuesta[inicio:fin])
    except (json.JSONDecodeError, ValueError):
        return None, "Ollama no devolvió un JSON válido para este cambio. Podés reintentar o hacerlo manual con proponer_cambio_manual."

    buscar = datos.get("buscar", "")
    reemplazar = datos.get("reemplazar", "")
    explicacion = datos.get("explicacion", instruccion)

    if not buscar or buscar not in contenido_actual:
        return None, (
            "El fragmento que propuso Ollama no coincide exactamente con el "
            "archivo real (pasa seguido con modelos chicos ante instrucciones "
            "amplias). No se creó ninguna propuesta -- probá con una instrucción "
            "más puntual (una función específica) o usá proponer_cambio_manual."
        )

    return _crear_propuesta(
        archivo=archivo_norm,
        buscar=buscar,
        reemplazar=reemplazar,
        que=f"Modificar un fragmento de {archivo_norm} según: {instruccion}",
        por_que=explicacion,
        como="Reemplazo de texto exacto (buscar -> reemplazar), una sola aparición, redactado por Ollama.",
        origen="ia",
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