"""
autotest.py
-------------
Ubicacion: Arche/core/IA/autotest.py

Arché se prueba a sí misma. Corre un chequeo automático de las partes
del sistema que se pueden probar SIN depender de que Ollama esté
respondiendo o de que el modelo de embeddings esté descargado (para
eso, las simula con respuestas controladas -- lo mismo que se hizo a
mano para validar cada cambio de código durante el desarrollo).

Qué prueba:
  1) Sintaxis de TODOS los .py del proyecto.
  2) Import limpio de los módulos clave.
  3) Comportamiento real de: narrador, sistema (recursos/contenido/
     limpieza), revisar_cambios_codigo (entorno aislado + backup),
     revertir_cambio_codigo, autorevision (detectores + referencias),
     clasificador (entrena bien con señal real, rechaza ruido),
     ollamaIA (historial, memoria, razonamiento en dos pasos),
     enrutar_cambio (hash estable, umbrales de decisión).

Qué NO prueba (no se puede desde acá, hace falta tu máquina real):
  - Que el modelo de Ollama genere código o respuestas BUENAS de verdad.
  - Que el modelo de embeddings rutee bien con significado real.
  - Rutas específicas de Windows (%TEMP%, etc.).

No toca ningún archivo real del proyecto ni dejar nada corrido
persistente: todo lo que escribe/borra pasa por archivos temporales
propios, y cualquier cosa que "monkeypatchea" (ollama.chat, funciones
de sistema/archivos) la restaura al terminar cada prueba.

Uso:
    python core/IA/autotest.py
    python core/IA/autotest.py -v      (muestra el detalle de cada test, no solo fallos)
"""

import ast
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

RAIZ_APP = Path(__file__).resolve().parents[2]  # Arche/
sys.path.insert(0, str(RAIZ_APP))

_TESTS = []
_VERBOSE = "-v" in sys.argv


def _test(fn):
    """Decorador: registra la función como test. El nombre de la función es el nombre del test."""
    _TESTS.append(fn)
    return fn


# ==================== 1) SINTAXIS DE TODO EL PROYECTO ====================

@_test
def test_sintaxis_de_todo_el_proyecto():
    rotos = []
    for archivo in RAIZ_APP.rglob("*.py"):
        if any(parte in ("backups_codigo", "__pycache__") for parte in archivo.parts):
            continue
        try:
            ast.parse(archivo.read_text(encoding="utf-8-sig"))
        except SyntaxError as e:
            rotos.append(f"{archivo.relative_to(RAIZ_APP)}: {e}")
    assert not rotos, f"{len(rotos)} archivo(s) con error de sintaxis:\n  " + "\n  ".join(rotos)


# ==================== 2) IMPORTS DE MÓDULOS CLAVE ====================

_MODULOS_CLAVE = [
    "core.rutas", "core.configuracion", "core.utilidades", "core.archivos",
    "core.memoria", "core.sistema", "core.notas", "core.recordatorio",
    "core.IA.ollamaIA", "core.IA.narrador", "core.IA.autorevision",
    "core.IA.revisar_cambios_codigo", "core.IA.proponer_cambio_codigo",
    "core.IA.revertir_cambio_codigo", "core.IA.enrutar_cambio",
    "core.IA.orquestador_autonomo", "core.IA.evaluar_confianza",
    "core.IA.clasificador", "core.IA.embeddings", "core.IA.estudio",
    "core.autodiagnostico",
]


@_test
def test_imports_de_modulos_clave():
    import importlib
    fallos = []
    for nombre in _MODULOS_CLAVE:
        try:
            importlib.import_module(nombre)
        except Exception as e:
            fallos.append(f"{nombre}: {type(e).__name__}: {e}")
    assert not fallos, f"{len(fallos)} módulo(s) no importan:\n  " + "\n  ".join(fallos)


# ==================== 3) NARRADOR ====================

