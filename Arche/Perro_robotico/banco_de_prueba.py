"""banco_de_prueba.py Banco de pruebas del perro robotico:  celular (ojos) -> Arche (cerebro) -> ESP32 (patas).

    celular  --JPEG por WiFi-->  Arche (vision + reglas)  --MQTT-->  ESP32 (4 servos)

Dos formas de usarlo:
  1) Dentro de Arche: di "banco de pruebas" (ver el parche de main.py).
  2) Suelto, desde esta carpeta:   python banco_pruebas.py
     opciones:  --fuente http://IP:8080/video   (usar una app tipo "IP Webcam" en vez de la pagina /camara)
                --http                          (sin HTTPS; solo sirve con --fuente)
                --puerto 5000

Necesita:  pip install flask opencv-python numpy paho-mqtt cryptography
(cryptography solo hace falta para el HTTPS que exige el navegador del celular para abrir la camara)

Seguridad:
  * Arranca en PARO. Nada se mueve hasta que elijas Manual o Perro en el panel.
  * Paro de emergencia en el panel (y "parada de emergencia" en la consola de Arche).
  * Paro automatico si: se pierde el video del celular, se pierde el ESP32 (latido) o cae el MQTT.
    Ademas el nuevo .ino pone las patas rectas si el ESP32 pierde el MQTT mas de 5 s.
"""

import argparse
import atexit
import collections
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, redirect, request, send_file, send_from_directory

import acciones_robot as ar          # patas, secuencias y MQTT de publicacion
import acceso                        # clave para cuando se entra por el tunel de internet
from vision import Detector, PRESETS_COLOR, anotar

HERE = os.path.dirname(os.path.abspath(__file__))
RUTA_CFG = os.path.join(HERE, "banco_config.json")

PUERTO = 5000
TIMEOUT_CAMARA = 3.0        # s sin cuadros -> paro
TIMEOUT_ESP = 6.0           # s sin latido del ESP32 -> paro (el .ino manda uno cada 2 s)
GRACIA_TRAS_ACTIVAR = 5.0   # s de margen despues de activar/reanudar antes de vigilar

EVENTOS = ["cara", "pelota", "movimiento", "cerca", "nada"]
REACCIONES = ["ninguna", "quieto", "saludar", "feliz", "cola", "ladrar", "enojado", "sentarse", "pararse",
              "acostarse", "avanzar", "correr", "retroceder", "izquierda", "derecha", "asustarse"]
MAPA_INICIAL = {"cara": "saludar", "pelota": "avanzar", "movimiento": "asustarse", "cerca": "quieto", "nada": "quieto"}

# cuadros seguidos que hacen falta para dar por buena una deteccion (evita parpadeos).
# Estan pensados para 15 fps: con mas fps ademas se exige el mismo TIEMPO, asi el perro
# reacciona igual de rapido/lento aunque lleguen 30 cuadros por segundo.
CONFIRMAR = {"movimiento": 1, "cerca": 2, "cara": 2, "pelota": 2, "nada": 8}
CONFIRMAR_SEG = {k: (n - 1) / 15.0 for k, n in CONFIRMAR.items()}

LOCOMOCION = {"avanzar", "retroceder", "izquierda", "derecha", "correr"}

# movimiento nuevo (no estaba en acciones_robot.py): retrocede rapido y vuelve a la pose recta
ar.SECUENCIAS.setdefault("asustarse", {
    "frames": [(60, 120, 120, 60, 0.12), (120, 60, 60, 120, 0.12)],
    "repetir": 5, "final": "pararse",
})


def duracion(nombre):
    """Segundos que dura un gesto de una sola pasada (0 si va en bucle o no existe)."""
    s = ar.SECUENCIAS.get(nombre)
    if not s or s.get("repetir") is None:
        return 0.0
    return sum(f[-1] for f in s["frames"]) * s["repetir"]


# ====================================================== cerebro del modo perro
class CerebroPerro:
    """Reglas de personalidad. Recibe el evento confirmado y devuelve la accion
    a mandar (o None = seguir como esta)."""

    def __init__(self):
        self.params = {"seg_sentarse": 20.0, "seg_dormir": 60.0}
        self.reiniciar(time.time())

    def reiniciar(self, t):
        self.postura = "parado"       # parado | sentado | acostado
        self.accion = None
        self.mood = "tranquilo"
        self.razon = "Esperando."
        self.susto_hasta = 0.0
        self.ocupado_hasta = 0.0
        self.ultimo_cmd = 0.0
        self.visto_hace = t           # ultima vez que vio algo
        self.saludo_hecho = False

    def _hacer(self, accion, t):
        self.accion = accion
        self.ultimo_cmd = t
        self.postura = {"sentarse": "sentado", "acostarse": "acostado"}.get(accion, "parado")
        self.ocupado_hasta = t + duracion(accion)
        return accion

    @staticmethod
    def _girar(x, invertir):
        if invertir:
            x = -x
        if x < -0.30:
            return "izquierda"
        if x > 0.30:
            return "derecha"
        return "avanzar"

    def decidir(self, ev, x, t, invertir=False):
        if ev != "nada":
            self.visto_hace = t

        if t < self.susto_hasta:                      # congelado por el susto
            return None

        if ev == "movimiento":                        # 1) se asusta y retrocede
            self.susto_hasta = t + 3.0
            self.mood = "asustado"
            self.razon = "Movimiento brusco: se asusta y retrocede."
            return self._hacer("asustarse", t)

        if ev == "cerca":                             # 2) algo cerca: se detiene
            self.mood = "cauteloso"
            self.razon = "Algo esta muy cerca: se detiene."
            return self._hacer("quieto", t) if self.accion != "quieto" else None

        if ev in ("cara", "pelota"):                  # 3) cara: alegria y acercarse / pelota: perseguir
            if self.postura != "parado":
                self.razon = "Se despierta/levanta para reaccionar."
                return self._hacer("pararse", t)
            if t < self.ocupado_hasta:
                return None
            if ev == "cara":
                self.mood = "alegre"
                if not self.saludo_hecho:
                    self.saludo_hecho = True
                    self.razon = "Ve una cara: se alegra."
                    return self._hacer("feliz", t)
                self.razon = "Se acerca a la cara."
            else:
                self.mood = "cazador"
                self.razon = "Persigue la pelota."
            accion = self._girar(x, invertir)
            if accion == self.accion or t - self.ultimo_cmd < 0.5:
                return None
            return self._hacer(accion, t)

        # 4) no ve nada
        sin_ver = t - self.visto_hace
        if self.accion in LOCOMOCION:
            self.razon = "Ya no ve nada: se detiene."
            return self._hacer("quieto", t)
        if t < self.ocupado_hasta:
            return None
        if sin_ver > 3.0:
            self.saludo_hecho = False                 # la proxima cara vuelve a saludarla
        if sin_ver > self.params["seg_dormir"] and self.postura != "acostado":
            self.mood = "dormido"
            self.razon = f"Aburrido hace {sin_ver:.0f} s: se duerme."
            return self._hacer("acostarse", t)
        if sin_ver > self.params["seg_sentarse"] and self.postura == "parado":
            self.mood = "aburrido"
            self.razon = f"Sin nada que hacer hace {sin_ver:.0f} s: se sienta."
            return self._hacer("sentarse", t)
        if self.postura == "parado" and self.mood not in ("tranquilo",) and sin_ver > 4.0:
            self.mood = "tranquilo"
            self.razon = "Tranquilo."
        return None


