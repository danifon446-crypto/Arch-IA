"""
seguridad.py
------------
Ubicacion: Arche/seguridad.py

Panel de seguridad de Arché para la terminal del PC. Algunas cosas (como
aprobar cambios de codigo) SOLO se pueden hacer desde aqui, a proposito: asi
nadie puede hacerlas por el chat, el celular o WhatsApp.

    python seguridad.py              -> estado general
    python seguridad.py sellar       -> aprobar el codigo tal como esta ahora
    python seguridad.py verificar    -> que archivos cambiaron desde el ultimo sellado
    python seguridad.py bitacora     -> ultimos eventos de seguridad
    python seguridad.py cifrar       -> cifrar YA las claves viejas que esten en texto plano
    python seguridad.py nuevo-pin    -> generar un PIN nuevo para el control desde el celular
"""

import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from core.rutas import DATABASE  # noqa: E402
from core.seguridad import cifrado, comandos, guardian  # noqa: E402


def cmd_estado():
    print(comandos.estado())


def cmd_verificar():
    r = guardian.verificar()
    print(guardian.resumen_texto(r))
    for clave in ("cambiados", "nuevos", "borrados"):
        for rel in r[clave]:
            print(f"   [{clave[:-1]}] {rel}")
    return 1 if guardian.hay_alerta(r) else 0


def cmd_sellar():
    r = guardian.verificar()
    if r["sellado"]:
        if not r["firma_valida"]:
            print("⚠ El registro de integridad tiene una firma que NO es de Arché.")
            print("  Antes de sellar, pasa Windows Defender (escaneo completo) y revisa los archivos.")
        cambios = r["cambiados"] + r["nuevos"] + r["borrados"]
        if not cambios and r["firma_valida"]:
            print("No hay nada que sellar: el código está igual que en el último sellado.")
            return 0
        print("Vas a aprobar estos cambios como tuyos:")
        for clave in ("cambiados", "nuevos", "borrados"):
            for rel in r[clave]:
                print(f"   [{clave[:-1]}] {rel}")
    respuesta = input("\n¿Los hiciste tú (o los aprobaste) y quieres sellar? (escribe 'si'): ").strip().lower()
    if respuesta not in ("si", "sí"):
        print("Cancelado. No sellé nada.")
        return 1
    n = guardian.sellar("aprobado por David en la terminal")
    print(f"Listo: sellé {n} archivos. Desde ahora te aviso si alguno cambia sin pasar por mí.")
    return 0


def cmd_bitacora():
    ok, msg = guardian.verificar_bitacora()
    print(("✔ " if ok else "⚠ ") + msg)
    print(comandos.bitacora(25))
    return 0 if ok else 1


def cmd_cifrar():
    if cifrado.metodo() == "ninguno":
        print("No hay cifrado disponible en este equipo. Instala:  pip install cryptography")
        return 1
    hechos = []
    if os.path.isdir(DATABASE):
        for nombre in sorted(os.listdir(DATABASE)):
            if nombre.startswith("nube_clave") and nombre.endswith(".txt"):
                ruta = os.path.join(DATABASE, nombre)
                with open(ruta, "r", encoding="utf-8") as f:
                    plano = not cifrado.esta_cifrado(f.read().strip())
                cifrado.leer_secreto(ruta, migrar=True)
                if plano:
                    hechos.append(nombre)
    try:
        from core import whatsapp
        if os.path.exists(whatsapp.ARCHIVO):
            with open(whatsapp.ARCHIVO, "r", encoding="utf-8") as f:
                antes = f.read()
            whatsapp._cargar()          # migra sola si habia tokens en texto plano
            with open(whatsapp.ARCHIVO, "r", encoding="utf-8") as f:
                if f.read() != antes:
                    hechos.append("whatsapp.json")
    except Exception as e:
        print(f"(No pude revisar WhatsApp: {e})")
    if hechos:
        print("Cifré: " + ", ".join(hechos))
        guardian.auditar("secretos_cifrados", archivos=hechos)
    else:
        print("Todo lo que encontré ya estaba cifrado (o no hay claves guardadas).")
    print("Método: " + cifrado.metodo())
    return 0


def cmd_nuevo_pin():
    from core.interfaz import ajustes, remoto
    pin = remoto.nuevo_pin()
    guardian.auditar("pin_celular_cambiado")
    print(f"PIN nuevo para el celular: {pin}")
    print("El anterior ya no sirve. Si el control remoto estaba encendido, reinicia Arché.")
    if not ajustes.obtener("celular"):
        print("(El control desde el celular está apagado.)")
    return 0


COMANDOS = {
    "estado": cmd_estado, "sellar": cmd_sellar, "verificar": cmd_verificar,
    "bitacora": cmd_bitacora, "cifrar": cmd_cifrar, "nuevo-pin": cmd_nuevo_pin,
}

if __name__ == "__main__":
    orden = (sys.argv[1] if len(sys.argv) > 1 else "estado").lower()
    funcion = COMANDOS.get(orden)
    if funcion is None:
        print(__doc__)
        sys.exit(2)
    sys.exit(funcion() or 0)
