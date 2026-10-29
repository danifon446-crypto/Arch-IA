"""
modelo_nuevo.py  (Fase 4, lado de tu PC)
----------------------------------------
Ubicacion: Arche/core/IA/modelo_nuevo.py

Cuando el entrenador de la nube (nube/entrenador/ciclo.py) publica un
arche-lora nuevo que aprobo su examen en Kaggle, este modulo:

  1. Lo DESCARGA de tu Hugging Face privado (Arche/modelos/, no se sube a GitHub).
  2. Lo crea en Ollama con OTRO nombre (arche-lora-vN): el tuyo no se toca.
  3. Repite el EXAMEN aqui, en tu PC, contra tu arche-lora ACTUAL, con
     frases que ninguno de los dos vio, y tal como Arché lo usaria de verdad.
  4. Solo si gana (y no empeora en ningun dominio) te AVISA. El cambio lo
     decides tu: "usa el modelo nuevo". Siempre se puede volver:
     "vuelve al modelo anterior".

Comandos:
  estado del entrenador
  entrena ya                       (pide un entrenamiento en el proximo ciclo de la nube)
  conecta hugging face             (pide tu token; se guarda cifrado)
  examina el modelo nuevo          (descarga y examina ya, sin esperar)
  usa el modelo nuevo | vuelve al modelo anterior | descarta el modelo nuevo
"""

import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict

from core.rutas import BASE as RAIZ_APP, DATABASE

ARCHIVO_ESTADO = os.path.join(DATABASE, "modelo_nuevo.json")
ARCHIVO_TOKEN = os.path.join(DATABASE, "hf_token.txt")
CARPETA_MODELOS = os.path.join(RAIZ_APP, "modelos")
MODELFILE_BASE = os.path.join(CARPETA_MODELOS, "Modelfile")
NOMBRE = "arche-lora"
NOMBRE_ANTERIOR = "arche-lora-anterior"

EXAMEN_FRASES = 60
EXAMEN_CHARLA = ["hola como estas", "explicame que es una variable", "dame un consejo para estudiar"]
TOLERANCIA_DOMINIO = 1           # un dominio puede tener como mucho 1 acierto menos que el actual
PRIMERA_ESPERA_SEG = 180
INTERVALO_HORAS = 6

_lock = threading.Lock()
_ocupado = threading.Lock()
_detener = threading.Event()
_hilo = None


class ErrorModelo(Exception):
    pass


# ------------------------------------------------------------------
# Estado local
# ------------------------------------------------------------------
def _leer_json(ruta, defecto):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def _escribir_json(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ruta)


def _estado():
    base = {"examinados": {}, "descartados": [], "aviso_pendiente": ""}
    base.update(_leer_json(ARCHIVO_ESTADO, {}))
    return base


def _guardar_estado(e):
    with _lock:
        _escribir_json(ARCHIVO_ESTADO, e)


def _token():
    env = os.environ.get("HF_TOKEN", "").strip()
    if env:
        return env
    try:
        from core.seguridad.cifrado import leer_secreto
        return leer_secreto(ARCHIVO_TOKEN)
    except Exception:
        return ""


# ------------------------------------------------------------------
# La nube: que candidato hay
# ------------------------------------------------------------------
def estado_nube():
    from core import memoria_nube
    filas = memoria_nube._pedir("GET", "arche_config", {"select": "valor", "clave": "eq.entrenador"}) or []
    return filas[0]["valor"] if filas and isinstance(filas[0].get("valor"), dict) else {}


def pedir_entrenamiento():
    from core import memoria_nube
    actual = estado_nube()
    actual["forzar"] = True
    memoria_nube._pedir("POST", "arche_config", {"on_conflict": "clave"}, [{"clave": "entrenador", "valor": actual}],
                        prefer="return=minimal,resolution=merge-duplicates")


