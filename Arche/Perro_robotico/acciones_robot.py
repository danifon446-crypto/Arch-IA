"""Modulo del perro robotico para Arche (12 servos con driver PCA9685, tipo SpotMicro).

Arche es el cerebro: traduce frases en MOVIMIENTOS (secuencias de angulos)
y los manda por MQTT al ESP32. El ESP32 solo mueve cada servo al angulo que
recibe, a traves del driver PCA9685 (ver perro_esp32/perro_esp32.ino, en esta misma carpeta).
Ese .ino entiende: BASE/servos (12 angulos o "relajar") y BASE/pata/... (formato viejo).
No reproduce secuencias solo: Arche manda cada paso (ESP_SECUENCIAS queda en False).

Cada pata tiene 3 servos:
    HOMBRO  abre/cierra la pata hacia el costado (90 = vertical)
    MUSLO   mueve la pata adelante/atras         (90 = vertical)
    RODILLA dobla la pata                         (90 = en L, como se armo)
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

import math
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
TOPIC_SECUENCIA = BASE + "/secuencia"    # una secuencia entera: el ESP32 la reproduce solo
TOPIC_SIGUE = BASE + "/sigue"            # "sigue caminando" cada segundo (si deja de llegar, el ESP32 para)
# True cuando el ESP32 avisa (en su info) que sabe reproducir secuencias solo. Lo pone el banco de pruebas.
# Asi caminar no depende de la demora de internet: antes cada paso viajaba por separado y llegaban tarde.
ESP_SECUENCIAS = False
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

# ---- CALIBRACION DE CADA SERVO ----------------------------------------------
# Se hace desde la app (Ajustes > Calibrar servos) y se guarda en calibracion.json:
# no hay que tocar este archivo ni volver a subir nada al ESP32.
#   invertir: el servo va montado en espejo (los del lado izquierdo, casi siempre): Arche le manda 180 - angulo
#   ajuste:   grados que se le suman para que con 90 la pata quede derecha (corrige el diente del cuerno)
#   min/max:  hasta donde puede ir esa articulacion sin chocar (en los mismos grados que usa Arche)
# Estos son los valores de fabrica; los que pongas en la app mandan.
INVERTIR = {
    "DD_H": False, "DD_M": False, "DD_R": False,
    "DI_H": True,  "DI_M": True,  "DI_R": True,
    "TD_H": False, "TD_M": False, "TD_R": False,
    "TI_H": True,  "TI_M": True,  "TI_R": True,
}
import json as _json
import os as _os

_RUTA_CALIB = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "calibracion.json")
RANGO_AJUSTE = (-30, 30)


def _calib_fabrica():
    # base: correccion grande que Arche calcula sola al "Guardar como PARADO" (ver capturar_pose)
    # ajuste: correccion fina que mueves tu en la app
    return {n: {"invertir": INVERTIR[n], "base": 0, "ajuste": 0, "min": 10, "max": 170} for n in SERVOS}


# Poses que guardas desde la app (Armar > Guardar como PARADO / ECHADO): angulos REALES de los 12 servos
# y la pose de Arche que les corresponde. Con ellas Arche calcula sola invertir y base de cada servo.
CAPTURAS = {"parado": None, "echado": None}
_resultado_captura = []


# Hacia donde apuntan las rodillas cuando el perro se agacha:
#   "atras"    -> como el perro Spot / SpotMicro: el muslo baja hacia ATRAS y la parte de abajo vuelve
#                 hacia adelante hasta el pie (la rodilla queda detras de la cadera)
#   "adelante" -> al reves: el muslo va hacia adelante y la rodilla queda delante de la cadera
RODILLAS = "atras"

# Cuanto esta DOBLADA la rodilla cuando su servo esta en 90 (asi se armo):
#   90 -> en "L": la parte de abajo a 90 grados del muslo (RECOMENDADO: la rodilla puede ir de casi recta
#         a muy doblada y le alcanza para pararse, sentarse y echarse)
#    0 -> recta: solo le quedan ~80 grados para doblarse y no le alcanza para echarse
RODILLA_EN_90 = 90

# ---- CINEMATICA INVERSA: largo de cada tramo de la pata, en milimetros ----
# Se miden en las piezas, de centro de eje a centro de eje (se pueden medir SUELTAS, antes de armar):
#   muslo:  eje del servo del muslo  ->  eje de la rodilla
#   pierna: eje de la rodilla        ->  punta del pie (donde toca el suelo)
# Con estos largos Arche calcula los angulos exactos para poner el pie donde quiere:
# al caminar el pie se arrastra en linea RECTA por el suelo y el cuerpo no sube y baja.
# Se cambian en la app (Ajustes > Calibrar servos > Medidas de la pata) y se guardan en calibracion.json.
# Medidas de tus piezas (sacadas del STL): muslo 122,5 mm y pierna 132 mm.
LARGO_MUSLO = 122.5
LARGO_PIERNA = 132.0
RANGO_LARGO = (40, 300)

CALIB = _calib_fabrica()
try:
    with open(_RUTA_CALIB, "r", encoding="utf-8") as _f:
        _d = _json.load(_f)
        for _n, _c in _d.items():
            if _n in CALIB and isinstance(_c, dict):
                CALIB[_n].update({k: _c[k] for k in ("invertir", "base", "ajuste", "min", "max") if k in _c})
        for _p, _v in (_d.get("_capturas") or {}).items():
            if _p in CAPTURAS and isinstance(_v, dict):
                CAPTURAS[_p] = _v
        if _d.get("_rodillas") in ("atras", "adelante"):
            RODILLAS = _d["_rodillas"]
        if isinstance(_d.get("_rodilla_en_90"), (int, float)):
            RODILLA_EN_90 = int(max(0, min(120, _d["_rodilla_en_90"])))
        if isinstance(_d.get("_largo_muslo"), (int, float)):
            LARGO_MUSLO = float(max(RANGO_LARGO[0], min(RANGO_LARGO[1], _d["_largo_muslo"])))
        if isinstance(_d.get("_largo_pierna"), (int, float)):
            LARGO_PIERNA = float(max(RANGO_LARGO[0], min(RANGO_LARGO[1], _d["_largo_pierna"])))
except (OSError, ValueError, TypeError, AttributeError):
    pass

def _a_servo_libre(nombre, ang):
    """Grados de Arche -> grados reales del servo, SIN recortar (para avisar si se sale)."""
    c = CALIB[nombre]
    ang = max(c["min"], min(c["max"], ang))          # nunca pasa de donde choca
    if c["invertir"]:
        ang = 180 - ang
    return ang + c.get("base", 0) + c["ajuste"]


def _a_servo(nombre, ang):
    """Grados de Arche -> grados reales del servo, con la calibracion de ese servo."""
    return max(0, min(180, int(round(_a_servo_libre(nombre, ang)))))


# ---- POSES Y MOVIMIENTOS (CALIBRA ESTOS VALORES CON TU ROBOT) ----------------
# Convencion (despues de INVERTIR):
#   hombro: 90 = vertical,  MAS de 90 = pata abierta hacia afuera
#   muslo:  90 = vertical,  MAS de 90 = hacia adelante, MENOS = hacia atras
#   rodilla: 90 = en L (como se armo), MENOS de 90 = mas doblada, MAS de 90 = mas recta
# Una pose son 12 angulos en el orden de SERVOS. Un paso es pose + segundos de pausa.
# None = no tocar ese servo.
NEUTRO = (90,) * 12          # posicion de ARMADO: hombro y muslo verticales, rodilla en "L" (ver RODILLA_EN_90)


# ---- AJUSTES DE LA MARCHA (se cambian en vivo desde la app: Ordenes > Ajustar la marcha) ----
# Se guardan en marcha.json para que no se pierdan al cerrar Arche.

_RUTA_MARCHA = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "marcha.json")
MARCHA_INICIAL = {
    "altura": 25,      # cuanto dobla las patas al estar parado (0 = patas rectas, 35 = muy agachado)
    "paso": 15,        # largo del paso: cuanto barre el muslo adelante/atras
    "levanta": 15,     # alto del paso: cuanto MAS dobla la pata cuando el pie va en el aire
    "velocidad": 1.0,  # 1 = normal, 2 = el doble de rapido, 0.5 = la mitad
    "abrir": 0,        # separa las 4 patas del cuerpo (+) o las junta (-): mas ancho = mas estable
    "centro": 0,       # mueve el cuerpo adelante (+) o atras (-) sobre los pies: corrige si se cae de cara o de cola
}
RANGOS_MARCHA = {"altura": (5, 50), "paso": (0, 25), "levanta": (0, 25), "velocidad": (0.3, 2.5),
                 "abrir": (-10, 20), "centro": (-20, 20)}
MARCHA = dict(MARCHA_INICIAL)
try:
    with open(_RUTA_MARCHA, "r", encoding="utf-8") as _f:
        for _k, _v in _json.load(_f).items():
            if _k in RANGOS_MARCHA:
                MARCHA[_k] = max(RANGOS_MARCHA[_k][0], min(RANGOS_MARCHA[_k][1], float(_v)))
except (OSError, ValueError, TypeError):
    pass

# Lo maximo que gira un MG996R a 6 V (unos 0.17 s por 60 grados = ~350 grados/s).
# Si un paso le pide mas que esto, el servo no alcanza a llegar y el perro "arrastra" las patas.
VEL_MAX_SERVO = 350.0
LIM_SERVO = (10, 170)        # igual que LIM_MIN / LIM_MAX del ESP32 (cada servo ademas tiene su min/max en CALIB)

_avisos_calculo = []         # se llena al armar los movimientos: lo que esta mal y que cambiar


_ik_recortes = set()         # patas que pidieron un punto fuera de alcance al armar los movimientos


def cinematica_inversa(x, h, anotar=True):
    """Donde poner el pie -> (angulo del muslo, cuanto se dobla la rodilla), en grados.
    x: mm hacia adelante (+) o atras (-) desde la cadera.  h: mm hacia abajo desde la cadera.
    muslo: 0 = vertical, + = hacia adelante.  doblez: 0 = pata recta, 90 = en L.
    Si el punto queda demasiado lejos o demasiado cerca, lo acerca al mas cercano que se alcanza."""
    l1, l2 = LARGO_MUSLO, LARGO_PIERNA
    d = math.hypot(x, h)
    d_min, d_max = abs(l1 - l2) + 1.0, l1 + l2 - 0.5
    if not d_min <= d <= d_max:
        if anotar:
            _ik_recortes.add((round(x), round(h)))
        d = max(d_min, min(d_max, d))
    # ley del coseno: angulo en la rodilla (entre muslo y pierna) y entre el muslo y la linea cadera-pie
    rodilla_int = math.acos(max(-1.0, min(1.0, (l1 * l1 + l2 * l2 - d * d) / (2 * l1 * l2))))
    alfa = math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    hacia_pie = math.atan2(x, h)                          # direccion de la cadera al pie
    # rodillas hacia atras (tipo Spot): el muslo queda DETRAS de la linea cadera-pie
    muslo = hacia_pie - alfa if RODILLAS == "atras" else hacia_pie + alfa
    return math.degrees(muslo), 180.0 - math.degrees(rodilla_int)


def altura_de(flex):
    """Altura de la cadera sobre el pie (mm) para un 'flex' (lo agachado, en grados: 0 = patas rectas)."""
    return (LARGO_MUSLO + LARGO_PIERNA) * math.cos(math.radians(max(0.0, min(85.0, flex))))


def _pata(flex=None, paso=0, abre=0):
    """(hombro, muslo, rodilla) de una pata, calculado con cinematica inversa.
    flex: cuanto se agacha (grados; define la altura de la cadera: (muslo+pierna)*cos(flex)).
    paso: lleva el pie adelante (+) o atras (-), en grados vistos desde la cadera; el pie se mueve
          en linea recta a la misma altura (no en arco), asi el cuerpo no sube y baja al caminar.
    abre: separa la pata del cuerpo (+).
    Los ajustes "abrir" y "centro" de la marcha se suman a todas las patas."""
    if flex is None:
        flex = MARCHA["altura"]
    h = altura_de(flex)
    x = h * math.tan(math.radians(max(-60.0, min(60.0, paso))))
    muslo, doblez = cinematica_inversa(x, h)
    # el angulo del servo de la rodilla depende de como se armo (RODILLA_EN_90). Menos grados = mas doblada.
    rodilla = 90 + RODILLA_EN_90 - doblez
    return (int(round(90 + abre + MARCHA["abrir"])),
            int(round(90 + muslo + MARCHA["centro"])),
            int(round(rodilla)))


def flex_maximo():
    """Lo mas que se puede agachar sin que la rodilla pase el limite del servo (10 grados)."""
    tope = 90 + RODILLA_EN_90 - LIM_SERVO[0]               # lo mas que se puede doblar la rodilla
    f = 0
    while f < 85 and cinematica_inversa(0, altura_de(f + 1), anotar=False)[1] <= tope:
        f += 1
    return f


def flex_recta():
    """El 'flex' que deja la pata lo mas recta posible sin que la rodilla pase el limite del servo."""
    minimo = 90 + RODILLA_EN_90 - LIM_SERVO[1]             # lo minimo que se puede doblar la rodilla
    f = 0
    while f < 85 and cinematica_inversa(0, altura_de(f), anotar=False)[1] < minimo:
        f += 1
    return f


def _pose(dd=None, di=None, td=None, ti=None):
    """Arma una pose de 12 angulos con (hombro, muslo, rodilla) de cada pata (None = parado)."""
    parado = _pata()
    return tuple(dd or parado) + tuple(di or parado) + tuple(td or parado) + tuple(ti or parado)


POSES = {}

_DERECHA = {"DD", "TD"}
_PAR_A = ("DD", "TI")      # el trote mueve las diagonales juntas
_PAR_B = ("DI", "TD")


def _trote(dir_der=1, dir_izq=1, amplitud=None, levanta=None, t=0.12):
    """Trote en diagonales (DD+TI y DI+TD), en 4 pasos suaves:
      1) el par que vuela se levanta y trae el pie al centro; el otro par empuja el cuerpo hasta el centro
      2) el par que vuela apoya el pie adelante;               el otro par termina de empujar atras
      3) y 4) lo mismo con los pares cambiados.
    Asi ningun servo tiene que girar mas de ~30 grados por paso (el MG996R no alcanza saltos mas grandes).
    dir_der / dir_izq: 1 = esa mitad empuja hacia adelante, -1 = hacia atras, 0 = en el sitio.
    amplitud: cuanto barre el muslo. levanta: cuanto mas se dobla la pata al dar el paso.
    t: segundos por paso (se divide por la "velocidad" de la marcha)."""
    amplitud = MARCHA["paso"] if amplitud is None else amplitud
    levanta = MARCHA["levanta"] if levanta is None else levanta
    altura = MARCHA["altura"]
    tt = t / MARCHA["velocidad"]
    frames = []
    for vuela, apoya in ((_PAR_A, _PAR_B), (_PAR_B, _PAR_A)):
        ang = {}
        for p in vuela:
            ang[p] = _pata(altura + levanta, paso=0)
        for p in apoya:
            ang[p] = _pata(altura, paso=0)
        frames.append(_pose(ang["DD"], ang["DI"], ang["TD"], ang["TI"]) + (tt,))
        for p in vuela:
            s = dir_der if p in _DERECHA else dir_izq
            ang[p] = _pata(altura, paso=s * amplitud)
        for p in apoya:
            s = dir_der if p in _DERECHA else dir_izq
            ang[p] = _pata(altura, paso=-s * amplitud)
        frames.append(_pose(ang["DD"], ang["DI"], ang["TD"], ang["TI"]) + (tt,))
    return frames


def _revisar(nombre, frames, bucle):
    """Busca problemas en un movimiento y deja en _avisos_calculo QUE cambiar."""
    malos = {}
    for f in frames:
        for k, a in enumerate(f[:12]):
            c = CALIB[SERVOS[k]]
            if a is not None and not max(LIM_SERVO[0], c["min"]) <= a <= min(LIM_SERVO[1], c["max"]):
                malos.setdefault(SERVOS[k][3], set()).add(SERVOS[k])
    # el angulo REAL que tendria que hacer cada servo (con la calibracion): si se sale de 10..170 no llega
    fuera = {}
    for f in frames:
        for k, a in enumerate(f[:12]):
            if a is None:
                continue
            r = _a_servo_libre(SERVOS[k], a)
            if not LIM_SERVO[0] <= r <= LIM_SERVO[1]:
                peor = fuera.get(k)
                if peor is None or abs(r - 90) > abs(peor - 90):
                    fuera[k] = r
    for k, r in fuera.items():
        lado = "bajar" if r > LIM_SERVO[1] else "subir"
        falta = (r - LIM_SERVO[1]) if r > LIM_SERVO[1] else (LIM_SERVO[0] - r)
        dientes = max(1, round(falta / 14.4 + 0.49))
        _avisos_calculo.append(("mal", f"'{nombre}': el servo {k + 1} ({NOMBRE_SERVO[SERVOS[k]]}) tendria que ir a {r:.0f}° "
                                       f"y solo llega de {LIM_SERVO[0]} a {LIM_SERVO[1]}. Sin desarmar: guarda PARADO con ese "
                                       f"servo unos {falta + 5:.0f}° mas hacia el centro (corrigiendo la rodilla), o baja "
                                       "'largo del paso' / 'alto del paso'."))
    if "R" in malos:
        _avisos_calculo.append(("mal", f"'{nombre}': la rodilla pasa el limite del servo (choca y no dobla mas). "
                                       "Baja 'altura' o 'alto del paso'."))
    if "M" in malos:
        _avisos_calculo.append(("mal", f"'{nombre}': el muslo pasa el limite del servo. "
                                       "Baja 'largo del paso' o pon 'centro' mas cerca de 0."))
    if "H" in malos:
        _avisos_calculo.append(("mal", f"'{nombre}': el hombro pasa el limite del servo. Pon 'abrir' mas cerca de 0."))
    # velocidad que se le pide a cada servo entre un paso y el siguiente
    peor, peor_srv = 0.0, None
    seq = list(frames) + (list(frames[:1]) if bucle else [])
    for a, b in zip(seq, seq[1:]):
        t = max(a[12], 0.01)
        for k in range(12):
            if a[k] is not None and b[k] is not None:
                vel = abs(b[k] - a[k]) / t
                if vel > peor:
                    peor, peor_srv = vel, SERVOS[k]
    if peor > VEL_MAX_SERVO:
        _avisos_calculo.append(("warn", f"'{nombre}': le pide al {NOMBRE_SERVO[peor_srv]} {peor:.0f} grados/s y un MG996R "
                                        f"llega a unos {VEL_MAX_SERVO:.0f}. No alcanza: baja 'velocidad' o 'largo del paso'."))


_version_mov = 0             # sube cada vez que cambian los movimientos o la calibracion


def construir_movimientos():
    """Arma todas las poses y secuencias con los ajustes actuales de MARCHA.
    Se llama al arrancar y cada vez que cambias un ajuste: lo que este corriendo toma el cambio en la vuelta siguiente."""
    global SECUENCIAS, _version_mov
    _version_mov += 1
    _ik_recortes.clear()
    altura = MARCHA["altura"]
    POSES.clear()
    POSES.update({
        "pararse":   _pose(),
        # traseras muy dobladas, delanteras casi rectas
        "sentarse":  _pose(dd=_pata(flex_recta()), di=_pata(flex_recta()), td=_pata(min(50, flex_maximo() - 5)), ti=_pata(min(50, flex_maximo() - 5))),
        # las 4 muy dobladas: el cuerpo baja al suelo
        "acostarse": _pose(*[_pata(min(60, flex_maximo() - 5))] * 4),
        # patas rectas de verdad (la rodilla sin doblar), sin importar como se armo
        "recta":     _pose(*[_pata(flex_recta())] * 4),
    })
    saludo = dict(di=_pata(altura, abre=8), td=_pata(min(altura + 10, flex_maximo() - 5), abre=8), ti=_pata(min(altura + 10, flex_maximo() - 5), abre=8))
    v = MARCHA["velocidad"]
    nuevas = {
        "pararse":   {"frames": [POSES["pararse"] + (0.5,)], "repetir": 1, "final": None},
        "sentarse":  {"frames": [POSES["sentarse"] + (0.7,)], "repetir": 1, "final": None},
        "acostarse": {"frames": [POSES["acostarse"] + (0.7,)], "repetir": 1, "final": None},
        "avanzar":    {"frames": _trote(1, 1), "repetir": None, "final": None},
        # t=0.13 y 1.2x el paso: con las medidas 122,5/132 la rodilla no pasa de ~350 grados/s (lo que da un MG996R)
        "correr":     {"frames": _trote(1, 1, amplitud=MARCHA["paso"] * 1.2, t=0.13),
                       "repetir": None, "final": None},
        "retroceder": {"frames": _trote(-1, -1), "repetir": None, "final": None},
        # giro: un lado empuja hacia adelante y el otro hacia atras
        "izquierda":  {"frames": _trote(1, -1, amplitud=MARCHA["paso"] * 0.8), "repetir": None, "final": None},
        "derecha":    {"frames": _trote(-1, 1, amplitud=MARCHA["paso"] * 0.8), "repetir": None, "final": None},
        # gestos
        # agacha y sube el frente rapido
        "ladrar":  {"frames": [_pose(dd=_pata(min(altura + 15, flex_maximo() - 5)), di=_pata(min(altura + 15, flex_maximo() - 5))) + (0.15 / v,),
                               POSES["pararse"] + (0.15 / v,)],
                    "repetir": 3, "final": "pararse"},
        # no hay servo de cola: menea la cadera de lado a lado con los hombros traseros
        "cola":    {"frames": [_pose(td=_pata(altura, abre=12), ti=_pata(altura, abre=-12)) + (0.2 / v,),
                               _pose(td=_pata(altura, abre=-12), ti=_pata(altura, abre=12)) + (0.2 / v,)],
                    "repetir": 4, "final": "pararse"},
        # abre las otras 3 patas para no caerse, sube la delantera derecha y la sacude con la rodilla
        "saludar": {"frames": [_pose(**saludo) + (0.4,),
                               _pose(dd=(90, 150, 70), **saludo) + (0.35,),
                               _pose(dd=(90, 150, 110), **saludo) + (0.25,),
                               _pose(dd=(90, 150, 70), **saludo) + (0.25,),
                               _pose(dd=(90, 150, 110), **saludo) + (0.5,)],
                    "repetir": 1, "final": "pararse"},
        # trote en el sitio, rapido
        "feliz":   {"frames": _trote(0, 0, amplitud=0, t=0.12),
                    "repetir": 4, "final": "pararse"},
        # agacha el frente y sube la cola
        "enojado": {"frames": [_pose(dd=_pata(33, paso=-5), di=_pata(33, paso=-5), td=_pata(5), ti=_pata(5)) + (1.2,)],
                    "repetir": 1, "final": "pararse"},
        # retrocede rapido y vuelve a pararse (lo usa el banco de pruebas)
        "asustarse": {"frames": _trote(-1, -1, amplitud=MARCHA["paso"] * 1.2, t=0.10),
                      "repetir": 3, "final": "pararse"},
        # para calibrar: mueve cada articulacion sola, un poco, en el sentido "positivo"
        "probar_articulaciones": {"frames": [], "repetir": 1, "final": "pararse"},
    }
    for k, n in enumerate(SERVOS):
        sube = [None] * 12
        sube[k] = 115 if n.endswith("_M") or n.endswith("_H") else 65   # muslo adelante / hombro afuera / rodilla doblada
        nuevas["probar_articulaciones"]["frames"] += [tuple(NEUTRO) + (0.6,), tuple(sube) + (1.2,)]
    nuevas["probar_articulaciones"]["frames"].append(tuple(NEUTRO) + (0.8,))

    _avisos_calculo.clear()
    if _ik_recortes:
        _avisos_calculo.append(("warn", f"Algunas poses ponen el pie mas lejos de lo que alcanza la pata "
                                        f"(muslo {LARGO_MUSLO:.0f} mm + pierna {LARGO_PIERNA:.0f} mm): se acerca al punto "
                                        "mas cercano. Baja 'largo del paso' o sube 'altura', y revisa las medidas de la pata."))
    for nombre in ("pararse", "avanzar", "correr", "retroceder", "izquierda", "derecha", "saludar", "feliz", "cola"):
        _revisar(nombre, nuevas[nombre]["frames"], nuevas[nombre]["repetir"] is None)
    try:
        SECUENCIAS.clear()
        SECUENCIAS.update(nuevas)        # mismo diccionario: el banco y los hilos que corren lo ven al instante
    except NameError:
        SECUENCIAS = nuevas


def marcha_actual():
    return dict(MARCHA)


def avisos_marcha():
    """Lista de (nivel, texto) con lo que esta mal en los movimientos y que cambiar."""
    return list(_avisos_calculo)


def cambiar_marcha(cambios, guardar=True):
    """Cambia ajustes de la marcha en vivo. cambios = {"altura": 22, ...}. Devuelve la marcha nueva."""
    for k, v in (cambios or {}).items():
        if k == "restablecer" and v:
            MARCHA.clear()
            MARCHA.update(MARCHA_INICIAL)
            continue
        if k in RANGOS_MARCHA:
            try:
                lo, hi = RANGOS_MARCHA[k]
                MARCHA[k] = round(max(lo, min(hi, float(v))), 2)
            except (TypeError, ValueError):
                continue
    construir_movimientos()
    if guardar:
        try:
            with open(_RUTA_MARCHA, "w", encoding="utf-8") as f:
                _json.dump(MARCHA, f, indent=2)
        except OSError:
            pass
    return dict(MARCHA)


construir_movimientos()

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
     "Si alguno va al reves, marca 'Invertir' en la app (Ajustes > Calibrar servos)."),
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

# "repite correr", "corre sin parar", "en bucle da la pata": la accion se repite hasta "quieto"
_RE_BUCLE = re.compile(r"^(?:repite|repetir|en bucle|seguido|sin parar)(?: a| el| la)? (.+)$|^(.+?) (?:sin parar|en bucle|seguido|una y otra vez)$")
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


_ultima_pose = [None] * 12   # lo ultimo que se mando (en grados de Arche), para re-mandarlo al calibrar

# ---- probar patas por separado ------------------------------------------------
# Patas que se mueven con las acciones (caminar, correr, sentarse...). Las demas se quedan en la pose
# de PARADO, quietas. Sirve para ver una sola pata haciendo el movimiento y encontrar cual esta mal.
# No se guarda: al reiniciar Arche vuelven a moverse las 4.
PATAS_ACTIVAS = set(PATAS)


def cambiar_patas_activas(patas):
    """patas = ["DD", "TI"] o [] / None = las 4. Devuelve la lista ordenada de las que se mueven."""
    elegidas = {p for p in (patas or []) if p in PATAS}
    PATAS_ACTIVAS.clear()
    PATAS_ACTIVAS.update(elegidas or PATAS)
    if not _ejecutor.actual and any(a is not None for a in _ultima_pose):
        try:
            _aplicar(POSES["pararse"])     # las que quedaron fuera vuelven a parado al instante
        except RobotError:
            pass
    return patas_activas()


def patas_activas():
    return [p for p in PATAS if p in PATAS_ACTIVAS]


def _filtrar_patas(angulos):
    """Las patas que no estan activas reciben la pose de PARADO en vez de la del movimiento."""
    doce = list(_a_doce(angulos))
    if len(PATAS_ACTIVAS) == len(PATAS):
        return doce
    parado = POSES["pararse"]
    for k, n in enumerate(SERVOS):
        if n[:2] not in PATAS_ACTIVAS:
            doce[k] = parado[k]
    return doce


def _aplicar(angulos):
    """Manda los 12 angulos en un solo mensaje. None = no tocar ese servo."""
    partes = []
    for k, (nombre, ang) in enumerate(zip(SERVOS, _a_doce(angulos))):
        if ang is None:
            partes.append("-1")
            continue
        _ultima_pose[k] = ang
        partes.append(str(_a_servo(nombre, ang)))
    _obtener_cliente().publish(TOPIC_SERVOS, ",".join(partes), qos=0)


# ------------------------------------------------------------- calibracion
def capturar_pose(cual):
    """Guarda los angulos REALES actuales de los 12 servos (los que pusiste en Armar) como la pose
    'parado' o 'echado'. Con PARADO (y mejor tambien ECHADO) Arche calcula sola la calibracion."""
    if cual not in CAPTURAS:
        raise RobotError("Pose invalida (parado o echado).")
    if any(a is None for a in _crudo):
        raise RobotError("Primero mueve los 12 servos en Armar (o toca 'Todos a 90°') para que Arche sepa donde esta cada uno.")
    logico = POSES["pararse" if cual == "parado" else "acostarse"]
    CAPTURAS[cual] = {"raw": list(_crudo), "logico": [float(x) for x in logico], "hora": time.strftime("%Y-%m-%d %H:%M")}
    if CAPTURAS["parado"]:
        _aplicar_capturas()
    else:
        _resultado_captura[:] = [("warn", "Guardado ECHADO. Ahora pon el perro PARADO y toca 'Guardar como PARADO'.")]
    construir_movimientos()
    _guardar_calibracion()
    return list(_resultado_captura)


def _aplicar_capturas():
    """Con la pose PARADO (y ECHADO si existe) calcula invertir y base de cada servo."""
    par, ech = CAPTURAS["parado"], CAPTURAS["echado"]
    res, invertidos = [], []
    for k, n in enumerate(SERVOS):
        c = CALIB[n]
        raw_p, L_p = par["raw"][k], par["logico"][k]
        if ech:
            dL = ech["logico"][k] - L_p
            dR = ech["raw"][k] - raw_p
            if abs(dL) >= 8 and abs(dR) >= 5:
                c["invertir"] = (dL * dR) < 0
                razon = abs(dR) / abs(dL)
                if not 0.5 <= razon <= 1.8:
                    res.append(("warn", f"Servo {k + 1} ({NOMBRE_SERVO[n]}): de parado a echado se movio {abs(dR):.0f}° y "
                                        f"Arche esperaba unos {abs(dL):.0f}°. Revisa que las dos poses esten bien puestas."))
            elif abs(dL) >= 8:
                res.append(("warn", f"Servo {k + 1} ({NOMBRE_SERVO[n]}): casi no cambio entre PARADO y ECHADO; "
                                    "no pude saber hacia donde gira. Usa 'Probar' en Calibrar servos."))
        if c["invertir"]:
            invertidos.append(str(k + 1))
        c["base"] = round(raw_p - ((180 - L_p) if c["invertir"] else L_p))
        c["ajuste"] = 0
        # poco recorrido desde la pose de parado: al caminar se va a quedar corto
        if n[3] in "MR" and (raw_p < LIM_SERVO[0] + 20 or raw_p > LIM_SERVO[1] - 20):
            meta = LIM_SERVO[0] + 30 if raw_p < 90 else LIM_SERVO[1] - 30
            res.append(("mal", f"Servo {k + 1} ({NOMBRE_SERVO[n]}): parado esta en {raw_p}°, pegado al tope "
                               f"({LIM_SERVO[0]}-{LIM_SERVO[1]}) y al caminar no tendra para donde moverse. "
                               f"Sin desarmar: en Armar llevalo a unos {meta}° (inclinado hacia el centro), corrige la "
                               "rodilla de esa pata hasta que el pie quede debajo de la cadera y vuelve a guardar PARADO."))
    res.insert(0, ("ok", "Calibracion calculada con tus poses" + (" PARADO y ECHADO." if ech else " (solo PARADO: "
                         "guarda tambien ECHADO para que Arche sepa hacia donde gira cada servo).")
                   + (f" Servos invertidos: {', '.join(invertidos)}." if invertidos else "")))
    _resultado_captura[:] = res


def estado_capturas():
    return {"parado": (CAPTURAS["parado"] or {}).get("hora"), "echado": (CAPTURAS["echado"] or {}).get("hora"),
            "resultado": [{"nivel": a, "texto": b} for a, b in _resultado_captura]}


def calibracion_actual():
    """[{n, nombre, invertir, base, ajuste, min, max}, ...] en el orden de los canales."""
    return [{"n": k + 1, "id": n, "nombre": NOMBRE_SERVO[n], **CALIB[n]} for k, n in enumerate(SERVOS)]


def _guardar_calibracion():
    try:
        with open(_RUTA_CALIB, "w", encoding="utf-8") as f:
            _json.dump({**CALIB, "_rodillas": RODILLAS, "_rodilla_en_90": RODILLA_EN_90,
                        "_largo_muslo": LARGO_MUSLO, "_largo_pierna": LARGO_PIERNA, "_capturas": CAPTURAS}, f, indent=2)
    except OSError:
        pass


def cambiar_calibracion(d, guardar=True):
    """d = {"servo": 1..12, "ajuste": 3, "invertir": true, "min": 20, "max": 160}  o  {"restablecer": true}.
    Se aplica al instante: si el perro esta quieto, re-manda la ultima pose para que veas el cambio."""
    global RODILLAS, RODILLA_EN_90, LARGO_MUSLO, LARGO_PIERNA
    d = d or {}
    if d.get("restablecer"):
        CALIB.clear()
        CALIB.update(_calib_fabrica())
        RODILLAS, RODILLA_EN_90 = "atras", 90
        LARGO_MUSLO, LARGO_PIERNA = 122.5, 132.0
        CAPTURAS.update({"parado": None, "echado": None})
        _resultado_captura.clear()
    elif d.get("rodillas") in ("atras", "adelante"):
        RODILLAS = d["rodillas"]
    elif "largo_muslo" in d or "largo_pierna" in d:
        try:
            if "largo_muslo" in d:
                LARGO_MUSLO = float(max(RANGO_LARGO[0], min(RANGO_LARGO[1], float(d["largo_muslo"]))))
            if "largo_pierna" in d:
                LARGO_PIERNA = float(max(RANGO_LARGO[0], min(RANGO_LARGO[1], float(d["largo_pierna"]))))
        except (TypeError, ValueError):
            raise RobotError("El largo tiene que ser un numero en milimetros.")
    elif "rodilla_en_90" in d:
        try:
            RODILLA_EN_90 = int(max(0, min(120, float(d["rodilla_en_90"]))))
        except (TypeError, ValueError):
            pass
    else:
        try:
            k = int(d.get("servo")) - 1
            nombre = SERVOS[k]
        except (TypeError, ValueError, IndexError):
            raise RobotError("Servo invalido (van del 1 al 12).")
        c = CALIB[nombre]
        if "invertir" in d:
            c["invertir"] = bool(d["invertir"])
        if "ajuste" in d:
            c["ajuste"] = int(max(RANGO_AJUSTE[0], min(RANGO_AJUSTE[1], float(d["ajuste"]))))
        if "min" in d:
            c["min"] = int(max(0, min(90, float(d["min"]))))
        if "max" in d:
            c["max"] = int(max(90, min(180, float(d["max"]))))
    construir_movimientos()              # los avisos de limites se recalculan con los nuevos min/max
    if guardar:
        _guardar_calibracion()
    if not _ejecutor.actual and any(a is not None for a in _ultima_pose):
        try:
            _aplicar(list(_ultima_pose))
        except RobotError:
            pass
    return calibracion_actual()


def pose_calibrar(cual):
    """'recta' = las 12 en 90: la posicion de armado (hombro y muslo verticales, rodilla en L) | 'parado' = pararse."""
    if cual == "parado":
        _ejecutor.quieto()
        return
    with _ejecutor._lock:
        _ejecutor._cancelar.set()
        _ejecutor.actual, _ejecutor.en_bucle = None, False
    _aplicar(NEUTRO)


# ------------------------------------------------------- mover servos "en crudo" (para armar)
# Aqui NO se aplica la calibracion: el angulo es el real del servo (el que ve el ESP32),
# para que veas todo su recorrido y decidas en que diente poner cada pieza.
_crudo = [None] * 12          # ultimo angulo crudo mandado a cada servo


def _parar_movimientos():
    with _ejecutor._lock:
        _ejecutor._cancelar.set()
        _ejecutor._cancelar = threading.Event()
        _ejecutor.actual, _ejecutor.en_bucle = None, False
        return _ejecutor._cancelar


def _mandar_crudo(angulos):
    _obtener_cliente().publish(TOPIC_SERVOS, ",".join("-1" if a is None else str(int(a)) for a in angulos), qos=0)


def mover_crudo(servo=None, angulo=90):
    """Mueve un servo (1..12) o todos (servo=None) al angulo REAL dado, sin calibracion."""
    angulo = max(LIM_SERVO[0], min(LIM_SERVO[1], int(round(float(angulo)))))
    _parar_movimientos()
    angs = [None] * 12
    if servo is None:
        angs = [angulo] * 12
    else:
        k = int(servo) - 1
        if not 0 <= k < 12:
            raise RobotError("Los servos van del 1 al 12.")
        angs[k] = angulo
    for k, a in enumerate(angs):
        if a is not None:
            _crudo[k] = a
    _mandar_crudo(angs)
    return angulo


def barrer(servo):
    """Recorre TODO el giro de un servo despacio (90 -> min -> max -> 90) para ver su rango completo."""
    k = int(servo) - 1
    if not 0 <= k < 12:
        raise RobotError("Los servos van del 1 al 12.")
    cancelar = _parar_movimientos()
    desde = _crudo[k] if _crudo[k] is not None else 90
    tramos = [(desde, LIM_SERVO[0]), (LIM_SERVO[0], LIM_SERVO[1]), (LIM_SERVO[1], 90)]

    def _ir():
        try:
            for a, b in tramos:
                paso = 2 if b > a else -2
                for ang in range(a, b + paso, paso):
                    if cancelar.is_set():
                        return
                    angs = [None] * 12
                    angs[k] = ang
                    _crudo[k] = ang
                    _mandar_crudo(angs)
                    cancelar.wait(0.03)         # unos 65 grados por segundo: despacio, para mirarlo
                if cancelar.wait(0.5):
                    return
        except RobotError:
            pass
    threading.Thread(target=_ir, name="robot-barrer", daemon=True).start()
    return f"Barriendo el servo {k + 1} ({NOMBRE_SERVO[SERVOS[k]]}): de {LIM_SERVO[0]} a {LIM_SERVO[1]} grados y vuelve a 90."


def probar_servo(servo):
    """Mueve SOLO ese servo un poco en el sentido 'positivo' y lo devuelve: hombro afuera, muslo adelante,
    rodilla se dobla. Si va al reves, marca 'invertir' en ese servo."""
    k = int(servo) - 1
    nombre = SERVOS[k]
    base = list(_ultima_pose) if any(a is not None for a in _ultima_pose) else list(NEUTRO)
    base = [90 if a is None else a for a in base]
    mov = list(base)
    mov[k] = base[k] + (25 if nombre[3] in "HM" else -25)
    with _ejecutor._lock:
        _ejecutor._cancelar.set()
        _ejecutor.actual, _ejecutor.en_bucle = None, False

    def _ida_y_vuelta():
        try:
            _aplicar(mov)
            time.sleep(0.9)
            _aplicar(base)
        except RobotError:
            pass
    threading.Thread(target=_ida_y_vuelta, daemon=True).start()
    hacia = {"H": "abrir hacia AFUERA", "M": "ir hacia ADELANTE (hacia la cabeza)", "R": "DOBLARSE"}[nombre[3]]
    return f"Servo {k + 1} ({NOMBRE_SERVO[nombre]}): debe {hacia}. Si fue al reves, marca 'Invertir'."


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
        self.actual = None           # que esta haciendo ahora
        self.en_bucle = False
        self.vueltas = 0

    def _secuencia_cruda(self, nombre, bucle):
        """La secuencia en angulos REALES (con la calibracion), lista para mandarla entera al ESP32."""
        sec = SECUENCIAS[nombre]
        veces = 0 if (bucle or sec["repetir"] is None) else int(sec["repetir"])
        frames = [list(f) for f in sec["frames"]]
        if veces and sec["final"]:
            frames.append(list(POSES[sec["final"]]) + [0.3])
        partes = [str(veces)]
        for f in frames:
            angs = ["-1" if a is None else str(_a_servo(n, a)) for n, a in zip(SERVOS, _filtrar_patas(f[:-1]))]
            partes.append(str(int(round(f[-1] * 1000))) + "," + ",".join(angs))
        ultimo = _filtrar_patas(frames[-1][:-1])
        for k, a in enumerate(ultimo):
            if a is not None:
                _ultima_pose[k] = a
        duracion = sum(f[-1] for f in sec["frames"])
        return ";".join(partes), veces, duracion

    def _reproducir_en_esp(self, nombre, cancelar, bucle):
        """El ESP32 reproduce la secuencia solo; aqui solo se le confirma que siga (y se re-manda si cambias ajustes)."""
        cliente = _obtener_cliente()
        texto, veces, duracion = self._secuencia_cruda(nombre, bucle)
        cliente.publish(TOPIC_SECUENCIA, texto, qos=1)
        version, t0 = _version_mov, time.time()
        if veces == 0:
            while not cancelar.wait(1.0):
                cliente.publish(TOPIC_SIGUE, "1", qos=0)
                if _version_mov != version:          # cambiaste la marcha o la calibracion: manda la nueva
                    texto, _, duracion = self._secuencia_cruda(nombre, bucle)
                    cliente.publish(TOPIC_SECUENCIA, texto, qos=1)
                    version = _version_mov
                self.vueltas = int((time.time() - t0) / max(duracion, 0.05))
        else:
            if not cancelar.wait(duracion * veces + 0.4):
                self.vueltas = veces

    def _reproducir(self, nombre, cancelar, bucle):
        try:
            if ESP_SECUENCIAS:
                self._reproducir_en_esp(nombre, cancelar, bucle)
                return
            veces = None if bucle else SECUENCIAS[nombre]["repetir"]
            i = 0
            while not cancelar.is_set() and (veces is None or i < veces):
                sec = SECUENCIAS[nombre]          # se lee en cada vuelta: toma al instante los ajustes nuevos
                for *angulos, pausa in sec["frames"]:
                    if cancelar.is_set():
                        return
                    _aplicar(_filtrar_patas(angulos))
                    cancelar.wait(pausa)
                i += 1
                self.vueltas = i
            sec = SECUENCIAS[nombre]
            if sec["final"] and not cancelar.is_set():
                _aplicar(POSES[sec["final"]])
        except RobotError as e:
            self.error = str(e)
        finally:
            if not cancelar.is_set():
                self.actual, self.en_bucle = None, False

    def ejecutar(self, nombre, bucle=False):
        """Arranca la accion (bucle=True: la repite sin parar hasta 'quieto'). Devuelve el hilo."""
        if nombre not in SECUENCIAS:
            raise RobotError(f"No conozco el movimiento '{nombre}'.")
        _obtener_cliente()   # falla ya (y se lo explica al usuario) si no hay MQTT
        with self._lock:
            self._cancelar.set()
            cancelar = threading.Event()
            self._cancelar = cancelar
            self.error = None
            self.actual, self.en_bucle, self.vueltas = nombre, bool(bucle), 0
            self._hilo = threading.Thread(target=self._reproducir, args=(nombre, cancelar, bool(bucle)),
                                          name="robot-mov", daemon=True)
            self._hilo.start()
            return self._hilo

    def quieto(self):
        """Corta cualquier movimiento y deja al perro parado."""
        with self._lock:
            self._cancelar.set()
            self.actual, self.en_bucle = None, False
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
        "- repite <accion> / <accion> sin parar (ej. 'repite correr'): la hace en bucle hasta 'quieto', para que la ajustes",
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

        m = _RE_BUCLE.match(t)
        if m:
            dentro = (m.group(1) or m.group(2) or "").strip()
            for nombre, patron, _resp in _ACCIONES_RE:
                if patron.match(dentro) and nombre != "quieto":
                    _ejecutor.ejecutar(nombre, bucle=True)
                    _modo_perro.interaccion(3600)
                    return (f"Repito '{nombre}' sin parar. Ajusta en vivo desde la app (Ordenes > Ajustar la marcha). "
                            "Di 'quieto' para parar.")

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