"""
widgets.py
----------
Ubicacion: Arche/core/interfaz/widgets.py

La biblioteca de widgets: cada widget es una funcion que dibuja SU tarjeta
dentro del rectangulo que le toca en la distribucion. Reciben la ventana (v)
para usar sus utilidades de dibujo, el widget (wd, con su color, nivel y
opciones) y el rectangulo (x, y, w, h).

Reglas: nunca se inventan datos. Si el equipo no da una medicion (ej. la
temperatura), el widget dice "no disponible".

Los widgets de voz, mascota, conversacion y el panel de pestañas viven en
ventana.py porque comparten mucho estado con ella.
"""

import calendar
import math
import socket
import time

from . import ajustes, datos, en_vivo, entrada, tema

try:
    import psutil
except Exception:
    psutil = None

NIVEL = {"minimo": 0, "normal": 1, "detallado": 2}


def _acento(wd, nombre):
    return wd.get("color") or getattr(tema, nombre)


def _caja(v, wd, x, y, w, h, titulo, color_attr):
    """Dibuja la tarjeta y devuelve (px, yy, bw, color, esc, nivel)."""
    esc = v._esc()
    col = _acento(wd, color_attr)
    v._tarjeta(x, y, w, h, wd.get("titulo") or titulo, col)
    return x + 16 * esc, y + 44 * esc, w - 32 * esc, col, esc, NIVEL.get(wd.get("nivel"), 1)


def _no_disponible(v, px, yy, txt, esc):
    v._texto(px, yy, txt, 9, tema.TENUE)
    return yy + 22 * esc


def _fila(v, px, yy, bw, etiqueta, valor, color=None, esc=1.0):
    v._texto(px, yy, etiqueta, 9, tema.TENUE)
    v._texto(px + bw, yy, str(valor), 9, color or tema.TEXTO, ancla="e")
    return yy + 20 * esc


# ------------------------------------------------------------------ datos del sistema (con cache)
_cache = {}


def _con_cache(clave, seg, fn):
    t = time.time()
    p = _cache.get(clave)
    if p and t - p[0] < seg:
        return p[1]
    try:
        val = fn()
    except Exception:
        val = p[1] if p else None
    _cache[clave] = (t, val)
    return val


def temperatura():
    """Grados si el equipo los da; None si no."""
    def _leer():
        if psutil is None or not hasattr(psutil, "sensors_temperatures"):
            return None
        t = psutil.sensors_temperatures() or {}
        for lista in t.values():
            for s in lista:
                if s.current:
                    return float(s.current)
        return None
    return _con_cache("temp", 5, _leer)


def red_info():
    def _leer():
        ip = "sin red"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        sal = {"ip": ip}
        if psutil is not None:
            c = psutil.net_io_counters()
            sal["enviado"], sal["recibido"] = c.bytes_sent, c.bytes_recv
        return sal
    return _con_cache("red", 1.5, _leer) or {}


def discos():
    def _leer():
        if psutil is None:
            return []
        sal = []
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
                sal.append({"nombre": p.mountpoint, "usado": u.percent, "libre_gb": u.free / 1024 ** 3})
            except Exception:
                continue
        return sal[:6]
    return _con_cache("discos", 10, _leer) or []


def _bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024.0


# ------------------------------------------------------------------ anillo
def anillo(v, cx, cy, r, valor, color, etiqueta, texto, esc, limite=None):
    """Indicador circular. El numero y la etiqueta lo hacen legible aunque no se distinga el color."""
    c = v.canvas
    gr = max(4, int(7 * esc))
    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=tema.PANEL_2, width=gr, tags=v._tag)
    ext = -359.9 * max(0.0, min(1.0, valor / 100.0))
    if abs(ext) > 1:
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=ext, style="arc", outline=color, width=gr,
                     tags=v._tag)
    v._texto(cx, cy - 4 * esc, texto, 11, tema.TEXTO, ancla="center", negrita=True)
    v._texto(cx, cy + 12 * esc, etiqueta, 8, tema.TENUE, ancla="center")


