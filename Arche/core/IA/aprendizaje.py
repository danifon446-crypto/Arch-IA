import json
import os
import re
import threading
import unicodedata
from difflib import SequenceMatcher

BASE = os.path.dirname(__file__)
ARCHIVO = os.path.join(BASE, "conocimiento.json")

_lock = threading.Lock()  # protege conocimiento.json de escrituras concurrentes (ej. modo estudio en background)

UMBRAL_SIMILITUD = 0.85  # qué tan parecida debe ser una frase para aceptarla por similitud (caracteres)
UMBRAL_SEMANTICO = 0.78  # qué tan parecida debe ser en SIGNIFICADO para aceptarla (embeddings)

ARCHIVO_META = os.path.join(BASE, "meta.json")
UMBRAL_REENTRENO = 5  # cada cuántos comandos nuevos se reentrena el clasificador automáticamente


def _reentrenar_si_corresponde():
    """
    Lleva la cuenta de comandos nuevos aprendidos desde el último
    reentrenamiento. Al llegar a UMBRAL_REENTRENO, reentrena el
    clasificador solo (en silencio si no hay datos suficientes todavía,
    para no llenar la consola de avisos en cada comando).

    Reentrena TANTO el clasificador de siempre (clasificador.py) COMO
    el jerárquico (clasificador_jerarquico.py, si está instalado) --
    así el jerárquico se mantiene al día automáticamente, sin que haga
    falta acordarse de correr 'entrenar jerarquico' a mano cada vez.
    Un fallo al entrenar el jerárquico (ej. todavía no tiene datos
    suficientes en algún dominio) no afecta al reentrenamiento normal.
    """
    meta = {"pendientes": 0}
    if os.path.exists(ARCHIVO_META):
        try:
            with open(ARCHIVO_META, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    meta["pendientes"] = meta.get("pendientes", 0) + 1

    if meta["pendientes"] >= UMBRAL_REENTRENO:
        try:
            from core.IA.clasificador import entrenar
            entrenado = entrenar(silencioso=True)
            if entrenado:
                meta["pendientes"] = 0
            # Si no había datos suficientes, no reseteamos el contador:
            # así lo vuelve a intentar en el próximo comando aprendido
            # (más barato que definir un segundo umbral independiente).
        except Exception as e:
            print(f"Arché: No se pudo reentrenar el clasificador ({e}).")

        try:
            from core.IA.clasificador_jerarquico import entrenar_jerarquico
            entrenar_jerarquico(silencioso=True)
        except ImportError:
            pass  # el clasificador jerárquico es opcional, todavía puede no estar instalado
        except Exception as e:
            print(f"Arché: No se pudo reentrenar el clasificador jerárquico ({e}).")
    else:
        with open(ARCHIVO_META, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        return

    with open(ARCHIVO_META, "w", encoding="utf-8") as f:
        json.dump(meta, f)


# ----------------------------------------------------------------------
# Normalización de texto (se usa en todo el módulo)
# ----------------------------------------------------------------------
def _normalizar(texto):
    """minúsculas + sin tildes, para comparar de forma consistente."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto


# ----------------------------------------------------------------------
# Persistencia (igual que antes, sin cambios de comportamiento)
# ----------------------------------------------------------------------
def cargar():

    if not os.path.exists(ARCHIVO):
        return []

    try:

        with open(ARCHIVO, "r", encoding="utf-8") as archivo:
            return json.load(archivo)

    except:
        return []


def guardar(datos):

    with open(ARCHIVO, "w", encoding="utf-8") as archivo:

        json.dump(
            datos,
            archivo,
            indent=4,
            ensure_ascii=False
        )


# ----------------------------------------------------------------------
# Generalización por plantillas
# ----------------------------------------------------------------------
def _extraer_template(pregunta_norm, contenido_norm):
    """
    Dada la pregunta normalizada y el contenido (parte variable), genera
    un patrón tipo "abre {X}". Devuelve None si no se puede generalizar
    (ej: intenciones sin contenido variable, como "hora" o "saludo").
    """
    if not contenido_norm or contenido_norm not in pregunta_norm:
        return None

    return pregunta_norm.replace(contenido_norm, "{X}", 1)


def _template_a_regex(template):
    """Convierte "abre {X}" en un regex que capture la parte variable."""
    partes = template.split("{X}")
    partes_escapadas = [re.escape(p) for p in partes]
    patron = "(.+)".join(partes_escapadas)
    return f"^{patron}$"


def _cobertura(pregunta_norm, parte):
    """Qué tan presente está 'parte' (fragmento fijo) dentro de la pregunta."""
    if not parte:
        return 0.0
    m = SequenceMatcher(None, pregunta_norm, parte)
    bloque = m.find_longest_match(0, len(pregunta_norm), 0, len(parte))
    return bloque.size / len(parte)


# Intenciones donde el "contenido" no varía de forma significativa entre
# preguntas (o directamente no se usa) -> es seguro reutilizarlo aunque
# no se pueda extraer de la pregunta actual.
ACCIONES_SIN_CONTENIDO_VARIABLE = {
    "saludo", "presentacion", "hora", "fecha", "ayuda",
    "mostrar_memoria", "mostrar_recordatorios",
}


def _contenido_seguro(pregunta_norm, dato):
    """
    Decide qué contenido devolver para un 'dato' candidato, SIN asumir
    que el contenido guardado de la vieja pregunta sirve para la actual.

    - Si el template tiene parte variable ({X}), se intenta extraer el
      contenido de LA PREGUNTA ACTUAL (no la vieja) usando esa estructura.
    - Si la acción no depende de contenido variable, se reutiliza el
      contenido guardado (es seguro, no cambia el significado).
    - En cualquier otro caso (contenido "inventado"/resumido por Ollama,
      sin estructura extraíble) se devuelve None: NO se debe confiar en
      ese contenido para esta pregunta nueva, aunque la pregunta se
      parezca a la que se aprendió.
    """
    template = dato.get("template", "")

    if "{X}" in template:
        regex = dato.get("regex") or _template_a_regex(template)
        match = re.match(regex, pregunta_norm)
        if match and match.groups():
            return match.group(1).strip()
        return None

    if dato["accion"] in ACCIONES_SIN_CONTENIDO_VARIABLE:
        return dato["contenido"]

    return None


# ----------------------------------------------------------------------
# Aprender (misma firma de siempre, ahora guarda también template/regex)
# ----------------------------------------------------------------------
def aprender(pregunta, accion, contenido, fuente="ollama"):

    pregunta_norm = _normalizar(pregunta)
    contenido_norm = _normalizar(contenido) if contenido else ""

    template = _extraer_template(pregunta_norm, contenido_norm)
    if template is None:
        # No generaliza (ej. "hora", "saludo") -> se guarda como plantilla literal
        template = pregunta_norm

    regex = _template_a_regex(template)

    # Embedding semántico (capa 3). Si la librería no está instalada o falla
    # por cualquier razón, seguimos sin él: las capas 1 y 2 igual funcionan.
    embedding = None
    try:
        from core.IA.embeddings import calcular_embedding
        embedding = calcular_embedding(pregunta_norm)
    except Exception as e:
        print(f"Arché: No se pudo calcular el embedding ({e}). Sigo sin él.")

    with _lock:
        datos = cargar()

        for dato in datos:

            if dato["pregunta"] == pregunta_norm:

                dato["accion"] = accion
                dato["contenido"] = contenido
                dato["fuente"] = fuente
                dato["template"] = template
                dato["regex"] = regex
                if embedding is not None:
                    dato["embedding"] = embedding

                guardar(datos)

                _reentrenar_si_corresponde()
                return

        nuevo_dato = {
            "pregunta": pregunta_norm,
            "accion": accion,
            "contenido": contenido,
            "fuente": fuente,
            "template": template,
            "regex": regex,
        }
        if embedding is not None:
            nuevo_dato["embedding"] = embedding

        datos.append(nuevo_dato)

        guardar(datos)

    _reentrenar_si_corresponde()


# ----------------------------------------------------------------------
# Resolver: reemplaza la comparación exacta por matching de plantillas
# ----------------------------------------------------------------------
def resolver(pregunta, umbral_similitud=UMBRAL_SIMILITUD):
    """
    Intenta resolver la pregunta usando lo aprendido hasta ahora.

    1. Match exacto por regex de plantilla (rápido y preciso). Cubre
       tanto frases literales ya vistas como variaciones de su parte
       variable (ej. "abre spotify" resuelve con el patrón de "abre youtube").
    2. Si no hay match exacto, similitud aproximada sobre la parte fija
       (tolera pequeños errores de tipeo en la parte fija).

    Devuelve {"accion":..., "contenido":...} o None si no hay nada
    suficientemente parecido -> en ese caso se debe consultar a Ollama.
    """
    pregunta_norm = _normalizar(pregunta)
    datos = cargar()

    # --- Paso 1: match exacto por regex ---
    for dato in datos:
        regex = dato.get("regex")
        if not regex:
            # Datos viejos guardados antes de este cambio, sin template/regex
            if dato["pregunta"] == pregunta_norm:
                return {"accion": dato["accion"], "contenido": dato["contenido"]}
            continue

        match = re.match(regex, pregunta_norm)
        if match:
            contenido = match.group(1).strip() if match.groups() else dato["contenido"]
            return {"accion": dato["accion"], "contenido": contenido}

    # --- Paso 2: similitud aproximada ---
    mejor_score = 0.0
    mejor_resultado = None

    for dato in datos:
        template = dato.get("template")
        if not template:
            continue

        partes_fijas = [p for p in template.split("{X}") if p.strip()]
        if not partes_fijas:
            continue

        score = max(_cobertura(pregunta_norm, parte) for parte in partes_fijas)

        if score > mejor_score:
            contenido_seguro = _contenido_seguro(pregunta_norm, dato)
            if contenido_seguro is None:
                # No podemos confiar en el contenido de este candidato
                # para la pregunta actual -> no lo usamos como resultado,
                # aunque la parte fija se parezca mucho.
                continue
            mejor_score = score
            mejor_resultado = {"accion": dato["accion"], "contenido": contenido_seguro}

    if mejor_score >= umbral_similitud:
        return mejor_resultado

    # --- Paso 3: similitud semántica (embeddings) ---
    # Entiende significado, no solo caracteres. Cubre sinónimos y
    # reformulaciones que las capas 1 y 2 no detectan
    # (ej. "prende spotify" ~ "abre spotify").
    resultado_semantico = _resolver_semantico(pregunta_norm, datos)
    if resultado_semantico is not None:
        return resultado_semantico

    return None


def _predecir_con_clasificador(vector_pregunta):
    """
    Le pide al clasificador su opinión sobre `vector_pregunta`, usando
    PRIMERO el jerárquico (clasificador_jerarquico.py, dominio + red
    de intención) y, si no está instalado o todavía no tiene un modelo
    entrenado para el dominio que corresponda, cae automáticamente al
    clasificador de siempre (clasificador.py) -- exactamente el mismo
    comportamiento que había antes de que existiera el jerárquico.

    Devuelve (accion_predicha, confianza). (None, 0.0) si ninguno de
    los dos pudo opinar.
    """
    try:
        from core.IA.clasificador_jerarquico import predecir_jerarquico
        accion, confianza, _dominio = predecir_jerarquico(vector_pregunta)
        if accion is not None:
            return accion, confianza
    except ImportError:
        pass  # el jerárquico es opcional, todavía puede no estar instalado
    except Exception:
        pass  # cualquier otro problema del jerárquico: no debe tapar al de siempre

    try:
        from core.IA.clasificador import predecir
        return predecir(vector_pregunta)
    except Exception:
        return None, 0.0


def _resolver_semantico(pregunta_norm, datos, umbral_semantico=UMBRAL_SEMANTICO):
    try:
        from core.IA.embeddings import calcular_embedding, similitud_coseno
    except Exception:
        # Librería no instalada o modelo no disponible -> esta capa se
        # salta silenciosamente, el resto de Arché sigue funcionando.
        return None

    entradas_con_embedding = [d for d in datos if d.get("embedding")]
    if not entradas_con_embedding:
        return None

    try:
        vector_pregunta = calcular_embedding(pregunta_norm)
    except Exception as e:
        print(f"Arché: No se pudo calcular el embedding de la pregunta ({e}).")
        return None

    mejor_score = 0.0
    mejor_resultado = None
    mejor_dato = None

    for dato in entradas_con_embedding:
        score = similitud_coseno(vector_pregunta, dato["embedding"])
        if score > mejor_score:
            contenido_seguro = _contenido_seguro(pregunta_norm, dato)
            if contenido_seguro is None:
                # La pregunta se parece en SIGNIFICADO, pero no podemos
                # confiar en que el contenido guardado sirva para esta
                # pregunta nueva (ej. "buscar"/"conversar" con contenido
                # resumido por Ollama, no extraíble). No lo usamos.
                continue
            mejor_score = score
            mejor_dato = dato
            mejor_resultado = {"accion": dato["accion"], "contenido": contenido_seguro}

    if mejor_score >= umbral_semantico:
        return mejor_resultado

    # --- Rescate por clasificador (paso 3.5) ---
    # Caso límite: el vecino más cercano no llegó al umbral, pero está
    # razonablemente cerca. Le preguntamos al clasificador entrenado
    # (jerárquico si está disponible, si no el de siempre) su opinión;
    # si coincide en la intención con confianza suficiente, aceptamos
    # el resultado del vecino más cercano de todas formas (el
    # clasificador no puede aportar el "contenido", solo confirma que
    # la intención es plausible; el contenido ya pasó por el mismo
    # filtro de _contenido_seguro de arriba).
    margen_rescate = 0.08
    confianza_minima_rescate = 0.6

    if mejor_resultado and mejor_score >= (umbral_semantico - margen_rescate):
        accion_predicha, confianza = _predecir_con_clasificador(vector_pregunta)
        if accion_predicha == mejor_resultado["accion"] and confianza >= confianza_minima_rescate:
            return mejor_resultado

    # --- Resolución autónoma por clasificador (paso 4) ---
    # A diferencia del rescate de arriba, esto NO necesita ningún vecino
    # parecido -- cubre una frase genuinamente nueva, distinta a todo lo
    # ya aprendido. Solo se acepta con confianza ALTA (más exigente que
    # el rescate: ahí el clasificador nunca decide solo, acá si), porque
    # sin un vecino no hay plantilla de la que extraer el "contenido" --
    # se usa la frase normalizada tal cual. Para intenciones que ignoran
    # "contenido" (saludo, hora, mostrar_memoria...) esto es exactamente
    # tan bueno como una respuesta de Ollama. Para las que sí lo usan
    # (crear_recordatorio, buscar...), el contenido queda menos prolijo
    # que uno extraído a mano, pero sigue siendo funcional -- y evita
    # caer a Ollama para algo que el clasificador ya reconoce bien.
    confianza_minima_autonoma = 0.85

    accion_predicha, confianza = _predecir_con_clasificador(vector_pregunta)
    if accion_predicha is not None and confianza >= confianza_minima_autonoma:
        return {"accion": accion_predicha, "contenido": pregunta_norm}

    return None