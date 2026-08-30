"""
voz.py
------
Reconocimiento de voz con wake word ("oye asistente") para Arché.

Arquitectura:
  1. Captura de audio continua en background (sounddevice).
  2. Detección de voz por ENERGÍA (RMS del audio) para segmentar
     "utterances" -> evita transcribir silencio constantemente.
     (No se usa webrtcvad a propósito: es una extensión en C que suele
     no tener wheels precompilados para Python 3.13 en Windows.)
  3. Transcripción en DOS NIVELES con faster-whisper:
     - Modelo "base" (rápido) revisa cada utterance en busca de la wake
       word. "Arché" resultó poco confiable de transcribir (nombre
       inventado, sin prior lingüístico), así que la wake word real es
       "oye asistente" / "asistente" (variantes de "arché" quedan como
       respaldo por si el modelo las acierta).
     - Modelo "small" (más preciso) solo se usa para re-transcribir el
       audio cuando ya se confirmó la wake word, y así obtener el
       comando con mejor calidad sin pagar ese costo en cada utterance.
  4. Se extrae el comando (lo que sigue a la wake word, o la siguiente
     utterance si dijeron solo la wake word sola) y se pasa tal cual al
     mismo pipeline que ya usa el texto escrito.

Requiere:
    pip install sounddevice faster-whisper numpy scipy

NOTA DE RENDIMIENTO:
La escucha continua consume CPU todo el tiempo. El detector de energía
en sí es prácticamente gratis. El modelo "base" corre en cada utterance
detectada (rápido). El modelo "small" solo corre cuando se confirmó la
wake word, así que su costo mayor es ocasional, no constante.

NOTA DE CALIBRACIÓN:
UMBRAL_ENERGIA depende de tu micrófono y el ruido ambiente de tu cuarto.
Si Arché no reacciona cuando hablas, bájalo. Si reacciona con cualquier
ruido de fondo, súbelo. Usa voz_calibrar.py para encontrar un buen valor.
"""

import queue
import numpy as np
import sounddevice as sd

CAPTURA_SAMPLE_RATE = None     # se detecta según el dispositivo, ver _detectar_samplerate()
WHISPER_SAMPLE_RATE = 16000    # Whisper espera específicamente esta tasa
FRAME_MS = 30

# Índice del dispositivo de entrada. Corre
# `py -c "import sounddevice as sd; print(sd.query_devices())"` si cambias
# de hardware y este índice deja de corresponder a tu micrófono.
DISPOSITIVO = 9  # "Varios micrófonos (2- Realtek(R) Audio), Windows WASAPI" -- mejor separación silencio/voz de los probados

UMBRAL_ENERGIA = 120           # calibrado con voz_calibrar.py (silencio ~0-30, voz ~300-1500)
SILENCIO_FIN_UTTERANCE_MS = 1000
DURACION_MINIMA_SEG = 0.3     # utterances más cortas que esto se ignoran (ruido)

WAKE_WORDS = [
    "oye asistente",
    "hola asistente",
    "asistente",
    "oye arche",
    "arche",
    "hey arche",
    "arce",
    "archie",
]  # "asistente" primero: palabras comunes que Whisper transcribe con más consistencia
   # que el nombre inventado "Arché". Las variantes de "arché" quedan como respaldo.

MODELO_DETECCION = "base"   # rápido: revisa cada utterance en busca de la wake word
MODELO_COMANDO = "small"    # más preciso: solo se usa cuando ya se confirmó la wake word

_modelos_whisper = {}


def _cargar_whisper(nombre):
    if nombre not in _modelos_whisper:
        from faster_whisper import WhisperModel
        print(f"Arché: Cargando modelo de voz '{nombre}' (solo la primera vez)...")
        _modelos_whisper[nombre] = WhisperModel(nombre, device="cpu", compute_type="int8")
        print(f"Arché: Modelo de voz '{nombre}' listo.")
    return _modelos_whisper[nombre]


def _transcribir(audio_float32, modelo_nombre=MODELO_DETECCION):
    modelo = _cargar_whisper(modelo_nombre)
    segmentos, _ = modelo.transcribe(audio_float32, language="es")
    return " ".join(seg.text for seg in segmentos).strip()


def _detectar_samplerate():
    info = sd.query_devices(DISPOSITIVO)
    return int(info["default_samplerate"])


def _resamplear(audio_np, sr_original, sr_destino=WHISPER_SAMPLE_RATE):
    """
    Resampleo con filtro anti-aliasing (scipy.signal.resample_poly).
    La interpolación lineal simple distorsiona la señal al bajar la tasa
    de muestreo (especialmente de 44100/48000 -> 16000), lo cual puede
    arruinar la transcripción. resample_poly filtra correctamente antes
    de reducir la tasa, preservando la inteligibilidad de la voz.
    """
    if sr_original == sr_destino or len(audio_np) == 0:
        return audio_np

    from math import gcd
    from scipy.signal import resample_poly

    divisor = gcd(sr_destino, sr_original)
    up = sr_destino // divisor
    down = sr_original // divisor
    return resample_poly(audio_np, up, down).astype(np.float32)


