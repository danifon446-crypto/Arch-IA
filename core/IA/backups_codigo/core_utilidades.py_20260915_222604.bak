import time
def decir_hora ():
    print("Arché:", time.strftime("%H:%M:%S"))

def saludar(nombre):
    print(f"Hola, {nombre}.¿Como estás?")

def decir_fecha():
    print("Arché:", time.strftime("%d/%m/%Y"))

def despedida():
    print("Arché: Hasta luego.")

def presentarse():
    print("Soy Arche tu IA personal")

def ayuda(categoria=None):
    if categoria is None:
        print("\nArché: Actualmente puedo ayudarte con:\n")
        print("•  Saludos")
        print("•  Fecha y hora")
        print("•  Páginas web")
        print("•  Programas")
        print("•  Archivos")
        print("•  Notas")
        print("•  Recordatorios")
        print("•  Memoria")
        print("•  Calculadora")
        print("•  Configuración")
        print("•  Búsqueda en Google")
        print("\nEjemplos:")
        print("• ¿Qué hace notas?")
        print("• ¿Qué hace programas?")
        print("• ¿Qué hace calculadora?")
        return
    categoria = categoria.lower()
    ayudas = {
        "saludos": [
            "Saludar",
            "Presentarme",
            "Despedirme"
        ],
        "fecha y hora": [
            "Decir la fecha",
            "Decir la hora"
        ],
        "páginas web": [
            "Abrir páginas web",
            "Aprender nuevas páginas web"
        ],
        "programas": [
            "Abrir programas",
            "Aprender nuevos programas"
        ],
        "archivos": [
            "Buscar archivos",
            "Abrir archivos",
            "Actualizar índice"
        ],
        "notas": [
            "Crear notas",
            "Leer notas",
            "Abrir notas",
            "Agregar texto",
            "Eliminar notas",
            "Mostrar todas las notas"
        ],
        "recordatorios": [
            "Crear recordatorios",
            "Mostrar recordatorios",
            "Completar recordatorios",
            "Eliminar recordatorios",
            "Avisar pendientes al iniciar"
        ],
        "memoria": [
            "Recordar información",
            "Mostrar recuerdos"
        ],
        "calculadora": [
            "Operaciones básicas",
            "Potencias",
            "Raíz cuadrada",
            "Seno",
            "Coseno",
            "Tangente",
            "Logaritmos",
            "Historial de cálculos"
        ],
        "configuración": [
            "Cambiar tu nombre",
            "Cambiar mi nombre",
            "Mostrar configuración",
            "Restablecer configuración"
        ],
        "búsqueda en google": [
            "Buscar cualquier tema en Google"
        ]
    }
    alias = {

        "configuracion": "configuración",

        "paginas web": "páginas web",

        "busqueda en google": "búsqueda en google",

        "google": "búsqueda en google",

        "fecha": "fecha y hora",

        "hora": "fecha y hora"

    }

    categoria = alias.get(categoria, categoria)

    if categoria in ayudas:
        print(f"\nArché: {categoria.upper()}\n")
        for funcion in ayudas[categoria]:
            print(f"• {funcion}")
    else:
        print("Arché: No conozco esa categoría.")

def extraer_contenido(comando, palabras):
    comando = comando.lower()

    for palabra in palabras:
        if comando.startswith(palabra):
            return comando[len(palabra):].strip()

    return ""