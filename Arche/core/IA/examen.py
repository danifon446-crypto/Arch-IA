"""
examen.py
---------
Ubicacion: Arche/core/IA/examen.py

Piezas 3, 4, 5 y 6 del Aula de Entrenamiento Progresivo. A diferencia
de estudio.py (que genera contenido a ciegas y lo cachea), esto EXAMINA
al clasificador jerarquico (clasificador_jerarquico.py) con ejercicios
de intencion CONOCIDA, mide si acierta, y solo entonces decide si
avanzar de nivel o reforzar lo que fallo.

  Pieza 3 -- CICLO DE EXAMEN:
    generar_ejercicio()  Ollama arma una frase con una tactica y una
                          intencion ya elegida (el "correcto" se sabe
                          de antemano, no hay que adivinarlo).
    rendir_examen()       Le pasa cada frase al clasificador jerarquico
                          y compara la prediccion contra la intencion
                          real.

  Pieza 4 -- TACTICAS: 8 formas de generar el ejercicio (ver TACTICAS),
    cada una con un nivel minimo en el que se habilita.

  Pieza 5 -- CURRICULO PROGRESIVO: un nivel_grupal UNICO para todos los
    dominios (ver examen_progreso.json). Cada dominio junta una racha
    de aciertos en el nivel actual; cuando TODOS los dominios llegan a
    la racha necesaria, el grupo entero sube de nivel junto (no antes).
    Mientras algunos dominios ya estan "listos" y otros no, el ciclo
    prioriza examinar a los atrasados.

  Pieza 6 -- REFUERZO AUTOMATICO: si el clasificador falla un
    ejercicio, esa frase exacta + la intencion correcta se agregan YA
    MISMO como dato de entrenamiento (via aprendizaje.aprender()) --
    sin pasar por ningun gate de aprobacion, a diferencia de los
    cambios de codigo. Un fallo de examen es solo informacion: no hay
    riesgo de romper nada, así que no hace falta tu OK cada vez.

IMPORTANTE -- una pieza que todavia falta conectar:
  Para poder EVALUAR una frase nueva contra el clasificador, hace
  falta convertirla en el mismo tipo de embedding que se uso para
  entrenar. Ese calculo vive en core/IA/aprendizaje.py, que todavia no
  vi -- _obtener_embedding_por_defecto() intenta encontrarlo solo
  (prueba nombres comunes) y, si no lo encuentra, avisa con un mensaje
  claro en vez de fallar en silencio o inventar un import que no
  existe. Pasame aprendizaje.py para conectarlo del todo.

Requiere lo mismo que clasificador_jerarquico.py (scikit-learn, numpy,
imbalanced-learn) mas Ollama para generar los ejercicios.
"""

import json
import os
import random
import time
import threading

from core.IA import dominios
from core.IA import clasificador_jerarquico as cj

BASE = os.path.dirname(__file__)
ARCHIVO_PROGRESO = os.path.join(BASE, "examen_progreso.json")

UMBRAL_RACHA = 4              # aciertos seguidos en el nivel actual para marcarse "listo"
CANTIDAD_POR_RONDA = 5         # ejercicios por llamada a rendir_examen()
PAUSA_ENTRE_EJERCICIOS_SEG = 3  # no saturar Ollama, mismo criterio que estudio.py
INTERVALO_ENTRE_RONDAS_SEG = 900  # 15 min entre ronda y ronda en background


# --------------------------------------------------------------------
# PIEZA 5: progreso -- nivel grupal unico + racha por dominio
# --------------------------------------------------------------------

def _progreso_default():
    return {
        "nivel_grupal": 1,
        "dominios": {
            nombre: {"racha": 0, "listo": False}
            for nombre in dominios.nombres_de_dominios()
        },
    }


