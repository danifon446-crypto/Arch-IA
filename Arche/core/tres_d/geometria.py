"""
geometria.py
------------
Ubicacion: Arche/core/tres_d/geometria.py

Lo básico para trabajar con modelos 3D sin programas externos (solo numpy):

  - Malla: los puntos (vértices) y los triángulos (caras) de un modelo.
  - leer_modelo / escribir_stl: abre STL (binario o de texto) y OBJ; guarda STL.
  - analizar: medidas, volumen, peso de filamento, si está cerrado, cuánto
    voladizo tiene (lo que necesitaría soportes) y si cabe en la impresora.
  - mejor_orientacion: prueba las 6 formas de acostar la pieza y elige la que
    necesita menos soportes.
  - escalar, rotar, espejo, apoyar: transformaciones.

Todas las medidas van en milímetros, con Z hacia arriba (como en los slicers).
"""

import math
import os
import struct

import numpy as np

# ---- ajustes de impresión (se cambian con «mi impresora es de 220x220x250», etc.) ----
CAMA = (220.0, 220.0, 250.0)          # tamaño de impresión X, Y, Z en mm (Ender 3 y parecidas)
DENSIDAD = {"pla": 1.24, "petg": 1.27, "abs": 1.04, "tpu": 1.21}     # g/cm3
DIAMETRO_FILAMENTO = 1.75             # mm
GROSOR_PARED = 1.2                    # mm de pared maciza (3 perímetros de 0,4)
RELLENO = 0.20                        # 20 % de relleno
ANGULO_VOLADIZO = 45.0                # más inclinado que esto necesita soporte
VELOCIDAD_CM3_H = 12.0                # cm3 de plástico por hora (impresora común, capa 0,2)


class Malla:
    """Un modelo 3D: vertices (n,3) en mm y caras (m,3) con índices de vértices."""

    def __init__(self, vertices, caras):
        self.vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
        self.caras = np.asarray(caras, dtype=np.int64).reshape(-1, 3)

    def copia(self):
        return Malla(self.vertices.copy(), self.caras.copy())

    # --- medidas ---
    def limites(self):
        if len(self.vertices) == 0:
            return np.zeros(3), np.zeros(3)
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def dimensiones(self):
        a, b = self.limites()
        return b - a

    def _triangulos(self):
        return self.vertices[self.caras]                 # (m,3,3)

    def normales_y_areas(self):
        t = self._triangulos()
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        doble = np.linalg.norm(n, axis=1)
        areas = doble / 2.0
        with np.errstate(invalid="ignore", divide="ignore"):
            normales = np.where(doble[:, None] > 1e-12, n / doble[:, None], 0.0)
        return normales, areas

    def volumen(self):
        """Volumen en mm3 (suma de tetraedros con signo; vale si la malla está cerrada)."""
        t = self._triangulos()
        return float(abs(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0))

    def area(self):
        return float(self.normales_y_areas()[1].sum())

    def cerrada(self):
        """True si cada arista la comparten exactamente 2 caras (sin huecos: se puede imprimir)."""
        if len(self.caras) == 0:
            return False
        c = self.caras
        aristas = np.concatenate([c[:, [0, 1]], c[:, [1, 2]], c[:, [2, 0]]])
        aristas.sort(axis=1)
        _, cuenta = np.unique(aristas, axis=0, return_counts=True)
        return bool(np.all(cuenta == 2))


# ------------------------------------------------------------------
# Leer y guardar
# ------------------------------------------------------------------

def _soldar(triangulos):
    """(m,3,3) de triángulos sueltos -> Malla con los vértices repetidos unidos."""
    puntos = np.asarray(triangulos, dtype=np.float64).reshape(-1, 3)
    if len(puntos) == 0:
        return Malla(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    claves = np.round(puntos, 5)
    unicos, inverso = np.unique(claves, axis=0, return_inverse=True)
    caras = np.asarray(inverso).reshape(-1, 3)
    # fuera triángulos sin área (dos esquinas en el mismo punto)
    buenas = (caras[:, 0] != caras[:, 1]) & (caras[:, 1] != caras[:, 2]) & (caras[:, 0] != caras[:, 2])
    return Malla(unicos, caras[buenas])


def _leer_stl(datos):
    # binario: 80 de cabecera + 4 de cantidad + 50 por triángulo
    if len(datos) >= 84:
        n = struct.unpack_from("<I", datos, 80)[0]
        if len(datos) == 84 + 50 * n and n > 0:
            tipo = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            return _soldar(np.frombuffer(datos, dtype=tipo, count=n, offset=84)["v"])
    # de texto
    texto = datos.decode("utf-8", errors="replace")
    puntos = []
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) == 4 and partes[0].lower() == "vertex":
            try:
                puntos.append((float(partes[1]), float(partes[2]), float(partes[3])))
            except ValueError:
                raise ValueError("El STL tiene un número que no se puede leer.")
    if not puntos or len(puntos) % 3:
        raise ValueError("No parece un STL válido (no encontré triángulos completos).")
    return _soldar(np.array(puntos).reshape(-1, 3, 3))


