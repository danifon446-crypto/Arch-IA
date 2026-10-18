"""
vista_redes.py
--------------
Ubicacion: Arche/core/interfaz/vista_redes.py

Dibuja las redes neuronales de Arché: el widget (movible y redimensionable) y
la vista grande (pantalla completa). Los datos salen de redes.py; aqui solo se
pinta y se reciben los clics.

Lo que se ve es real:
  - las capas y el numero de neuronas salen de la red entrenada (si hay muchas
    neuronas se dibuja una muestra y se dice cuantas hay de verdad);
  - el color de cada linea es el PESO real entre esas dos neuronas;
  - al probar una frase, el brillo de cada neurona es su activacion real.

Todo se puede elegir en Ajustes > Redes neuronales (estilo, neuronas por capa,
colores, leyenda, neurona de cerca, ejemplos visibles, etc.).
"""

import threading
import time

from . import ajustes, redes, tema

ui = {"grande": False, "clave": None, "intencion": None, "neurona": None, "forzar": False, "prueba_vista": 0.0}

_formas = {}              # clave -> {"key": ..., "f": forma | None}
_cargando = set()
_dd = {}                  # cache de lo ya muestreado para dibujar


def _A(k):
    return ajustes.obtener(k)


# ------------------------------------------------------------------ datos para dibujar
def _forma(clave):
    """Pesos de la red (se leen en un hilo aparte: el pickle puede ser grande). None mientras carga."""
    info = redes.red_info(clave)
    if not info or not info["entrenada"]:
        return None
    key = (info["ejemplos_red"], round(info["precision"], 5))
    c = _formas.get(clave)
    if c and c["key"] == key:
        return c["f"]
    if clave not in _cargando:
        _cargando.add(clave)

        def cargar():
            try:
                f = redes.forma_de(clave)
            except Exception:
                f = None
            _formas[clave] = {"key": key, "f": f}
            _cargando.discard(clave)

        threading.Thread(target=cargar, name="arche-redes-pesos", daemon=True).start()
    return c["f"] if c else None


def _muestra(n, k):
    if n <= k:
        return list(range(n))
    return sorted({int(round(i * (n - 1) / (k - 1))) for i in range(k)})


def _preparar(clave, k):
    """Muestra de neuronas y pesos entre ellas para dibujar. None si no hay red cargada."""
    f = _forma(clave)
    if not f:
        return None
    key = (clave, k, id(f))
    c = _dd.get(clave)
    if c and c["key"] == key:
        return c
    import numpy as np
    coefs = f["coefs"]
    binaria = coefs[-1].shape[1] == 1
    tam = [coefs[0].shape[0]] + [w.shape[1] for w in coefs[:-1]]
    nsal = 2 if binaria else coefs[-1].shape[1]
    info = redes.red_info(clave) or {}
    ej = {e["id"]: e["ejemplos"] for e in info.get("etiquetas", [])}
    salida = list(range(nsal))
    if nsal > 14:
        salida = sorted(sorted(salida, key=lambda i: -ej.get(f["clases"][i], 0))[:14])
    idx = [_muestra(n, k) for n in tam] + [salida]
    pesos = []
    for l, w in enumerate(coefs):
        if l == len(coefs) - 1 and binaria:
            w = np.hstack([-w, w])
        pesos.append(np.asarray(w)[np.ix_(idx[l], idx[l + 1])])
    mx = max([float(np.abs(p).max()) for p in pesos if p.size] or [1.0]) or 1.0
    c = {"key": key, "idx": idx, "tam": tam + [nsal], "pesos": pesos, "max": mx, "f": f, "binaria": binaria}
    _dd[clave] = c
    return c


def _prueba_de(clave):
    p = redes.estado["prueba"]
    if p and p.get("clave") == clave and not p.get("error") and p.get("ocultas") is not None:
        return p
    return None


def _sincronizar():
    """Si llego una prueba nueva, la vista salta a la red donde se hizo."""
    p = redes.estado["prueba"]
    if p and p["ts"] > ui["prueba_vista"]:
        ui["prueba_vista"] = p["ts"]
        if p.get("clave") and redes.clave_valida(p["clave"]):
            ui["clave"] = p["clave"]
    snap = redes.snapshot()
    if ui["clave"] is None or (snap["listo"] and not redes.clave_valida(ui["clave"])):
        ui["clave"] = redes.primera_clave()
    return snap


def _etiqueta_corta(r):
    n = r["nombre"]
    return n.replace("General · ", "").replace("Clásica · todas las intenciones", "clásica")


def _rec(v, txt, ancho, tam=9):
    chars = max(3, int(ancho / (tam * 0.68 * v._esc() * _A("texto_escala") / 100.0)))
    return txt if len(txt) <= chars else txt[:chars - 1] + "…"


def _visibles_selector(snap):
    """Las redes de arriba y las del dominio que estas mirando (todas estan en el arbol y la lista)."""
    cur = redes.red_info(ui["clave"])
    fam = None
    if cur:
        fam = cur["clave"] if cur["nivel"] == 1 else (cur["padre"] if cur["nivel"] == 2 else None)
    return [r for r in snap["redes"] if r["nivel"] <= 1 or r["padre"] == fam or r["clave"] == ui["clave"]]


def _salto(v, d):
    ids = [r["clave"] for r in redes.snapshot()["redes"]]
    if ids and ui["clave"] in ids:
        ui["clave"] = ids[(ids.index(ui["clave"]) + d) % len(ids)]
        ui["intencion"] = None
        ui["neurona"] = None


# ------------------------------------------------------------------ el diagrama
def _fondo_neurona(color, a):
    return tema.mezclar(tema.PANEL_2, color, max(0.0, min(1.0, a)))


