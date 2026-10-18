"""
Pruebas de core/control_pc.py (corren en cualquier sistema, sin abrir
navegadores de verdad: todo lo del PC se simula).

Uso:  cd Arche && python prueba_control_pc.py
"""

import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import control_pc as cp

# Los archivos de sitios van a una carpeta temporal: la prueba nunca toca tu Database real.
_TMP = tempfile.mkdtemp()
cp.ARCHIVO_SITIOS_BUSQUEDA = os.path.join(_TMP, "sitios_busqueda.json")
cp.ARCHIVO_SITIOS_ABRIR = os.path.join(_TMP, "sitios.json")

fallos = 0


def chequear(nombre, obtenido, esperado):
    global fallos
    ok = obtenido == esperado
    print(("OK   " if ok else "FALLA"), nombre)
    if not ok:
        fallos += 1
        print(f"      esperado: {esperado!r}\n      obtenido: {obtenido!r}")


# ---------------------------------------------------------- interpretar_busqueda
chequear("busca X en youtube", cp.interpretar_busqueda("busca gatos graciosos en youtube"), ("youtube", "gatos graciosos"))
chequear("buscar X en claude", cp.interpretar_busqueda("Buscar recetas de pasta en Claude"), ("claude", "recetas de pasta"))
chequear("búsqueda con tilde y signos", cp.interpretar_busqueda("¡Búscame música relajante en YouTube!"), ("youtube", "musica relajante"))
chequear("sitio al principio", cp.interpretar_busqueda("busca en youtube tutorial de arduino"), ("youtube", "tutorial de arduino"))
chequear("alias 'yt'", cp.interpretar_busqueda("busca lofi en yt"), ("youtube", "lofi"))
chequear("alias 'chat gpt'", cp.interpretar_busqueda("busca ideas en chat gpt"), ("chatgpt", "ideas"))
chequear("el 'en' en la consulta no confunde", cp.interpretar_busqueda("busca clima en bogota"), None)
chequear("el 'en' en la consulta + sitio", cp.interpretar_busqueda("busca clima en bogota en google"), ("google", "clima en bogota"))
chequear("sin sitio -> None (flujo de siempre)", cp.interpretar_busqueda("busca inteligencia artificial"), None)
chequear("sitio sin consulta -> None", cp.interpretar_busqueda("busca en youtube"), None)
chequear("no es búsqueda -> None", cp.interpretar_busqueda("abre youtube"), None)
chequear("archivo no se confunde", cp.interpretar_busqueda("busca archivo informe"), None)

# ---------------------------------------------------------- url_de_busqueda
chequear("url youtube", cp.url_de_busqueda("youtube", "gatos graciosos"),
         "https://www.youtube.com/results?search_query=gatos+graciosos")
chequear("url claude", cp.url_de_busqueda("claude", "hola & chao"), "https://claude.ai/new?q=hola+%26+chao")
chequear("url sitio desconocido", cp.url_de_busqueda("nada", "x"), None)

# ---------------------------------------------------------- preferencia
chequear("usa siempre chrome", cp.interpretar_preferencia("usa siempre chrome"), ("fijar", "chrome"))
chequear("siempre usa edge", cp.interpretar_preferencia("siempre usa Microsoft Edge"), ("fijar", "edge"))
chequear("preguntame el navegador", cp.interpretar_preferencia("Pregúntame el navegador"), ("preguntar", None))
chequear("frase normal -> None", cp.interpretar_preferencia("abre chrome"), None)

# ---------------------------------------------------------- elegir navegador (simulado)
INSTALADOS = {
    "chrome": {"nombre": "Google Chrome", "ruta": "C:/chrome.exe"},
    "edge": {"nombre": "Microsoft Edge", "ruta": "C:/msedge.exe"},
    "firefox": {"nombre": "Mozilla Firefox", "ruta": "C:/firefox.exe"},
}

