"""
control_pc.py
-------------
Ubicacion: Arche/core/control_pc.py

Control del computador con "conciencia" de lo que hay en él:

  1) Detecta qué navegadores hay INSTALADOS y cuáles están ABIERTOS ahora.
  2) Si hay más de uno y le pedís algo ("abre youtube", "busca X en
     google"), te pregunta en cuál -- en vez de elegir por su cuenta.
     Podés decirle "usa siempre chrome" para que no vuelva a preguntar,
     y "pregúntame el navegador" para volver a la pregunta.
  3) Busca directo en un sitio: "busca gatos en youtube",
     "busca como hacer arroz en claude", "busca arduino en wikipedia".
     Funciona en CUALQUIER sitio: los que Arché ya sabe abrir (sitios.json),
     dominios escritos tal cual ("busca X en amazon.com") o uno que le
     enseñes con "aprende buscar en <sitio>".
  4) Cuenta qué navegadores/programas conocidos tenés abiertos.

Funciona en Windows (donde corre Arché), pero también detecta
navegadores en Linux/Mac con shutil.which para poder probarlo.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import webbrowser
from urllib.parse import quote, quote_plus, urlparse

try:
    import psutil
except ImportError:  # instalador.py no la lista, pero sistema.py ya la usa
    psutil = None

from core.rutas import DATABASE

ARCHIVO_PREFERENCIA = os.path.join(DATABASE, "navegador_preferido.json")
ARCHIVO_NAVEGADORES_EXTRA = os.path.join(DATABASE, "navegadores_extra.json")  # los que tú me enseñas


# ------------------------------------------------------------------
# NAVEGADORES CONOCIDOS
# ------------------------------------------------------------------

# id -> nombre para mostrar, ejecutable, y rutas típicas en Windows.
NAVEGADORES = {
    "chrome": {
        "nombre": "Google Chrome",
        "exe": "chrome.exe",
        "linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
        "rutas": [
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        ],
    },
    "edge": {
        "nombre": "Microsoft Edge",
        "exe": "msedge.exe",
        "linux": ["microsoft-edge", "microsoft-edge-stable"],
        "rutas": [
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        ],
    },
    "firefox": {
        "nombre": "Mozilla Firefox",
        "exe": "firefox.exe",
        "linux": ["firefox"],
        "rutas": [
            r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
            r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
        ],
    },
    "brave": {
        "nombre": "Brave",
        "exe": "brave.exe",
        "linux": ["brave-browser", "brave"],
        "rutas": [
            r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
    },
    "opera": {
        "nombre": "Opera",
        "exe": "opera.exe",
        "linux": ["opera"],
        "rutas": [
            r"%LocalAppData%\Programs\Opera\opera.exe",
            r"%LocalAppData%\Programs\Opera\launcher.exe",
            r"%ProgramFiles%\Opera\opera.exe",
            r"%ProgramFiles%\Opera\launcher.exe",
            r"%ProgramFiles(x86)%\Opera\launcher.exe",
        ],
    },
    "vivaldi": {
        "nombre": "Vivaldi",
        "exe": "vivaldi.exe",
        "linux": ["vivaldi", "vivaldi-stable"],
        "rutas": [
            r"%LocalAppData%\Vivaldi\Application\vivaldi.exe",
            r"%ProgramFiles%\Vivaldi\Application\vivaldi.exe",
        ],
    },
}

# Ejecutables demasiado genéricos para reconocer un navegador por su proceso.
EXE_GENERICOS = {"launcher.exe", "setup.exe", "update.exe", "installer.exe"}

# Otros programas que vale la pena mencionar cuando preguntás qué tenés abierto.
PROGRAMAS_CONOCIDOS = {
    "code.exe": "Visual Studio Code",
    "spotify.exe": "Spotify",
    "discord.exe": "Discord",
    "whatsapp.exe": "WhatsApp",
    "telegram.exe": "Telegram",
    "slack.exe": "Slack",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "powerpnt.exe": "PowerPoint",
    "notepad.exe": "Bloc de notas",
    "calculatorapp.exe": "Calculadora",
    "explorer.exe": None,  # siempre está; no aporta
    "obs64.exe": "OBS Studio",
    "vlc.exe": "VLC",
    "steam.exe": "Steam",
}

ES_WINDOWS = sys.platform.startswith("win")


# ------------------------------------------------------------------
# SITIOS DONDE SE PUEDE BUSCAR DIRECTO
# ------------------------------------------------------------------
#
# Hay cuatro formas de que Arché sepa buscar dentro de un sitio, de la
# más precisa a la más general:
#
#   1) Una plantilla que TÚ le enseñaste ("aprende buscar en mercadolibre").
#   2) Las que ya vienen incluidas (youtube, claude, google...).
#   3) Cualquier sitio que Arché ya aprendió a ABRIR (sitios.json, el mismo
#      archivo que usa navegador.py): busca con Google restringido a ese
#      dominio ("gatos site:dominio.com").
#   4) Cualquier dominio escrito tal cual ("busca X en amazon.com").
#
# Así nada de lo que Arché ya sabe se desaprovecha: cada sitio que le
# enseñaste a abrir ya sirve también para buscar.

ARCHIVO_SITIOS_BUSQUEDA = os.path.join(DATABASE, "sitios_busqueda.json")  # plantillas aprendidas
ARCHIVO_SITIOS_ABRIR = os.path.join(DATABASE, "sitios.json")              # el de navegador.py

# id -> (nombre para mostrar, plantilla de URL con {q}, otros nombres)
SITIOS_BUSQUEDA = {
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}", ["yt", "you tube"]),
    "google": ("Google", "https://www.google.com/search?q={q}", ["internet", "la web"]),
    "claude": ("Claude", "https://claude.ai/new?q={q}", ["claude ai"]),
    "chatgpt": ("ChatGPT", "https://chatgpt.com/?q={q}", ["chat gpt", "gpt"]),
    "wikipedia": ("Wikipedia", "https://es.wikipedia.org/w/index.php?search={q}", ["wiki"]),
    "github": ("GitHub", "https://github.com/search?q={q}", []),
    "spotify": ("Spotify", "https://open.spotify.com/search/{q}", []),
    "maps": ("Google Maps", "https://www.google.com/maps/search/{q}", ["google maps", "mapas"]),
    "bing": ("Bing", "https://www.bing.com/search?q={q}", []),
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?q={q}", ["duck duck go", "ddg"]),
}

_ALIAS_SITIO = {}
for _id, (_nombre, _url, _alias) in SITIOS_BUSQUEDA.items():
    _ALIAS_SITIO[_id] = _id
    for _a in _alias:
        _ALIAS_SITIO[_a] = _id

_RE_DOMINIO = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
TERMINO_DE_PRUEBA = "gatos graciosos"


def _normalizar(texto):
    """Minúsculas, sin tildes y con espacios simples."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.split())