# ------------------------------------------------------------------ sistema
def w_sistema(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "ESTADO DEL EQUIPO", "AZUL_CLARO")
    eq = v.snap.get("equipo", {})
    ocultar = set(ajustes.obtener("sistema_ocultar"))
    limites = {"cpu": ajustes.obtener("limite_cpu"), "ram": ajustes.obtener("limite_ram"),
               "disco": ajustes.obtener("limite_disco")}
    items = [("cpu", "CPU"), ("ram", "RAM"), ("disco", "Disco")]
    if "bateria" in eq:
        items.append(("bateria", "Batería" + (" · cargando" if eq.get("enchufado") else "")))
    items = [i for i in items if i[0] not in ocultar]
    if "cpu" not in eq:
        _no_disponible(v, px, yy, "Cargando datos del equipo…" if time.time() - v.t0 < 6 else "Sin datos (instala psutil)", esc)
        return
    estilo = wd["opts"].get("estilo") or ajustes.obtener("sistema_estilo")

    def color_de(k, val):
        if k == "bateria":
            return tema.ALERTA if val < 20 and not eq.get("enchufado") else tema.OK
        lim = limites.get(k, 90)
        if val >= lim:
            return tema.ALERTA
        return tema.ATENCION if val >= lim * 0.78 else tema.OK

    def marca(k, val):                   # no depende solo del color: un "!" cuando pasa el limite
        return " !" if k in limites and val >= limites[k] else ""

    if estilo == "circular":
        n = max(1, len(items))
        cols = 2 if w > 170 * esc and n > 1 else 1
        celda_w = bw / cols
        r = max(18 * esc, min(celda_w * 0.34, 44 * esc))
        for i, (k, nombre) in enumerate(items):
            cx = px + celda_w * (i % cols) + celda_w / 2
            cy = yy + r + 10 * esc + (i // cols) * (r * 2 + 30 * esc)
            if cy + r > y + h - 8 * esc:
                break
            anillo(v, cx, cy, r, eq[k], color_de(k, eq[k]), nombre.split(" ")[0], f"{eq[k]:.0f}%{marca(k, eq[k])}", esc)
    elif estilo == "numeros":
        for k, nombre in items:
            if yy + 30 * esc > y + h:
                break
            v._texto(px, yy + 12 * esc, f"{eq[k]:.0f}%{marca(k, eq[k])}", 20, color_de(k, eq[k]), negrita=True)
            v._texto(px + bw, yy + 12 * esc, nombre, 9, tema.TENUE, ancla="e")
            yy += 34 * esc
    elif estilo == "compacto":
        for k, nombre in items:
            if yy + 18 * esc > y + h:
                break
            v._texto(px, yy, nombre.split(" ")[0], 9, tema.TENUE)
            v._texto(px + bw, yy, f"{eq[k]:.0f}%{marca(k, eq[k])}", 9, color_de(k, eq[k]), ancla="e", negrita=True)
            yy += 18 * esc
    else:
        for k, nombre in items:
            if yy + 44 * esc > y + h:
                break
            yy = v._barra(px, yy, bw, nombre, eq[k], color_de(k, eq[k]), f"{eq[k]:.0f}%{marca(k, eq[k])}")
    if nivel >= 2 and estilo in ("barras", "compacto", "numeros"):
        t = temperatura()
        if yy + 20 * esc < y + h:
            _fila(v, px, yy + 4 * esc, bw, "Temperatura", f"{t:.0f} °C" if t is not None else "no disponible",
                  None if t is not None else tema.TENUE, esc)


# ------------------------------------------------------------------ graficas
def w_graficas(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "ACTIVIDAD", "MORADO_CLARO")
    if "grafica" in ajustes.obtener("sistema_ocultar"):
        _no_disponible(v, px, yy, "Oculta en Ajustes › Sistema", esc)
        return
    alto = y + h - yy - 26 * esc
    if alto < 20 * esc:
        return
    v._texto(px + bw, y + 20 * esc, "CPU", 8, tema.GRAFICA_A, ancla="e")
    v._texto(px + bw - 34 * esc, y + 20 * esc, "RAM", 8, tema.GRAFICA_B, ancla="e")
    v._grafica(px, yy - 8 * esc, bw, alto, [(list(v.hist_ram), tema.GRAFICA_B), (list(v.hist_cpu), tema.GRAFICA_A)])
    if v.hist_cpu and nivel >= 1:
        v._texto(px, y + h - 14 * esc, f"CPU {v.hist_cpu[-1]:.0f}% · RAM {v.hist_ram[-1]:.0f}%" if v.hist_ram else "", 8, tema.TENUE)


# ------------------------------------------------------------------ segundo plano
def w_procesos(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "SEGUNDO PLANO", "MORADO_CLARO")
    cubiertos = ("Piloto automático de mejora", "Autonomía: avisos y hábitos", "Voz natural", "Examen automático",
                 "Modo estudio")
    procs = [p for p in v.snap.get("procesos", []) if nivel >= 2 or p["nombre"] not in cubiertos]
    v._texto(x + w - 16 * esc, y + 20 * esc, f"{len(procs)}", 8, tema.TENUE, ancla="e")
    fila = (34 if nivel else 22) * esc
    pulso = 0.5 + 0.5 * math.sin(v.fase * 2.2)
    mostrados = 0
    for p in procs:
        if yy + fila > y + h - 6 * esc:
            break
        colp = tema.MORADO_CLARO if p["activo"] else tema.AZUL_CLARO
        r = 4 * esc
        v.canvas.create_oval(px, yy - r, px + 2 * r, yy + r, tags=v._tag, outline="",
                             fill=tema.mezclar(tema.PANEL, colp, (0.55 + 0.45 * pulso) if p["activo"] else 0.55))
        nombre = p["nombre"] + (f" ×{p['cantidad']}" if p["cantidad"] > 1 else "")
        maxc = int((bw - 16 * esc) / (9 * esc * 0.6))
        v._texto(px + 16 * esc, yy, nombre[:maxc], 9, tema.TEXTO, negrita=bool(p["activo"]))
        if p["detalle"] and nivel:
            v._texto(px + 16 * esc, yy + 14 * esc, p["detalle"][:maxc + 4], 8, tema.TENUE)
        yy += fila
        mostrados += 1
    if not procs:
        v._texto(px, yy, "Sin tareas extra ahora" if time.time() - v.t0 > 6 else "Cargando…", 9, tema.TENUE)
    elif mostrados < len(procs):
        v._texto(px, y + h - 14 * esc, f"+{len(procs) - mostrados} más", 8, tema.TENUE)


# ------------------------------------------------------------------ modelo
def w_modelo(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "MODELO DE IA", "MORADO_CLARO")
    nb, rd = v.snap.get("nube", {}), v.snap.get("red", {})
    cerebro = f"{nb.get('proveedor', 'ollama')} · {nb.get('modelo', 'local')}" if nb else "Ollama local"
    maxc = int(bw / (10 * esc * 0.6))
    v._texto(px, yy, cerebro[:maxc], 10, tema.TEXTO, negrita=True)
    yy += 20 * esc
    if nivel >= 1 and yy < y + h - 10 * esc:
        v._texto(px, yy, (f"red neuronal {rd['precision'] * 100:.1f}% · {rd['intenciones']} intenciones" if rd.get("activo")
                          else "red neuronal inactiva")[:maxc + 6], 9, tema.AZUL_CLARO if rd.get("activo") else tema.TENUE)
        yy += 20 * esc
    if nivel >= 2 and yy < y + h - 10 * esc:
        v._texto(px, yy, f"{rd.get('ejemplos', 0)} ejemplos de entrenamiento" if rd.get("activo") else "sin datos de entrenamiento", 9, tema.TENUE)


# ------------------------------------------------------------------ estado del asistente
def w_estado_asistente(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "ESTADO DEL ASISTENTE", "AZUL_CLARO")
    est = v.estado_extendido()
    nombre, colr = v.etiqueta_estado(est)
    r = 6 * esc
    pulso = 0.5 + 0.5 * math.sin(v.fase * 2)
    v.canvas.create_oval(px, yy - r, px + 2 * r, yy + r, fill=tema.mezclar(tema.PANEL, colr, 0.4 + 0.6 * pulso), outline="", tags=v._tag)
    v._texto(px + 20 * esc, yy, nombre, 13, colr, negrita=True)
    if nivel >= 1 and yy + 26 * esc < y + h:
        ult = [i for i in en_vivo.intenciones][-1:]
        v._texto(px, yy + 24 * esc, ("última intención: " + ult[0]["intencion"])[:int(bw / (9 * esc * 0.6))] if ult else "sin órdenes todavía", 9, tema.TENUE)


# ------------------------------------------------------------------ actividad / historial / registro
def w_actividad(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "ACTIVIDAD RECIENTE", "MORADO_CLARO")
    ints = list(en_vivo.intenciones)[::-1]
    if not ints:
        v._texto(px, yy, "Nada todavía: escríbeme algo.", 9, tema.TENUE)
        return
    maxc = int(bw / (9 * esc * 0.6))
    for i in ints:
        if yy + 22 * esc > y + h:
            break
        v._texto(px, yy, i["intencion"][:maxc - 8], 9, tema.TEXTO)
        v._texto(px + bw, yy, f"{i['seg']}s", 8, tema.TENUE, ancla="e")
        if nivel >= 2:
            v._texto(px, yy + 13 * esc, f"{i['via'] or '—'}", 8, tema.TENUE)
            yy += 14 * esc
        yy += 20 * esc


def w_historial(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "HISTORIAL DE ACCIONES", "AZUL_CLARO")
    ordenes = [m for m in en_vivo.chat if m["q"] == "tu"][::-1]
    if not ordenes:
        v._texto(px, yy, "Aún sin órdenes en esta sesión.", 9, tema.TENUE)
        return
    maxc = int((bw - 44 * esc) / (9 * esc * 0.6))
    for m in ordenes:
        if yy + 20 * esc > y + h:
            break
        v._texto(px, yy, time.strftime("%H:%M", time.localtime(m["ts"])), 8, tema.TENUE)
        v._texto(px + 42 * esc, yy, m["t"][:maxc], 9, tema.TEXTO)
        yy += 20 * esc


def w_registro(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "REGISTRO DE EVENTOS", "AZUL_CLARO")
    ev = list(v.eventos)[::-1]
    if not ev:
        v._texto(px, yy, "Sin eventos todavía.", 9, tema.TENUE, mono=True)
        return
    maxc = int((bw - 60 * esc) / (9 * esc * 0.6))
    for t, tipo, txt in ev:
        if yy + 16 * esc > y + h:
            break
        colr = {"orden": tema.AZUL_CLARO, "aviso": tema.MORADO_CLARO, "error": tema.ROJO_CLARO,
                "tarea": tema.TENUE}.get(tipo, tema.TEXTO)
        v._texto(px, yy, time.strftime("%H:%M:%S", time.localtime(t)), 8, tema.TENUE, mono=True)
        v._texto(px + 58 * esc, yy, f"{tipo[:5]:<5} {txt}"[:maxc], 8, colr, mono=True)
        yy += 16 * esc


def w_mejora(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "MEJORA CONTINUA", "AZUL_CLARO")
    mej = v.snap.get("hoy", {}).get("mejora", [])[::-1]
    if not mej:
        v._texto(px, yy, "Aún nada (trabajo cuando no me usas).", 9, tema.TENUE)
        return
    maxc = int(bw / (9 * esc * 0.6))
    for t, txt in mej:
        if yy + 28 * esc > y + h:
            break
        try:
            hora = time.strftime("%d/%m %H:%M", time.localtime(t))
        except Exception:
            hora = ""
        v._texto(px, yy, txt[:maxc], 9, tema.TEXTO)
        if nivel:
            v._texto(px, yy + 13 * esc, hora, 8, tema.TENUE)
            yy += 12 * esc
        yy += 22 * esc


def w_estadisticas(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "ESTADÍSTICAS", "MORADO_CLARO")
    v._texto(px, yy + 6 * esc, str(en_vivo.ordenes), 24, tema.TEXTO, negrita=True)
    v._texto(px + 60 * esc, yy + 4 * esc, "órdenes en esta sesión", 9, tema.TENUE)
    yy += 36 * esc
    ex, rd = v.snap.get("examen", {}), v.snap.get("red", {})
    if nivel >= 1 and yy < y + h - 10 * esc:
        yy = _fila(v, px, yy, bw, "Intenciones entendidas", len(en_vivo.intenciones), esc=esc)
        if ex.get("dominios"):
            yy = _fila(v, px, yy, bw, "Examen · nivel", f"{ex.get('nivel')} ({ex.get('listos')}/{len(ex['dominios'])})", esc=esc)
    if nivel >= 2 and yy < y + h - 10 * esc:
        yy = _fila(v, px, yy, bw, "Precisión de la red", f"{rd['precision'] * 100:.1f}%" if rd.get("activo") else "no disponible", esc=esc)
        mins = int((time.time() - v.t0) / 60)
        _fila(v, px, yy, bw, "Ventana abierta", f"{mins} min", esc=esc)


# ------------------------------------------------------------------ productividad
def w_reloj(v, wd, x, y, w, h, esc):
    esc = v._esc()
    col = _acento(wd, "TEXTO") if wd.get("color") else tema.TEXTO
    v._tarjeta_simple(x, y, w, h, wd)
    lt = time.localtime()
    estilo = wd["opts"].get("estilo", "digital")
    if estilo == "analogico" and h > 60 * esc:
        r = min(w, h) * 0.38
        cx, cy = x + w / 2, y + h / 2
        v.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=tema.BORDE, width=2, tags=v._tag)
        for k in range(12):
            a = math.radians(k * 30)
            v._linea((cx + math.sin(a) * r * 0.86, cy - math.cos(a) * r * 0.86, cx + math.sin(a) * r * 0.97, cy - math.cos(a) * r * 0.97), tema.TENUE, 2)
        for frac, largo, anc, c2 in (((lt.tm_hour % 12 + lt.tm_min / 60) / 12, 0.5, 4, col), ((lt.tm_min + lt.tm_sec / 60) / 60, 0.75, 3, col),
                                    (lt.tm_sec / 60, 0.85, 1, tema.ROJO_CLARO)):
            a = frac * 2 * math.pi
            v._linea((cx, cy, cx + math.sin(a) * r * largo, cy - math.cos(a) * r * largo), c2, anc)
        return
    grande = max(14, min(h * 0.42, w * 0.2) / esc * 0.9)
    v._texto(x + w / 2, y + h * 0.42, time.strftime("%H:%M", lt), grande, col, ancla="center", negrita=True)
    if h > 50 * esc:
        v._texto(x + w / 2, y + h * 0.78, f"{('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')[lt.tm_wday]} {time.strftime('%d/%m/%Y', lt)}", 9, tema.TENUE, ancla="center")


