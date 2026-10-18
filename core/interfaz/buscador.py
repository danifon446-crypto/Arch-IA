"""
buscador.py
-----------
Ubicacion: Arche/core/interfaz/buscador.py

Barra de acceso rapido (Ctrl+Espacio): escribes unas letras y aparecen
acciones, ajustes, perfiles, temas, componentes y tus favoritos. Acepta
coincidencias parciales («tem» encuentra temas, colores y apariencia). Lo que
no coincide con nada se envia a Arché como una orden normal.
"""

from . import ajustes, centro, layout, lenguaje, perfiles, tema

ACCIONES = (
    ("Editar diseño", "mover y redimensionar paneles", ("editor",), "editor distribucion layout mover paneles"),
    ("Centro de personalización", "todos los ajustes", ("centro_ir", "apariencia"), "ajustes configuracion personalizar"),
    ("Deshacer último cambio visual", "", ("ev", "deshacer"), "undo atras"),
    ("Rehacer", "", ("ev", "rehacer"), "redo"),
    ("Pantalla completa (modo TV)", "F11", "tv", "tv fullscreen"),
    ("Modo ambiente", "reloj y esfera", "ambiente", "reposo"),
    ("Activar modo ahorro", "interfaz más ligera", ("orden", "modo ahorro"), "rendimiento ligero lenta"),
    ("Revertir modo ahorro", "", ("orden", "revertir ahorro"), "rendimiento"),
    ("Restablecer distribución", "pide confirmación", ("orden", "restablece la distribucion"), "layout original fabrica"),
    ("Crear punto de restauración", "", ("prefill", "crea un punto de restauracion "), "backup guardar"),
    ("Copia de seguridad de la interfaz", "", ("orden", "copia de seguridad"), "exportar respaldo"),
    ("Esfera flotante", "burbuja sobre otras apps", ("aj", "flotante", True), "flotante burbuja"),
    ("Recorrido guiado", "con la mascota", ("orden", "recorrido"), "tour ayuda"),
    ("Ver procesos en segundo plano", "", ("orden", "procesos"), "tareas"),
    ("Lista de comandos de Arché", "", ("orden", "comandos"), "ayuda comandos"),
    ("Ver redes neuronales (pantalla grande)", "diagrama con ejemplos reales", ("redes", "abrir"), "redes neuronales neuronas ejemplos agregar entrenar"),
    ("Entrenar las redes neuronales", "en segundo plano", ("redes", "entrenar", "todas"), "reentrenar clasificador"),
    ("Escribir una nota", "", ("prefill", "nota: "), "apuntar recordar"),
)


def entradas(v=None):
    sal = []
    for f in ajustes.obtener("favoritos"):
        sal.append({"texto": f, "detalle": "favorito", "accion": ("orden", f), "claves": "favorito"})
    for texto, detalle, accion, claves in ACCIONES:
        sal.append({"texto": texto, "detalle": detalle, "accion": accion, "claves": claves})
    for n, desc, _ in perfiles.listar():
        sal.append({"texto": f"Perfil: {n}", "detalle": desc.rstrip("."), "accion": ("perfil", n), "claves": "perfil modo interfaz"})
    for n, mostrar, propio in tema.listar():
        sal.append({"texto": f"Tema: {mostrar}", "detalle": "tuyo" if propio else "de fábrica", "accion": ("aj", "tema", n), "claves": "tema colores apariencia"})
    lay = perfiles.layout_actual()
    presentes = {w["tipo"] for w in lay["widgets"] if w["visible"]}
    for w in lay["widgets"]:
        n = layout.nombre_de(w["tipo"])
        if w["visible"]:
            sal.append({"texto": f"Ocultar {n}", "detalle": "componente", "accion": ("lay", "vis", w["id"]), "claves": "quitar esconder widget"})
        else:
            sal.append({"texto": f"Mostrar {n}", "detalle": "componente", "accion": ("lay", "vis", w["id"]), "claves": "agregar widget"})
    for t in layout.tipos():
        if t not in presentes and not any(w["tipo"] == t for w in lay["widgets"]):
            sal.append({"texto": f"Agregar {layout.nombre_de(t)}", "detalle": layout.info(t)[7][:50], "accion": ("lay", "add", t), "claves": "widget componente"})
    for cat, nombre in centro.CATEGORIAS:
        for it in centro.items_de(cat):
            if it[0] == "bool":
                sal.append({"texto": f"Alternar: {it[2]}", "detalle": nombre, "accion": ("ajalt", it[1]), "claves": it[1]})
            elif it[0] == "opc":
                for o in ajustes.OPCIONES[it[1]]:
                    sal.append({"texto": f"{it[2]}: {it[3].get(o, o)}", "detalle": nombre, "accion": ("aj", it[1], o), "claves": it[1]})
            elif it[0] in ("num", "color", "botones"):
                et = it[2] if it[0] != "botones" else it[1]
                sal.append({"texto": f"Ajuste: {et}", "detalle": nombre, "accion": ("centro_ir", cat), "claves": it[1] if it[0] != "botones" else ""})
    return sal


def _puntaje(q_tokens, e):
    texto = lenguaje._limpio(e["texto"])
    todo = texto + " " + lenguaje._limpio(e["claves"] + " " + e["detalle"])
    total = 0.0
    for t in q_tokens:
        if t in texto:
            total += 3 + (2 if texto.startswith(t) else 0) + (1 if f" {t}" in texto else 0)
        elif t in todo:
            total += 1.2
        else:
            # subsecuencia: «tm» encuentra «tema»
            it = iter(texto)
            if len(t) >= 2 and all(c in it for c in t):
                total += 0.6
            else:
                return 0.0
    return total - len(texto) * 0.002


def buscar(consulta, n=7, v=None):
    todas = entradas(v)
    q = lenguaje._limpio(consulta).split()
    if not q:
        return todas[:n]
    puntuadas = [(p, e) for e in todas if (p := _puntaje(q, e)) > 0]
    puntuadas.sort(key=lambda x: -x[0])
    return [e for _, e in puntuadas[:n]]
