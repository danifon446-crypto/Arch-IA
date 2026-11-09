"""Modulo del perro robotico para Arche (12 servos con driver PCA9685, tipo SpotMicro).

Arche es el cerebro: traduce frases en MOVIMIENTOS (secuencias de angulos)
y los manda por MQTT al ESP32. El ESP32 solo mueve cada servo al angulo que
recibe, a traves del driver PCA9685 (ver perro_esp32.ino).

Cada pata tiene 3 servos:
    HOMBRO  abre/cierra la pata hacia el costado (90 = vertical)
    MUSLO   mueve la pata adelante/atras         (90 = vertical)
    RODILLA dobla la pata                         (90 = recta)
El orden es el de los canales del PCA9685:

    canal 0 DD hombro   1 DD muslo   2 DD rodilla     DD = delantera derecha
    canal 3 DI hombro   4 DI muslo   5 DI rodilla     DI = delantera izquierda
    canal 6 TD hombro   7 TD muslo   8 TD rodilla     TD = trasera derecha
    canal 9 TI hombro  10 TI muslo  11 TI rodilla     TI = trasera izquierda

Por cada paso se manda UN solo mensaje con los 12 angulos ("90,90,...,90"),
asi las 4 patas se mueven a la vez y el ESP32 confirma con un solo ack.

Si la frase no es del robot devuelve None y Arche pasa al siguiente modulo.
Necesita: pip install paho-mqtt
"""

import random
import re
import threading
import time
import unicodedata

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# ---- MQTT: debe ser IGUAL que en el ESP32 -----------------------------------
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
BASE = "perro_robot_77"
TOPIC_SERVOS = BASE + "/servos"          # los 12 angulos juntos
# Topicos del formato viejo (4 patas). Se dejan porque el banco de pruebas saca
# de aqui la base para escuchar latido/estado/ack. El ESP32 tambien los entiende.
TOPICS = {
    "DD": BASE + "/pata/delantera_der",
    "DI": BASE + "/pata/delantera_izq",
    "TD": BASE + "/pata/trasera_der",
    "TI": BASE + "/pata/trasera_izq",
}
PATAS = ["DD", "DI", "TD", "TI"]
SERVOS = ["DD_H", "DD_M", "DD_R", "DI_H", "DI_M", "DI_R",
          "TD_H", "TD_M", "TD_R", "TI_H", "TI_M", "TI_R"]          # orden = canales 0..11
N_SERVOS = len(SERVOS)
_PATA_TXT = {"DD": "delantera der", "DI": "delantera izq", "TD": "trasera der", "TI": "trasera izq"}
_ART_TXT = {"H": "hombro", "M": "muslo", "R": "rodilla"}
NOMBRE_SERVO = {n: f"{_PATA_TXT[n[:2]]} {_ART_TXT[n[3]]}" for n in SERVOS}

# Los servos del lado izquierdo van montados en espejo: con True, Arche les manda
# 180 - angulo para que "adelante" sea adelante en los dos lados.
# CALIBRA ESTO con el perro armado (ver "prueba las articulaciones" mas abajo):
# si una articulacion se mueve al reves de lo que esperas, cambia su valor aqui.
INVERTIR = {
    "DD_H": False, "DD_M": False, "DD_R": False,
    "DI_H": True,  "DI_M": True,  "DI_R": True,
    "TD_H": False, "TD_M": False, "TD_R": False,
    "TI_H": True,  "TI_M": True,  "TI_R": True,
}

# ---- POSES Y MOVIMIENTOS (CALIBRA ESTOS VALORES CON TU ROBOT) ----------------
# Convencion (despues de INVERTIR):
#   hombro: 90 = vertical,  MAS de 90 = pata abierta hacia afuera
#   muslo:  90 = vertical,  MAS de 90 = hacia adelante, MENOS = hacia atras
#   rodilla: 90 = recta,    MENOS de 90 = doblada
# Una pose son 12 angulos en el orden de SERVOS. Un paso es pose + segundos de pausa.
# None = no tocar ese servo.
NEUTRO = (90,) * 12          # patas rectas: la posicion en la que se ensamblo


def _pata(flex=20, paso=0, abre=0):
    """(hombro, muslo, rodilla) de una pata.
    flex: cuanto se agacha (dobla rodilla y adelanta muslo para que el pie quede debajo de la cadera).
    paso: lleva el pie adelante (+) o atras (-).  abre: separa la pata del cuerpo (+)."""
    return (90 + abre, 90 + flex + paso, 90 - 2 * flex)


