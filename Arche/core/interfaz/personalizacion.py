"""
personalizacion.py
------------------
Ubicacion: Arche/core/interfaz/personalizacion.py

TODAS las opciones de personalizacion de la interfaz nueva viven aqui.
Para agregar una opcion basta con UNA linea en la lista OPCIONES de abajo:

  - se guarda sola en config.json (con su valor por defecto y su regla),
  - aparece sola en Ajustes, en su seccion, con el control que le toca,
  - se puede exportar, importar y restablecer,
  - y se aplica sola en la pagina:
      * si le pones  css="--nombre"  la pagina crea esa variable CSS con el valor
        (y  unidad="px"  o "%" si hace falta), y
      * SIEMPRE pone el atributo  data-<clave>  en la pagina con el valor
        ("si"/"no" en los interruptores), para que lo uses en el CSS.

Ejemplo completo, una opcion nueva que hace las letras mas gruesas:

  1) aqui:
        interruptor("web_negrita", "Letra más gruesa", "Texto", False),

  2) en web/estilo.css (o en tu CSS propio, desde Ajustes):
        [data-web_negrita="si"] body { font-weight: 550; }

Y listo: reinicia Arché y ya esta en Ajustes. Otro ejemplo, con un deslizador:

        deslizador("web_margen", "Margen de las secciones", "Diseño", 28, 8, 64, css="--margen", unidad="px"),
        ...y en el CSS:   .seccion { padding-left: var(--margen); padding-right: var(--margen); }

Estilos rapidos: al final de este archivo esta ESTILOS. Cada estilo es un nombre,
una descripcion y los valores que pone de un clic. Copia uno y cambialo para crear el tuyo.

Tipos:  interruptor (si/no) · deslizador (numero) · eleccion (lista cerrada)
        color (#RRGGBB, "" = el del tema) · texto · lista (datos que maneja la pagina)
Este archivo es solo datos: no importa nada de Arché, asi que no puede romperla.
"""

OPCIONES = []


def _op(tipo, clave, etiqueta, seccion, defecto, **extra):
    d = {"tipo": tipo, "clave": clave, "etiqueta": etiqueta, "seccion": seccion, "defecto": defecto}
    d.update(extra)
    OPCIONES.append(d)
    return d


def interruptor(clave, etiqueta, seccion, defecto, ayuda="", css=None):
    return _op("bool", clave, etiqueta, seccion, bool(defecto), ayuda=ayuda, css=css)


def deslizador(clave, etiqueta, seccion, defecto, minimo, maximo, ayuda="", css=None, unidad=""):
    return _op("int", clave, etiqueta, seccion, int(defecto), min=minimo, max=maximo, ayuda=ayuda, css=css, unidad=unidad)


def eleccion(clave, etiqueta, seccion, defecto, opciones, ayuda="", css=None):
    """opciones: [(valor, "Texto que se ve"), ...]  (el valor va al atributo data-<clave>)."""
    return _op("opc", clave, etiqueta, seccion, defecto, opciones=[list(o) for o in opciones], ayuda=ayuda, css=css)


def color(clave, etiqueta, seccion, defecto="", ayuda="", css=None):
    return _op("hex", clave, etiqueta, seccion, defecto, ayuda=ayuda, css=css)


def texto(clave, etiqueta, seccion, defecto="", maximo=60, ayuda=""):
    return _op("txt", clave, etiqueta, seccion, defecto, max=maximo, ayuda=ayuda)


def lista(clave, defecto=None):
    """Datos que maneja la pagina con su propio editor (no salen como control en Ajustes)."""
    return _op("lista", clave, clave, "", list(defecto or []), oculto=True)


# =====================================================================
#  LAS OPCIONES  (agrega las tuyas donde quieras; el orden es el de Ajustes)
# =====================================================================

# ---- Lo esencial ----
eleccion("web_info", "Cantidad de información en pantalla", "Lo esencial", "equilibrada", [
    ("minima", "Mínima: casi solo la esfera y la conversación"), ("equilibrada", "Equilibrada"),
    ("completa", "Completa: todo a la vista")],
    ayuda="Lo que no se ve sigue a un clic. Cambia cuántos detalles salen en cada sección.")
eleccion("web_esfera", "Esfera en la pantalla de Arché", "Lo esencial", "grande", [
    ("grande", "Grande, en el centro"), ("pequena", "Pequeña, arriba"), ("oculta", "Oculta")])
