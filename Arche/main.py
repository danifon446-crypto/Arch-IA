import time
import threading
import re

from core.instalador import verificar_e_instalar
verificar_e_instalar()

from core.utilidades import *
from core.navegador import *
from core.programaV2 import *
from core.busquedas import *
from core.sistema import *
from core.memoria import *
from core.notas import *
from core.recordatorio import *
from core.conversacion import responder as responder_conversacion
from core.archivos import *
from core.configuracion import *
from core.calculadora import *
from cerebroIA import *
from core.IA.ollamaIA import conversar, hay_historial_activo, reiniciar_historial, razonar_y_responder, necesita_razonamiento_profundo
from core.IA.clasificador import info_modelo
from core.IA.telemetria import resumen as resumen_telemetria, registrar_comando
from core.IA.introspeccion import reporte_texto
from core.IA.autoconocimiento import manejar_autoconocimiento
from core.IA.respuestas import buscar_respuesta, guardar_respuesta, _normalizar
from core.IA.preguntas_frecuentes import PREGUNTAS_FRECUENTES

# NOTA: archivos que existen en el proyecto pero NO se usan en ningún
# lado (no rompen nada si se quedan, es solo peso muerto):
#   - core/cerebro/  (carpeta completa: abrir.py, ayuda.py, buscar.py,
#     crear_recordatorio.py, editar_memoria.py, eliminar_recordatorio.py,
#     fecha.py, hora.py, mostrar_memoria.py, mostrar_recordatorios.py,
#     presentacion.py, recordar.py, saludo.py) -> listas de frases de
#     ejemplo de una versión vieja de reconocimiento de comandos, ya
#     reemplazada por Ollama + embeddings + la red neuronal.
#   - core/programas.py      -> reemplazado por core/programaV2.py
#   - core/prueba.py         -> archivo de pruebas sueltas
#   - core/compresion.py     -> intento viejo de interpretar comandos,
#     reemplazado por core/IA/aprendizaje.py + Ollama
#   - core/archivos1.py      -> reemplazado por core/archivos.py
# Pero igual siguen ahi por que con esos es que sirve copia(seguridad)


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


def manejar_pedido_de_cambio(instruccion):
    """
    Punto de entrada UNICO para cualquier pedido de que Arche modifique
    su propio codigo -- sin importar si llego por el trigger literal
    ("cambia esto: ...") o porque el clasificador (comprender()) lo
    reconocio en lenguaje natural como intencion "modificar_codigo".

    Rutea solo el destino, genera la propuesta con el camino mas
    confiable segun el caso (agregar funcion aislada vs editar), y
    avisa en una frase natural -- sin ID tecnico ni ruta de archivo
    cruda, eso ya lo vas a ver bien explicado en 'revisar cambios de
    codigo' si hace falta.
    """
    from core.IA.enrutar_cambio import decidir_destino, construir_instruccion_final, es_pedido_de_agregado
    from core.IA.proponer_cambio_codigo import proponer_cambio_ia, proponer_agregar_funcion_cerca, _extraer_funcion

    decision = decidir_destino(instruccion)
    print(f"Arché: {decision['explicacion']}")

    if decision["tipo"] == "editar_existente" and not decision.get("confianza_alta", True):
        confirmar = input(
            "Arché: No estoy muy seguro de este destino. "
            "¿Seguimos igual (s), o preferís decirme vos el archivo con "
            "'escribe en <archivo> : ...' en su lugar? [s/n]\nTú: "
        ).strip().lower()
        if confirmar not in ("s", "si", "sí"):
            print("Arché: Dale, cancelado. Usá 'escribe en <archivo> : <instrucción>' cuando sepas el destino.")
            return

    if decision["tipo"] == "editar_existente" and decision["funcion"] and es_pedido_de_agregado(instruccion):
        ruta_archivo = decision["archivo"]
        contenido_archivo = open(ruta_archivo, "r", encoding="utf-8").read()
        codigo_ancla = _extraer_funcion(contenido_archivo, decision["funcion"])
        if codigo_ancla is None:
            print("Arché: No pude aislar esa función para anclar el cambio, lo intento como edición genérica.")
            instruccion_final = construir_instruccion_final(decision, instruccion)
            propuesta, error = proponer_cambio_ia(decision["archivo"], instruccion_final, origen="autonomo")
        else:
            propuesta, error = proponer_agregar_funcion_cerca(decision["archivo"], codigo_ancla, instruccion, origen="autonomo")
    else:
        instruccion_final = construir_instruccion_final(decision, instruccion)
        propuesta, error = proponer_cambio_ia(decision["archivo"], instruccion_final, origen="autonomo")

    if error:
        print(f"Arché: No lo pude resolver bien: {error}")
    else:
        print("Arché: Listo, ya tengo el cambio armado. Decime 'revisar cambios de codigo' cuando quieras que te lo cuente y lo aprobés.")



