"""
comandos.py
-----------
Ubicacion: Arche/core/seguridad/comandos.py

Ordenes de seguridad que se le pueden decir a Arché en el chat. Son SOLO DE
LECTURA a proposito: aprobar cambios ("sellar") no se puede pedir por chat
(ni desde el celular ni por WhatsApp), solo corriendo en el PC:

    python seguridad.py sellar

Asi, aunque alguien tome control del chat, no puede "bendecir" codigo malo.

  estado de seguridad / revisa la seguridad   -> integridad, bitacora y cifrado
  bitacora de seguridad / eventos de seguridad -> ultimos eventos registrados
"""

import re
import unicodedata

from core.seguridad import cifrado, guardian

_ESTADO = re.compile(r"^(estado de (la )?seguridad|revisa (la |tu )?seguridad|como esta (la |tu )?seguridad|"
                     r"seguridad|escanea(te)? (tu|el) codigo|verifica (tu|el) codigo)\??$")
_BITACORA = re.compile(r"^(bitacora|eventos|registro|historial) de seguridad$|^que paso en seguridad\??$")

_NOMBRES_METODO = {
    "dpapi": "DPAPI de Windows (atadas a tu usuario)",
    "fernet": "Fernet / AES (llave local)",
    "ninguno": "SIN cifrado (instala 'cryptography')",
}


def _normalizar(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower().strip())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def estado():
    r = guardian.verificar()
    ok_bit, msg_bit = guardian.verificar_bitacora()
    lineas = [
        "Arché: 🔒 Estado de seguridad",
        "  Código:    " + guardian.resumen_texto(r),
        "  Bitácora:  " + ("✔ " if ok_bit else "⚠ ") + msg_bit,
        "  Claves:    cifradas con " + _NOMBRES_METODO.get(cifrado.metodo(), cifrado.metodo()),
    ]
    return "\n".join(lineas)


def bitacora(n=12):
    eventos = guardian.ultimos_eventos(n)
    if not eventos:
        return "Arché: La bitácora de seguridad está vacía."
    lineas = ["Arché: Últimos eventos de seguridad:"]
    for e in eventos:
        detalle = ", ".join(f"{k}={v}" for k, v in (e.get("detalle") or {}).items() if k != "texto")
        lineas.append(f"  {e.get('t', '')}  {e.get('evento', '')}" + (f"  ({detalle[:90]})" if detalle else ""))
    return "\n".join(lineas)


def manejar(texto):
    """Devuelve True si la orden era de seguridad (y ya la respondio)."""
    t = _normalizar(texto)
    if _ESTADO.match(t):
        print(estado())
        return True
    if _BITACORA.match(t):
        print(bitacora())
        return True
    return False