def w_calendario(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, time.strftime("CALENDARIO · %B %Y").upper() if False else "CALENDARIO", "AZUL_CLARO")
    hoy = time.localtime()
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    v._texto(x + w - 16 * esc, y + 20 * esc, f"{meses[hoy.tm_mon - 1]} {hoy.tm_year}", 9, tema.TENUE, ancla="e")
    celda_w = bw / 7
    celda_h = min(22 * esc, (y + h - yy - 22 * esc) / 7)
    if celda_h < 10 * esc:
        return
    for i, d in enumerate(("L", "M", "X", "J", "V", "S", "D")):
        v._texto(px + celda_w * (i + 0.5), yy, d, 8, tema.TENUE, ancla="center")
    yy += celda_h
    for fila, semana in enumerate(calendar.Calendar(0).monthdayscalendar(hoy.tm_year, hoy.tm_mon)):
        for i, d in enumerate(semana):
            if not d:
                continue
            cx, cy = px + celda_w * (i + 0.5), yy + celda_h * (fila + 0.5)
            if d == hoy.tm_mday:
                r = min(celda_w, celda_h) * 0.45
                v.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=tema.mezclar(tema.PANEL, col, 0.7), outline=col, tags=v._tag)
            v._texto(cx, cy, str(d), 9, tema.TEXTO if d == hoy.tm_mday else tema.TENUE, ancla="center", negrita=d == hoy.tm_mday)


