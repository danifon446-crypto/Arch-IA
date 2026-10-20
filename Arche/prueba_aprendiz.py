"""
prueba_aprendiz.py
------------------
Ubicacion: Arche/prueba_aprendiz.py

Prueba (sin internet, sin Ollama, sin tocar tu Database ni tu aprendizaje):
  * modo aprendiz: Arche contesta primero con Ollama, la nube revisa en segundo plano, y aprende
    segun coincidan o no; datos de hoy y fallos de Ollama siguen yendo a la nube; cupo diario.
  * comandos: 'responde tu primero', 'responde la nube primero', 'estado aprendiz'.
  * examen: la exigencia sube con el nivel, un acierto con poca seguridad no cuenta, la nube
    confirma fallos antes de aprender, y el examen automatico devuelve su hilo (se puede frenar).

Correr:  python prueba_aprendiz.py
"""
import os
import sys
import tempfile
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.IA import aprender_de_nube as an, aprendiz, cerebro, examen, nube, nube_tareas, respuestas  # noqa: E402

fallos = []


def chequear(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}")
    else:
        print(f"FALLA {nombre}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")
        fallos.append(nombre)


CFG = {}
guardadas, charlas, llamadas_nube, apuntes = [], [], [], []
ESTADO = {"ollama": "El sol es una estrella enorme de gas caliente que da luz y calor a la Tierra.",
          "nube": "El sol es una estrella gigante de gas caliente que da luz y calor a nuestro planeta."}


def nube_responder(mensajes, sistema=None, max_tokens=0, temperature=0):
    llamadas_nube.append(mensajes[-1]["content"])
    return ESTADO["nube"]


parches = [
    mock.patch.object(nube, "_leer_config", lambda: CFG),
    mock.patch.object(nube, "_guardar_config", lambda d: None),
    mock.patch.object(nube, "configurada", lambda prov=None: True),
    mock.patch.object(nube, "disponible", lambda: True),
    mock.patch.object(nube, "modo", lambda: "auto"),
    mock.patch.object(nube, "responder", nube_responder),
    mock.patch.object(cerebro, "_ollama", lambda p: ESTADO["ollama"]),
    mock.patch.object(respuestas, "guardar_respuesta", lambda q, t: guardadas.append((q, t))),
    mock.patch.object(an, "aprender_de_charla", lambda q, t, volatil=False: charlas.append((q, t))),
    mock.patch.object(an, "_apuntar", lambda *a, **k: apuntes.append(a)),
    mock.patch.object(an, "activo", lambda: True),
    mock.patch.object(cerebro.web, "hay_internet", lambda: False),
]
for p in parches:
    p.start()


def limpiar():
    CFG.clear()
    for lista in (guardadas, charlas, llamadas_nube, apuntes):
        lista.clear()


P = "como funciona el sol en el sistema solar"

# ---- parecido / coincidencia
chequear("parecido: textos casi iguales coinciden", aprendiz.coinciden(ESTADO["ollama"], ESTADO["nube"]), True)
chequear("parecido: textos distintos NO coinciden",
         aprendiz.coinciden("La capital de Francia es Paris.", "El sol es una estrella de gas caliente."), False)
chequear("parecido: vacio no coincide", aprendiz.coinciden("", "algo"), False)

# ---- por defecto esta activado y respeta el modo solo-nube
limpiar()
chequear("aprendiz: activado por defecto", aprendiz.activo(), True)
chequear("aprendiz: pregunta normal se contesta local", aprendiz.debe_responder_local(P), True)
chequear("aprendiz: dato de hoy NO se contesta local", aprendiz.debe_responder_local("cual es el precio del dolar hoy"), False)
with mock.patch.object(nube, "modo", lambda: "nube"):
    chequear("aprendiz: modo solo nube no contesta local", aprendiz.debe_responder_local(P), False)

# ---- coinciden: contesta Ollama, nube revisa, guarda la local en cache
limpiar()
r = cerebro.responder(P)
chequear("responder: contesta Ollama primero", (r["texto"], r["fuente"]), (ESTADO["ollama"], "ollama"))
chequear("responder: no se cachea por su cuenta (lo decide la revision)", r["cacheable"], False)
for t in threading.enumerate():
    if t.name == "aprendiz":
        t.join(timeout=5)          # la revision sale sola en segundo plano al contestar
