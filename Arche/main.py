import time
import threading

from core.utilidades import *
from core.navegador import *
from core.programaV2 import *
from core.busquedas import *
from core.sistema import *
from core.memoria import *
from core.notas import *
from core.recordatorio import *
from core.conversacion import *
from core.archivos import *
from core.configuracion import *
from core.calculadora import *
from cerebroIA import *
from core.IA.ollamaIA import conversar
from core.IA.clasificador import info_modelo
from core.IA.telemetria import resumen as resumen_telemetria


def _barra_progreso(valor, ancho=20):
    """Genera una barra visual tipo [████████░░░░] para un valor 0-1."""
    llenos = int(valor * ancho)
    vacios = ancho - llenos
    return "█" * llenos + "░" * vacios


def _mostrar_estado_red():
    info = info_modelo()

    print("\n" + "═" * 46)
    print("   🧠  ESTADO DE LA RED NEURONAL DE ARCHÉ")
    print("═" * 46)

    if info is None or not info.get("activo"):
        print("  Estado:      ⚪ Inactiva")
        print("  Motivo:      Aún no hay suficientes ejemplos")
        print("               por intención para entrenar de forma")
        print("               confiable (mínimo por clase requerido).")
        print("  Qué hacer:   Seguí usando Arché o dejá correr el")
        print("               modo estudio — se activa sola cuando")
        print("               haya datos suficientes.")
        print("═" * 46 + "\n")
        return

    precision = info.get("precision", 0.0)
    num_ejemplos = info.get("num_ejemplos", 0)
    clases = info.get("clases", [])
    arquitectura = info.get("arquitectura", "desconocida")

    if precision >= 0.90:
        nivel = "Excelente"
    elif precision >= 0.75:
        nivel = "Buena"
    elif precision >= 0.60:
        nivel = "Aceptable"
    else:
        nivel = "Débil (por debajo del mínimo usable)"

    barra = _barra_progreso(precision)

    print("  Estado:      🟢 Activa")
    print(f"  Precisión:   {barra}  {precision*100:.1f}%  ({nivel})")
    print(f"  Arquitectura:{arquitectura}")
    print(f"  Ejemplos:    {num_ejemplos} usados para entrenar")
    print(f"  Intenciones: {len(clases)} reconocidas")

    if clases:
        print("               " + ", ".join(clases))

    print("═" * 46 + "\n")


def _mostrar_estadisticas():
    r = resumen_telemetria()

    print("\n" + "═" * 46)
    print("   📊  ESTADÍSTICAS DE USO")
    print("═" * 46)

    if r is None:
        print("  Todavía no tengo datos de uso registrados.")
        print("═" * 46 + "\n")
        return

    print(f"  Comandos procesados: {r['total_comandos']}")
    print(f"  Tasa de fallo (desconocido): {r['tasa_fallo']}%")

    print("\n  Intenciones más frecuentes:")
    for intencion, cant in r["intenciones_mas_frecuentes"][:5]:
        print(f"    • {intencion}: {cant}")

    print("\n  Resuelto por:")
    for capa, cant in r["resuelto_por"]:
        print(f"    • {capa}: {cant}")

    if r["duracion_promedio_por_modulo"]:
        print("\n  Tiempo promedio por módulo:")
        for modulo, seg in r["duracion_promedio_por_modulo"].items():
            print(f"    • {modulo}: {seg}s")

    print("═" * 46 + "\n")


print("=" * 60)
print("        Arche v2.0.1")
print("=" * 60)

if obtener("nombre_usuario") == "Usuario":
    nombre = input("¿Cómo te llamas?\nTú: ").strip()
    if nombre:
        cambiar("nombre_usuario", nombre)


print()
print("Analizando datos...")
time.sleep(2)

if obtener("mostrar_estado"):
    hablar("Todos los sistemas están operativos.")

if obtener("saludo_inicial"):
    hablar(f"Hola, {obtener('nombre_usuario')}.")
    hablar("¿En qué puedo ayudarte?")

if obtener("mostrar_recordatorios"):
    revisar_recordatorios()

# ------------------------------------------------------------------
# MODO ESTUDIO: ya NO arranca solo al iniciar Arché. Vos decidís
# cuándo empieza con "iniciar estudio automatico" y cuándo para con
# "detener estudio". El comando "estudiar" (una sola ronda, sin loop)
# sigue disponible aparte, en cualquier momento.
# ------------------------------------------------------------------
_evento_detener_estudio = threading.Event()
_hilo_estudio = None

