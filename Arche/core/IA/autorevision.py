"""
autorevision.py
------------------
Ubicacion: Arche/core/IA/autorevision.py

Arche revisa su PROPIO codigo por iniciativa propia (no hace falta
decirle que funcion mirar), en UN SOLO pase unificado sobre todo el
proyecto:

  - Chequeos deterministas (sin Ollama, gratis, siempre corren):
    funciones duplicadas, imports sin usar, funciones que parecen no
    usarse en ningun lado, "except:" desnudos. Son hallazgos, no
    correcciones automaticas.

  - Revision asistida por Ollama, CON MEMORIA: cada funcion se hashea
    y se guarda en revision_codigo_cache.json junto con el resultado
    de su revision. La proxima vez que corras autorevision(), SOLO
    se le pregunta a Ollama por las funciones nuevas o que cambiaron
    desde la ultima vez (hash distinto) -- las que ya se revisaron y
    no cambiaron se saltan. Asi, con el uso, cada corrida gasta cada
    vez menos en Ollama, sin perder cobertura sobre lo que si cambio.
    Esto es "aprender lo necesario, nada en exceso": Arche recuerda
    lo que ya reviso, en vez de repreguntar por gusto.

  Si Ollama encuentra un bug real en una funcion, genera una
  propuesta de correccion real con proponer_cambio_ia() -- que pasa
  por el MISMO gate de aprobacion de siempre (revisar_cambios_codigo.py).
  Autorevisarse NUNCA implica aplicar nada sin tu aprobacion explicita.

Alcance: todo el proyecto (Arche/), excluyendo los archivos
protegidos del propio sistema de auto-modificacion (ver
proponer_cambio_codigo.ARCHIVOS_PROTEGIDOS) y carpetas irrelevantes.

Uso:
    python core/IA/autorevision.py                  (pase completo, con memoria)
    python core/IA/autorevision.py --sin-ia          (solo chequeos deterministas)
    python core/IA/autorevision.py --limite 20       (limita cuantas funciones NUEVAS revisa esta vez)
"""

import ast
import hashlib
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Este archivo vive en Arche/core/IA/autorevision.py -- agregamos la
# raiz real del proyecto (Arche/) a sys.path ANTES de importar nada
# de core.IA, para que el import funcione sin importar desde que
# carpeta se ejecute este script.
_RAIZ_APP = Path(__file__).resolve().parents[2]
if str(_RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP))

from core.IA.proponer_cambio_codigo import (
    RAIZ_APP, ARCHIVOS_PROTEGIDOS, proponer_cambio_ia, proponer_cambio_manual,
)

BASE = Path(__file__).parent
ARCHIVO_CACHE_REVISION = BASE / "revision_codigo_cache.json"

IGNORAR_CARPETAS = {
    "__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database",
    "backups_codigo", "backups_autoconocimiento",
}
IGNORAR_ARCHIVOS = {"autorevision.py"}  # este mismo archivo: no tiene sentido auto-revisarse a si mismo aca