def _cargar_progreso():
    if not os.path.exists(ARCHIVO_PROGRESO):
        return _progreso_default()
    try:
        with open(ARCHIVO_PROGRESO, "r", encoding="utf-8") as f:
            progreso = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _progreso_default()

    # si se agrego un dominio nuevo en dominios.py despues de guardar
    # progreso por primera vez, lo suma sin pisar lo que ya habia.
    for nombre in dominios.nombres_de_dominios():
        progreso.setdefault("dominios", {}).setdefault(nombre, {"racha": 0, "listo": False})
    return progreso


def _guardar_progreso(progreso):
    with open(ARCHIVO_PROGRESO, "w", encoding="utf-8") as f:
        json.dump(progreso, f, ensure_ascii=False, indent=2)


def _subir_nivel_grupal(progreso):
    progreso["nivel_grupal"] += 1
    for info in progreso["dominios"].values():
        info["racha"] = 0
        info["listo"] = False


def elegir_dominio_a_examinar(progreso):
    """
    Prioriza a los dominios que TODAVÍA no llegaron a la racha
    necesaria en el nivel actual (piece 5: "el esfuerzo se redirige a
    nivelar a los atrasados"). Si ya todos están listos, sube el grupo
    entero de nivel y arranca de nuevo con cualquiera.
    """
    atrasados = [d for d, info in progreso["dominios"].items() if not info["listo"]]
    if atrasados:
        return random.choice(atrasados)
    _subir_nivel_grupal(progreso)
    return random.choice(dominios.nombres_de_dominios())


def registrar_resultado(progreso, dominio, acierto):
    """Actualiza la racha de `dominio` tras un ejercicio, y lo marca
    'listo' si alcanzó UMBRAL_RACHA en el nivel actual."""
    info = progreso["dominios"][dominio]
    if acierto:
        info["racha"] += 1
    else:
        info["racha"] = 0
    if info["racha"] >= UMBRAL_RACHA:
        info["listo"] = True


def _marcar_automatico(corriendo):
    """Persiste si el LOOP automático (iniciar_examen_en_background) está
    corriendo ahora mismo -- separado de si hay una ronda de 'examen'
    manual en curso. Se guarda junto al progreso porque es el mismo
    archivo/candado que ya existe, no hace falta uno nuevo."""
    progreso = _cargar_progreso()
    progreso["automatico_corriendo"] = corriendo
    progreso["automatico_actualizado_ts"] = time.time()
    _guardar_progreso(progreso)


# Si "automatico_corriendo" quedó en True pero hace más de esto que no
# se refresca, es más probable que el proceso se haya cortado de golpe
# (cerraste la terminal, apagaste la compu) que que siga corriendo de
# verdad -- la marca en disco no se entera sola de un corte abrupto.
# Margen generoso: 3 rondas seguidas perdidas, con un piso de 30 min
# para no marcar falsos positivos si una ronda tarda de más (Ollama
# lento, por ejemplo).
_UMBRAL_DESACTUALIZADO_SEG = max(1800, INTERVALO_ENTRE_RONDAS_SEG * 3)


def estado_examen():
    """Para el comando 'estado examen': resumen legible del progreso,
    incluyendo si el examen automático está corriendo en background
    ahora mismo (no solo el progreso del currículo)."""
    progreso = _cargar_progreso()
    lineas = []

    if progreso.get("automatico_corriendo"):
        hace = int(time.time() - progreso.get("automatico_actualizado_ts", time.time()))
        if hace > _UMBRAL_DESACTUALIZADO_SEG:
            lineas.append(
                f"⚪ Parece que el examen automático se cortó sin avisar hace {hace // 60} min "
                f"(¿cerraste la terminal o se apagó la compu?) -- si lo querés seguir, corré "
                f"'iniciar examen automatico' de nuevo."
            )
        else:
            lineas.append(f"🟢 Examen automático corriendo en background (hace {hace}s que sigue activo).")
    else:
        lineas.append("⚪ Examen automático NO está corriendo en background ahora mismo.")

    lineas.append(f"Nivel grupal actual: {progreso['nivel_grupal']}")
    for nombre in dominios.nombres_de_dominios():
        info = progreso["dominios"][nombre]
        marca = "✅ listo" if info["listo"] else f"racha {info['racha']}/{UMBRAL_RACHA}"
        lineas.append(f"  • {nombre}: {marca}")
    return "\n".join(lineas)


