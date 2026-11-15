"""
asistente.py
------------
Ubicacion: Arche/core/tres_d/asistente.py

Arché revisa la pieza y propone arreglos CONCRETOS: cada sugerencia trae
números calculados sobre TU pieza (no consejos genéricos) y, cuando se puede,
la orden exacta que la arregla. La página la aplica con un toque (o con el
pulgar arriba) y después muestra el antes y el después.

  sugerencias(nombre) -> [{id, tipo, titulo, por_que, antes, despues, orden}]
     tipo:  "arreglo"  algo que conviene corregir antes de imprimir (tiene orden)
            "idea"     algo útil que puede hacer por ti (tiene orden)
            "consejo"  algo que se ajusta en el slicer (sin orden: Arché no maneja el slicer)
"""

import math

import numpy as np

from . import disenador as dis
from . import geometria as geo


def _cm2(mm2):
    return f"{mm2 / 100:.1f} cm²"


def _pct(x):
    return f"{x:.0f} %"


def _cabe(dims, cama):
    return bool(np.all(np.sort(dims[:2]) <= np.sort(np.array(cama[:2])) + 1e-6) and dims[2] <= cama[2] + 1e-6)


def _orientaciones(malla):
    """Cada forma de apoyarla, con sus medidas y su voladizo."""
    salida = []
    for o in geo.mejor_orientacion(malla):
        m = geo.apoyar(malla) if o["eje"] is None else geo.rotar(malla, o["eje"], o["grados"])
        salida.append(dict(o, dims=m.dimensiones()))
    return salida


