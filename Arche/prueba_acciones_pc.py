"""
Pruebas de core/acciones_pc.py. Corren en cualquier sistema: todo lo que toca
Windows (teclas, ventanas, PowerShell, apagado) se simula, asi que NO mueve
nada de tu computador.

Uso:  cd Arche && python prueba_acciones_pc.py
"""

import contextlib
import ctypes
import io
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import acciones_pc as ap
from core import control_pc
from core.IA import catalogo

fallos = 0


def chequear(nombre, obtenido, esperado):
    global fallos
    ok = obtenido == esperado
    print(("OK   " if ok else "FALLA"), nombre)
    if not ok:
        fallos += 1
        print(f"      esperado: {esperado!r}\n      obtenido: {obtenido!r}")


def id_de(frase):
    r = ap.interpretar(frase)
    return r[0] if r else None


# ---------------------------------------------------------- interpretar
CASOS = {
    "sube el volumen": "subir_volumen", "mas volumen": "subir_volumen", "sube un poco el volumen": "subir_volumen",
    "sube el volumen en 20": "subir_volumen", "baja el volumen": "bajar_volumen", "baja el volumen en 20": "bajar_volumen",
    "menos volumen": "bajar_volumen", "sube el volumen a 50": "volumen_a", "pon el volumen al 40": "volumen_a",
    "pon el volumen en 30": "volumen_a", "volumen al 70": "volumen_a", "pon el volumen al maximo": "volumen_a",
    "silencia": "silenciar", "mutea el pc": "silenciar", "pausa la musica": "pausar_reproducir", "dale play": "pausar_reproducir",
    "siguiente cancion": "siguiente_cancion", "pasa a la siguiente cancion": "siguiente_cancion",
    "cancion anterior": "cancion_anterior", "sube el brillo": "subir_brillo", "baja el brillo": "bajar_brillo",
    "pon el brillo al 60": "brillo_a", "toma una captura de pantalla": "captura_pantalla", "screenshot": "captura_pantalla",
    "minimiza todo": "mostrar_escritorio", "muestra el escritorio": "mostrar_escritorio",
    "minimiza chrome": "minimizar_ventana", "maximiza word": "maximizar_ventana", "pon chrome en pantalla completa": "maximizar_ventana",
    "cierra discord": "cerrar_ventana", "cierra la sesion": "cerrar_sesion", "pasa a spotify": "enfocar_ventana",
    "pon chrome a la izquierda": "acomodar_ventana", "teclea hola en bloc de notas": "teclear_texto",
    "presiona ctrl+t en chrome": "presionar_tecla", "bloquea el pc": "bloquear_pc",
    "apaga el pc": "apagar_pc", "reinicia el equipo": "reiniciar_pc", "suspende el pc": "suspender_pc",
    "cancela el apagado": "cancelar_apagado", "cuanta bateria tengo": "ver_bateria",
    "que hay en el portapapeles": "ver_portapapeles", "copia al portapapeles hola": "copiar_portapapeles",
    "copia hola mundo al portapapeles": "copiar_portapapeles", "abre la carpeta descargas": "abrir_carpeta",
    "abre mis documentos": "abrir_carpeta", "espera 3 segundos": "esperar", "mis ventanas": "listar_ventanas",
}
for frase, esperado in CASOS.items():
    chequear(f"'{frase}' -> {esperado}", id_de(frase), esperado)

# frases que NO son del control del PC: tienen que seguir su camino de siempre
for frase in ("busca gatos en youtube", "abre youtube", "calcula 2+2", "hola", "que hora es", "crea una nota compras",
              "escribe en core/x.py : algo", "minimiza", "cierra", "estado del sistema", "abre archivo informe"):
    chequear(f"'{frase}' no es del PC", id_de(frase), None)

# "teclea" conserva mayusculas y tildes del texto
chequear("teclea conserva el texto tal cual", ap.interpretar("teclea Hola, ¿Qué Tal?")[1]["x"], "Hola, ¿Qué Tal?")

# ---------------------------------------------------------- atajos y pasos
chequear("atajo ctrl+shift+t", ap.parsear_atajo("ctrl+shift+t"), ["ctrl", "shift", "t"])
chequear("atajo en espanol 'control + c'", ap.parsear_atajo("control + c"), ["ctrl", "c"])
chequear("atajo 'alt tab'", ap.parsear_atajo("alt tab"), ["alt", "tab"])
chequear("atajo f5", ap.parsear_atajo("f5"), ["f5"])
chequear("atajo desconocido", ap.parsear_atajo("hola mundo"), None)
chequear("dividir en pasos", ap.dividir_pasos("abre chrome y luego busca gatos en youtube"), ["abre chrome", "busca gatos en youtube"])
chequear("dividir con ';' y 'despues'", ap.dividir_pasos("sube el volumen; baja el brillo despues captura de pantalla"),
         ["sube el volumen", "baja el brillo", "captura de pantalla"])
