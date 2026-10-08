"""
nube_tareas.py
--------------
Ubicacion: Arche/core/IA/nube_tareas.py

Deja que la nube ayude tambien en el RESTO de lo que antes hacia solo Ollama,
tarea por tarea y con Ollama siempre de respaldo:

  * "estudio": las tareas puntuales de texto (modo estudio, ejercicios,
    changelog...). Viene ENCENDIDA cuando la nube esta conectada.
  * "codigo": escribir/revisar codigo para la autocodificacion y la
    autorevision. Viene APAGADA: manda fragmentos de tu codigo a internet y
    gasta mucho cupo gratis. Se prende con 'usa la nube para programar'.

Lo que NO cambia: todas las compuertas de seguridad de la autocodificacion
(pruebas, verificacion, copia de respaldo, confirmacion) siguen igual, porque
este modulo solo reemplaza QUIEN escribe el texto, no que se hace con el.

intentar() devuelve el texto de la nube o None; si es None el llamador sigue
con Ollama como siempre. Si la nube dice "limite" (429) descansa un rato para
que un bucle de autorevision no se coma el cupo del dia.
"""

import time

from core.IA import nube

TAREAS = {
    "estudio": {"defecto": True, "nombre": "estudio y tareas de texto"},
    "codigo": {"defecto": False, "nombre": "escribir y revisar codigo (autocodificacion)"},
}
PAUSA_POR_LIMITE = 120          # segundos de descanso tras un 429
_pausa_hasta = 0.0
_ultimo_motivo = ""


def activa(tarea):
    datos = nube._leer_config().get("tareas", {})
    if tarea in datos:
        return bool(datos[tarea])
    return TAREAS[tarea]["defecto"]


def fijar(tarea, valor):
    if tarea not in TAREAS:
        raise ValueError(f"tarea desconocida: {tarea}")
    cfg = nube._leer_config()
    tareas = dict(cfg.get("tareas", {}))
    tareas[tarea] = bool(valor)
    cfg["tareas"] = tareas
    nube._guardar_config(cfg)


def _contar(tarea, origen):
    cfg = nube._leer_config()
    uso = dict(cfg.get("tareas_uso", {}))
    clave = f"{tarea}_{origen}"
    uso[clave] = int(uso.get(clave, 0)) + 1
    cfg["tareas_uso"] = uso
    nube._guardar_config(cfg)


def intentar(tarea, prompt, max_tokens=400, temperature=0.2, sistema=None):
    """Texto de la nube o None (entonces se usa Ollama). Nunca lanza."""
    global _pausa_hasta, _ultimo_motivo
    try:
        if tarea not in TAREAS or not activa(tarea):
            return None
        if time.time() < _pausa_hasta or not nube.disponible():
            return None
        texto = nube.responder([{"role": "user", "content": prompt}], sistema=sistema,
                               max_tokens=max_tokens, temperature=temperature)
        _contar(tarea, "nube")
        _ultimo_motivo = ""
        return texto
    except nube.ErrorNube as e:
        _ultimo_motivo = str(e)
        if e.codigo == 429:
            _pausa_hasta = time.time() + PAUSA_POR_LIMITE
        try:
            _contar(tarea, "respaldo")
        except Exception:
            pass
        return None
    except Exception as e:
        _ultimo_motivo = str(e)
        return None


def resumen_texto():
    uso = nube._leer_config().get("tareas_uso", {})
    lineas = []
    for t, d in TAREAS.items():
        lineas.append(f"{d['nombre']}: {'con la nube' if activa(t) else 'solo Ollama'} "
                      f"(nube {uso.get(t + '_nube', 0)} veces, respaldo Ollama por fallo {uso.get(t + '_respaldo', 0)}).")
    return lineas