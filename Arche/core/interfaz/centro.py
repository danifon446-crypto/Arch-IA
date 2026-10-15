"""
centro.py
---------
Ubicacion: Arche/core/interfaz/centro.py

El Centro de personalizacion: todos los ajustes organizados por categorias,
con buscador. Esta pensado para que un principiante cambie lo basico con un
clic, y para que quien quiera controlar cada detalle lo encuentre aqui.

Cada categoria es una lista de "items" declarativos (interruptor, opciones,
numero, color, boton...). La ventana los dibuja y los cambios se ven en vivo.
Las acciones que disparan los botones las ejecuta ejecutar().
"""

import os
import time

from . import ajustes, estado_visual as ev, extensiones, fondos, layout, lenguaje, perfiles, rendimiento, tema

CATEGORIAS = (
    ("apariencia", "Apariencia"), ("distribucion", "Distribución"), ("widgets", "Widgets"),
    ("ventanas", "Ventanas"), ("voz", "Voz"), ("mascota", "Mascota"),
    ("efectos", "Efectos"), ("fondos", "Fondos"), ("conversacion", "Conversación"),
    ("sistema", "Sistema"), ("redes", "Redes"), ("navegacion", "Navegación"), ("notificaciones", "Notificaciones"),
    ("accesibilidad", "Accesibilidad"), ("rendimiento", "Rendimiento"), ("perfiles", "Perfiles"),
    ("importar", "Importar"), ("extensiones", "Extensiones"),
)
NOMBRES_CAT = dict(CATEGORIAS)

PESTANAS_BASE = (("controles", "CONTROLES", "AZUL_CLARO"), ("ajustes", "PERSONALIZA", "MORADO_CLARO"),
                 ("hoy", "HOY", "ROJO_CLARO"), ("aprende", "APRENDE", "AZUL_CLARO"))
ICONOS_PESTANA = {"controles": "◉", "ajustes": "✦", "hoy": "☀", "aprende": "✎"}

ESTADOS = ("reposo", "escuchando", "pensando", "generando", "hablando", "ejecutando", "buscando", "confirmando", "alerta", "error")
NOMBRES_ESTADO = {"reposo": "inactivo", "escuchando": "escuchando", "pensando": "procesando", "generando": "generando respuesta",
                  "hablando": "hablando", "ejecutando": "ejecutando tarea", "buscando": "buscando información",
                  "confirmando": "esperando confirmación", "alerta": "atendiendo una alerta", "error": "con un error"}


# ------------------------------------------------------------------ items declarativos
def B(clave, etiqueta, detalle=""):
    return ("bool", clave, etiqueta, detalle)


def O(clave, etiqueta, nombres=None):
    return ("opc", clave, etiqueta, nombres or {})


def N(clave, etiqueta, paso=5, unidad="", detalle=""):
    return ("num", clave, etiqueta, paso, unidad, detalle)


def C(clave, etiqueta, detalle=""):
    return ("color", clave, etiqueta, detalle)


def T(texto):
    return ("titulo", texto)


def A(etiqueta, *acciones, detalle=""):
    """Fila de botones: A("Titulo", ("Texto boton", accion), ...)"""
    return ("botones", etiqueta, acciones, detalle)


def F(nombre):
    return ("fn", nombre)


