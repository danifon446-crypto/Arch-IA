"""
interfaz
--------
Ubicacion: Arche/core/interfaz/

La cara de Arché: consola con Rich, ventana grafica y modo TV.
main.py solo llama a manejar(comando); aqui se decide si la frase es suya.
"""

import re
import unicodedata

from . import consola, tema, datos, ventana


def _limpio(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¿?¡!,.;:]", " ", t)
    return " ".join(t.split())


def _msg(texto):
    print(f"Arché: {texto}")


def interpretar(comando):
    c = _limpio(comando)
    if re.match(r"^(cierra|cerrar|quita|oculta)( la)? (interfaz|ventana)( de arche)?$", c):
        return ("cerrar_interfaz", None)
    if re.match(r"^(sal|salir|salte) del modo tv$|^(cierra|quita|apaga) (el )?modo tv$", c):
        return ("salir_modo_tv", None)
    if re.match(r"^(activa|abre|pon|enciende|ver en|muestra en)( el)?( modo)? (tv|television|pantalla grande)( modo)?$|^modo tv$", c):
        return ("modo_tv", None)
    if re.match(r"^(abre|abrir|muestra|mostrar|enciende|activa|lanza)( la| mi)? (interfaz|ventana)( grafica| de arche)?$|^interfaz$", c):
        return ("abrir_interfaz", None)
    if re.match(r"^(panel|paneles|mostrar panel|muestra( el)? panel|panel de arche|dashboard)$", c):
        return ("panel", None)
    if re.match(r"^(panel de estado|muestra( el)? estado visual|estado visual)$", c):
        return ("panel_estado", None)
    if re.match(r"^(panel de aprendizaje|muestra( el)? panel de aprendizaje|progreso visual)$", c):
        return ("panel_aprendizaje", None)
    return None


def manejar(comando):
    """Devuelve (intencion, contenido) si la frase era de la interfaz, o None."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion = cual[0]

    if intencion in ("abrir_interfaz", "modo_tv", "salir_modo_tv"):
        if not ventana.disponible():
            _msg("A este Python le falta Tkinter. En Windows viene incluido; en la Raspberry instala "
                 "'sudo apt install python3-tk'. Mientras tanto uso la consola: dime 'panel'.")
            return (intencion, None)
        if intencion == "salir_modo_tv":
            if ventana.abierta():
                ventana.abrir(tv=False)
                _msg("Salí del modo TV.")
            else:
                _msg("El modo TV no está abierto.")
            return (intencion, None)
        tv = intencion == "modo_tv"
        ventana.abrir(tv=tv)
        _msg("Listo, abrí mi pantalla en modo TV (Esc para salir)." if tv
             else "Listo, abrí mi ventana. Puedes seguir hablándome por aquí.")
    elif intencion == "cerrar_interfaz":
        _msg("Cerré la ventana." if ventana.cerrar() else "La ventana no estaba abierta.")
    elif intencion == "panel":
        consola.panel_completo()
    elif intencion == "panel_estado":
        consola.panel_estado()
    elif intencion == "panel_aprendizaje":
        consola.panel_aprendizaje()
    return cual