def w_notas(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "NOTAS", "MORADO_CLARO")
    notas = ajustes.obtener("notas")
    if not notas:
        v._texto(px, yy, "Escribe «nota: …» y aparece aquí.", 9, tema.TENUE)
        return
    maxc = int((bw - 22 * esc) / (9 * esc * 0.6))
    for i, n in enumerate(notas):
        if yy + 20 * esc > y + h:
            v._texto(px, y + h - 12 * esc, f"+{len(notas) - i} más", 8, tema.TENUE)
            break
        v._texto(px, yy, f"{i + 1}.", 8, tema.TENUE)
        v._texto(px + 16 * esc, yy, str(n)[:maxc], 9, tema.TEXTO)
        v.zonas.append((px + bw - 18 * esc, yy - 8 * esc, px + bw, yy + 8 * esc, ("nota_borrar", i)))
        v._texto(px + bw, yy, "✕", 8, tema.ROJO_CLARO if v.hover == ("nota_borrar", i) else tema.TENUE, ancla="e")
        yy += 20 * esc


def w_recordatorios(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "RECORDATORIOS", "ROJO_CLARO")
    al = v.snap.get("hoy", {}).get("alarmas", [])
    if not al:
        v._texto(px, yy, "Sin alarmas pendientes.", 9, tema.TENUE)
        return
    maxc = int(bw / (9 * esc * 0.6))
    for cuando, txt in al:
        if yy + 28 * esc > y + h:
            break
        v._texto(px, yy, (txt or "aviso")[:maxc], 9, tema.TEXTO)
        v._texto(px, yy + 13 * esc, str(cuando)[5:16], 8, tema.TENUE)
        yy += 30 * esc


