"""
orden.py
--------
Ubicacion: Arche/core/interfaz/orden.py

Que la pantalla no quede llena de cosas. Ocho ideas, todas apagables y
personalizables (PERSONALIZA > Orden):

  1. Paneles que aparecen solos: un widget marcado «solo si hay algo» se
     muestra cuando hay algo que hacer y se va cuando ya no.
  2. El cajon: las extensiones y los paneles que no tienes en pantalla se abren
     en un panel temporal; solo fijas unos pocos.
  3. Paginas (Inicio, Arché, Mi día, Equipo...) que cambias con un boton o una tecla.
  4. Tarjeta con pestañas: varios paneles en uno.
  5. Paneles plegables: se encogen a una linea y se abren al tocarlos.
  6. Carrusel: varios paneles que rotan en el mismo sitio (bueno para la TV).
  7. Tope de paneles: si pasas del limite, propone ocultar los que menos usas.
  8. Modos con su propio orden (trabajo, TV, noche), por hora o por frase.

Aqui no hay nada de dibujo pesado: se calcula que se ve y donde (objetivos),
y se dibujan las piezas nuevas (barra de paginas, cajon, contenedores, barra
plegada). El resto sigue siendo layout.py, perfiles.py y ventana.py.
Todo lo que toca la pantalla ocurre en el hilo de la ventana.
"""

import re
import time

from . import ajustes, en_vivo, layout, perfiles, tema

estado = {
    "pagina": "",          # pagina que se ve
    "cajon": False,        # el cajon esta abierto
    "cajon_tipo": None,    # panel abierto dentro del cajon (tipo)
    "sel": {},             # contenedor -> indice elegido
    "pausa": {},           # carrusel -> hasta cuando no rota
    "abiertos": {},        # widget plegado -> cuando lo abriste (se vuelve a plegar solo)
    "visto": {},           # widget «solo si hay algo» -> ultima vez que habia algo
    "cond": {},            # cache de condiciones: id -> (hora, valor)
    "uso_pend": 0,
    "regla": None,         # regla de horario aplicada ahora
    "previo": None,        # perfil que tenias antes de esa regla
    "propuestas": {},      # firma -> hora (para no repetir la misma propuesta)
    "t_tope": 0.0,
    "t_modos": 0.0,
    "ocultos_auto": set(),  # ids de paneles «solo si hay algo» que ahora no se ven (no cuentan para el tope)
}

PAGINAS_TIPICAS = ("Inicio", "Arché", "Mi día", "Equipo")
IMPRESCINDIBLES = ("voz", "chat", "mascota", "panel", "pestanas", "carrusel")
ALTO_PLEGADO = 36        # pixeles (a escala 1) de un panel plegado

# tipo -> condicion por defecto de «solo si hay algo»
TIPO_COND = {"notificaciones": "hay_avisos", "progreso": "algo_en_curso", "recordatorios": "hay_alarmas",
             "mejora": "hay_mejoras", "redes": "redes_sin_entrenar"}


# ------------------------------------------------------------------ condiciones («hay algo»)
def _c_avisos(v, wd):
    ahora = time.time()
    n = sum(1 for a in list(getattr(v, "historial_notif", [])) if ahora - a.get("ts", 0) < 90)
    return n > 0, f"{n} aviso(s)"


def _c_en_curso(v, wd):
    try:
        if en_vivo.estado_visual() not in ("reposo",):
            return True, "Arché está trabajando"
        act = [p for p in v.snap.get("procesos", []) if p.get("activo") and p.get("nombre") in ("Acción en el PC", "Orden automática")]
        return bool(act), "tareas en curso"
    except Exception:
        return False, ""


def _c_alarmas(v, wd):
    n = len(v.snap.get("hoy", {}).get("alarmas", []))
    return n > 0, f"{n} alarma(s)"


def _c_mejoras(v, wd):
    from . import redes
    n = len(redes.recientes_auto(1) or [])
    return n > 0, "mejoras recientes"


def _c_redes(v, wd):
    from . import redes
    s = redes.snapshot()
    if not s.get("listo"):
        return False, ""
    n = sum(r.get("pendientes", 0) for r in s.get("redes", []))
    return n > 0, f"{n} ejemplo(s) sin entrenar"


def _c_no_entendidas(v, wd):
    from . import bloques_ext
    fil = bloques_ext._f_no_entendidas(v, None, 1).get("filas", [])
    return bool(fil and fil[0][2]), "frases sin entender"


def _c_dudosas(v, wd):
    from . import bloques_ext
    fil = bloques_ext._f_dudosas(v, None, 1).get("filas", [])
    return bool(fil and fil[0][2]), "frases dudosas"


def _c_temporizador(v, wd):
    from . import bloques_ext
    return any(t.get("fin") is not None for t in bloques_ext._temps.values()), "temporizador corriendo"


def _c_lista(v, wd):
    from . import bloques_ext, extensiones
    ext = extensiones._cargadas.get(str(wd.get("tipo", ""))[4:])
    if not ext:
        return False, ""
    for b in ext["bloques"]:
        if b["tipo"] in ("lista", "fechas", "gastos") and b.get("archivo"):
            return bool(bloques_ext._lineas_archivo(ext, b["archivo"])), "la lista tiene algo"
    return True, ""


def _c_alerta(v, wd):
    eq = v.snap.get("equipo", {})
    return (eq.get("cpu", 0) >= ajustes.obtener("limite_cpu") or eq.get("ram", 0) >= ajustes.obtener("limite_ram")), "el equipo va al límite"


# nombre -> (funcion, como se lo dice a la persona)
CONDICIONES = {
    "hay_avisos": (_c_avisos, "hay avisos recientes"),
    "algo_en_curso": (_c_en_curso, "Arché está haciendo algo"),
    "hay_alarmas": (_c_alarmas, "hay alarmas pendientes"),
    "hay_mejoras": (_c_mejoras, "mejoré algo sola"),
    "redes_sin_entrenar": (_c_redes, "hay ejemplos sin entrenar"),
    "hay_no_entendidas": (_c_no_entendidas, "hay frases sin entender"),
    "hay_dudosas": (_c_dudosas, "hay frases dudosas"),
    "temporizador_activo": (_c_temporizador, "un temporizador está corriendo"),
    "hay_en_lista": (_c_lista, "la lista tiene algo"),
    "alerta_equipo": (_c_alerta, "el equipo va al límite"),
}


def condicion_de(wd):
    """Nombre de la condicion de «solo si hay algo» de un widget (la tuya, la de la extension o la del tipo)."""
    c = (wd.get("opts") or {}).get("condicion")
    if c in CONDICIONES:
        return c
    tipo = wd.get("tipo", "")
    if tipo.startswith("ext:"):
        try:
            from . import extensiones
            e = extensiones._cargadas.get(tipo[4:])
            if e and e.get("aparece_si") in CONDICIONES:
                return e["aparece_si"]
        except Exception:
            pass
        return None
    return TIPO_COND.get(tipo)


def hay_algo(v, wd):
    """True/False si se puede saber; None si este widget no tiene condicion."""
    nombre = condicion_de(wd)
    if nombre is None:
        return None
    ahora = time.time()
    c = estado["cond"].get(wd["id"])
    if c and ahora - c[0] < 0.7:
        return c[1]
    try:
        val = bool(CONDICIONES[nombre][0](v, wd)[0])
    except Exception:
        val = True       # ante la duda, que se vea: nunca esconder por un error
    estado["cond"][wd["id"]] = (ahora, val)
    return val


def _visible_ahora(v, wd):
    """Aplica «aparece»: siempre / solo si hay algo (con 8 s de gracia para que no parpadee)."""
    if (wd.get("opts") or {}).get("aparece") != "si_hay" or not ajustes.obtener("orden_auto"):
        return True
    h = hay_algo(v, wd)
    if h is None:
        return True
    ahora = time.time()
    if h:
        estado["visto"][wd["id"]] = ahora
        return True
    return ahora - estado["visto"].get(wd["id"], 0) < 8


# ------------------------------------------------------------------ paginas
def pagina_actual(lay=None):
    lay = lay or perfiles.layout_actual()
    ps = layout.paginas_de(lay)
    if estado["pagina"] not in ps:
        estado["pagina"] = ps[0]
    return estado["pagina"]