def diagrama(v, x, y, w, h, esc, clave, grande=False):
    """Dibuja la red. Devuelve nada; registra zonas clicables de neuronas (si grande)."""
    c = v.canvas
    info = redes.red_info(clave)
    if info is None:
        v._texto(x + w / 2, y + h / 2, "Leyendo las redes…", 10, tema.TENUE, ancla="center")
        return
    k = int(_A("redes_neuronas"))
    pad = 16 * esc
    prep = _preparar(clave, k) if info["entrenada"] else None
    if info["entrenada"] and prep is None:
        v._texto(x + w / 2, y + h / 2, "Cargando los pesos de la red…", 10, tema.TENUE, ancla="center")
        return
    if prep is None:
        _fantasma(v, x, y, w, h, esc, info)
        return

    anim = _A("redes_animar") and not v._reducido() and not v._ahorro()
    pr = _prueba_de(clave)
    onda = 99.0
    if pr is not None:
        onda = (time.time() - pr["ts"]) * 1.6 if anim else 99.0
    nc = len(prep["idx"])
    reserva_sup = 30 * esc if (grande or w > 330 * esc) else 22 * esc
    reserva_inf = 18 * esc if _A("redes_leyenda") or grande else 14 * esc
    ancho_etq = (_ancho_etiquetas(v, info, prep, esc) if _A("redes_etiquetas") else 0)
    x0, x1 = x + pad + 12 * esc, x + w - pad - ancho_etq
    ytop, ybot = y + reserva_sup, y + h - reserva_inf
    colx = [x0 + (x1 - x0) * i / max(1, nc - 1) for i in range(nc)]
    posy = []
    rad = []
    for i, ids in enumerate(prep["idx"]):
        n = len(ids)
        alto = ybot - ytop
        paso = alto / max(1, n)
        r = max(2.5 * esc, min(13 * esc if grande else 10 * esc, paso * 0.38, (x1 - x0) / max(1, nc - 1) * 0.3))
        rad.append(r)
        posy.append([ytop + paso * (j + 0.5) for j in range(n)])

    # lineas: el peso real entre las neuronas dibujadas
    frac = _A("redes_conexiones") / 100.0
    if frac > 0 and not (v._ahorro() and prep["max"] > 0 and frac > 0.5):
        import numpy as np
        pos, neg = _A("redes_color_pos"), _A("redes_color_neg")
        for l, W in enumerate(prep["pesos"]):
            a = np.abs(W)
            if a.size == 0:
                continue
            corte = float(np.quantile(a, 1.0 - frac)) if frac < 1 else -1.0
            acts = None
            if pr is not None and l >= 1 and l - 1 < len(pr["ocultas"]):
                acts = pr["ocultas"][l - 1]
            elif pr is not None and l == 0:
                acts = pr["entrada"]
            for i in range(W.shape[0]):
                fa = 1.0
                if acts is not None:
                    fa = 0.25 + 0.75 * acts[prep["idx"][l][i]] * (1.0 if onda >= l else 0.0)
                for j in range(W.shape[1]):
                    wv = float(W[i, j])
                    if abs(wv) < corte:
                        continue
                    fuerza = min(1.0, abs(wv) / prep["max"])
                    col = (pos if wv >= 0 else neg) if _A("redes_pesos") else tema.TENUE
                    col = tema.mezclar(tema.PANEL, col, min(1.0, (0.12 + 0.75 * fuerza) * fa))
                    c.create_line(colx[l], posy[l][i], colx[l + 1], posy[l + 1][j], fill=col,
                                  width=max(1, int(1 + fuerza * 1.4 * esc)), tags=v._tag)

    # neuronas
    f = prep["f"]
    clases = f["clases"]
    colores = (tema.AZUL_CLARO, tema.MORADO_CLARO, tema.ROJO_CLARO)
    sel_n = ui["neurona"]
    for l, ids in enumerate(prep["idx"]):
        ultima = l == nc - 1
        col = colores[2] if ultima else (colores[0] if l == 0 else colores[1])
        for j, gi in enumerate(ids):
            cx, cy, r = colx[l], posy[l][j], rad[l]
            a = 0.35
            if pr is not None:
                if ultima:
                    a = pr["probs"][gi] if gi < len(pr["probs"]) else 0.0
                    a = 0.15 + 0.85 * a
                elif l == 0:
                    a = 0.15 + 0.85 * pr["entrada"][gi]
                elif l - 1 < len(pr["ocultas"]):
                    a = 0.15 + 0.85 * pr["ocultas"][l - 1][gi]
                if onda < l:
                    a = 0.2
            borde = col
            ancho_b = 1
            elegido = (sel_n == (l, gi)) or (ultima and ui["intencion"] == clases[gi])
            if elegido:
                borde, ancho_b = tema.TEXTO, 2
            if a > 0.75 and (pr is not None) and not v._ahorro():
                c.create_oval(cx - r * 1.6, cy - r * 1.6, cx + r * 1.6, cy + r * 1.6, fill="",
                              outline=tema.mezclar(tema.PANEL, col, 0.5), width=1, tags=v._tag)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=_fondo_neurona(col, a), outline=borde,
                          width=ancho_b, tags=v._tag)
            if grande and not ultima and l > 0:
                v.zonas.append((cx - r, cy - r, cx + r, cy + r, ("redes", "neurona", l, gi)))
            elif grande and l == 0:
                v.zonas.append((cx - r, cy - r, cx + r, cy + r, ("redes", "neurona", 0, gi)))
            if ultima:
                et = clases[gi] if gi < len(clases) else str(gi)
                v.zonas.append((cx - r, cy - r, x + w, cy + r, ("redes", "intencion", et)))
                if _A("redes_etiquetas"):
                    txt = _rec(v, et, ancho_etq - 18 * esc - 40 * esc, 8)
                    v._texto(cx + r + 6 * esc, cy, txt, 8, tema.TEXTO if elegido else tema.TENUE, negrita=elegido)
                    if pr is not None and gi < len(pr["probs"]):
                        v._texto(x + w - pad / 2, cy, f"{pr['probs'][gi] * 100:.0f}%", 8,
                                 tema.TEXTO if pr["probs"][gi] > 0.5 else tema.TENUE, ancla="e")
                    elif info:
                        n_e = next((e["ejemplos"] for e in info["etiquetas"] if e["id"] == et), 0)
                        v._texto(x + w - pad / 2, cy, str(n_e), 8, tema.TENUE, ancla="e")

    # rotulos de las capas (nombre y numero real de neuronas)
    forma = info["forma"] or {}
    nombres = ["Entrada"] + [f"Oculta {i + 1}" for i in range(nc - 2)] + ["Salida"]
    reales = prep["tam"]
    sep = (x1 - x0) / max(1, nc - 1)
    if w > 230 * esc:
        for l in range(nc):
            ancla, xl = ("center", colx[l])
            if l == 0:
                ancla, xl = "w", x + pad
            elif l == nc - 1:
                ancla, xl = "e", x + w - pad
            v._texto(xl, y + 9 * esc, nombres[l], 7, tema.TEXTO, ancla=ancla, negrita=True)
            if grande or w > 330 * esc:
                muestra = "" if len(prep["idx"][l]) == reales[l] else f" · muestra {len(prep['idx'][l])}"
                v._texto(xl, y + 19 * esc, _rec(v, f"{reales[l]} neuronas{muestra}", max(sep, 90 * esc), 7), 7, tema.TENUE, ancla=ancla)
    if grande and forma:
        v._texto(x + pad, y + h - 7 * esc, f"activación: {forma.get('activacion', '?')} · pesos reales entre las neuronas dibujadas",
                 7, tema.TENUE)
    if pr is not None and grande:
        v._texto(x + w - pad, y + h - 7 * esc, f"prueba: «{pr['frase'][:40]}»", 7, tema.MORADO_CLARO, ancla="e")


def _ancho_etiquetas(v, info, prep, esc):
    mx = max([len(e) for e in prep["f"]["clases"]] or [4])
    return min(150 * esc, (mx * 6 + 62) * esc)