ATAJOS_BASE = [{"texto": "Procesos", "orden": "procesos"}, {"texto": "Comandos", "orden": "comandos"},
               {"texto": "Ambiente", "orden": "ambiente"}, {"texto": "Modo TV", "orden": "modo tv"}]


def w_atajos(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "ACCESOS DIRECTOS", "AZUL_CLARO")
    lista = ajustes.obtener("atajos_rapidos") or ATAJOS_BASE
    cx, fila_y = px, yy - 8 * esc
    for a in lista:
        if not isinstance(a, dict) or "orden" not in a:
            continue
        ancho = (len(str(a.get("texto", a["orden"]))) * 6.6 + 20) * esc
        if cx + ancho > px + bw:
            cx, fila_y = px, fila_y + 28 * esc
        if fila_y + 22 * esc > y + h:
            break
        v._chip(cx, fila_y, str(a.get("texto", a["orden"])), ("orden", a["orden"]), False, col, ancho)
        cx += ancho + 6 * esc


# ------------------------------------------------------------------ red / dispositivos
def w_red(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "RED", "AZUL_CLARO")
    info = red_info()
    if not info:
        _no_disponible(v, px, yy, "Sin datos de red", esc)
        return
    yy = _fila(v, px, yy, bw, "Dirección", info.get("ip", "—"), esc=esc)
    if "enviado" in info:
        ahora = time.time()
        prev = v._red_prev
        if prev and ahora - prev[0] > 0.9:
            dt = ahora - prev[0]
            v._red_vel = ((info["enviado"] - prev[1]) / dt, (info["recibido"] - prev[2]) / dt)
            v._red_prev = (ahora, info["enviado"], info["recibido"])
        elif not prev:
            v._red_prev = (ahora, info["enviado"], info["recibido"])
        sube, baja = v._red_vel
        if nivel >= 1 and yy < y + h:
            yy = _fila(v, px, yy, bw, "Subida", _bytes(sube) + "/s", esc=esc)
            yy = _fila(v, px, yy, bw, "Bajada", _bytes(baja) + "/s", esc=esc)
        if nivel >= 2 and yy < y + h:
            _fila(v, px, yy, bw, "Total recibido", _bytes(info["recibido"]), esc=esc)
    else:
        _no_disponible(v, px, yy, "Velocidad: no disponible (instala psutil)", esc)


