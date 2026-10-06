"""
catalogo.py
-----------
Ubicacion: Arche/core/IA/catalogo.py

FUENTE UNICA de todo lo que Arche sabe hacer. Antes, el clasificador
solo conocia las ~17 intenciones que Ollama arma en comprender(); todo
lo demas (notas, calculadora, archivos, sistema, configuracion, estudio,
autorevision, Gran Sabio, examen...) se activaba SOLO con frases exactas
en main.py, asi que ninguna red podia aprenderlo.

Cada entrada del catalogo tiene:
  id           nombre de la intencion (es la etiqueta que aprenden las redes)
  dominio      grupo general (sistema, notas, archivos, ...)
  descripcion  que hace, en una frase (la usan Ollama-generador y Ollama-juez)
  comando      el comando CANONICO que main.py ya entiende. Con "{X}" si lleva
               un dato variable. None = lo maneja el flujo viejo (analizar()).
  argumento    que es el dato variable (o None)
  semillas     frases de ejemplo iniciales (con "{X}" donde va el dato)
  confirmar    True si conviene preguntar antes de ejecutar (acciones que borran)

El ENRUTADOR (enrutador_natural.py) usa esto para convertir una frase libre
("anotame que compre leche") en el comando canonico ("crea una nota compre leche")
y dejar que main.py haga el resto -- sin duplicar ni tocar ningun manejador.

Para sumar una capacidad nueva: agrega una entrada aca, corre
'sembrar catalogo' y 'entrenar a fondo'. Nada mas.
"""

import random
import re
import unicodedata

# Datos de ejemplo para rellenar el "{X}" de las semillas segun el tipo de dato.
RELLENOS = {
    "nota": ["compras", "ideas del proyecto", "tareas de la semana", "recetas", "reunion del lunes", "lista del mercado"],
    "archivo": ["informe final", "tarea de fisica", "fotos del viaje", "presupuesto", "curriculum"],
    "operacion": ["2+2", "15*4", "100/8", "raiz de 81", "7*6", "25% de 200"],
    "funcion": ["ultimo_calculo", "historial", "guardar_historial", "buscar", "resumen"],
    "tema": ["python", "arduino", "historia de colombia", "redes neuronales", "electronica"],
    "categoria": ["notas", "la calculadora", "archivos", "recordatorios", "programas"],
    "objetivo": ["limpiar las funciones sin uso", "mejorar el examen", "conectar mas comandos", "terminar el informe"],
    "id": ["cod_12", "cod_30", "cod_101"],
    "horas": ["2", "6", "12"],
    "busqueda": ["inteligencia artificial", "recetas de pasta", "universidad de cundinamarca", "robots con arduino", "clima en bogota"],
    "sitio": ["youtube", "google", "spotify", "chrome", "la calculadora"],
    "recordatorio": ["llamar al medico", "entregar el trabajo", "pagar el internet", "estudiar para el examen"],
    "dato": ["mi color favorito es el azul", "mi cumpleanos es en mayo", "vivo en bogota", "trabajo con arduino"],
    "texto": ["comprar leche", "revisar el correo", "llamar a mama"],
    # lo que se busca + el sitio al final (lo extrae la red / Ollama junto)
    "busqueda_sitio": ["gatos graciosos en youtube", "recetas de pasta en claude", "arduino en wikipedia",
                       "musica relajante en spotify", "tutorial de python en youtube", "restaurantes cerca en maps",
                       "robots en github", "zapatos en mercadolibre"],
    "sitio_web": ["mercadolibre", "amazon", "pinterest", "twitch", "netflix"],
    "navegador": ["chrome", "edge", "firefox", "brave", "opera"],
    "ventana": ["chrome", "spotify", "bloc de notas", "word", "discord", "el explorador"],
    "ventana_lado": ["chrome a la izquierda", "spotify a la derecha", "bloc de notas a la derecha"],
    "porcentaje": ["20", "30", "50", "70", "100"],
    "tecla": ["enter", "ctrl+c", "ctrl+t", "alt+tab", "f5", "esc"],
    "carpeta": ["descargas", "escritorio", "documentos", "imagenes", "musica", "videos"],
    "duracion": ["10 minutos", "25 minutos", "1 hora", "5 minutos", "45 minutos"],
    "hora_alarma": ["7 de la mañana", "6:30", "5 de la tarde", "10 de la noche"],
    "aviso_tiempo": ["20 minutos que saque la ropa", "1 hora que llame a mama", "10 minutos que apague el horno"],
    "rutina": ["estudio", "trabajo", "cine", "descanso"],
    "rutina_def": ["estudio: abre chrome, sube el brillo", "cine: pon el brillo al 30, silencia el sonido",
                   "trabajo: abre chrome, abre word"],
    "ciudad": ["bogota", "medellin", "cali", "madrid", "ciudad de mexico"],
    "voz_motor": ["natural", "del sistema"],
    "voz_nombre": ["gonzalo", "salome", "dalia", "jorge"],
    "tema_archivos": ["la tesis", "la universidad", "mi hoja de vida", "el proyecto de arduino"],
}

ENTRADAS = []
POR_ID = {}


def _e(id, dominio, comando, descripcion, semillas, argumento=None, confirmar=False, subdominio=None):
    entrada = {
        "id": id, "dominio": dominio, "comando": comando, "descripcion": descripcion,
        "argumento": argumento, "semillas": semillas, "confirmar": confirmar,
        "subdominio": subdominio,
    }
    ENTRADAS.append(entrada)
    POR_ID[id] = entrada


# ---------------------------------------------------------------- conversacion
_e("saludo", "conversacion", None, "saludar al asistente",
   ["hola", "buenos dias", "buenas tardes", "hey arche", "que mas", "hola como andas", "buenas noches"])
_e("presentacion", "conversacion", None, "preguntarle al asistente quien es o como se llama",
   ["quien eres", "presentate", "como te llamas", "que eres exactamente", "cuentame sobre ti", "dime quien eres tu"])
_e("conversar", "conversacion", None, "hacer una pregunta general, pedir una explicacion, una opinion o una traduccion",
   ["explicame que es una red neuronal", "como se hace el arroz", "cuanto espacio hay entre la tierra y la luna",
    "cual es la capital de francia", "dame un consejo para estudiar mejor", "que opinas de la inteligencia artificial",
    "traduce buenos dias al ingles", "cuentame un dato curioso", "por que el cielo es azul", "cuanto es la velocidad de la luz"])

