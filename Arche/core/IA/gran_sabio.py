"""
gran_sabio.py
-------------
Ubicacion: Arche/core/IA/gran_sabio.py

Inspirado en el Gran Sabio / Raphael de "Tensei shitara Slime Datta Ken":
una capa de ANALISIS que identifica que tiene Arche delante, mide el
impacto de tocar algo, estima que tan dificil es un pedido, APRENDE de
sus propios errores para no repetirlos, calcula riesgo, habla con un
tono analitico si se lo pedis, y lleva un registro simple de objetivos.

Todo esto AYUDA a las decisiones que ya existen -- no reemplaza ni se
salta ninguna aprobacion (revisar_cambios_codigo.py sigue siendo el
unico lugar donde algo se aplica de verdad):

  - identificar_funcion() / analizar()      -> que es una funcion/frase
  - analizar_impacto()                      -> quien mas usa una funcion
  - pistas_aprendidas()                     -> se inyecta SOLA en los
    prompts de proponer_cambio_codigo.py, para avisarle al modelo de
    errores que ya cometio antes con esa misma funcion en ese archivo
  - registrar_error()                       -> lo llama proponer_cambio_codigo.py
    cada vez que detecta un error conocido (retorno inexistente, open
    sobre una carpeta), asi la proxima vez lo evita desde el primer intento
  - estimar_dificultad()                    -> antes de gastar un intento
    con el modelo, avisa si el pedido pinta dificil (varias funciones,
    pedido largo, archivo grande, o ya fallo antes en ese archivo)
  - evaluar_riesgo()                        -> riesgo estimado de una
    propuesta de codigo ya generada

Comandos que usa este modulo (conectados en main.py):
  - "analiza <nombre o frase>"        -> identificar_y_explicar()
  - "impacto <nombre>"                -> quien usa esa funcion
  - "riesgo <id>"                     -> riesgo estimado de una propuesta pendiente
  - "modo gran sabio on" / "... off"  -> activa/desactiva el prefijo "Respuesta:"
  - "objetivo: <texto>"               -> agrega un objetivo
  - "objetivos"                       -> lista los objetivos pendientes
  - "logre <texto>"                   -> marca un objetivo como logrado
"""

import ast
import json
import re
import unicodedata
from pathlib import Path

from core.IA.proponer_cambio_codigo import RAIZ_APP, ARCHIVOS_PROTEGIDOS, _cargar_pendientes

BASE = Path(__file__).parent
ARCHIVO_CONFIG = BASE / "gran_sabio_config.json"
ARCHIVO_OBJETIVOS = BASE / "objetivos_raphael.json"
ARCHIVO_ERRORES = BASE / "errores_aprendidos.json"

IGNORAR_CARPETAS = {
    "__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database",
    "backups_codigo", "backups_autoconocimiento",
}


# --------------------------------------------------------------------
# VOZ: prefijo "Respuesta: " -- toggle simple en un json propio, para
# no depender del formato interno de core/configuracion.py.
# --------------------------------------------------------------------

def _cargar_config():
    if not ARCHIVO_CONFIG.exists():
        return {"voz": False}
    try:
        return json.loads(ARCHIVO_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"voz": False}


def _guardar_config(cfg):
    ARCHIVO_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def voz_activa():
    return _cargar_config().get("voz", False)


def activar_voz(valor):
    cfg = _cargar_config()
    cfg["voz"] = valor
    _guardar_config(cfg)
    print(f"Arché: {'Activé' if valor else 'Desactivé'} el modo Gran Sabio "
          f"{'-- ahora empiezo mis análisis con «Respuesta:».' if valor else '-- vuelvo a hablar normal.'}")


def decir(texto):
    """Imprime con el prefijo 'Respuesta:' si el modo esta activo, o normal si no."""
    prefijo = "Respuesta: " if voz_activa() else ""
    print(f"Arché: {prefijo}{texto}")


# --------------------------------------------------------------------
# Utilidades comunes de recorrido del proyecto
# --------------------------------------------------------------------