def _leer_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def sitios_aprendidos():
    """{nombre normalizado: {'url': '...{q}...', 'sep': '+'}} -- lo que Arché aprendió a buscar."""
    return {_normalizar(k): v for k, v in _leer_json(ARCHIVO_SITIOS_BUSQUEDA).items()
            if isinstance(v, dict) and "{q}" in v.get("url", "")}


def sitios_para_abrir():
    """{nombre normalizado: url} -- los sitios que Arché ya sabe ABRIR (sitios.json)."""
    return {_normalizar(k): v for k, v in _leer_json(ARCHIVO_SITIOS_ABRIR).items()
            if isinstance(v, str) and v.strip()}


def _dominio_de(url):
    """'https://www.mercadolibre.com.co/algo' -> 'mercadolibre.com.co'."""
    url = (url or "").strip()
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _nombres_de_sitio():
    """{nombre normalizado: clave canónica} de todo lo que Arché puede buscar."""
    nombres = {}
    for nombre in sitios_para_abrir():
        nombres[nombre] = nombre
    for alias, id_ in _ALIAS_SITIO.items():
        nombres[alias] = id_
    for nombre in sitios_aprendidos():
        nombres[nombre] = nombre
    return nombres


def sitio_conocido(nombre):
    """Clave canónica del sitio ('youtube', 'mercadolibre', 'amazon.com') o None."""
    n = _normalizar(nombre)
    nombres = _nombres_de_sitio()
    if n in nombres:
        return nombres[n]
    if _RE_DOMINIO.match(n):
        return n
    return None