ALTURA = 20                  # flex al estar parado: patas un poco dobladas = mas firme que rectas
# La rodilla queda en 90 - 2*flex: no pases de flex 35 (rodilla 20) o choca con el limite del ESP32.
PARADO = _pata(ALTURA)


def _pose(dd=PARADO, di=PARADO, td=PARADO, ti=PARADO):
    """Arma una pose de 12 angulos con (hombro, muslo, rodilla) de cada pata."""
    return tuple(dd) + tuple(di) + tuple(td) + tuple(ti)


POSES = {
    "pararse":   _pose(),
    # traseras muy dobladas, delanteras casi rectas
    "sentarse":  _pose(dd=_pata(0), di=_pata(0), td=_pata(35), ti=_pata(35)),
    # las 4 muy dobladas: el cuerpo baja al suelo
    "acostarse": _pose(dd=_pata(35), di=_pata(35), td=_pata(35), ti=_pata(35)),
}

_DERECHA = {"DD", "TD"}
_PAR_A = ("DD", "TI")      # el trote mueve las diagonales juntas
_PAR_B = ("DI", "TD")


def _trote(dir_der=1, dir_izq=1, amplitud=15, levanta=15, t_aire=0.16, t_suelo=0.08):
    """Genera los 4 pasos de un trote en diagonales.
    dir_der / dir_izq: 1 = esa mitad empuja hacia adelante, -1 = hacia atras, 0 = en el sitio.
    amplitud: cuanto barre el muslo. levanta: cuanto mas se dobla la pata al dar el paso."""
    frames = []
    for vuela, apoya in ((_PAR_A, _PAR_B), (_PAR_B, _PAR_A)):
        for en_aire in (True, False):
            ang = {}
            for p in vuela:
                s = dir_der if p in _DERECHA else dir_izq
                ang[p] = _pata(ALTURA + (levanta if en_aire else 0), paso=s * amplitud)
            for p in apoya:
                s = dir_der if p in _DERECHA else dir_izq
                ang[p] = _pata(ALTURA, paso=-s * amplitud)
            frames.append(_pose(ang["DD"], ang["DI"], ang["TD"], ang["TI"]) + (t_aire if en_aire else t_suelo,))
    return frames


_SALUDO_BASE = dict(di=_pata(ALTURA, abre=8), td=_pata(ALTURA + 10, abre=8), ti=_pata(ALTURA + 10, abre=8))

