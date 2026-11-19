"""
avatar.py
---------
Ubicacion: Arche/core/nucleo/avatar.py

PRESENCIA VISUAL: Arché vive en tu escritorio, en una esquina, siempre encima, aunque no
tengas la interfaz abierta. Se ve SOLO la figura: sin ventana, sin cuadro y sin fondo.

Cómo lo hace:
  * La figura la dibuja avatar_dibujo.py, que es el mismo dibujo de tu interfaz web
    (dibujarOrbe de app.js) pasado a Python: misma forma, colores, halo, chispas y tiempos.
  * Lee en cada cuadro los MISMOS ajustes de la interfaz (forma, color, tamaño, velocidad,
    brillo, chispas, acentos) y el tema. Cambias algo en la interfaz -> el avatar cambia solo.
  * La muestra en una "ventana por capas" de Windows (UpdateLayeredWindow): transparencia
    real píxel por píxel. Donde no hay figura no hay nada: los clics pasan a lo de atrás.
    (No usa pywebview: su transparencia no funciona en todos los PC.)

Lo que muestra es lo mismo que la interfaz: reposo, escuchando, pensando, hablando.
Cuando el equipo o el Depredador trabajan aparece «pensando», y cuando llevas más de
30 minutos sin usar el PC (o es de madrugada) se atenúa.
Los avisos de Arché salen un momento en un globo encima de la figura.
  clic        -> abre la interfaz (o la burbuja para escribirle, con arche_fondo.pyw)
  arrastrar   -> la mueves (recuerda dónde la dejaste)

Comandos: muestra el avatar · esconde el avatar · avatar grande · avatar pequeño
          avatar sin halo / avatar con halo · estado del avatar
"""

import ctypes
import os
import time

from core.nucleo import comun

ARCH = comun.ruta("avatar.json")
ARCH_POSICION = comun.ruta("avatar_posicion.json")
CUADRO_MS = 50

_control = {"hilo": None, "parar": False, "orden": None, "modo": None, "error": ""}


def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("tamano", 200)
    e.setdefault("halo", "auto")       # "auto" | True | False
    return e


def _guardar(e):
    comun.guardar(ARCH, e)


def _posicion():
    p = comun.cargar(ARCH_POSICION, {})
    return p.get("x"), p.get("y")


# ------------------------------------------------------------------
# Qué mostrar (lo mismo que la interfaz + lo que hace el núcleo)
# ------------------------------------------------------------------

def estado_actual(base=None, ocupado=None, inactivo=None, hora=None):
    """reposo | escuchando | pensando | hablando | desconectado (atenuada)."""
    if base is None:
        try:
            from core.interfaz import en_vivo
            base = en_vivo.estado_visual()
        except Exception:
            base = "reposo"
    if base in ("hablando", "escuchando", "pensando"):
        if base == "escuchando" and ocupado:
            return "pensando"
        return base
    if ocupado is None:
        ocupado = False
        try:
            from core.nucleo import equipo, depredador
            ocupado = bool(equipo._mision_en_curso["id"]) or depredador._lock_caza.locked()
        except Exception:
            pass
    if ocupado:
        return "pensando"
    if inactivo is None:
        try:
            from core.nucleo import ritmo
            inactivo = ritmo.minutos_inactivo()
        except Exception:
            inactivo = 0
    hora = comun.ahora().hour if hora is None else hora
    if inactivo > 30 or 1 <= hora < 5:
        return "desconectado"
    return "reposo"


def globo_actual():
    g = comun.ultimo_globo()
    edad = time.time() - float(g.get("cuando", 0) or 0)
    texto = (g.get("texto") or "").split("\n")[0]
    return {"texto": texto[:180] + ("…" if len(texto) > 180 else ""), "nivel": g.get("nivel", "info"),
            "edad": round(edad, 1)}


_CLAVES = ("estilo_voz", "orbe_velocidad", "efecto_brillo", "orbe_tamano", "orbe_color", "efecto_particulas",
           "web_acento", "web_acento_2", "reducir_movimiento", "tema", "alto_contraste")
_sincro = {"mtime": None, "revisado": 0.0}


