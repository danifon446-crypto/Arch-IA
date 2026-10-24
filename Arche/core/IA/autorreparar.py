"""
autorreparar.py
---------------
Ubicacion: Arche/core/IA/autorreparar.py

Arché se arregla sola a partir de los errores REALES que tuvo mientras la
usabas (los anota registro_errores.py).

Para cada error pendiente:
  1. Busca la funcion donde ocurrio y arma un pedido con el error, el
     traceback, las variables de ese momento y el codigo.
  2. Le pide al modelo de codigo (la nube si activaste 'usa la nube para
     programar'; si no, Ollama) DOS cosas: el parche (BUSCAR/REEMPLAZAR) y
     una PRUEBA que reproduce el error.
  3. Comprueba en una copia aislada del proyecto que:
       - con el codigo ACTUAL la prueba FALLA con el mismo tipo de error
         (o sea, la prueba de verdad reproduce el problema), y
       - con el PARCHE la prueba PASA.
     Si algo de eso no se cumple, le explica al modelo que fallo y reintenta.
  4. Si el parche esta demostrado, lo aplica por el camino de siempre
     (mejora_continua.aplicar_lote_seguro: sintaxis, entorno aislado, respaldo,
     autotest completo antes y despues, y deshace si aparece una falla nueva).
  5. Guarda la prueba en core/IA/pruebas_aprendidas/ (el autotest la corre
     siempre desde entonces, asi ese error no puede volver sin que se note),
     y hace commit en git del arreglo y de la prueba.

Limites: MAX_REPARACIONES_CICLO por ciclo, MAX_REPARACIONES_DIA por dia,
MAX_INTENTOS_POR_ERROR intentos por error. Nunca toca archivos protegidos
(ni main.py, ni el autotest, ni el propio motor de cambios). Un parche de
riesgo "alto" (ver gran_sabio.evaluar_riesgo) no se aplica solo.

Comandos:
  errores registrados / que errores has tenido     -> lista de errores reales y su estado
  reparate / reparate ahora / arregla tus errores  -> intenta reparar ya los pendientes
  reintenta el error <firma>                        -> vuelve a poner un error en pendiente
  olvida el error <firma>                           -> lo saca de la lista de pendientes
  verifica tu autonomia / prueba tu autorreparacion -> se comprueba de punta a punta (core/IA/autoverificacion.py)
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from core.IA import registro_errores

RAIZ_APP = Path(__file__).resolve().parents[2]          # Arche/
CARPETA_PRUEBAS = RAIZ_APP / "core" / "IA" / "pruebas_aprendidas"

MAX_INTENTOS_POR_ERROR = 3        # intentos (cada uno con hasta MAX_RONDAS_MODELO pedidos al modelo)
MAX_RONDAS_MODELO = 2
MAX_REPARACIONES_CICLO = 2
MAX_REPARACIONES_DIA = 6
RIESGO_MAXIMO_REPARACION = 50     # medio se acepta (hay prueba que lo demuestra); alto, no
TIMEOUT_PRUEBA = 40
MAX_LINEAS_FRAGMENTO = 120
TOKENS_RESPUESTA = 1800

MARCA_PRUEBA_INICIO = "<<<<<<< PRUEBA"
MARCA_PRUEBA_FIN = ">>>>>>> FIN"
PATRON_PRUEBA = re.compile(r"<{3,}\s*PRUEBA\s*\n(.*?)\n\s*>{3,}\s*FIN", re.DOTALL)
PATRON_FENCE = re.compile(r"^```[a-zA-Z]*\s*$", re.MULTILINE)

# Lo que una prueba generada NO puede usar: corre en tu PC y no debe tocar nada real.
_PROHIBIDO_EN_PRUEBA = [
    (re.compile(r"\bimport\s+(subprocess|socket|requests|urllib|webbrowser|pyautogui|keyboard|mouse|ctypes|winreg|ollama)\b"), "importa un módulo que toca el sistema o la red"),
    (re.compile(r"\bfrom\s+(subprocess|socket|requests|urllib|webbrowser|pyautogui|keyboard|mouse|ctypes|winreg|ollama)\b"), "importa un módulo que toca el sistema o la red"),
    (re.compile(r"\bos\.(system|startfile|popen|exec\w*|spawn\w*|kill)\b"), "ejecuta programas"),
    (re.compile(r"\bshutil\.rmtree\b"), "borra carpetas"),
    (re.compile(r"\b(eval|exec|__import__)\s*\("), "ejecuta código dinámico"),
    (re.compile(r"\b[A-Za-z]:\\{1,2}[A-Za-z]|/home/|/Users/|USERPROFILE|expanduser"), "usa rutas reales de tu PC"),
]

# Corre la prueba dentro del entorno aislado. Se pasa con -c.
_RUNNER = (
    "import sys, os, builtins, runpy\n"
    "sys.path.insert(0, os.getcwd())\n"
    "os.environ['ARCHE_SANDBOX'] = '1'\n"
    "def _sin_input(*a, **k):\n"
    "    raise EOFError('input() no está disponible en las pruebas')\n"
    "builtins.input = _sin_input\n"
    "ns = runpy.run_path(sys.argv[1], run_name='prueba_arche')\n"
    "ns['prueba']()\n"
    "print('PRUEBA_OK')\n"
)


def _msg(texto):
    print(f"Arché: {texto}")


# ------------------------------------------------------------------
# Piezas que se pueden simular en las pruebas
# ------------------------------------------------------------------

def _generar(prompt):
    """Texto del modelo de codigo. Usa la nube si 'codigo' esta activo en nube_tareas; si no, Ollama."""
    from core.IA import ollamaIA
    try:
        return ollamaIA.generar_codigo(prompt, num_predict=TOKENS_RESPUESTA, temperature=0.1) or ""
    except Exception:
        return ""


def _entorno_aislado():
    from core.IA.revisar_cambios_codigo import _copiar_codigo_a_entorno_aislado
    return _copiar_codigo_a_entorno_aislado()


def _aplicar_con_barandas(propuesta):
    """(aplicadas, deshechas) del camino seguro de la mejora continua (sin commit: lo hacemos aqui)."""
    from core import mejora_continua
    return mejora_continua.aplicar_lote_seguro([propuesta], hacer_commit=False)


def _anexar_prueba_al_ultimo_lote(rel_prueba):
    from core import mejora_continua
    mejora_continua.anexar_al_ultimo_lote(pruebas=[rel_prueba])


def _commit(archivos, mensaje):
    from core.IA import git_arche
    return git_arche.commit(archivos, mensaje)


def _riesgo(propuesta):
    from core.IA import gran_sabio
    return gran_sabio.evaluar_riesgo(propuesta)


def _es_protegido(rel):
    from core.IA.proponer_cambio_codigo import es_protegido
    return es_protegido(rel, automatico=True)


# ------------------------------------------------------------------
# Contexto del error
# ------------------------------------------------------------------

def _modulo_de(rel):
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel


def _fragmento(contenido, linea):
    """(texto, desde, hasta, clase): la funcion mas interna que contiene `linea`, o una ventana alrededor."""
    lineas = contenido.splitlines()
    desde, hasta, clase = max(1, linea - 30), min(len(lineas), linea + 30), None
    try:
        arbol = ast.parse(contenido)
        mejor = None
        pila = [(arbol, None)]
        while pila:
            nodo, clase_actual = pila.pop()
            for hijo in ast.iter_child_nodes(nodo):
                if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fin = getattr(hijo, "end_lineno", hijo.lineno)
                    inicio = min([hijo.lineno] + [d.lineno for d in hijo.decorator_list])
                    if inicio <= linea <= fin and (mejor is None or inicio >= mejor[0]):
                        mejor = (inicio, fin, clase_actual)
                    pila.append((hijo, clase_actual))
                elif isinstance(hijo, ast.ClassDef):
                    pila.append((hijo, hijo.name))
                else:
                    pila.append((hijo, clase_actual))
        if mejor:
            desde, hasta, clase = mejor
    except SyntaxError:
        pass
    if hasta - desde + 1 > MAX_LINEAS_FRAGMENTO:
        mitad = MAX_LINEAS_FRAGMENTO // 2
        desde, hasta = max(desde, linea - mitad), min(hasta, linea + mitad)
    return "\n".join(lineas[desde - 1:hasta]), desde, hasta, clase


def armar_prompt(err, contenido, intento_anterior=None):
    fragmento, desde, hasta, clase = _fragmento(contenido, int(err.get("linea") or 1))
    locales = "\n".join(f"  {k} = {v}" for k, v in (err.get("locales") or {}).items()) or "  (no disponibles)"
    donde = f"método {clase}.{err['funcion']}" if clase else f"función {err['funcion']}"
    partes = [
        "Eres el sistema de autorreparación de Arché, un asistente personal escrito en Python. "
        "Hubo un error REAL mientras el usuario la usaba. Tu trabajo: (1) corregir la CAUSA con el cambio "
        "más pequeño posible y (2) escribir una prueba que reproduzca el error.",
        "",
        f"ERROR: {err['tipo']}: {err.get('mensaje', '')}",
        f"Ocurrió en {err['archivo']}, {donde}, línea {err['linea']}: {err.get('codigo_linea', '')}",
        f"Frase del usuario en ese momento: {err.get('frase') or '(ninguna)'}",
        "Variables locales en ese punto:",
        locales,
        "",
        "Final del traceback:",
        (err.get("traceback") or "")[-1500:],
        "",
        f"CÓDIGO ACTUAL de {err['archivo']} (líneas {desde} a {hasta}). El módulo se importa como "
        f"`{_modulo_de(err['archivo'])}`:",
        "```python",
        fragmento,
        "```",
        "",
        "Responde EXACTAMENTE con estos dos bloques y nada más:",
        "",
        "<<<<<<< BUSCAR",
        "(fragmento copiado EXACTO, carácter por carácter y con la misma sangría, del código de arriba; "
        "incluye varias líneas para que sea único en el archivo)",
        "=======",
        "(ese mismo fragmento ya corregido)",
        ">>>>>>> REEMPLAZAR",
        "",
        MARCA_PRUEBA_INICIO,
        f"from {_modulo_de(err['archivo'])} import ...",
        "",
        "def prueba():",
        "    # llama al código con datos que provocan el error original",
        "    # y comprueba con assert el comportamiento correcto",
        "    ...",
        MARCA_PRUEBA_FIN,
        "",
        "Reglas:",
        "- Corrige la causa. NO escondas el error con un try/except que lo ignore en silencio.",
        "- No cambies el nombre ni los parámetros de la función, ni lo que devuelve en los casos que ya funcionaban.",
        "- La prueba se corre en una COPIA AISLADA del proyecto: la carpeta Database está vacía, no hay internet, "
        "no hay Ollama y input() no está disponible. Si el código necesita archivos o datos, créalos dentro de la "
        "prueba con tempfile, o reemplaza temporalmente (monkeypatch) la función que los lee.",
        "- La prueba NO puede usar subprocess, red, os.system, borrar carpetas ni rutas reales del PC.",
        "- Con el código ACTUAL la prueba debe FALLAR lanzando el mismo error "
        f"({err['tipo']}); con tu corrección debe PASAR sin errores.",
        "- La función de la prueba se llama exactamente `prueba` y no recibe argumentos.",
    ]
    if intento_anterior:
        partes += [
            "",
            "TU INTENTO ANTERIOR NO SIRVIÓ:",
            intento_anterior["motivo"],
            "Lo que respondiste fue:",
            intento_anterior["respuesta"][-2500:],
            "Corrige eso y vuelve a responder con los dos bloques completos.",
        ]
    return "\n".join(partes)


# ------------------------------------------------------------------
# Respuesta del modelo
# ------------------------------------------------------------------

def _limpiar_fences(texto):
    return PATRON_FENCE.sub("", texto).strip("\n")


def extraer_respuesta(texto):
    """(buscar, reemplazar, prueba) o lanza ValueError con el motivo."""
    from core.IA.proponer_cambio_codigo import PATRON_BLOQUE
    texto = texto or ""
    m = PATRON_BLOQUE.search(texto)
    if not m:
        raise ValueError("No encontré el bloque <<<<<<< BUSCAR / ======= / >>>>>>> REEMPLAZAR.")
    buscar, reemplazar = _limpiar_fences(m.group(1)), _limpiar_fences(m.group(2))
    p = PATRON_PRUEBA.search(texto)
    if not p:
        raise ValueError("No encontré el bloque <<<<<<< PRUEBA / >>>>>>> FIN con la prueba.")
    prueba = _limpiar_fences(p.group(1)).strip() + "\n"
    if not buscar.strip():
        raise ValueError("El bloque BUSCAR está vacío.")
    if buscar == reemplazar:
        raise ValueError("BUSCAR y REEMPLAZAR son idénticos: no corregiste nada.")
    return buscar, reemplazar, prueba


def _ajustar_buscar(contenido, buscar, reemplazar):
    """Si el modelo cambio solo los espacios al final de las lineas, lo acomoda. Devuelve (buscar, reemplazar)."""
    if contenido.count(buscar) == 1:
        return buscar, reemplazar
    sin_cola = "\n".join(l.rstrip() for l in buscar.split("\n"))
    lineas = contenido.split("\n")
    n = len(sin_cola.split("\n"))
    for i in range(len(lineas) - n + 1):
        ventana = lineas[i:i + n]
        if "\n".join(l.rstrip() for l in ventana) == sin_cola:
            original = "\n".join(ventana)
            if contenido.count(original) == 1:
                return original, reemplazar
    return buscar, reemplazar


def revisar_prueba(codigo):
    """None si la prueba es aceptable, o el motivo por el que no."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError as e:
        return f"La prueba no es Python válido: {e}"
    if not any(isinstance(n, ast.FunctionDef) and n.name == "prueba" and not n.args.args
               for n in arbol.body):
        return "La prueba no define `def prueba():` (sin argumentos) a nivel de módulo."
    for patron, motivo in _PROHIBIDO_EN_PRUEBA:
        if patron.search(codigo):
            return f"La prueba no está permitida: {motivo}."
    return None


