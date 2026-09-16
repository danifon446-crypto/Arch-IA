"""
diagnostico_cambia_esto.py
------------------------------
Ubicacion sugerida: Arche/ (raiz) -- temporal, para depurar.

Reproduce EXACTO lo que paso con "cambia esto: agregá una función que
cuente cuántas notas hay guardadas", mostrando la respuesta cruda del
modelo, para ver por que el fragmento BUSCAR no matcheo.

Uso (desde Arche/, con Ollama corriendo):
    python diagnostico_cambia_esto.py
"""

from core.IA.enrutar_cambio import decidir_destino, es_pedido_de_agregado
from core.IA.proponer_cambio_codigo import _extraer_funcion, _armar_prompt_funcion_nueva_aislada, _extraer_contenido_nuevo
from core.IA.ollamaIA import conversar
from pathlib import Path

INSTRUCCION_ORIGINAL = "agregá una función que cuente cuántas notas hay guardadas"

decision = decidir_destino(INSTRUCCION_ORIGINAL)
print("DECISIÓN DE RUTEO:")
print(f"  archivo: {decision['archivo']}")
print(f"  función: {decision['funcion']}")
print(f"  explicación: {decision['explicacion']}")
print(f"  ¿parece pedido de agregado?: {es_pedido_de_agregado(INSTRUCCION_ORIGINAL)}\n")

ruta = Path(decision["archivo"])
contenido_actual = ruta.read_text(encoding="utf-8")

fragmento_funcion = _extraer_funcion(contenido_actual, decision["funcion"])
print("FUNCIÓN ANCLA (no se le pide al modelo, ya la tenemos exacta):")
print("-" * 40)
print(fragmento_funcion)
print("-" * 40)
print()

prompt = _armar_prompt_funcion_nueva_aislada(INSTRUCCION_ORIGINAL)

print("=" * 60)
print("PROMPT ENVIADO (función nueva aislada):")
print("=" * 60)
print(prompt)
print()

print("=" * 60)
print("RESPUESTA CRUDA DEL MODELO:")
print("=" * 60)
respuesta = conversar(prompt, num_predict=400, temperature=0.2)
print(respuesta)
print("=" * 60)

codigo_nuevo = _extraer_contenido_nuevo(respuesta)
print(f"\n¿Se extrajo código?: {'sí' if codigo_nuevo else 'NO'}")
if codigo_nuevo:
    print("\nCódigo extraído:")
    print("-" * 40)
    print(codigo_nuevo)
    print("-" * 40)
    import ast
    try:
        ast.parse(codigo_nuevo)
        print("\n✔ Es Python válido.")
    except SyntaxError as e:
        print(f"\n✘ NO es Python válido: {e}")