def _hash_funcion(codigo):
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def _cargar_cache():
    if not ARCHIVO_CACHE_REVISION.exists():
        return {}
    try:
        return json.loads(ARCHIVO_CACHE_REVISION.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _guardar_cache(cache):
    ARCHIVO_CACHE_REVISION.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _archivos_del_proyecto(incluir_protegidos=False):
    """
    incluir_protegidos=False (default): para buscar CANDIDATOS a
    proponer cambios (duplicados, imports sin usar, codigo muerto) --
    nunca tiene sentido proponer un cambio sobre un archivo protegido,
    asi que se excluyen aca.

    incluir_protegidos=True: para CONTAR REFERENCIAS (ver
    _construir_indice_referencias). Un archivo protegido puede ser el
    UNICO lugar que usa una funcion (ej. generar_codigo() de
    ollamaIA.py, que solo se llama desde proponer_cambio_codigo.py,
    que esta protegido) -- si se lo excluye del conteo, esa funcion
    parece "sin referencias" y autorevision propondria borrarla,
    rompiendo el propio sistema de auto-modificacion. El archivo
    protegido no se toca nunca, pero lo que EL referencia si cuenta.
    """
    for archivo in RAIZ_APP.rglob("*.py"):
        rel = archivo.relative_to(RAIZ_APP).as_posix()
        if any(parte in IGNORAR_CARPETAS for parte in archivo.parts):
            continue
        if not incluir_protegidos and archivo.name in IGNORAR_ARCHIVOS:
            continue
        if not incluir_protegidos and rel in ARCHIVOS_PROTEGIDOS:
            continue
        yield archivo, rel


def _funciones_de(ruta):
    try:
        contenido = ruta.read_text(encoding="utf-8-sig")
        arbol = ast.parse(contenido, filename=str(ruta))
    except (SyntaxError, UnicodeDecodeError):
        return []
    lineas = contenido.splitlines(keepends=True)
    funciones = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inicio = nodo.decorator_list[0].lineno if nodo.decorator_list else nodo.lineno
            fin = nodo.end_lineno
            codigo = "".join(lineas[inicio - 1:fin])
            funciones.append({"nombre": nodo.name, "codigo": codigo})
    return funciones


def _normalizar_cuerpo(codigo):
    """Para detectar duplicados: compara la 'forma' del codigo linea
    por linea (ignorando indentacion exacta y espacios de mas), no
    los nombres de variables -- suficiente para encontrar copias
    pegadas con cambios cosmeticos."""
    lineas = [l.strip() for l in codigo.splitlines() if l.strip()]
    return "\n".join(lineas)


# ------------------------- CAPA 1: deterministica -------------------------

def buscar_funciones_duplicadas():
    """Funciones con cuerpo casi identico, en archivos iguales o
    distintos, aunque tengan nombres distintos. Señal de que
    convendria unificarlas en una sola."""
    vistos = {}
    duplicados = []

    for archivo, rel in _archivos_del_proyecto():
        for fn in _funciones_de(archivo):
            if len(fn["codigo"].splitlines()) < 3:
                continue  # funciones muy cortas dan falsos positivos seguido
            clave = hashlib.sha256(_normalizar_cuerpo(fn["codigo"]).encode()).hexdigest()
            if clave in vistos:
                duplicados.append({
                    "archivo_a": vistos[clave]["archivo"], "funcion_a": vistos[clave]["nombre"],
                    "archivo_b": rel, "funcion_b": fn["nombre"],
                })
            else:
                vistos[clave] = {"archivo": rel, "nombre": fn["nombre"]}

    return duplicados


def buscar_imports_sin_usar():
    resultados = []
    for archivo, rel in _archivos_del_proyecto():
        try:
            contenido = archivo.read_text(encoding="utf-8-sig")
            arbol = ast.parse(contenido, filename=str(archivo))
        except (SyntaxError, UnicodeDecodeError):
            continue

        importados = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    importados.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(nodo, ast.ImportFrom):
                for alias in nodo.names:
                    if alias.name != "*":
                        importados.add(alias.asname or alias.name)

        usados = {
            nodo.id for nodo in ast.walk(arbol) if isinstance(nodo, ast.Name)
        } | {
            nodo.attr for nodo in ast.walk(arbol) if isinstance(nodo, ast.Attribute)
        }

        for nombre in importados - usados:
            resultados.append({"archivo": rel, "import": nombre})

    return resultados


def _nombres_de_clases_visitor(arbol):
    """Nombres de clases que heredan de ast.NodeVisitor / NodeTransformer
    (o algo que TERMINA en 'Visitor'/'Transformer', para cubrir subclases
    de subclases sin tener que resolver la jerarquia completa)."""
    clases_visitor = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef):
            for base in nodo.bases:
                nombre_base = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if "Visitor" in nombre_base or "Transformer" in nombre_base:
                    clases_visitor.add(nodo.name)
    return clases_visitor


def _es_metodo_de_despacho_dinamico(archivo, nombre_funcion):
    """
    True si la funcion es un metodo tipo visit_X/generic_visit dentro
    de una clase que hereda de NodeVisitor/NodeTransformer -- estos se
    llaman por convencion de nombre via getattr(), NUNCA aparecen
    escritos literal en ningun lado del codigo. Es EXACTAMENTE el
    patron que genero el falso positivo con introspeccion.py.
    """
    if not (nombre_funcion.startswith("visit_") or nombre_funcion == "generic_visit"):
        return False
    try:
        contenido = archivo.read_text(encoding="utf-8-sig")
        arbol = ast.parse(contenido)
    except (SyntaxError, UnicodeDecodeError):
        return False
    return bool(_nombres_de_clases_visitor(arbol))


