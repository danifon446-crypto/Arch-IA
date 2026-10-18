import time
import webbrowser
from urllib.parse import quote_plus

def obtener_busqueda(comando):
    partes = comando.split()    
    for i in range(len(partes)):
        if partes[i] == "busca" or partes[i] == "buscar":

            if i + 1 < len(partes):
                return " ".join(partes[i + 1:])

            return None

    return None

def buscar_google(busqueda):
    print (f"Arche esta buscando '{busqueda}' en Google")
    time.sleep(1.5)
    # abrir_url pregunta en cuál navegador si hay más de uno
    from core.control_pc import abrir_url
    abrir_url("https://www.google.com/search?q=" + quote_plus(busqueda))