eleccion("estilo_voz", "Forma de la esfera", "Lo esencial", "esfera", [
    ("esfera", "Esfera"), ("ondas", "Ondas de voz"), ("anillos", "Anillos"), ("nucleo", "Núcleo con órbitas"),
    ("geometrica", "Geométrica")], ayuda="Se ve en la pantalla de Arché, en la conversación y en la barra lateral.")
deslizador("web_luz", "Luz ambiental de la esfera", "Lo esencial", 60, 0, 100, css="--luz",
           ayuda="La ventana se tiñe con el color de lo que estoy haciendo: escuchar, pensar o hablar.")
eleccion("web_inicio", "Sección al abrir", "Lo esencial", "inicio", [
    ("inicio", "Arché"), ("hoy", "Hoy"), ("equipo", "Equipo"), ("mente", "Mente"), ("ajustes", "Ajustes"),
    ("ultima", "La última que usé")])

# ---- Colores ----
color("web_acento", "Color de acento", "Colores", "",
      ayuda="Botones, selección y detalles. Vacío = el del tema.")
color("web_acento_2", "Segundo color", "Colores", "",
      ayuda="Gráficas, barras y la esfera. Vacío = el del tema.")
eleccion("web_degradado", "Fondo de la ventana", "Colores", "ninguno", [
    ("ninguno", "Liso"), ("tema", "Degradado del tema"), ("aurora", "Aurora"), ("atardecer", "Atardecer"),
    ("oceano", "Océano"), ("bosque", "Bosque"), ("galaxia", "Galaxia"), ("carbon", "Carbón")],
    ayuda="Se combina con la imagen de fondo si pusiste una.")

# ---- Superficies ----
eleccion("web_superficie", "Estilo de los paneles", "Superficies", "suave", [
    ("plana", "Planos, sin caja"), ("suave", "Suaves"), ("vidrio", "Vidrio"), ("contorno", "Solo contorno")])
deslizador("web_radio", "Redondeo", "Superficies", 20, 4, 32, css="--radio", unidad="px")
deslizador("web_vidrio", "Transparencia", "Superficies", 14, 0, 70, css="--vidrio",
           ayuda="Con imagen o degradado de fondo se nota más.")
deslizador("web_desenfoque", "Desenfoque detrás de los paneles", "Superficies", 14, 0, 30, css="--desenfoque", unidad="px")
eleccion("web_densidad", "Espacio entre cosas", "Superficies", "comoda", [("compacta", "Compacto"), ("comoda", "Cómodo"),
                                                                          ("amplia", "Amplio")])
deslizador("web_ancho", "Ancho máximo del contenido", "Superficies", 1180, 820, 1800, css="--ancho-max", unidad="px")

# ---- Texto ----
eleccion("web_fuente", "Letra", "Texto", "sistema", [
    ("sistema", "Segoe UI (la de Windows)"), ("bahnschrift", "Bahnschrift (técnica)"), ("trebuchet", "Trebuchet"),
    ("verdana", "Verdana (muy legible)"), ("georgia", "Georgia (con serifa)"), ("cascadia", "Cascadia (de código)"),
    ("redondeada", "Redondeada")])
eleccion("web_titulos", "Tamaño del saludo y los títulos", "Texto", "normal",
         [("pequenos", "Pequeños"), ("normal", "Normales"), ("grandes", "Grandes")])
eleccion("web_peso", "Grosor del saludo", "Texto", "fino", [("fino", "Fino"), ("normal", "Normal"), ("grueso", "Grueso")])
interruptor("web_reloj_24h", "Hora en formato 24 h", "Texto", False)
interruptor("web_segundos", "Mostrar segundos en el reloj", "Texto", False)

# ---- Barra lateral ----
interruptor("web_lateral_compacta", "Solo iconos (los nombres salen al pasar el mouse)", "Barra lateral", True)
eleccion("web_lateral_lado", "Lado de la barra", "Barra lateral", "izquierda", [("izquierda", "Izquierda"), ("derecha", "Derecha")])
interruptor("web_lateral_contadores", "Contadores (mensajes nuevos, pendientes)", "Barra lateral", True)
lista("web_secciones")          # orden y visibilidad: [{"id": "hoy", "ver": true}, ...]