def w_dispositivos(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "DISPOSITIVOS", "MORADO_CLARO")
    try:
        from . import remoto
        celular = remoto.activo()
    except Exception:
        celular = False
    yy = _fila(v, px, yy, bw, "Control por celular", "activo" if celular else "apagado", tema.AZUL_CLARO if celular else tema.TENUE, esc)
    yy = _fila(v, px, yy, bw, "Micrófono (escucha)", "activo" if ajustes.obtener("escucha") else "apagado", None, esc)
    eq = v.snap.get("equipo", {})
    if "bateria" in eq and yy < y + h:
        yy = _fila(v, px, yy, bw, "Batería", f"{eq['bateria']:.0f}%" + (" · cargando" if eq.get("enchufado") else ""), esc=esc)
    if nivel >= 1:
        for d in discos():
            if yy + 18 * esc > y + h:
                break
            yy = _fila(v, px, yy, bw, d["nombre"][:14], f"{d['usado']:.0f}% usado", None, esc)


# ------------------------------------------------------------------ notificaciones y progreso
def w_notificaciones(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "NOTIFICACIONES", "MORADO_CLARO")
    lista = list(v.historial_notif)[::-1]
    if not lista:
        v._texto(px, yy, "Sin avisos todavía.", 9, tema.TENUE)
        return
    maxc = int((bw - 14 * esc) / (9 * esc * 0.6))
    for a in lista:
        if yy + 24 * esc > y + h:
            break
        colr = {"exito": tema.AZUL_CLARO, "error": tema.ROJO_CLARO}.get(a["tipo"], tema.MORADO_CLARO)
        simbolo = {"exito": "✓", "error": "!"}.get(a["tipo"], "•")
        v._texto(px, yy, simbolo, 10, colr, negrita=True)
        v._texto(px + 14 * esc, yy, a["texto"][:maxc], 9, tema.TEXTO)
        if nivel >= 1:
            v._texto(px + 14 * esc, yy + 12 * esc, time.strftime("%H:%M:%S", time.localtime(a["ts"])), 8, tema.TENUE)
            yy += 10 * esc
        yy += 22 * esc


