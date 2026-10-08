"""
guia_comandos.py
----------------
Ubicacion: Arche/core/guia_comandos.py

Dos cosas que se mantienen al dia SOLAS, sin que tengas que editar
ninguna lista a mano:

  1. GUIA DE COMANDOS ('comandos', 'comandos <categoria>')
     Se arma en el momento juntando tres fuentes:
       - catalogo.py            (comando + descripcion de cada capacidad)
       - main.py                (se lee el codigo y se sacan todas las
                                 frases que compara contra 'comando')
       - comandos_extra.py      (funciones que Arche conecto con tu OK)
     Agregas un comando nuevo en main.py (o una entrada al catalogo) y
     aparece en la guia la proxima vez que la pidas. Si todavia no tiene
     descripcion lo muestra igual, marcado, para que no quede escondido.
     Los comandos que aparecieron desde la ultima vez que miraste la
     guia salen con "NUEVO".

  2. PROXIMOS PASOS ('proximos pasos', 'que hago ahora')
     Mira el estado REAL (cuantos ejemplos hay por intencion, que redes
     del jerarquico estan activas, como va el examen) y te dice que
     comando conviene correr ahora, y por que.

No necesita Ollama ni modelos de embeddings: lee archivos y el estado
guardado, asi que es instantaneo.
"""

import ast
import json
import os
import unicodedata
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))        # .../Arche/core
RAIZ = os.path.dirname(BASE)                              # .../Arche
ARCHIVO_MAIN = os.path.join(RAIZ, "main.py")
ARCHIVO_VISTOS = os.path.join(BASE, "IA", "guia_comandos_vistos.json")
ARCHIVO_EJEMPLOS_MANUALES = os.path.join(BASE, "IA", "ejemplos_manuales.txt")

# Con menos de esto por intencion, una red tiene poco de donde aprender.
# (El minimo "tecnico" para entrenar es MIN_EJEMPLOS_POR_CLASE; esto es
# la meta razonable para que generalice, no un requisito.)
META_EJEMPLOS_POR_INTENCION = 20

_NOMBRES_DE_COMANDO = {"comando", "comando_original"}


def _norm(texto):
    texto = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


# --------------------------------------------------------------------
# Descripciones de comandos que existen en main.py pero NO tienen
# entrada propia en el catalogo. Clave: el comando normalizado (sin
# tildes). Valor: (categoria, descripcion).
# --------------------------------------------------------------------
DESCRIPCIONES_EXTRA = {
    "comandos": ("guia", "Esta guia. Se arma sola desde main.py y el catalogo."),
    "comandos de": ("guia", "comandos <categoria>: el detalle de UNA categoria, con descripciones."),
    "proximos pasos": ("guia", "Te dice que comando correr ahora segun el estado del entrenamiento."),
    "intenciones de": ("entrenamiento", "intenciones <dominio>: solo las intenciones de ese dominio."),
    "ensenar": ("entrenamiento", "ensenar <frase> => <intencion>: agrega UN ejemplo a mano."),
    "importar ejemplos": ("entrenamiento", "Carga varios ejemplos de golpe desde ejemplos_manuales.txt."),
    "intenciones": ("entrenamiento", "Lista las intenciones validas (para saber como llamarlas al ensenar)."),
    "sembrar catalogo": ("entrenamiento", "Siembra instantanea de ejemplos base desde el catalogo (sin Ollama)."),
    "entrenar rapido": ("entrenamiento", "Genera ejemplos con Ollama, sin juez, en segundo plano."),
    "entrenar a fondo": ("entrenamiento", "Genera y JUZGA ejemplos con Ollama: mas lento, mas limpio."),
    "detener entrenamiento": ("entrenamiento", "Corta el entrenamiento en segundo plano."),
    "estado banco": ("entrenamiento", "Cuantos ejemplos hay por intencion."),
    "entrenar jerarquico": ("entrenamiento", "Entrena a mano el clasificador jerarquico (tambien se reentrena solo cada pocos ejemplos)."),
    "estado red jerarquica": ("entrenamiento", "Que redes del jerarquico estan activas y con que precision."),
    "examen": ("examen", "Una ronda de examen: Arche se prueba y refuerza lo que falla."),
    "estado examen": ("examen", "Nivel y racha de cada dominio; si el examen automatico esta corriendo."),
    "iniciar examen automatico": ("examen", "Examen en segundo plano mientras Arche este abierta."),
    "detener examen automatico": ("examen", "Para el examen automatico."),
    "adios": ("sistema", "Cierra a Arche."),
    "cuanto es": ("calculadora", "cuanto es <operacion>: lo mismo que 'calcula'."),
    "escribe en": ("codigo", "escribe en <archivo> : <instruccion>: pide un cambio de codigo indicando tu el archivo."),
    "conecta": ("codigo", "conecta <funcion>: conecta a una frase una funcion que Arche escribio (pide tu aprobacion)."),
    "cambia esto": ("codigo", "cambia esto: <instruccion>: Arche propone un cambio en su propio codigo (pasa por tu aprobacion)."),
    "revisa tu codigo sin ia": ("codigo", "Autorevision solo con chequeos fijos: sin Ollama, instantanea."),
    "autorevisate cada": ("codigo", "autorevisate cada <horas>: cambia cada cuanto se autorevisa sola."),
    "modo gran sabio on": ("arche", "Activa el tono analitico del Gran Sabio al hablar."),
    "modo gran sabio off": ("arche", "Desactiva el tono analitico del Gran Sabio."),
    "modo natural on": ("entrenamiento", "Entiende frases libres para todo el catalogo."),
    "modo natural off": ("entrenamiento", "Vuelve a pedir los comandos tal cual."),
}