# "repetir": None = en bucle hasta que llegue otra orden o "quieto"
# "final": pose a la que vuelve al terminar (None = se queda donde acabo)
SECUENCIAS = {
    "pararse":   {"frames": [POSES["pararse"] + (0.5,)], "repetir": 1, "final": None},
    "sentarse":  {"frames": [POSES["sentarse"] + (0.7,)], "repetir": 1, "final": None},
    "acostarse": {"frames": [POSES["acostarse"] + (0.7,)], "repetir": 1, "final": None},
    "avanzar":    {"frames": _trote(1, 1), "repetir": None, "final": None},
    "correr":     {"frames": _trote(1, 1, amplitud=20, levanta=15, t_aire=0.10, t_suelo=0.05),
                   "repetir": None, "final": None},
    "retroceder": {"frames": _trote(-1, -1), "repetir": None, "final": None},
    # giro: un lado empuja hacia adelante y el otro hacia atras
    "izquierda":  {"frames": _trote(1, -1, amplitud=12), "repetir": None, "final": None},
    "derecha":    {"frames": _trote(-1, 1, amplitud=12), "repetir": None, "final": None},
    # gestos
    # agacha y sube el frente rapido
    "ladrar":  {"frames": [_pose(dd=_pata(ALTURA + 15), di=_pata(ALTURA + 15)) + (0.15,), POSES["pararse"] + (0.15,)],
                "repetir": 3, "final": "pararse"},
    # no hay servo de cola: menea la cadera de lado a lado con los hombros traseros
    "cola":    {"frames": [_pose(td=_pata(ALTURA, abre=12), ti=_pata(ALTURA, abre=-12)) + (0.2,),
                           _pose(td=_pata(ALTURA, abre=-12), ti=_pata(ALTURA, abre=12)) + (0.2,)],
                "repetir": 4, "final": "pararse"},
    # abre las otras 3 patas para no caerse, sube la delantera derecha y la sacude con la rodilla
    "saludar": {"frames": [_pose(**_SALUDO_BASE) + (0.4,),
                           _pose(dd=(90, 150, 70), **_SALUDO_BASE) + (0.35,),
                           _pose(dd=(90, 150, 110), **_SALUDO_BASE) + (0.25,),
                           _pose(dd=(90, 150, 70), **_SALUDO_BASE) + (0.25,),
                           _pose(dd=(90, 150, 110), **_SALUDO_BASE) + (0.5,)],
                "repetir": 1, "final": "pararse"},
    # trote en el sitio, rapido
    "feliz":   {"frames": _trote(0, 0, amplitud=0, levanta=15, t_aire=0.12, t_suelo=0.06),
                "repetir": 4, "final": "pararse"},
    # agacha el frente y sube la cola
    "enojado": {"frames": [_pose(dd=_pata(33, paso=-5), di=_pata(33, paso=-5), td=_pata(5), ti=_pata(5)) + (1.2,)],
                "repetir": 1, "final": "pararse"},
    # retrocede rapido y vuelve a pararse (lo usa el banco de pruebas)
    "asustarse": {"frames": _trote(-1, -1, amplitud=18, levanta=15, t_aire=0.08, t_suelo=0.04),
                  "repetir": 3, "final": "pararse"},
    # para calibrar: mueve cada articulacion sola, un poco, en el sentido "positivo"
    "probar_articulaciones": {"frames": [], "repetir": 1, "final": "pararse"},
}
for _k, _n in enumerate(SERVOS):
    _sube = [None] * 12
    _sube[_k] = 115 if _n.endswith("_M") or _n.endswith("_H") else 65   # muslo adelante / hombro afuera / rodilla doblada
    SECUENCIAS["probar_articulaciones"]["frames"] += [tuple(NEUTRO) + (0.6,), tuple(_sube) + (1.2,)]
SECUENCIAS["probar_articulaciones"]["frames"].append(tuple(NEUTRO) + (0.8,))

# ---- cerebro del modo perro -------------------------------------------------
PAUSA_TRAS_ORDEN = 20
PERMITIR_CAMINAR_AUTONOMO = True
ACCIONES_DE_MOVIMIENTO = {"avanzar", "retroceder", "izquierda", "derecha", "correr"}
DURACION_MOVIMIENTO = {
    "avanzar": (2.0, 4.0), "retroceder": (1.0, 2.0),
    "izquierda": (1.0, 2.5), "derecha": (1.0, 2.5), "correr": (1.5, 3.0),
}
PAUSAS = {"tranquilo": (15, 45), "jugueton": (6, 15), "alerta": (5, 12)}
COMPORTAMIENTOS = {
    "tranquilo": {"cola": 5, "sentarse": 2, "pararse": 2, "saludar": 1, "ladrar": 1,
                  "avanzar": 3, "izquierda": 1, "derecha": 1},
    "jugueton": {"feliz": 4, "cola": 3, "ladrar": 3, "saludar": 2, "pararse": 1,
                 "avanzar": 5, "izquierda": 2, "derecha": 2, "retroceder": 1, "correr": 3},
    "alerta": {"ladrar": 4, "enojado": 1, "pararse": 1, "avanzar": 1},
}
COSTO_ENERGIA = {"cola": 2, "feliz": 3, "ladrar": 4, "saludar": 5, "enojado": 3, "sentarse": 1, "pararse": 1,
                 "avanzar": 6, "retroceder": 3, "izquierda": 4, "derecha": 4, "correr": 10}
ENERGIA_PARA_DORMIR = 20
ENERGIA_PARA_DESPERTAR = 60