@_test
def test_narrador_traduce_areas_conocidas():
    from core.IA.narrador import area_natural
    assert area_natural("core/IA/notas.py") == "las notas"
    assert area_natural("core/archivos.py") == "la búsqueda de archivos"
    # un archivo sin mapeo no debe explotar, arma algo razonable
    assert "_" not in area_natural("core/un_archivo_nuevo_random.py")


# ==================== 4) SISTEMA (pilar 2) ====================

@_test
def test_sistema_bytes_legibles():
    from core.sistema import _bytes_legibles
    assert _bytes_legibles(500) == "500.0 B"
    assert _bytes_legibles(1024) == "1.0 KB"
    assert _bytes_legibles(1024 * 1024 * 3) == "3.0 MB"


@_test
def test_sistema_interpretar_categorias_limpieza():
    from core.sistema import interpretar_categorias_limpieza as f
    casos = [
        ("limpia pycache", ["pycache"]),
        ("limpia tmp", ["archivos_tmp"]),
        ("limpia temporales windows", ["temporales_windows"]),
        ("limpia todo", ["pycache", "archivos_tmp", "temporales_windows"]),
        ("limpia algo random", []),
    ]
    fallos = [f"'{t}' -> {f(t)} (esperaba {e})" for t, e in casos if f(t) != e]
    assert not fallos, "; ".join(fallos)


@_test
def test_sistema_busqueda_por_contenido_y_limpieza():
    import core.sistema as sistema

    carpeta = Path(tempfile.mkdtemp(prefix="arche_test_sistema_"))
    try:
        (carpeta / "__pycache__").mkdir()
        (carpeta / "__pycache__" / "algo.pyc").write_text("cache", encoding="utf-8")
        (carpeta / "notas.txt").write_text("reunion sobre el proyecto arche manana", encoding="utf-8")
        (carpeta / "temporal.tmp").write_text("dato viejo", encoding="utf-8")

        cargar_indice_original = sistema.cargar_indice
        carpetas_originales = sistema.CARPETAS
        sistema.cargar_indice = lambda: [
            {"nombre": "notas", "ruta": str(carpeta / "notas.txt"), "tipo": "archivo", "extension": ".txt", "peso": 40, "modificado": ""},
            {"nombre": "temporal", "ruta": str(carpeta / "temporal.tmp"), "tipo": "archivo", "extension": ".tmp", "peso": 10, "modificado": ""},
        ]
        sistema.CARPETAS = [str(carpeta)]

        # búsqueda por contenido
        resultados = sistema.buscar_por_contenido("arche")
        assert len(resultados) == 1 and "notas.txt" in resultados[0]["ruta"]
        assert sistema.buscar_por_contenido("esto no existe en ningun lado") == []

        # análisis + limpieza selectiva (confirmar solo una categoría)
        reporte = sistema.analizar_limpieza()
        assert reporte["pycache"]["cantidad"] == 1
        assert reporte["archivos_tmp"]["cantidad"] == 1

        resultado = sistema.ejecutar_limpieza(reporte, ["pycache"])
        assert resultado["borrados"] == 1
        assert not (carpeta / "__pycache__").exists(), "borró pycache"
        assert (carpeta / "temporal.tmp").exists(), "NO debía tocar tmp (no se confirmó esa categoría)"
    finally:
        sistema.cargar_indice = cargar_indice_original
        sistema.CARPETAS = carpetas_originales
        shutil.rmtree(carpeta, ignore_errors=True)


# ==================== 5) REVISAR_CAMBIOS_CODIGO (entorno aislado) ====================

@_test
def test_revisar_cambios_entorno_aislado_no_toca_archivo_real_si_falla():
    from core.IA.revisar_cambios_codigo import aplicar_propuesta
    import hashlib

    ruta_real = RAIZ_APP / "core" / "rutas.py"
    hash_antes = hashlib.sha256(ruta_real.read_bytes()).hexdigest()

    propuesta_rota = {
        "id": "autotest-rota", "archivo": "core/rutas.py",
        "buscar": "import os",
        "reemplazar": "import os\nimport modulo_que_no_existe_autotest",
        "que": "autotest", "por_que": None,
    }
    resultado = aplicar_propuesta(propuesta_rota)
    hash_despues = hashlib.sha256(ruta_real.read_bytes()).hexdigest()

    assert resultado is False
    assert hash_antes == hash_despues, "el archivo real se modificó a pesar de que el cambio era inválido"