def _url_desde_plantilla(plantilla, consulta, sep="+"):
    consulta = consulta.strip()
    if sep == "%20":
        codificada = quote(consulta)
    elif sep in ("+", ""):
        codificada = quote_plus(consulta)
    else:
        codificada = sep.join(quote_plus(parte) for parte in consulta.split())
    return plantilla.replace("{q}", codificada)


def url_de_busqueda(sitio, consulta):
    """URL de búsqueda lista para abrir, o None si no se puede armar.
    Orden: lo que enseñaste > lo incluido > sitio ya conocido (site:) > dominio."""
    clave = _normalizar(sitio)

    aprendido = sitios_aprendidos().get(clave)
    if aprendido:
        return _url_desde_plantilla(aprendido["url"], consulta, aprendido.get("sep", "+"))

    clave = _ALIAS_SITIO.get(clave, clave)
    if clave in SITIOS_BUSQUEDA:
        return _url_desde_plantilla(SITIOS_BUSQUEDA[clave][1], consulta)

    dominio = None
    url_abrir = sitios_para_abrir().get(clave)
    if url_abrir:
        dominio = _dominio_de(url_abrir)
    elif _RE_DOMINIO.match(clave):
        dominio = clave
    if dominio:
        return "https://www.google.com/search?q=" + quote_plus(f"{consulta.strip()} site:{dominio}")
    return None


def nombre_para_mostrar(sitio):
    clave = _ALIAS_SITIO.get(_normalizar(sitio), _normalizar(sitio))
    return SITIOS_BUSQUEDA[clave][0] if clave in SITIOS_BUSQUEDA and clave not in sitios_aprendidos() else sitio


_VERBOS_BUSQUEDA = r"(?:busca|buscar|buscame|buscarme|investiga|averigua|googlea|pon|ponme|reproduce)"


def interpretar_busqueda(comando):
    """
    Entiende frases como:
        'busca gatos graciosos en youtube'
        'buscame recetas de pasta en claude'
        'busca en youtube tutorial de arduino'
        'busca zapatos en mercadolibre'   (si Arché conoce mercadolibre)
        'busca laptops en amazon.com'
    y devuelve (sitio, consulta). Si la frase no nombra un sitio que
    Arché conozca, devuelve None (para que lo maneje el flujo de siempre).
    """
    texto = _normalizar(comando)
    texto = re.sub(r"[¿?¡!]", "", texto).strip()

    m = re.match(rf"^{_VERBOS_BUSQUEDA}\s+(.+)$", texto)
    if not m:
        return None
    resto = m.group(1).strip()

    nombres = _nombres_de_sitio()
    ordenados = sorted(nombres.keys(), key=len, reverse=True)

    # Forma 1: '<consulta> en <sitio>' (el sitio va al final)
    for nombre in ordenados:
        sufijo = f" en {nombre}"
        if resto.endswith(sufijo):
            consulta = resto[: -len(sufijo)].strip()
            if consulta:
                return nombres[nombre], consulta
    m_dom = re.search(r"^(.+?) en ((?:[a-z0-9-]+\.)+[a-z]{2,})$", resto)
    if m_dom:
        return m_dom.group(2), m_dom.group(1).strip()

    # Forma 2: 'en <sitio> <consulta>' (el sitio va al principio)
    for nombre in ordenados:
        prefijo = f"en {nombre} "
        if resto.startswith(prefijo):
            consulta = resto[len(prefijo):].strip()
            if consulta:
                return nombres[nombre], consulta

    return None


def separar_sitio(contenido):
    """'gatos graciosos en youtube' -> ('gatos graciosos', 'youtube').
    Sin ' en ' devuelve (contenido, None). Sirve para lo que clasifican
    las redes: traen 'qué se busca + en qué sitio' juntos."""
    texto = (contenido or "").strip()
    if " en " not in texto:
        return texto, None
    consulta, _, sitio = texto.rpartition(" en ")
    return consulta.strip(), sitio.strip() or None


# ------------------------------------------------------------------
# DETECCIÓN: QUÉ NAVEGADORES HAY
# ------------------------------------------------------------------

def _ruta_en_registro(exe):
    """En Windows, la ruta registrada en 'App Paths' para un .exe."""
    if not ES_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:
        return None
    clave = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(raiz, clave) as k:
                ruta, _ = winreg.QueryValueEx(k, None)
                if ruta and os.path.exists(ruta):
                    return ruta
        except OSError:
            continue
    return None