# (accion, frases exactas, respuesta de Arche)
ACCIONES = [
    ("sentarse", ["sientate", "sentate", "sientese", "toma asiento"], "Me siento."),
    ("pararse", ["parate", "levantate", "ponte de pie", "de pie"], "Me paro."),
    ("acostarse", ["acuestate", "echate", "tirate", "ponte en el suelo"], "Me acuesto."),
    ("avanzar", ["avanza", "camina", "ven", "anda", "adelante", "anda adelante"], "Voy."),
    ("correr", ["corre", "correr", "corre rapido", "a correr", "trota"], "Voy corriendo."),
    ("retroceder", ["retrocede", "atras", "marcha atras", "da marcha atras"], "Voy hacia atras."),
    ("izquierda", ["gira a la izquierda", "gira izquierda", "voltea a la izquierda", "izquierda"], "Giro a la izquierda."),
    ("derecha", ["gira a la derecha", "gira derecha", "voltea a la derecha", "derecha"], "Giro a la derecha."),
    ("quieto", ["quieto", "quieta", "detente", "alto", "para", "no te muevas"], "Me quedo quieto."),
    ("ladrar", ["ladra", "ladrale", "guau", "haz ruido de perro"], "Guau."),
    ("cola", ["mueve la cola", "menea la cola", "cola"], "Muevo la cola."),
    ("saludar", ["da la pata", "dame la pata", "saluda", "saludame"], "Te doy la pata."),
    ("probar_articulaciones", ["prueba las articulaciones", "probar articulaciones", "calibra las patas",
                               "prueba los servos"],
     "Muevo cada servo solo, del 1 al 12: hombros hacia afuera, muslos hacia adelante y rodillas se doblan. "
     "Si alguno va al reves, cambialo en INVERTIR (acciones_robot.py)."),
]

_PREFIJO = r"^(?:por favor |oye |perro |robot |dogo )*"
_SUFIJO = r"(?: por favor| ya| ahora| aqui| perro| robot)*$"

_RE_ESTADO = re.compile(r"^(?:estado|prueba|revisa|conexion|esta vivo|esta conectado)(?: del| de el| al| a| el)?(?: robot| perro| esp32)(?: conectado)?$")
# "mueve el servo 2 a 90": servo 1..12 (ver SERVOS); sin numero = los 12
_RE_SERVO = re.compile(r"^(?:mueve|pon|gira)(?: el)? servo(?: (\d+))?(?: a| al| en)? (\d{1,3})(?: grados)?$")
_RE_MODO_ON = re.compile(r"^(?:activa|enciende|pon|inicia|entra en)(?: el)? modo perro$|^actua como (?:un )?perro$|^modo perro(?: on| activado)?$")
_RE_MODO_OFF = re.compile(r"^(?:desactiva|apaga|quita|sal del|termina)(?: el)? modo perro$|^deja de actuar como (?:un )?perro$|^modo perro off$")
_RE_AYUDA = re.compile(r"^(?:comandos|ayuda|que sabe hacer|que puede hacer|que haces)(?: del| de el| de| el)? (?:robot|perro)$")
_RE_RELAJAR = re.compile(r"^(?:relaja|suelta|apaga)(?: los| el)? (?:servos|motores|robot|perro)$|^relajate$")
_RE_EMERGENCIA = re.compile(r"^(?:parada de emergencia|emergencia|alto total|detente todo|detener robot|para el robot)$")

_ACCIONES_RE = []
for _nombre, _frases, _resp in ACCIONES:
    _alt = "|".join(re.escape(f) for f in _frases)
    _ACCIONES_RE.append((_nombre, re.compile(_PREFIJO + "(?:" + _alt + ")" + _SUFIJO), _resp))


class RobotError(Exception):
    """Error que se le explica al usuario tal cual."""


def _normalizar(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^\w\s.]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


# ------------------------------------------------------------------- MQTT

_cliente = None
_lock_mqtt = threading.Lock()


def _obtener_cliente():
    """Cliente MQTT persistente (se reconecta solo). Mandar 4 patas por paso
    seria muy lento si se abriera una conexion nueva cada vez."""
    global _cliente
    if mqtt is None:
        raise RobotError("Falta paho-mqtt. Instala con: pip install paho-mqtt")
    with _lock_mqtt:
        if _cliente is None:
            try:
                try:
                    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho-mqtt 2.x
                except AttributeError:
                    c = mqtt.Client()                                   # paho-mqtt 1.x
                c.connect(MQTT_BROKER, MQTT_PORT, 60)
                c.loop_start()
            except Exception as e:
                raise RobotError(f"No pude conectar al broker MQTT ({e}).")
            _cliente = c
        # espera un momento a que termine de conectar
        for _ in range(30):
            if _cliente.is_connected():
                break
            time.sleep(0.1)
        if not _cliente.is_connected():
            raise RobotError("Sin conexion con el broker MQTT. Revisa tu internet.")
        return _cliente


