"""
conectar_funciones.py
---------------------
Ubicacion: Arche/core/IA/conectar_funciones.py

Cuando Arche escribe una funcion nueva y vos la aprobas, se ofrece a
CONECTARLA a un comando del chat -- asi la funcion se puede usar de verdad
sin que tengas que tocar main.py.

Como funciona:
  - Los comandos conectados viven en core/comandos_extra.py, un registro
    simple {frase: (modulo, funcion, devuelve_valor, plantilla)}.
  - Conectar una funcion = agregar UNA linea a ese registro. Se propone con
    proponer_cambio_manual, o sea que pasa por el MISMO gate de aprobacion
    de siempre (revisar_cambios_codigo.py): Arche no toca nada sin tu OK.
  - Solo se ofrece conectar funciones SIN argumentos obligatorios.

Uso desde main.py:
    ids = ids_pendientes()  ->  revisar cambios  ->  ofrecer_tras_revision(ids)
    y el comando "conecta <nombre_de_funcion>" para funciones ya existentes.
"""

import ast

from core.comandos_extra import _normalizar
from core.IA.proponer_cambio_codigo import (
    RAIZ_APP, _cargar_pendientes, _extraer_funcion, _requiere_argumentos,
    proponer_cambio_manual,
)

ARCHIVO_REGISTRO = "core/comandos_extra.py"
MARCA = "    # --- comandos agregados por Arché (no borrar esta línea) ---"

IGNORAR_CARPETAS = {
    "__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database",
    "backups_codigo", "backups_autoconocimiento",
}


def ids_pendientes():
    """Ids de las propuestas que hoy estan pendientes (para comparar antes/despues de revisar)."""
    return {p["id"] for p in _cargar_pendientes() if p.get("estado") == "pendiente"}


def _defs_de_nivel_superior(codigo):
    try:
        arbol = ast.parse(codigo)
    except SyntaxError:
        return []
    return [n.name for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _archivo_a_modulo(archivo_rel):
    base = archivo_rel[:-3] if archivo_rel.endswith(".py") else archivo_rel
    return base.replace("/", ".")


def funciones_nuevas_aprobadas(ids_antes):
    """
    [(archivo, funcion)] de funciones que Arche agrego en propuestas que
    estaban pendientes en `ids_antes`, ya no lo estan, y EXISTEN de verdad
    en el archivo (o sea, se aplicaron -- no fueron rechazadas).
    """
    resultado = []
    for p in _cargar_pendientes():
        if p.get("id") not in ids_antes or p.get("estado") == "pendiente":
            continue
        if not str(p.get("que", "")).startswith("Agregar una función nueva"):
            continue
        ya_existian = set(_defs_de_nivel_superior(p.get("buscar", "")))
        nuevas = [n for n in _defs_de_nivel_superior(p.get("reemplazar", "")) if n not in ya_existian]
        ruta = RAIZ_APP / p.get("archivo", "")
        if not nuevas or not ruta.is_file():
            continue
        actual = ruta.read_text(encoding="utf-8")
        for nombre in nuevas:
            if _extraer_funcion(actual, nombre):
                resultado.append((p["archivo"], nombre))
    return resultado


def buscar_funcion(nombre):
    """Archivos del proyecto (rutas relativas) que definen `nombre` a nivel de modulo."""
    encontrados = []
    for ruta in RAIZ_APP.rglob("*.py"):
        relativa = ruta.relative_to(RAIZ_APP)
        if any(parte in IGNORAR_CARPETAS for parte in relativa.parts):
            continue
        try:
            contenido = ruta.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        if nombre in _defs_de_nivel_superior(contenido):
            encontrados.append(relativa.as_posix())
    return encontrados


def _devuelve_valor(codigo_funcion):
    try:
        arbol = ast.parse(codigo_funcion)
    except SyntaxError:
        return True
    return any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(arbol))