def _referencias_reales(archivo_rel, nombre_funcion, indice_referencias):
    """Cuenta referencias a `nombre_funcion` fuera de su propia
    definicion, usando nombres/atributos reales del AST (no texto
    plano) -- evita falsos positivos por substrings casuales, aunque
    sigue sin resolver despacho dinamico (para eso esta la funcion de
    arriba, que excluye esos casos aparte)."""
    return indice_referencias.get(nombre_funcion, 0)


def _construir_indice_referencias():
    """Recorre TODO el proyecto una sola vez y cuenta cuantas veces
    aparece cada identificador como Name o como atributo (nodo.attr)
    -- incluye la propia definicion, por eso el umbral de 'sin usar'
    es <= 1 (solo la definicion) en vez de == 0."""
    conteo = {}
    for archivo, rel in _archivos_del_proyecto(incluir_protegidos=True):
        try:
            contenido = archivo.read_text(encoding="utf-8-sig")
            arbol = ast.parse(contenido)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Name):
                conteo[nodo.id] = conteo.get(nodo.id, 0) + 1
            elif isinstance(nodo, ast.Attribute):
                conteo[nodo.attr] = conteo.get(nodo.attr, 0) + 1
            elif isinstance(nodo, ast.ImportFrom):
                # "from X import Y as Z": lo que se usa en el resto del
                # archivo es el Name "Z" (ya contado arriba), pero el
                # NOMBRE REAL definido en X es "Y" -- sin esto, una
                # funcion importada con alias parece "sin referencias"
                # en su archivo de origen y se propone borrarla por error.
                for alias in nodo.names:
                    conteo[alias.name] = conteo.get(alias.name, 0) + 1
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # la propia definicion tambien cuenta como una "aparicion"
                conteo[nodo.name] = conteo.get(nodo.name, 0) + 1
    return conteo


def buscar_codigo_muerto():
    """
    Funciones que parecen no usarse en ningun lado, usando referencias
    REALES de ast (Name/Attribute), no texto plano -- mas preciso que
    la version anterior.

    Devuelve dos listas:
      - "alta_confianza": cero referencias reales fuera de su propia
        definicion, y NO son metodos de despacho dinamico (visit_* en
        NodeVisitor). Candidatos genuinos a proponer su eliminacion.
      - "revisar_con_cuidado": matchean el patron de despacho dinamico
        (ej. visit_FunctionDef) -- probablemente SI se usan, pero por
        convencion de nombre, no por texto literal. Nunca se proponen
        para borrar automaticamente.
    """
    indice = _construir_indice_referencias()
    alta_confianza = []
    revisar_con_cuidado = []

    for archivo, rel in _archivos_del_proyecto():
        for fn in _funciones_de(archivo):
            if fn["nombre"].startswith("__"):
                continue

            if _es_metodo_de_despacho_dinamico(archivo, fn["nombre"]):
                revisar_con_cuidado.append({"archivo": rel, "nombre": fn["nombre"], "motivo": "posible despacho dinamico (visit_*)"})
                continue

            referencias = _referencias_reales(rel, fn["nombre"], indice)
            if referencias <= 1:  # solo su propia definicion
                alta_confianza.append({"archivo": rel, "nombre": fn["nombre"], "codigo": fn["codigo"]})

    return {"alta_confianza": alta_confianza, "revisar_con_cuidado": revisar_con_cuidado}


def buscar_except_desnudos():
    resultados = []
    for archivo, rel in _archivos_del_proyecto():
        try:
            contenido = archivo.read_text(encoding="utf-8-sig")
            arbol = ast.parse(contenido, filename=str(archivo))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.ExceptHandler) and nodo.type is None:
                resultados.append({"archivo": rel, "linea": nodo.lineno})
    return resultados


