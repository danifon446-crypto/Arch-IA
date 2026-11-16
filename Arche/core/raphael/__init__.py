"""
Raphael
-------
Carpeta: Arche/core/raphael/

Todo lo nuevo de Arché en un solo lugar. main.py solo llama a cuatro cosas:

    raphael_arche.iniciar()                      # al arrancar
    raphael_arche.registrar_actividad(frase)     # con cada orden (para aprender tu ritmo)
    raphael_arche.manejar(frase)                 # True si la frase era de Raphael
    raphael_arche.detener_todo()                 # al decir «adiós»

  comun.py            avisos («Informe: ...»), pensar con la nube u Ollama, archivos
  sabio.py            Gran Sabio: cerebro de la fábrica, rangos, fusión, evolución a Raphael
  depredador.py       caza habilidades en GitHub
  jaula.py            donde se encierra y escanea lo que se baja de internet
  imaginacion.py      imagina futuros antes de cambiar código; pensamiento acelerado
  tempest.py          equipo de subordinados con nombre que evolucionan
  cronista.py         noticias, fracasos del día, lecciones, resúmenes de mañana y noche
  fracasos_semilla.py la biblioteca base de fracasos
  ritmo.py            aprende a qué hora empiezas y terminas tu día
  guardian.py         vigila impostores, programas raros, arranque automático, mineros
  voz_viva.py         conversación seguida, interrupciones, reconocer tu voz
  avatar.py           la esfera de Arché en tu escritorio
"""

import threading
import time

from core.raphael import comun

_reloj = {"hilo": None, "parar": threading.Event(), "ultimo_sabio": 0.0}
_iniciado = {"listo": False}

# Orden en que cada parte revisa una frase. Las frases son específicas, así que no se pisan
# con los comandos que Arché ya tenía.
_PARTES = ("sabio", "depredador", "tempest", "imaginacion", "cronista", "guardian", "voz_viva", "avatar")

AYUDA = """Lo nuevo de Arché (Raphael):

GRAN SABIO / RAPHAEL
  estado del sabio · rangos · fusiona <habilidad> y <habilidad> · la habilidad falló
DEPREDADOR
  caza <lo que quieres que aprenda> · presas · absorbe presa N · descarta presa N
  depredador apagado / encendido · token de github <token>
TEMPEST
  misión: <lo que quieres> · tu equipo · nombra al investigador <Nombre> · misiones
  informe de la misión N · abre la misión N · cancela la misión
IMAGINACIÓN
  imagina: <plan> · qué pasaría si <algo> · piensa a fondo: <pregunta> · qué imaginaste
CRONISTA
  ponme al día · fracaso del día · cuéntame un fracaso de <tema> · cuéntame más de la N
  resumen de hoy · lecciones · se parece a algún fracaso: <idea>
  mis noticias · agrega X a mis noticias · quita X de mis noticias
  tu ritmo · dame las noticias a las 7 · noticias a tu ritmo · resúmenes apagados
GUARDIÁN DEL PC
  estado del guardián · escanea mi pc · alertas del guardián · confía en <programa>
  termina el proceso N · guardián apagado / encendido
CONVERSACIÓN VIVA
  conversación viva encendida / apagada · aprende mi voz · solo obedece mi voz
  obedece a todos · sensibilidad de interrupción alta/media/baja
AVATAR
  muestra el avatar · esconde el avatar · avatar grande · avatar pequeño"""


def _parte(nombre):
    import importlib
    return importlib.import_module(f"core.raphael.{nombre}")


def _tic():
    """Lo que el reloj hace cada minuto. Cada parte se protege sola: un error no apaga a las demás."""
    from core.raphael import ritmo, cronista, guardian, depredador, sabio
    for funcion in (ritmo.muestrear, cronista.revisar, guardian.revisar, depredador.revisar):
        try:
            funcion()
        except Exception as e:
            comun.anotar(comun.ruta("errores.jsonl"), {"cuando": comun.ahora_txt(), "donde": funcion.__module__,
                                                       "error": repr(e)[:400]})
    if time.time() - _reloj["ultimo_sabio"] > 600:
        _reloj["ultimo_sabio"] = time.time()
        try:
            sabio.revisar()
        except Exception as e:
            comun.anotar(comun.ruta("errores.jsonl"), {"cuando": comun.ahora_txt(), "donde": "sabio",
                                                       "error": repr(e)[:400]})


def _bucle():
    time.sleep(20)               # deja que Arché termine de arrancar
    while not _reloj["parar"].is_set():
        _tic()
        _reloj["parar"].wait(60)


def iniciar(con_avatar=True, con_voz=True):
    if _iniciado["listo"]:
        return
    _iniciado["listo"] = True
    from core.raphael import sabio, imaginacion
    try:
        sabio.instalar_ganchos()          # el Gran Sabio revisa cada habilidad nueva y lleva sus rangos
    except Exception as e:
        print(f"Arché: (El Gran Sabio no se pudo conectar a la evolución: {e})")
    try:
        imaginacion.instalar()            # imagina antes de cambiar su propio código
    except Exception as e:
        print(f"Arché: (La imaginación no se pudo conectar: {e})")
    if con_voz:
        comun.en_hilo(lambda: _parte("voz_viva").instalar(), nombre="arche-voz-viva")
    if con_avatar:
        try:
            _parte("avatar").iniciar()
        except Exception:
            pass
    _reloj["parar"].clear()
    _reloj["hilo"] = threading.Thread(target=_bucle, name="arche-raphael-reloj", daemon=True)
    _reloj["hilo"].start()


def registrar_actividad(comando=None):
    try:
        from core.raphael import ritmo
        ritmo.registrar(comando)
    except Exception:
        pass


def manejar(comando):
    c = comun.norm(comando)
    if c in ("ayuda raphael", "que hay de nuevo", "novedades de raphael", "comandos de raphael", "que es raphael"):
        comun.msg(AYUDA)
        return True
    for nombre in _PARTES:
        try:
            if _parte(nombre).manejar(comando):
                return True
        except Exception as e:
            comun.msg(f"Esa orden de {nombre} me dio un error ({type(e).__name__}: {str(e)[:120]}).")
            return True
    return False


def detener_todo():
    _reloj["parar"].set()
    for nombre, funcion in (("tempest", "detener"), ("avatar", "detener")):
        try:
            getattr(_parte(nombre), funcion)()
        except Exception:
            pass
