from core.IA.aprendizaje import resolver, aprender


def buscar(pregunta):
    """
    Antes: comparaba la pregunta contra el texto exacto guardado.
    Ahora: usa resolver(), que generaliza por plantillas (parte variable)
    y tolera variaciones menores en la parte fija.
    """
    return resolver(pregunta)


def responder(pregunta):

    conocimiento = buscar(pregunta)

    if conocimiento:

        return {
            "intencion": conocimiento["accion"],
            "contenido": conocimiento["contenido"]
        }

    return None


def aprender_nuevo(pregunta, respuesta, fuente="ollama"):

    aprender(
        pregunta=pregunta,
        accion=respuesta["intencion"],
        contenido=respuesta["contenido"],
        fuente=fuente
    )


if __name__ == "__main__":

    while True:

        texto = input("Tú: ")

        if texto.lower() == "salir":
            break

        respuesta = responder(texto)

        if respuesta:
            print(respuesta)
        else:
            print("No conozco ese comando.")