def sugerencias(nombre, cama=None, material="pla"):
    from . import ajustes
    a_cfg = ajustes()
    cama = cama or a_cfg["cama"]
    material = a_cfg.get("material", material)
    malla = dis.abrir(nombre)
    receta = dis.leer_receta(nombre)
    pieza = receta.get("pieza")
    medidas = receta.get("medidas") or {}
    an = geo.analizar(malla, material=material, cama=cama)
    area = max(malla.area(), 1e-9)
    actual_sop, actual_base = geo._voladizo(geo.apoyar(malla))
    opciones = _orientaciones(malla)
    lista = []

    # 1) no cabe en la impresora
    if not an["cabe"]:
        girada = next((o for o in opciones if _cabe(o["dims"], cama)), None)
        d = an["dimensiones"]
        if girada and girada["eje"] is not None:
            lista.append({"id": "girar_para_caber", "tipo": "arreglo", "titulo": "Girarla para que quepa",
                          "por_que": f"Así como está mide {d[0]:.0f}×{d[1]:.0f}×{d[2]:.0f} mm y tu impresora llega a "
                                     f"{cama[0]:.0f}×{cama[1]:.0f}×{cama[2]:.0f}. Acostada de otra forma sí entra, sin achicarla.",
                          "antes": "no cabe", "despues": f"{girada['dims'][0]:.0f}×{girada['dims'][1]:.0f}×{girada['dims'][2]:.0f} mm, cabe",
                          "orden": f"rota el modelo {girada['grados']:g} en {girada['eje']}"})
        else:
            lados = np.sort(np.array(d[:2]))
            factor = min(float(np.min(np.sort(np.array(cama[:2])) / np.maximum(lados, 1e-9))),
                         float(cama[2] / max(d[2], 1e-9))) * 0.97
            pct = max(1, int(math.floor(factor * 100)))
            lista.append({"id": "escalar_para_caber", "tipo": "arreglo", "titulo": f"Escalarla al {pct} % para que quepa",
                          "por_que": f"Mide {d[0]:.0f}×{d[1]:.0f}×{d[2]:.0f} mm y tu impresora llega a "
                                     f"{cama[0]:.0f}×{cama[1]:.0f}×{cama[2]:.0f}. Ni girándola entra. "
                                     "Si la medida importa, mejor pártela en dos.",
                          "antes": f"{d[0]:.0f}×{d[1]:.0f}×{d[2]:.0f} mm",
                          "despues": f"{d[0] * pct / 100:.0f}×{d[1] * pct / 100:.0f}×{d[2] * pct / 100:.0f} mm",
                          "orden": f"escala el modelo al {pct}%"})

    # 2) mucho voladizo y otra posición necesita bastante menos soporte
    mejor = opciones[0]
    if actual_sop / area > 0.03 and mejor["eje"] is not None and mejor["soporte_mm2"] < actual_sop * 0.6 - 50 \
            and _cabe(mejor["dims"], cama):
        lista.append({"id": "orientar", "tipo": "arreglo", "titulo": "Girarla para usar menos soportes",
                      "por_que": f"Ahora {_pct(actual_sop / area * 100)} de la superficie queda en el aire y necesita soporte "
                                 f"(lo rojo). {mejor['nombre'].capitalize()} baja a {_pct(mejor['soporte_mm2'] / area * 100)}: "
                                 "menos plástico tirado y mejor acabado.",
                      "antes": f"{_cm2(actual_sop)} en voladizo", "despues": f"{_cm2(mejor['soporte_mm2'])} en voladizo",
                      "orden": "orienta el modelo para imprimir"})

    # 3) malla con huecos
    if not an["cerrada"]:
        lista.append({"id": "reparar", "tipo": "arreglo", "titulo": "Reparar la malla",
                      "por_que": "Tiene bordes sueltos o caras repetidas; el slicer puede rellenarla mal o saltarse capas. "
                                 "Intento cerrarla uniendo los puntos que casi se tocan.",
                      "antes": "malla abierta", "despues": "malla cerrada (si se puede)", "orden": "repara el modelo"})

    # 4) paredes demasiado delgadas (piezas de Arché, donde sé el grosor exacto)
    if pieza in ("caja", "vaso") and float(medidas.get("pared", 2)) < 1.2:
        lista.append({"id": "pared", "tipo": "arreglo", "titulo": "Pared más gruesa",
                      "por_que": f"La pared mide {float(medidas['pared']):g} mm: con boquilla de 0,4 son menos de 3 líneas "
                                 "y queda frágil o con huecos. Con 1,6 mm son 4 líneas firmes.",
                      "antes": f"pared {float(medidas['pared']):g} mm", "despues": "pared 1.6 mm",
                      "orden": "cambia la pared a 1.6"})

    # 5) se apoya en poquito y es alta: se puede caer a mitad de impresión
    dims = an["dimensiones"]
    base_cm2 = actual_base / 100
    ya_orienta = any(x["id"] == "orientar" for x in lista) and mejor["base_mm2"] > actual_base * 2
    if dims[2] > 25 and base_cm2 < max(2.0, dims[2] * dims[2] / 900) and not ya_orienta:
        mas_base = max(opciones, key=lambda o: (o["base_mm2"] - o["soporte_mm2"] * 2))
        if mas_base["eje"] is not None and mas_base["base_mm2"] > actual_base * 2 and \
                mas_base["soporte_mm2"] <= actual_sop + 100 and _cabe(mas_base["dims"], cama):
            lista.append({"id": "acostar", "tipo": "arreglo", "titulo": "Acostarla para que no se caiga",
                          "por_que": f"Toca la cama con solo {base_cm2:.1f} cm² y mide {dims[2]:.0f} mm de alto: "
                                     "puede despegarse o tambalear. Acostada se apoya mucho mejor.",
                          "antes": f"{base_cm2:.1f} cm² apoyados", "despues": f"{mas_base['base_mm2'] / 100:.1f} cm² apoyados",
                          "orden": f"rota el modelo {mas_base['grados']:g} en {mas_base['eje']}"})
        else:
            lista.append({"id": "borde", "tipo": "consejo", "titulo": "Usa borde (brim) en el slicer",
                          "por_que": f"Toca la cama con {base_cm2:.1f} cm² y mide {dims[2]:.0f} mm de alto. Un borde de "
                                     "5 mm la sostiene y se quita con la mano al terminar.",
                          "antes": "", "despues": "", "orden": None})

    # 6) ahorro real con menos relleno (piezas grandes)
    if an["horas"] > 1.5:
        menos = geo.analizar(malla, material=material, cama=cama, relleno=0.10)
        ahorro_g = an["gramos"] - menos["gramos"]
        ahorro_h = an["horas"] - menos["horas"]
        if ahorro_g >= 3:
            lista.append({"id": "relleno", "tipo": "consejo", "titulo": "Relleno al 10 % si no hace fuerza",
                          "por_que": f"Si es decorativa o no carga peso, en el slicer pon 10 % en vez de 20 %: "
                                     f"ahorras unos {ahorro_g:.0f} g y {geo.tiempo_legible(ahorro_h)}.",
                          "antes": f"{an['gramos']:.0f} g · {geo.tiempo_legible(an['horas'])}",
                          "despues": f"{menos['gramos']:.0f} g · {geo.tiempo_legible(menos['horas'])}", "orden": None})

    # 7) ideas que solo tienen sentido para ciertas piezas
    if pieza == "engranaje":
        z = int(round(float(medidas.get("dientes", 20))))
        m = float(medidas.get("modulo", 2))
        for z2, nombre_rel in ((z, "igual (1:1)"), (min(200, z * 2), "el doble (1:2)")):
            lista.append({"id": f"companero_{z2}", "tipo": "idea", "titulo": f"Engranaje compañero {nombre_rel}",
                          "por_que": f"Del mismo módulo ({m:g}) para que engranen. Pon los ejes a "
                                     f"{m * (z + z2) / 2:.1f} mm de distancia (+0,2 mm de holgura).",
                          "antes": f"{z} dientes", "despues": f"{z2} dientes",
                          "orden": f"crea un engranaje compañero de {z2} dientes"})
            if z2 == z * 2 or z * 2 > 200:
                break
    if pieza == "caja" and not medidas.get("tapa"):
        lista.append({"id": "tapa", "tipo": "idea", "titulo": "Hacerle tapa que encaje",
                      "por_que": "Una tapa con ceja, 0,25 mm más chica por lado para que entre a presión sin forzar.",
                      "antes": "sin tapa", "despues": "con tapa", "orden": "ponle tapa"})
    if receta.get("importado") and receta.get("espejo_de") is None and not dis.existe(nombre + "_espejo") \
            and not _simetrica(malla):
            lista.append({"id": "espejo", "tipo": "idea", "titulo": "La pieza del otro lado",
                          "por_que": "Si va en pareja (izquierda y derecha, como las patas del perro), hago la versión espejo.",
                          "antes": "", "despues": "", "orden": "espejo del modelo"})

    orden_tipo = {"arreglo": 0, "idea": 1, "consejo": 2}
    lista.sort(key=lambda s: orden_tipo[s["tipo"]])
    return {"nombre": nombre, "sugerencias": lista,
            "resumen": ("Lista para imprimir. " if not any(s["tipo"] == "arreglo" for s in lista) else "")
            + (f"{sum(1 for s in lista if s['tipo'] == 'arreglo')} arreglo(s) recomendado(s)." if any(s["tipo"] == "arreglo" for s in lista) else "")}