def _a_doce(angulos):
    """4 valores (formato viejo: solo muslos), 8 (formato viejo hombro+rodilla) o 12 -> lista de 12."""
    angulos = list(angulos)
    doce = [None] * 12
    if len(angulos) == 4:
        for k, ang in enumerate(angulos):
            doce[3 * k + 1] = ang      # muslos = canales 1, 4, 7, 10
        return doce
    if len(angulos) == 8:
        for k in range(4):
            doce[3 * k + 1], doce[3 * k + 2] = angulos[2 * k], angulos[2 * k + 1]
        return doce
    if len(angulos) != 12:
        raise RobotError(f"Un paso necesita 12 angulos, llegaron {len(angulos)}.")
    return angulos


def _aplicar(angulos):
    """Manda los 12 angulos en un solo mensaje. None = no tocar ese servo."""
    partes = []
    for nombre, ang in zip(SERVOS, _a_doce(angulos)):
        if ang is None:
            partes.append("-1")
            continue
        ang = max(0, min(180, int(round(ang))))
        if INVERTIR.get(nombre):
            ang = 180 - ang
        partes.append(str(ang))
    _obtener_cliente().publish(TOPIC_SERVOS, ",".join(partes), qos=0)


def relajar():
    """Suelta los 12 servos (dejan de hacer fuerza y de gastar bateria)."""
    _obtener_cliente().publish(TOPIC_SERVOS, "relajar", qos=0)


def enviar_comando_servo(angulo, servo=None):
    """servo 1..12 = canales 0..11 del PCA9685 (ver SERVOS). None = los 12."""
    if servo is None:
        _aplicar((angulo,) * 12)
        return
    if not 1 <= servo <= 12:
        raise RobotError("Los servos van del 1 al 12: " + ", ".join(
            f"{k + 1}={NOMBRE_SERVO[n]}" for k, n in enumerate(SERVOS)) + ".")
    angs = [None] * 12
    angs[servo - 1] = angulo
    _aplicar(angs)


# ------------------------------------------------------ ejecutor de movimientos

class _Ejecutor:
    """Reproduce secuencias en un hilo para no bloquear a Arche.
    Una orden nueva cancela la anterior."""

    def __init__(self):
        self._cancelar = threading.Event()
        self._hilo = None
        self._lock = threading.Lock()
        self.error = None

    def _reproducir(self, nombre, cancelar):
        sec = SECUENCIAS[nombre]
        try:
            veces = sec["repetir"]
            i = 0
            while not cancelar.is_set() and (veces is None or i < veces):
                for *angulos, pausa in sec["frames"]:
                    if cancelar.is_set():
                        return
                    _aplicar(angulos)
                    cancelar.wait(pausa)
                i += 1
            if sec["final"] and not cancelar.is_set():
                _aplicar(POSES[sec["final"]])
        except RobotError as e:
            self.error = str(e)

    def ejecutar(self, nombre):
        """Arranca la accion. Devuelve el hilo (por si se quiere esperar)."""
        if nombre not in SECUENCIAS:
            raise RobotError(f"No conozco el movimiento '{nombre}'.")
        _obtener_cliente()   # falla ya (y se lo explica al usuario) si no hay MQTT
        with self._lock:
            self._cancelar.set()
            cancelar = threading.Event()
            self._cancelar = cancelar
            self.error = None
            self._hilo = threading.Thread(target=self._reproducir, args=(nombre, cancelar),
                                          name="robot-mov", daemon=True)
            self._hilo.start()
            return self._hilo

    def quieto(self):
        """Corta cualquier movimiento y deja las patas rectas."""
        with self._lock:
            self._cancelar.set()
        _aplicar(POSES["pararse"])


_ejecutor = _Ejecutor()


def _enviar_accion(nombre):
    if nombre == "quieto":
        _ejecutor.quieto()
        return None
    return _ejecutor.ejecutar(nombre)


# ---------------------------------------------------------------- modo perro

