"""
avatar_ventana.py
-----------------
Ubicacion: Arche/core/nucleo/avatar_ventana.py

La ventanita transparente del avatar (pywebview), igual que core/interfaz/web/ventana_web.py:
corre en un proceso aparte porque pywebview necesita el hilo principal. Arché la lanza sola.

    python avatar_ventana.py <url> <ancho> <alto> <x|-> <y|-> <archivo_posicion> <pid_de_arche>

  - sin bordes, siempre encima, fondo transparente, se arrastra desde cualquier punto
  - guarda dónde la dejas
  - se cierra sola si Arché se cierra
"""

import json
import os
import sys
import time


def _arche_viva(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        codigo = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(codigo))
        ctypes.windll.kernel32.CloseHandle(h)
        return codigo.value == 259                                     # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    if len(sys.argv) < 8:
        print(__doc__)
        return
    url, ancho, alto, x, y, ruta_pos, pid = sys.argv[1:8]
    ancho, alto, pid = int(ancho), int(alto), int(pid)
    import webview

    opciones = dict(width=ancho, height=alto, frameless=True, transparent=True, on_top=True, easy_drag=True,
                    resizable=False, background_color="#000000")
    if x != "-" and y != "-":
        opciones.update(x=int(x), y=int(y))
    else:
        try:
            pantalla = webview.screens[0]
            opciones.update(x=pantalla.width - ancho - 20, y=pantalla.height - alto - 70)
        except Exception:
            pass
    try:
        ventana = webview.create_window("Arché", url, focus=False, **opciones)
    except TypeError:                     # versiones viejas de pywebview sin 'focus'
        ventana = webview.create_window("Arché", url, **opciones)

    def _guardar_posicion(nx, ny):
        try:
            with open(ruta_pos, "w", encoding="utf-8") as f:
                json.dump({"x": int(nx), "y": int(ny)}, f)
        except OSError:
            pass

    try:
        ventana.events.moved += _guardar_posicion
    except Exception:
        pass

    def _vigilar():
        while True:
            time.sleep(3)
            if not _arche_viva(pid):
                try:
                    ventana.destroy()
                except Exception:
                    os._exit(0)
                return

    webview.start(_vigilar, private_mode=False)


if __name__ == "__main__":
    main()
