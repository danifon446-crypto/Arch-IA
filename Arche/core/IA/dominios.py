"""
dominios.py
-----------
Ubicacion: Arche/core/IA/dominios.py

Pieza 1 del Aula de Entrenamiento Progresivo: agrupa las intenciones
que ya reconoce Arche (las mismas que arma comprender() en ollamaIA.py
y que main.py despacha) en DOMINIOS mas amplios.

Esto es solo el MAPEO -- no entrena nada ni cambia el comportamiento
actual de Arche. Lo usan:
  - clasificador_jerarquico.py (pieza 2), para separar el entrenamiento
    en una red de dominio + una red por dominio.
  - El futuro ciclo de examen (piezas 3-6), para saber en que dominio
    generar ejercicios y llevar el nivel de cada uno por separado.

Si agregas una intencion nueva en ollamaIA.py/main.py, sumala aca en el
dominio que corresponda -- si no, validar() la va a marcar como
huerfana.
"""

DOMINIOS = {
    "sistema": {
        "hora", "fecha", "ayuda", "ayuda_categoria", "buscar", "abrir",
    },
    "codigo": {
        "modificar_codigo",
    },
    "conversacion": {
        "saludo", "presentacion", "conversar",
    },
    "memoria": {
        "recordar", "mostrar_memoria", "editar_memoria",
        "crear_recordatorio", "mostrar_recordatorios",
        "completar_recordatorio", "eliminar_recordatorio",
    },
}

# Intenciones que a propósito NO tienen dominio: no tiene sentido
# entrenar una red para reconocer "no supe qué es esto".
SIN_DOMINIO = {"desconocido"}

_INDICE_INTENCION_A_DOMINIO = {
    intencion: dominio
    for dominio, intenciones in DOMINIOS.items()
    for intencion in intenciones
}


def dominio_de(intencion):
    """Devuelve el nombre del dominio de `intencion`, o None si no está
    mapeada (ni en DOMINIOS ni en SIN_DOMINIO -- probablemente una
    intención nueva que falta agregar acá)."""
    return _INDICE_INTENCION_A_DOMINIO.get(intencion)


def nombres_de_dominios():
    return list(DOMINIOS.keys())


def intenciones_de(dominio):
    return DOMINIOS.get(dominio, set())


def validar(intenciones_conocidas):
    """
    Compara `intenciones_conocidas` (ej. las que ya aparecen en los
    datos de aprendizaje.cargar()) contra este mapeo. Devuelve la lista
    de intenciones que NO están ni en DOMINIOS ni en SIN_DOMINIO -- son
    "huérfanas": probablemente una intención nueva que se agregó en
    otro lado pero todavía no se sumó acá.
    """
    mapeadas = set(_INDICE_INTENCION_A_DOMINIO) | SIN_DOMINIO
    return sorted(set(intenciones_conocidas) - mapeadas)