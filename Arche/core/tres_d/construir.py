"""
construir.py
------------
Ubicacion: Arche/core/tres_d/construir.py

El modo Construir del taller: armas una pieza propia juntando formas (caja,
cilindro, esfera, cono, prisma, o tus modelos guardados) y restando otras
(agujeros). Aquí se convierte esa lista de partes en un sólido EXACTO y
cerrado (manifold3d), y Arché revisa la construcción:

  - partes sueltas: si una parte no toca a las demás, saldría como pieza aparte,
  - agujeros para tornillo: un agujero de 3 mm justo no deja pasar un M3 impreso,
  - agujeros que no cortan nada (están fuera de la pieza),
  - que no quepa en la impresora.

Cada parte:  {"id", "forma", "medidas": {...}, "pos": [x, y, z], "rot": [rx, ry, rz], "restar": bool, "modelo": nombre}
  pos = dónde queda el CENTRO de la base de la forma (z = altura de la base), en mm.
  rot = grados (primero X, luego Y, luego Z), alrededor del centro de la base.
"""

import math

import numpy as np

from . import geometria as geo
from . import piezas

MAX_PARTES = 60
FORMAS = ("caja", "cilindro", "esfera", "cono", "prisma", "modelo")
TORNILLOS = {2.0: 2.2, 2.5: 2.7, 3.0: 3.2, 4.0: 4.3, 5.0: 5.3, 6.0: 6.4, 8.0: 8.4}   # métrica -> agujero que imprime bien