# ---------------------------------------------------------------------- tiempo
_e("hora", "tiempo", None, "preguntar la hora actual",
   ["que hora es", "dime la hora", "me dices la hora", "que horas son", "hora actual", "sabes que hora es"])
_e("fecha", "tiempo", None, "preguntar la fecha o el dia de hoy",
   ["que fecha es hoy", "que dia es hoy", "a cuantos estamos", "dime la fecha", "en que fecha estamos", "que dia de la semana es"])

# ------------------------------------------------------------------------ web
_e("buscar", "web", None, "buscar informacion en internet sobre un tema",
   ["busca {X}", "investiga sobre {X}", "averigua {X} en internet", "buscame informacion de {X}", "googlea {X}", "encuentra informacion sobre {X}"],
   argumento="busqueda")
_e("abrir", "web", None, "abrir una pagina web o un programa",
   ["abre {X}", "entra a {X}", "abreme {X}", "ve a {X}", "inicia {X}", "ejecuta {X}"],
   argumento="sitio")
_e("buscar_en_sitio", "web", None,
   "buscar algo directamente dentro de un sitio o pagina concreta (youtube, claude, wikipedia, mercadolibre...); el contenido es lo que se busca seguido de 'en' y el sitio",
   ["busca {X}", "buscame {X}", "ponme {X}", "quiero ver {X}", "encuentrame {X}", "abre la busqueda de {X}"],
   argumento="busqueda_sitio")
_e("aprender_sitio_busqueda", "web", "aprende buscar en {X}", "ensenarle al asistente como se busca dentro de un sitio web nuevo",
   ["ensenate a buscar en {X}", "quiero que aprendas a buscar en {X}", "aprende a buscar dentro de {X}", "aprende como se busca en {X}"],
   argumento="sitio_web")

# ------------------------------------------------------------------ computador
_e("que_tengo_abierto", "computador", "que tengo abierto", "ver que navegadores y programas estan instalados y abiertos en el computador",
   ["que navegadores tengo abiertos", "que programas tengo abiertos", "que hay abierto en mi pc", "dime que tengo abierto", "tengo chrome abierto", "que ventanas tengo abiertas"])
_e("fijar_navegador", "computador", "usa siempre {X}", "dejar fijo un navegador para abrir todo sin preguntar en cual",
   ["abre todo siempre en {X}", "quiero que uses {X} siempre", "siempre abre en {X}", "deja {X} como mi navegador", "usa {X} para todo"],
   argumento="navegador")
_e("preguntar_navegador", "computador", "preguntame el navegador", "volver a preguntar en cual navegador abrir cada cosa cuando hay varios",
   ["pregunta siempre en que navegador abrir", "ya no uses siempre el mismo navegador", "vuelve a preguntarme el navegador", "quiero elegir el navegador cada vez"])

# ventanas (core/acciones_pc.py)
_e("enfocar_ventana", "computador", "pasa a {X}", "traer al frente una ventana o programa que ya esta abierto",
   ["cambia a la ventana de {X}", "trae {X} al frente", "enfoca {X}", "muestrame la ventana de {X}", "pasa a {X}", "activa la ventana de {X}"],
   argumento="ventana")
_e("minimizar_ventana", "computador", "minimiza {X}", "minimizar una ventana o programa abierto",
   ["esconde la ventana de {X}", "manda {X} a la barra de tareas", "oculta {X}", "minimiza la ventana de {X}", "quita {X} de la pantalla"],
   argumento="ventana")
_e("maximizar_ventana", "computador", "maximiza {X}", "maximizar una ventana o programa abierto para que ocupe toda la pantalla",
   ["pon {X} en pantalla completa", "agranda la ventana de {X}", "expande {X}", "haz mas grande {X}", "maximiza la ventana de {X}"],
   argumento="ventana")
_e("cerrar_ventana", "computador", "cierra {X}", "cerrar una ventana o programa que esta abierto",
   ["cierra la ventana de {X}", "cierra el programa {X}", "termina {X}", "quiero cerrar {X}", "ya no necesito {X}, cierralo"],
   argumento="ventana")
_e("mostrar_escritorio", "computador", "muestra el escritorio", "minimizar todas las ventanas para ver el escritorio",
   ["minimiza todo", "oculta todas las ventanas", "quiero ver el escritorio", "ve al escritorio", "despeja la pantalla"])
_e("acomodar_ventana", "computador", "acomoda {X}", "poner una ventana en la mitad izquierda o derecha de la pantalla",
   ["pon {X}", "ubica {X}", "ancla {X}", "mueve {X}", "pega {X}"],
   argumento="ventana_lado")

# sonido y reproduccion
_e("subir_volumen", "computador", "sube el volumen", "subir el volumen del computador",
   ["mas volumen", "aumenta el volumen", "subele al sonido", "que suene mas fuerte", "no se escucha, sube el sonido", "sube un poco el volumen"])
_e("bajar_volumen", "computador", "baja el volumen", "bajar el volumen del computador",
   ["menos volumen", "reduce el volumen", "bajale al sonido", "que suene mas bajito", "esta muy duro, baja el volumen", "baja un poco el volumen"])
_e("volumen_a", "computador", "pon el volumen al {X}", "dejar el volumen en un porcentaje exacto",
   ["deja el volumen en {X}", "volumen al {X} por ciento", "ajusta el sonido al {X}", "pon el sonido en {X}", "sube el volumen al {X}"],
   argumento="porcentaje")
_e("silenciar", "computador", "silencia el sonido", "silenciar o reactivar el sonido del computador",
   ["mutea el computador", "quita el sonido", "ponlo en silencio", "activa el sonido", "silencio"])
_e("pausar_reproducir", "computador", "pausa la musica", "pausar o reanudar la musica o el video que esta sonando",
   ["pon pausa", "reanuda la musica", "dale play", "pausa el video", "continua la reproduccion"])
_e("siguiente_cancion", "computador", "siguiente cancion", "pasar a la siguiente cancion o pista",
   ["pasa a la siguiente cancion", "salta esta cancion", "next", "pon la proxima cancion", "cambia de cancion"])
_e("cancion_anterior", "computador", "cancion anterior", "volver a la cancion o pista anterior",
   ["pon la cancion anterior", "regresa la cancion", "vuelve a la cancion anterior", "previous", "pon el tema anterior"])

