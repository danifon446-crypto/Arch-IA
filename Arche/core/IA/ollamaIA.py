import json
import ollama
from core.IA.telemetria import medir

# --------------------------------------------------------------------
# UN SOLO MODELO para comprender() y conversar().
# Esto evita el "swap" (descargar/cargar modelo distinto en cada turno),
# que es la causa más probable de la lentitud que estás viendo.
#
# Ajusta el tag según lo que tengas descargado (`ollama list` para ver).
# Tags livianos recomendados: "qwen2.5:1.5b", "qwen2.5:0.5b", "phi3:mini",
# "gemma2:2b". Evita usar el nombre sin tag (ej. "qwen2.5" a secas),
# porque eso baja la versión "latest", que puede ser la de 7B.
# --------------------------------------------------------------------
MODELO = "arche-lora"

# Modelo SEPARADO, especializado en codigo, para TODO lo que escribe,
# revisa o verifica codigo (proponer_cambio_codigo.py, autorevision.py,
# verificar_cambio.py). arche-lora es un modelo chico fine-tuneado para
# conversar/clasificar con la personalidad de Arche -- mostro
# comportamiento rigido/sobreajustado para generar codigo (devolvia la
# misma respuesta sin importar el prompt, ni siquiera reaccionaba a
# retroalimentacion de errores explicita).
#
# Antes era "qwen2.5-coder:1.5b" (1.5B parametros): demasiado chico para
# entender el codigo que tenia que modificar. "qwen3-coder:30b" es mucho
# mas potente pero necesita ~19 GB de memoria y en esta PC el servidor de
# Ollama se caia al cargarlo (GGML_ASSERT mem_buffer != NULL). Se usa
# "qwen2.5-coder:7b" (~5 GB): mucho mejor que el de 1.5B y si entra.
# Si proponer_cambio_codigo avisa que el modelo de codigo no respondio,
# baja a "qwen2.5-coder:3b". Para probar otro, cambia solo esta linea.
MODELO_CODIGO = "qwen2.5-coder:7b"

# keep_alive mantiene el modelo cargado en memoria entre llamadas.
# Con "30m" evitas que se descargue si pasan más de 5 min (default de Ollama)
# entre un comando y otro.
KEEP_ALIVE = "30m"

# El modelo de codigo es grande: no tiene sentido dejarlo cargado 30 min
# despues de cada pedido (le quitaria memoria al modelo conversacional).
KEEP_ALIVE_CODIGO = "5m"

# --------------------------------------------------------------------
# HISTORIAL DE CONVERSACIÓN (memoria de corto plazo, dentro de una
# misma sesión de Arché abierta). Antes conversar() mandaba SOLO la
# pregunta suelta a Ollama -- sin esto, Arché no podía referirse a
# nada de lo que se habló un mensaje antes. Es opt-in (usar_historial)
# para no afectar a quienes usan conversar() para otra cosa que no es
# charla real (estudio.py arma preguntas de examen, generar_changelog.py
# redacta un changelog -- ninguno de los dos debe arrastrar charla vieja).
# --------------------------------------------------------------------
_historial_conversacion = []
LIMITE_HISTORIAL_MENSAJES = 20  # ~10 intercambios ida y vuelta


def hay_historial_activo():
    return len(_historial_conversacion) > 0


def reiniciar_historial():
    """Para 'olvidate de lo que hablamos' / arrancar charla nueva a propósito."""
    _historial_conversacion.clear()


def _recortar_historial():
    exceso = len(_historial_conversacion) - LIMITE_HISTORIAL_MENSAJES
    if exceso > 0:
        del _historial_conversacion[:exceso]