# --------------------------------------------------------------------
# PIEZA 4: tácticas -- cada una arma el prompt para UNA táctica
# --------------------------------------------------------------------

def _prompt_completar_oracion(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español, típica de un usuario hablándole a un asistente "
        f"virtual, cuya intención clara sea \"{tema}\". La frase debe sonar natural y "
        f"NO debe estar completa del todo -- que falte la última palabra clave, como si "
        f"la persona la hubiera tipeado a medias. Responde con SOLO esa frase, sin comillas, "
        f"sin numerar, sin explicación."
    )


def _prompt_texto_largo(intencion_ejemplo, tema):
    return (
        f"Escribí UN párrafo corto en español (2-3 oraciones), con contexto que no viene "
        f"al caso mezclado adentro (charla casual, un comentario random), pero que en algún "
        f"punto deja clara la intención de \"{tema}\". Responde con SOLO ese párrafo, sin "
        f"comillas, sin numerar, sin explicación."
    )


def _prompt_frase_ambigua(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español que PODRÍA interpretarse de dos formas distintas, "
        f"pero que en contexto normal la interpretación correcta es \"{tema}\". Tiene que "
        f"sonar ambigua a propósito. Responde con SOLO esa frase, sin comillas, sin numerar, "
        f"sin explicación."
    )


def _prompt_distractor(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español cuya intención real es \"{tema}\", pero que incluya "
        f"una palabra o expresión que normalmente haría pensar en OTRA cosa distinta (un "
        f"distractor a propósito), aunque el sentido final siga siendo \"{tema}\". Responde "
        f"con SOLO esa frase, sin comillas, sin numerar, sin explicación."
    )


def _prompt_ruido_typos(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español con la intención \"{tema}\", pero escrita como se "
        f"tipea rápido de verdad: con 2 o 3 errores de tipeo, sin tildes, quizás sin "
        f"mayúscula inicial. Responde con SOLO esa frase, sin comillas, sin numerar, sin "
        f"explicación."
    )


def _prompt_cambio_dominio(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español que EMPIECE pareciendo que va sobre otro tema "
        f"cualquiera, pero que a mitad de camino cambie y termine siendo claramente sobre "
        f"\"{tema}\" (la intención final, la que importa, es esa). Responde con SOLO esa "
        f"frase, sin comillas, sin numerar, sin explicación."
    )


def _prompt_negacion(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español con la intención \"{tema}\", pero formulada con una "
        f"negación o vuelta de tuerca (ej. en vez de pedirlo directo, decir lo contrario de "
        f"lo que NO querés) de forma que el sentido final siga siendo \"{tema}\". Responde "
        f"con SOLO esa frase, sin comillas, sin numerar, sin explicación."
    )


def _prompt_implicita(intencion_ejemplo, tema):
    return (
        f"Escribí UNA frase en español que NUNCA pida literalmente \"{tema}\" con esas "
        f"palabras, sino que lo insinúe de forma indirecta, de manera que haga falta "
        f"inferir que la intención real es \"{tema}\". Responde con SOLO esa frase, sin "
        f"comillas, sin numerar, sin explicación."
    )


# (nombre, nivel_minimo, funcion_que_arma_el_prompt) -- del doc, de mas
# simple a mas dificil, apiladas (no reemplazadas) al subir de nivel.
TACTICAS = [
    ("completar_oracion", 1, _prompt_completar_oracion),
    ("ruido_typos", 2, _prompt_ruido_typos),
    ("texto_largo_pregunta", 2, _prompt_texto_largo),
    ("frase_ambigua", 3, _prompt_frase_ambigua),
    ("distractor", 3, _prompt_distractor),
    ("cambio_dominio", 4, _prompt_cambio_dominio),
    ("negacion_inversion", 4, _prompt_negacion),
    ("intencion_implicita", 5, _prompt_implicita),
]


