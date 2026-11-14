"""
piezas.py
---------
Ubicacion: Arche/core/tres_d/piezas.py

El catálogo de piezas que Arché sabe fabricar a medida, y el intérprete de
"recetas" (árboles de formas) para piezas libres.

Cada pieza es una función con medidas en milímetros que devuelve un sólido.
Usa manifold3d, una librería de geometría que garantiza sólidos CERRADOS
(sin huecos), que es lo que necesita una impresora 3D.

  construir("caja", {"largo": 80, "ancho": 50, "alto": 30})  -> Malla
  desde_receta({"tipo": "diferencia", "de": [...]})          -> Malla

Todas las piezas salen apoyadas en la cama (Z = 0) y en la posición en que
conviene imprimirlas.
"""

import math

import numpy as np

from .geometria import Malla, apoyar

_m3d = None


def motor():
    """Carga manifold3d la primera vez (y lo instala si falta)."""
    global _m3d
    if _m3d is None:
        try:
            import manifold3d
        except ImportError:
            try:
                from core.instalador import verificar_e_instalar
                verificar_e_instalar(["manifold3d"])
            except Exception:
                pass
            try:
                import manifold3d
            except ImportError:
                raise RuntimeError("Me falta la librería de geometría. Instálala con:  pip install manifold3d")
        manifold3d.set_min_circular_angle(6.0)           # círculos suaves...
        manifold3d.set_min_circular_edge_length(0.5)     # ...sin exagerar en piezas chicas
        _m3d = manifold3d
    return _m3d


def a_malla(solido):
    """Sólido de manifold3d -> Malla de Arché (comprueba que quedó bien)."""
    m = motor()
    if solido.is_empty():
        raise ValueError("Con esas medidas la pieza queda vacía (algún agujero se comió todo).")
    if solido.status() != m.Error.NoError:
        raise ValueError(f"La geometría no cerró bien ({solido.status()}).")
    malla = solido.to_mesh()
    return apoyar(Malla(np.asarray(malla.vert_properties)[:, :3], np.asarray(malla.tri_verts)))


# ------------------------------------------------------------------
# Ayudas para construir
# ------------------------------------------------------------------

def _rect_redondo(largo, ancho, radio):
    """Rectángulo centrado con las esquinas redondeadas (figura 2D)."""
    m = motor()
    radio = max(0.0, min(radio, largo / 2 - 0.01, ancho / 2 - 0.01))
    if radio < 0.05:
        return m.CrossSection.square([largo, ancho], True)
    return m.CrossSection.square([largo - 2 * radio, ancho - 2 * radio], True).offset(radio, m.JoinType.Round)


def _cil(diametro, alto, x=0.0, y=0.0, z=0.0):
    return motor().Manifold.cylinder(alto, diametro / 2.0).translate([x, y, z])


def _caja(lx, ly, lz, x=0.0, y=0.0, z=0.0):
    """Caja con una esquina en (x, y, z)."""
    return motor().Manifold.cube([lx, ly, lz]).translate([x, y, z])


def _poligono(puntos):
    m = motor()
    return m.CrossSection([[(float(x), float(y)) for x, y in puntos]], m.FillRule.Positive)


def _positivo(poligono_puntos):
    """Asegura que el polígono vaya en sentido antihorario (si no, sale vacío)."""
    p = list(poligono_puntos)
    area = sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))
    return p if area > 0 else p[::-1]


# ------------------------------------------------------------------
# Las piezas
# ------------------------------------------------------------------

def caja(largo, ancho, alto, pared, redondeo, tapa, postes):
    exterior = _rect_redondo(largo, ancho, redondeo).extrude(alto)
    hueco = _rect_redondo(largo - 2 * pared, ancho - 2 * pared, max(0.0, redondeo - pared)).extrude(alto).translate([0, 0, pared])
    solido = exterior - hueco
    if postes:
        # 4 postes en las esquinas para atornillar una placa (tornillo M3 autorroscante)
        alto_poste = min(6.0, alto - pared)
        dx, dy = largo / 2 - pared - 4.5, ancho / 2 - pared - 4.5
        for sx in (-1, 1):
            for sy in (-1, 1):
                poste = _cil(7.0, alto_poste, sx * dx, sy * dy, pared) - _cil(2.6, alto_poste + 1, sx * dx, sy * dy, pared)
                solido = solido + poste
    if tapa:
        holgura = 0.25
        placa_tapa = _rect_redondo(largo, ancho, redondeo).extrude(pared)
        lx, ly = largo - 2 * pared - 2 * holgura, ancho - 2 * pared - 2 * holgura
        r = max(0.0, redondeo - pared)
        ceja = (_rect_redondo(lx, ly, r).extrude(3.0) - _rect_redondo(lx - 2 * 1.6, ly - 2 * 1.6, max(0.0, r - 1.6)).extrude(3.0))
        solido = solido + (placa_tapa + ceja.translate([0, 0, pared])).translate([largo + 8, 0, 0])
    return solido