# pantalla
_e("subir_brillo", "computador", "sube el brillo", "subir el brillo de la pantalla",
   ["mas brillo", "aumenta el brillo", "la pantalla esta muy oscura", "subele brillo a la pantalla", "sube un poco el brillo"])
_e("bajar_brillo", "computador", "baja el brillo", "bajar el brillo de la pantalla",
   ["menos brillo", "reduce el brillo", "la pantalla esta muy clara", "bajale el brillo", "baja un poco el brillo"])
_e("brillo_a", "computador", "pon el brillo al {X}", "dejar el brillo de la pantalla en un porcentaje exacto",
   ["deja el brillo en {X}", "brillo al {X} por ciento", "ajusta el brillo al {X}", "pon el brillo en {X}"],
   argumento="porcentaje")
_e("captura_pantalla", "computador", "toma una captura de pantalla", "tomar una captura de pantalla y guardarla como imagen",
   ["captura la pantalla", "haz un screenshot", "sacale una foto a la pantalla", "pantallazo", "guarda lo que se ve en pantalla"])

# teclado y mouse
_e("teclear_texto", "computador", "teclea {X}", "escribir un texto por el usuario en otra ventana, como si lo tecleara",
   ["escribe por mi {X}", "tipea {X}", "digita {X}", "teclea esto {X}"],
   argumento="texto")
_e("presionar_tecla", "computador", "presiona {X}", "presionar una tecla o un atajo de teclado en otra ventana",
   ["pulsa {X}", "oprime {X}", "aprieta {X}", "manda el atajo {X}"],
   argumento="tecla")

# el equipo
_e("bloquear_pc", "computador", "bloquea el pc", "bloquear el computador para que pida la clave",
   ["bloquea la pantalla", "bloquea el computador", "voy a salir, bloquea el equipo", "pon la pantalla de bloqueo"])
_e("apagar_pc", "computador", "apaga el pc", "apagar el computador",
   ["apaga el computador", "apaga el equipo", "quiero apagar la compu", "apaga todo", "apaga el portatil"])
_e("reiniciar_pc", "computador", "reinicia el pc", "reiniciar el computador",
   ["reinicia el computador", "reinicia el equipo", "reinicia la compu", "reiniciar todo", "reinicia el portatil"])
_e("cerrar_sesion", "computador", "cierra la sesion", "cerrar la sesion de usuario de Windows",
   ["cierra sesion", "sal de mi cuenta de windows", "cerrar sesion de windows", "cierra mi sesion"])
_e("suspender_pc", "computador", "suspende el pc", "poner el computador en suspension o hibernacion",
   ["suspende el equipo", "pon el computador a dormir", "duerme la compu", "hiberna el pc"])
_e("cancelar_apagado", "computador", "cancela el apagado", "cancelar un apagado o reinicio que ya se programo",
   ["cancela el reinicio", "ya no apagues el pc", "detén el apagado", "no apagues"])
_e("ver_bateria", "computador", "cuanta bateria tengo", "ver cuanta bateria queda y si esta cargando",
   ["como esta la bateria", "cuanta bateria me queda", "nivel de bateria", "estoy conectado al cargador"])
_e("ver_portapapeles", "computador", "que hay en el portapapeles", "ver el texto que esta copiado en el portapapeles",
   ["muestra el portapapeles", "que copie", "lee lo que copie", "dime lo que tengo copiado"])
_e("copiar_portapapeles", "computador", "copia al portapapeles {X}", "copiar un texto al portapapeles",
   ["guarda en el portapapeles {X}", "copia este texto {X}", "pon {X} en el portapapeles"],
   argumento="texto")
_e("abrir_carpeta", "computador", "abre la carpeta {X}", "abrir una carpeta del usuario como descargas, escritorio o documentos",
   ["abre mis {X}", "muestrame la carpeta de {X}", "quiero ver mis {X}", "abre el explorador en {X}"],
   argumento="carpeta")

# --------------------------------------------- la voz de Arché (core/voz.py)
_e("activar_voz", "computador", "activa la voz", "hacer que Arche hable en voz alta con sus respuestas",
   ["quiero que hables", "habla conmigo", "ya puedes hablar", "prende tu voz", "hablame en voz alta"])
_e("desactivar_voz", "computador", "desactiva la voz", "dejar de hablar en voz alta y responder solo en texto",
   ["no hables mas", "apaga tu voz", "modo silencioso", "quiero que respondas solo en texto"])
_e("callar", "computador", "calla", "dejar de hablar ahora mismo (la voz sigue activada)",
   ["callate", "silencio", "basta ya", "deja de hablar", "para de hablar"])
_e("repetir", "computador", "repite eso", "volver a decir en voz alta lo ultimo que Arche dijo",
   ["que dijiste", "repiteme lo ultimo", "lee eso en voz alta", "dilo otra vez"])
_e("probar_voz", "computador", "prueba la voz", "probar como suena la voz de Arche",
   ["como suena tu voz", "di hola", "testea la voz", "hazme una prueba de voz"])
_e("motor_voz", "computador", "usa la voz {X}", "cambiar el tipo de voz: natural (online, mas humana) o la del sistema (sin internet)",
   ["cambia a la voz {X}", "quiero la voz {X}", "pon la voz {X}"], argumento="voz_motor")
_e("elegir_voz", "computador", "usa la voz de {X}", "elegir una voz concreta de las naturales (gonzalo, salome, dalia...)",
   ["pon la voz de {X}", "quiero que hables como {X}", "cambia la voz a {X}"], argumento="voz_nombre")
_e("estado_voz", "computador", "estado de la voz", "ver si la voz esta activada, que motor usa y a que velocidad",
   ["estas hablando", "tienes voz", "como esta tu voz configurada"])
_e("velocidad_voz", "computador", "habla mas rapido", "hablar mas rapido o mas lento",
   ["habla mas lento", "habla mas despacio", "mas rapido por favor", "habla mas deprisa"])

# ----------------------------------------- alarmas y temporizadores (core/alarmas.py)
_e("crear_aviso", "computador", "avisame en {X}", "avisar al usuario dentro de un rato o a una hora, con un sonido y un mensaje",
   ["recuerdame en {X}", "dime en {X}", "avisame dentro de {X}"], argumento="aviso_tiempo")
_e("poner_alarma", "computador", "pon una alarma a las {X}", "poner una alarma que suene a una hora",
   ["despiertame a las {X}", "ponme una alarma para las {X}", "programa una alarma a las {X}"], argumento="hora_alarma")
