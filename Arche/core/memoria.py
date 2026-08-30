import os
import json

from datetime import datetime
from core.rutas import DATABASE

archivo_memoria = os.path.join(DATABASE, "memoria.json")

if not os.path.exists(archivo_memoria):
    with open(archivo_memoria, "w", encoding="utf-8") as archivo:
        json.dump([], archivo, indent=4)

def detectar_tipo(texto):
        texto = texto.lower()
        if any(palabra in texto for palabra in [
            "me gusta", "mi color favorito", "mis colores favoritos",
            "prefiero", "mi comida favorita", "mi canción favorita"
        ]):
            return "gusto"
        elif any(palabra in texto for palabra in [
            "mi mamá", "mi mama", "mi papá", "mi papa",
            "mi hermano", "mi hermana", "mi novia",
            "mi novio", "mi perro", "mi gato"
        ]):
            return "persona"
        elif any(palabra in texto for palabra in [
            "vivo en", "estudio", "trabajo", "me gusta"
        ]):
            return "informacion_personal"
        elif any(palabra in texto for palabra in [
            "mañana", "hoy", "comprar", "hacer",
            "llamar", "recordar", "examen", "tarea"
        ]):
            return "recordatorio"
        elif any(palabra in texto for palabra in [
            "cumplo años", "cumpleaños", "nací", "naci"
        ]):
            return "fecha"
        return "otro"

def recordar(texto):
        with open(archivo_memoria, "r", encoding="utf-8") as archivo:
            recuerdos = json.load(archivo)
        nuevo = {
            "tipo": detectar_tipo(texto),
            "contenido": texto,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prioridad": detectar_prioridad(texto),
            "estado": "pendiente"
            }
        if any(
        recuerdo["contenido"].lower() == texto.lower()
        for recuerdo in recuerdos
    ):
            print("Arché: Ya recordaba eso.")
        return
        recuerdos.append(nuevo) 

        with open(archivo_memoria, "w", encoding="utf-8") as archivo:
            json.dump(recuerdos, archivo, indent=4, ensure_ascii=False)

        print(f"Arché: Lo recordaré como {nuevo['tipo']}.")


def mostrar_recuerdos():
        with open(archivo_memoria, "r", encoding="utf-8") as archivo:
            recuerdos = json.load(archivo)
        if recuerdos:
            print("Arché: Esto es lo que recuerdo:")
            for recuerdo in recuerdos:
                print(f"- ({recuerdo['tipo']}) {recuerdo['contenido']}")
        else:
            print("Arché: No recuerdo nada por ahora.")

def detectar_prioridad(texto):
        texto = texto.lower()
        if any(palabra in texto for palabra in [
            "urgente",
            "examen",
            "mañana",
            "hoy",
            "importante",
            "ya",
            "cita"
        ]):
            return "alta"
        elif any(palabra in texto for palabra in [
            "comprar",
            "llamar",
            "hacer",
            "estudiar",
            "revisar",
            "terminar"
        ]):
            return "normal"
        elif any(palabra in texto for palabra in [
            "algún día",
            "algun dia",
            "cuando pueda",
            "más adelante",
            "mas adelante",
            "en el futuro"
        ]):
            return "baja"

        return "normal"