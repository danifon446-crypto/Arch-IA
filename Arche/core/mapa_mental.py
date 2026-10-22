"""
mapa_mental.py
--------------
Mapas mentales hechos DE VERDAD por Arché (no los "finge" la nube).

  mapa mental de fuerzas
  haz un mapa mental sobre la fotosíntesis
  el mapa mental            (usa el tema del que venían hablando)
  abre el mapa mental       (vuelve a abrir el último)

Cómo lo hace:
  1. Le pide a la nube (o a Ollama si no hay nube) SOLO la estructura en JSON:
     tema central, ramas y puntos de cada rama.
  2. Dibuja el mapa él mismo (SVG dentro de un .html, sin librerías) y lo guarda
     en la carpeta mapas_mentales/.
  3. Lo abre en el navegador. Solo dice "listo" si el archivo se escribió; si
     algo falla, dice exactamente qué falló.

Desde WhatsApp no abre ventanas (no estás frente al PC): responde con el mapa en
texto y lo deja guardado en el PC.
"""

import html
import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from core.rutas import BASE

CARPETA = os.path.join(BASE, "mapas_mentales")
MAX_RAMAS = 8
MAX_HIJOS = 6
COLORES = ["#4f7cff", "#8b5cf6", "#ef476f", "#3b82f6", "#a855f7", "#f43f5e", "#6366f1", "#c026d3"]

_RE_MAPA = re.compile(r"\bmapas?\s+(?:mental(?:es)?|conceptual(?:es)?)\b")
_RE_TEMA = re.compile(r"\b(?:de|del|sobre|acerca de|para)\s+(.+)$")
_RE_REABRIR = re.compile(r"\b(abre|abrir|muestra|mostrar|ver|veo|enseña|ensena|otra vez|de nuevo)\b")
_ultimo = {"mapa": None, "ruta": None}


def _sin_tildes(texto):
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        texto = texto.replace(a, b)
    return texto


# ------------------------------------------------------------------
# 1. Pedir la estructura
# ------------------------------------------------------------------

_SISTEMA = ("Eres un generador de mapas mentales. Respondes únicamente con JSON válido, "
            "sin explicaciones, sin markdown y sin comillas de código.")


def _prompt(tema, contexto):
    if tema:
        objetivo = f"Tema: {tema}"
    else:
        objetivo = ("Tema: el tema del que veníamos hablando. Conversación reciente:\n" + contexto)
    return (
        f"{objetivo}\n\n"
        "Arma un mapa mental en español. Devuelve SOLO este JSON, con esta forma exacta:\n"
        '{"centro": "tema central", "ramas": [{"titulo": "rama", "hijos": ["punto", "punto"]}]}\n'
        f"Reglas: de 4 a {MAX_RAMAS} ramas; de 2 a {MAX_HIJOS} puntos por rama; cada texto de máximo 7 palabras; "
        "sin repetir ideas; contenido correcto y útil para estudiar."
    )


def _contexto_reciente():
    try:
        from core.IA import cerebro
        recientes = cerebro._historial[-6:]
        return "\n".join(("Usuario: " if m["role"] == "user" else "Arché: ") + m["content"][:400]
                         for m in recientes)
    except Exception:
        return ""


def _extraer_json(texto):
    texto = re.sub(r"```(?:json)?", "", texto or "")
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini < 0 or fin <= ini:
        raise ValueError("la respuesta no trajo un JSON")
    return json.loads(texto[ini:fin + 1])


def normalizar_mapa(datos):
    """Valida lo que devolvió el modelo y lo deja en forma segura. Lanza ValueError si no sirve."""
    if not isinstance(datos, dict):
        raise ValueError("la estructura no es un objeto")
    centro = str(datos.get("centro", "")).strip()
    ramas = []
    for r in datos.get("ramas", []) if isinstance(datos.get("ramas"), list) else []:
        if isinstance(r, str):
            titulo, hijos = r, []
        elif isinstance(r, dict):
            titulo, hijos = str(r.get("titulo", "")).strip(), r.get("hijos", [])
        else:
            continue
        hijos = [str(h).strip() for h in hijos if str(h).strip()] if isinstance(hijos, list) else []
        if titulo:
            ramas.append({"titulo": titulo[:60], "hijos": [h[:70] for h in hijos[:MAX_HIJOS]]})
    if not centro or len(ramas) < 2:
        raise ValueError("faltó el tema central o hay menos de 2 ramas")
    return {"centro": centro[:60], "ramas": ramas[:MAX_RAMAS]}