with tempfile.TemporaryDirectory() as tmp:
    pref = os.path.join(tmp, "pref.json")
    with mock.patch.object(cp, "ARCHIVO_PREFERENCIA", pref), \
         mock.patch.object(cp, "navegadores_instalados", return_value=INSTALADOS):

        # dos abiertos -> pregunta SOLO entre esos dos
        with mock.patch.object(cp, "navegadores_abiertos", return_value=["chrome", "edge"]), \
             mock.patch.object(cp, "_preguntar", return_value="2") as pregunta:
            chequear("2 abiertos: pregunta y elige edge", cp.elegir_navegador(), ("edge", "C:/msedge.exe"))
            chequear("se preguntó una vez", pregunta.call_count, 1)

        # uno abierto -> lo usa sin preguntar
        with mock.patch.object(cp, "navegadores_abiertos", return_value=["firefox"]), \
             mock.patch.object(cp, "_preguntar") as pregunta:
            chequear("1 abierto: sin preguntar", cp.elegir_navegador(), ("firefox", "C:/firefox.exe"))
            chequear("no se preguntó", pregunta.call_count, 0)

        # ninguno abierto, varios instalados -> pregunta entre los instalados
        with mock.patch.object(cp, "navegadores_abiertos", return_value=[]), \
             mock.patch.object(cp, "_preguntar", return_value="firefox"):
            chequear("ninguno abierto: elige por nombre", cp.elegir_navegador(), ("firefox", "C:/firefox.exe"))

        # respuesta que no se entiende -> predeterminado del sistema
        with mock.patch.object(cp, "navegadores_abiertos", return_value=["chrome", "edge"]), \
             mock.patch.object(cp, "_preguntar", return_value="el rojo"):
            chequear("respuesta rara -> predeterminado", cp.elegir_navegador(), (None, None))

        # "1 siempre" fija la preferencia y ya no vuelve a preguntar
        with mock.patch.object(cp, "navegadores_abiertos", return_value=["chrome", "edge"]), \
             mock.patch.object(cp, "_preguntar", return_value="1 siempre"):
            chequear("'1 siempre' elige chrome", cp.elegir_navegador(), ("chrome", "C:/chrome.exe"))
        chequear("quedó guardada", cp.navegador_preferido(), "chrome")
        with mock.patch.object(cp, "navegadores_abiertos", return_value=["chrome", "edge"]), \
             mock.patch.object(cp, "_preguntar") as pregunta:
            chequear("con preferencia no pregunta", cp.elegir_navegador(), ("chrome", "C:/chrome.exe"))
            chequear("no se preguntó (pref)", pregunta.call_count, 0)
        cp.fijar_navegador_preferido(None)
        chequear("preferencia borrada", cp.navegador_preferido(), None)

        # abrir_url usa el navegador elegido
        with mock.patch.object(cp, "navegadores_abiertos", return_value=["chrome", "edge"]), \
             mock.patch.object(cp, "_preguntar", return_value="1"), \
             mock.patch.object(cp.subprocess, "Popen") as popen:
            chequear("abrir_url devuelve True", cp.abrir_url("https://example.com"), True)
            chequear("lanzó el navegador elegido", popen.call_args[0][0], ["C:/chrome.exe", "https://example.com"])

    # sin navegadores detectados -> cae a webbrowser
    with mock.patch.object(cp, "ARCHIVO_PREFERENCIA", os.path.join(tmp, "p2.json")), \
         mock.patch.object(cp, "navegadores_instalados", return_value={}), \
         mock.patch.object(cp, "navegadores_abiertos", return_value=[]), \
         mock.patch.object(cp.webbrowser, "open", return_value=True) as wb:
        chequear("sin navegadores -> webbrowser", cp.abrir_url("https://example.com"), True)
        chequear("webbrowser recibió la URL", wb.call_args[0][0], "https://example.com")

    # resumen en lenguaje natural
    with mock.patch.object(cp, "ARCHIVO_PREFERENCIA", os.path.join(tmp, "p3.json")), \
         mock.patch.object(cp, "navegadores_instalados", return_value=INSTALADOS), \
         mock.patch.object(cp, "navegadores_abiertos", return_value=["chrome", "edge"]), \
         mock.patch.object(cp, "programas_abiertos", return_value=["Spotify"]):
        r = cp.resumen_del_pc()
        chequear("resumen menciona abiertos", "Abiertos ahora: Google Chrome, Microsoft Edge" in r, True)
        chequear("resumen menciona otros programas", "Spotify" in r, True)