def tacticas_para_nivel(nivel):
    return [t for t in TACTICAS if t[1] <= nivel]


# --------------------------------------------------------------------
# PIEZA 3: generar el ejercicio y rendir el examen
# --------------------------------------------------------------------

_PALABRA_POR_INTENCION = {
    # Nombre en lenguaje natural de cada intención, para que el prompt
    # a Ollama tenga sentido en español (en vez del identificador crudo).
    "hora": "preguntar la hora", "fecha": "preguntar la fecha",
    "ayuda": "pedir ayuda sobre qué puede hacer el asistente",
    "ayuda_categoria": "pedir ayuda sobre una función puntual del asistente",
    "buscar": "buscar algo en internet", "abrir": "abrir una página o programa",
    "modificar_codigo": "pedirle al asistente que modifique su propio código",
    "saludo": "saludar", "presentacion": "preguntarle al asistente quién es",
    "conversar": "hacer una pregunta general para que el asistente responda",
    "recordar": "pedirle al asistente que recuerde un dato personal",
    "mostrar_memoria": "preguntar qué recuerda el asistente",
    "editar_memoria": "pedir que corrija algo que recuerda mal",
    "crear_recordatorio": "pedir que cree un recordatorio",
    "mostrar_recordatorios": "preguntar qué recordatorios hay pendientes",
    "completar_recordatorio": "avisar que ya se cumplió un recordatorio",
    "eliminar_recordatorio": "pedir que borre un recordatorio",
}


def _limpiar_frase(texto):
    """Primera línea no vacía de la respuesta de Ollama, sin comillas
    ni numeración -- un ejercicio es UNA sola frase, no una lista."""
    for linea in (texto or "").strip().splitlines():
        limpia = linea.strip().strip('"').strip("'").strip()
        limpia = limpia.lstrip("0123456789.-) ").strip()
        if limpia:
            return limpia
    return ""


# Fragmentos que aparecen en TODOS los prompts de _prompt_*() de arriba.
# Si la respuesta de Ollama los contiene, no generó una frase de
# ejemplo -- repitió (total o parcialmente) la instrucción. Aceptar
# eso como ejercicio válido contaminaría conocimiento.json con texto
# que no es una frase de usuario real (ver caso real: el examen de
# 'editar_memoria' devolvió literalmente el prompt como "frase").
_MARCAS_ECO_DEL_PROMPT = (
    "responde con solo", "sin comillas", "sin numerar", "sin explicacion",
    "escribi una frase", "escribi un parrafo", "la intencion clara sea",
    "tipica de un usuario",
)


def _es_eco_del_prompt(frase):
    frase_norm = _normalizar_como_aprendizaje(frase)
    return any(marca in frase_norm for marca in _MARCAS_ECO_DEL_PROMPT)


# Una frase/párrafo de ejercicio real (incluso la táctica "texto largo",
# que pide 2-3 oraciones) no debería superar esto. Los prompts en sí
# miden entre 294 y 405 caracteres (ver TACTICAS) -- si la respuesta se
# les acerca, es mucho más probable que sea un eco que un ejercicio real.
_LARGO_MAXIMO_RAZONABLE = 260


def _conteo_por_intencion(dominio):
    """Cuántos ejemplos con embedding tiene HOY cada intención de
    `dominio` en conocimiento.json."""
    from core.IA.aprendizaje import cargar
    conteo = {intencion: 0 for intencion in dominios.intenciones_de(dominio)}
    for d in cargar():
        if not d.get("embedding"):
            continue
        accion = d.get("accion")
        if accion in conteo:
            conteo[accion] += 1
    return conteo