def razonar_y_responder(pregunta, num_predict=400, temperature=0.7,
                         usar_historial=False, usar_memoria=False,
                         mostrar_razonamiento=False):
    """
    Para preguntas que lo ameritan (ver necesita_razonamiento_profundo):
    en vez de contestar de un tiro, primero le pide al modelo un
    borrador de razonamiento paso a paso (sin mostrárselo a la
    persona), y RECIÉN AHÍ le pide la respuesta final usando ese
    borrador como base. Esto es más lento (dos llamadas a Ollama en
    vez de una), así que solo tiene sentido para preguntas que
    realmente lo necesitan -- no para un "hola" o un "gracias".

    mostrar_razonamiento=True devuelve (respuesta, razonamiento) en
    vez de solo la respuesta, por si querés mostrar o loguear el
    borrador interno.
    """
    contexto_memoria = ""
    if usar_memoria:
        from core.memoria import resumen_para_contexto
        contexto_memoria = resumen_para_contexto()

    instrucciones_borrador = (
        "Eres Arché. Antes de responderle a la persona, pensá el "
        "problema paso a paso, en borrador -- identificá qué te están "
        "preguntando en realidad, qué datos o supuestos hacen falta, "
        "y cómo llegarías a una respuesta sólida. Esto NO se le "
        "muestra a la persona todavía, así que no le hables "
        "directamente a ella ni saludes -- es solo tu razonamiento "
        "interno, en unas pocas líneas."
    )
    if contexto_memoria:
        instrucciones_borrador += f"\n\nDatos que ya sabés de la persona: {contexto_memoria}"

    mensajes_borrador = [{"role": "system", "content": instrucciones_borrador}]
    if usar_historial:
        mensajes_borrador.extend(_historial_conversacion)
    mensajes_borrador.append({"role": "user", "content": pregunta})

    with medir("ollama_razonar_borrador"):
        try:
            respuesta_borrador = ollama.chat(
                model=MODELO,
                keep_alive=KEEP_ALIVE,
                messages=mensajes_borrador,
                options={"temperature": 0.3, "num_predict": 250},  # menos "creatividad" para el borrador, es análisis, no charla
            )
        except Exception as e:
            print("Error Ollama:", e)
            mensaje_error = "No puedo conectarme a Ollama ahora mismo. Fijate que esté corriendo (ollama serve)."
            return (mensaje_error, "") if mostrar_razonamiento else mensaje_error
    razonamiento = respuesta_borrador["message"]["content"]

    instrucciones_final = (
        "Eres Arché, un asistente inteligente. Ya pensaste este problema "
        "en borrador (te lo paso abajo) -- ahora respondele a la persona "
        "de forma clara, natural y directa, como en una charla real. "
        "NO le muestres el borrador ni digas frases como 'pensando en "
        "esto' o 'mi análisis fue' -- solo dale la respuesta final, ya "
        "elaborada, con la calidad de haberlo pensado bien."
        f"\n\nTu borrador de razonamiento:\n{razonamiento}"
    )
    if contexto_memoria:
        instrucciones_final += (
            f"\n\nDatos que ya sabés de la persona -- usalos con "
            f"naturalidad si vienen al caso: {contexto_memoria}"
        )

    mensajes_final = [{"role": "system", "content": instrucciones_final}]
    if usar_historial:
        mensajes_final.extend(_historial_conversacion)
    mensajes_final.append({"role": "user", "content": pregunta})

    with medir("ollama_razonar_final"):
        try:
            respuesta_final = ollama.chat(
                model=MODELO,
                keep_alive=KEEP_ALIVE,
                messages=mensajes_final,
                options={"temperature": temperature, "num_predict": num_predict},
            )
        except Exception as e:
            print("Error Ollama:", e)
            mensaje_error = "No puedo conectarme a Ollama ahora mismo. Fijate que esté corriendo (ollama serve)."
            return (mensaje_error, razonamiento) if mostrar_razonamiento else mensaje_error
    texto = respuesta_final["message"]["content"]

    if usar_historial:
        _historial_conversacion.append({"role": "user", "content": pregunta})
        _historial_conversacion.append({"role": "assistant", "content": texto})
        _recortar_historial()

    if mostrar_razonamiento:
        return texto, razonamiento
    return texto


_PISTAS_RAZONAMIENTO_PROFUNDO = (
    "por qué", "por que", "cómo puedo", "como puedo", "cuál es mejor",
    "cual es mejor", "qué me conviene", "que me conviene", "deberia",
    "debería", "compará", "compara", "diferencia entre", "ventajas y desventajas",
    "pros y contras", "analiza", "analizá", "razoná", "razona", "pensá bien",
    "piensa bien", "qué opinas", "que opinas", "recomendame", "recomiéndame",
)


