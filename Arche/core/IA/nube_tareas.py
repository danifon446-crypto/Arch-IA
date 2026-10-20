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
from datetime import datetime

from core.IA import nube

TAREAS = {
    "estudio": {"defecto": True, "nombre": "estudio y tareas de texto"},
    "examen": {"defecto": True, "nombre": "examen de las redes (ejercicios y verificacion)"},
    "codigo": {"defecto": False, "nombre": "escribir y revisar codigo (autocodificacion)"},
}
PAUSA_POR_LIMITE = 120          # segundos de descanso tras un 429

# Cupo diario PROPIO de cada tarea (pedidos a la nube por dia). None = sin tope.
# El proveedor gratis da ~1.000 pedidos/dia por modelo y el chat y el estudio gastan del mismo
# cupo, asi que el codigo se queda con una parte y deja margen. Se cambia con fijar_cupo()
# o escribiendo "cupo_diario": {"codigo": N} en Database/nube.json.
CUPO_DIARIO_DEFECTO = {"codigo": 600, "examen": 250}
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


def _hoy():
    return datetime.now().strftime("%Y-%m-%d")


def cupo_diario(tarea):
    """Tope de pedidos por dia para la tarea, o None si no tiene."""
    propio = nube._leer_config().get("cupo_diario", {})
    if tarea in propio:
        if propio[tarea] is None:
            return None                      # quitado a proposito: sin tope
        try:
            return max(0, int(propio[tarea]))
        except (TypeError, ValueError):
            pass
    return CUPO_DIARIO_DEFECTO.get(tarea)


def fijar_cupo(tarea, valor):
    """Cambia el cupo diario de una tarea. valor=None lo quita (sin tope)."""
    if tarea not in TAREAS:
        raise ValueError(f"tarea desconocida: {tarea}")
    cfg = nube._leer_config()
    cupos = dict(cfg.get("cupo_diario", {}))
    cupos[tarea] = None if valor is None else max(0, int(valor))
    cfg["cupo_diario"] = cupos
    nube._guardar_config(cfg)


def usadas_hoy(tarea):
    dia = nube._leer_config().get("tareas_dia", {})
    if dia.get("fecha") != _hoy():
        return 0
    try:
        return int(dia.get(tarea, 0))
    except (TypeError, ValueError):
        return 0


def cupo_restante(tarea):
    """Pedidos que le quedan hoy a la tarea, o None si no tiene tope."""
    tope = cupo_diario(tarea)
    if tope is None:
        return None
    return max(0, tope - usadas_hoy(tarea))


def cupo_para_lote(tarea):
    """Cuantos pedidos puede gastar un lote de trabajo (como la autorevision) hoy.

    None = sin tope: la tarea esta en solo-Ollama, o la nube no esta disponible ahora
    (entonces trabaja Ollama, como siempre). Un numero (puede ser 0) = la nube esta
    haciendo el trabajo y ese es el cupo que queda.
    """
    try:
        if not activa(tarea) or not nube.disponible():
            return None
    except Exception:
        return None
    return cupo_restante(tarea)


def lote_en_pausa(tarea):
    """Por que un lote largo debe parar y seguir despues: 'cupo', 'limite' o '' (puede seguir).

    Solo aplica cuando la nube esta haciendo el trabajo. Si la tarea esta en solo-Ollama no
    hay nada que esperar, asi que devuelve ''.
    """
    try:
        if not activa(tarea):
            return ""
    except Exception:
        return ""
    if cupo_restante(tarea) == 0:
        return "cupo"
    if time.time() < _pausa_hasta:
        return "limite"
    return ""


def _contar(tarea, origen):
    cfg = nube._leer_config()
    uso = dict(cfg.get("tareas_uso", {}))
    clave = f"{tarea}_{origen}"
    uso[clave] = int(uso.get(clave, 0)) + 1
    cfg["tareas_uso"] = uso
    if origen == "nube":
        dia = dict(cfg.get("tareas_dia", {}))
        if dia.get("fecha") != _hoy():
            dia = {"fecha": _hoy()}
        dia[tarea] = int(dia.get(tarea, 0)) + 1
        cfg["tareas_dia"] = dia
    nube._guardar_config(cfg)


def intentar(tarea, prompt, max_tokens=400, temperature=0.2, sistema=None):
    """Texto de la nube o None (entonces se usa Ollama). Nunca lanza."""
    global _pausa_hasta, _ultimo_motivo
    try:
        if tarea not in TAREAS or not activa(tarea):
            return None
        if cupo_restante(tarea) == 0:
            _ultimo_motivo = "cupo diario de la tarea agotado"
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
        linea = (f"{d['nombre']}: {'con la nube' if activa(t) else 'solo Ollama'} "
                 f"(nube {uso.get(t + '_nube', 0)} veces, respaldo Ollama por fallo {uso.get(t + '_respaldo', 0)}).")
        tope = cupo_diario(t)
        if activa(t) and tope is not None:
            linea += f" Cupo de hoy: {usadas_hoy(t)} de {tope}."
        lineas.append(linea)
    return lineas