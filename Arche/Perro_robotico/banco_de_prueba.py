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
import collections
import json
import logging
import os
import re
import socket
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request, send_file

import acciones_robot as ar          # patas, secuencias y MQTT de publicacion
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

# cuadros seguidos que hacen falta para dar por buena una deteccion (evita parpadeos)
CONFIRMAR = {"movimiento": 1, "cerca": 2, "cara": 2, "pelota": 2, "nada": 8}

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

        self.modo = "paro"                   # paro | manual | perro
        self.modo_previo = "manual"
        self.motivo_paro = "Arranca en paro: elige Manual o Perro."
        self.gracia_hasta = 0.0

        self.mapa = dict(MAPA_INICIAL)
        self.cooldown = 2.5
        self.invertir_giro = False

        # percepcion
        self.ev = "nada"
        self.cand = "nada"
        self.cand_n = 0
        self.res = None
        self.ultimo_x = {"cara": 0.0, "pelota": 0.0}
        self.ultimo_jpg = None
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
                             "invertir_giro": d.get("invertir_giro", self.invertir_giro)}, guardar=False)

    def _guardar(self):
        try:
            with open(RUTA_CFG, "w", encoding="utf-8") as f:
                json.dump({"mapa": self.mapa, "cooldown": self.cooldown, "invertir_giro": self.invertir_giro,
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
        try:
            c = ar.mqtt.Client(ar.mqtt.CallbackAPIVersion.VERSION2)   # paho-mqtt 2.x
        except AttributeError:
            c = ar.mqtt.Client()                                       # paho-mqtt 1.x

        def on_connect(cl, userdata, flags, rc, *extra):
            self.mon_conectado = True
            self.mon_visto = True
            cl.subscribe([(self.t_estado, 0), (self.t_hb, 0), (self.t_ack, 0)])

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

        c.on_connect, c.on_disconnect, c.on_message = on_connect, on_disconnect, on_message
        try:
            c.connect_async(ar.MQTT_BROKER, ar.MQTT_PORT, 30)
            c.loop_start()
        except Exception as e:
            self.mon_error = f"No pude iniciar el monitor MQTT ({e})."
        self._mon = c

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
            self.accion_actual = None
        try:
            ar._modo_perro.detener("Paro del banco de pruebas.")
            ar._ejecutor.quieto()
        except Exception:
            pass

    def set_modo(self, modo):
        if modo not in ("manual", "perro"):
            return False, "Modo invalido."
        if time.time() - self.t_ultimo_cuadro > TIMEOUT_CAMARA:
            return False, "No llega video del celular: abre /camara en el celular y pulsa Iniciar."
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
            self.gracia_hasta = time.time() + GRACIA_TRAS_ACTIVAR
            self.cerebro.reiniciar(time.time())
            self.ev_manual_prev = self.ev
            self.ultimo_error = ""
        return True, f"Modo {modo} activado."

    def reanudar(self):
        return self.set_modo(self.modo_previo if self.modo_previo in ("manual", "perro") else "manual")

    def _vigilante(self):
        while not self._fin.wait(0.25):
            t = time.time()
            if self.modo == "paro" or t < self.gracia_hasta:
                continue
            if t - self.t_ultimo_cuadro > TIMEOUT_CAMARA:
                self.paro("Se perdio el video del celular.")
            elif self.esp_perdido():
                self.paro("Se perdio la conexion con el ESP32.")
            elif self.mon_visto and not self.mon_conectado:
                self.paro("Se perdio la conexion con el broker MQTT.")

    def cerrar(self):
        self._fin.set()
        self.paro("Banco cerrado.")

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
        if cand == self.cand:
            self.cand_n += 1
        else:
            self.cand, self.cand_n = cand, 1
        if self.cand_n >= CONFIRMAR[cand]:
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

            if self.modo == "manual":
                accion = self._decidir_manual(ev)
            elif self.modo == "perro":
                accion = self.cerebro.decidir(ev, self.ultimo_x.get(ev, 0.0), ahora, self.invertir_giro)
            else:
                accion = None
            if accion:
                self._enviar(accion, ev, t_llegada, det_ms)

            etiqueta = f"{ev}  [{self.modo}]" + (f"  -> {self.accion_actual}" if self.accion_actual and self.modo != "paro" else "")
            ok, buf = cv2.imencode(".jpg", anotar(frame, res, etiqueta), [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                self.ultimo_jpg = buf.tobytes()
            return {"evento": ev, "crudo": res["evento"], "modo": self.modo}

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
            "modo": self.modo, "motivo_paro": self.motivo_paro, "error": self.ultimo_error or self.mon_error,
            "camara": {"ok": cam_ok, "fps": round(fps, 1), "cuadros": self.cuadros,
                       "hace_s": round(t - self.t_ultimo_cuadro, 1) if self.t_ultimo_cuadro else None},
            "esp": {"estado": self.esp_estado, "hb_visto": self.hb_visto, "perdido": self.esp_perdido(),
                    "hb_hace_s": round(t - self.last_hb, 1) if self.hb_visto else None},
            "mqtt": {"ok": self.mon_conectado},
            "evento": self.ev, "crudo": res.get("evento", "nada"),
            "detalle": {"movimiento": res.get("movimiento"), "textura": res.get("textura"),
                        "cerca_por": res.get("cerca_por", ""), "cara": res.get("cara"), "pelota": res.get("pelota")},
            "accion_actual": self.accion_actual,
            "eventos": EVENTOS, "reacciones": REACCIONES, "mapa": self.mapa,
            "colores": list(PRESETS_COLOR), "config": dict(self.detector.config),
            "cooldown": self.cooldown, "invertir_giro": self.invertir_giro,
            "perro": {"mood": self.cerebro.mood, "postura": self.cerebro.postura, "razon": self.cerebro.razon,
                      "params": dict(self.cerebro.params)},
            "lat": {"deteccion": self._prom(self.lat_det), "red_celular": self._prom(self.lat_red),
                    "publicar": self._prom(pubs), "total": self._prom(totales),
                    "por_evento": por_evento, "historial": hist},
        }


# ============================================================ servidor web
def crear_app(b):
    app = Flask(__name__)

    @app.get("/")
    def panel():
        return send_file(os.path.join(HERE, "panel.html"))

    @app.get("/camara")
    def camara():
        return send_file(os.path.join(HERE, "camara.html"))

    @app.post("/frame")
    def frame():
        t_llegada = time.perf_counter()
        img = cv2.imdecode(np.frombuffer(request.get_data(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return jsonify(error="cuadro invalido"), 400
        r = b.procesar(img, t_llegada, request.headers.get("X-Net-Ms", type=float))
        r["proc_ms"] = round((time.perf_counter() - t_llegada) * 1000, 1)
        return jsonify(r)

    @app.get("/video")
    def video():
        def generar():
            ultimo = None
            while True:
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


def servir(b, puerto=PUERTO, https=True):
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = crear_app(b)
    ctx = None
    if https:
        try:
            import cryptography  # noqa: F401
            ctx = "adhoc"
        except ImportError:
            print("Banco: sin 'cryptography' no hay HTTPS y el celular no abrira la camara desde el navegador. "
                  "Instala: pip install cryptography (o usa --fuente con una app de camara IP).")
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


# OJO: "estado del banco" a secas ya es un comando de Arche (banco de entrenamiento), por eso aqui
# siempre se exige "de pruebas".
_RE_ABRIR = re.compile(r"^(?:abre|activa|enciende|inicia|arranca)(?: el)? banco de pruebas$|^banco de pruebas$")
_RE_PARO = re.compile(r"^(?:apaga|para|detiene|desactiva)(?: el)? banco de pruebas$|^paro del banco de pruebas$")
_RE_ESTADO = re.compile(r"^estado del banco de pruebas$")
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
            return (f"Banco de pruebas listo. Panel en el PC: {url}/  |  Ojos en el celular: {url}/camara  "
                    "(acepta el aviso del certificado). Arranca en PARO: elige Manual o Perro en el panel.")
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
    except Exception as e:
        return f"El banco de pruebas fallo: {e}"
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Banco de pruebas del perro robotico")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--http", action="store_true", help="sin HTTPS (solo sirve con --fuente)")
    ap.add_argument("--fuente", help="URL de un stream de camara IP, ej. http://192.168.1.50:8080/video")
    a = ap.parse_args()
    b = obtener_banco()
    esquema = "http" if a.http else "https"
    ip = ip_local()
    print(f"\nPanel (PC):      {esquema}://{ip}:{a.puerto}/")
    if a.fuente:
        print(f"Video: leyendo {a.fuente}")
    else:
        print(f"Ojos (celular):  {esquema}://{ip}:{a.puerto}/camara   <- acepta el aviso de certificado")
    print("El banco arranca en PARO. Ctrl+C para salir.\n")
    if a.fuente:
        threading.Thread(target=leer_fuente, args=(b, a.fuente), daemon=True).start()
    try:
        servir(b, a.puerto, https=not a.http)
    except KeyboardInterrupt:
        pass
    finally:
        b.cerrar()