def ajustes_de_la_interfaz():
    """(ajustes, colores) tal como los usa la interfaz AHORA. Si el archivo de ajustes cambió
    (aunque lo haya cambiado otro proceso), se vuelve a leer."""
    from core.interfaz import ajustes, tema
    if time.time() - _sincro["revisado"] > 1:
        _sincro["revisado"] = time.time()
        try:
            m = os.path.getmtime(ajustes._ARCHIVO)
        except OSError:
            m = None
        if m != _sincro["mtime"]:
            if _sincro["mtime"] is not None:
                with ajustes._lock:
                    ajustes._datos = None
            _sincro["mtime"] = m
    datos = {}
    for k in _CLAVES:
        try:
            datos[k] = ajustes.obtener(k)
        except Exception:
            datos[k] = None
    nombre = tema.resolver(datos.get("tema") or "") or tema.actual() or "arche"
    colores = dict(tema.colores_de(nombre))
    if datos.get("alto_contraste"):
        try:
            colores = tema._contraste(colores)
        except Exception:
            pass
    colores.setdefault("alerta", colores.get("rojo_claro"))
    return datos, colores


def halo_visible(ajustes, colores):
    """En la interfaz el halo se ve sobre un fondo oscuro. Si tu color es muy oscuro (negro), allá el halo
    casi no se nota, pero sobre el escritorio quedaría como una mancha gris: en «auto» no se dibuja."""
    preferencia = _estado()["halo"]
    if preferencia in (True, False):
        return preferencia
    color = (ajustes.get("orbe_color") or ajustes.get("web_acento_2") or colores.get("azul_claro") or "#5b7cff")
    try:
        h = color.lstrip("#")
        r_, g_, b_ = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError):
        return True
    return 0.2126 * r_ + 0.7152 * g_ + 0.0722 * b_ >= 0.25


def cuadro(dibujante, t_ms):
    """La imagen RGBA de este instante (figura + globo si hay un aviso reciente)."""
    from core.nucleo import avatar_dibujo
    ajustes, colores = ajustes_de_la_interfaz()
    if not halo_visible(ajustes, colores):
        ajustes = dict(ajustes, efecto_brillo=0)
    estado = estado_actual()
    imagen = dibujante.dibujar(estado, 0 if ajustes.get("reducir_movimiento") else t_ms, ajustes, colores)
    g = globo_actual()
    if g["texto"] and g["edad"] < 12:
        imagen = avatar_dibujo.poner_globo(imagen, g["texto"], colores, alerta=g["nivel"] == "alerta")
    return imagen


def _clic():
    if os.environ.get("ARCHE_FONDO") == "1":
        try:
            from core import presencia
            presencia.abrir_burbuja()
            return
        except Exception:
            pass
    try:
        from core.interfaz import web
        web.abrir()
    except Exception:
        try:
            from core import interfaz
            interfaz.manejar("abre la interfaz")
        except Exception:
            pass


# ------------------------------------------------------------------
# Ventana por capas de Windows (transparencia real por píxel)
# ------------------------------------------------------------------

def a_bgra_premultiplicado(imagen):
    """Bytes en el formato que pide UpdateLayeredWindow: BGRA con el color ya multiplicado por alfa."""
    import numpy as np
    arr = np.asarray(imagen.convert("RGBA"), dtype=np.float32)
    alfa = arr[..., 3:4] / 255.0
    salida = np.empty(arr.shape, np.uint8)
    salida[..., 0] = (arr[..., 2:3] * alfa)[..., 0]
    salida[..., 1] = (arr[..., 1:2] * alfa)[..., 0]
    salida[..., 2] = (arr[..., 0:1] * alfa)[..., 0]
    salida[..., 3] = arr[..., 3]
    return salida.tobytes()


