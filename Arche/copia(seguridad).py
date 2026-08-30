import time

from core.utilidades import *
from core.navegador import *
from core.programaV2 import *
from core.busquedas import *
from core.sistema import *
from core.memoria import *
from core.notas import *
from core.recordatorio import *
from core.conversacion import *
from core.archivos import *
from core.configuracion import *
from core.calculadora import *

print("=" * 60)
print("        Arche v2.0.1")
print("=" * 60)

if obtener("nombre_usuario") == "Usuario":
    nombre = input("¿Cómo te llamas?\nTú: ").strip()
    if nombre:
        cambiar("nombre_usuario", nombre)

print()
print("Analizando datos...")
time.sleep(2)

if obtener("mostrar_estado"):
    hablar("Todos los sistemas están operativos.")

if obtener("saludo_inicial"):
    hablar(f"Hola, {obtener('nombre_usuario')}.")
    hablar("¿En qué puedo ayudarte?")

if obtener("mostrar_recordatorios"):
    revisar_recordatorios()

while True:

    comando = input("\nTú: ").lower().strip()

    if not comando:
        continue

    # CONVERSACIÓN

    if responder(comando):
        continue

    elif comando in [
        "hola",
        "buenas",
        "buenos días",
        "buenas tardes",
        "buenas noches"
    ]:
        saludar(obtener("nombre_usuario"))

    elif comando in [
        "preséntate",
        "presentate",
        "quién eres",
        "quien eres"
    ]:
        presentarse()

    elif comando in [
        "hora",
        "qué hora es",
        "que hora es"
    ]:
        decir_hora()

    elif comando in [
        "fecha",
        "qué fecha es",
        "que fecha es",
        "día de hoy",
        "dia de hoy",
        "qué día es hoy",
        "que dia es hoy"
    ]:
        decir_fecha()

    elif comando in [
        "adiós",
        "adios",
        "salir"
    ]:
        despedida()
        break

    # AYUDA

    elif (
        "haces" in comando
        or "hacer" in comando
        or "ayuda" in comando
        or "puedes" in comando
    ):
        ayuda()

    elif comando.startswith("que hace ") or comando.startswith("qué hace "):
        categoria = comando.lower()
        categoria = categoria.replace("qué hace", "")
        categoria = categoria.replace("que hace", "")
        categoria = categoria.replace("¿", "")
        categoria = categoria.replace("?", "")
        categoria = categoria.strip()
        ayuda(categoria)

    # CONFIGURACIÓN

    elif comando in [
        "configuración",
        "configuracion",
        "mostrar configuración",
        "mostrar configuracion"
    ]:
        mostrar()

    elif comando == "cambiar mi nombre":
        nuevo = input("Arché: ¿Cómo quieres que te llame?\nTú: ").strip()
        if nuevo:
            cambiar("nombre_usuario", nuevo)
            hablar(f"De acuerdo, ahora te llamaré {nuevo}.")

    elif comando == "cambiar tu nombre":
        nuevo = input("Arché: ¿Cómo quieres llamarme?\nTú: ").strip()
        if nuevo:
            cambiar("nombre_asistente", nuevo)
            hablar(f"Ahora mi nombre es {nuevo}.")

    elif comando in [
        "restablecer configuración",
        "restablecer configuracion"
    ]:
        restaurar()
        hablar("Configuración restablecida.")

    # NOTAS

    elif comando.startswith("crea una nota"):
        nombre_nota = comando.replace("crea una nota", "", 1).strip()

        if nombre_nota:
            crear_nota(nombre_nota)
        else:
            print("Arché: ¿Cómo quieres llamar la nota?")

    elif comando.startswith("lee la nota"):
        nombre_nota = comando.replace("lee la nota", "", 1).strip()

        if nombre_nota:
            leer_nota(nombre_nota)
        else:
            print("Arché: ¿Qué nota quieres leer?")

    elif comando.startswith("abre la nota"):
        nombre_nota = comando.replace("abre la nota", "", 1).strip()

        if nombre_nota:
            abrir_nota(nombre_nota)
        else:
            print("Arché: ¿Qué nota quieres abrir?")

    elif comando.startswith("agrega a"):
        nombre_nota = comando.replace("agrega a", "", 1).strip()

        if nombre_nota:
            agregar_nota(nombre_nota)
        else:
            print("Arché: ¿A qué nota quieres agregar texto?")

    elif comando.startswith("elimina la nota"):
        nombre_nota = comando.replace("elimina la nota", "", 1).strip()

        if nombre_nota:
            eliminar_nota(nombre_nota)
        else:
            print("Arché: ¿Qué nota quieres eliminar?")

    elif comando in [
        "mis notas",
        "listar notas"
    ]:
        listar_notas()

    # MEMORIA

    elif comando.startswith("recuerda"):
        recuerdo = comando.replace("recuerda", "", 1).strip()

        if recuerdo:
            recordar(recuerdo)
        else:
            print("Arché: ¿Qué quieres que recuerde?")

    elif comando in [
        "que recuerdas",
        "qué recuerdas",
        "recuerdos"
    ]:
        mostrar_recuerdos()

    # RECORDATORIOS

    elif comando.startswith("recuérdame") or comando.startswith("recordatorio"):
        crear_recordatorio()

    elif comando == "mis recordatorios":
        mostrar_recordatorios()

    elif comando == "completar recordatorio":
        completar_recordatorio()

    elif comando == "eliminar recordatorio":
        eliminar_recordatorio()

    # ARCHIVOS

    elif comando == "actualizar archivos":
        actualizar_indice()

    elif comando.startswith("busca archivo"):
        nombre = comando.replace("busca archivo", "", 1).strip()
        mostrar_resultados(buscar(nombre))

    elif comando.startswith("abre archivo"):
        nombre = comando.replace("abre archivo", "", 1).strip()
        buscar_y_abrir(nombre)

    # BÚSQUEDAS EN GOOGLE

    elif comando.startswith("busca") or comando.startswith("buscar"):
        busqueda = obtener_busqueda(comando)

        if busqueda:
            buscar_google(busqueda)

        else:
            respuesta = input("Arché: ¿Qué quieres buscar?\nTú: ").lower()

            busqueda = obtener_busqueda(respuesta)

            if busqueda:
                buscar_google(busqueda)
            else:
                buscar_google(respuesta)


    # PÁGINAS WEB Y PROGRAMAS


    elif comando.startswith("abre") or comando.startswith("abrir"):
        nombre = obtener_sitio(comando)

        if not nombre:
            nombre = input("Arché: ¿Qué deseas abrir?\nTú: ").strip().lower()

        tipo = input(
            "Arché: ¿Es una página web (1) o un programa (2)?\nTú: "
        ).strip().lower()

        if tipo == "1":

            if nombre in sitios:
                abrir_navegador(nombre)
            else:
                respuesta = input(
                    "Arché: No conozco esa página. ¿Quieres enseñármela? (sí/no)\nTú: "
                ).strip().lower()

                if respuesta in ["si", "sí", "s"]:
                    aprender_sitio(nombre)

        elif tipo == "2":
            aprender_programa(nombre)

        else:

            print("Arché: Opción no válida.")

    
    # CALCULADORA

    elif comando.startswith("calcula"):
        operacion = comando.replace(
            "calcula",
            "",
            1
        ).strip()

        if operacion:
            calcular(operacion)
        else:
            print("Arché: ¿Qué operación quieres calcular?")

    elif comando.startswith("cuanto es"):

        operacion = comando.replace(
            "cuanto es",
            "",
            1
        ).strip()

        if operacion:
            calcular(operacion)
        else:
            print("Arché: ¿Qué operación quieres calcular?")

    elif comando.startswith("cuánto es"):

        operacion = comando.replace(
            "cuánto es",
            "",
            1
        ).strip()

        if operacion:
            calcular(operacion)
        else:
            print("Arché: ¿Qué operación quieres calcular?")

    elif comando in [
        "historial calculos",
        "historial cálculos"
    ]:
        historial()

    
    # COMANDO DESCONOCIDO
    

    else:
        print("Arché: Aún no sé hacer eso.")