def _pedir_estructura(tema, contexto):
    """(mapa, error). Prueba la nube y, si falla o no hay, Ollama."""
    prompt = _prompt(tema, contexto)
    errores = []
    try:
        from core.IA import nube
        if nube.modo() != "ollama" and nube.configurada() and nube.disponible():
            try:
                texto = nube.responder([{"role": "user", "content": prompt}], sistema=_SISTEMA,
                                       max_tokens=900, temperature=0.4)
                return normalizar_mapa(_extraer_json(texto)), None
            except Exception as e:
                errores.append(f"la nube: {e}")
    except Exception as e:
        errores.append(f"la nube no está disponible: {e}")
    try:
        from core.IA.ollamaIA import conversar
        texto = conversar(prompt, num_predict=700, permitir_nube=False)
        return normalizar_mapa(_extraer_json(texto)), None
    except Exception as e:
        errores.append(f"Ollama: {e}")
    return None, "; ".join(errores)


# ------------------------------------------------------------------
# 2. Dibujar
# ------------------------------------------------------------------

def _ancho(texto, tam=14):
    return int(len(texto) * tam * 0.56) + 26


def _lados(ramas):
    mitad = (len(ramas) + 1) // 2
    return ramas[:mitad], ramas[mitad:]


def construir_svg(mapa):
    centro = mapa["centro"]
    cw, ch = max(150, _ancho(centro, 18)), 54
    fila, hueco = 34, 70
    partes, xs, ys = [], [0], [0]

    def nodo(x_borde, y, texto, color, lado, grande=False, hijo=False):
        w = _ancho(texto, 13 if hijo else 15)
        h = 26 if hijo else 34
        x = x_borde if lado > 0 else x_borde - w
        xs.extend([x, x + w])
        ys.extend([y - h / 2, y + h / 2])
        relleno = "none" if hijo else color
        opac = "0" if hijo else "0.22"
        partes.append(f'<rect x="{x:.0f}" y="{y - h / 2:.0f}" width="{w}" height="{h}" rx="{h / 2:.0f}" '
                      f'fill="{relleno}" fill-opacity="{opac}" stroke="{color}" stroke-width="{1.2 if hijo else 2}"/>')
        partes.append(f'<text x="{x + w / 2:.0f}" y="{y + 5:.0f}" text-anchor="middle" '
                      f'font-size="{13 if hijo else 15}" fill="{"#dfe3ff" if hijo else "#ffffff"}" '
                      f'font-weight="{400 if hijo else 600}">{html.escape(texto)}</text>')
        return w

    def curva(x1, y1, x2, y2, color, grosor):
        xm = (x1 + x2) / 2
        partes.append(f'<path d="M{x1:.0f} {y1:.0f} C{xm:.0f} {y1:.0f} {xm:.0f} {y2:.0f} {x2:.0f} {y2:.0f}" '
                      f'fill="none" stroke="{color}" stroke-width="{grosor}" stroke-opacity="0.75" stroke-linecap="round"/>')

    indice_color = 0
    for lado, grupo in ((1, _lados(mapa["ramas"])[0]), (-1, _lados(mapa["ramas"])[1])):
        if not grupo:
            continue
        alturas = [max(1, len(r["hijos"])) * fila + 14 for r in grupo]
        y = -sum(alturas) / 2
        for r, alto in zip(grupo, alturas):
            color = COLORES[indice_color % len(COLORES)]
            indice_color += 1
            yb = y + alto / 2
            bw = _ancho(r["titulo"], 15)
            x_borde = lado * (cw / 2 + hueco)
            curva(lado * cw / 2, 0, x_borde, yb, color, 3)
            nodo(x_borde, yb, r["titulo"], color, lado)
            x_hijo = x_borde + lado * (bw + hueco * 0.8)
            n = len(r["hijos"])
            for j, h in enumerate(r["hijos"]):
                yh = y + 7 + fila * (j + 0.5) + (alto - 14 - fila * max(1, n)) / 2
                curva(x_borde + lado * bw, yb, x_hijo, yh, color, 1.6)
                nodo(x_hijo, yh, h, color, lado, hijo=True)
            y += alto

    # nodo central (se dibuja al final para quedar encima de las curvas)
    partes.append(f'<rect x="{-cw / 2:.0f}" y="{-ch / 2:.0f}" width="{cw}" height="{ch}" rx="{ch / 2:.0f}" '
                  f'fill="#161a3d" stroke="#6d83ff" stroke-width="3"/>')
    partes.append(f'<text x="0" y="6" text-anchor="middle" font-size="18" font-weight="700" fill="#ffffff">'
                  f'{html.escape(centro)}</text>')
    xs.extend([-cw / 2, cw / 2])
    ys.extend([-ch / 2, ch / 2])

    margen = 40
    x0, y0 = min(xs) - margen, min(ys) - margen
    ancho, alto = max(xs) - min(xs) + 2 * margen, max(ys) - min(ys) + 2 * margen
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {ancho:.0f} {alto:.0f}" '
            f'width="{ancho:.0f}" height="{alto:.0f}" font-family="Segoe UI, Arial, sans-serif">'
            + "".join(partes) + "</svg>")