# Comandos del control del PC que main.py resuelve con funciones (no con un
# 'if comando == ...' literal), asi que la lectura de main.py no los ve.
# Clave normalizada -> (comando a mostrar, descripcion).
COMANDOS_CONTROL_PC = {
    "espera": ("computador", "espera <N> segundos", "Pausa de N segundos (sirve entre pasos encadenados)."),
    "varios pasos": ("computador", "<orden> y luego <orden> [y luego <orden>...]",
                     "Encadena varias ordenes del PC o de la web, por ejemplo: abre chrome y luego busca gatos en youtube."),
    "mis ventanas": ("computador", "mis ventanas", "Lista las ventanas que tienes abiertas."),
    "busca en un sitio": ("web", "busca <algo> en youtube | claude | google | chatgpt | wikipedia | github | spotify | maps | <cualquier sitio que conozca o dominio>",
                          "Abre la busqueda directo en ese sitio. Si hay mas de un navegador, pregunta en cual."),
}

ORDEN_EXTRAS = ["guia", "entrenamiento", "examen"]
CATEGORIA_CONECTADOS = "conectados por arche"
CATEGORIA_OTROS = "otros"


# --------------------------------------------------------------------
# Fuente 1: main.py (leido como codigo, no como texto)
# --------------------------------------------------------------------

def _es_nombre_comando(nodo):
    return isinstance(nodo, ast.Name) and nodo.id in _NOMBRES_DE_COMANDO


def _strings(nodo):
    """Lista de strings si `nodo` es un str o una lista/tupla/set de str;
    None si trae algo que no es un literal."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return [nodo.value]
    if isinstance(nodo, (ast.List, ast.Tuple, ast.Set)):
        salida = []
        for elemento in nodo.elts:
            if not (isinstance(elemento, ast.Constant) and isinstance(elemento.value, str)):
                return None
            salida.append(elemento.value)
        return salida
    return None


def _literales_del_test(test):
    """[(texto, es_prefijo)] de las frases que un `if` compara contra
    'comando'. Entiende: comando == "x", comando in [...],
    comando.startswith("x" | ("x","y")), y las combinaciones con `or`."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        salida = []
        for valor in test.values:
            salida.extend(_literales_del_test(valor))
        return salida

    if isinstance(test, ast.Compare) and len(test.ops) == 1 and _es_nombre_comando(test.left):
        if isinstance(test.ops[0], (ast.Eq, ast.In)):
            textos = _strings(test.comparators[0])
            return [(t, False) for t in textos] if textos else []
        return []

    if (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)
            and test.func.attr == "startswith" and _es_nombre_comando(test.func.value)
            and test.args):
        textos = _strings(test.args[0])
        return [(t, True) for t in textos] if textos else []

    return []