def _fantasma(v, x, y, w, h, esc, info):
    """Una red que aun no existe: solo se muestra la forma esperada y se dice por que falta."""
    c = v.canvas
    n_sal = max(2, min(10, len(info["etiquetas"])))
    cols = [(5, tema.AZUL_CLARO), (6, tema.MORADO_CLARO), (n_sal, tema.ROJO_CLARO)]
    x0, x1 = x + 40 * esc, x + w - 60 * esc
    ytop, ybot = y + 26 * esc, y + h - 40 * esc
    pts = []
    for i, (n, col) in enumerate(cols):
        cx = x0 + (x1 - x0) * i / 2
        paso = (ybot - ytop) / n
        pts.append([(cx, ytop + paso * (j + 0.5), col) for j in range(n)])
    for a, b in zip(pts, pts[1:]):
        for p in a:
            for q in b:
                c.create_line(p[0], p[1], q[0], q[1], fill=tema.mezclar(tema.PANEL, tema.BORDE, 0.5), tags=v._tag)
    r = max(3 * esc, min(9 * esc, (ybot - ytop) / n_sal * 0.35))
    for col_pts in pts:
        for cx, cy, col in col_pts:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=tema.PANEL, outline=tema.mezclar(tema.PANEL, col, 0.6), tags=v._tag)
    if info["trivial"]:
        msg = "Esta red no hace falta: solo tiene una intención posible."
    else:
        msg = f"Sin entrenar. Necesita al menos {info['min_por_clase']} ejemplos en 2 o más intenciones."
    v._texto(x + w / 2, y + h - 18 * esc, _rec(v, msg, w - 20 * esc, 9), 9, tema.ATENCION, ancla="center")


# ------------------------------------------------------------------ otros estilos
def _arbol(v, x, y, w, h, esc, grande):
    snap = redes.snapshot()
    nodos = snap["redes"]
    hijos = {}
    for r in nodos:
        hijos.setdefault(r["padre"], []).append(r)
    pos = {}

    def asignar(r, nivel):
        hs = hijos.get(r["clave"], [])
        if not hs:
            pos[r["clave"]] = (nivel, len(pos_filas))
            pos_filas.append(r["clave"])
            return
        for hh in hs:
            asignar(hh, nivel + 1)
        ys = [pos[hh["clave"]][1] for hh in hs]
        pos[r["clave"]] = (nivel, (min(ys) + max(ys)) / 2)

    pos_filas = []
    for raiz in hijos.get(None, []):
        asignar(raiz, 0)
    n = max(1, len(pos_filas))
    nivel_max = max([p[0] for p in pos.values()] or [0])
    paso = max(22 * esc, min(34 * esc, (h - 16 * esc) / n))
    clave_s = "redes_arbol" + ("_g" if grande else "")
    total = n * paso + 16 * esc
    v._scroll_reg[clave_s] = (x, y, x + w, y + h)
    off = max(0, min(v.scroll.get(clave_s, 0), max(0, total - h)))
    v.scroll[clave_s] = off
    y_ini = y
    y = y - off
    bw = min(150 * esc, (w - 20 * esc) / (nivel_max + 1) - 16 * esc)
    por_clave = {r["clave"]: r for r in nodos}
    centro = {}
    for k, (niv, fila) in pos.items():
        cx = x + 10 * esc + niv * (bw + 16 * esc)
        cy = y + 12 * esc + (fila + 0.5) * paso
        centro[k] = (cx, cy)
    for r in nodos:
        if r["padre"] in centro and r["clave"] in centro:
            a, b = centro[r["padre"]], centro[r["clave"]]
            if min(a[1], b[1]) >= y_ini and max(a[1], b[1]) <= y_ini + h:
                v._linea((a[0] + bw, a[1], b[0], b[1]), tema.BORDE, 1)
    for r in nodos:
        cx, cy = centro[r["clave"]]
        if cy - paso * 0.42 < y_ini or cy + paso * 0.42 > y_ini + h:
            continue
        sel = r["clave"] == ui["clave"]
        col = tema.OK if r["entrenada"] else tema.TENUE
        accion = ("redes", "sel", r["clave"])
        pasa = v.hover == accion
        v._redondo(cx, cy - paso * 0.42, cx + bw, cy + paso * 0.42, 6 * esc,
                   fill=tema.mezclar(tema.PANEL_2, tema.MORADO, 0.5 if sel else (0.2 if pasa else 0.0)),
                   outline=tema.TEXTO if sel else (col if r["entrenada"] else tema.BORDE))
        base = r["dominio"] if r["tipo"] == "subdominios" else (r.get("sub") or _etiqueta_corta(r))
        txt = _rec(v, base + (" ▸" if r["tipo"] == "subdominios" else ""), bw - 40 * esc, 8)
        v._texto(cx + 6 * esc, cy, txt, 8, tema.TEXTO if r["activa"] else tema.TENUE, negrita=sel)
        if r["trivial"]:
            lab = "—"
        elif r["entrenada"]:
            lab = f"{r['precision'] * 100:.0f}%"
        else:
            lab = "sin red"
        v._texto(cx + bw - 5 * esc, cy, lab, 7, col, ancla="e")
        v.zonas.append((cx, cy - paso * 0.42, cx + bw, cy + paso * 0.42, accion))


def _lista(v, x, y, w, h, esc, grande):
    snap = redes.snapshot()
    fila = 28 * esc
    clave_s = "redes_lista" + ("_g" if grande else "")
    total = len(snap["redes"]) * fila
    v._scroll_reg[clave_s] = (x, y, x + w, y + h)
    off = max(0, min(v.scroll.get(clave_s, 0), max(0, total - h)))
    v.scroll[clave_s] = off
    v._texto(x + 8 * esc, y + 8 * esc, "RED", 7, tema.TENUE)
    v._texto(x + w * 0.52, y + 8 * esc, "PRECISIÓN", 7, tema.TENUE)
    v._texto(x + w * 0.70, y + 8 * esc, "EJEMPLOS", 7, tema.TENUE)
    v._texto(x + w - 6 * esc, y + 8 * esc, "SIN ENTRENAR", 7, tema.TENUE, ancla="e")
    yy = y + 18 * esc - off
    for r in snap["redes"]:
        if yy >= y + 14 * esc and yy + fila <= y + h + 1:
            sel = r["clave"] == ui["clave"]
            accion = ("redes", "sel", r["clave"])
            if sel or v.hover == accion:
                v._redondo(x + 2, yy, x + w - 2, yy + fila - 3 * esc, 6 * esc,
                           fill=tema.mezclar(tema.PANEL_2, tema.MORADO, 0.4 if sel else 0.15), outline="")
            v._texto(x + 8 * esc, yy + fila / 2 - 1, _rec(v, r["nombre"], w * 0.48, 9), 9, tema.TEXTO if r["activa"] else tema.TENUE, negrita=sel)
            if r["trivial"]:
                v._texto(x + w * 0.52, yy + fila / 2 - 1, "no hace falta", 8, tema.TENUE)
            elif r["entrenada"]:
                p = r["precision"]
                v._texto(x + w * 0.52, yy + fila / 2 - 1, f"{p * 100:.0f}%", 9, tema.OK if p >= 0.9 else (tema.ATENCION if p >= 0.7 else tema.ALERTA))
            else:
                v._texto(x + w * 0.52, yy + fila / 2 - 1, "sin entrenar", 8, tema.TENUE)
            v._texto(x + w * 0.70, yy + fila / 2 - 1, f"{r['ejemplos_hoy']}", 9, tema.TEXTO)
            if r["pendientes"]:
                v._texto(x + w - 6 * esc, yy + fila / 2 - 1, f"+{r['pendientes']}", 9, tema.ATENCION, ancla="e")
            v.zonas.append((x + 2, yy, x + w - 2, yy + fila - 3 * esc, accion))
        yy += fila


