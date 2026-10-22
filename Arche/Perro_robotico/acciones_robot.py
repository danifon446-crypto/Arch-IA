"""Modulo del perro robotico para Arche.

Arche es el cerebro: traduce frases en MOVIMIENTOS (secuencias de angulos)
y los publica por MQTT en los 4 topicos de las patas del ESP32.
El ESP32 solo mueve cada servo al angulo que recibe.

Patas (igual que en el ESP32):
    DD = delantera derecha (pin 13)    DI = delantera izquierda (pin 12)
    TD = trasera derecha   (pin 14)    TI = trasera izquierda   (pin 27)

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
TOPICS = {
    "DD": "perro_robot_77/pata/delantera_der",
    "DI": "perro_robot_77/pata/delantera_izq",
    "TD": "perro_robot_77/pata/trasera_der",
    "TI": "perro_robot_77/pata/trasera_izq",
}
PATAS = ["DD", "DI", "TD", "TI"]   # orden de los angulos en las poses y pasos

# Si una pata se mueve al reves (servo montado en espejo), pon True aqui.
INVERTIR = {"DD": False, "DI": True, "TD": False, "TI": True}

# ---- POSES Y MOVIMIENTOS (CALIBRA ESTOS VALORES CON TU ROBOT) ----------------
# Cada pose son 4 angulos (DD, DI, TD, TI). 90 = pata recta.
# Un paso es (DD, DI, TD, TI, segundos_de_pausa). None = no tocar esa pata.
NEUTRO = (90, 90, 90, 90)
POSES = {
    "pararse":   NEUTRO,
    "sentarse":  (90, 90, 150, 150),
    "acostarse": (150, 150, 150, 150),
}

# "repetir": None = en bucle hasta que llegue otra orden o "quieto"
# "final": pose a la que vuelve al terminar (None = se queda donde acabo)
SECUENCIAS = {
    "pararse":   {"frames": [NEUTRO + (0.4,)], "repetir": 1, "final": None},
    "sentarse":  {"frames": [POSES["sentarse"] + (0.5,)], "repetir": 1, "final": None},
    "acostarse": {"frames": [POSES["acostarse"] + (0.5,)], "repetir": 1, "final": None},
    # trote en diagonales: DD+TI adelante mientras DI+TD atras, y al reves
    "avanzar":    {"frames": [(120, 60, 60, 120, 0.35), (60, 120, 120, 60, 0.35)], "repetir": None, "final": None},
    "correr":     {"frames": [(130, 50, 50, 130, 0.18), (50, 130, 130, 50, 0.18)], "repetir": None, "final": None},
    "retroceder": {"frames": [(60, 120, 120, 60, 0.35), (120, 60, 60, 120, 0.35)], "repetir": None, "final": None},
    # giro: solo se mueve un lado, el otro queda firme
    "izquierda":  {"frames": [(120, 90, 60, 90, 0.35), (60, 90, 120, 90, 0.35)], "repetir": None, "final": None},
    "derecha":    {"frames": [(90, 120, 90, 60, 0.35), (90, 60, 90, 120, 0.35)], "repetir": None, "final": None},
    # gestos (no hay servo de cola: la "cola" la mueve con una pata trasera)
    "ladrar":  {"frames": [(120, 120, 90, 90, 0.15), (90, 90, 90, 90, 0.15)], "repetir": 3, "final": "pararse"},
    "cola":    {"frames": [(None, None, None, 120, 0.2), (None, None, None, 70, 0.2)], "repetir": 4, "final": "pararse"},
    "saludar": {"frames": [(150, None, None, None, 0.4), (120, None, None, None, 0.25),
                           (150, None, None, None, 0.25), (120, None, None, None, 0.25),
                           (150, None, None, None, 0.6)], "repetir": 1, "final": "pararse"},
    "feliz":   {"frames": [(120, 60, 60, 120, 0.2), (60, 120, 120, 60, 0.2)], "repetir": 4, "final": "pararse"},
    "enojado": {"frames": [(60, 60, 110, 110, 1.2)], "repetir": 1, "final": "pararse"},
}

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
]

_PREFIJO = r"^(?:por favor |oye |perro |robot |dogo )*"
_SUFIJO = r"(?: por favor| ya| ahora| aqui| perro| robot)*$"

_RE_ESTADO = re.compile(r"^(?:estado|prueba|revisa|conexion|esta vivo|esta conectado)(?: del| de el| al| a| el)?(?: robot| perro| esp32)(?: conectado)?$")
# "mueve el servo 2 a 90": servo 1=DD, 2=DI, 3=TD, 4=TI; sin numero = las 4 patas
_RE_SERVO = re.compile(r"^(?:mueve|pon|gira)(?: el)? servo(?: (\d+))?(?: a| al| en)? (\d{1,3})(?: grados)?$")
_RE_MODO_ON = re.compile(r"^(?:activa|enciende|pon|inicia|entra en)(?: el)? modo perro$|^actua como (?:un )?perro$|^modo perro(?: on| activado)?$")
_RE_MODO_OFF = re.compile(r"^(?:desactiva|apaga|quita|sal del|termina)(?: el)? modo perro$|^deja de actuar como (?:un )?perro$|^modo perro off$")
_RE_AYUDA = re.compile(r"^(?:comandos|ayuda|que sabe hacer|que puede hacer|que haces)(?: del| de el| de| el)? (?:robot|perro)$")
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


def _mover_pata(pata, angulo):
    angulo = max(0, min(180, int(angulo)))
    if INVERTIR.get(pata):
        angulo = 180 - angulo
    # el ESP32 solo acepta digitos enteros 0-180
    _obtener_cliente().publish(TOPICS[pata], str(angulo), qos=0)


def _aplicar(angulos):
    """angulos: 4 valores (DD, DI, TD, TI); None = no tocar esa pata."""
    for pata, ang in zip(PATAS, angulos):
        if ang is not None:
            _mover_pata(pata, ang)


def enviar_comando_servo(angulo, servo=None):
    """servo 1..4 = DD, DI, TD, TI. None = las 4 patas."""
    if servo is None:
        _aplicar((angulo,) * 4)
    else:
        if not 1 <= servo <= 4:
            raise RobotError("Los servos van del 1 al 4 (1=delantera der, 2=delantera izq, 3=trasera der, 4=trasera izq).")
        _mover_pata(PATAS[servo - 1], angulo)


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
        _aplicar(NEUTRO)


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
        "- mueve el servo 2 a 90 (1=delantera der, 2=delantera izq, 3=trasera der, 4=trasera izq; sin numero = las 4)",
        "- sientate, parate, acuestate, ven, corre, retrocede, gira a la izquierda, gira a la derecha",
        "- quieto, ladra, mueve la cola, da la pata",
        "- activa el modo perro / desactiva el modo perro (yo decido que hace: juega, camina, corre, se cansa, duerme)",
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
            _ejecutor.quieto() if False else None
            enviar_comando_servo(angulo, servo)
            _modo_perro.interaccion()
            return f"{'Las 4 patas' if servo is None else 'Servo ' + str(servo)} a {angulo} grados."

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