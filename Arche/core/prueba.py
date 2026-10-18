# Prueba
while True:

    usuario = input("Tu: ")

    if usuario == "salir":
        break

    resultado = pensar(usuario)

    print("Arche piensa:", resultado)


# PRUEBAS


pruebas = [
    "hola",
    "abre youtube",
    "abre discord",
    "busca python",
    "qué hora es",
    "recuérdame estudiar"
]

print("\n===== PRUEBAS =====")

for prueba in pruebas:
    print(f"{prueba} -> {pensar(prueba)}")