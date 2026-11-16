"""
voz_viva.py
-----------
Ubicacion: Arche/core/raphael/voz_viva.py

CONVERSACIÓN VIVA: hablar con Arché como con una persona, no por comandos sueltos.

Mejora la escucha que Arché ya tiene (core/IA/voz.py, «oye Arché ...») sin modificar ese
archivo: se pone en su lugar al arrancar.

  1. CONVERSACIÓN SEGUIDA: después de «oye Arché», durante 20 segundos (y cada vez que
     ella termina de hablar) puedes seguir hablando SIN repetir «oye Arché».
     «eso es todo» / «gracias, nada más» cierra la conversación.
  2. INTERRUPCIÓN: si Arché está hablando y tú hablas fuerte encima, se calla y te escucha.
     (Con parlantes muy altos puede confundirse con su propia voz: sube o baja con
     «sensibilidad de interrupción alta / media / baja». Con audífonos funciona mejor.)
  3. TU VOZ: con «aprende mi voz» graba 3 frases cortas tuyas y saca una huella. Con
     «solo obedece mi voz» ignora a otras personas. Es una huella sencilla (no biométrica
     de banco): distingue voces bastante distintas, no imitadores.
  4. INICIATIVA: los avisos importantes de Raphael (comun.informe) ya se dicen en voz alta
     solos; aquí no hay que hacer nada.
  5. FILTRO DE ALUCINACIONES: Whisper a veces "oye" frases en el silencio («gracias por ver
     el video», «subtítulos de Amara.org»...). Se ignoran.
"""

import queue
import re
import time

from core.raphael import comun

ARCH = comun.ruta("voz_viva.json")
VENTANA_SEG = 20
SENSIBILIDAD = {"alta": 2.0, "media": 3.0, "baja": 4.5}
FRAMES_INTERRUPCION = 8                   # ~240 ms hablando encima
SEGUNDOS_MUESTRA_VOZ = 4
MUESTRAS_VOZ = 3

_RELLENO = {"eh", "em", "mm", "mmm", "ah", "uh", "este", "pues", "ajá", "aja", "hm", "hmm", "eeh"}
_ALUCINACIONES = re.compile(r"gracias por ver|suscribete|subtitulos? (?:realizados|por|de)|amara\.?org|"
                            r"musica de fondo|\[musica\]|♪")
_CIERRE = re.compile(r"^(?:gracias[, ]*)?(?:eso es todo|nada mas|ya esta|listo gracias|es todo|ya no|"
                     r"gracias arche|chao arche|hasta luego)$")

_original = {"escuchar": None}
_huella = {"vector": None, "umbral": None}


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activa", True)
    e.setdefault("sensibilidad", "media")
    e.setdefault("solo_mi_voz", False)
    e.setdefault("huella", None)
    e.setdefault("umbral_huella", None)
    return e


def _guardar(e):
    comun.guardar(ARCH, e)


# ------------------------------------------------------------------
# Piezas que se prueban sin micrófono
# ------------------------------------------------------------------

class VentanaConversacion:
    """Mientras está abierta, no hace falta decir «oye Arché»."""

    def __init__(self, segundos=VENTANA_SEG):
        self.segundos = segundos
        self.hasta = 0.0

    def abrir(self, t=None):
        self.hasta = (t or time.time()) + self.segundos

    def extender(self, t=None):
        if self.abierta(t):
            self.hasta = max(self.hasta, (t or time.time()) + self.segundos)

    def cerrar(self):
        self.hasta = 0.0

    def abierta(self, t=None):
        return (t or time.time()) < self.hasta


def es_ruido(texto_norm):
    """True si lo transcrito no es algo que le dijiste a Arché."""
    t = (texto_norm or "").strip(" .,!?¿¡")
    if not t or _ALUCINACIONES.search(t):
        return True
    palabras = t.split()
    return all(p in _RELLENO for p in palabras)


def es_cierre(texto_norm):
    return bool(_CIERRE.match((texto_norm or "").strip(" .,!?¿¡")))