def necesita_razonamiento_profundo(texto):
    """
    Heurística simple: ¿esta pregunta se beneficia de pensarla en dos
    pasos, o alcanza con una respuesta directa? Mirá el largo (una
    pregunta de una sola palabra o muy corta casi nunca lo necesita) y
    palabras que suelen aparecer en preguntas de comparación, opinión,
    consejo o "por qué" -- las que más se benefician de un borrador
    previo en vez de improvisar directo.
    """
    texto_norm = (texto or "").lower().strip()
    if len(texto_norm) < 12:
        return False
    return any(pista in texto_norm for pista in _PISTAS_RAZONAMIENTO_PROFUNDO)


def comprender(comando):

    prompt = f"""
Eres el cerebro de un asistente virtual llamado Arché.

Tu función es analizar los comandos del usuario y clasificarlos en una intención.
No debes responder al usuario directamente, solamente debes identificar qué quiere hacer.

REGLAS IMPORTANTES:

1. Tu respuesta debe ser SIEMPRE un JSON válido.
2. No escribas explicaciones, textos adicionales ni comentarios.
3. No inventes nuevas intenciones.
4. Usa únicamente las intenciones permitidas.
5. Si no entiendes el comando, usa "desconocido".
6. El campo "contenido" debe contener únicamente la información necesaria para ejecutar la acción.
7. Si la intención no necesita información adicional, deja "contenido" vacío.

INTENCIONES DISPONIBLES:

saludo
presentacion
hora
fecha
ayuda
buscar
abrir
recordar
mostrar_memoria
editar_memoria
crear_recordatorio
mostrar_recordatorios
eliminar_recordatorio
modificar_codigo
conversar
desconocido


FORMATO OBLIGATORIO:

{{
"intencion":"nombre",
"contenido":"informacion"
}}


EJEMPLOS:


Usuario: hola
Respuesta:
{{"intencion":"saludo","contenido":"saludo"}}


Usuario: quién eres
Respuesta:
{{"intencion":"presentacion","contenido":"pregunta sobre identidad"}}


Usuario: qué hora es
Respuesta:
{{"intencion":"hora","contenido":"hora actual"}}


Usuario: qué fecha es hoy
Respuesta:
{{"intencion":"fecha","contenido":"fecha actual"}}


Usuario: qué puedes hacer
Respuesta:
{{"intencion":"ayuda","contenido":"funciones del asistente"}}


Usuario: busca inteligencia artificial
Respuesta:
{{"intencion":"buscar","contenido":"inteligencia artificial"}}


Usuario: busca udec
Respuesta:
{{"intencion":"buscar","contenido":"udec"}}


Usuario: busca universidad de cundinamarca
Respuesta:
{{"intencion":"buscar","contenido":"universidad de cundinamarca"}}


Usuario: abre youtube
Respuesta:
{{"intencion":"abrir","contenido":"youtube"}}


Usuario: abre google
Respuesta:
{{"intencion":"abrir","contenido":"google"}}


Usuario: recuerda que mi proyecto es un robot
Respuesta:
{{"intencion":"recordar","contenido":"mi proyecto es un robot"}}


Usuario: qué recuerdas
Respuesta:
{{"intencion":"mostrar_memoria","contenido":"consultar memoria"}}


Usuario: recuérdame estudiar mañana
Respuesta:
{{"intencion":"crear_recordatorio","contenido":"estudiar mañana"}}


Usuario: qué recordatorios tengo
Respuesta:
{{"intencion":"mostrar_recordatorios","contenido":"ver recordatorios"}}


Usuario: elimina mi recordatorio de estudiar
Respuesta:
{{"intencion":"eliminar_recordatorio","contenido":"recordatorio de estudiar"}}


Usuario: cuéntame un chiste
Respuesta:
{{"intencion":"desconocido","contenido":"solicitud no disponible"}}

REGLA IMPORTANTE PARA DIFERENCIAR "ABRIR" Y "BUSCAR":

ABRIR:
Usa "abrir" cuando el usuario quiere entrar directamente a una página, programa o aplicación.

Palabras comunes:
abre, abrir, entra, entrar, visita, ir a, ve a, inicia, ejecuta.

Ejemplos:

Usuario: abre youtube
Respuesta:
{{"intencion":"abrir","contenido":"youtube"}}

Usuario: entra a la página de la universidad de cundinamarca
Respuesta:
{{"intencion":"abrir","contenido":"universidad de cundinamarca"}}

Usuario: abre google
Respuesta:
{{"intencion":"abrir","contenido":"google"}}


BUSCAR:
Usa "buscar" cuando el usuario quiere encontrar información, investigar o consultar algo.

Palabras comunes:
busca, buscar, investiga, averigua, encuentra, información sobre, dime sobre.

Ejemplos:

Usuario: busca universidad de cundinamarca
Respuesta:
{{"intencion":"buscar","contenido":"universidad de cundinamarca"}}

Usuario: busca información sobre robots
Respuesta:
{{"intencion":"buscar","contenido":"robots"}}

Usuario: investiga sobre inteligencia artificial
Respuesta:
{{"intencion":"buscar","contenido":"inteligencia artificial"}}


Si el usuario dice "página de..." o "sitio de..." sin pedir información, interpreta como ABRIR.

Ejemplo:

Usuario: abre la página de la universidad de cundinamarca
Respuesta:
{{"intencion":"abrir","contenido":"universidad de cundinamarca"}}

REGLA IMPORTANTE PARA EL CONTENIDO:

El campo "contenido" debe conservar la información importante del comando del usuario.

No reduzcas demasiado la información.
No elimines detalles técnicos, nombres de tecnologías, componentes, lugares o características importantes.
El contenido debe ser un resumen útil del objetivo del usuario, manteniendo los datos necesarios para ejecutar la acción.

Ejemplos:

Usuario:
busca cómo crear un robot con Arduino, sensores, reconocimiento de voz y visión artificial

Respuesta:
{{"intencion":"buscar","contenido":"crear un robot con Arduino, sensores, reconocimiento de voz y visión artificial"}}


Usuario:
investiga cómo hacer una incubadora automática usando ESP32, sensores de temperatura, humedad y control de motores

Respuesta:
{{"intencion":"buscar","contenido":"hacer una incubadora automática usando ESP32, sensores de temperatura, humedad y control de motores"}}


Usuario:
quiero información sobre inteligencia artificial aplicada a robots autónomos con cámaras y reconocimiento de objetos

Respuesta:
{{"intencion":"buscar","contenido":"inteligencia artificial aplicada a robots autónomos con cámaras y reconocimiento de objetos"}}


No hagas respuestas demasiado generales.

Ejemplo incorrecto:

Usuario:
busca arquitectura para un asistente artificial autónomo con reconocimiento de voz, visión por computadora y memoria

Respuesta incorrecta:
{{"intencion":"buscar","contenido":"asistente artificial"}}


Ejemplo correcto:
{{"intencion":"buscar","contenido":"arquitectura para un asistente artificial autónomo con reconocimiento de voz, visión por computadora y memoria"}}

REGLA IMPORTANTE PARA DIFERENCIAR "BUSCAR" Y "CONVERSAR":

Usa la intención "buscar" SOLAMENTE cuando el usuario quiera que Arché busque información en Internet.

Indicadores de búsqueda:
- busca...
- buscar...
- investiga...
- averigua...
- encuentra información...
- consulta...
- busca en Google...
- busca en Internet...

Usa la intención "conversar" cuando el usuario haga una pregunta, pida una explicación, solicite una opinión, una traducción, una receta, un resumen, una historia o cualquier respuesta que deba ser generada por Arché.

Ejemplos:

Usuario:
¿Cómo hacer arroz?

Respuesta:
{{"intencion":"conversar","contenido":"cómo hacer arroz"}}

Usuario:
¿Cómo hacer arroz? Responde en inglés.

Respuesta:
{{"intencion":"conversar","contenido":"cómo hacer arroz, responder en inglés"}}

Usuario:
Explícame qué es una red neuronal.

Respuesta:
{{"intencion":"conversar","contenido":"qué es una red neuronal"}}

Usuario:
Traduce 'buenos días' al inglés.

Respuesta:
{{"intencion":"conversar","contenido":"traducir 'buenos días' al inglés"}}

Usuario:
Busca cómo hacer arroz.

Respuesta:
{{"intencion":"buscar","contenido":"cómo hacer arroz"}}

Usuario:
Investiga cómo hacer arroz.

Respuesta:
{{"intencion":"buscar","contenido":"cómo hacer arroz"}}

REGLA IMPORTANTE PARA "MODIFICAR_CODIGO":

Usa "modificar_codigo" cuando el usuario te pida a VOS (Arché) que cambies, arregles, mejores, simplifiques, optimices o agregues algo a TU PROPIO código o funcionamiento interno -- no cuando te pida información sobre código en general, ni una explicación de programación.

Indicadores típicos: "arreglá", "arregla", "che arreglá", "corregí", "mejorá", "simplificá", "optimizá", "agregale", "agregá una función", "che, la función de X está mal", "hacé que X funcione mejor", "eso se puede hacer más simple", "sería bueno que X también hiciera Y".

El campo "contenido" debe llevar la instrucción del cambio tal cual la dijo el usuario, sin recortarla.

Ejemplos:

Usuario:
che, arreglá el bug de contar_notas

Respuesta:
{{"intencion":"modificar_codigo","contenido":"arreglá el bug de contar_notas"}}

Usuario:
sería bueno que las notas también cuenten cuántas hay guardadas

Respuesta:
{{"intencion":"modificar_codigo","contenido":"que las notas también cuenten cuántas hay guardadas"}}

Usuario:
la función que busca archivos está muy repetida, se podría simplificar

Respuesta:
{{"intencion":"modificar_codigo","contenido":"la función que busca archivos está muy repetida, se podría simplificar"}}

Usuario:
agregale a recordatorios una opción para contar cuántos hay

Respuesta:
{{"intencion":"modificar_codigo","contenido":"agregale a recordatorios una opción para contar cuántos hay"}}

Diferencia con "conversar": si el usuario pregunta CÓMO se hace algo en general (sin pedirte que vos cambies tu propio código), es "conversar", no "modificar_codigo".

Ejemplo:

Usuario:
¿cómo se cuenta cuántos archivos hay en una carpeta en Python?

Respuesta:
{{"intencion":"conversar","contenido":"cómo se cuenta cuántos archivos hay en una carpeta en Python"}}

IMPORTANTE:
El formato final debe ser exactamente:

{{
"intencion":"nombre_intencion",
"contenido":"informacion"
}}

Ahora analiza el siguiente comando:
Ahora analiza:
{comando}
"""

    try:
        with medir("ollama_comprender"):
            respuesta = ollama.chat(
                model=MODELO,
                format="json",
                keep_alive=KEEP_ALIVE,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                options={
                    # La salida es un JSON corto: no necesita generar mucho.
                    # Esto evita que el modelo se "explaye" y tarde de más.
                    "num_predict": 80,
                    "temperature": 0.2,
                }
            )

        texto = respuesta["message"]["content"].strip()

        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        texto = texto[inicio:fin]  # <- antes esta línea se pisaba y no se usaba

        print("Respuesta de Ollama:")
        print(texto)
        print("-" * 40)

        datos = json.loads(texto)

        # Corregir errores comunes de Ollama
        if "contenido:" in datos:
            datos["contenido"] = datos.pop("contenido:")

        return datos
    except Exception as e:

        print("Error Ollama:", e)

        return {
            "intencion": "desconocido",
            "contenido": ""
        }


