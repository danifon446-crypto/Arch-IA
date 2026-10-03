"""
dominios.py
-----------
Ubicacion: Arche/core/IA/dominios.py

Pieza 1 del Aula de Entrenamiento Progresivo -- reescrito para salir
del CATALOGO (catalogo.py) en vez de tener 4 dominios fijos a mano.

Antes este archivo definia manualmente solo 4 dominios (sistema,
codigo, conversacion, memoria) cubriendo ~17 intenciones -- las unicas
que Ollama sabia reconocer en comprender(). Arche maneja muchas mas
(notas, archivos, calculadora, configuracion, y todo lo que se fue
agregando: Gran Sabio, examen, estudio...). Ahora que catalogo.py es
la fuente unica de TODO lo que Arche sabe hacer, los dominios salen
de ahi automaticamente -- agregar una intencion nueva al catalogo la
suma a su dominio sin tocar este archivo.
"""

from core.IA import catalogo

DOMINIOS = {
    dominio: set(ids)
    for dominio, ids in catalogo.dominios_del_catalogo().items()
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
    intención nueva que falta agregar en catalogo.py)."""
    return _INDICE_INTENCION_A_DOMINIO.get(intencion)


def nombres_de_dominios():
    return list(DOMINIOS.keys())


def intenciones_de(dominio):
    return DOMINIOS.get(dominio, set())


def es_trivial(dominio):
    """True si el dominio tiene UNA sola intención posible (ej. 'codigo':
    solo 'modificar_codigo', ya que las demás acciones de código --
    revisar cambios, analizar, riesgo -- ahora también viven en el
    dominio 'codigo' del catálogo, así que en la práctica ya no es
    trivial; queda la función por si algún dominio nuevo sí lo es).
    Un dominio trivial nunca puede entrenar una red de intención propia
    -- el clasificador necesita al menos 2 clases para tener algo que
    distinguir. No es falta de datos: aunque se junten mil ejemplos,
    seguirá siendo una sola clase. Ahí, saber el DOMINIO ya resuelve la
    intención sin hacer falta ninguna red adicional."""
    return len(intenciones_de(dominio)) == 1


def unica_intencion_de(dominio):
    """Para un dominio trivial (ver es_trivial): su única intención
    posible, o None si el dominio no es trivial o no existe."""
    intenciones = intenciones_de(dominio)
    return next(iter(intenciones)) if len(intenciones) == 1 else None


def tiene_subdominios(dominio):
    """True si `dominio` se partió en sub-grupos en catalogo.py (ej.
    'arche', con sus 23 intenciones repartidas en 6 sub-temas). Un
    dominio sin subdominios entrena en DOS niveles, como siempre
    (dominio -> intención); uno con subdominios pasa a TRES
    (dominio -> subdominio -> intención) -- "miniredes de las
    miniredes": cada subdominio es una red chica que solo tiene que
    distinguir entre sus pocas intenciones hermanas, en vez de una
    sola red peleándose con las 23 del dominio entero."""
    return catalogo.tiene_subdominios(dominio)


def subdominios_de(dominio):
    return catalogo.subdominios_de(dominio)


def subdominio_de(intencion):
    return catalogo.subdominio_de(intencion)


def validar(intenciones_conocidas):
    """
    Compara `intenciones_conocidas` (ej. las que ya aparecen en los
    datos de aprendizaje.cargar()) contra este mapeo. Devuelve la lista
    de intenciones que NO están ni en DOMINIOS ni en SIN_DOMINIO -- son
    "huérfanas": probablemente una intención vieja (de antes del
    catálogo) que ya no está mapeada, o un dato con la acción mal escrita.
    """
    mapeadas = set(_INDICE_INTENCION_A_DOMINIO) | SIN_DOMINIO
    return sorted(set(intenciones_conocidas) - mapeadas)