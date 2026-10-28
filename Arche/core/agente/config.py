"""
config.py
---------
Ubicacion: Arche/core/agente/config.py

Donde guarda sus cosas el agente y su configuracion (todo en Database/agente/):

  config.json         entorno por defecto, datos de conexion a Minecraft, limites
  modelos.json        que modelo usa cada rol (planificador, decisor, ...)
  experiencias.jsonl  la memoria de experiencias

Para pruebas se puede cambiar la carpeta con la variable ARCHE_AGENTE_DIR.
"""

from __future__ import annotations

import json
import os
import threading

try:
    from core.rutas import DATABASE
except Exception:  # fuera de Arché (pruebas sueltas)
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Database")


def carpeta() -> str:
    ruta = os.environ.get("ARCHE_AGENTE_DIR") or os.path.join(DATABASE, "agente")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def ruta(nombre: str) -> str:
    return os.path.join(carpeta(), nombre)


POR_DEFECTO = {
    "entorno": "minecraft",
    "minecraft": {
        "host": "localhost",
        "puerto": 25565,
        "usuario": "Arche",
        "version": "",            # vacio = que Mineflayer la detecte sola
        "auth": "offline",        # mundo abierto a LAN o servidor con online-mode=false
        "puerto_puente": 3921,
    },
    "limites": {
        "max_pasos": 60,              # acciones por objetivo
        "max_segundos": 900,          # tiempo total por objetivo
        "max_fallos_seguidos": 5,
        "max_repeticiones": 3,        # misma accion igual y sin cambios en el entorno
        "max_replanificaciones": 3,
        "permitir_peligrosas": False,
    },
}

_lock = threading.Lock()


def _mezclar(base: dict, extra: dict) -> dict:
    salida = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(salida.get(k), dict):
            salida[k] = _mezclar(salida[k], v)
        else:
            salida[k] = v
    return salida


def leer_json(nombre: str, defecto):
    try:
        with open(ruta(nombre), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def guardar_json(nombre: str, datos) -> None:
    destino = ruta(nombre)
    tmp = destino + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(tmp, destino)


def cargar() -> dict:
    return _mezclar(POR_DEFECTO, leer_json("config.json", {}))


def guardar(cfg: dict) -> None:
    guardar_json("config.json", cfg)


def fijar(clave: str, valor) -> dict:
    """fijar("minecraft.host", "192.168.1.5") -> guarda y devuelve la config nueva."""
    cfg = cargar()
    destino = cfg
    partes = clave.split(".")
    for p in partes[:-1]:
        destino = destino.setdefault(p, {})
    destino[partes[-1]] = valor
    guardar(cfg)
    return cfg