def ir_a_pagina(nombre):
    lay = perfiles.layout_actual()
    ps = layout.paginas_de(lay)
    t = layout._limpio(nombre)
    for p in ps:
        if layout._limpio(p) == t:
            estado["pagina"] = p
            layout.PAGINA_ACTUAL = p
            return True, p
    if t.isdigit() and 1 <= int(t) <= len(ps):
        estado["pagina"] = ps[int(t) - 1]
        layout.PAGINA_ACTUAL = estado["pagina"]
        return True, estado["pagina"]
    return False, ""


def pagina_vecina(paso):
    lay = perfiles.layout_actual()
    ps = layout.paginas_de(lay)
    i = ps.index(pagina_actual(lay)) if pagina_actual(lay) in ps else 0
    estado["pagina"] = ps[(i + paso) % len(ps)]
    layout.PAGINA_ACTUAL = estado["pagina"]
    return estado["pagina"]


def _reparar(lay):
    nuevo = layout.validar(lay)
    lay.clear()
    lay.update(nuevo)


def crear_pagina(nombre):
    lay = perfiles.layout_actual()
    n = " ".join(str(nombre).split())[:20]
    if not n or n == "*":
        return False, "dime cómo se llama la página"
    if any(layout._limpio(p) == layout._limpio(n) for p in layout.paginas_de(lay)):
        return False, f"ya existe una página «{n}»"
    if len(layout.paginas_de(lay)) >= 8:
        return False, "el máximo son 8 páginas"
    lay["paginas"] = layout.paginas_de(lay) + [n]
    perfiles.marcar_sucio()
    estado["pagina"] = n
    layout.PAGINA_ACTUAL = n
    return True, f"creé la página «{n}» y ya estás en ella"


def borrar_pagina(nombre):
    lay = perfiles.layout_actual()
    ps = layout.paginas_de(lay)
    real = next((p for p in ps if layout._limpio(p) == layout._limpio(nombre)), None)
    if real is None:
        return False, f"no hay una página «{nombre}»"
    if len(ps) == 1:
        return False, "tiene que quedar al menos una página"
    mov = [w for w in lay["widgets"] if (w.get("opts") or {}).get("pagina") == real]
    for w in mov:
        w["opts"].pop("pagina", None)
    lay["paginas"] = [p for p in ps if p != real]
    _reparar(lay)
    perfiles.marcar_sucio()
    pagina_actual(lay)
    return True, f"borré la página «{real}»" + (f"; sus {len(mov)} panel(es) pasaron a «{lay['paginas'][0]}»" if mov else "")


def renombrar_pagina(nombre, nuevo):
    lay = perfiles.layout_actual()
    ps = layout.paginas_de(lay)
    real = next((p for p in ps if layout._limpio(p) == layout._limpio(nombre)), None)
    nuevo = " ".join(str(nuevo).split())[:20]
    if real is None or not nuevo or nuevo == "*":
        return False, "no encuentro esa página"
    for w in lay["widgets"]:
        if (w.get("opts") or {}).get("pagina") == real:
            w["opts"]["pagina"] = nuevo
    lay["paginas"] = [nuevo if p == real else p for p in ps]
    if estado["pagina"] == real:
        estado["pagina"] = nuevo
    perfiles.marcar_sucio()
    return True, f"«{real}» ahora se llama «{nuevo}»"


# ------------------------------------------------------------------ uso real (clics)
def registrar_uso(v, x, y):
    """Cuenta el clic para el widget que esta debajo (sirve para proponer que ocultar)."""
    for wid, (rx, ry, rw, rh) in list(getattr(v, "rects", {}).items()):
        if rx <= x <= rx + rw and ry <= y <= ry + rh:
            w = layout.buscar(perfiles.layout_actual(), wid)
            if w is None:
                return
            clave = w["tipo"]
            uso = dict(ajustes.obtener("orden_uso") or {})
            uso[clave] = int(uso.get(clave, 0)) + 1
            estado["uso_pend"] += 1
            if estado["uso_pend"] >= 5 or len(uso) != len(ajustes.obtener("orden_uso") or {}):
                estado["uso_pend"] = 0
                ajustes.fijar("orden_uso", uso)
            else:
                ajustes.obtener("orden_uso").update(uso)
            return


def uso_de(tipo):
    return int((ajustes.obtener("orden_uso") or {}).get(tipo, 0))


# ------------------------------------------------------------------ que se ve y donde
def plegado_efectivo(v, wd):
    """True si el panel se dibuja plegado ahora mismo."""
    if not ajustes.obtener("orden_activo") or v.editando:
        return False
    if not (wd.get("opts") or {}).get("plegado"):
        return False
    t = estado["abiertos"].get(wd["id"])
    if t is None:
        return True
    seg = int(ajustes.obtener("orden_plegar_auto"))
    if seg and time.time() - t > seg:
        estado["abiertos"].pop(wd["id"], None)
        return True
    return False


def objetivos(v, lay, m, top, cw, ch, gap, bajo):
    """{id: (x, y, w, h)} en pixeles de lo que se dibuja: pagina actual, paneles que aparecen solos,
    plegados y huecos cerrados. En modo diseño se ve todo lo de la pagina tal cual."""
    A = ajustes.obtener
    pag = pagina_actual(lay)
    layout.PAGINA_ACTUAL = pag
    if estado.get("dibujada") != pag:                 # al cambiar de pagina, sin animacion de «crecer»
        estado["dibujada"] = pag
        v._vis.clear()
        v._vis_listo = False
    activo = A("orden_activo") and not v.editando
    esc = v._esc()
    base = []                      # (wd, x, y, w, h, alto_efectivo)
    for wd in lay["widgets"]:
        if not wd["visible"] or wd.get("ventana") or layout.en_contenedor(wd):
            continue
        p = layout.pagina_de(wd, lay)
        if p != "*" and p != pag:
            continue
        x, y = m + wd["x"] * cw + gap / 2, top + wd["y"] * ch + gap / 2
        w, h = wd["w"] * cw - gap, wd["h"] * ch - gap
        eh = h
        if activo:
            if not _visible_ahora(v, wd):
                continue_flag = True
            else:
                continue_flag = False
            if continue_flag:
                base.append((wd, x, y, w, h, 0.0))
                continue
            if plegado_efectivo(v, wd):
                eh = min(h, ALTO_PLEGADO * esc)
        base.append((wd, x, y, w, h, eh))
    sal, plegados = {}, set()
    compactar = activo and A("orden_compactar") and any(b[5] < b[4] - 0.5 for b in base)
    if compactar:
        quitados = [(b[1], b[1] + b[3], b[2] + b[4], b[4] - b[5] + (gap if b[5] <= 0 else 0)) for b in base if b[5] < b[4] - 0.5]   # x0,x1,fondo,liberado
        puestos = []           # (x0, x1, y, alto) ya colocados
        fondo_total = top + layout.FILAS * ch
        for wd, x, y, w, h, eh in sorted(base, key=lambda b: (b[2], b[1])):
            if eh <= 0:
                continue
            sube = 0.0
            for qx0, qx1, qfondo, d in quitados:
                if qx0 < x + w - 1 and x < qx1 - 1 and qfondo <= y + 1:
                    sube += d
            ny = y - sube
            for px0, px1, py, pa in puestos:
                if px0 < x + w - 1 and x < px1 - 1 and py + pa + gap > ny and py < y:
                    ny = max(ny, py + pa + gap)
            alto = eh
            if A("orden_rellenar") and sube > 0 and (y + h) >= fondo_total - gap * 2 and eh >= h - 0.5:
                alto = eh + (y - ny)
            puestos.append((x, x + w, ny, alto))
            sal[wd["id"]] = (x, ny, w, alto)
            if eh < h - 0.5:
                plegados.add(wd["id"])
    else:
        for wd, x, y, w, h, eh in base:
            if eh <= 0:
                continue
            sal[wd["id"]] = (x, y, w, eh)
            if eh < h - 0.5:
                plegados.add(wd["id"])
    v._orden_plegados = plegados
    estado["ocultos_auto"] = {b[0]["id"] for b in base if b[5] <= 0}
    return sal