_e("poner_temporizador", "computador", "pon un temporizador de {X}", "poner un temporizador o cronometro regresivo",
   ["temporizador de {X}", "ponme un timer de {X}", "cuenta {X} y avisame"], argumento="duracion")
_e("ver_alarmas", "computador", "mis alarmas", "ver las alarmas, avisos y temporizadores pendientes",
   ["que alarmas tengo", "muestrame mis temporizadores", "cuales son mis avisos pendientes"])
_e("cancelar_alarma", "computador", "cancela la alarma", "cancelar la proxima alarma o temporizador",
   ["borra la alarma", "quita el temporizador", "ya no quiero esa alarma"], confirmar=False)
_e("cancelar_todas_alarmas", "computador", "cancela todas las alarmas", "cancelar todas las alarmas, avisos y temporizadores",
   ["borra todas mis alarmas", "quita todos los temporizadores", "elimina todos los avisos"], confirmar=True)

# ------------------------------------------- rutinas y modos (core/rutinas.py)
_e("crear_rutina", "computador", "crea la rutina {X}", "crear una rutina: un nombre y una serie de ordenes que se lanzan juntas",
   ["guarda la rutina {X}", "arma la rutina {X}", "quiero una rutina {X}"], argumento="rutina_def")
_e("ejecutar_rutina", "computador", "ejecuta la rutina {X}", "lanzar una rutina o modo guardado (estudio, trabajo, cine...)",
   ["activa el modo {X}", "inicia la rutina {X}", "pon el modo {X}", "empieza la rutina {X}"], argumento="rutina")
_e("ver_rutinas", "computador", "mis rutinas", "ver las rutinas o modos que el usuario tiene guardados",
   ["que rutinas tengo", "muestrame mis modos", "lista mis rutinas"])
_e("ver_rutina", "computador", "que hace la rutina {X}", "ver los pasos de una rutina",
   ["que tiene el modo {X}", "muestrame la rutina {X}", "que pasos tiene la rutina {X}"], argumento="rutina")
_e("borrar_rutina", "computador", "borra la rutina {X}", "borrar una rutina guardada",
   ["elimina la rutina {X}", "quita el modo {X}"], argumento="rutina", confirmar=True)

# --------------------------- mantenimiento del PC (core/pc_avanzado.py)
_e("diagnostico_pc", "computador", "dame un diagnostico de mi pc", "resumen del estado del PC: CPU, memoria, disco, bateria y que gasta mas",
   ["como esta mi computador", "revisa mi pc", "esta lento mi pc", "chequeo del equipo", "estado completo del pc"])
_e("programas_cpu", "computador", "que consume mas cpu", "ver que programas gastan mas procesador",
   ["que esta gastando el procesador", "que programa pone lento el pc", "quien usa mas cpu"])
_e("programas_memoria", "computador", "que consume mas memoria", "ver que programas gastan mas memoria RAM",
   ["que usa mas ram", "quien se come la memoria", "que programa gasta mas ram"])
_e("liberar_memoria", "computador", "libera memoria", "mostrar lo mas pesado y cerrar lo que el usuario elija para liberar RAM",
   ["libera ram", "cierra lo que mas consume", "quiero liberar memoria"], confirmar=True)
_e("espacio_discos", "computador", "espacio de mis discos", "ver cuanto espacio libre queda en cada disco",
   ["cuanto espacio me queda en los discos", "capacidad de mis discos", "cuanto disco tengo libre"])
_e("archivos_grandes", "computador", "que ocupa mas espacio", "encontrar los archivos mas grandes del PC",
   ["cuales son mis archivos mas pesados", "que archivos gastan mas disco", "que pesa mas en mi pc"])
_e("buscar_duplicados", "computador", "busca archivos duplicados", "encontrar archivos repetidos para liberar espacio",
   ["hay archivos repetidos", "detecta duplicados", "revisa si tengo archivos repetidos"])
_e("mover_duplicados", "computador", "mueve los duplicados a la papelera", "mover los archivos duplicados a la papelera de Arche (se pueden restaurar)",
   ["limpia los archivos duplicados", "manda los repetidos a la papelera"], confirmar=True)
_e("descargas_viejas", "computador", "revisa mis descargas", "ver que hay de viejo en la carpeta de descargas",
   ["que hay en mis descargas", "analiza mis descargas", "descargas viejas"])
_e("limpiar_descargas", "computador", "limpia las descargas viejas", "mover las descargas viejas a la papelera de Arche",
   ["ordena mis descargas", "borra lo viejo de descargas"], confirmar=True)
_e("analizar_limpieza", "computador", "que puedo limpiar", "ver cuanta basura (temporales, cache) se puede limpiar sin riesgo",
   ["cuanta basura tengo", "que puedo borrar sin problema", "analiza la limpieza"])
_e("limpiar_pc", "computador", "limpia todo", "limpiar archivos temporales, cache y pycache",
   ["limpia los temporales", "limpia el cache", "borra los archivos temporales"], confirmar=True)
_e("buscar_archivos_tema", "computador", "busca mis archivos sobre {X}", "buscar archivos del usuario por nombre y por contenido sobre un tema",
   ["encuentrame mis archivos de {X}", "dame los archivos sobre {X}", "donde estan mis archivos de {X}"], argumento="tema_archivos")
_e("restaurar_papelera", "computador", "restaura la papelera de arche", "devolver a su sitio lo que Arche movio a su papelera",
   ["deshaz la limpieza", "recupera lo que moviste", "devuelve lo que limpiaste"])

# ------------------------------ internet y cerebro online (core/IA/cerebro.py)
_e("clima", "web", "como esta el clima en {X}", "decir el clima actual y el pronostico de una ciudad (usa internet)",
   ["que clima hace en {X}", "va a llover en {X}", "temperatura en {X}", "como esta el tiempo en {X}"], argumento="ciudad")
_e("noticias", "web", "dame las noticias de {X}", "traer titulares de noticias de un tema (usa internet)",
   ["que hay de nuevo en {X}", "noticias de {X}", "cuentame las noticias de {X}"], argumento="tema")
_e("investigar", "web", "investiga {X}", "investigar un tema en internet y resumirlo con fuentes",
   ["averigua sobre {X}", "busca informacion y resumeme {X}", "hazme un resumen de {X}"], argumento="tema")
_e("conectar_nube", "configuracion", "conecta la nube", "poner la clave del modelo en la nube para que Arche piense con el, dejando a Ollama de respaldo",
   ["usa un cerebro en internet", "conectate a internet para pensar", "pon la clave de la nube"])
