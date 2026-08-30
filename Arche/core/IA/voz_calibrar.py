"""
voz_calibrar.py
----------------
Corre esto SOLO (no como parte de Arché) para encontrar un buen valor de
UMBRAL_ENERGIA para tu micrófono.

Uso:
    py voz_calibrar.py

Vas a ver una barra con el nivel de energía en tiempo real. Fíjate:
  - Qué valor marca cuando estás EN SILENCIO (ruido de fondo normal).
  - Qué valor marca cuando HABLAS normal.

UMBRAL_ENERGIA en voz.py debería quedar en un punto intermedio: bastante
arriba del nivel de silencio, bastante abajo del nivel de tu voz.
"""

import numpy as np
import sounddevice as sd

SAMPLE_RATE = None  # se detecta automáticamente según el dispositivo
FRAME_MS = 30

# Índice del dispositivo de entrada a usar. Corre
# `py -c "import sounddevice as sd; print(sd.query_devices())"` para ver
# los índices disponibles y ajusta este valor al de tu micrófono real.
DISPOSITIVO = 15  # "Varios micrófonos (Realtek HD Audio Mic Array input), Windows WDM-KS"


def calcular_rms(frame_int16_bytes):
    audio = np.frombuffer(frame_int16_bytes, dtype=np.int16).astype(np.float32)
    return np.sqrt(np.mean(audio ** 2)) if len(audio) else 0.0


def main():
    global SAMPLE_RATE

    info = sd.query_devices(DISPOSITIVO)
    SAMPLE_RATE = int(info["default_samplerate"])
    frame_samples = int(SAMPLE_RATE * FRAME_MS / 1000)

    print(f"Usando dispositivo #{DISPOSITIVO}: {info['name']}")
    print(f"Tasa de muestreo nativa detectada: {SAMPLE_RATE} Hz")
    print("Calibrando... habla normal, luego quédate en silencio. Ctrl+C para salir.\n")

    contador = {"n": 0}

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[status: {status}]")
        rms = calcular_rms(bytes(indata))
        contador["n"] += 1
        # Solo 1 de cada 15 frames (~cada 0.45s) para no inundar la consola
        if contador["n"] % 15 == 0:
            barra = "█" * int(min(rms / 20, 60))
            print(f"Energía: {rms:8.1f} {barra}")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=frame_samples,
        dtype="int16",
        channels=1,
        device=DISPOSITIVO,
        callback=callback,
    ):
        try:
            while True:
                sd.sleep(100)
        except KeyboardInterrupt:
            print("\n\nListo. Elige un UMBRAL_ENERGIA entre el nivel de silencio y el de tu voz.")


if __name__ == "__main__":
    main()