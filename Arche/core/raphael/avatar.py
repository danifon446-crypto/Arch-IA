"""
avatar.py
---------
Ubicacion: Arche/core/raphael/avatar.py

PRESENCIA VISUAL: Arché vive en tu escritorio como una esfera de luz flotante (sin ventana,
siempre encima, en una esquina), aunque no tengas la interfaz abierta.

Cómo reacciona (a lo que pasa DE VERDAD, no a una animación de adorno):
  reposo      azul y morado, respira despacio
  hablando    rosa/magenta, se deforma al ritmo de su voz
  pensando    morado, con puntos girando (misión de Tempest, caza del Depredador)
  alerta      rojo, late rápido (el guardián o el Depredador encontraron algo)
  logro       dorado un momento (subió de rango, absorbió una presa, terminó una misión)
  durmiendo   apagada, con «z» (llevas un rato sin usar el PC o es de madrugada)

Cuando Arché te avisa algo, sale un globo de texto al lado de la esfera.
  clic                -> abre la burbuja para escribirle (si arche_fondo.pyw está corriendo)
  arrastrar           -> la mueves (recuerda dónde la dejaste)
  clic derecho        -> esconder / más grande / más pequeña

Comandos: muestra el avatar · esconde el avatar · avatar grande · avatar pequeño
"""

import math
import random
import time

from core.raphael import comun

ARCH = comun.ruta("avatar.json")
TRANSPARENTE = "#010203"

COLORES = {
    "reposo": ("#5b7cfa", "#9b5bfa"),
    "hablando": ("#ff4fa3", "#c03cff"),
    "pensando": ("#9b5bfa", "#5b3cc4"),
    "alerta": ("#ff3b3b", "#a0101a"),
    "logro": ("#ffd24a", "#ff9a1f"),
    "durmiendo": ("#2c3966", "#1b2240"),
}

_control = {"hilo": None, "parar": False, "orden": None}


def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("tamano", 110)
    e.setdefault("x", None)
    e.setdefault("y", None)
    return e


def _guardar(e):
    comun.guardar(ARCH, e)


# ------------------------------------------------------------------
# Qué está pasando (se prueba sin pantalla)
# ------------------------------------------------------------------

def estado_actual(globo=None, hablando=None, pensando=None, inactivo=None, hora=None):
    globo = globo if globo is not None else comun.ultimo_globo()
    reciente = time.time() - float(globo.get("cuando", 0)) < 30
    if reciente and globo.get("nivel") == "alerta":
        return "alerta"
    if hablando is None:
        try:
            from core import voz
            hablando = voz.hablando()
        except Exception:
            hablando = False
    if hablando:
        return "hablando"
    if reciente and globo.get("nivel") == "logro" and time.time() - float(globo.get("cuando", 0)) < 8:
        return "logro"
    if pensando is None:
        pensando = False
        try:
            from core.raphael import tempest, depredador
            pensando = bool(tempest._mision_en_curso["id"]) or depredador._lock_caza.locked()
        except Exception:
            pass
    if pensando:
        return "pensando"
    if inactivo is None:
        try:
            from core.raphael import ritmo
            inactivo = ritmo.minutos_inactivo()
        except Exception:
            inactivo = 0
    hora = comun.ahora().hour if hora is None else hora
    if inactivo > 30 or 1 <= hora < 5:
        return "durmiendo"
    return "reposo"


def _mezclar(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(a, b))


def radio(estado, t, base):
    if estado == "hablando":
        return base * (0.86 + 0.09 * math.sin(t * 13) + 0.05 * random.random())
    if estado == "alerta":
        return base * (0.82 + 0.12 * abs(math.sin(t * 6)))
    if estado == "durmiendo":
        return base * (0.72 + 0.02 * math.sin(t * 0.8))
    return base * (0.84 + 0.05 * math.sin(t * 1.6))


# ------------------------------------------------------------------
# La ventana (hilo propio de Tk)
# ------------------------------------------------------------------

