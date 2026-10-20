"""
lenguaje.py
-----------
Ubicacion: Arche/core/interfaz/lenguaje.py

Personalizar la interfaz con frases normales:

    «haz la interfaz más minimalista»      «cambia el tema a azul oscuro»
    «mueve el chat a la izquierda»         «oculta la mascota»
    «reduce las animaciones»               «quiero una interfaz técnica»
    «recupera mi distribución anterior»    «deja visibles las estadísticas del sistema»

Reglas:
  - Entiende solo lo que reconoce de verdad. Si no lo entiende, devuelve None y
    la frase sigue su camino normal hacia Arché (nunca se la traga).
  - Lo que cambia mucho (perfiles, «más minimalista», restablecer) primero se
    PREVISUALIZA: dice que va a cambiar y espera un «sí» (o el boton Aplicar).
  - Lo pequeño se aplica al instante y se puede deshacer («deshacer»).
  - Solo dice «listo» si el cambio ocurrio. Si no se pudo, dice por que.
"""

import os
import re
import time
import unicodedata

from . import ajustes, estado_visual as ev, layout, perfiles, tema, extensiones

DIR_EXPORT = None            # se calcula al usarse (Database/interfaz)
pendiente = None             # {"resumen": [...], "aplicar": fn, "hasta": ts, "texto": str}
_VIGENCIA = 120              # segundos que espera tu confirmacion


def _limpio(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¿?¡!,;]", " ", t)
    t = re.sub(r"\.+$", "", t.strip())
    return " ".join(t.split())


def carpeta_export():
    global DIR_EXPORT
    if DIR_EXPORT is None:
        try:
            from core.rutas import DATABASE
        except Exception:
            DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Database")
        DIR_EXPORT = os.path.join(DATABASE, "interfaz")
    return DIR_EXPORT


# ------------------------------------------------------------------ colores con nombre
_COLORES = {"rojo": "#c0262d", "azul": "#2f55d4", "verde": "#1f9d55", "morado": "#7a3fd1", "violeta": "#7a3fd1",
            "negro": "#05050a", "blanco": "#f4f4fb", "naranja": "#e8751a", "amarillo": "#e5c60f", "rosa": "#e0509a",
            "gris": "#7d7d8c", "cian": "#18c7d9", "celeste": "#4da3ff", "turquesa": "#1fb8a6", "marron": "#7a4a2a",
            "dorado": "#d4a017", "vino": "#6e1030"}


def color_de(texto):
    """HEX desde '#112233', '10,20,30' o 'rojo oscuro'. None si no es un color."""
    h = ajustes.normalizar_hex(texto)
    if h:
        return h
    t = _limpio(texto)
    base = next((c for c in _COLORES if re.search(rf"\b{c}\b", t)), None)
    if base is None:
        return None
    col = _COLORES[base]
    if re.search(r"muy oscuro|bien oscuro", t):
        return tema.mezclar(col, "#000000", 0.7)
    if "oscuro" in t:
        return tema.mezclar(col, "#000000", 0.45)
    if re.search(r"claro|pastel", t):
        return tema.mezclar(col, "#ffffff", 0.35)
    return col


# ------------------------------------------------------------------ utilidades
def _w(texto):
    """Widget de la distribucion activa por nombre ('el chat', 'las estadisticas del sistema')."""
    t = re.sub(r"^(el|la|los|las|mi|mis|un|una)\s+", "", _limpio(texto))
    t = re.sub(r"^(panel|widget|componente|modulo)s? de ", "", t) if t.startswith(("panel de ", "widget de ")) else t
    return layout.encontrar_por_nombre(perfiles.layout_actual(), t)


def _tocado():
    perfiles.marcar_sucio()


def _ped(accion, dato=None):
    try:
        from . import ventana
        return ventana.pedir(accion, dato)
    except Exception:
        return False


def _pide_confirmacion(texto, resumen, aplicar):
    global pendiente
    pendiente = {"resumen": resumen, "aplicar": aplicar, "hasta": time.time() + _VIGENCIA, "texto": texto}
    cuerpo = "; ".join(resumen[:6]) + ("…" if len(resumen) > 6 else "")
    return f"Esto cambiaría: {cuerpo}. ¿Lo aplico? Di «sí» o toca Aplicar (y puedes deshacerlo)."


def hay_pendiente():
    global pendiente
    if pendiente and time.time() > pendiente["hasta"]:
        pendiente = None
    return pendiente


def confirmar():
    global pendiente
    p = hay_pendiente()
    if not p:
        return "No hay nada pendiente de confirmar."
    pendiente = None
    ev.punto_de_control(p["texto"])
    return p["aplicar"]()


def cancelar():
    global pendiente
    if hay_pendiente():
        pendiente = None
        return "Vale, no cambié nada."
    return "No había nada pendiente."


def _cambios_ajustes(d):
    """Frases sobre lo que cambiaria un dict de ajustes."""
    sal = []
    for k, v in d.items():
        if ajustes.obtener(k) != v:
            sal.append(f"{k} → {v if not isinstance(v, bool) else ('sí' if v else 'no')}")
    return sal


def _aplicar_ajustes(d):
    ok, mal = ajustes.fijar_varios(d)
    return ok, mal


# ------------------------------------------------------------------ manejadores
# Cada uno recibe (m, texto_limpio, original) y devuelve un mensaje, o None si la frase no es suya.
def _h_confirmar(m, t, o):
    if hay_pendiente():
        if re.fullmatch(r"(si|sii+|claro|dale|ok|okay|vale|aplica(lo)?|aplicar|confirmo|confirmar|hazlo|adelante|de una)", t):
            return confirmar()
        if re.fullmatch(r"(no|cancela(r|lo)?|mejor no|olvidalo|nada|deja eso)", t):
            return cancelar()
    return None


def _h_deshacer(m, t, o):
    if re.fullmatch(r"(deshaz|deshacer|deshaz eso|deshace eso|atras|vuelve atras|deshacer cambio|deshaz el ultimo cambio)", t):
        return ev.deshacer()[1].capitalize() + "."
    if re.fullmatch(r"(rehaz|rehacer|rehaz eso|rehace eso)", t):
        return ev.rehacer()[1].capitalize() + "."
    if re.search(r"(recupera|restaura|vuelve a|devuelveme|regresa a|pon) (mi |la )?(distribucion|disposicion|diseno) anterior", t):
        return ev.layout_anterior()[1].capitalize() + "."
    return None