def ejecutar_capa_1():
    return {
        "duplicados": buscar_funciones_duplicadas(),
        "imports_sin_usar": buscar_imports_sin_usar(),
        "codigo_muerto": buscar_codigo_muerto(),
        "except_desnudos": buscar_except_desnudos(),
    }


# ------------------------- Revisión unificada (determinista + Ollama con memoria) -------------------------

def revisar_funcion_con_ollama(archivo_rel, fn):
    """
    Le pregunta al modelo DOS cosas en una sola llamada (eficiente):
    si hay un bug real, y si hay una mejora de calidad clara (más
    simple, más eficiente, menos repetición) -- sin pedir opiniones
    de estilo subjetivas, solo cosas concretas y accionables.

    Usa generar_codigo (modelo especializado en código), no conversar
    (arche-lora) -- ya vimos hoy que arche-lora es poco confiable para
    tareas que requieren entender código de verdad.

    Devuelve (bug_o_None, mejora_o_None).
    """
    from core.IA.ollamaIA import generar_codigo

    prompt = f"""Sos un revisor de código Python breve y directo.

Archivo: {archivo_rel}

Función a revisar:
---
{fn['codigo']}
---

Respondé EXACTAMENTE con este formato, dos líneas:

BUG: <descripción corta de un bug real y concreto (variable mal usada, condición invertida, recurso sin cerrar, comparación incorrecta), o la palabra NINGUNO si no hay ninguno>
MEJORA: <descripción corta de una mejora de CALIDAD concreta y accionable (código repetido que se puede simplificar, forma más eficiente de hacer lo mismo, manejo de errores faltante), o la palabra NINGUNA si no hay ninguna>

No expliques nada más. No dupliques información entre BUG y MEJORA -- si ya lo pusiste como bug, no lo repitas como mejora.
"""
    respuesta = generar_codigo(prompt, num_predict=150, temperature=0.1).strip()

    bug = None
    mejora = None
    for linea in respuesta.splitlines():
        linea = linea.strip()
        if linea.upper().startswith("BUG:"):
            valor = linea.split(":", 1)[1].strip()
            if valor and not valor.upper().startswith("NINGUNO"):
                bug = valor
        elif linea.upper().startswith("MEJORA:"):
            valor = linea.split(":", 1)[1].strip()
            if valor and not valor.upper().startswith("NINGUNA"):
                mejora = valor

    return bug, mejora


def generar_propuestas_codigo_muerto(candidatos_alta_confianza):
    """
    Para cada funcion de "alta confianza" (cero referencias reales,
    sin patron de despacho dinamico), genera una propuesta de
    ELIMINACION determinista (sin Ollama, no hace falta: borrar un
    bloque de codigo es mecanico). La propuesta pasa por el MISMO
    gate de siempre (revisar_cambios_codigo.py), con backup, diff
    real, sintaxis + smoke test, y tu aprobacion explicita.
    """
    ids_generados = []
    for candidato in candidatos_alta_confianza:
        propuesta, error = proponer_cambio_manual(
            archivo=candidato["archivo"],
            buscar=candidato["codigo"],
            reemplazar="",
            que=f"Eliminar la función '{candidato['nombre']}', que no tiene referencias reales en ningún otro lugar del proyecto.",
        )
        if propuesta:
            ids_generados.append(propuesta["id"])
    return ids_generados