def w_progreso(v, wd, x, y, w, h, esc):
    px, yy, bw, col, esc, nivel = _caja(v, wd, x, y, w, h, "PROGRESO DE TAREAS", "AZUL_CLARO")
    activos = [p for p in v.snap.get("procesos", []) if p["activo"]]
    ex = v.snap.get("examen", {})
    filas = [(p["nombre"], p["detalle"] or "trabajando…", None) for p in activos]
    if ex.get("automatico") and ex.get("dominios"):
        filas.append(("Examen automático", f"{ex['listos']}/{len(ex['dominios'])} dominios listos", ex["listos"] / max(1, len(ex["dominios"]))))
    if not filas:
        v._texto(px, yy, "Sin tareas en curso.", 9, tema.TENUE)
        return
    hb = max(5, int(6 * esc))
    for nombre, det, frac in filas:
        if yy + 34 * esc > y + h:
            break
        v._texto(px, yy, nombre[:int(bw / (9 * esc * 0.6))], 9, tema.TEXTO, negrita=True)
        yb = yy + 18 * esc
        v._linea((px + hb / 2, yb, px + bw - hb / 2, yb), tema.PANEL_2, hb)
        if frac is not None:         # progreso real
            v._linea((px + hb / 2, yb, px + hb / 2 + (bw - hb) * frac, yb), col, hb)
        else:                        # sin porcentaje conocido: barra que se mueve, no un numero inventado
            t = (v.fase * 0.4) % 1.0
            a = px + hb / 2 + (bw - hb) * max(0.0, t - 0.2)
            b = px + hb / 2 + (bw - hb) * min(1.0, t + 0.2)
            v._linea((a, yb, max(a + 1, b), yb), col, hb)
        if nivel:
            v._texto(px, yb + 12 * esc, det[:int(bw / (8 * esc * 0.6))], 8, tema.TENUE)
        yy += (42 if nivel else 32) * esc


def w_redes(v, wd, x, y, w, h, esc):
    """Las redes neuronales de Arché (diagrama, arbol o lista; con ejemplos reales). Ver vista_redes.py."""
    from . import vista_redes
    vista_redes.dibujar_widget(v, wd, x, y, w, h, esc)


def w_contenedor(v, wd, x, y, w, h, esc):
    """Tarjeta con pestañas o carrusel (ver orden.py)."""
    from . import orden
    orden.dibujar_contenedor(v, wd, x, y, w, h, esc)


TABLA = {
    "pestanas": w_contenedor, "carrusel": w_contenedor,
    "sistema": w_sistema, "graficas": w_graficas, "procesos": w_procesos, "modelo": w_modelo, "redes": w_redes,
    "estado_asistente": w_estado_asistente, "actividad": w_actividad, "historial": w_historial,
    "registro": w_registro, "mejora": w_mejora, "estadisticas": w_estadisticas, "reloj": w_reloj,
    "calendario": w_calendario, "notas": w_notas, "recordatorios": w_recordatorios, "atajos": w_atajos,
    "red": w_red, "dispositivos": w_dispositivos, "notificaciones": w_notificaciones, "progreso": w_progreso,
}