def cilindro(diametro, alto):
    return _cil(diametro, alto)


def tubo(diametro, interior, alto):
    return _cil(diametro, alto) - _cil(interior, alto + 2, z=-1)


def esfera(diametro):
    return motor().Manifold.sphere(diametro / 2.0).translate([0, 0, diametro / 2.0])


def cono(diametro, punta, alto):
    return motor().Manifold.cylinder(alto, diametro / 2.0, punta / 2.0)


def placa(largo, ancho, grosor, agujeros_largo, agujeros_ancho, diametro_agujero, margen, redondeo):
    solido = _rect_redondo(largo, ancho, redondeo).extrude(grosor)
    nx, ny = int(agujeros_largo), int(agujeros_ancho)
    if nx > 0 and ny > 0 and diametro_agujero > 0:
        xs = [0.0] if nx == 1 else np.linspace(-largo / 2 + margen, largo / 2 - margen, nx)
        ys = [0.0] if ny == 1 else np.linspace(-ancho / 2 + margen, ancho / 2 - margen, ny)
        for x in xs:
            for y in ys:
                solido = solido - _cil(diametro_agujero, grosor + 2, float(x), float(y), -1)
    return solido


def escuadra(largo, alto, ancho, grosor, agujero, refuerzo):
    base = _caja(largo, ancho, grosor)
    pared = _caja(grosor, ancho, alto)
    solido = base + pared
    if refuerzo and ancho >= 14:
        lado = min(largo, alto) * 0.6
        triangulo = _poligono(_positivo([(grosor, grosor), (grosor + lado, grosor), (grosor, grosor + lado)]))
        costilla = triangulo.extrude(grosor).rotate([90, 0, 0])          # de pie, a lo largo de Y
        solido = solido + costilla.translate([0, grosor, 0]) + costilla.translate([0, ancho, 0])
    if agujero > 0:
        # uno en el piso y uno en la pared, centrados
        solido = solido - _cil(agujero, grosor + 2, grosor + (largo - grosor) * 0.6, ancho / 2, -1)
        taladro = _cil(agujero, grosor + 2).rotate([0, 90, 0]).translate([-1, ancho / 2, grosor + (alto - grosor) * 0.6])
        solido = solido - taladro
    return solido


def separador(diametro, agujero, alto, hexagonal):
    m = motor()
    cuerpo = m.Manifold.cylinder(alto, diametro / 2.0, diametro / 2.0, 6) if hexagonal else _cil(diametro, alto)
    return cuerpo - _cil(agujero, alto + 2, z=-1)


def _perfil_engranaje(dientes, modulo, presion=20.0):
    z = int(dientes)
    a = math.radians(presion)
    rp = modulo * z / 2.0
    rb = rp * math.cos(a)
    ra = rp + modulo
    rf = max(rp - 1.25 * modulo, modulo * 0.6)
    inv = math.tan(a) - a
    beta = math.pi / (2 * z) + inv                    # medio ancho del diente en el círculo base
    t_fin = math.sqrt(max(0.0, (ra / rb) ** 2 - 1))
    t_ini = math.sqrt((rf / rb) ** 2 - 1) if rf > rb else 0.0
    pasos = 8
    puntos = []
    for k in range(z):
        centro = 2 * math.pi * k / z
        flanco = []
        for i in range(pasos + 1):
            t = t_ini + (t_fin - t_ini) * i / pasos
            r = rb * math.sqrt(1 + t * t)
            fi = t - math.atan(t)
            flanco.append((r, fi))
        fi_punta = flanco[-1][1]
        if fi_punta > beta - 0.002:                    # diente demasiado puntiagudo: se recorta
            flanco = [(r, fi) for r, fi in flanco if fi < beta - 0.002] or flanco[:1]
        if rf < rb:
            puntos.append((rf * math.cos(centro - beta), rf * math.sin(centro - beta)))
        for r, fi in flanco:
            puntos.append((r * math.cos(centro - beta + fi), r * math.sin(centro - beta + fi)))
        for r, fi in reversed(flanco):
            puntos.append((r * math.cos(centro + beta - fi), r * math.sin(centro + beta - fi)))
        if rf < rb:
            puntos.append((rf * math.cos(centro + beta), rf * math.sin(centro + beta)))
    return puntos


