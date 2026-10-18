"""Modulo del perro robotico para Arche.

Arche es el cerebro: este modulo traduce frases en ordenes HTTP para el ESP32
y, en modo perro, DECIDE solo que hace el perro (estados de animo + energia).
El ESP32 solo ejecuta las acciones (y mueve la cara en el celular).
Sigue la misma regla que los demas modulos con reglas propias: si la frase no
es del robot devuelve None y Arche pasa al siguiente modulo.

Como engancharlo (en la cadena de modulos de main.py, junto a alarmas/rutinas):

    from acciones_robot import manejar as manejar_robot
    ...
    respuesta = manejar_robot(frase)
    if respuesta is not None:
        return respuesta

Para que la camara (u otro modulo de Arche) haga reaccionar al perro:

    from acciones_robot import reaccionar
    reaccionar("persona")        # "persona", "dueno" o "desconocido"

El servo se mueve por MQTT (necesita: pip install paho-mqtt).
Todo lo demas usa solo la libreria estandar de Python.
"""

import ipaddress
import json
import os
import random
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

RUTA_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "robot_config.json")
CONFIG_BASE = {"ip": "", "puerto": 80, "timeout": 3.0}

# ---- MQTT (servo) -----------------------------------------------------------
# Debe ser el mismo broker y topico que usa el ESP32.
# broker.emqx.io es publico: usa un topico dificil de adivinar (ej. "arche/servo/daniel-x7k2").
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC = "arche/servo/control"
MQTT_TOPIC_ACCION = "arche/accion/control"   # igual en el ESP32
ACCIONES_POR_MQTT = True                      # False = las acciones vuelven a ir por HTTP

LATIDO_SEGUNDOS = 5          # aviso al ESP32 mientras el modo perro esta activo
FALLOS_PARA_CORTAR = 3       # latidos seguidos sin respuesta antes de apagar el modo perro
PAUSA_TRAS_ORDEN = 20        # segundos que el perro "espera" despues de una orden tuya antes de actuar solo

# ---- cerebro del modo perro -------------------------------------------------
# El perro camina por su cuenta (pon False si quieres que solo se mueva cuando se lo ordenes).
PERMITIR_CAMINAR_AUTONOMO = True
ACCIONES_DE_MOVIMIENTO = {"avanzar", "retroceder", "izquierda", "derecha"}
# cuanto camina cada vez (segundos, al azar entre los dos valores); luego Arche le manda "quieto"
DURACION_MOVIMIENTO = {"avanzar": (2.0, 4.0), "retroceder": (1.0, 2.0), "izquierda": (1.0, 2.5), "derecha": (1.0, 2.5)}

# segundos entre un comportamiento y el siguiente, segun el estado de animo
PAUSAS = {
    "tranquilo": (15, 45),
    "jugueton": (6, 15),
    "alerta": (5, 12),
}

# que hace en cada estado y con que peso (mas peso = mas frecuente)
COMPORTAMIENTOS = {
    "tranquilo": {"cola": 5, "sentarse": 2, "pararse": 2, "saludar": 1, "ladrar": 1,
                  "avanzar": 3, "izquierda": 1, "derecha": 1},
    "jugueton": {"feliz": 4, "cola": 3, "ladrar": 3, "saludar": 2, "pararse": 1,
                 "avanzar": 5, "izquierda": 2, "derecha": 2, "retroceder": 1},
    "alerta": {"ladrar": 4, "enojado": 1, "pararse": 1, "avanzar": 1},
}

# cuanta energia gasta cada comportamiento (0-100)
COSTO_ENERGIA = {"cola": 2, "feliz": 3, "ladrar": 4, "saludar": 5, "enojado": 3, "sentarse": 1, "pararse": 1,
                 "avanzar": 6, "retroceder": 3, "izquierda": 4, "derecha": 4}
ENERGIA_PARA_DORMIR = 20     # por debajo de esto se acuesta a dormir
ENERGIA_PARA_DESPERTAR = 60  # al recuperar esto se levanta

