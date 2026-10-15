"""
layout.py
---------
Ubicacion: Arche/core/interfaz/layout.py

El modelo de la distribucion de la ventana: una cuadricula de 24 columnas por
16 filas donde cada widget ocupa un rectangulo. Aqui no se dibuja nada: solo
se valida, se mueve, se redimensiona, se oculta, se duplica y se ordena.

Reglas que se respetan siempre:
  - ningun widget visible se superpone con otro (los cambios que lo harian se
    rechazan o se intercambian los huecos);
  - un layout danado o con datos raros se repara al leerlo, nunca rompe la ventana.
"""

import copy

COLS = 24
FILAS = 16

# tipo -> (nombre, categoria, ancho, alto, ancho_min, alto_min, unico, descripcion)
CATALOGO = {
    "voz": ("Esfera de voz", "Visuales", 12, 7, 4, 3, True, "La esfera (u ondas) que reacciona a mi voz."),
    "mascota": ("Mascota", "Visuales", 12, 3, 3, 2, True, "Tu mascota con su globo de texto y lo que entendí."),
    "chat": ("Conversación", "Interacción", 12, 6, 5, 3, True, "Lo que hablamos y la caja para escribirme."),
    "sistema": ("Estado del equipo", "Sistema", 6, 8, 3, 3, False, "CPU, RAM, disco y batería."),
    "graficas": ("Gráficas CPU y RAM", "Sistema", 6, 4, 3, 2, False, "Historial reciente del uso del equipo."),
    "procesos": ("Segundo plano", "Arché", 6, 8, 3, 3, True, "Lo que hago mientras no me miras."),
    "panel": ("Panel de pestañas", "Interacción", 6, 16, 4, 6, True, "Controles, personalización, hoy y aprendizaje."),
    "modelo": ("Modelo de IA", "Arché", 6, 3, 3, 2, True, "Qué cerebro uso y cómo va la red neuronal."),
    "redes": ("Redes neuronales", "Arché", 6, 6, 3, 3, True, "Las redes neuronales con sus neuronas, ejemplos reales y caja para agregar más."),
    "estado_asistente": ("Estado del asistente", "Arché", 5, 3, 3, 2, True, "Lo que estoy haciendo ahora mismo."),
    "actividad": ("Actividad reciente", "Arché", 6, 5, 3, 3, False, "Lo último que entendí."),
    "historial": ("Historial de acciones", "Arché", 6, 5, 3, 3, False, "Tus últimas órdenes con la hora."),
    "mejora": ("Mejora continua", "Arché", 6, 5, 3, 3, True, "Lo que mejoré sola."),
    "estadisticas": ("Estadísticas de uso", "Arché", 5, 4, 3, 3, True, "Órdenes, intenciones y examen."),
    "reloj": ("Reloj", "Productividad", 6, 3, 2, 2, False, "Hora y fecha."),
    "calendario": ("Calendario", "Productividad", 6, 6, 4, 4, True, "El mes con el día de hoy."),
    "notas": ("Notas", "Productividad", 6, 5, 3, 3, True, "Notas rápidas («nota: ...»)."),
    "recordatorios": ("Recordatorios", "Productividad", 6, 4, 3, 3, True, "Próximas alarmas y temporizadores."),
    "atajos": ("Accesos directos", "Productividad", 6, 3, 3, 2, True, "Botones para tus órdenes favoritas."),
    "red": ("Red", "Sistema", 6, 4, 3, 3, True, "Dirección, envío y recepción."),
    "dispositivos": ("Dispositivos", "Dispositivos", 6, 4, 3, 3, True, "Discos, batería y control por celular."),
    "notificaciones": ("Notificaciones", "Interacción", 6, 5, 3, 3, True, "Avisos recientes."),
    "progreso": ("Progreso de tareas", "Arché", 8, 3, 4, 2, True, "Panel de progreso de tareas largas."),
    "registro": ("Registro de eventos", "Arché", 8, 5, 4, 3, True, "Órdenes, avisos y tareas, para depurar."),
}