def items_de(cat):
    if cat == "apariencia":
        return [T("TEMA"), F("temas"), A("Tu tema", ("Nuevo", ("prefill", "crea un tema llamado ")), ("Duplicar", ("prefill", "duplica el tema  como ")),
                                         ("Exportar", ("orden", "exporta tema")), ("Borrar", ("tema_borrar",)),
                                         detalle="Los temas de fábrica no se borran. Cambiar un color crea tu propio tema."),
                F("colores_tema"),
                T("CAMBIO AUTOMÁTICO"), B("tema_horario", "Tema según la hora", "día 7:00–19:00 · noche el resto"),
                F("temas_horario"), T("TEXTO"), F("fuente")]
    if cat == "distribucion":
        return [T("DISEÑO DE LA VENTANA"),
                A("Editor visual", ("Editar diseño", ("editor",)), ("Deshacer", ("ev", "deshacer")), ("Rehacer", ("ev", "rehacer")),
                  detalle="Arrastra, estira, oculta o intercambia paneles. Los cambios se ven al momento."),
                A("Restablecer", ("Distribución original", ("orden", "restablece la distribucion")), ("Cambios de este perfil", ("orden", "restablece perfil")),
                  detalle="Pide confirmación antes."),
                N("_margen", "Margen de la ventana", 4, " px"), N("_separacion", "Separación entre paneles", 2, " px"),
                ("laybool", "cabecera", "Cabecera (título, hora y estado)"), ("laybool", "pie", "Barra inferior (botones)"),
                T("COMPONENTES"), F("componentes")]
    if cat == "widgets":
        return [T("AGREGAR COMPONENTE"), F("agregar_widget"), T("AJUSTES DE UN COMPONENTE"), F("opciones_widget")]
    if cat == "ventanas":
        return [T("VENTANA PRINCIPAL"), O("ventana_modo", "Modo", {"normal": "normal", "compacta": "compacta", "superpuesta": "superpuesta"}),
                B("ventana_siempre_visible", "Siempre al frente", "queda sobre las demás apps"),
                N("ventana_opacidad", "Opacidad de la ventana", 10, " %"), B("ventana_sin_borde", "Sin bordes", "sin la barra del sistema (Esc / F11 siguen funcionando)"),
                T("ESFERA FLOTANTE"), B("flotante", "Esfera flotante", "burbuja pequeña sobre otras apps (arrástrala; doble clic abre la ventana)"),
                O("flotante_contenido", "Qué muestra", {"esfera": "esfera", "mascota": "mascota"}), N("flotante_tam", "Tamaño", 20, " px"),
                B("minimizar_sin_foco", "Minimizar al usar otra app", "solo con esfera flotante activa"),
                B("bandeja", "Icono en la bandeja", "necesita pystray"),
                T("PANTALLAS"), F("pantallas"),
                T("ADAPTACIÓN AL CONTEXTO (todo requiere tu permiso)"),
                B("ctx_progreso", "Panel de progreso en tareas largas"), B("ctx_resultados", "Resultados de búsqueda en ventana temporal"),
                B("ctx_reposo", "Reducirme a la esfera cuando no hay actividad"),
                B("ambiente_auto", "Modo ambiente solo", "tras unos minutos sin actividad"), N("ambiente_minutos", "Minutos para ambiente", 1, " min"),
                T("CELULAR"), F("celular")]
    if cat == "voz":
        return [T("IDENTIDAD VISUAL"), O("estilo_voz", "Forma de mi voz", {"esfera": "esfera", "ondas": "ondas", "anillos": "anillos",
                                                                           "nucleo": "núcleo", "geometrica": "geométrica"}),
                N("orbe_tamano", "Tamaño", 10, " %"), N("orbe_velocidad", "Velocidad", 25, " %"), C("orbe_color", "Color propio", "vacío = el del tema"),
                T("ESTADOS"), O("estado_indicador", "Cómo mostrar lo que hago", {"animacion": "animación", "icono": "icono", "texto": "texto", "combinado": "todo junto"}),
                F("estados_colores")]
    if cat == "mascota":
        return [T("MASCOTA"), B("mascota", "Mostrar mascota"),
                O("mascota_personaje", "Personaje", {"chispa": "chispa", "robot": "robot", "gato": "gato", "esfera": "esfera", "minimal": "minimal", "imagen": "imagen"}),
                ("nombre",), N("mascota_tamano", "Tamaño", 10, " %"), N("mascota_opacidad", "Transparencia (opacidad)", 10, " %"),
                O("mascota_visibilidad", "Visibilidad", {"siempre": "siempre", "temporal": "solo cuando habla"}),
                B("mascota_reacciones", "Reacciona a lo que hago", "se alegra, se concentra, duerme…"),
                B("consejos", "Consejos", "me ve ocupada y te digo trucos"), O("mascota_frecuencia", "Frecuencia de consejos", {"poca": "poca", "normal": "normal", "mucha": "mucha"}),
                B("mascota_flotante", "Mascota flotante", "sale de la ventana y flota sobre otras apps"),
                B("intencion_en_vivo", "Ver qué entendí", "muestra la intención de cada orden"), T("GUÍA"),
                A("Recorrido", ("Hacer el recorrido", ("orden", "recorrido")))]
    if cat == "efectos":
        return [T("EFECTOS"), N("efecto_sombra", "Sombras", 10, " %"), N("efecto_borde_luminoso", "Bordes luminosos", 10, " %"),
                N("efecto_brillo", "Brillo de la esfera", 10, " %"), B("efecto_profundidad", "Profundidad", "capas y reflejos suaves en los paneles"),
                N("efecto_particulas", "Partículas alrededor de la esfera", 10, " %"), N("efectos_simultaneos", "Efectos a la vez (tope)", 1, ""),
                T("MOVIMIENTO"), N("anim_velocidad", "Velocidad de las animaciones", 25, " %"),
                B("anim_transiciones", "Los paneles se deslizan al moverse"), B("reducir_movimiento", "Movimiento reducido", "menos animación, mismas funciones"),
                A("Todo apagado", ("Quitar todos los efectos", ("orden", "quita los efectos")), ("Activar efectos", ("orden", "activa los efectos")))]
    if cat == "fondos":
        return [T("FONDO"), F("fondo"), N("fondo_oscuridad", "Oscuridad", 10, " %"), N("fondo_desenfoque", "Desenfoque", 2, " px", "necesita Pillow"),
                B("fondo_movimiento", "Fondo en movimiento", "apágalo para que el video o GIF se quede quieto"),
                T("ESCENA AMBIENTAL"), O("escena", "Escena", {"ninguna": "ninguna", "gradiente": "gradiente", "particulas": "partículas", "ondas": "ondas",
                                                              "rejilla": "rejilla", "nebulosa": "nebulosa"}),
                N("escena_intensidad", "Intensidad", 10, " %"), N("escena_velocidad", "Velocidad", 25, " %"), N("escena_brillo", "Brillo", 10, " %")]
    if cat == "conversacion":
        return [T("CONVERSACIÓN"), O("chat_vista", "Vista", {"clasica": "clásica", "compacta": "compacta", "tecnica": "técnica"}),
                N("chat_tam", "Tamaño de letra", 1, " pt"), N("chat_ancho", "Ancho del chat", 10, " %"), N("chat_espacio", "Espacio entre mensajes", 2, " px"),
                O("chat_alineacion", "Alineación", {"izquierda": "izquierda", "derecha": "derecha", "alternada": "alternada"}),
                C("chat_color_usuario", "Color de tus mensajes"), C("chat_color_arche", "Color de Arché"),
                B("chat_marcas_tiempo", "Marcas de tiempo"), N("chat_historial", "Mensajes visibles", 2, ""), B("chat_indicador", "Indicador «pensando…»"),
                B("chat_entrada_arriba", "Caja de escritura arriba"), N("chat_entrada_alto", "Alto de la caja", 6, " px")]
    if cat == "sistema":
        return [T("PANEL DEL SISTEMA"), O("sistema_estilo", "Cómo mostrar CPU, RAM…", {"barras": "barras", "circular": "circular", "numeros": "números", "compacto": "compacto"}),
                N("sistema_actualizacion", "Actualizar cada", 1, " s"), F("sistema_ocultar"),
                T("AVISOS POR LÍMITE"), N("limite_cpu", "Avisar si la CPU pasa de", 5, " %"), N("limite_ram", "Avisar si la RAM pasa de", 5, " %"),
                N("limite_disco", "Avisar si el disco pasa de", 5, " %"),
                ("info", "Lo que el equipo no mida aparece como «no disponible»: nunca invento datos.")]
    if cat == "redes":
        return [T("VISTA"), O("redes_estilo", "Cómo dibujar las redes", {"diagrama": "diagrama", "arbol": "árbol", "lista": "lista"}),
                N("redes_neuronas", "Neuronas por capa", 2, "", "muestra de neuronas; el número real se indica en cada capa"),
                N("redes_conexiones", "Líneas visibles", 10, " %"), B("redes_pesos", "Color según el peso real", "azul = a favor · rojo = en contra"),
                B("redes_animar", "Pulso de luz al probar una frase"), C("redes_color_pos", "Color de pesos positivos"),
                C("redes_color_neg", "Color de pesos negativos"), B("redes_leyenda", "Leyenda de colores"),
                B("redes_cerca", "«Una neurona de cerca»", "en la vista grande"), B("redes_etiquetas", "Nombre de cada intención junto a la salida"),
                N("redes_ejemplos_max", "Ejemplos visibles", 1, ""),
                T("CAJAS"), B("redes_probador", "Caja para probar una frase", "enciende las neuronas con activaciones reales"),
                B("redes_agregar", "Caja para agregar ejemplos"),
                T("AL AGREGAR EJEMPLOS (Arché decide la intención)"),
                N("redes_umbral_auto", "Seguridad mínima", 5, " %", "para agregar sin preguntar; si duda, pregunta a la nube y luego a ti"),
                B("redes_usar_nube", "Preguntar a la nube cuando la red duda", "necesita la nube conectada"),
                B("redes_proponer_nuevas", "Proponer una intención nueva si ninguna encaja", "tú confirmas; queda en Database/intenciones_propuestas.json"),
                B("redes_marcar_auto", "Marcar «auto» lo que clasifico sola"),
                O("redes_entrenar", "Reentrenar", {"manual": "con el botón", "automatico": "al agregar", "sistema": "cada 5 (como siempre)"}),
                N("redes_deshacer_segundos", "Tiempo p/ deshacer", 2, " s"),
                T("ACCIONES"), A("Redes", ("Abrir vista grande", ("redes", "abrir")), ("Entrenar todas", ("redes", "entrenar", "todas")),
                                 detalle="También: «ver redes neuronales», «agrega la frase …», «entrena las redes»."),
                ("info", "Nunca invento datos: una red sin entrenar se muestra como tal y la nube solo se consulta si tú lo permites.")]
    if cat == "navegacion":
        return [T("NAVEGACIÓN"), O("navegacion", "Estructura", {"pestanas": "pestañas", "iconos": "iconos", "lateral": "lateral", "menu": "menú"}),
                B("nav_etiquetas", "Mostrar etiquetas"), N("nav_iconos_tam", "Tamaño de iconos", 10, " %"), F("nav_orden")]
    if cat == "notificaciones":
        return [T("AVISOS"), N("notif_segundos", "Cuánto duran", 1, " s"), O("notif_posicion", "Dónde aparecen", {"arriba": "arriba", "abajo": "abajo"}),
                B("notif_exito", "Avisos de éxito"), B("notif_error", "Avisos de error"), B("notif_info", "Avisos informativos"),
                B("notif_silencio", "No molestar", "no muestra avisos (siguen en el widget Notificaciones)"),
                B("sonidos", "Sonidos", "solo Windows"), B("intencion_en_vivo", "Ver qué entendí")]
    if cat == "accesibilidad":
        return [T("TAMAÑO"), N("ui_escala", "Tamaño de la interfaz", 10, " %"), N("texto_escala", "Tamaño del texto", 10, " %"),
                T("CONTRASTE Y MOVIMIENTO"), B("alto_contraste", "Alto contraste"), B("reducir_movimiento", "Reducir animaciones"),
                T("TECLADO"), B("teclado_nav", "Navegar con Tab / Enter", "Tab mueve el foco, Enter activa, Esc lo suelta"), F("atajos"),
                ("info", "El estado nunca depende solo del color: siempre hay texto, forma o símbolo.")]
    if cat == "rendimiento":
        return [T("MODO DE RENDIMIENTO"), O("rendimiento", "Modo", {"normal": "normal", "ahorro": "ahorro", "auto": "auto"}),
                A("Ahorro", ("Activar ahorro", ("orden", "modo ahorro")), ("Revertir", ("orden", "revertir ahorro")),
                  detalle="Apaga fondos animados, escenas, partículas y transiciones. Revertir lo deja como estaba."),
                O("fluidez", "Cuadros por segundo", {"alta": "alta (30)", "normal": "normal (20)", "ahorro": "ahorro (12)"}),
                B("rend_sugerir", "Proponerme el ahorro si va lenta", "solo en modo auto, y nunca lo activa sin preguntar"), F("rendimiento_info")]
    if cat == "perfiles":
        return [T("PERFILES"), F("perfiles"),
                A("Tu perfil", ("Guardar como…", ("prefill", "guarda la interfaz como ")), ("Duplicar…", ("prefill", "duplica perfil  como ")),
                  ("Renombrar…", ("prefill", "renombra perfil  a ")), ("Borrar", ("perfil_borrar",)),
                  detalle="Lo que cambias se guarda en el perfil activo."),
                A("Fábrica", ("Restablecer este perfil", ("orden", "restablece perfil"))), T("POR PANTALLA"), F("pantallas")]
    if cat == "importar":
        return [T("EXPORTAR"), A("Guardar en Database/interfaz", ("Perfil", ("orden", "exporta perfil")), ("Tema", ("orden", "exporta tema")),
                                 ("Copia de seguridad", ("orden", "copia de seguridad"))),
                T("IMPORTAR"), F("archivos_export"), T("PUNTOS DE RESTAURACIÓN"),
                A("Puntos", ("Crear punto", ("prefill", "crea un punto de restauracion ")), ("Ver", ("orden", "puntos de restauracion"))), F("puntos"),
                T("SINCRONIZAR ENTRE EQUIPOS (opcional)"), F("sync")]
    if cat == "extensiones":
        return [T("EXTENSIONES VISUALES"), F("extensiones"),
                ("info", "Son archivos .json en Database/extensiones. Un tema no puede pedir permisos; un widget con botones debe declarar «comandos».")]
    return []


