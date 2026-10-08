import ast
import re
import time
import threading

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
from core.conversacion import responder as responder_conversacion, saludar, presentarse
from core.tiempo import decir_hora, decir_fecha
from core.ayuda import ayuda
from core.archivos import *
from core.configuracion import *
from core.calculadora import *
from core import control_pc
from core import acciones_pc
from core import voz as voz_arche            # Arché habla (voz natural online o la de Windows)
from core import alarmas as alarmas_arche    # alarmas, avisos y temporizadores que suenan
from core import mejora_continua as mejora_arche  # piloto automatico: se mejora sola cuando no la usas
from core import autonomia as autonomia_arche  # se adelanta: avisos del equipo, habitos, resumen del dia
from core import rutinas as rutinas_arche    # rutinas / modos propios (estudio, cine...)
from core import pc_avanzado                 # diagnóstico, limpieza, duplicados, buscar archivos
from core.IA import cerebro as cerebro_nube  # internet (clima, noticias, investigar) y nube + Ollama
from core.IA import aprender_de_nube         # aprende de la nube: intenciones y datos (en segundo plano)
from cerebroIA import *
from core.IA.ollamaIA import conversar
from core.IA.clasificador import info_modelo
from core.IA.telemetria import resumen as resumen_telemetria, registrar_comando
from core.IA.autoconocimiento import manejar_autoconocimiento
from core.IA.respuestas import buscar_respuesta, guardar_respuesta, _normalizar
from core.IA.preguntas_frecuentes import PREGUNTAS_FRECUENTES
from core.IA.autotest import *
from core.IA.verificar_cambio import *
import importlib
from core import comandos_extra
from core.IA import conectar_funciones
from core.IA import gran_sabio
from core.IA import catalogo
from core.IA import entrenador_masivo
from core.IA import enrutador_natural

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
# Pero igual siguen ahi por que con esos es que sirve copia(seguridad)


def _barra_progreso(valor, ancho=20):
    """Genera una barra visual tipo [████████░░░░] para un valor 0-1."""
    llenos = int(valor * ancho)
    vacios = ancho - llenos
    return "█" * llenos + "░" * vacios


def _mostrar_estado_red():
    info = info_modelo()

    print("    ESTADO DE LA RED NEURONAL DE ARCHÉ")

    if info is None or not info.get("activo"):
        print("  Estado:      ⚪ Inactiva")
        print("  Motivo:      Aún no hay suficientes ejemplos")
        print("               por intención para entrenar de forma")
        print("               confiable (mínimo por clase requerido).")
        print("  Qué hacer:   Seguí usando Arché o dejá correr el")
        print("               modo estudio — se activa sola cuando")
        print("               haya datos suficientes.")
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



def _mostrar_estadisticas():
    r = resumen_telemetria()

    print("   📊  ESTADÍSTICAS DE USO")

    if r is None:
        print("  Todavía no tengo datos de uso registrados.")
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



def _decir(resultado):
    """Muchas funciones de core/sistema.py DEVUELVEN el texto en vez de
    imprimirlo. Si devuelve texto, lo muestra; si ya lo imprimió ella
    misma (y devuelve None), no repite nada."""
    if resultado:
        print(f"Arché: {resultado}")


def _ruta_explicita_en(instruccion):
    """
    Si el pedido nombra un archivo .py que EXISTE en el proyecto
    (ej. 'en core/calculadora.py, agregá ...'), devuelve su ruta
    relativa normalizada (ej. 'core/calculadora.py'); si no, None.
    Acepta la ruta completa o solo el nombre (busca en raíz, core/ y
    core/IA/). Sirve para respetar el archivo que vos indicás en vez
    de dejar que el enrutador adivine (o invente uno nuevo).
    """
    from core.IA.proponer_cambio_codigo import RAIZ_APP

    for candidato in re.findall(r"[\w./\\-]+\.py", instruccion):
        candidato = candidato.replace("\\", "/")
        if candidato.startswith("./"):
            candidato = candidato[2:]
        for carpeta in ("", "core/", "core/IA/"):
            relativa = carpeta + candidato
            if (RAIZ_APP / relativa).is_file():
                return relativa
    return None