# ------------------------------------------------------------------ dibujo: plegado y boton de plegar
def dibujar_plegado(v, wd, x, y, w, h):
    esc = v._esc()
    col = wd.get("color") or tema.MORADO_CLARO
    v._tarjeta(x, y, w, h, "", col)
    nombre = (wd.get("titulo") or _nombre(wd)).upper()
    v._texto(x + 32 * esc, y + h / 2, nombre[:max(4, int((w - 90 * esc) / (7.4 * esc)))], 10, col, negrita=True)
    v.canvas.create_oval(x + 16 * esc, y + h / 2 - 4 * esc, x + 24 * esc, y + h / 2 + 4 * esc, fill=col, outline="", tags=v._tag)
    h_ = hay_algo(v, wd) if (wd.get("opts") or {}).get("aparece") == "si_hay" else None
    if h_:
        v._texto(x + w - 40 * esc, y + h / 2, "●", 9, tema.ATENCION, ancla="e")
    v._texto(x + w - 18 * esc, y + h / 2, "▸", 11, tema.TENUE, ancla="e")
    v.zonas.append((x, y, x + w, y + h, ("ord", "abrir", wd["id"])))


def _nombre(wd):
    return layout.nombre_de(wd["tipo"])


def boton_plegar(v, wd, x, y, w, h):
    """Boton «–» que aparece al pasar el mouse sobre un panel (o siempre, segun Ajustes)."""
    modo = ajustes.obtener("orden_plegar_boton")
    if modo == "nunca" or v.editando or not ajustes.obtener("orden_activo") or layout.en_contenedor(wd):
        return
    esc = v._esc()
    mx, my = v.mouse
    sobre = x <= mx <= x + w and y <= my <= y + h
    if modo == "al_pasar" and not sobre:
        return
    if wd["tipo"] in ("panel",) or h < 70 * esc or w < 110 * esc:
        return
    bw = 22 * esc
    x0, y0 = x + w - bw - 8 * esc, y + 7 * esc
    accion = ("ord", "plegar", wd["id"])
    v._redondo(x0, y0, x0 + bw, y0 + bw * 0.8, 8 * esc, fill=tema.mezclar(tema.BOTON, tema.TENUE, 0.2 if v.hover != accion else 0.5), outline=tema.BORDE)
    v._texto(x0 + bw / 2, y0 + bw * 0.4, "–", 11, tema.TEXTO, ancla="center", negrita=True)
    v.zonas.append((x0, y0, x0 + bw, y0 + bw * 0.8, accion))


# ------------------------------------------------------------------ contenedores (pestañas y carrusel)
def _miembros(lay, cont):
    ids = (cont.get("opts") or {}).get("miembros", [])
    return [w for i in ids for w in lay["widgets"] if w["id"] == i]


def _etiqueta(w, ancho):
    t = w.get("titulo") or _nombre(w)
    if len(t) <= ancho:
        return t
    palabras, corto = t.split(), ""
    for p in palabras:                                # primero intenta con las primeras palabras enteras
        if len((corto + " " + p).strip()) > ancho:
            break
        corto = (corto + " " + p).strip()
    return corto if len(corto) >= 4 else t[:max(3, ancho - 1)] + "…"


def indice_activo(v, cont, n):
    if n <= 0:
        return 0
    sel = estado["sel"].get(cont["id"], 0) % n
    if cont["tipo"] == "carrusel":
        ahora = time.time()
        if ahora < estado["pausa"].get(cont["id"], 0):
            return sel
        seg = max(3, int(ajustes.obtener("orden_carrusel_seg")))
        return int(ahora / seg) % n if n > 1 else 0
    return sel


def dibujar_contenedor(v, cont, x, y, w, h, esc):
    lay = perfiles.layout_actual()
    ms = _miembros(lay, cont)
    col = cont.get("color") or tema.MORADO_CLARO
    if not ms:
        v._tarjeta(x, y, w, h, (cont.get("titulo") or _nombre(cont)).upper(), col)
        v._texto(x + 16 * esc, y + 50 * esc, "Está vacía. En PERSONALIZA > Orden eliges qué paneles van aquí,", 9, tema.TENUE, ancho=w - 32 * esc)
        v._texto(x + 16 * esc, y + 84 * esc, "o di: «agrupa el reloj y las notas en pestañas».", 9, tema.TENUE, ancho=w - 32 * esc)
        return
    i = indice_activo(v, cont, len(ms))
    tira = 26 * esc
    if cont["tipo"] == "pestanas":
        disp = w
        por = max(5, int(disp / len(ms) / (6.6 * esc)) - 3)
        px = x
        for k, mw in enumerate(ms):
            txt = _etiqueta(mw, por)
            cw = min((len(txt) * 6.6 + 20) * esc, disp / len(ms))
            if px + cw > x + w + 1:
                break
            px = v._chip(px, y, txt, ("ord", "pestana", cont["id"], k), k == i, mw.get("color") or col, cw) + 4 * esc
    else:
        v._chip(x, y, "‹", ("ord", "pestana", cont["id"], (i - 1) % len(ms)), False, col, 26 * esc)
        v._chip(x + w - 26 * esc, y, "›", ("ord", "pestana", cont["id"], (i + 1) % len(ms)), False, col, 26 * esc)
        v._texto(x + w / 2, y + 11 * esc, _etiqueta(ms[i], 30), 9, col, ancla="center", negrita=True)
        total = len(ms) * 12 * esc
        for k in range(len(ms)):
            cx = x + w / 2 - total / 2 + k * 12 * esc + 6 * esc
            v.canvas.create_oval(cx - 3 * esc, y + tira - 2 * esc, cx + 3 * esc, y + tira + 4 * esc,
                                 fill=col if k == i else tema.BORDE, outline="", tags=v._tag)
        tira += 8 * esc
    miembro = ms[i]
    sub = dict(miembro)
    sub["opts"] = dict(miembro.get("opts") or {})
    v._pintar_widget(sub, x, y + tira + 4 * esc, w, max(40 * esc, h - tira - 4 * esc))
    v._wd = None


# ------------------------------------------------------------------ cajon
def abrir_cajon(abrir=True):
    estado["cajon"] = bool(abrir)
    if not abrir:
        estado["cajon_tipo"] = None


def tipos_del_cajon():
    """[(tipo, nombre, detalle, es_ext)] lo que el cajon ofrece: extensiones y paneles que no estan en esta pagina."""
    lay = perfiles.layout_actual()
    pag = pagina_actual(lay)
    sal = []
    for t in layout.tipos():
        if t in IMPRESCINDIBLES or t == "panel":
            continue
        en_pantalla = any(w["tipo"] == t and w["visible"] and not w.get("ventana") and not layout.en_contenedor(w)
                          and layout.pagina_de(w, lay) in ("*", pag) for w in lay["widgets"])
        if en_pantalla:
            continue
        i = layout.info(t)
        det = i[7]
        if t.startswith("ext:"):
            try:
                from . import extensiones
                det = (extensiones._cargadas.get(t[4:]) or {}).get("descripcion") or "Extensión instalada."
            except Exception:
                pass
        sal.append((t, i[0], det, t.startswith("ext:")))
    sal.sort(key=lambda r: (not r[3], r[1].lower()))
    return sal


def fijar_desde_cajon(tipo):
    lay = perfiles.layout_actual()
    if tipo.startswith("ext:"):
        topes = int(ajustes.obtener("orden_cajon_fijos"))
        fijas = [w for w in lay["widgets"] if w["tipo"].startswith("ext:") and w["visible"] and not w.get("ventana") and not layout.en_contenedor(w)]
        if topes and len(fijas) >= topes and not any(w["tipo"] == tipo for w in fijas):
            return False, f"ya tienes {len(fijas)} extensiones fijas (máximo {topes}); suelta una al cajón o sube el máximo"
    ok, msg = layout.anadir(lay, tipo)
    perfiles.marcar_sucio()
    if ok:
        estado["cajon_tipo"] = None
    return ok, ("fijé «" + layout.nombre_de(tipo) + "» en la página " + pagina_actual(lay)) if ok else \
        f"{msg} en «{pagina_actual(lay)}»; puedes seguir viéndolo en el cajón o pasar a otra página"