# Para el buscador y el lenguaje natural: como llama la gente a cada widget
SINONIMOS = {
    "voz": ("esfera", "voz", "visualizador", "orbe", "circulo"),
    "mascota": ("mascota", "personaje", "chispa"),
    "chat": ("chat", "conversacion", "mensajes", "conversación"),
    "sistema": ("estado del equipo", "equipo", "sistema", "estadisticas del sistema", "recursos", "cpu", "ram"),
    "graficas": ("graficas", "grafica", "historial de cpu"),
    "procesos": ("procesos", "segundo plano", "tareas en ejecucion", "tareas"),
    "panel": ("panel", "pestanas", "controles", "panel derecho"),
    "modelo": ("modelo", "cerebro", "estado del modelo"),
    "redes": ("redes neuronales", "red neuronal", "redes", "neuronas", "clasificador", "precision de las redes", "vista de redes", "ejemplos"),
    "estado_asistente": ("estado del asistente", "estado de arche", "estado"),
    "actividad": ("actividad", "actividad reciente"),
    "historial": ("historial", "historial de acciones"),
    "mejora": ("mejora", "mejora continua"),
    "estadisticas": ("estadisticas", "estadisticas de uso"),
    "reloj": ("reloj", "hora"),
    "calendario": ("calendario", "fecha"),
    "notas": ("notas", "nota", "apuntes"),
    "recordatorios": ("recordatorios", "alarmas", "recordatorio"),
    "atajos": ("atajos", "accesos directos", "accesos"),
    "red": ("red", "internet", "wifi"),
    "dispositivos": ("dispositivos", "discos", "bateria"),
    "notificaciones": ("notificaciones", "avisos"),
    "progreso": ("progreso", "barra de progreso"),
    "registro": ("registro", "log", "logs", "eventos"),
}

NIVELES = ("minimo", "normal", "detallado")
_extra = {}      # tipos que aportan las extensiones: "ext:nombre" -> misma tupla del catalogo


def registrar_tipo(tipo, datos):
    _extra[tipo] = datos


def olvidar_tipos_extra():
    _extra.clear()


def info(tipo):
    return CATALOGO.get(tipo) or _extra.get(tipo)


def tipos():
    return list(CATALOGO) + list(_extra)


def nombre_de(tipo):
    i = info(tipo)
    return i[0] if i else tipo


def nuevo_widget(tipo, id=None, x=0, y=0, visible=True, **extra):
    i = info(tipo)
    w = {"id": id or tipo, "tipo": tipo, "x": x, "y": y, "w": i[2], "h": i[3], "visible": visible,
         "opacidad": 100, "color": "", "titulo": "", "nivel": "normal", "ventana": None, "opts": {}}
    w.update(extra)
    return w


def armar(lista, **cfg):
    """Crea un layout desde [(tipo, x, y, w, h)] o [(tipo, x, y, w, h, {extras})]."""
    ws = []
    for fila in lista:
        tipo, x, y, w, h = fila[:5]
        extra = fila[5] if len(fila) > 5 else {}
        ws.append(nuevo_widget(tipo, x=x, y=y, **{**extra}))
        ws[-1]["w"], ws[-1]["h"] = w, h
    lay = {"v": 1, "margen": 22, "separacion": 14, "cabecera": True, "pie": True, "widgets": ws}
    lay.update(cfg)
    return lay


def por_defecto():
    """La distribucion de siempre de Arché (perfil General)."""
    return armar([
        ("sistema", 0, 0, 6, 8), ("procesos", 0, 8, 6, 8),
        ("voz", 6, 0, 12, 7), ("mascota", 6, 7, 12, 3), ("chat", 6, 10, 12, 6),
        ("panel", 18, 0, 6, 16),
    ])


# ------------------------------------------------------------------ geometria
def rect(w):
    return (w["x"], w["y"], w["x"] + w["w"], w["y"] + w["h"])


