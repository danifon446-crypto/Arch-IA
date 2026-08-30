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

# keep_alive mantiene el modelo cargado en memoria entre llamadas.
# Con "30m" evitas que se descargue si pasan más de 5 min (default de Ollama)
# entre un comando y otro.
KEEP_ALIVE = "30m"


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


def conversar(pregunta, num_predict=300):

    prompt = f"""
Eres Arché, un asistente inteligente.

Responde de forma clara, precisa y útil.

Si sabes la respuesta, respóndela directamente.

Si no la sabes, dilo honestamente.

Pregunta:

{pregunta}
"""

    with medir("ollama_conversar"):
        respuesta = ollama.chat(
            model=MODELO,
            keep_alive=KEEP_ALIVE,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            options={
                "temperature": 0.7,
                # Limita la respuesta para que no se extienda de más.
                # Súbelo si necesitas respuestas largas (resúmenes, explicaciones extensas).
                "num_predict": num_predict,
            }
        )

    return respuesta["message"]["content"]