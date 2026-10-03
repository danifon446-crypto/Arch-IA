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
}
EXTRA_FIJOS_PREFIJOS = (
    "escribe en ", "cambia esto", "mejora esto", "arregla esto", "cuanto es ", "conecta ", "conectar ",
    "autorevisate cada", "entrenar a fondo", "que hace ", "modo gran sabio",
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