# ------------------------------------------------------------------ buscador de ajustes
def _texto_item(it):
    if it[0] in ("bool", "num", "color"):
        return f"{it[2]} {it[1]}"
    if it[0] == "opc":
        return f"{it[2]} {it[1]} " + " ".join(str(x) for x in it[3].values())
    if it[0] == "botones":
        return it[1] + " " + " ".join(a[0] for a in it[2]) + " " + it[3]
    if it[0] == "fn":
        return {"temas": "tema colores", "colores_tema": "colores del tema hex", "componentes": "componentes widgets mostrar ocultar",
                "agregar_widget": "agregar widget componente", "perfiles": "perfiles", "puntos": "puntos restauracion",
                "fondo": "fondo imagen video", "atajos": "atajos teclado", "pantallas": "pantalla monitor",
                "extensiones": "extensiones", "sync": "sincronizar equipos", "sistema_ocultar": "ocultar cpu ram disco bateria"}.get(it[1], it[1])
    return ""


def buscar_items(consulta):
    """[(categoria, item)] que coinciden con todas las palabras de la consulta."""
    q = lenguaje._limpio(consulta).split()
    if not q:
        return []
    sal = []
    for cat, nombre in CATEGORIAS:
        for it in items_de(cat):
            if it[0] in ("titulo", "info"):
                continue
            txt = lenguaje._limpio(_texto_item(it) + " " + nombre)
            if all(p in txt for p in q):
                sal.append((cat, it))
    return sal


# ------------------------------------------------------------------ dibujo
def _ancho_chip(texto, esc):
    return (len(texto) * 6.6 + 20) * esc


def construir(v, esc, categoria, filtro=""):
    """Bloques [(alto, fn(px, yy, bw))] de una categoria (o de los resultados de la busqueda)."""
    bloques = []
    if filtro.strip():
        encontrados = buscar_items(filtro)
        if not encontrados:
            bloques.append((40 * esc, lambda px, yy, bw: v._texto(px, yy + 14 * esc, "Ningún ajuste coincide. Prueba otra palabra (ej. «color», «fondo»).", 9, v_tema().TENUE)))
        ultima = None
        for cat, it in encontrados:
            if cat != ultima:
                ultima = cat
                bloques.append(_b_titulo(v, esc, NOMBRES_CAT[cat].upper()))
            bloques += _bloques_item(v, esc, it)
        return bloques
    for it in items_de(categoria):
        bloques += _bloques_item(v, esc, it)
    return bloques


def v_tema():
    return tema


def _bw(v):
    return getattr(v, "centro_bw", 280)


def _b_titulo(v, esc, txt):
    def f(px, yy, bw):
        v._texto(px, yy + 12 * esc, txt, 8, tema.TENUE, negrita=True)
        v.canvas.create_line(px + len(txt) * 7 * esc, yy + 12 * esc, px + bw, yy + 12 * esc, fill=tema.BORDE, tags=v._tag)
    return (26 * esc, f)


def _filas_chips(esc, bw, textos, x0=0.0):
    """Reparte chips en filas: devuelve [(fila, x, texto_idx, ancho)]."""
    pos, fila, x = [], 0, x0
    for i, t in enumerate(textos):
        w = _ancho_chip(t, esc)
        if x > x0 and x + w > bw:
            fila += 1
            x = x0
        pos.append((fila, x, i, w))
        x += w + 6 * esc
    return pos, (fila + 1)