class _ModoPerro:
    """Arche decide: estado de animo + energia -> que movimiento hacer."""

    def __init__(self):
        self._hilo = None
        self._parar = threading.Event()
        self.estado = "tranquilo"      # tranquilo | jugueton | alerta | dormido
        self.energia = 70.0
        self._estado_hasta = 0.0
        self._pausa_hasta = 0.0
        self.ultimo_evento = "El modo perro no se ha activado."

    @property
    def activo(self):
        return self._hilo is not None and self._hilo.is_alive()

    def resumen(self):
        return f"estado {self.estado}, energia {self.energia:.0f}/100"

    def iniciar(self):
        if self.activo:
            return False
        self.estado = "tranquilo"
        self.energia = max(self.energia, 50.0)
        self._pausa_hasta = 0.0
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="robot-modo-perro", daemon=True)
        self._hilo.start()
        return True

    def detener(self, motivo="Lo detuviste."):
        self._parar.set()
        self.ultimo_evento = f"Modo perro apagado. {motivo}"

    def interaccion(self, segundos=PAUSA_TRAS_ORDEN):
        self._pausa_hasta = time.time() + segundos
        if self.activo:
            self.energia = min(100.0, self.energia + 10)
            if self.estado == "dormido":
                self.estado = "tranquilo"
            self._cambiar_estado("jugueton", 60)

    def evento(self, tipo):
        if not self.activo:
            return None
        if tipo in ("persona", "dueno"):
            self._cambiar_estado("jugueton", 60)
            self.energia = min(100.0, self.energia + 5)
            hizo = "saluda" if tipo == "dueno" else "mueve la cola"
            self._orden("saludar" if tipo == "dueno" else "cola")
            self.ultimo_evento = f"Vio a {'su dueno' if tipo == 'dueno' else 'una persona'} y {hizo}."
        elif tipo == "desconocido":
            self._cambiar_estado("alerta", 30)
            self._orden("ladrar")
            self.ultimo_evento = "Vio a alguien desconocido y ladro."
        else:
            return None
        return self.ultimo_evento

    def _cambiar_estado(self, estado, duracion=0):
        self.estado = estado
        self._estado_hasta = time.time() + duracion if duracion else 0.0

    def _orden(self, nombre):
        """Devuelve el hilo del movimiento, o None si fallo."""
        try:
            return _enviar_accion(nombre) or True
        except RobotError as e:
            self.ultimo_evento = f"Fallo al mover el robot: {e}"
            return None

    def _tick(self, ahora):
        if self.estado == "dormido":
            self.energia = min(100.0, self.energia + 0.5)
            if self.energia >= ENERGIA_PARA_DESPERTAR:
                self._orden("pararse")
                self._cambiar_estado("tranquilo")
                self.ultimo_evento = "Desperto descansado."
        else:
            self.energia = max(0.0, self.energia - 0.02)
            if self.estado in ("jugueton", "alerta") and self._estado_hasta and ahora > self._estado_hasta:
                self._cambiar_estado("tranquilo")
            if self.energia < ENERGIA_PARA_DORMIR:
                self._orden("acostarse")
                self._cambiar_estado("dormido")
                self.ultimo_evento = "Se canso y se acosto a dormir."

    def _actuar(self):
        if self.estado == "dormido":
            return 5.0
        pesos = {n: p for n, p in COMPORTAMIENTOS[self.estado].items()
                 if PERMITIR_CAMINAR_AUTONOMO or n not in ACCIONES_DE_MOVIMIENTO}
        if not pesos:
            return 10.0
        eleccion = random.choices(list(pesos), weights=list(pesos.values()))[0]
        t0 = time.time()
        hilo = self._orden(eleccion)
        if hilo:
            self.energia = max(0.0, self.energia - COSTO_ENERGIA.get(eleccion, 2))
            self.ultimo_evento = f"[{self.estado}] hizo '{eleccion}' por su cuenta ({self.resumen()})."
            if eleccion in ACCIONES_DE_MOVIMIENTO:
                # camina un rato y se detiene (salvo que tu le hayas dado otra orden)
                self._parar.wait(random.uniform(*DURACION_MOVIMIENTO[eleccion]))
                if not self._parar.is_set() and self._pausa_hasta <= t0:
                    self._orden("quieto")
            elif isinstance(hilo, threading.Thread):
                hilo.join(10)
        return random.uniform(*PAUSAS[self.estado])

    def _bucle(self):
        proximo = time.time() + random.uniform(*PAUSAS["tranquilo"])
        while not self._parar.is_set():
            ahora = time.time()
            self._tick(ahora)
            if ahora >= proximo and ahora >= self._pausa_hasta:
                proximo = time.time() + self._actuar()
            self._parar.wait(1.0)


