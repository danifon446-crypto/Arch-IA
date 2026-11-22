"""
resolver.py
-----------
Ubicacion: Arche/core/nucleo/resolver.py

RESOLVER AL VUELO: cuando le pides algo que Arché no sabe hacer, en vez de «no sé, lo intento
esta noche», lo resuelve en ese momento y aprende de ello.

  1. Primero mira si ya tiene una habilidad para eso (las que fabricó, cazó o aprendió aquí).
  2. Si no, el modelo (la nube si está conectada; si no, Ollama) escribe un programa CORTO solo
     para tu pedido. Arché lo revisa (sin internet, sin tocar archivos, sin comandos del sistema),
     lo corre aislado y con límite de tiempo, y te da el resultado.
     Si el programa falla, le muestra el error al modelo para que lo corrija (hasta 2 veces).
  3. Guarda cada pedido resuelto. Cuando un mismo TIPO de pedido funciona 3 veces, escribe una
     HABILIDAD permanente para ese tipo, usando tus pedidos reales como pruebas (así la prueba
     no es inventada), y la instala. La próxima vez responde al instante con ella.

Qué puede resolver: cálculos, conversiones, fechas y días, porcentajes, estadísticas, textos
(contar, invertir, ordenar, mayúsculas...), números romanos o binarios, generar contraseñas o
listas, etc. Lo que necesita internet, tu cuenta, archivos o el PC lo hacen los comandos de
Arché, no esto: si el modelo ve que no se puede con un programa, lo dice y Arché sigue como antes.

Cuándo entra:
  * con pedidos de cálculo o texto claros (convierte, cuántos ... hay en, qué día cae, promedio,
    porcentaje, al revés, en binario, romano...), antes que la charla, para que la respuesta salga
    de un cálculo de verdad y no de lo que el modelo "cree";
  * con cualquier orden que Arché no entendió.

Comandos: resuelve: <pedido> · qué aprendiste resolviendo · resolver apagado / encendido
"""

import ast
import re
import tempfile
import threading

from core.nucleo import comun

ARCH = comun.ruta("resolver.json")
INTENTOS = 3
VECES_PARA_HABILIDAD = 3
TIEMPO_PROGRAMA = 20

MODULOS_PERMITIDOS = {"math", "cmath", "statistics", "fractions", "decimal", "datetime", "calendar", "time", "re",
                      "string", "random", "secrets", "itertools", "functools", "collections", "json", "unicodedata",
                      "textwrap", "operator", "bisect", "heapq", "numbers", "zoneinfo", "difflib", "hashlib",
                      "base64", "binascii", "uuid", "locale", "enum", "dataclasses", "typing"}
LLAMADAS_PROHIBIDAS = {"eval", "exec", "compile", "__import__", "open", "input", "breakpoint", "exit", "quit",
                       "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview"}

# Pedidos que claramente son de calcular: necesitan un número en la frase...
_CALCULO_CON_NUMERO = re.compile(
    r"\b(convierte|convertir|conviertas|pasa(?:me|r)?|equivale[n]?|cuant[oa]s?|porcentaje|por\s+ciento|promedio|"
    r"media|mediana|desviacion|raiz|factorial|primo|primos|mcd|mcm|maximo\s+comun|minimo\s+comun|binario|"
    r"hexadecimal|octal|romano|romanos|interes|cuota|propina|dividido|multiplicado|elevado|potencia|"
    r"descuento|iva)\b|\d\s*%")
# ...o son de texto/fechas sin lugar a dudas (no necesitan número).
_CALCULO_SIN_NUMERO = re.compile(
    r"\b(que\s+dia\s+(?:cae|cayo|fue|sera)|cuantos\s+dias\s+(?:faltan|hay|quedan|han\s+pasado)|"
    r"al\s+reves|invierte\s+(?:el\s+texto|la\s+frase|la\s+palabra|esto)|"
    r"cuenta\s+(?:las\s+)?(?:letras|palabras|vocales|consonantes|caracteres)|"
    r"ordena\s+(?:alfabeticamente|de\s+menor|de\s+mayor|estas\s+palabras|estos\s+nombres)|"
    r"genera(?:me)?\s+(?:una\s+)?(?:contrasena|clave\s+segura)|en\s+numeros\s+romanos|"
    r"en\s+mayusculas|en\s+minusculas|deletrea|es\s+(?:un\s+)?palindromo|son\s+anagramas)\b")
# Lo que NO es para esto aunque tenga números (lo hacen otros comandos de Arché).
_NO_ES_PARA_MI = re.compile(
    r"\b(alarma|recordatorio|recuerdame|temporizador|avisame|volumen|brillo|abre|abrir|cierra|pon\s+musica|"
    r"reproduce|busca\s+en|youtube|spotify|servo|perro|mision|caza|noticias|clima|nota)\b")

