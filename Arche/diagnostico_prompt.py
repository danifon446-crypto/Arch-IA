"""
diagnostico_prompt.py
------------------------
Ubicacion sugerida: Arche/ (raiz, junto a main.py) -- es temporal,
solo para depurar, se puede borrar despues.

Llama a conversar() con el MISMO prompt que usa proponer_cambio_ia,
pero imprime la respuesta CRUDA del modelo sin intentar parsearla.
Sirve para ver exactamente que esta devolviendo arche-lora y por que
no matchea el formato BUSCAR/REEMPLAZAR esperado.

Uso (desde Arche/, con Ollama corriendo):
    python diagnostico_prompt.py
"""

from pathlib import Path
from core.IA.ollamaIA import conversar
from core.IA.proponer_cambio_codigo import _armar_prompt, _extraer_funcion

ARCHIVO = "core/notas.py"
INSTRUCCION = "agregar un print de confirmacion al inicio de la funcion crear_nota"

ruta = Path(ARCHIVO)
contenido_actual = ruta.read_text(encoding="utf-8")

fragmento = _extraer_funcion(contenido_actual, "crear_nota")
contenido_para_prompt = fragmento if fragmento else contenido_actual


print("FRAGMENTO AISLADO QUE SE LE MANDA AL MODELO:")

print(contenido_para_prompt)
print()

prompt = _armar_prompt(ARCHIVO, contenido_para_prompt, INSTRUCCION)


print("PROMPT ENVIADO (primeros 500 caracteres):")

print(prompt[:500])
print("...\n")


print("RESPUESTA CRUDA DEL MODELO:")

respuesta = conversar(prompt, num_predict=600, temperature=0.1)
print(respuesta)

print(f"\nLongitud de la respuesta: {len(respuesta)} caracteres")