def engranaje(dientes, modulo, grosor, agujero):
    solido = _poligono(_positivo(_perfil_engranaje(dientes, modulo))).extrude(grosor)
    if agujero > 0:
        solido = solido - _cil(agujero, grosor + 2, z=-1)
    return solido


# cuerpo (largo, ancho), separación de tornillos a lo largo, a lo ancho (0 = uno por lado), diámetro del tornillo
SERVOS = {
    "sg90":   {"cuerpo": (22.8, 12.4), "tornillos": (27.8, 0.0), "tornillo": 2.2},
    "mg90s":  {"cuerpo": (22.8, 12.4), "tornillos": (27.8, 0.0), "tornillo": 2.2},
    "mg996r": {"cuerpo": (40.7, 19.9), "tornillos": (49.5, 10.0), "tornillo": 4.3},
}
SERVOS["mg995"] = SERVOS["mg996r"]
SERVOS["ds3218"] = SERVOS["mg996r"]


def soporte_servo(modelo, grosor, margen):
    datos = SERVOS[modelo]
    cl, ca = datos["cuerpo"][0] + 0.4, datos["cuerpo"][1] + 0.4      # 0,4 mm de holgura
    sl, sa = datos["tornillos"]
    largo = sl + datos["tornillo"] + 2 * margen
    ancho = ca + 2 * margen
    solido = _rect_redondo(largo, ancho, 2.5).extrude(grosor)
    solido = solido - motor().Manifold.cube([cl, ca, grosor + 2], True).translate([0, 0, grosor / 2])
    for sx in (-1, 1):
        for sy in ((-1, 1) if sa else (0,)):
            solido = solido - _cil(datos["tornillo"], grosor + 2, sx * sl / 2, sy * sa / 2, -1)
    return solido


def vaso(diametro, alto, pared, base, drenaje):
    solido = _cil(diametro, alto) - _cil(diametro - 2 * pared, alto, z=base)
    n = int(drenaje)
    for k in range(n):
        ang = 2 * math.pi * k / n
        r = 0.0 if n == 1 else diametro * 0.22
        solido = solido - _cil(5.0, base + 2, r * math.cos(ang), r * math.sin(ang), -1)
    return solido


def rueda(diametro, ancho, agujero, rayos):
    n = int(rayos)
    if n <= 0:
        solido = _cil(diametro, ancho)
    else:
        llanta = max(3.0, diametro * 0.07)
        cubo = max(agujero + 8.0, diametro * 0.22)
        solido = (_cil(diametro, ancho) - _cil(diametro - 2 * llanta, ancho + 2, z=-1)) + _cil(cubo, ancho)
        grosor_rayo = max(3.0, diametro * 0.06)
        largo_rayo = diametro / 2 - llanta / 2
        for k in range(n):
            rayo = _caja(largo_rayo, grosor_rayo, ancho, 0, -grosor_rayo / 2, 0).rotate([0, 0, 360.0 * k / n])
            solido = solido + rayo
    if agujero > 0:
        solido = solido - _cil(agujero, ancho + 2, z=-1)
    return solido


