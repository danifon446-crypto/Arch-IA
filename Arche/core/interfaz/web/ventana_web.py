"""
ventana_web.py
--------------
Ubicacion: Arche/core/interfaz/web/ventana_web.py

La ventana propia de la interfaz nueva (pywebview). Corre en un proceso aparte
porque pywebview necesita el hilo principal, y el de Arché esta ocupado
escuchandote en la consola. Arché la lanza sola; no hace falta abrirla a mano.

    python ventana_web.py <direccion> [color_de_fondo]
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("Uso: python ventana_web.py <direccion> [color]")
        return
    url = sys.argv[1]
    fondo = sys.argv[2] if len(sys.argv) > 2 else "#0a0916"
    import webview
    webview.create_window("Arché", url, width=1320, height=860, min_size=(900, 600),
                          background_color=fondo, text_select=True)
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