def mandar_al_cajon(wid):
    lay = perfiles.layout_actual()
    w = layout.buscar(lay, wid)
    if w is None:
        return False, "no encuentro ese panel"
    if w["tipo"] in IMPRESCINDIBLES:
        return False, f"«{_nombre(w)}» es de lo básico: ocúltalo desde Diseño si de verdad quieres"
    ok, _ = layout.ocultar(lay, w["id"])
    perfiles.marcar_sucio()
    return ok, f"guardé «{_nombre(w)}» en el cajón"


def ext_al_cajon():
    lay = perfiles.layout_actual()
    n = 0
    for w in lay["widgets"]:
        if w["tipo"].startswith("ext:") and w["visible"] and not w.get("ventana") and not layout.en_contenedor(w):
            layout.ocultar(lay, w["id"])
            n += 1
    perfiles.marcar_sucio()
    return n


def dibujar_cajon(v, W, H, esc):
    """Capa del cajon: lista de lo disponible a la derecha y, si abres uno, el panel temporal en el centro."""
    c = v.canvas
    c.create_rectangle(0, 0, W, H, fill=tema.mezclar(tema.FONDO, "#000000", 0.55), outline="", stipple="gray50", tags=v._tag)
    v.zonas.append((0, 0, W, H, ("ord", "cajon_cerrar")))
    cw = min(W * 0.34, 340 * esc)
    x0, y0, x1, y1 = W - cw - 12 * esc, 12 * esc, W - 12 * esc, H - 12 * esc
    v._redondo(x0, y0, x1, y1, 14 * esc, fill=tema.PANEL, outline=tema.MORADO_CLARO)
    v.zonas.append((x0, y0, x1, y1, ("ord", "nada")))
    v._texto(x0 + 18 * esc, y0 + 22 * esc, "CAJÓN", 11, tema.MORADO_CLARO, negrita=True)
    v._texto(x0 + 18 * esc, y0 + 42 * esc, "Toca uno para verlo un momento. «Fijar» lo deja en pantalla.", 8, tema.TENUE, ancho=cw - 36 * esc)
    v._chip(x1 - 74 * esc, y0 + 12 * esc, "cerrar", ("ord", "cajon_cerrar"), False, tema.ROJO_CLARO, 62 * esc)
    items = tipos_del_cajon()
    ys = y0 + 78 * esc
    area = (y1 - 12 * esc) - ys
    paso = 46 * esc
    tot = len(items) * paso
    sc = min(v.scroll.get("cajon", 0), max(0, tot - area))
    v.scroll["cajon"] = sc
    v._scroll_reg["cajon"] = (x0, ys, x1, y1)
    if not items:
        v._texto(x0 + 18 * esc, ys + 10 * esc, "Todo lo que existe ya está en esta página.", 9, tema.TENUE)
    ult = None
    for k, (tipo, nombre, det, es_ext) in enumerate(items):
        yy = ys + k * paso - sc
        if yy < ys - 2 or yy + paso > y1 - 8 * esc:
            continue
        sel = estado["cajon_tipo"] == tipo
        acc = ("ord", "cajon_abrir", tipo)
        pasa = v.hover == acc
        v._redondo(x0 + 10 * esc, yy, x1 - 10 * esc, yy + paso - 6 * esc, 9 * esc,
                   fill=tema.mezclar(tema.BOTON, tema.MORADO_CLARO, 0.6 if sel else (0.25 if pasa else 0.0)), outline=tema.MORADO_CLARO if sel else tema.BORDE)
        v._texto(x0 + 22 * esc, yy + 12 * esc, nombre[:int((cw - 70 * esc) / (7 * esc))], 10, tema.TEXTO, negrita=True)
        v._texto(x0 + 22 * esc, yy + 28 * esc, ("extensión · " if es_ext else "") + det[:int((cw - 70 * esc) / (5.6 * esc))], 8, tema.TENUE)
        v.zonas.append((x0 + 10 * esc, yy, x1 - 10 * esc, yy + paso - 6 * esc, acc))
    tipo = estado["cajon_tipo"]
    if tipo and layout.info(tipo):
        px0, py0 = 24 * esc, 24 * esc
        px1, py1 = x0 - 16 * esc, H - 24 * esc
        pw, ph = min(px1 - px0, 560 * esc), min(py1 - py0, 460 * esc)
        px0 = px0 + (px1 - px0 - pw) / 2
        py0 = py0 + (py1 - py0 - ph) / 2
        v.zonas.append((px0 - 6, py0 - 6, px0 + pw + 6, py0 + ph + 38 * esc, ("ord", "nada")))
        wd = layout.nuevo_widget(tipo, id="_cajon")
        v._pintar_widget(wd, px0, py0, pw, ph)
        yb = py0 + ph + 8 * esc
        v._chip(px0, yb, "Fijar en pantalla", ("ord", "cajon_fijar", tipo), True, tema.MORADO_CLARO, 130 * esc)
        v._chip(px0 + 138 * esc, yb, "Cerrar este", ("ord", "cajon_abrir", tipo), False, tema.TENUE, 96 * esc)


# ------------------------------------------------------------------ barra de paginas
def dibujar_paginas(v, W, m, esc):
    lay = perfiles.layout_actual()
    ps = layout.paginas_de(lay)
    modo = ajustes.obtener("orden_barra_paginas")
    if modo == "nunca" or (modo == "auto" and len(ps) < 2):
        return
    pag = pagina_actual(lay)
    x = m + 190 * esc
    y = m + 14 * esc
    limite = W - m - 330 * esc
    for k, p in enumerate(ps):
        ancho = (len(p) * 6.8 + 22) * esc
        if x + ancho > limite:
            break
        x = v._chip(x, y, p, ("ord", "pagina", p), p == pag, tema.AZUL_CLARO, ancho) + 5 * esc


# ------------------------------------------------------------------ acciones (clics)
_CAMBIAN = ("plegar", "al_cajon", "miembro", "contenedor_nuevo", "pagina_borrar", "opt", "cajon_fijar")


def accion(v, a):
    sub = a[1] if len(a) > 1 else ""
    lay = perfiles.layout_actual()
    if sub in _CAMBIAN:
        try:
            from . import estado_visual as ev
            ev.punto_de_control("orden de la pantalla")
        except Exception:
            pass
    if sub == "opt":                                 # ("ord", "opt", id, clave, valor)
        w = layout.buscar(lay, a[2])
        if w is None:
            return True
        if a[3] == "condicion":
            w["opts"]["condicion"] = a[4]
            ok, msg = True, ""
        else:
            ok, msg = layout.opcion(lay, a[2], a[3], a[4])
        perfiles.marcar_sucio()
        if not ok and msg:
            v.avisar(msg[:1].upper() + msg[1:], "info")
        return True
    if sub == "pagina":
        ir_a_pagina(a[2])
    elif sub == "pagina_sig":
        pagina_vecina(1)
    elif sub == "pagina_ant":
        pagina_vecina(-1)
    elif sub == "plegar":
        w = layout.buscar(lay, a[2])
        if w:
            w["opts"]["plegado"] = True
            estado["abiertos"].pop(w["id"], None)
            perfiles.marcar_sucio()
    elif sub == "abrir":
        w = layout.buscar(lay, a[2])
        if w:
            if int(ajustes.obtener("orden_plegar_auto")) == 0:
                w["opts"]["plegado"] = False
                perfiles.marcar_sucio()
            else:
                estado["abiertos"][w["id"]] = time.time()
    elif sub == "pestana":
        estado["sel"][a[2]] = int(a[3])
        estado["pausa"][a[2]] = time.time() + 25
    elif sub == "cajon":
        abrir_cajon(not estado["cajon"])
    elif sub == "cajon_cerrar":
        abrir_cajon(False)
    elif sub == "cajon_ver":                         # desde el buscador: abre el cajon con ese panel
        estado["cajon"], estado["cajon_tipo"] = True, a[2]
    elif sub == "cajon_abrir":
        estado["cajon_tipo"] = None if estado["cajon_tipo"] == a[2] else a[2]
    elif sub == "cajon_fijar":
        ok, msg = fijar_desde_cajon(a[2])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "info")
        if ok:
            abrir_cajon(False)
    elif sub == "al_cajon":
        ok, msg = mandar_al_cajon(a[2])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "info")
    elif sub == "miembro":                          # ("ord","miembro", contenedor, widget): entra o sale
        ok, msg = alternar_miembro(lay, a[2], a[3])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "info")
    elif sub == "contenedor_nuevo":
        ok, msg = crear_contenedor(lay, a[2], [])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "info")
    elif sub == "pagina_borrar":
        ok, msg = borrar_pagina(a[2])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "info")
    elif sub == "regla_borrar":
        d = list(ajustes.obtener("orden_horarios"))
        if 0 <= a[2] < len(d):
            d.pop(a[2])
            ajustes.fijar("orden_horarios", d)
    elif sub == "frase_borrar":
        d = dict(ajustes.obtener("orden_frases"))
        d.pop(a[2], None)
        ajustes.fijar("orden_frases", d)
    return True