chequear("no parte una nota que dice 'luego'", ap.dividir_pasos("crea una nota comprar leche y luego llamar a mama"),
         ["crea una nota comprar leche y luego llamar a mama"])
chequear("una sola orden queda igual", ap.dividir_pasos("abre chrome"), ["abre chrome"])

# la estructura de INPUT de Windows tiene que medir lo que Windows espera (40 bytes en 64 bits, 28 en 32)
chequear("tamano de INPUT correcto", ctypes.sizeof(ap._INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

# ---------------------------------------------------------- catalogo <-> acciones
todo_computador = [e for e in catalogo.ENTRADAS if e["dominio"] == "computador"]
# voz, alarmas, rutinas y mantenimiento los manejan sus propios modulos (prueba_modulos_nuevos.py)
computador = [e for e in todo_computador if e["subdominio"] not in ("voz", "alarmas", "rutinas", "mantenimiento")]
propias_de_control_pc = {"que_tengo_abierto", "fijar_navegador", "preguntar_navegador"}
for e in computador:
    if e["id"] in propias_de_control_pc:
        continue
    rellenos = catalogo.RELLENOS.get(e.get("argumento"), [""]) if "{X}" in e["comando"] else [""]
    ok = all(id_de(e["comando"].replace("{X}", r).strip()) == e["id"] for r in rellenos)
    chequear(f"el comando del catalogo de {e['id']} lo entiende acciones_pc", ok, True)
ids_catalogo = {e["id"] for e in computador} - propias_de_control_pc
chequear("toda accion con catalogo existe en ACCIONES", ids_catalogo <= set(ap.ACCIONES), True)
chequear("toda accion (menos las internas) esta en el catalogo",
         set(ap.ACCIONES) - {"esperar", "listar_ventanas"} <= ids_catalogo, True)
chequear("todos los comandos del dominio estan en un subdominio", all(e.get("subdominio") for e in todo_computador), True)
chequear("el dominio computador se entrena en 3 niveles", catalogo.tiene_subdominios("computador"), True)

# ---------------------------------------------------------- acciones (todo simulado)
PROPIAS = {1}
V = [
    {"hwnd": 100, "titulo": "Terminal - py main.py", "pid": 1, "exe": "windowsterminal.exe", "minimizada": False},
    {"hwnd": 101, "titulo": "YouTube - Google Chrome", "pid": 10, "exe": "chrome.exe", "minimizada": False},
    {"hwnd": 102, "titulo": "Gmail - Google Chrome", "pid": 10, "exe": "chrome.exe", "minimizada": False},
    {"hwnd": 103, "titulo": "Spotify Premium", "pid": 20, "exe": "spotify.exe", "minimizada": False},
    {"hwnd": 104, "titulo": "Sin titulo: Bloc de notas", "pid": 30, "exe": "notepad.exe", "minimizada": True},
    {"hwnd": 105, "titulo": "Nueva pestana - Microsoft Edge", "pid": 40, "exe": "msedge.exe", "minimizada": False},
    {"hwnd": 106, "titulo": "Hilo de edge cases - Opera", "pid": 50, "exe": "opera.exe", "minimizada": False},
]


class Mundo:
    """Reemplaza todo lo que toca Windows y apunta lo que Arché habría hecho."""

    def __init__(self, respuestas=(), windows=True, ventanas=None):
        self.teclas, self.textos, self.enfocadas, self.mostradas = [], [], [], []
        self.cerradas, self.comandos, self.shells, self.ps = [], [], [], []
        self.bloqueos = 0
        self.respuestas = list(respuestas)
        self.preguntas = 0
        self.windows = windows
        self.ventanas = V if ventanas is None else ventanas
        self.salida = io.StringIO()
        self.codigo_shutdown = 0

    def _preguntar(self, texto):
        self.preguntas += 1
        return self.respuestas.pop(0) if self.respuestas else ""

    def __enter__(self):
        self.pilas = contextlib.ExitStack()
        e = self.pilas.enter_context
        e(mock.patch.object(control_pc, "ES_WINDOWS", self.windows))
        e(mock.patch.object(control_pc, "_preguntar", self._preguntar))
        e(mock.patch.object(ap, "_tecla", lambda n: self.teclas.append(list(n))))
        e(mock.patch.object(ap, "_escribir_texto", lambda t: self.textos.append(t)))
        e(mock.patch.object(ap, "_ventanas_visibles", lambda: list(self.ventanas)))
        e(mock.patch.object(ap, "_pids_propios", lambda: PROPIAS))
        e(mock.patch.object(ap, "_enfocar", lambda h: self.enfocadas.append(h) or True))
        e(mock.patch.object(ap, "_mostrar_ventana", lambda h, m: self.mostradas.append((h, m))))
        e(mock.patch.object(ap, "_cerrar_ventana_hwnd", lambda h: self.cerradas.append(h)))
        e(mock.patch.object(ap, "_abrir_shell", lambda d: self.shells.append(d)))
        e(mock.patch.object(ap, "_bloquear_estacion", lambda: setattr(self, "bloqueos", self.bloqueos + 1)))
        e(mock.patch.object(ap, "_ejecutar", lambda a: self.comandos.append(list(a)) or self.codigo_shutdown))
        e(mock.patch.object(ap.time, "sleep", lambda s: None))
        e(contextlib.redirect_stdout(self.salida))
        return self

    def __exit__(self, *a):
        self.pilas.close()

    def dice(self, texto):
        return texto in self.salida.getvalue()


# ventanas ----------------------------------------------------------
with Mundo() as m:
    r = ap.manejar("pasa a spotify")
chequear("pasa a spotify: devuelve la intencion", r, ("enfocar_ventana", "spotify"))
chequear("pasa a spotify: trae esa ventana", m.enfocadas, [103])

with Mundo() as m:
    r = ap.manejar("ve a youtube")
chequear("'ve a youtube' lo hace Arché normal si no hay ventana asi... pero YouTube SI esta en Chrome", r, ("enfocar_ventana", "youtube"))

with Mundo(ventanas=[v for v in V if "YouTube" not in v["titulo"]]) as m:
    r = ap.manejar("ve a youtube")
chequear("'ve a youtube' sin esa ventana: no es mio (None, sigue el flujo normal)", (r, m.enfocadas), (None, []))

with Mundo() as m:
    ap.manejar("minimiza chrome")
chequear("minimiza chrome: la de arriba, minimizada", m.mostradas, [(101, 6)])

with Mundo() as m:
    ap.manejar("maximiza spotify")
chequear("maximiza spotify", (m.mostradas, m.enfocadas), ([(103, 3)], [103]))

with Mundo() as m:
    ap.manejar("minimiza esto")
chequear("'minimiza esto' usa la ventana de antes de la terminal, nunca la terminal", m.mostradas, [(101, 6)])

with Mundo() as m:
    ap.manejar("minimiza zoom")
chequear("ventana que no existe: avisa y no toca nada", (m.mostradas, m.dice("No veo ninguna ventana de 'zoom'")), ([], True))

with Mundo(respuestas=["2"]) as m:
    ap.manejar("minimiza edge")
chequear("dos programas distintos coinciden: pregunta cual", (m.preguntas, m.mostradas), (1, [(106, 6)]))

with Mundo() as m:
    ap.manejar("pon chrome a la izquierda")
chequear("acomoda: enfoca y manda Win+Izquierda", (m.enfocadas, m.teclas), ([101], [["win", "left"]]))

with Mundo() as m:
    ap.manejar("muestra el escritorio")
chequear("muestra el escritorio: Win+D", m.teclas, [["win", "d"]])

with Mundo(respuestas=["n"]) as m:
    ap.manejar("cierra chrome")
chequear("cierra chrome (2 ventanas), dices que no: no cierra nada", (m.preguntas, m.cerradas), (1, []))

with Mundo(respuestas=["s"]) as m:
    ap.manejar("cierra chrome")
chequear("cierra chrome (2 ventanas), dices que si: cierra las 2", sorted(m.cerradas), [101, 102])

with Mundo() as m:
    ap.manejar("cierra spotify")
chequear("cierra spotify (1 ventana): sin preguntar", (m.preguntas, m.cerradas), (0, [103]))

with Mundo() as m:
    ap.manejar("cierra terminal")
chequear("nunca cierra su propia terminal", (m.cerradas, m.dice("ciérrala tú")), ([], True))

proceso = mock.Mock()
proceso.info = {"name": "OneDrive.exe"}
with Mundo(respuestas=["s"], ventanas=[]) as m, mock.patch.object(ap, "_procesos_por_nombre", return_value=[proceso]):
    ap.manejar("cierra onedrive")
chequear("programa sin ventana: confirma y lo termina", (m.preguntas, proceso.terminate.called), (1, True))

protegido = mock.Mock()
protegido.info = {"name": "svchost.exe"}
with Mundo(respuestas=["s"], ventanas=[]) as m, mock.patch.object(ap, "_procesos_por_nombre", return_value=[protegido]):
    ap.manejar("cierra svchost")
chequear("procesos del sistema: no los toca", (m.preguntas, protegido.terminate.called), (0, False))

# teclado y mouse -----------------------------------------------------
with Mundo() as m:
    r = ap.manejar("teclea hola mundo en bloc de notas")
chequear("teclea en una ventana nombrada", (m.enfocadas, m.textos), ([104], ["hola mundo"]))

with Mundo() as m:
    ap.manejar("teclea hola en la playa")
chequear("'en la playa' no es una ventana: todo es texto, a la ventana de antes", (m.enfocadas, m.textos), ([101], ["hola en la playa"]))

with Mundo() as m:
    ap.manejar("presiona ctrl+t en chrome")
chequear("presiona atajo en una ventana", (m.enfocadas, m.teclas), ([101], [["ctrl", "t"]]))

with Mundo() as m:
    ap.manejar("presiona enter")
chequear("presiona sin destino: la ventana de antes (nunca la terminal)", (m.enfocadas, m.teclas), ([101], [["enter"]]))

with Mundo() as m:
    ap.manejar("presiona blablabla")
chequear("tecla desconocida: no manda nada", (m.teclas, m.enfocadas), ([], []))

with Mundo(ventanas=[V[0]]) as m:
    ap.manejar("teclea hola")
chequear("si solo existe la terminal: no teclea en ella", (m.textos, m.dice("No encuentro la ventana")), ([], True))

with Mundo() as m:
    ap.manejar("teclea " + "x" * 600)
chequear("texto demasiado largo: no lo teclea", m.textos, [])

# sonido -------------------------------------------------------------
with Mundo() as m:
    ap.manejar("sube el volumen")
chequear("sube el volumen: 5 pulsaciones (10%)", m.teclas, [["volume_up"]] * 5)

with Mundo() as m:
    ap.manejar("baja el volumen en 20")
chequear("baja el volumen en 20: 10 pulsaciones", m.teclas, [["volume_down"]] * 10)

with Mundo() as m:
    ap.manejar("pon el volumen al 50")
chequear("volumen al 50: al fondo (50) y sube 25", m.teclas, [["volume_down"]] * 50 + [["volume_up"]] * 25)

with Mundo() as m:
    ap.manejar("pon el volumen al maximo")
chequear("volumen al maximo", m.teclas[-50:], [["volume_up"]] * 50)

with Mundo() as m:
    ap.manejar("silencia"), ap.manejar("pausa la musica"), ap.manejar("siguiente cancion"), ap.manejar("cancion anterior")
chequear("teclas multimedia", m.teclas, [["volume_mute"], ["play_pause"], ["next"], ["prev"]])

# brillo y captura -----------------------------------------------------
with Mundo() as m, mock.patch.object(ap, "_brillo_actual", return_value=50), \
        mock.patch.object(ap, "_poner_brillo", return_value=True) as poner:
    ap.manejar("sube el brillo")
    ap.manejar("baja el brillo en 10")
chequear("brillo relativo", [c.args[0] for c in poner.call_args_list], [70, 40])

with Mundo() as m, mock.patch.object(ap, "_poner_brillo", return_value=True) as poner:
    ap.manejar("pon el brillo al 30")
chequear("brillo absoluto", poner.call_args.args[0], 30)

with Mundo() as m, mock.patch.object(ap, "_brillo_actual", return_value=None), \
        mock.patch.object(ap, "_poner_brillo") as poner:
    ap.manejar("sube el brillo")
chequear("brillo ilegible (monitor externo): avisa y no inventa", (poner.called, m.dice("No pude leer el brillo")), (False, True))

with Mundo() as m, mock.patch.object(ap, "_powershell", return_value=(True, "C:\\Users\\x\\Pictures\\Capturas de Arche\\captura 1.png")):
    ap.manejar("toma una captura de pantalla")
chequear("captura: dice donde quedo", m.dice("Capturas de Arche"), True)

# el equipo ----------------------------------------------------------
with Mundo() as m:
    ap.manejar("bloquea el pc")
chequear("bloquear", m.bloqueos, 1)

with Mundo(respuestas=["n"]) as m:
    ap.manejar("apaga el pc")
chequear("apagar: dices que no -> NO se ejecuta nada", (m.preguntas, m.comandos), (1, []))

with Mundo(respuestas=["s"]) as m:
    ap.manejar("apaga el pc")
chequear("apagar: dices que si -> shutdown con 30 s de margen", m.comandos, [["shutdown", "/s", "/t", "30"]])

with Mundo(respuestas=["si"]) as m:
    ap.manejar("reinicia el pc")
chequear("reiniciar con confirmacion", m.comandos, [["shutdown", "/r", "/t", "30"]])

with Mundo(respuestas=["no"]) as m:
    ap.manejar("cierra la sesion")
chequear("cerrar sesion: dices que no", m.comandos, [])

with Mundo(respuestas=["s"]) as m:
    ap.manejar("cierra la sesion")
chequear("cerrar sesion: dices que si", m.comandos, [["shutdown", "/l"]])

with Mundo() as m:
    ap.manejar("cancela el apagado")
chequear("cancelar apagado", m.comandos, [["shutdown", "/a"]])

with Mundo() as m:
    m.codigo_shutdown = 1
    ap.manejar("cancela el apagado")
chequear("cancelar sin nada programado: lo dice", m.dice("No había ningún apagado"), True)

bateria = types.SimpleNamespace(percent=87.0, power_plugged=False, secsleft=7500)
with Mundo() as m, mock.patch.object(ap, "psutil", types.SimpleNamespace(sensors_battery=lambda: bateria)):
    ap.manejar("cuanta bateria tengo")
chequear("bateria: porcentaje y tiempo", (m.dice("87%"), m.dice("2 h 5 min")), (True, True))

with Mundo() as m, mock.patch.object(ap, "psutil", types.SimpleNamespace(sensors_battery=lambda: None)):
    ap.manejar("cuanta bateria tengo")
chequear("equipo de escritorio sin bateria", m.dice("no reporta batería"), True)

with Mundo() as m, mock.patch.object(ap, "_powershell", return_value=(True, "texto copiado")) as ps:
    ap.manejar("que hay en el portapapeles")
chequear("ver portapapeles", (ps.call_args.args[0], m.dice("texto copiado")), ("Get-Clipboard -Raw", True))

with Mundo() as m, mock.patch.object(ap, "_powershell", return_value=(True, "")) as ps:
    ap.manejar("copia al portapapeles Hola ñandú")
import base64
chequear("copiar portapapeles: manda el texto intacto (tildes/ñ) en base64",
         base64.b64encode("Hola ñandú".encode("utf-8")).decode() in ps.call_args.args[0], True)

with Mundo() as m:
    ap.manejar("abre la carpeta descargas"), ap.manejar("abre mis documentos")
chequear("abrir carpetas conocidas", m.shells, ["shell:Downloads", "shell:Personal"])

# ventanas abiertas (para 'que tengo abierto') -------------------------
with Mundo():
    lineas = ap.listar_ventanas_texto()
chequear("lista de ventanas: no incluye la terminal de Arché", any("Terminal - py main.py" in l for l in lineas), False)
chequear("lista de ventanas: si incluye Spotify", any("Spotify" in l for l in lineas), True)
chequear("lista de ventanas: marca las minimizadas", any("Bloc de notas" in l and "[minimizada]" in l for l in lineas), True)

# robustez -----------------------------------------------------------
with Mundo() as m:
    with mock.patch.object(ap, "_tecla", side_effect=OSError("boom")):
        r = ap.manejar("sube el volumen")
chequear("si una accion falla, Arché no se cae y lo dice", (r, m.dice("No pude hacerlo")), (("subir_volumen", ""), True))

with Mundo(windows=False) as m:
    r = ap.manejar("sube el volumen")
chequear("fuera de Windows: lo dice y no toca nada", (r[0], m.teclas, m.dice("solo lo sé hacer en Windows")), ("subir_volumen", [], True))

with Mundo(windows=False) as m:
    r = ap.manejar("pasa a spotify")
chequear("fuera de Windows, orden suave: sigue el flujo normal", r, None)

with Mundo(windows=False) as m:
    r = ap.manejar("espera 0")
chequear("'espera' funciona en cualquier sistema", r, ("esperar", "0"))

print()
print("TODO OK" if fallos == 0 else f"{fallos} prueba(s) fallaron")
sys.exit(1 if fallos else 0)