def _num(v, defecto, minimo=0.2, maximo=1000.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return float(defecto)
    return max(minimo, min(maximo, v)) if math.isfinite(v) else float(defecto)


def nodo_de(parte):
    """Una parte -> un nodo de receta (ver piezas.desde_receta)."""
    forma = str(parte.get("forma", "")).lower()
    if forma not in FORMAS:
        raise ValueError(f"No conozco la forma «{forma}».")
    m = parte.get("medidas") or {}
    if forma == "caja":
        nodo = {"tipo": "caja", "medidas": [_num(m.get("x"), 20), _num(m.get("y"), 20), _num(m.get("z"), 10)]}
    elif forma == "cilindro":
        nodo = {"tipo": "cilindro", "diametro": _num(m.get("diametro"), 10), "alto": _num(m.get("alto"), 10)}
    elif forma == "esfera":
        nodo = {"tipo": "esfera", "diametro": _num(m.get("diametro"), 10)}
    elif forma == "cono":
        nodo = {"tipo": "cono", "diametro": _num(m.get("diametro"), 10), "punta": _num(m.get("punta"), 0, 0.0), "alto": _num(m.get("alto"), 10)}
    elif forma == "prisma":
        nodo = {"tipo": "prisma", "lados": int(_num(m.get("lados"), 6, 3, 64)), "diametro": _num(m.get("diametro"), 10), "alto": _num(m.get("alto"), 10)}
    else:
        nodo = {"tipo": "modelo", "nombre": str(parte.get("modelo", ""))}
    if forma == "modelo" and m.get("escala"):
        nodo["escalar"] = _num(m.get("escala"), 1, 0.01, 100)
    rot = parte.get("rot") or [0, 0, 0]
    if any(float(r or 0) for r in rot):
        nodo["rotar"] = [float(_num(r, 0, -360, 360)) for r in list(rot)[:3]]
    pos = parte.get("pos") or [0, 0, 0]
    nodo["mover"] = [float(_num(p, 0, -1000, 1000)) for p in list(pos)[:3]]
    return nodo


def _solido(parte):
    return piezas._nodo(nodo_de(parte), [0])


def _centro(solido):
    b = solido.bounding_box()
    return np.array([(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2])


def _acercar(suelta, otras, union_otras):
    """Cuánto mover (mm) una parte suelta hacia la más cercana para que se crucen ~1 mm. None si no se puede."""
    yo = _centro(suelta)
    cercana = min(otras, key=lambda o: float(np.linalg.norm(_centro(o) - yo)))
    direccion = _centro(cercana) - yo
    largo = float(np.linalg.norm(direccion))
    if largo < 1e-6:
        return None
    toca = lambda t: (suelta.translate(list(direccion * t)) ^ union_otras).volume() > 1e-3
    if not toca(1.0):
        return None
    lo, hi = 0.0, 1.0
    for _ in range(30):                      # búsqueda binaria: el primer punto donde se tocan
        medio = (lo + hi) / 2
        if toca(medio):
            hi = medio
        else:
            lo = medio
    t = min(1.0, hi + 1.0 / largo)           # y 1 mm más, para que queden bien pegadas
    return [round(float(v), 1) for v in direccion * t]


def construir(partes, cama=None, material="pla"):
    """Devuelve (Malla, info). info trae medidas, peso, avisos de Arché y qué partes tienen problemas."""
    m = piezas.motor()
    if not isinstance(partes, list) or not partes:
        raise ValueError("No hay partes todavía.")
    if len(partes) > MAX_PARTES:
        raise ValueError(f"Son demasiadas partes (máximo {MAX_PARTES}).")
    suma = [p for p in partes if not p.get("restar")]
    resta = [p for p in partes if p.get("restar")]
    if not suma:
        raise ValueError("Solo hay agujeros: agrega al menos una forma sólida.")
    solidos = {id(p): _solido(p) for p in partes}
    cuerpo = m.Manifold.batch_boolean([solidos[id(p)] for p in suma], m.OpType.Add) if len(suma) > 1 else solidos[id(suma[0])]
    resultado = cuerpo
    if resta:
        resultado = m.Manifold.batch_boolean([cuerpo] + [solidos[id(p)] for p in resta], m.OpType.Subtract)
    if resultado.is_empty():
        raise ValueError("Los agujeros se comieron toda la pieza.")

    avisos, problemas, juntar = [], {}, {}

    # 1) partes sueltas: ¿con cuántos trozos queda? y ¿cuáles no tocan a ninguna otra?
    trozos = len(resultado.decompose())
    if trozos > 1 and len(suma) > 1:
        mayor = max(suma, key=lambda q: solidos[id(q)].volume())     # la parte más grande se queda quieta
        for p in suma:
            otras = [solidos[id(q)] for q in suma if q is not p]
            union_otras = m.Manifold.batch_boolean(otras, m.OpType.Add) if len(otras) > 1 else otras[0]
            # tocar = se cruzan, o están pegadas cara con cara (separación ~0)
            choca = (solidos[id(p)] ^ union_otras).volume() > 1e-6
            if not choca:
                a, b = solidos[id(p)].bounding_box()[:3], solidos[id(p)].bounding_box()[3:]
                c, d = union_otras.bounding_box()[:3], union_otras.bounding_box()[3:]
                separacion = max(max(c[i] - b[i], a[i] - d[i]) for i in range(3))
                if separacion > 0.05:
                    problemas.setdefault(p.get("id"), []).append("suelta")
                    mov = None if p is mayor else _acercar(solidos[id(p)], [solidos[id(q)] for q in suma if q is not p], union_otras)
                    if mov:
                        juntar[p.get("id")] = mov
        avisos.append({"id": "sueltas", "tipo": "arreglo",
                       "texto": f"La pieza queda en {trozos} trozos separados: hay partes que no tocan a las demás "
                                "(las marco en rojo). Acércalas hasta que se crucen un poco."})

    # 2) agujeros
    for p in resta:
        corta = (cuerpo ^ solidos[id(p)]).volume() > 1e-6
        if not corta:
            problemas.setdefault(p.get("id"), []).append("no_corta")
            avisos.append({"id": f"no_corta_{p.get('id')}", "tipo": "arreglo", "parte": p.get("id"),
                           "texto": "Hay un agujero que no corta nada: está fuera de la pieza. Muévelo encima de una parte."})
            continue
        if p.get("forma") == "cilindro":
            d = _num((p.get("medidas") or {}).get("diametro"), 10)
            justo = TORNILLOS.get(round(d, 1))
            if justo:
                avisos.append({"id": f"tornillo_{p.get('id')}", "tipo": "arreglo", "parte": p.get("id"),
                               "texto": f"Un agujero de {d:g} mm justos no deja pasar un tornillo M{d:g} impreso (el plástico "
                                        f"se encoge). Para M{d:g} usa {justo:g} mm.",
                               "cambio": {"parte": p.get("id"), "medida": "diametro", "valor": justo}})

    malla = piezas.a_malla(resultado)
    a = geo.analizar(malla, material=material, cama=cama or geo.CAMA)
    if not a["cabe"]:
        avisos.append({"id": "no_cabe", "tipo": "consejo",
                       "texto": "Así no cabe en tu impresora. Al guardarla, Arché te propone cómo girarla o escalarla."})
    info = {"dimensiones": a["dimensiones"], "volumen_cm3": a["volumen_cm3"], "gramos": a["gramos"],
            "tiempo": geo.tiempo_legible(a["horas"]), "cabe": a["cabe"], "trozos": trozos,
            "soporte_pct": a["soporte_pct"], "triangulos": a["triangulos"],
            "avisos": avisos, "problemas": problemas, "juntar": juntar}
    return malla, info


# ------------------------------------------------------------------
# Modelar (estilo Blender): objetos hechos de triángulos que llegan desde la página
# ------------------------------------------------------------------

MAX_VERTICES = 1_500_000


def unir_mallas(objetos, cama=None, material="pla"):
    """objetos = [{"v": [x,y,z,...], "f": [a,b,c,...]}] ya en su lugar (con giros y modificadores).
    Los une en un solo sólido cerrado. Devuelve (Malla, info)."""
    m = piezas.motor()
    if not isinstance(objetos, list) or not objetos:
        raise ValueError("No hay objetos para guardar.")
    total = sum(len(o.get("v") or []) for o in objetos) // 3
    if total > MAX_VERTICES:
        raise ValueError("La escena es demasiado pesada para guardarla (baja la subdivisión).")
    solidos, abiertos = [], 0
    for o in objetos:
        v = np.asarray(o.get("v") or [], dtype=np.float32).reshape(-1, 3)
        f = np.asarray(o.get("f") or [], dtype=np.int64).reshape(-1, 3)
        if not len(v) or not len(f) or f.min() < 0 or f.max() >= len(v) or not np.isfinite(v).all():
            raise ValueError("Llegó un objeto dañado.")
        mesh = m.Mesh(vert_properties=v, tri_verts=f.astype(np.uint32))
        mesh.merge()
        s = m.Manifold(mesh)
        if s.status() != m.Error.NoError or s.is_empty():
            abiertos += 1
            continue
        solidos.append(s)
    if not solidos:
        raise ValueError("Ningún objeto quedó cerrado; no se puede imprimir así.")
    resultado = m.Manifold.batch_boolean(solidos, m.OpType.Add) if len(solidos) > 1 else solidos[0]
    trozos = len(resultado.decompose())
    malla = piezas.a_malla(resultado)
    a = geo.analizar(malla, material=material, cama=cama or geo.CAMA)
    avisos = []
    if abiertos:
        avisos.append(f"{abiertos} objeto(s) tenían la malla abierta y los dejé afuera.")
    if trozos > 1:
        avisos.append(f"Quedan {trozos} trozos separados: hay objetos que no se tocan. Si es a propósito (varias "
                      "piezas en la misma cama), está bien.")
    if not a["cabe"]:
        avisos.append("No cabe en tu impresora; en el Taller Arché te propone cómo girarla o escalarla.")
    return malla, {"dimensiones": a["dimensiones"], "gramos": a["gramos"], "tiempo": geo.tiempo_legible(a["horas"]),
                   "trozos": trozos, "cabe": a["cabe"], "avisos": avisos, "triangulos": a["triangulos"]}