# ------------------------------------------------------------------ contenedores: crear, agrupar
def _id_libre(lay, base):
    k, wid = 2, base
    while any(o["id"] == wid for o in lay["widgets"]):
        wid = f"{base}-{k}"
        k += 1
    return wid


def crear_contenedor(lay, tipo, miembros):
    """Tarjeta con pestañas o carrusel con esos widgets (objetos del layout). Ocupa el sitio del primero."""
    if tipo not in layout.CONTENEDORES:
        return False, "solo hay tarjeta con pestañas y carrusel"
    ms = [m for m in miembros if m["tipo"] not in layout.CONTENEDORES and not layout.en_contenedor(m)][:8]
    if miembros and len(ms) < 1:
        return False, "esos paneles ya están dentro de otra tarjeta"
    wid = _id_libre(lay, tipo)
    if ms:
        p = ms[0]
        c = layout.nuevo_widget(tipo, id=wid, x=p["x"], y=p["y"])
        c["w"], c["h"] = max(p["w"], layout.info(tipo)[4]), max(p["h"], layout.info(tipo)[5])
        c["x"] = min(c["x"], layout.COLS - c["w"])
        c["y"] = min(c["y"], layout.FILAS - c["h"])
        if (p.get("opts") or {}).get("pagina"):
            c["opts"]["pagina"] = p["opts"]["pagina"]
        c["visible"] = True
        c["opts"]["miembros"] = [m["id"] for m in ms]
        for m in ms:
            m["opts"]["en"] = wid
            m["opts"].pop("plegado", None)
        lay["widgets"].append(c)
        _reparar(lay)
        perfiles.marcar_sucio()
        return True, f"armé la {'tarjeta con pestañas' if tipo == 'pestanas' else 'carrusel'} con " + ", ".join(_nombre(m) for m in ms)
    ok, msg = layout.anadir(lay, tipo)
    perfiles.marcar_sucio()
    return ok, ("agregué una " + ("tarjeta con pestañas" if tipo == "pestanas" else "carrusel") + " vacía; elige qué lleva en PERSONALIZA > Orden") if ok else msg


def alternar_miembro(lay, cid, wid):
    c = layout.buscar(lay, cid)
    w = layout.buscar(lay, wid)
    if c is None or w is None or c["tipo"] not in layout.CONTENEDORES or w["tipo"] in layout.CONTENEDORES or w["id"] == c["id"]:
        return False, "no se puede"
    ms = list(c["opts"].get("miembros", []))
    if wid in ms:
        ms.remove(wid)
        w["opts"].pop("en", None)
        c["opts"]["miembros"] = ms
        w["visible"] = True
        _reparar(lay)
        perfiles.marcar_sucio()
        return True, f"saqué «{_nombre(w)}» de la tarjeta"
    if layout.en_contenedor(w):
        return False, f"«{_nombre(w)}» ya está en otra tarjeta"
    if len(ms) >= 8:
        return False, "máximo 8 paneles por tarjeta"
    ms.append(wid)
    c["opts"]["miembros"] = ms
    w["opts"]["en"] = cid
    w["visible"] = True
    _reparar(lay)
    perfiles.marcar_sucio()
    return True, f"metí «{_nombre(w)}» en la tarjeta"


def separar_contenedor(lay, c):
    for m in _miembros(lay, c):
        m["opts"].pop("en", None)
    lay["widgets"].remove(c)
    _reparar(lay)
    perfiles.marcar_sucio()


# ------------------------------------------------------------------ tope de paneles
def _en_pantalla(lay, pag):
    """Los paneles que cuentan para el tope: sin lo basico (esfera, chat, mascota, panel) ni los que aparecen solos."""
    return [w for w in lay["widgets"] if w["visible"] and not w.get("ventana") and not layout.en_contenedor(w)
            and layout.pagina_de(w, lay) in ("*", pag) and w["tipo"] not in IMPRESCINDIBLES
            and (w.get("opts") or {}).get("aparece") != "si_hay"]


def candidatos_a_ocultar(lay, pag, cuantos):
    ws = [w for w in _en_pantalla(lay, pag) if w["tipo"] not in IMPRESCINDIBLES]
    ws.sort(key=lambda w: (uso_de(w["tipo"]), -w["w"] * w["h"]))
    return ws[:cuantos]


def revisar_tope(v=None, forzar=False):
    """Si hay mas paneles que el tope, propone (con confirmacion) ocultar los que menos usas. Devuelve el texto o None."""
    from . import lenguaje
    A = ajustes.obtener
    tope = int(A("orden_tope"))
    if tope <= 0 or not A("orden_activo"):
        return None
    if not forzar and not A("orden_proponer"):
        return None
    lay = perfiles.layout_actual()
    pag = pagina_actual(lay)
    ws = _en_pantalla(lay, pag)
    if len(ws) <= tope:
        return "Estás dentro del tope: " + f"{len(ws)} paneles en «{pag}» (máximo {tope})." if forzar else None
    sobran = len(ws) - tope
    cand = candidatos_a_ocultar(lay, pag, sobran)
    if not cand:
        return None
    firma = pag + "|" + ",".join(sorted(w["id"] for w in cand))
    ahora = time.time()
    if not forzar and ahora - estado["propuestas"].get(firma, 0) < 900:
        return None
    if lenguaje.hay_pendiente() and not forzar:
        return None
    estado["propuestas"][firma] = ahora
    ids = [w["id"] for w in cand]
    res = [f"ocultar «{_nombre(w)}» ({uso_de(w['tipo'])} clic(s))" for w in cand]

    def aplicar():
        l2 = perfiles.layout_actual()
        for i in ids:
            layout.ocultar(l2, i)
        perfiles.marcar_sucio()
        return "Listo: guardé en el cajón " + ", ".join(_nombre(w) for w in cand) + ". Di «deshacer» para volver."

    msg = (f"Tienes {len(ws)} paneles en «{pag}» (sin contar esfera, chat, mascota y panel) y el tope es {tope}. Por tus clics, los que menos usas son: "
           + ", ".join(_nombre(w) for w in cand) + ". ")
    return msg + lenguaje._pide_confirmacion("tope de paneles", res, aplicar)


# ------------------------------------------------------------------ ordenar toda la pantalla
_PLANTILLA = (
    ("Inicio", [("progreso", 0, 0, 18, 2), ("notificaciones", 0, 2, 18, 3), ("voz", 0, 5, 18, 5), ("mascota", 0, 10, 18, 2), ("chat", 0, 12, 18, 4)]),
    ("Arché", [("redes", 0, 0, 9, 8), ("estado_asistente", 9, 0, 9, 3), ("modelo", 9, 3, 9, 3), ("procesos", 0, 8, 9, 8),
               ("pestanas:Actividad", 9, 6, 9, 5), ("mejora", 9, 11, 9, 5)]),
    ("Mi día", [("reloj", 0, 0, 9, 3), ("calendario", 0, 3, 9, 7), ("notas", 9, 0, 9, 6), ("recordatorios", 9, 6, 9, 4),
                ("pestanas:Mi día", 0, 10, 18, 6)]),
    ("Equipo", [("sistema", 0, 0, 6, 16), ("carrusel", 6, 0, 12, 16)]),
)
_GRUPOS = {"pestanas:Actividad": ["actividad", "historial", "estadisticas", "registro"],
           "pestanas:Mi día": ["ext:Pendientes", "ext:Pomodoro", "ext:Gastos del día", "atajos"],
           "carrusel": ["graficas", "red", "dispositivos"]}


