"""
reglas.py
---------
Ubicacion: Arche/core/agente/reglas.py

Las reglas del juego que Arché aprende por su cuenta. Las consigue de dos formas:
  1. Los datos del propio juego (recetas, herramientas): ver conocimiento.py. Esas no se escriben aqui.
  2. Investigando en la wiki del juego (supervivencia, monstruos, hambre...): lee las paginas,
     un modelo extrae unas pocas reglas practicas y se guardan en reglas_<entorno>.json.

Se hace una sola vez (o cuando se lo pides con "agente investiga") y desde entonces
esas reglas se le muestran al planificador y al decisor en cada objetivo.
Tambien se pueden agregar reglas a mano: "agente reglas agrega <texto>".
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request

from core.agente import config
from core.agente.modelos import ErrorModelo, pedir_json

MAX_CHARS_PARA_MODELO = 1800        # lo que se le muestra al modelo en cada consulta
MAX_REGLAS = 40

# Que investigar por defecto en cada entorno (en ingles: la wiki tiene mas contenido).
TEMAS = {
    "minecraft": ["Survival", "Hostile mob", "Hunger", "Tutorial surviving the first night", "Mining"],
}
WIKIS = {
    "minecraft": "https://minecraft.wiki/api.php",
}
_UA = "Arche-agente/1.0 (asistente personal; lectura de la wiki)"


def _archivo(entorno: str) -> str:
    return f"reglas_{''.join(c for c in entorno if c.isalnum() or c in '_-')}.json"


def cargar(entorno: str) -> dict:
    d = config.leer_json(_archivo(entorno), None)
    return d if isinstance(d, dict) and isinstance(d.get("reglas"), list) else {"reglas": []}


def guardar(entorno: str, datos: dict) -> None:
    config.guardar_json(_archivo(entorno), datos)


def listar(entorno: str) -> list[dict]:
    return cargar(entorno)["reglas"]


def anadir(entorno: str, texto: str, fuente: str = "usuario") -> int:
    """Agrega una regla (o varias separadas por salto de linea o ';'). Devuelve cuantas nuevas entraron."""
    d = cargar(entorno)
    existentes = {r["texto"].strip().lower() for r in d["reglas"]}
    nuevas = 0
    for parte in re.split(r"[\n;]+", texto):
        parte = parte.strip(" -•\t")
        if len(parte) < 4 or parte.lower() in existentes:
            continue
        d["reglas"].append({"texto": parte[:260], "fuente": fuente, "t": time.time()})
        existentes.add(parte.lower())
        nuevas += 1
    d["reglas"] = d["reglas"][-MAX_REGLAS:]
    guardar(entorno, d)
    return nuevas


def borrar_todo(entorno: str) -> int:
    n = len(listar(entorno))
    guardar(entorno, {"reglas": []})
    return n


def texto_para_modelo(entorno: str) -> str:
    reglas = listar(entorno)
    if not reglas:
        return ""
    lineas, total = [], 0
    for r in reversed(reglas):                       # las mas nuevas primero si no caben todas
        linea = "- " + r["texto"]
        if total + len(linea) > MAX_CHARS_PARA_MODELO:
            break
        lineas.append(linea)
        total += len(linea)
    return "REGLAS QUE APRENDÍ DEL JUEGO:\n" + "\n".join(reversed(lineas))


def resumen(entorno: str) -> str:
    reglas = listar(entorno)
    if not reglas:
        return (f"Todavía no tengo reglas guardadas de {entorno}. "
                "Escribe «agente investiga» y las busco yo en la wiki, o agrega una: «agente reglas agrega <texto>».")
    return f"Reglas de {entorno} ({len(reglas)}):\n" + "\n".join(
        f"{i}. {r['texto']}  [{r.get('fuente', '?')}]" for i, r in enumerate(reglas, 1))


# --------------------------------------------------------------------------
# Investigar en la wiki
# --------------------------------------------------------------------------
def _get_json(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _html_a_texto(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|table|sup)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()


def descargar_wiki(entorno: str, tema: str, max_chars: int = 2200) -> tuple[str, str]:
    """-> (titulo, texto) de la mejor pagina de la wiki para ese tema. Lanza OSError/ValueError si no se puede."""
    api = WIKIS.get(entorno)
    if not api:
        raise ValueError(f"no conozco una wiki para {entorno}")
    q = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrsearch": tema,
                                "gsrlimit": 1, "prop": "extracts", "explaintext": 1, "exchars": max_chars})
    datos = _get_json(f"{api}?{q}")
    paginas = list(((datos.get("query") or {}).get("pages") or {}).values())
    if not paginas:
        raise ValueError(f"sin resultados para «{tema}»")
    pag = paginas[0]
    titulo, texto = pag.get("title", tema), (pag.get("extract") or "").strip()
    if not texto:                                    # esa wiki no tiene la extension de extractos: se lee el HTML
        q2 = urllib.parse.urlencode({"action": "parse", "format": "json", "page": titulo, "prop": "text",
                                     "disablelimitreport": 1, "redirects": 1})
        h = ((_get_json(f"{api}?{q2}").get("parse") or {}).get("text") or {}).get("*", "")
        texto = _html_a_texto(h)[:max_chars]
    if not texto:
        raise ValueError(f"la página «{titulo}» vino vacía")
    return titulo, texto[:max_chars]


_SISTEMA = ("Eres un jugador experto que prepara a un agente autónomo para jugar. Lees textos de una wiki y sacas "
            "reglas PRÁCTICAS y verificables: requisitos (qué hace falta para qué), peligros y cómo evitarlos, "
            "el orden sensato de hacer las cosas. Nada de historia ni curiosidades. Respondes únicamente con JSON.")


def investigar(entorno: str, router, temas: list[str] | None = None, descargar=None, avisar=None) -> tuple[int, str]:
    """
    Lee la wiki, extrae reglas y las guarda. Devuelve (reglas_nuevas, mensaje).
    descargar(entorno, tema) -> (titulo, texto) se puede reemplazar (pruebas, otra fuente).
    """
    avisar = avisar or (lambda t: None)
    descargar = descargar or descargar_wiki
    temas = temas or TEMAS.get(entorno) or []
    if not temas:
        return 0, f"No tengo temas que investigar para {entorno}."
    paginas, fallos = [], []
    for t in temas:
        try:
            titulo, texto = descargar(entorno, t)
            paginas.append((titulo, texto))
            avisar(f"  Leí «{titulo}».")
        except Exception as e:
            fallos.append(f"{t}: {e}")
    d = cargar(entorno)
    d["intento"] = time.time()
    if not paginas:
        guardar(entorno, d)
        return 0, "No pude leer la wiki (" + "; ".join(fallos[:2]) + "). Reviso tu internet y lo intento otra vez luego."
    corpus = "\n\n".join(f"## {t}\n{x}" for t, x in paginas)[:7500]
    conocidas = "\n".join("- " + r["texto"] for r in d["reglas"][-15:]) or "(ninguna)"
    prompt = (f"Juego: {entorno}\n\nREGLAS QUE YA TENGO (no las repitas):\n{conocidas}\n\nTEXTOS DE LA WIKI:\n{corpus}\n\n"
              'Devuelve SOLO este JSON: {"reglas": ["regla 1", "regla 2"]} con 6 a 14 reglas nuevas, cada una de '
              "máximo 160 caracteres, en español, concretas y útiles para jugar.")

    def validar(x):
        r = x.get("reglas")
        return None if isinstance(r, list) and r and all(isinstance(i, str) for i in r) else "'reglas' debe ser una lista de textos"

    try:
        res = pedir_json(router, "reflexion", [{"role": "user", "content": prompt}], sistema=_SISTEMA,
                         validar=validar, max_tokens=900, temperatura=0.2)
    except ErrorModelo as e:
        guardar(entorno, d)
        return 0, f"Leí la wiki pero no pude resumirla ahora ({e}). Lo reintento cuando haya nube."
    if not res:
        guardar(entorno, d)
        return 0, "Leí la wiki pero el modelo no devolvió reglas utilizables."
    guardar(entorno, d)
    nuevas = anadir(entorno, "\n".join(res["reglas"][:14]), "wiki: " + ", ".join(t for t, _ in paginas[:3]))
    d = cargar(entorno)
    d["investigado"] = time.time()
    guardar(entorno, d)
    return nuevas, f"Aprendí {nuevas} regla(s) nuevas de {len(paginas)} página(s) de la wiki."


def debe_investigar(entorno: str, horas_entre_intentos: float = 12.0) -> bool:
    """True si nunca investigo y no lo intento hace poco (para no gastar nube en cada objetivo)."""
    if entorno not in TEMAS:
        return False
    d = cargar(entorno)
    if d.get("investigado") or d["reglas"]:
        return False
    return time.time() - float(d.get("intento", 0)) > horas_entre_intentos * 3600
