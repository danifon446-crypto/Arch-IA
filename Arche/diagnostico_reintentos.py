"""
diagnostico_reintentos.py
----------------------------
Ubicacion sugerida: Arche/ (raiz) -- temporal, para depurar.

Reproduce el bucle completo de proponer_agregar_funcion_cerca a mano,
mostrando CADA intento completo (prompt + respuesta cruda), para ver
por que el ciclo de autocorreccion no esta funcionando como se espera.

Uso (desde Arche/, con Ollama corriendo):
    python diagnostico_reintentos.py
"""

from core.IA.enrutar_cambio import decidir_destino
from core.IA.proponer_cambio_codigo import (
    _extraer_funcion, _armar_prompt_funcion_nueva_aislada,
    _extraer_contenido_nuevo, _validar_sin_alucinaciones,
    _nombres_globales_reales,
)
from core.IA.ollamaIA import conversar
from pathlib import Path
import ast

INSTRUCCION = "agrega una funcion que cuente cuantas notas hay guardadas"

decision = decidir_destino(INSTRUCCION)
ruta = Path(decision["archivo"])
contenido_archivo = ruta.read_text(encoding="utf-8")

nombres_disponibles = None
intento_anterior = None

for intento in range(1, 4):
    print("\n" + "#" * 70)
    print(f"# INTENTO {intento}")
    print("#" * 70)

    prompt = _armar_prompt_funcion_nueva_aislada(INSTRUCCION, nombres_disponibles, intento_anterior)

    print("\n--- PROMPT ENVIADO ---")
    print(prompt)

    respuesta = conversar(prompt, num_predict=400, temperature=0.2)

    print("\n--- RESPUESTA CRUDA ---")
    print(repr(respuesta))
    print("\n(version legible)")
    print(respuesta)

    codigo_nuevo = _extraer_contenido_nuevo(respuesta)

    if codigo_nuevo is None:
        error_especifico = "No incluiste los marcadores CONTENIDO/FIN tal cual se pidió."
        print(f"\n--- RESULTADO: falló extracción de formato ---")
        intento_anterior = (respuesta, error_especifico)
        continue

    print(f"\n--- CÓDIGO EXTRAÍDO ---\n{codigo_nuevo}")

    try:
        ast.parse(codigo_nuevo)
    except SyntaxError as e:
        error_especifico = f"Error de sintaxis en la línea {e.lineno}: {e.msg}"
        print(f"\n--- RESULTADO: sintaxis inválida: {error_especifico} ---")
        intento_anterior = (respuesta, error_especifico)
        continue

    ok, alucinados = _validar_sin_alucinaciones(codigo_nuevo, contenido_archivo)
    if not ok:
        error_especifico = f"Usaste estos nombres que no existen: {', '.join(sorted(alucinados))}."
        print(f"\n--- RESULTADO: nombres alucinados: {alucinados} ---")
        intento_anterior = (respuesta, error_especifico)
        nombres_disponibles = _nombres_globales_reales(contenido_archivo)
        continue

    print("\n--- RESULTADO: ✔ ÉXITO, código válido y sin alucinaciones ---")
    break
else:
    print("\n\nSe agotaron los 3 intentos sin éxito.")