def _contenido_red(v, x, y, w, h, esc, grande):
    estilo = _A("redes_estilo")
    if estilo == "arbol":
        _arbol(v, x, y, w, h, esc, grande)
    elif estilo == "lista":
        _lista(v, x, y, w, h, esc, grande)
    else:
        diagrama(v, x, y, w, h, esc, ui["clave"], grande)


# ------------------------------------------------------------------ ejemplos
def _intenciones_de(info, etiqueta):
    d = redes._ia().dom
    if info["tipo"] == "dominios":
        return sorted(d.intenciones_de(etiqueta))
    if info["tipo"] == "subdominios":
        return sorted(d.subdominios_de(info["dominio"]).get(etiqueta, ()))
    return [etiqueta]


def _ejemplos_de_etiqueta(info, etiqueta):
    sal = []
    ints = _intenciones_de(info, etiqueta)
    for i in ints:
        for e in redes.ejemplos_de(i):
            sal.append(dict(e, intencion=i))
    return sal


def _lista_ejemplos(v, x, y, w, h, esc, info, grande, maxn=None):
    """Los ejemplos reales de la etiqueta elegida. Cada uno se puede quitar; los «auto» llevan marca."""
    sel = ui["intencion"]
    if not sel:
        v._texto(x + 8 * esc, y + 12 * esc, "Elige una intención (en la lista o tocando una neurona de salida)", 8, tema.TENUE)
        return
    ejs = _ejemplos_de_etiqueta(info, sel)
    n_total = next((e["ejemplos"] for e in info["etiquetas"] if e["id"] == sel), len(ejs))
    v._texto(x + 8 * esc, y + 10 * esc, _rec(v, f"Ejemplos de «{sel}»", w * 0.6, 9), 9, tema.TEXTO, negrita=True)
    v._texto(x + w - 8 * esc, y + 10 * esc, f"{n_total} en total" + ("" if len(ejs) >= n_total else f" · {len(ejs)} recientes"),
             8, tema.TENUE, ancla="e")
    if not ejs:
        v._texto(x + 8 * esc, y + 34 * esc, "Todavía no tiene ejemplos guardados. Agrégale desde abajo.", 8, tema.ATENCION)
        return
    fila = 22 * esc
    area_y, area_h = y + 22 * esc, h - 22 * esc
    if maxn:
        ejs = ejs[:maxn]
    clave_s = "redes_ej" + ("_g" if grande else "")
    total = len(ejs) * fila
    v._scroll_reg[clave_s] = (x, area_y, x + w, area_y + area_h)
    off = max(0, min(v.scroll.get(clave_s, 0), max(0, total - area_h)))
    v.scroll[clave_s] = off
    yy = area_y - off
    multi = len(_intenciones_de(info, sel)) > 1
    for e in ejs:
        if yy >= area_y - 1 and yy + fila <= area_y + area_h + 1:
            if e["auto"]:
                v._redondo(x + 6 * esc, yy + 3 * esc, x + 36 * esc, yy + fila - 3 * esc, 6 * esc, fill=tema.mezclar(tema.PANEL, tema.MORADO, 0.6), outline="")
                v._texto(x + 21 * esc, yy + fila / 2, "auto", 7, tema.TEXTO, ancla="center")
            ini = 42 * esc if e["auto"] else 10 * esc
            txt = e["pregunta"] + (f"  → {e['intencion']}" if multi else "")
            v._texto(x + ini, yy + fila / 2, _rec(v, txt, w - ini - 30 * esc, 8), 8, tema.TEXTO)
            xq = x + w - 8 * esc
            accion = ("redes", "quitar", e["pregunta"], e["intencion"])
            pasa = v.hover == accion
            v._texto(xq, yy + fila / 2, "✕", 9, tema.ALERTA if pasa else tema.TENUE, ancla="e")
            v.zonas.append((xq - 18 * esc, yy, x + w, yy + fila, accion))
        yy += fila


# ------------------------------------------------------------------ cola de lo que se esta agregando
def _items_visibles():
    ahora = time.time()
    sal = []
    for it in list(redes.estado["resultados"]):
        if it["estado"] in ("agregada", "duplicada", "error", "propuesta", "descartada", "deshecha"):
            it.setdefault("visto", ahora)
            if it["estado"] in ("descartada", "deshecha") and ahora - it["visto"] > 4:
                continue
            if it["estado"] != "agregada" and ahora - it["visto"] > 25:
                continue
            if it["estado"] == "agregada" and ahora - it["visto"] > max(30, _A("redes_deshacer_segundos") * 2):
                continue
        sal.append(it)
        if len(sal) >= 5:
            break
    return sal


def _cola(v, x, y, w, esc, items):
    """Dibuja lo que pasa con cada frase. Devuelve la altura usada."""
    ahora = time.time()
    yy = y
    for it in items:
        e = it["estado"]
        alto = 40 * esc if e in ("elegir", "nueva") else 24 * esc
        if e in ("elegir", "nueva"):
            alto = 46 * esc
        color = {"agregada": tema.OK, "pensando": tema.MORADO_CLARO, "elegir": tema.ATENCION, "nueva": tema.ATENCION,
                 "error": tema.ALERTA, "duplicada": tema.TENUE, "propuesta": tema.OK}.get(e, tema.TENUE)
        v._redondo(x, yy, x + w, yy + alto - 3 * esc, 7 * esc, fill=tema.PANEL_2, outline=tema.mezclar(tema.BORDE, color, 0.5))
        marca = {"agregada": "✓", "pensando": "…" * (1 + int(ahora * 2) % 3), "elegir": "?", "nueva": "+", "error": "!",
                 "duplicada": "=", "propuesta": "✓", "descartada": "·", "deshecha": "↶"}.get(e, "")
        v._texto(x + 8 * esc, yy + 12 * esc, marca, 9, color, negrita=True)
        v._texto(x + 22 * esc, yy + 12 * esc, _rec(v, f"«{it['frase']}»", w * 0.45, 8), 8, tema.TEXTO)
        msg = it["mensaje"]
        if e == "agregada":
            msg = f"→ {it['intencion']} · {it['metodo']}"
            if it.get("auto"):
                msg += " · auto"
        v._texto(x + w * 0.48, yy + 12 * esc, _rec(v, msg, w * 0.5 - 70 * esc, 8), 8, color)
        if e == "agregada" and ahora - it.get("visto", ahora) <= _A("redes_deshacer_segundos"):
            v._chip(x + w - 66 * esc, yy + 1 * esc, "Deshacer", ("redes", "deshacer", it["id"]), False, tema.ATENCION, ancho=60 * esc)
        elif e in ("error", "duplicada"):
            v._texto(x + w - 8 * esc, yy + 12 * esc, "✕", 9, tema.TENUE, ancla="e")
            v.zonas.append((x + w - 24 * esc, yy, x + w, yy + 22 * esc, ("redes", "descartar", it["id"])))
        if e in ("elegir", "nueva"):
            xx = x + 8 * esc
            ya = yy + 22 * esc
            if e == "nueva":
                nom = it["nueva"]["nombre"] or "intencion_nueva"
                xx = v._chip(xx, ya, f"Crear «{nom}»", ("redes", "proponer", it["id"]), True, tema.ATENCION) + 5 * esc
            for o in it["opciones"][:3]:
                etq = _rec(v, o["intencion"] + (f" {o['puntaje'] * 100:.0f}%" if o.get("puntaje") is not None and o["origen"] == "red" else ""), 120 * esc, 8)
                if xx + (len(etq) * 6.6 + 20) * esc > x + w - 64 * esc:
                    break
                xx = v._chip(xx, ya, etq, ("redes", "elegir", it["id"], o["intencion"]), False, tema.AZUL_CLARO) + 5 * esc
            v._chip(x + w - 58 * esc, ya, "Descartar", ("redes", "descartar", it["id"]), False, tema.TENUE, ancho=52 * esc)
        yy += alto
    return yy - y