class _Capa:
    """Lo mínimo de Win32 para pintar una imagen con alfa sobre una ventana ya creada."""

    def __init__(self, hwnd, lado):
        from ctypes import wintypes
        self.w = wintypes
        self.hwnd, self.lado = hwnd, lado
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        self.u, self.g = u, g

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

        u.GetDC.restype, u.GetDC.argtypes = wintypes.HDC, [wintypes.HWND]
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = wintypes.HDC, [wintypes.HDC]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
        g.SelectObject.restype, g.SelectObject.argtypes = wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]
        g.DeleteObject.argtypes, g.DeleteDC.argtypes = [wintypes.HGDIOBJ], [wintypes.HDC]
        u.UpdateLayeredWindow.restype = wintypes.BOOL
        u.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                          ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                          wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
        u.GetWindowLongW.restype, u.GetWindowLongW.argtypes = wintypes.LONG, [wintypes.HWND, ctypes.c_int]
        u.SetWindowLongW.restype = wintypes.LONG
        u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]

        GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TOOLWINDOW = -20, 0x00080000, 0x00000080
        estilo = (u.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW) & 0xFFFFFFFF
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo - (1 << 32) if estilo & 0x80000000 else estilo)

        self.dc_pantalla = u.GetDC(None)
        self.dc_mem = g.CreateCompatibleDC(self.dc_pantalla)
        cabecera = BITMAPINFOHEADER()
        cabecera.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        cabecera.biWidth, cabecera.biHeight = lado, -lado          # negativo = de arriba hacia abajo
        cabecera.biPlanes, cabecera.biBitCount, cabecera.biCompression = 1, 32, 0
        self.bits = ctypes.c_void_p()
        self.bitmap = g.CreateDIBSection(self.dc_pantalla, ctypes.byref(cabecera), 0, ctypes.byref(self.bits), None, 0)
        if not self.bitmap or not self.bits:
            raise OSError("no pude crear la imagen de la ventana")
        self.anterior = g.SelectObject(self.dc_mem, self.bitmap)
        self.mezcla = BLENDFUNCTION(0, 0, 255, 1)                  # AC_SRC_OVER, alfa por píxel
        self.tamano = wintypes.SIZE(lado, lado)
        self.origen = wintypes.POINT(0, 0)

    def pintar(self, imagen):
        datos = a_bgra_premultiplicado(imagen)
        ctypes.memmove(self.bits, datos, len(datos))
        if not self.u.UpdateLayeredWindow(self.hwnd, self.dc_pantalla, None, ctypes.byref(self.tamano), self.dc_mem,
                                          ctypes.byref(self.origen), 0, ctypes.byref(self.mezcla), 2):   # ULW_ALPHA
            raise OSError("Windows rechazó la ventana por capas")

    def cerrar(self):
        try:
            self.g.SelectObject(self.dc_mem, self.anterior)
            self.g.DeleteObject(self.bitmap)
            self.g.DeleteDC(self.dc_mem)
            self.u.ReleaseDC(None, self.dc_pantalla)
        except Exception:
            pass


def _correr():
    import tkinter as tk
    from core.nucleo import avatar_dibujo
    lado = int(_estado()["tamano"])
    raiz = tk.Tk()
    raiz.overrideredirect(True)
    raiz.attributes("-topmost", True)
    x, y = _posicion()
    x = x if x is not None else raiz.winfo_screenwidth() - lado - 24
    y = y if y is not None else raiz.winfo_screenheight() - lado - 80
    raiz.geometry(f"{lado}x{lado}+{int(x)}+{int(y)}")
    raiz.update_idletasks()
    raiz.update()

    capa, etiqueta, foto = None, None, [None]
    try:
        try:
            hwnd = int(raiz.wm_frame(), 16)          # la ventana de Windows que envuelve a la de Tk
        except (ValueError, tk.TclError):
            hwnd = raiz.winfo_id()
        capa = _Capa(hwnd, lado)
        capa.pintar(cuadro(avatar_dibujo.Dibujante(lado), 0))      # si Windows la rechaza, mejor saberlo ya
        _control["modo"] = "capas"
    except Exception as e:
        # Plan B (no debería hacer falta en Windows 10/11): recorte por color, sin bordes suaves.
        _control["modo"], _control["error"] = "recorte", repr(e)[:200]
        if capa is not None:
            capa.cerrar()
            capa = None
        clave = "#010203"
        raiz.configure(bg=clave)
        try:
            raiz.attributes("-transparentcolor", clave)
        except tk.TclError:
            pass
        etiqueta = tk.Label(raiz, bg=clave, bd=0)
        etiqueta.pack()

    dibujante = avatar_dibujo.Dibujante(lado)
    arrastre = {"x": 0, "y": 0, "movio": False}

    def _presionar(ev):
        arrastre.update(x=ev.x_root - raiz.winfo_x(), y=ev.y_root - raiz.winfo_y(), movio=False, x0=ev.x_root, y0=ev.y_root)

    def _mover(ev):
        if abs(ev.x_root - arrastre["x0"]) + abs(ev.y_root - arrastre["y0"]) > 4:
            arrastre["movio"] = True
        if arrastre["movio"]:
            raiz.geometry(f"+{ev.x_root - arrastre['x']}+{ev.y_root - arrastre['y']}")

    def _soltar(ev):
        if arrastre["movio"]:
            comun.guardar(ARCH_POSICION, {"x": raiz.winfo_x(), "y": raiz.winfo_y()})
        else:
            comun.en_hilo(_clic, nombre="arche-avatar-clic")

    for widget in (raiz, etiqueta):
        if widget is not None:
            widget.bind("<ButtonPress-1>", _presionar)
            widget.bind("<B1-Motion>", _mover)
            widget.bind("<ButtonRelease-1>", _soltar)

    inicio = time.time()
    fallos = [0]

    def _cuadro():
        if _control["parar"] or _control.get("orden") in ("esconder", "reiniciar"):
            if capa is not None:
                capa.cerrar()
            raiz.destroy()
            return
        try:
            imagen = cuadro(dibujante, (time.time() - inicio) * 1000)
            if capa is not None:
                capa.pintar(imagen)
            else:
                from PIL import Image, ImageTk
                import numpy as np
                arr = np.asarray(imagen).copy()
                visible = arr[..., 3] > 90
                arr[~visible] = (1, 2, 3, 255)
                arr[visible, 3] = 255
                foto[0] = ImageTk.PhotoImage(Image.fromarray(arr, "RGBA").convert("RGB"))
                etiqueta.configure(image=foto[0])
            fallos[0] = 0
        except Exception as e:
            fallos[0] += 1
            if fallos[0] == 1:
                _control["error"] = repr(e)[:200]
                comun.anotar(comun.ruta("errores.jsonl"), {"cuando": comun.ahora_txt(), "donde": "avatar",
                                                           "error": repr(e)[:400]})
            if fallos[0] > 40:
                raiz.destroy()
                return
        raiz.after(CUADRO_MS, _cuadro)

    _cuadro()
    raiz.mainloop()
    if _control.get("orden") == "reiniciar" and not _control["parar"]:
        _control["orden"] = None
        _correr()