def autorevisar(usar_ollama=True, limite_nuevas=None, proponer_borrado_codigo_muerto=True):
    """
    Pase UNICO y unificado sobre todo el proyecto:
      - Corre los chequeos deterministas globales (duplicados, imports
        sin usar, codigo muerto, except desnudos) -- siempre, gratis.
      - Para el codigo muerto de "alta confianza" (ver
        buscar_codigo_muerto), genera propuestas de ELIMINACION reales
        -- vos las aprobas o rechazas en revisar_cambios_codigo.py,
        igual que cualquier otro cambio. El codigo "a revisar con
        cuidado" (patron de despacho dinamico) NUNCA se propone para
        borrar, solo se reporta.
      - Para cada funcion, decide si vale la pena consultarle a Ollama:
        SOLO si es nueva o cambio desde la ultima autorevision (hash
        distinto al que hay en revision_codigo_cache.json). Si ya la
        reviso antes y no cambio, la salta -- esto es la "memoria":
        Arche no vuelve a preguntarle al modelo por algo que ya sabe
        que esta bien.

    Con el tiempo, a medida que el codigo se estabiliza, cada corrida
    gasta cada vez menos en Ollama (solo lo nuevo/modificado), sin
    perder cobertura sobre el codigo que SI cambio.

    Devuelve un unico reporte combinado (determinista + IA).
    """
    reporte = ejecutar_capa_1()
    reporte["revision_ia"] = {
        "nuevas_o_modificadas": 0,
        "saltadas_por_cache": 0,
        "bugs_encontrados": [],
        "mejoras_encontradas": [],
        "propuestas_generadas": [],
    }

    reporte["codigo_muerto"]["se_propusieron_eliminaciones"] = False
    if proponer_borrado_codigo_muerto and reporte["codigo_muerto"]["alta_confianza"]:
        ids = generar_propuestas_codigo_muerto(reporte["codigo_muerto"]["alta_confianza"])
        reporte["revision_ia"]["propuestas_generadas"].extend(ids)
        reporte["codigo_muerto"]["se_propusieron_eliminaciones"] = True

    if not usar_ollama:
        return reporte

    cache = _cargar_cache()
    revisadas_esta_vez = 0

    for archivo, rel in _archivos_del_proyecto():
        for fn in _funciones_de(archivo):
            clave = f"{rel}::{fn['nombre']}"
            hash_actual = _hash_funcion(fn["codigo"])

            entrada_previa = cache.get(clave)
            if entrada_previa and entrada_previa.get("hash") == hash_actual:
                reporte["revision_ia"]["saltadas_por_cache"] += 1
                continue  # ya la conocemos, sin cambios -> no gastamos Ollama de nuevo

            if limite_nuevas and revisadas_esta_vez >= limite_nuevas:
                continue  # hay mas nuevas/modificadas de las que este pase quiere cubrir

            revisadas_esta_vez += 1
            reporte["revision_ia"]["nuevas_o_modificadas"] += 1

            print(f"  revisando {clave} (nueva o modificada)...", end=" ", flush=True)
            bug, mejora = revisar_funcion_con_ollama(rel, fn)

            if not bug and not mejora:
                print("ok")
            else:
                if bug:
                    print(f"⚠ bug: {bug}")
                    reporte["revision_ia"]["bugs_encontrados"].append({"archivo": rel, "funcion": fn["nombre"], "bug": bug})
                    instruccion_bug = f"en la función '{fn['nombre']}': corregir este bug: {bug}"
                    propuesta, error = proponer_cambio_ia(rel, instruccion_bug, origen="autorevision")
                    if propuesta:
                        reporte["revision_ia"]["propuestas_generadas"].append(propuesta["id"])
                        print(f"    -> propuesta {propuesta['id']} generada")
                    elif error:
                        print(f"    -> no se pudo generar propuesta: {error}")

                if mejora:
                    print(f"  ✎ mejora: {mejora}")
                    reporte["revision_ia"]["mejoras_encontradas"].append({"archivo": rel, "funcion": fn["nombre"], "mejora": mejora})
                    instruccion_mejora = f"en la función '{fn['nombre']}': mejorar esto (sin cambiar su comportamiento): {mejora}"
                    propuesta_m, error_m = proponer_cambio_ia(rel, instruccion_mejora, origen="autorevision")
                    if propuesta_m:
                        reporte["revision_ia"]["propuestas_generadas"].append(propuesta_m["id"])
                        print(f"    -> propuesta {propuesta_m['id']} generada")
                    elif error_m:
                        print(f"    -> no se pudo generar propuesta: {error_m}")

            cache[clave] = {
                "hash": hash_actual,
                "resultado": bug or mejora or "ok",
                "fecha": datetime.now().isoformat(),
            }

    _guardar_cache(cache)
    return reporte