# ---------------------------------------------------------- CUALQUIER sitio
import json
import time
import types

# 1) un sitio que Arché ya sabe ABRIR (sitios.json) ya sirve para buscar
with open(cp.ARCHIVO_SITIOS_ABRIR, "w", encoding="utf-8") as f:
    json.dump({"mercadolibre": "https://www.mercadolibre.com.co", "mi universidad": "https://www.ucundinamarca.edu.co/inicio"}, f)
chequear("sitio de sitios.json", cp.interpretar_busqueda("busca zapatos en mercadolibre"), ("mercadolibre", "zapatos"))
chequear("sitio de dos palabras", cp.interpretar_busqueda("busca horarios en mi universidad"), ("mi universidad", "horarios"))
chequear("url con site: del dominio", cp.url_de_busqueda("mercadolibre", "zapatos rojos"),
         "https://www.google.com/search?q=zapatos+rojos+site%3Amercadolibre.com.co")
chequear("dominio sin www ni ruta", cp.url_de_busqueda("mi universidad", "horarios"),
         "https://www.google.com/search?q=horarios+site%3Aucundinamarca.edu.co")

# 2) un dominio escrito tal cual
chequear("dominio literal", cp.interpretar_busqueda("busca laptops en amazon.com"), ("amazon.com", "laptops"))
chequear("url de dominio literal", cp.url_de_busqueda("amazon.com", "laptops"),
         "https://www.google.com/search?q=laptops+site%3Aamazon.com")
chequear("sitio desconocido sigue siendo None", cp.interpretar_busqueda("busca zapatos en pinterest"), None)

# 3) deducir plantillas (cada sitio separa las palabras distinto)
chequear("plantilla con +", cp.deducir_plantilla("https://x.com/s?q=gatos+graciosos&p=1"), ("https://x.com/s?q={q}&p=1", "+"))
chequear("plantilla con %20", cp.deducir_plantilla("https://x.com/s/gatos%20graciosos"), ("https://x.com/s/{q}", "%20"))
chequear("plantilla con -", cp.deducir_plantilla("https://listado.x.com/gatos-graciosos#D[A:gatos]"), ("https://listado.x.com/{q}#D[A:gatos]", "-"))
chequear("plantilla ya con {q}", cp.deducir_plantilla("https://x.com/?q={q}"), ("https://x.com/?q={q}", "+"))
chequear("URL sin el termino -> None", cp.deducir_plantilla("https://x.com/home"), None)

# 4) ensenar un sitio nuevo de punta a punta y usarlo
with mock.patch.object(cp, "_preguntar", return_value="https://listado.pinterest.com/gatos-graciosos/"):
    chequear("ensenar_sitio_busqueda", cp.ensenar_sitio_busqueda("Pinterest"), True)
chequear("lo aprendido se reconoce", cp.interpretar_busqueda("busca disenos de gatos en pinterest"), ("pinterest", "disenos de gatos"))
chequear("y arma la URL con su separador", cp.url_de_busqueda("pinterest", "disenos de gatos"),
         "https://listado.pinterest.com/disenos-de-gatos/")
with mock.patch.object(cp, "_preguntar", return_value="https://x.com/home"):
    chequear("ensenar con URL mala -> False", cp.ensenar_sitio_busqueda("otro"), False)

# 5) lo que clasifican las redes: 'qué se busca + sitio' juntos
chequear("separar_sitio", cp.separar_sitio("gatos graciosos en youtube"), ("gatos graciosos", "youtube"))
chequear("separar_sitio con varios 'en'", cp.separar_sitio("clima en bogota en google"), ("clima en bogota", "google"))
chequear("separar_sitio sin sitio", cp.separar_sitio("gatos"), ("gatos", None))