_e("estado_nube", "configuracion", "estado de la nube", "ver si el modelo en la nube esta conectado y en que modo esta",
   ["estas conectado a la nube", "con que cerebro piensas", "que modelo usas ahora"])
_e("usar_nube", "configuracion", "usa la nube", "pensar con la nube cuando haya internet y con Ollama si no",
   ["piensa con la nube", "usa el modelo grande", "modo automatico de cerebro"])
_e("usar_ollama", "configuracion", "usa ollama", "pensar solo con Ollama local, sin usar la nube",
   ["no uses la nube", "piensa solo con ollama", "usa el modelo local"])

# --------------------------------------------------------------------- memoria
_e("recordar", "memoria", None, "pedirle al asistente que recuerde un dato personal",
   ["recuerda que {X}", "quiero que sepas que {X}", "guarda en tu memoria que {X}", "ten presente que {X}", "no olvides que {X}", "anota en tu memoria que {X}"],
   argumento="dato")
_e("mostrar_memoria", "memoria", None, "preguntar que datos personales recuerda el asistente",
   ["que recuerdas de mi", "que sabes de mi", "muestrame lo que recuerdas", "que tienes guardado en tu memoria", "dime que recuerdas"])
_e("editar_memoria", "memoria", None, "corregir o cambiar un dato que el asistente recuerda mal",
   ["corrige lo que recuerdas", "lo que sabes de mi esta mal", "cambia un dato de tu memoria", "quiero editar tu memoria", "actualiza lo que recuerdas de mi"])
_e("crear_recordatorio", "memoria", None, "crear un recordatorio o pendiente",
   ["recuerdame {X}", "avisame que tengo que {X}", "ponme un recordatorio para {X}", "crea un recordatorio {X}", "no me dejes olvidar {X}", "agenda un recordatorio de {X}"],
   argumento="recordatorio")
_e("mostrar_recordatorios", "memoria", None, "ver los recordatorios o pendientes que hay",
   ["que recordatorios tengo", "muestrame mis recordatorios", "que tengo pendiente", "cuales son mis pendientes", "lista mis recordatorios", "tengo algo pendiente"])
_e("completar_recordatorio", "memoria", None, "marcar un recordatorio como hecho",
   ["ya hice un pendiente", "marca un recordatorio como hecho", "complete un recordatorio", "ya cumpli una tarea pendiente", "tacha un recordatorio"])
_e("eliminar_recordatorio", "memoria", None, "borrar un recordatorio",
   ["borra un recordatorio", "elimina un recordatorio", "quita un pendiente", "ya no necesito un recordatorio", "cancela un recordatorio"])

# ----------------------------------------------------------------------- notas
_e("crear_nota", "notas", "crea una nota {X}", "crear una nota nueva con un nombre",
   ["anota {X}", "crea una nota llamada {X}", "haz una nota de {X}", "quiero guardar una nota sobre {X}", "apunta una nota {X}", "nueva nota {X}"],
   argumento="nota")
_e("leer_nota", "notas", "lee la nota {X}", "leer el contenido de una nota",
   ["leeme la nota {X}", "que dice la nota {X}", "muestrame la nota {X}", "ensename lo que dice la nota {X}", "dime el contenido de la nota {X}"],
   argumento="nota")
_e("abrir_nota", "notas", "abre la nota {X}", "abrir una nota para verla o editarla",
   ["abre mi nota {X}", "quiero editar la nota {X}", "abreme la nota {X}", "abre el archivo de la nota {X}"],
   argumento="nota")
_e("agregar_nota", "notas", "agrega a {X}", "agregar texto a una nota que ya existe",
   ["anade texto a la nota {X}", "escribe mas en la nota {X}", "agrega algo a {X}", "quiero sumarle texto a la nota {X}"],
   argumento="nota")
_e("eliminar_nota", "notas", "elimina la nota {X}", "borrar una nota",
   ["borra la nota {X}", "quita la nota {X}", "ya no quiero la nota {X}", "elimina mi nota {X}", "deshazte de la nota {X}"],
   argumento="nota", confirmar=True)
_e("listar_notas", "notas", "mis notas", "ver la lista de todas las notas guardadas",
   ["que notas tengo", "muestrame todas mis notas", "lista mis notas", "cuales son mis notas", "dime que notas he guardado"])

# -------------------------------------------------------------------- archivos
_e("actualizar_archivos", "archivos", "actualizar archivos", "actualizar el indice de archivos del computador",
   ["actualiza el indice de archivos", "vuelve a indexar mis archivos", "refresca la lista de archivos", "reindexa los archivos", "escanea mis archivos otra vez"])
_e("buscar_archivo", "archivos", "busca archivo {X}", "buscar un archivo o documento por su nombre",
   ["encuentra el archivo {X}", "donde esta el archivo {X}", "busca el documento {X}", "ubica el archivo {X}", "necesito encontrar {X} en mis archivos"],
   argumento="archivo")
_e("abrir_archivo", "archivos", "abre archivo {X}", "abrir un archivo o documento del computador",
   ["abre el archivo {X}", "abreme el documento {X}", "quiero abrir el archivo {X}", "abre mi documento {X}"],
   argumento="archivo")

# ------------------------------------------------------------------ calculadora
_e("calcular", "calculadora", "calcula {X}", "resolver una operacion matematica",
   ["cuanto es {X}", "resuelve {X}", "hazme la operacion {X}", "dime el resultado de {X}", "cuanto da {X}", "calculame {X}"],
   argumento="operacion")
_e("historial_calculos", "calculadora", "historial calculos", "ver el historial de calculos anteriores",
   ["muestrame mis calculos anteriores", "que cuentas hice", "ver el historial de operaciones", "ensename las operaciones que hice", "historial de la calculadora"])
_e("ultimo_calculo", "calculadora", "ultimo calculo", "ver el ultimo calculo que se hizo",
   ["cual fue mi ultimo calculo", "dime la ultima operacion que hice", "que fue lo ultimo que calcule", "cual fue la ultima cuenta"])

# --------------------------------------------------------------------- sistema
_e("estado_sistema", "sistema", "estado del sistema", "ver el estado del computador: procesador, memoria y disco",
   ["como esta mi pc", "como anda la computadora", "dime el estado del equipo", "cuanta memoria y cpu estoy usando", "como va el rendimiento de mi compu", "que tal esta el sistema"])