# ---- Pantalla de Arché ----
texto("web_saludo", "Saludo propio", "Pantalla de Arché", "", 60,
      ayuda="Vacío = «Buenos días», «Buenas tardes»… Usa {nombre} para tu nombre.")
interruptor("web_v_clima", "Vistazo: clima", "Pantalla de Arché", True)
interruptor("web_v_recordatorio", "Vistazo: próximo recordatorio", "Pantalla de Arché", True)
interruptor("web_v_pendientes", "Vistazo: pendientes", "Pantalla de Arché", True)
interruptor("web_v_pomodoro", "Vistazo: pomodoro en marcha", "Pantalla de Arché", True)
interruptor("web_v_equipo", "Vistazo: equipo (solo si va cargado)", "Pantalla de Arché", True)
interruptor("web_botones_dock", "Mis botones encima de la caja de texto", "Pantalla de Arché", True)
interruptor("web_sugerencias", "Sugerencias cuando la conversación está vacía", "Pantalla de Arché", True)
texto("web_ciudad", "Ciudad para el clima", "Pantalla de Arché", "Bogotá")

# ---- Conversación ----
eleccion("web_chat_diseno", "Diseño de la conversación", "Conversación", "libre", [
    ("libre", "Libre: sin cuadro, con las ondas arriba"), ("panel", "En un panel con borde"),
    ("escenario", "Centrada bajo la esfera grande")])
eleccion("web_ondas_chat", "Ondas de voz arriba de la conversación", "Conversación", "siempre", [
    ("siempre", "Siempre"), ("hablando", "Solo cuando hablo o pienso"), ("nunca", "Nunca")])
eleccion("web_avisos_fondo", "Lo que digo por mi cuenta (cargando, avisos…)", "Conversación", "agrupados", [
    ("agrupados", "En una línea pequeña que se puede abrir"), ("ocultos", "Solo en Mente › Actividad"),
    ("normales", "Como mensajes normales")])
eleccion("web_burbujas", "Forma de los mensajes", "Conversación", "redondeadas", [
    ("redondeadas", "Burbujas redondeadas"), ("cuadradas", "Cuadradas"), ("lineas", "Sin burbuja (con línea)"),
    ("abierta", "Abierta: mis respuestas sin caja")])
interruptor("web_avatar", "Mi esfera junto a mis mensajes", "Conversación", True)
interruptor("web_entendi", "Mostrar debajo de cada orden lo que entendí", "Conversación", True)
interruptor("web_enter_envia", "Enter envía el mensaje", "Conversación", True, ayuda="Shift+Enter hace una línea nueva.")
interruptor("web_sonido_envio", "Sonido suave al enviar", "Conversación", False)
interruptor("web_aviso_respuesta", "Avisarme si respondo mientras estás en otra sección", "Conversación", True)

# ---- Mascota ----
interruptor("mascota", "Mostrar la mascota", "Mascota", True)
eleccion("mascota_personaje", "Personaje", "Mascota", "chispa", [("chispa", "Chispa"), ("robot", "Robot"), ("gato", "Gato")])
texto("mascota_nombre", "Nombre de la mascota", "Mascota", "Chispa", 20)
deslizador("mascota_tamano", "Tamaño", "Mascota", 100, 50, 200)
interruptor("consejos", "Que me dé consejos de vez en cuando", "Mascota", True)
eleccion("mascota_frecuencia", "Cada cuánto da consejos", "Mascota", "normal",
         [("poca", "Poco (cada 8 min)"), ("normal", "Normal (cada 4 min)"), ("mucha", "Seguido (cada 2 min)")])
interruptor("mascota_reacciones", "Que reaccione a lo que hago", "Mascota", True,
            ayuda="Habla cuando hablo, piensa conmigo, celebra cuando terminas algo y se duerme si no la usas.")

# ---- Hoy ----
interruptor("web_clima", "Clima y pronóstico", "Hoy", True)
interruptor("web_noticias", "Titulares", "Hoy", True)
lista("web_hoy_pestanas")       # orden y visibilidad de las pestañas de Hoy