def _h_perfil(m, t, o):
    mm = re.match(r"^(?:cambia(?: al| a el)?|pasa al|activa(?: el)?|usa(?: el)?|pon(?: el)?|ve al|vuelve al|quiero(?: el)?|abre el) "
                  r"(?:perfil|modo)(?: de)? (.+)$|^perfil (.+)$|^(?:quiero|dame|pon|usa|cambia a|activa) (?:una |la |mi )?interfaz "
                  r"(?:para )?(tecnica|tecnico|minimalista|de desarrollo|de programacion|de trabajo|de trabajar|de ambiente|ambiental|normal|general|de entretenimiento|"
                  r"para programar|para trabajar|para entretener)$", t)
    if not mm:
        return None
    nombre = next(g for g in mm.groups() if g)
    nombre = re.sub(r"^(de |para )", "", nombre.strip())
    nombre = {"trabajar": "trabajo", "programar": "programar", "entretener": "entretenimiento"}.get(nombre, nombre)
    real = perfiles.resolver(nombre)
    if real is None:
        return f"No tengo un perfil «{nombre}». Los que hay: " + ", ".join(n for n, _, _ in perfiles.listar()) + "."
    if real == perfiles.activo():
        return f"Ya estás en el perfil «{real}»."
    desc = perfiles.listar()
    destino = next(d for n, d, _ in desc if n == real)
    return _pide_confirmacion(o, [f"perfil «{real}» ({destino.rstrip('.')})"],
                              lambda: perfiles.activar(real)[1].capitalize() + ". Di «deshacer» para volver.")


def _h_minimalista(m, t, o):
    if not re.match(r"^(haz|hace|deja|pon|quiero|quisiera|ponme|dejame)( la| mi| una)? ?(interfaz|ventana|pantalla|todo)?( mas| bien| muy)? (minimalista|simple|sencilla|limpia)$", t):
        return None
    cambios = {"mascota": False, "escena": "ninguna", "efecto_particulas": 0, "efecto_profundidad": False,
               "efecto_sombra": 0, "efecto_borde_luminoso": 0, "fondo": "", "chat_vista": "compacta"}
    resumen = _cambios_ajustes(cambios)
    lay = perfiles.layout_actual()
    ocultables = [w for w in lay["widgets"] if w["visible"] and w["tipo"] not in ("voz", "chat")]
    if ocultables:
        resumen.append("se ocultan " + ", ".join(layout.nombre_de(w["tipo"]) for w in ocultables))
    if not resumen:
        return "Ya está lo más minimalista que puedo dejarla."

    def aplicar():
        _aplicar_ajustes(cambios)
        for w in ocultables:
            layout.ocultar(lay, w["id"])
        # lo que queda se reparte para ocupar el espacio
        v = layout.buscar(lay, "voz")
        ch = layout.buscar(lay, "chat")
        if v and ch:
            v.update(x=5, y=0, w=14, h=10)
            ch.update(x=5, y=10, w=14, h=6)
        _tocado()
        return "Listo: dejé la interfaz minimalista (voz y conversación). Di «deshacer» si no te gusta."
    return _pide_confirmacion(o, resumen, aplicar)


def _h_tema(m, t, o):
    mm = re.match(r"^(?:(?:cambia|pon|usa|activa|quiero|ponme|cambiame)(?: el| la| los)? )?(?:tema|colores|paleta|apariencia)(?: a| de| en| por)? (.+)$|"
                  r"^(?:pon|usa|quiero|ponme|dame)(?: la| el)? interfaz (?:en |de color )?(azul|verde|rojo|morado|naranja|neon|oscura|negra)(?: oscuro)?$", t)
    if not mm:
        return None
    nombre = (mm.group(1) or mm.group(2)).strip()
    if nombre in ("siguiente", "otro", "distinto"):
        return None
    real = tema.resolver(nombre)
    if real is None:
        sin = {"naranja": "ambar", "amarillo": "ambar", "dorado": "ambar", "verde": "esmeralda", "rojo": "neon", "rosa": "neon",
               "oscuro": "arche", "oscura": "arche", "negro": "arche", "negra": "arche", "azul": "azul", "celeste": "azul",
               "cian": "holografico", "blanco": "minimalista", "gris": "minimalista"}
        clave = next((k for k in sin if re.search(rf"\b{k}\b", nombre)), None)
        real = sin.get(clave) if clave else None
        if real is None:
            return ("No tengo un tema «" + nombre + "». Los que hay: " + ", ".join(n for _, n, _ in tema.listar()) +
                    ". Si quieres uno tuyo: «crea un tema llamado …».")
    ajustes.fijar("tema", real)
    return f"Tema {tema.NOMBRES.get(real, real)} puesto."


def _h_tema_propio(m, t, o):
    mm = re.match(r"^(?:crea|haz|nuevo|crear)(?: un| mi)? tema(?: llamado| que se llame| con nombre)? (.+?)(?: (?:desde|a partir de|basado en) (.+))?$", t)
    if mm:
        ok, res = tema.crear(mm.group(1).strip().title(), mm.group(2))
        if ok:
            ajustes.fijar("tema", res)
            return f"Creé el tema «{res}» y lo activé. Cámbiale colores con «color del fondo #112233» o en PERSONALIZA › Apariencia."
        return res.capitalize() + "."
    mm = re.match(r"^(?:duplica|copia) el tema (.+?) (?:como|con nombre|llamado) (.+)$", t)
    if mm:
        ok, res = tema.duplicar(mm.group(1), mm.group(2).title())
        return (f"Dupliqué el tema como «{res}»." if ok else res.capitalize() + ".")
    mm = re.match(r"^(?:borra|elimina|quita) el tema (.+)$", t)
    if mm:
        real = tema.resolver(mm.group(1))
        if real is None:
            return f"No encuentro el tema «{mm.group(1)}»."
        if not tema.es_propio(real):
            return "Solo puedo borrar temas que hayas creado tú."
        if tema.actual() == real:
            ajustes.fijar("tema", "arche")
        ok, res = tema.borrar(real)
        return f"Borré el tema «{res}»." if ok else res
    mm = re.match(r"^(?:cambia |pon |ponle |fija )?(?:el )?color (?:de |del |de la |de los |de las )?(.+?) (?:a|en|de|por|=) ?(.+)$", t)
    if not mm:      # «color del fondo rojo oscuro» / «color de texto #fff»
        mm = re.match(r"^(?:cambia |pon |ponle |fija )?(?:el )?color (?:de |del |de la |de los |de las )?(" + "|".join(sorted(tema.ALIAS_ROLES, key=len, reverse=True)) + r") (.+)$", t)
    if mm:
        rol_txt, valor = mm.group(1).strip(), mm.group(2).strip()
        rol = tema.ALIAS_ROLES.get(re.sub(r"^(el |la |los |las )", "", rol_txt))
        if rol is None:
            rol = tema.ALIAS_ROLES.get(rol_txt.split()[-1]) if rol_txt else None
        if rol is None and rol_txt in tema.ROLES:
            rol = rol_txt
        if rol is None:
            return None
        hexa = color_de(valor)
        if not hexa:
            return f"«{valor}» no es un color que reconozca. Usa #RRGGBB, R,G,B o un nombre como «rojo oscuro»."
        actual = tema.actual()
        if not tema.es_propio(actual):
            ok, res = tema.crear("Mi " + tema.NOMBRES.get(actual, actual).title(), actual)
            if not ok:
                return res.capitalize() + "."
            actual = res
            ajustes.fijar("tema", actual)
            nuevo = True
        else:
            nuevo = False
        ok, res = tema.fijar_color(actual, rol, hexa)
        if not ok:
            return res.capitalize() + "."
        tema.aplicar(actual)
        return (f"Creé tu tema «{actual}» y " if nuevo else "") + f"puse {tema.ROLES[rol]} en {res}."
    mm = re.match(r"^(?:exporta(?:r)?|guarda(?:r)?) (?:el |mi )?tema(?: (.+))?$", t)
    if mm:
        ok, res = tema.exportar(mm.group(1) or tema.actual(), carpeta_export())
        return (f"Tema exportado en {res}." if ok else res.capitalize() + ".")
    return None