def _elegir_intencion_a_examinar(dominio):
    """
    Prioriza la intención con MENOS ejemplos dentro de `dominio` (empate:
    al azar entre las más flacas), en vez de elegir uniforme al azar
    entre todas. Con selección uniforme, cubrir con MIN_EJEMPLOS_POR_CLASE
    ejemplos cada intención de un dominio con varias clases tarda mucho
    más de lo necesario (problema del "coleccionista de figuritas": sigue
    repitiendo por azar las que ya están cubiertas). Priorizando la más
    floja, cada ejercicio ataca directo el hueco más grande.
    """
    conteo = _conteo_por_intencion(dominio)
    if not conteo:
        return None
    minimo = min(conteo.values())
    candidatas = [intencion for intencion, n in conteo.items() if n == minimo]
    return random.choice(candidatas)


def generar_ejercicio(dominio, nivel):
    """
    Arma UN ejercicio: elige la intención más floja dentro de `dominio`
    (ver _elegir_intencion_a_examinar) y una táctica habilitada para
    `nivel`, le pide a Ollama la frase, y devuelve
    {"frase", "intencion_correcta", "dominio", "tactica", "nivel"} --
    o None si Ollama no devolvió nada usable.
    """
    from core.IA.ollamaIA import conversar

    intencion = _elegir_intencion_a_examinar(dominio)
    if intencion is None:
        return None
    tema = _PALABRA_POR_INTENCION.get(intencion, intencion.replace("_", " "))

    tacticas_disponibles = tacticas_para_nivel(nivel)
    nombre_tactica, _, armar_prompt = random.choice(tacticas_disponibles)

    prompt = armar_prompt(intencion, tema)
    respuesta = conversar(prompt, num_predict=120, temperature=0.9)
    frase = _limpiar_frase(respuesta)
    if not frase:
        return None
    if len(frase) > _LARGO_MAXIMO_RAZONABLE or _es_eco_del_prompt(frase):
        # Ollama no generó un ejercicio -- devolvió (parte de) el propio
        # prompt. Descartamos en vez de usar esto como ejemplo: no es
        # una frase de usuario real, y si se acepta como fallo, se
        # guardaría como dato de entrenamiento contaminado.
        return None

    return {
        "frase": frase, "intencion_correcta": intencion,
        "dominio": dominio, "tactica": nombre_tactica, "nivel": nivel,
    }


def _normalizar_como_aprendizaje(texto):
    """
    Mismo criterio que aprendizaje._normalizar(): minúsculas + sin
    tildes. aprendizaje.py calcula el embedding de cada dato guardado
    sobre el texto YA normalizado así -- si acá no lo normalizamos
    igual, el embedding de examen no queda comparable con los que ya
    existen en conocimiento.json.
    """
    import unicodedata
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def _obtener_embedding_por_defecto(texto):
    """core.IA.embeddings.calcular_embedding -- la misma función que usa
    aprendizaje.py para calcular el embedding de cada dato que aprende,
    así los embeddings de examen quedan en el mismo espacio que los del
    entrenamiento real."""
    from core.IA.embeddings import calcular_embedding
    return calcular_embedding(_normalizar_como_aprendizaje(texto))


