import json
import sys
import traceback
import urllib.request
from functools import wraps
from pathlib import Path

_RAIZ_APP = Path(__file__).resolve().parents[2]
if str(_RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP))

from core.IA.orquestador_autonomo import OrquestadorAutonomo


def rendir_cuentas(archivo: str, error: str, exito: bool):
    estado = "resuelto" if exito else "no resuelto"
    prompt = (
        f"Eres Arché, un asistente virtual empático y cercano. "
        f"Sucedió un problema interno en el archivo '{archivo}' provocado por: '{error}'. "
        f"Intentaste solucionarlo automáticamente y el resultado fue {estado}.\n\n"
        f"Explícale al usuario qué ocurrió de manera muy natural, conversacional y breve.\n"
        f"REGLAS OBLIGATORIAS:\n"
        f"1. NO muestres código Python, fragmentos de funciones ni bloques ```.\n"
        f"2. Usa un tono de voz tranquilo y directo, como un colega contando qué pasó.\n"
        f"3. No des detalles técnicos innecesarios."
    )

    datos = json.dumps({
        "model": "arche-lora",
        "prompt": prompt,
        "stream": False
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=datos,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            respuesta = json.loads(resp.read().decode("utf-8")).get("response", "")
            print(f"\n🗣️ Arché: {respuesta.strip()}\n")
    except Exception:
        if exito:
            print(f"\n🗣️ Arché: Oye, noté un pequeño fallo en {archivo}, pero ya me encargué de solucionarlo internamente. Todo sigue marchando bien.")
        else:
            print(f"\n🗣️ Arché: Tuve un inconveniente técnico en {archivo} y no logré corregirlo automáticamente esta vez.")


def capturar_y_reparar(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            ultimo_marco = tb[-1]
            archivo_fallido = Path(ultimo_marco.filename).name
            linea_error = ultimo_marco.lineno
            tipo_error = type(e).__name__
            mensaje_error = str(e)

            meta_autonoma = (
                f"El archivo {archivo_fallido} falló en la línea {linea_error} "
                f"con el error {tipo_error}: '{mensaje_error}'. "
                f"Corrige el fallo para que el módulo vuelva a funcionar correctamente."
            )

            print(f"\n🔍 [AUTO-DIAGNÓSTICO] Error detectado en {archivo_fallido}:{linea_error}. Iniciando autoreparación...")

            orquestador = OrquestadorAutonomo()
            exito = orquestador.ejecutar_meta(meta_autonoma)

            rendir_cuentas(archivo_fallido, mensaje_error, exito)

            return None
    return wrapper
