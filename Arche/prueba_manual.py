from core.IA.proponer_cambio_codigo import proponer_cambio_manual

p, e = proponer_cambio_manual(
    'core/notas.py',
    'def crear_nota(nombre):',
    'def crear_nota(nombre):\n    print("Arché: creando nota nueva.")',
    que='Agregar print de confirmacion'
)
print(p or e)