def soporte_celular(ancho, grosor_celular, inclinacion, grosor, alto):
    """Atril para el celular. Sale ACOSTADO de lado: así se imprime sin soportes."""
    m = motor()
    g = grosor
    a = math.radians(inclinacion)
    x0 = g + grosor_celular + 1.0                       # donde arranca el respaldo
    dx, dz = alto * math.cos(a), alto * math.sin(a)
    largo_base = x0 + dx + g + 25.0
    base = m.CrossSection.square([largo_base, g])
    labio = m.CrossSection.square([g, 14.0])
    # respaldo: una tabla inclinada de grosor g
    nx, nz = math.sin(a) * g, -math.cos(a) * g          # perpendicular hacia atrás
    respaldo = _poligono(_positivo([(x0, g * 0.5), (x0 + dx, g * 0.5 + dz), (x0 + dx + nx, g * 0.5 + dz + nz), (x0 + nx, g * 0.5 + nz)]))
    # puntal: de 2/3 del respaldo hasta el final de la base
    px, pz = x0 + dx * 0.66 + nx, g * 0.5 + dz * 0.66 + nz
    puntal = _poligono(_positivo([(px, pz), (px - g * 0.9, pz - g * 0.9), (largo_base - g * 1.4, g * 0.5), (largo_base, g * 0.5)]))
    perfil = base + labio + respaldo + puntal
    return perfil.extrude(ancho)


def gancho(ancho, profundidad, alto, grosor, agujero):
    """Gancho de pared. Sale acostado de lado: así queda fuerte y sin soportes."""
    m = motor()
    g = grosor
    perfil = (m.CrossSection.square([g, alto]) + m.CrossSection.square([profundidad, g])
              + m.CrossSection.square([g, alto * 0.38]).translate([profundidad - g, 0]))
    solido = perfil.extrude(ancho)
    if agujero > 0:
        for fraccion in (0.62, 0.86):
            taladro = _cil(agujero, g + 2).rotate([0, 90, 0]).translate([-1, alto * fraccion, ancho / 2])
            solido = solido - taladro
    return solido


# ------------------------------------------------------------------
# Catálogo: nombre -> función, medidas (por defecto, mínimo, máximo) y nombres que entiende
# ------------------------------------------------------------------

def _p(defecto, minimo, maximo):
    return {"defecto": defecto, "min": minimo, "max": maximo}


