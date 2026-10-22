"""Vision del banco de pruebas del perro robotico.

Entrada: un cuadro BGR (numpy) que manda el celular.
Salida: UN evento por cuadro:
    "movimiento"  cambio brusco entre cuadros (tiene prioridad: es lo que asusta)
    "cerca"       algo tapa/ocupa mucho de la escena
    "cara"        cara frontal (Haar cascade de OpenCV)
    "pelota"      mancha redonda del color elegido
    "nada"        ninguna de las anteriores

Todo es heuristica clasica (sin redes neuronales): rapida y facil de calibrar
desde el panel. "Cerca" se estima con UNA sola camara, asi que es aproximado:
cuenta como cerca una cara/pelota muy grande, o que la textura del centro del
cuadro se desplome respecto a su valor normal (algo tapando el lente).

Necesita: pip install opencv-python numpy
"""

import cv2
import numpy as np

ANCHO_ANALISIS = 320   # los cuadros se reducen a este ancho para analizarlos rapido

# rangos HSV de OpenCV (H 0-179). La roja necesita dos porque el tono "da la vuelta".
PRESETS_COLOR = {
    "amarilla (tenis)": [((22, 90, 90), (42, 255, 255))],
    "naranja": [((4, 120, 120), (20, 255, 255))],
    "verde": [((40, 80, 60), (85, 255, 255))],
    "azul": [((95, 100, 60), (125, 255, 255))],
    "roja": [((0, 120, 90), (8, 255, 255)), ((172, 120, 90), (179, 255, 255))],
}

CONFIG_INICIAL = {
    "color_pelota": "amarilla (tenis)",
    "umbral_movimiento": 0.10,   # fraccion de pixeles que cambian entre cuadros para contar como brusco
    "cerca_por_tamano": 0.12,    # una cara que ocupa esta fraccion del cuadro = cerca
    "cerca_pelota": 0.06,        # idem para la pelota
    "cerca_por_textura": 0.20,   # textura central por debajo de esta fraccion de su base = cerca
    "area_min_pelota": 0.004,    # mancha minima (fraccion del cuadro) para considerarla pelota
}

_KERNEL = np.ones((5, 5), np.uint8)