@_test
def test_revisar_cambios_aplica_y_revertir_deshace():
    from core.IA.revisar_cambios_codigo import aplicar_propuesta
    from core.IA.revertir_cambio_codigo import revertir
    import core.IA.ollamaIA as ollamaIA

    # Este test prueba aplicar+revertir, no la verificación con IA (esa
    # tiene su propio test) -- mockeamos generar_codigo para que no
    # dependa de tener Ollama corriendo, ya que el cambio de prueba
    # ("return") cuenta como lógica y dispara esa verificación.
    generar_codigo_original = ollamaIA.generar_codigo
    ollamaIA.generar_codigo = lambda prompt, num_predict=400, temperature=0.2: "OK"

    archivo_prueba = RAIZ_APP / "core" / "_autotest_scratch.py"
    archivo_prueba.write_text("def saludo():\n    return 'hola'\n", encoding="utf-8")
    try:
        propuesta = {
            "id": "autotest-ok", "archivo": "core/_autotest_scratch.py",
            "buscar": "return 'hola'",
            "reemplazar": "return 'hola, mundo'",
            "que": "autotest", "por_que": None,
        }
        aplicado = aplicar_propuesta(propuesta)
        assert aplicado is True
        assert "hola, mundo" in archivo_prueba.read_text(encoding="utf-8")

        revertido = revertir("core/_autotest_scratch.py")
        assert revertido is True
        assert "hola, mundo" not in archivo_prueba.read_text(encoding="utf-8")
    finally:
        ollamaIA.generar_codigo = generar_codigo_original
        archivo_prueba.unlink(missing_ok=True)
        carpeta_backups = RAIZ_APP / "core" / "IA" / "backups_codigo"
        for backup in carpeta_backups.glob("core___autotest_scratch.py.bak.*"):
            backup.unlink(missing_ok=True)


# ==================== 6) AUTOREVISION ====================

@_test
def test_autorevision_detectores_corren_sin_explotar():
    from core.IA.autorevision import (
        buscar_funciones_duplicadas, buscar_imports_sin_usar,
        buscar_codigo_muerto, buscar_except_desnudos,
    )
    assert isinstance(buscar_funciones_duplicadas(), list)
    assert isinstance(buscar_imports_sin_usar(), list)
    muerto = buscar_codigo_muerto()
    assert "alta_confianza" in muerto and "revisar_con_cuidado" in muerto
    assert isinstance(buscar_except_desnudos(), list)


@_test
def test_autorevision_no_marca_como_muerto_lo_usado_solo_desde_protegidos():
    # Regresión del bug real: generar_codigo() de ollamaIA.py se usa
    # SOLO desde archivos protegidos -- no debe aparecer como código
    # muerto (ver sesión de arreglo de autorevision.py).
    from core.IA.autorevision import _construir_indice_referencias
    idx = _construir_indice_referencias()
    assert idx.get("generar_codigo", 0) >= 2, "generar_codigo() parece sin referencias -- volvió el bug del índice"


# ==================== 7) CLASIFICADOR (red neuronal) ====================

