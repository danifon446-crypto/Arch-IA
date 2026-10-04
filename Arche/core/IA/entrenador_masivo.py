"""
entrenador_masivo.py
---------------------
Ubicacion: Arche/core/IA/entrenador_masivo.py

Resuelve tres problemas reales que aparecieron usándolo:

  1. "corrió toda la noche y casi no avanzó" -- el reentreno automático
     que dispara aprendizaje.aprender() puede colgarse en silencio si
     corre desde un hilo de fondo en Windows (ver el fix de n_jobs en
     clasificador_jerarquico.py). Acá, ADEMÁS, cada intención se
     procesa dentro de su propio try/except con un timestamp visible
     -- si UNA falla, se salta a la siguiente en vez de morir en
     silencio, y siempre queda claro hasta dónde llegó.

  2. "mas ejemplos no es la idea" -- el juez sigue existiendo
     (entrenar_a_fondo), pero ahora evalúa TODAS las frases candidatas
     de una intención en UNA sola consulta a Ollama, no una por frase
     -- mismo control de calidad, una fracción de las llamadas.

  3. "es muy lento" -- entrenar_rapido() es un camino nuevo, más
     liviano: UNA sola consulta a Ollama por intención, sin juez
     (confía en el generador), pensado para juntar volumen rápido
     cuando ya sembraste la base con sembrar_catalogo() y querés
     avanzar más rápido que con el control de calidad de fondo.

  sembrar_catalogo()   Sin Ollama, instantáneo (semillas de catalogo.py).
  entrenar_rapido()    Con Ollama, SIN juez, una consulta por intención.
  entrenar_a_fondo()   Con Ollama, CON juez por lote (más lento, más limpio).
"""

import time
from datetime import datetime

from core.IA import catalogo

PAUSA_ENTRE_INTENCIONES_SEG = 2


def _ahora():
    return datetime.now().strftime("%H:%M:%S")


def sembrar_catalogo(silencioso=False):
    """
    Siembra INSTANTÁNEA: usa las semillas + rellenos ya escritos a mano
    en catalogo.py, sin llamar a Ollama. Le da a TODAS las intenciones
    una base mínima de una sola pasada.
    """
    from core.IA import aprendizaje

    # aprender() reentrena todas las redes cada UMBRAL_REENTRENO ejemplos; al
    # sembrar cientos de golpe eso eran decenas de reentrenos (y de avisos en
    # pantalla). Igual que 'importar ejemplos': se desactiva durante la carga
    # y se reentrena UNA sola vez al final.
    umbral_original = aprendizaje.UMBRAL_REENTRENO
    aprendizaje.UMBRAL_REENTRENO = float("inf")
    agregados = 0
    try:
        for entrada in catalogo.ENTRADAS:
            for frase, contenido in catalogo.expandir_semillas(entrada, max_por_semilla=2):
                aprendizaje.aprender(frase, entrada["id"], contenido, fuente="catalogo")
                agregados += 1
    finally:
        aprendizaje.UMBRAL_REENTRENO = umbral_original

    if not silencioso:
        print(f"Arché: Sembré {agregados} ejemplo(s) base para {len(catalogo.ENTRADAS)} intenciones del catálogo.")
    if agregados:
        if not silencioso:
            print("Arché: Reentreno las redes una sola vez (puede tardar un poco)...")
        aprendizaje.reentrenar_ahora()
    return agregados


def _limpiar_lineas(texto):
    lineas = []
    for linea in (texto or "").strip().splitlines():
        limpia = linea.strip().strip('"').strip("'").strip()
        limpia = limpia.lstrip("0123456789.-) ").strip()
        if limpia:
            lineas.append(limpia)
    return lineas


def _generar_frases_libres(entrada, cantidad):
    """Para intenciones SIN argumento: frases completas, listas para usar."""
    from core.IA.ollamaIA import conversar

    prompt = (
        f"Generá {cantidad} frases DISTINTAS y naturales en español, de las que "
        f"alguien le diría de verdad a un asistente virtual para pedirle esto: "
        f"\"{entrada['descripcion']}\". Variá el largo y el estilo (alguna corta, "
        f"alguna más elaborada, alguna informal). Una por línea, sin numerar, sin "
        f"comillas, sin explicación."
    )
    respuesta = conversar(prompt, num_predict=350, temperature=0.9)
    return _limpiar_lineas(respuesta)[:cantidad]