def _ruta_navegador(info):
    """Ruta del ejecutable de un navegador, o None si no está instalado."""
    if ES_WINDOWS:
        ruta = _ruta_en_registro(info["exe"])
        if ruta:
            return ruta
        for plantilla in info["rutas"]:
            ruta = os.path.expandvars(plantilla)
            if os.path.exists(ruta):
                return ruta
    for comando in info.get("linux", []) + [info["exe"]]:
        ruta = shutil.which(comando)
        if ruta:
            return ruta
    return None


def _ruta_de_comando(comando):
    ''''"C:\\x\\opera.exe" --arg' -> 'C:\\x\\opera.exe' (el comando que Windows
    tiene registrado para abrir un navegador).'''
    comando = (comando or "").strip()
    if comando.startswith('"'):
        fin = comando.find('"', 1)
        return comando[1:fin] if fin > 0 else comando[1:]
    m = re.match(r"^(.*?\.exe)\b", comando, re.IGNORECASE)
    return m.group(1) if m else comando.split(" ")[0]


def _navegadores_del_registro():
    """
    [(nombre, ruta)] de los navegadores que Windows tiene registrados
    (la lista de 'Aplicación web predeterminada'). Es la que usa el
    propio Windows, así que incluye navegadores instalados en CUALQUIER
    carpeta y también los que Arché no conoce de antemano.
    """
    if not ES_WINDOWS:
        return []
    try:
        import winreg
    except ImportError:
        return []

    encontrados = []
    for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            base = winreg.OpenKey(raiz, r"SOFTWARE\Clients\StartMenuInternet")
        except OSError:
            continue
        with base:
            i = 0
            while True:
                try:
                    clave = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(base, clave) as k:
                        try:
                            nombre, _ = winreg.QueryValueEx(k, None)
                        except OSError:
                            nombre = clave
                    with winreg.OpenKey(base, clave + r"\shell\open\command") as k:
                        comando, _ = winreg.QueryValueEx(k, None)
                except OSError:
                    continue
                ruta = _ruta_de_comando(comando)
                if ruta and os.path.exists(ruta):
                    encontrados.append((nombre or clave, ruta))
    return encontrados


def _id_de_navegador(nombre, ruta):
    """Id conocido ('opera') si encaja por ejecutable o por nombre; si no,
    uno nuevo sacado del nombre ('vivaldi')."""
    exe = os.path.basename(ruta).lower()
    for nav_id, info in NAVEGADORES.items():
        if exe == info["exe"].lower():
            return nav_id
    nombre_norm = _normalizar(nombre)
    for nav_id in NAVEGADORES:
        if nav_id in nombre_norm:
            return nav_id
    slug = re.sub(r"[^a-z0-9]+", "", nombre_norm)
    return slug or re.sub(r"[^a-z0-9]+", "", os.path.splitext(exe)[0]) or "navegador"


def _rutas_de_procesos_abiertos():
    """{nombre del proceso en minúsculas: ruta de su .exe} de lo que corre ahora."""
    if psutil is None:
        return {}
    rutas = {}
    for p in psutil.process_iter(["name", "exe"]):
        try:
            nombre = (p.info.get("name") or "").lower()
            exe = p.info.get("exe")
            if nombre and exe:
                rutas.setdefault(nombre, exe)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return rutas


def navegadores_instalados():
    """
    {id: {'nombre':..., 'ruta':...}} de los navegadores que encontró.
    Mira, en orden: las carpetas típicas, lo que Windows tiene registrado
    (cualquier carpeta), los que están ABIERTOS ahora (su proceso dice
    dónde están) y los que tú le enseñaste.
    """
    encontrados = {}
    for nav_id, info in NAVEGADORES.items():
        ruta = _ruta_navegador(info)
        if ruta:
            encontrados[nav_id] = {"nombre": info["nombre"], "ruta": ruta}

    for nombre, ruta in _navegadores_del_registro():
        if os.path.basename(ruta).lower() == "iexplore.exe":
            continue
        nav_id = _id_de_navegador(nombre, ruta)
        if nav_id not in encontrados:
            nombre_mostrar = NAVEGADORES[nav_id]["nombre"] if nav_id in NAVEGADORES else nombre
            encontrados[nav_id] = {"nombre": nombre_mostrar, "ruta": ruta}

    rutas_abiertas = _rutas_de_procesos_abiertos()
    for nav_id, info in NAVEGADORES.items():
        if nav_id not in encontrados:
            ruta = rutas_abiertas.get(info["exe"].lower())
            if ruta and os.path.exists(ruta):
                encontrados[nav_id] = {"nombre": info["nombre"], "ruta": ruta}

    for nav_id, datos in _leer_json(ARCHIVO_NAVEGADORES_EXTRA).items():
        if (nav_id not in encontrados and isinstance(datos, dict)
                and os.path.exists(datos.get("ruta", ""))):
            encontrados[nav_id] = {"nombre": datos.get("nombre", nav_id), "ruta": datos["ruta"]}
    return encontrados


