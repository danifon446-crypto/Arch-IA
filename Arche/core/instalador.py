"""
instalador.py
-------------
Verifica que las librerías externas que necesita Arché estén
instaladas y, si falta alguna, las instala solas con pip la primera
vez que se corre el programa (o cada vez que falte algo nuevo).

Así quien use Arché no tiene que saber de antemano qué instalar a
mano: main.py llama a verificar_e_instalar() ANTES de cualquier otro
import que dependa de estas librerías, y si algo falta, se instala
en el momento.

Nota: la primera vez puede tardar varios minutos (sobre todo
sentence-transformers y faster-whisper, que son pesados). Las
siguientes veces, si ya está todo instalado, esto no hace nada y
arranca al instante.
"""

import subprocess
import sys
import importlib

# nombre del import -> nombre real del paquete en pip (no siempre coinciden)
DEPENDENCIAS = {
    "ollama": "ollama",                              # conversar/comprender con el modelo local
    "ddgs": "ddgs",                                   # búsqueda de sitios (navegador.py)
    "numpy": "numpy",                                 # embeddings, clasificador, voz
    "scipy": "scipy",                                 # resampleo de audio (voz.py)
    "sklearn": "scikit-learn",                        # red neuronal (clasificador.py)
    "sentence_transformers": "sentence-transformers",  # embeddings semánticos
    "faster_whisper": "faster-whisper",               # transcripción de voz
    "sounddevice": "sounddevice",                     # captura de micrófono
}


def _esta_instalado(nombre_import):
    try:
        importlib.import_module(nombre_import)
        return True
    except Exception:
        # No solo ImportError: algunas librerías (ej. sounddevice) fallan
        # con otro tipo de error si falta una dependencia del sistema
        # operativo, no solo si falta el paquete de pip en sí.
        return False


def verificar_e_instalar(paquetes=None):
    """
    Revisa cada dependencia y, si falta, la instala con pip en el
    mismo intérprete de Python que está corriendo Arché.

    paquetes: opcional, lista de nombres de import a revisar (por
    defecto revisa todas las de DEPENDENCIAS). Útil si un módulo
    puntual solo necesita asegurar una o dos librerías.
    """
    objetivo = paquetes or list(DEPENDENCIAS.keys())

    faltantes = [
        (nombre_import, DEPENDENCIAS[nombre_import])
        for nombre_import in objetivo
        if nombre_import in DEPENDENCIAS and not _esta_instalado(nombre_import)
    ]

    if not faltantes:
        return

    print("=" * 60)
    print("Arché: Me faltan algunas librerías para funcionar completo.")
    print(f"Arché: Voy a instalar {len(faltantes)}: "
          f"{', '.join(p for _, p in faltantes)}")
    print("Arché: Puede tardar varios minutos la primera vez, según tu conexión.")
    print("=" * 60)

    fallidas = []

    for nombre_import, paquete in faltantes:
        print(f"\nArché: Instalando {paquete}...")
        resultado = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", paquete],
            capture_output=True,
            text=True,
        )

        # En algunos sistemas (sobre todo Linux con Python "administrado
        # externamente") pip rechaza instalar directo. Windows normalmente
        # no tiene este problema, pero por si acaso reintentamos una vez
        # con --break-system-packages antes de darlo por fallido.
        if resultado.returncode != 0 and "externally-managed-environment" in resultado.stderr:
            resultado = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--break-system-packages", paquete],
                capture_output=True,
                text=True,
            )

        if resultado.returncode != 0 or not _esta_instalado(nombre_import):
            fallidas.append((paquete, resultado.stderr.strip()[-500:]))
            print(f"Arché: No pude instalar {paquete} automáticamente.")
        else:
            print(f"Arché: {paquete} listo.")

    print("\n" + "=" * 60)
    if fallidas:
        print("Arché: Terminé, pero algunas fallaron. Instálalas a mano:")
        for paquete, error in fallidas:
            print(f"  pip install {paquete}")
            if error:
                print(f"    (motivo: {error})")
        print("Arché: Las funciones que dependen de esas librerías no van a estar disponibles hasta entonces.")
    else:
        print("Arché: Todas las dependencias quedaron instaladas.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    verificar_e_instalar()