# ------------------------------------------------------------------ cajas de texto
def _colocar_entrada(v, atributo, x, y, w, h):
    if v.canvas is not v._cv0:            # el widget esta en una ventana aparte: sus cajas viven en la principal
        return
    iid = getattr(v, atributo + "_id")
    v.canvas.coords(iid, x, y)
    v.canvas.itemconfigure(iid, width=int(max(40, w)), height=int(h), state="normal")
    v.canvas.tag_raise(iid)


def _caja_agregar(v, x, y, w, esc, info, hint=True):
    """Texto + botones para agregar ejemplos. Devuelve la altura usada."""
    alto = 52 * esc if hint else 30 * esc
    yy = y
    if hint:
        v._texto(x, yy + 6 * esc, "Agregar ejemplos · Arché decide la intención" if not ui["forzar"] else
                 f"Agregar a «{ui['intencion']}» (tú eliges)", 8, tema.MORADO_CLARO, negrita=True)
        yy += 16 * esc
    if not hint and w < 360 * esc:
        # panel angosto: la caja ocupa todo el ancho y los botones van debajo
        _colocar_entrada(v, "red_add", x, yy + 2 * esc, w, 26 * esc)
        bx = x + w
        bx = v._boton(bx, yy + 58 * esc, "Pegar varias", ("redes", "pegar"), tema.AZUL_CLARO)
        v._boton(bx, yy + 58 * esc, "Agregar", ("redes", "agregar"), tema.MORADO_CLARO)
        return 60 * esc
    bx = x + w
    bx = v._boton(bx, yy + 28 * esc, "Pegar varias", ("redes", "pegar"), tema.AZUL_CLARO)
    bx = v._boton(bx, yy + 28 * esc, "Agregar", ("redes", "agregar"), tema.MORADO_CLARO)
    _colocar_entrada(v, "red_add", x, yy + 2 * esc, bx - x, 24 * esc)
    return alto + (8 * esc if hint else 0)


def _caja_probar(v, x, y, w, esc, clave):
    pr = redes.estado["prueba"]
    bx = x + w
    if w < 360 * esc:
        # panel angosto: caja a todo el ancho y el boton debajo
        _colocar_entrada(v, "red_test", x, y + 2 * esc, w, 26 * esc)
        v._boton(bx, y + 58 * esc, "Probar", ("redes", "probar"), tema.AZUL_CLARO)
        yy = y + 62 * esc
        extra_alto = 30 * esc
    else:
        bx = v._boton(bx, y + 28 * esc, "Probar", ("redes", "probar"), tema.AZUL_CLARO)
        _colocar_entrada(v, "red_test", x, y + 2 * esc, bx - x, 24 * esc)
        yy = y + 32 * esc
        extra_alto = 0
    if redes.estado["probando"]:
        v._texto(x, yy + 4 * esc, "Calculando las neuronas…", 8, tema.TENUE)
    elif pr:
        if pr.get("error"):
            v._texto(x, yy + 4 * esc, _rec(v, pr["error"], w, 8), 8, tema.ALERTA)
        elif pr["pasos"]:
            ruta = "  →  ".join(f"{p['etiqueta']} {p['confianza'] * 100:.0f}%" for p in pr["pasos"])
            v._texto(x, yy + 4 * esc, _rec(v, f"«{pr['frase']}»:  {ruta}", w, 8), 8, tema.TEXTO)
        else:
            v._texto(x, yy + 4 * esc, "Ninguna red entrenada pudo clasificarla todavía.", 8, tema.TENUE)
    return 48 * esc + extra_alto


def _estado_entreno(v, x, y, w, esc, info):
    """Texto, botones y progreso del entrenamiento (alto: 60 * esc)."""
    e = redes.estado["entreno"]
    if info:
        txt = f"{_etiqueta_corta(info)}: {info['ejemplos_hoy']} ejemplos"
        if info["entrenada"]:
            txt += f" · precisión {info['precision'] * 100:.0f}% (entrenada con {info['ejemplos_red']})"
        v._texto(x, y + 8 * esc, _rec(v, txt, w, 8), 8, tema.TEXTO)
        if info["pendientes"]:
            v._texto(x, y + 21 * esc, f"{info['pendientes']} ejemplo(s) nuevo(s) sin entrenar", 8, tema.ATENCION)
        elif info["trivial"]:
            v._texto(x, y + 21 * esc, "Sin entrenamiento: una sola intención", 8, tema.TENUE)
        elif not info["entrenable"]:
            v._texto(x, y + 21 * esc, _rec(v, f"Aún no entrena: faltan ejemplos (mín. {info['min_por_clase']} por intención, en 2+)", w, 8), 8, tema.TENUE)
    fy = y + 58 * esc
    if e["corriendo"]:
        total = max(1, e["total"])
        v._texto(x, y + 38 * esc, _rec(v, f"Entrenando {e['actual'] or '…'}  ({e['hecho']}/{e['total']})", w, 8), 8, tema.MORADO_CLARO)
        hb = 5 * esc
        yb = y + 48 * esc
        v._redondo(x, yb, x + w, yb + hb, hb / 2, fill=tema.PANEL_2, outline="")
        frac = e["hecho"] / total
        if frac > 0:
            v._redondo(x, yb, x + w * frac, yb + hb, hb / 2, fill=tema.MORADO_CLARO, outline="")
        else:
            t = (time.time() * 0.8) % 1.0
            v._redondo(x + (w - w * 0.25) * t, yb, x + (w - w * 0.25) * t + w * 0.25, yb + hb, hb / 2, fill=tema.MORADO_CLARO, outline="")
    else:
        bx = x + w
        bx = v._boton(bx, fy, "Entrenar todas", ("redes", "entrenar", "todas"), tema.ROJO_CLARO)
        if info and info["entrenable"]:
            bx = v._boton(bx, fy, "Entrenar esta", ("redes", "entrenar", info["clave"]), tema.MORADO_CLARO)
        if e["mensaje"]:
            v._texto(x, fy - 13 * esc, _rec(v, e["mensaje"], bx - x, 8), 8, tema.OK if "Listo" in e["mensaje"] else tema.ATENCION)
    return 60 * esc


