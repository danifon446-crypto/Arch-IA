"""
fondos.py
---------
Ubicacion: Arche/core/interfaz/fondos.py

Fondos para la ventana: imagenes (png, jpg, webp, bmp), GIF animados y videos
(mp4, avi, mov, mkv, webm). Se guardan en Database/fondos; basta con copiar
ahi los archivos que quieras y elegirlos en AJUSTES o con "fondo siguiente".

Imagenes y GIF usan Pillow. Los videos necesitan OpenCV (pip install
opencv-python); si no esta, se avisa y se sigue sin video.
"""

import base64
import os
import time

from core.rutas import DATABASE

CARPETA = os.path.join(DATABASE, "fondos")
IMAGENES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
ANIMADOS = (".gif",)
VIDEOS = (".mp4", ".avi", ".mov", ".mkv", ".webm")

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:
    Image = ImageOps = None
try:
    from PIL import ImageTk
except Exception:
    ImageTk = None
try:
    import cv2
except Exception:
    cv2 = None


def soporte():
    """(imagenes, video) disponibles."""
    return Image is not None, cv2 is not None


def listar():
    try:
        os.makedirs(CARPETA, exist_ok=True)
        return sorted(f for f in os.listdir(CARPETA) if f.lower().endswith(IMAGENES + ANIMADOS + VIDEOS))
    except Exception:
        return []


def ruta(nombre):
    return os.path.join(CARPETA, nombre) if nombre else ""


def siguiente(actual, paso=1):
    """Nombre del siguiente fondo de la lista ('' = ninguno, tambien cuenta como opcion)."""
    opciones = [""] + listar()
    i = opciones.index(actual) if actual in opciones else 0
    return opciones[(i + paso) % len(opciones)]


def _a_tk(tk, imagen):
    """PIL.Image -> imagen de Tk (con ImageTk si existe, si no con PPM)."""
    if ImageTk is not None:
        try:
            return ImageTk.PhotoImage(imagen)
        except Exception:
            pass
    ppm = b"P6\n%d %d\n255\n" % imagen.size + imagen.convert("RGB").tobytes()
    return tk.PhotoImage(data=ppm, format="PPM")


class Fondo:
    """Un fondo ya cargado y ajustado al tamano de la ventana."""

    def __init__(self, tk, nombre, ancho, alto, oscuridad, color_base):
        self.tk, self.nombre = tk, nombre
        self.ancho, self.alto = max(2, int(ancho)), max(2, int(alto))
        self.oscuridad = max(0, min(90, int(oscuridad))) / 100.0
        self.color_base = color_base
        self.error = ""
        self.animado = False
        self._frames = []          # GIF: [(PIL.Image original, duracion_seg)]
        self._cache = {}           # indice -> imagen de Tk
        self._video = None
        self._fps = 15.0
        self._t0 = time.time()
        self._ultimo = None
        self._foto = None
        self.desenfoque = 0         # 0-20 (necesita Pillow)
        self.quieto = False         # True: el video o GIF se queda en el primer cuadro (ahorra recursos)
        self._abrir()

    # ---- carga ----
    def _abrir(self):
        ruta_ = ruta(self.nombre)
        ext = os.path.splitext(self.nombre)[1].lower()
        if Image is None:
            self.error = "Falta Pillow (pip install pillow)."
            return
        if not os.path.exists(ruta_):
            self.error = "No encuentro ese fondo en Database/fondos."
            return
        try:
            if ext in VIDEOS:
                if cv2 is None:
                    self.error = "Para videos instala OpenCV: pip install opencv-python"
                    return
                self._video = cv2.VideoCapture(ruta_)
                if not self._video.isOpened():
                    self.error = "No pude abrir ese video."
                    return
                self._fps = min(20.0, self._video.get(cv2.CAP_PROP_FPS) or 15.0)
                self.animado = True
            elif ext in ANIMADOS:
                im = Image.open(ruta_)
                n = getattr(im, "n_frames", 1)
                paso = max(1, n // 90)                      # como mucho ~90 cuadros
                for i in range(0, n, paso):
                    im.seek(i)
                    self._frames.append((im.convert("RGB").copy(), max(0.04, im.info.get("duration", 80) / 1000.0 * paso)))
                self.animado = len(self._frames) > 1
            else:
                self._frames = [(Image.open(ruta_).convert("RGB"), 1.0)]
        except Exception as e:
            self.error = f"No pude cargar el fondo ({e})."

    # ---- cuadros ----
    def _ajustar(self, im):
        im = ImageOps.fit(im.convert("RGB"), (self.ancho, self.alto), method=Image.BILINEAR)
        if self.desenfoque > 0:
            im = im.filter(ImageFilter.GaussianBlur(self.desenfoque))
        if self.oscuridad > 0:
            capa = Image.new("RGB", im.size, self.color_base)
            im = Image.blend(im, capa, self.oscuridad)
        return im

    def cuadro(self):
        """Imagen de Tk para ahora mismo (o None si no hay cambio / no hay fondo)."""
        if self.error:
            return None
        try:
            if self._video is not None:
                if self.quieto and self._foto is not None:
                    return None
                if time.time() - self._t0 < 1.0 / self._fps and self._foto is not None:
                    return None
                self._t0 = time.time()
                ok, bgr = self._video.read()
                if not ok:
                    self._video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, bgr = self._video.read()
                    if not ok:
                        return None
                im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                self._foto = _a_tk(self.tk, self._ajustar(im))
                return self._foto
            if not self._frames:
                return None
            if not self.animado or self.quieto:
                if self._foto is None:
                    self._foto = _a_tk(self.tk, self._ajustar(self._frames[0][0]))
                    return self._foto
                return None
            total = sum(d for _, d in self._frames)
            t = (time.time() - self._t0) % total
            acum, idx = 0.0, 0
            for i, (_, d) in enumerate(self._frames):
                acum += d
                if t < acum:
                    idx = i
                    break
            if idx == self._ultimo:
                return None
            self._ultimo = idx
            if idx not in self._cache:
                if len(self._cache) > 40:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[idx] = _a_tk(self.tk, self._ajustar(self._frames[idx][0]))
            self._foto = self._cache[idx]
            return self._foto
        except Exception as e:
            self.error = f"Fallo el fondo ({e})."
            return None

    def cerrar(self):
        try:
            if self._video is not None:
                self._video.release()
        except Exception:
            pass
        self._frames, self._cache, self._foto = [], {}, None
