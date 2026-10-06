"""
web.py
------
Ubicacion: Arche/core/web.py

Lo que Arché puede traer de internet SIN claves ni cuentas:
  * buscar()      -> resultados de busqueda (DuckDuckGo; si falla, Wikipedia)
  * leer_pagina() -> el texto de una pagina (para resumirla)
  * clima()       -> clima actual y de hoy/mañana (Open-Meteo)
  * noticias()    -> titulares (Google Noticias por RSS)
  * hay_internet()

Solo libreria estandar. Lo unico que toca la red es _get() (y el socket de
hay_internet), asi que todo se prueba sin conexion.
"""

import html
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Arche/1.0"
TIMEOUT = 10

_cache_internet = {"cuando": 0.0, "valor": False}
CACHE_INTERNET_SEGUNDOS = 20


def hay_internet(forzar=False):
    """True si hay salida a internet. Se acuerda del resultado 20 segundos."""
    ahora = time.time()
    if not forzar and ahora - _cache_internet["cuando"] < CACHE_INTERNET_SEGUNDOS:
        return _cache_internet["valor"]
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=2).close()
        valor = True
    except OSError:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2).close()
            valor = True
        except OSError:
            valor = False
    _cache_internet.update(cuando=ahora, valor=valor)
    return valor


def _get(url, timeout=TIMEOUT, datos=None):
    """GET (o POST si hay datos) y devuelve el texto. Unico punto de red."""
    cuerpo = urllib.parse.urlencode(datos).encode("utf-8") if datos else None
    req = urllib.request.Request(url, data=cuerpo, headers={"User-Agent": USER_AGENT,
                                                            "Accept-Language": "es-419,es;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        crudo = r.read(2_000_000)
        cod = r.headers.get_content_charset() or "utf-8"
    return crudo.decode(cod, errors="replace")


def _texto(fragmento):
    t = re.sub(r"<[^>]+>", " ", fragmento or "")
    return " ".join(html.unescape(t).split())


# ------------------------------------------------------------------
# Busqueda
# ------------------------------------------------------------------

def _resultados_duckduckgo(pagina):
    resultados = []
    # se parte la pagina en cada enlace de resultado (result__a): cada trozo
    # trae su titulo y, mas abajo, su resumen. Es mas robusto que contar <div>.
    bloques = re.split(r'(?=<a[^>]+class="[^"]*result__a)', pagina)[1:]
    for b in bloques:
        m = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, flags=re.S)
        if not m:
            m = re.search(r'<a[^>]+href="([^"]+)"[^>]+class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', b, flags=re.S)
        if not m:
            continue
        enlace = html.unescape(m.group(1))
        if "uddg=" in enlace:
            enlace = urllib.parse.unquote(enlace.split("uddg=", 1)[1].split("&", 1)[0])
        elif enlace.startswith("//"):
            enlace = "https:" + enlace
        if not enlace.startswith("http") or "duckduckgo.com/y.js" in enlace:
            continue
        s = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', b, flags=re.S)
        resultados.append({"titulo": _texto(m.group(2)), "url": enlace,
                           "resumen": _texto(s.group(1)) if s else ""})
    return resultados


def _resultados_wikipedia(consulta, n):
    url = ("https://es.wikipedia.org/w/api.php?action=query&list=search&format=json&utf8=1"
           f"&srlimit={n}&srsearch=" + urllib.parse.quote(consulta))
    datos = json.loads(_get(url))
    salida = []
    for r in datos.get("query", {}).get("search", []):
        titulo = r.get("title", "")
        salida.append({"titulo": titulo,
                       "url": "https://es.wikipedia.org/wiki/" + urllib.parse.quote(titulo.replace(" ", "_")),
                       "resumen": _texto(r.get("snippet", ""))})
    return salida


def buscar(consulta, n=5):
    """[{titulo, url, resumen}] (hasta n). Lista vacia si no hay red o nada."""
    consulta = (consulta or "").strip()
    if not consulta:
        return []
    try:
        pagina = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(consulta))
        resultados = _resultados_duckduckgo(pagina)
        if resultados:
            return resultados[:n]
    except Exception:
        pass
    try:
        return _resultados_wikipedia(consulta, n)[:n]
    except Exception:
        return []