# ---- Pomodoro ----
deslizador("web_pomodoro_min", "Minutos de concentración", "Pomodoro", 25, 5, 90)
deslizador("web_descanso_min", "Minutos de descanso", "Pomodoro", 5, 1, 30)
interruptor("web_pomodoro_sonido", "Sonar al terminar", "Pomodoro", True)
interruptor("web_pomodoro_arche", "Que Arché lo diga en voz alta", "Pomodoro", False,
            ayuda="Al terminar le pide a Arché que te avise (si tiene la voz activa, lo dice).")

# ---- Datos de las funciones (los editan sus propios paneles) ----
lista("web_botones", [
    {"texto": "Modo estudio", "orden": "ejecuta la rutina estudio", "icono": "libro"},
    {"texto": "Noticias", "orden": "dame las noticias", "icono": "diario"},
    {"texto": "Diagnóstico", "orden": "hazme un diagnóstico del pc", "icono": "cpu"},
])


# =====================================================================
#  ESTILOS RÁPIDOS: un clic cambia varias opciones a la vez.
#  Para crear uno, copia un bloque y cambia los valores (las claves son las de arriba
#  o las de ajustes.py; lo que no pongas se queda como esté).
# =====================================================================
ESTILOS = {
    "Calma": {"descripcion": "Poca información, mucho aire y luz suave.",
              "valores": {"web_info": "minima", "web_esfera": "grande", "web_luz": 45, "web_superficie": "plana",
                          "web_densidad": "amplia", "web_peso": "fino", "web_degradado": "tema", "web_burbujas": "abierta"}},
    "Equilibrio": {"descripcion": "Lo de fábrica: claro y ordenado.",
                   "valores": {"web_info": "equilibrada", "web_esfera": "grande", "web_luz": 60, "web_superficie": "suave",
                               "web_densidad": "comoda", "web_peso": "fino", "web_degradado": "ninguno",
                               "web_burbujas": "redondeadas"}},
    "Centro de mando": {"descripcion": "Todo a la vista, compacto, para usar a diario.",
                        "valores": {"web_info": "completa", "web_esfera": "pequena", "web_luz": 35,
                                    "web_superficie": "contorno", "web_densidad": "compacta", "web_peso": "normal",
                                    "web_burbujas": "cuadradas", "web_lateral_compacta": False}},
    "Vidrio": {"descripcion": "Paneles translúcidos sobre un fondo de color.",
               "valores": {"web_superficie": "vidrio", "web_vidrio": 45, "web_desenfoque": 22, "web_degradado": "aurora",
                           "web_luz": 70}},
    "Neón": {"descripcion": "Oscuro con brillos intensos.",
             "valores": {"tema": "neon", "web_luz": 90, "web_superficie": "contorno", "web_degradado": "galaxia",
                         "web_fuente": "bahnschrift"}},
}


# ---------------------------------------------------------------------
def por_clave():
    return {o["clave"]: o for o in OPCIONES}


def secciones():
    """Nombres de seccion en el orden en que aparecen."""
    vistas = []
    for o in OPCIONES:
        if o["seccion"] and o["seccion"] not in vistas:
            vistas.append(o["seccion"])
    return vistas


# =====================================================================
#  MODOS (los perfiles de Arché: general, programar, trabajo...)
#  Al activar un modo por primera vez, la interfaz nueva toma estos valores.
#  Después, cada modo recuerda lo que cambies mientras está activo.
# =====================================================================
WEB_POR_MODO = {
    "general": {"web_info": "equilibrada", "web_esfera": "grande", "web_superficie": "suave"},
    "programar": {"web_info": "completa", "web_esfera": "pequena", "web_superficie": "contorno", "web_densidad": "compacta",
                  "web_fuente": "cascadia", "web_burbujas": "cuadradas", "chat_marcas_tiempo": True,
                  "web_inicio": "inicio", "web_luz": 30},
    "tecnico": {"web_info": "completa", "web_superficie": "contorno", "web_densidad": "compacta", "web_luz": 35},
    "trabajo": {"web_info": "equilibrada", "web_esfera": "pequena", "web_superficie": "suave", "web_inicio": "hoy"},
    "minimalista": {"web_info": "minima", "web_superficie": "plana", "web_densidad": "amplia", "web_luz": 40},
    "ambiente": {"web_info": "minima", "web_esfera": "grande", "web_luz": 45, "web_superficie": "plana"},
    "entretenimiento": {"web_info": "equilibrada", "web_luz": 90, "web_degradado": "galaxia", "web_superficie": "vidrio",
                        "web_vidrio": 40},
}
