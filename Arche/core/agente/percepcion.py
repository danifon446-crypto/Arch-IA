"""
percepcion.py
-------------
Ubicacion: Arche/core/agente/percepcion.py

Como el agente "ve" el entorno. Pide la observacion al entorno y, si trae una
imagen (captura de pantalla, camara) y hay un modelo de vision disponible, la
convierte en una descripcion en texto que se suma a la observacion. Asi el
decisor (que puede ser un modelo que solo lee texto) tambien se entera de lo
que se ve.

  - Si no hay modelo de vision, sigue funcionando solo con los datos del entorno.
  - Si la imagen no cambio desde la ultima vez, reutiliza la descripcion (no
    gasta otra llamada al modelo).

capturar_pantalla() es una ayuda para entornos que miran la pantalla del PC.
"""

from __future__ import annotations

import hashlib
import io
import time

from core.agente.modelos import ErrorModelo
from core.agente.tipos import Observacion

PROMPT_VISION = (
    "Eres los ojos de un agente que juega o usa un programa. Describe en español, en 4 a 6 frases cortas y "
    "concretas, lo que se ve en la imagen: dónde está el personaje o el cursor, qué objetos, enemigos o "
    "peligros hay cerca (lava, vacío, monstruos, ventanas de error), qué indican las barras, el inventario "
    "o los textos visibles. No inventes lo que no se vea. {contexto}"
)


def capturar_pantalla(max_ancho: int = 1024, calidad: int = 70) -> bytes | None:
    """Foto de la pantalla en JPEG, o None si no se puede (falta Pillow o no hay pantalla)."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab().convert("RGB")
        if img.width > max_ancho:
            alto = int(img.height * max_ancho / img.width)
            img = img.resize((max_ancho, alto))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=calidad)
        return buf.getvalue()
    except Exception:
        return None


class Percepcion:
    def __init__(self, entorno, router, usar_vision: bool = True):
        self.entorno = entorno
        self.router = router
        self.usar_vision = usar_vision
        self._vision = (0.0, False)
        self._ultima_huella = None
        self._ultima_descripcion = ""
        self.aviso_vision = ""

    def _hay_vision(self) -> bool:
        ts, valor = self._vision
        if time.time() - ts < 60:
            return valor
        try:
            valor = bool(self.router.hay_vision())
        except Exception:
            valor = False
        self._vision = (time.time(), valor)
        return valor

    def observar(self) -> Observacion:
        con_imagen = self.usar_vision and self._hay_vision()
        obs = self.entorno.observar(con_imagen=con_imagen)
        if obs.imagen and con_imagen:
            obs.descripcion_visual = self._describir(obs)
        return obs

    def _describir(self, obs: Observacion) -> str:
        huella = hashlib.md5(obs.imagen).hexdigest()
        if huella == self._ultima_huella:
            return self._ultima_descripcion
        contexto = f"Contexto: {obs.texto[:300]}" if obs.texto else ""
        try:
            texto = self.router.responder(
                "vision", [{"role": "user", "content": PROMPT_VISION.format(contexto=contexto)}],
                imagenes=[obs.imagen], max_tokens=300)
        except ErrorModelo as e:
            self.aviso_vision = f"visión no disponible ({e})"
            return ""
        self._ultima_huella, self._ultima_descripcion = huella, texto
        return texto

    @staticmethod
    def texto_para_modelo(obs: Observacion, max_chars: int = 2500) -> str:
        texto = obs.texto
        if obs.descripcion_visual:
            texto += "\n\nLO QUE SE VE EN LA IMAGEN (modelo de visión):\n" + obs.descripcion_visual
        if len(texto) > max_chars:
            texto = texto[:max_chars] + "\n[...recortado]"
        return texto
