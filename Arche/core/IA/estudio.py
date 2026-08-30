"""
estudio.py
----------
"Modo estudio": Arché se hace preguntas a sí misma (sobre temas que vos
definas, y variaciones de lo que ya aprendió) para pre-cachear respuestas
y comandos usando Ollama como "maestro", en vez de esperar a que
preguntes lo mismo en el momento real.

IMPORTANTE - qué es y qué no es esto:
No crea razonamiento nuevo. Todo el contenido sigue viniendo de Ollama.
Lo que hace es ADELANTAR ese trabajo en background, para que cuando
preguntes algo parecido más tarde, ya esté guardado y no haga falta
esperar a Ollama en el momento.

Se puede correr:
  - en background al arrancar Arché (hilo aparte, con pausas entre cada
    llamada a Ollama para no saturar el hardware mientras usás Arché
    en paralelo)
  - manualmente, con el comando "estudiar" en main.py
"""

import json
import os
import re
import time
import threading

BASE = os.path.dirname(__file__)
ARCHIVO_TEMAS = os.path.join(BASE, "temas_estudio.json")

PAUSA_ENTRE_LLAMADAS_SEG = 3     # no saturar Ollama mientras se estudia en background
PREGUNTAS_POR_TEMA = 6
VARIACIONES_POR_ITEM = 3
MAX_ITEMS_A_VARIAR = 5           # por ronda, cuántos comandos/preguntas ya aprendidos se toman para generar variaciones
INTERVALO_ENTRE_RONDAS_SEG = 600  # 10 min de pausa entre una ronda de estudio y la siguiente


FRASES_DE_RELLENO = (
    "claro", "aqui tienes", "aquí tienes", "por supuesto", "estas son",
    "estas son las", "aca tienes", "acá tienes", "aca van", "acá van",
    "aca te dejo", "acá te dejo", "espero que", "aqui te dejo", "aquí te dejo",
)


def _es_linea_de_relleno(linea):
    import unicodedata
    linea_norm = unicodedata.normalize("NFKD", linea.lower())
    linea_norm = "".join(c for c in linea_norm if not unicodedata.combining(c))
    return any(linea_norm.startswith(frase) for frase in FRASES_DE_RELLENO)


def _parece_completa(linea):
    """
    Descarta líneas que probablemente se cortaron a mitad de camino por
    el límite de tokens de Ollama (num_predict): no terminan en
    puntuación de cierre.
    """
    return linea.rstrip().endswith((".", "?", "!", ":", ")", '"'))


def _normalizar_lista(texto_respuesta, requerir_pregunta=False):
    """
    Convierte una respuesta de Ollama (una idea por línea, tal vez
    numerada) en lista de strings limpios, descartando:
      - líneas vacías
      - líneas de relleno/preámbulo ("Claro, aquí tienes...")
      - líneas que parecen cortadas a mitad de frase (num_predict)
      - si requerir_pregunta=True, líneas que no tienen "?" (para el
        caso de generar preguntas, donde una línea sin "?" no es una
        pregunta real, es basura o relleno)
    """
    lineas = texto_respuesta.strip().split("\n")
    resultado = []
    for linea in lineas:
        limpia = re.sub(r"^[\d\.\-\)\s]+", "", linea).strip()
        if not limpia:
            continue
        if _es_linea_de_relleno(limpia):
            continue
        if not _parece_completa(limpia):
            continue
        if requerir_pregunta and "?" not in limpia:
            continue
        resultado.append(limpia)
    return resultado


