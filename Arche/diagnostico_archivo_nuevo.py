"""
diagnostico_archivo_nuevo.py
-------------------------------
Ubicacion sugerida: Arche/ (raiz, junto a main.py) -- temporal, para depurar.

Muestra la respuesta CRUDA del modelo al pedirle que genere un
archivo nuevo, sin intentar parsearla, para ver por que no matchea
el formato CONTENIDO/FIN o por que el contenido no es Python valido.

Uso (desde Arche/, con Ollama corriendo):
    python diagnostico_archivo_nuevo.py
"""

from core.IA.ollamaIA import conversar
from core.IA.proponer_cambio_codigo import _armar_prompt_archivo_nuevo, _extraer_contenido_nuevo

ARCHIVO = "core/IA/saludo_test.py"
INSTRUCCION = "crear un archivo con una funcion saludar(nombre) que imprima un saludo"

prompt = _armar_prompt_archivo_nuevo(ARCHIVO, INSTRUCCION)

print("=" * 60)
print("RESPUESTA CRUDA DEL MODELO:")
print("=" * 60)
respuesta = conversar(prompt, num_predict=800, temperature=0.2)
print(respuesta)
print("=" * 60)

contenido = _extraer_contenido_nuevo(respuesta)
print(f"\n¿Se extrajo contenido con los marcadores CONTENIDO/FIN?: {'sí' if contenido else 'NO'}")

if contenido:
    print("\nContenido extraído:")
    print("-" * 40)
    print(contenido)
    print("-" * 40)

    import ast
    try:
        ast.parse(contenido)
        print("\n✔ El contenido extraído SÍ es Python válido.")
    except SyntaxError as e:
        print(f"\n✘ El contenido extraído NO es Python válido: {e}")