def _archivos_del_proyecto():
    for archivo in RAIZ_APP.rglob("*.py"):
        rel = archivo.relative_to(RAIZ_APP)
        if any(parte in IGNORAR_CARPETAS for parte in rel.parts):
            continue
        yield archivo, rel.as_posix()


def _indice_referencias():
    conteo = {}
    for archivo, _ in _archivos_del_proyecto():
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Name):
                conteo[nodo.id] = conteo.get(nodo.id, 0) + 1
            elif isinstance(nodo, ast.Attribute):
                conteo[nodo.attr] = conteo.get(nodo.attr, 0) + 1
    return conteo


# --------------------------------------------------------------------
# ANALIZA / IDENTIFICA: que es una funcion, o que intencion reconoceria
# Arche en una frase -- nivel "Gran Sabio le dice a Rimuru que hay ahi".
# --------------------------------------------------------------------

def identificar_funcion(nombre):
    """Busca `nombre` como funcion definida a nivel de modulo en todo el
    proyecto. Devuelve una lista: vacia si no existe, un item si es
    unica, varios si hay mas de una con ese nombre (nombres repetidos
    en distintos archivos)."""
    encontradas = []
    for archivo, rel in _archivos_del_proyecto():
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in arbol.body:
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
                docstring = ast.get_docstring(nodo)
                argumentos = [a.arg for a in nodo.args.args]
                devuelve = any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(nodo))
                encontradas.append({
                    "archivo": rel, "nombre": nombre, "argumentos": argumentos,
                    "devuelve_valor": devuelve, "docstring": docstring,
                    "lineas": (nodo.end_lineno or nodo.lineno) - nodo.lineno + 1,
                })
    if len(encontradas) == 1:
        encontradas[0]["usos_en_el_proyecto"] = max(_indice_referencias().get(nombre, 0) - 1, 0)
    return encontradas


def analizar(texto):
    """
    Punto de entrada de 'analiza <algo>'. Si la primera palabra de
    `texto` es un identificador valido de Python, primero busca si es
    una funcion del proyecto y arma su ficha tecnica. Si no es un
    identificador, o no se encuentra ninguna funcion con ese nombre, lo
    trata como una frase en lenguaje natural y usa el clasificador
    (comprender) para decir que intencion reconoceria Arche ahi.
    """
    texto = (texto or "").strip()
    if not texto:
        decir("¿Qué querés que analice? Puede ser el nombre de una función, o una frase.")
        return

    candidato = texto.split()[0]
    if candidato.isidentifier():
        resultados = identificar_funcion(candidato)
        if len(resultados) == 1:
            info = resultados[0]
            partes = [f"'{info['nombre']}' está en {info['archivo']}, tiene {info['lineas']} línea(s)"]
            partes.append(f"recibe {', '.join(info['argumentos'])}" if info["argumentos"] else "no recibe argumentos")
            partes.append("devuelve un valor" if info["devuelve_valor"] else "no devuelve nada (imprime o modifica algo)")
            usos = info["usos_en_el_proyecto"]
            partes.append(f"se usa {usos} vez/veces más en el proyecto" if usos else "no la usa nada más en el proyecto")
            if info["docstring"]:
                partes.append(f"su descripción dice: «{info['docstring'].splitlines()[0]}»")
            decir(". ".join(partes) + ".")
            return
        if len(resultados) > 1:
            archivos = ", ".join(r["archivo"] for r in resultados)
            decir(f"Hay {len(resultados)} funciones llamadas '{candidato}', en: {archivos}.")
            return

    from core.IA.ollamaIA import comprender
    clasificacion = comprender(texto)
    intencion = clasificacion.get("intencion", "desconocido")
    contenido = clasificacion.get("contenido", "")
    if intencion == "desconocido":
        decir(f"No identifico una acción clara en «{texto}» -- no tengo un comando para eso todavía.")
    else:
        detalle = f" (contenido: {contenido})" if contenido else ""
        decir(f"Identifiqué esto como una intención de tipo '{intencion}'{detalle}.")


# --------------------------------------------------------------------
# IMPACTO: quien mas usa una funcion, para saber que se rompe si la
# tocas. Distinto de "identificar_funcion" (que solo cuenta apariciones
# totales) -- esto dice DESDE DONDE la llaman.
# --------------------------------------------------------------------

