import re

VERBOS = {
    "abrir": [
        "abre",
        "abrir",
        "abreme",
        "inicia",
        "ejecuta",
        "entra a",
        "entra en",
        "ingresa a",
        "ingresa en",
        "llévame a",
        "llevame a",
        "quiero abrir",
        "quiero entrar a",
        "quiero ingresar a"
    ],

    "buscar": [
        "busca",
        "buscar",
        "investiga",
        "consulta",
        "averigua",
        "busca sobre",
        "investiga sobre"
    ]
}


def limpiar(texto):

    texto = texto.lower()

    texto = texto.replace("á","a")
    texto = texto.replace("é","e")
    texto = texto.replace("í","i")
    texto = texto.replace("ó","o")
    texto = texto.replace("ú","u")

    texto = re.sub(r"[¿?¡!,.]", "", texto)

    return texto.strip()


def comprender(comando):

    comando = limpiar(comando)

    for intencion, verbos in VERBOS.items():

        for verbo in verbos:

            if comando.startswith(verbo):

                contenido = comando.replace(
                    verbo,
                    "",
                    1
                ).strip()

                return {
                    "intencion": intencion,
                    "contenido": contenido
                }

    return None