def _simetrica(malla):
    """True si la pieza es igual a su espejo (en X o en Y): ahí la versión espejo no sirve de nada."""
    v = malla.vertices - malla.vertices.mean(axis=0)
    paso = max(float(malla.dimensiones().max()), 1.0) / 400
    base = {tuple(x) for x in np.round(v / paso).astype(np.int64)}
    for eje in (0, 1):
        w = v.copy()
        w[:, eje] *= -1
        reflejo = {tuple(x) for x in np.round(w / paso).astype(np.int64)}
        if len(base & reflejo) >= 0.97 * len(base):
            return True
    return False


def reparar(malla):
    """Intenta cerrar la malla uniendo puntos que casi se tocan. Devuelve (malla nueva, ok)."""
    from .piezas import motor
    m = motor()
    triangulos = malla.vertices[malla.caras]
    for tolerancia in (0.001, 0.005, 0.02):          # mm: une puntos que están a menos de esto
        try:
            puntos = triangulos.reshape(-1, 3)
            claves = np.round(puntos / tolerancia).astype(np.int64)
            unicos, inverso = np.unique(claves, axis=0, return_inverse=True)
            caras = np.asarray(inverso).reshape(-1, 3)
            buenas = (caras[:, 0] != caras[:, 1]) & (caras[:, 1] != caras[:, 2]) & (caras[:, 0] != caras[:, 2])
            vertices = unicos.astype(np.float64) * tolerancia
            mesh = m.Mesh(vert_properties=np.asarray(vertices, dtype=np.float32),
                          tri_verts=np.asarray(caras[buenas], dtype=np.uint32))
            mesh.merge()
            solido = m.Manifold(mesh)
            if solido.status() == m.Error.NoError and not solido.is_empty():
                r = solido.to_mesh()
                nueva = geo.apoyar(geo.Malla(np.asarray(r.vert_properties)[:, :3], np.asarray(r.tri_verts)))
                if nueva.cerrada() and nueva.volumen() > 0:
                    return nueva, True
        except Exception:
            continue
    return malla, False