_e("procesos_consumen", "sistema", "procesos que mas consumen", "ver que programas consumen mas recursos",
   ["que programa esta gastando mas recursos", "que esta consumiendo mas memoria", "que proceso hace lenta mi pc", "muestrame que gasta mas cpu", "por que esta lenta la compu", "que programas usan mas ram"])
_e("espacio_disco", "sistema", "espacio libre", "ver cuanto espacio libre queda en el disco",
   ["cuanto espacio me queda en el disco", "cuanto almacenamiento tengo libre", "me queda espacio en el disco duro", "dime cuanto espacio libre hay", "cuanto disco tengo disponible", "estoy corto de espacio"])

# --------------------------------------------------------------- configuracion
_e("mostrar_config", "configuracion", "configuracion", "ver la configuracion actual del asistente",
   ["muestrame la configuracion", "como esta configurado todo", "ver mis ajustes", "que ajustes tengo", "abre la configuracion"])
_e("cambiar_nombre_usuario", "configuracion", "cambiar mi nombre", "cambiar el nombre con el que el asistente llama al usuario",
   ["quiero que me llames de otra forma", "cambiame el nombre", "no me llamo asi", "llamame distinto", "cambia como me dices"])
_e("cambiar_nombre_asistente", "configuracion", "cambiar tu nombre", "cambiar el nombre del asistente",
   ["quiero cambiarte el nombre", "te voy a poner otro nombre", "cambiate el nombre", "quiero llamarte diferente", "ponte otro nombre"])
_e("restablecer_config", "configuracion", "restablecer configuracion", "volver la configuracion a los valores originales",
   ["vuelve a la configuracion de fabrica", "resetea los ajustes", "deja todo como al principio", "reinicia la configuracion", "restaura los ajustes originales"],
   confirmar=True)

# ---------------------------------------------------------------------- codigo
_e("modificar_codigo", "codigo", None, "pedirle al asistente que cambie, arregle o mejore su propio codigo",
   ["arregla tu codigo", "mejora tu funcion de {X}", "agregate una funcion que {X}", "cambia como funciona {X}", "hazte una mejora en {X}", "quiero que modifiques tu codigo para que {X}"],
   argumento="funcion")
_e("revisar_cambios", "codigo", "revisar cambios de codigo", "revisar y aprobar los cambios de codigo propuestos",
   ["muestrame los cambios de codigo por aprobar", "quiero ver los cambios que propusiste", "revisemos las propuestas de codigo", "que cambios me quieres mostrar", "vamos a aprobar cambios"])
_e("cambios_pendientes", "codigo", "cambios de codigo pendientes", "ver cuantas propuestas de cambio de codigo hay pendientes",
   ["cuantas propuestas tienes pendientes", "lista las propuestas pendientes", "que cambios tienes armados", "hay cambios de codigo esperando"])
_e("autorevisar", "codigo", "revisate", "que el asistente revise su propio codigo buscando problemas",
   ["revisa tu propio codigo", "hazte una revision", "mira si tu codigo tiene problemas", "autoevaluate el codigo", "chequea tu codigo"])
_e("autorevisar_y_arreglar", "codigo", "revisate y arregla todo", "revisarse y dejar armados los arreglos de cada problema",
   ["revisate y deja los arreglos listos", "revisa tu codigo y prepara las correcciones", "hazte una revision completa con parches"],
   confirmar=True)
_e("analizar_funcion", "codigo", "analiza {X}", "analizar una funcion del proyecto: que hace, que devuelve, cuanto se usa",
   ["explicame que hace la funcion {X}", "analiza la funcion {X}", "dame la ficha de {X}", "que es {X} en tu codigo"],
   argumento="funcion")
_e("impacto_funcion", "codigo", "impacto {X}", "ver que partes del proyecto usan una funcion antes de cambiarla",
   ["que se rompe si cambio {X}", "quien usa la funcion {X}", "que tan importante es {X}", "que depende de {X}"],
   argumento="funcion")
_e("riesgo_propuesta", "codigo", "riesgo {X}", "ver que tan riesgosa es una propuesta de cambio",
   ["que tan riesgosa es la propuesta {X}", "evalua el riesgo de {X}", "es peligroso aprobar {X}"],
   argumento="id")

# ----------------------------------------------------------------------- arche
_e("ayuda", "arche", "ayuda", "preguntar que sabe hacer el asistente",
   ["ayuda", "que puedes hacer", "en que me puedes ayudar", "cuales son tus funciones", "muestrame lo que sabes hacer", "necesito ayuda"])
_e("ayuda_categoria", "arche", "que hace {X}", "preguntar que hace o para que sirve una parte del asistente",
   ["que hace {X}", "para que sirve {X}", "explicame que hace la parte de {X}", "que puedes hacer con {X}"],
   argumento="categoria")
_e("estudiar", "arche", "estudiar", "hacer una ronda de estudio",
   ["ponte a estudiar", "estudia un rato", "repasa lo que sabes", "haz una ronda de estudio"])
_e("iniciar_estudio", "arche", "iniciar estudio automatico", "activar el estudio en segundo plano",
   ["empieza a estudiar sola", "estudia en segundo plano", "activa el estudio automatico", "ponte a estudiar todo el tiempo"])
_e("detener_estudio", "arche", "detener estudio", "parar el estudio",
   ["deja de estudiar", "para el estudio", "ya no estudies", "detene el estudio"])
_e("temas_estudio", "arche", "temas de estudio", "ver los temas que estudia el asistente",
   ["que temas estudias", "cuales son tus temas de estudio", "muestrame tus temas", "sobre que estudias"])
_e("agregar_tema", "arche", "agregar tema {X}", "agregar un tema nuevo a los temas de estudio",
   ["quiero que estudies {X}", "aprende sobre {X}", "anade {X} a tus temas de estudio", "estudia el tema {X}"],
   argumento="tema")
_e("estado_red", "arche", "estado red", "ver el estado de la red neuronal clasica",
   ["como va tu red neuronal", "que tan buena es tu red", "muestrame el estado del clasificador", "estado de la red"])
_e("estadisticas", "arche", "estadisticas", "ver estadisticas de uso del asistente",
   ["como te ha ido con los comandos", "dame tus estadisticas de uso", "cuantos comandos has procesado", "muestrame tus numeros"])