def _es_llamada_a(nodo, nombre):
    return (
        isinstance(nodo, ast.Call)
        and (
            (isinstance(nodo.func, ast.Name) and nodo.func.id == nombre)
            or (isinstance(nodo.func, ast.Attribute) and nodo.func.attr == nombre)
        )
    )


def _llamadores_de(nombre):
    """[{'archivo':.., 'desde': nombre_de_la_funcion_que_la_llama_o_"nivel de módulo"}]
    para cada lugar del proyecto que llama a `nombre` (no cuenta su propia definición)."""
    llamadores = []
    for archivo, rel in _archivos_del_proyecto():
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo_top in arbol.body:
            if isinstance(nodo_top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if nodo_top.name == nombre:
                    continue  # su propia definición no es un "llamador"
                if any(_es_llamada_a(n, nombre) for n in ast.walk(nodo_top)):
                    llamadores.append({"archivo": rel, "desde": nodo_top.name})
            elif any(_es_llamada_a(n, nombre) for n in ast.walk(nodo_top)):
                llamadores.append({"archivo": rel, "desde": "nivel de módulo"})
    return llamadores


def analizar_impacto(nombre):
    """Para el comando 'impacto <nombre>' y como aviso previo al editar
    una función existente: quién más la llama en el proyecto."""
    if not nombre or not nombre.isidentifier():
        decir("Decime el nombre de una función, por ejemplo 'impacto ultimo_calculo'.")
        return
    llamadores = _llamadores_de(nombre)
    if not llamadores:
        decir(f"'{nombre}' no la llama nada más en el proyecto (al menos no por su nombre) -- tocarla es de bajo impacto.")
        return
    lugares = ", ".join(f"{l['desde']} ({l['archivo']})" for l in llamadores[:8])
    extra = f", y {len(llamadores) - 8} más" if len(llamadores) > 8 else ""
    decir(f"'{nombre}' la usan {len(llamadores)} lugar(es): {lugares}{extra}. Si le cambiás la firma o el comportamiento, esos lugares se pueden ver afectados.")


# --------------------------------------------------------------------
# MEMORIA DE ERRORES: cada vez que proponer_cambio_codigo.py detecta un
# error conocido (retorno inexistente, open sobre una carpeta), lo
# registra aca. La proxima vez que el pedido mencione esa funcion EN
# ESE MISMO ARCHIVO, se le avisa al modelo ANTES de intentar, no
# despues de fallar.
# --------------------------------------------------------------------

def _cargar_errores():
    if not ARCHIVO_ERRORES.exists():
        return {}
    try:
        return json.loads(ARCHIVO_ERRORES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _guardar_errores(errores):
    ARCHIVO_ERRORES.write_text(json.dumps(errores, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_error(archivo, funcion, detalle):
    """Guarda que, en `archivo`, usar `funcion` de cierta forma causó
    `detalle` (el mensaje de error concreto). Se llama automáticamente
    desde proponer_cambio_codigo.py -- no hace falta invocarlo a mano."""
    if not funcion:
        return
    errores = _cargar_errores()
    clave = f"{archivo}::{funcion}"
    entrada = errores.setdefault(clave, {"veces": 0, "detalles": []})
    entrada["veces"] += 1
    if detalle and detalle not in entrada["detalles"]:
        entrada["detalles"].append(detalle)
        entrada["detalles"] = entrada["detalles"][-3:]  # solo los 3 más recientes
    _guardar_errores(errores)


def pistas_aprendidas(archivo, instruccion):
    """Texto para agregar al prompt: advertencias de errores YA
    registrados para funciones que el pedido menciona, en ESE archivo.
    Cadena vacía si no hay nada aprendido que aplique."""
    errores = _cargar_errores()
    if not errores:
        return ""
    instruccion_norm = (instruccion or "").lower()
    avisos = []
    for clave, info in errores.items():
        arch, funcion = clave.split("::", 1)
        if arch != archivo or funcion.lower() not in instruccion_norm:
            continue
        avisos.append(f"- Con '{funcion}' ya se falló antes ({info['veces']} vez/veces): {info['detalles'][-1]}")
    if not avisos:
        return ""
    return "\nAPRENDIDO DE ERRORES PREVIOS EN ESTE ARCHIVO (no los repitas):\n" + "\n".join(avisos) + "\n"


# --------------------------------------------------------------------
# ESTIMA DIFICULTAD: antes de gastar un intento con el modelo, avisa si
# el pedido pinta complicado -- para sugerir partirlo en vez de
# descubrirlo recien despues de 3 intentos fallidos.
# --------------------------------------------------------------------

def _normalizar_para_buscar(texto):
    """minusculas, sin tildes, con guiones bajos como espacios -- para
    poder buscar 'ultimo_calculo' dentro de 'el último cálculo' aunque
    esten escritos distinto."""
    texto = (texto or "").lower().replace("_", " ")
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _funciones_mencionadas(instruccion, contenido_archivo):
    """Funciones REALES del archivo que la instrucción menciona, sea
    literal ('la función historial') o en lenguaje natural ('el último
    cálculo' -> ultimo_calculo). Más confiable que buscar solo la frase
    'función X': agarra menciones naturales, no solo las explícitas."""
    try:
        arbol = ast.parse(contenido_archivo or "")
    except SyntaxError:
        return set()
    instruccion_norm = _normalizar_para_buscar(instruccion)
    encontradas = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nombre_norm = _normalizar_para_buscar(nodo.name)
            if len(nombre_norm) >= 4 and nombre_norm in instruccion_norm:
                encontradas.add(nodo.name)
    return encontradas


def estimar_dificultad(archivo, instruccion, contenido_archivo):
    """Devuelve (nivel, motivos) donde nivel es 'bajo'/'medio'/'alto'."""
    motivos = []
    puntaje = 0

    _PALABRAS_COMUNES = {"que", "el", "la", "los", "las", "un", "una", "unos", "unas",
                          "de", "del", "para", "con", "al", "lo", "se", "y", "o"}
    nombres_explicitos = {
        n for n in re.findall(r"funci[oó]n\s+['\"]?([a-zA-Z_]\w*)", instruccion or "")
        if n.lower() not in _PALABRAS_COMUNES
    }
    nombres_mencionados = nombres_explicitos | _funciones_mencionadas(instruccion, contenido_archivo)
    if len(nombres_mencionados) > 1:
        puntaje += 20
        motivos.append(f"menciona varias funciones a la vez ({', '.join(sorted(nombres_mencionados))})")

    if len(instruccion or "") > 220:
        puntaje += 15
        motivos.append("el pedido es largo, con varias condiciones juntas")

    if len(contenido_archivo or "") > 8000:
        puntaje += 15
        motivos.append("el archivo es grande, hay mucho contexto para leer")

    errores = _cargar_errores()
    fallas_previas = sum(info["veces"] for clave, info in errores.items() if clave.startswith(archivo + "::"))
    if fallas_previas >= 2:
        puntaje += 20
        motivos.append(f"este archivo ya falló {fallas_previas} vez/veces antes con pedidos parecidos")

    nivel = "bajo" if puntaje < 20 else "medio" if puntaje < 45 else "alto"
    return nivel, motivos


# --------------------------------------------------------------------
# CALCULA PROBABILIDADES: riesgo estimado de una propuesta pendiente.
# Es una heuristica informativa -- el gate real (revisar_cambios_codigo.py)
# sigue siendo el que valida sintaxis y ejecucion antes de aplicar.
# --------------------------------------------------------------------

_PATRONES_RIESGO = [
    (re.compile(r"\bos\.remove\(|\bshutil\.rmtree\(|\.unlink\("), 25, "borra archivos"),
    (re.compile(r"\bsubprocess\.|\bos\.system\("), 25, "ejecuta comandos del sistema"),
    (re.compile(r"\beval\(|\bexec\("), 30, "ejecuta código dinámico (eval/exec)"),
    (re.compile(r"open\([^)]*[\"']w[\"']"), 10, "sobrescribe un archivo"),
    (re.compile(r"\bglobal\b"), 8, "modifica una variable global"),
]


def evaluar_riesgo(propuesta):
    """
    Puntaje de riesgo 0-100 (mas alto = mas delicado) para una propuesta
    de proponer_cambio_codigo.py, con la lista de motivos que suman.
    """
    motivos = []
    puntaje = 0

    if propuesta.get("archivo") in ARCHIVOS_PROTEGIDOS:
        puntaje += 40
        motivos.append("toca un archivo protegido del propio sistema de Arché")

    if propuesta.get("tipo") == "archivo_nuevo":
        puntaje += 5
        motivos.append("crea un archivo nuevo")

    codigo = (propuesta.get("buscar") or "") + "\n" + (propuesta.get("reemplazar") or "")
    for patron, peso, motivo in _PATRONES_RIESGO:
        if patron.search(codigo):
            puntaje += peso
            motivos.append(motivo)

    lineas_cambiadas = abs(
        len((propuesta.get("reemplazar") or "").splitlines())
        - len((propuesta.get("buscar") or "").splitlines())
    )
    if lineas_cambiadas > 15:
        puntaje += 10
        motivos.append(f"cambia {lineas_cambiadas} líneas de una sola vez")

    if str(propuesta.get("que", "")).lower().startswith("eliminar"):
        puntaje += 10
        motivos.append("elimina algo existente")

    puntaje = min(puntaje, 100)
    if not motivos:
        motivos.append("cambio acotado, sin patrones de riesgo conocidos")
    return puntaje, motivos


def calcular_riesgo_de(id_propuesta):
    """Para el comando 'riesgo <id>': busca la propuesta entre las
    pendientes y muestra su riesgo estimado."""
    propuesta = next((p for p in _cargar_pendientes() if p.get("id") == id_propuesta), None)
    if propuesta is None:
        decir(f"No encuentro ninguna propuesta pendiente con id '{id_propuesta}'.")
        return
    puntaje, motivos = evaluar_riesgo(propuesta)
    nivel = "bajo" if puntaje < 20 else "medio" if puntaje < 50 else "alto"
    decir(f"[{id_propuesta}] riesgo estimado: {puntaje}/100 ({nivel}). Motivos: {'; '.join(motivos)}.")


# --------------------------------------------------------------------
# RAPHAEL: objetivos -- seguimiento simple de metas del proyecto.
# --------------------------------------------------------------------

def _cargar_objetivos():
    if not ARCHIVO_OBJETIVOS.exists():
        return []
    try:
        return json.loads(ARCHIVO_OBJETIVOS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _guardar_objetivos(objetivos):
    ARCHIVO_OBJETIVOS.write_text(json.dumps(objetivos, ensure_ascii=False, indent=2), encoding="utf-8")


def agregar_objetivo(texto):
    texto = (texto or "").strip()
    if not texto:
        decir("¿Cuál es el objetivo?")
        return
    objetivos = _cargar_objetivos()
    if any(o["texto"] == texto and o["estado"] == "pendiente" for o in objetivos):
        decir("Ya tengo ese objetivo anotado.")
        return
    objetivos.append({"texto": texto, "estado": "pendiente"})
    _guardar_objetivos(objetivos)
    decir(f"Objetivo agregado: {texto}.")


def listar_objetivos():
    pendientes = [o for o in _cargar_objetivos() if o["estado"] == "pendiente"]
    if not pendientes:
        decir("No tengo objetivos pendientes anotados.")
        return
    decir(f"Tengo {len(pendientes)} objetivo(s) pendiente(s):")
    for o in pendientes:
        print(f"  • {o['texto']}")


def completar_objetivo(texto):
    texto = (texto or "").strip()
    objetivos = _cargar_objetivos()
    for o in objetivos:
        if o["texto"] == texto and o["estado"] == "pendiente":
            o["estado"] = "logrado"
            _guardar_objetivos(objetivos)
            decir(f"Marcado como logrado: {texto}.")
            return
    decir(f"No tengo un objetivo pendiente que diga exactamente «{texto}».")