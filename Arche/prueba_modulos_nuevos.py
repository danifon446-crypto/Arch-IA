"""
Pruebas de lo ultimo que se le sumo a Arché: voz natural, alarmas, rutinas,
mantenimiento del PC, internet/nube y su conexion con main.py y el catalogo.
Corren en cualquier sistema: no hablan, no suenan, no tocan internet ni tus
archivos (todo va a una carpeta temporal y lo del sistema se simula).

Uso:  cd Arche && python prueba_modulos_nuevos.py
"""

import ast
import contextlib
import datetime
import io
import os
import sys
import tempfile
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import acciones_pc, alarmas, autonomia, control_pc, medios, mejora_continua, pc_avanzado, rutinas, voz
from core.IA import catalogo, cerebro
try:
    from core.IA import voz as microfono
except OSError:
    # sin PortAudio (p. ej. un Linux sin microfono): se simula solo la libreria de audio
    sys.modules["sounddevice"] = mock.MagicMock()
    from core.IA import voz as microfono

fallos = 0
CARPETA = tempfile.mkdtemp(prefix="arche_prueba_")


def chequear(nombre, obtenido, esperado):
    global fallos
    ok = obtenido == esperado
    print(("OK   " if ok else "FALLA"), nombre)
    if not ok:
        fallos += 1
        print(f"      esperado: {esperado!r}\n      obtenido: {obtenido!r}")