def _correr():
    import tkinter as tk
    e = _estado()
    tam = int(e["tamano"])
    ancho, alto = 340, tam + 120
    raiz = tk.Tk()
    raiz.overrideredirect(True)
    raiz.attributes("-topmost", True)
    try:
        raiz.attributes("-transparentcolor", TRANSPARENTE)
    except tk.TclError:
        pass
    raiz.configure(bg=TRANSPARENTE)
    x = e["x"] if e["x"] is not None else raiz.winfo_screenwidth() - ancho - 20
    y = e["y"] if e["y"] is not None else raiz.winfo_screenheight() - alto - 70
    raiz.geometry(f"{ancho}x{alto}+{int(x)}+{int(y)}")
    lienzo = tk.Canvas(raiz, width=ancho, height=alto, bg=TRANSPARENTE, highlightthickness=0)
    lienzo.pack()
    arrastre = {"x": 0, "y": 0, "movio": False}
    cx, cy = ancho - tam // 2 - 10, alto - tam // 2 - 10

    def _presionar(ev):
        arrastre.update(x=ev.x, y=ev.y, movio=False)

    def _mover(ev):
        arrastre["movio"] = True
        raiz.geometry(f"+{raiz.winfo_x() + ev.x - arrastre['x']}+{raiz.winfo_y() + ev.y - arrastre['y']}")

    def _soltar(ev):
        if arrastre["movio"]:
            est = _estado(); est["x"], est["y"] = raiz.winfo_x(), raiz.winfo_y(); _guardar(est)
        else:
            try:
                from core import presencia
                presencia.abrir_burbuja()
            except Exception:
                pass

    menu = tk.Menu(raiz, tearoff=0)
    menu.add_command(label="Esconder", command=lambda: _control.update(orden="esconder"))
    menu.add_command(label="Más grande", command=lambda: _control.update(orden="grande"))
    menu.add_command(label="Más pequeña", command=lambda: _control.update(orden="pequeno"))
    lienzo.bind("<ButtonPress-1>", _presionar)
    lienzo.bind("<B1-Motion>", _mover)
    lienzo.bind("<ButtonRelease-1>", _soltar)
    lienzo.bind("<Button-3>", lambda ev: menu.tk_popup(ev.x_root, ev.y_root))

    inicio = time.time()

    def _cuadro():
        orden = _control.get("orden")
        if _control["parar"] or orden == "esconder":
            if orden == "esconder":
                est = _estado(); est["activo"] = False; _guardar(est)
            _control.update(orden=None)
            raiz.destroy()
            return
        if orden in ("grande", "pequeno"):
            est = _estado()
            est["tamano"] = max(60, min(220, est["tamano"] + (30 if orden == "grande" else -30)))
            _guardar(est)
            _control.update(orden="reiniciar")
            raiz.destroy()
            return
        t = time.time() - inicio
        estado = estado_actual()
        c1, c2 = COLORES[estado]
        lienzo.delete("all")
        r = radio(estado, t, tam / 2)
        for i in range(7, 0, -1):            # capas: de afuera (oscuro) hacia el centro (brillante)
            f = i / 7
            col = _mezclar(c1, c2, f)
            rr = r * (0.35 + 0.65 * f)
            lienzo.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=col, outline="")
        lienzo.create_oval(cx - r * 0.18, cy - r * 0.45, cx + r * 0.08, cy - r * 0.22, fill="#ffffff", outline="")
        if estado == "pensando":
            for k in range(3):
                ang = t * 3 + k * 2 * math.pi / 3
                px, py = cx + math.cos(ang) * r * 1.1, cy + math.sin(ang) * r * 1.1
                lienzo.create_oval(px - 4, py - 4, px + 4, py + 4, fill="#d8c8ff", outline="")
        if estado == "durmiendo":
            dz = (t * 8) % 30
            lienzo.create_text(cx + r * 0.7, cy - r * 0.8 - dz, text="z", fill="#8899cc", font=("Segoe UI", 12, "bold"))
        globo = comun.ultimo_globo()
        if globo.get("texto") and time.time() - float(globo.get("cuando", 0)) < 12:
            texto = globo["texto"].split("\n")[0]
            texto = texto[:170] + ("…" if len(texto) > 170 else "")
            fondo = "#2a1216" if globo.get("nivel") == "alerta" else "#1b1f33"
            item = lienzo.create_text(14, 14, text=texto, anchor="nw", width=ancho - tam - 40, fill="#f2f4ff",
                                      font=("Segoe UI", 10))
            x1, y1, x2, y2 = lienzo.bbox(item)
            lienzo.create_rectangle(x1 - 8, y1 - 6, x2 + 8, y2 + 6, fill=fondo, outline=c1, width=2)
            lienzo.tag_raise(item)
        raiz.after(50, _cuadro)

    _cuadro()
    raiz.mainloop()
    if _control.get("orden") == "reiniciar":
        _control.update(orden=None)
        _correr()


def iniciar(forzar=False):
    """Arranca la esfera (solo en Windows, salvo forzar=True). No hace nada si ya está."""
    if _control["hilo"] is not None and _control["hilo"].is_alive():
        return True
    if not forzar and (not comun.es_windows() or not _estado()["activo"]):
        return False
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    _control.update(parar=False, orden=None)
    _control["hilo"] = comun.en_hilo(_correr, nombre="arche-avatar")
    return True


def detener():
    _control["parar"] = True


def manejar(comando):
    c = comun.norm(comando)
    if c in ("muestra el avatar", "muestra tu avatar", "avatar encendido", "aparece en el escritorio", "muestrate"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg("Aquí estoy, en la esquina de tu pantalla." if iniciar(forzar=True)
                  else "No pude mostrarme (falta tkinter o no hay pantalla).")
        return True
    if c in ("esconde el avatar", "esconde tu avatar", "avatar apagado", "quitate del escritorio"):
        e = _estado(); e["activo"] = False; _guardar(e)
        _control["orden"] = "esconder"
        comun.msg("Me escondo. Di «muestra el avatar» para volver.")
        return True
    if c in ("avatar grande", "avatar mas grande", "hazte mas grande"):
        _control["orden"] = "grande"
        comun.msg("Más grande.")
        return True
    if c in ("avatar pequeno", "avatar mas pequeno", "hazte mas pequena", "avatar chiquito"):
        _control["orden"] = "pequeno"
        comun.msg("Más pequeña.")
        return True
    return False
