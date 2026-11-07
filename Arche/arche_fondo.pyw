"""
arche_fondo.pyw
---------------
Ubicacion: Arche/arche_fondo.pyw

Arranca Arché EN SEGUNDO PLANO: sin ventana negra de consola.
Arché queda viva desde que prendes el PC y la llamas con:
  - el atajo de teclado (Ctrl+Alt+A abre la burbuja para escribirle),
  - la voz («oye Arché ...»),
  - el icono junto al reloj (bandeja).
Y ella te avisa sola con notificaciones de Windows.

Cómo se usa:
  - Doble clic a este archivo (abre con pythonw, no sale consola), o
  - que arranque solo con Windows:  python instalar_inicio.py

Lo que Arché "imprime" queda en  Arche/logs/arche_fondo.log  (por si algo falla).
main.py NO cambia: este archivo solo prepara el terreno y luego lo ejecuta.
"""

import os
import sys
import threading

AQUI = os.path.dirname(os.path.abspath(__file__))
os.chdir(AQUI)
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)
os.environ["ARCHE_FONDO"] = "1"          # otros módulos pueden saber que corremos sin consola


# ------------------------------------------------------------------
# 1. Una sola Arché a la vez (si ya está corriendo, no abrir otra)
# ------------------------------------------------------------------

def _ya_esta_corriendo():
    carpeta = os.path.join(AQUI, "logs")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "arche_fondo.lock")
    global _candado_archivo
    _candado_archivo = open(ruta, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(_candado_archivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_candado_archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True


# ------------------------------------------------------------------
# 2. Sin consola: lo que Arché imprime va a un archivo de registro
# ------------------------------------------------------------------

class _Registro:
    """Reemplaza la consola. Escribe todo en el log y, si una frase de Arché
    sale de un hilo de fondo (un aviso que nadie pidió), la manda como
    notificación de Windows a través de core/presencia.py."""

    def __init__(self, archivo):
        self._f = archivo
        self._hilo_principal = threading.get_ident()
        self._linea = ""
        self.encoding = "utf-8"

    def write(self, texto):
        try:
            self._f.write(texto)
            self._f.flush()
        except Exception:
            pass
        if threading.get_ident() != self._hilo_principal:
            self._linea += texto
            while "\n" in self._linea:
                linea, self._linea = self._linea.split("\n", 1)
                self._quizas_notificar(linea)
        return len(texto)

    def _quizas_notificar(self, linea):
        limpia = linea.strip()
        if limpia.lower().startswith(("arché:", "arche:")):
            presencia = sys.modules.get("core.presencia")
            if presencia is not None:
                presencia.aviso_de_fondo(limpia.split(":", 1)[1].strip())

    def flush(self):
        try:
            self._f.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        return self._f.fileno()


def _preparar_salida():
    carpeta = os.path.join(AQUI, "logs")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "arche_fondo.log")
    try:
        if os.path.getsize(ruta) > 5 * 1024 * 1024:      # más de 5 MB: guardo el viejo y empiezo otro
            os.replace(ruta, ruta + ".anterior")
    except OSError:
        pass
    archivo = open(ruta, "a", encoding="utf-8", errors="replace", buffering=1)
    registro = _Registro(archivo)
    sys.stdout = sys.__stdout__ = registro
    sys.stderr = sys.__stderr__ = registro


def _preparar_entrada():
    """Con pythonw no hay teclado de consola. Le damos a Arché una "consola"
    que nunca termina (un tubo vacío), así input() espera tranquilo y los
    mensajes le llegan por la burbuja, la voz, la ventana o Telegram."""
    lectura, escritura = os.pipe()
    global _tubo_abierto
    _tubo_abierto = escritura                 # mientras esto exista, el tubo no "se acaba"
    entrada = os.fdopen(lectura, "r", encoding="utf-8")
    sys.stdin = sys.__stdin__ = entrada


def _sin_ventanas_negras():
    """Sin consola propia, Windows le abre una ventana negra a CADA programa de consola
    que lance Arché (cloudflared, pip, ollama, powershell...). Esto los abre ocultos.
    Las apps con ventana (Chrome, Notepad, juegos) se abren normal: esto no las afecta.
    Si algún día quieres que algo SÍ abra consola, pásale creationflags=subprocess.CREATE_NEW_CONSOLE."""
    if sys.platform != "win32":
        return
    import subprocess
    sin_ventana = 0x08000000          # CREATE_NO_WINDOW
    nueva_consola = 0x00000010        # CREATE_NEW_CONSOLE

    popen_original = subprocess.Popen.__init__

    def popen_oculto(self, *args, **kwargs):
        banderas = kwargs.get("creationflags", 0) or 0
        if not banderas & nueva_consola:
            kwargs["creationflags"] = banderas | sin_ventana
        popen_original(self, *args, **kwargs)

    subprocess.Popen.__init__ = popen_oculto

    def system_oculto(comando):
        return subprocess.call(comando, shell=True)
    os.system = system_oculto


def _no_abrir_ventana_al_iniciar():
    """En segundo plano la ventana grande no se abre sola: la abres con
    Ctrl+Alt+I o desde el icono. (Tu ajuste «automatica» no se toca.)"""
    try:
        from core import interfaz
        interfaz.automatica = lambda: False
    except Exception as e:
        print(f"(arche_fondo) no pude preparar la interfaz: {e}")


# ------------------------------------------------------------------
# Arranque
# ------------------------------------------------------------------

if __name__ == "__main__":
    if _ya_esta_corriendo():
        sys.exit(0)
    if sys.stdout is None or os.path.basename(sys.executable).lower() == "pythonw.exe":
        _preparar_salida()
        _preparar_entrada()
        _sin_ventanas_negras()
    print("\n===== Arché arrancó en segundo plano =====")

    _no_abrir_ventana_al_iniciar()
    try:
        from core import presencia
        presencia.iniciar()
    except Exception as e:
        print(f"(arche_fondo) presencia no arrancó: {e}")

    import runpy
    try:
        runpy.run_path(os.path.join(AQUI, "main.py"), run_name="__main__")
    finally:
        try:
            from core import presencia
            presencia.detener()
        except Exception:
            pass
        os._exit(0)