def imprimir_reporte_natural(reporte, sin_ia=False):
    """
    Como imprimir_reporte(), pero hablado -- sin rutas crudas, sin
    'archivo.py::funcion', sin símbolos técnicos. Es lo que usa Arché
    cuando te está hablando en el chat (main.py, comando 'revisate').
    imprimir_reporte() (la versión técnica, con rutas exactas) sigue
    disponible para cuando corrés el script vos mismo en la terminal
    y querés precisión quirúrgica en vez de conversación.
    """
    from core.IA.narrador import area_natural, nombre_funcion_hablado

    algo_para_contar = False

    if reporte["duplicados"]:
        algo_para_contar = True
        n = len(reporte["duplicados"])
        print(f"\nArché: Encontré {n} par(es) de funciones que hacen básicamente lo mismo:")
        for d in reporte["duplicados"]:
            area_a = area_natural(d["archivo_a"])
            area_b = area_natural(d["archivo_b"])
            fn = nombre_funcion_hablado(d["funcion_a"])
            if d["archivo_a"] == d["archivo_b"]:
                print(f"  • En {area_a} hay más de una versión de '{fn}' -- probablemente una pisó a la otra sin querer.")
            else:
                print(f"  • '{fn}' está repetida entre {area_a} y {area_b}.")

    if reporte["imports_sin_usar"]:
        algo_para_contar = True
        n = len(reporte["imports_sin_usar"])
        print(f"\nArché: Hay {n} import(s) que no se usan para nada:")
        for i in reporte["imports_sin_usar"]:
            print(f"  • En {area_natural(i['archivo'])}, el import de '{i['import']}' no lo usa nadie.")

    if reporte["codigo_muerto"]["alta_confianza"]:
        algo_para_contar = True
        n = len(reporte["codigo_muerto"]["alta_confianza"])
        if reporte["codigo_muerto"].get("se_propusieron_eliminaciones"):
            print(f"\nArché: Encontré {n} función(es) que no usa nadie más en el proyecto, y ya dejé propuesta(s) para borrarlas:")
        else:
            print(f"\nArché: Encontré {n} función(es) que no parece usar nadie más en el proyecto (todavía no propuse borrarlas):")
        for f in reporte["codigo_muerto"]["alta_confianza"]:
            print(f"  • '{nombre_funcion_hablado(f['nombre'])}' en {area_natural(f['archivo'])}.")

    if reporte["codigo_muerto"]["revisar_con_cuidado"]:
        algo_para_contar = True
        n = len(reporte["codigo_muerto"]["revisar_con_cuidado"])
        print(f"\nArché: Hay {n} función(es) que parecen sin uso, pero no me animo a tocarlas porque se llaman de forma indirecta -- las dejo para que las mires vos:")
        for f in reporte["codigo_muerto"]["revisar_con_cuidado"]:
            print(f"  • '{nombre_funcion_hablado(f['nombre'])}' en {area_natural(f['archivo'])} ({f['motivo']}).")

    if reporte["except_desnudos"]:
        algo_para_contar = True
        n = len(reporte["except_desnudos"])
        print(f"\nArché: Encontré {n} lugar(es) donde atrapo cualquier error sin decir cuál -- eso puede estar tapando bugs sin que nadie se entere:")
        for e in reporte["except_desnudos"]:
            print(f"  • En {area_natural(e['archivo'])} (línea {e['linea']}).")

    if not sin_ia:
        ia = reporte["revision_ia"]
        if ia["bugs_encontrados"]:
            algo_para_contar = True
            n = len(ia["bugs_encontrados"])
            print(f"\nArché: Ollama me señaló {n} posible(s) bug(s) al revisar funciones nuevas o modificadas:")
            for h in ia["bugs_encontrados"]:
                print(f"  • En {area_natural(h['archivo'])}, '{nombre_funcion_hablado(h['funcion'])}': {h['bug']}")

        if ia["mejoras_encontradas"]:
            algo_para_contar = True
            n = len(ia["mejoras_encontradas"])
            print(f"\nArché: También vi {n} mejora(s) de calidad posibles (nada urgente):")
            for m in ia["mejoras_encontradas"]:
                print(f"  • En {area_natural(m['archivo'])}, '{nombre_funcion_hablado(m['funcion'])}': {m['mejora']}")

    if reporte["revision_ia"]["propuestas_generadas"]:
        n = len(reporte["revision_ia"]["propuestas_generadas"])
        print(f"\nArché: En total dejé {n} propuesta(s) listas para que las revises. Decime 'cambios de código pendientes' o corré el revisor cuando quieras.")

    if not algo_para_contar:
        print("\nArché: Me revisé entero y no encontré nada para reportarte esta vez -- todo parece estar en orden.")