def rendir_examen(dominio=None, cantidad=CANTIDAD_POR_RONDA, obtener_embedding=None, silencioso=False):
    """
    Ronda de examen sobre UN dominio (el más atrasado si no se
    especifica). Por cada ejercicio: genera la frase con intención
    conocida, le pide al clasificador jerárquico que la clasifique,
    compara, y si falla la refuerza al toque (aprendizaje.aprender()) --
    sin pedir aprobación, un fallo de examen no tiene riesgo.

    Actualiza y guarda el progreso (racha/nivel) al final.
    Devuelve un resumen: {"dominio", "nivel", "aciertos", "total", "detalle": [...]}.
    """
    obtener_embedding = obtener_embedding or _obtener_embedding_por_defecto
    progreso = _cargar_progreso()
    dominio = dominio or elegir_dominio_a_examinar(progreso)
    nivel = progreso["nivel_grupal"]

    if not silencioso:
        print(f"Arché (examen): rindo examen de '{dominio}', nivel {nivel}...")

    detalle = []
    for i in range(cantidad):
        ejercicio = generar_ejercicio(dominio, nivel)
        if ejercicio is None:
            continue

        try:
            embedding = obtener_embedding(ejercicio["frase"])
        except RuntimeError as e:
            if not silencioso:
                print(f"Arché (examen): {e}")
            break  # sin forma de embeber, no tiene sentido seguir intentando esta ronda

        accion_predicha, confianza, dominio_predicho = cj.predecir_jerarquico(embedding)
        acierto = accion_predicha == ejercicio["intencion_correcta"]
        registrar_resultado(progreso, dominio, acierto)

        if not acierto:
            try:
                from core.IA import aprendizaje
                aprendizaje.aprender(
                    ejercicio["frase"], ejercicio["intencion_correcta"], "",
                    fuente="examen",
                )
            except Exception as e:
                if not silencioso:
                    print(f"Arché (examen): no pude reforzar el fallo automáticamente ({e}).")

        detalle.append({**ejercicio, "predicho": accion_predicha, "acierto": acierto})
        if not silencioso:
            marca = "✅" if acierto else "❌"
            print(f"  {marca} [{ejercicio['tactica']}] «{ejercicio['frase']}» "
                  f"-- esperado: {ejercicio['intencion_correcta']}, predicho: {accion_predicha}")

        time.sleep(PAUSA_ENTRE_EJERCICIOS_SEG)

    _guardar_progreso(progreso)

    aciertos = sum(1 for d in detalle if d["acierto"])
    if not silencioso:
        info_dom = progreso["dominios"][dominio]
        estado = "✅ ¡listo para subir de nivel!" if info_dom["listo"] else f"racha {info_dom['racha']}/{UMBRAL_RACHA}"
        print(f"Arché (examen): {aciertos}/{len(detalle)} en '{dominio}' -- {estado}.")

    return {"dominio": dominio, "nivel": nivel, "aciertos": aciertos, "total": len(detalle), "detalle": detalle}


# --------------------------------------------------------------------
# Orquestación en background (mismo patrón que estudio.py)
# --------------------------------------------------------------------

def iniciar_examen_en_background(
    retraso_inicial_seg=20,
    intervalo_entre_rondas_seg=INTERVALO_ENTRE_RONDAS_SEG,
    detener_evento=None,
    avisar=None,
):
    """
    Corre rendir_examen() en loop, en un hilo aparte, mientras Arché
    esté abierta -- mismo patrón que iniciar_estudio_en_background() y
    iniciar_autorevision_en_background(). Si un dominio queda "listo"
    en esta ronda y avisar() está definido, lo cuenta.
    """
    def _tarea():
        time.sleep(retraso_inicial_seg)
        while detener_evento is None or not detener_evento.is_set():
            # Se refresca en CADA ronda (no solo una vez al arrancar) para
            # que "hace Ns que sigue activo" en estado_examen() refleje
            # actividad real, y para que un cierre abrupto (cerrar la
            # terminal, apagar la compu) se note como desactualizado en
            # vez de mostrar "corriendo" para siempre.
            _marcar_automatico(True)
            try:
                resultado = rendir_examen(silencioso=True)
                if avisar is not None and resultado["total"] > 0:
                    avisar(
                        f"Rendí examen de '{resultado['dominio']}': "
                        f"{resultado['aciertos']}/{resultado['total']} aciertos. "
                        f"Decime 'estado examen' si querés el detalle."
                    )
            except Exception:
                pass  # un error acá no debe tirar abajo el hilo de fondo

            for _ in range(intervalo_entre_rondas_seg):
                if detener_evento is not None and detener_evento.is_set():
                    break
                time.sleep(1)

        _marcar_automatico(False)

    hilo = threading.Thread(target=_tarea, daemon=True)
    hilo.start()
    return hilo