CATALOGO = {
    "caja": {
        "funcion": caja, "descripcion": "Caja abierta, con tapa y postes si quieres",
        "alias": ["caja", "cajita", "contenedor", "estuche", "carcasa"],
        "ejemplo": "crea una caja de 80x50x30 con tapa",
        "medidas": {"largo": _p(60, 5, 400), "ancho": _p(40, 5, 400), "alto": _p(30, 3, 400),
                    "pared": _p(2, 0.8, 20), "redondeo": _p(3, 0, 50), "tapa": _p(0, 0, 1), "postes": _p(0, 0, 1)},
    },
    "cilindro": {
        "funcion": cilindro, "descripcion": "Cilindro macizo",
        "alias": ["cilindro", "eje", "barra", "varilla", "pasador"],
        "ejemplo": "crea un cilindro de 20 de diámetro y 50 de alto",
        "medidas": {"diametro": _p(20, 1, 400), "alto": _p(30, 0.5, 400)},
    },
    "tubo": {
        "funcion": tubo, "descripcion": "Tubo (cilindro hueco)",
        "alias": ["tubo", "buje", "casquillo", "anillo", "arandela", "aro"],
        "ejemplo": "crea un tubo de 20 de diámetro, 16 interior y 40 de alto",
        "medidas": {"diametro": _p(20, 2, 400), "interior": _p(16, 0.5, 398), "alto": _p(30, 0.5, 400)},
    },
    "esfera": {
        "funcion": esfera, "descripcion": "Esfera", "alias": ["esfera", "bola", "pelota"],
        "ejemplo": "crea una esfera de 30", "medidas": {"diametro": _p(30, 1, 400)},
    },
    "cono": {
        "funcion": cono, "descripcion": "Cono o cono cortado", "alias": ["cono", "embudo"],
        "ejemplo": "crea un cono de 30 de diámetro y 40 de alto",
        "medidas": {"diametro": _p(30, 1, 400), "punta": _p(0, 0, 400), "alto": _p(30, 0.5, 400)},
    },
    "placa": {
        "funcion": placa, "descripcion": "Placa con agujeros para atornillar",
        "alias": ["placa", "lamina", "base", "plataforma", "chapa"],
        "ejemplo": "crea una placa de 80x50 de 3 de grosor con 4 agujeros de 3",
        "medidas": {"largo": _p(80, 5, 400), "ancho": _p(50, 5, 400), "grosor": _p(3, 0.6, 50),
                    "agujeros_largo": _p(2, 0, 12), "agujeros_ancho": _p(2, 0, 12),
                    "diametro_agujero": _p(3.2, 0, 30), "margen": _p(6, 2, 100), "redondeo": _p(3, 0, 50)},
    },
    "escuadra": {
        "funcion": escuadra, "descripcion": "Escuadra en L con refuerzos y agujeros",
        "alias": ["escuadra", "angulo", "soporte en l", "soporte l", "esquinero", "bracket"],
        "ejemplo": "crea una escuadra de 40 de largo, 40 de alto y 20 de ancho",
        "medidas": {"largo": _p(40, 8, 300), "alto": _p(40, 8, 300), "ancho": _p(20, 6, 300),
                    "grosor": _p(3, 1, 20), "agujero": _p(3.2, 0, 20), "refuerzo": _p(1, 0, 1)},
    },
    "separador": {
        "funcion": separador, "descripcion": "Separador para tornillos (redondo o hexagonal)",
        "alias": ["separador", "espaciador", "standoff", "distanciador"],
        "ejemplo": "crea un separador de 10 de alto para tornillo de 3",
        "medidas": {"diametro": _p(8, 2, 100), "agujero": _p(3.2, 0.5, 98), "alto": _p(10, 0.5, 300), "hexagonal": _p(0, 0, 1)},
    },
    "engranaje": {
        "funcion": engranaje, "descripcion": "Engranaje recto de dientes de evolvente (engrana de verdad)",
        "alias": ["engranaje", "engrane", "pinon", "piñon", "rueda dentada"],
        "ejemplo": "crea un engranaje de 20 dientes módulo 2",
        "medidas": {"dientes": _p(20, 8, 200), "modulo": _p(2, 0.5, 10), "grosor": _p(6, 1, 100), "agujero": _p(5, 0, 100)},
    },
    "soporte_servo": {
        "funcion": soporte_servo, "descripcion": "Placa para montar un servo (SG90, MG90S, MG996R, DS3218)",
        "alias": ["soporte para servo", "soporte de servo", "soporte servo", "montura de servo", "montura para servo",
                  "base para servo", "placa para servo"],
        "ejemplo": "crea un soporte para servo mg996r",
        "medidas": {"modelo": {"defecto": "sg90", "opciones": sorted(SERVOS)}, "grosor": _p(3, 1.5, 12), "margen": _p(6, 3, 40)},
    },
    "vaso": {
        "funcion": vaso, "descripcion": "Vaso, portalápices o maceta (con drenaje)",
        "alias": ["vaso", "portalapices", "porta lapices", "maceta", "matera", "recipiente", "tarro"],
        "ejemplo": "crea una maceta de 90 de diámetro y 80 de alto",
        "medidas": {"diametro": _p(70, 10, 400), "alto": _p(90, 5, 400), "pared": _p(2, 0.8, 20),
                    "base": _p(2, 0.6, 20), "drenaje": _p(0, 0, 8)},
    },
    "rueda": {
        "funcion": rueda, "descripcion": "Rueda con rayos y agujero para el eje",
        "alias": ["rueda", "llanta", "polea"],
        "ejemplo": "crea una rueda de 60 de diámetro con 5 rayos",
        "medidas": {"diametro": _p(60, 10, 400), "ancho": _p(12, 2, 200), "agujero": _p(5, 0, 100), "rayos": _p(5, 0, 12)},
    },
    "soporte_celular": {
        "funcion": soporte_celular, "descripcion": "Atril para el celular (se imprime de lado, sin soportes)",
        "alias": ["soporte para celular", "soporte de celular", "soporte celular", "soporte para el celular",
                  "atril", "base para celular", "soporte para telefono", "soporte para el telefono", "soporte de telefono"],
        "ejemplo": "crea un soporte para celular",
        "medidas": {"ancho": _p(70, 20, 250), "grosor_celular": _p(12, 5, 40), "inclinacion": _p(65, 40, 85),
                    "grosor": _p(4, 2, 12), "alto": _p(95, 40, 250)},
    },
    "gancho": {
        "funcion": gancho, "descripcion": "Gancho de pared con agujeros para tornillo",
        "alias": ["gancho", "colgador", "percha", "perchero"],
        "ejemplo": "crea un gancho de 30 de profundidad",
        "medidas": {"ancho": _p(20, 8, 200), "profundidad": _p(30, 10, 200), "alto": _p(55, 20, 300),
                    "grosor": _p(4, 2, 20), "agujero": _p(4, 0, 12)},
    },
}