# ------------------------------------------------------------------
# Arranque y comandos
# ------------------------------------------------------------------

def activo():
    return _control["hilo"] is not None and _control["hilo"].is_alive()


def iniciar(forzar=False):
    """Arranca el avatar (solo en Windows, salvo forzar=True). No hace nada si ya está."""
    if activo():
        return True
    if not forzar and (not comun.es_windows() or not _estado()["activo"]):
        return False
    try:
        import tkinter  # noqa: F401
        import numpy  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False
    _control.update(parar=False, orden=None, error="")
    _control["hilo"] = comun.en_hilo(_correr, nombre="arche-avatar")
    return True


def detener():
    _control["parar"] = True


def explicar_modo():
    if not activo():
        return "El avatar está escondido. Di «muestra el avatar»."
    try:
        estilo = ajustes_de_la_interfaz()[0].get("estilo_voz") or "esfera"
    except Exception:
        estilo = "?"
    if _control["modo"] == "capas":
        return (f"Me estoy dibujando con la forma «{estilo}» de tu interfaz, sobre una ventana transparente de Windows "
                "(solo se ve la figura).")
    return (f"Me estoy dibujando con la forma «{estilo}», pero Windows no aceptó la ventana transparente fina "
            f"({_control['error']}), así que uso un recorte simple.")


def manejar(comando):
    c = comun.norm(comando)
    if c in ("muestra el avatar", "muestra tu avatar", "avatar encendido", "aparece en el escritorio", "muestrate"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg("Aquí estoy, en la esquina de tu pantalla, con la forma de tu interfaz."
                  if iniciar(forzar=True) else "No pude mostrarme (falta tkinter, numpy o pillow).")
        return True
    if c in ("esconde el avatar", "esconde tu avatar", "avatar apagado", "quitate del escritorio", "quita el avatar"):
        e = _estado(); e["activo"] = False; _guardar(e)
        _control["orden"] = "esconder"
        comun.msg("Me escondo. Di «muestra el avatar» para volver.")
        return True
    if c in ("estado del avatar", "como estas dibujando el avatar", "modo del avatar"):
        comun.msg(explicar_modo())
        return True
    if c in ("avatar sin halo", "quita el halo del avatar", "avatar sin brillo"):
        e = _estado(); e["halo"] = False; _guardar(e)
        comun.msg("Listo, sin halo: solo la figura.")
        return True
    if c in ("avatar con halo", "pon el halo del avatar", "avatar con brillo"):
        e = _estado(); e["halo"] = True; _guardar(e)
        comun.msg("Listo, con el halo de tu interfaz.")
        return True
    if c in ("avatar grande", "avatar mas grande", "hazte mas grande"):
        e = _estado(); e["tamano"] = min(420, int(e["tamano"]) + 40); _guardar(e)
        _control["orden"] = "reiniciar"
        comun.msg("Más grande.")
        return True
    if c in ("avatar pequeno", "avatar mas pequeno", "hazte mas pequena", "avatar chiquito"):
        e = _estado(); e["tamano"] = max(100, int(e["tamano"]) - 40); _guardar(e)
        _control["orden"] = "reiniciar"
        comun.msg("Más pequeña.")
        return True
    return False