def _h_widget_visibilidad(m, t, o):
    mm = re.match(r"^(oculta|esconde|quita|saca|no muestres|elimina|borra)( de la pantalla)? (.+)$", t)
    if mm:
        objetivo = mm.group(3)
        if re.match(r"^(el |la )?(mascota)$", objetivo):
            ajustes.fijar("mascota", False)
            return "Escondí la mascota. Di «muestra la mascota» para traerla de vuelta."
        if re.search(r"(cabecera|encabezado)", objetivo):
            lay = perfiles.layout_actual()
            lay["cabecera"] = False
            _tocado()
            return "Ocupé la cabecera. Di «muestra la cabecera» para recuperarla."
        w = _w(objetivo)
        if w is None:
            return None
        if mm.group(1) in ("elimina", "borra") and not layout.info(w["tipo"])[6]:
            ok, msg = layout.quitar(perfiles.layout_actual(), w["id"])
        else:
            ok, msg = layout.ocultar(perfiles.layout_actual(), w["id"])
        _tocado()
        return f"{layout.nombre_de(w['tipo'])}: {msg}." if ok else msg.capitalize() + "."
    mm = re.match(r"^(muestra|muestrame|pon|agrega|anade|añade|enciende|activa|deja visibles?|deja|trae|abre|mostrar)(?: en pantalla)? (.+)$", t)
    if mm:
        objetivo = mm.group(2)
        if re.match(r"^(a |de nuevo |otra vez )?(el |la )?(mascota)( de nuevo)?$", objetivo):
            ajustes.fijar("mascota", True)
            return "¡Aquí estoy de nuevo!"
        if re.search(r"(cabecera|encabezado)", objetivo):
            perfiles.layout_actual()["cabecera"] = True
            _tocado()
            return "Cabecera visible."
        w = _w(objetivo)
        if w is not None:
            ok, msg = layout.mostrar(perfiles.layout_actual(), w["id"])
            _tocado()
            return f"{layout.nombre_de(w['tipo'])}: {msg}." if ok else msg.capitalize() + "."
        tipo = layout.tipo_por_nombre(re.sub(r"^(el |la |los |las |un |una )", "", objetivo))
        if tipo:
            ok, msg = layout.anadir(perfiles.layout_actual(), tipo)
            _tocado()
            return f"{layout.nombre_de(tipo)}: {msg}." if ok else msg.capitalize() + "."
    return None


