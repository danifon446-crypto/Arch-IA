"""
narrador.py
--------------
Ubicacion: Arche/core/IA/narrador.py

Punto único donde vive la traducción de "cosas técnicas del código"
a "lenguaje natural, como si Arché te estuviera hablando". Antes esto
vivía duplicado dentro de revisar_cambios_codigo.py; ahora cualquier
módulo que necesite explicarte algo de código (proponer un cambio,
reportar un hallazgo de autorevisión, contar qué se rompió y se
reparó solo) pasa por acá, para que la voz de Arché sea consistente
en todos lados y no haya que mantener la misma traducción en dos
lugares distintos.

Uso:
    from core.IA.narrador import area_natural, texto_amigable_que, frase_confianza
"""

import re

ETIQUETA_ORIGEN = {
    "usuario_directo": "me lo pediste vos",
    "autorevision": "lo encontré yo solo revisándome",
    "generalizado": "es una extensión de un cambio que ya aprobaste antes",
    "manual": "lo armé sin usar el modelo",
    "ia": "lo redactó el modelo a tu pedido",
}

MAPA_AREAS_NATURALES = {
    "notas": "las notas",
    "recordatorio": "los recordatorios",
    "calculadora": "la calculadora",
    "archivos": "la búsqueda de archivos",
    "memoria": "la memoria",
    "configuracion": "la configuración",
    "navegador": "el navegador",
    "conversacion": "las respuestas rápidas",
    "utilidades": "las utilidades generales",
    "sistema": "el sistema",
    "busquedas": "las búsquedas",
    "programaV2": "el manejo de programas",
    "introspeccion": "el análisis interno de mi propio código",
    "autorevision": "mi sistema de autorevisión",
    "ollamaIA": "la conexión con Ollama",
    "aprendizaje": "mi sistema de aprendizaje",
    "respuestas": "mi caché de respuestas",
    "telemetria": "las estadísticas de uso",
    "estudio": "el modo estudio",
    "clasificador": "mi clasificador de intenciones",
    "embeddings": "el sistema de comparación semántica",
    "enrutar_cambio": "el sistema que decide dónde aplicar un cambio",
    "proponer_cambio_codigo": "el generador de propuestas de código",
    "revisar_cambios_codigo": "el revisor de cambios de código",
    "revertir_cambio_codigo": "el sistema de reversión de cambios",
    "evaluar_confianza": "el evaluador de riesgo de un cambio",
    "orquestador_autonomo": "el orquestador de autorreparación",
    "autodiagnostico": "el autodiagnóstico",
}


def area_natural(archivo_norm):
    """
    Convierte una ruta como 'core/IA/notas.py' en una frase hablada
    como 'las notas'. Si no hay traducción conocida, arma algo
    razonable a partir del nombre del archivo en vez de mostrar la
    ruta cruda.
    """
    nombre = archivo_norm
    if nombre.startswith("core/IA/"):
        nombre = nombre[len("core/IA/"):]
    elif nombre.startswith("core/"):
        nombre = nombre[len("core/"):]
    if nombre.endswith(".py"):
        nombre = nombre[:-3]

    if nombre in MAPA_AREAS_NATURALES:
        return MAPA_AREAS_NATURALES[nombre]

    return nombre.replace("_", " ")


def texto_amigable_que(que_texto):
    """
    Limpia el campo 'que' de una propuesta (a veces trae texto
    técnico tipo 'según: ...' o 'Eliminar la función X') para que
    suene a una frase dicha en voz alta.
    """
    match = re.search(r"según:\s*(.+)$", que_texto, re.DOTALL)
    if match:
        return match.group(1).strip()

    match_eliminar = re.search(r"Eliminar la función '([^']+)'", que_texto)
    if match_eliminar:
        return f"eliminar la función '{match_eliminar.group(1)}', que no se usa en ningún otro lugar"

    return que_texto


def frase_confianza(nivel, motivo=None):
    nivel_norm = (nivel or "").strip().lower()
    if "bajo" in nivel_norm:
        return "Es un cambio chico y me da bastante confianza."
    if "medio" in nivel_norm:
        return "Toca algo de lógica real, no es trivial -- vale la pena que lo mires con algo de atención."
    return "Este es más delicado que lo habitual -- prestale especial atención antes de aprobar."


def nombre_funcion_hablado(nombre_funcion):
    """'_construir_indice_referencias' -> 'construir indice referencias' (sin guiones bajos ni prefijos privados)."""
    return nombre_funcion.lstrip("_").replace("_", " ")