def _nombres_de_procesos_abiertos():
    if psutil is None:
        return set()
    nombres = set()
    for p in psutil.process_iter(["name"]):
        try:
            nombre = p.info.get("name")
            if nombre:
                nombres.add(nombre.lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return nombres


def navegadores_abiertos(instalados=None):
    """Ids de los navegadores instalados que tienen un proceso corriendo
    ahora mismo."""
    procesos = _nombres_de_procesos_abiertos()
    if instalados is None:
        instalados = navegadores_instalados()
    abiertos = []
    for nav_id, datos in instalados.items():
        if nav_id in NAVEGADORES:
            info = NAVEGADORES[nav_id]
            exe = info["exe"].lower()
            candidatos = {exe, exe[:-4]} | {c.lower() for c in info.get("linux", [])}
        else:
            exe = os.path.basename(datos["ruta"]).lower()
            if exe in EXE_GENERICOS:
                continue
            candidatos = {exe, os.path.splitext(exe)[0]}
        if procesos & candidatos:
            abiertos.append(nav_id)
    return abiertos


def programas_abiertos():
    """Nombres legibles de programas conocidos que están abiertos
    (sin navegadores, esos van aparte)."""
    procesos = _nombres_de_procesos_abiertos()
    vistos = []
    for exe, nombre in PROGRAMAS_CONOCIDOS.items():
        if nombre and exe in procesos and nombre not in vistos:
            vistos.append(nombre)
    return vistos


# ------------------------------------------------------------------
# PREFERENCIA ("usa siempre chrome")
# ------------------------------------------------------------------

def navegador_preferido():
    try:
        with open(ARCHIVO_PREFERENCIA, "r", encoding="utf-8") as f:
            return json.load(f).get("navegador")
    except (OSError, ValueError, AttributeError):
        return None


def fijar_navegador_preferido(nav_id):
    """Guarda (o borra, con None) el navegador que se usa sin preguntar."""
    if nav_id is None:
        try:
            os.remove(ARCHIVO_PREFERENCIA)
        except OSError:
            pass
        return
    with open(ARCHIVO_PREFERENCIA, "w", encoding="utf-8") as f:
        json.dump({"navegador": nav_id}, f, ensure_ascii=False, indent=4)


def interpretar_preferencia(comando):
    """
    'usa siempre chrome' / 'siempre usa edge'  -> ('fijar', 'chrome')
    'preguntame el navegador' / 'pregunta siempre el navegador' -> ('preguntar', None)
    Cualquier otra cosa -> None.
    """
    texto = _normalizar(comando)
    if re.search(r"\b(preguntame|pregunta)\b.*\bnavegador\b", texto):
        return ("preguntar", None)
    if re.search(r"\b(usa|utiliza|abre con|abre en)\b.*\bsiempre\b|\bsiempre\b.*\b(usa|utiliza)\b", texto):
        for nav_id, info in NAVEGADORES.items():
            alias = {nav_id, _normalizar(info["nombre"])}
            if nav_id == "chrome":
                alias.add("google chrome")
            if nav_id == "edge":
                alias |= {"microsoft edge", "explorer"}
            if any(a and a in texto for a in alias):
                return ("fijar", nav_id)
        try:
            for nav_id, datos in navegadores_instalados().items():
                if nav_id not in NAVEGADORES and _normalizar(datos["nombre"]) in texto:
                    return ("fijar", nav_id)
        except Exception:
            pass
    return None


def _ensenar_ruta_navegador(nav_id, nombre):
    """No lo encuentro: te pido que me digas dónde está (como con los
    programas). Lo guarda en navegadores_extra.json."""
    print(f"Arché: No encuentro {nombre} instalado. Si lo tienes, arrastra aquí su .exe y pulsa Enter (o escribe 'no').")
    ruta = _preguntar("Tú: ").strip().strip('"')
    if not ruta or _normalizar(ruta) in ("no", "n"):
        return False
    if not os.path.isfile(ruta):
        print("Arché: Esa ruta no existe.")
        return False
    datos = _leer_json(ARCHIVO_NAVEGADORES_EXTRA)
    datos[nav_id] = {"nombre": nombre, "ruta": ruta}
    try:
        _guardar_json(ARCHIVO_NAVEGADORES_EXTRA, datos)
    except OSError as e:
        print(f"Arché: No pude guardarlo ({e}).")
        return False
    return True


def fijar_navegador(nav_id):
    """
    'usa siempre X'. SOLO lo fija si X está instalado (antes decía
    "listo" aunque no existiera y seguía abriendo otro). Si no lo
    encuentra, te deja decirle dónde está. Devuelve (ok, mensaje).
    """
    instalados = navegadores_instalados()
    nombre = NAVEGADORES[nav_id]["nombre"] if nav_id in NAVEGADORES else nav_id
    if nav_id not in instalados:
        if _ensenar_ruta_navegador(nav_id, nombre):
            instalados = navegadores_instalados()
        if nav_id not in instalados:
            otros = ", ".join(i["nombre"] for i in instalados.values()) or "ninguno"
            return False, (f"No encontré {nombre} en este equipo, así que no cambié nada. "
                           f"Los que encuentro: {otros}.")
    fijar_navegador_preferido(nav_id)
    return True, f"Listo, de ahora en más abro todo en {instalados[nav_id]['nombre']}."


# ------------------------------------------------------------------
# ELEGIR NAVEGADOR (pregunta si hace falta)
# ------------------------------------------------------------------

def candidatos_para_elegir():
    """
    Lista ordenada de (id, nombre, abierto) entre la que el usuario
    puede elegir. Prioriza los que ya están abiertos: si hay dos o más
    abiertos, solo se pregunta entre esos; si hay uno abierto, se usa
    ese; si no hay ninguno abierto, se pregunta entre los instalados.
    """
    instalados = navegadores_instalados()
    abiertos = [n for n in navegadores_abiertos(instalados) if n in instalados]

    if len(abiertos) >= 1:
        base = abiertos
    else:
        base = list(instalados.keys())

    return [(n, instalados[n]["nombre"], n in abiertos) for n in base], instalados


def _preguntar(texto):
    try:
        return input(texto).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def elegir_navegador(preguntar=True):
    """
    Devuelve (id, ruta) del navegador a usar, o (None, None) si hay
    que usar el predeterminado del sistema (o si cancelaste).

    Lógica:
      - Si hay uno fijado con 'usa siempre X' y existe -> ese.
      - Si hay un solo candidato -> ese, sin preguntar.
      - Si hay varios -> te pregunta cuál.
    """
    candidatos, instalados = candidatos_para_elegir()

    fijo = navegador_preferido()
    if fijo and fijo in instalados:
        return fijo, instalados[fijo]["ruta"]

    if not candidatos:
        return None, None

    if len(candidatos) == 1:
        nav_id = candidatos[0][0]
        return nav_id, instalados[nav_id]["ruta"]

    if not preguntar:
        nav_id = candidatos[0][0]
        return nav_id, instalados[nav_id]["ruta"]

    hay_abiertos = any(abierto for _, _, abierto in candidatos)
    cabecera = ("Tienes más de un navegador abierto. ¿En cuál lo hago?"
                if hay_abiertos else
                "Tengo más de un navegador instalado. ¿En cuál lo hago?")
    print(f"Arché: {cabecera}")
    for i, (_, nombre, abierto) in enumerate(candidatos, start=1):
        marca = " (abierto)" if abierto else ""
        print(f"  {i}. {nombre}{marca}")
    print("  (Escribe el número o el nombre. Con 'siempre' al final -- ej. '1 siempre' -- no vuelvo a preguntar.)")

    respuesta = _normalizar(_preguntar("Tú: "))
    siempre = respuesta.endswith("siempre")
    respuesta = respuesta.replace("siempre", "").strip()

    elegido = None
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(candidatos):
        elegido = candidatos[int(respuesta) - 1][0]
    else:
        for nav_id, nombre, _ in candidatos:
            if respuesta and (respuesta == nav_id or respuesta in _normalizar(nombre)):
                elegido = nav_id
                break

    if elegido is None:
        print("Arché: No te entendí, lo abro en el navegador predeterminado.")
        return None, None

    if siempre:
        fijar_navegador_preferido(elegido)
        print(f"Arché: Listo, de ahora en más uso {instalados[elegido]['nombre']} sin preguntar. "
              f"Dime 'pregúntame el navegador' para volver a elegir.")
    return elegido, instalados[elegido]["ruta"]


# ------------------------------------------------------------------
# ABRIR UNA URL
# ------------------------------------------------------------------

def abrir_url(url, preguntar=True):
    """
    Abre `url` en el navegador adecuado (preguntando si hay varios).
    Reemplaza a webbrowser.open() en el resto de Arché. Devuelve True
    si pudo abrirla.
    """
    nav_id, ruta = elegir_navegador(preguntar=preguntar)

    if ruta:
        try:
            subprocess.Popen([ruta, url])
            return True
        except OSError as e:
            print(f"Arché: No pude abrir {NAVEGADORES[nav_id]['nombre']} ({e}); pruebo con el predeterminado.")

    try:
        return bool(webbrowser.open(url))
    except Exception as e:
        print(f"Arché: No pude abrir el navegador: {e}")
        return False


def buscar_en_sitio(sitio, consulta):
    """'busca X en youtube' -> abre la búsqueda directa en ese sitio."""
    url = url_de_busqueda(sitio, consulta)
    if url is None:
        return buscar_en_sitio_desconocido(sitio, consulta)
    print(f"Arché: Buscando '{consulta}' en {nombre_para_mostrar(sitio)}...")
    time.sleep(0.8)
    return abrir_url(url)


def _guardar_json(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)


def buscar_en_sitio_desconocido(nombre, consulta):
    """
    El sitio no está en ninguna lista. En vez de rendirse, reusa lo que
    Arché ya sabe hacer para abrir páginas: busca la oficial en internet
    (la misma búsqueda de navegador.py), te pregunta si es esa y, si
    dices que sí, la guarda en sitios.json (queda disponible para ABRIR
    y para BUSCAR) y busca ahí dentro con Google restringido al dominio.
    """
    print(f"Arché: Todavía no conozco '{nombre}'. Voy a buscar su página...")
    try:
        from core import navegador
        resultados = navegador._buscar_ddg(f"{nombre} sitio oficial", max_results=3)
    except Exception:
        resultados = []
        navegador = None

    if not resultados:
        print(f"Arché: No la encontré. Si me enseñas cómo se busca ahí, dime 'aprende buscar en {nombre}'.")
        return False

    url = resultados[0]["href"]
    respuesta = _normalizar(_preguntar(f"Arché: ¿Es esta? {url}\n(si/no)\nTú: "))
    if respuesta not in ("si", "s"):
        print(f"Arché: Vale. Dime 'aprende buscar en {nombre}' y me enseñas cómo se busca ahí.")
        return False

    clave = _normalizar(nombre)
    sitios_abrir = navegador.sitios if navegador is not None else _leer_json(ARCHIVO_SITIOS_ABRIR)
    sitios_abrir[clave] = url          # mismo dict que usa 'abre <sitio>' (se actualiza en vivo)
    try:
        _guardar_json(ARCHIVO_SITIOS_ABRIR, sitios_abrir)
    except OSError:
        pass
    print(f"Arché: Guardé {clave}. Ahora también puedo abrirlo con 'abre {clave}'.")
    url_busqueda = "https://www.google.com/search?q=" + quote_plus(f"{consulta.strip()} site:{_dominio_de(url)}")
    print(f"Arché: Buscando '{consulta}' en {clave}...")
    return abrir_url(url_busqueda)


def deducir_plantilla(url_ejemplo, termino=TERMINO_DE_PRUEBA):
    """
    A partir de la URL de una búsqueda hecha con `termino`, deduce la
    plantilla: reemplaza el término por {q} y detecta cómo ese sitio
    separa las palabras ('+', '%20', '-' o '_'). Devuelve (plantilla, sep)
    o None si no encuentra el término en la URL.
    """
    url_ejemplo = (url_ejemplo or "").strip()
    if "{q}" in url_ejemplo:
        return url_ejemplo, "+"
    variantes = (
        ("+", quote_plus(termino)),
        ("%20", quote(termino)),
        ("-", termino.replace(" ", "-")),
        ("_", termino.replace(" ", "_")),
        ("+", termino.replace(" ", "+")),
    )
    bajo = url_ejemplo.lower()
    for sep, codificada in variantes:
        pos = bajo.find(codificada.lower())
        if pos != -1:
            plantilla = url_ejemplo[:pos] + "{q}" + url_ejemplo[pos + len(codificada):]
            return plantilla, sep
    return None


def ensenar_sitio_busqueda(nombre):
    """'aprende buscar en mercadolibre': te pide la URL de una búsqueda de
    ejemplo, deduce la plantilla y la guarda para siempre."""
    nombre = _normalizar(nombre)
    if not nombre:
        print("Arché: ¿En qué sitio quieres que aprenda a buscar?")
        return False

    print(f"Arché: Dale. Entra a {nombre}, busca exactamente '{TERMINO_DE_PRUEBA}' y pega aquí la URL de la página de resultados.")
    url = _preguntar("Tú: ").strip().strip('"')
    if not url:
        print("Arché: Cancelado.")
        return False

    deducido = deducir_plantilla(url)
    if deducido is None:
        print(f"Arché: No encontré '{TERMINO_DE_PRUEBA}' en esa dirección. Tiene que ser la URL de la página de resultados de esa búsqueda.")
        return False

    plantilla, sep = deducido
    datos = _leer_json(ARCHIVO_SITIOS_BUSQUEDA)
    datos[nombre] = {"url": plantilla, "sep": sep}
    try:
        _guardar_json(ARCHIVO_SITIOS_BUSQUEDA, datos)
    except OSError as e:
        print(f"Arché: No pude guardarlo ({e}).")
        return False
    print(f"Arché: Listo, ya sé buscar en {nombre}. Prueba: 'busca algo en {nombre}'.")
    return True


def aprender_de_uso(frase, contenido, intencion="buscar_en_sitio"):
    """
    Refuerzo de las redes con el uso real: cada vez que usas un comando
    de control del PC, la frase queda como ejemplo de su intención en el
    banco de Arché (aprendizaje.py) y se registra en la telemetría. Así
    la próxima vez que lo digas con otras palabras, el enrutador natural
    ya lo reconoce. Va en segundo plano (calcular el embedding es lento
    y no debe frenar el comando). Si algo falla, no pasa nada.
    """
    def _tarea():
        try:
            from core.IA import aprendizaje
            aprendizaje.aprender(frase, intencion, contenido, fuente="control_pc")
        except Exception:
            pass
        try:
            from core.IA.telemetria import registrar_comando
            registrar_comando(frase, intencion, resuelto_por="determinístico")
        except Exception:
            pass

    threading.Thread(target=_tarea, daemon=True).start()


# ------------------------------------------------------------------
# "ESTAR AL TANTO DEL COMPU"
# ------------------------------------------------------------------

def resumen_del_pc():
    """Texto en lenguaje natural: navegadores instalados/abiertos y
    programas conocidos que están abiertos ahora."""
    instalados = navegadores_instalados()
    abiertos = [n for n in navegadores_abiertos(instalados) if n in instalados]

    lineas = []
    if instalados:
        nombres = ", ".join(i["nombre"] for i in instalados.values())
        lineas.append(f"Navegadores instalados: {nombres}.")
    else:
        lineas.append("No encontré navegadores instalados (usaría el predeterminado del sistema).")

    if abiertos:
        lineas.append("Abiertos ahora: " + ", ".join(instalados[n]["nombre"] for n in abiertos) + ".")
    else:
        lineas.append("No hay ningún navegador abierto ahora mismo.")

    fijo = navegador_preferido()
    if fijo and fijo in instalados:
        lineas.append(f"Tengo fijado {instalados[fijo]['nombre']} como navegador (no pregunto).")
    elif len(instalados) > 1:
        lineas.append("Cuando me pidas algo en la web y haya más de uno, te pregunto en cuál.")

    otros = programas_abiertos()
    if otros:
        lineas.append("Otros programas abiertos: " + ", ".join(otros) + ".")

    return "\n  ".join(lineas)