# ------------------------------------------------------------------
# Gestión de temas (lo que vos definís)
# ------------------------------------------------------------------
def cargar_temas():
    if not os.path.exists(ARCHIVO_TEMAS):
        return []
    try:
        with open(ARCHIVO_TEMAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_temas(temas):
    with open(ARCHIVO_TEMAS, "w", encoding="utf-8") as f:
        json.dump(temas, f, indent=4, ensure_ascii=False)


def agregar_tema(tema, descripcion=None):
    temas = cargar_temas()
    tema = tema.strip()
    if not tema:
        return False

    ya_existe = any(_texto_tema(t)[0] == tema for t in temas)
    if ya_existe:
        return False

    if descripcion:
        temas.append({"tema": tema, "descripcion": descripcion.strip()})
    else:
        temas.append(tema)

    guardar_temas(temas)
    return True


def _texto_tema(item):
    """
    Un tema puede guardarse como string simple ("arduino") o como dict
    con descripción ({"tema": "ollama", "descripcion": "herramienta para
    correr modelos de lenguaje localmente"}) -- esto último ayuda cuando
    el nombre del tema es ambiguo/raro y el modelo chico lo confunde con
    otra palabra (ej. "ollama" -> "olla").
    """
    if isinstance(item, dict):
        return item.get("tema", ""), item.get("descripcion")
    return item, None


# ------------------------------------------------------------------
# Generación vía Ollama
# ------------------------------------------------------------------
def _generar_preguntas_sobre_tema(tema, descripcion=None, cantidad=PREGUNTAS_POR_TEMA):
    from core.IA.ollamaIA import conversar

    referencia_tema = f"'{tema}' ({descripcion})" if descripcion else f"'{tema}'"

    prompt = f"""Eres un generador de preguntas de estudio sobre el tema: {referencia_tema}

Genera {cantidad} preguntas EN ESPAÑOL que, si se responden bien, le den
a quien las lee capacidad real de entender y USAR el tema — no solo un
dato suelto para recitar.

Reparte las preguntas entre estos ángulos (no repitas el mismo ángulo
dos veces si podés):
1. CONCEPTO: ¿qué es y cómo funciona en el fondo?
2. APLICACIÓN PRÁCTICA: ¿cómo se usa o para qué se aplica en la vida real?
3. COMPARACIÓN: ¿en qué se diferencia de sus alternativas más comunes?
4. DECISIÓN: ¿cuándo conviene usarlo y cuándo NO conviene?
5. PROBLEMAS COMUNES: ¿qué suele salir mal y cómo se soluciona o se evita?
6. RELACIÓN: ¿cómo se conecta con otros conceptos o herramientas relacionadas?

Evita preguntas de trivia específica y sin valor práctico, como
"¿a qué altura se debe montar X?" o "¿de qué color suele ser X?".
Cada pregunta debe servir para construir criterio, no solo memorizar
un hecho aislado.

Responde SOLO con las preguntas, una por línea, sin numerar, sin
explicaciones, sin frase introductoria antes de la lista."""

    respuesta = conversar(prompt, num_predict=600)
    return _normalizar_lista(respuesta, requerir_pregunta=True)[:cantidad]


def _generar_variaciones(frase, cantidad=VARIACIONES_POR_ITEM):
    from core.IA.ollamaIA import conversar

    prompt = (
        f"Genera {cantidad} formas distintas y naturales de decir esto en "
        f"español, conservando exactamente el mismo significado: '{frase}'. "
        f"Una por línea, sin numerar, sin explicaciones, sin frase introductoria."
    )
    respuesta = conversar(prompt, num_predict=400)
    return _normalizar_lista(respuesta)[:cantidad]


# ------------------------------------------------------------------
# Estudio de temas (preguntas nuevas -> respuestas.py)
# ------------------------------------------------------------------
def _estudiar_tema(item):
    from core.IA.ollamaIA import conversar
    from core.IA.respuestas import buscar_respuesta, guardar_respuesta

    tema, descripcion = _texto_tema(item)

    print(f"Arché (estudio): repasando el tema '{tema}'...")
    preguntas = _generar_preguntas_sobre_tema(tema, descripcion)

    for pregunta in preguntas:
        if buscar_respuesta(pregunta):
            continue  # ya la sabe, no gastamos otra llamada a Ollama

        respuesta = conversar(pregunta)
        guardar_respuesta(pregunta, respuesta)
        print(f"Arché (estudio): aprendí a responder '{pregunta}'")
        time.sleep(PAUSA_ENTRE_LLAMADAS_SEG)


def _estudiar_todos_los_temas():
    for item in cargar_temas():
        _estudiar_tema(item)


# ------------------------------------------------------------------
# Estudio de variaciones (de lo que ya se aprendió)
# ------------------------------------------------------------------
def _estudiar_variaciones_de_comandos():
    from core.IA.aprendizaje import cargar as cargar_comandos, aprender

    datos = cargar_comandos()
    for dato in datos[:MAX_ITEMS_A_VARIAR]:
        variaciones = _generar_variaciones(dato["pregunta"])
        for variacion in variaciones:
            aprender(variacion, dato["accion"], dato["contenido"], fuente="estudio")
        if variaciones:
            print(f"Arché (estudio): {len(variaciones)} variaciones nuevas para '{dato['pregunta']}'")
        time.sleep(PAUSA_ENTRE_LLAMADAS_SEG)


def _estudiar_variaciones_de_respuestas():
    from core.IA.respuestas import cargar as cargar_respuestas, guardar_respuesta

    datos = cargar_respuestas()
    for dato in datos[:MAX_ITEMS_A_VARIAR]:
        variaciones = _generar_variaciones(dato["pregunta"])
        for variacion in variaciones:
            # No hace falta volver a preguntarle a Ollama la respuesta:
            # es la MISMA respuesta, solo asociamos una forma nueva de
            # preguntar la misma cosa.
            guardar_respuesta(variacion, dato["respuesta"])
        if variaciones:
            print("Arché (estudio): variaciones nuevas para una respuesta ya conocida")
        time.sleep(PAUSA_ENTRE_LLAMADAS_SEG)


# ------------------------------------------------------------------
# Orquestación
# ------------------------------------------------------------------
def estudiar_todo():
    """Corre todo el modo estudio de una (temas + variaciones + limpieza). Bloqueante."""
    print("Arché: Empezando modo estudio...")
    try:
        _estudiar_todos_los_temas()
        _estudiar_variaciones_de_comandos()
        _estudiar_variaciones_de_respuestas()

        # Limpieza automática y conservadora al final de cada ronda:
        # borra solo contaminación de patrón obvio (contenido cruzado
        # entre preguntas claramente distintas). No toca casos dudosos.
        from core.IA.limpieza_auto import limpiar_automatico
        resultado_limpieza = limpiar_automatico(simular=False)
        if resultado_limpieza["borrados"] > 0:
            print(f"Arché (estudio): limpieza automática, {resultado_limpieza['borrados']} entradas contaminadas eliminadas.")

    except Exception as e:
        print(f"Arché: El modo estudio se detuvo por un error ({e}).")
    print("Arché: Modo estudio terminado.")


def iniciar_estudio_en_background(
    retraso_inicial_seg=8,
    intervalo_entre_rondas_seg=INTERVALO_ENTRE_RONDAS_SEG,
    detener_evento=None,
):
    """
    Corre estudiar_todo() en un hilo aparte, en LOOP continuo mientras
    Arché esté abierta: una ronda, pausa de intervalo_entre_rondas_seg,
    otra ronda, y así sucesivamente.

    detener_evento: threading.Event opcional. Si se pasa y se llama a
    evento.set() desde afuera (ej. un comando "detener estudio" en
    main.py), el loop termina prolijamente en vez de seguir para siempre.

    Como cada ronda ya se salta las preguntas que resultan casi
    idénticas a algo que ya sabe (via buscar_respuesta), las rondas
    sucesivas naturalmente van generando cada vez más contenido nuevo
    en vez de repetir trabajo.
    """
    def _tarea():
        time.sleep(retraso_inicial_seg)
        while detener_evento is None or not detener_evento.is_set():
            estudiar_todo()
            print(f"Arché (estudio): próxima ronda en {intervalo_entre_rondas_seg // 60} min.")

            # Espera interrumpible: revisa cada segundo si nos pidieron
            # parar, en vez de dormir el intervalo entero de una vez.
            for _ in range(intervalo_entre_rondas_seg):
                if detener_evento is not None and detener_evento.is_set():
                    break
                time.sleep(1)

        print("Arché (estudio): detenido.")

    hilo = threading.Thread(target=_tarea, daemon=True)
    hilo.start()
    return hilo