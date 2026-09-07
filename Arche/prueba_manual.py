from core.IA.proponer_cambio_codigo import proponer_cambio_manual

buscar = "def crear_nota(nombre):"
reemplazar = "def crear_nota(nombre):\n    print(\"Arche: creando nota nueva.\")"

p, e = proponer_cambio_manual('core/notas.py', buscar, reemplazar, que='Agregar print de confirmacion')
print(p or e)
