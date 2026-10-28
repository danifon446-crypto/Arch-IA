"""
memoria_experiencias.py
-----------------------
Ubicacion: Arche/core/agente/memoria_experiencias.py

La memoria de experiencias a largo plazo del agente. Cada vez que termina un
subobjetivo (bien o mal) guarda una experiencia:

    que intentaba, en que entorno, que paso, que acciones funcionaron,
    que error cometio y una LECCION corta y reutilizable.

Antes de planificar o decidir, el agente busca las experiencias parecidas a lo
que va a hacer y las lee. Cada leccion lleva la cuenta de cuantas veces se
uso y cuantas de esas veces el subobjetivo salio bien: las que sirven suben,
las que no, bajan. Asi mejora con el tiempo sin que nadie reprograme nada.

No usa librerias externas: la busqueda es por palabras en comun (sin tildes,
sin palabras vacias). Se guarda en Database/agente/experiencias.jsonl.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import uuid

from core.agente import config

MAX_EXPERIENCIAS = 2000

_VACIAS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a", "en", "y", "o", "u", "que",
    "con", "por", "para", "se", "su", "sus", "lo", "es", "no", "si", "mi", "me", "te", "ya", "hay", "como",
    "the", "of", "to", "and", "in", "on", "is", "it", "un", "mas", "muy", "este", "esta", "esto",
}


def _sin_tildes(texto: str) -> str:
    d = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def tokens(texto: str) -> set[str]:
    salida = set()
    for t in re.split(r"[^a-z0-9]+", _sin_tildes(texto)):
        if not t or t in _VACIAS or len(t) < 2:
            continue
        if len(t) > 4 and t.endswith("s"):
            t = t[:-1]
        salida.add(t)
    return salida


class MemoriaExperiencias:
    def __init__(self, archivo: str | None = None):
        self.archivo = archivo or config.ruta("experiencias.jsonl")
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self._cargar()

    # --- disco -------------------------------------------------------
    def _cargar(self):
        self._items = []
        try:
            with open(self.archivo, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea:
                        try:
                            self._items.append(json.loads(linea))
                        except ValueError:
                            continue
        except OSError:
            pass

    def _escribir(self):
        tmp = self.archivo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for it in self._items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        os.replace(tmp, self.archivo)

    # --- escribir ----------------------------------------------------
    def guardar(self, entorno: str, objetivo: str, subobjetivo: str, resultado: str, pasos: int,
                acciones_clave: list[str], error: str, leccion: str, etiquetas=None) -> dict | None:
        """resultado: 'exito', 'fracaso' o 'parcial'. Sin leccion no se guarda nada."""
        leccion = (leccion or "").strip()
        if not leccion:
            return None
        with self._lock:
            clave = _sin_tildes(leccion)
            for it in self._items:
                if it.get("entorno") == entorno and _sin_tildes(it.get("leccion", "")) == clave:
                    it["repeticiones"] = it.get("repeticiones", 1) + 1
                    it["ts"] = time.time()
                    self._escribir()
                    return it
            exp = {
                "id": uuid.uuid4().hex[:10], "ts": time.time(), "entorno": entorno,
                "objetivo": objetivo, "subobjetivo": subobjetivo, "resultado": resultado,
                "pasos": pasos, "acciones_clave": acciones_clave[:10], "error": (error or "")[:300],
                "leccion": leccion[:400], "etiquetas": list(etiquetas or []),
                "usos": 0, "aciertos": 0, "repeticiones": 1,
            }
            self._items.append(exp)
            if len(self._items) > MAX_EXPERIENCIAS:
                self._items.sort(key=lambda e: (self._utilidad(e), e.get("ts", 0)))
                self._items = self._items[len(self._items) - MAX_EXPERIENCIAS:]
            self._escribir()
            return exp

    def marcar_uso(self, ids, exito: bool):
        """Despues de usar lecciones: anota si el subobjetivo salio bien con ellas a la vista."""
        if not ids:
            return
        with self._lock:
            cambiado = False
            for it in self._items:
                if it["id"] in ids:
                    it["usos"] = it.get("usos", 0) + 1
                    if exito:
                        it["aciertos"] = it.get("aciertos", 0) + 1
                    cambiado = True
            if cambiado:
                self._escribir()

    def olvidar(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items = []
            self._escribir()
            return n

    # --- leer --------------------------------------------------------
    @staticmethod
    def _utilidad(e: dict) -> float:
        usos, aciertos = e.get("usos", 0), e.get("aciertos", 0)
        return (aciertos + 1) / (usos + 2) - 0.5          # -0.5 .. +0.5

    def buscar(self, entorno: str, texto: str, k: int = 4, minimo: float = 0.08) -> list[dict]:
        consulta = tokens(texto)
        if not consulta:
            return []
        puntuadas = []
        with self._lock:
            for e in self._items:
                if e.get("entorno") != entorno:
                    continue
                doc = tokens(" ".join([e.get("subobjetivo", ""), e.get("objetivo", ""),
                                       e.get("leccion", ""), " ".join(e.get("etiquetas", []))]))
                if not doc:
                    continue
                comun = len(consulta & doc)
                if not comun:
                    continue
                jac = comun / len(consulta | doc)
                puntaje = jac * (1 + 0.6 * self._utilidad(e)) + 0.02 * min(e.get("repeticiones", 1), 5)
                if puntaje >= minimo:
                    puntuadas.append((puntaje, e))
        puntuadas.sort(key=lambda p: p[0], reverse=True)
        return [e for _, e in puntuadas[:k]]

    @staticmethod
    def formatear(experiencias: list[dict]) -> str:
        if not experiencias:
            return ""
        lineas = []
        for e in experiencias:
            marca = {"exito": "funcionó", "fracaso": "falló", "parcial": "a medias"}.get(e.get("resultado"), "")
            lineas.append(f"- ({marca}) {e['leccion']}")
        return "\n".join(lineas)

    def total(self, entorno: str | None = None) -> int:
        with self._lock:
            return sum(1 for e in self._items if entorno in (None, e.get("entorno")))

    def resumen(self, entorno: str | None = None, ultimas: int = 6) -> str:
        with self._lock:
            items = [e for e in self._items if entorno in (None, e.get("entorno"))]
        if not items:
            return "Todavía no tengo experiencias guardadas."
        ex = sum(1 for e in items if e.get("resultado") == "exito")
        fr = sum(1 for e in items if e.get("resultado") == "fracaso")
        lineas = [f"{len(items)} experiencias ({ex} de éxitos, {fr} de fracasos). Las más recientes:"]
        for e in sorted(items, key=lambda e: e.get("ts", 0), reverse=True)[:ultimas]:
            lineas.append(f"  - [{e.get('resultado')}] {e['leccion']}")
        return "\n".join(lineas)
