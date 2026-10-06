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

from core import acciones_pc, alarmas, pc_avanzado, rutinas, voz
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
MODULOS = (voz, alarmas, rutinas, pc_avanzado, cerebro)
NUEVOS = [e for e in catalogo.ENTRADAS if e["subdominio"] in ("voz", "alarmas", "rutinas", "mantenimiento")
          or e["id"] in ("clima", "noticias", "investigar", "conectar_nube", "estado_nube", "usar_nube", "usar_ollama")]
chequear("hay 41 intenciones nuevas en el catalogo", len(NUEVOS), 41)
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

print()
print("TODO OK" if not fallos else f"{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)