@_test
def test_clasificador_entrena_con_senial_real_y_predice_bien():
    import numpy as np
    import core.IA.clasificador as clasificador
    import core.IA.aprendizaje as aprendizaje

    archivo_original = clasificador.ARCHIVO_MODELO
    cargar_original = aprendizaje.cargar
    try:
        clasificador.ARCHIVO_MODELO = os.path.join(tempfile.mkdtemp(), "clasificador_test.pkl")
        rng = np.random.RandomState(0)
        centros = {"buscar_archivo": [1, 0, 0], "conversar": [0, 1, 0], "abrir_programa": [0, 0, 1]}
        datos = [
            {"embedding": (np.array(c) + rng.randn(3) * 0.15).tolist(), "accion": accion}
            for accion, c in centros.items() for _ in range(25)
        ]
        aprendizaje.cargar = lambda: datos

        assert clasificador.entrenar(silencioso=True) is True
        accion, confianza = clasificador.predecir([0.02, 0.97, -0.05])
        assert accion == "conversar" and confianza > 0.5
    finally:
        clasificador.ARCHIVO_MODELO = archivo_original
        aprendizaje.cargar = cargar_original


@_test
def test_clasificador_rechaza_ruido_sin_senial():
    # Regresión del bug de fuga de datos: con puro ruido, antes del fix
    # esto se colaba con ~60% de "precisión válida". Ahora debe rechazarlo.
    import numpy as np
    import core.IA.clasificador as clasificador
    import core.IA.aprendizaje as aprendizaje

    archivo_original = clasificador.ARCHIVO_MODELO
    cargar_original = aprendizaje.cargar
    try:
        clasificador.ARCHIVO_MODELO = os.path.join(tempfile.mkdtemp(), "clasificador_test.pkl")
        rng = np.random.RandomState(1)
        datos = [
            {"embedding": rng.randn(20).tolist(), "accion": accion}
            for accion, n in [("buscar_archivo", 80), ("conversar", 80), ("abrir_programa", 20)]
            for _ in range(n)
        ]
        aprendizaje.cargar = lambda: datos

        assert clasificador.entrenar(silencioso=True) is False, "aceptó un modelo entrenado sobre puro ruido -- volvió el bug de fuga de datos"
    finally:
        clasificador.ARCHIVO_MODELO = archivo_original
        aprendizaje.cargar = cargar_original


# ==================== 8) OLLAMAIA (historial, memoria, razonamiento) ====================

def _con_ollama_simulado(respuestas_por_llamada):
    """Monkeypatchea ollama.chat con respuestas controladas; devuelve (parche, lista_de_llamadas)."""
    import core.IA.ollamaIA as ollamaIA
    llamadas = []
    iterador = iter(respuestas_por_llamada)

    def _fake(model, keep_alive, messages, options):
        llamadas.append(messages)
        try:
            texto = next(iterador)
        except StopIteration:
            texto = respuestas_por_llamada[-1]
        return {"message": {"content": texto}}

    original = ollamaIA.ollama.chat
    ollamaIA.ollama.chat = _fake
    return ollamaIA, llamadas, original


@_test
def test_ollamaIA_sin_historial_es_identico_a_siempre():
    ollamaIA, llamadas, original = _con_ollama_simulado(["respuesta cualquiera"])
    try:
        ollamaIA.conversar("hola")
        assert len(llamadas[-1]) == 1 and llamadas[-1][0]["role"] == "user", \
            "el camino sin historial/memoria no debe cambiar -- lo usan estudio.py y generar_changelog.py"
    finally:
        ollamaIA.ollama.chat = original


@_test
def test_ollamaIA_historial_mantiene_contexto_entre_turnos():
    ollamaIA, llamadas, original = _con_ollama_simulado([
        "El iPhone 15 cuesta 799 dólares.",
        "En euros serían unos 900€.",
    ])
    try:
        ollamaIA.reiniciar_historial()
        ollamaIA.conversar("cuanto cuesta el iphone 15", usar_historial=True)
        ollamaIA.conversar("y en euros?", usar_historial=True)
        mensajes_segunda_llamada = llamadas[-1]
        assert any("iphone 15" in m["content"].lower() for m in mensajes_segunda_llamada), \
            "la segunda llamada no incluyó el turno anterior"
    finally:
        ollamaIA.ollama.chat = original
        ollamaIA.reiniciar_historial()


