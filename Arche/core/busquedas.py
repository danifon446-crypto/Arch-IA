import time
import webbrowser

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
    webbrowser.open("https://www.google.com/search?q=" + busqueda.replace(" ", "+"))