def _coherencia(nombre, p):
    """Arregla combinaciones imposibles antes de construir (y dice qué cambió)."""
    notas = []
    if nombre == "tubo" and p["interior"] >= p["diametro"] - 0.8:
        p["interior"] = max(0.5, p["diametro"] - 2.4)
        notas.append(f"el hueco no puede ser tan grande: lo dejé en {p['interior']:g} mm")
    if nombre == "separador" and p["agujero"] >= p["diametro"] - 1.6:
        p["diametro"] = p["agujero"] + 4.0
        notas.append(f"subí el diámetro a {p['diametro']:g} mm para que quede pared")
    if nombre in ("caja", "vaso"):
        lado = min(p["largo"], p["ancho"]) if nombre == "caja" else p["diametro"]
        if p["pared"] * 2 >= lado - 1:
            p["pared"] = max(0.8, (lado - 1) / 4)
            notas.append(f"la pared era demasiado gruesa: la dejé en {p['pared']:g} mm")
    if nombre == "caja" and p["pared"] >= p["alto"]:
        p["alto"] = p["pared"] + 5
    if nombre == "cono" and p["punta"] > p["diametro"]:
        p["punta"], p["diametro"] = p["diametro"], p["punta"]
    if nombre == "placa":
        for eje, lado in (("agujeros_largo", "largo"), ("agujeros_ancho", "ancho")):
            if p[eje] > 1 and p["margen"] * 2 >= p[lado] - p["diametro_agujero"]:
                p["margen"] = max(2.0, p[lado] / 4)
        if p["diametro_agujero"] >= min(p["largo"], p["ancho"]) - 2:
            p["diametro_agujero"] = max(0.0, min(p["largo"], p["ancho"]) / 3)
            notas.append("los agujeros eran más grandes que la placa: los achiqué")
    if nombre in ("engranaje", "rueda"):
        tope = (p["modulo"] * p["dientes"] - 2.5 * p["modulo"]) - 3 if nombre == "engranaje" else p["diametro"] * 0.5
        if p["agujero"] > tope:
            p["agujero"] = max(0.0, round(tope * 0.6, 1))
            notas.append(f"el agujero del eje era demasiado grande: lo dejé en {p['agujero']:g} mm")
    if nombre == "escuadra" and p["grosor"] * 2 > min(p["largo"], p["alto"]):
        p["grosor"] = min(p["largo"], p["alto"]) / 4
    return notas


def medidas_completas(nombre, medidas=None):
    """Las medidas de la pieza con los valores por defecto donde no dijeron nada,
    y recortadas a lo razonable. Devuelve (medidas, notas)."""
    if nombre not in CATALOGO:
        raise KeyError(nombre)
    medidas = dict(medidas or {})
    final = {}
    for clave, regla in CATALOGO[nombre]["medidas"].items():
        valor = medidas.get(clave, regla["defecto"])
        if "opciones" in regla:
            valor = str(valor).lower()
            final[clave] = valor if valor in regla["opciones"] else regla["defecto"]
            continue
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            valor = float(regla["defecto"])
        if not math.isfinite(valor):
            valor = float(regla["defecto"])
        final[clave] = max(regla["min"], min(regla["max"], valor))
    notas = _coherencia(nombre, final)
    return final, notas


def construir(nombre, medidas=None):
    """Fabrica una pieza del catálogo. Devuelve (Malla, medidas usadas, notas)."""
    final, notas = medidas_completas(nombre, medidas)
    solido = CATALOGO[nombre]["funcion"](**final)
    return a_malla(solido), final, notas


# ------------------------------------------------------------------
# Recetas: un árbol de formas y operaciones (para piezas libres)
# ------------------------------------------------------------------
# Formas:       caja {medidas:[x,y,z]}   cilindro {diametro, alto}   esfera {diametro}
#               cono {diametro, punta, alto}   prisma {lados, diametro, alto}
#               extrusion {puntos:[[x,y],...], alto}   pieza {nombre, medidas:{...}}
# Operaciones:  union / diferencia / interseccion / envolvente  {de:[...]}
# En cualquiera: mover:[x,y,z]  rotar:[rx,ry,rz] (grados)  escalar: n o [x,y,z]  espejo:"x"|"y"|"z"
# Las formas nacen CENTRADAS en X e Y y apoyadas en Z = 0.