# 6) sitio totalmente desconocido: busca la pagina oficial, pregunta, guarda en sitios.json y busca
import core
fake_nav = types.SimpleNamespace(
    _buscar_ddg=lambda consulta, max_results=3: [{"href": "https://www.twitch.tv/"}],
    sitios={},
)
with mock.patch.dict(sys.modules, {"core.navegador": fake_nav}), \
     mock.patch.object(core, "navegador", fake_nav, create=True), \
     mock.patch.object(cp, "_preguntar", return_value="si"), \
     mock.patch.object(cp, "abrir_url", return_value=True) as abrir:
    chequear("desconocido: lo encuentra y busca", cp.buscar_en_sitio("twitch", "speedruns"), True)
    chequear("busca con site: del dominio hallado", abrir.call_args[0][0], "https://www.google.com/search?q=speedruns+site%3Atwitch.tv")
    chequear("lo guardo en el dict de sitios.json", fake_nav.sitios.get("twitch"), "https://www.twitch.tv/")
chequear("y quedo en el archivo", cp._leer_json(cp.ARCHIVO_SITIOS_ABRIR).get("twitch"), "https://www.twitch.tv/")

with mock.patch.dict(sys.modules, {"core.navegador": fake_nav}), \
     mock.patch.object(core, "navegador", fake_nav, create=True), \
     mock.patch.object(cp, "_preguntar", return_value="no"), \
     mock.patch.object(cp, "abrir_url") as abrir:
    chequear("desconocido: dices que no -> False", cp.buscar_en_sitio_desconocido("netflix", "series"), False)
    chequear("y no abre nada", abrir.call_count, 0)

# ---------------------------------------------------------- refuerzo de las redes
fake_aprendizaje = types.SimpleNamespace(aprender=mock.Mock())
import core.IA
with mock.patch.dict(sys.modules, {"core.IA.aprendizaje": fake_aprendizaje}), \
     mock.patch.object(core.IA, "aprendizaje", fake_aprendizaje, create=True):
    cp.aprender_de_uso("busca gatos en youtube", "gatos en youtube")
    time.sleep(0.3)
    chequear("aprender_de_uso manda el ejemplo al banco", fake_aprendizaje.aprender.call_args,
             mock.call("busca gatos en youtube", "buscar_en_sitio", "gatos en youtube", fuente="control_pc"))

# ---------------------------------------------------------- catalogo (redes neuronales)
from core.IA import catalogo

for id_ in ("buscar_en_sitio", "aprender_sitio_busqueda", "que_tengo_abierto", "fijar_navegador", "preguntar_navegador"):
    chequear(f"catalogo tiene {id_}", id_ in catalogo.POR_ID, True)
chequear("dominio 'computador' existe", "computador" in catalogo.dominios_del_catalogo(), True)
chequear("buscar_en_sitio es del dominio web (junto a buscar)", catalogo.POR_ID["buscar_en_sitio"]["dominio"], "web")

# el enrutador NO debe tratar 'busca ...' como comando fijo (si no, saltaria a las redes)
chequear("'busca gatos en youtube' NO es comando fijo", catalogo.es_comando_fijo("busca gatos en youtube"), False)
chequear("'buscame informacion de x' NO es comando fijo", catalogo.es_comando_fijo("buscame informacion de x"), False)
chequear("'que tengo abierto' si es comando fijo", catalogo.es_comando_fijo("que tengo abierto"), True)

# el comando canonico que arma el enrutador lo entiende el manejador de siempre
canon = catalogo.armar_comando(catalogo.POR_ID["fijar_navegador"], "chrome")
chequear("canonico fijar_navegador", canon, "usa siempre chrome")
chequear("...y lo entiende interpretar_preferencia", cp.interpretar_preferencia(canon), ("fijar", "chrome"))
canon = catalogo.armar_comando(catalogo.POR_ID["preguntar_navegador"])
chequear("canonico preguntar_navegador", cp.interpretar_preferencia(canon), ("preguntar", None))