_e("limpiar_conocimiento", "arche", "limpiar automatico", "limpiar del conocimiento los aprendizajes contaminados o malos",
   ["limpia los datos contaminados", "depura lo que aprendiste mal", "borra los aprendizajes malos", "haz una limpieza de tu conocimiento"],
   confirmar=True)
_e("autorevision_on", "arche", "iniciar autorevision automatica", "activar la autorevision automatica en segundo plano",
   ["activa la autorevision automatica", "revisate sola cada cierto tiempo", "empieza a autorevisarte sola"])
_e("autorevision_off", "arche", "detener autorevision automatica", "desactivar la autorevision automatica",
   ["desactiva la autorevision", "deja de autorevisarte sola", "para la autorevision automatica"])
_e("entrenar_jerarquico", "arche", "entrenar jerarquico", "entrenar las redes jerarquicas con lo aprendido",
   ["entrena tus redes", "reentrena el clasificador jerarquico", "actualiza tus miniredes", "entrena las redes por dominio"])
_e("estado_jerarquico", "arche", "estado red jerarquica", "ver el estado de las redes jerarquicas",
   ["como van tus miniredes", "estado de las redes por dominio", "que tan buenas son tus redes jerarquicas"])
_e("examen", "arche", "examen", "rendir una ronda de examen para evaluar el clasificador",
   ["rinde un examen", "ponte a prueba", "hazte un examen", "evaluate ahora"])
_e("estado_examen", "arche", "estado examen", "ver el progreso del examen y los niveles",
   ["como vas en el examen", "en que nivel estas", "muestrame tu progreso del examen", "como va el aula de entrenamiento"])
_e("examen_on", "arche", "iniciar examen automatico", "activar el examen automatico en segundo plano",
   ["activa el examen automatico", "examinate sola en segundo plano", "empieza a examinarte sola"])
_e("examen_off", "arche", "detener examen automatico", "desactivar el examen automatico",
   ["desactiva el examen automatico", "deja de examinarte", "para los examenes"])
_e("objetivos", "arche", "objetivos", "ver los objetivos pendientes del proyecto",
   ["que objetivos tenemos pendientes", "cuales son nuestras metas", "muestrame los objetivos", "que metas faltan"])
_e("agregar_objetivo", "arche", "objetivo: {X}", "agregar un objetivo nuevo al proyecto",
   ["anota como objetivo {X}", "nueva meta {X}", "agrega un objetivo {X}", "quiero lograr {X}"],
   argumento="objetivo")
_e("objetivo_logrado", "arche", "logre {X}", "marcar un objetivo como logrado",
   ["ya cumpli {X}", "marca como logrado {X}", "termine {X}", "objetivo cumplido {X}"],
   argumento="objetivo")
_e("entrenar_fondo", "arche", "entrenar a fondo", "generar muchos ejemplos con Ollama y entrenar las redes a fondo",
   ["entrena a fondo", "pasate un rato generando ejemplos", "quiero que practiques muchas frases", "entrenamiento intensivo"],
   confirmar=True)
_e("estado_banco", "arche", "estado banco", "ver cuantos ejemplos tiene cada intencion",
   ["cuantos ejemplos tienes", "muestrame tu banco de ejemplos", "cuantas frases has aprendido por intencion"])


# ====================================================================== utilidades

# Comandos fijos de main.py que no salen de una entrada del catalogo (alias, salidas...)
EXTRA_FIJOS_EXACTOS = {
    "adios", "salir", "configuracion", "mostrar configuracion", "restablecer configuracion",
    "estado de la red", "estado del clasificador", "estado clasificador", "telemetria",
    "mis notas", "listar notas", "historial calculos", "revisa tu codigo", "autorevisate",
    "revisa tu codigo sin ia", "revisate y arregla", "sembrar catalogo", "detener entrenamiento",
    "estado del examen", "rendir examen", "mis temas", "mis objetivos", "modo natural on",
    "modo natural off", "modo gran sabio on", "modo gran sabio off", "entrenar clasificador jerarquico",
    "estado clasificador jerarquico", "activar examen automatico", "activar estudio automatico",
    "activar autorevision automatica", "ayuda",
    "comandos", "guia", "guia de comandos", "lista de comandos", "que comandos hay",
    "proximos pasos", "que hago ahora", "que me falta", "siguiente paso",
    "importar ejemplos", "intenciones", "lista de intenciones", "mis intenciones",
}
EXTRA_FIJOS_PREFIJOS = (
    "escribe en ", "cambia esto", "mejora esto", "arregla esto", "cuanto es ", "conecta ", "conectar ",
    "autorevisate cada", "entrenar a fondo", "que hace ", "modo gran sabio",
    "comandos ", "ensenar ", "importar ejemplos", "intenciones de ",
)


def normalizar(texto):
    """minusculas, sin tildes, sin signos, espacios simples."""
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[¿?¡!.,;]", "", texto)
    return " ".join(texto.split())


def descripcion_de(id_intencion):
    entrada = POR_ID.get(id_intencion)
    return entrada["descripcion"] if entrada else None


def dominios_del_catalogo():
    resultado = {}
    for e in ENTRADAS:
        resultado.setdefault(e["dominio"], []).append(e["id"])
    return resultado


def _prefijo_fijo(comando):
    return normalizar(comando.split("{X}")[0])


def es_comando_fijo(texto):
    """True si `texto` ya es un comando que main.py entiende tal cual (exacto o
    por prefijo). El enrutador NO toca esos: van directo a su manejador."""
    norm = normalizar(texto)
    if norm in EXTRA_FIJOS_EXACTOS or norm.startswith(EXTRA_FIJOS_PREFIJOS):
        return True
    for e in ENTRADAS:
        comando = e["comando"]
        if not comando:
            continue
        if "{X}" in comando:
            prefijo = _prefijo_fijo(comando)
            if prefijo and norm.startswith(prefijo):
                return True
        elif norm == normalizar(comando):
            return True
    return False


def armar_comando(entrada, argumento=""):
    """Comando canonico listo para main.py: 'crea una nota {X}' + 'compras' -> 'crea una nota compras'.
    None si la entrada no tiene comando canonico (la maneja el flujo viejo)."""
    comando = entrada.get("comando")
    if not comando:
        return None
    return comando.replace("{X}", argumento).strip()