MAX_NODOS = 150
LIMITE_MM = 1000.0


def _num(valor, defecto, minimo=0.01, maximo=LIMITE_MM):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return float(defecto)
    if not math.isfinite(v):
        return float(defecto)
    return max(minimo, min(maximo, v))


def _vec(valor, n=3, defecto=0.0, minimo=-LIMITE_MM, maximo=LIMITE_MM):
    if not isinstance(valor, (list, tuple)):
        valor = [valor] * n
    valor = list(valor)[:n] + [defecto] * (n - len(valor))
    return [_num(v, defecto, minimo, maximo) for v in valor]


def _nodo(nodo, cuenta):
    m = motor()
    if not isinstance(nodo, dict):
        raise ValueError("Cada parte de la receta debe ser un objeto con «tipo».")
    cuenta[0] += 1
    if cuenta[0] > MAX_NODOS:
        raise ValueError("La receta es demasiado grande.")
    tipo = str(nodo.get("tipo", "")).lower().strip()
    if tipo == "caja":
        x, y, z = _vec(nodo.get("medidas", [10, 10, 10]), 3, 10, 0.01)
        s = m.Manifold.cube([x, y, z]).translate([-x / 2, -y / 2, 0])
    elif tipo == "cilindro":
        s = _cil(_num(nodo.get("diametro"), 10), _num(nodo.get("alto"), 10))
    elif tipo == "esfera":
        d = _num(nodo.get("diametro"), 10)
        s = m.Manifold.sphere(d / 2).translate([0, 0, d / 2])
    elif tipo == "cono":
        s = m.Manifold.cylinder(_num(nodo.get("alto"), 10), _num(nodo.get("diametro"), 10) / 2,
                                _num(nodo.get("punta", 0), 0, 0.0) / 2)
    elif tipo == "prisma":
        lados = int(_num(nodo.get("lados"), 6, 3, 64))
        d = _num(nodo.get("diametro"), 10)
        s = m.Manifold.cylinder(_num(nodo.get("alto"), 10), d / 2, d / 2, lados)
    elif tipo == "extrusion":
        puntos = nodo.get("puntos") or []
        if not isinstance(puntos, list) or not 3 <= len(puntos) <= 400:
            raise ValueError("Una extrusión necesita entre 3 y 400 puntos.")
        pts = [tuple(_vec(p, 2)) for p in puntos]
        s = _poligono(_positivo(pts)).extrude(_num(nodo.get("alto"), 5))
    elif tipo == "pieza":
        nombre = str(nodo.get("nombre", "")).lower()
        if nombre not in CATALOGO:
            raise ValueError(f"No conozco la pieza «{nombre}».")
        final, _ = medidas_completas(nombre, nodo.get("medidas") if isinstance(nodo.get("medidas"), dict) else {})
        s = CATALOGO[nombre]["funcion"](**final)
    elif tipo in ("union", "diferencia", "interseccion", "envolvente"):
        partes = nodo.get("de")
        if not isinstance(partes, list) or not partes:
            raise ValueError(f"«{tipo}» necesita una lista «de» con al menos una parte.")
        solidos = [_nodo(p, cuenta) for p in partes]
        s = solidos[0]
        if tipo == "envolvente":
            s = m.Manifold.batch_hull(solidos)
        else:
            for otro in solidos[1:]:
                s = s + otro if tipo == "union" else (s - otro if tipo == "diferencia" else s ^ otro)
    else:
        raise ValueError(f"No conozco la forma «{tipo}».")
    # transformaciones, siempre en este orden: escalar, espejo, rotar, mover
    if "escalar" in nodo:
        s = s.scale(_vec(nodo["escalar"], 3, 1.0, 0.01, 100.0))
    if nodo.get("espejo") in ("x", "y", "z"):
        s = s.mirror({"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[nodo["espejo"]])
    if "rotar" in nodo:
        s = s.rotate(_vec(nodo["rotar"], 3, 0.0, -360.0, 360.0))
    if "mover" in nodo:
        s = s.translate(_vec(nodo["mover"], 3))
    return s


def desde_receta(receta):
    """Árbol de formas -> Malla. Lanza ValueError con un mensaje claro si algo no cuadra."""
    return a_malla(_nodo(receta, [0]))