# ------------------------------------------------------------------
# Descargar
# ------------------------------------------------------------------
def _descargar(repo, ruta_en_repo, destino, bytes_esperados=None):
    token = _token()
    if not token:
        raise ErrorModelo("falta tu token de Hugging Face (di 'conecta hugging face')")
    url = f"https://huggingface.co/{repo}/resolve/main/{ruta_en_repo}"
    pedido = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "Arche/1.0"})
    tmp = destino + ".parcial"
    try:
        with urllib.request.urlopen(pedido, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1024 * 1024)
    except urllib.error.HTTPError as e:
        raise ErrorModelo("Hugging Face no aceptó el token" if e.code in (401, 403)
                          else f"Hugging Face respondió {e.code} al bajar {ruta_en_repo}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorModelo(f"no pude descargar {ruta_en_repo} ({getattr(e, 'reason', e)})")
    if bytes_esperados and os.path.getsize(tmp) != int(bytes_esperados):
        os.remove(tmp)
        raise ErrorModelo(f"la descarga de {ruta_en_repo} quedó incompleta")
    os.replace(tmp, destino)
    return destino


# ------------------------------------------------------------------
# Ollama (por su linea de comandos: funciona con cualquier version)
# ------------------------------------------------------------------
def _ollama_exe():
    exe = shutil.which("ollama")
    if exe:
        return exe
    posible = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    if os.path.exists(posible):
        return posible
    raise ErrorModelo("no encontré el programa de Ollama")


def _ollama(*args):
    r = subprocess.run([_ollama_exe(), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ErrorModelo(f"ollama {args[0]} falló: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def _existe_en_ollama(nombre):
    try:
        lista = _ollama("list")
    except ErrorModelo:
        return False
    return any(l.split()[0].split(":")[0] == nombre for l in lista.splitlines()[1:] if l.strip())


def _crear_en_ollama(nombre, ruta_gguf):
    """Mismo SYSTEM y parametros que tu Modelfile; solo cambia el archivo del modelo."""
    try:
        with open(MODELFILE_BASE, "r", encoding="utf-8-sig") as f:
            base = f.read()
    except OSError:
        base = 'FROM x\nPARAMETER temperature 0.7\nPARAMETER num_predict 300\n'
    lineas = [l for l in base.splitlines() if not l.strip().upper().startswith("FROM ")]
    contenido = f"FROM {ruta_gguf}\n" + "\n".join(lineas) + "\n"
    ruta = os.path.join(CARPETA_MODELOS, f"Modelfile_{nombre}")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)
    _ollama("create", nombre, "-f", ruta)


# ------------------------------------------------------------------
# Examen local
# ------------------------------------------------------------------
def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").strip().lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _clasificar_corto(modelo, frase):
    from core.IA import formato_lora, ollamaIA
    r = ollamaIA.ollama.chat(model=modelo, messages=formato_lora.mensajes_clasificar(frase), format="json",
                             keep_alive="5m", options={"num_predict": 60, "temperature": 0.0})
    return formato_lora.parsear(r["message"]["content"])


def _clasificar_como_hoy(frase):
    """Exactamente como Arché usa HOY su arche-lora (formato corto si ya viene del entrenador)."""
    from core.IA import enrutador_natural, formato_lora
    if formato_lora.usa_formato_corto():
        return _clasificar_corto(NOMBRE, frase)
    return enrutador_natural._resolver_con_ollama(frase)


def _muestra(validacion, n, semilla):
    por_dominio = defaultdict(list)
    for e in validacion:
        por_dominio[e.get("dominio", "")].append(e)
    rng = random.Random(semilla)
    for lista in por_dominio.values():
        rng.shuffle(lista)
    elegidas, i = [], 0
    while len(elegidas) < n and any(i < len(l) for l in por_dominio.values()):
        for lista in por_dominio.values():
            if i < len(lista) and len(elegidas) < n:
                elegidas.append(lista[i])
        i += 1
    return elegidas


def examinar(nombre_nuevo, validacion, avisar=print):
    import contextlib
    import io
    muestra = _muestra(validacion, EXAMEN_FRASES, semilla=len(validacion))
    resultado = {"n": len(muestra), "actual": 0, "nuevo": 0, "seg_actual": 0.0, "seg_nuevo": 0.0,
                 "dominios": {}, "charla_ok": 0}
    dominios = defaultdict(lambda: [0, 0, 0])            # aciertos actual, aciertos nuevo, total
    for i, e in enumerate(muestra, 1):
        with contextlib.redirect_stdout(io.StringIO()):
            t = time.time()
            try:
                actual = _clasificar_como_hoy(e["frase"])
            except Exception:
                actual = None
            resultado["seg_actual"] += time.time() - t
            t = time.time()
            try:
                nuevo = _clasificar_corto(nombre_nuevo, e["frase"])
            except Exception:
                nuevo = None
            resultado["seg_nuevo"] += time.time() - t
        ok_a = bool(actual) and actual[0] == e["intencion"]
        ok_n = bool(nuevo) and nuevo[0] == e["intencion"]
        resultado["actual"] += ok_a
        resultado["nuevo"] += ok_n
        d = dominios[e.get("dominio", "")]
        d[0] += ok_a
        d[1] += ok_n
        d[2] += 1
        if i % 15 == 0:
            avisar(f"(examen del modelo nuevo: {i}/{len(muestra)})")
    from core.IA import ollamaIA
    for pregunta in EXAMEN_CHARLA:
        try:
            r = ollamaIA.ollama.chat(model=nombre_nuevo, messages=[{"role": "user", "content": pregunta}],
                                     options={"num_predict": 120})["message"]["content"]
        except Exception:
            r = ""
        from core.IA import formato_lora
        resultado["charla_ok"] += len(r.strip()) >= 8 and formato_lora.parsear(r) is None
    resultado["dominios"] = {k: v for k, v in sorted(dominios.items())}
    peores = [k for k, (a, n, _t) in dominios.items() if n < a - TOLERANCIA_DOMINIO]
    resultado["peores"] = peores
    resultado["gana"] = (resultado["nuevo"] > resultado["actual"] and not peores
                         and resultado["charla_ok"] >= len(EXAMEN_CHARLA) - 1)
    return resultado


def _texto_resultado(version, r):
    n = max(1, r["n"])
    velocidad = r["seg_actual"] / r["seg_nuevo"] if r["seg_nuevo"] > 0 else 0
    texto = (f"arche-lora v{version}: acertó {r['nuevo']}/{r['n']} ({r['nuevo'] / n:.0%}) frente a "
             f"{r['actual']}/{r['n']} ({r['actual'] / n:.0%}) de tu arche-lora actual")
    if velocidad >= 1.2:
        texto += f", y responde unas {velocidad:.1f} veces más rápido"
    texto += f"; charla {r['charla_ok']}/{len(EXAMEN_CHARLA)}."
    if r.get("peores"):
        texto += " Empeora en: " + ", ".join(r["peores"]) + "."
    return texto


# ------------------------------------------------------------------
# Revisar si hay candidato (lo usa el hilo y el comando)
# ------------------------------------------------------------------
def revisar_candidato(avisar=print, forzar=False):
    if not _ocupado.acquire(blocking=False):
        return "Ya estoy descargando o examinando un modelo; espera a que termine."
    try:
        candidato = (estado_nube() or {}).get("candidato") or {}
        version = candidato.get("version")
        if not version:
            return "Todavía no hay ningún modelo nuevo de la nube."
        from core.IA import formato_lora
        if int(formato_lora.modelo_activo().get("version") or 0) >= int(version):
            return f"Ya estás usando arche-lora v{formato_lora.modelo_activo().get('version')} (la última)."
        est = _estado()
        if str(version) in est["examinados"] and not forzar:
            r = est["examinados"][str(version)]
            return _texto_resultado(version, r) + (" Di 'usa el modelo nuevo' para cambiarlo." if r["gana"]
                                                   else " No te lo recomiendo.")
        if version in est["descartados"] and not forzar:
            return f"La v{version} la descartaste."
        os.makedirs(CARPETA_MODELOS, exist_ok=True)
        gguf = os.path.join(CARPETA_MODELOS, f"arche-lora-v{version}.gguf")
        if not os.path.exists(gguf):
            avisar(f"Descargando arche-lora v{version} ({int(candidato.get('bytes', 0)) / 1e9:.1f} GB)...")
            _descargar(candidato["repo"], candidato["archivo"], gguf, candidato.get("bytes"))
        val = _descargar(candidato["repo"], candidato["validacion"],
                         os.path.join(CARPETA_MODELOS, f"validacion-v{version}.jsonl"))
        with open(val, encoding="utf-8") as f:
            validacion = [json.loads(l) for l in f if l.strip()]
        nombre = f"arche-lora-v{version}"
        _crear_en_ollama(nombre, gguf)
        avisar(f"Examinando arche-lora v{version} contra tu arche-lora actual (puede tardar un rato)...")
        r = examinar(nombre, validacion, avisar)
        est = _estado()
        est["examinados"][str(version)] = r
        mensaje = _texto_resultado(version, r)
        if r["gana"]:
            mensaje += " Ganó el examen. Di 'usa el modelo nuevo' para cambiarlo (puedes volver cuando quieras)."
            est["aviso_pendiente"] = mensaje
        else:
            mensaje += " No ganó, así que sigo con el actual."
        _guardar_estado(est)
        return mensaje
    finally:
        _ocupado.release()


# ------------------------------------------------------------------
# Cambiar y volver
# ------------------------------------------------------------------
def usar_nuevo():
    from core.IA import formato_lora
    candidato = (estado_nube() or {}).get("candidato") or {}
    version = candidato.get("version")
    est = _estado()
    r = est["examinados"].get(str(version))
    if not version or r is None:
        return "No hay un modelo nuevo examinado todavía. Di 'examina el modelo nuevo'."
    if not r["gana"]:
        return "Ese modelo no ganó el examen; no lo cambio. (Si igual lo quieres, dímelo con 'usa el modelo nuevo igual'.)"
    return _cambiar(version, formato_lora)


def _cambiar(version, formato_lora):
    nombre = f"arche-lora-v{version}"
    if _existe_en_ollama(NOMBRE):
        _ollama("cp", NOMBRE, NOMBRE_ANTERIOR)
    _ollama("cp", nombre, NOMBRE)
    previo = formato_lora.modelo_activo()
    _escribir_json(formato_lora._archivo_modelo_activo(),
                   {"version": int(version), "formato": "corto", "desde": time.strftime("%Y-%m-%d %H:%M"),
                    "anterior": {k: v for k, v in previo.items() if k != "anterior"}})
    est = _estado()
    est["aviso_pendiente"] = ""
    _guardar_estado(est)
    return (f"Listo: arche-lora ahora es la v{version}. Tu modelo de antes quedó guardado como "
            f"'{NOMBRE_ANTERIOR}'. Si algo no te gusta, di 'vuelve al modelo anterior'.")


def volver_anterior():
    from core.IA import formato_lora
    if not _existe_en_ollama(NOMBRE_ANTERIOR):
        return "No tengo guardado un modelo anterior."
    activo = formato_lora.modelo_activo()
    _ollama("cp", NOMBRE_ANTERIOR, NOMBRE)
    anterior = activo.get("anterior") or {}
    if anterior.get("formato") == "corto":
        _escribir_json(formato_lora._archivo_modelo_activo(), anterior)
    else:
        try:
            os.remove(formato_lora._archivo_modelo_activo())
        except OSError:
            pass
    if activo.get("version"):
        est = _estado()
        if activo["version"] not in est["descartados"]:
            est["descartados"].append(activo["version"])
        _guardar_estado(est)
    return "Listo, volví al modelo anterior. Arché lo usa igual que antes."


def descartar():
    candidato = (estado_nube() or {}).get("candidato") or {}
    version = candidato.get("version")
    if not version:
        return "No hay ningún modelo nuevo que descartar."
    est = _estado()
    if version not in est["descartados"]:
        est["descartados"].append(version)
    est["aviso_pendiente"] = ""
    _guardar_estado(est)
    return f"Descarté arche-lora v{version}. Sigo con el actual."


def texto_estado():
    from core.IA import formato_lora
    activo = formato_lora.modelo_activo()
    partes = [f"Uso arche-lora {'v' + str(activo['version']) if activo.get('version') else 'original (la de tu Colab)'}."]
    try:
        nube = estado_nube()
    except Exception as e:
        return partes[0] + f" No pude leer la nube: {e}."
    if not nube:
        partes.append("El entrenador de la nube todavía no ha corrido (revisa sus secretos en GitHub).")
    else:
        if nube.get("estado") == "entrenando":
            partes.append(f"En la nube se está entrenando la v{nube.get('en_curso')} (desde {nube.get('iniciado', '')[:16]} UTC).")
        if nube.get("nota"):
            partes.append("Último aviso del entrenador: " + nube["nota"])
        if nube.get("forzar"):
            partes.append("Pediste entrenar ya: arranca en el próximo ciclo de la nube.")
        candidato = nube.get("candidato") or {}
        if candidato.get("version"):
            r = _estado()["examinados"].get(str(candidato["version"]))
            partes.append(_texto_resultado(candidato["version"], r) if r else
                          f"Hay un candidato v{candidato['version']} que todavía no examino en tu PC.")
    return " ".join(partes)


# ------------------------------------------------------------------
# Segundo plano
# ------------------------------------------------------------------
def _bucle():
    if _detener.wait(PRIMERA_ESPERA_SEG):
        return
    while not _detener.is_set():
        try:
            from core import memoria_nube
            if memoria_nube.activo() and _token():
                mensaje = revisar_candidato(avisar=lambda *_: None)
                if "Ganó el examen" in mensaje:
                    print(f"\nArché: {mensaje}")
        except Exception:
            pass                                     # el hilo nunca se debe caer
        _detener.wait(INTERVALO_HORAS * 3600)


def iniciar():
    global _hilo
    if _hilo is None or not _hilo.is_alive():
        _detener.clear()
        _hilo = threading.Thread(target=_bucle, name="arche-modelo-nuevo", daemon=True)
        _hilo.start()


def detener():
    _detener.set()


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------
_R = [
    ("estado", re.compile(r"^(estado|como va) (del|el) entrenador$|^(estado|como va) (de )?arche-?lora$")),
    ("entrenar", re.compile(r"^(entrena|entrenate|reentrena|reentrenate) (ya|ahora)$")),
    ("token", re.compile(r"^(conecta|configura) (hugging ?face|hf)$")),
    ("examinar", re.compile(r"^(examina|revisa|busca) (el )?modelo nuevo$")),
    ("usar_igual", re.compile(r"^usa el modelo nuevo igual$")),
    ("usar", re.compile(r"^(usa|cambia a|pasate a) el modelo nuevo$")),
    ("volver", re.compile(r"^(vuelve|regresa) al modelo anterior$")),
    ("descartar", re.compile(r"^descarta el modelo nuevo$")),
]


def interpretar(comando):
    texto = re.sub(r"\s+", " ", _norm(comando)).strip(" .!?¿¡")
    for nombre, regex in _R:
        if regex.match(texto):
            return nombre
    return None


def _ejecutar(cual, confirmar):
    from core.IA import formato_lora
    if cual == "estado":
        return texto_estado()
    if cual == "entrenar":
        pedir_entrenamiento()
        return "Listo, le pedí a la nube que entrene un arche-lora nuevo en su próximo ciclo (una vez al día)."
    if cual == "token":
        print("Arché: Pega tu token de Hugging Face (empieza con 'hf_'). Se guarda cifrado:")
        try:
            token = confirmar("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            token = ""
        if not token.startswith("hf_"):
            return "Eso no parece un token de Hugging Face. No cambié nada."
        from core.seguridad.cifrado import guardar_secreto
        guardar_secreto(ARCHIVO_TOKEN, token)
        return "Guardado. Cuando haya un modelo nuevo lo descargo y lo examino solo."
    if cual == "examinar":
        return revisar_candidato(forzar=True)
    if cual == "usar":
        return usar_nuevo()
    if cual == "usar_igual":
        version = ((estado_nube() or {}).get("candidato") or {}).get("version")
        if not version or str(version) not in _estado()["examinados"]:
            return "Primero tengo que examinarlo: di 'examina el modelo nuevo'."
        return _cambiar(version, formato_lora)
    if cual == "volver":
        return volver_anterior()
    if cual == "descartar":
        return descartar()
    return "No entendí qué hacer con el modelo."


def manejar(comando, confirmar=input):
    cual = interpretar(comando)
    if cual is None:
        return None
    try:
        print("Arché: " + _ejecutar(cual, confirmar))
    except Exception as e:
        print(f"Arché: No pude: {e}.")
    return (cual, None)