def _bloques_item(v, esc, it):
    tipo = it[0]
    A_ = ajustes.obtener
    if tipo == "titulo":
        return [_b_titulo(v, esc, it[1])]
    if tipo == "info":
        lineas = 1 + int(len(it[1]) * 5.4 // max(120, _bw(v)))
        return [((16 + 12 * lineas) * esc, lambda px, yy, bw: v._texto(px, yy + 8 * esc, it[1], 8, tema.TENUE, ancho=int(bw)))]
    if tipo == "bool":
        _, clave, etiqueta, detalle = it

        def f(px, yy, bw):
            v._texto(px, yy + 8 * esc, etiqueta, 10, tema.TEXTO)
            if detalle:
                v._texto(px, yy + 23 * esc, detalle[:int(bw / (8 * esc * 0.6)) - 8], 8, tema.TENUE)
            accion = ("ajalt", clave)
            v._interruptor(px + bw, yy + 12 * esc, bool(A_(clave)), accion, esc)
            v.zonas.append((px, yy, px + bw, yy + 30 * esc, accion))
        return [(38 * esc, f)]
    if tipo == "opc":
        _, clave, etiqueta, nombres = it
        ops = ajustes.OPCIONES[clave]
        textos = [nombres.get(o, o) for o in ops]
        _, filas = _filas_chips(esc, _bw(v), textos)

        def f(px, yy, bw):
            v._texto(px, yy + 8 * esc, etiqueta, 10, tema.TEXTO)
            pos, _n = _filas_chips(esc, bw, textos)
            for fila, x, i, w in pos:
                v._chip(px + x, yy + 22 * esc + fila * 26 * esc, textos[i], ("aj", clave, ops[i]), A_(clave) == ops[i], None, w)
        # estimar filas con el ancho tipico del panel (el real se calcula al dibujar)
        n = max(1, filas)
        return [((30 + 26 * n) * esc, f)]
    if tipo == "num":
        _, clave, etiqueta, paso, unidad, detalle = it

        def f(px, yy, bw):
            valor = _valor_num(clave)
            ancho_lib = bw - ((len(f"{valor}{unidad}") * 7 + 14) + 70) * esc
            maxc = max(4, int(ancho_lib / (7.2 * esc)))
            v._texto(px, yy + 8 * esc, etiqueta if len(etiqueta) <= maxc else etiqueta[:maxc - 1] + "…", 10, tema.TEXTO)
            if detalle:
                v._texto(px, yy + 34 * esc, detalle, 8, tema.TENUE, ancho=int(bw))
            xr = px + bw
            xm = xr - 26 * esc
            v._chip(xm, yy - 2 * esc, "+", ("num", clave, paso), False, None, 26 * esc)
            v._texto(xm - 8 * esc, yy + 9 * esc, f"{valor}{unidad}", 10, tema.MORADO_CLARO, ancla="e", negrita=True)
            ancho_v = (len(f"{valor}{unidad}") * 7 + 14) * esc
            v._chip(xm - 8 * esc - ancho_v - 26 * esc, yy - 2 * esc, "−", ("num", clave, -paso), False, None, 26 * esc)
        lineas = 1 + len(detalle) * 5.2 // max(120, _bw(v)) if detalle else 0
        return [((44 + 12 * lineas if detalle else 34) * esc, f)]
    if tipo == "color":
        _, clave, etiqueta, detalle = it

        def f(px, yy, bw):
            valor = A_(clave)
            v._texto(px, yy + 8 * esc, etiqueta, 10, tema.TEXTO)
            v._texto(px, yy + 23 * esc, valor or (detalle or "del tema"), 8, tema.TENUE)
            sw = 22 * esc
            x0 = px + bw - sw
            v._redondo(x0, yy, x0 + sw, yy + sw, 6 * esc, fill=valor or tema.PANEL_2, outline=tema.BORDE)
            v.zonas.append((x0, yy, x0 + sw, yy + sw, ("color", clave)))
            if valor:
                v._chip(x0 - 66 * esc, yy, "quitar", ("aj", clave, ""), False, None, 58 * esc)
        return [(40 * esc, f)]
    if tipo == "botones":
        _, etiqueta, acciones, detalle = it
        textos = [a[0] for a in acciones]

        def f(px, yy, bw):
            v._texto(px, yy + 8 * esc, etiqueta, 10, tema.TEXTO)
            pos, _n = _filas_chips(esc, bw, textos)
            for fila, x, i, w in pos:
                v._chip(px + x, yy + 22 * esc + fila * 26 * esc, textos[i], acciones[i][1], False, None, w)
            if detalle:
                v._texto(px, yy + 22 * esc + (_n * 26 + 4) * esc, detalle, 8, tema.TENUE, ancho=int(bw))
        _, filas = _filas_chips(esc, _bw(v), textos)
        return [((34 + 26 * filas + (14 if detalle else 0)) * esc, f)]
    if tipo == "laybool":
        _, clave, etiqueta = it

        def f(px, yy, bw):
            lay = perfiles.layout_actual()
            v._texto(px, yy + 8 * esc, etiqueta, 10, tema.TEXTO)
            accion = ("lay", "alt", clave)
            v._interruptor(px + bw, yy + 12 * esc, bool(lay.get(clave, True)), accion, esc)
            v.zonas.append((px, yy, px + bw, yy + 30 * esc, accion))
        return [(34 * esc, f)]
    if tipo == "nombre":
        def f(px, yy, bw):
            v._texto(px, yy + 8 * esc, "Nombre", 10, tema.TEXTO)
            v._texto(px + bw - 66 * esc, yy + 8 * esc, A_("mascota_nombre")[:16], 10, tema.MORADO_CLARO, ancla="e")
            v._chip(px + bw - 60 * esc, yy - 2 * esc, "cambiar", ("nombre",), False, None, 60 * esc)
        return [(34 * esc, f)]
    if tipo == "fn":
        fn = _FN.get(it[1])
        return fn(v, esc) if fn else []
    return []


def _valor_num(clave):
    if clave == "_margen":
        return perfiles.layout_actual().get("margen", 22)
    if clave == "_separacion":
        return perfiles.layout_actual().get("separacion", 14)
    return ajustes.obtener(clave)


# ------------------------------------------------------------------ items "fn" (listas dinamicas)
def _f_temas(v, esc):
    lista = tema.listar()
    textos = [n for _, n, _ in lista]

    def f(px, yy, bw):
        pos, _n = _filas_chips(esc, bw, textos)
        for fila, x, i, w in pos:
            nombre = lista[i][0]
            v._chip(px + x, yy + fila * 26 * esc, textos[i], ("aj", "tema", nombre), tema.actual() == nombre,
                    tema.MORADO_CLARO if lista[i][2] else None, w)
    _, filas = _filas_chips(esc, _bw(v), textos)
    return [((10 + 26 * filas) * esc, f)]


def _f_colores_tema(v, esc):
    bloques = []
    actual = tema.actual()
    propio = tema.es_propio(actual)
    cols = tema.colores_de(actual)

    def cab(px, yy, bw):
        v._texto(px, yy + 10 * esc, "COLORES DEL TEMA «" + (actual if propio else tema.NOMBRES.get(actual, actual)) + "»", 8, tema.TENUE, negrita=True)
        if not propio:
            v._texto(px, yy + 26 * esc, "Toca un color: se crea tu propio tema con ese cambio.", 8, tema.TENUE)
        else:
            v._chip(px + bw - 96 * esc, yy, "restablecer", ("tema_reset",), False, None, 96 * esc)
    bloques.append((38 * esc, cab))
    for rol, desc in tema.ROLES.items():
        def f(px, yy, bw, rol=rol, desc=desc):
            col = cols.get(rol) or {"boton": tema.BOTON, "ok": tema.OK, "atencion": tema.ATENCION, "alerta": tema.ALERTA,
                                    "grafica_a": tema.GRAFICA_A, "grafica_b": tema.GRAFICA_B, "seleccion": tema.SELECCION}.get(rol, "#000000")
            sw = 20 * esc
            x0 = px + bw - sw
            v._texto(px, yy + 9 * esc, desc, 9, tema.TEXTO)
            v._texto(x0 - 8 * esc, yy + 9 * esc, col, 8, tema.TENUE, ancla="e", mono=True)
            v._redondo(x0, yy - 1 * esc, x0 + sw, yy + sw - 1 * esc, 5 * esc, fill=col, outline=tema.BORDE)
            v.zonas.append((px, yy - 4 * esc, px + bw, yy + sw, ("colorrol", rol)))
        bloques.append((26 * esc, f))
    return bloques


def _f_temas_horario(v, esc):
    lista = tema.listar()
    nombres = [n for _, n, _ in lista]

    def f(px, yy, bw):
        for k, (etq, clave) in enumerate((("Día", "tema_dia"), ("Noche", "tema_noche"))):
            y0 = yy + k * 56 * esc
            v._texto(px, y0 + 8 * esc, etq, 10, tema.TEXTO)
            pos, _n = _filas_chips(esc, bw - 50 * esc, nombres, 0)
            for fila, x, i, w in pos[:6]:
                v._chip(px + 50 * esc + x, y0 + fila * 26 * esc - 2 * esc, nombres[i], ("aj", clave, lista[i][0]),
                        ajustes.obtener(clave) == lista[i][0], None, w)
    return [(150 * esc, f)]


def _f_fuente(v, esc):
    fuentes = ("", "Segoe UI", "Consolas", "Arial", "Verdana", "Calibri", "Georgia")
    textos = [f or "del sistema" for f in fuentes]

    def f(px, yy, bw):
        v._texto(px, yy + 8 * esc, "Tipo de letra", 10, tema.TEXTO)
        pos, _n = _filas_chips(esc, bw, textos)
        for fila, x, i, w in pos:
            v._chip(px + x, yy + 22 * esc + fila * 26 * esc, textos[i], ("aj", "fuente", fuentes[i]), ajustes.obtener("fuente") == fuentes[i], None, w)
    return [(86 * esc, f)]


def _f_componentes(v, esc):
    lay = perfiles.layout_actual()
    bloques = []
    for w in lay["widgets"]:
        def f(px, yy, bw, w=w):
            visible = w["visible"] and not w.get("ventana")
            v._texto(px, yy + 8 * esc, layout.nombre_de(w["tipo"]) + (f"  ({w['id']})" if w["id"] != w["tipo"] else ""), 10,
                     tema.TEXTO if visible else tema.TENUE, negrita=visible)
            estado = "en ventana aparte" if w.get("ventana") else ("visible" if visible else "oculto")
            v._texto(px, yy + 23 * esc, f"{estado} · {w['w']}×{w['h']}", 8, tema.TENUE)
            x = px + bw
            accion = ("lay", "vis", w["id"])
            v._interruptor(x, yy + 12 * esc, visible, accion, esc)
            v.zonas.append((x - 40 * esc, yy, x, yy + 28 * esc, accion))
            xx = x - 50 * esc
            if not layout.info(w["tipo"])[6]:
                xx = v._chip(xx - 28 * esc, yy + 1 * esc, "⧉", ("lay", "dup", w["id"]), False, None, 26 * esc) - 34 * esc
                v._chip(xx - 28 * esc + 0, yy + 1 * esc, "✕", ("lay", "quitar", w["id"]), False, None, 26 * esc)
        bloques.append((38 * esc, f))
    return bloques


def _f_agregar_widget(v, esc):
    lay = perfiles.layout_actual()
    presentes = {w["tipo"] for w in lay["widgets"] if w["visible"]}
    faltan = [t for t in layout.tipos() if not (layout.info(t)[6] and t in presentes)]
    textos = [layout.nombre_de(t) for t in faltan]

    def f(px, yy, bw):
        pos, _n = _filas_chips(esc, bw, textos)
        for fila, x, i, w in pos:
            v._chip(px + x, yy + fila * 26 * esc, "+ " + textos[i], ("lay", "add", faltan[i]), False, None, w + 14 * esc)
    _, filas = _filas_chips(esc, _bw(v), textos)
    return [((10 + 28 * filas) * esc, f)]


def _f_opciones_widget(v, esc):
    lay = perfiles.layout_actual()
    ws = [w for w in lay["widgets"] if w["visible"] or w.get("ventana")]
    sel = v.centro_sel if any(w["id"] == v.centro_sel for w in lay["widgets"]) else (ws[0]["id"] if ws else None)
    bloques = []
    textos = [layout.nombre_de(w["tipo"]) + (f" ({w['id'].split('-')[-1]})" if "-" in w["id"] else "") for w in ws]

    def selector(px, yy, bw):
        pos, _n = _filas_chips(esc, bw, textos)
        for fila, x, i, w in pos:
            v._chip(px + x, yy + fila * 26 * esc, textos[i], ("sel_widget", ws[i]["id"]), ws[i]["id"] == sel, None, w)
    _, filas = _filas_chips(esc, _bw(v), textos)
    bloques.append(((10 + 26 * filas) * esc, selector))
    w = layout.buscar(lay, sel) if sel else None
    if w is None:
        return bloques

    def op_num(etq, clave, paso, unidad=""):
        def f(px, yy, bw):
            v._texto(px, yy + 8 * esc, etq, 10, tema.TEXTO)
            xm = px + bw - 26 * esc
            v._chip(xm, yy - 2 * esc, "+", ("lay", "op", w["id"], clave, paso), False, None, 26 * esc)
            valor = w[clave]
            v._texto(xm - 8 * esc, yy + 9 * esc, f"{valor}{unidad}", 10, tema.MORADO_CLARO, ancla="e", negrita=True)
            ancho_v = (len(f"{valor}{unidad}") * 7 + 14) * esc
            v._chip(xm - 8 * esc - ancho_v - 26 * esc, yy - 2 * esc, "−", ("lay", "op", w["id"], clave, -paso), False, None, 26 * esc)
        return (34 * esc, f)
    bloques.append(op_num("Transparencia (opacidad)", "opacidad", 10, " %"))

    def nivel(px, yy, bw):
        v._texto(px, yy + 8 * esc, "Nivel de información", 10, tema.TEXTO)
        x = px
        for n in layout.NIVELES:
            x = v._chip(x, yy + 22 * esc, n, ("lay", "nivel", w["id"], n), w["nivel"] == n) + 6 * esc
    bloques.append((56 * esc, nivel))

    def color(px, yy, bw):
        v._texto(px, yy + 8 * esc, "Color de acento", 10, tema.TEXTO)
        v._texto(px, yy + 23 * esc, w["color"] or "el del tema", 8, tema.TENUE)
        sw = 22 * esc
        x0 = px + bw - sw
        v._redondo(x0, yy, x0 + sw, yy + sw, 6 * esc, fill=w["color"] or tema.PANEL_2, outline=tema.BORDE)
        v.zonas.append((x0, yy, x0 + sw, yy + sw, ("lay", "color", w["id"])))
        if w["color"]:
            v._chip(x0 - 66 * esc, yy, "quitar", ("lay", "colorquitar", w["id"]), False, None, 58 * esc)
    bloques.append((40 * esc, color))
    if w["tipo"] == "reloj":
        def estilo(px, yy, bw):
            v._texto(px, yy + 8 * esc, "Estilo del reloj", 10, tema.TEXTO)
            x = px
            for n in ("digital", "analogico"):
                x = v._chip(x, yy + 22 * esc, n, ("lay", "estilo", w["id"], n), w["opts"].get("estilo", "digital") == n) + 6 * esc
        bloques.append((56 * esc, estilo))
    if w["tipo"] == "sistema":
        def estilo_s(px, yy, bw):
            v._texto(px, yy + 8 * esc, "Estilo de este panel", 10, tema.TEXTO)
            x = px
            for n in ("barras", "circular", "numeros", "compacto"):
                x = v._chip(x, yy + 22 * esc, n, ("lay", "estilo", w["id"], n), (w["opts"].get("estilo") or ajustes.obtener("sistema_estilo")) == n) + 4 * esc
        bloques.append((56 * esc, estilo_s))

    def acciones(px, yy, bw):
        x = px
        x = v._chip(x, yy, "al frente", ("lay", "frente", w["id"]), False) + 6 * esc
        x = v._chip(x, yy, "al fondo", ("lay", "fondo", w["id"]), False) + 6 * esc
        if w["tipo"] != "chat":
            v._chip(x, yy, "ventana aparte", ("lay", "desacoplar", w["id"]), False)
    bloques.append((34 * esc, acciones))
    return bloques


def _f_pantallas(v, esc):
    mapa = ajustes.obtener("pantallas")
    nombres = [n for n, _, _ in perfiles.listar()]

    def f(px, yy, bw):
        for k, (clase, etq) in enumerate((("pequena", "Pequeña (<900 px)"), ("normal", "Normal"), ("amplia", "Amplia (>1500 px)"))):
            y0 = yy + k * 56 * esc
            v._texto(px, y0 + 8 * esc, etq, 10, tema.TEXTO)
            x = px
            x = v._chip(x, y0 + 22 * esc, "ninguno", ("pantalla", clase, ""), not mapa.get(clase)) + 4 * esc
            for n in nombres[:5]:
                x = v._chip(x, y0 + 22 * esc, n, ("pantalla", clase, n), mapa.get(clase) == n) + 4 * esc
        v._texto(px, yy + 172 * esc, f"Ahora: pantalla {v.clase_pantalla()} ({v.ancho_real}×{v.alto_real}). El perfil elegido se activa solo al cambiar de tamaño.", 8, tema.TENUE, ancho=int(bw))
    return [(196 * esc, f)]


def _f_celular(v, esc):
    def f(px, yy, bw):
        try:
            from . import remoto
            activo = remoto.activo()
        except Exception:
            return
        if activo:
            v._texto(px, yy + 6 * esc, remoto.direccion(), 9, tema.AZUL_CLARO)
            v._texto(px, yy + 22 * esc, f"PIN  {ajustes.obtener('celular_pin')}", 11, tema.TEXTO, negrita=True)
            v._chip(px + bw - 70 * esc, yy + 14 * esc, "PIN nuevo", ("pin",), False, None, 70 * esc)
        else:
            v._texto(px, yy + 6 * esc, "Control por celular apagado (actívalo en CONTROLES).", 8, tema.TENUE)
    return [(44 * esc, f)]


def _f_estados_colores(v, esc):
    cols = ajustes.obtener("estado_colores")
    bloques = []
    for est in ESTADOS:
        def f(px, yy, bw, est=est):
            col = cols.get(est)
            nombre, base = v.etiqueta_estado(est)
            v._texto(px, yy + 8 * esc, NOMBRES_ESTADO[est], 10, tema.TEXTO)
            sw = 20 * esc
            x0 = px + bw - sw
            v._redondo(x0, yy - 1 * esc, x0 + sw, yy + sw - 1 * esc, 5 * esc, fill=col or base, outline=tema.BORDE)
            v.zonas.append((x0, yy - 1 * esc, x0 + sw, yy + sw, ("estadocolor", est)))
            if col:
                v._chip(x0 - 66 * esc, yy - 2 * esc, "quitar", ("estadocolor_quitar", est), False, None, 58 * esc)
        bloques.append((26 * esc, f))
    return bloques


def _f_fondo(v, esc):
    def f(px, yy, bw):
        nombre = ajustes.obtener("fondo")
        lista = fondos.listar()
        v._texto(px, yy + 8 * esc, "Fondo", 10, tema.TEXTO)
        v._texto(px + bw, yy + 8 * esc, (nombre or "ninguno")[:24], 9, tema.MORADO_CLARO if nombre else tema.TENUE, ancla="e")
        x = px
        x = v._chip(x, yy + 24 * esc, "◀", ("fondo", "ant"), False, None, 30 * esc) + 6 * esc
        x = v._chip(x, yy + 24 * esc, "▶", ("fondo", "sig"), False, None, 30 * esc) + 6 * esc
        v._chip(x, yy + 24 * esc, "ninguno", ("fondo", "ninguno"), not nombre)
        pil, video = fondos.soporte()
        if not lista:
            msg, col = "Copia imágenes, GIF o videos a Database/fondos", tema.TENUE
        elif not pil:
            msg, col = "Falta Pillow: pip install pillow", tema.ROJO_CLARO
        elif nombre and nombre.lower().endswith(fondos.VIDEOS) and not video:
            msg, col = "Para video: pip install opencv-python", tema.ROJO_CLARO
        else:
            msg, col = f"{len(lista)} fondo(s) en Database/fondos", tema.TENUE
        v._texto(px, yy + 62 * esc, msg, 8, col)
    return [(74 * esc, f)]


def _f_sistema_ocultar(v, esc):
    oc = set(ajustes.obtener("sistema_ocultar"))
    bloques = []
    for clave, etq in (("cpu", "CPU"), ("ram", "RAM"), ("disco", "Disco"), ("bateria", "Batería"), ("grafica", "Gráfica de actividad")):
        def f(px, yy, bw, clave=clave, etq=etq):
            v._texto(px, yy + 8 * esc, "Mostrar " + etq, 10, tema.TEXTO)
            accion = ("sis_ocultar", clave)
            v._interruptor(px + bw, yy + 12 * esc, clave not in oc, accion, esc)
            v.zonas.append((px, yy, px + bw, yy + 28 * esc, accion))
        bloques.append((32 * esc, f))
    return bloques


def _f_nav_orden(v, esc):
    orden = v.pestanas_ordenadas(todas=True)
    bloques = []
    ocultas = set(ajustes.obtener("nav_ocultas"))
    for i, (clave, nombre, _c) in enumerate(orden):
        def f(px, yy, bw, clave=clave, nombre=nombre, i=i):
            v._texto(px, yy + 8 * esc, nombre.title(), 10, tema.TEXTO if clave not in ocultas else tema.TENUE)
            x = px + bw
            if clave != "ajustes":
                v._interruptor(x, yy + 12 * esc, clave not in ocultas, ("nav", "ocultar", clave), esc)
                v.zonas.append((x - 40 * esc, yy, x, yy + 28 * esc, ("nav", "ocultar", clave)))
            else:
                v._texto(x, yy + 8 * esc, "siempre visible", 8, tema.TENUE, ancla="e")
            v._chip(x - 130 * esc, yy - 2 * esc, "▲", ("nav", "subir", clave), False, None, 26 * esc)
            v._chip(x - 100 * esc, yy - 2 * esc, "▼", ("nav", "bajar", clave), False, None, 26 * esc)
        bloques.append((32 * esc, f))
    return bloques


def _f_atajos(v, esc):
    nombres = {"buscador": "Buscador de comandos", "editor": "Editor de diseño", "tv": "Pantalla completa", "deshacer": "Deshacer", "rehacer": "Rehacer"}
    at = ajustes.obtener("atajos")
    bloques = []
    for clave, etq in nombres.items():
        def f(px, yy, bw, clave=clave, etq=etq):
            v._texto(px, yy + 8 * esc, etq, 10, tema.TEXTO)
            v._chip(px + bw - 150 * esc, yy - 2 * esc, str(at.get(clave, ajustes.DEFAULTS["atajos"].get(clave, ""))), ("prefill", f"atajo {clave} "), False, None, 150 * esc)
        bloques.append((30 * esc, f))
    bloques.append((22 * esc, lambda px, yy, bw: v._texto(px, yy + 8 * esc, "Toca uno y escribe la combinación (ej. «Ctrl+Shift+K»).", 8, tema.TENUE)))
    return bloques


def _f_rendimiento_info(v, esc):
    def f(px, yy, bw):
        act = rendimiento.activo()
        v._texto(px, yy + 8 * esc, "Modo ahorro: " + ("ACTIVO" if act else "apagado"), 10, tema.MORADO_CLARO if act else tema.TENUE, negrita=act)
        v._texto(px, yy + 24 * esc, "Lo que aligera: " + rendimiento.descripcion_ahorro(), 8, tema.TENUE, ancho=int(bw))
        ms = v.ms_cuadro
        if ms:
            v._texto(px, yy + 64 * esc, f"Último cuadro: {ms:.0f} ms (objetivo {v.intervalo_objetivo():.0f} ms)", 8, tema.TENUE)
    return [(84 * esc, f)]


def _f_perfiles(v, esc):
    lista = perfiles.listar()
    bloques = []
    for n, desc, integrado in lista:
        def f(px, yy, bw, n=n, desc=desc, integrado=integrado):
            activo = n == perfiles.activo()
            v._texto(px, yy + 8 * esc, n + ("  ◀ activo" if activo else ""), 10, tema.MORADO_CLARO if activo else tema.TEXTO, negrita=activo)
            v._texto(px, yy + 23 * esc, (desc + (" (fábrica)" if integrado else ""))[:int(bw / (8 * esc * 0.6)) - 10], 8, tema.TENUE)
            if not activo:
                v._chip(px + bw - 70 * esc, yy + 2 * esc, "usar", ("perfil", n), False, None, 62 * esc)
        bloques.append((40 * esc, f))
    return bloques


def _f_archivos_export(v, esc):
    carpeta = lenguaje.carpeta_export()
    try:
        archivos = sorted(f for f in os.listdir(carpeta) if f.endswith(".json"))[-8:]
    except Exception:
        archivos = []
    bloques = []
    if not archivos:
        return [(30 * esc, lambda px, yy, bw: v._texto(px, yy + 8 * esc, "Nada que importar todavía (Database/interfaz).", 9, tema.TENUE))]
    for a in archivos:
        def f(px, yy, bw, a=a):
            v._texto(px, yy + 8 * esc, a[:int(bw / (9 * esc * 0.6)) - 10], 9, tema.TEXTO)
            v._chip(px + bw - 70 * esc, yy - 2 * esc, "importar", ("importar", a), False, None, 70 * esc)
        bloques.append((28 * esc, f))
    return bloques


def _f_puntos(v, esc):
    pts = ev.listar_puntos()[:8]
    if not pts:
        return [(30 * esc, lambda px, yy, bw: v._texto(px, yy + 8 * esc, "Aún sin puntos. Se crean solos antes de cambios grandes.", 9, tema.TENUE))]
    bloques = []
    for n, auto, ts in pts:
        def f(px, yy, bw, n=n, auto=auto, ts=ts):
            v._texto(px, yy + 8 * esc, n[:20] + (" (auto)" if auto else ""), 10, tema.TEXTO)
            v._texto(px, yy + 23 * esc, time.strftime("%d/%m/%Y %H:%M", time.localtime(ts)), 8, tema.TENUE)
            v._chip(px + bw - 70 * esc, yy - 2 * esc, "restaurar", ("punto", "restaurar", n), False, None, 70 * esc)
            v._chip(px + bw - 106 * esc, yy - 2 * esc, "✕", ("punto", "borrar", n), False, None, 30 * esc)
        bloques.append((38 * esc, f))
    return bloques


def _f_sync(v, esc):
    def f(px, yy, bw):
        carpeta = ajustes.obtener("sync_carpeta")
        v._texto(px, yy + 8 * esc, "Carpeta: " + (carpeta or "sin configurar (local)"), 9, tema.TEXTO if carpeta else tema.TENUE, ancho=int(bw))
        v._chip(px, yy + 28 * esc, "Elegir carpeta…", ("prefill", "sincroniza con "), False, None, 120 * esc)
        if carpeta:
            v._chip(px + 128 * esc, yy + 28 * esc, "Subir", ("orden", "sube la sincronizacion"), False, None, 60 * esc)
            v._chip(px + 194 * esc, yy + 28 * esc, "Bajar", ("orden", "trae la sincronizacion"), False, None, 60 * esc)
        v._texto(px, yy + 62 * esc, "Solo viaja el aspecto (ajustes visuales, temas, perfiles); nunca tus datos ni los del asistente.", 8, tema.TENUE, ancho=int(bw))
    return [(90 * esc, f)]


def _f_extensiones(v, esc):
    lista = extensiones.listar()
    bloques = []
    if not lista:
        bloques.append((30 * esc, lambda px, yy, bw: v._texto(px, yy + 8 * esc, "No hay extensiones instaladas.", 9, tema.TENUE)))
    for n, tp, perm in lista:
        def f(px, yy, bw, n=n, tp=tp, perm=perm):
            on = extensiones.activa(n)
            v._texto(px, yy + 8 * esc, n, 10, tema.TEXTO)
            v._texto(px, yy + 23 * esc, f"{tp} · " + ("permisos: " + ", ".join(perm) if perm else "sin permisos"), 8, tema.AZUL_CLARO if perm else tema.TENUE)
            v._chip(px + bw - 62 * esc, yy - 2 * esc, "quitar", ("orden", f"quita la extension {n}"), False, None, 62 * esc)
            etq, orden = ("Activada", f"desactiva la extension {n}") if on else ("Desactivada", f"activa la extension {n}")
            v._chip(px + bw - 62 * esc - 94 * esc, yy - 2 * esc, etq, ("orden", orden), on, tema.OK if on else None, 88 * esc)
        bloques.append((44 * esc, f))
    for e in extensiones.errores[:3]:
        bloques.append((28 * esc, lambda px, yy, bw, e=e: v._texto(px, yy + 8 * esc, "Rechazada: " + e, 8, tema.ROJO_CLARO, ancho=int(bw))))
    bloques.append((34 * esc, lambda px, yy, bw: (v._chip(px, yy, "Volver a buscar", ("ext_scan",), False, None, 110 * esc),
                                                  v._chip(px + 118 * esc, yy, "Instalar…", ("prefill", "importa extension "), False, None, 80 * esc))))
    return bloques


_FN = {"temas": _f_temas, "colores_tema": _f_colores_tema, "temas_horario": _f_temas_horario, "fuente": _f_fuente,
       "componentes": _f_componentes, "agregar_widget": _f_agregar_widget, "opciones_widget": _f_opciones_widget,
       "pantallas": _f_pantallas, "celular": _f_celular, "estados_colores": _f_estados_colores, "fondo": _f_fondo,
       "sistema_ocultar": _f_sistema_ocultar, "nav_orden": _f_nav_orden, "atajos": _f_atajos,
       "rendimiento_info": _f_rendimiento_info, "perfiles": _f_perfiles, "archivos_export": _f_archivos_export,
       "puntos": _f_puntos, "sync": _f_sync, "extensiones": _f_extensiones}


# ------------------------------------------------------------------ acciones
def _paso_num(clave, delta):
    if clave in ("_margen", "_separacion"):
        lay = perfiles.layout_actual()
        k = "margen" if clave == "_margen" else "separacion"
        lo, hi = (4, 60) if k == "margen" else (0, 40)
        lay[k] = max(lo, min(hi, int(lay.get(k, 22 if k == "margen" else 14)) + delta))
        perfiles.marcar_sucio()
        return
    ajustes.fijar(clave, ajustes.obtener(clave) + delta)


def ejecutar(v, accion):
    """Ejecuta la accion de un boton del centro. Devuelve True si la conocia."""
    if not isinstance(accion, tuple) or not accion:
        return False
    t = accion[0]
    lay = perfiles.layout_actual()
    if t == "aj":
        ev.punto_de_control(f"{accion[1]}")
        if accion[1] == "tema" and not tema.existe(accion[2]):
            return True
        ajustes.fijar(accion[1], accion[2])
        return True
    if t == "ajalt":
        ev.punto_de_control(accion[1])
        ajustes.alternar(accion[1])
        if accion[1] in ("alto_contraste",):
            tema.aplicar(ajustes.obtener("tema"))
        return True
    if t == "num":
        ev.punto_de_control(accion[1])
        _paso_num(accion[1], accion[2])
        return True
    if t == "ev":
        ok, msg = (ev.deshacer() if accion[1] == "deshacer" else ev.rehacer())
        v.avisar(msg.capitalize(), "exito" if ok else "info")
        return True
    if t == "cat":
        v.centro_cat, v.centro_busqueda = accion[1], ""
        v.scroll["ajustes"] = 0
        v.busca.delete(0, "end")
        return True
    if t == "sel_widget":
        v.centro_sel = accion[1]
        return True
    if t == "orden":
        v.enviar_orden(accion[1])
        return True
    if t == "prefill":
        v.rellenar_entrada(accion[1])
        return True
    if t == "perfil":
        v.enviar_orden(f"perfil {accion[1]}")
        return True
    if t == "perfil_borrar":
        v.rellenar_entrada(f"borra perfil {perfiles.activo()}")
        return True
    if t == "tema_borrar":
        v.rellenar_entrada(f"borra el tema {tema.actual()}")
        return True
    if t == "tema_reset":
        ev.punto_de_control("restablecer colores")
        tema.restablecer_colores(tema.actual())
        tema.aplicar(tema.actual())
        return True
    if t == "importar":
        carpeta = lenguaje.carpeta_export()
        tipo = "perfil" if a_es(accion[1], ".perfil.json") else ("tema" if a_es(accion[1], ".tema.json") else "copia")
        v.enviar_orden(f"importa {tipo} {os.path.join(carpeta, accion[1])}")
        return True
    if t == "punto":
        v.enviar_orden(("restaura el punto " if accion[1] == "restaurar" else "borra el punto ") + accion[2])
        return True
    if t == "pantalla":
        d = dict(ajustes.obtener("pantallas"))
        if accion[2]:
            d[accion[1]] = accion[2]
        else:
            d.pop(accion[1], None)
        ajustes.fijar("pantallas", d)
        return True
    if t == "sis_ocultar":
        ev.punto_de_control("sistema")
        oc = set(ajustes.obtener("sistema_ocultar"))
        oc.symmetric_difference_update({accion[1]})
        ajustes.fijar("sistema_ocultar", sorted(oc))
        return True
    if t == "nav":
        orden = [c for c, _n, _x in v.pestanas_ordenadas(todas=True)]
        if accion[1] == "ocultar":
            oc = set(ajustes.obtener("nav_ocultas"))
            oc.symmetric_difference_update({accion[2]})
            oc.discard("ajustes")
            ajustes.fijar("nav_ocultas", sorted(oc))
        else:
            i = orden.index(accion[2])
            j = i - 1 if accion[1] == "subir" else i + 1
            if 0 <= j < len(orden):
                orden[i], orden[j] = orden[j], orden[i]
                ajustes.fijar("nav_orden", orden)
        return True
    if t == "ext_scan":
        extensiones.escanear()
        v.avisar(f"{len(extensiones.listar())} extensión(es) cargadas", "info")
        return True
    if t == "estadocolor":
        v.pedir_color("estado:" + accion[1])
        return True
    if t == "estadocolor_quitar":
        d = dict(ajustes.obtener("estado_colores"))
        d.pop(accion[1], None)
        ajustes.fijar("estado_colores", d)
        return True
    if t == "color":
        v.pedir_color("ajuste:" + accion[1])
        return True
    if t == "colorrol":
        v.pedir_color("rol:" + accion[1])
        return True
    if t == "editor":
        v.poner_editor(True)
        return True
    if t == "lay":
        return _ejecutar_lay(v, lay, accion)
    return False


def a_es(nombre, sufijo):
    return nombre.endswith(sufijo)


def _ejecutar_lay(v, lay, accion):
    op = accion[1]
    ev.punto_de_control("distribución")
    msg = ok = None
    if op == "alt":
        lay[accion[2]] = not lay.get(accion[2], True)
        ok = True
    elif op == "vis":
        w = layout.buscar(lay, accion[2])
        if w is None:
            return True
        ok, msg = layout.ocultar(lay, w["id"]) if (w["visible"] and not w.get("ventana")) else layout.mostrar(lay, w["id"])
    elif op == "dup":
        ok, msg = layout.duplicar(lay, accion[2])
    elif op == "quitar":
        ok, msg = layout.quitar(lay, accion[2])
    elif op == "add":
        ok, msg = layout.anadir(lay, accion[2])
    elif op == "op":
        w = layout.buscar(lay, accion[2])
        if w:
            ok, msg = layout.opcion(lay, w["id"], accion[3], w[accion[3]] + accion[4])
    elif op == "nivel":
        ok, msg = layout.opcion(lay, accion[2], "nivel", accion[3])
    elif op == "estilo":
        ok, msg = layout.opcion(lay, accion[2], "estilo", accion[3])
    elif op == "color":
        v.pedir_color("widget:" + accion[2])
        return True
    elif op == "colorquitar":
        ok, msg = layout.opcion(lay, accion[2], "color", "")
    elif op in ("frente", "fondo"):
        ok, msg = layout.al_frente(lay, accion[2], op == "frente")
    elif op == "desacoplar":
        v.pedir("desacoplar", accion[2])
        return True
    perfiles.marcar_sucio()
    if ok is False and msg:
        v.avisar(msg.capitalize(), "info")
    return True