chequear("revision: pregunto a la nube", llamadas_nube, [P])
chequear("revision: coincidia -> guarda la respuesta local", guardadas, [(P, ESTADO["ollama"])])
chequear("revision: coincidia -> no pide correccion", charlas, [])
chequear("revision: cuenta coincidencias", (aprendiz._stats()["revisadas"], aprendiz._stats()["coinciden"]), (1, 1))

# ---- difieren: aprende la de la nube
limpiar()
ESTADO["ollama"] = "Es un objeto muy grande en el cielo que todos conocemos bien."
aprendiz.revisar(P, ESTADO["ollama"], sincrono=True)
chequear("revision: difiere -> aprende la de la nube", charlas, [(P, ESTADO["nube"])])
chequear("revision: difiere -> NO guarda la local", guardadas, [])
chequear("revision: cuenta correcciones", aprendiz._stats()["corregidas"], 1)
ESTADO["ollama"] = "El sol es una estrella enorme de gas caliente que da luz y calor a la Tierra."

# ---- no gasta nube en lo que no vale la pena
limpiar()
for q in ["hola", "que puedes hacer tu", "sube el volumen un poco mas", "cual es el clima hoy en bogota"]:
    aprendiz.revisar(q, "respuesta cualquiera larga de prueba", sincrono=True)
chequear("revision: saludos, preguntas sobre Arche, ordenes y datos de hoy no gastan nube", llamadas_nube, [])

# ---- cupo diario
limpiar()
CFG["aprendiz"] = {"fecha": __import__("datetime").date.today().isoformat(), "hoy": aprendiz.TOPE_REVISIONES_DIA}
aprendiz.revisar(P, ESTADO["ollama"], sincrono=True)
chequear("cupo: agotado el dia no llama a la nube", llamadas_nube, [])
CFG["aprendiz"]["fecha"] = "2000-01-01"
chequear("cupo: otro dia se renueva", aprendiz.revisiones_restantes(), aprendiz.TOPE_REVISIONES_DIA)

# ---- nube caida / limite
limpiar()


def nube_cae(*a, **k):
    raise nube.ErrorNube("429", 429) if False else nube.ErrorNube("limite", 429)


with mock.patch.object(nube, "responder", nube_cae):
    try:
        aprendiz.revisar(P, ESTADO["ollama"], sincrono=True)
        ok = True
    except Exception:
        ok = False
chequear("nube caida: la revision no rompe nada", (ok, guardadas, charlas), (True, [], []))

# ---- Ollama falla -> contesta la nube como antes
limpiar()
with mock.patch.object(cerebro, "_ollama", lambda p: "No puedo conectarme a Ollama ahora mismo. Fijate que esté corriendo (ollama serve)."), \
        mock.patch.object(cerebro, "pensar", lambda p, c=None, max_tokens=500: ("respuesta de la nube", "nube", "")):
    r = cerebro.responder(P)
chequear("Ollama caido: contesta la nube", (r["texto"], r["fuente"]), ("respuesta de la nube", "nube"))

# ---- apagado: flujo de siempre
limpiar()
aprendiz.fijar(False)
with mock.patch.object(cerebro, "pensar", lambda p, c=None, max_tokens=500: ("de la nube", "nube", "")):
    r = cerebro.responder(P)
chequear("apagado: contesta la nube primero", r["fuente"], "nube")
aprendiz.fijar(True)

# ---- comandos
for frase, esperado in [("responde tu primero", ("aprendiz", True)), ("Contesta tú primero", ("aprendiz", True)),
                        ("responde la nube primero", ("aprendiz", False)), ("que responda la nube", ("aprendiz", False)),
                        ("estado aprendiz", ("aprendiz_estado", None)),
                        ("usa la nube para el examen", ("nube_tarea", ("examen", True))),
                        ("no uses la nube para el examen", ("nube_tarea", ("examen", False))),
                        ("no uses la nube para programar", ("nube_tarea", ("codigo", False)))]:
    chequear(f"comando: {frase}", cerebro.interpretar(frase), esperado)

# ---- examen: rigor progresivo
chequear("rigor: racha nivel 1", examen.racha_necesaria(1), 4)
chequear("rigor: racha sube con el nivel", examen.racha_necesaria(4), 7)
chequear("rigor: racha con tope", examen.racha_necesaria(99), examen.RACHA_TOPE)
chequear("rigor: confianza sube", examen.confianza_minima(3) > examen.confianza_minima(1), True)
chequear("rigor: confianza con tope", examen.confianza_minima(99), examen.CONFIANZA_TOPE)
prog = {"nivel_grupal": 3, "dominios": {"d": {"racha": 0, "listo": False}}}
for _ in range(5):
    examen.registrar_resultado(prog, "d", True)