def _ultima_funcion(contenido):
    """Nombre de la última función definida a nivel de módulo en
    `contenido` (sirve de ancla para 'agregar una función al final'),
    o None si no hay ninguna o el código no parsea."""
    try:
        arbol = ast.parse(contenido)
    except SyntaxError:
        return None
    nombres = [n.name for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return nombres[-1] if nombres else None


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

    Si el pedido nombra un archivo existente ("en core/calculadora.py,
    ..."), se respeta ESE archivo. Si ademas es un pedido de agregar
    una función, se ancla a la última función de ese archivo (en vez
    de mandarle el archivo entero al modelo, que falla seguido).
    """
    from core.IA.enrutar_cambio import decidir_destino, construir_instruccion_final, es_pedido_de_agregado
    from core.IA.proponer_cambio_codigo import proponer_cambio_ia, proponer_agregar_funcion_cerca, _extraer_funcion, RAIZ_APP

    decision = decidir_destino(instruccion)

    ruta_explicita = _ruta_explicita_en(instruccion)
    if ruta_explicita:
        contenido_explicito = (RAIZ_APP / ruta_explicita).read_text(encoding="utf-8")
        decision["tipo"] = "editar_existente"
        decision["archivo"] = ruta_explicita
        decision["confianza_alta"] = True
        decision["explicacion"] = f"Voy a trabajar sobre {ruta_explicita}, como me pediste."
        # una función sugerida por el enrutador solo vale si existe en ESTE archivo
        if decision.get("funcion") and not _extraer_funcion(contenido_explicito, decision["funcion"]):
            decision["funcion"] = None
        if not decision.get("funcion") and es_pedido_de_agregado(instruccion):
            decision["funcion"] = _ultima_funcion(contenido_explicito)

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

    # GRAN SABIO: antes de gastarle un intento al modelo, avisa si el
    # archivo/función objetivo ya dieron problemas antes, o si tocar la
    # función existente afecta a otros lugares del proyecto.
    from core.IA import gran_sabio
    if decision["tipo"] == "editar_existente":
        ruta_para_dificultad = RAIZ_APP / decision["archivo"]
        contenido_para_dificultad = ruta_para_dificultad.read_text(encoding="utf-8") if ruta_para_dificultad.is_file() else ""
        nivel, motivos = gran_sabio.estimar_dificultad(decision["archivo"], instruccion, contenido_para_dificultad)
        if nivel == "medio":
            print(f"Arché: Ojo, este pedido tiene algo de riesgo de fallar ({'; '.join(motivos)}) -- lo intento igual.")
        elif nivel == "alto":
            print(f"Arché: Este pedido pinta difícil ({'; '.join(motivos)}).")
            seguir = input("Arché: ¿Lo intento igual (s), o preferís partirlo en pasos más chicos? [s/n]\nTú: ").strip().lower()
            if seguir not in ("s", "si", "sí"):
                print("Arché: Dale, cancelado. Probá pidiendo un cambio más puntual.")
                return
        if decision.get("funcion") and not es_pedido_de_agregado(instruccion):
            # editar una función existente (no agregar una nueva): avisa a quién más afecta
            gran_sabio.analizar_impacto(decision["funcion"])

    if decision["tipo"] == "editar_existente" and decision["funcion"] and es_pedido_de_agregado(instruccion):
        ruta_archivo = RAIZ_APP / decision["archivo"]
        contenido_archivo = ruta_archivo.read_text(encoding="utf-8")
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


# Mantiene al dia el archivo de comandos (Herrmientas/Comandos de Arche.txt)
from core.guia_comandos import exportar_guia_a_archivo
exportar_guia_a_archivo()

# Desde aquí todo lo que Arché imprime con "Arché:" se lee en voz alta si la voz
# está activa ("activa la voz"). Si está apagada no hace nada.
voz_arche.instalar_en_consola()

print()
print("Analizando datos...")
time.sleep(2)

if obtener("mostrar_estado"):
    hablar("Todos los sistemas están operativos.")

if obtener("actualizar_indice_automaticamente"):
    actualizar_indice()

# NOVEDADES: si desde la última vez se aprobó y aplicó alguna
# auto-modificación de código (nueva función, arreglo, etc.), avisa
# en una frase natural -- antes esto quedaba enterrado y solo se
# sabía si preguntabas explícitamente "qué te auto-modificaste".
from core.IA.autoconocimiento import novedades_desde
_novedades = novedades_desde(obtener("ultima_automod_avisada"))
if _novedades:
    if len(_novedades) == 1:
        hablar(f"Ahora puedo hacer esto: {_novedades[0]['que']}")
    else:
        hablar(f"Desde la última vez aprendí {len(_novedades)} cosas nuevas:")
        for i, n in enumerate(_novedades, start=1):
            print(f"  {i}. {n['que']}")
    cambiar("ultima_automod_avisada", _novedades[-1].get("fecha_propuesta", ""))

if obtener("saludo_inicial"):
    hablar(f"Hola, {obtener('nombre_usuario')}.")
    hablar("¿En qué puedo ayudarte?")

if obtener("mostrar_recordatorios"):
    revisar_recordatorios()

# Alarmas: avisa las que se pasaron con Arché cerrado y deja el vigilante corriendo.
alarmas_arche.avisar_perdidas()
alarmas_arche.iniciar_vigilante()
autonomia_arche.iniciar_vigilante()
autonomia_arche.resumen_del_dia()
mejora_arche.iniciar()
mejora_arche.resumen_pendiente()

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

_evento_detener_examen = threading.Event()
_hilo_examen = None

_evento_detener_entrenamiento = threading.Event()
_hilo_entrenamiento = None
if obtener("autorevision_automatica"):
    from core.IA.autorevision import iniciar_autorevision_en_background
    _hilo_autorevision = iniciar_autorevision_en_background(
        intervalo_seg=int(obtener("autorevision_intervalo_horas") * 3600),
        detener_evento=_evento_detener_autorevision,
        avisar=hablar,
    )

# El enrutador natural, cuando reconoce una frase libre como un comando
# que Arché ya sabe manejar, no lo ejecuta el mismo -- lo pone aca y el
# bucle lo procesa en la SIGUIENTE vuelta exactamente como si lo
# hubieras tipeado tal cual. Cero funciones duplicadas.
_cola_comandos_naturales = []

while True:

    if _cola_comandos_naturales:
        comando_original = _cola_comandos_naturales.pop(0)
    else:
        comando_original = input("\nTú: ").strip()
    comando = comando_original.lower()

    if not comando:
        continue

    # VARIOS PASOS: "abre chrome y luego busca gatos en youtube" -> se parte en
    # pasos y se encolan (con una pausa entre cada uno) para que el bucle los
    # procese como si los hubieras escrito uno por uno.
    # (una rutina se define con varias órdenes adentro: no se parte al crearla)
    _pasos = [] if re.match(r"^(crea|agrega|guarda|arma)\b.*\brutina\b", comando) \
        else acciones_pc.dividir_pasos(comando_original)
    if len(_pasos) > 1:
        _encolar = []
        for _i, _paso in enumerate(_pasos):
            if _i:
                _encolar.append("espera 2")
            _encolar.append(_paso)
        _cola_comandos_naturales[0:0] = _encolar
        print(f"Arché: Entendido, son {len(_pasos)} pasos. Voy uno por uno.")
        continue

    # ------------------------------------------------------------------
    # COMANDOS DETERMINÍSTICOS: se revisan PRIMERO, sin pasar por el
    # clasificador de IA. Son comparaciones de texto directas, instantáneas.
    # Si alguno coincide, se maneja aquí y se salta el resto del ciclo con
    # "continue" -> nunca se llama a analizar()/Ollama para estos casos.
    # ------------------------------------------------------------------

    if comando in ["adiós", "adios", "salir"]:
        responder_conversacion("adios")
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

    # AYUDA
    # Determinística, igual que notas/calculadora: no depende de que el
    # clasificador de IA identifique la intención correctamente. Antes
    # "ayuda" y "qué hace X" solo se reconocían vía intencion=="ayuda"/
    # "ayuda_categoria" en analizar() -- si Ollama clasificaba mal (le
    # pasó con "modificar_codigo"), terminaba proponiendo cambios de
    # código sobre algo que no tenía nada que ver.

    if comando == "ayuda":
        ayuda()
        continue

    if comando.startswith("qué hace") or comando.startswith("que hace"):
        categoria = comando.replace("qué hace", "", 1).replace("que hace", "", 1)
        categoria = categoria.replace("¿", "").replace("?", "").strip()
        ayuda(categoria)
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
        mostrar_resultados(buscar(nombre), se_buscó_en_indice_vacío=indice_vacio())
        continue

    if comando.startswith("abre archivo"):
        nombre = comando.replace("abre archivo", "", 1).strip()
        buscar_y_abrir(nombre)
        continue

    # CONTROL DEL PC: búsqueda directa en un sitio ("busca gatos en youtube",
    # "busca recetas en claude"), qué hay abierto, y qué navegador usar.
    # Va ANTES del clasificador: son comparaciones directas, instantáneas.
    # Solo reconoce la búsqueda si nombra un sitio conocido; si no
    # ("busca inteligencia artificial"), sigue el flujo de siempre.

    # "pon another love en spotify" / "reproduce X en youtube": que SUENE (y reutiliza la pestaña abierta)
    _reproduccion = control_pc.interpretar_reproduccion(comando_original)
    if _reproduccion:
        from core import medios
        medios.reproducir(*_reproduccion)
        control_pc.aprender_de_uso(comando_original, f"{_reproduccion[1]} en {_reproduccion[0]}")
        continue

    _busqueda_en_sitio = control_pc.interpretar_busqueda(comando_original)
    if _busqueda_en_sitio:
        control_pc.buscar_en_sitio(*_busqueda_en_sitio)
        # refuerzo: esta frase queda como ejemplo para las redes (en segundo plano)
        control_pc.aprender_de_uso(comando_original, f"{_busqueda_en_sitio[1]} en {_busqueda_en_sitio[0]}")
        continue

    if comando.startswith("aprende buscar en "):
        control_pc.ensenar_sitio_busqueda(comando.replace("aprende buscar en ", "", 1))
        continue

    if comando in ["que tengo abierto", "qué tengo abierto", "que navegadores tengo", "qué navegadores tengo",
                   "que hay abierto", "qué hay abierto", "estado del pc", "estado de mi pc",
                   "que navegador tengo abierto", "qué navegador tengo abierto"]:
        print("Arché: " + control_pc.resumen_del_pc())
        acciones_pc.imprimir_ventanas()
        continue

    _preferencia_navegador = control_pc.interpretar_preferencia(comando_original)
    if _preferencia_navegador:
        _accion, _nav = _preferencia_navegador
        if _accion == "preguntar":
            control_pc.fijar_navegador_preferido(None)
            print("Arché: Listo, cuando haya más de un navegador te voy a preguntar en cuál.")
        else:
            _ok, _mensaje = control_pc.fijar_navegador(_nav)
            print(f"Arché: {_mensaje}")
        continue

    # VOZ, ALARMAS, RUTINAS, MANTENIMIENTO DEL PC e INTERNET/NUBE. Cada módulo
    # devuelve None si la frase no es suya, así que todo sigue como siempre.
    _resultado_modulo = None
    autonomia_arche.registrar(comando_original)      # anota ordenes seguras repetidas (habitos)
    mejora_arche.latido()                            # mientras hablas, no se pone a mejorar
    for _modulo in (mejora_arche, autonomia_arche, voz_arche, alarmas_arche, rutinas_arche, pc_avanzado, cerebro_nube, aprender_de_nube):
        _resultado_modulo = _modulo.manejar(comando_original)
        if _resultado_modulo:
            break
    if _resultado_modulo:
        _intencion_m, _contenido_m = _resultado_modulo
        if _intencion_m == "ejecutar_rutina" and isinstance(_contenido_m, dict) and _contenido_m.get("pasos"):
            # los pasos entran a la misma cola que "abre chrome y luego ...",
            # así cada uno pasa por sus confirmaciones de siempre
            _cola_comandos_naturales[0:0] = rutinas_arche.pasos_con_pausas(_contenido_m["pasos"])
        elif _intencion_m in catalogo.POR_ID:
            # refuerzo: la frase queda como ejemplo para las redes (en segundo plano)
            control_pc.aprender_de_uso(comando_original, _contenido_m if isinstance(_contenido_m, str) else "", _intencion_m)
        continue

    # CONTROL DEL PC (core/acciones_pc.py): ventanas, volumen, brillo, teclado
    # y mouse, captura, bloqueo/apagado, portapapeles, carpetas. Si no es una
    # acción del PC devuelve None y todo sigue como siempre.
    _accion_pc = acciones_pc.manejar(comando_original)
    if _accion_pc:
        if _accion_pc[0] in catalogo.POR_ID:
            # refuerzo: la frase queda como ejemplo para las redes (en segundo plano)
            control_pc.aprender_de_uso(comando_original, _accion_pc[1], _accion_pc[0])
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

    # ESTADO DEL SISTEMA
    # Estas funciones ya existían en core/sistema.py y core/utilidades.py
    # pero ningún comando las llamaba. _decir() muestra el texto si la
    # función lo devuelve, y no repite nada si ya lo imprimió ella misma.

    if comando in ["estado del sistema", "estado sistema", "como esta el sistema", "cómo está el sistema",
                   "como esta mi pc", "cómo está mi pc"]:
        _decir(hablar_estado_sistema())
        continue

    if comando in ["procesos que mas consumen", "procesos que más consumen", "que consume mas", "qué consume más"]:
        _decir(hablar_procesos_que_mas_consumen())
        continue

    if comando in ["espacio libre", "espacio en disco", "espacio disponible", "cuanto espacio libre tengo",
                   "cuánto espacio libre tengo"]:
        from core.utilidades import espacio_disponible
        print(f"Arché: Te queda {espacio_disponible():.1f}% del disco libre.")
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
        ids_antes = conectar_funciones.ids_pendientes()
        revisar_cambios_codigo()
        # Si se aprobó una función nueva escrita por Arché, ofrece conectarla
        # a un comando del chat (esa conexión también pide tu aprobación).
        conectar_funciones.ofrecer_tras_revision(ids_antes)
        importlib.reload(comandos_extra)  # para que un comando recién aprobado ya funcione
        exportar_guia_a_archivo()  # el archivo de comandos incluye lo recién aprobado
        continue

    if comando.startswith("conecta ") or comando.startswith("conectar "):
        nombre_funcion = comando_original.split()[-1].strip(".,:;'\"")
        conectar_funciones.conectar_por_nombre(nombre_funcion)
        importlib.reload(comandos_extra)
        exportar_guia_a_archivo()
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

    if comando in ["revisa tu codigo", "revisa tu código", "autorevisate", "autorevísate", "revisate", "revísate"]:
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

    if comando in ["revisate y arregla todo", "revísate y arregla todo", "revisate y arregla", "revísate y arregla"]:
        from core.IA.autorevision import autorevisar, imprimir_reporte_natural
        print("Arché: Dale, me reviso entero y esta vez además te dejo armado el parche de "
              "cada cosa que encuentre. Ojo, esto tarda bastante más -- por cada hallazgo le "
              "pido a Ollama que redacte el cambio, no solo que lo detecte.")
        reporte = autorevisar(usar_ollama=True, generar_propuestas=True)
        imprimir_reporte_natural(reporte, sin_ia=False)
        continue

    # MODO ESTUDIO

    if comando == "estudiar":
        from core.IA.estudio import estudiar_todo
        if _hilo_estudio is not None and _hilo_estudio.is_alive():
            print("Arché: Ya estoy estudiando. Decime 'detener estudio' si querés que pare.")
        else:
            _evento_detener_estudio.clear()
            _hilo_estudio = threading.Thread(
                target=estudiar_todo,
                args=(_evento_detener_estudio,),
                daemon=True,
            )
            _hilo_estudio.start()
            print("Arché: Empecé a estudiar en segundo plano (una sola ronda). "
                  "Podés seguir usándome mientras tanto, y decime 'detener estudio' si querés cortarlo antes.")
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

    # GRAN SABIO / RAPHAEL: análisis, riesgo, voz analítica y objetivos.
    # Es solo información -- no aplica ni decide nada por su cuenta.

    if comando.startswith("analiza "):
        gran_sabio.analizar(comando_original[len("analiza "):])
        continue

    if comando.startswith("riesgo "):
        gran_sabio.calcular_riesgo_de(comando_original[len("riesgo "):].strip())
        continue

    if comando.startswith("impacto "):
        gran_sabio.analizar_impacto(comando_original[len("impacto "):].strip())
        continue

    if comando in ["modo gran sabio on", "activar modo gran sabio", "activar gran sabio"]:
        gran_sabio.activar_voz(True)
        continue

    if comando in ["modo gran sabio off", "desactivar modo gran sabio", "desactivar gran sabio"]:
        gran_sabio.activar_voz(False)
        continue

    if comando.startswith("objetivo:") or comando.startswith("objetivo :"):
        gran_sabio.agregar_objetivo(comando_original.split(":", 1)[1])
        continue

    if comando in ["objetivos", "mis objetivos"]:
        gran_sabio.listar_objetivos()
        continue

    if comando.startswith("logre ") or comando.startswith("logré "):
        gran_sabio.completar_objetivo(comando_original.split(" ", 1)[1])
        continue

    if comando in ["sembrar catalogo", "sembrar el catalogo"]:
        entrenador_masivo.sembrar_catalogo()
        continue

    if comando in ["estado banco", "estado del banco"]:
        print(entrenador_masivo.estado_banco())
        continue

    if comando in ["entrenar a fondo", "entrenamiento a fondo"]:
        confirmar = input(
            "Arché: Esto genera y juzga ejemplos nuevos para cada intención del catálogo "
            "-- tarda un rato (llama a Ollama dos veces por cada frase candidata: una para "
            "generarla, otra para juzgarla). ¿Lo corro en segundo plano mientras seguís "
            "usándome? [s/n]\nTú: "
        ).strip().lower()
        if confirmar in ("s", "si", "sí"):
            if _hilo_entrenamiento is not None and _hilo_entrenamiento.is_alive():
                print("Arché: Ya estoy entrenando a fondo.")
            else:
                _evento_detener_entrenamiento.clear()
                _hilo_entrenamiento = threading.Thread(
                    target=entrenador_masivo.entrenar_a_fondo,
                    kwargs={"detener_evento": _evento_detener_entrenamiento},
                    daemon=True,
                )
                _hilo_entrenamiento.start()
                print("Arché: Empecé a entrenar a fondo en segundo plano. Decime 'detener entrenamiento' si querés cortarlo antes.")
        else:
            print("Arché: Dale, cancelado.")
        continue

    if comando in ["entrenar rapido", "entrenar rápido", "entrenamiento rapido"]:
        if _hilo_entrenamiento is not None and _hilo_entrenamiento.is_alive():
            print("Arché: Ya estoy entrenando.")
        else:
            _evento_detener_entrenamiento.clear()
            _hilo_entrenamiento = threading.Thread(
                target=entrenador_masivo.entrenar_rapido,
                kwargs={"detener_evento": _evento_detener_entrenamiento},
                daemon=True,
            )
            _hilo_entrenamiento.start()
            print("Arché: Empecé a entrenar rápido (sin juez) en segundo plano.")
        continue

    if comando in ["detener entrenamiento"]:
        if _hilo_entrenamiento is not None and _hilo_entrenamiento.is_alive():
            _evento_detener_entrenamiento.set()
            print("Arché: Voy a parar el entrenamiento a fondo después de esta intención.")
        else:
            print("Arché: No estoy entrenando a fondo ahora mismo.")
        continue

    if comando in ["modo natural on", "activar modo natural", "activar enrutador natural"]:
        enrutador_natural.activar(True)
        print("Arché: Listo, ahora también entiendo frases libres para TODO lo que sé hacer "
              "(antes de esto, Ollama solo reconocía mis comandos de charla; ahora reconoce "
              "el catálogo completo -- notas, archivos, calculadora, sistema, y el resto).")
        continue

    if comando in ["modo natural off", "desactivar modo natural", "desactivar enrutador natural"]:
        enrutador_natural.activar(False)
        print("Arché: Dale, vuelvo a necesitar los comandos tal cual (o lo que reconozca comprender()).")
        continue

    # AULA DE ENTRENAMIENTO PROGRESIVO: clasificador jerárquico + examen.
    # No reemplaza al clasificador actual (clasificador.py) -- corre
    # aparte, en sus propios archivos, hasta que decidas activarlo.

    if comando in ["entrenar jerarquico", "entrenar clasificador jerarquico"]:
        from core.IA.clasificador_jerarquico import entrenar_jerarquico
        entrenar_jerarquico()
        continue

    if comando in ["estado red jerarquica", "estado clasificador jerarquico"]:
        from core.IA.clasificador_jerarquico import info_jerarquico
        info = info_jerarquico()
        for nombre, datos_info in info.items():
            if datos_info["activo"]:
                print(f"  • {nombre}: activo, {datos_info['precision']:.0%} precisión, {datos_info['n_ejemplos']} ejemplos")
            else:
                print(f"  • {nombre}: inactivo (sin datos suficientes todavía)")
        continue

    if comando in ["examen", "rendir examen"]:
        from core.IA.examen import rendir_examen
        try:
            rendir_examen()
        except RuntimeError as e:
            print(f"Arché: {e}")
        continue

    if comando in ["estado examen", "estado del examen"]:
        from core.IA.examen import estado_examen
        print(estado_examen())
        continue

    if comando in ["iniciar examen automatico", "iniciar examen automático", "activar examen automatico"]:
        from core.IA.examen import iniciar_examen_en_background
        if _hilo_examen is not None and _hilo_examen.is_alive():
            print("Arché: El examen automático ya está corriendo.")
        else:
            _evento_detener_examen.clear()
            _hilo_examen = iniciar_examen_en_background(detener_evento=_evento_detener_examen, avisar=hablar)
            print("Arché: Empecé a examinarme en segundo plano.")
        continue

    if comando in ["detener examen automatico", "detener examen automático"]:
        if _hilo_examen is not None and _hilo_examen.is_alive():
            _evento_detener_examen.set()
            print("Arché: Voy a parar de examinarme después de esta ronda.")
        else:
            print("Arché: El examen automático no está corriendo.")
        continue

    # GUÍA DE COMANDOS (se arma sola desde main.py + catálogo, ver
    # core/guia_comandos.py) y CARGA MANUAL DE EJEMPLOS (core/IA/ensenar.py).

    if comando in ["comandos", "guia", "guía", "guia de comandos", "guía de comandos",
                   "lista de comandos", "que comandos hay", "qué comandos hay"]:
        from core.guia_comandos import mostrar_guia
        mostrar_guia()
        continue

    if comando in ["comandos todo", "comandos completos", "comandos completo", "lista completa de comandos",
                   "todos los comandos", "guia completa"]:
        from core.guia_comandos import mostrar_guia
        mostrar_guia(completo=True)
        continue

    if comando.startswith(("comandos buscar ", "comando buscar ", "buscar comando ", "buscar comandos ", "que comando sirve para ")):
        from core.guia_comandos import buscar_en_guia
        buscar_en_guia(comando.split(" ", 2)[2] if comando.startswith(("comandos buscar ", "comando buscar ", "buscar comando")) else comando.split(" para ", 1)[1])
        continue

    if comando.startswith("comandos de ") or comando.startswith("comandos "):
        from core.guia_comandos import mostrar_guia
        mostrar_guia(comando.split(" ", 1)[1].replace("de ", "", 1) if comando.startswith("comandos de ") else comando.split(" ", 1)[1])
        continue

    if comando in ["proximos pasos", "próximos pasos", "que hago ahora", "qué hago ahora",
                   "que me falta", "qué me falta", "siguiente paso"]:
        from core.guia_comandos import mostrar_proximos_pasos
        mostrar_proximos_pasos()
        continue

    if comando.startswith("enseñar ") or comando.startswith("ensenar "):
        from core.IA.ensenar import comando_ensenar
        comando_ensenar(comando_original)
        continue

    if comando.startswith("importar ejemplos"):
        from core.IA.ensenar import importar_ejemplos
        importar_ejemplos()
        continue

    if comando in ["intenciones", "lista de intenciones", "mis intenciones"]:
        from core.IA.ensenar import listar_intenciones
        print(listar_intenciones())
        continue

    if comando.startswith("intenciones de "):
        from core.IA.ensenar import listar_intenciones
        print(listar_intenciones(comando.split(" ", 2)[2]))
        continue

    # COMANDOS CONECTADOS POR ARCHÉ (registro en core/comandos_extra.py):
    # funciones que Arché escribió y vos aprobaste conectar a una frase.
    # Van después de los comandos fijos de arriba, así que nunca los pisan.

    if comandos_extra.manejar(comando_original):
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

    # Nada determinístico coincidió -> antes de caer al clasificador viejo
    # (que solo conoce ~17 intenciones), probamos el enrutador natural,
    # que conoce las ~60 del catálogo completo. Es opt-in ("modo natural
    # on") para no cambiarle el comportamiento a nadie que no lo pida.
    resultado = None
    if enrutador_natural.activo():
        ruteo = enrutador_natural.enrutar(comando_original)
        if ruteo:
            id_intencion, argumento, confianza = ruteo
            entrada = catalogo.POR_ID.get(id_intencion)
            if entrada and entrada["comando"]:
                # Tiene un comando fijo equivalente (ej. "crea una nota {X}")
                # -> se reinyecta y lo procesa el MISMO chequeo determinístico
                # de siempre, sin duplicar ninguna función acá.
                comando_canonico = catalogo.armar_comando(entrada, argumento)
                if entrada.get("confirmar"):
                    print(f"Arché: Entendí que pedís: {entrada['descripcion']}"
                          f"{f' ({argumento})' if argumento else ''}. Es delicado, "
                          f"¿lo confirmo? [s/n]")
                    ok = input("Tú: ").strip().lower()
                    if ok not in ("s", "si", "sí"):
                        print("Arché: Dale, cancelado.")
                        continue
                else:
                    print(f"Arché: (Entendí: {entrada['descripcion']})")
                _cola_comandos_naturales.append(comando_canonico)
                continue
            elif entrada:
                # Sin comando fijo (saludo, conversar, buscar, abrir, memoria,
                # modificar_codigo...) -> se arma el MISMO formato que ya
                # devuelve analizar(), y sigue por el switch de siempre, unas
                # líneas más abajo, sin tocarlo.
                resultado = {"intencion": id_intencion, "contenido": argumento}

    # Nada determinístico ni el enrutador natural coincidió -> AHORA sí
    # vale la pena clasificar con la IA (resolver() por plantillas primero,
    # Ollama como último recurso dentro de analizar()). La telemetría del
    # resultado ya se registra DENTRO de analizar() (en cerebroIA.py), con
    # información más precisa de qué capa resolvió el comando -- por eso
    # acá no se vuelve a registrar.
    if resultado is None:
        resultado = analizar(comando)
    intencion = resultado["intencion"]
    contenido = resultado["contenido"]

    # un saludo es corto y trae una palabra de saludo; una frase larga sin ella (p. ej. "explicame que es una
    # red neuronal") no es un saludo aunque una red se haya equivocado: se trata como charla.
    if intencion == "saludo" and not re.search(
            r"\b(hola|holi|ola|buen[oa]s?|hey|saludos|que tal|que mas|como (?:estas|andas|vas|te va)|alo|buenas)\b",
            comando.lower().replace("é", "e").replace("á", "a")):
        intencion, contenido = "conversar", comando

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

    elif intencion in ("buscar", "buscar_en_sitio"):
        # si el contenido nombra un sitio ("gatos en youtube"), busca ahí
        _en_sitio = control_pc.interpretar_busqueda("busca " + contenido) if contenido else None
        if _en_sitio:
            control_pc.buscar_en_sitio(*_en_sitio)
        elif intencion == "buscar_en_sitio" and contenido and control_pc.separar_sitio(contenido)[1]:
            # la red entendió que hay un sitio, pero Arché todavía no lo conoce
            _consulta, _sitio = control_pc.separar_sitio(contenido)
            control_pc.buscar_en_sitio_desconocido(_sitio, _consulta)
        elif contenido:
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
        else:
            respuesta_propia = buscar_respuesta(contenido)

            if respuesta_propia:
                # Capa 1: caché de respuestas por similitud semántica.
                print(f"Arché: {respuesta_propia}")
                registrar_comando(contenido, "conversar", resuelto_por="cache_respuestas")
            else:
                # Capa 2: última instancia. Piensa con la nube si hay clave e
                # internet (y busca en la web si la pregunta pide algo actual);
                # si no, o si la nube falla, responde Ollama como siempre.
                _r = cerebro_nube.responder(contenido)
                if _r["aviso"]:
                    print(f"Arché: ({_r['aviso']})")
                print(f"Arché: {_r['texto']}")
                if _r["cacheable"]:
                    # solo lo que contesta Ollama sin internet se guarda en el caché
                    guardar_respuesta(contenido, _r["texto"])
                registrar_comando(contenido, "conversar",
                                  resuelto_por="nube" if _r["fuente"] == "nube" else "ollama_conversar")
                if _r["fuente"] == "nube":
                    # en segundo plano: si fue conocimiento estable, queda guardado bajo varias formas de preguntarlo
                    aprender_de_nube.aprender_de_charla(contenido, _r["texto"], volatil=_r["web"])

    # COMANDO DESCONOCIDO

    elif intencion == "desconocido":
        print("Arché: Aún no sé hacer eso.")