# las semillas se expanden con rellenos que traen el sitio
ejemplos = catalogo.expandir_semillas(catalogo.POR_ID["buscar_en_sitio"], max_por_semilla=1)
chequear("semillas de buscar_en_sitio traen el sitio en el contenido", all(" en " in c for _, c in ejemplos) and len(ejemplos) > 0, True)

# ---------------------------------------------------------- deteccion de navegadores (Opera y otros)
tmp2 = tempfile.mkdtemp()


def _falso_exe(*partes):
    ruta = os.path.join(tmp2, *partes)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    open(ruta, "w").close()
    return ruta


exe_launcher = _falso_exe("Opera", "launcher.exe")
exe_opera = _falso_exe("Opera", "opera.exe")
exe_waterfox = _falso_exe("Waterfox", "waterfox.exe")
exe_ie = _falso_exe("IE", "iexplore.exe")

chequear("comando con comillas y argumentos", cp._ruta_de_comando(f'"{exe_launcher}" --foo'), exe_launcher)
chequear("comando sin comillas con argumentos", cp._ruta_de_comando(f"{exe_waterfox} --profile x"), exe_waterfox)
chequear("id por nombre cuando el exe es generico", cp._id_de_navegador("Opera Stable", exe_launcher), "opera")
chequear("id por ejecutable", cp._id_de_navegador("Lo que sea", "C:/x/msedge.exe"), "edge")
chequear("id nuevo para uno desconocido", cp._id_de_navegador("Waterfox", exe_waterfox), "waterfox")


# winreg falso: solo existe en Windows, asi que se simula el arbol de StartMenuInternet
class _Clave:
    def __init__(self, valores=None, hijos=None):
        self.valores, self.hijos, self.ruta = valores or {}, hijos or [], ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_BASE = r"SOFTWARE\Clients\StartMenuInternet"
_ARBOL = {
    _BASE: _Clave(hijos=["OperaStable", "IEXPLORE.EXE", "Waterfox"]),
    _BASE + r"\OperaStable": _Clave({None: "Opera Stable"}),
    _BASE + r"\OperaStable\shell\open\command": _Clave({None: f'"{exe_launcher}" --foo'}),
    _BASE + r"\IEXPLORE.EXE": _Clave({None: "Internet Explorer"}),
    _BASE + r"\IEXPLORE.EXE\shell\open\command": _Clave({None: exe_ie}),
    _BASE + r"\Waterfox": _Clave({None: "Waterfox"}),
    _BASE + r"\Waterfox\shell\open\command": _Clave({None: exe_waterfox}),
}


def _abrir_clave(raiz, ruta):
    if isinstance(raiz, str):
        if raiz != "HKLM":
            raise OSError("sin datos en HKCU")
        completa = ruta
    else:
        completa = raiz.ruta + "\\" + ruta
    clave = _ARBOL.get(completa)
    if clave is None:
        raise OSError("no existe")
    clave.ruta = completa
    return clave


def _enumerar(clave, i):
    if i >= len(clave.hijos):
        raise OSError("fin")
    return clave.hijos[i]


def _valor(clave, nombre):
    if nombre not in clave.valores:
        raise OSError("sin valor")
    return clave.valores[nombre], 1


winreg_falso = types.SimpleNamespace(HKEY_LOCAL_MACHINE="HKLM", HKEY_CURRENT_USER="HKCU",
                                     OpenKey=_abrir_clave, EnumKey=_enumerar, QueryValueEx=_valor)
with mock.patch.object(cp, "ES_WINDOWS", True), mock.patch.dict(sys.modules, {"winreg": winreg_falso}):
    del_registro = cp._navegadores_del_registro()
chequear("registro de Windows: lee todos", sorted(n for n, _ in del_registro),
         ["Internet Explorer", "Opera Stable", "Waterfox"])