def construir_orden(lay_actual):
    """(layout nuevo, [resumen]) con paginas, paneles que aparecen solos, tarjetas y el resto en el cajon."""
    disponibles = {w["tipo"]: w for w in lay_actual["widgets"]}
    ext_inst = [t for t in layout.tipos() if t.startswith("ext:")]
    lista, usados = [], set()
    paginas = []
    for pag, cols in _PLANTILLA:
        paginas.append(pag)
        for nombre, x, y, w, h in cols:
            base = nombre.split(":")[0]
            if base in layout.CONTENEDORES:
                miem = [t for t in _GRUPOS[nombre] if layout.info(t)]
                if not miem:
                    continue
                usados.update(miem)
                lista.append((base, pag, x, y, w, h, miem))
            elif layout.info(base):
                usados.add(base)
                lista.append((base, pag, x, y, w, h, None))
    ws = []
    for tipo, pag, x, y, w, h, miem in lista:
        wd = layout.nuevo_widget(tipo, x=x, y=y)
        wd["w"], wd["h"] = w, h
        if pag != "Inicio":
            wd["opts"]["pagina"] = pag
        if tipo in TIPO_COND:
            wd["opts"]["aparece"] = "si_hay"
        if tipo == "modelo":
            wd["opts"]["plegado"] = True
        prev = disponibles.get(tipo)
        if prev:
            wd["color"], wd["opacidad"], wd["nivel"] = prev.get("color", ""), prev.get("opacidad", 100), prev.get("nivel", "normal")
        if miem:
            wd["id"] = _id_libre({"widgets": ws}, tipo)
            wd["opts"]["miembros"] = []
            for t in miem:
                m = layout.nuevo_widget(t, id=_id_libre({"widgets": ws + [wd]}, t.replace("ext:", "ext-")))
                m["opts"]["en"] = wd["id"]
                wd["opts"]["miembros"].append(m["id"])
                if pag != "Inicio":
                    m["opts"]["pagina"] = pag
                if t.startswith("ext:"):
                    m["opts"]["aparece"] = "siempre"
                ws.append(m)
        ws.append(wd)
    panel = layout.nuevo_widget("panel", x=18, y=0)
    panel["opts"]["pagina"] = "*"
    ws.append(panel)
    # lo demas (extensiones y paneles que quedaron fuera) va al cajon: existe pero no ocupa pantalla
    restantes = [t for t in layout.tipos() if t not in usados and t not in ("panel",) + layout.CONTENEDORES]
    for t in restantes:
        w = layout.nuevo_widget(t, id=_id_libre({"widgets": ws}, t.replace("ext:", "ext-")), visible=False)
        if t.startswith("ext:") and layout.info(t) and t in ext_inst and condicion_de(w):
            w["opts"]["aparece"] = "si_hay"
        ws.append(w)
    nuevo = layout.armar([], paginas=paginas, margen=lay_actual.get("margen", 22), separacion=lay_actual.get("separacion", 14),
                         cabecera=lay_actual.get("cabecera", True), pie=lay_actual.get("pie", True))
    nuevo["widgets"] = ws
    nuevo = layout.validar(nuevo)
    n_auto = sum(1 for w in nuevo["widgets"] if (w["opts"].get("aparece") == "si_hay") and w["visible"])
    n_ext = sum(1 for w in nuevo["widgets"] if w["tipo"].startswith("ext:") and not w["visible"] and not layout.en_contenedor(w))
    n_card = sum(1 for w in nuevo["widgets"] if w["tipo"] in layout.CONTENEDORES)
    res = ["4 páginas: " + ", ".join(paginas) + " (el panel de la derecha está en todas)",
           f"{n_auto} panel(es) que aparecen solos cuando hay algo",
           f"{n_card} tarjeta(s) con pestañas o carrusel", "el panel «Modelo de IA» plegado"]
    if n_ext:
        res.append(f"{n_ext} extensión(es) al cajón (Ctrl+J o el botón Cajón)")
    return nuevo, res


def proponer_orden():
    from . import lenguaje
    nuevo, res = construir_orden(perfiles.layout_actual())

    def aplicar():
        perfiles.poner_layout(nuevo)
        estado["pagina"] = layout.paginas_de(nuevo)[0]
        layout.PAGINA_ACTUAL = estado["pagina"]
        estado["abiertos"].clear()
        return "Pantalla ordenada. Cambia de página con los botones de arriba. Di «deshacer» para volver a como estaba."
    return "Te propongo ordenar tu pantalla así. " + lenguaje._pide_confirmacion("ordenar la pantalla", res, aplicar)


# ------------------------------------------------------------------ modos por hora y por frase
def _min(txt):
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?$", txt.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    return h * 60 + mi if h < 24 and mi < 60 else None


def parsear_regla(txt):
    """'09:00-18:00=trabajo' -> (ini, fin, perfil) o None."""
    m = re.match(r"^\s*([\d:]+)\s*-\s*([\d:]+)\s*=\s*(.+?)\s*$", str(txt))
    if not m:
        return None
    a, b = _min(m.group(1)), _min(m.group(2))
    return (a, b, m.group(3)) if a is not None and b is not None and a != b else None


def regla_activa(ahora=None):
    t = time.localtime(ahora)
    cur = t.tm_hour * 60 + t.tm_min
    for txt in ajustes.obtener("orden_horarios"):
        r = parsear_regla(txt)
        if not r:
            continue
        a, b, p = r
        dentro = (a <= cur < b) if a < b else (cur >= a or cur < b)
        if dentro:
            return txt, p
    return None


def tick_modos(v):
    """Cada ~20 s: si entraste en un horario de modo, activa ese perfil; al salir, vuelve al que tenias."""
    if not ajustes.obtener("orden_modos_auto") or not ajustes.obtener("orden_activo"):
        return
    ahora = time.time()
    if ahora - estado["t_modos"] < 20:
        return
    estado["t_modos"] = ahora
    r = regla_activa()
    if r and r[0] != estado["regla"]:
        real = perfiles.resolver(r[1])
        estado["regla"] = r[0]
        if real and real != perfiles.activo():
            estado["previo"] = perfiles.activo()
            ok, msg = perfiles.activar(real)
            v.avisar(f"Modo «{real}» por horario ({r[0].split('=')[0]})", "info")
    elif not r and estado["regla"]:
        estado["regla"] = None
        previo, estado["previo"] = estado["previo"], None
        if previo and previo != perfiles.activo() and perfiles.resolver(previo):
            perfiles.activar(previo)
            v.avisar(f"Terminó el horario: vuelvo al perfil «{previo}»", "info")


def al_recibir_orden(texto, origen=None):
    """Oyente de TODA orden (no la reclama): si es una frase de modo («modo trabajo»), cambia de perfil."""
    if not ajustes.obtener("orden_modos_auto") or not ajustes.obtener("orden_activo"):
        return
    t = layout._limpio(texto)
    for frase, perfil in (ajustes.obtener("orden_frases") or {}).items():
        if t == layout._limpio(frase):
            real = perfiles.resolver(perfil)
            if real and real != perfiles.activo():
                perfiles.activar(real)
            return


_instalado = False


def instalar():
    """Engancha el oyente de ordenes (una sola vez) para los modos por frase."""
    global _instalado
    if _instalado:
        return
    _instalado = True
    try:
        from . import entrada
        entrada.al_recibir(al_recibir_orden)
    except Exception:
        pass


def tick(v):
    """Lo periodico de la ventana: modos por hora y tope de paneles."""
    try:
        tick_modos(v)
        ahora = time.time()
        if ahora - estado["t_tope"] > 6 and not v.editando:
            estado["t_tope"] = ahora
            msg = revisar_tope(v)
            if msg:
                v.avisar("Propongo ordenar un poco: mira el chat", "info")
                en_vivo.chat.append({"q": "arche", "t": msg, "ts": time.time()})
                print(f"Arché: {msg}")
    except Exception as e:
        if "invalid command" in str(e):
            raise
        v._una_vez("orden", e)