@_test
def test_ollamaIA_memoria_filtra_recordatorios():
    import json
    import core.rutas as rutas
    import core.memoria as memoria

    carpeta_temp = tempfile.mkdtemp()
    archivo_original_memoria = memoria.archivo_memoria
    try:
        memoria.archivo_memoria = os.path.join(carpeta_temp, "memoria.json")
        with open(memoria.archivo_memoria, "w", encoding="utf-8") as f:
            json.dump([
                {"tipo": "gusto", "contenido": "le gusta el mate", "fecha": "", "prioridad": "normal", "estado": "pendiente"},
                {"tipo": "recordatorio", "contenido": "comprar pan mañana", "fecha": "", "prioridad": "alta", "estado": "pendiente"},
            ], f)

        ollamaIA, llamadas, original = _con_ollama_simulado(["ok"])
        try:
            ollamaIA.reiniciar_historial()
            ollamaIA.conversar("hola", usar_memoria=True)
            system_msg = llamadas[-1][0]["content"]
            assert "mate" in system_msg, "no inyectó el gusto guardado"
            assert "pan" not in system_msg, "filtró mal -- un recordatorio de tareas se filtró a la charla natural"
        finally:
            ollamaIA.ollama.chat = original
            ollamaIA.reiniciar_historial()
    finally:
        memoria.archivo_memoria = archivo_original_memoria
        shutil.rmtree(carpeta_temp, ignore_errors=True)


@_test
def test_ollamaIA_razonar_hace_dos_llamadas_y_no_filtra_el_borrador():
    ollamaIA, llamadas, original = _con_ollama_simulado([
        "Borrador interno: comparar precio y calidad.",
        "Yo elegiría la opción B.",
    ])
    try:
        ollamaIA.reiniciar_historial()
        respuesta, razonamiento = ollamaIA.razonar_y_responder(
            "cual es mejor, A o B?", usar_historial=True, mostrar_razonamiento=True
        )
        assert len(llamadas) == 2, "debe hacer 2 llamadas: borrador + respuesta final"
        assert "Borrador interno" not in respuesta, "el borrador se filtró a la respuesta visible"
        assert len(ollamaIA._historial_conversacion) == 2, "el historial no debe guardar el borrador, solo la respuesta final"
    finally:
        ollamaIA.ollama.chat = original
        ollamaIA.reiniciar_historial()


@_test
def test_ollamaIA_heuristica_razonamiento_profundo():
    from core.IA.ollamaIA import necesita_razonamiento_profundo as f
    casos = [
        ("hola", False), ("gracias", False),
        ("¿cuál es mejor, Python o JavaScript?", True),
        ("¿por qué falla esto?", True),
    ]
    fallos = [f"'{t}' -> {f(t)} (esperaba {e})" for t, e in casos if f(t) != e]
    assert not fallos, "; ".join(fallos)


# ==================== 9) ENRUTAR_CAMBIO ====================

@_test
def test_enrutar_cambio_hash_estable_entre_llamadas():
    # OJO: hash() de Python es estable DENTRO de un mismo proceso (el
    # seed se fija una vez al arrancar) -- comparar _hash_codigo(x) ==
    # _hash_codigo(x) en el mismo proceso NUNCA hubiera detectado el
    # bug real (que solo aparece entre reinicios de Arché, procesos
    # distintos). Por eso esto compara contra un proceso de Python
    # NUEVO, aparte -- es la única forma de probar esto de verdad.
    import subprocess
    codigo = "def f():\n    return 1"

    from core.IA.enrutar_cambio import _hash_codigo
    hash_en_este_proceso = _hash_codigo(codigo)

    script = (
        f"import sys; sys.path.insert(0, {str(RAIZ_APP)!r}); "
        f"from core.IA.enrutar_cambio import _hash_codigo; "
        f"print(_hash_codigo({codigo!r}))"
    )
    resultado = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    hash_en_otro_proceso = resultado.stdout.strip()

    assert hash_en_este_proceso == hash_en_otro_proceso, (
        "el hash cambió entre procesos distintos -- volvió el bug de hash() "
        "randomizado por Python (el cache de embeddings dejaría de servir "
        "entre reinicios de Arché)"
    )


