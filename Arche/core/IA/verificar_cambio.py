"""
verificar_cambio.py
----------------------
Ubicacion: Arche/core/IA/verificar_cambio.py

"Reasoning sandwich" aplicado al pipeline de cambios de código.

La idea (de investigación sobre por qué agentes de código andan mejor
o peor -- ver "harness engineering"): concentrar el razonamiento más
fuerte en las DOS PUNTAS de una tarea -- planificar y verificar -- y
dejar la ejecución del medio más mecánica.

Arché ya tenía la primera punta (proponer_cambio_codigo.py piensa
bastante antes de generar el parche) y el medio (el parche en sí,
probado en entorno aislado). Le faltaba la segunda punta: nadie, ni
humano ni modelo, volvía a mirar el cambio con espíritu crítico antes
de aplicarlo -- solo se chequeaba que NO estuviera roto (sintaxis,
import), nunca que hiciera de verdad lo que decía que iba a hacer.

Esto agrega esa segunda mirada, pero SOLO para cambios que
evaluar_confianza.py ya marcó como medio riesgo o para revisar con
cuidado -- los de bajo riesgo no pagan el costo extra de una llamada
más a Ollama, ya están bien cubiertos con lo mecánico.

Si la respuesta del modelo no se puede interpretar con claridad, esto
NO bloquea el cambio (el chequeo mecánico ya se corrió y pasó) --
solo se pierde esta capa extra de revisión para ese caso puntual, en
vez de convertir la verificación en un punto único de fallo que frene
todo si Ollama contesta de forma rara.
"""

import re


_MARCA_OK = "OK"
_MARCA_PROBLEMA = "PROBLEMA"


def _armar_prompt(propuesta, nivel, motivo):
    que = propuesta.get("que", "")
    por_que = propuesta.get("por_que") or ""
    buscar = propuesta.get("buscar", "")
    reemplazar = propuesta.get("reemplazar", "")

    return f"""Sos un revisor de código estricto. Te paso un cambio ya generado
-- tu trabajo NO es escribir código, es encontrarle problemas si los
tiene, con espíritu crítico, como si fueras el último control antes
de aplicarlo a un sistema real.

Por qué se hizo este cambio: {que}
{f"Contexto adicional: {por_que}" if por_que else ""}
Por qué se lo marcó como riesgo "{nivel}": {motivo}

CÓDIGO ANTERIOR (lo que se busca):
{buscar}

CÓDIGO NUEVO (lo que lo reemplaza):
{reemplazar}

Preguntate: ¿este cambio realmente logra lo que dice que hace? ¿hay
algo que se rompe, un caso raro sin cubrir, una condición invertida,
un efecto secundario no mencionado, algo que contradice el motivo
que se dio?

Respondé ÚNICAMENTE en uno de estos dos formatos, nada más:
- Si no encontrás ningún problema real: la palabra "{_MARCA_OK}" sola.
- Si encontrás un problema concreto: "{_MARCA_PROBLEMA}: " seguido de
  una explicación breve (1-2 frases) de cuál es el problema exacto.

No inventes problemas por inventar -- si el cambio está bien, decí
"{_MARCA_OK}". Solo marcá "{_MARCA_PROBLEMA}" si de verdad ves algo
concreto que está mal, no por estilo o preferencia personal.
"""


def _interpretar_respuesta(texto):
    """
    Devuelve (hay_problema, detalle, se_pudo_interpretar).
    se_pudo_interpretar=False significa "el chequeo mecánico ya pasó,
    esta capa extra no se pudo aplicar para este caso -- no bloquea".
    """
    texto_limpio = (texto or "").strip()
    texto_upper = texto_limpio.upper()

    if texto_upper.startswith(_MARCA_OK):
        return False, None, True

    if texto_upper.startswith(_MARCA_PROBLEMA):
        detalle = re.sub(rf"^{_MARCA_PROBLEMA}:?\s*", "", texto_limpio, flags=re.IGNORECASE).strip()
        return True, (detalle or "el modelo marcó un problema pero no explicó cuál"), True

    return False, None, False


def verificar_cambio_con_ia(propuesta, nivel, motivo):
    """
    Le pide a Ollama que revise el cambio con espíritu crítico.
    Devuelve (aprobado: bool, detalle: str|None).

    aprobado=True cubre dos casos distintos (mirá el resultado si te
    importa la diferencia): "el modelo no vio problema" y "no se pudo
    interpretar la respuesta, se deja pasar por default". En ambos
    casos el cambio sigue su curso normal -- este chequeo es una capa
    EXTRA sobre lo mecánico, no un reemplazo.
    """
    from core.IA.ollamaIA import generar_codigo

    prompt = _armar_prompt(propuesta, nivel, motivo)
    respuesta = generar_codigo(prompt, num_predict=200, temperature=0.1)

    hay_problema, detalle, se_pudo_interpretar = _interpretar_respuesta(respuesta)

    if not se_pudo_interpretar:
        return True, None

    if hay_problema:
        return False, detalle

    return True, None