# ------------------------------------------------------------------ frases
def _nombres(texto):
    t = re.sub(r"\s+(?:y|e)\s+", ",", texto)
    return [p.strip() for p in t.split(",") if p.strip()]


def _widgets_por_nombres(lay, texto):
    ws, falta = [], []
    for n in _nombres(texto):
        n2 = re.sub(r"^(el|la|los|las|mi|mis)\s+", "", layout._limpio(n))
        w = layout.encontrar_por_nombre(lay, n2)
        (ws if w else falta).append(w or n)
    return ws, falta


def _hora(txt, sufijo=None):
    t = txt.replace(".", "").strip()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|de la manana|de la tarde|de la noche)?$", t)
    if not m:
        return None
    h, mi, suf = int(m.group(1)), int(m.group(2) or 0), m.group(3) or sufijo
    if suf in ("pm", "de la tarde", "de la noche") and h < 12:
        h += 12
    if suf in ("am", "de la manana") and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def responder(t, original=""):
    """Frases de orden. t ya viene sin tildes ni mayusculas. Devuelve texto o None."""
    from . import lenguaje
    lay = perfiles.layout_actual()
    m = re.match(r"^(?:por favor )?(?:ordena|organiza|acomoda|arregla|limpia)(?: mi| la| toda la| todo)?(?: pantalla| interfaz| ventana| todo)?(?: ahora)?$", t)
    if m and any(p in t for p in ("pantalla", "interfaz", "ventana", "todo")):
        return proponer_orden()
    if re.match(r"^(?:revisa|chequea|mira)(?: el)? (?:tope|limite)(?: de paneles)?$", t):
        return revisar_tope(None, forzar=True) or "No hay tope puesto: con «tope de 6 paneles» lo activo."
    # ---- paginas
    if re.match(r"^(?:pagina|pasa a la pagina|ve a la pagina|ve a la) siguiente$|^pagina siguiente$", t):
        return f"Ahora estás en «{pagina_vecina(1)}»."
    if re.match(r"^(?:pagina|pasa a la pagina|ve a la pagina|ve a la) anterior$|^pagina anterior$", t):
        return f"Ahora estás en «{pagina_vecina(-1)}»."
    m = re.match(r"^(?:ve|ir|vamos|pasa|cambia|abre|muestra|llevame|quiero ver)(?: a| al| a la| la)? pagina (?:de |llamada )?(.+)$", t)
    if m:
        ok, p = ir_a_pagina(m.group(1))
        return f"Estás en «{p}»." if ok else "No tengo esa página. Las que hay: " + ", ".join(layout.paginas_de(lay)) + "."
    m = re.match(r"^(?:crea|agrega|anade|haz|nueva)(?: una| otra| una nueva)? pagina(?: llamada| que se llame| de| para)? (.+)$", t)
    if m:
        nombre = re.sub(r"\s+", " ", original.strip()).split(" ", 1)[-1] if False else m.group(1)
        mo = re.search(r"pagina(?: llamada| que se llame| de| para)? (.+)$", original.strip(), re.I)
        ok, msg = crear_pagina((mo.group(1) if mo else nombre).strip(" .!?"))
        return msg[:1].upper() + msg[1:] + "."
    m = re.match(r"^(?:borra|elimina|quita)(?: la)? pagina (.+)$", t)
    if m:
        ok, msg = borrar_pagina(m.group(1))
        return msg[:1].upper() + msg[1:] + "."
    m = re.match(r"^renombra(?: la)? pagina (.+?) (?:a|como) (.+)$", t)
    if m:
        mo = re.search(r"(?:a|como) (.+)$", original.strip(), re.I)
        ok, msg = renombrar_pagina(m.group(1), (mo.group(1) if mo else m.group(2)).strip(" .!?"))
        return msg[:1].upper() + msg[1:] + "."
    m = re.match(r"^(?:pon|mueve|pasa|lleva|manda|deja)(?: el| la| los| las)? (.+?) (?:en|a)(?: la)? pagina (.+)$", t)
    if m:
        w = layout.encontrar_por_nombre(lay, re.sub(r"^(el|la|los|las|mi|mis)\s+", "", m.group(1)))
        if w is None:
            return f"No encuentro «{m.group(1)}» en tu pantalla."
        ps = layout.paginas_de(lay)
        real = next((p for p in ps if layout._limpio(p) == m.group(2).strip()), None)
        if real is None:
            return "No tengo esa página. Las que hay: " + ", ".join(ps) + "."
        ok, msg = layout.opcion(lay, w["id"], "pagina", real)
        perfiles.marcar_sucio()
        return (f"Pasé «{_nombre(w)}» a la página «{real}»." if ok else msg[:1].upper() + msg[1:] + ".")
    m = re.match(r"^(?:pon|deja|muestra)(?: el| la| los| las)? (.+?) en todas las paginas$", t)
    if m:
        w = layout.encontrar_por_nombre(lay, re.sub(r"^(el|la|los|las|mi|mis)\s+", "", m.group(1)))
        if w is None:
            return f"No encuentro «{m.group(1)}» en tu pantalla."
        ok, msg = layout.opcion(lay, w["id"], "pagina", "*")
        perfiles.marcar_sucio()
        return f"«{_nombre(w)}» se ve en todas las páginas." if ok else msg[:1].upper() + msg[1:] + "."
    # ---- aparecer solo si hay algo
    m = re.match(r"^(?:muestra|pon|deja|haz que aparezca)?\s*(?:el |la |los |las )?(.+?)\s+(?:solo|solamente|unicamente)\s+(?:si|cuando)\s+(?:haya|hay|haga falta|sea necesario|tenga algo|tenga cosas|pase algo)(?: algo| pendientes| cosas)?$", t) or \
        re.match(r"^(?:que |haz que )?(?:el |la |los |las )?(.+?)\s+(?:aparezca|aparece|salga|sale|se muestre|se muestra)\s+(?:solo|solamente|unicamente)\s+(?:si|cuando)\s+.+$", t)
    if m:
        w = layout.encontrar_por_nombre(lay, re.sub(r"^(el|la|los|las|mi|mis)\s+", "", m.group(1)))
        if w is None:
            return f"No encuentro «{m.group(1)}» en tu pantalla."
        if condicion_de(w) is None:
            return (f"«{_nombre(w)}» no sabe cuándo «hay algo» (no tiene una condición). "
                    "En PERSONALIZA > Widgets > Opciones de este panel eliges una: avisos, alarmas, tareas en curso, ejemplos sin entrenar, etc.")
        layout.opcion(lay, w["id"], "aparece", "si_hay")
        perfiles.marcar_sucio()
        return f"Listo: «{_nombre(w)}» aparece solo cuando {CONDICIONES[condicion_de(w)][1]}."
    m = re.match(r"^(?:muestra|deja|pon)(?: el| la| los| las)? (.+?) siempre(?: visible)?$|^(?:el |la |los |las )?(.+?) siempre visible$", t)
    if m:
        nom = m.group(1) or m.group(2)
        w = layout.encontrar_por_nombre(lay, re.sub(r"^(el|la|los|las|mi|mis)\s+", "", nom))
        if w is not None:
            layout.opcion(lay, w["id"], "aparece", "siempre")
            perfiles.marcar_sucio()
            return f"«{_nombre(w)}» se ve siempre."
    # ---- plegar
    m = re.match(r"^(pliega|colapsa|encoge|recoge|despliega|expande|desplega)(?: el| la| los| las)? (.+)$", t)
    if m:
        plegar = m.group(1) in ("pliega", "colapsa", "encoge", "recoge")
        if m.group(2) in ("todo", "todos", "todo lo plegable", "los paneles", "todos los paneles"):
            n = 0
            for w in layout.__dict__["_visibles"](lay):
                if w["tipo"] not in IMPRESCINDIBLES:
                    w["opts"]["plegado"] = plegar
                    n += 1
            perfiles.marcar_sucio()
            estado["abiertos"].clear()
            return f"{'Plegué' if plegar else 'Desplegué'} {n} panel(es)."
        w = layout.encontrar_por_nombre(lay, m.group(2))
        if w is not None:
            w["opts"]["plegado"] = plegar
            estado["abiertos"].pop(w["id"], None)
            perfiles.marcar_sucio()
            return f"«{_nombre(w)}» {'plegado: toca su barra para abrirlo' if plegar else 'desplegado'}."
    # ---- tarjetas y carrusel
    m = re.match(r"^(?:agrupa|junta|une|mete|combina|pon)(?: el| la| los| las)? (.+?) en (?:una |un )?(tarjeta con pestanas|tarjeta de pestanas|pestanas|tarjeta|carrusel|rotativo)$", t)
    if m:
        ws, falta = _widgets_por_nombres(lay, m.group(1))
        if falta:
            return "No encuentro: " + ", ".join(f"«{f}»" for f in falta) + ". Dime nombres como aparecen en Widgets."
        if len(ws) < 2:
            return "Dame al menos dos paneles para agrupar, por ejemplo: «agrupa el reloj y las notas en pestañas»."
        tipo = "carrusel" if m.group(2) in ("carrusel", "rotativo") else "pestanas"
        ok, msg = crear_contenedor(lay, tipo, ws)
        return msg[:1].upper() + msg[1:] + ("." if ok else ".")
    m = re.match(r"^(?:crea|agrega|anade|pon)(?: una| un)? (tarjeta con pestanas|tarjeta de pestanas|carrusel)$", t)
    if m:
        ok, msg = crear_contenedor(lay, "carrusel" if m.group(1) == "carrusel" else "pestanas", [])
        return msg[:1].upper() + msg[1:] + "."
    m = re.match(r"^(?:separa|desagrupa|deshaz|rompe|quita)(?: la| el)? (tarjeta con pestanas|tarjeta de pestanas|tarjeta|carrusel|pestanas)$", t)
    if m:
        cs = [w for w in lay["widgets"] if w["tipo"] in layout.CONTENEDORES]
        if not cs:
            return "No tienes ninguna tarjeta con pestañas ni carrusel."
        separar_contenedor(lay, cs[0])
        return "Separé la tarjeta: sus paneles volvieron a la pantalla (si no cabían, quedaron en el cajón)."
    # ---- cajon
    if re.match(r"^(?:abre|muestra|ensename|ver)(?: el)? cajon(?: de paneles| de extensiones)?$", t):
        abrir_cajon(True)
        return "Abrí el cajón (Esc lo cierra). Toca un panel para verlo y «Fijar» para dejarlo en pantalla."
    if re.match(r"^(?:cierra|esconde)(?: el)? cajon$", t):
        abrir_cajon(False)
        return "Cerré el cajón."
    m = re.match(r"^(?:abre|muestra|ensename)(?: el| la)? (?:panel de |widget de |extension )?(.+?) en el cajon$", t)
    if m:
        tipo = layout.tipo_por_nombre(re.sub(r"^(el|la|los|las|mi|mis)\s+", "", m.group(1)))
        if tipo is None:
            return f"No conozco un panel llamado «{m.group(1)}»."
        estado["cajon"], estado["cajon_tipo"] = True, tipo
        return f"Abrí «{layout.nombre_de(tipo)}» en el cajón."
    if re.match(r"^(?:manda|mueve|pasa|guarda|lleva|deja) (?:mis |todas mis |las |todas las )?extensiones (?:al|en el|a el) cajon$", t):
        n = ext_al_cajon()
        return f"Guardé {n} extensión(es) en el cajón; las abres con «abre el cajón»." if n else "No tenías extensiones en pantalla."
    m = re.match(r"^(?:guarda|manda|mete|pon|mueve|lleva)(?: el| la| los| las)? (.+?) (?:en|al) (?:el )?cajon$", t)
    if m:
        w = layout.encontrar_por_nombre(lay, re.sub(r"^(el|la|los|las|mi|mis)\s+", "", m.group(1)))
        if w is None:
            return f"No encuentro «{m.group(1)}» en tu pantalla."
        ok, msg = mandar_al_cajon(w["id"])
        return msg[:1].upper() + msg[1:] + "."
    m = re.match(r"^(?:fija|deja fijo|deja fija|pon en pantalla)(?: el| la| los| las)? (.+)$", t)
    if m:
        tipo = layout.tipo_por_nombre(re.sub(r"^(el|la|los|las|mi|mis)\s+", "", m.group(1)))
        if tipo:
            ok, msg = fijar_desde_cajon(tipo)
            return msg[:1].upper() + msg[1:] + "."
    if t in ("olvida el conteo de clics", "borra el conteo de clics", "reinicia el conteo de clics"):
        ajustes.fijar("orden_uso", {})
        return "Borré el conteo de clics."
    # ---- tope
    m = re.match(r"^(?:pon |ponme |quiero )?(?:un )?(?:tope|limite|maximo)(?: de| a)? (\d{1,2})(?: paneles| widgets| cosas)?$|^(?:no )?(?:mas de|maximo) (\d{1,2}) paneles$", t)
    if m:
        n = int(m.group(1) or m.group(2))
        ajustes.fijar("orden_tope", n)
        extra = revisar_tope(None, forzar=True)
        return f"Tope de {n} paneles por página." + (" " + extra if extra and "dentro del tope" not in extra else "")
    if t in ("sin tope", "quita el tope", "sin limite de paneles", "quita el limite de paneles"):
        ajustes.fijar("orden_tope", 0)
        return "Sin tope de paneles."
    # ---- modos por hora y por frase
    m = re.match(r"^(?:de|desde)(?: las)? (.+?) (?:a|hasta)(?: las)? (.+?),? (?:usa|pon|activa|cambia a)(?: el)?(?: modo| perfil) (.+)$", t)
    if m:
        suf = "pm" if re.search(r"(pm|tarde|noche)", m.group(2)) and not re.search(r"(am|manana)", m.group(1)) else None
        a, b = _hora(m.group(1), suf if suf == "pm" and "noche" in m.group(2) else None), _hora(m.group(2))
        real = perfiles.resolver(m.group(3).strip())
        if a is None or b is None:
            return "No entendí la hora. Di por ejemplo: «de 9:00 a 18:00 usa el modo trabajo»."
        if real is None:
            return f"No tengo un perfil «{m.group(3)}». Los que hay: " + ", ".join(n for n, _, _ in perfiles.listar()) + "."
        reglas = [r for r in ajustes.obtener("orden_horarios") if not (parsear_regla(r) and parsear_regla(r)[2] == real)]
        reglas.append(f"{a}-{b}={real}")
        ajustes.fijar("orden_horarios", reglas[:12])
        estado["regla"] = None
        return f"De {a} a {b} uso el perfil «{real}» (y al terminar vuelvo al que tengas)."
    if re.match(r"^(?:quita|borra|elimina) (?:todas )?(?:las )?reglas de horario$|^sin horarios$", t):
        ajustes.fijar("orden_horarios", [])
        return "Quité los horarios de modos."
    m = re.match(r"^cuando (?:diga|escriba|yo diga) (.+?),? (?:usa|pon|activa|cambia a)(?: el)?(?: modo| perfil) (.+)$", t)
    if m:
        real = perfiles.resolver(m.group(2).strip())
        if real is None:
            return f"No tengo un perfil «{m.group(2)}». Los que hay: " + ", ".join(n for n, _, _ in perfiles.listar()) + "."
        d = dict(ajustes.obtener("orden_frases"))
        d[m.group(1).strip().strip("«»\"'")] = real
        ajustes.fijar("orden_frases", d)
        return f"Cuando digas «{m.group(1).strip()}» paso al perfil «{real}»."
    m = re.match(r"^(?:olvida|borra|quita) la frase (.+)$", t)
    if m:
        d = dict(ajustes.obtener("orden_frases"))
        k = next((k for k in d if layout._limpio(k) == m.group(1).strip().strip("«»\"'")), None)
        if k:
            d.pop(k)
            ajustes.fijar("orden_frases", d)
            return f"Olvidé la frase «{k}»."
    return None