chequear("rigor: nivel 3 con 5 aciertos aun no esta listo (pide 6)", prog["dominios"]["d"]["listo"], False)
examen.registrar_resultado(prog, "d", True)
chequear("rigor: nivel 3 con 6 aciertos queda listo", prog["dominios"]["d"]["listo"], True)

# ---- examen: ronda completa con mocks
with tempfile.TemporaryDirectory() as carpeta:
    ejercicios = iter([
        {"frase": "f1", "intencion_correcta": "a", "dominio": "d", "tactica": "t", "nivel": 3},
        {"frase": "f2", "intencion_correcta": "a", "dominio": "d", "tactica": "t", "nivel": 3},   # acierto flojo
        {"frase": "f3", "intencion_correcta": "a", "dominio": "d", "tactica": "t", "nivel": 3},   # fallo real
        {"frase": "f4", "intencion_correcta": "a", "dominio": "d", "tactica": "t", "nivel": 3},   # ejercicio malo
    ])
    resultados = {"f1": ("a", 0.95, "d"), "f2": ("a", 0.50, "d"), "f3": ("b", 0.9, "d"), "f4": ("b", 0.9, "d")}
    aprendidas = []
    confirma = {"f3": True, "f4": False}
    progreso_ram = {"nivel_grupal": 3, "dominios": {"d": {"racha": 0, "listo": False}}}
    with mock.patch.object(examen, "ARCHIVO_PROGRESO", os.path.join(carpeta, "p.json")), \
            mock.patch.object(examen, "_cargar_progreso", lambda: progreso_ram), \
            mock.patch.object(examen, "_guardar_progreso", lambda p: None), \
            mock.patch.object(examen, "generar_ejercicio", lambda d, n: next(ejercicios)), \
            mock.patch.object(examen, "confirmar_con_la_nube", lambda f, i: confirma.get(f)), \
            mock.patch.object(examen.time, "sleep", lambda s: None), \
            mock.patch.object(examen.cj, "predecir_jerarquico", lambda emb: resultados[emb]), \
            mock.patch("core.IA.aprendizaje.aprender", lambda f, i, r, fuente="": aprendidas.append(f)):
        res = examen.rendir_examen(dominio="d", cantidad=4, obtener_embedding=lambda f: f, silencioso=True)
    chequear("ronda: el ejercicio malo (la nube dice NO) no cuenta", res["total"], 3)
    chequear("ronda: solo el acierto con seguridad suficiente cuenta", res["aciertos"], 1)
    chequear("ronda: el acierto flojo se marca", [d["flojo"] for d in res["detalle"]], [False, True, False])
    chequear("ronda: se aprende del acierto flojo y del fallo confirmado, no del ejercicio malo", aprendidas, ["f2", "f3"])

# ---- examen: confirmar con la nube
with mock.patch.object(nube_tareas, "intentar", lambda *a, **k: "SI"):
    chequear("confirmar: SI", examen.confirmar_con_la_nube("abre youtube", "abrir_sitio"), True)
with mock.patch.object(nube_tareas, "intentar", lambda *a, **k: "No."):
    chequear("confirmar: NO", examen.confirmar_con_la_nube("hola", "abrir_sitio"), False)
with mock.patch.object(nube_tareas, "intentar", lambda *a, **k: None):
    chequear("confirmar: sin nube -> None (se aprende como siempre)", examen.confirmar_con_la_nube("x", "y"), None)
chequear("nube_tareas: 'examen' es una tarea con cupo", ("examen" in nube_tareas.TAREAS, nube_tareas.CUPO_DIARIO_DEFECTO["examen"] > 0), (True, True))

# ---- examen automatico: devuelve el hilo y se frena
detener = threading.Event()
with mock.patch.object(examen, "_marcar_automatico", lambda c: None), \
        mock.patch.object(examen, "rendir_examen", lambda silencioso=True: {"total": 0}):
    hilo = examen.iniciar_examen_en_background(retraso_inicial_seg=0, intervalo_entre_rondas_seg=1, detener_evento=detener)
    chequear("automatico: devuelve el hilo", isinstance(hilo, threading.Thread), True)
    detener.set()
    hilo.join(timeout=5)
    chequear("automatico: se frena al pedirlo", hilo.is_alive(), False)

for p in parches:
    p.stop()
print()
print("TODO OK" if not fallos else f"FALLARON {len(fallos)}: " + "; ".join(fallos))
sys.exit(1 if fallos else 0)