def _normalizar(texto):
    import unicodedata
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def _es_voz(frame_int16_bytes, umbral=UMBRAL_ENERGIA):
    audio = np.frombuffer(frame_int16_bytes, dtype=np.int16).astype(np.float32)
    rms = np.sqrt(np.mean(audio ** 2)) if len(audio) else 0.0
    return rms > umbral


def _extraer_comando(texto_normalizado):
    """
    Si el texto contiene una wake word, devuelve lo que sigue a ella
    (puede ser cadena vacía si solo dijeron la wake word).
    Devuelve None si no se detectó ninguna wake word.
    """
    for wake in WAKE_WORDS:
        if wake in texto_normalizado:
            resto = texto_normalizado.split(wake, 1)[1].strip()
            return resto
    return None


def escuchar_continuo(al_detectar_comando, detener_evento=None, umbral_energia=UMBRAL_ENERGIA):
    """
    Bucle pensado para correr en un hilo aparte. Escucha el micrófono,
    detecta la wake word, y llama a al_detectar_comando(texto) cada vez
    que reconoce un comando completo.

    detener_evento: threading.Event opcional para frenar el hilo
    limpiamente desde afuera (evento.set() para detener).
    """
    sample_rate = _detectar_samplerate()
    frame_samples = int(sample_rate * FRAME_MS / 1000)
    silencio_fin_frames = SILENCIO_FIN_UTTERANCE_MS // FRAME_MS

    # Buffer circular de "pre-grabación": guarda constantemente los
    # últimos N frames aunque estemos en silencio, para poder anteponerlos
    # cuando se detecta voz y así no perder el ataque de la primera palabra.
    PREROLL_FRAMES = 12  # ~360ms a 30ms/frame
    preroll = []

    buffer_utterance = []
    frames_silencio_seguidos = 0
    en_utterance = False
    esperando_comando_tras_wake = False

    cola_audio = queue.Queue()

    def callback(indata, frames, time_info, status):
        cola_audio.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=frame_samples,
        dtype="int16",
        channels=1,
        device=DISPOSITIVO,
        callback=callback,
    ):
        while detener_evento is None or not detener_evento.is_set():
            try:
                frame_bytes = cola_audio.get(timeout=1)
            except queue.Empty:
                continue

            es_voz = _es_voz(frame_bytes, umbral_energia)

            if es_voz:
                if not en_utterance:
                    # Primer frame de voz detectado: anteponemos el
                    # pre-roll acumulado para no perder el inicio.
                    buffer_utterance.extend(preroll)
                buffer_utterance.append(frame_bytes)
                frames_silencio_seguidos = 0
                en_utterance = True
                continue

            # Frame en silencio: siempre se guarda en el pre-roll
            # (rotando), esté o no en curso una utterance.
            preroll.append(frame_bytes)
            if len(preroll) > PREROLL_FRAMES:
                preroll.pop(0)

            if not en_utterance:
                continue

            # Estamos en silencio, pero veníamos de una utterance en curso
            buffer_utterance.append(frame_bytes)  # incluye un poco de cola
            frames_silencio_seguidos += 1

            if frames_silencio_seguidos < silencio_fin_frames:
                continue

            # --- Utterance terminada -> transcribir ---
            audio_bytes = b"".join(buffer_utterance)
            audio_np = (
                np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            )

            buffer_utterance = []
            en_utterance = False
            frames_silencio_seguidos = 0
            preroll = []

            if len(audio_np) < sample_rate * DURACION_MINIMA_SEG:
                continue  # demasiado corto, probablemente ruido

            audio_16k = _resamplear(audio_np, sample_rate)

            texto = _transcribir(audio_16k, MODELO_DETECCION)
            print(f"[debug] transcripción cruda ({MODELO_DETECCION}): {texto!r}")
            if not texto:
                continue

            texto_norm = _normalizar(texto)

            if esperando_comando_tras_wake:
                esperando_comando_tras_wake = False
                # Ya sabemos que esto ES contenido real (el comando tras
                # la wake word) -> vale la pena re-transcribir con el
                # modelo más preciso.
                texto_fino = _transcribir(audio_16k, MODELO_COMANDO)
                print(f"[debug] transcripción fina ({MODELO_COMANDO}): {texto_fino!r}")
                al_detectar_comando(_normalizar(texto_fino))
                continue

            comando = _extraer_comando(texto_norm)
            if comando is None:
                continue  # no dijeron la wake word, se ignora

            if comando:
                # Confirmado: esta utterance trae wake word + comando
                # juntos -> re-transcribimos el mismo audio con el modelo
                # preciso para una mejor versión final.
                texto_fino = _transcribir(audio_16k, MODELO_COMANDO)
                print(f"[debug] transcripción fina ({MODELO_COMANDO}): {texto_fino!r}")
                texto_fino_norm = _normalizar(texto_fino)
                comando_fino = _extraer_comando(texto_fino_norm)
                al_detectar_comando(comando_fino if comando_fino else comando)
            else:
                print("Arché: Te escucho...")
                esperando_comando_tras_wake = True