class Detector:
    def __init__(self):
        ruta = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.cascada = cv2.CascadeClassifier(ruta)
        if self.cascada.empty():
            raise RuntimeError("No pude cargar el detector de caras de OpenCV (" + ruta + ").")
        self.config = dict(CONFIG_INICIAL)
        self.recalibrar()

    def recalibrar(self):
        """Olvida el cuadro anterior y la textura 'normal' (usalo si cambias el celular de lugar)."""
        self._prev = None
        self._base = None
        self._n = 0

    # ------------------------------------------------------------ piezas
    def _movimiento(self, gris):
        h, w = gris.shape
        g = cv2.resize(gris, (160, max(1, int(160 * h / w))), interpolation=cv2.INTER_AREA)
        g = cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)
        g -= g.mean()                      # ignora cambios de exposicion globales
        if self._prev is None or self._prev.shape != g.shape:
            self._prev = g
            return 0.0
        d = np.abs(g - self._prev)
        self._prev = g
        return float((d > 25).mean())

    def _cara(self, gris, w, h):
        eq = cv2.equalizeHist(gris)
        caras = self.cascada.detectMultiScale(eq, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
        if len(caras) == 0:
            return None
        x, y, fw, fh = max(caras, key=lambda c: c[2] * c[3])
        return {
            "x": float((x + fw / 2.0 - w / 2.0) / (w / 2.0)),   # -1 izquierda ... +1 derecha
            "area": float(fw * fh) / float(w * h),
            "caja": (x / w, y / h, (x + fw) / w, (y + fh) / h),
        }

    def _pelota(self, chico, w, h):
        rangos = PRESETS_COLOR.get(self.config["color_pelota"], PRESETS_COLOR["amarilla (tenis)"])
        hsv = cv2.cvtColor(cv2.GaussianBlur(chico, (7, 7), 0), cv2.COLOR_BGR2HSV)
        mascara = None
        for lo, hi in rangos:
            m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            mascara = m if mascara is None else cv2.bitwise_or(mascara, m)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, _KERNEL)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, _KERNEL)
        contornos = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        mejor = None
        minimo = self.config["area_min_pelota"] * w * h
        for c in contornos:
            area = cv2.contourArea(c)
            if area < minimo:
                continue
            perimetro = cv2.arcLength(c, True)
            if perimetro == 0:
                continue
            circularidad = 4.0 * np.pi * area / (perimetro * perimetro)
            if circularidad < 0.6:          # descarta manchas alargadas o irregulares
                continue
            if mejor is None or area > mejor[0]:
                mejor = (area, c)
        if mejor is None:
            return None
        x, y, bw, bh = cv2.boundingRect(mejor[1])
        return {
            "x": float((x + bw / 2.0 - w / 2.0) / (w / 2.0)),
            "area": float(mejor[0]) / float(w * h),
            "caja": (x / w, y / h, (x + bw) / w, (y + bh) / h),
        }

    def _textura(self, gris):
        h, w = gris.shape
        roi = gris[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
        v = float(cv2.Laplacian(roi, cv2.CV_64F).var())
        if self._base is None:
            self._base = v
            self._n = 1
            return v, 1.0
        return v, v / max(self._base, 1e-6)

    def _actualizar_base(self, v, congelar):
        if congelar or self._base is None:
            return
        alfa = 0.2 if self._n < 15 else 0.02     # aprende rapido al inicio y luego muy despacio
        self._base = (1 - alfa) * self._base + alfa * v
        self._n += 1

    # ------------------------------------------------------------- principal
    def analizar(self, frame):
        cfg = self.config
        h0, w0 = frame.shape[:2]
        escala = ANCHO_ANALISIS / float(w0)
        chico = cv2.resize(frame, (ANCHO_ANALISIS, max(1, int(h0 * escala))), interpolation=cv2.INTER_AREA)
        h, w = chico.shape[:2]
        gris = cv2.cvtColor(chico, cv2.COLOR_BGR2GRAY)

        frac = self._movimiento(gris)
        cara = self._cara(gris, w, h)
        pelota = self._pelota(chico, w, h)
        v, ratio = self._textura(gris)

        brusco = frac >= cfg["umbral_movimiento"]
        cerca_por = ""
        if cara and cara["area"] >= cfg["cerca_por_tamano"]:
            cerca_por = "cara muy grande"
        elif pelota and pelota["area"] >= cfg["cerca_pelota"]:
            cerca_por = "pelota muy grande"
        elif self._n >= 15 and self._base >= 20 and ratio < cfg["cerca_por_textura"]:
            cerca_por = "centro tapado"

        if brusco:
            evento = "movimiento"
        elif cerca_por:
            evento = "cerca"
        elif cara:
            evento = "cara"
        elif pelota:
            evento = "pelota"
        else:
            evento = "nada"

        self._actualizar_base(v, congelar=bool(cerca_por) or brusco)

        cajas = []
        if cara:
            cajas.append(("cara",) + tuple(cara["caja"]))
        if pelota:
            cajas.append(("pelota",) + tuple(pelota["caja"]))
        return {
            "evento": evento,
            "movimiento": round(frac, 3),
            "textura": round(float(ratio), 2),
            "cerca_por": cerca_por,
            "cara": {"x": round(cara["x"], 2), "area": round(cara["area"], 3)} if cara else None,
            "pelota": {"x": round(pelota["x"], 2), "area": round(pelota["area"], 3)} if pelota else None,
            "cajas": cajas,
        }


_COLORES = {"cara": (80, 220, 80), "pelota": (0, 140, 255)}


def anotar(frame, res, etiqueta=None):
    """Dibuja las cajas y el evento sobre el cuadro (para el video del panel)."""
    h, w = frame.shape[:2]
    for tipo, x0, y0, x1, y1 in res["cajas"]:
        p0, p1 = (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h))
        cv2.rectangle(frame, p0, p1, _COLORES.get(tipo, (255, 255, 255)), 2)
        cv2.putText(frame, tipo, (p0[0], max(14, p0[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    _COLORES.get(tipo, (255, 255, 255)), 1, cv2.LINE_AA)
    texto = etiqueta or res["evento"]
    cv2.rectangle(frame, (0, 0), (10 + 11 * len(texto), 26), (0, 0, 0), -1)
    cv2.putText(frame, texto, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return frame