REGISTRO = [("Opera Stable", exe_launcher), ("Internet Explorer", exe_ie), ("Waterfox", exe_waterfox)]
with mock.patch.object(cp, "_ruta_navegador", return_value=None), \
     mock.patch.object(cp, "_navegadores_del_registro", return_value=REGISTRO), \
     mock.patch.object(cp, "_rutas_de_procesos_abiertos", return_value={}), \
     mock.patch.object(cp, "ARCHIVO_NAVEGADORES_EXTRA", os.path.join(tmp2, "extra.json")):
    inst = cp.navegadores_instalados()
chequear("Opera aparece aunque su exe sea launcher.exe", inst.get("opera"), {"nombre": "Opera", "ruta": exe_launcher})
chequear("navegador que no conocia aparece", inst.get("waterfox"), {"nombre": "Waterfox", "ruta": exe_waterfox})
chequear("Internet Explorer no cuenta", [k for k in inst if "explorer" in k], [])

with mock.patch.object(cp, "_ruta_navegador", return_value=None), \
     mock.patch.object(cp, "_navegadores_del_registro", return_value=[]), \
     mock.patch.object(cp, "_rutas_de_procesos_abiertos", return_value={"opera.exe": exe_opera}), \
     mock.patch.object(cp, "ARCHIVO_NAVEGADORES_EXTRA", os.path.join(tmp2, "extra.json")):
    chequear("si esta abierto, su proceso dice donde esta", cp.navegadores_instalados().get("opera", {}).get("ruta"), exe_opera)

extra = os.path.join(tmp2, "extra2.json")
with open(extra, "w", encoding="utf-8") as f:
    json.dump({"opera": {"nombre": "Opera", "ruta": exe_opera}, "fantasma": {"nombre": "X", "ruta": "C:/no/existe.exe"}}, f)
with mock.patch.object(cp, "_ruta_navegador", return_value=None), \
     mock.patch.object(cp, "_navegadores_del_registro", return_value=[]), \
     mock.patch.object(cp, "_rutas_de_procesos_abiertos", return_value={}), \
     mock.patch.object(cp, "ARCHIVO_NAVEGADORES_EXTRA", extra):
    inst = cp.navegadores_instalados()
chequear("los que tu ensenaste se usan", inst.get("opera", {}).get("ruta"), exe_opera)
chequear("una ruta enseñada que ya no existe se ignora", "fantasma" in inst, False)

# abiertos: por proceso; 'launcher.exe' generico no cuenta como navegador
inst3 = {"opera": {"nombre": "Opera", "ruta": exe_launcher}, "waterfox": {"nombre": "Waterfox", "ruta": exe_waterfox},
         "chrome": {"nombre": "Google Chrome", "ruta": "C:/chrome.exe"}}
with mock.patch.object(cp, "_nombres_de_procesos_abiertos", return_value={"opera.exe", "launcher.exe", "waterfox.exe"}):
    chequear("abiertos por proceso (opera conocido, waterfox desconocido)", cp.navegadores_abiertos(inst3), ["opera", "waterfox"])
inst_gen = {"raro": {"nombre": "Raro", "ruta": os.path.join(tmp2, "Opera", "launcher.exe")}}
with mock.patch.object(cp, "_nombres_de_procesos_abiertos", return_value={"launcher.exe"}):
    chequear("exe generico no se toma por navegador abierto", cp.navegadores_abiertos(inst_gen), [])

# 'usa siempre X': solo si X existe
solo_chrome = {"chrome": {"nombre": "Google Chrome", "ruta": "C:/chrome.exe"}}
with mock.patch.object(cp, "ARCHIVO_PREFERENCIA", os.path.join(tmp2, "pref.json")), \
     mock.patch.object(cp, "navegadores_instalados", return_value=solo_chrome), \
     mock.patch.object(cp, "_preguntar", return_value="no"):
    ok, msg = cp.fijar_navegador("opera")
    chequear("usa siempre opera sin Opera -> no lo fija", ok, False)
    chequear("...y dice cuales si encuentra", "Google Chrome" in msg and "no cambié nada" in msg, True)
    chequear("...y no guardo nada", cp.navegador_preferido(), None)
    ok, msg = cp.fijar_navegador("chrome")
    chequear("usa siempre chrome (instalado) -> lo fija", (ok, cp.navegador_preferido()), (True, "chrome"))
    cp.fijar_navegador_preferido(None)