def solapa(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _visibles(lay, ignorar=None):
    return [w for w in lay["widgets"] if w.get("visible") and w["id"] != ignorar and not w.get("ventana")]


def choques(lay, r, ignorar=None):
    return [w for w in _visibles(lay, ignorar) if solapa(r, rect(w))]


def hueco(lay, ancho, alto, ignorar=None):
    """Primer sitio libre (x, y) para un rectangulo de ese tamaño, o None."""
    for y in range(0, FILAS - alto + 1):
        for x in range(0, COLS - ancho + 1):
            if not choques(lay, (x, y, x + ancho, y + alto), ignorar):
                return x, y
    return None


def buscar(lay, id_o_tipo):
    for w in lay["widgets"]:
        if w["id"] == id_o_tipo:
            return w
    for w in lay["widgets"]:
        if w["tipo"] == id_o_tipo:
            return w
    return None


def _coincide(n, t):
    """Nombre exacto (o en plural). Nunca por pedazos: «estado banco» no es «estado»."""
    return bool(n) and (t == n or t == n + "s" or t + "s" == n or t == n + "es")


def encontrar_por_nombre(lay, texto):
    """Widget por nombre o sinonimo EXACTO ("el chat", "estadisticas del sistema")."""
    t = _limpio(texto)
    for w in lay["widgets"]:
        if _limpio(w["id"]) == t or _limpio(w.get("titulo", "")) == t:
            return w
    for w in lay["widgets"]:
        i = info(w["tipo"])
        nombres = list(SINONIMOS.get(w["tipo"], ())) + [i[0] if i else ""]
        if any(_coincide(_limpio(n), t) for n in nombres):
            return w
    return None


def tipo_por_nombre(texto):
    t = _limpio(texto)
    for tipo in tipos():
        nombres = list(SINONIMOS.get(tipo, ())) + [nombre_de(tipo)]
        if any(_coincide(_limpio(n), t) for n in nombres):
            return tipo
    return None


def _limpio(s):
    import unicodedata
    t = unicodedata.normalize("NFD", str(s).lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


# ------------------------------------------------------------------ validacion
def validar(lay):
    """Devuelve un layout seguro a partir de cualquier cosa. Nunca lanza excepciones."""
    if not isinstance(lay, dict) or not isinstance(lay.get("widgets"), list):
        return por_defecto()
    sal = {"v": 1, "margen": _num(lay.get("margen"), 22, 4, 60), "separacion": _num(lay.get("separacion"), 14, 0, 40),
           "cabecera": bool(lay.get("cabecera", True)), "pie": bool(lay.get("pie", True)), "widgets": []}
    vistos = set()
    for w in lay["widgets"]:
        if not isinstance(w, dict):
            continue
        tipo = w.get("tipo")
        i = info(tipo)
        if i is None:
            continue
        wid = str(w.get("id") or tipo)[:40]
        base, k = wid, 2
        while wid in vistos:
            wid = f"{base}-{k}"
            k += 1
        vistos.add(wid)
        ancho = _num(w.get("w"), i[2], i[4], COLS)
        alto = _num(w.get("h"), i[3], i[5], FILAS)
        x = _num(w.get("x"), 0, 0, COLS - ancho)
        y = _num(w.get("y"), 0, 0, FILAS - alto)
        nv = w.get("nivel") if w.get("nivel") in NIVELES else "normal"
        col = w.get("color") if isinstance(w.get("color"), str) else ""
        try:
            from . import ajustes
            col = ajustes.normalizar_hex(col) or ""
        except Exception:
            col = ""
        ven = w.get("ventana")
        if isinstance(ven, dict):
            ven = {k2: _num(ven.get(k2), d, -4000, 8000) for k2, d in (("x", 100), ("y", 100), ("w", 420), ("h", 320))}
        else:
            ven = None
        opts = w.get("opts") if isinstance(w.get("opts"), dict) else {}
        sal["widgets"].append({"id": wid, "tipo": tipo, "x": x, "y": y, "w": ancho, "h": alto,
                               "visible": bool(w.get("visible", True)), "opacidad": _num(w.get("opacidad"), 100, 0, 100),
                               "color": col, "titulo": str(w.get("titulo") or "")[:30], "nivel": nv,
                               "ventana": ven, "opts": opts})
    # tipos unicos: solo uno
    unicos = set()
    limpio = []
    for w in sal["widgets"]:
        if info(w["tipo"])[6]:
            if w["tipo"] in unicos:
                continue
            unicos.add(w["tipo"])
        limpio.append(w)
    sal["widgets"] = limpio
    # superposiciones entre visibles: el que llega despues busca otro sitio (o se oculta)
    puestos = []
    for w in sal["widgets"]:
        if not w["visible"] or w.get("ventana"):
            continue
        if any(solapa(rect(w), rect(p)) for p in puestos):
            hay = _hueco_en(puestos, w["w"], w["h"])
            if hay:
                w["x"], w["y"] = hay
            else:
                w["visible"] = False
                continue
        puestos.append(w)
    if not sal["widgets"]:
        return por_defecto()
    return sal


def _hueco_en(puestos, ancho, alto):
    for y in range(0, FILAS - alto + 1):
        for x in range(0, COLS - ancho + 1):
            r = (x, y, x + ancho, y + alto)
            if not any(solapa(r, rect(p)) for p in puestos):
                return x, y
    return None


def _num(v, defecto, lo, hi):
    try:
        n = int(float(v))
    except Exception:
        n = defecto
    return max(lo, min(hi, n))


# ------------------------------------------------------------------ operaciones
# Todas devuelven (ok, mensaje). Si no pueden hacerlo, dicen por que y no cambian nada.
def mover(lay, id, x, y):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    x = max(0, min(COLS - w["w"], int(x)))
    y = max(0, min(FILAS - w["h"], int(y)))
    if (x, y) == (w["x"], w["y"]):
        return True, "sin cambios"
    r = (x, y, x + w["w"], y + w["h"])
    chocan = choques(lay, r, w["id"])
    if not chocan:
        w["x"], w["y"] = x, y
        return True, "movido"
    if len(chocan) == 1:                       # soltado sobre otro: intercambian sitios
        return intercambiar(lay, w["id"], chocan[0]["id"])
    return False, "ese sitio está ocupado"


def intercambiar(lay, a, b):
    wa, wb = buscar(lay, a), buscar(lay, b)
    if wa is None or wb is None or wa is wb:
        return False, "no puedo intercambiar eso"
    ra = (wa["x"], wa["y"], wa["w"], wa["h"])
    rb = (wb["x"], wb["y"], wb["w"], wb["h"])
    ia, ib = info(wa["tipo"]), info(wb["tipo"])
    if rb[2] < ia[4] or rb[3] < ia[5] or ra[2] < ib[4] or ra[3] < ib[5]:
        return False, "no caben uno en el sitio del otro"
    wa["x"], wa["y"], wa["w"], wa["h"] = rb
    wb["x"], wb["y"], wb["w"], wb["h"] = ra
    return True, "intercambiados"


def redimensionar(lay, id, ancho, alto):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    i = info(w["tipo"])
    ancho = max(i[4], min(COLS - w["x"], int(ancho)))
    alto = max(i[5], min(FILAS - w["y"], int(alto)))
    # si choca, se achica hasta donde quepa
    a, b = ancho, alto
    while choques(lay, (w["x"], w["y"], w["x"] + a, w["y"] + b), w["id"]):
        if a > w["w"] and a >= b:
            a -= 1
        elif b > w["h"]:
            b -= 1
        elif a > w["w"]:
            a -= 1
        else:
            return False, "no cabe: hay otro componente al lado"
    if (a, b) == (w["w"], w["h"]):
        return False, "no hay espacio libre para agrandarlo"
    w["w"], w["h"] = a, b
    return True, "redimensionado" if (a, b) == (ancho, alto) else "redimensionado hasta donde cabe"


def mostrar(lay, id):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    if w["visible"] and not w.get("ventana"):
        return True, "ya estaba visible"
    w["ventana"] = None
    if choques(lay, rect(w), w["id"]):
        w["visible"] = True
        sitio = hueco(lay, w["w"], w["h"], w["id"])
        i = info(w["tipo"])
        if sitio is None:                      # prueba mas pequeño
            for ancho, alto in ((max(i[4], w["w"] // 2), w["h"]), (i[4], i[5])):
                sitio = hueco(lay, ancho, alto, w["id"])
                if sitio:
                    w["w"], w["h"] = ancho, alto
                    break
        if sitio is None:
            w["visible"] = False
            return False, "no hay espacio libre: oculta o achica otro componente primero"
        w["x"], w["y"] = sitio
    w["visible"] = True
    return True, "visible"


def ocultar(lay, id):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    if not w["visible"] and not w.get("ventana"):
        return True, "ya estaba oculto"
    w["visible"] = False
    w["ventana"] = None
    return True, "oculto (sigue disponible en la lista de componentes)"


def quitar(lay, id):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    lay["widgets"].remove(w)
    return True, "quitado de la distribución"


def duplicar(lay, id):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    if info(w["tipo"])[6]:
        return False, f"«{info(w['tipo'])[0]}» solo puede estar una vez"
    k = 2
    while any(o["id"] == f"{w['tipo']}-{k}" for o in lay["widgets"]):
        k += 1
    copia = copy.deepcopy(w)
    copia["id"] = f"{w['tipo']}-{k}"
    copia["visible"] = False
    lay["widgets"].append(copia)
    ok, msg = mostrar(lay, copia["id"])
    if not ok:
        return True, "duplicado, pero oculto (" + msg + ")"
    return True, "duplicado"


def anadir(lay, tipo):
    i = info(tipo)
    if i is None:
        return False, "ese componente no existe"
    if i[6]:
        ya = [w for w in lay["widgets"] if w["tipo"] == tipo]
        if ya:
            return mostrar(lay, ya[0]["id"])
    k, wid = 2, tipo
    while any(o["id"] == wid for o in lay["widgets"]):
        wid = f"{tipo}-{k}"
        k += 1
    w = nuevo_widget(tipo, id=wid, visible=False)
    lay["widgets"].append(w)
    ok, msg = mostrar(lay, wid)
    if not ok:
        lay["widgets"].remove(w)
    return ok, "agregado" if ok else msg


def al_frente(lay, id, frente=True):
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    lay["widgets"].remove(w)
    if frente:
        lay["widgets"].append(w)
    else:
        lay["widgets"].insert(0, w)
    return True, "orden cambiado"


def mover_a_lado(lay, id, lado):
    """«Mueve el chat a la izquierda»: toma el sitio del que esta mas a ese lado (y le da el suyo)."""
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    otros = [o for o in _visibles(lay, w["id"])]
    if not otros:
        return False, "no hay otros componentes con quien cambiar"
    clave = {"izquierda": lambda o: o["x"], "derecha": lambda o: -(o["x"] + o["w"]),
             "arriba": lambda o: o["y"], "abajo": lambda o: -(o["y"] + o["h"])}.get(lado)
    if clave is None:
        return False, "lado desconocido"
    extremo = min(otros, key=clave)
    # ya esta en ese lado
    if clave(w) <= clave(extremo):
        return True, f"ya estaba {('a la ' if lado in ('izquierda', 'derecha') else '')}{lado}"
    return intercambiar(lay, w["id"], extremo["id"])


def opcion(lay, id, clave, valor):
    """Cambia opacidad, color, titulo o nivel de un componente."""
    w = buscar(lay, id)
    if w is None:
        return False, "no encuentro ese componente"
    if clave == "opacidad":
        w["opacidad"] = _num(valor, 100, 0, 100)
    elif clave == "color":
        from . import ajustes
        h = ajustes.normalizar_hex(valor) if valor else ""
        if valor and not h:
            return False, "no es un color valido"
        w["color"] = h or ""
    elif clave == "titulo":
        w["titulo"] = str(valor)[:30]
    elif clave == "nivel":
        if valor not in NIVELES:
            return False, "niveles: " + ", ".join(NIVELES)
        w["nivel"] = valor
    elif clave == "estilo":
        w["opts"]["estilo"] = valor
    else:
        return False, "opcion desconocida"
    return True, "listo"


def resumen_diferencias(a, b):
    """Frases cortas con lo que cambia al pasar del layout a al b."""
    sal = []
    ma = {w["id"]: w for w in a["widgets"]}
    mb = {w["id"]: w for w in b["widgets"]}
    for k, w in mb.items():
        if k not in ma:
            sal.append(f"aparece «{nombre_de(w['tipo'])}»")
            continue
        o = ma[k]
        if o["visible"] != w["visible"]:
            sal.append(("se muestra" if w["visible"] else "se oculta") + f" «{nombre_de(w['tipo'])}»")
        elif (o["x"], o["y"], o["w"], o["h"]) != (w["x"], w["y"], w["w"], w["h"]):
            sal.append(f"cambia de sitio o tamaño «{nombre_de(w['tipo'])}»")
        elif (o["opacidad"], o["color"], o["nivel"]) != (w["opacidad"], w["color"], w["nivel"]):
            sal.append(f"cambia el aspecto de «{nombre_de(w['tipo'])}»")
    for k, w in ma.items():
        if k not in mb:
            sal.append(f"desaparece «{nombre_de(w['tipo'])}»")
    return sal