def _generar_plantillas(entrada, cantidad):
    """Para intenciones CON argumento: variaciones de la plantilla ya
    escrita en catalogo.py, preservando "{X}" literal -- así se sabe
    con exactitud dónde va el dato variable."""
    from core.IA.ollamaIA import conversar

    plantilla_base = entrada["semillas"][0]
    prompt = (
        f'Tomá esta plantilla de frase: "{plantilla_base}"\n\n'
        f"Generá {cantidad} formas DISTINTAS y naturales de decir lo mismo en "
        f'español, conservando el marcador "{{X}}" EXACTAMENTE IGUAL, tal cual, '
        f"en el lugar que corresponda (nunca lo traduzcas ni lo cambies). Una por "
        f"línea, sin numerar, sin comillas, sin explicación."
    )
    respuesta = conversar(prompt, num_predict=300, temperature=0.9)
    return [l for l in _limpiar_lineas(respuesta) if "{X}" in l][:cantidad]


def _candidatas_para(entrada, cantidad):
    """(frase, contenido) para una intención, sin filtrar todavía --
    con argumento (plantillas × rellenos) o sin él (frases libres)."""
    if entrada.get("argumento"):
        rellenos = catalogo.RELLENOS.get(entrada["argumento"], [])
        if not rellenos:
            return []
        plantillas = _generar_plantillas(entrada, max(2, cantidad // 3))
        candidatas = []
        for plantilla in plantillas:
            for relleno in rellenos[:3]:
                candidatas.append((plantilla.replace("{X}", relleno), relleno))
        return candidatas[:cantidad]
    return [(f, "") for f in _generar_frases_libres(entrada, cantidad)]


def _juez_filtra(candidatas, entrada):
    """
    UNA sola consulta a Ollama para TODAS las candidatas de esta
    intención (antes era una consulta por frase -- esto corta las
    llamadas al juez a una fracción). Le muestra las frases numeradas
    y le pide que devuelva SOLO los números que de verdad representan
    la intención pedida.

    Si Ollama no responde en un formato parseable, se queda con TODAS
    las candidatas (falla hacia "aceptar", no hacia "perder todo el
    trabajo de generación" -- el juez es un filtro extra, no el único
    control de calidad).
    """
    from core.IA.ollamaIA import conversar

    if not candidatas:
        return []

    lista = "\n".join(f"{i+1}. {frase}" for i, (frase, _) in enumerate(candidatas))
    prompt = (
        f"Las siguientes frases DEBERÍAN ser pedidos de un usuario a un asistente "
        f"virtual para esto: \"{entrada['descripcion']}\".\n\n{lista}\n\n"
        f"Decime SOLO los números de las frases que de verdad representan ese pedido "
        f"con claridad (descartá las que quedaron ambiguas, incompletas o que piden "
        f"otra cosa). Respondé ÚNICAMENTE los números separados por comas, sin texto "
        f"antes ni después. Si todas sirven, respondé todos los números."
    )
    respuesta = conversar(prompt, num_predict=60, temperature=0.0)

    import re
    numeros = {int(n) for n in re.findall(r"\d+", respuesta or "")}
    if not numeros:
        return candidatas  # el juez no dio un formato usable -> no se descarta nada

    return [c for i, c in enumerate(candidatas) if (i + 1) in numeros]


def entrenar_a_fondo(por_intencion=6, detener_evento=None, avisar_progreso=None, silencioso=False):
    """
    Pasada completa sobre el catálogo con control de calidad: por cada
    intención, genera candidatas y las filtra con el juez (UNA consulta
    por intención, no por frase) antes de guardarlas. Cada intención
    corre dentro de su propio try/except -- si una falla, se anota y
    se sigue con la próxima, nunca se corta la corrida entera.
    """
    from core.IA import aprendizaje

    resumen = {"generadas": 0, "aceptadas": 0, "fallidas": [], "por_intencion": {}}
    total = len(catalogo.ENTRADAS)

    for i, entrada in enumerate(catalogo.ENTRADAS, start=1):
        if detener_evento is not None and detener_evento.is_set():
            if not silencioso:
                print(f"Arché (entrenamiento): [{_ahora()}] detenido a pedido, en {i}/{total}.")
            break

        try:
            candidatas = _candidatas_para(entrada, por_intencion)
            aceptadas = _juez_filtra(candidatas, entrada)
            for frase, contenido in aceptadas:
                aprendizaje.aprender(frase, entrada["id"], contenido, fuente="entrenamiento_masivo")

            resumen["generadas"] += len(candidatas)
            resumen["aceptadas"] += len(aceptadas)
            resumen["por_intencion"][entrada["id"]] = len(aceptadas)

            mensaje = f"[{_ahora()}] ({i}/{total}) '{entrada['id']}': {len(aceptadas)}/{len(candidatas)} aceptadas"
            if avisar_progreso:
                avisar_progreso(entrada["id"], len(aceptadas), len(candidatas))
            elif not silencioso:
                print(f"Arché (entrenamiento): {mensaje}")

        except Exception as e:
            resumen["fallidas"].append(entrada["id"])
            if not silencioso:
                print(f"Arché (entrenamiento): [{_ahora()}] ({i}/{total}) '{entrada['id']}' falló "
                      f"({type(e).__name__}: {e}) -- sigo con la próxima.")

        time.sleep(PAUSA_ENTRE_INTENCIONES_SEG)

    if not silencioso:
        print(f"Arché: Entrenamiento a fondo terminado -- {resumen['aceptadas']}/{resumen['generadas']} "
              f"aceptados, {len(resumen['fallidas'])} intención(es) fallaron"
              f"{': ' + ', '.join(resumen['fallidas']) if resumen['fallidas'] else ''}.")

    return resumen


def entrenar_rapido(por_intencion=10, detener_evento=None, avisar_progreso=None, silencioso=False):
    """
    Camino RÁPIDO: sin juez, una sola consulta a Ollama por intención
    (la de generación, nada más). Pensado para juntar volumen rápido
    después de haber sembrado la base -- menos control de calidad que
    entrenar_a_fondo, pero varias veces más rápido.
    """
    from core.IA import aprendizaje

    resumen = {"generadas": 0, "aceptadas": 0, "fallidas": [], "por_intencion": {}}
    total = len(catalogo.ENTRADAS)

    for i, entrada in enumerate(catalogo.ENTRADAS, start=1):
        if detener_evento is not None and detener_evento.is_set():
            if not silencioso:
                print(f"Arché (entrenamiento rápido): [{_ahora()}] detenido a pedido, en {i}/{total}.")
            break

        try:
            candidatas = _candidatas_para(entrada, por_intencion)
            for frase, contenido in candidatas:
                aprendizaje.aprender(frase, entrada["id"], contenido, fuente="entrenamiento_rapido")

            resumen["generadas"] += len(candidatas)
            resumen["aceptadas"] += len(candidatas)
            resumen["por_intencion"][entrada["id"]] = len(candidatas)

            mensaje = f"[{_ahora()}] ({i}/{total}) '{entrada['id']}': {len(candidatas)} agregadas"
            if avisar_progreso:
                avisar_progreso(entrada["id"], len(candidatas), len(candidatas))
            elif not silencioso:
                print(f"Arché (entrenamiento rápido): {mensaje}")

        except Exception as e:
            resumen["fallidas"].append(entrada["id"])
            if not silencioso:
                print(f"Arché (entrenamiento rápido): [{_ahora()}] ({i}/{total}) '{entrada['id']}' falló "
                      f"({type(e).__name__}: {e}) -- sigo con la próxima.")

        time.sleep(1)

    if not silencioso:
        print(f"Arché: Entrenamiento rápido terminado -- {resumen['aceptadas']} ejemplos nuevos, "
              f"{len(resumen['fallidas'])} intención(es) fallaron"
              f"{': ' + ', '.join(resumen['fallidas']) if resumen['fallidas'] else ''}.")

    return resumen


def estado_banco():
    """Para el comando 'estado banco': cuántos ejemplos hay HOY por
    intención, comparado contra el catálogo completo."""
    from core.IA import aprendizaje
    from collections import Counter

    datos = aprendizaje.cargar()
    conteo = Counter(d.get("accion") for d in datos)

    lineas = []
    for entrada in sorted(catalogo.ENTRADAS, key=lambda e: conteo.get(e["id"], 0)):
        n = conteo.get(entrada["id"], 0)
        marca = "⚠️ " if n < 5 else ""
        lineas.append(f"  {marca}{entrada['id']} ({entrada['dominio']}): {n} ejemplo(s)")

    huerfanos = set(conteo) - set(catalogo.POR_ID)
    total = sum(conteo.values())
    encabezado = f"Total en conocimiento.json: {total} ejemplos, {len(catalogo.ENTRADAS)} intenciones en el catálogo."
    pie = f"\n  (hay {len(huerfanos)} acción(es) en los datos que no están en el catálogo: {sorted(huerfanos)})" if huerfanos else ""
    return encabezado + "\n" + "\n".join(lineas) + pie