# ------------------------------------------------------------------ leyenda y neurona de cerca
def _leyenda(v, x, y, w, h, esc):
    pos, neg = _A("redes_color_pos"), _A("redes_color_neg")
    v._texto(x + 8 * esc, y + 10 * esc, "LEYENDA", 7, tema.TENUE)
    filas = [(tema.AZUL_CLARO, "Entrada: el embedding de la frase (384 números)"),
             (tema.MORADO_CLARO, "Capas ocultas: neuronas que detectan rasgos"),
             (tema.ROJO_CLARO, "Salida: una neurona por intención"),
             (pos, "Línea: peso positivo (empuja a favor)"),
             (neg, "Línea: peso negativo (empuja en contra)"),
             (tema.TEXTO, "Brillo: cuánto se activó con tu frase")]
    yy = y + 24 * esc
    paso = min(15 * esc, (h - 28 * esc) / len(filas))
    for col, txt in filas:
        if yy + paso > y + h:
            break
        if col in (pos, neg):
            v._linea((x + 8 * esc, yy, x + 24 * esc, yy), col, 2)
        else:
            r = 4 * esc
            v.canvas.create_oval(x + 16 * esc - r, yy - r, x + 16 * esc + r, yy + r, fill=_fondo_neurona(col, 0.8), outline=col, tags=v._tag)
        v._texto(x + 32 * esc, yy, _rec(v, txt, w - 40 * esc, 8), 8, tema.TEXTO)
        yy += paso


def _cerca(v, x, y, w, h, esc, clave):
    """Una neurona de cerca: lo que de verdad se sabe de ella (pesos, sesgo, activacion)."""
    import numpy as np
    v._texto(x + 8 * esc, y + 10 * esc, "UNA NEURONA DE CERCA", 7, tema.TENUE)
    sel = ui["neurona"]
    f = _forma(clave)
    info = redes.red_info(clave)
    if not f or not info or sel is None:
        msg = "Toca una neurona del diagrama." if f else "Sin red entrenada."
        v._texto(x + 8 * esc, y + 34 * esc, msg, 8, tema.TENUE)
        return
    l, i = sel
    coefs, inter = f["coefs"], f["intercepts"]
    pr = _prueba_de(clave)
    r = min(h * 0.3, 26 * esc)
    cx, cy = x + 12 * esc + r, y + h / 2 + 6 * esc
    a = 0.4
    if l == 0:
        tipo = f"Neurona de entrada #{i}"
        det = ["Una de las 384 dimensiones del embedding.", "Sola no significa nada legible:", "el significado está en el conjunto."]
        if pr is not None:
            a = 0.15 + 0.85 * pr["entrada"][i]
            det.append(f"Con tu frase: {pr['entrada'][i] * 100:.0f}% de su rango")
        col = tema.AZUL_CLARO
    elif l <= len(coefs) - 1 and l - 1 < len(coefs) - 1:
        w_in = coefs[l - 1][:, i]
        tipo = f"Oculta {l} · neurona #{i} de {coefs[l - 1].shape[1]}"
        det = [f"Recibe {len(w_in)} entradas · sesgo {float(inter[l - 1][i]):+.3f}",
               f"Peso medio {float(np.mean(w_in)):+.3f} · mayor {float(np.abs(w_in).max()):.3f}",
               f"{float((w_in > 0).mean()) * 100:.0f}% de sus pesos son positivos"]
        if pr is not None and l - 1 < len(pr["ocultas"]):
            a = 0.15 + 0.85 * pr["ocultas"][l - 1][i]
            det.append(f"Con tu frase: {pr['ocultas'][l - 1][i] * 100:.0f}% de su rango")
        col = tema.MORADO_CLARO
    else:
        tipo, det, col = "Neurona", [], tema.MORADO_CLARO
    v.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=_fondo_neurona(col, a), outline=col, width=2, tags=v._tag)
    if l >= 1 and l - 1 < len(coefs) - 1:                      # histograma de sus pesos de entrada
        w_in = coefs[l - 1][:, i]
        h_, _ = np.histogram(w_in, bins=14)
        mx = max(1, h_.max())
        bx0, bw_ = cx + r + 14 * esc, 5 * esc
        for k, n in enumerate(h_):
            alto = (n / mx) * 26 * esc
            v._redondo(bx0 + k * (bw_ + 1), cy + 30 * esc - alto, bx0 + k * (bw_ + 1) + bw_, cy + 30 * esc, 1, fill=col, outline="")
    v._texto(x + 8 * esc, y + 22 * esc, _rec(v, tipo, w - 16 * esc, 8), 8, tema.TEXTO, negrita=True)
    xt = cx + r + 14 * esc
    for j, t in enumerate(det[:4]):
        v._texto(xt, y + 36 * esc + j * 13 * esc, _rec(v, t, x + w - xt - 6 * esc, 8), 8, tema.TENUE)


# ------------------------------------------------------------------ widget
def dibujar_widget(v, wd, x, y, w, h, esc):
    """El widget de la cuadricula: una red con su selector, el diagrama y un acceso a la vista grande."""
    snap = _sincronizar()
    c = v.canvas
    v._tarjeta(x, y, w, h, "REDES NEURONALES", tema.MORADO_CLARO)
    px = x + 14 * esc
    bw = w - 28 * esc
    if not redes.disponible():
        v._texto(px, y + 44 * esc, "No encuentro core/IA: no hay redes que mostrar.", 9, tema.TENUE)
        return
    if not snap["listo"]:
        v._texto(px, y + 44 * esc, "Leyendo las redes…", 9, tema.TENUE)
        return
    if snap["error"]:
        v._texto(px, y + 44 * esc, _rec(v, "Error al leer: " + snap["error"], bw, 8), 8, tema.ALERTA)
        return
    info = redes.red_info(ui["clave"])
    # selector ‹ nombre ›  y boton de vista grande
    y0 = y + 32 * esc
    v._chip(px, y0, "‹", ("redes", "ciclar", -1), False, ancho=24 * esc)
    xb = x + w - 14 * esc
    ancho_g = 96 * esc
    v._chip(xb - ancho_g, y0, "Vista grande", ("redes", "abrir"), True, tema.AZUL_CLARO, ancho=ancho_g)
    v._chip(xb - ancho_g - 28 * esc, y0, "›", ("redes", "ciclar", 1), False, ancho=24 * esc)
    nombre = _etiqueta_corta(info) if info else "—"
    v._texto(px + 30 * esc, y0 + 11 * esc, _rec(v, nombre, bw - ancho_g - 70 * esc, 9), 9, tema.TEXTO, negrita=True)
    y1 = y0 + 30 * esc
    extra = 0.0
    principal = v.canvas is v._cv0
    puede_agregar = principal and _A("redes_agregar") and h > 250 * esc
    puede_probar = principal and _A("redes_probador") and h > 330 * esc
    if puede_agregar:
        extra += (62 if bw < 360 * esc else 36) * esc
    if puede_probar:
        extra += (80 if bw < 360 * esc else 50) * esc
    area_h = h - (y1 - y) - extra - 22 * esc
    ej_h = 0.0
    if info and ui["intencion"] and area_h > 190 * esc and _A("redes_estilo") == "diagrama":
        ej_h = area_h * 0.42
    if area_h - ej_h > 110 * esc and bw > 200 * esc:
        _contenido_red(v, px, y1, bw, area_h - ej_h, esc, False)
    elif area_h > 20 * esc:
        v._texto(px, y1 + 8 * esc, _rec(v, "Muy pequeño para dibujar las neuronas:", bw, 8), 8, tema.TENUE)
        v._texto(px, y1 + 22 * esc, _rec(v, "agranda el panel o abre la vista grande.", bw, 8), 8, tema.TENUE)
    if ej_h:
        _lista_ejemplos(v, px, y1 + area_h - ej_h, bw, ej_h, esc, info, False, maxn=int(_A("redes_ejemplos_max")))
    yy = y1 + max(area_h, 0)
    if info:
        txt = f"{info['ejemplos_hoy']} ejemplos"
        if info["entrenada"]:
            txt += f" · {info['precision'] * 100:.0f}%"
        if info["pendientes"]:
            txt += f" · +{info['pendientes']} sin entrenar"
        elif not info["entrenada"] and not info["trivial"]:
            txt += " · sin entrenar"
        v._texto(px, yy + 8 * esc, _rec(v, txt, bw, 8), 8, tema.TENUE)
    yy += 18 * esc
    if puede_probar:
        yy += _caja_probar(v, px, yy, bw, esc, ui["clave"]) + 2 * esc
    if puede_agregar:
        _caja_agregar(v, px, yy, bw, esc, info, hint=False)