_modo_perro = _ModoPerro()


def reaccionar(tipo):
    """Para que la camara haga reaccionar al perro. tipo: persona | dueno | desconocido."""
    return _modo_perro.evento(tipo)


def detener_todo():
    """Para el modo perro y deja el robot quieto (usar al cerrar Arche)."""
    _modo_perro.detener("Arche se esta cerrando.")
    try:
        _ejecutor.quieto()
    except RobotError:
        pass


# ------------------------------------------------------------------ comandos

def _texto_ayuda():
    return "\n".join([
        "Esto puede hacer el perro:",
        "- estado del robot / prueba el robot (revisa la conexion MQTT)",
        "- mueve el servo 2 a 90 (1-12: " + ", ".join(f"{k + 1}={NOMBRE_SERVO[n]}" for k, n in enumerate(SERVOS))
        + "; sin numero = los 12)",
        "- prueba las articulaciones (mueve cada servo solo, del 1 al 12, para revisar que vaya al lado correcto)",
        "- sientate, parate, acuestate, ven, corre, retrocede, gira a la izquierda, gira a la derecha",
        "- quieto, ladra, mueve la cola, da la pata",
        "- activa el modo perro / desactiva el modo perro (yo decido que hace: juega, camina, corre, se cansa, duerme)",
        "- relaja los servos (los suelta para que no gasten bateria; cualquier orden los vuelve a activar)",
        "- parada de emergencia",
    ])


def manejar(frase):
    """Responde si la frase es del robot; si no, devuelve None."""
    if not frase:
        return None
    t = _normalizar(frase)
    if not t:
        return None

    try:
        if _RE_EMERGENCIA.match(t):
            _modo_perro.detener("Parada de emergencia.")
            _ejecutor.quieto()
            return "Parada de emergencia: el robot esta quieto y el modo perro apagado."

        if _RE_ESTADO.match(t):
            _obtener_cliente()
            extra = f" Modo perro: {'activo, ' + _modo_perro.resumen() if _modo_perro.activo else 'apagado'}."
            return f"Conectado al broker MQTT ({MQTT_BROKER}).{extra} {_modo_perro.ultimo_evento}"

        m = _RE_SERVO.match(t)
        if m:
            angulo = int(m.group(2))
            if not 0 <= angulo <= 180:
                return "El angulo tiene que estar entre 0 y 180."
            servo = int(m.group(1)) if m.group(1) else None
            enviar_comando_servo(angulo, servo)
            _modo_perro.interaccion()
            if servo is None:
                return f"Los 12 servos a {angulo} grados."
            if not 1 <= servo <= 12:
                return "Los servos van del 1 al 12."
            return f"Servo {servo} ({NOMBRE_SERVO[SERVOS[servo - 1]]}) a {angulo} grados."

        if _RE_RELAJAR.match(t):
            _modo_perro.detener("Servos relajados.")
            with _ejecutor._lock:
                _ejecutor._cancelar.set()
            relajar()
            return "Servos relajados: el perro ya no hace fuerza. Cualquier orden lo vuelve a activar."

        if _RE_MODO_ON.match(t):
            _obtener_cliente()   # confirma que hay MQTT antes de arrancar
            if _modo_perro.iniciar():
                return ("Modo perro activado: yo decido que hace. Camina, corre, juega, ladra, saluda y se cansa "
                        "hasta quedarse dormido. Di 'parada de emergencia' para frenarlo.")
            return "El modo perro ya estaba activo."

        if _RE_MODO_OFF.match(t):
            if _modo_perro.activo:
                _modo_perro.detener()
                return "Modo perro apagado."
            return "El modo perro ya estaba apagado."

        if _RE_AYUDA.match(t):
            return _texto_ayuda()

        for nombre, patron, respuesta in _ACCIONES_RE:
            if patron.match(t):
                _enviar_accion(nombre)
                if nombre != "quieto":
                    _modo_perro.interaccion()
                return respuesta

    except RobotError as e:
        return str(e)

    return None


if __name__ == "__main__":
    import sys
    texto = " ".join(sys.argv[1:]) or "comandos del robot"
    print(manejar(texto) or "(esa frase no es del robot)")
    time.sleep(3)   # deja que termine el movimiento antes de cerrar