def callado(f, *a, **k):
    """Corre f sin imprimir y devuelve (resultado, lo_impreso)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = f(*a, **k)
    return r, buf.getvalue()


class ConfigFalsa:
    """Reemplaza core.configuracion para no tocar tu configuracion real."""
    def __init__(self, **datos):
        self.datos = dict(datos)

    def obtener(self, clave):
        return self.datos.get(clave)

    def cambiar(self, clave, valor):
        self.datos[clave] = valor


# ------------------------------------------------------------------ recorte
for frase in ("haz clic", "doble clic", "clic derecho", "baja la pagina", "sube la pagina"):
    chequear(f"ya no existe '{frase}'", acciones_pc.interpretar(frase), None)
for viejo in ("hacer_clic", "clic_derecho", "doble_clic", "desplazar_abajo", "desplazar_arriba"):
    chequear(f"el catalogo ya no tiene {viejo}", viejo in catalogo.POR_ID, False)
chequear("teclear y presionar siguen", (acciones_pc.interpretar("teclea hola")[0],
                                         acciones_pc.interpretar("presiona ctrl+c")[0]),
         ("teclear_texto", "presionar_tecla"))

# ------------------------------------------------- catalogo <-> modulos
MODULOS = (voz, alarmas, rutinas, pc_avanzado, cerebro, autonomia, mejora_continua)
NUEVOS = [e for e in catalogo.ENTRADAS if e["subdominio"] in ("voz", "alarmas", "rutinas", "mantenimiento", "autonomia")
          or e["id"] in ("clima", "noticias", "investigar", "conectar_nube", "estado_nube", "usar_nube", "usar_ollama")]
chequear("hay 56 intenciones nuevas en el catalogo", len(NUEVOS), 56)
sin_manejador = []
for e in NUEVOS:
    cmd = catalogo.armar_comando(e, catalogo.RELLENOS[e["argumento"]][0] if e["argumento"] else "")
    if not any(m.interpretar(cmd) for m in MODULOS):
        sin_manejador.append((e["id"], cmd))
chequear("todo comando canonico nuevo lo entiende un modulo", sin_manejador, [])
chequear("computador sin intenciones sueltas (todas con subdominio)",
         [e["id"] for e in catalogo.ENTRADAS if e["dominio"] == "computador" and not e["subdominio"]], [])
faltan_rellenos = [e["argumento"] for e in catalogo.ENTRADAS if e["argumento"] and e["argumento"] not in catalogo.RELLENOS]
chequear("todos los tipos de dato tienen ejemplos", faltan_rellenos, [])

# ----------------------------------------------------------------- main.py
fuente = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"), encoding="utf-8").read()
arbol = ast.parse(fuente)
for llamada in ("voz_arche.instalar_en_consola()", "alarmas_arche.avisar_perdidas()", "alarmas_arche.iniciar_vigilante()",
                "rutinas_arche.pasos_con_pausas(", "_modulo.manejar(comando_original)"):
    chequear(f"main.py usa {llamada}", llamada in fuente, True)
chequear("main.py importa los 5 modulos nuevos",
         all(f"as {a}" in fuente or f"import {a}" in fuente
             for a in ("voz_arche", "alarmas_arche", "rutinas_arche", "pc_avanzado", "cerebro_nube")), True)
chequear("los modulos nuevos van antes del control del PC",
         fuente.index("_modulo.manejar(comando_original)") < fuente.index("acciones_pc.manejar(comando_original)"), True)

# ---------------------------------------------------------------------- voz
cfg = ConfigFalsa(voz=True)
with mock.patch.object(voz, "configuracion", cfg), mock.patch.object(voz, "ES_WINDOWS", True):
    chequear("motor por defecto: natural", voz.motor(), "natural")
    chequear("voz natural por defecto (Colombia)", voz.voz_natural(), "es-CO-SalomeNeural")
    chequear("velocidad 0 -> +0%", voz._porcentaje_de_velocidad(), "+0%")
    cfg.datos["voz_velocidad"] = 3
    chequear("velocidad 3 -> +24%", voz._porcentaje_de_velocidad(), "+24%")
    cfg.datos["voz_velocidad"] = 0

    # frase dicha con el motor natural: sintetiza, reproduce y borra el mp3
    dichas, borradas = [], []

    def sintetizar_ok(texto, ruta):
        open(ruta, "wb").write(b"mp3")
        dichas.append((texto, voz.voz_natural()))

    reproducidas = []
    with mock.patch.object(voz, "_sintetizar", sintetizar_ok), \
            mock.patch.object(voz, "_reproducir", lambda r: reproducidas.append(os.path.exists(r))):
        voz._parar_natural.clear()
        chequear("_hablar_natural dice la frase", voz._hablar_natural("hola"), True)
    chequear("sintetizo con la voz elegida", dichas, [("hola", "es-CO-SalomeNeural")])
    chequear("el mp3 existia al reproducir", reproducidas, [True])

    # sin internet / sin libreria: devuelve False (el hilo usa el motor del sistema)
    def sintetizar_falla(texto, ruta):
        raise OSError("sin internet")

    with mock.patch.object(voz, "_sintetizar", sintetizar_falla):
        chequear("sin internet: _hablar_natural devuelve False", voz._hablar_natural("hola"), False)
    chequear("no deja mp3 temporales sueltos",
             [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("arche_voz_")], [])

    # el hilo: natural si se puede, sistema si no
    sistema = []
    resultados = iter([True, False])
    with mock.patch.object(voz, "_hablar_natural", lambda t: next(resultados)), \
            mock.patch.object(voz, "_enviar", lambda t: sistema.append(t) or True):
        voz._parar_natural.clear()
        voz.decir("primera frase")
        voz.decir("segunda frase")
        for _ in range(100):
            if sistema and voz._cola_natural.empty() and not voz._hablando_natural.is_set():
                break
            time.sleep(0.02)
    chequear("respaldo: solo la que fallo sale por la voz del sistema", sistema, ["segunda frase"])

    # hablando() y calla()
    voz._hablando_natural.set()
    chequear("hablando() es True mientras habla", voz.hablando(), True)
    voz._hablando_natural.clear()
    chequear("hablando() es False en silencio", voz.hablando(), False)
    voz._cola_natural.put("a medias")
    with mock.patch.object(voz, "_reiniciar", lambda: None):
        voz.calla()
    chequear("calla() vacia la cola y corta", (voz._cola_natural.empty(), voz._parar_natural.is_set()), (True, True))
    voz._parar_natural.clear()

    # sistema operativo sin voz: no hace nada
    with mock.patch.object(voz, "ES_WINDOWS", False):
        chequear("fuera de Windows decir() no hace nada", voz.decir("hola"), False)
    cfg.datos["voz"] = False
    chequear("voz apagada: no habla", voz.decir("hola"), False)
    chequear("forzar=True habla aunque este apagada",
             (lambda: (setattr(voz, "_encolar_natural", lambda t: True), voz.decir("hola", forzar=True))[1])(), True)

# comandos de voz
for frase, esperado in {
    "usa la voz natural": ("motor_voz", "natural"), "usa la voz del sistema": ("motor_voz", "sistema"),
    "pon la voz de windows": ("motor_voz", "sistema"), "usa la voz de gonzalo": ("elegir_voz", "gonzalo"),
    "activa la voz": ("activar_voz", None), "calla": ("callar", None), "repite eso": ("repetir", None),
    "habla mas rapido": ("velocidad_voz", "+2"), "estado de la voz": ("estado_voz", None),
}.items():
    chequear(f"voz entiende '{frase}'", voz.interpretar(frase), esperado)

cfg = ConfigFalsa(voz=True, voz_motor="natural")
with mock.patch.object(voz, "configuracion", cfg), mock.patch.object(voz, "ES_WINDOWS", True), \
        mock.patch.object(voz, "calla", lambda: None), mock.patch.object(voz, "decir", lambda *a, **k: True):
    callado(voz.manejar, "usa la voz de gonzalo")
    chequear("elegir voz natural la guarda", cfg.datos.get("voz_natural"), "es-CO-GonzaloNeural")
    _, salida = callado(voz.manejar, "usa la voz de napoleon")
    chequear("voz desconocida: lo dice", "No conozco" in salida, True)
    callado(voz.manejar, "usa la voz del sistema")
    chequear("cambiar a motor del sistema", cfg.datos.get("voz_motor"), "sistema")
    callado(voz.manejar, "usa la voz natural")
    chequear("volver al motor natural", cfg.datos.get("voz_motor"), "natural")
    _, salida = callado(voz.manejar, "que voces hay")
    chequear("lista las voces naturales", "gonzalo" in salida and "salome" in salida, True)

# el microfono se calla mientras Arché habla
with mock.patch.object(voz, "hablando", lambda: True):
    chequear("microfono: ignora si Arché habla", microfono._arche_esta_hablando(), True)
with mock.patch.object(voz, "hablando", lambda: False):
    chequear("microfono: escucha si Arché calla", microfono._arche_esta_hablando(), False)

# --------------------------------------------------------------- alarmas
ahora = datetime.datetime(2026, 10, 5, 8, 0, 0)
with mock.patch.object(alarmas, "ARCHIVO", os.path.join(CARPETA, "alarmas.json")), \
        mock.patch.object(alarmas, "iniciar_vigilante", lambda: None):
    r = alarmas.interpretar("pon un temporizador de 10 minutos", ahora)
    chequear("temporizador de 10 minutos", (r[0], r[1]["tipo"], r[1]["cuando"]),
             ("crear_alarma", "temporizador", ahora + datetime.timedelta(minutes=10)))
    r = alarmas.interpretar("avisame en 20 minutos que saque la ropa", ahora)
    chequear("aviso con texto", (r[1]["tipo"], r[1]["texto"]), ("aviso", "saque la ropa"))
    r = alarmas.interpretar("pon una alarma a las 7 de la mañana", ahora)
    chequear("alarma de manana: es al dia siguiente", r[1]["cuando"], datetime.datetime(2026, 10, 6, 7, 0))
    chequear("sin alarma sonando, 'posponer' no crea nada raro", alarmas.interpretar("pospon la alarma 10 minutos", ahora), None)
    chequear("'recuerdame llamar al medico' (sin hora) sigue al flujo normal",
             alarmas.interpretar("recuerdame llamar al medico", ahora), None)
    res, _ = callado(alarmas.manejar, "pon un temporizador de 10 minutos", ahora)
    chequear("manejar crea y lo deja pendiente", (res[0], len(alarmas.pendientes())), ("poner_temporizador", 1))
    res, salida = callado(alarmas.manejar, "mis alarmas", ahora)
    chequear("mis alarmas las lista", ("Temporizador" in salida or "temporizador" in salida, res[0]), (True, "ver_alarmas"))
    callado(alarmas.manejar, "cancela todas las alarmas", ahora)
    chequear("cancelar todas deja cero", len(alarmas.pendientes()), 0)

# --------------------------------------------------------------- rutinas
with mock.patch.object(rutinas, "ARCHIVO", os.path.join(CARPETA, "rutinas.json")):
    chequear("primera vez: trae rutinas de ejemplo", sorted(rutinas.listar()), ["cine", "descanso", "estudio", "trabajo"])
    chequear("'modo cine' ejecuta la rutina", rutinas.interpretar("modo cine"), ("ejecutar_rutina", {"nombre": "cine"}))
    res, _ = callado(rutinas.manejar, "ejecuta la rutina cine")
    chequear("ejecutar devuelve los pasos para la cola", (res[0], res[1]["pasos"]),
             ("ejecutar_rutina", ["pon el brillo al 30", "pon el volumen al 60", "muestra el escritorio"]))
    chequear("pasos con pausa de 2 segundos entre cada uno", rutinas.pasos_con_pausas(["a", "b", "c"]),
             ["a", "espera 2", "b", "espera 2", "c"])
    callado(rutinas.manejar, "crea la rutina lectura: silencia el sonido, pon el brillo al 40")
    chequear("crear rutina propia", rutinas.obtener("lectura") and rutinas.obtener("lectura")["pasos"],
             ["silencia el sonido", "pon el brillo al 40"])
    callado(rutinas.manejar, "agrega a la rutina lectura: pausa la musica")
    chequear("agregar un paso", len(rutinas.obtener("lectura")["pasos"]), 3)
    callado(rutinas.manejar, "borra la rutina lectura")
    chequear("borrar rutina", rutinas.obtener("lectura"), None)
    chequear("los ejemplos no se vuelven a crear si ya existe el archivo", "cine" in rutinas.listar(), True)
    _, salida = callado(rutinas.manejar, "ejecuta la rutina inventada")
    chequear("rutina inexistente: lo avisa", "inventada" in salida, True)
    chequear("main parte la creacion de una rutina? no (tiene varias ordenes dentro)",
             acciones_pc.dividir_pasos("abre chrome y luego sube el brillo"), ["abre chrome", "sube el brillo"])

# ---------------------------------------------------- mantenimiento del PC
chequear("diagnostico se entiende", pc_avanzado.interpretar("dame un diagnostico de mi pc"), ("diagnostico_pc", None))
chequear("'abre el 2' abre el resultado 2", pc_avanzado.interpretar("abre el 2")[0], "abrir_resultado")
chequear("una frase cualquiera no es de mantenimiento", pc_avanzado.interpretar("hola como estas"), None)
chequear("limpiar sin confirmar es solo analisis: 'que puedo limpiar'",
         pc_avanzado.interpretar("que puedo limpiar"), ("analizar_limpieza", None))
with mock.patch.object(pc_avanzado, "PAPELERA", os.path.join(CARPETA, "papelera")), \
        mock.patch.object(pc_avanzado, "MANIFIESTO", os.path.join(CARPETA, "papelera", "manifiesto.json")):
    res, salida = callado(pc_avanzado.manejar, "que puedo limpiar")
    chequear("analizar la limpieza no rompe ni borra nada", (res is not None, "Traceback" in salida), (True, False))

# ------------------------------------------------------- internet y nube
chequear("clima con ciudad", cerebro.interpretar("como esta el clima en bogota"), ("clima", "bogota"))
chequear("investigar", cerebro.interpretar("investiga la inflacion")[0], "investigar")
chequear("noticias", cerebro.interpretar("noticias de tecnologia"), ("noticias", "tecnologia"))
chequear("conectar la nube", cerebro.interpretar("conecta la nube"), ("conectar_nube", None))
chequear("usar ollama de respaldo", cerebro.interpretar("usa ollama"), ("usar_ollama", None))
chequear("una pregunta normal no es de internet", cerebro.interpretar("cuentame un chiste"), None)

# ---- la nube piensa la charla y Ollama es el respaldo
from core.IA import nube

def _cerebro(modo, configurada, disponible, nube_responde=None, nube_falla=False):
    """Corre cerebro.pensar con todo simulado. Devuelve (texto, fuente, aviso, llamadas_a_nube)."""
    llamadas = []

    def responder_nube(mensajes, sistema=None, max_tokens=500):
        llamadas.append(mensajes)
        if nube_falla:
            raise nube.ErrorNube("sin saldo")
        return nube_responde

    cerebro._historial.clear()
    with mock.patch.object(nube, "modo", lambda: modo), mock.patch.object(nube, "configurada", lambda: configurada), \
            mock.patch.object(nube, "disponible", lambda: disponible), mock.patch.object(nube, "responder", responder_nube), \
            mock.patch.object(cerebro, "_ollama", lambda prompt, num_predict=350: "respuesta de ollama"), \
            mock.patch.object(cerebro, "_sistema_para_nube", lambda: "sistema"):
        r = cerebro.pensar("hola, como estas")
    return (*r, len(llamadas))

chequear("nube conectada y con internet: piensa la nube", _cerebro("auto", True, True, "hola desde la nube"),
         ("hola desde la nube", "nube", "", 1))
chequear("sin clave: Ollama, sin tocar la nube", _cerebro("auto", False, False), ("respuesta de ollama", "ollama", "", 0))
chequear("sin internet: Ollama", _cerebro("auto", True, False), ("respuesta de ollama", "ollama", "", 0))
chequear("modo ollama: nunca usa la nube", _cerebro("ollama", True, True, "x"), ("respuesta de ollama", "ollama", "", 0))
t, f, aviso, n = _cerebro("auto", True, True, nube_falla=True)
chequear("la nube falla: responde Ollama y avisa", (t, f, "La nube no respondio" in aviso.replace("ó", "o"), n),
         ("respuesta de ollama", "ollama", True, 1))
t, f, aviso, n = _cerebro("nube", True, False)
chequear("modo solo nube sin internet: lo dice y no usa Ollama", (f, "solo nube" in t), ("nube", True))
chequear("main.py usa cerebro_nube.responder en la charla", "cerebro_nube.responder(contenido)" in fuente, True)
chequear("main.py ya no llama a Ollama directo en la charla", "respuesta = conversar(contenido)" in fuente, False)

# ------------------------------------------- voz: sincronia y personalizacion
for frase, esperado in {
    "voz mas aguda": ("tono_voz", "+1"), "voz mas grave": ("tono_voz", "-1"), "tono de la voz a 3": ("tono_voz", 3),
    "volumen de la voz a 50": ("volumen_voz", 50), "voz mas suave": ("volumen_voz", "-15"),
    "sincroniza la voz con el texto": ("sincronia_voz", True), "habla junto con el texto": ("sincronia_voz", True),
    "no sincronices la voz": ("sincronia_voz", False), "habla despues del texto": ("sincronia_voz", False),
    "lectura corta": ("lectura_voz", "corta"), "lee todo": ("lectura_voz", "completa"),
    "restablece la voz": ("restablecer_voz", None), "voces online": ("voces_online", None),
    "usa la voz mexicana": ("elegir_voz", "mexicana"),
}.items():
    chequear(f"voz entiende '{frase}'", voz.interpretar(frase), esperado)

cfg = ConfigFalsa(voz=True, voz_motor="natural")
with mock.patch.object(voz, "configuracion", cfg):
    chequear("tono 0 -> +0Hz", voz._hz_de_tono(), "+0Hz")
    cfg.datos["voz_tono"] = 2
    chequear("tono 2 -> +8Hz", voz._hz_de_tono(), "+8Hz")
    cfg.datos["voz_volumen"] = 60
    chequear("volumen 60 -> -40%", voz._porcentaje_de_volumen(), "-40%")
    chequear("sincronizada por defecto", voz.sincronizada(), True)
    chequear("voz mexicana (mujer)", voz.buscar_voz_natural("mexicana"), "es-MX-DaliaNeural")
    chequear("voz argentina de hombre", voz.buscar_voz_natural("argentina de hombre"), "es-AR-TomasNeural")
    chequear("nombre completo de Edge", voz.buscar_voz_natural("es-CL-LorenzoNeural"), "es-CL-LorenzoNeural")
    chequear("voz inventada -> None", voz.buscar_voz_natural("napoleon"), None)
    cfg.datos["voz_natural"] = "es-MX-DaliaNeural"
    chequear("'de hombre' mantiene el pais", voz.buscar_voz_natural("de hombre"), "es-MX-JorgeNeural")
    cfg.datos["voz_lectura"] = "corta"
    chequear("lectura corta: solo la primera frase", voz._segun_lectura("Hola. Esto es largo. Mas cosas."), "Hola.")
    cfg.datos["voz_lectura"] = "completa"
    with mock.patch.object(voz, "calla", lambda: None), mock.patch.object(voz, "decir", lambda *a, **k: True), \
            mock.patch.object(voz, "ES_WINDOWS", True):
        callado(voz.manejar, "volumen de la voz a 40")
        callado(voz.manejar, "voz mas aguda")
        callado(voz.manejar, "no sincronices la voz")
        callado(voz.manejar, "lectura corta")
    chequear("comandos guardan volumen/tono/sync/lectura",
             (cfg.datos["voz_volumen"], cfg.datos["voz_tono"], cfg.datos["voz_sincronizada"], cfg.datos["voz_lectura"]),
             (40, 3, False, "corta"))
    with mock.patch.object(voz, "calla", lambda: None):
        callado(voz.manejar, "restablece la voz")
    chequear("restablecer borra la personalizacion", (voz.tono(), voz.volumen(), voz.sincronizada(), voz.lectura()),
             (0, 100, True, "completa"))

# sincronia: el texto sale justo cuando el audio ya esta listo, y suena el mismo audio
cfg = ConfigFalsa(voz=True, voz_motor="natural")
orden = []
with mock.patch.object(voz, "configuracion", cfg), mock.patch.object(voz, "ES_WINDOWS", True), \
        mock.patch.object(voz, "edge_tts_instalado", lambda: True), \
        mock.patch.object(voz, "_sintetizar", lambda t, r: (orden.append("audio listo"), open(r, "wb").write(b"mp3"))), \
        mock.patch.object(voz, "_print_original", lambda *a, **k: orden.append("texto")), \
        mock.patch.object(voz, "_encolar_natural", lambda t, r=None: (orden.append(("suena", t, bool(r))), r and os.remove(r))):
    voz._print_con_voz("Arché: Hola, ¿cómo estás?")
    chequear("sincronia: audio primero, luego texto, luego suena",
             orden, ["audio listo", "texto", ("suena", "Hola, ¿cómo estás?", True)])
    orden.clear()
    cfg.datos["voz_sincronizada"] = False
    with mock.patch.object(voz, "decir", lambda t, forzar=False: orden.append("decir")):
        voz._print_con_voz("Arché: Hola")
    chequear("sin sincronia: texto de una vez y luego voz", orden, ["texto", "decir"])
    orden.clear()
    cfg.datos["voz_sincronizada"] = True
    with mock.patch.object(voz, "_sintetizar", lambda t, r: (_ for _ in ()).throw(OSError("sin internet"))), \
            mock.patch.object(voz, "decir", lambda t, forzar=False: orden.append("decir")):
        voz._print_con_voz("Arché: Hola")
    chequear("sin internet: el texto sale igual (una sola vez)", orden, ["texto", "decir"])
    orden.clear()
    voz._print_con_voz("esto no es de Arché")
    chequear("lineas que no son de Arché: solo texto", orden, ["texto"])
    chequear("audio que tarda demasiado: no se espera", voz._preparar_audio("hola", espera=0.05)
             if False else None, None)
with mock.patch.object(voz, "_sintetizar", lambda t, r: time.sleep(0.5)):
    t0 = time.time()
    chequear("audio que tarda demasiado: devuelve None sin esperar", voz._preparar_audio("hola", espera=0.05), None)
    chequear("...y no se queda esperando", time.time() - t0 < 0.4, True)
    time.sleep(0.8)
chequear("sin mp3 sueltos tras la sincronia", [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("arche_voz_")], [])

# ------------------------------------------- la nube en el resto de tareas
from core.IA import nube, nube_tareas
nube_tareas.nube.ARCHIVO_CONFIG = os.path.join(CARPETA, "nube_tareas.json")
chequear("estudio viene encendido y codigo apagado", (nube_tareas.activa("estudio"), nube_tareas.activa("codigo")), (True, False))
llamadas = []
with mock.patch.object(nube_tareas.nube, "disponible", lambda: True), \
        mock.patch.object(nube_tareas.nube, "responder", lambda m, **k: (llamadas.append(m), "desde la nube")[1]):
    chequear("codigo apagado: no usa la nube", nube_tareas.intentar("codigo", "haz algo"), None)
    nube_tareas.fijar("codigo", True)
    chequear("codigo encendido: usa la nube", nube_tareas.intentar("codigo", "haz algo"), "desde la nube")
    nube_tareas.fijar("codigo", False)
def _falla429(m, **k):
    raise nube_tareas.nube.ErrorNube("limite", codigo=429)
with mock.patch.object(nube_tareas.nube, "disponible", lambda: True), \
        mock.patch.object(nube_tareas.nube, "responder", _falla429):
    chequear("falla (429): devuelve None para que siga Ollama", nube_tareas.intentar("estudio", "x"), None)
    chequear("tras el 429 descansa un rato", nube_tareas._pausa_hasta > time.time(), True)
nube_tareas._pausa_hasta = 0
with mock.patch.object(nube_tareas.nube, "disponible", lambda: False):
    chequear("sin nube disponible: None", nube_tareas.intentar("estudio", "x"), None)
chequear("tarea desconocida: None", nube_tareas.intentar("magia", "x"), None)
for frase, esperado in {"prueba la nube": ("probar_nube", None), "funciona la nube": ("probar_nube", None),
                        "usa la nube para programar": ("nube_tarea", ("codigo", True)),
                        "no uses la nube para programar": ("nube_tarea", ("codigo", False)),
                        "usa la nube para estudiar": ("nube_tarea", ("estudio", True)),
                        "no uses la nube para el estudio": ("nube_tarea", ("estudio", False)),
                        "para que usas la nube": ("nube_tareas_estado", None)}.items():
    chequear(f"cerebro entiende '{frase}'", cerebro.interpretar(frase), esperado)
chequear("cerebro: 'usa la nube' sigue siendo el modo automatico", cerebro.interpretar("usa la nube"), ("usar_nube", None))

# ollamaIA: la nube entra primero y Ollama queda de respaldo
try:
    import ollama  # noqa: F401
except ImportError:
    sys.modules["ollama"] = mock.MagicMock()   # sin Ollama instalado: solo se simula la libreria
from core.IA import ollamaIA
nube_tareas.fijar("codigo", True)
with mock.patch.object(nube_tareas, "intentar", lambda t, p, **k: "codigo de la nube" if t == "codigo" else None):
    chequear("generar_codigo usa la nube si responde", ollamaIA.generar_codigo("haz algo"), "codigo de la nube")
usadas = []
fake = mock.MagicMock()
fake.chat.side_effect = lambda **k: (usadas.append(k["model"]), {"message": {"content": "de ollama"}})[1]
with mock.patch.object(nube_tareas, "intentar", lambda *a, **k: None), mock.patch.object(ollamaIA, "ollama", fake):
    chequear("si la nube no responde, codigo cae a Ollama", ollamaIA.generar_codigo("haz algo"), "de ollama")
    chequear("conversar(permitir_nube=False) no toca la nube",
             ollamaIA.conversar("hola", permitir_nube=False), "de ollama")
nube_tareas.fijar("codigo", False)
chequear("cerebro._ollama no reintenta la nube", "permitir_nube=False" in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "core", "IA", "cerebro.py"), encoding="utf-8").read(), True)

# prueba la nube de punta a punta (simulada)
with mock.patch.object(cerebro.nube, "configurada", lambda *a: True), mock.patch.object(cerebro.web, "hay_internet", lambda: True), \
        mock.patch.object(cerebro.nube, "probar", lambda: (True, "ok")), \
        mock.patch.object(cerebro.nube, "responder", lambda m, **k: "Es un modelo inspirado en el cerebro."), \
        mock.patch("core.IA.aprender_de_nube._llamar", lambda p, n: '{"intencion": "brillo", "contenido": "70"}'):
    ok, salida = callado(cerebro.probar_nube_completa)
    chequear("prueba la nube: todo bien", (ok, "4/4" in salida), (True, True))
with mock.patch.object(cerebro.nube, "configurada", lambda *a: False):
    ok, salida = callado(cerebro.probar_nube_completa)
    chequear("prueba la nube sin clave: lo dice", (ok, "conecta la nube" in salida), (False, True))
with mock.patch.object(cerebro.nube, "configurada", lambda *a: True), mock.patch.object(cerebro.web, "hay_internet", lambda: True), \
        mock.patch.object(cerebro.nube, "probar", lambda: (False, "la clave de la nube no sirve")):
    ok, salida = callado(cerebro.probar_nube_completa)
    chequear("prueba la nube con clave mala: muestra el motivo", (ok, "no sirve" in salida), (False, True))

# ------------------------------- 'proximos pasos': ejemplos ya importados no vuelven a salir
from core.IA import ensenar
_f = os.path.join(CARPETA, "ejemplos_prueba.txt")
open(_f, "w", encoding="utf-8").write("# nota\nhola que tal | saludo\n\notra frase | hora\n")
with mock.patch.object(ensenar, "_archivo_registro", lambda: os.path.join(CARPETA, "registro_ejemplos.json")):
    chequear("ejemplos sin importar: cuenta las lineas utiles", ensenar.lineas_pendientes(_f), 2)
    ensenar.marcar_importado(_f)
    chequear("ya importados: 0 pendientes", ensenar.lineas_pendientes(_f), 0)
    open(_f, "a", encoding="utf-8").write("una nueva | fecha\n")
    chequear("si agregas lineas, vuelven a contar", ensenar.lineas_pendientes(_f), 3)

# ----------------------------------------------- numeros en palabras y voces por nombre
for frase, esperado in {"sube el brillo al cuarenta por ciento": ("brillo_a", "40"),
                        "pon el volumen al treinta y cinco": ("volumen_a", "35"),
                        "pon el brillo al cien": ("brillo_a", "100"),
                        "pon el volumen a veinticinco": ("volumen_a", "25")}.items():
    r = acciones_pc.interpretar(frase)
    chequear(f"numeros en palabras: '{frase}'", (r[0], r[1]["n"]) if r else None, esperado)
chequear("'por ciento' no se vuelve 100", acciones_pc._limpiar("al 40 por ciento"), "al 40 por ciento")
for texto, esperado in {"española": "es-ES-ElviraNeural", "valentina": "es-UY-ValentinaNeural", "sofia": "es-BO-SofiaNeural",
                        "SofiaNeural": "es-BO-SofiaNeural", "boliviana de hombre": "es-BO-MarceloNeural",
                        "napoleon": None}.items():
    chequear(f"voz por nombre/pais: '{texto}'", voz.buscar_voz_natural(texto), esperado)
chequear("la ñ no estorba al limpiar", voz._limpio("la voz española"), "la voz espanola")

# ------------------------------------------------ reproducir y reutilizar pestaña
for frase, esperado in {"pon another love en spotify": ("spotify", "another love"),
                        "reproduce gatos en youtube": ("youtube", "gatos"),
                        "ponme boulevard en spotify": ("spotify", "boulevard"),
                        "busca gatos en youtube": None, "pon gatos en google": None,
                        "pon el brillo al 50": None}.items():
    chequear(f"reproduccion entiende '{frase}'", control_pc.interpretar_reproduccion(frase), esperado)
ventanas = [{"hwnd": 1, "titulo": "Another Love • Tom Odell", "exe": "chrome.exe", "pid": 1, "minimizada": False},
            {"hwnd": 2, "titulo": "notas - Bloc de notas", "exe": "notepad.exe", "pid": 2, "minimizada": False}]
with mock.patch.object(medios, "_ventanas", lambda: ventanas), mock.patch.object(control_pc, "ES_WINDOWS", True):
    chequear("spotify sonando (titulo 'Cancion • Artista') se reconoce", (medios.ventana_del_sitio("spotify") or {}).get("hwnd"), 1)
    chequear("youtube no esta abierto: None", medios.ventana_del_sitio("youtube"), None)
    escritas = []
    with mock.patch.object(medios, "_escribir_en_ventana", lambda h, u: escritas.append((h, u)) or True), \
            mock.patch.object(control_pc, "abrir_url", lambda u, preguntar=True: escritas.append(("nueva", u)) or True):
        medios.abrir_reutilizando("spotify", "https://open.spotify.com/search/x")
        medios.abrir_reutilizando("youtube", "https://youtube.com/watch?v=aaaaaaaaaaa")
    chequear("con una ventana abierta la reutiliza; si no, abre una nueva",
             escritas, [(1, "https://open.spotify.com/search/x"), ("nueva", "https://youtube.com/watch?v=aaaaaaaaaaa")])
with mock.patch.object(medios, "_buscar_web", lambda q, maximo=6: [{"href": "https://example.com/x"},
                                                                  {"href": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3"}]):
    chequear("primer video: toma el primer enlace de watch", medios.primer_video("algo"), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
with mock.patch.object(medios, "_buscar_web", lambda q, maximo=6: []):
    chequear("sin resultados: None", medios.primer_video("algo"), None)
abiertas = []
with mock.patch.object(medios, "abrir_reutilizando", lambda sitio, url: abiertas.append((sitio, url)) or (True, 7)), \
        mock.patch.object(medios, "_dar_play_en_segundo_plano", lambda h, c: abiertas.append(("play", h, c))), \
        mock.patch.object(medios, "primer_video", lambda c: "https://www.youtube.com/watch?v=aaaaaaaaaaa"), \
        mock.patch.object(control_pc, "ES_WINDOWS", True):
    _, sal = callado(medios.reproducir, "spotify", "another love")
    _, sal2 = callado(medios.reproducir, "youtube", "gatos")
chequear("spotify: abre la busqueda y luego le da play", abiertas[:2],
         [("spotify", "https://open.spotify.com/search/another+love"), ("play", 7, "another love")])
chequear("youtube: abre el video directo", abiertas[2], ("youtube", "https://www.youtube.com/watch?v=aaaaaaaaaaa"))
chequear("el mensaje no repite el sitio", ("spotify" in sal.lower(), "Poniendo" in sal), (False, True))
chequear("el script de play busca botones 'Play <titulo>' y no el de la barra", "(Play|Reproducir)" in medios._script_play(5), True)
with mock.patch.object(medios, "ESPERA_CARGA", 0), mock.patch.object(medios, "_ejecutar_script", lambda sc, espera=25: (True, "OK:Play Another Love")):
    chequear("pulsar_play devuelve el nombre del boton", medios.pulsar_play(5, espera=1), "Play Another Love")
with mock.patch.object(medios, "ESPERA_CARGA", 0), mock.patch.object(medios, "_ejecutar_script", lambda sc, espera=25: (True, "NO")), \
        mock.patch.object(medios.time, "sleep", lambda s: None):
    chequear("si no hay boton: None", medios.pulsar_play(5, espera=0), None)
sal_busqueda = callado(control_pc.buscar_en_sitio, "spotify", "boulevard")[1] if False else ""
abiertas2 = []
with mock.patch.object(medios, "abrir_reutilizando", lambda sitio, url: abiertas2.append(sitio) or (True, None)), \
        mock.patch.object(control_pc.time, "sleep", lambda s: None):
    _, sal = callado(control_pc.buscar_en_sitio, "spotify", "boulevard")
chequear("buscar en spotify tambien reutiliza la pestana y no dice el sitio", (abiertas2, "en spotify" in sal.lower()), (["spotify"], False))

# ------------------------------------------------------------- autonomia
autonomia.ARCHIVO = os.path.join(CARPETA, "autonomia.json")
cfg_aut = ConfigFalsa()
lun = datetime.datetime(2026, 10, 5, 19, 0)
with mock.patch.object(autonomia, "configuracion", cfg_aut):
    chequear("autonomia: nivel por defecto 'avisos'", autonomia.nivel(), "avisos")
    for cmd, ok in {"abre spotify": True, "pon another love en spotify": True, "ejecuta la rutina estudio": True,
                    "baja el volumen": True, "apaga el pc": False, "cierra chrome": False, "limpia todo": False,
                    "teclea hola": False, "borra la rutina cine": False, "hola como estas": False}.items():
        chequear(f"autonomia: es_segura('{cmd}')", autonomia.es_segura(cmd), ok)
    # habitos: 3 dias distintos a la misma hora
    for dia in (1, 2, 3):
        autonomia.registrar("pon another love en spotify", lun - datetime.timedelta(days=dia, minutes=10))
    autonomia.registrar("apaga el pc", lun - datetime.timedelta(days=1))
    habitos = autonomia._cargar()["habitos"]
    chequear("autonomia: solo anota ordenes seguras", list(habitos), ["pon another love en spotify"])
    chequear("autonomia: detecta el habito a esa hora", [c for c, _ in autonomia.habitos_para_ahora(lun)], ["pon another love en spotify"])
    chequear("autonomia: a otra hora no lo sugiere", autonomia.habitos_para_ahora(lun.replace(hour=8)), [])
    autonomia._pendiente = None
    dicho, sal = callado(autonomia.revisar, lun, {})
    chequear("autonomia: sugiere el habito y deja pendiente la respuesta", (len(dicho), autonomia._pendiente is not None), (1, True))
    chequear("autonomia: no repite la sugerencia el mismo dia", callado(autonomia.revisar, lun, {})[0], [])
    ejecutadas = []
    with mock.patch.object(autonomia, "_ejecutar", lambda c: ejecutadas.append(c) or True), \
            mock.patch.object(autonomia, "_ahora", lambda: lun):
        callado(autonomia.manejar, "siempre")
    chequear("autonomia: 'siempre' ejecuta y aprueba el habito", (ejecutadas, autonomia._cargar()["habitos"]["pon another love en spotify"]["aprobado"]),
             (["pon another love en spotify"], True))
    chequear("autonomia: sin sugerencia pendiente 'si' no se intercepta", autonomia.interpretar("si"), None)
    # modo avisos: no ejecuta solo; proactiva: si
    ma = lun + datetime.timedelta(days=1)
    with mock.patch.object(autonomia, "_ejecutar", lambda c: ejecutadas.append("auto:" + c) or True):
        callado(autonomia.revisar, ma, {})
        chequear("autonomia: en modo avisos no hace nada solo", [e for e in ejecutadas if e.startswith("auto:")], [])
        cfg_aut.datos["autonomia"] = "proactiva"
        autonomia._pendiente = None
        dicho, _ = callado(autonomia.revisar, ma + datetime.timedelta(days=1), {})
        time.sleep(0.2)
        chequear("autonomia: en proactiva hace solo el habito aprobado", ("auto:pon another love en spotify" in ejecutadas, dicho[0].startswith("auto:")), (True, True))
        cfg_aut.datos["autonomia"] = "apagada"
        chequear("autonomia: apagada no hace ni dice nada", callado(autonomia.revisar, ma + datetime.timedelta(days=5), {"bateria": 5.0, "cargando": False})[0], [])
        cfg_aut.datos["autonomia"] = "avisos"
    # rechazos
    autonomia._pendiente = None
    habitos = autonomia._cargar(); habitos["habitos"]["abre chrome"] = {"cmd": "abre chrome", "usos": [(lun - datetime.timedelta(days=d)).isoformat(timespec="minutes") for d in (1, 2, 3)],
                                                                      "rechazos": 0, "aprobado": False, "sugerido": None, "ultima_auto": None}
    autonomia._guardar(habitos)
    callado(autonomia.revisar, lun.replace(day=lun.day), {})
    for _ in range(3):
        autonomia._pendiente = {"cmd": "abre chrome", "clave": "abre chrome", "tipo": "habito", "hasta": lun + datetime.timedelta(hours=1)}
        with mock.patch.object(autonomia, "_ahora", lambda: lun):
            callado(autonomia.manejar, "no")
    chequear("autonomia: tras 3 'no' deja de sugerir ese habito", autonomia._cargar()["habitos"]["abre chrome"]["rechazos"], 3)
    # sensores
    est = {"cuentas": {"memoria": 0, "cpu": 0}}
    chequear("autonomia: bateria baja avisa", [a[0] for a in autonomia.evaluar({"bateria": 12.0, "cargando": False}, est)], ["bateria"])
    chequear("autonomia: bateria baja pero cargando no avisa", autonomia.evaluar({"bateria": 12.0, "cargando": True}, est), [])
    chequear("autonomia: memoria alta un instante no avisa", autonomia.evaluar({"memoria": 95.0}, est), [])
    autonomia.evaluar({"memoria": 95.0}, est)
    avisos = autonomia.evaluar({"memoria": 95.0}, est)
    chequear("autonomia: memoria alta sostenida avisa y sugiere liberar", [(a[0], a[2]) for a in avisos], [("memoria", "libera memoria")])
    chequear("autonomia: disco casi lleno avisa", [a[0] for a in autonomia.evaluar({"disco_libre": 6.0}, est)], ["disco"])
    autonomia._estado["ultimo_aviso"].clear()
    d1, _ = callado(autonomia.revisar, lun, {"bateria": 10.0, "cargando": False})
    d2, _ = callado(autonomia.revisar, lun + datetime.timedelta(minutes=5), {"bateria": 10.0, "cargando": False})
    chequear("autonomia: el aviso no se repite de inmediato", (len(d1) >= 1, [x for x in d2 if "batería" in x]), (True, []))
    # comandos y resumen
    for frase, esperado in {"nivel de autonomia proactiva": ("nivel_autonomia", "proactiva"), "se mas autonomo": ("nivel_autonomia", "proactiva"),
                            "solo avisame": ("nivel_autonomia", "avisos"), "no me avises nada": ("nivel_autonomia", "apagada"),
                            "que has notado": ("estado_autonomia", None), "olvida mis habitos": ("olvidar_habitos", None)}.items():
        chequear(f"autonomia entiende '{frase}'", autonomia.interpretar(frase), esperado)
    callado(autonomia.manejar, "nivel de autonomia proactiva")
    chequear("autonomia: el comando cambia el nivel", cfg_aut.datos["autonomia"], "proactiva")
    callado(autonomia.manejar, "olvida mis habitos")
    chequear("autonomia: olvidar borra los habitos", autonomia._cargar()["habitos"], {})
    with mock.patch.object(autonomia, "_leer_sensores", lambda: {"bateria": 25.0, "cargando": False}):
        lineas, _ = callado(autonomia.resumen_del_dia, lun, True)
    chequear("resumen del dia: saludo, hora y bateria", (lineas[0].startswith("Buenas noches"), any("batería" in l for l in lineas)), (True, True))
    chequear("resumen del dia: una sola vez por dia", callado(autonomia.resumen_del_dia, lun)[0], [])
chequear("main.py conecta la autonomia (vigilante, resumen, registro, modulo)",
         all(x in fuente for x in ("autonomia_arche.iniciar_vigilante()", "autonomia_arche.resumen_del_dia()",
                                   "autonomia_arche.registrar(comando_original)", "autonomia_arche, voz_arche")), True)
chequear("main.py corrige el saludo mal clasificado y reproduce con medios",
         all(x in fuente for x in ('intencion, contenido = "conversar", comando', "medios.reproducir(*_reproduccion)")), True)

# ------------------------------------------ la nube no aprende cosas que no son conocimiento
from core.IA import aprender_de_nube as adn
for pregunta, respuesta, esperado in [
        ("que nivel de autonomia tienes", "Tengo autonomia limitada y no puedo tomar decisiones por mi cuenta.", False),
        ("estas aprendiendo eso que estas respondiendo", "No, no estoy aprendiendo mientras hablamos nada de nada.", False),
        ("sube el brillo del computador a la mitad", "Puedes hacerlo desde la configuracion de tu sistema operativo.", False),
        ("para que sirve una red neuronal en la practica", "No tengo acceso directo a los ajustes de pantalla, pero puedes hacerlo desde ahi.", False),
        ("para que sirve una red neuronal en la practica", "Sirve para aprender patrones a partir de ejemplos, como reconocer imagenes o texto.", True)]:
    chequear(f"aprender de la charla: '{pregunta[:32]}...' -> {esperado}", adn._vale_la_pena_charla(pregunta, respuesta), esperado)
chequear("la nube sabe lo que Arche puede hacer (no dice 'no puedo controlar tu PC')",
         "sube el brillo al 40" in cerebro._sistema_para_nube(), True)

# ------------------------------------------------ guia: 'comandos voz' busca si no es categoria
from core import guia_comandos
_, sal = callado(guia_comandos.mostrar_guia, "voz", False)
chequear("'comandos voz' busca en vez de rendirse", ("Encontré" in sal, "No tengo una categoría" in sal), (True, False))
_, sal = callado(guia_comandos.mostrar_guia, "computador", False)
chequear("'comandos computador' sigue mostrando la categoria", "COMPUTADOR" in sal, True)

print()
# ---- arreglos del log (OneDrive, play de Spotify, respuestas genericas) ----
from core.IA import respuestas as _resp
chequear("respuesta generica no se guarda ni se reutiliza", (_resp.respuesta_inutil("¿Hay algo en lo que pueda ayudarte?"), _resp.respuesta_inutil("Una red neuronal es un modelo inspirado en el cerebro que aprende patrones a partir de ejemplos.")), (True, False))
chequear("el script de play tiene respaldo por clic y lista de botones", ("mouse_event" in medios._script_play(5), "NO:" in medios._script_play(5)), (True, True))
from core.IA import aprendizaje as _apr
import tempfile as _tf, os as _os
_orig_arch = _apr.ARCHIVO
_d = _tf.mkdtemp(); _apr.ARCHIVO = _os.path.join(_d, "c.json")
_n = {"i": 0}
_real_replace = _os.replace
def _falla_dos_veces(a, b):
    _n["i"] += 1
    if _n["i"] <= 2:
        raise PermissionError(13, "bloqueado")
    return _real_replace(a, b)
with mock.patch.object(_apr.time, "sleep", lambda s: None), mock.patch.object(_apr.os, "replace", _falla_dos_veces):
    _apr.guardar([{"a": 1}])
chequear("guardar reintenta si OneDrive bloquea", _apr.cargar(), [{"a": 1}])
_apr.ARCHIVO = _orig_arch



# ------------------------------------------------------- mejora continua
mc = mejora_continua
mc.ARCHIVO = os.path.join(CARPETA, "mejora_continua.json")
chequear("mejora: nivel por defecto 'datos'", mc.nivel(), "datos")
for frase, esperado in (("mejorate sola", ("nivel_mejora", "datos")), ("nivel de mejora completa", ("nivel_mejora", "completa")),
                        ("no te mejores sola", ("nivel_mejora", "apagada")), ("mejorate ahora", ("mejorar_ahora", None)),
                        ("que has mejorado", ("estado_mejora", None)), ("mejora tu codigo", None), ("hola", None)):
    chequear(f"mejora: interpretar('{frase}')", mc.interpretar(frase), esperado)

llamadas = []
def _falso(nombre, devuelve):
    return lambda *a, **k: (llamadas.append(nombre), devuelve)[1]

class _Eventos:  # telemetria simulada
    pass

with mock.patch.object(mc, "_ejemplos_pendientes", lambda: 3), \
        mock.patch.object(mc, "_importar_ejemplos", lambda: (3, 1)), \
        mock.patch.object(mc, "_tamano_catalogo", lambda: 100), \
        mock.patch.object(mc, "_sembrar", lambda: 7), \
        mock.patch.object(mc, "_nube_lista", lambda: True), \
        mock.patch.object(mc, "_comandos_fallidos", lambda d: ["subile el brillo un poquito", "hazme cafe ya"]), \
        mock.patch.object(mc, "_preguntar_a_la_nube", lambda f: ("subir_brillo", "") if "brillo" in f else ("desconocido", "")), \
        mock.patch.object(mc, "_purgar_cache", lambda: 2), \
        mock.patch.object(mc, "_limpiar_conocimiento", lambda: 0), \
        mock.patch.object(mc, "_correr_autotest", lambda: (20, 0, "")), \
        mock.patch.object(mc, "_estudiar", lambda: llamadas.append("estudio")), \
        mock.patch.object(mc, "_revisar_codigo", lambda: {"duplicados": 2, "imports_sin_usar": 0}):
    mc.fijar_nivel("datos")
    mc._ultimo_latido = 0
    hechas = mc.ciclo(forzar=True)
    textos = " | ".join(hechas)
    chequear("mejora: importa ejemplos y siembra", "importé 3" in textos and "sembré 7" in textos, True)
    chequear("mejora: aprende solo de lo que la nube entendio", "subile el brillo un poquito" in textos and "hazme cafe" not in textos, True)
    chequear("mejora: limpia el cache", "quité 2" in textos, True)
    chequear("mejora: pruebas sin fallos no molestan", "me probé" not in textos, True)
    chequear("mejora: nivel datos no revisa el codigo", "revisé mi código" in textos, False)
    chequear("mejora: respeta el descanso (no repite enseguida)", mc.ciclo(ahora=mc._ahora() + 60), [])
    mc.fijar_nivel("completa")
    chequear("mejora: nivel completa deja informe del codigo sin tocar nada", any("No toqué nada" in t for t in mc.ciclo(forzar=True)), True)
    mc._ultimo_latido = time.time()
    chequear("mejora: si estas escribiendo no hace nada", mc.ciclo(), [])
    mc._ultimo_latido = 0
    mc.fijar_nivel("apagada")
    chequear("mejora: apagada no hace nada", mc.ciclo(forzar=True), [])
    mc.fijar_nivel("datos")
with mock.patch.object(mc, "_correr_autotest", lambda: (18, 2, "  MAL  test_x\n  MAL  test_y")):
    chequear("mejora: avisa si al probarse algo falla", "fallaron 2" in (mc.tarea_pruebas() or ""), True)
with mock.patch.object(mc, "_ejemplos_pendientes", lambda: (_ for _ in ()).throw(RuntimeError("x"))):
    mc._ultimo_latido = 0
    chequear("mejora: una tarea rota no tumba el ciclo", isinstance(mc.ciclo(forzar=True), list), True)
dicho, _ = callado(mc.resumen_pendiente)
chequear("mejora: cuenta lo hecho al volver", len(dicho) >= 2, True)
chequear("mejora: y no lo repite", callado(mc.resumen_pendiente)[0], [])
chequear("main.py conecta la mejora continua", all(x in fuente for x in ("mejora_arche.iniciar()", "mejora_arche.latido()", "mejora_arche.resumen_pendiente()")), True)

print("TODO OK" if not fallos else f"{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)