def ofrecer_conexion(archivo_rel, nombre):
    """
    Pregunta si conectar `nombre` a un comando, arma la propuesta y abre
    la revision para que la apruebes. Devuelve True si dejo una propuesta.
    """
    ruta = RAIZ_APP / archivo_rel
    codigo = _extraer_funcion(ruta.read_text(encoding="utf-8"), nombre) if ruta.is_file() else None
    if codigo is None:
        print(f"Arché: No encuentro la función '{nombre}' en {archivo_rel}.")
        return False
    if _requiere_argumentos(codigo):
        print(f"Arché: '{nombre}' necesita datos para funcionar, así que todavía no sé conectarla sola a un comando.")
        return False

    registro = RAIZ_APP / ARCHIVO_REGISTRO
    if not registro.is_file() or MARCA not in registro.read_text(encoding="utf-8"):
        print(f"Arché: No encuentro {ARCHIVO_REGISTRO} (o le falta la línea de inserción), así que no puedo conectar funciones.")
        return False

    frase_sugerida = _normalizar(nombre.replace("_", " "))
    respuesta = input(
        f"Arché: Tengo lista la función '{nombre}'. ¿La conecto a un comando del chat? "
        f"Lo diría como '{frase_sugerida}'. [s = sí / n = no / o escribí otra frase]\nTú: "
    ).strip()
    if not respuesta or respuesta.lower() in ("n", "no"):
        print(f"Arché: Dale, no la conecto. Cuando quieras, decime 'conecta {nombre}'.")
        return False
    frase = frase_sugerida if respuesta.lower() in ("s", "si", "sí") else _normalizar(respuesta)
    if not frase:
        print("Arché: No entendí la frase, no conecto nada.")
        return False

    if f"{frase!r}:" in registro.read_text(encoding="utf-8"):
        print(f"Arché: Ya existe un comando '{frase}'. Elegí otra frase y volvé a decirme 'conecta {nombre}'.")
        return False

    devuelve_valor = _devuelve_valor(codigo)
    plantilla = None
    if devuelve_valor:
        texto = input(
            "Arché: ¿Cómo querés que te diga el resultado? Podés usar {0}, {1}... para las partes "
            "(ej. 'Tu último cálculo fue {0} = {1}.'). Enter = mostrarlo tal cual.\nTú: "
        ).strip()
        plantilla = texto or None

    linea = f"    {frase!r}: ({_archivo_a_modulo(archivo_rel)!r}, {nombre!r}, {devuelve_valor!r}, {plantilla!r}),"
    propuesta, error = proponer_cambio_manual(
        archivo=ARCHIVO_REGISTRO,
        buscar=MARCA,
        reemplazar=MARCA + "\n" + linea,
        que=f"Conectar la función '{nombre}' al comando '{frase}'.",
        origen="autonomo",
    )
    if error:
        print(f"Arché: No pude armar la conexión: {error}")
        return False

    print(f"Arché: Listo, armé la conexión de '{nombre}' al comando '{frase}'. Te la muestro para que la apruebes:")
    from core.IA.revisar_cambios_codigo import main as revisar_cambios_codigo
    revisar_cambios_codigo()
    return True


def ofrecer_tras_revision(ids_antes):
    """Llamar justo despues de 'revisar cambios de codigo': ofrece conectar
    las funciones nuevas que se aprobaron en esa revision (maximo 3)."""
    for archivo_rel, nombre in funciones_nuevas_aprobadas(ids_antes)[:3]:
        ofrecer_conexion(archivo_rel, nombre)


def conectar_por_nombre(nombre):
    """Para el comando 'conecta <funcion>': busca la funcion en el proyecto y ofrece conectarla."""
    if not nombre.isidentifier():
        print("Arché: Decime el nombre de la función, por ejemplo 'conecta ultimo_calculo'.")
        return
    encontrados = buscar_funcion(nombre)
    if not encontrados:
        print(f"Arché: No encuentro ninguna función llamada '{nombre}' en el proyecto.")
    elif len(encontrados) > 1:
        print(f"Arché: '{nombre}' está definida en más de un archivo ({', '.join(encontrados)}), no sé cuál conectar.")
    else:
        ofrecer_conexion(encontrados[0], nombre)