# ------------------------------------------------------------------
# Correr una prueba en una copia aislada
# ------------------------------------------------------------------

def correr_prueba(codigo_prueba, archivo=None, contenido=None, entorno=None):
    """
    Corre `prueba()` en una copia aislada del proyecto (opcionalmente con
    `archivo` reemplazado por `contenido`). Devuelve (paso: bool, salida: str).
    """
    propio = entorno is None
    entorno = Path(entorno) if entorno is not None else _entorno_aislado()
    try:
        if archivo is not None and contenido is not None:
            destino = entorno / archivo
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido, encoding="utf-8")
        ruta_prueba = entorno / "_prueba_reparacion_arche.py"
        ruta_prueba.write_text(codigo_prueba, encoding="utf-8")
        env = dict(os.environ, ARCHE_SANDBOX="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        try:
            r = subprocess.run([sys.executable, "-c", _RUNNER, str(ruta_prueba)], cwd=str(entorno),
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               stdin=subprocess.DEVNULL, timeout=TIMEOUT_PRUEBA, env=env)
        except subprocess.TimeoutExpired:
            return False, f"La prueba tardó más de {TIMEOUT_PRUEBA}s (¿bucle infinito o espera algo?)."
        salida = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return (r.returncode == 0 and "PRUEBA_OK" in (r.stdout or "")), salida[-2500:]
    finally:
        if propio:
            shutil.rmtree(entorno, ignore_errors=True)


def _fallo_con_el_mismo_error(salida, tipo):
    return re.search(r"\b" + re.escape(tipo) + r"\b", salida or "") is not None


# ------------------------------------------------------------------
# Reparar un error
# ------------------------------------------------------------------

def _guardar_prueba(err, codigo_prueba):
    CARPETA_PRUEBAS.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_PRUEBAS / f"prueba_{err['firma']}.py"
    cabecera = (
        f'"""\nPrueba aprendida por la autorreparación de Arché ({datetime.now():%Y-%m-%d %H:%M}).\n'
        f"Reproduce: {err['tipo']}: {str(err.get('mensaje', ''))[:150]}\n"
        f"En: {err['archivo']} -> {err['funcion']} (línea {err['linea']})\n"
        f"Si esta prueba falla, ese error volvió. No la borres sin revisar.\n"
        f'"""\n'
    )
    ruta.write_text(cabecera + codigo_prueba, encoding="utf-8")
    return ruta.relative_to(RAIZ_APP).as_posix()


def _intentar_una_vez(err, contenido):
    """
    Pide parche + prueba al modelo (con reintento guiado) y los demuestra en un
    entorno aislado. Devuelve (buscar, reemplazar, prueba) o (None, motivo).
    """
    anterior = None
    for _ in range(MAX_RONDAS_MODELO):
        respuesta = _generar(armar_prompt(err, contenido, anterior))
        if not respuesta.strip():
            return None, "el modelo de código no respondió (¿nube u Ollama apagados?)"
        try:
            buscar, reemplazar, prueba = extraer_respuesta(respuesta)
            buscar, reemplazar = _ajustar_buscar(contenido, buscar, reemplazar)
            n = contenido.count(buscar)
            if n != 1:
                raise ValueError("El fragmento BUSCAR " + ("no existe exacto en el archivo." if n == 0
                                 else f"aparece {n} veces; tiene que ser único (agrega más líneas)."))
            nuevo = contenido.replace(buscar, reemplazar, 1)
            try:
                ast.parse(nuevo)
            except SyntaxError as e:
                raise ValueError(f"Con tu parche el archivo deja de ser Python válido: {e}")
            motivo = revisar_prueba(prueba)
            if motivo:
                raise ValueError(motivo)

            entorno = _entorno_aislado()
            try:
                paso_antes, salida_antes = correr_prueba(prueba, entorno=entorno)
                if paso_antes:
                    raise ValueError("Con el código ACTUAL tu prueba PASA, así que no reproduce el error. "
                                     "Tiene que fallar con " + err["tipo"] + ".")
                if not _fallo_con_el_mismo_error(salida_antes, err["tipo"]):
                    raise ValueError(f"Con el código actual tu prueba falla, pero por OTRA razón (no por {err['tipo']}). "
                                     f"Salida:\n{salida_antes[-1200:]}")
                paso_despues, salida_despues = correr_prueba(prueba, archivo=err["archivo"], contenido=nuevo,
                                                             entorno=entorno)
                if not paso_despues:
                    raise ValueError(f"Con tu parche la prueba sigue fallando. Salida:\n{salida_despues[-1200:]}")
            finally:
                shutil.rmtree(entorno, ignore_errors=True)
            return (buscar, reemplazar, prueba), None
        except ValueError as e:
            anterior = {"motivo": str(e), "respuesta": respuesta}
    return None, anterior["motivo"] if anterior else "sin respuesta útil"


def _recargar(rel):
    """Recarga en memoria el modulo arreglado, para que el arreglo valga sin reiniciar Arché.
    Devuelve True si se recargo. (Lo que main.py importo con 'from x import *' al arrancar
    sigue con la version vieja hasta que reinicies.)"""
    import importlib
    nombre = _modulo_de(rel)
    modulo = sys.modules.get(nombre)
    if modulo is None:
        return False
    try:
        importlib.reload(modulo)
        return True
    except Exception:
        return False


def _resumir(motivo, largo=180):
    """Primera linea del motivo, recortada (el detalle completo solo lo ve el modelo)."""
    lineas = [l.strip() for l in str(motivo or "").strip().split("\n") if l.strip()]
    if not lineas:
        return "sin detalle"
    texto = lineas[0].replace(" Salida:", "").rstrip(":. ")
    if len(lineas) > 1:
        texto += f" → {lineas[-1]}"                # la ultima linea del traceback dice el error
    return texto[:largo] + ("…" if len(texto) > largo else "")


def reparar(err):
    """
    Intenta reparar un error registrado. Devuelve (estado, texto) donde estado es
    'resuelto', 'reintentar', 'no_pude', 'necesita_humano' u 'obsoleto'.
    """
    firma, rel = err["firma"], err["archivo"]

    if _es_protegido(rel):
        registro_errores.marcar(firma, "necesita_humano", "está en un archivo protegido: no lo toco sola")
        return "necesita_humano", f"el error de {rel} está en un archivo protegido; te lo dejo a ti"

    ruta = RAIZ_APP / rel
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except OSError:
        registro_errores.marcar(firma, "obsoleto", "el archivo ya no existe")
        return "obsoleto", f"{rel} ya no existe"

    if err.get("codigo_linea") and err["codigo_linea"] not in contenido:
        registro_errores.marcar(firma, "obsoleto", "la línea que fallaba ya no está (¿lo cambiaste a mano?)")
        return "obsoleto", f"la línea que fallaba en {rel} ya cambió"

    resultado, motivo = _intentar_una_vez(err, contenido)

    if resultado is not None:
        buscar, reemplazar, prueba = resultado
        from core.IA.proponer_cambio_codigo import proponer_cambio_manual
        que = f"Reparar {err['tipo']} en {rel} ({err['funcion']})"
        propuesta, error_prop = proponer_cambio_manual(rel, buscar, reemplazar, que=que, origen="autorreparacion")
        if propuesta is None:
            motivo = f"no se pudo crear la propuesta: {error_prop}"
        else:
            puntaje, motivos_riesgo = _riesgo(propuesta)
            if puntaje >= RIESGO_MAXIMO_REPARACION:
                registro_errores.marcar(firma, "necesita_humano",
                                        f"tengo un arreglo probado ({propuesta['id']}) pero es de riesgo alto "
                                        f"({puntaje}/100: {'; '.join(motivos_riesgo)}). Revísalo con 'revisar cambios'.")
                return "necesita_humano", (f"armé un arreglo probado para {err['tipo']} en {rel}, pero es de riesgo "
                                           f"alto; quedó como propuesta {propuesta['id']} para que la apruebes tú")
            aplicadas, deshechas = _aplicar_con_barandas(propuesta)
            if aplicadas:
                rel_prueba = _guardar_prueba(err, prueba)
                try:
                    _anexar_prueba_al_ultimo_lote(rel_prueba)
                except Exception:
                    pass
                ok_git, git_txt = _commit([rel, rel_prueba],
                                          f"Arché (autorreparación): {que}\n\n"
                                          f"Error: {err['tipo']}: {str(err.get('mensaje', ''))[:200]}\n"
                                          f"Prueba que lo demuestra: {rel_prueba}")
                nota = f"reparado con la propuesta {propuesta['id']}; prueba en {rel_prueba}"
                if ok_git:
                    nota += f"; commit {git_txt}"
                registro_errores.marcar(firma, "resuelto", nota)
                recargado = _recargar(rel)
                return "resuelto", (f"arreglé {err['tipo']} en {rel} ({err['funcion']}) y lo demostré con una prueba "
                                    f"nueva" + (f" (commit {git_txt})" if ok_git else "")
                                    + (". Ya lo cargué en memoria" if recargado else "")
                                    + (". Si el error sigue apareciendo, reiníciame" if rel != "main.py" else ""))
            motivo = ("el arreglo pasaba su prueba pero rompía otras del autotest, así que lo deshice"
                      + (f": {deshechas[0]}" if deshechas else ""))

    corto = _resumir(motivo)
    intentos = registro_errores.sumar_intento(firma, corto)
    if intentos >= MAX_INTENTOS_POR_ERROR:
        registro_errores.marcar(firma, "no_pude", f"lo intenté {intentos} veces; último motivo: {corto}")
        return "no_pude", f"no pude arreglar {err['tipo']} en {rel} después de {intentos} intentos ({corto})"
    return "reintentar", f"intenté arreglar {err['tipo']} en {rel} y todavía no ({corto}); lo reintento después"


# ------------------------------------------------------------------
# Ciclo (lo llama la mejora continua) y cupo diario
# ------------------------------------------------------------------

def _cupo_hoy():
    from core import mejora_continua
    d = mejora_continua._cargar().get("reparaciones_dia") or {}
    hoy = datetime.now().strftime("%Y-%m-%d")
    return d.get("n", 0) if d.get("dia") == hoy else 0


def _sumar_cupo(n):
    from core import mejora_continua
    hoy = datetime.now().strftime("%Y-%m-%d")
    with mejora_continua._lock:
        d = mejora_continua._cargar()
        previo = d.get("reparaciones_dia") or {}
        base = previo.get("n", 0) if previo.get("dia") == hoy else 0
        d["reparaciones_dia"] = {"dia": hoy, "n": base + n}
        mejora_continua._guardar(d)


def ciclo_reparacion(maximo=MAX_REPARACIONES_CICLO, detener=None, ignorar_cupo=False):
    """Intenta reparar hasta `maximo` errores pendientes. Devuelve lista de (estado, texto)."""
    resultados = []
    for err in registro_errores.pendientes():
        if len(resultados) >= maximo or (detener is not None and detener.is_set()):
            break
        if not ignorar_cupo and _cupo_hoy() >= MAX_REPARACIONES_DIA:
            break
        try:
            estado, texto = reparar(err)
        except Exception as e:
            registro_errores.registrar(e, origen="autorreparacion")
            registro_errores.sumar_intento(err["firma"], f"la reparación misma falló: {type(e).__name__}: {e}")
            estado, texto = "reintentar", f"la reparación de {err['archivo']} falló ({type(e).__name__}: {e})"
        _sumar_cupo(1)
        resultados.append((estado, texto))
    return resultados


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

def _norm(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[¿?¡!,.;:]", " ", t).split())


_R_LISTA = re.compile(r"^(?:errores\s+registrados|que\s+errores\s+(?:has\s+tenido|tuviste|tienes)|"
                      r"tus\s+errores|muestra(?:me)?\s+tus\s+errores|estado\s+de\s+(?:la\s+)?(?:auto)?reparacion)$")
_R_REPARAR = re.compile(r"^(?:reparate(?:\s+ahora|\s+ya|\s+sola)?|arregla\s+tus\s+errores|autorreparate|"
                        r"autorepara(?:te)?|arreglate(?:\s+sola)?)$")
_R_REINTENTAR = re.compile(r"^reintenta\s+el\s+error\s+([0-9a-f]{6,10})$")
_R_OLVIDAR = re.compile(r"^olvida\s+el\s+error\s+([0-9a-f]{6,10})$")

_NOMBRE_ESTADO = {"pendiente": "pendiente", "resuelto": "resuelto", "no_pude": "no pude",
                  "necesita_humano": "para ti", "obsoleto": "ya cambió", "ignorado": "ignorado"}


def _veces(n):
    n = int(n or 1)
    return "1 vez" if n == 1 else f"{n} veces"


def _listar():
    errores = registro_errores.todos()
    if not errores:
        _msg("No tengo errores registrados. Cuando algo me falle mientras me usas, lo anoto y lo intento arreglar sola.")
        return
    _msg(f"Errores reales que tuve ({len(errores)}):")
    for e in sorted(errores, key=lambda x: -float(x.get("ultima", 0)))[:15]:
        cuando = datetime.fromtimestamp(e.get("ultima", 0)).strftime("%d/%m %H:%M")
        print(f"  • [{e['firma']}] {_NOMBRE_ESTADO.get(e.get('estado'), e.get('estado'))} — "
              f"{e['tipo']} en {e['archivo']}:{e['linea']} ({e['funcion']}), {_veces(e.get('veces', 1))}, {cuando}")
        if e.get("nota"):
            print(f"      {e['nota'][:200]}")
    print("       'reparate' intenta arreglar los pendientes ya; 'reintenta el error <firma>' o 'olvida el error <firma>'.")


def manejar(comando):
    t = _norm(comando)
    if not t:
        return None
    from core.IA import autoverificacion                 # "verifica tu autonomia": prueba de punta a punta
    r = autoverificacion.manejar(comando)
    if r is not None:
        return r
    if _R_LISTA.match(t):
        _listar()
        return ("errores_registrados", None)
    if _R_REPARAR.match(t):
        pend = registro_errores.pendientes()
        if not pend:
            _msg("No tengo errores pendientes de arreglar. ('errores registrados' para ver el historial)")
            return ("autorreparar", None)
        _msg(f"Voy a intentar arreglar {min(len(pend), MAX_REPARACIONES_CICLO)} error(es). "
             f"Para cada uno escribo el arreglo y una prueba, y los compruebo antes de tocar nada (puede tardar)...")
        for estado, texto in ciclo_reparacion(ignorar_cupo=True):
            print(f"  • {texto}")
        return ("autorreparar", None)
    m = _R_REINTENTAR.match(t)
    if m:
        e = registro_errores.actualizar(m.group(1), estado="pendiente", intentos=0, nota="lo pediste de nuevo")
        _msg("Listo, lo vuelvo a intentar en mi próximo ciclo (o dime 'reparate')." if e
             else "No encuentro un error con esa firma.")
        return ("reintentar_error", m.group(1))
    m = _R_OLVIDAR.match(t)
    if m:
        e = registro_errores.marcar(m.group(1), "ignorado", "me pediste que no lo intentara")
        _msg("Listo, no intento arreglar ese." if e else "No encuentro un error con esa firma.")
        return ("olvidar_error", m.group(1))
    return None