_lock = threading.Lock()


# ------------------------------------------------------------------
# Estado
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("resueltos", [])        # [{pedido, tipo, codigo, salida, cuando}]
    e.setdefault("habilidades", {})      # tipo -> nombre de la habilidad aprendida
    e.setdefault("fallidos", [])
    return e


def _guardar(e):
    e["resueltos"] = e["resueltos"][-300:]
    e["fallidos"] = e["fallidos"][-100:]
    comun.guardar(ARCH, e)


def activo():
    return bool(_estado()["activo"])


def parece_calculo(texto):
    t = comun.norm(texto)
    if _NO_ES_PARA_MI.search(t):
        return False
    if re.search(r"\d", t) and _CALCULO_CON_NUMERO.search(t):
        return True
    return bool(_CALCULO_SIN_NUMERO.search(t))


# ------------------------------------------------------------------
# Revisar y correr el programa
# ------------------------------------------------------------------

def revisar_programa(codigo):
    """(ok, motivo). Solo librería estándar segura, sin archivos, sin red, sin comandos ni trucos."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError as e:
        return False, f"error de sintaxis en la línea {e.lineno} ({e.msg})"
    for n in ast.walk(arbol):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            nombres = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for m in nombres:
                if m.split(".")[0] not in MODULOS_PERMITIDOS:
                    return False, f"usa el módulo {m}, que no está permitido (solo librería estándar sin red ni archivos)"
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in LLAMADAS_PROHIBIDAS:
                return False, f"usa {f.id}(), que no está permitido"
        elif isinstance(n, ast.Attribute) and n.attr.startswith("__") and n.attr != "__name__":
            return False, f"usa {n.attr}, que no está permitido"
        elif isinstance(n, ast.Name) and n.id.startswith("__") and n.id not in ("__name__",):
            return False, f"usa {n.id}, que no está permitido"
    if not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print" for n in ast.walk(arbol)):
        return False, "no imprime la respuesta con print()"
    return True, "ok"


def correr(codigo):
    """(ok, salida) corriendo el programa aislado, en una carpeta temporal y con límite de tiempo."""
    from core import evolucion as evo
    with tempfile.TemporaryDirectory(prefix="arche_resolver_") as tmp:
        ok, salida = evo._correr_aislado(codigo, cwd=tmp, tiempo=TIEMPO_PROGRAMA)
    salida = (salida or "").strip()
    if ok and not salida:
        return False, "no imprimió nada"
    return ok, salida


_FORMATO_PROGRAMA = (
    "Reglas del programa:\n"
    "  • Python 3, SOLO librería estándar segura (math, datetime, calendar, statistics, fractions, decimal, re, "
    "random, secrets, itertools, collections, string, unicodedata...).\n"
    "  • Nada de internet, archivos, os, subprocess, input(), eval ni exec.\n"
    "  • Los datos del pedido van escritos dentro del programa.\n"
    "  • Al final imprime con print() UNA respuesta corta y clara en español, como se la dirías a una persona "
    "(con el número o el resultado y su unidad).\n"
    "  • Si el pedido NO se puede resolver con un programa así (necesita internet, archivos, el PC, la cuenta "
    "de alguien u opiniones), responde exactamente: NO_SE_PUEDE: <por qué en pocas palabras>\n"
    "Responde SOLO con el código en un bloque ```python (o con la línea NO_SE_PUEDE).")


def _ahora_texto():
    d = comun.ahora()
    dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    return f"{dias[d.weekday()]} {d.strftime('%Y-%m-%d %H:%M')}"


def resolver(pedido, avisar=None):
    """(ok, texto, codigo). ok=None quiere decir «esto no es para un programa»."""
    avisar = avisar or (lambda t: None)
    base = (f"Pedido de {comun.nombre_usuario()} a Arché: «{pedido}»\n"
            f"(Fecha y hora actual: {_ahora_texto()}, Colombia.)\n"
            "Escribe un programa corto de Python que lo resuelva.\n" + _FORMATO_PROGRAMA)
    respuesta = comun.pensar(base, temperatura=0.1, codigo=True, max_tokens=1200)
    if re.search(r"\bNO_SE_PUEDE\b", respuesta or ""):
        return None, re.sub(r"(?s).*NO_SE_PUEDE\s*:?\s*", "", respuesta).strip()[:200], ""
    codigo = comun.extraer_codigo(respuesta)
    if not codigo:
        return False, "el modelo no respondió", ""
    problema = ""
    for intento in range(INTENTOS):
        ok, motivo = revisar_programa(codigo)
        if ok:
            ok, salida = correr(codigo)
            if ok:
                return True, salida[-1500:], codigo
            lineas = [l for l in salida.splitlines() if l.strip() and "File " not in l
                      and not set(l.strip()) <= set("~^ ")][-4:]
            problema = "al correrlo falló: " + " | ".join(l.strip() for l in lineas)[:400]
        else:
            problema = motivo
        if intento == INTENTOS - 1:
            break
        avisar("Lo corrijo y vuelvo a probar...")
        nuevo = comun.extraer_codigo(comun.pensar(
            f"{base}\n\nTu programa anterior tuvo un problema: {problema}\n"
            f"PROGRAMA ANTERIOR:\n```python\n{codigo[:4000]}\n```\nDevuélvelo corregido.",
            temperatura=0.1, codigo=True, max_tokens=1200))
        if nuevo:
            codigo = nuevo
    return False, problema, codigo


# ------------------------------------------------------------------
# Aprender: de pedidos resueltos a una habilidad permanente
# ------------------------------------------------------------------

def tipo_de(pedido):
    """Una «forma» del pedido para agrupar los parecidos: sin números ni palabras de relleno."""
    t = re.sub(r"\d+(?:[.,]\d+)?", " ", comun.norm(pedido))
    palabras = sorted(p for p in comun.palabras(t) if not p.isdigit())
    return " ".join(palabras[:6])


def _parecidos(e, pedido):
    return [r for r in e["resueltos"] if comun.parecido(r["pedido"], pedido) >= 0.34]


def anotar_resuelto(pedido, codigo, salida):
    with _lock:
        e = _estado()
        e["resueltos"].append({"pedido": pedido, "tipo": tipo_de(pedido), "codigo": codigo[-3000:],
                               "salida": salida[:500], "cuando": comun.ahora_txt()})
        _guardar(e)
        parecidos = _parecidos(e, pedido)
    if len(parecidos) >= VECES_PARA_HABILIDAD and not _ya_hay_habilidad(pedido):
        comun.en_hilo(aprender_habilidad, parecidos[-6:], nombre="arche-resolver-aprende")


def _ya_hay_habilidad(pedido):
    e = _estado()
    return any(comun.parecido(tipo, tipo_de(pedido)) >= 0.5 for tipo in e["habilidades"])


def aprender_habilidad(ejemplos):
    """Escribe e instala una habilidad general a partir de pedidos reales ya resueltos."""
    from core import evolucion as evo
    from core.nucleo import depredador
    casos = "\n".join(f"  pedido: {r['pedido']!r}\n  respuesta correcta: {r['salida']!r}" for r in ejemplos)
    pedido = (
        "Arché ya resolvió estos pedidos parecidos con programas sueltos. Escribe UNA habilidad general que "
        "resuelva cualquier pedido de este tipo, entendiendo la frase en español.\n\n" + casos + "\n\n"
        "Formato OBLIGATORIO (un solo módulo Python):\n"
        "  def ejecutar(texto: str) -> str   # recibe la frase y devuelve la respuesta en español\n"
        "  def probar() -> None              # un assert por CADA pedido de arriba: ejecutar(pedido) debe "
        "contener el número o dato principal de su respuesta correcta\n"
        "  PALABRAS = [...]                  # palabras clave específicas de este tipo de pedido\n"
        "  DESCRIPCION = '...'\n"
        "Solo librería estándar; nada de internet, archivos, os, subprocess, eval ni exec.\n"
        "Responde SOLO con el código en un bloque ```python.")
    codigo = comun.extraer_codigo(comun.pensar(pedido, temperatura=0.2, codigo=True, max_tokens=2500))
    from core.nucleo import analista, cuarentena
    for intento in range(INTENTOS):
        problema = depredador._problema_de(codigo, analista, cuarentena) if codigo else "el modelo no respondió"
        if not problema:
            break
        if intento == INTENTOS - 1:
            with _lock:
                e = _estado()
                e["fallidos"].append({"tipo": tipo_de(ejemplos[-1]["pedido"]), "por_que": problema[:300],
                                      "cuando": comun.ahora_txt()})
                _guardar(e)
            return False, problema
        codigo = comun.extraer_codigo(comun.pensar(
            f"{pedido}\n\nTu versión anterior tuvo un problema: {problema}\n"
            f"```python\n{(codigo or '')[:6000]}\n```\nDevuélvela completa y corregida.",
            temperatura=0.1, codigo=True, max_tokens=2500)) or codigo
    tipo = tipo_de(ejemplos[-1]["pedido"])
    nombre = ("aprendida_" + evo._slug(tipo or "pedido"))[:46]
    ok, por_que = depredador.instalar_habilidad_nueva(nombre, codigo, f"aprendida resolviendo: {tipo}")
    if not ok:
        return False, por_que
    with evo._lock:
        hab = evo._cargar(evo.ARCH_HABILIDADES, {})
        hab[nombre] = {"tarea": ejemplos[-1]["pedido"], "creada": comun.ahora_txt(), "usos": 0, "origen": "resolver"}
        evo._guardar(evo.ARCH_HABILIDADES, hab)
    analista.registrar_origen(nombre, "resolver", tarea=ejemplos[-1]["pedido"])
    with _lock:
        e = _estado()
        e["habilidades"][tipo] = nombre
        _guardar(e)
    comun.informe(f"Aprendí una habilidad nueva de tanto resolverlo: «{ejemplos[-1]['pedido']}» y parecidos. "
                  "La próxima vez respondo al instante.", nivel="logro", origen="resolver")
    return True, nombre


# ------------------------------------------------------------------
# Puntos de entrada
# ------------------------------------------------------------------

def con_habilidad(texto):
    """Si ya hay una habilidad que lo resuelve, su respuesta. Si no, None."""
    try:
        from core import evolucion as evo
        if evo._cargar(evo.ARCH_HABILIDADES, {}):
            return evo.usar_habilidad(texto)
    except Exception:
        pass
    return None


def atender(texto, avisar=None):
    """Resuelve el pedido: habilidad si hay, si no un programa al vuelo. Devuelve el texto o None."""
    respuesta = con_habilidad(texto)
    if respuesta:
        return respuesta
    ok, resultado, codigo = resolver(texto, avisar)
    if ok:
        anotar_resuelto(texto, codigo, resultado)
        return resultado
    if ok is False:
        with _lock:
            e = _estado()
            e["fallidos"].append({"pedido": texto[:200], "por_que": resultado[:300], "cuando": comun.ahora_txt()})
            _guardar(e)
    return None


def instalar():
    """Cuando ninguna parte de Arché entiende una orden, antes de «no sé» se intenta resolver al vuelo."""
    from core import evolucion as evo
    if getattr(evo.orden_no_entendida, "_con_resolver", False):
        return
    original = evo.orden_no_entendida

    def orden_no_entendida_con_resolver(frase):
        respuesta = original(frase)               # sus habilidades fabricadas (y lo anota para la noche)
        if respuesta or not activo():
            return respuesta
        # Se resuelve en segundo plano para que puedas seguir escribiéndole mientras tanto.
        _responder_en_hilo(frase)
        return "No tengo un comando para eso; déjame resolverlo y ya te digo."

    orden_no_entendida_con_resolver._con_resolver = True
    evo.orden_no_entendida = orden_no_entendida_con_resolver


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_RESUELVE = re.compile(r"^(?:resuelve(?:me)?|calcula(?:me)?\s+con\s+codigo|hazlo\s+con\s+codigo)\s*:?\s+(.{3,})$")


def _responder_en_hilo(texto):
    def _trabajo():
        respuesta = atender(texto, avisar=lambda t: comun.msg(t, voz=False))
        comun.msg(respuesta if respuesta else
                  "No pude resolverlo con un programa. Si es algo de internet o del PC, prueba con mis comandos "
                  "(«comandos») o pregúntamelo como charla.")
    comun.en_hilo(_trabajo, nombre="arche-resolver")


def manejar(comando):
    texto = (comando or "").strip()
    c = comun.norm(texto)
    if c in ("resolver apagado", "no resuelvas al vuelo", "apaga el resolver"):
        e = _estado(); e["activo"] = False; _guardar(e)
        comun.msg("Listo, ya no resuelvo al vuelo lo que no sé hacer.")
        return True
    if c in ("resolver encendido", "resuelve al vuelo", "activa el resolver"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg("Listo, lo que no sepa hacer lo intento resolver al momento.")
        return True
    if c in ("que aprendiste resolviendo", "que has resuelto", "estado del resolver"):
        e = _estado()
        partes = [f"Resolví {len(e['resueltos'])} pedidos con programas al vuelo."]
        if e["habilidades"]:
            partes.append("De eso aprendí estas habilidades: " + ", ".join(e["habilidades"].values()) + ".")
        else:
            partes.append(f"Cuando un mismo tipo de pedido me funcione {VECES_PARA_HABILIDAD} veces, lo vuelvo habilidad.")
        if e["resueltos"]:
            partes.append("Últimos: " + " | ".join(r["pedido"][:50] for r in e["resueltos"][-4:]))
        comun.msg(" ".join(partes))
        return True
    m = _R_RESUELVE.match(c)
    if m:
        pedido = texto.split(":", 1)[1].strip() if ":" in texto else texto.split(None, 1)[1]
        comun.msg("Lo resuelvo...", voz=False)
        _responder_en_hilo(pedido)
        return True
    if activo() and parece_calculo(texto):
        comun.msg("Lo calculo...", voz=False)
        _responder_en_hilo(texto)
        return True
    return False