print("                  Arche v2.0.1")


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

# ------------------------------------------------------------------
# AUTOREVISIÓN AUTOMÁTICA: a diferencia del modo estudio, esta SÍ
# arranca sola al iniciar Arché (si autorevision_automatica está en
# True, que es el default) -- es de solo lectura, nunca aplica nada
# sin tu aprobación, así que no hay riesgo en que corra sin que la
# pidas. Se puede parar con "detener autorevision automatica".
# ------------------------------------------------------------------
_evento_detener_autorevision = threading.Event()
_hilo_autorevision = None
_ultimo_reporte_limpieza = None  # lo llena "analiza limpieza"; lo usa "limpia <categoria>" después
if obtener("autorevision_automatica"):
    from core.IA.autorevision import iniciar_autorevision_en_background
    _hilo_autorevision = iniciar_autorevision_en_background(
        intervalo_seg=int(obtener("autorevision_intervalo_horas") * 3600),
        detener_evento=_evento_detener_autorevision,
        avisar=hablar,
    )

while True:

    comando_original = input("\nTú: ").strip()
    comando = comando_original.lower()

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

    # AUTO-MODIFICACIÓN DE CÓDIGO
    # Arché nunca escribe directo a un archivo real: genera una
    # propuesta (buscar/reemplazar acotado), y solo se aplica al
    # correr "revisar cambios de codigo" con tu aprobación explícita.

    if comando.startswith("escribe en "):
        resto = comando_original[len("escribe en "):].strip()
        if " : " in resto:
            archivo, instruccion = resto.split(" : ", 1)
            from core.IA.proponer_cambio_codigo import proponer_cambio_ia
            propuesta, error = proponer_cambio_ia(archivo.strip(), instruccion.strip())
            if error:
                print(f"Arché: {error}")
            else:
                print(f"Arché: Generé la propuesta {propuesta['id']} para {propuesta['archivo']}. "
                    f"Corré 'revisar cambios de codigo' para verla y aprobarla.")
        else:
            print("Arché: Usá el formato 'escribe en <archivo> : <qué querés que cambie>'.")
        continue

    if comando in ["revisar cambios de codigo", "revisar cambios de código"]:
        from core.IA.revisar_cambios_codigo import main as revisar_cambios_codigo
        revisar_cambios_codigo()
        continue

    if comando.startswith("cambia esto") or comando.startswith("mejora esto") or comando.startswith("arreglá esto") or comando.startswith("arregla esto"):
        instruccion = ""
        for prefijo in ["cambia esto", "mejora esto", "arreglá esto", "arregla esto"]:
            if comando_original.lower().startswith(prefijo):
                instruccion = comando_original[len(prefijo):].strip(" :")
                break
        if not instruccion:
            print("Arché: Decime qué querés que cambie. Ej: 'cambia esto: agregá una función que cuente las notas'.")
            continue

        manejar_pedido_de_cambio(instruccion)
        continue

    if comando in ["cambios de codigo pendientes", "cambios de código pendientes"]:
        from core.IA.proponer_cambio_codigo import _cargar_pendientes
        pendientes = [p for p in _cargar_pendientes() if p["estado"] == "pendiente"]
        if not pendientes:
            print("Arché: No tengo propuestas de código pendientes.")
        else:
            print(f"Arché: Tengo {len(pendientes)} propuesta(s) pendiente(s):")
            for p in pendientes:
                print(f"  • [{p['id']}] {p['archivo']}: {p['que']}")
        continue

    if comando in ["revisa tu codigo", "revisa tu código", "autorevisate", "autorevísate"]:
        from core.IA.autorevision import autorevisar, imprimir_reporte_natural
        print("Arché: Dale, me reviso entero. Los chequeos rápidos son instantáneos; "
              "si hay funciones nuevas o modificadas desde la última vez, esas las "
              "reviso con Ollama, así que puede tardar un poco.")
        reporte = autorevisar(usar_ollama=True)
        imprimir_reporte_natural(reporte, sin_ia=False)
        continue

    if comando in ["revisa tu codigo sin ia", "revisa tu código sin ia"]:
        from core.IA.autorevision import autorevisar, imprimir_reporte_natural
        print("Arché: Dale, corro solo los chequeos deterministas (sin Ollama, instantáneo).")
        reporte = autorevisar(usar_ollama=False)
        imprimir_reporte_natural(reporte, sin_ia=True)
        continue

    if comando in ["olvida lo que hablamos", "nueva conversacion", "nueva conversación", "reinicia la charla", "empecemos de nuevo"]:
        reiniciar_historial()
        print("Arché: Listo, arranco de cero -- no voy a arrastrar nada de lo que veníamos hablando.")
        continue

    # CONTROL DEL SISTEMA (pilar 2: recursos, búsqueda por contenido, limpieza)

    if comando in ["estado del sistema", "como esta el sistema", "cómo está el sistema", "recursos", "que tal el pc", "qué tal el pc"]:
        import core.sistema as sistema
        hablar(sistema.hablar_estado_sistema())
        continue

    if comando in ["que procesos consumen mas", "qué procesos consumen más", "procesos"]:
        import core.sistema as sistema
        print(sistema.hablar_procesos_que_mas_consumen())
        continue

    if comando.startswith("busca contenido") or comando.startswith("busca en el contenido") or comando.startswith("que archivos mencionan") or comando.startswith("qué archivos mencionan"):
        import core.sistema as sistema
        texto_buscado = re.sub(r"^(busca contenido|busca en el contenido|que archivos mencionan|qué archivos mencionan)\s*", "", comando).strip()
        if not texto_buscado:
            print("Arché: Decime qué texto buscar. Ej: 'busca contenido presupuesto 2026'.")
        else:
            resultados = sistema.buscar_por_contenido(texto_buscado)
            sistema.mostrar_resultados_contenido(resultados, texto_buscado)
        continue

    if comando in ["analiza limpieza", "que se puede limpiar", "qué se puede limpiar", "analiza el disco"]:
        import core.sistema as sistema
        _ultimo_reporte_limpieza = sistema.analizar_limpieza()
        print(sistema.hablar_analisis_limpieza(_ultimo_reporte_limpieza))
        continue

    if comando.startswith("limpia"):
        import core.sistema as sistema
        if _ultimo_reporte_limpieza is None:
            print("Arché: Todavía no analicé qué hay para limpiar en esta sesión. Decime 'analiza limpieza' primero, así ves qué se borraría antes de confirmarlo.")
        else:
            categorias = sistema.interpretar_categorias_limpieza(comando)
            if not categorias:
                print("Arché: No reconocí qué categoría limpiar. Opciones: 'limpia pycache', 'limpia tmp', 'limpia temporales windows', o 'limpia todo'.")
            else:
                resultado = sistema.ejecutar_limpieza(_ultimo_reporte_limpieza, categorias)
                print(sistema.hablar_resultado_limpieza(resultado))
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

    # AUTOREVISIÓN AUTOMÁTICA

    if comando in ["iniciar autorevision automatica", "iniciar autorevisión automática",
                   "activar autorevision automatica", "activar autorevisión automática"]:
        from core.IA.autorevision import iniciar_autorevision_en_background
        if _hilo_autorevision is not None and _hilo_autorevision.is_alive():
            print("Arché: La autorevisión automática ya está corriendo.")
        else:
            _evento_detener_autorevision.clear()
            _hilo_autorevision = iniciar_autorevision_en_background(
                intervalo_seg=int(obtener("autorevision_intervalo_horas") * 3600),
                detener_evento=_evento_detener_autorevision,
                avisar=hablar,
            )
            cambiar("autorevision_automatica", True)
            print("Arché: Listo, me voy a autorevisar sola en segundo plano de ahora en más.")
        continue

    if comando in ["detener autorevision automatica", "detener autorevisión automática"]:
        if _hilo_autorevision is not None and _hilo_autorevision.is_alive():
            _evento_detener_autorevision.set()
            cambiar("autorevision_automatica", False)
            print("Arché: Dale, dejo de autorevisarme sola. Podés pedírmelo vos cuando quieras con 'revisate'.")
        else:
            print("Arché: La autorevisión automática no está corriendo.")
        continue

    if comando.startswith("autorevisate cada"):
        resto = comando.replace("autorevisate cada", "", 1).replace("autorevísate cada", "", 1).strip()
        try:
            horas = float(resto.split()[0])
            cambiar("autorevision_intervalo_horas", horas)
            print(f"Arché: Listo, de ahora en más me autorevisaré cada {horas} hora(s) "
                  f"(vale a partir del próximo arranque, o de que reinicies la autorevisión automática).")
        except (ValueError, IndexError):
            print("Arché: No te entendí el número de horas. Ej: 'autorevisate cada 3'.")
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

    # CONVERSACIÓN RÁPIDA (gracias, cómo estás, buenos días, etc.)
    # Respuestas instantáneas sin pasar por el clasificador ni Ollama.

    if responder_conversacion(comando):
        continue

    # AUTOCONOCIMIENTO (changelog / dependencia de Ollama)

    respuesta_auto = manejar_autoconocimiento(comando)
    if respuesta_auto:
        print(f"Arché: {respuesta_auto}")
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

    # AUTO-MODIFICACIÓN RECONOCIDA EN LENGUAJE NATURAL
    # (el trigger literal "cambia esto: ..." ya se maneja arriba, entre
    # los comandos deterministas -- esto es para cuando lo decís de
    # forma mas natural, sin ese formato exacto)

    elif intencion == "modificar_codigo":
        texto_instruccion = contenido if contenido else comando_original
        manejar_pedido_de_cambio(texto_instruccion)

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
        contenido_norm = _normalizar(contenido)

        if contenido_norm in PREGUNTAS_FRECUENTES:
            # Capa 0: lookup fijo, comparación de texto exacta.
            # No calcula embeddings ni llama a Ollama.
            respuesta_fija = PREGUNTAS_FRECUENTES[contenido_norm]
            print(f"Arché: {respuesta_fija}")
            registrar_comando(contenido, "conversar", resuelto_por="pregunta_frecuente")
        elif not hay_historial_activo() and (respuesta_propia := buscar_respuesta(contenido)):
            # Capa 1: caché de respuestas por similitud semántica.
            # SOLO si todavía no hay charla en curso en esta sesión --
            # una vez que hay historial, una pregunta de seguimiento
            # ("¿y en euros?") depende de lo que se dijo antes, y la
            # caché podría traer una respuesta vieja de otra
            # conversación sin ese contexto. Mejor mandarla a Ollama
            # con el historial real en ese caso.
            print(f"Arché: {respuesta_propia}")
            registrar_comando(contenido, "conversar", resuelto_por="cache_respuestas")
        else:
            # Capa 2: última instancia, llamada a Ollama -- con
            # historial de la charla y memoria de lo que ya sabe de vos.
            # Si la pregunta se beneficia de pensarla en dos pasos
            # (comparación, "por qué", consejo, etc.), o si la pediste
            # explícitamente con "pensá bien: ...", usa razonar_y_responder
            # (más lento, dos llamadas) en vez de la respuesta directa.
            era_pregunta_suelta = not hay_historial_activo()  # antes de esta llamada, no despues
            pedido_explicito = contenido_norm.startswith("pensa bien") or contenido_norm.startswith("piensa bien") or contenido_norm.startswith("analiza a fondo")
            if pedido_explicito or necesita_razonamiento_profundo(contenido):
                respuesta = razonar_y_responder(contenido, usar_historial=True, usar_memoria=True)
            else:
                respuesta = conversar(contenido, usar_historial=True, usar_memoria=True)
            print(f"Arché: {respuesta}")
            if era_pregunta_suelta:
                # Solo cacheamos preguntas que fueron el PRIMER mensaje
                # de la sesión (sin contexto previo) -- una respuesta
                # que dependió del historial no tiene sentido fuera de
                # ese contexto, y guardarla podría hacer que aparezca
                # suelta, sin sentido, en una charla totalmente distinta.
                guardar_respuesta(contenido, respuesta)
            registrar_comando(contenido, "conversar", resuelto_por="ollama_conversar")

    # COMANDO DESCONOCIDO

    elif intencion == "desconocido":
        print("Arché: Aún no sé hacer eso.")