# ============================================================ el banco
class Banco:
    def __init__(self):
        self.detector = Detector()
        self.cerebro = CerebroPerro()
        self.lock = threading.RLock()        # percepcion + decisiones
        self.lock_lat = threading.Lock()     # latencias (el ack llega por otro hilo)
        self._fin = threading.Event()

        self.modo = "paro"                   # paro | manual | perro | ordenes
        self.modo_previo = "manual"
        self.motivo_paro = "Arranca en paro: elige Manual o Perro."
        self.gracia_hasta = 0.0
        # pausa = algo se corto un momento (video, ESP32, MQTT). El robot se queda quieto,
        # pero el modo NO se pierde: cuando todo vuelve, sigue solo (sin tocar Reanudar).
        self.pausa = ""

        self.mapa = dict(MAPA_INICIAL)
        self.cooldown = 2.5
        self.invertir_giro = False
        # False = no le importa si la camara esta prendida: Manual/Perro arrancan sin video
        # y no se pausa si se corta (el modo Perro sigue solo, como si no viera nada).
        self.usar_camara = True

        # percepcion
        self.ev = "nada"
        self.cand = "nada"
        self.cand_n = 0
        self.cand_t0 = 0.0
        self.res = None
        self.ultimo_x = {"cara": 0.0, "pelota": 0.0}
        self.ultimo_jpg = None
        self.ultimo_n = 0                    # numero del cuadro que hay en ultimo_jpg
        self.hay_cuadro = threading.Condition()
        self.cam_id = None                   # para descartar cuadros que llegan tarde (la app manda varios a la vez)
        self.cam_seq = 0
        # imagen ORIGINAL del celular (sin recomprimir) + lo detectado, para que el panel dibuje las cajas
        self.crudo = None
        self.crudo_n = 0
        self.crudo_info = None
        self.pide_anotado_t = 0.0            # ultima vez que alguien pidio la imagen con marcas quemadas
        self.t_ultimo_cuadro = 0.0
        self.tiempos = collections.deque(maxlen=20)
        self.cuadros = 0
        self.ev_manual_prev = "nada"
        self.ultima_reaccion = 0.0
        self.accion_actual = None
        self.ultimo_error = ""

        # latencias
        self.lat_det = collections.deque(maxlen=30)
        self.lat_red = collections.deque(maxlen=30)
        self.historial = collections.deque(maxlen=30)
        self.stats = {e: {"n": 0, "suma": 0.0, "min": None, "max": None} for e in EVENTOS + ["prueba"]}
        self.pendiente = None
        self.contador = 0

        # estado del ESP32 / MQTT (lo reporta el .ino)
        self.esp_estado = None
        self.last_hb = 0.0
        self.hb_visto = False
        self.mon_conectado = False
        self.mon_visto = False
        self.mon_error = ""
        # datos que manda el ESP32 cada 2 s por BASE/info (senal, reinicio, servos...)
        self.esp_info = None
        self.t_esp_info = 0.0
        self.esp_reinicios = 0           # reinicios vistos desde que se abrio el banco

        self._cargar()
        self._iniciar_mqtt()
        threading.Thread(target=self._vigilante, name="banco-vigilante", daemon=True).start()

    # ------------------------------------------------------------ persistencia
    def _cargar(self):
        try:
            with open(RUTA_CFG, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        for k, v in d.get("mapa", {}).items():
            if k in EVENTOS and v in REACCIONES:
                self.mapa[k] = v
        self.aplicar_config({**d.get("detector", {}), **d.get("perro", {}),
                             "cooldown": d.get("cooldown", self.cooldown),
                             "invertir_giro": d.get("invertir_giro", self.invertir_giro),
                             "usar_camara": d.get("usar_camara", self.usar_camara)}, guardar=False)

    def _guardar(self):
        try:
            with open(RUTA_CFG, "w", encoding="utf-8") as f:
                json.dump({"mapa": self.mapa, "cooldown": self.cooldown, "invertir_giro": self.invertir_giro,
                           "usar_camara": self.usar_camara,
                           "detector": self.detector.config, "perro": self.cerebro.params}, f, indent=2)
        except OSError:
            pass

    RANGOS = {
        "umbral_movimiento": (0.01, 0.8), "cerca_por_tamano": (0.02, 0.9), "cerca_pelota": (0.01, 0.9),
        "cerca_por_textura": (0.02, 0.9), "area_min_pelota": (0.0005, 0.1),
        "cooldown": (0.0, 30.0), "seg_sentarse": (3.0, 600.0), "seg_dormir": (5.0, 1800.0),
    }

    def aplicar_config(self, d, guardar=True):
        for k, v in d.items():
            try:
                if k == "color_pelota":
                    if v in PRESETS_COLOR:
                        self.detector.config[k] = v
                elif k == "invertir_giro":
                    self.invertir_giro = bool(v)
                elif k == "usar_camara":
                    self.usar_camara = bool(v)
                    if not self.usar_camara and self.pausa.startswith("Se perdio el video"):
                        self.pausa = ""          # si estaba en pausa solo por la camara, sigue
                elif k in self.RANGOS:
                    lo, hi = self.RANGOS[k]
                    v = max(lo, min(hi, float(v)))
                    if k == "cooldown":
                        self.cooldown = v
                    elif k in self.cerebro.params:
                        self.cerebro.params[k] = v
                    elif k in self.detector.config:
                        self.detector.config[k] = v
            except (TypeError, ValueError):
                continue
        if guardar:
            self._guardar()

    def set_mapa(self, evento, accion):
        if evento in EVENTOS and accion in REACCIONES:
            self.mapa[evento] = accion
            self._guardar()
            return True
        return False

    # ------------------------------------------------------------------ MQTT
    def _iniciar_mqtt(self):
        if ar.mqtt is None:
            self.mon_error = "Falta paho-mqtt (pip install paho-mqtt)."
            return
        base = ar.TOPICS["DD"].rsplit("/pata/", 1)[0]
        self.t_estado, self.t_hb, self.t_ack = base + "/estado", base + "/hb", base + "/ack"
        self.t_info = base + "/info"
        try:
            c = ar.mqtt.Client(ar.mqtt.CallbackAPIVersion.VERSION2)   # paho-mqtt 2.x
        except AttributeError:
            c = ar.mqtt.Client()                                       # paho-mqtt 1.x

        def on_connect(cl, userdata, flags, rc, *extra):
            self.mon_conectado = True
            self.mon_visto = True
            cl.subscribe([(self.t_estado, 0), (self.t_hb, 0), (self.t_ack, 0), (self.t_info, 0)])

        def on_disconnect(cl, userdata, *args):
            self.mon_conectado = False

        def on_message(cl, userdata, msg):
            ahora = time.perf_counter()
            if msg.topic == self.t_hb:
                self.last_hb = time.time()
                self.hb_visto = True
            elif msg.topic == self.t_estado:
                self.esp_estado = msg.payload.decode("utf-8", "ignore").strip()
            elif msg.topic == self.t_ack:
                self._on_ack(ahora)
            elif msg.topic == self.t_info:
                self._on_info(msg.payload)

        c.on_connect, c.on_disconnect, c.on_message = on_connect, on_disconnect, on_message
        try:
            c.connect_async(ar.MQTT_BROKER, ar.MQTT_PORT, 30)
            c.loop_start()
        except Exception as e:
            self.mon_error = f"No pude iniciar el monitor MQTT ({e})."
        self._mon = c

    def _on_info(self, payload):
        try:
            d = json.loads(payload.decode("utf-8", "ignore"))
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        previo = self.esp_info
        if previo and isinstance(d.get("up"), (int, float)) and d["up"] < previo.get("up", 0):
            self.esp_reinicios += 1      # el tiempo encendido volvio a empezar: se reinicio
        self.esp_info = d
        self.t_esp_info = time.time()
        ar.ESP_SECUENCIAS = bool(d.get("seq"))   # el ESP32 nuevo reproduce las secuencias solo

    def diagnostico(self):
        """Lo que esta saliendo mal ahora mismo y QUE cambiar. Lista de {"nivel": ok|warn|mal, "texto": ...}."""
        d = []
        t = time.time()
        i = self.esp_info or {}
        if self.esp_perdido():
            d.append(("mal", "El ESP32 no responde: revisa que este prendido y con WiFi (monitor serie: 'MQTT conectado')."))
        elif not self.hb_visto:
            d.append(("warn", "Todavia no llega el latido del ESP32. Si no llega en unos segundos, revisa su WiFi."))
        if i.get("reinicio") == "bajo voltaje" or self.esp_reinicios:
            d.append(("mal", "El ESP32 se reinicia (bajo voltaje): la fuente no aguanta los 12 servos. "
                             "Usa bateria 2S + regulador buck de 6 V y 20 A para los servos, y uno aparte de 5 V para el ESP32. "
                             "Mientras tanto baja 'velocidad' y 'largo del paso' para que pidan menos corriente."))
        if isinstance(i.get("rssi"), (int, float)) and i["rssi"] < -72:
            d.append(("warn", f"Senal WiFi del ESP32 debil ({i['rssi']} dBm): las ordenes llegan tarde y el paso se ve a saltos. "
                              "Acerca el perro al router o usa el hotspot del celular cerca."))
        if self.t_esp_info and t - self.t_esp_info > 6 and not self.esp_perdido():
            d.append(("warn", "El ESP32 dejo de mandar sus datos: puede estar trabado. Reinicialo (boton EN)."))
        # perro_esp32.ino (el de esta carpeta) no reproduce secuencias solo: Arche le manda cada paso.
        # Es lo normal, no se avisa. Si la senal es mala el paso se ve a saltos (eso ya lo avisa el RSSI de arriba).
        if i.get("drv") == "pines":
            d.append(("warn", "El ESP32 no encuentra el PCA9685: revisa SDA=21, SCL=22, VCC=3V3 y GND del driver."))
        sueltos = [ar.NOMBRE_SERVO[ar.SERVOS[k]] for k, a in enumerate(i.get("ang") or []) if a == -1 and k < len(ar.SERVOS)]
        if sueltos and ar._ejecutor.actual:
            d.append(("warn", "Estos servos estan sueltos (sin fuerza): " + ", ".join(sueltos) + ". Di 'parate' para activarlos."))
        if isinstance(i.get("ang"), list) and len(i["ang"]) not in (0, len(ar.SERVOS)):
            d.append(("mal", f"El ESP32 maneja {len(i['ang'])} servos y Arche {len(ar.SERVOS)}: sube el perro_esp32.ino de 12 servos."))
        avisos = ar.avisos_marcha()
        haciendo = ar._ejecutor.actual
        if haciendo:                          # solo los de lo que esta haciendo ahora: lo demas es ruido
            propios = [a for a in avisos if a[1].startswith(f"'{haciendo}'")]
            d.extend(propios)
            otros = len({a[1].split("'")[1] for a in avisos}) - (1 if propios else 0)
            if otros > 0:
                d.append(("warn", f"Otros {otros} movimientos tambien tienen avisos con estos ajustes (se ven al parar)."))
        else:
            d.extend(avisos)
        if not d:
            d.append(("ok", "Todo en orden. Si se ve mal, mira la guia 'Si ves esto, cambia esto'."))
        return [{"nivel": n, "texto": x} for n, x in d]

    def esp_perdido(self):
        if self.esp_estado == "offline":
            return True
        return self.hb_visto and (time.time() - self.last_hb) > TIMEOUT_ESP

    def _on_ack(self, ahora):
        with self.lock_lat:
            p = self.pendiente
            if not p or ahora < p["t_cmd"]:
                return
            self.pendiente = None
            rec = p["rec"]
            rec["esp_ms"] = round((ahora - p["t_cmd"]) * 1000, 1)
            rec["total_ms"] = round((ahora - p["t_llegada"]) * 1000, 1)
            s = self.stats[rec["evento"]]
            t = rec["total_ms"]
            s["n"] += 1
            s["suma"] += t
            s["min"] = t if s["min"] is None else min(s["min"], t)
            s["max"] = t if s["max"] is None else max(s["max"], t)

    # ---------------------------------------------------------- modos y paro
    def paro(self, motivo):
        with self.lock:
            if self.modo != "paro":
                self.modo_previo = self.modo
            self.modo = "paro"
            self.motivo_paro = motivo
            self.pausa = ""
            self.accion_actual = None
        try:
            ar._modo_perro.detener("Paro del banco de pruebas.")
            ar._ejecutor.quieto()
        except Exception:
            pass

    def set_modo(self, modo):
        if modo not in ("manual", "perro"):
            return False, "Modo invalido."
        if self.usar_camara and time.time() - self.t_ultimo_cuadro > TIMEOUT_CAMARA:
            return False, "No llega video del celular: en la app, pestana Ojos > Iniciar camara (o abre /camara en el celular)."
        if self.esp_perdido():
            return False, "El ESP32 aparece desconectado: revisa su WiFi/MQTT."
        try:
            ar._obtener_cliente()
        except ar.RobotError as e:
            return False, str(e)
        with self.lock:
            ar._modo_perro.detener("Banco de pruebas activo.")   # apaga el modo perro viejo
            self.modo = modo
            self.motivo_paro = ""
            self.pausa = ""
            self.gracia_hasta = time.time() + GRACIA_TRAS_ACTIVAR
            self.cerebro.reiniciar(time.time())
            self.ev_manual_prev = self.ev
            self.ultimo_error = ""
        return True, f"Modo {modo} activado."

    def reanudar(self):
        return self.set_modo(self.modo_previo if self.modo_previo in ("manual", "perro") else "manual")

    def ceder_control(self):
        """Pasa a modo "ordenes" SIN tocar el robot: la camara deja de mandar reacciones
        para que no pise lo que mandas desde la app. No es un paro: no hay que Reanudar.
        Devuelve el modo que habia (o None si estaba en paro: el paro solo lo quitas tu)."""
        with self.lock:
            if self.modo == "paro":
                return None
            previo = self.modo
            if previo in ("manual", "perro"):
                self.modo_previo = previo
            self.modo = "ordenes"
            self.pausa = ""
            self.accion_actual = None
            return previo

    def devolver_control(self, previo):
        """Deshace ceder_control (cuando la frase al final no era una orden del perro)."""
        with self.lock:
            if self.modo == "ordenes" and previo in ("manual", "perro"):
                self.modo = previo
                self.gracia_hasta = time.time() + GRACIA_TRAS_ACTIVAR

    def repetir(self, accion):
        """Repite una accion en bucle (para mirarla y ajustarla)."""
        if accion == "quieto":
            return self.orden("quieto")
        if accion not in ar.SECUENCIAS:
            return False, "No conozco esa accion."
        try:
            ar._modo_perro.detener("Repitiendo una accion para ajustarla.")
            ar._ejecutor.ejecutar(accion, bucle=True)
        except ar.RobotError as e:
            return False, str(e)
        self.ceder_control()
        return True, f"Repitiendo '{accion}' sin parar. Ajusta abajo y mira como cambia. Toca Quieto para parar."

    def orden(self, frase):
        """Una frase escrita o tocada en la app pasa por el MISMO camino que cuando
        se la dices a Arche en el PC: acciones_robot.manejar() -> MQTT -> ESP32."""
        frase = (frase or "").strip()[:200]
        if not frase:
            return False, "Escribe una orden."
        t = ar._normalizar(frase)
        if _RE_EMERGENCIA.match(t):
            self.paro("Parada de emergencia desde la app.")
        try:
            respuesta = ar.manejar(frase)
        except Exception as e:
            respuesta = f"El perro fallo: {e}"
        if respuesta is None:
            return False, "Esa frase no es una orden del perro. Prueba: sientate, ven, quieto, da la pata, comandos del perro."
        self.ceder_control()     # era del perro: la camara deja de reaccionar para no pisarla
        return True, respuesta

    def _problema(self, t):
        """Por que no se puede seguir reaccionando a la camara ahora mismo ("" = todo bien)."""
        if self.usar_camara and t - self.t_ultimo_cuadro > TIMEOUT_CAMARA:
            return "Se perdio el video del celular."
        if self.esp_perdido():
            return "Se perdio la conexion con el ESP32."
        if self.mon_visto and not self.mon_conectado:
            return "Se perdio la conexion con el broker MQTT."
        return ""

    def _vigilante(self):
        """Antes: cualquier corte = PARO y habia que tocar Reanudar a cada rato.
        Ahora: corte = PAUSA (el robot se queda quieto) y sigue solo cuando todo vuelve.
        En modo ordenes no vigila la camara: ahi mandas tu, no lo que ve el celular."""
        while not self._fin.wait(0.25):
            t = time.time()
            if self.modo not in ("manual", "perro") or t < self.gracia_hasta:
                continue
            problema = self._problema(t)
            if problema and not self.pausa:
                with self.lock:
                    self.pausa = problema
                    self.accion_actual = None
                try:
                    ar._ejecutor.quieto()    # si el ESP32 no esta, igual se pone recto solo a los 5 s
                except Exception:
                    pass
            elif not problema and self.pausa:
                with self.lock:
                    self.pausa = ""
                    self.gracia_hasta = t + 1.0
                    self.cerebro.reiniciar(t)
                    self.ev_manual_prev = self.ev

    def cerrar(self):
        self._fin.set()
        self.paro("Banco cerrado.")
        cerrar_tunel()                       # que el acceso por internet no quede abierto al cerrar Arche

    # -------------------------------------------------------- reaccionar
    def _enviar(self, accion, evento, t_llegada, det_ms):
        t_cmd = time.perf_counter()
        rec = {"hora": time.strftime("%H:%M:%S"), "evento": evento, "accion": accion,
               "det_ms": round(det_ms, 1), "pub_ms": None, "esp_ms": None, "total_ms": None}
        with self.lock_lat:
            self.contador += 1
            self.pendiente = {"rec": rec, "t_llegada": t_llegada, "t_cmd": t_cmd}
        try:
            ar._enviar_accion(accion)
        except ar.RobotError as e:
            self.ultimo_error = str(e)
            with self.lock_lat:
                self.pendiente = None
            return False
        rec["pub_ms"] = round((time.perf_counter() - t_llegada) * 1000, 1)
        with self.lock_lat:
            self.historial.appendleft(rec)
        self.ultima_reaccion = time.time()
        self.accion_actual = accion
        return True

    def probar(self, accion):
        if self.modo == "paro":
            return False, "Estas en paro: elige Manual o Perro primero."
        if accion not in REACCIONES or accion == "ninguna":
            return False, "Reaccion invalida."
        t = time.perf_counter()
        ok = self._enviar(accion, "prueba", t, 0.0)
        return ok, ("Enviado." if ok else self.ultimo_error)

    def _decidir_manual(self, ev):
        if ev == self.ev_manual_prev:
            return None
        accion = self.mapa.get(ev, "ninguna")
        if accion == "ninguna":
            self.ev_manual_prev = ev
            return None
        if accion != "quieto" and time.time() - self.ultima_reaccion < self.cooldown:
            return None                      # sigue pendiente: se reintenta al pasar el cooldown
        self.ev_manual_prev = ev
        return accion

    def _suavizar(self, cand):
        if cand == self.ev:
            self.cand, self.cand_n = cand, 0
            return self.ev
        ahora = time.monotonic()
        if cand == self.cand:
            self.cand_n += 1
        else:
            self.cand, self.cand_n, self.cand_t0 = cand, 1, ahora
        if self.cand_n >= CONFIRMAR[cand] and ahora - self.cand_t0 >= CONFIRMAR_SEG[cand] - 0.01:
            self.ev, self.cand_n = cand, 0
        return self.ev

    # ---------------------------------------------------------- por cuadro
    def procesar(self, frame, t_llegada, net_ms=None):
        with self.lock:
            t0 = time.perf_counter()
            res = self.detector.analizar(frame)
            det_ms = (time.perf_counter() - t0) * 1000
            self.lat_det.append(det_ms)
            if net_ms is not None:
                self.lat_red.append(net_ms)
            ahora = time.time()
            self.t_ultimo_cuadro = ahora
            self.tiempos.append(ahora)
            self.cuadros += 1
            self.res = res
            for k in ("cara", "pelota"):
                if res[k]:
                    self.ultimo_x[k] = res[k]["x"]
            ev = self._suavizar(res["evento"])

            if self.pausa:
                accion = None
            elif self.modo == "manual":
                accion = self._decidir_manual(ev)
            elif self.modo == "perro":
                accion = self.cerebro.decidir(ev, self.ultimo_x.get(ev, 0.0), ahora, self.invertir_giro)
            else:
                accion = None
            if accion:
                self._enviar(accion, ev, t_llegada, det_ms)

            # La imagen con las marcas "quemadas" solo se arma si alguien la esta mirando (panel viejo,
            # /video o una camara IP): recomprimir cada cuadro gasta PC y le quita nitidez.
            if self.crudo is None or time.time() - self.pide_anotado_t < 5:
                etiqueta = f"{ev}  [{self.modo}]" + (f"  -> {self.accion_actual}" if self.accion_actual and self.modo != "paro" else "")
                ok, buf = cv2.imencode(".jpg", anotar(frame, res, etiqueta), [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    with self.hay_cuadro:
                        self.ultimo_jpg = buf.tobytes()
                        self.ultimo_n = self.cuadros
                        self.hay_cuadro.notify_all()
            return {"evento": ev, "crudo": res["evento"], "modo": self.modo,
                    "accion": self.accion_actual if self.modo != "paro" else None,
                    # cajas en fraccion del cuadro (0..1): la app las dibuja sobre su camara en vivo
                    "cajas": [[c[0]] + [round(float(v), 3) for v in c[1:]] for c in res.get("cajas", [])]}

    # ------------------------------------------------------------- estado
    @staticmethod
    def _prom(d):
        return round(sum(d) / len(d), 1) if d else None

    def estado(self):
        t = time.time()
        fps = 0.0
        if len(self.tiempos) >= 2 and self.tiempos[-1] > self.tiempos[0]:
            fps = (len(self.tiempos) - 1) / (self.tiempos[-1] - self.tiempos[0])
        cam_ok = (t - self.t_ultimo_cuadro) < TIMEOUT_CAMARA
        res = self.res or {}
        with self.lock_lat:
            hist = [dict(h) for h in list(self.historial)[:12]]
            por_evento = {e: {"n": s["n"], "prom": round(s["suma"] / s["n"], 1) if s["n"] else None,
                              "min": s["min"], "max": s["max"]} for e, s in self.stats.items()}
        totales = [h["total_ms"] for h in hist if h["total_ms"] is not None]
        pubs = [h["pub_ms"] for h in hist if h["pub_ms"] is not None]
        return {
            "modo": self.modo, "motivo_paro": self.motivo_paro, "pausa": self.pausa, "error": self.ultimo_error or self.mon_error,
            "camara": {"ok": cam_ok, "fps": round(fps, 1), "cuadros": self.cuadros,
                       "hace_s": round(t - self.t_ultimo_cuadro, 1) if self.t_ultimo_cuadro else None},
            "esp": {"estado": self.esp_estado, "hb_visto": self.hb_visto, "perdido": self.esp_perdido(),
                    "info": self.esp_info, "reinicios": self.esp_reinicios,
                    "info_hace_s": round(t - self.t_esp_info, 1) if self.t_esp_info else None,
                    "hb_hace_s": round(t - self.last_hb, 1) if self.hb_visto else None},
            "mqtt": {"ok": self.mon_conectado},
            "evento": self.ev, "crudo": res.get("evento", "nada"),
            "detalle": {"movimiento": res.get("movimiento"), "textura": res.get("textura"),
                        "cerca_por": res.get("cerca_por", ""), "cara": res.get("cara"), "pelota": res.get("pelota")},
            "accion_actual": self.accion_actual,
            "eventos": EVENTOS, "reacciones": REACCIONES, "mapa": self.mapa,
            "colores": list(PRESETS_COLOR), "config": dict(self.detector.config),
            "cooldown": self.cooldown, "invertir_giro": self.invertir_giro, "usar_camara": self.usar_camara,
            "marcha": ar.marcha_actual(), "rangos_marcha": ar.RANGOS_MARCHA,
            "crudo": ar._crudo, "lim_servo": ar.LIM_SERVO, "capturas": ar.estado_capturas(),
            "calibracion": ar.calibracion_actual(), "rango_ajuste": ar.RANGO_AJUSTE, "rodillas": ar.RODILLAS, "rodilla_en_90": ar.RODILLA_EN_90,
            "largos": {"muslo": ar.LARGO_MUSLO, "pierna": ar.LARGO_PIERNA},
            "haciendo": {"accion": ar._ejecutor.actual, "bucle": ar._ejecutor.en_bucle, "vueltas": ar._ejecutor.vueltas},
            "acciones_bucle": [n for n in ("avanzar", "correr", "retroceder", "izquierda", "derecha", "feliz", "saludar",
                                           "cola", "ladrar", "sentarse", "acostarse", "enojado") if n in ar.SECUENCIAS],
            "diagnostico": self.diagnostico(),
            "arche_perro": {"activo": ar._modo_perro.activo, "resumen": ar._modo_perro.resumen(),
                            "evento": ar._modo_perro.ultimo_evento},
            "perro": {"mood": self.cerebro.mood, "postura": self.cerebro.postura, "razon": self.cerebro.razon,
                      "params": dict(self.cerebro.params)},
            "lat": {"deteccion": self._prom(self.lat_det), "red_celular": self._prom(self.lat_red),
                    "publicar": self._prom(pubs), "total": self._prom(totales),
                    "por_evento": por_evento, "historial": hist},
        }


# ============================================================ servidor web
def viene_por_tunel(req):
    """True si llega desde internet (y por eso pide clave).
    * Cloudflare SIEMPRE agrega Cf-Connecting-Ip / Cf-Ray, y nadie se las puede quitar: eso manda primero,
      asi nadie de internet se cuela fingiendo ser de Tailscale.
    * "tailscale serve" pone Tailscale-User-Login con la cuenta de quien entra (y borra la que traiga el
      pedido): son tus aparatos, no hace falta clave.
    * Cualquier otro proxy (X-Forwarded-For) se trata como internet.
    Lo que llega directo por la WiFi o por la IP 100.x de Tailscale no trae ninguna."""
    if req.headers.get("Cf-Connecting-Ip") or req.headers.get("Cf-Ray"):
        return True
    # "tailscale funnel" abre el banco a todo internet (para el iPhone sin Tailscale): siempre con clave
    if req.headers.get("Tailscale-Funnel-Request"):
        return True
    if req.headers.get("Tailscale-User-Login"):
        return False
    return bool(req.headers.get("X-Forwarded-For"))


def ip_cliente(req):
    return req.headers.get("Cf-Connecting-Ip") or (req.headers.get("X-Forwarded-For", "").split(",")[0].strip()) \
        or req.remote_addr or "?"


class CarteroRTC:
    """Presenta al celular (emisor) con cada panel (visor) para que se pasen el video por WebRTC.
    Solo pasa mensajes cortos (ofertas/respuestas): el video NO pasa por aqui, va directo."""

    def __init__(self):
        self.cv = threading.Condition()
        self.buzones = {}           # id -> [mensajes]
        self.visto = {}             # id -> ultima vez que reviso su buzon
        self.emisor = None

    def _limpiar(self):
        t = time.time()
        for k in [k for k, v in self.visto.items() if t - v > 60]:
            self.buzones.pop(k, None)
            self.visto.pop(k, None)

    def poner(self, para, msg):
        with self.cv:
            caja = self.buzones.setdefault(para, [])
            caja.append(msg)
            del caja[:-20]          # nunca crece sin control
            self.cv.notify_all()

    def registrar_emisor(self, yo):
        with self.cv:
            self.emisor = yo
            self.buzones[yo] = []
            self.visto[yo] = time.time()
            self._limpiar()

    def emisor_vivo(self):
        return self.emisor is not None and time.time() - self.visto.get(self.emisor, 0) < 25

    def recoger(self, yo, espera=15.0):
        with self.cv:
            self.visto[yo] = time.time()
            if not self.buzones.get(yo):
                self.cv.wait_for(lambda: bool(self.buzones.get(yo)), timeout=espera)
            self.visto[yo] = time.time()
            msgs = self.buzones.get(yo, [])
            self.buzones[yo] = []
            return msgs


_ID_OK = re.compile(r"^[A-Za-z0-9_-]{4,40}$")


RUTAS_LIBRES = ("/entrar", "/manifest.webmanifest", "/sw.js", "/iconos/")


def crear_app(b):
    app = Flask(__name__)

    @app.before_request
    def pedir_clave_por_internet():
        if not viene_por_tunel(request):
            return None
        if any(request.path == r or (r.endswith("/") and request.path.startswith(r)) for r in RUTAS_LIBRES):
            return None
        if acceso.sesion_valida(request.cookies.get(acceso.COOKIE)):
            return None
        if request.method == "GET" and request.path in ("/", "/app", "/camara"):
            return redirect("/entrar?siguiente=" + request.path)
        return jsonify(error="clave", msg="Falta la clave del banco."), 401

    @app.route("/entrar", methods=["GET", "POST"])
    def entrar():
        siguiente = request.values.get("siguiente", "/app")
        if not siguiente.startswith("/") or siguiente.startswith("//"):
            siguiente = "/app"
        error = ""
        if request.method == "POST":
            ip = ip_cliente(request)
            espera = acceso.bloqueado(ip)
            if espera:
                error = f"Demasiados intentos. Espera {max(1, espera // 60)} min."
            elif acceso.probar_clave(ip, request.form.get("clave", "")):
                r = redirect(siguiente)
                r.set_cookie(acceso.COOKIE, acceso.valor_sesion(), max_age=365 * 24 * 3600,
                             secure=True, httponly=True, samesite="Lax")
                return r
            else:
                espera = acceso.bloqueado(ip)
                error = (f"Demasiados intentos. Espera {max(1, espera // 60)} min." if espera
                         else "Esa no es la clave. Revísala en el PC: dile a Arché “clave del perro”.")
        with open(os.path.join(HERE, "app", "entrar.html"), "r", encoding="utf-8") as f:
            html = f.read()
        from html import escape
        html = html.replace("{{SIGUIENTE}}", escape(siguiente)).replace("{{ERROR}}", escape(error))
        return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/")
    def panel():
        return send_file(os.path.join(HERE, "panel.html"))

    @app.get("/camara")
    def camara():
        return send_file(os.path.join(HERE, "camara.html"))

    # ---- app para iPhone (lo mismo que el panel + la camara, instalable en la pantalla de inicio)
    @app.get("/app")
    def app_iphone():
        r = send_file(os.path.join(HERE, "app", "app.html"))
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.get("/manifest.webmanifest")
    def manifest():
        r = send_file(os.path.join(HERE, "app", "manifest.webmanifest"), mimetype="application/manifest+json")
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.get("/sw.js")
    def service_worker():
        r = send_file(os.path.join(HERE, "app", "sw.js"), mimetype="text/javascript")
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.get("/iconos/<path:nombre>")
    def iconos(nombre):
        return send_from_directory(os.path.join(HERE, "app", "iconos"), nombre)

    @app.get("/cuadro.jpg")
    def cuadro():
        """El ultimo cuadro analizado (con las marcas). La app lo pide seguido: en iPhone es
        mas confiable que el video /video, que Safari a veces deja congelado."""
        despues = request.args.get("despues", default=0, type=int)
        # crudo=1: la imagen tal cual la mando el celular (mas nitida) y lo detectado en la cabecera X-Info.
        # Si no hay (camara IP con --fuente), se manda la de siempre con las marcas dibujadas.
        crudo = request.args.get("crudo") == "1" and b.crudo is not None
        if not crudo:
            b.pide_anotado_t = time.time()
        actual = (lambda: b.crudo_n) if crudo else (lambda: b.ultimo_n)
        with b.hay_cuadro:
            # espera (max 1.5 s) a que haya un cuadro mas nuevo que el que ya tiene la app:
            # asi cada pedido trae una imagen nueva en vez de repetir la misma
            if (b.crudo if crudo else b.ultimo_jpg) is not None and actual() <= despues:
                b.hay_cuadro.wait_for(lambda: actual() > despues, timeout=1.5)
            if crudo:
                jpg, n, info = b.crudo, b.crudo_n, b.crudo_info
            else:
                jpg, n, info = b.ultimo_jpg, b.ultimo_n, None
        if jpg is None:
            return ("", 204)
        cab = {"Cache-Control": "no-store", "X-Cuadro": str(n)}
        if info is not None:
            cab["X-Info"] = json.dumps(info)
        return Response(jpg, mimetype="image/jpeg", headers=cab)

    @app.get("/certificado.cer")
    def certificado():
        return _respuesta_certificado()

    @app.get("/marcas")
    def marcas():
        """Solo lo detectado (sin imagen): cuando el video va por WebRTC, el panel ya tiene la imagen."""
        despues = request.args.get("despues", default=0, type=int)
        with b.hay_cuadro:
            if b.crudo_n <= despues:
                b.hay_cuadro.wait_for(lambda: b.crudo_n > despues, timeout=1.5)
            n, info = b.crudo_n, b.crudo_info
        return jsonify(n=n, info=info)

    # ---------------- WebRTC: el PC solo presenta; el video va directo del celular al panel
    cartero = CarteroRTC()

    @app.get("/rtc.js")
    def rtc_js():
        r = send_file(os.path.join(HERE, "app", "rtc.js"), mimetype="text/javascript")
        r.headers["Cache-Control"] = "no-cache"
        return r

    def _id(d, campo="yo"):
        v = str((d or {}).get(campo) or "")
        return v if _ID_OK.match(v) else None

    @app.post("/rtc/emisor")
    def rtc_emisor():
        yo = _id(request.get_json(silent=True))
        if not yo:
            return jsonify(ok=False), 400
        cartero.registrar_emisor(yo)
        return jsonify(ok=True)

    @app.post("/rtc/pedir")
    def rtc_pedir():
        yo = _id(request.get_json(silent=True))
        if not yo:
            return jsonify(ok=False), 400
        if not cartero.emisor_vivo():
            return jsonify(ok=False, msg="No hay celular transmitiendo.")
        with cartero.cv:
            cartero.buzones[yo] = []          # empieza limpio (sin ofertas viejas)
            cartero.visto[yo] = time.time()
        cartero.poner(cartero.emisor, {"tipo": "visor", "de": yo})
        return jsonify(ok=True)

    @app.post("/rtc/enviar")
    def rtc_enviar():
        d = request.get_json(silent=True) or {}
        para, de = _id(d, "para"), _id(d, "de")
        tipo, sdp = d.get("tipo"), d.get("sdp")
        if not para or not de or tipo not in ("offer", "answer") or not isinstance(sdp, str) or len(sdp) > 20000:
            return jsonify(ok=False), 400
        cartero.poner(para, {"tipo": tipo, "de": de, "sdp": sdp})
        return jsonify(ok=True)

    @app.get("/rtc/buzon")
    def rtc_buzon():
        yo = _id(request.args)
        if not yo:
            return jsonify(mensajes=[]), 400
        return jsonify(mensajes=cartero.recoger(yo))

    @app.post("/frame")
    def frame():
        t_llegada = time.perf_counter()
        cam, seq = request.headers.get("X-Cam"), request.headers.get("X-Seq", type=int)
        if cam and seq is not None:
            with b.lock:
                if cam == b.cam_id and seq <= b.cam_seq:
                    # llego despues de uno mas nuevo (por internet pasa): no se analiza para no ir hacia atras
                    return jsonify(evento=b.ev, modo=b.modo, descartado=True, proc_ms=0.0)
                b.cam_id, b.cam_seq = cam, seq
        img = cv2.imdecode(np.frombuffer(request.get_data(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return jsonify(error="cuadro invalido"), 400
        r = b.procesar(img, t_llegada, request.headers.get("X-Net-Ms", type=float))
        with b.hay_cuadro:
            b.crudo = request.get_data()
            b.crudo_n = b.cuadros
            b.crudo_info = {"cajas": r.get("cajas", []), "evento": r.get("evento"), "accion": r.get("accion"),
                            "modo": r.get("modo")}
            b.hay_cuadro.notify_all()
        r["proc_ms"] = round((time.perf_counter() - t_llegada) * 1000, 1)
        return jsonify(r)

    @app.get("/video")
    def video():
        def generar():
            ultimo = None
            while True:
                b.pide_anotado_t = time.time()
                jpg = b.ultimo_jpg
                if jpg is not None and jpg is not ultimo:
                    ultimo = jpg
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                time.sleep(0.05)
        return Response(generar(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/estado")
    def estado():
        return jsonify(b.estado())

    @app.post("/api/modo")
    def modo():
        ok, msg = b.set_modo((request.get_json(silent=True) or {}).get("modo"))
        return jsonify(ok=ok, msg=msg)

    @app.post("/api/paro")
    def paro():
        b.paro("Paro de emergencia desde el panel.")
        return jsonify(ok=True)

    @app.post("/api/reanudar")
    def reanudar():
        ok, msg = b.reanudar()
        return jsonify(ok=ok, msg=msg)

    @app.post("/api/mapa")
    def mapa():
        d = request.get_json(silent=True) or {}
        return jsonify(ok=b.set_mapa(d.get("evento"), d.get("accion")))

    @app.post("/api/config")
    def config():
        b.aplicar_config(request.get_json(silent=True) or {})
        return jsonify(ok=True)

    @app.post("/api/probar")
    def probar():
        ok, msg = b.probar((request.get_json(silent=True) or {}).get("accion"))
        return jsonify(ok=ok, msg=msg)

    @app.post("/api/orden")
    def orden():
        ok, msg = b.orden((request.get_json(silent=True) or {}).get("frase"))
        return jsonify(ok=ok, msg=msg)

    @app.post("/api/repetir")
    def repetir():
        ok, msg = b.repetir((request.get_json(silent=True) or {}).get("accion"))
        return jsonify(ok=ok, msg=msg)

    @app.post("/api/calibrar")
    def calibrar():
        try:
            b.ceder_control()
            return jsonify(ok=True, calibracion=ar.cambiar_calibracion(request.get_json(silent=True) or {}))
        except ar.RobotError as e:
            return jsonify(ok=False, msg=str(e))

    @app.post("/api/calibrar/pose")
    def calibrar_pose():
        try:
            b.ceder_control()
            ar._modo_perro.detener("Calibrando.")
            ar.pose_calibrar((request.get_json(silent=True) or {}).get("pose", "recta"))
            return jsonify(ok=True)
        except ar.RobotError as e:
            return jsonify(ok=False, msg=str(e))

    @app.post("/api/calibrar/probar")
    def calibrar_probar():
        try:
            b.ceder_control()
            ar._modo_perro.detener("Calibrando.")
            return jsonify(ok=True, msg=ar.probar_servo((request.get_json(silent=True) or {}).get("servo")))
        except (ar.RobotError, TypeError, ValueError, IndexError) as e:
            return jsonify(ok=False, msg=f"No pude probar ese servo ({e}).")

    @app.post("/api/crudo")
    def crudo():
        d = request.get_json(silent=True) or {}
        try:
            b.ceder_control()
            ar._modo_perro.detener("Moviendo servos para armar.")
            ang = ar.mover_crudo(d.get("servo"), d.get("angulo", 90))
            return jsonify(ok=True, angulo=ang)
        except (ar.RobotError, TypeError, ValueError) as e:
            return jsonify(ok=False, msg=str(e))

    @app.post("/api/capturar")
    def capturar():
        try:
            res = ar.capturar_pose((request.get_json(silent=True) or {}).get("pose"))
            return jsonify(ok=True, resultado=[{"nivel": a, "texto": b} for a, b in res])
        except ar.RobotError as e:
            return jsonify(ok=False, msg=str(e))

    @app.post("/api/barrer")
    def barrer():
        try:
            b.ceder_control()
            ar._modo_perro.detener("Moviendo servos para armar.")
            return jsonify(ok=True, msg=ar.barrer((request.get_json(silent=True) or {}).get("servo")))
        except (ar.RobotError, TypeError, ValueError) as e:
            return jsonify(ok=False, msg=str(e))

    @app.post("/api/marcha")
    def marcha():
        return jsonify(ok=True, marcha=ar.cambiar_marcha(request.get_json(silent=True) or {}),
                       avisos=[{"nivel": n, "texto": x} for n, x in ar.avisos_marcha()])

    @app.post("/api/recalibrar")
    def recalibrar():
        with b.lock:
            b.detector.recalibrar()
        return jsonify(ok=True)

    @app.post("/api/reiniciar_latencias")
    def reiniciar_lat():
        with b.lock_lat:
            b.historial.clear()
            for s in b.stats.values():
                s.update({"n": 0, "suma": 0.0, "min": None, "max": None})
        return jsonify(ok=True)

    return app


def leer_fuente(b, url):
    """Alternativa a la pagina /camara: lee un stream (app 'IP Webcam', DroidCam...).
    Un hilo lee siempre y solo se analiza el cuadro mas nuevo, para no acumular retraso."""
    ultimo = {"f": None, "t": 0.0, "n": 0}

    def lector():
        while True:
            cap = cv2.VideoCapture(url)
            while cap.isOpened():
                ok, f = cap.read()
                if not ok:
                    break
                ultimo["f"], ultimo["t"] = f, time.perf_counter()
                ultimo["n"] += 1
            cap.release()
            time.sleep(2)

    threading.Thread(target=lector, daemon=True, name="banco-fuente").start()
    visto = 0
    while True:
        if ultimo["n"] != visto and ultimo["f"] is not None:
            visto = ultimo["n"]
            b.procesar(ultimo["f"], ultimo["t"], None)
        else:
            time.sleep(0.01)


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))     # no envia nada: solo averigua que interfaz usaria
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "IP-DE-TU-PC"


def _respuesta_certificado():
    import certificados
    certificados.preparar(ip_local())
    return Response(certificados.ca_der(), mimetype="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="Arche_perro.cer"'})


def crear_app_instalar(puerto_https):
    """Pagina SIN https (puerto + 1) solo para instalar el certificado en el iPhone.
    No tiene ningun control del robot."""
    inst = Flask("banco_instalar")

    @inst.get("/")
    def pagina():
        with open(os.path.join(HERE, "app", "instalar.html"), "r", encoding="utf-8") as f:
            html = f.read()
        url_app = f"https://{request.host.split(':')[0]}:{puerto_https}/app"
        return html.replace("{{URL_APP}}", url_app)

    @inst.get("/certificado.cer")
    def certificado():
        return _respuesta_certificado()

    @inst.get("/iconos/<path:nombre>")
    def iconos(nombre):
        return send_from_directory(os.path.join(HERE, "app", "iconos"), nombre)

    return inst


def _servir_instalar(puerto_https):
    from werkzeug.serving import make_server
    try:
        srv = make_server("0.0.0.0", puerto_https + 1, crear_app_instalar(puerto_https), threaded=True)
    except OSError as e:
        print(f"Banco: no pude abrir la pagina de instalacion en el puerto {puerto_https + 1} ({e}).")
        return
    srv.serve_forever()


def contexto_https():
    """Certificado propio (el que el iPhone puede instalar y confiar). Si algo falla, el de siempre."""
    try:
        import certificados
        return certificados.contexto_ssl(ip_local())
    except ImportError:
        print("Banco: sin 'cryptography' no hay HTTPS y el celular no abrira la camara desde el navegador. "
              "Instala: pip install cryptography (o usa --fuente con una app de camara IP).")
        return None
    except Exception as e:
        print(f"Banco: no pude crear el certificado propio ({e}); uso uno temporal (la app de iPhone no se podra instalar).")
        return "adhoc"


def servir(b, puerto=PUERTO, https=True):
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = crear_app(b)
    ctx = contexto_https() if https else None
    if ctx is not None:
        threading.Thread(target=_servir_instalar, args=(puerto,), daemon=True, name="banco-instalar").start()
    app.run(host="0.0.0.0", port=puerto, ssl_context=ctx, threaded=True, use_reloader=False)


# ======================================================= integracion con Arche
_banco = None
_hilo_servidor = None
_url_base = ""


def obtener_banco():
    global _banco
    if _banco is None:
        _banco = Banco()
    return _banco


def iniciar(puerto=PUERTO, https=True, fuente=None):
    """Arranca el banco y el servidor web en hilos (para llamarlo desde Arche)."""
    global _hilo_servidor, _url_base
    b = obtener_banco()
    if _hilo_servidor is None or not _hilo_servidor.is_alive():
        esquema = "https" if https else "http"
        _url_base = f"{esquema}://{ip_local()}:{puerto}"
        _hilo_servidor = threading.Thread(target=servir, args=(b, puerto, https), daemon=True, name="banco-web")
        _hilo_servidor.start()
        if fuente:
            threading.Thread(target=leer_fuente, args=(b, fuente), daemon=True, name="banco-lector").start()
    return _url_base


# ------------------------------------------------------- tunel publico (cloudflared)
_tunel = None
_url_tunel = None


def _buscar_cloudflared():
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    for r in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe", r"C:\Program Files\cloudflared\cloudflared.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe")):
        if os.path.exists(r):
            return r
    return None


def iniciar_tunel(puerto=PUERTO, https=True, esperar=25.0):
    """Abre un tunel de Cloudflare hacia el banco. Devuelve (url | None, mensaje)."""
    global _tunel, _url_tunel
    if _tunel is not None and _tunel.poll() is None and _url_tunel:
        return _url_tunel, "ya estaba abierto"
    exe = _buscar_cloudflared()
    if not exe:
        return None, ("No encontré 'cloudflared'. Instálalo con: winget install --id Cloudflare.cloudflared "
                      "y vuelve a abrir Arché.")
    origen = f"https://127.0.0.1:{puerto}" if https else f"http://127.0.0.1:{puerto}"
    args = [exe, "tunnel", "--no-autoupdate", "--url", origen]
    if https:
        args.append("--no-tls-verify")       # el certificado del banco es propio; el tramo PC->cloudflared es local
    _url_tunel = None
    try:
        _tunel = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        _tunel = None
        return None, f"No pude abrir cloudflared ({e})."

    def _leer():
        global _url_tunel
        for linea in _tunel.stderr:
            m = re.search(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com", linea)   # "api." sale en los errores
            if m and not _url_tunel:
                _url_tunel = m.group(0)
    threading.Thread(target=_leer, name="tunel-perro", daemon=True).start()

    fin = time.time() + esperar
    while time.time() < fin and not _url_tunel and _tunel.poll() is None:
        time.sleep(0.2)
    if not _url_tunel:
        cerrar_tunel()
        return None, "cloudflared no me dio una dirección a tiempo. Revisa tu internet e inténtalo otra vez."
    return _url_tunel, "abierto"


def cerrar_tunel():
    global _tunel, _url_tunel
    if _tunel is not None:
        try:
            _tunel.terminate()
        except Exception:
            pass
    _tunel, _url_tunel = None, None


atexit.register(cerrar_tunel)


def _ip_tailscale():
    try:
        import certificados
        return certificados.ip_tailscale()
    except Exception:
        return None


def _url_tailscale_publicada(puerto=PUERTO):
    try:
        import tailscale_perro
        if tailscale_perro.esta_publicado(puerto):
            return tailscale_perro.url()
    except Exception:
        pass
    return None


def _url_instalar(puerto=PUERTO):
    return f"http://{ip_local()}:{puerto + 1}"


# OJO: "estado del banco" a secas ya es un comando de Arche (banco de entrenamiento), por eso aqui
# siempre se exige "de pruebas".
_RE_ABRIR = re.compile(r"^(?:abre|activa|enciende|inicia|arranca)(?: el)? banco de pruebas$|^banco de pruebas$")
_RE_PARO = re.compile(r"^(?:apaga|para|detiene|desactiva)(?: el)? banco de pruebas$|^paro del banco de pruebas$")
_RE_ESTADO = re.compile(r"^estado del banco de pruebas$")
_RE_TUNEL_ABRIR = re.compile(r"^(?:abre|activa|enciende|inicia|arranca)(?: el)? (?:tunel|acceso por internet) del "
                             r"(?:perro|banco de pruebas)$|^banco de pruebas por internet$")
_RE_TUNEL_CERRAR = re.compile(r"^(?:cierra|apaga|desactiva|deten|detiene|quita)(?: el)? (?:tunel|acceso por internet) "
                              r"del (?:perro|banco de pruebas)$")
_RE_TS_ABRIR = re.compile(r"^(?:abre|activa|publica|pon|enciende)(?: el)? (?:perro|banco de pruebas) (?:en|por) tailscale$|"
                          r"^(?:activa|enciende)(?: el)? tailscale del (?:perro|banco de pruebas)$|^banco de pruebas por tailscale$")
_RE_TS_QUITAR = re.compile(r"^(?:quita|apaga|desactiva|cierra)(?: el)? (?:perro|banco de pruebas) (?:de|en|por) tailscale$|"
                           r"^(?:quita|apaga|desactiva)(?: el)? tailscale del (?:perro|banco de pruebas)$")
_RE_CLAVE_VER = re.compile(r"^(?:cual es |dime |muestrame )?(?:la )?clave del (?:perro|banco de pruebas)$")
_RE_CLAVE_NUEVA = re.compile(r"^(?:cambia|renueva|nueva|genera)(?: una)?(?: nueva)?(?: la)? clave del (?:perro|banco de pruebas)$")
_RE_EMERGENCIA = re.compile(r"^(?:parada de emergencia|emergencia|alto total|detente todo|detener robot|para el robot)$")


def manejar(frase):
    """Para la cadena de modulos de Arche: texto de respuesta, o None si la frase no es del banco."""
    if not frase:
        return None
    t = ar._normalizar(frase)
    if _RE_EMERGENCIA.match(t):
        if _banco is not None:
            _banco.paro("Parada de emergencia desde Arche.")
        return None                      # el modulo del robot tambien la atiende
    try:
        if _RE_ABRIR.match(t):
            url = iniciar()
            texto = (f"Banco de pruebas listo. Panel en el PC: {url}/  |  App del iPhone en la misma WiFi: {url}/app  "
                     f"(la primera vez, instala el certificado desde {_url_instalar()} en Safari).")
            url_ts = _url_tailscale_publicada()
            if url_ts:
                texto += f"  |  Por Tailscale (dirección fija, desde cualquier red): {url_ts}/app"
            elif _ip_tailscale():
                texto += "  |  Para usarlo por Tailscale con dirección fija di: abre el perro en tailscale"
            return texto + "  |  Arranca en PARO: elige Manual o Perro."
        if _RE_TS_ABRIR.match(t):
            iniciar()
            import tailscale_perro
            url_ts, estado = tailscale_perro.publicar(PUERTO)
            if not url_ts:
                return "No pude publicar el banco en Tailscale. " + estado
            return (f"Listo, el banco está en Tailscale: {url_ts}/app  |  Ábrela en Safari del iPhone con Tailscale "
                    "encendido y agrégala a la pantalla de inicio. Esa dirección no cambia y no hace falta clave "
                    "ni instalar certificado. Tailscale la recuerda aunque reinicies el PC.")
        if _RE_TS_QUITAR.match(t):
            import tailscale_perro
            ok, salida = tailscale_perro.quitar()
            return "Quité el banco de Tailscale." if ok else f"No pude quitarlo de Tailscale ({salida})."
        if _RE_TUNEL_ABRIR.match(t):
            iniciar()
            url, estado = iniciar_tunel()
            if not url:
                return "No pude abrir el acceso por internet. " + estado
            return (f"Acceso por internet listo. App: {url}/app  |  Clave: {acceso.clave_bonita()}  |  "
                    "No hace falta instalar certificado. Esa dirección cambia cada vez que abres el túnel. "
                    "Cuando termines di: cierra el tunel del perro.")
        if _RE_TUNEL_CERRAR.match(t):
            cerrar_tunel()
            return "Acceso por internet cerrado. El banco sigue funcionando en tu WiFi y por Tailscale."
        if _RE_CLAVE_VER.match(t):
            return f"La clave del banco de pruebas es {acceso.clave_bonita()}."
        if _RE_CLAVE_NUEVA.match(t):
            return (f"Clave nueva: {acceso.cambiar_clave()}. Todos los que habían entrado por internet "
                    "tienen que volver a escribirla.")
        if _RE_PARO.match(t):
            if _banco is None:
                return "El banco de pruebas no esta activo."
            _banco.paro("Paro pedido desde Arche.")
            return "Banco en paro: el robot esta quieto."
        if _RE_ESTADO.match(t):
            if _banco is None:
                return "El banco de pruebas no esta activo. Di: banco de pruebas."
            e = _banco.estado()
            return (f"Banco: modo {e['modo']}, celular {'ok' if e['camara']['ok'] else 'sin video'} "
                    f"({e['camara']['fps']} fps), ESP32 {'perdido' if e['esp']['perdido'] else (e['esp']['estado'] or 'sin datos')}, "
                    f"evento {e['evento']}.")
        # Ordenes al perro dichas a Arche ("sientate", "ven", "mueve el servo 2 a 90"...).
        # Con el banco abierto pasan por aqui, para que la camara no las pise (igual que desde la app).
        if _banco is not None:
            ok, respuesta = _banco.orden(frase)
            if ok:
                return respuesta
    except Exception as e:
        return f"El banco de pruebas fallo: {e}"
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Banco de pruebas del perro robotico")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--http", action="store_true", help="sin HTTPS (solo sirve con --fuente)")
    ap.add_argument("--fuente", help="URL de un stream de camara IP, ej. http://192.168.1.50:8080/video")
    ap.add_argument("--tunel", action="store_true", help="abre tambien un tunel de internet con cloudflared (pide clave)")
    a = ap.parse_args()
    b = obtener_banco()
    esquema = "http" if a.http else "https"
    ip = ip_local()
    print(f"\nPanel (PC):      {esquema}://{ip}:{a.puerto}/")
    if a.fuente:
        print(f"Video: leyendo {a.fuente}")
    else:
        print(f"Ojos (celular):  {esquema}://{ip}:{a.puerto}/camara")
    if not a.http:
        print(f"App iPhone:      {esquema}://{ip}:{a.puerto}/app")
        print(f"Instalar (1a vez, en Safari del iPhone):  {_url_instalar(a.puerto)}")
        url_ts = _url_tailscale_publicada(a.puerto)
        if url_ts:
            print(f"Por Tailscale:   {url_ts}/app   (direccion fija)")
    if a.tunel:
        def _avisar_tunel():
            time.sleep(2)
            url, estado = iniciar_tunel(a.puerto, https=not a.http)
            print(f"Internet:        {url}/app   clave {acceso.clave_bonita()}" if url else f"Tunel: {estado}")
        threading.Thread(target=_avisar_tunel, daemon=True).start()
    print("El banco arranca en PARO. Ctrl+C para salir.\n")
    if a.fuente:
        threading.Thread(target=leer_fuente, args=(b, a.fuente), daemon=True).start()
    try:
        servir(b, a.puerto, https=not a.http)
    except KeyboardInterrupt:
        pass
    finally:
        cerrar_tunel()
        b.cerrar()