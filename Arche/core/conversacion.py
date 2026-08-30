import random

RESPUESTAS = {

    "gracias": [
        "Con gusto.",
        "Para eso estoy.",
        "Siempre es un placer ayudar.",
        "No hay de qué."
    ],

    "como estas": [
        "Funcionando correctamente.",
        "Todos mis sistemas están operativos.",
        "Estoy listo para ayudarte.",
        "Me encuentro funcionando sin problemas."
    ],

    "que tal": [
        "Todo marcha correctamente.",
        "Muy bien. ¿Y tú?",
        "Listo para ayudarte."
    ],

    "buenos dias": [
        "¡Buenos días!",
        "Espero que tengas un excelente día.",
        "Buenos días. ¿En qué puedo ayudarte?"
    ],

    "buenas tardes": [
        "¡Buenas tardes!",
        "Espero que estés teniendo una buena tarde.",
        "Buenas tardes. ¿Qué necesitas?"
    ],

    "buenas noches": [
        "Buenas noches.",
        "Que tengas una excelente noche.",
        "Buenas noches. ¿En qué puedo ayudarte?"
    ],

    "adios": [
        "Hasta luego.",
        "Nos vemos pronto.",
        "Fue un gusto ayudarte.",
        "Que tengas un excelente día."
    ],

    "quien te creo": [
        "Fui creado por Daniel González.",
        "Mi creador es Daniel González.",
        "Daniel González me desarrolló desde cero."
    ],

    "como te llamas": [
        "Mi nombre es Arché.",
        "Soy Arché.",
        "Puedes llamarme Arché."
    ],

    "que haces": [
        "Puedo ayudarte con distintas tareas.",
        "Estoy preparado para ayudarte.",
        "Puedo abrir programas, páginas, tomar notas y mucho más."
    ],

    "felicidades": [
        "Muchas gracias.",
        "Lo aprecio.",
        "Gracias por tus palabras."
    ],

    "bien": [
        "Me alegra saberlo.",
        "Excelente.",
        "Perfecto."
    ],

    "mal": [
        "Espero que todo mejore.",
        "Ánimo, mañana será un mejor día.",
        "Deseo que las cosas mejoren pronto."
    ]

}


def normalizar(texto):

    texto = texto.lower()

    reemplazos = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u"
    }

    for a, b in reemplazos.items():
        texto = texto.replace(a, b)

    return texto


def responder(comando):

    comando = normalizar(comando)

    for clave in RESPUESTAS:

        if clave in comando:

            print("Arché:", random.choice(RESPUESTAS[clave]))

            return True

    return False