def _mel_filtros(n_fft, sr, n_mel=26):
    import numpy as np

    def hz_a_mel(h):
        return 2595 * np.log10(1 + h / 700.0)

    def mel_a_hz(m):
        return 700 * (10 ** (m / 2595.0) - 1)

    mels = np.linspace(hz_a_mel(80), hz_a_mel(sr / 2 - 200), n_mel + 2)
    bins = np.floor((n_fft + 1) * mel_a_hz(mels) / sr).astype(int)
    filtros = np.zeros((n_mel, n_fft // 2 + 1))
    for i in range(1, n_mel + 1):
        a, b, c = bins[i - 1], bins[i], bins[i + 1]
        for k in range(a, b):
            filtros[i - 1, k] = (k - a) / max(1, b - a)
        for k in range(b, c):
            filtros[i - 1, k] = (c - k) / max(1, c - b)
    return filtros


def huella_de(audio, sr=16000):
    """Vector que resume cómo suena una voz (energías mel: media y variación). None si no hay voz."""
    import numpy as np
    audio = np.asarray(audio, dtype=np.float32)
    n_fft, salto = 512, 160
    if len(audio) < n_fft * 4:
        return None
    ventanas = np.lib.stride_tricks.sliding_window_view(audio, n_fft)[::salto] * np.hanning(n_fft)
    potencia = np.abs(np.fft.rfft(ventanas, axis=1)) ** 2
    energia = potencia.sum(axis=1)
    con_voz = energia > np.percentile(energia, 40)
    if con_voz.sum() < 10:
        return None
    mel = np.log(potencia[con_voz] @ _mel_filtros(n_fft, sr).T + 1e-9)
    mel -= mel.mean(axis=1, keepdims=True)        # quita el volumen: queda el "color" de la voz
    return np.concatenate([mel.mean(axis=0), mel.std(axis=0)])


def similitud(a, b):
    import numpy as np
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def umbral_desde_muestras(huellas):
    """El umbral sale de cuánto se parecen TUS propias muestras entre sí (con un margen)."""
    sims = [similitud(huellas[i], huellas[j]) for i in range(len(huellas)) for j in range(i + 1, len(huellas))]
    return max(0.5, min(sims) - 0.08) if sims else 0.8


def _cargar_huella():
    e = _estado()
    if e.get("huella"):
        _huella["vector"] = e["huella"]
        _huella["umbral"] = e.get("umbral_huella") or 0.8


def es_mi_voz(audio_16k):
    """True si no está activo «solo mi voz», o si la voz se parece a la tuya."""
    e = _estado()
    if not e["solo_mi_voz"] or not _huella["vector"]:
        return True
    h = huella_de(audio_16k)
    if h is None:
        return False
    return similitud(h, _huella["vector"]) >= _huella["umbral"]


# ------------------------------------------------------------------
# La escucha nueva (mismo contrato que core/IA/voz.escuchar_continuo)
# ------------------------------------------------------------------

def escuchar_continuo(al_detectar_comando, detener_evento=None, umbral_energia=None):
    from core.IA import voz as oido
    import numpy as np
    import sounddevice as sd

    umbral = umbral_energia or oido.UMBRAL_ENERGIA
    sample_rate = oido._detectar_samplerate()
    frame_samples = int(sample_rate * oido.FRAME_MS / 1000)
    silencio_fin = oido.SILENCIO_FIN_UTTERANCE_MS // oido.FRAME_MS
    preroll_max = 12
    ventana = VentanaConversacion()
    cola = queue.Queue()
    estado = {"buffer": [], "preroll": [], "en_voz": False, "silencio": 0, "esperando": False,
              "fuerte": 0, "interrumpio": False, "hablaba": False}

    def callback(indata, frames, time_info, status):
        cola.put(bytes(indata))

    def _rms(frame):
        a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0

    def _reiniciar():
        estado.update(buffer=[], en_voz=False, silencio=0)

    with sd.RawInputStream(samplerate=sample_rate, blocksize=frame_samples, dtype="int16", channels=1,
                           device=oido.DISPOSITIVO, callback=callback):
        while detener_evento is None or not detener_evento.is_set():
            try:
                frame = cola.get(timeout=1)
            except queue.Empty:
                continue
            factor = SENSIBILIDAD.get(_estado()["sensibilidad"], 3.0)
            hablando = oido._arche_esta_hablando()
            if hablando:
                estado["hablaba"] = True
                if _rms(frame) > umbral * factor:
                    estado["fuerte"] += 1
                    estado["buffer"].append(frame)
                    if estado["fuerte"] >= FRAMES_INTERRUPCION:
                        try:
                            from core import voz
                            voz.calla()
                        except Exception:
                            pass
                        estado.update(en_voz=True, silencio=0, fuerte=0, interrumpio=True)
                        ventana.abrir()
                    continue
                estado["fuerte"] = 0
                if not estado["interrumpio"]:
                    _reiniciar()
                    estado["preroll"] = []
                continue
            if estado["hablaba"]:            # Arché acaba de terminar de hablar: le toca a Daniel
                estado["hablaba"] = False
                ventana.extender()

            if _rms(frame) > umbral:
                if not estado["en_voz"]:
                    estado["buffer"].extend(estado["preroll"])
                estado["buffer"].append(frame)
                estado.update(en_voz=True, silencio=0)
                continue
            estado["preroll"].append(frame)
            if len(estado["preroll"]) > preroll_max:
                estado["preroll"].pop(0)
            if not estado["en_voz"]:
                continue
            estado["buffer"].append(frame)
            estado["silencio"] += 1
            if estado["silencio"] < silencio_fin:
                continue

            audio = np.frombuffer(b"".join(estado["buffer"]), dtype=np.int16).astype(np.float32) / 32768.0
            interrumpio = estado["interrumpio"]
            _reiniciar()
            estado.update(preroll=[], interrumpio=False)
            if len(audio) < sample_rate * oido.DURACION_MINIMA_SEG:
                continue
            audio_16k = oido._resamplear(audio, sample_rate)
            if not es_mi_voz(audio_16k):
                continue

            if interrumpio or ventana.abierta() or estado["esperando"]:
                # Conversación en curso: no hace falta la palabra de activación.
                texto = oido._normalizar(oido._transcribir(audio_16k, oido.MODELO_COMANDO))
                estado["esperando"] = False
                if es_ruido(texto):
                    continue
                if es_cierre(texto):
                    ventana.cerrar()
                    print("Arché: Listo. Cuando me necesites, di «oye Arché».")
                    continue
                comando = oido._extraer_comando(texto)
                ventana.abrir()
                al_detectar_comando(comando if comando else texto)
                continue

            texto = oido._normalizar(oido._transcribir(audio_16k, oido.MODELO_DETECCION))
            if es_ruido(texto):
                continue
            comando = oido._extraer_comando(texto)
            if comando is None:
                continue
            if comando:
                fino = oido._normalizar(oido._transcribir(audio_16k, oido.MODELO_COMANDO))
                comando_fino = oido._extraer_comando(fino)
                ventana.abrir()
                al_detectar_comando(comando_fino if comando_fino else comando)
            else:
                print("Arché: Te escucho...")
                estado["esperando"] = True
                ventana.abrir()


# ------------------------------------------------------------------
# Aprender tu voz
# ------------------------------------------------------------------

def aprender_mi_voz(avisar=print):
    from core.IA import voz as oido
    import sounddevice as sd
    import numpy as np
    sr = oido._detectar_samplerate()
    frases = ["Hola Arché, soy yo y esta es mi voz.", "Hoy quiero trabajar en mis proyectos.",
              "Recuerda cómo sueno para reconocerme."]
    huellas = []
    for i in range(MUESTRAS_VOZ):
        avisar(f"Muestra {i + 1}/{MUESTRAS_VOZ}: cuando veas «YA», di: «{frases[i]}»")
        time.sleep(1.5)
        avisar("YA")
        grab = sd.rec(int(SEGUNDOS_MUESTRA_VOZ * sr), samplerate=sr, channels=1, dtype="int16", device=oido.DISPOSITIVO)
        sd.wait()
        audio = grab[:, 0].astype(np.float32) / 32768.0
        h = huella_de(oido._resamplear(audio, sr))
        if h is None:
            avisar("No te escuché bien en esa. Repitamos.")
            return False
        huellas.append(h)
    vector = np.mean(huellas, axis=0)
    e = _estado()
    e["huella"] = [float(x) for x in vector]
    e["umbral_huella"] = umbral_desde_muestras(huellas)
    _guardar(e)
    _cargar_huella()
    avisar("Listo, ya conozco tu voz. Di «solo obedece mi voz» para que ignore a otras personas.")
    return True


# ------------------------------------------------------------------
# Instalación
# ------------------------------------------------------------------

def instalar():
    """Pone la escucha nueva en lugar de la de core/IA/voz.py (si la voz se puede usar en este PC)."""
    if not _estado()["activa"]:
        return False
    try:
        from core.IA import voz as oido
    except Exception:
        return False                      # sin micrófono / sin librerías: Arché sigue igual
    if _original["escuchar"] is None:
        _original["escuchar"] = oido.escuchar_continuo
    oido.escuchar_continuo = escuchar_continuo
    _cargar_huella()
    try:                                  # si el micrófono ya estaba escuchando con la versión vieja, se reinicia
        from core.interfaz import micro
        if micro.activa():
            micro.detener()
            time.sleep(1.2)
            micro.iniciar()
    except Exception:
        pass
    return True


def desinstalar():
    try:
        from core.IA import voz as oido
        if _original["escuchar"] is not None:
            oido.escuchar_continuo = _original["escuchar"]
    except Exception:
        pass


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

def manejar(comando):
    c = comun.norm(comando)
    if c in ("conversacion viva encendida", "conversacion viva on", "activa la conversacion viva", "modo conversacion"):
        e = _estado(); e["activa"] = True; _guardar(e)
        comun.msg("Conversación viva encendida: después de «oye Arché» puedes seguir hablando sin repetirlo, "
                  "y si hablas encima de mí, me callo y te escucho." if instalar() else
                  "La activé, pero en este PC no pude usar el micrófono (faltan librerías o micrófono).")
        return True
    if c in ("conversacion viva apagada", "conversacion viva off", "apaga la conversacion viva"):
        e = _estado(); e["activa"] = False; _guardar(e)
        desinstalar()
        comun.msg("Conversación viva apagada: vuelvo a necesitar «oye Arché» antes de cada orden.")
        return True
    if c in ("aprende mi voz", "aprende como suena mi voz", "reconoce mi voz"):
        comun.msg("Voy a grabar 3 frases cortas tuyas. Habla normal, cerca del micrófono.")
        comun.en_hilo(lambda: aprender_mi_voz(avisar=comun.msg), nombre="arche-huella-voz")
        return True
    if c in ("solo obedece mi voz", "solo mi voz", "obedeceme solo a mi"):
        e = _estado()
        if not e.get("huella"):
            comun.msg("Primero necesito conocer tu voz: di «aprende mi voz».")
            return True
        e["solo_mi_voz"] = True; _guardar(e)
        comun.msg("Listo: solo obedezco órdenes de voz que suenen como tú.")
        return True
    if c in ("obedece a todos", "obedece cualquier voz", "quita solo mi voz"):
        e = _estado(); e["solo_mi_voz"] = False; _guardar(e)
        comun.msg("Listo: obedezco a cualquier voz que diga «oye Arché».")
        return True
    m = re.match(r"^sensibilidad de (?:la )?interrupcion (alta|media|baja)$", c)
    if m:
        e = _estado(); e["sensibilidad"] = m.group(1); _guardar(e)
        comun.msg(f"Sensibilidad de interrupción: {m.group(1)}.")
        return True
    if c in ("estado de la voz viva", "estado de la conversacion viva"):
        e = _estado()
        comun.msg(f"Conversación viva: {'encendida' if e['activa'] else 'apagada'}. Sensibilidad para interrumpirme: "
                  f"{e['sensibilidad']}. Huella de tu voz: {'sí' if e.get('huella') else 'no'}"
                  f"{' (solo te obedezco a ti)' if e['solo_mi_voz'] else ''}.")
        return True
    return False
