"""
evaluar_confianza.py
----------------------
Ubicacion: Arche/core/IA/evaluar_confianza.py

Calcula un nivel de riesgo para una propuesta de cambio de codigo,
usando un CHECKLIST FIJO y auditable -- no una opinion libre de
Ollama. La idea es que el criterio sea siempre el mismo, para que se
pueda revisar despues por que a un cambio se lo etiqueto de una forma
u otra (y ajustar el checklist si el criterio resulta ser malo, en vez
de depender de que el modelo "tenga buen ojo" ese dia).

El checklist evalua 3 preguntas sobre el fragmento que cambia:
  1. ¿Toca logica condicional o de control de flujo (if/for/while/try/
     return/raise), o es puramente estructural (comentario, import,
     print, una linea aislada)?
  2. ¿Toca operaciones de red, archivos o subprocesos (abrir/borrar
     archivos, requests, sockets, subprocess, os.system)?
  3. ¿El nombre que se esta tocando (funcion/variable) tiene
     referencias reales en OTROS archivos del proyecto? (una funcion
     usada en varios lugares es mas arriesgada de tocar que una que
     solo vive en su propio archivo).

Devuelve (nivel, motivo) donde nivel es uno de:
    "bajo", "medio", "revisar con cuidado"
y motivo es una frase corta y concreta, no una etiqueta sola.
"""

import re
from pathlib import Path

RAIZ_APP = Path(__file__).resolve().parents[2]

PATRON_LOGICA = re.compile(r"\b(if|elif|else|for|while|try|except|return|raise)\b")
PATRON_IO = re.compile(r"\b(open\(|requests\.|socket\.|subprocess\.|os\.remove|os\.system|urllib|shutil\.)")
PATRON_NOMBRE_FUNCION = re.compile(r"\bdef\s+(\w+)\s*\(")


def _archivos_del_proyecto(excluir_rel=None):
    for archivo in RAIZ_APP.rglob("*.py"):
        rel = archivo.relative_to(RAIZ_APP).as_posix()
        if rel == excluir_rel:
            continue
        if any(parte in {"__pycache__", ".git", "venv", ".venv", "env"} for parte in archivo.parts):
            continue
        yield archivo, rel


def _referencias_externas(nombre_funcion, archivo_origen_rel):
    """Busca el nombre en otros archivos del proyecto. No es un
    analisis de AST completo (no resuelve imports ni alcance) --
    es deliberadamente simple: una coincidencia de texto ya es
    señal suficiente de "hay que mirar esto con mas cuidado",
    y una ausencia total es señal razonable de "esto vive solo
    en su archivo"."""
    encontrados = []
    patron = re.compile(r"\b" + re.escape(nombre_funcion) + r"\b")
    for archivo, rel in _archivos_del_proyecto(excluir_rel=archivo_origen_rel):
        try:
            contenido = archivo.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if patron.search(contenido):
            encontrados.append(rel)
    return encontrados


def evaluar_riesgo(propuesta):
    """
    propuesta: dict con al menos 'archivo', 'buscar', 'reemplazar'.
    Devuelve (nivel: str, motivo: str).
    """
    buscar = propuesta.get("buscar", "")
    reemplazar = propuesta.get("reemplazar", "")
    archivo = propuesta.get("archivo", "")
    texto_completo = buscar + reemplazar

    motivos = []
    nivel = "bajo"

    toca_logica = bool(PATRON_LOGICA.search(buscar))
    toca_io = bool(PATRON_IO.search(texto_completo))

    match_funcion = PATRON_NOMBRE_FUNCION.search(buscar)
    referencias = []
    if match_funcion:
        referencias = _referencias_externas(match_funcion.group(1), archivo)

    if toca_io:
        nivel = "revisar con cuidado"
        motivos.append("toca operaciones de red, archivos o subprocesos")
    elif toca_logica:
        nivel = "medio"
        motivos.append("modifica lógica condicional o de control de flujo, no solo estructura")
    else:
        motivos.append("cambio estructural (comentario, import o línea aislada), sin lógica condicional")

    if referencias:
        if nivel == "bajo":
            nivel = "medio"
        motivos.append(f"la función tiene referencias en {len(referencias)} otro(s) archivo(s) ({', '.join(referencias[:3])}{'...' if len(referencias) > 3 else ''})")
    elif match_funcion:
        motivos.append("sin referencias detectadas en otros archivos del proyecto")

    if reemplazar == "":
        motivos.insert(0, "elimina código")

    return nivel, "; ".join(motivos)