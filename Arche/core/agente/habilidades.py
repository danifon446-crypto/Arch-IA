"""
habilidades.py
--------------
Ubicacion: Arche/core/agente/habilidades.py

Cuando el agente resuelve un subobjetivo sin fallar, guarda la secuencia exacta de
acciones. La proxima vez que le toque el MISMO subobjetivo, la repite directo, sin
pedirle nada a ningun modelo. Si la habilidad falla, baja de puntaje y a la segunda
falla seguida se descarta, y el agente vuelve a razonar con el modelo.

Solo se guardan acciones que no dependen de un sitio concreto (nada de coordenadas),
porque repetirlas en otro lugar no tendria sentido. Se guarda en habilidades.jsonl.
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
from core.agente.tipos import Accion

# acciones que se pueden repetir en cualquier sitio
REPETIBLES = {"recolectar", "craftear", "colocar", "equipar", "comer", "dormir", "subir_a_superficie",
              "alejarse", "ir_a_bloque", "buscar_bloque", "esperar"}
MAX_ACCIONES = 6
MAX_HABILIDADES = 500
FALLOS_PARA_DESCARTAR = 2


def _clave(texto: str) -> str:
    d = unicodedata.normalize("NFD", str(texto).lower())
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", d).strip()


class Habilidades:
    def __init__(self, archivo: str | None = None):
        self.archivo = archivo or config.ruta("habilidades.jsonl")
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- disco
    def _leer(self) -> list[dict]:
        if not os.path.exists(self.archivo):
            return []
        salida = []
        with open(self.archivo, encoding="utf-8") as f:
            for linea in f:
                try:
                    salida.append(json.loads(linea))
                except ValueError:
                    continue
        return salida

    def _escribir(self, lista: list[dict]) -> None:
        tmp = self.archivo + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for h in lista[-MAX_HABILIDADES:]:
                f.write(json.dumps(h, ensure_ascii=False) + "\n")
        os.replace(tmp, self.archivo)

    # ---------------------------------------------------------------- uso
    @staticmethod
    def servible(acciones: list[Accion]) -> bool:
        return 0 < len(acciones) <= MAX_ACCIONES and all(a.nombre in REPETIBLES for a in acciones)

    def buscar(self, entorno: str, descripcion: str) -> dict | None:
        k = _clave(descripcion)
        with self._lock:
            mejores = [h for h in self._leer() if h["entorno"] == entorno and h["clave"] == k
                       and h.get("fallos_seguidos", 0) < FALLOS_PARA_DESCARTAR]
        if not mejores:
            return None
        return max(mejores, key=lambda h: (h.get("aciertos", 0) - h.get("fallos", 0), h.get("t", 0)))

    @staticmethod
    def acciones(h: dict) -> list[Accion]:
        return [Accion(a["nombre"], dict(a.get("args") or {}), "habilidad guardada") for a in h["acciones"]]

    def guardar(self, entorno: str, descripcion: str, acciones: list[Accion]) -> bool:
        if not self.servible(acciones):
            return False
        k = _clave(descripcion)
        nuevas = [{"nombre": a.nombre, "args": a.args} for a in acciones]
        with self._lock:
            lista = self._leer()
            for h in lista:
                if h["entorno"] == entorno and h["clave"] == k:
                    if h["acciones"] != nuevas:
                        h["acciones"], h["fallos_seguidos"] = nuevas, 0     # una receta nueva que SI funciono
                    h["aciertos"] = h.get("aciertos", 0) + 1
                    h["t"] = time.time()
                    self._escribir(lista)
                    return True
            lista.append({"id": uuid.uuid4().hex[:10], "entorno": entorno, "clave": k, "descripcion": descripcion,
                          "acciones": nuevas, "aciertos": 1, "fallos": 0, "fallos_seguidos": 0, "t": time.time()})
            self._escribir(lista)
        return True

    def marcar(self, id_: str, exito: bool) -> None:
        with self._lock:
            lista = self._leer()
            for h in lista:
                if h["id"] == id_:
                    if exito:
                        h["aciertos"] = h.get("aciertos", 0) + 1
                        h["fallos_seguidos"] = 0
                    else:
                        h["fallos"] = h.get("fallos", 0) + 1
                        h["fallos_seguidos"] = h.get("fallos_seguidos", 0) + 1
                    break
            self._escribir(lista)

    def total(self) -> int:
        with self._lock:
            return len(self._leer())

    def resumen(self) -> str:
        with self._lock:
            lista = self._leer()
        if not lista:
            return "Todavía no tengo habilidades guardadas. Se guardan solas cuando resuelvo algo sin fallar."
        lista.sort(key=lambda h: h.get("aciertos", 0), reverse=True)
        lineas = [f"Habilidades guardadas: {len(lista)}"]
        for h in lista[:12]:
            pasos = " → ".join(Accion(a["nombre"], a.get("args") or {}).corta() for a in h["acciones"])
            lineas.append(f"- «{h['descripcion']}» ({h.get('aciertos', 0)} bien, {h.get('fallos', 0)} mal): {pasos}")
        return "\n".join(lineas)

    def olvidar(self) -> None:
        with self._lock:
            if os.path.exists(self.archivo):
                os.remove(self.archivo)