def imprimir_reporte(reporte, sin_ia=False):
    """
    Imprime el reporte de autorevisar() en formato legible. Separada
    de autorevisar() para que main.py (u otro llamador) pueda pedir
    el reporte y mostrarlo sin depender de que se ejecute como script.
    """
    print("\n" + "=" * 60)
    print("REPORTE DE AUTOREVISIÓN")
    print("=" * 60)

    if reporte["duplicados"]:
        print(f"\nFunciones posiblemente duplicadas ({len(reporte['duplicados'])}):")
        for d in reporte["duplicados"]:
            print(f"  • {d['archivo_a']}::{d['funcion_a']}  ≈  {d['archivo_b']}::{d['funcion_b']}")

    if reporte["imports_sin_usar"]:
        print(f"\nImports sin usar ({len(reporte['imports_sin_usar'])}):")
        for i in reporte["imports_sin_usar"]:
            print(f"  • {i['archivo']}: {i['import']}")

    if reporte["codigo_muerto"]["alta_confianza"]:
        print(f"\nFunciones sin referencias reales, candidatas a eliminar ({len(reporte['codigo_muerto']['alta_confianza'])}):")
        etiqueta = ("-> propuesta de eliminación generada, revisá con 'python core/IA/revisar_cambios_codigo.py'"
                    if reporte["codigo_muerto"].get("se_propusieron_eliminaciones")
                    else "-> solo reportada, no se generó propuesta (proponer_borrado_codigo_muerto=False)")
        for f in reporte["codigo_muerto"]["alta_confianza"]:
            print(f"  • {f['archivo']}::{f['nombre']}  {etiqueta}")

    if reporte["codigo_muerto"]["revisar_con_cuidado"]:
        print(f"\nFunciones que parecen sin uso pero son de despacho dinámico -- NO se proponen para borrar ({len(reporte['codigo_muerto']['revisar_con_cuidado'])}):")
        for f in reporte["codigo_muerto"]["revisar_con_cuidado"]:
            print(f"  • {f['archivo']}::{f['nombre']} ({f['motivo']})")

    if reporte["except_desnudos"]:
        print(f"\n'except:' desnudos ({len(reporte['except_desnudos'])}):")
        for e in reporte["except_desnudos"]:
            print(f"  • {e['archivo']}:{e['linea']}")

    if not sin_ia:
        ia = reporte["revision_ia"]
        print(f"\nRevisión con Ollama: {ia['nuevas_o_modificadas']} función(es) nueva(s)/modificada(s) revisada(s), "
              f"{ia['saltadas_por_cache']} salteada(s) por caché (ya revisadas, sin cambios).")
        if ia["bugs_encontrados"]:
            print(f"\nPosibles bugs encontrados ({len(ia['bugs_encontrados'])}):")
            for h in ia["bugs_encontrados"]:
                print(f"  • {h['archivo']}::{h['funcion']}: {h['bug']}")

        if ia["mejoras_encontradas"]:
            print(f"\nMejoras de calidad detectadas ({len(ia['mejoras_encontradas'])}):")
            for m in ia["mejoras_encontradas"]:
                print(f"  • {m['archivo']}::{m['funcion']}: {m['mejora']}")

    if reporte["revision_ia"]["propuestas_generadas"]:
        print(f"\nEn total se generaron {len(reporte['revision_ia']['propuestas_generadas'])} propuesta(s) "
              f"(código muerto a eliminar + correcciones de bugs).")
        print("Corré 'python core/IA/revisar_cambios_codigo.py' para revisarlas y aprobarlas.")

    hay_hallazgos_deterministas = any([
        reporte["duplicados"], reporte["imports_sin_usar"],
        reporte["codigo_muerto"]["alta_confianza"], reporte["codigo_muerto"]["revisar_con_cuidado"],
        reporte["except_desnudos"],
    ])
    hay_hallazgos_ia = not sin_ia and reporte["revision_ia"]["bugs_encontrados"]

    if not hay_hallazgos_deterministas and not hay_hallazgos_ia:
        print("\nNo encontré nada para reportar esta vez.")