def _h_widget_mover(m, t, o):
    mm = re.match(r"^(?:mueve|pasa|lleva|pon|coloca|cambia)(?: de lado)? (.+?) (?:a|hacia|en|al|del)(?: la| el)? (izquierda|derecha|arriba|abajo)$", t)
    if mm:
        w = _w(mm.group(1))
        if w is None:
            return None
        lado = mm.group(2)
        ok, msg = layout.mover_a_lado(perfiles.layout_actual(), w["id"], lado)
        _tocado()
        return f"{layout.nombre_de(w['tipo'])}: {msg}." if ok else msg.capitalize() + "."
    mm = re.match(r"^(agranda|haz mas grande|hazlo mas grande|achica|haz mas pequeno|haz mas chico|reduce|encoge)(?: el| la| los| las)? (.+)$", t)
    if mm:
        w = _w(mm.group(2))
        if w is None:
            return None
        grande = mm.group(1) in ("agranda", "haz mas grande", "hazlo mas grande")
        d = 2 if grande else -2
        ok, msg = layout.redimensionar(perfiles.layout_actual(), w["id"], w["w"] + d, w["h"] + (d // 2 if grande else d // 2))
        if not ok and not grande:
            ok, msg = False, "ya está en su tamaño mínimo" if w["w"] <= layout.info(w["tipo"])[4] else msg
        _tocado()
        return f"{layout.nombre_de(w['tipo'])}: {msg}." if ok else msg.capitalize() + "."
    mm = re.match(r"^duplica(?: el| la| los| las)? (.+)$", t)
    if mm:
        w = _w(mm.group(1))
        if w is None:
            return None
        ok, msg = layout.duplicar(perfiles.layout_actual(), w["id"])
        _tocado()
        return f"{layout.nombre_de(w['tipo'])}: {msg}." if ok else msg.capitalize() + "."
    mm = re.match(r"^(?:pon|haz|deja)(?: el| la| los| las)? (.+?) (?:con |al )?(?:transparente|(?:transparencia|opacidad)(?: al| a| de)? ?(\d{1,3}) ?%?)$", t)
    if mm:
        w = _w(mm.group(1))
        if w is None:
            return None
        op = int(mm.group(2)) if mm.group(2) else 40
        layout.opcion(perfiles.layout_actual(), w["id"], "opacidad", op)
        _tocado()
        return f"{layout.nombre_de(w['tipo'])}: opacidad {min(100, op)}%."
    mm = re.match(r"^(?:pon|cambia|ponle)(?: el| la)? (?:color|acento) (?:de|del|de la)(?: el| la)? (.+?) (?:a|en|de) (.+)$", t)
    if mm and not tema.ALIAS_ROLES.get(mm.group(1)):
        w = _w(mm.group(1))
        if w is None:
            return None
        hexa = color_de(mm.group(2))
        if not hexa:
            return f"«{mm.group(2)}» no es un color que reconozca."
        layout.opcion(perfiles.layout_actual(), w["id"], "color", hexa)
        _tocado()
        return f"{layout.nombre_de(w['tipo'])}: acento {hexa}."
    mm = re.match(r"^(?:pon|muestra|deja)(?: el| la)? (.+?) (?:en modo|con nivel|con detalle)? ?(minimo|normal|detallado)$", t)
    if mm:
        w = _w(mm.group(1))
        if w:
            layout.opcion(perfiles.layout_actual(), w["id"], "nivel", mm.group(2))
            _tocado()
            return f"{layout.nombre_de(w['tipo'])}: nivel {mm.group(2)}."
    return None


def _h_animaciones(m, t, o):
    if re.fullmatch(r"(reduce|reducir|baja|menos|quita|desactiva|apaga|sin|para)( las| los| el| la)? (animaciones|movimiento|efectos de movimiento)( de la interfaz)?|menos animaciones|sin animaciones|menos movimiento", t):
        ajustes.fijar("reducir_movimiento", True)
        ajustes.fijar("anim_transiciones", False)
        return "Reduje el movimiento: la esfera y los paneles se mueven mucho menos. Di «activa las animaciones» para recuperarlas."
    if re.fullmatch(r"(activa|enciende|pon|quiero|vuelve a poner)( las| el)? (animaciones|movimiento)( de nuevo)?", t):
        ajustes.fijar("reducir_movimiento", False)
        ajustes.fijar("anim_transiciones", True)
        return "Animaciones activadas."
    mm = re.match(r"^(?:pon|cambia|ajusta)(?: la)? velocidad de(?: las)? animaciones(?: a| al| en)? (\d{2,3})", t)
    if mm:
        return f"Velocidad de animaciones: {ajustes.fijar('anim_velocidad', int(mm.group(1)))}%."
    return None


def _h_efectos(m, t, o):
    if re.fullmatch(r"(quita|apaga|desactiva|sin|elimina)( todos)?( los| las)? (efectos|efectos visuales|brillos|sombras)", t):
        cambios = {"efecto_sombra": 0, "efecto_borde_luminoso": 0, "efecto_particulas": 0, "efecto_profundidad": False,
                   "escena": "ninguna", "efecto_brillo": 20}
        _aplicar_ajustes(cambios)
        return "Apagué los efectos (sombras, bordes luminosos, partículas y escena). Di «activa los efectos» para recuperarlos."
    if re.fullmatch(r"(activa|enciende|pon|quiero)( los)? efectos( visuales)?", t):
        _aplicar_ajustes({"efecto_sombra": 40, "efecto_borde_luminoso": 45, "efecto_brillo": 70, "efecto_profundidad": True})
        return "Efectos activados."
    mm = re.match(r"^(?:pon|activa|usa|cambia a)(?: la)? (?:escena|ambiente|animacion de fondo) (?:de )?(\w+)$", t)
    if mm:
        q = mm.group(1)
        q = {"particulas": "particulas", "ondas": "ondas", "rejilla": "rejilla", "nebulosa": "nebulosa", "gradiente": "gradiente",
             "ninguna": "ninguna", "ninguno": "ninguna", "nada": "ninguna"}.get(q)
        if not q:
            return "Escenas disponibles: " + ", ".join(ajustes.OPCIONES["escena"]) + "."
        ajustes.fijar("escena", q)
        return f"Escena: {q}."
    if re.fullmatch(r"(sin escena|quita la escena|quita el fondo animado)", t):
        ajustes.fijar("escena", "ninguna")
        return "Quité la escena."
    return None


def _h_accesibilidad(m, t, o):
    if re.fullmatch(r"(activa|pon|enciende|quiero)( el)? (alto contraste|contraste alto|mas contraste)", t):
        ajustes.fijar("alto_contraste", True)
        tema.aplicar(ajustes.obtener("tema"))
        return "Alto contraste activado."
    if re.fullmatch(r"(desactiva|quita|apaga)( el)? (alto contraste|contraste alto)", t):
        ajustes.fijar("alto_contraste", False)
        tema.aplicar(ajustes.obtener("tema"))
        return "Alto contraste desactivado."
    mm = re.match(r"^(?:haz |pon |quiero )?(?:la )?(letra|texto|fuente)(?: de la interfaz)? (?:mas )?(grande|pequena|pequeno|chica|chico)$|"
                  r"^(?:agranda|achica|aumenta|reduce|sube|baja)(?: el| la)? (?:tamano de la )?(letra|texto|fuente)$", t)
    if mm:
        sube = bool(re.search(r"grande|agranda|aumenta|sube", t))
        n = ajustes.fijar("texto_escala", ajustes.obtener("texto_escala") + (15 if sube else -15))
        return f"Texto al {n}%."
    mm = re.match(r"^(?:haz |pon |quiero )?(?:la )?(interfaz|ventana|todo) (?:mas )?(grande|pequena|pequeno|chica|chico)$|"
                  r"^(?:agranda|achica|aumenta|reduce)(?: la)? (?:interfaz|ventana|escala)$", t)
    if mm:
        sube = bool(re.search(r"grande|agranda|aumenta", t))
        n = ajustes.fijar("ui_escala", ajustes.obtener("ui_escala") + (10 if sube else -10))
        return f"Interfaz al {n}%."
    mm = re.match(r"^(?:pon|cambia|ajusta)(?: la)? (?:escala|tamano) de la interfaz (?:a|al|en) (\d{2,3}) ?%?$", t)
    if mm:
        return f"Interfaz al {ajustes.fijar('ui_escala', int(mm.group(1)))}%."
    if re.fullmatch(r"(restablece|resetea|vuelve a)( el)?( tamano| escala)( de la interfaz| del texto| normal)?", t):
        ajustes.fijar("ui_escala", 100)
        ajustes.fijar("texto_escala", 100)
        return "Tamaños de interfaz y texto en 100%."
    return None


def _h_chat(m, t, o):
    if re.fullmatch(r"(pon |usa |quiero |cambia a )?(el )?chat (compacto|clasico|tecnico)|(conversacion|chat) (en )?(vista )?(compacta|clasica|tecnica)", t):
        v = re.search(r"compact|clasic|tecnic", t).group(0)
        v = {"compact": "compacta", "clasic": "clasica", "tecnic": "tecnica"}[v]
        ajustes.fijar("chat_vista", v)
        return f"Conversación en vista {v}."
    mm = re.match(r"^(?:muestra|pon|activa|quita|oculta|desactiva)(?: las| la)? (?:marcas de tiempo|hora|horas)(?: en (?:el chat|los mensajes|la conversacion))?$", t)
    if mm:
        on = bool(re.match(r"^(muestra|pon|activa)", t))
        ajustes.fijar("chat_marcas_tiempo", on)
        return "Marcas de tiempo " + ("visibles." if on else "ocultas.")
    mm = re.match(r"^(?:pon|cambia|ajusta)(?: la)? letra del chat (?:a|en|de) (\d{1,2})$", t)
    if mm:
        return f"Letra del chat: {ajustes.fijar('chat_tam', int(mm.group(1)))}."
    mm = re.match(r"^(?:pon|mueve|coloca) (?:la caja|el cuadro|la entrada)(?: de (?:escritura|texto))? (arriba|abajo)$", t)
    if mm:
        ajustes.fijar("chat_entrada_arriba", mm.group(1) == "arriba")
        return f"La caja de escritura queda {mm.group(1)}."
    return None


def _h_redes(m, t, o):
    """Las redes neuronales: abrir la vista, agregar ejemplos (Arché decide la intención), entrenar."""
    if re.fullmatch(r"(abre |muestra |ensename |ver |ve a |ir a )?(la )?(vista (grande )?de )?(las )?redes( neuronales)?( en grande| a pantalla completa)?|(abre |muestra |ver )?(la )?red neuronal", t):
        return "Abrí la vista de redes neuronales." if _ped("redes", True) else "Necesito la ventana abierta: dime «abre la interfaz»."
    if re.fullmatch(r"(cierra|oculta|quita|sal de)( la)? (vista (grande )?de )?(las )?redes( neuronales)?", t):
        _ped("redes", False)
        return "Cerré la vista de redes."
    if "=>" not in o and "|" not in o:
        mm = re.match(r"^\s*(?:agrega|agregar|a[ñn]ade|a[ñn]adir|suma|s[úu]male|ens[eé][ñn]a(?:le)?|aprende|guarda)\w*\s+"
                      r"(?:(?:a\s+(?:las\s+)?redes|a\s+arch[eé])\s*[:\-]?\s*|"
                      r"(?:(?:estos?|estas?|esta|esa|ese|la|el|los|las|unos|unas|otra|otro)\s+)?(?:nuev[oa]s?\s+)?(?:ejemplos?|frases?)"
                      r"(?:\s+de\s+entrenamiento)?(?:\s+a\s+(?:las\s+)?redes)?\s*[:\-]?\s*)(.+)$", o, re.I | re.S)
        if mm:
            texto = mm.group(1).strip().strip("«»\"'")
            if texto:
                from . import redes
                n = redes.agregar(texto)
                _ped("redes", True)
                return (f"Estoy clasificando {n} frase(s): decido la intención yo sola y te aviso en la vista de redes "
                        f"(puedes deshacer, y si dudo te dejo elegir).") if n else None
    if re.fullmatch(r"(entrena|reentrena|entrenar|reentrenar|actualiza)( todas)?( las| la)? (redes?( neuronales?)?|red neuronal|clasificador)( ahora)?", t):
        from . import redes
        ok = redes.entrenar("todas")
        return ("Entrenando las redes en segundo plano; el avance se ve en la vista de redes." if ok
                else (redes.estado["entreno"]["mensaje"] or "Ya estoy entrenando."))
    if re.fullmatch(r"(prueba|probar|prueba la frase|prueba en las redes)[:\s]+.+", t):
        from . import redes
        frase = re.sub(r"(?i)^\s*(prueba|probar)( la frase| en las redes)?[:\s]+", "", o).strip().strip("«»\"'")
        if frase:
            redes.probar(frase, None)
            _ped("redes", True)
            return "Probé la frase: en la vista de redes ves qué neuronas se encienden."
    if re.fullmatch(r"(intenciones|propuestas)( nuevas)? propuestas?|(que|cuales) intenciones (nuevas )?(propuse|hay propuestas)|propuestas de intenciones", t):
        from . import redes
        pr = redes.leer_propuestas()
        if not pr:
            return "No hay intenciones nuevas propuestas."
        return "Intenciones propuestas (les falta su acción): " + "; ".join(f"{p['nombre']} ({len(p['frases'])} frase(s))" for p in pr[:8]) + "."
    return None


def _h_rendimiento(m, t, o):
    from . import rendimiento
    if re.fullmatch(r"(activa|pon|enciende|quiero|usa)( el)? (modo )?(ahorro|alto rendimiento|rendimiento|ahorro de recursos)|(ahorra|ahorrar) recursos|haz (la interfaz )?mas (rapida|ligera)|(ve|va) lenta(.*)?", t):
        if rendimiento.activo():
            return "El modo ahorro ya está activo. Di «revertir ahorro» para volver."
        previstos = [f"{k} → {v}" for k, v in rendimiento.AHORRO.items() if ajustes.obtener(k) != v]
        if not previstos:
            return "Ya estás con todo lo ligero que el modo ahorro permite."
        return _pide_confirmacion(o, previstos, lambda: "Modo ahorro activado (" + str(len(rendimiento.aplicar())) +
                                  " ajustes). Di «revertir ahorro» para dejar todo como estaba.")
    if re.fullmatch(r"(revierte|revertir|quita|desactiva|apaga|vuelve a lo normal de)( el)?( modo)? (ahorro|alto rendimiento|rendimiento)|revertir ahorro", t):
        return "Dejé todo como estaba antes del ahorro." if rendimiento.revertir() else "El modo ahorro no estaba activo."
    if re.fullmatch(r"(activa|pon)( el)? (modo )?(rendimiento )?(automatico|auto)|rendimiento automatico", t):
        ajustes.fijar("rendimiento", "auto")
        return "Rendimiento automático: si la interfaz va lenta te lo propondré (nunca lo cambio sin preguntar)."
    return None


def _h_restaurar(m, t, o):
    if re.fullmatch(r"(restablece|restaura|resetea|reinicia|vuelve a|recupera)( la)? (distribucion|disposicion)( original| de fabrica| por defecto| predeterminada)?", t) and "anterior" not in t:
        return _pide_confirmacion(o, ["la distribución de este perfil vuelve a la de fábrica"],
                                  lambda: (perfiles.restablecer_distribucion()[1].capitalize() + ". Di «deshacer» si te arrepientes."))
    if re.fullmatch(r"(vuelve|volver|regresa|restablece|restaura|resetea)( a)?( la)? (configuracion|interfaz|apariencia|aspecto|todo)( original| de fabrica| por defecto| predeterminad[ao])|(restablece|resetea) (la )?interfaz", t):
        def aplicar():
            ev.crear_punto("antes de restablecer", auto=True)
            ajustes.aplicar_captura({k: ajustes.DEFAULTS[k] for k in ajustes.claves_visuales()})
            perfiles.restablecer_distribucion()
            tema.aplicar(ajustes.obtener("tema"))
            return "Volví a la configuración original (guardé un punto «antes de restablecer»)."
        return _pide_confirmacion(o, ["todos los ajustes visuales vuelven a los de fábrica", "la distribución vuelve a la original",
                                      "tus temas y perfiles no se borran"], aplicar)
    mm = re.match(r"^(?:crea|guarda|haz)(?: un)? punto de (?:restauracion|control)(?: (?:llamado|con nombre|que se llame))? ?(.*)$", t)
    if mm:
        return f"Guardé el punto de restauración «{ev.crear_punto(mm.group(1).strip().title())}»."
    mm = re.match(r"^(?:restaura|vuelve a|recupera|carga)(?: el)? punto(?: de restauracion)? (.+)$", t)
    if mm:
        return ev.restaurar_punto(mm.group(1))[1].capitalize() + ". Di «deshacer» si no era lo que querías."
    if re.fullmatch(r"(puntos de restauracion|mis puntos|lista de puntos|que puntos hay)", t):
        lista = ev.listar_puntos()
        if not lista:
            return "No hay puntos de restauración todavía. Di «crea un punto de restauración»."
        return "Puntos: " + "; ".join(f"{n}{' (auto)' if a else ''} {time.strftime('%d/%m %H:%M', time.localtime(ts))}" for n, a, ts in lista[:8]) + "."
    mm = re.match(r"^compara(?: el punto)? (.+?) (?:con|y|contra) (.+)$", t)
    if mm:
        r = ev.comparar(mm.group(1).strip(), mm.group(2).strip())
        if r is None:
            return "No encuentro uno de esos puntos (di «puntos de restauración»)."
        a, b, difs = r
        return f"{a} ↔ {b}: " + ("; ".join(difs[:10]) if difs else "son iguales") + ("…" if len(difs) > 10 else ".")
    mm = re.match(r"^(?:borra|elimina) el punto(?: de restauracion)? (.+)$", t)
    if mm:
        return ev.borrar_punto(mm.group(1))[1].capitalize() + "."
    return None


def _h_perfiles_admin(m, t, o):
    if re.fullmatch(r"(perfiles|mis perfiles|lista de perfiles|que perfiles hay|cuales son los perfiles)", t):
        return "Perfiles: " + ", ".join(f"{n}{' ◀' if n == perfiles.activo() else ''}" for n, _, _ in perfiles.listar()) + "."
    mm = re.match(r"^(?:guarda|guardar)(?: la interfaz| esta interfaz| esto| mi interfaz| el diseno)? como (?:perfil )?(.+)$|^(?:crea|nuevo) perfil(?: llamado)? (.+)$", t)
    if mm:
        ok, res = perfiles.guardar_como((mm.group(1) or mm.group(2)).strip().title())
        return f"Guardé tu interfaz como el perfil «{res}» y ahora lo estás usando." if ok else res.capitalize() + "."
    mm = re.match(r"^duplica(?: el)? perfil (.+?) (?:como|con nombre|llamado) (.+)$", t)
    if mm:
        ok, res = perfiles.crear(mm.group(2).strip().title(), mm.group(1))
        return f"Dupliqué el perfil como «{res}»." if ok else res.capitalize() + "."
    mm = re.match(r"^(?:renombra|cambiale el nombre al|cambia el nombre del) perfil (.+?) (?:a|como|por) (.+)$", t)
    if mm:
        ok, res = perfiles.renombrar(mm.group(1), mm.group(2).strip().title())
        return f"Ahora se llama «{res}»." if ok else res.capitalize() + "."
    mm = re.match(r"^(?:borra|elimina) (?:el )?perfil (.+)$", t)
    if mm:
        ok, res = perfiles.borrar(mm.group(1))
        return f"Borré el perfil «{res}»." if ok else res.capitalize() + "."
    mm = re.match(r"^restablece(?: el)? perfil(?: (.+))?$", t)
    if mm:
        real = perfiles.resolver(mm.group(1)) if mm.group(1) else perfiles.activo()
        if real is None:
            return f"No encuentro el perfil «{mm.group(1)}»."
        return _pide_confirmacion(o, [f"el perfil «{real}» vuelve a como venía de fábrica"],
                                  lambda: perfiles.restablecer(real)[1].capitalize() + ".")
    mm = re.match(r"^exporta(?:r)?(?: el)? perfil(?: (.+))?$", t)
    if mm:
        ok, res = perfiles.exportar(mm.group(1), carpeta_export())
        return f"Perfil exportado en {res}." if ok else res.capitalize() + "."
    mm = re.match(r"^(?:importa|importar|carga)(?: el)? (perfil|tema|copia|extension) (.+)$", t)
    if mm:
        ruta = re.sub(r'^["\']|["\']$', "", o.strip().split(None, 2)[-1].strip())
        tipo = mm.group(1)
        if tipo == "perfil":
            ok, res = perfiles.importar(ruta)
            msg = f"Importé el perfil «{res}». Di «perfil {res}» para usarlo." if ok else res
        elif tipo == "tema":
            ok, res = tema.importar(ruta)
            msg = f"Importé el tema «{res}»." if ok else res
        elif tipo == "extension":
            ok, res = extensiones.instalar(ruta)
            msg = res
        else:
            ok, res = ev.importar_copia(ruta)
            msg = res
        return msg[:1].upper() + msg[1:] + ("" if msg.endswith(".") else ".")
    if re.fullmatch(r"(copia de seguridad|haz una copia de seguridad|exporta(r)? (mi )?interfaz|exporta(r)? (mi )?configuracion|respalda la interfaz)", t):
        ok, res = ev.exportar_copia(carpeta_export())
        return f"Copia guardada en {res}." if ok else res
    mm = re.match(r"^sincroniza(?:r)? (?:con|en) (.+)$", t)
    if mm:
        carpeta = o.strip().split(None, 2)[-1].strip().strip('"\'')
        ajustes.fijar("sync_carpeta", carpeta)
        ok, res = ev.sincronizar("subir", carpeta)
        return (f"Sincronización lista con {carpeta}: {res}. En otro equipo di «sincroniza con la misma carpeta» y luego «trae la sincronización»."
                if ok else res.capitalize() + ".")
    if re.fullmatch(r"(trae|baja|descarga|recibe) (la )?sincronizacion", t):
        ok, res = ev.sincronizar("bajar")
        return res.capitalize() + "."
    if re.fullmatch(r"(sube|envia|actualiza) (la )?sincronizacion", t):
        ok, res = ev.sincronizar("subir")
        return res.capitalize() + "."
    if re.fullmatch(r"(extensiones|mis extensiones|que extensiones hay)", t):
        extensiones.escanear()
        lst = extensiones.listar()
        txt = ("Extensiones: " + "; ".join(f"{n} ({tp}{', permisos: ' + ', '.join(p) if p else ''})" for n, tp, p in lst) + ".") if lst \
            else "No hay extensiones. Copia un .json a Database/extensiones o di «importa extensión <ruta>»."
        if extensiones.errores:
            txt += " Rechazadas: " + " | ".join(extensiones.errores[:3])
        return txt
    if re.fullmatch(r"(galeria de extensiones|extensiones disponibles|que extensiones (hay|tienes) (en la galeria|para instalar)|galeria)", t):
        gal = extensiones.galeria()
        if not gal:
            return "La galería está vacía."
        return ("Galería: " + "; ".join(f"{n} ({tp}{', instalada' if ya else ''})" for n, _d, tp, ya in gal) +
                ". Di «instala la extensión <nombre>» o «instala todas las extensiones».")
    if re.fullmatch(r"(instala|instalar|agrega|anade) (todas )?(las )?extensiones( de la galeria)?", t):
        n, mal = extensiones.instalar_todas_de_galeria()
        return f"Instalé {n} extensión(es) de la galería." + (" Falló: " + "; ".join(mal[:2]) + "." if mal else "")
    if re.fullmatch(r"(busca|actualiza|recarga|vuelve a buscar) (las )?extensiones", t):
        extensiones.escanear()
        return f"{len(extensiones.listar())} extensión(es) cargadas." + (" Rechazadas: " + " | ".join(extensiones.errores[:3]) if extensiones.errores else "")
    mm = re.match(r"^(?:crea|haz|crear|nueva)(?: una| la)? extension (\w+)(?: llamada| que se llame| con nombre)? (.+)$", t)
    if mm:
        mo = re.search(r"(?i)extensi[oó]n\s+\w+\s+(?:llamada\s+|que se llame\s+|con nombre\s+)?(.+)$", o.strip())
        ok, res = extensiones.crear_plantilla(mm.group(1), (mo.group(1) if mo else mm.group(2)).strip())
        return res[:1].upper() + res[1:] + "."
    mm = re.match(r"^(?:instala|instalar|agrega|anade)(?: la)? extension (?!de |desde )(.+)$", t)
    if mm and not re.search(r"[\\/]|\.json", mm.group(1)):
        ok, res = extensiones.instalar_de_galeria(mm.group(1))
        return res[:1].upper() + res[1:] + "."
    mm = re.match(r"^(activa|enciende|desactiva|apaga)(?: la)? extension (.+)$", t)
    if mm:
        extensiones.escanear()
        f = extensiones.activar if mm.group(1) in ("activa", "enciende") else extensiones.desactivar
        _m = f(mm.group(2))[1]
        return _m[:1].upper() + _m[1:] + "."
    mm = re.match(r"^(?:quita|borra|elimina|desinstala)(?: la)? extension (.+)$", t)
    if mm:
        _m = extensiones.quitar(mm.group(1))[1]
        return _m[:1].upper() + _m[1:] + "."
    return None


def _h_ventanas(m, t, o):
    if re.fullmatch(r"(editar|edita|modo edicion|abre el editor|editor)( de)?( la)?( interfaz| distribucion| diseno| disposicion)?|edita(r)? (la )?(interfaz|distribucion|el diseno)|quiero (editar|mover) (la )?(interfaz|los paneles|los widgets)", t):
        return "Abrí el editor de diseño: arrastra los paneles, estira la esquina, ✕ oculta. Enter o «Listo» para salir." if _ped("editor", True) else "Necesito la ventana abierta: dime «abre la interfaz»."
    if re.fullmatch(r"(termina|cierra|sal del|salir del|deja de) ?(editar|edicion|editor)( de la interfaz)?|listo con el editor", t):
        _ped("editor", False)
        return "Cerré el editor."
    if re.fullmatch(r"(abre |muestra |ir a |ve a )?(el )?(centro de personalizacion|personalizar|personalizacion|ajustes de apariencia)", t):
        return "Te abrí el centro de personalización." if _ped("centro", True) else "Necesito la ventana abierta: dime «abre la interfaz»."
    mm = re.match(r"^(?:busca|buscar|donde esta|encuentra)(?: el)? ajuste (.+)$|^ajuste (.+)$", t)
    if mm:
        return "Busqué ese ajuste en el centro de personalización." if _ped("buscar_ajuste", (mm.group(1) or mm.group(2))) else "Necesito la ventana abierta."
    if re.fullmatch(r"(activa|pon|muestra|abre|enciende|quiero)( la)? (esfera flotante|burbuja|esfera aparte|esfera sobre las apps)", t):
        ajustes.fijar("flotante", True)
        return "Esfera flotante activada (arrástrala; doble clic abre la ventana)."
    if re.fullmatch(r"(quita|oculta|cierra|apaga|desactiva)( la)? (esfera flotante|burbuja)", t):
        ajustes.fijar("flotante", False)
        return "Esfera flotante apagada."
    if re.fullmatch(r"(activa|pon|usa|quiero)( la)? (ventana )?compacta|ventana compacta", t):
        ajustes.fijar("ventana_modo", "compacta")
        return "Ventana compacta (solo esfera y conversación)."
    if re.fullmatch(r"(ventana normal|modo normal|sal de(l modo)? compacta?|vuelve a la ventana normal)", t):
        ajustes.fijar("ventana_modo", "normal")
        return "Ventana normal."
    if re.fullmatch(r"(activa|pon|usa|quiero)( el)? (modo )?(superpuest[ao]|overlay|panel sobre el escritorio)", t):
        ajustes.fijar("ventana_modo", "superpuesta")
        return "Modo superpuesto: sin bordes, semitransparente y siempre visible."
    if re.fullmatch(r"(mantenla|pon la ventana|deja la ventana|mantener la ventana) siempre visible|siempre visible|siempre al frente|(mantenla|pon la ventana) al frente", t):
        ajustes.fijar("ventana_siempre_visible", True)
        return "La ventana se queda siempre al frente."
    if re.fullmatch(r"(ya no |quita |desactiva )?(siempre visible|siempre al frente)( la ventana)?", t) and re.match(r"^(ya no|quita|desactiva)", t):
        ajustes.fijar("ventana_siempre_visible", False)
        return "La ventana ya no se queda siempre al frente."
    if re.fullmatch(r"(activa|pon|muestra|enciende)( el)? icono( en la)?( bandeja)?( del sistema)?|icono en la bandeja", t):
        ajustes.fijar("bandeja", True)
        return "Pedí el icono de la bandeja (necesita «pip install pystray pillow»; si falta te lo aviso en la ventana)."
    mm = re.match(r"^(?:saca|desacopla|separa|abre en una ventana|pon en (?:una )?ventana(?: aparte)?|ventana independiente(?: para| de)?) (?:el |la |los |las )?(.+?)(?: a una ventana(?: aparte)?| en una ventana(?: aparte)?)?$", t)
    if mm:
        w = _w(mm.group(1))
        if w is None:
            return None
        if w["tipo"] == "chat":
            return "El chat no se puede separar porque aquí vive la caja de escritura; para escribir desde otro sitio usa el buscador (Ctrl+Espacio)."
        return (f"{layout.nombre_de(w['tipo'])} ahora está en su propia ventana (cierra esa ventana para volver a ponerlo en el panel)."
                if _ped("desacoplar", w["id"]) else "Necesito la ventana abierta: dime «abre la interfaz».")
    return None


def _h_notas(m, t, o):
    mm = re.match(r"^(?:nota|anota|apunta|anotar|apuntar|recuerdame que anote)\s*[:\-]?\s+(.+)$", o.strip(), re.I)
    if mm and not re.match(r"^(nota|notas)$", t):
        txt = mm.group(1).strip()
        lista = list(ajustes.obtener("notas")) + [txt[:200]]
        ajustes.fijar("notas", lista[-30:])
        return "Anotado: " + txt[:60]
    mm = re.match(r"^(?:borra|elimina|quita) la nota (\d+)$", t)
    if mm:
        i = int(mm.group(1)) - 1
        lista = list(ajustes.obtener("notas"))
        if 0 <= i < len(lista):
            lista.pop(i)
            ajustes.fijar("notas", lista)
            return "Borré la nota."
        return "No tengo esa nota."
    if re.fullmatch(r"(borra|elimina|quita|limpia) (todas )?(las )?notas", t):
        ajustes.fijar("notas", [])
        return "Borré todas las notas."
    return None


def _h_favoritos(m, t, o):
    mm = re.match(r"^(?:fija|anade|agrega|pon)(?: en| a)? favoritos? (.+)$", o.strip(), re.I)
    if mm:
        lista = [f for f in ajustes.obtener("favoritos") if f != mm.group(1).strip()] + [mm.group(1).strip()]
        ajustes.fijar("favoritos", lista[-8:])
        return f"«{mm.group(1).strip()}» quedó fijada en favoritos."
    mm = re.match(r"^(?:quita|borra|desfija)(?: de)? favoritos? (.+)$", t)
    if mm:
        lista = [f for f in ajustes.obtener("favoritos") if _limpio(f) != mm.group(1).strip()]
        ajustes.fijar("favoritos", lista)
        return "Quité ese favorito."
    mm = re.match(r"^(?:crea|agrega|anade|añade)(?: un)? (?:acceso directo|atajo) (.+?) (?:que haga|para|con la orden|=>) (.+)$", o.strip(), re.I)
    if mm:
        lista = list(ajustes.obtener("atajos_rapidos")) + [{"texto": mm.group(1).strip()[:20], "orden": mm.group(2).strip()[:120]}]
        ajustes.fijar("atajos_rapidos", lista[-12:])
        return f"Acceso directo «{mm.group(1).strip()}» creado."
    return None


def _h_mascota(m, t, o):
    mm = re.match(r"^(?:pon|usa|cambia a|quiero)(?: la| el)? (?:mascota )?(esfera|minimal|minimalista|imagen)$|^mascota (esfera|minimal|imagen)$", t)
    if mm:
        q = (mm.group(1) or mm.group(2)).replace("minimalista", "minimal")
        if q == "imagen":
            from . import mascota as mm_
            if not os.path.isdir(getattr(mm_, "CARPETA_IMAGENES", "")) and not mm_.imagenes():
                return "Copia una imagen PNG a Database/mascotas y vuelvo a intentarlo."
        ajustes.fijar("mascota_personaje", q)
        ajustes.fijar("mascota", True)
        return f"Mascota: {q}."
    mm = re.match(r"^(?:haz|pon)(?: a)? (?:la )?mascota (?:mas )?(grande|pequena|chica|pequeno)$", t)
    if mm:
        n = ajustes.fijar("mascota_tamano", ajustes.obtener("mascota_tamano") + (25 if mm.group(1) == "grande" else -25))
        return f"Mascota al {n}%."
    if re.fullmatch(r"(la )?mascota (solo )?(de vez en cuando|temporal|a ratos|temporalmente)|que la mascota aparezca a ratos", t):
        ajustes.fijar("mascota_visibilidad", "temporal")
        return "La mascota aparecerá solo cuando tenga algo que decir."
    if re.fullmatch(r"(la )?mascota (siempre|siempre visible|permanente)", t):
        ajustes.fijar("mascota_visibilidad", "siempre")
        return "La mascota se queda siempre visible."
    if re.fullmatch(r"(mascota|personaje) (flotante|aparte)|(saca|pon) la mascota (flotante|aparte|fuera)", t):
        ajustes.fijar("mascota_flotante", True)
        ajustes.fijar("flotante", True)
        ajustes.fijar("flotante_contenido", "mascota")
        return "La mascota ahora flota sobre otras apps."
    return None


def _h_tema_horario(m, t, o):
    if re.fullmatch(r"(activa|pon|quiero)( el)? (cambio )?(de )?tema (automatico|por hora|segun la hora|por horario)|tema automatico", t):
        ajustes.fijar("tema_horario", True)
        return f"Cambiaré de tema solo: «{ajustes.obtener('tema_dia')}» de 7:00 a 19:00 y «{ajustes.obtener('tema_noche')}» el resto. Cámbialos con «tema de día X» y «tema de noche Y»."
    if re.fullmatch(r"(desactiva|quita|apaga)( el)? (cambio )?(de )?tema (automatico|por hora|segun la hora|por horario)", t):
        ajustes.fijar("tema_horario", False)
        return "Tema fijo otra vez."
    mm = re.match(r"^tema de (dia|noche)(?: a| es| sera)? (.+)$", t)
    if mm:
        real = tema.resolver(mm.group(2))
        if real is None:
            return f"No tengo un tema «{mm.group(2)}»."
        ajustes.fijar("tema_dia" if mm.group(1) == "dia" else "tema_noche", real)
        return f"Tema de {mm.group(1)}: {real}."
    return None


def _h_pantalla(m, t, o):
    mm = re.match(r"^(?:usa|pon|guarda|asigna) (?:el )?perfil (.+?) (?:en|para) (?:pantallas? |monitor(?:es)? |ventanas? )?(pequenas?|chicas?|normales?|amplias?|grandes?)$", t)
    if mm:
        real = perfiles.resolver(mm.group(1))
        if real is None:
            return f"No tengo el perfil «{mm.group(1)}»."
        clase = {"pequenas": "pequena", "chicas": "pequena", "chica": "pequena", "normales": "normal", "amplias": "amplia",
                 "grandes": "amplia", "grande": "amplia", "amplia": "amplia", "normal": "normal", "pequena": "pequena"}[mm.group(2)]
        d = dict(ajustes.obtener("pantallas"))
        d[clase] = real
        ajustes.fijar("pantallas", d)
        return f"En pantallas {clase}s usaré el perfil «{real}»."
    if re.fullmatch(r"(olvida|quita|borra) (los )?perfiles por pantalla", t):
        ajustes.fijar("pantallas", {})
        return "Ya no cambio de perfil según la pantalla."
    return None


def _h_contexto(m, t, o):
    mm = re.match(r"^(activa|permite|desactiva|no permitas|quita)( el)? (panel de progreso|progreso automatico|resultados en ventana|reposo automatico|reducir en reposo)$", t)
    if mm:
        on = mm.group(1) in ("activa", "permite")
        clave = {"panel de progreso": "ctx_progreso", "progreso automatico": "ctx_progreso", "resultados en ventana": "ctx_resultados",
                 "reposo automatico": "ctx_reposo", "reducir en reposo": "ctx_reposo"}[mm.group(3)]
        ajustes.fijar(clave, on)
        return f"Adaptación «{mm.group(3)}»: " + ("permitida." if on else "apagada.")
    return None


def _h_estado(m, t, o):
    if re.fullmatch(r"(que perfil estoy usando|perfil actual|en que perfil estoy)", t):
        return f"Estás en el perfil «{perfiles.activo()}», con el tema «{tema.actual()}»."
    if re.fullmatch(r"(que widgets hay|que componentes hay|componentes|widgets|lista de widgets|que puedo agregar|biblioteca de widgets)", t):
        lay = perfiles.layout_actual()
        vis = [layout.nombre_de(w["tipo"]) for w in lay["widgets"] if w["visible"]]
        otros = [layout.nombre_de(tp) for tp in layout.tipos() if not any(w["tipo"] == tp and w["visible"] for w in lay["widgets"]) and not layout.info(tp)[6] or
                 (layout.info(tp)[6] and not any(w["tipo"] == tp for w in lay["widgets"]))]
        ocultos = [layout.nombre_de(w["tipo"]) for w in lay["widgets"] if not w["visible"]]
        return ("Visibles: " + ", ".join(vis) + ". Ocultos: " + (", ".join(ocultos) or "ninguno") + ". Disponibles para agregar: " +
                ", ".join(sorted(set(otros))) + ".")
    return None


def _h_orden(m, t, o):
    """Orden de la pantalla: paginas, cajon, plegar, tarjetas, tope y modos (ver orden.py)."""
    from . import orden
    return orden.responder(t, o)


_MANEJADORES = (_h_confirmar, _h_deshacer, _h_orden, _h_perfil, _h_minimalista, _h_tema_propio, _h_tema, _h_tema_horario,
                _h_animaciones, _h_efectos, _h_accesibilidad, _h_chat, _h_redes, _h_rendimiento, _h_restaurar, _h_perfiles_admin,
                _h_ventanas, _h_notas, _h_favoritos, _h_mascota, _h_pantalla, _h_contexto, _h_estado,
                _h_widget_mover, _h_widget_visibilidad)


def responder(texto):
    """Devuelve el mensaje de Arché si la frase era de personalizacion, o None si no lo era."""
    if not isinstance(texto, str) or not texto.strip() or len(texto) > 240:
        return None
    t = _limpio(texto)
    if not t:
        return None
    antes = ev.capturar(False)
    for h in _MANEJADORES:
        try:
            msg = h(None, t, texto)
        except Exception as e:      # un error aqui nunca debe tumbar a Arché: la frase sigue su camino
            print(f"[interfaz] no pude interpretar «{texto[:40]}»: {e}")
            return None
        if msg:
            if h.__name__ not in ("_h_confirmar", "_h_deshacer"):
                ev.empujar(antes, texto.strip()[:60])
            return msg
    return None