def construir_html(mapa):
    titulo = html.escape(mapa["centro"])
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Mapa mental: {titulo}</title>"
        "<style>html,body{margin:0;height:100%;background:#0a0b14;color:#dfe3ff;font-family:'Segoe UI',Arial,sans-serif}"
        "header{padding:14px 22px;font-size:14px;color:#8d96d6;letter-spacing:.04em}"
        "main{display:flex;justify-content:center;align-items:center;padding:0 12px 24px}"
        "svg{max-width:100%;height:auto;max-height:88vh}</style></head><body>"
        f"<header>ARCHÉ · MAPA MENTAL</header><main>{construir_svg(mapa)}</main></body></html>"
    )


def texto_del_mapa(mapa):
    lineas = [f"Mapa mental: {mapa['centro']}"]
    for r in mapa["ramas"]:
        lineas.append(f"- {r['titulo']}")
        lineas.extend(f"    · {h}" for h in r["hijos"])
    return "\n".join(lineas)


def guardar(mapa):
    os.makedirs(CARPETA, exist_ok=True)
    nombre = re.sub(r"[^a-z0-9]+", "_", _sin_tildes(mapa["centro"].lower())).strip("_")[:40] or "mapa"
    ruta = os.path.join(CARPETA, nombre + ".html")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(construir_html(mapa))
    return ruta


def abrir(ruta):
    """True solo si se pudo pedir al sistema que lo abra."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(ruta)                       # Windows
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", ruta])
            return True
        return bool(webbrowser.open(Path(ruta).resolve().as_uri()))
    except Exception:
        return False


# ------------------------------------------------------------------
# 3. Comando
# ------------------------------------------------------------------

def _canal():
    try:
        from core import canales
        return canales.canal_actual()
    except Exception:
        return "consola"


def _tema_del_comando(c):
    m = _RE_MAPA.search(c)
    resto = c[m.end():]
    t = _RE_TEMA.search(resto)
    if not t:
        return None
    tema = re.sub(r"\b(en una ventana|por favor|ahora|ya|de nuevo)\b", "", t.group(1)).strip(" .,:;!?")
    return tema or None


def manejar(comando):
    """True si el comando pedía un mapa mental (y ya lo atendió)."""
    c = _sin_tildes(comando.lower()).strip()
    if not _RE_MAPA.search(c):
        return False
    en_pc = _canal() == "consola"
    tema = _tema_del_comando(c)

    if not tema and _ultimo["ruta"] and _RE_REABRIR.search(c) and os.path.exists(_ultimo["ruta"]):
        if en_pc:
            if abrir(_ultimo["ruta"]):
                print(f"Arché: Abrí el último mapa mental ({_ultimo['mapa']['centro']}).")
            else:
                print(f"Arché: No pude abrirlo solo, pero está guardado en: {_ultimo['ruta']}")
        else:
            print("Arché: " + texto_del_mapa(_ultimo["mapa"]))
        return True

    contexto = "" if tema else _contexto_reciente()
    if not tema and not contexto:
        print("Arché: ¿De qué tema quieres el mapa mental?")
        tema = input("Tú: ").strip()
        if not tema:
            print("Arché: Cancelado.")
            return True

    print(f"Arché: Armando el mapa mental{f' de {tema}' if tema else ''}...")
    mapa, error = _pedir_estructura(tema, contexto)
    if not mapa:
        print("Arché: No pude armar el mapa mental: no logré obtener la estructura "
              f"({error}). No dibujé nada.")
        return True

    try:
        ruta = guardar(mapa)
    except Exception as e:
        print(f"Arché: Tengo la estructura, pero no pude escribir el archivo ({e}). No dibujé nada.")
        return True
    _ultimo["mapa"], _ultimo["ruta"] = mapa, ruta

    if not en_pc:
        print("Arché: " + texto_del_mapa(mapa) + "\n(Lo dejé guardado en el PC.)")
    elif abrir(ruta):
        print(f"Arché: Listo, armé el mapa mental de «{mapa['centro']}» y lo abrí en tu navegador. "
              f"Queda guardado en: {ruta}")
    else:
        print(f"Arché: Armé el mapa mental de «{mapa['centro']}», pero no pude abrirlo solo. "
              f"Ábrelo tú desde: {ruta}")
    return True