# ------------------------------------------------------------------ vista grande
def dibujar_grande(v, W, H, esc):
    snap = _sincronizar()
    c = v.canvas
    c.create_rectangle(0, 0, W, H, fill=tema.FONDO, outline="", tags=v._tag)
    m = int(16 * esc)
    v._texto(m, m + 10 * esc, "REDES NEURONALES", 13, tema.MORADO_CLARO, negrita=True)
    activas = sum(1 for r in snap["redes"] if r["entrenada"])
    v._texto(m + 190 * esc, m + 11 * esc, f"{activas}/{len(snap['redes'])} entrenadas · {snap['total']} ejemplos", 8, tema.TENUE)
    v._boton(W - m, m + 24 * esc, "✕ Cerrar", ("redes", "cerrar"), tema.ROJO_CLARO)
    if not redes.disponible() or not snap["listo"] or snap["error"]:
        msg = ("No encuentro core/IA: no hay redes que mostrar." if not redes.disponible()
               else ("Leyendo las redes…" if not snap["listo"] else "Error al leer: " + snap["error"]))
        v._texto(W / 2, H / 2, msg, 11, tema.TENUE, ancla="center")
        return
    # estilo
    y = m + 34 * esc
    xx = m
    for val, txt in (("diagrama", "Diagrama"), ("arbol", "Árbol"), ("lista", "Lista")):
        xx = v._chip(xx, y, txt, ("redes", "estilo", val), _A("redes_estilo") == val, tema.MORADO_CLARO) + 5 * esc
    xx += 10 * esc
    left_w = (W - 3 * m) * 0.60
    # selector de red (chips, con salto de linea)
    x0 = xx
    cur_y = y
    for r in _visibles_selector(snap):
        txt = _etiqueta_corta(r)
        wch = (len(txt) * 6.6 + 20) * esc
        if x0 + wch > m + left_w:
            x0 = m
            cur_y += 26 * esc
        x0 = v._chip(x0, cur_y, txt, ("redes", "sel", r["clave"]), r["clave"] == ui["clave"],
                     tema.OK if r["entrenada"] else tema.TENUE, ancho=wch) + 5 * esc
    ytop = cur_y + 32 * esc
    info = redes.red_info(ui["clave"])
    if info and ui["intencion"] not in [e["id"] for e in info["etiquetas"]]:
        ets = sorted(info["etiquetas"], key=lambda e: -e["ejemplos"])
        ui["intencion"] = ets[0]["id"] if ets else None
    inferior = 128 * esc if (_A("redes_leyenda") or _A("redes_cerca")) else 0
    ybot = H - m
    # columna izquierda: diagrama + leyenda/neurona de cerca
    dh = ybot - ytop - inferior - (8 * esc if inferior else 0)
    v._redondo(m, ytop, m + left_w, ytop + dh, 14 * esc, fill=tema.PANEL, outline=tema.BORDE)
    _contenido_red(v, m, ytop, left_w, dh, esc, True)
    if inferior:
        yb = ytop + dh + 8 * esc
        mitad = left_w / 2 - 4 * esc
        if _A("redes_leyenda"):
            ancho_l = mitad if _A("redes_cerca") else left_w
            v._redondo(m, yb, m + ancho_l, yb + inferior, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
            _leyenda(v, m, yb, ancho_l, inferior, esc)
        if _A("redes_cerca"):
            xc = m + (mitad + 8 * esc if _A("redes_leyenda") else 0)
            wc = mitad if _A("redes_leyenda") else left_w
            v._redondo(xc, yb, xc + wc, yb + inferior, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
            _cerca(v, xc, yb, wc, inferior, esc, ui["clave"])
    # columna derecha
    rx = m * 2 + left_w
    rw = W - m - rx
    gap = 8 * esc
    yy = y
    v._redondo(rx, yy, rx + rw, yy + 66 * esc, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
    _estado_entreno(v, rx + 12 * esc, yy + 4 * esc, rw - 24 * esc, esc, info)
    yy += 66 * esc + gap
    items = _items_visibles()
    if items:
        alto = sum((46 if it["estado"] in ("elegir", "nueva") else 24) * esc for it in items) + 8 * esc
        v._redondo(rx, yy, rx + rw, yy + alto, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
        _cola(v, rx + 8 * esc, yy + 4 * esc, rw - 16 * esc, esc, items)
        yy += alto + gap
    bajo = 0.0
    if _A("redes_probador"):
        bajo += 78 * esc
    if _A("redes_agregar"):
        bajo += 76 * esc
    resto = ybot - yy - bajo - gap * 2
    resto = max(resto, 80 * esc)
    h_int = resto * 0.38
    h_ej = resto - h_int - gap
    # intenciones de la red
    v._redondo(rx, yy, rx + rw, yy + h_int, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
    _lista_etiquetas(v, rx, yy, rw, h_int, esc, info)
    yy += h_int + gap
    v._redondo(rx, yy, rx + rw, yy + h_ej, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
    if info:
        _lista_ejemplos(v, rx, yy, rw, h_ej, esc, info, True)
    yy += h_ej + gap
    if _A("redes_agregar"):
        v._redondo(rx, yy, rx + rw, yy + 76 * esc, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
        _caja_agregar_grande(v, rx + 12 * esc, yy + 4 * esc, rw - 24 * esc, esc, info)
        yy += 76 * esc + gap
    if _A("redes_probador"):
        v._redondo(rx, yy, rx + rw, yy + 78 * esc, 12 * esc, fill=tema.PANEL, outline=tema.BORDE)
        v._texto(rx + 12 * esc, yy + 12 * esc, "Probar una frase · ver qué neuronas se encienden", 8, tema.AZUL_CLARO, negrita=True)
        _caja_probar(v, rx + 12 * esc, yy + 18 * esc, rw - 24 * esc, esc, ui["clave"])


def _caja_agregar_grande(v, x, y, w, esc, info):
    forzable = bool(info and ui["intencion"] and info["tipo"] == "intenciones")
    if not forzable:
        ui["forzar"] = False
    v._texto(x, y + 10 * esc, "Agregar ejemplos (varias con «;»)", 8, tema.MORADO_CLARO, negrita=True)
    if forzable:
        v._chip(x + w - 110 * esc, y + 2 * esc, "Elijo yo" if ui["forzar"] else "Decide Arché", ("redes", "forzar"), ui["forzar"], tema.ATENCION, ancho=110 * esc)
    yy = y + 20 * esc
    bx = x + w
    bx = v._boton(bx, yy + 28 * esc, "Pegar varias", ("redes", "pegar"), tema.AZUL_CLARO)
    bx = v._boton(bx, yy + 28 * esc, "Agregar", ("redes", "agregar"), tema.MORADO_CLARO)
    _colocar_entrada(v, "red_add", x, yy + 2 * esc, bx - x, 24 * esc)
    if ui["forzar"]:
        v._texto(x, yy + 38 * esc, f"Se guardará en «{ui['intencion']}» sin preguntar a nadie.", 8, tema.TENUE)
    else:
        n_prop = redes.snapshot().get("propuestas", 0)
        extra = f" · {n_prop} intención(es) nueva(s) propuesta(s)" if n_prop else ""
        v._texto(x, yy + 38 * esc, _rec(v, f"La red decide si >{_A('redes_umbral_auto')}% de seguridad; si duda, pregunta a la nube{extra}", w, 8), 8, tema.TENUE)


def _lista_etiquetas(v, x, y, w, h, esc, info):
    """Las salidas de la red elegida (intenciones/subdominios/dominios) con cuantos ejemplos tiene cada una."""
    if not info:
        return
    v._texto(x + 10 * esc, y + 10 * esc, "SALIDAS DE ESTA RED", 7, tema.TENUE)
    et = sorted(info["etiquetas"], key=lambda e: -e["ejemplos"])
    fila = 20 * esc
    area_y, area_h = y + 20 * esc, h - 22 * esc
    clave_s = "redes_et"
    total = len(et) * fila
    v._scroll_reg[clave_s] = (x, area_y, x + w, area_y + area_h)
    off = max(0, min(v.scroll.get(clave_s, 0), max(0, total - area_h)))
    v.scroll[clave_s] = off
    mx = max([e["ejemplos"] for e in et] or [1]) or 1
    yy = area_y - off
    for e in et:
        if yy >= area_y - 1 and yy + fila <= area_y + area_h + 1:
            sel = ui["intencion"] == e["id"]
            accion = ("redes", "intencion", e["id"])
            if sel or v.hover == accion:
                v._redondo(x + 4 * esc, yy, x + w - 4 * esc, yy + fila - 2 * esc, 5 * esc, fill=tema.mezclar(tema.PANEL_2, tema.MORADO, 0.4 if sel else 0.15), outline="")
            v._texto(x + 10 * esc, yy + fila / 2 - 1, _rec(v, e["id"], w * 0.42, 8), 8, tema.TEXTO if sel else tema.TENUE, negrita=sel)
            bx0, bx1 = x + w * 0.48, x + w - 52 * esc
            hb = 4 * esc
            ym = yy + fila / 2 - 1
            v._redondo(bx0, ym - hb / 2, bx1, ym + hb / 2, hb / 2, fill=tema.PANEL_2, outline="")
            falta = e["ejemplos"] < info["min_por_clase"] and not info["trivial"]
            if e["ejemplos"]:
                v._redondo(bx0, ym - hb / 2, bx0 + (bx1 - bx0) * min(1.0, e["ejemplos"] / mx), ym + hb / 2, hb / 2,
                           fill=tema.ATENCION if falta else tema.OK, outline="")
            v._texto(x + w - 8 * esc, ym, f"{e['ejemplos']}" + (" ⚠" if falta else ""), 8, tema.ATENCION if falta else tema.TEXTO, ancla="e")
            v.zonas.append((x + 4 * esc, yy, x + w - 4 * esc, yy + fila - 2 * esc, accion))
        yy += fila


# ------------------------------------------------------------------ acciones
def entradas_ocultas(v):
    for att in ("red_add", "red_test"):
        v.canvas.itemconfigure(getattr(v, att + "_id"), state="hidden")


def accion(v, a):
    t = a[1]
    if t == "abrir":
        ui["grande"] = True
        v.canvas.focus_set()
    elif t == "cerrar":
        ui["grande"] = False
    elif t == "estilo":
        ajustes.fijar("redes_estilo", a[2])
    elif t == "sel":
        ui["clave"], ui["intencion"], ui["neurona"] = a[2], None, None
    elif t == "ciclar":
        _salto(v, a[2])
    elif t == "intencion":
        ui["intencion"] = a[2]
    elif t == "neurona":
        ui["neurona"] = None if ui["neurona"] == (a[2], a[3]) else (a[2], a[3])
    elif t == "forzar":
        ui["forzar"] = not ui["forzar"]
    elif t == "agregar":
        _enviar_agregar(v, v.red_add.get())
    elif t == "pegar":
        try:
            _enviar_agregar(v, v.root.clipboard_get())
        except Exception:
            v.avisar("No hay texto copiado para pegar.", "info")
    elif t == "probar":
        _enviar_probar(v)
    elif t == "entrenar":
        if not redes.entrenar(a[2]):
            e = redes.estado["entreno"]
            v.avisar(e["mensaje"] or "Ya estoy entrenando.", "info")
    elif t == "elegir":
        redes.elegir(a[2], a[3])
    elif t == "proponer":
        redes.proponer(a[2])
    elif t == "descartar":
        redes.descartar(a[2])
    elif t == "deshacer":
        redes.deshacer(a[2])
    elif t == "quitar":
        redes.quitar_ejemplo(a[2], a[3])
        v.avisar("Ejemplo quitado.", "info")


def _enviar_agregar(v, texto):
    texto = (texto or "").strip()
    if not texto:
        v.avisar("Escribe una frase (o varias separadas por «;»).", "info")
        return
    if ui["forzar"] and ui["intencion"]:
        n = redes.agregar_a(texto, ui["intencion"])
    else:
        n = redes.agregar(texto)
    v.red_add.delete(0, "end")
    if n == 0:
        v.avisar("No pude agregar eso.", "error")


def _enviar_probar(v):
    texto = v.red_test.get().strip()
    if texto:
        redes.probar(texto, None)


def enter_en(v, cual):
    if cual == "add":
        _enviar_agregar(v, v.red_add.get())
    else:
        _enviar_probar(v)
    return "break"