def _leer_obj(datos):
    vertices, caras = [], []
    for linea in datos.decode("utf-8", errors="replace").splitlines():
        partes = linea.split()
        if not partes:
            continue
        if partes[0] == "v" and len(partes) >= 4:
            vertices.append((float(partes[1]), float(partes[2]), float(partes[3])))
        elif partes[0] == "f" and len(partes) >= 4:
            indices = []
            for p in partes[1:]:
                i = int(p.split("/")[0])
                indices.append(i - 1 if i > 0 else len(vertices) + i)
            for k in range(1, len(indices) - 1):            # un polígono se parte en abanico
                caras.append((indices[0], indices[k], indices[k + 1]))
    if not vertices or not caras:
        raise ValueError("No parece un OBJ válido (sin vértices o sin caras).")
    v = np.array(vertices)
    c = np.array(caras)
    if c.min() < 0 or c.max() >= len(v):
        raise ValueError("El OBJ nombra vértices que no existen.")
    return _soldar(v[c])


MAX_BYTES = 80 * 1024 * 1024          # no abrir archivos gigantes por error


def leer_modelo(ruta):
    """Abre un .stl o .obj y devuelve una Malla."""
    if os.path.getsize(ruta) > MAX_BYTES:
        raise ValueError("Ese archivo pesa más de 80 MB; es demasiado para abrirlo aquí.")
    with open(ruta, "rb") as f:
        datos = f.read()
    return leer_bytes(datos, os.path.splitext(ruta)[1].lower())


def leer_bytes(datos, extension=".stl"):
    if extension == ".obj":
        malla = _leer_obj(datos)
    elif extension == ".stl":
        malla = _leer_stl(datos)
    else:
        raise ValueError("Solo sé abrir archivos .stl y .obj.")
    if len(malla.caras) == 0:
        raise ValueError("El modelo no tiene triángulos.")
    return malla