def leer_pagina(url, maximo=3000):
    """Texto de una pagina web (sin menus ni scripts), cortado a `maximo`."""
    try:
        pagina = _get(url, timeout=12)
    except Exception:
        return ""
    pagina = re.sub(r"(?is)<(script|style|noscript|nav|header|footer|aside|form|svg)[^>]*>.*?</\1>", " ", pagina)
    parrafos = re.findall(r"(?is)<(?:p|h1|h2|h3|li)[^>]*>(.*?)</(?:p|h1|h2|h3|li)>", pagina)
    texto = " ".join(_texto(p) for p in parrafos if len(_texto(p)) > 40) or _texto(pagina)
    return texto[:maximo]


# ------------------------------------------------------------------
# Clima
# ------------------------------------------------------------------

_CODIGOS_CLIMA = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "con niebla", 48: "con niebla", 51: "con llovizna ligera", 53: "con llovizna", 55: "con llovizna fuerte",
    61: "con lluvia ligera", 63: "con lluvia", 65: "con lluvia fuerte", 66: "con lluvia helada",
    67: "con lluvia helada fuerte", 71: "con nevada ligera", 73: "con nevada", 75: "con nevada fuerte",
    80: "con chubascos ligeros", 81: "con chubascos", 82: "con chubascos fuertes",
    95: "con tormenta", 96: "con tormenta y granizo", 99: "con tormenta fuerte y granizo",
}


def clima(ciudad):
    """Texto con el clima de `ciudad`, o None si no la encontro / no hay red."""
    try:
        geo = json.loads(_get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=es&name="
                              + urllib.parse.quote(ciudad)))
        lugares = geo.get("results") or []
        if not lugares:
            return None
        l = lugares[0]
        url = ("https://api.open-meteo.com/v1/forecast?"
               f"latitude={l['latitude']}&longitude={l['longitude']}"
               "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&timezone=auto&forecast_days=2")
        d = json.loads(_get(url))
    except Exception:
        return None
    try:
        ahora = d["current"]
        dia = d["daily"]
        nombre = l.get("name", ciudad)
        pais = l.get("country", "")
        estado = _CODIGOS_CLIMA.get(int(ahora.get("weather_code", -1)), "variable")
        texto = (f"En {nombre}{', ' + pais if pais else ''} hace {round(ahora['temperature_2m'])} grados "
                 f"(se siente como {round(ahora['apparent_temperature'])}), está {estado}, "
                 f"con {round(ahora['relative_humidity_2m'])}% de humedad. "
                 f"Hoy la máxima es {round(dia['temperature_2m_max'][0])} y la mínima {round(dia['temperature_2m_min'][0])}, "
                 f"con {round(dia['precipitation_probability_max'][0] or 0)}% de probabilidad de lluvia.")
        if len(dia["temperature_2m_max"]) > 1:
            texto += (f" Mañana: entre {round(dia['temperature_2m_min'][1])} y {round(dia['temperature_2m_max'][1])} grados, "
                      f"{round(dia['precipitation_probability_max'][1] or 0)}% de lluvia.")
        return texto
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# Noticias
# ------------------------------------------------------------------

def noticias(tema=None, n=5):
    """[{titulo, fuente, url}] de Google Noticias (Colombia, en español)."""
    base = "https://news.google.com/rss"
    sufijo = "hl=es-419&gl=CO&ceid=CO:es-419"
    url = (f"{base}/search?q={urllib.parse.quote(tema)}&{sufijo}" if tema else f"{base}?{sufijo}")
    try:
        raiz = ET.fromstring(_get(url))
    except Exception:
        return []
    salida = []
    for item in raiz.iter("item"):
        titulo = html.unescape((item.findtext("title") or "").strip())
        fuente = (item.findtext("source") or "").strip()
        if " - " in titulo and not fuente:
            titulo, fuente = titulo.rsplit(" - ", 1)
        elif fuente and titulo.endswith(" - " + fuente):
            titulo = titulo[: -len(fuente) - 3]
        if titulo:
            salida.append({"titulo": titulo, "fuente": fuente, "url": (item.findtext("link") or "").strip()})
        if len(salida) >= n:
            break
    return salida