"""
aplicar_parche_fase4.py
-----------------------
Conecta el entrenador automático de arche-lora (Fase 4) a Arché:
  * main.py: importa core/IA/modelo_nuevo.py, agrega sus comandos y lo arranca.
  * core/IA/enrutador_natural.py: si el arche-lora activo vino del entrenador,
    le pregunta en el formato corto (solo la frase, sin el catálogo de 5.000
    tokens). Si usas el arche-lora de siempre, todo queda EXACTAMENTE igual.

Guarda una copia de cada archivo antes de tocarlo.
Uso (desde la carpeta Arche):   py aplicar_parche_fase4.py
Se puede correr dos veces: si ya está puesto, no hace nada.
"""

import os
import shutil
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))

CORTO = '''    válida o el modelo no reconoció ninguna intención."""
    from core.IA import ollamaIA

    # arche-lora entrenado por el entrenador automático (Fase 4): ya se sabe
    # las intenciones, así que se le pregunta solo la frase (core/IA/formato_lora.py).
    from core.IA import formato_lora
    if formato_lora.usa_formato_corto():
        try:
            respuesta = ollamaIA.ollama.chat(
                model=ollamaIA.MODELO,
                format="json",
                keep_alive=ollamaIA.KEEP_ALIVE,
                messages=formato_lora.mensajes_clasificar(texto),
                options={"num_predict": 60, "temperature": 0.1},
            )
            resultado = formato_lora.parsear(respuesta["message"]["content"])
        except Exception:
            return None
        if not resultado or resultado[0] not in catalogo.POR_ID:
            return None
        return resultado
'''

ARCHIVOS = {
    "main.py": [
        ("from core import compartir as red_arche",
         "from core.IA import modelo_nuevo as modelo_nuevo_arche  # entrenador automático de arche-lora (Fase 4)\n"
         "from core import compartir as red_arche",
         "importar el módulo"),
        ("for _modulo in (memoria_nube_arche,",
         "for _modulo in (memoria_nube_arche, modelo_nuevo_arche,",
         "agregar sus comandos (necesita antes el parche de la memoria en la nube)"),
        ("memoria_nube_arche.iniciar()",
         "memoria_nube_arche.iniciar()\n"
         "modelo_nuevo_arche.iniciar()             # revisa si la nube entrenó un arche-lora nuevo y lo examina",
         "arrancarlo al iniciar"),
    ],
    os.path.join("core", "IA", "enrutador_natural.py"): [
        ('    válida o el modelo no reconoció ninguna intención."""\n    from core.IA import ollamaIA\n', CORTO,
         "agregar el formato corto"),
    ],
}
MARCAS = {"main.py": "modelo_nuevo_arche", os.path.join("core", "IA", "enrutador_natural.py"): "formato_lora"}


def main():
    for falta in (os.path.join("core", "IA", "modelo_nuevo.py"), os.path.join("core", "IA", "formato_lora.py")):
        if not os.path.exists(os.path.join(AQUI, falta)):
            print(f"Falta {falta}. Cópialo primero.")
            return 1
    nuevos = {}
    for rel, cambios in ARCHIVOS.items():
        with open(os.path.join(AQUI, rel), "r", encoding="utf-8") as f:
            codigo = f.read()
        if MARCAS[rel] in codigo:
            print(f"{rel} ya tiene la Fase 4. No lo toco.")
            continue
        for viejo, _nuevo, que in cambios:
            if codigo.count(viejo) != 1:
                print(f"No encontré dónde {que} en {rel}. No cambié nada.")
                print("Mándame ese archivo y lo ajusto.")
                return 1
        for viejo, nuevo, _que in cambios:
            codigo = codigo.replace(viejo, nuevo, 1)
        compile(codigo, rel, "exec")
        nuevos[rel] = codigo
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    for rel, codigo in nuevos.items():
        ruta = os.path.join(AQUI, rel)
        shutil.copy2(ruta, ruta[:-3] + f"_antes_fase4_{sello}.py.bak")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(codigo)
        print(f"Listo: {rel} (copia de seguridad: {os.path.basename(ruta)[:-3]}_antes_fase4_{sello}.py.bak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