def escribir_stl(malla, ruta, nombre="Arche"):
    """Guarda la malla como STL binario (el formato que abren todos los slicers)."""
    t = malla.vertices[malla.caras].astype("<f4")
    normales, _ = malla.normales_y_areas()
    registro = np.zeros(len(t), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    registro["n"] = normales.astype("<f4")
    registro["v"] = t
    cabecera = (f"Arche 3D - {nombre}".encode("ascii", "replace")[:80]).ljust(80, b" ")
    temporal = ruta + ".tmp"
    with open(temporal, "wb") as f:
        f.write(cabecera)
        f.write(struct.pack("<I", len(t)))
        f.write(registro.tobytes())
    os.replace(temporal, ruta)


# ------------------------------------------------------------------
# Transformaciones (devuelven una malla nueva)
# ------------------------------------------------------------------

def apoyar(malla):
    """La deja apoyada en la cama (Z mínima = 0) y centrada en X e Y."""
    m = malla.copia()
    a, b = m.limites()
    m.vertices -= np.array([(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, a[2]])
    return m


def escalar(malla, factor):
    """factor: un número (todo igual) o (fx, fy, fz)."""
    f = np.array([factor] * 3 if np.isscalar(factor) else factor, dtype=np.float64)
    if np.any(f <= 0) or np.any(~np.isfinite(f)):
        raise ValueError("La escala debe ser mayor que cero.")
    m = malla.copia()
    m.vertices *= f
    return apoyar(m)


def _matriz_rotacion(eje, grados):
    a = math.radians(grados)
    c, s = math.cos(a), math.sin(a)
    if eje == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if eje == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    if eje == "z":
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    raise ValueError("El eje debe ser x, y o z.")


def rotar(malla, eje, grados):
    m = malla.copia()
    m.vertices = m.vertices @ _matriz_rotacion(eje, grados).T
    return apoyar(m)


def espejo(malla, eje):
    """Hace la pieza espejo (la pata izquierda a partir de la derecha, por ejemplo)."""
    i = {"x": 0, "y": 1, "z": 2}.get(eje)
    if i is None:
        raise ValueError("El eje debe ser x, y o z.")
    m = malla.copia()
    m.vertices[:, i] *= -1
    m.caras = m.caras[:, ::-1].copy()        # al reflejar hay que voltear las caras para que sigan mirando afuera
    return apoyar(m)


# ------------------------------------------------------------------
# Análisis para imprimir
# ------------------------------------------------------------------

def _voladizo(malla, angulo=ANGULO_VOLADIZO):
    """(área que necesita soporte, área apoyada en la cama) en mm2, con la pieza como está."""
    normales, areas = malla.normales_y_areas()
    if len(areas) == 0:
        return 0.0, 0.0
    z_min = malla.vertices[:, 2].min()
    z_caras = malla.vertices[malla.caras][:, :, 2]
    en_cama = (z_caras.max(axis=1) - z_min) < 0.05
    hacia_abajo = normales[:, 2] < -math.cos(math.radians(angulo))
    return float(areas[hacia_abajo & ~en_cama].sum()), float(areas[en_cama & (normales[:, 2] < -0.99)].sum())


_GIROS = [("como está", None, 0), ("acostada sobre un lado (giro de 90° en X)", "x", 90),
          ("acostada sobre el otro lado (giro de -90° en X)", "x", -90),
          ("acostada (giro de 90° en Y)", "y", 90), ("acostada (giro de -90° en Y)", "y", -90),
          ("boca abajo (giro de 180° en X)", "x", 180)]


def mejor_orientacion(malla):
    """Prueba las 6 formas de apoyar la pieza. Devuelve una lista ordenada (la
    mejor primero) de dicts: nombre, eje, grados, soporte_mm2, base_mm2, alto."""
    opciones = []
    for nombre, eje, grados in _GIROS:
        m = apoyar(malla) if eje is None else rotar(malla, eje, grados)
        soporte, base = _voladizo(m)
        opciones.append({"nombre": nombre, "eje": eje, "grados": grados, "soporte_mm2": soporte,
                         "base_mm2": base, "alto": float(m.dimensiones()[2])})
    area = max(malla.area(), 1e-9)
    # menos soporte es lo principal; a igual soporte, más base (se pega mejor) y menos altura (más rápida)
    opciones.sort(key=lambda o: (round(o["soporte_mm2"] / area, 3), -round(o["base_mm2"] / area, 3), o["alto"]))
    return opciones


def analizar(malla, material="pla", cama=None, relleno=RELLENO):
    """Todo lo que conviene saber antes de imprimir. Devuelve un dict."""
    cama = cama or CAMA
    dims = malla.dimensiones()
    vol_mm3 = malla.volumen()
    area = malla.area()
    cerrada = malla.cerrada()
    soporte, base = _voladizo(malla)

    # plástico: una cáscara maciza + el interior con relleno
    cascara = min(vol_mm3, area * GROSOR_PARED)
    plastico_mm3 = cascara + max(0.0, vol_mm3 - cascara) * relleno
    densidad = DENSIDAD.get(material, DENSIDAD["pla"])
    gramos = plastico_mm3 / 1000.0 * densidad
    metros = plastico_mm3 / (math.pi * (DIAMETRO_FILAMENTO / 2.0) ** 2) / 1000.0
    horas = plastico_mm3 / 1000.0 / VELOCIDAD_CM3_H

    cabe = bool(np.all(np.sort(dims[:2]) <= np.sort(np.array(cama[:2])) + 1e-6) and dims[2] <= cama[2] + 1e-6)
    opciones = mejor_orientacion(malla)
    mejor = opciones[0]
    conviene_girar = mejor["eje"] is not None and mejor["soporte_mm2"] < soporte * 0.7 - 1.0

    avisos = []
    if not cerrada:
        avisos.append("La malla tiene huecos o caras sueltas: el slicer puede fallar. Conviene repararla.")
    if not cabe:
        avisos.append(f"No cabe en la impresora ({cama[0]:.0f}×{cama[1]:.0f}×{cama[2]:.0f} mm): "
                      "hay que escalarla, girarla o partirla.")
    if dims.min() < 0.8:
        avisos.append("Tiene un lado de menos de 0,8 mm: puede no salir con boquilla de 0,4.")
    porcentaje = soporte / area * 100 if area else 0.0
    if porcentaje > 3:
        avisos.append(f"El {porcentaje:.0f} % de la superficie queda en voladizo: necesita soportes.")
    if conviene_girar:
        avisos.append(f"Imprímela {mejor['nombre']}: necesita mucho menos soporte.")
    if base < 30 and dims[2] > 20:
        avisos.append("Se apoya en muy poca superficie: usa borde (brim) para que no se despegue.")

    return {
        "dimensiones": [float(d) for d in dims], "volumen_cm3": vol_mm3 / 1000.0, "area_cm2": area / 100.0,
        "triangulos": int(len(malla.caras)), "cerrada": cerrada, "cabe": cabe,
        "material": material if material in DENSIDAD else "pla", "relleno": relleno,
        "gramos": gramos, "metros_filamento": metros, "horas": horas,
        "soporte_pct": porcentaje, "base_cm2": base / 100.0,
        "mejor_orientacion": mejor, "conviene_girar": conviene_girar, "avisos": avisos,
    }


def tiempo_legible(horas):
    minutos = int(round(horas * 60))
    if minutos < 60:
        return f"{max(1, minutos)} min"
    return f"{minutos // 60} h {minutos % 60:02d} min"


def resumen(a):
    """El análisis en frases, para decirlo en el chat."""
    d = a["dimensiones"]
    lineas = [f"Mide {d[0]:.1f} × {d[1]:.1f} × {d[2]:.1f} mm ({a['volumen_cm3']:.1f} cm³, {a['triangulos']} triángulos).",
              f"En {a['material'].upper()} con {a['relleno'] * 100:.0f} % de relleno: unos {a['gramos']:.0f} g "
              f"({a['metros_filamento']:.1f} m de filamento), más o menos {tiempo_legible(a['horas'])} de impresión."]
    if not a["avisos"]:
        lineas.append("Está lista para imprimir: cerrada, cabe en la cama y casi no necesita soportes.")
    lineas.extend(a["avisos"])
    return lineas