def conversar(pregunta, num_predict=300, temperature=0.7, usar_historial=False, usar_memoria=False):
    """
    temperature=0.7 por defecto (charla normal, como siempre).
    Para tareas que necesitan copiar texto exacto (ej. proponer_cambio_codigo.py
    generando fragmentos de código), se puede bajar a 0.1 o menos: menos
    "creatividad" del modelo, más fidelidad al texto original.

    usar_historial=False, usar_memoria=False por defecto: mantiene
    EXACTAMENTE el comportamiento de siempre (una sola pregunta suelta,
    sin contexto extra) -- así no le cambia el prompt por debajo a
    estudio.py ni a generar_changelog.py, que usan esta misma función
    para tareas puntuales, no para charlar.

    usar_historial=True: manda también los últimos turnos de la charla
    real (ver _historial_conversacion), para que Arché pueda referirse
    a lo que se dijo antes en la misma sesión.

    usar_memoria=True: le agrega al prompt un resumen de lo que
    memoria.py ya tiene guardado (gustos, personas, info personal),
    para que lo use con naturalidad sin que se lo repitas cada vez.
    """
    if not usar_historial and not usar_memoria:
        prompt = f"""
Eres Arché, un asistente inteligente.

Responde de forma clara, precisa y útil.

Si sabes la respuesta, respóndela directamente.

Si no la sabes, dilo honestamente.

Pregunta:

{pregunta}
"""
        with medir("ollama_conversar"):
            try:
                respuesta = ollama.chat(
                    model=MODELO,
                    keep_alive=KEEP_ALIVE,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": temperature, "num_predict": num_predict},
                )
            except Exception as e:
                print("Error Ollama:", e)
                return "No puedo conectarme a Ollama ahora mismo. Fijate que esté corriendo (ollama serve)."
        return respuesta["message"]["content"]

    instrucciones = (
        "Eres Arché, un asistente inteligente. Respondé de forma clara, "
        "precisa, útil y natural, como en una charla real. Si sabés la "
        "respuesta, respondela directamente. Si no la sabés, decilo "
        "honestamente."
    )
    if usar_memoria:
        from core.memoria import resumen_para_contexto
        contexto = resumen_para_contexto()
        if contexto:
            instrucciones += (
                f"\n\nCosas que ya sabés de la persona con la que hablás -- "
                f"usalas con naturalidad si vienen al caso, no las repitas "
                f"todas de una ni las fuerces si no aplican: {contexto}"
            )

    mensajes = [{"role": "system", "content": instrucciones}]
    if usar_historial:
        mensajes.extend(_historial_conversacion)
    mensajes.append({"role": "user", "content": pregunta})

    with medir("ollama_conversar"):
        try:
            respuesta = ollama.chat(
                model=MODELO,
                keep_alive=KEEP_ALIVE,
                messages=mensajes,
                options={"temperature": temperature, "num_predict": num_predict},
            )
        except Exception as e:
            print("Error Ollama:", e)
            return "No puedo conectarme a Ollama ahora mismo. Fijate que esté corriendo (ollama serve)."
    texto = respuesta["message"]["content"]

    if usar_historial:
        _historial_conversacion.append({"role": "user", "content": pregunta})
        _historial_conversacion.append({"role": "assistant", "content": texto})
        _recortar_historial()

    return texto


