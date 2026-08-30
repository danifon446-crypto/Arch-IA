import time
import webbrowser
import os
import json
import urllib.parse
from ddgs import DDGS
from core.rutas import DATABASE

archivo_sitios = os.path.join(DATABASE, "sitios.json")

if os.path.exists(archivo_sitios):
    with open(archivo_sitios, "r", encoding="utf-8") as archivo:
        sitios = json.load(archivo)
else:
    sitios = {}
    with open(archivo_sitios, "w", encoding="utf-8") as archivo:
        json.dump(sitios, archivo, indent=4)


def obtener_sitio(comando):
    partes = comando.split()
    for i in range(len(partes)):
            if partes[i] == "abre" or partes[i] == "abrir":
                if i + 1 < len(partes):
                    return " ".join(partes[i + 1:])
                return None
    return comando


def abrir_navegador(sitio):
    sitio = sitio.lower()

    if sitio in sitios:
        print(f"Arché: Abriendo {sitio}...")
        time.sleep(1.5)
        webbrowser.open(sitios[sitio])
    else:
        print("Arché: No tengo acceso a esa página.")


def aprender_sitio(sitio):
        sitio = sitio.strip().lower()
        direccion = input("Arché: Escribe la dirección de la página:\nTú: ")
        sitios[sitio] = direccion
        with open(archivo_sitios, "w", encoding="utf-8") as archivo:
            json.dump(sitios, archivo, indent=4)
        print(f"Arché: He aprendido a abrir {sitio}.")
        abrir_navegador(sitio)


def existe_sitio(nombre):
        return nombre.lower().strip() in sitios


def _buscar_ddg(consulta, max_results=5):
    """
    Wrapper interno con manejo de errores. Devuelve lista de resultados
    (puede estar vacía) en vez de dejar que una excepción de red rompa
    todo el flujo de Arché.
    """
    try:
        with DDGS() as buscador:
            return list(buscador.text(consulta, max_results=max_results))
    except Exception as e:
        print(f"Arché: Error al buscar en DuckDuckGo: {e}")
        return []


def buscar_sitio(nombre):
    """
    Busca la página oficial de 'nombre'. Pide varios resultados (no solo
    uno) para tener margen si algún motor interno falla, y si la query
    con 'sitio oficial' no devuelve nada, reintenta con el nombre solo.
    """
    print(f"Arché: Buscando la página oficial de {nombre}...")

    resultados = _buscar_ddg(f"{nombre} sitio oficial", max_results=5)

    if not resultados:
        # Reintento con query más simple, por si el sufijo "sitio oficial"
        # está haciendo que el motor no encuentre coincidencias.
        resultados = _buscar_ddg(nombre, max_results=5)

    if not resultados:
        print("Arché: No encontré ninguna página.")
        return

    url = resultados[0]["href"]

    print(f"\nArché: Encontré:\n{url}")

    respuesta = input(
        "\n¿Quieres guardarla? (si/no)\nTú: "
    ).lower()

    if respuesta in ["si", "sí", "s"]:

        sitios[nombre] = url

        with open(
            archivo_sitios,
            "w",
            encoding="utf-8"
        ) as archivo:

            json.dump(
                sitios,
                archivo,
                indent=4,
                ensure_ascii=False
            )

        print("Arché: Página aprendida.")

        abrir_navegador(nombre)