def expandir_semillas(entrada, max_por_semilla=2, rng=None):
    """[(frase, contenido)] con el '{X}' rellenado con datos de ejemplo. Las
    semillas sin '{X}' salen tal cual con contenido ''."""
    rng = rng or random
    resultado = []
    rellenos = RELLENOS.get(entrada.get("argumento"), [])
    for semilla in entrada["semillas"]:
        if "{X}" in semilla and rellenos:
            for relleno in rng.sample(rellenos, min(max_por_semilla, len(rellenos))):
                resultado.append((semilla.replace("{X}", relleno), relleno))
        elif "{X}" not in semilla:
            resultado.append((semilla, ""))
    return resultado


# ====================================================================
# SUBDOMINIOS: agrupar, DENTRO de un dominio grande, las intenciones
# que tienen algo en común -- para que el clasificador jerárquico
# pueda entrenar una "minired de la minired" cuando un dominio tiene
# demasiadas intenciones parecidas entre sí para distinguir de una
# (ver clasificador_jerarquico.py). Un dominio sin ninguna entrada acá
# sigue entrenando en DOS niveles, exactamente como siempre
# (dominio -> intención); uno con entradas acá pasa a TRES
# (dominio -> subdominio -> intención).
#
# Se asigna DESPUÉS de armar ENTRADAS (no como argumento de _e()) para
# no tener que tocar cada una de las líneas de arriba.
# ====================================================================

SUBDOMINIOS_ASIGNADOS = {
    # memoria: guardar un dato vs consultarlo vs modificarlo/borrarlo
    "recordar": "guardar", "crear_recordatorio": "guardar",
    "mostrar_memoria": "consultar", "mostrar_recordatorios": "consultar",
    "editar_memoria": "modificar", "completar_recordatorio": "modificar", "eliminar_recordatorio": "modificar",

    # codigo: generar un cambio vs revisar/aprobar vs analizar antes de tocar
    "modificar_codigo": "generar",
    "revisar_cambios": "revisar", "cambios_pendientes": "revisar",
    "autorevisar": "revisar", "autorevisar_y_arreglar": "revisar",
    "analizar_funcion": "analizar", "impacto_funcion": "analizar", "riesgo_propuesta": "analizar",

    # arche: el dominio mas grande (23) -- se parte en 6 sub-temas chicos
    "ayuda": "ayuda", "ayuda_categoria": "ayuda",
    "estudiar": "estudio", "iniciar_estudio": "estudio", "detener_estudio": "estudio",
    "temas_estudio": "estudio", "agregar_tema": "estudio",
    "estado_red": "autoconocimiento", "estadisticas": "autoconocimiento",
    "limpiar_conocimiento": "autoconocimiento",
    "autorevision_on": "autoconocimiento", "autorevision_off": "autoconocimiento",
    "entrenar_jerarquico": "autoconocimiento", "estado_jerarquico": "autoconocimiento",
    "examen": "examen", "estado_examen": "examen", "examen_on": "examen", "examen_off": "examen",
    "objetivos": "objetivos", "agregar_objetivo": "objetivos", "objetivo_logrado": "objetivos",
    "entrenar_fondo": "entrenamiento", "estado_banco": "entrenamiento",

    # computador: navegador / ventanas / sonido / pantalla / entrada / equipo
    "que_tengo_abierto": "navegador", "fijar_navegador": "navegador", "preguntar_navegador": "navegador",
    "enfocar_ventana": "ventanas", "minimizar_ventana": "ventanas", "maximizar_ventana": "ventanas",
    "cerrar_ventana": "ventanas", "mostrar_escritorio": "ventanas", "acomodar_ventana": "ventanas",
    "subir_volumen": "sonido", "bajar_volumen": "sonido", "volumen_a": "sonido", "silenciar": "sonido",
    "pausar_reproducir": "sonido", "siguiente_cancion": "sonido", "cancion_anterior": "sonido",
    "subir_brillo": "pantalla", "bajar_brillo": "pantalla", "brillo_a": "pantalla", "captura_pantalla": "pantalla",
    "teclear_texto": "entrada", "presionar_tecla": "entrada",
    "bloquear_pc": "equipo", "apagar_pc": "equipo", "reiniciar_pc": "equipo", "cerrar_sesion": "equipo",
    "suspender_pc": "equipo", "cancelar_apagado": "equipo", "ver_bateria": "equipo",
    "ver_portapapeles": "equipo", "copiar_portapapeles": "equipo", "abrir_carpeta": "equipo",
    # computador / voz
    "activar_voz": "voz", "desactivar_voz": "voz", "callar": "voz", "repetir": "voz", "probar_voz": "voz", "motor_voz": "voz", "elegir_voz": "voz", "estado_voz": "voz", "velocidad_voz": "voz",
    # computador / alarmas
    "crear_aviso": "alarmas", "poner_alarma": "alarmas", "poner_temporizador": "alarmas", "ver_alarmas": "alarmas", "cancelar_alarma": "alarmas", "cancelar_todas_alarmas": "alarmas",
    # computador / rutinas
    "crear_rutina": "rutinas", "ejecutar_rutina": "rutinas", "ver_rutinas": "rutinas", "ver_rutina": "rutinas", "borrar_rutina": "rutinas",
    # computador / mantenimiento
    "diagnostico_pc": "mantenimiento", "programas_cpu": "mantenimiento", "programas_memoria": "mantenimiento", "liberar_memoria": "mantenimiento", "espacio_discos": "mantenimiento", "archivos_grandes": "mantenimiento", "buscar_duplicados": "mantenimiento", "mover_duplicados": "mantenimiento", "descargas_viejas": "mantenimiento", "limpiar_descargas": "mantenimiento", "analizar_limpieza": "mantenimiento", "limpiar_pc": "mantenimiento", "buscar_archivos_tema": "mantenimiento", "restaurar_papelera": "mantenimiento",
}
for _id, _subdominio in SUBDOMINIOS_ASIGNADOS.items():
    if _id in POR_ID:
        POR_ID[_id]["subdominio"] = _subdominio


def subdominios_de(dominio):
    """{subdominio: {ids...}} de las entradas de `dominio` que tienen
    subdominio asignado. Vacío si el dominio no se partió en subgrupos."""
    resultado = {}
    for entrada in ENTRADAS:
        if entrada["dominio"] == dominio and entrada.get("subdominio"):
            resultado.setdefault(entrada["subdominio"], set()).add(entrada["id"])
    return resultado


def tiene_subdominios(dominio):
    return len(subdominios_de(dominio)) >= 2


def subdominio_de(id_intencion):
    entrada = POR_ID.get(id_intencion)
    return entrada.get("subdominio") if entrada else None