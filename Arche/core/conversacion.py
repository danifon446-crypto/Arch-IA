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


def saludar(nombre):
    """
    Usada por main.py cuando la IA reconoce un saludo ("hola", "buenas",
    etc.). No existía en ningún lado del proyecto -- llamarla crasheaba
    con NameError apenas el clasificador identificaba intencion "saludo".
    """
    saludos = [
        f"¡Hola, {nombre}!",
        f"Hola de nuevo, {nombre}.",
        f"¡Qué bueno verte, {nombre}!",
        f"Hola, {nombre}. ¿En qué puedo ayudarte?",
    ]
    print(f"Arché: {random.choice(saludos)}")


def presentarse():
    """
    Usada por main.py para intencion "presentacion" (ej: '¿quién eres?',
    'preséntate'). Tampoco existía en ningún lado del proyecto.
    """
    print(
        "Arché: Soy Arché, tu asistente personal. Puedo tomar notas, "
        "recordarte cosas, hacer cálculos, buscar y abrir cosas en tu "
        "equipo, y también aprender y mejorar mi propio código con tu "
        "aprobación. Decime 'ayuda' si querés ver todo lo que puedo hacer."
    )


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