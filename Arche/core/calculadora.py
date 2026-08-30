import ast
import math
import operator
import json
import os

from core.rutas import DATABASE

archivo = os.path.join(
    DATABASE,
    "historial_calculos.json"
)


if not os.path.exists(archivo):
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump([], f, indent=4)


# VARIABLES

ANS = 0
OPERADORES = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod
}

UNARIOS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg
}

FUNCIONES = {
    "sqrt": math.sqrt,
    "sin": lambda x: math.sin(math.radians(x)),
    "cos": lambda x: math.cos(math.radians(x)),
    "tan": lambda x: math.tan(math.radians(x)),
    "log": math.log10,
    "ln": math.log,
    "abs": abs,
    "round": round
}

CONSTANTES = {
    "pi": math.pi,
    "e": math.e
}


# HISTORIAL


def guardar_historial(expresion, resultado):
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except:
        datos = []
    datos.append({
        "expresion": expresion,
        "resultado": resultado
    })
    datos = datos[-50:]
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


# EVALUADOR


def evaluar(nodo):
    if isinstance(nodo, ast.Constant):
        return nodo.value
    if isinstance(nodo, ast.Num):
        return nodo.n
    if isinstance(nodo, ast.BinOp):
        return OPERADORES[type(nodo.op)](
            evaluar(nodo.left),
            evaluar(nodo.right)
        )
    if isinstance(nodo, ast.UnaryOp):
        return UNARIOS[type(nodo.op)](
            evaluar(nodo.operand)
        )
    if isinstance(nodo, ast.Name):
        nombre = nodo.id.lower()
        if nombre == "ans":
            return ANS
        if nombre in CONSTANTES:
            return CONSTANTES[nombre]
        raise ValueError
    if isinstance(nodo, ast.Call):
        nombre = nodo.func.id.lower()
        if nombre not in FUNCIONES:
            raise ValueError
        argumentos = [
            evaluar(arg)
            for arg in nodo.args
        ]
        return FUNCIONES[nombre](*argumentos)
    raise ValueError()

# LIMPIAR EXPRESIÓN


def limpiar(expresion):
    expresion = expresion.lower().strip()
    reemplazos = {
        "más": "+",
        "mas": "+",
        "menos": "-",
        "por": "*",
        "x": "*",
        "entre": "/",
        "dividido": "/",
        "dividido por": "/",
        "^": "**",
        "raiz de": "sqrt",
        "raíz de": "sqrt",
        "raiz": "sqrt",
        "raíz": "sqrt",
        "sen": "sin",
        "%": "/100"
    }
    for viejo, nuevo in reemplazos.items():
        expresion = expresion.replace(viejo, nuevo)
    return expresion



# CALCULAR


def calcular(expresion):
    global ANS
    try:
        expresion = limpiar(expresion)
        arbol = ast.parse(
            expresion,
            mode="eval"
        )
        resultado = evaluar(arbol.body)
        ANS = resultado
        guardar_historial(
            expresion,
            resultado
        )
        if isinstance(resultado, float):
            if resultado.is_integer():
                resultado = int(resultado)
            else:
                resultado = round(resultado, 8)
        print(f"Arché: Resultado = {resultado}")
        return resultado
    except ZeroDivisionError:
        print("Arché: No se puede dividir entre cero.")
    except Exception:
        print("Arché: No pude resolver esa operación.")


# HISTORIAL


def historial():
    try:
        with open(
            archivo,
            "r",
            encoding="utf-8"
        ) as f:
            datos = json.load(f)
    except:
        datos = []
    if not datos:
        print("Arché: No hay cálculos guardados.")
        return
    print()
    print("=" * 45)
    print("HISTORIAL")
    print("=" * 45)
    for i, dato in enumerate(datos, start=1):
        print(
            f"{i}. {dato['expresion']} = {dato['resultado']}"
        )
    print("=" * 45)