while True:

    comando = input("\nTú: ").lower().strip()

    if not comando:
        continue

    # ------------------------------------------------------------------
    # COMANDOS DETERMINÍSTICOS: se revisan PRIMERO, sin pasar por el
    # clasificador de IA. Son comparaciones de texto directas, instantáneas.
    # Si alguno coincide, se maneja aquí y se salta el resto del ciclo con
    # "continue" -> nunca se llama a analizar()/Ollama para estos casos.
    # ------------------------------------------------------------------

    if comando in ["adiós", "adios", "salir"]:
        despedida()
        break

    # CONFIGURACIÓN

    if comando in [
        "configuración",
        "configuracion",
        "mostrar configuración",
        "mostrar configuracion"
    ]:
        mostrar()
        continue

    if comando == "cambiar mi nombre":
        nuevo = input("Arché: ¿Cómo quieres que te llame?\nTú: ").strip()
        if nuevo:
            cambiar("nombre_usuario", nuevo)
            hablar(f"De acuerdo, ahora te llamaré {nuevo}.")
        continue

    if comando == "cambiar tu nombre":
        nuevo = input("Arché: ¿Cómo quieres llamarme?\nTú: ").strip()
        if nuevo:
            cambiar("nombre_asistente", nuevo)
            hablar(f"Ahora mi nombre es {nuevo}.")
        continue

    if comando in ["restablecer configuración", "restablecer configuracion"]:
        restaurar()
        hablar("Configuración restablecida.")
        continue

    # NOTAS

    if comando.startswith("crea una nota"):
        nombre_nota = comando.replace("crea una nota", "", 1).strip()
        if nombre_nota:
            crear_nota(nombre_nota)
        else:
            print("Arché: ¿Cómo quieres llamar la nota?")
        continue

    if comando.startswith("lee la nota"):
        nombre_nota = comando.replace("lee la nota", "", 1).strip()
        if nombre_nota:
            leer_nota(nombre_nota)
        else:
            print("Arché: ¿Qué nota quieres leer?")
        continue

    if comando.startswith("abre la nota"):
        nombre_nota = comando.replace("abre la nota", "", 1).strip()
        if nombre_nota:
            abrir_nota(nombre_nota)
        else:
            print("Arché: ¿Qué nota quieres abrir?")
        continue

    if comando.startswith("agrega a"):
        nombre_nota = comando.replace("agrega a", "", 1).strip()
        if nombre_nota:
            agregar_nota(nombre_nota)
        else:
            print("Arché: ¿A qué nota quieres agregar texto?")
        continue

    if comando.startswith("elimina la nota"):
        nombre_nota = comando.replace("elimina la nota", "", 1).strip()
        if nombre_nota:
            eliminar_nota(nombre_nota)
        else:
            print("Arché: ¿Qué nota quieres eliminar?")
        continue

    if comando in ["mis notas", "listar notas"]:
        listar_notas()
        continue

    # ARCHIVOS

    if comando == "actualizar archivos":
        actualizar_indice()
        continue

    if comando.startswith("busca archivo"):
        nombre = comando.replace("busca archivo", "", 1).strip()
        mostrar_resultados(buscar(nombre))
        continue

    if comando.startswith("abre archivo"):
        nombre = comando.replace("abre archivo", "", 1).strip()
        buscar_y_abrir(nombre)
        continue

    # CALCULADORA

    if comando.startswith("calcula"):
        operacion = comando.replace("calcula", "", 1).strip()
        if operacion:
            calcular(operacion)
        else:
            print("Arché: ¿Qué operación quieres calcular?")
        continue

    if comando.startswith("cuanto es"):
        operacion = comando.replace("cuanto es", "", 1).strip()
        if operacion:
            calcular(operacion)
        else:
            print("Arché: ¿Qué operación quieres calcular?")
        continue

    if comando.startswith("cuánto es"):
        operacion = comando.replace("cuánto es", "", 1).strip()
        if operacion:
            calcular(operacion)
        else:
            print("Arché: ¿Qué operación quieres calcular?")
        continue

    if comando in ["historial calculos", "historial cálculos"]:
        historial()
        continue

    # RED NEURONAL / CLASIFICADOR

    if comando in ["estado red", "estado de la red", "estado del clasificador", "estado clasificador"]:
        _mostrar_estado_red()
        continue

    # TELEMETRÍA

    if comando in ["estadisticas", "estadísticas", "telemetria", "telemetría"]:
        _mostrar_estadisticas()
        continue

    # LIMPIEZA AUTOMÁTICA

    if comando in ["limpiar automatico", "limpiar automático", "limpieza automatica", "limpieza automática"]:
        from core.IA.limpieza_auto import limpiar_automatico
        resultado = limpiar_automatico(simular=False)
        if resultado["borrados"] == 0:
            print("Arché: No encontré contaminación obvia para limpiar.")
        else:
            print(f"Arché: Limpié {resultado['borrados']} entradas contaminadas (backup guardado).")
            for d in resultado["detalle"]:
                print(f"  • '{d['pregunta']}' (tenía {d['accion']}/{d['contenido']} mal reutilizado)")
        continue

    # MODO ESTUDIO

    if comando == "estudiar":
        from core.IA.estudio import estudiar_todo
        estudiar_todo()
        continue

    if comando in ["iniciar estudio automatico", "iniciar estudio automático", "activar estudio automatico", "activar estudio automático"]:
        from core.IA.estudio import iniciar_estudio_en_background
        if _hilo_estudio is not None and _hilo_estudio.is_alive():
            print("Arché: El estudio automático ya está corriendo.")
        else:
            _evento_detener_estudio.clear()
            _hilo_estudio = iniciar_estudio_en_background(detener_evento=_evento_detener_estudio)
            print("Arché: Empecé a estudiar en segundo plano.")
        continue

    if comando == "detener estudio":
        if _hilo_estudio is not None and _hilo_estudio.is_alive():
            _evento_detener_estudio.set()
            print("Arché: Voy a parar de estudiar después de esta ronda.")
        else:
            print("Arché: El estudio automático no está corriendo.")
        continue

    if comando.startswith("agregar tema"):
        resto = comando.replace("agregar tema", "", 1).strip()
        if resto:
            from core.IA.estudio import agregar_tema
            if " : " in resto:
                tema, descripcion = resto.split(" : ", 1)
            else:
                tema, descripcion = resto, None
            if agregar_tema(tema.strip(), descripcion):
                print(f"Arché: Agregué '{tema.strip()}' a mis temas de estudio.")
            else:
                print(f"Arché: Ya tenía '{tema.strip()}' en mis temas de estudio.")
        else:
            print("Arché: ¿Qué tema quieres que agregue? (opcional: 'agregar tema X : descripción' para temas ambiguos)")
        continue

    if comando in ["temas de estudio", "mis temas"]:
        from core.IA.estudio import cargar_temas, _texto_tema
        temas = cargar_temas()
        if temas:
            print("Arché: Mis temas de estudio son:")
            for item in temas:
                tema, descripcion = _texto_tema(item)
                if descripcion:
                    print(f"  • {tema} ({descripcion})")
                else:
                    print(f"  • {tema}")
        else:
            print("Arché: Todavía no tengo temas de estudio. Agrega uno con 'agregar tema <tema>'.")
        continue

    # Nada determinístico coincidió -> AHORA sí vale la pena clasificar
    # con la IA (resolver() por plantillas primero, Ollama como último
    # recurso dentro de analizar()). La telemetría del resultado ya se
    # registra DENTRO de analizar() (en cerebroIA.py), con información
    # más precisa de qué capa resolvió el comando -- por eso acá no se
    # vuelve a registrar.

    resultado = analizar(comando)
    intencion = resultado["intencion"]
    contenido = resultado["contenido"]

    if intencion == "saludo":
        saludar(obtener("nombre_usuario"))

    elif intencion == "presentacion":
        presentarse()

    elif intencion == "hora":
        decir_hora()

    elif intencion == "fecha":
        decir_fecha()

    # AYUDA

    elif intencion == "ayuda":
        ayuda()

    elif intencion == "ayuda_categoria":
        categoria = comando.lower()
        categoria = categoria.replace("qué hace", "")
        categoria = categoria.replace("que hace", "")
        categoria = categoria.replace("¿", "")
        categoria = categoria.replace("?", "")
        categoria = categoria.strip()
        ayuda(categoria)

    # MEMORIA

    elif intencion == "recordar":
        if contenido:
            recordar(contenido)
        else:
            print("Arché: ¿Qué quieres que recuerde?")

    elif intencion == "mostrar_memoria":
        mostrar_recuerdos()

    # RECORDATORIOS

    elif intencion == "crear_recordatorio":
        crear_recordatorio(contenido)

    elif intencion == "mostrar_recordatorios":
        mostrar_recordatorios()

    elif intencion == "completar_recordatorio":
        completar_recordatorio()

    elif intencion == "eliminar_recordatorio":
        eliminar_recordatorio()

    # BÚSQUEDAS EN GOOGLE

    elif intencion == "buscar":
        if contenido:
            buscar_google(contenido)
        else:
            respuesta = input("Arché: ¿Qué quieres buscar?\nTú: ").strip().lower()
            if respuesta:
                buscar_google(respuesta)

    # PÁGINAS WEB Y PROGRAMAS

    elif intencion == "abrir":
        nombre = contenido
        if not nombre:
            nombre = input("Arché: ¿Qué deseas abrir?\nTú: ").strip().lower()

        if nombre in sitios:
            abrir_navegador(nombre)
        elif nombre in programas:
            abrir_programa(nombre)
        else:
            tipo = input(
                "Arché: ¿Es una página web (1) o un programa (2)?\nTú: "
            ).strip()
            if tipo == "1":
                buscar_sitio(nombre)
            elif tipo == "2":
                aprender_programa(nombre)
            else:
                print("Arché: Cancelado.")

    elif intencion == "conversar":
        from core.IA.respuestas import buscar_respuesta, guardar_respuesta

        respuesta_propia = buscar_respuesta(contenido)

        if respuesta_propia:
            print(f"Arché: {respuesta_propia}")
        else:
            respuesta = conversar(contenido)
            print(f"Arché: {respuesta}")
            guardar_respuesta(contenido, respuesta)

    # COMANDO DESCONOCIDO

    elif intencion == "desconocido":
        print("Arché: Aún no sé hacer eso.")