def comandos_de_main(ruta=None):
    """
    [{"principal", "alias": [...], "prefijo": bool, "linea": int}] -- un
    elemento por cada `if` de main.py que decide un comando. Si main.py
    no se puede leer o no compila, devuelve [] (la guia sigue andando
    con las otras dos fuentes).
    """
    try:
        # (ARCHIVO_MAIN se lee AQUI y no como valor por defecto: un default
        # se fija al definir la funcion y no seguiria cambios posteriores.)
        with open(ruta or ARCHIVO_MAIN, "r", encoding="utf-8") as f:
            arbol = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return []

    grupos, vistos = [], set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.If):
            continue
        literales = _literales_del_test(nodo.test)
        if not literales:
            continue
        principal, es_prefijo = literales[0]
        clave = _norm(principal)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        alias = []
        for texto, _ in literales[1:]:
            if _norm(texto) != clave and texto not in alias:
                alias.append(texto)
        grupos.append({"principal": principal.strip(), "alias": alias,
                       "prefijo": es_prefijo, "linea": nodo.lineno})
    grupos.sort(key=lambda g: g["linea"])
    return grupos


# --------------------------------------------------------------------
# Fuente 2: catalogo.py     Fuente 3: comandos_extra.py
# --------------------------------------------------------------------

def _indice_catalogo():
    """{comando normalizado (sin '{X}') : entrada} del catalogo."""
    try:
        from core.IA import catalogo
    except Exception:
        return {}, []
    indice = {}
    for entrada in catalogo.ENTRADAS:
        comando = entrada.get("comando")
        if not comando:
            continue
        indice[_norm(comando.split("{X}")[0])] = entrada
    return indice, [e["dominio"] for e in catalogo.ENTRADAS]


def _comandos_conectados():
    try:
        from core import comandos_extra
        return dict(comandos_extra.COMANDOS)
    except Exception:
        return {}


# --------------------------------------------------------------------
# La guia
# --------------------------------------------------------------------

def construir_guia():
    """
    {categoria: [{"comando", "alias", "descripcion", "clave"}]}
    La categoria viene del catalogo cuando el comando esta ahi; si no,
    de DESCRIPCIONES_EXTRA; si tampoco, cae en 'otros' sin descripcion.
    """
    indice, dominios_en_orden = _indice_catalogo()
    guia = {}

    def _sumar(categoria, comando, alias, descripcion, clave):
        guia.setdefault(categoria, []).append({
            "comando": comando, "alias": alias,
            "descripcion": descripcion, "clave": clave,
        })

    claves_cubiertas = set()

    for grupo in comandos_de_main():
        clave = _norm(grupo["principal"])
        candidatos = [clave] + [_norm(a) for a in grupo["alias"]]

        entrada = next((indice[c] for c in candidatos if c in indice), None)
        if entrada is not None:
            comando = entrada["comando"].replace("{X}", f"<{entrada.get('argumento') or 'dato'}>")
            _sumar(entrada["dominio"], comando, grupo["alias"], entrada["descripcion"], clave)
        else:
            extra = next((DESCRIPCIONES_EXTRA[c] for c in candidatos if c in DESCRIPCIONES_EXTRA), None)
            comando = grupo["principal"] + (" <...>" if grupo["prefijo"] else "")
            if extra:
                _sumar(extra[0], comando, grupo["alias"], extra[1], clave)
            else:
                _sumar(CATEGORIA_OTROS, comando, grupo["alias"], None, clave)
        claves_cubiertas.update(candidatos)

    # Capacidades del catalogo con comando propio que main.py no
    # menciona tal cual (las maneja por otro camino): igual se listan.
    for clave, entrada in indice.items():
        if clave in claves_cubiertas or not clave:
            continue
        comando = entrada["comando"].replace("{X}", f"<{entrada.get('argumento') or 'dato'}>")
        _sumar(entrada["dominio"], comando, [], entrada["descripcion"], clave)

    for clave, (categoria, comando, descripcion) in COMANDOS_CONTROL_PC.items():
        _sumar(categoria, comando, [], descripcion, clave)

    ya_listadas = {c["clave"] for items in guia.values() for c in items}
    for frase, definicion in _comandos_conectados().items():
        if _norm(frase) in ya_listadas:
            continue  # ya aparece (p. ej. tambien tiene entrada en el catalogo)
        modulo, funcion = definicion[0], definicion[1]
        _sumar(CATEGORIA_CONECTADOS, frase, [], f"Llama a {modulo}.{funcion}()", _norm(frase))

    orden = []
    for categoria in dominios_en_orden + ORDEN_EXTRAS + [CATEGORIA_CONECTADOS]:
        if categoria in guia and categoria not in orden:
            orden.append(categoria)
    for categoria in guia:
        if categoria not in orden and categoria != CATEGORIA_OTROS:
            orden.append(categoria)
    if CATEGORIA_OTROS in guia:
        orden.append(CATEGORIA_OTROS)
    return {categoria: guia[categoria] for categoria in orden}


