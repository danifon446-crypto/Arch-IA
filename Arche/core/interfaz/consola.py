"""
consola.py
----------
Ubicacion: Arche/core/interfaz/consola.py

Paneles bonitos en la terminal con Rich: banner, estado del equipo y
progreso de aprendizaje. Si Rich no esta instalado, cae a texto simple.
"""

from . import datos, tema

try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    HAY_RICH = True
except Exception:   # sin Rich: texto plano
    HAY_RICH = False


def _barra(valor, ancho=22, color=None):
    valor = max(0.0, min(100.0, float(valor)))
    llenos = int(round(valor / 100 * ancho))
    return "█" * llenos, "░" * (ancho - llenos), (color or tema.color_de_uso(valor))


def _consola():
    return Console(highlight=False)


def _linea_barra(etiqueta, valor, sufijo=""):
    llenos, vacios, color = _barra(valor)
    t = Text()
    t.append(f"{etiqueta:<8}", style=tema.TENUE)
    t.append(llenos, style=color)
    t.append(vacios, style=tema.PANEL_2)
    t.append(f" {valor:5.1f}%{sufijo}", style=tema.TEXTO)
    return t


def banner():
    if not HAY_RICH:
        print("ARCHÉ")
        return
    c = _consola()
    letras = "A  R  C  H  É"
    t = Text(justify="center")
    for i, ch in enumerate(letras):
        t.append(ch, style=f"bold {tema.degradado(i / max(1, len(letras) - 1))}")
    c.print(Panel(t, border_style=tema.BORDE, box=box.DOUBLE, padding=(1, 8),
                  subtitle=Text("asistente autónomo", style=tema.TENUE)))


def panel_estado():
    d = datos.instantanea()
    eq, vz, nb, rd = d["equipo"], d["voz"], d["nube"], d["red"]
    if not HAY_RICH:
        print(f"CPU {eq.get('cpu', 0):.0f}%  RAM {eq.get('ram', 0):.0f}%  Disco {eq.get('disco', 0):.0f}%")
        print(f"Voz: {'activa' if vz['activa'] else 'apagada'} | Nube: {nb.get('proveedor', '?')}")
        return
    filas = []
    if "cpu" in eq:
        filas.append(_linea_barra("CPU", eq["cpu"]))
        filas.append(_linea_barra("RAM", eq["ram"]))
        filas.append(_linea_barra("Disco", eq["disco"]))
    else:
        filas.append(Text("Sin datos del equipo (falta psutil)", style=tema.TENUE))
    if "bateria" in eq:
        sufijo = "  ⚡" if eq.get("enchufado") else ""
        filas.append(_linea_barra("Batería", eq["bateria"], sufijo))
    filas.append(Text(""))
    t = Text()
    t.append("Voz      ", style=tema.TENUE)
    if vz["hablando"]:
        t.append("● hablando", style=tema.ROJO_CLARO)
    elif vz["activa"]:
        t.append("● activa", style=tema.AZUL_CLARO)
    else:
        t.append("○ apagada", style=tema.TENUE)
    filas.append(t)
    t = Text()
    t.append("Cerebro  ", style=tema.TENUE)
    if nb:
        nube_txt = f"{nb.get('proveedor', '?')} · {nb.get('modelo', '')}"
        t.append(nube_txt, style=tema.MORADO_CLARO if nb.get("configurada") else tema.TENUE)
        t.append(f"  (modo {nb.get('modo', '?')}, Ollama de respaldo)", style=tema.TENUE)
    else:
        t.append("Ollama local", style=tema.MORADO_CLARO)
    filas.append(t)
    t = Text()
    t.append("Red      ", style=tema.TENUE)
    if rd.get("activo"):
        t.append(f"activa · {rd['precision'] * 100:.1f}% · {rd['intenciones']} intenciones · "
                 f"{rd['ejemplos']} ejemplos", style=tema.AZUL_CLARO)
    else:
        t.append("inactiva (faltan ejemplos)", style=tema.TENUE)
    filas.append(t)
    _consola().print(Panel(Group(*filas), title=Text("ESTADO", style=f"bold {tema.AZUL_CLARO}"),
                           border_style=tema.AZUL, box=box.ROUNDED, padding=(1, 2)))


def panel_aprendizaje():
    ex = datos.examen()
    if not HAY_RICH:
        print(f"Nivel {ex['nivel']}: {ex['listos']}/{len(ex['dominios'])} dominios listos")
        return
    tabla = Table(box=None, show_header=False, padding=(0, 1))
    tabla.add_column(width=14)
    tabla.add_column()
    tabla.add_column(justify="right")
    umbral = max(1, ex["umbral"])
    for dom in ex["dominios"]:
        pct = 100 if dom["listo"] else min(100, dom["racha"] / umbral * 100)
        llenos, vacios, _ = _barra(pct, 18)
        color = tema.AZUL_CLARO if dom["listo"] else (tema.MORADO_CLARO if dom["racha"] else tema.ROJO_CLARO)
        estado = "listo" if dom["listo"] else f"{dom['racha']}/{umbral}"
        tabla.add_row(Text(dom["nombre"], style=tema.TEXTO), Text(llenos + vacios, style=color),
                      Text(estado, style=tema.TENUE))
    if not ex["dominios"]:
        tabla.add_row(Text("Aún no hay progreso de examen.", style=tema.TENUE), "", "")
    cabecera = Text()
    cabecera.append(f"Nivel {ex['nivel']}", style=f"bold {tema.MORADO_CLARO}")
    cabecera.append(f"   {ex['listos']}/{len(ex['dominios'])} dominios listos   ", style=tema.TENUE)
    cabecera.append("● examen automático" if ex["automatico"] else "○ examen automático apagado",
                    style=tema.AZUL_CLARO if ex["automatico"] else tema.TENUE)
    _consola().print(Panel(Group(cabecera, Text(""), tabla),
                           title=Text("APRENDIZAJE", style=f"bold {tema.MORADO_CLARO}"),
                           border_style=tema.MORADO, box=box.ROUNDED, padding=(1, 2)))


def panel_procesos():
    lista = datos.procesos()
    if not HAY_RICH:
        print("Segundo plano:" if lista else "No hay nada corriendo en segundo plano.")
        for p in lista:
            print(f"  - {p['nombre']}: {p['detalle']}")
        return
    tabla = Table(box=None, show_header=False, padding=(0, 1))
    tabla.add_column(width=2)
    tabla.add_column()
    tabla.add_column()
    for p in lista:
        punto = Text("●", style=tema.MORADO_CLARO if p["activo"] else tema.AZUL_CLARO)
        nombre = p["nombre"] + (f"  ×{p['cantidad']}" if p["cantidad"] > 1 else "")
        tabla.add_row(punto, Text(nombre, style=tema.TEXTO), Text(p["detalle"], style=tema.TENUE))
    if not lista:
        tabla.add_row("", Text("No hay nada corriendo en segundo plano ahora mismo.", style=tema.TENUE), "")
    pie = Text("● morado: trabajando ahora    ● azul: en espera, atenta", style=tema.TENUE)
    _consola().print(Panel(Group(tabla, Text(""), pie),
                           title=Text("SEGUNDO PLANO", style=f"bold {tema.MORADO_CLARO}"),
                           border_style=tema.MORADO, box=box.ROUNDED, padding=(1, 2)))


def panel_completo():
    banner()
    panel_estado()
    panel_procesos()
    panel_aprendizaje()
