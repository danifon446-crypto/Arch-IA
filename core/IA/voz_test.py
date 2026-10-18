"""
voz_test.py
-----------
Prueba standalone de voz.py: escucha en segundo plano, y cada vez que
detecta "oye arché" + un comando, lo imprime en pantalla.

NO ejecuta ninguna acción real todavía, solo muestra qué entendió.
Sirve para validar que la wake word y la transcripción funcionan bien
en tu hardware antes de integrarlo en main.py.

Uso:
    py voz_test.py

Prueba diciendo cosas como:
    "oye arché abre spotify"
    "arché qué hora es"
    "oye arché" (solo la wake word) -> debería responder "Te escucho..."
    y ahí decir el comando en la siguiente frase.

Ctrl+C para salir.
"""

from voz import escuchar_continuo


def mostrar_comando(texto):
    print(f"\n Comando detectado: {texto!r}\n")


if __name__ == "__main__":
    print("Escuchando... di 'oye arché' seguido de un comando. Ctrl+C para salir.\n")
    try:
        escuchar_continuo(mostrar_comando)
    except KeyboardInterrupt:
        print("\nListo, saliendo.")