def _cargar_vistos():
    try:
        with open(ARCHIVO_VISTOS, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return None   # None = primera vez: no marcar todo como "nuevo"


def _guardar_vistos(claves):
    try:
        with open(ARCHIVO_VISTOS, "w", encoding="utf-8") as f:
            json.dump(sorted(claves), f, ensure_ascii=False, indent=1)
    except OSError:
        pass  # no poder guardar esto no debe romper la guia


def _buscar_categoria(guia, texto):
    texto = _norm(texto)
    if not texto:
        return None
    for nombre in guia:
        if texto == _norm(nombre):
            return nombre
    for nombre in guia:
        if texto in _norm(nombre) or _norm(nombre) in texto:
            return nombre
    return None


def texto_para_archivo():
    """La guia completa como texto plano, para guardarla en un .txt.
    Sin lineas decorativas: solo titulos en mayuscula y una linea por comando."""
    guia = construir_guia()
    lineas = ["COMANDOS DE ARCHÉ",
              "Este archivo se actualiza solo cada vez que Arché arranca.",
              "No lo edites a mano: tus cambios se pierden."]
    for nombre, items in guia.items():
        lineas.append("")
        lineas.append(nombre.upper())
        for item in items:
            linea = f"  {item['comando']}"
            if item["descripcion"]:
                linea += f"  -  {item['descripcion']}"
            lineas.append(linea)
            if item["alias"]:
                lineas.append(f"      También: {', '.join(item['alias'])}")
    return "\n".join(lineas) + "\n"


# Nombre del archivo que se mantiene al dia. Vive en Herrmientas/ (la carpeta
# de utilidades del proyecto, hermana de Arche/), al lado de Comandos.txt,
# que son tus notas personales y NO se toca.
ARCHIVO_GUIA_TXT = os.path.join(os.path.dirname(RAIZ), "Herrmientas", "Comandos de Arche.txt")


def exportar_guia_a_archivo(ruta=None):
    """Escribe la guia en 'Herrmientas/Comandos de Arche.txt'. Solo
    reescribe si el contenido cambio. Nunca rompe a Arche: si no se
    puede escribir (carpeta no existe, solo lectura, .exe empaquetado),
    devuelve False sin hacer ruido."""
    ruta = ruta or ARCHIVO_GUIA_TXT
    try:
        texto = texto_para_archivo()
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                if f.read() == texto:
                    return True
        except OSError:
            pass
        carpeta = os.path.dirname(ruta)
        if not os.path.isdir(carpeta):
            return False
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        return True
    except Exception:
        return False


def mostrar_guia(categoria=None, actualizar_vistos=True, completo=False):
    """Imprime la guia. Sin argumento: resumen de todo. Con categoria:
    detalle con descripciones y alias. Devuelve el texto impreso."""
    guia = construir_guia()
    vistos = _cargar_vistos()
    todas = {c["clave"] for items in guia.values() for c in items}
    nuevas = set() if vistos is None else (todas - vistos)

    lineas = []
    if categoria:
        nombre = _buscar_categoria(guia, categoria)
        if nombre is None:
            encontrados = buscar_en_guia(categoria)       # no es una categoria: lo busco como palabra
            if encontrados:
                return ""
            lineas.append(f"Arché: Las categorías son: {', '.join(guia)}.")
        else:
            lineas.append("")
            lineas.append(f"   {nombre.upper()}")
            for item in guia[nombre]:
                marca = "  🆕 NUEVO" if item["clave"] in nuevas else ""
                lineas.append(f"\n• {item['comando']}{marca}")
                lineas.append(f"  {item['descripcion'] or '(sin descripción todavía — agregala en DESCRIPCIONES_EXTRA o en el catálogo)'}")
                if item["alias"]:
                    lineas.append(f"  También: {', '.join(item['alias'])}")
            lineas.append("")
    elif completo:
        lineas.append("")
        lineas.append("   GUÍA COMPLETA DE COMANDOS (se actualiza sola)")
        for nombre, items in guia.items():
            lineas.append(f"\n• {nombre.upper()}")
            for item in items:
                marca = "  🆕" if item["clave"] in nuevas else ""
                lineas.append(f"    - {item['comando']}{marca}")
        if nuevas:
            lineas.append(f"\n🆕 = apareció desde la última vez que miraste la guía ({len(nuevas)}).")
    else:
        lineas.append("")
        lineas.append("   GUÍA DE COMANDOS (resumen; se actualiza sola)")
        for nombre, items in guia.items():
            hay_nuevos = sum(1 for i in items if i["clave"] in nuevas)
            ejemplos = ", ".join(i["comando"] for i in items[:3])
            extra = f"  🆕{hay_nuevos}" if hay_nuevos else ""
            lineas.append(f"\n• {nombre.upper()} ({len(items)}){extra}\n    {ejemplos}…")
        if nuevas:
            lineas.append(f"\n🆕 = comandos que aparecieron desde la última vez ({len(nuevas)}).")
        lineas.append("\n'comandos <categoría>' = detalle de una · 'comandos buscar <palabra>' = encontrar uno "
                      "· 'comandos todo' = la lista entera · 'próximos pasos' = qué correr ahora.")

    texto = "\n".join(lineas)
    print(texto)
    if actualizar_vistos:
        _guardar_vistos(todas)
    return texto


def buscar_en_guia(texto, maximo=12):
    """Busca comandos por palabra (en el comando, la descripcion y los alias).
    Imprime y devuelve la lista de coincidencias [(categoria, comando, descripcion)]."""
    palabras = [w for w in _norm(texto).split() if len(w) > 1]
    resultados = []
    if palabras:
        for categoria, items in construir_guia().items():
            for item in items:
                fajo = _norm(" ".join([item["comando"], item["descripcion"] or "", " ".join(item["alias"] or [])]))
                if all(w in fajo for w in palabras):
                    resultados.append((categoria, item["comando"], item["descripcion"] or ""))
    if not palabras:
        print("Arché: Dime qué buscas, por ejemplo 'comandos buscar volumen'.")
    elif not resultados:
        print(f"Arché: No encontré comandos con '{texto.strip()}'. Prueba con otra palabra o 'comandos todo'.")
    else:
        print(f"Arché: Encontré {len(resultados)} comando(s) con '{texto.strip()}':")
        for categoria, comando, desc in resultados[:maximo]:
            print(f"  • {comando}  ({categoria.lower()})" + (f" - {desc}" if desc else ""))
        if len(resultados) > maximo:
            print(f"  … y {len(resultados) - maximo} más; afina la búsqueda con otra palabra.")
    return resultados


# --------------------------------------------------------------------
# Proximos pasos: recomendaciones segun el estado real
# --------------------------------------------------------------------

def _ejemplos_manuales_pendientes():
    """Lineas de ejemplos_manuales.txt que todavia no entraron al banco
    (0 si el archivo no cambio desde la ultima vez que se importo)."""
    try:
        from core.IA import ensenar
        return ensenar.lineas_pendientes(ARCHIVO_EJEMPLOS_MANUALES)
    except Exception:
        return 0


def calcular_proximos_pasos():
    """[(comando, razon)] ordenado por prioridad. Cada fuente de estado
    va en su propio try/except: si una falla (p. ej. no hay datos
    todavia) se sigue con las demas."""
    pasos = []

    # --- banco de ejemplos ---
    conteo, total_datos, sin_embedding = Counter(), 0, 0
    try:
        from core.IA import aprendizaje, catalogo
        from core.IA.clasificador import MIN_EJEMPLOS_POR_CLASE
        datos = aprendizaje.cargar()
        total_datos = len(datos)
        sin_embedding = sum(1 for d in datos if not d.get("embedding"))
        conteo = Counter(d.get("accion") for d in datos if d.get("embedding"))

        ids = [e["id"] for e in catalogo.ENTRADAS]
        if total_datos == 0:
            pasos.append(("sembrar catalogo",
                        "Todavía no hay ningún ejemplo. Esto siembra una base para todas las intenciones, sin Ollama."))
        else:
            vacias = [i for i in ids if conteo.get(i, 0) == 0]
            if vacias:
                muestra = ", ".join(vacias[:6]) + ("…" if len(vacias) > 6 else "")
                pasos.append(("sembrar catalogo",
                            f"{len(vacias)} intención(es) no tienen ningún ejemplo con embedding ({muestra})."))
            flacas = [i for i in ids if 0 < conteo.get(i, 0) < META_EJEMPLOS_POR_INTENCION]
            if flacas:
                muestra = ", ".join(f"{i} ({conteo[i]})" for i in sorted(flacas, key=conteo.get)[:6])
                pasos.append(("entrenar rapido",
                            f"{len(flacas)} intención(es) tienen menos de {META_EJEMPLOS_POR_INTENCION} ejemplos: {muestra}. "
                            f"Más ejemplos DISTINTOS entre sí ayudan; si prefieres controlarlos tú: "
                            f"'ensenar <frase> => <intencion>' o 'importar ejemplos'."))
            bajo_minimo = [i for i in ids if 0 < conteo.get(i, 0) < MIN_EJEMPLOS_POR_CLASE]
            if bajo_minimo:
                pasos.append(("intenciones",
                            f"{len(bajo_minimo)} están por debajo del mínimo para entrenar ({MIN_EJEMPLOS_POR_CLASE}); "
                            f"'intenciones' muestra los nombres válidos para enseñarles."))
        if sin_embedding:
            pasos.append(("(sin comando)",
                        f"{sin_embedding} ejemplo(s) guardados sin embedding: no cuentan para entrenar. "
                        f"Suele pasar si sentence-transformers no estaba disponible cuando se aprendieron."))
    except Exception as e:
        pasos.append(("(sin comando)", f"No pude leer el banco de ejemplos ({type(e).__name__}: {e})."))

    pendientes = _ejemplos_manuales_pendientes()
    if pendientes:
        pasos.insert(0, ("importar ejemplos",
                        f"Hay {pendientes} línea(s) en ejemplos_manuales.txt esperando entrar al banco."))

    # --- clasificador jerarquico ---
    activos_dominio = set()
    try:
        from core.IA.clasificador_jerarquico import info_jerarquico
        info = info_jerarquico()
        inactivos = [k for k, v in info.items() if not v.get("activo")]
        if not info.get("dominio", {}).get("activo"):
            pasos.append(("entrenar jerarquico",
                        "La red de dominio todavía no está activa. Se reentrena sola cada 5 ejemplos nuevos, "
                        "pero si ya hay datos suficientes puedes forzarlo."))
        elif inactivos:
            pasos.append(("entrenar jerarquico",
                        f"{len(inactivos)} red(es) siguen inactivas: {', '.join(inactivos[:6])}"
                        f"{'…' if len(inactivos) > 6 else ''}. Se activan al juntar ejemplos suficientes."))
        activos_dominio = {k for k, v in info.items() if v.get("activo")}
    except Exception:
        pass

    # --- examen ---
    try:
        from core.IA import examen
        progreso = examen._cargar_progreso()
        if "dominio" in activos_dominio:
            if not progreso.get("automatico_corriendo"):
                pasos.append(("iniciar examen automatico",
                            f"El jerárquico ya puede examinarse (nivel grupal {progreso['nivel_grupal']}). "
                            f"Cada fallo se convierte en un ejemplo nuevo, sin que hagas nada."))
        else:
            pasos.append(("(espera)", "El examen necesita que la red de dominio esté activa primero."))
    except Exception:
        pass

    if not pasos:
        pasos.append(("estado examen", "Todo se ve al día. Mira cómo va el examen o deja el examen automático corriendo."))
    return pasos


def mostrar_proximos_pasos():
    pasos = calcular_proximos_pasos()
    lineas = ["", "PRÓXIMOS PASOS (según el estado de ahora mismo):"]
    for n, (comando, razon) in enumerate(pasos, start=1):
        lineas.append(f"\n  {n}. {comando}")
        lineas.append(f"     {razon}")
    lineas.append("")
    texto = "\n".join(lineas)
    print(texto)
    return texto