INTERVALO_AUTOREVISION_SEG = 6 * 60 * 60  # cada cuánto se repite sola, mientras Arché sigue abierta


def _contar_hallazgos(reporte, sin_ia=False):
    """Cuántos hallazgos hay en total en un reporte de autorevisar(), sin importar la categoría."""
    total = (
        len(reporte["duplicados"])
        + len(reporte["imports_sin_usar"])
        + len(reporte["codigo_muerto"]["alta_confianza"])
        + len(reporte["codigo_muerto"]["revisar_con_cuidado"])
        + len(reporte["except_desnudos"])
    )
    if not sin_ia:
        total += len(reporte["revision_ia"]["bugs_encontrados"]) + len(reporte["revision_ia"]["mejoras_encontradas"])
    return total


def iniciar_autorevision_en_background(
    retraso_inicial_seg=15,
    intervalo_seg=INTERVALO_AUTOREVISION_SEG,
    usar_ollama=False,
    detener_evento=None,
    avisar=None,
):
    """
    Corre autorevisar() sola, en un hilo aparte, cada intervalo_seg
    mientras Arché esté abierta -- sin que se lo pidas cada vez. Mismo
    patrón que iniciar_estudio_en_background() en estudio.py.

    SOLO detecta y reporta; nunca propone eliminar código muerto ni
    aplica nada (eso sigue pidiendo tu aprobación explícita como
    siempre -- esto no toca esa regla). Si el número de hallazgos NO
    cambió respecto de la última corrida, se queda callada en vez de
    repetirte lo mismo cada rato; si cambió, llama a avisar(mensaje)
    para contarte que apareció algo nuevo.

    usar_ollama=False por defecto: la pasada automática es la
    determinista (instantánea, no depende de esperar a Ollama de
    fondo). La pasada completa con Ollama la seguís pidiendo vos con
    "revisate" cuando quieras.

    detener_evento: threading.Event opcional para cortarla desde
    afuera (ej. un comando "detener autorevision automatica").
    avisar: función que recibe un string (típicamente `hablar` de
    core/configuracion.py). Si no se pasa, no avisa nada por su
    cuenta -- igual queda todo en el log/reporte para quien lo pida.
    """
    def _tarea():
        ultimo_total = None
        time.sleep(retraso_inicial_seg)
        while detener_evento is None or not detener_evento.is_set():
            try:
                reporte = autorevisar(usar_ollama=usar_ollama, proponer_borrado_codigo_muerto=False)
                total = _contar_hallazgos(reporte, sin_ia=not usar_ollama)
                if total > 0 and total != ultimo_total and avisar is not None:
                    avisar(
                        f"Mientras andaba en segundo plano me autorevisé y encontré {total} "
                        f"cosa(s) para mejorar en el código. Decime 'revisate' cuando quieras el detalle."
                    )
                ultimo_total = total
            except Exception:
                # Un error acá no debe tirar abajo el hilo de fondo.
                pass

            # Espera interrumpible: revisa cada segundo si nos pidieron
            # parar, en vez de dormir el intervalo entero de una vez.
            for _ in range(intervalo_seg):
                if detener_evento is not None and detener_evento.is_set():
                    break
                time.sleep(1)

    hilo = threading.Thread(target=_tarea, daemon=True)
    hilo.start()
    return hilo


if __name__ == "__main__":
    import sys

    sin_ia = "--sin-ia" in sys.argv
    tecnico = "--tecnico" in sys.argv
    limite = None
    if "--limite" in sys.argv:
        idx = sys.argv.index("--limite")
        limite = int(sys.argv[idx + 1])

    print("Ejecutando autorevisión de Arché (todo el proyecto)...")
    if not sin_ia:
        print("Los chequeos deterministas son inmediatos; la revisión con Ollama")
        print("solo se hace sobre funciones nuevas o modificadas desde la última vez.\n")

    reporte = autorevisar(usar_ollama=not sin_ia, limite_nuevas=limite)
    if tecnico:
        imprimir_reporte(reporte, sin_ia=sin_ia)
    else:
        imprimir_reporte_natural(reporte, sin_ia=sin_ia)