@_test
def test_enrutar_cambio_decidir_destino_respeta_umbrales():
    import core.IA.enrutar_cambio as enrutar
    import core.IA.embeddings as embeddings

    vectores = {
        "match alto": [1.0, 0.0, 0.0],
        "existente alto": [0.9, 0.1, 0.0],
        "sin relacion": [0.0, 0.0, 1.0],
    }
    embeddings_original = embeddings.calcular_embedding
    similitud_original = embeddings.similitud_coseno
    cargar_original = enrutar._cargar_indice
    construir_original = enrutar._construir_indice
    try:
        embeddings.calcular_embedding = lambda texto: vectores.get(texto, [0.0, 0.0, 1.0])
        embeddings.similitud_coseno = lambda a, b: sum(x * y for x, y in zip(a, b))
        indice_falso = {
            "core/ventas.py::calcular_total": {
                "archivo": "core/ventas.py", "funcion": "calcular_total",
                "embedding": vectores["existente alto"],
            }
        }
        enrutar._cargar_indice = lambda: indice_falso
        enrutar._construir_indice = lambda: indice_falso

        d = enrutar.decidir_destino("match alto")
        assert d["tipo"] == "editar_existente" and d["confianza_alta"] is True

        d = enrutar.decidir_destino("sin relacion")
        assert d["tipo"] == "crear_nuevo"
    finally:
        embeddings.calcular_embedding = embeddings_original
        embeddings.similitud_coseno = similitud_original
        enrutar._cargar_indice = cargar_original
        enrutar._construir_indice = construir_original


@_test
def test_orquestador_detecta_correccion_que_no_cambio_nada():
    # Patrón de "harness engineering": si el intento nuevo (con tu
    # corrección) resulta idéntico al anterior, insistir hasta agotar
    # reintentos sería repetir el mismo error a ciegas -- debe cortar
    # apenas lo detecta, no gastar todos los reintentos igual.
    import builtins
    import core.IA.orquestador_autonomo as orq

    input_original = builtins.input
    try:
        orquestador = orq.OrquestadorAutonomo(reintentos_max=3)
        propuesta_fija = {
            "id": "x", "archivo": "core/algo.py",
            "buscar": "return 1", "reemplazar": "return 2",
            "que": "segun: prueba", "por_que": None,
        }
        llamadas = []

        def _generar_falso(orden, sugerencia_extra=None):
            llamadas.append(sugerencia_extra)
            return dict(propuesta_fija), None

        orquestador._generar_propuesta = _generar_falso
        entradas = iter(["una correccion que en los hechos no cambia nada", "otra mas, no debería hacer falta"])
        builtins.input = lambda prompt="": next(entradas)

        resultado = orquestador.ejecutar_meta("arreglame algo")
        assert resultado is False
        assert len(llamadas) == 2, f"debió cortar tras 1 regeneración sin cambios, gastó {len(llamadas) - 1}"
    finally:
        builtins.input = input_original