# ...y si no lo encuentra, le dices donde esta y queda aprendido
with mock.patch.object(cp, "ARCHIVO_PREFERENCIA", os.path.join(tmp2, "pref2.json")), \
     mock.patch.object(cp, "ARCHIVO_NAVEGADORES_EXTRA", os.path.join(tmp2, "extra3.json")), \
     mock.patch.object(cp, "_ruta_navegador", return_value=None), \
     mock.patch.object(cp, "_navegadores_del_registro", return_value=[]), \
     mock.patch.object(cp, "_rutas_de_procesos_abiertos", return_value={}), \
     mock.patch.object(cp, "_preguntar", return_value=f'"{exe_opera}"'):
    ok, msg = cp.fijar_navegador("opera")
    chequear("le ensenas la ruta de Opera -> queda fijado", (ok, cp.navegador_preferido()), (True, "opera"))
    chequear("...y se acuerda de la ruta", cp._leer_json(cp.ARCHIVO_NAVEGADORES_EXTRA).get("opera", {}).get("ruta"), exe_opera)

with mock.patch.object(cp, "navegadores_instalados", return_value={"waterfox": {"nombre": "Waterfox", "ruta": exe_waterfox}}):
    chequear("'usa siempre' tambien con navegadores desconocidos", cp.interpretar_preferencia("usa siempre waterfox"), ("fijar", "waterfox"))

# ---------------------------------------------------------- sembrar catalogo: reentrena UNA vez, sin avisos de sklearn
import warnings
from core.IA import aprendizaje, entrenador_masivo

llamadas = {"aprender": 0, "reentrenar": 0, "umbral_durante": set()}


def _aprender_falso(*a, **k):
    llamadas["aprender"] += 1
    llamadas["umbral_durante"].add(aprendizaje.UMBRAL_REENTRENO)


def _reentrenar_falso():
    llamadas["reentrenar"] += 1


umbral_antes = aprendizaje.UMBRAL_REENTRENO
with mock.patch.object(aprendizaje, "aprender", _aprender_falso), \
     mock.patch.object(aprendizaje, "reentrenar_ahora", _reentrenar_falso):
    agregados = entrenador_masivo.sembrar_catalogo(silencioso=True)
chequear("sembrar_catalogo siembra ejemplos", agregados > 0 and llamadas["aprender"] == agregados, True)
chequear("durante la siembra el reentreno automatico esta apagado", llamadas["umbral_durante"], {float("inf")})
chequear("reentrena UNA sola vez al final", llamadas["reentrenar"], 1)
chequear("el umbral vuelve a su valor", aprendizaje.UMBRAL_REENTRENO, umbral_antes)


def _entrenar_con_aviso(*a, **k):
    warnings.warn("The least populated class in y has only 1 members, which is less than n_splits=2.", UserWarning)
    return True


fake_clasif = types.SimpleNamespace(entrenar=_entrenar_con_aviso)
fake_jerar = types.SimpleNamespace(entrenar_jerarquico=lambda silencioso=False: {"dominio": True, "web": False})
with tempfile.TemporaryDirectory() as tmp_meta, \
     mock.patch.object(aprendizaje, "ARCHIVO_META", os.path.join(tmp_meta, "meta.json")), \
     mock.patch.dict(sys.modules, {"core.IA.clasificador": fake_clasif, "core.IA.clasificador_jerarquico": fake_jerar}), \
     mock.patch.object(core.IA, "clasificador", fake_clasif, create=True), \
     mock.patch.object(core.IA, "clasificador_jerarquico", fake_jerar, create=True):
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        aprendizaje.reentrenar_ahora()
    chequear("reentrenar_ahora no muestra el aviso de sklearn", [str(a.message) for a in avisos if "least populated" in str(a.message)], [])

print()
print("TODO OK" if fallos == 0 else f"{fallos} prueba(s) fallaron")
sys.exit(1 if fallos else 0)