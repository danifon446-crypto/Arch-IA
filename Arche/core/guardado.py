"""
guardado.py
-----------
Ubicacion: Arche/core/guardado.py

Guardar y leer archivos JSON SIN riesgo de perder los datos.

EL PROBLEMA
  Varios módulos guardaban así:   open(archivo, "w") + json.dump(...)
  open(..., "w") primero VACÍA el archivo y después escribe. Si justo en ese
  instante se va la luz, se cierra Arché, o un hilo de fondo lee el archivo,
  queda a medias (dañado). Y al volver a abrir, módulos como configuracion.py
  veían el archivo dañado y lo REEMPLAZABAN por los valores de fábrica:
  perdías tu configuración, recuerdos o programas sin que nadie avisara.

LA SOLUCIÓN
  guardar_json(): escribe en un archivo temporal al lado y, cuando ya está
  completo, lo cambia por el bueno de un solo golpe (os.replace). El archivo
  real siempre está entero: o el viejo o el nuevo, nunca uno a medias.
  Además deja una copia del anterior en "<archivo>.bak".

  leer_json(): si el archivo está dañado NO lo pisa: guarda una copia en
  "<archivo>.danado" para que se pueda revisar y recupera el ".bak".

Uso:
    from core.guardado import guardar_json, leer_json
    datos = leer_json(ruta, defecto={})
    guardar_json(ruta, datos)
"""

import json
import os
import shutil
import threading
import time

_candado = threading.Lock()
_REINTENTOS = 6           # OneDrive / antivirus bloquean el archivo unos instantes


def guardar_json(ruta, datos, indent=4, respaldo=True):
    """Guarda `datos` en `ruta` de forma atómica. Lanza el error solo si de
    ninguna manera se pudo escribir (igual que hacía open/json.dump)."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    texto = json.dumps(datos, indent=indent, ensure_ascii=False)
    temporal = f"{ruta}.{os.getpid()}.{threading.get_ident()}.tmp"
    with _candado:
        ultimo = None
        for intento in range(_REINTENTOS):
            try:
                with open(temporal, "w", encoding="utf-8") as f:
                    f.write(texto)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                if respaldo and os.path.exists(ruta) and os.path.getsize(ruta) > 2:
                    try:
                        shutil.copy2(ruta, ruta + ".bak")
                    except OSError:
                        pass
                os.replace(temporal, ruta)
                return
            except PermissionError as e:
                ultimo = e
                time.sleep(0.3 * (intento + 1))
            except OSError as e:
                ultimo = e
                break
        # último recurso: como se hacía antes (mejor eso que no guardar)
        try:
            if os.path.exists(temporal):
                os.remove(temporal)
        except OSError:
            pass
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(texto)
        except OSError:
            raise ultimo


def _leer(ruta, tipo):
    with open(ruta, "r", encoding="utf-8-sig") as f:
        datos = json.load(f)
    if tipo is not None and not isinstance(datos, tipo):
        raise ValueError(f"se esperaba {tipo.__name__}")
    return datos


def leer_json(ruta, defecto=None, tipo=None, avisar=True):
    """Lee `ruta`. Si no existe -> `defecto`. Si está dañado: lo copia a
    "<ruta>.danado", intenta el ".bak" y si tampoco -> `defecto`.
    NUNCA escribe encima del archivo dañado."""
    if not os.path.exists(ruta):
        return defecto
    try:
        return _leer(ruta, tipo)
    except (OSError, ValueError) as e:
        bloqueado = isinstance(e, PermissionError)
        if bloqueado:                           # bloqueado un instante: reintenta, no está dañado
            for intento in range(_REINTENTOS):
                time.sleep(0.3 * (intento + 1))
                try:
                    return _leer(ruta, tipo)
                except PermissionError:
                    continue
                except (OSError, ValueError):
                    bloqueado = False
                    break
    nombre = os.path.basename(ruta)
    if bloqueado:                               # otro programa lo tiene tomado: no está dañado
        try:
            return _leer(ruta + ".bak", tipo)
        except (OSError, ValueError):
            if avisar:
                print(f"Arché: No pude leer {nombre} (otro programa lo tiene abierto).")
            return defecto
    # está dañado de verdad
    try:
        shutil.copy2(ruta, ruta + ".danado")
    except OSError:
        pass
    try:
        datos = _leer(ruta + ".bak", tipo)
        if avisar:
            print(f"Arché: El archivo {nombre} estaba dañado; recuperé la copia anterior "
                  f"(dejé el dañado como {nombre}.danado).")
        return datos
    except (OSError, ValueError):
        if avisar:
            print(f"Arché: El archivo {nombre} estaba dañado y no había copia; empiezo con lo básico "
                  f"(dejé el dañado como {nombre}.danado por si se puede rescatar).")
        return defecto
