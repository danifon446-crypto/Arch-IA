"""
ayuda.py
--------
Responde "qué puede hacer Arché" -- el comando ayuda() que main.py
llama pero que nunca se llegó a implementar en ningún lado del
proyecto (ni siquiera en copia(seguridad).py). Sin esto, pedir
"ayuda" crashea con NameError apenas el clasificador reconoce esa
intención.

Organizado por categoría para que "qué hace notas" (ayuda("notas"))
muestre solo esa sección, y "ayuda" a secas muestre todo resumido.
"""

CATEGORIAS = {
    "notas": [
        ("crea una nota <nombre>", "Crea una nota nueva y te pide el contenido."),
        ("lee la nota <nombre>", "Muestra el contenido de una nota."),
        ("agrega a <nombre>", "Agrega texto al final de una nota existente."),
        ("elimina la nota <nombre>", "Borra una nota."),
        ("mis notas", "Lista todas tus notas."),
    ],
    "recordatorios": [
        ("recuérdame <algo>", "Crea un recordatorio (te pido fecha, hora y prioridad)."),
        ("mis recordatorios", "Muestra tus recordatorios pendientes."),
        ("completar recordatorio", "Marca un recordatorio como completado."),
        ("eliminar recordatorio", "Borra un recordatorio."),
    ],
    "calculadora": [
        ("calcula <operación>", "Resuelve una operación matemática. Ej: 'calcula 2 + 2 * 3'."),
        ("cuánto es <operación>", "Lo mismo que 'calcula'."),
        ("historial cálculos", "Muestra tus últimos cálculos."),
    ],
    "archivos": [
        ("busca archivo <nombre>", "Busca un archivo o carpeta en tu equipo por nombre."),
        ("abre archivo <nombre>", "Busca y abre un archivo."),
        ("actualizar archivos", "Reindexa tus archivos en segundo plano."),
    ],
    "programas": [
        ("abre <programa o sitio>", "Abre un programa o página web conocida (o aprende a abrirla)."),
    ],
    "memoria": [
        ("recuerda que <algo>", "Guarda algo para que Arché lo recuerde."),
        ("qué recuerdas", "Muestra lo que Arché tiene guardado en memoria."),
    ],
    "configuración": [
        ("configuración", "Muestra la configuración actual."),
        ("cambiar mi nombre / cambiar tu nombre", "Cambia cómo te llamás vos o cómo se llama Arché."),
        ("restablecer configuración", "Vuelve la configuración a los valores por defecto."),
    ],
    "auto-mejora": [
        ("cambia esto: <instrucción>", "Le pedís a Arché que modifique su propio código."),
        ("escribe en <archivo> : <instrucción>", "Igual que arriba, pero indicando vos el archivo."),
        ("revisar cambios de código", "Ver y aprobar/rechazar cambios de código pendientes."),
        ("cambios de código pendientes", "Lista las propuestas de código sin resolver."),
        ("revisa tu código", "Arché se autorevisa buscando errores (usa Ollama para lo nuevo)."),
        ("autorevisate cada <horas>", "Cambia cada cuánto se autorevisa sola."),
    ],
    "aprendizaje": [
        ("estudiar", "Corre una ronda de estudio (una sola vez)."),
        ("iniciar estudio automático / detener estudio", "Prende o apaga el estudio en segundo plano."),
        ("agregar tema <tema>", "Agrega un tema a la lista de estudio de Arché."),
        ("temas de estudio", "Lista los temas que Arché está estudiando."),
        ("estado red", "Muestra el estado de la red neuronal propia de Arché."),
    ],
    "estadísticas": [
        ("estadísticas", "Muestra cuántos comandos procesó y cómo le fue resolviéndolos."),
    ],
}


def _resumen_completo():
    print()
    print("=" * 46)
    print("   ¿QUÉ PUEDO HACER?")
    print("=" * 46)
    for categoria, comandos in CATEGORIAS.items():
        print(f"\n• {categoria.upper()}")
        for comando, _descripcion in comandos:
            print(f"    - {comando}")
    print("\n" + "=" * 46)
    print("Decí 'qué hace <categoría>' para más detalle de una sola "
        "(ej: 'qué hace notas').")
    print("=" * 46 + "\n")


def _detalle_categoria(categoria):
    categoria = categoria.strip().lower()

    coincidencia = None
    for nombre in CATEGORIAS:
        if categoria == nombre or categoria in nombre or nombre in categoria:
            coincidencia = nombre
            break

    if coincidencia is None:
        print(f"Arché: No tengo una categoría de ayuda para '{categoria}'. "
            f"Decí 'ayuda' para ver todas.")
        return

    print()
    print(f"   {coincidencia.upper()}")
    for comando, descripcion in CATEGORIAS[coincidencia]:
        print(f"\n• {comando}")
        print(f"  {descripcion}")
    print("\n" + "-" * 46 + "\n")


def ayuda(categoria=None):
    if categoria:
        _detalle_categoria(categoria)
    else:
        _resumen_completo()
