from core.IA.modelo import responder, aprender_nuevo
from core.IA.ollamaIA import comprender
from core.IA.telemetria import registrar_comando


def analizar(comando):

    comando = comando.strip().lower()


    # 1. Consultar la IA propia

    resultado = responder(comando)

    if resultado is not None:

        print("Arché: Ya conozco este comando.")

        registrar_comando(comando, resultado["intencion"], resuelto_por="cache_propio")

        return resultado

    # 2. Consultar Ollama

    print("Arché: Pensando...")

    resultado = comprender(comando)

    if resultado is None:

        registrar_comando(comando, "desconocido", resuelto_por="ollama_sin_respuesta")

        return {
            "intencion": "desconocido",
            "contenido": ""
        }

    # 3. Aprender automáticamente

    if resultado["intencion"] != "desconocido":

        aprender_nuevo(
            pregunta=comando,
            respuesta=resultado,
            fuente="ollama"
        )

        print("Arché: He aprendido este comando.")

    registrar_comando(comando, resultado["intencion"], resuelto_por="ollama")


    # 4. Devolver la decisión


    return resultado


if __name__ == "__main__":

    while True:

        comando = input("\nTú: ")

        if comando.lower() == "salir":
            break

        resultado = analizar(comando)

        print(resultado)