@_test
def test_reasoning_sandwich_verifica_riesgo_medio_y_alto_no_bajo():
    # "Reasoning sandwich": los cambios de bajo riesgo NO pagan el costo
    # extra de una llamada a Ollama; los de riesgo medio/cuidado sí se
    # revisan una vez más antes de tocar el archivo real, y si Ollama
    # marca un problema concreto, el cambio NO se aplica.
    import hashlib
    import core.IA.ollamaIA as ollamaIA
    from core.IA.revisar_cambios_codigo import aplicar_propuesta

    llamadas = []

    def _fake_generar_codigo(prompt, num_predict=400, temperature=0.2):
        llamadas.append(prompt)
        if "ELIMINAR TODO" in prompt:
            return "PROBLEMA: borra la validación de permisos sin reemplazarla"
        return "OK"

    original = ollamaIA.generar_codigo
    ollamaIA.generar_codigo = _fake_generar_codigo
    rutas_creadas = []
    try:
        def _archivo(nombre, contenido):
            ruta = RAIZ_APP / f"core/_autotest_sandwich_{nombre}.py"
            ruta.write_text(contenido, encoding="utf-8")
            rutas_creadas.append(ruta)
            return f"core/_autotest_sandwich_{nombre}.py"

        # bajo riesgo: sin lógica condicional, nombre sin referencias -- 0 llamadas
        r_bajo = _archivo("bajo", "def funcion_unica_autotest_sandwich_uno():\n    valor = 1\n    return valor\n")
        aplicado = aplicar_propuesta({"id": "s1", "archivo": r_bajo, "buscar": "    valor = 1", "reemplazar": "    valor = 1  # comentario", "que": "comentario", "por_que": None})
        assert aplicado is True and len(llamadas) == 0, "un cambio de bajo riesgo no debería llamar a Ollama para verificar"

        # riesgo medio, Ollama aprueba -- se aplica
        r_medio_ok = _archivo("medio_ok", "def funcion_unica_autotest_sandwich_dos():\n    if True:\n        valor = 1\n    return valor\n")
        aplicado = aplicar_propuesta({"id": "s2", "archivo": r_medio_ok, "buscar": "    if True:\n        valor = 1", "reemplazar": "    if True:\n        valor = 1\n    else:\n        valor = 2", "que": "agregar rama else", "por_que": None})
        assert aplicado is True and len(llamadas) == 1

        # riesgo medio, Ollama encuentra un problema -- NO se aplica, archivo intacto
        r_medio_mal = _archivo("medio_mal", "def funcion_unica_autotest_sandwich_tres():\n    if True:\n        permiso = True\n    return permiso\n")
        ruta_completa = RAIZ_APP / r_medio_mal
        hash_antes = hashlib.sha256(ruta_completa.read_bytes()).hexdigest()
        aplicado = aplicar_propuesta({"id": "s3", "archivo": r_medio_mal, "buscar": "    if True:\n        permiso = True", "reemplazar": "    if True:\n        pass  # ELIMINAR TODO chequeo de permisos", "que": "sacar chequeo", "por_que": None})
        hash_despues = hashlib.sha256(ruta_completa.read_bytes()).hexdigest()
        assert aplicado is False, "debió bloquear el cambio marcado como PROBLEMA"
        assert hash_antes == hash_despues, "no debió tocar el archivo real"
        assert len(llamadas) == 2
    finally:
        ollamaIA.generar_codigo = original
        for ruta in rutas_creadas:
            ruta.unlink(missing_ok=True)
        for backup in (RAIZ_APP / "core" / "IA" / "backups_codigo").glob("core___autotest_sandwich_*"):
            backup.unlink(missing_ok=True)


# ==================== RUNNER ====================

def main():
    print("=" * 60)
    print("Arché -- autotest")
    print("=" * 60)

    ok, fallo = 0, 0
    for fn in _TESTS:
        nombre = fn.__name__
        try:
            fn()
            ok += 1
            if _VERBOSE:
                print(f"  OK   {nombre}")
        except AssertionError as e:
            fallo += 1
            print(f"  MAL  {nombre}")
            print(f"       {e}")
        except Exception:
            fallo += 1
            print(f"  MAL  {nombre}  (error inesperado, no un assert)")
            print("       " + "\n       ".join(traceback.format_exc().splitlines()[-3:]))

    print("=" * 60)
    total = ok + fallo
    if fallo == 0:
        print(f"Arché: Me probé entera -- {ok}/{total} pruebas pasaron. Todo en orden.")
    else:
        print(f"Arché: Me probé entera -- {ok}/{total} pasaron, {fallo} fallaron (ver arriba).")
    print("=" * 60)
    return 0 if fallo == 0 else 1


if __name__ == "__main__":
    sys.exit(main())