def generar_codigo(prompt, num_predict=400, temperature=0.2):
    """
    Igual que conversar(), pero usa MODELO_CODIGO (un modelo separado,
    especializado en generar codigo) en vez de MODELO (arche-lora, el
    modelo conversacional de Arche).

    Se separo porque arche-lora mostro comportamiento sobreajustado
    para tareas de generacion de codigo -- devolvia la misma respuesta
    palabra por palabra sin importar cambios sustanciales en el
    prompt, incluso con retroalimentacion explicita del error anterior.
    Un modelo especificamente entrenado para codigo no tiene ese sesgo.

    Usada por todo lo que escribe, revisa o verifica codigo:
    proponer_cambio_codigo.py (Fase 3: auto-modificacion de codigo),
    autorevision.py y verificar_cambio.py. El resto de Arche sigue
    usando arche-lora normalmente via conversar()/comprender().

    Si falla (modelo no descargado, Ollama caido), imprime el error y
    devuelve "" -- proponer_cambio_codigo.generar_codigo() detecta la
    respuesta vacia y cae al modelo general.
    """
    with medir("ollama_generar_codigo"):
        try:
            respuesta = ollama.chat(
                model=MODELO_CODIGO,
                keep_alive=KEEP_ALIVE_CODIGO,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                options={
                    "temperature": temperature,
                    "num_predict": num_predict,
                }
            )
        except Exception as e:
            print("Error Ollama:", e)
            return ""

    return respuesta["message"]["content"]