# (nombre de la accion en el ESP32, frases exactas que la piden, respuesta de Arche)
ACCIONES = [
    ("sentarse", ["sientate", "sentate", "sientese", "toma asiento"], "Me siento."),
    ("pararse", ["parate", "levantate", "ponte de pie", "de pie"], "Me paro."),
    ("acostarse", ["acuestate", "echate", "tirate", "ponte en el suelo"], "Me acuesto."),
    ("avanzar", ["avanza", "camina", "ven", "anda", "adelante", "anda adelante"], "Voy."),
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

_IP = r"(\d{1,3}(?:\.\d{1,3}){3})"
_RE_IP = re.compile(r"\b(?:conecta(?:te)?|configura|fija|pon|usa|cambia)\b.*\b(?:robot|perro|esp32)\b.*?" + _IP)
_RE_IP_ALT = re.compile(r"\b(?:ip|direccion)\b.*\b(?:robot|perro|esp32)\b.*?" + _IP)
_RE_ESTADO = re.compile(r"^(?:estado|prueba|revisa|conexion|esta vivo|esta conectado)(?: del| de el| al| a| el)?(?: robot| perro| esp32)(?: conectado)?$")
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


def cargar_config():
    cfg = dict(CONFIG_BASE)
    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def guardar_config(cfg):
    try:
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        raise RobotError(f"No pude guardar la configuracion del robot ({e}).")


_LOCK_HTTP = threading.Lock()   # evita que tus ordenes y las del modo perro se pisen


def _llamar(ruta, **params):
    cfg = cargar_config()
    if not cfg["ip"]:
        raise RobotError("Todavia no tengo la IP del robot. Dime: conecta el robot a 192.168.4.1 (la IP que sale en el Monitor Serie).")
    url = f"http://{cfg['ip']}:{cfg['puerto']}{ruta}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with _LOCK_HTTP:
            with urllib.request.urlopen(url, timeout=float(cfg["timeout"])) as r:
                return r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        try:
            detalle = e.read().decode("utf-8", "replace").strip()
        except OSError:
            detalle = ""
        raise RobotError(f"El robot respondio con error {e.code}" + (f": {detalle}." if detalle else "."))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RobotError(
            f"No logro hablar con el robot en {cfg['ip']}. Revisa que este encendido, "
            "en la misma WiFi que el PC y que la IP no haya cambiado."
        )


def _ejecutar_accion(nombre):
    respuesta = _enviar_accion(nombre)
    if respuesta and respuesta.startswith("pendiente"):
        return f"El robot todavia no sabe hacer '{nombre}': {respuesta}"
    return None


def _publicar_mqtt(topic, mensaje):
    if mqtt is None:
        raise RobotError("Falta paho-mqtt. Instala con: pip install paho-mqtt")
    try:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho-mqtt 2.x
        except AttributeError:
            client = mqtt.Client()                                   # paho-mqtt 1.x
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        client.publish(topic, str(mensaje)).wait_for_publish(3)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        raise RobotError(f"No pude enviar el comando MQTT ({e}).")


def enviar_comando_servo(angulo):
    """Publica el angulo por MQTT para el ESP32."""
    _publicar_mqtt(MQTT_TOPIC, angulo)


def _enviar_accion(nombre):
    """Manda una accion al robot por MQTT o HTTP. Devuelve la respuesta del ESP32 (None si fue MQTT)."""
    if ACCIONES_POR_MQTT:
        _publicar_mqtt(MQTT_TOPIC_ACCION, nombre)
        return None
    return _llamar("/accion", nombre=nombre)


# ---------------------------------------------------------------- modo perro

class _ModoPerro:
    """Arche decide: estado de animo + energia -> que comportamiento pedirle al ESP32."""

    def __init__(self):
        self._hilo = None
        self._parar = threading.Event()
        self.estado = "tranquilo"      # tranquilo | jugueton | alerta | dormido
        self.energia = 70.0
        self._estado_hasta = 0.0       # cuando expira jugueton/alerta
        self._pausa_hasta = 0.0        # silencio de iniciativa despues de una orden tuya
        self._no_soportadas = set()    # acciones que el ESP32 aun no sabe hacer ("pendiente")
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

    # --- eventos externos -------------------------------------------------
    def interaccion(self, segundos=PAUSA_TRAS_ORDEN):
        """Le diste una orden: Arche calla su iniciativa un rato y el perro se anima."""
        self._pausa_hasta = time.time() + segundos
        if self.activo:
            self.energia = min(100.0, self.energia + 10)
            if self.estado == "dormido":
                self.estado = "tranquilo"
            self._cambiar_estado("jugueton", 60)

    def evento(self, tipo):
        """Gancho para la camara. Devuelve lo que hizo, o None si el modo perro esta apagado."""
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

    # --- internos ---------------------------------------------------------
    def _cambiar_estado(self, estado, duracion=0):
        self.estado = estado
        self._estado_hasta = time.time() + duracion if duracion else 0.0

    def _orden(self, nombre):
        """Pide una accion al ESP32. False si fallo o si aun no la sabe hacer."""
        if nombre in self._no_soportadas:
            return False
        try:
            r = _enviar_accion(nombre)
        except RobotError:
            return False
        if r and r.startswith("pendiente"):
            self._no_soportadas.add(nombre)
            return False
        return True

    def _tick(self, ahora):
        """Una vez por segundo: energia y cambios de estado."""
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
                self.ultimo_evento = "Se cansó y se acostó a dormir."

    def _actuar(self):
        """Elige un comportamiento segun el estado. Devuelve los segundos hasta el proximo."""
        if self.estado == "dormido":
            return 5.0
        pesos = {
            n: p for n, p in COMPORTAMIENTOS[self.estado].items()
            if n not in self._no_soportadas
            and (PERMITIR_CAMINAR_AUTONOMO or n not in ACCIONES_DE_MOVIMIENTO)
        }
        if not pesos:
            return 10.0
        eleccion = random.choices(list(pesos), weights=list(pesos.values()))[0]
        if self._orden(eleccion):
            self.energia = max(0.0, self.energia - COSTO_ENERGIA.get(eleccion, 2))
            self.ultimo_evento = f"[{self.estado}] hizo '{eleccion}' por su cuenta ({self.resumen()})."
            if eleccion in ACCIONES_DE_MOVIMIENTO:
                # camina un rato y luego se detiene; si tu le diste una orden mientras tanto, no la pisa
                t0 = time.time()
                self._parar.wait(random.uniform(*DURACION_MOVIMIENTO[eleccion]))
                if not self._parar.is_set() and self._pausa_hasta <= t0:
                    self._orden("quieto")
        return random.uniform(*PAUSAS[self.estado])

    def _bucle(self):
        fallos = 0
        ultimo_latido = 0.0
        proximo = time.time() + random.uniform(*PAUSAS["tranquilo"])
        while not self._parar.is_set():
            ahora = time.time()
            if not ACCIONES_POR_MQTT and ahora - ultimo_latido >= LATIDO_SEGUNDOS:
                ultimo_latido = ahora
                try:
                    _llamar("/estado")
                    fallos = 0
                except RobotError as e:
                    fallos += 1
                    if fallos >= FALLOS_PARA_CORTAR:
                        self.ultimo_evento = f"Modo perro apagado: perdi al robot. {e}"
                        return
            self._tick(ahora)
            if ahora >= proximo and ahora >= self._pausa_hasta:
                proximo = ahora + self._actuar()
            self._parar.wait(1.0)


_modo_perro = _ModoPerro()


def reaccionar(tipo):
    """Para que la camara/vision de Arche haga reaccionar al perro. tipo: persona | dueno | desconocido."""
    return _modo_perro.evento(tipo)


def detener_todo():
    """Para el modo perro y le dice al robot que se quede quieto (usar al cerrar Arche)."""
    _modo_perro.detener("Arche se esta cerrando.")
    try:
        _enviar_accion("quieto")
    except RobotError:
        pass


# ------------------------------------------------------------------ comandos

def _texto_ayuda():
    lineas = [
        "Esto puede hacer el perro:",
        "- conecta el robot a 192.168.4.1 (guarda la IP del ESP32)",
        "- estado del robot / prueba el robot",
        "- mueve el servo a 90 (por MQTT)",
        "- sientate, parate, acuestate, ven, retrocede, gira a la izquierda, gira a la derecha",
        "- quieto, ladra, mueve la cola, da la pata",
        "- activa el modo perro / desactiva el modo perro (yo decido que hace: juega, se cansa, duerme)",
        "- parada de emergencia",
    ]
    return "\n".join(lineas)


def manejar(frase):
    """Responde si la frase es del robot; si no, devuelve None."""
    if not frase:
        return None
    t = _normalizar(frase)
    if not t:
        return None

    try:
        # emergencia primero: siempre gana
        if _RE_EMERGENCIA.match(t):
            _modo_perro.detener("Parada de emergencia.")
            _enviar_accion("quieto")
            return "Parada de emergencia: el robot esta quieto y el modo perro apagado."

        m = _RE_IP.search(t) or _RE_IP_ALT.search(t)
        if m:
            ip = m.group(1)
            try:
                ipaddress.IPv4Address(ip)
            except ValueError:
                return f"{ip} no es una IP valida."
            cfg = cargar_config()
            cfg["ip"] = ip
            guardar_config(cfg)
            try:
                _llamar("/estado")
                return f"Listo, el robot esta en {ip} y responde."
            except RobotError as e:
                return f"Guarde la IP {ip}, pero todavia no responde. {e}"

        if _RE_ESTADO.match(t):
            r = _llamar("/estado")
            extra = f" Modo perro: {'activo, ' + _modo_perro.resumen() if _modo_perro.activo else 'apagado'}."
            return f"El robot responde ({r}).{extra} {_modo_perro.ultimo_evento}"

        m = _RE_SERVO.match(t)
        if m:
            angulo = int(m.group(2))
            if not 0 <= angulo <= 180:
                return "El angulo tiene que estar entre 0 y 180."
            enviar_comando_servo(angulo)
            _modo_perro.interaccion()
            return f"Servo a {angulo} grados."

        if _RE_MODO_ON.match(t):
            if not ACCIONES_POR_MQTT:
                _llamar("/estado")  # confirma que el robot esta ahi antes de arrancar
            if _modo_perro.iniciar():
                return ("Modo perro activado: yo decido que hace. Camina, juega, ladra, saluda y se cansa "
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
                aviso = _ejecutar_accion(nombre)
                if nombre != "quieto":
                    _modo_perro.interaccion()
                return aviso if aviso else respuesta

    except RobotError as e:
        return str(e)

    return None


if __name__ == "__main__":
    # prueba rapida desde la terminal: python acciones_robot.py "mueve la cola"
    import sys

    texto = " ".join(sys.argv[1:]) or "comandos del robot"
    print(manejar(texto) or "(esa frase no es del robot)")