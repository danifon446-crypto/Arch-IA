"""
ciclo.py  (Fase 4: entrenador automatico de arche-lora)
-------------------------------------------------------
Corre una vez al dia en GitHub Actions. Es una maquina de dos estados
guardada en Supabase (arche_config -> "entrenador"):

  (si Kaggle tarda en procesar los datos queda en ESPERANDO_DATOS y
   el siguiente ciclo lanza el entrenamiento cuando esten listos)
  LIBRE       -> ¿toca entrenar? (>= 500 ejemplos nuevos y >= 7 dias, o
                 "entrena ya" desde Arché). Si toca: arma el dataset
                 (datos.py), lo sube a Kaggle como dataset PRIVADO, lanza
                 el entrenamiento en GPU (kaggle_entrenar.py) y pasa a
                 ENTRENANDO.
  ENTRENANDO  -> pregunta a Kaggle como va. Cuando termina, baja el
                 resultado; si APROBO el examen, sube el GGUF a tu
                 repositorio PRIVADO de Hugging Face como candidato
                 (arche-lora-vN) y vuelve a LIBRE.

Tu PC (core/IA/modelo_nuevo.py) ve el candidato, lo descarga, repite el
examen contra TU arche-lora actual y solo si gana te pregunta si lo usas.

Secretos (GitHub -> Settings -> Secrets -> Actions):
  SUPABASE_URL, SUPABASE_SERVICE_KEY            (los mismos de los turnos)
  KAGGLE_USERNAME, KAGGLE_API_TOKEN             (o KAGGLE_KEY, el token viejo)
  HF_TOKEN                                      (token "Write" de Hugging Face)
  HF_REPO (opcional)                            por defecto <tu_usuario_hf>/arche-lora

Uso:  python nube/entrenador/ciclo.py            (un ciclo normal)
      python nube/entrenador/ciclo.py --forzar   (entrena ya aunque no toque)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))      # nube/  -> turno.py (cliente de Supabase)
sys.path.insert(0, AQUI)

import datos                      # noqa: E402
from turno import ErrorTurno, Supabase   # noqa: E402

MIN_NUEVOS = 500
MIN_DIAS = 7
# CRECIMIENTO DE LA LoRA: con más datos, más capacidad (rango). Nunca baja de lo que ya aprobó.
RANGOS_LORA = [(0, 16), (1500, 32), (4000, 64), (10000, 128)]   # (ejemplos de entrenamiento, rango)
PESO_CHARLA = 4                  # un ejemplo de charla del auto-juego cuenta como 4 frases nuevas
MAX_HORAS_ENTRENANDO = 14         # Kaggle corta a las 12 h; si pasa de esto algo quedo colgado
SLUG_DATASET = "arche-datos"
SLUG_KERNEL = "arche-entrenador"
ACELERADOR = "NvidiaTeslaT4"


def ahora():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def de_iso(texto):
    try:
        return datetime.strptime(texto[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


ESTADO_INICIAL = {"estado": "libre", "version": 0, "max_id": 0, "fecha": "", "iniciado": "",
                  "en_curso": None, "candidato": None, "nota": "", "forzar": False}


# ------------------------------------------------------------------
# Estado en Supabase
# ------------------------------------------------------------------
def leer_estado(supa):
    filas = supa.leer("arche_config", {"select": "valor", "clave": "eq.entrenador"})
    estado = dict(ESTADO_INICIAL)
    if filas and isinstance(filas[0].get("valor"), dict):
        estado.update(filas[0]["valor"])
    return estado


def guardar_estado(supa, estado):
    supa._pedir("POST", "arche_config", {"on_conflict": "clave"}, [{"clave": "entrenador", "valor": estado}],
                extra={"Prefer": "return=minimal,resolution=merge-duplicates"})


# ------------------------------------------------------------------
# Kaggle (por la linea de comandos oficial)
# ------------------------------------------------------------------
def kaggle(*args, revisar=True):
    r = subprocess.run(["kaggle", *args], capture_output=True, text=True)
    salida = (r.stdout or "") + (r.stderr or "")
    if revisar and r.returncode != 0:
        raise ErrorTurno(f"kaggle {' '.join(args[:2])} falló: {salida.strip()[-400:]}")
    return salida


def estado_kernel(usuario, slug=SLUG_KERNEL):
    texto = kaggle("kernels", "status", f"{usuario}/{slug}").lower()
    for palabra in ("complete", "error", "cancel", "running", "queued"):
        if palabra in texto:
            return palabra, texto.strip()
    return "desconocido", texto.strip()


def estado_dataset(usuario):
    """'ready', 'failed', otro estado de Kaggle, o el error (sin acceso / no existe)."""
    texto = kaggle("datasets", "status", f"{usuario}/{SLUG_DATASET}", revisar=False).strip()
    if "403" in texto or "don't have access" in texto:
        return "sin acceso: revisa KAGGLE_USERNAME (tu usuario exacto) y KAGGLE_API_TOKEN"
    if "404" in texto or "not found" in texto.lower():
        return "no existe: el dataset no se creó"
    return (texto.splitlines() or [""])[-1].strip().lower()


def subir_dataset(usuario, carpeta, version):
    """Sube el dataset y espera hasta ~15 min. Devuelve el ultimo estado que dio Kaggle."""
    with open(os.path.join(carpeta, "dataset-metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"title": SLUG_DATASET, "id": f"{usuario}/{SLUG_DATASET}",
                   "licenses": [{"name": "CC0-1.0"}]}, f)
    existe = subprocess.run(["kaggle", "datasets", "status", f"{usuario}/{SLUG_DATASET}"],
                            capture_output=True, text=True).returncode == 0
    if existe:
        salida = kaggle("datasets", "version", "-p", carpeta, "-m", f"arche-lora v{version}", "-t")
    else:
        salida = kaggle("datasets", "create", "-p", carpeta, "-t")       # privado por defecto
    print("  Kaggle respondió: " + " ".join(salida.split())[-300:], flush=True)
    # la linea de comandos de Kaggle a veces devuelve "todo bien" aunque haya fallado: se revisa el texto
    if re.search(r"error|forbidden|denied|not authorized|unauthorized|verify|phone|\b40[13]\b", salida, re.I):
        raise ErrorTurno("Kaggle no aceptó el dataset: " + " ".join(salida.split())[-300:])
    return esperar_dataset(usuario, minutos=15)


def esperar_dataset(usuario, minutos):
    ultimo = ""
    for _ in range(minutos * 4):
        time.sleep(15)
        ultimo = estado_dataset(usuario)
        print(f"  Kaggle dice que el dataset está: {ultimo}", flush=True)
        if ultimo in ("ready", "failed") or ultimo.startswith(("sin acceso", "no existe")):
            break
    return ultimo


def elegir_rango(n_entrenamiento, estado):
    """Rango de la LoRA segun cuantos datos hay; crece solo y nunca baja del ultimo aprobado.
    Si el ultimo entrenamiento NO aprobo con ese rango, no sube mas hasta que apruebe."""
    rango = max(r for minimo, r in RANGOS_LORA if n_entrenamiento >= minimo)
    aprobado = int(estado.get("rango_lora") or 16)
    if estado.get("ultimo_rechazado_rango") and rango > aprobado:
        rango = min(rango, int(estado["ultimo_rechazado_rango"]))
    return max(rango, aprobado)


def lanzar_kernel(usuario, version, rango=16):
    carpeta = tempfile.mkdtemp(prefix="arche_kernel_")
    with open(os.path.join(AQUI, "kaggle_entrenar.py"), encoding="utf-8") as f:
        codigo = f.read().replace('VERSION = "__VERSION__"', f'VERSION = "{version}"', 1)
    codigo = codigo.replace("LORA_R, LORA_ALPHA, LORA_DROPOUT = 16, 32, 0.05",
                            f"LORA_R, LORA_ALPHA, LORA_DROPOUT = {int(rango)}, {int(rango) * 2}, 0.05", 1)
    with open(os.path.join(carpeta, "kaggle_entrenar.py"), "w", encoding="utf-8") as f:
        f.write(codigo)
    with open(os.path.join(carpeta, "kernel-metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"id": f"{usuario}/{SLUG_KERNEL}", "title": SLUG_KERNEL, "code_file": "kaggle_entrenar.py",
                   "language": "python", "kernel_type": "script", "is_private": "true",
                   "enable_gpu": "true", "enable_internet": "true", "machine_shape": ACELERADOR,
                   "dataset_sources": [f"{usuario}/{SLUG_DATASET}"], "competition_sources": [],
                   "kernel_sources": [], "model_sources": []}, f)
    kaggle("kernels", "push", "-p", carpeta, "--accelerator", ACELERADOR)


# ------------------------------------------------------------------
# El profesor (kaggle_profesor.py): un modelo grande que genera ejemplos y el examen fijo
# ------------------------------------------------------------------
SLUG_PROFESOR = "arche-profesor"
DIAS_ENTRE_PROFESOR = 2
MAX_HORAS_PROFESOR = 6
MAX_CHARLA_PROFESOR = 2000
MAX_EXAMEN_PROFESOR = 250


def lanzar_profesor(usuario, temas):
    carpeta = tempfile.mkdtemp(prefix="arche_profesor_")
    with open(os.path.join(AQUI, "kaggle_profesor.py"), encoding="utf-8") as f:
        codigo = f.read().replace('TEMAS_JSON = "[]"', "TEMAS_JSON = " + json.dumps(json.dumps(temas[:40])), 1)
    with open(os.path.join(carpeta, "kaggle_profesor.py"), "w", encoding="utf-8") as f:
        f.write(codigo)
    with open(os.path.join(carpeta, "kernel-metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"id": f"{usuario}/{SLUG_PROFESOR}", "title": SLUG_PROFESOR, "code_file": "kaggle_profesor.py",
                   "language": "python", "kernel_type": "script", "is_private": "true",
                   "enable_gpu": "true", "enable_internet": "true", "machine_shape": ACELERADOR,
                   "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}, f)
    kaggle("kernels", "push", "-p", carpeta, "--accelerator", ACELERADOR)


def leer_jsonl(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def guardar_lo_del_profesor(supa, nuevos, examen):
    """Suma lo nuevo a Supabase sin duplicar. Devuelve (ejemplos agregados, preguntas de examen agregadas)."""
    charla = leer_config(supa, "charla_profesor", {}) or {}
    previos = charla.get("ejemplos", [])
    vistas = {datos.normalizar(e["pregunta"]) for e in previos}
    agregados = [{"pregunta": e["pregunta"], "respuesta": e["respuesta"], "tema": e.get("tema", "")}
                 for e in nuevos if datos.normalizar(e["pregunta"]) not in vistas]
    guardar_config(supa, "charla_profesor", {"total": int(charla.get("total", 0)) + len(agregados),
                                             "ejemplos": (previos + agregados)[-MAX_CHARLA_PROFESOR:]})
    ex = leer_config(supa, "examen_profesor", {}) or {}
    items = ex.get("items", [])
    vistas_ex = {datos.normalizar(e["pregunta"]) for e in items}
    nuevas_ex = [{"pregunta": e["pregunta"], "claves": e["claves"], "area": e.get("tema", "general")[:40]}
                 for e in examen if e.get("claves") and datos.normalizar(e["pregunta"]) not in vistas_ex]
    lugar = max(0, MAX_EXAMEN_PROFESOR - len(items))           # el examen fijo crece hasta un tope y se queda
    if nuevas_ex[:lugar]:
        guardar_config(supa, "examen_profesor", {"items": items + nuevas_ex[:lugar], "actualizado": iso(ahora())})
    return len(agregados), len(nuevas_ex[:lugar])


def recoger_profesor(supa, usuario, avisar):
    """Si el profesor estaba corriendo y terminó, guarda su trabajo. Devuelve True si SIGUE corriendo."""
    prof = leer_config(supa, "profesor", {}) or {}
    if prof.get("estado") == "corriendo":
        situacion, texto = estado_kernel(usuario, SLUG_PROFESOR)
        horas = (ahora() - (de_iso(prof.get("iniciado") or "") or ahora())).total_seconds() / 3600
        if situacion in ("running", "queued") and horas <= MAX_HORAS_PROFESOR:
            avisar(f"El profesor sigue trabajando en Kaggle ({horas:.1f} h).")
            return True
        prof.update(estado="libre", fecha=iso(ahora()))
        if situacion == "complete":
            carpeta = tempfile.mkdtemp(prefix="arche_salida_prof_")
            kaggle("kernels", "output", f"{usuario}/{SLUG_PROFESOR}", "-p", carpeta, "-o", "-q")
            n, ne = guardar_lo_del_profesor(supa, leer_jsonl(os.path.join(carpeta, "profesor.jsonl")),
                                            leer_jsonl(os.path.join(carpeta, "examen.jsonl")))
            try:
                with open(os.path.join(carpeta, "resumen_profesor.json"), encoding="utf-8") as f:
                    resumen = json.load(f)
            except (OSError, ValueError):
                resumen = {}
            prof["nota"] = (f"el profesor ({resumen.get('modelo', '?')}) dejó {n} ejemplos nuevos y "
                            f"{ne} preguntas para el examen fijo")
            shutil.rmtree(carpeta, ignore_errors=True)
        else:
            prof["nota"] = f"el profesor no terminó en Kaggle: {situacion} {texto[-200:]}"
        guardar_config(supa, "profesor", prof)
        avisar(prof["nota"])
    return False


def lanzar_profesor_si_toca(supa, usuario, avisar):
    """Solo con la GPU libre (el entrenador no está en Kaggle) y cada DIAS_ENTRE_PROFESOR días."""
    prof = leer_config(supa, "profesor", {}) or {}
    if prof.get("estado") == "corriendo":
        return
    ultima = de_iso(prof.get("fecha") or "")
    if ultima and (ahora() - ultima).days < DIAS_ENTRE_PROFESOR:
        return
    temas = (leer_config(supa, "temas_profesor", {}) or {}).get("temas", [])
    lanzar_profesor(usuario, [t for t in temas if isinstance(t, str)])
    prof.update(estado="corriendo", iniciado=iso(ahora()))
    guardar_config(supa, "profesor", prof)
    avisar(f"Lancé al profesor en Kaggle con {len(temas)} temas de Arché (+ los temas base).")


# ------------------------------------------------------------------
# Hugging Face
# ------------------------------------------------------------------
def publicar_en_hf(carpeta, version, metricas):
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_TOKEN"])
    repo = os.environ.get("HF_REPO", "").strip() or f"{api.whoami()['name']}/arche-lora"
    api.create_repo(repo, private=True, exist_ok=True, repo_type="model")
    gguf = metricas["gguf"]["archivo"]
    destino = f"v{version}"
    for nombre in (gguf, "metricas.json", "validacion.jsonl"):
        api.upload_file(path_or_fileobj=os.path.join(carpeta, nombre), path_in_repo=f"{destino}/{nombre}",
                        repo_id=repo, commit_message=f"arche-lora v{version}: {nombre}")
    return {"version": version, "repo": repo, "archivo": f"{destino}/{gguf}", "metricas": f"{destino}/metricas.json",
            "validacion": f"{destino}/validacion.jsonl", "bytes": metricas["gguf"]["bytes"],
            "tipo": metricas["gguf"]["tipo"], "fecha": iso(ahora()),
            "acierto": metricas["examen_nuevo"]["acierto"], "acierto_base": metricas["examen_base"]["acierto"]}


# ------------------------------------------------------------------
# El ciclo
# ------------------------------------------------------------------
def contar_nuevos(supa, desde_id):
    filas = supa.leer_todo("arche_ejemplos", {"select": "id", "id": f"gt.{int(desde_id)}", "retirado": "is.false"})
    return len(filas), max((f["id"] for f in filas), default=desde_id)


def toca_entrenar(estado, nuevos, forzar):
    if forzar or estado.get("forzar"):
        return True, "pedido a mano"
    if nuevos < MIN_NUEVOS:
        return False, f"hay {nuevos} ejemplos nuevos (hacen falta {MIN_NUEVOS})"
    ultima = de_iso(estado.get("fecha") or "")
    if ultima and (ahora() - ultima).days < MIN_DIAS:
        return False, f"el último entrenamiento fue hace {(ahora() - ultima).days} días (mínimo {MIN_DIAS})"
    return True, f"{nuevos} ejemplos nuevos"


def leer_config(supa, clave, defecto=None):
    try:
        filas = supa.leer("arche_config", {"select": "valor", "clave": f"eq.{clave}"})
        valor = (filas or [{}])[0].get("valor")
        return valor if valor is not None else defecto
    except Exception:
        return defecto


def guardar_config(supa, clave, valor):
    supa._pedir("POST", "arche_config", {"on_conflict": "clave"}, [{"clave": clave, "valor": valor}],
                extra={"Prefer": "return=minimal,resolution=merge-duplicates"})


def leer_charla(supa):
    """Charla para entrenar: la del auto-juego de Arché (charla_aprendida) + la del profesor
    (charla_profesor). Devuelve (contador total que solo crece, ejemplos)."""
    total, ejemplos = 0, []
    for clave in ("charla_aprendida", "charla_profesor"):
        valor = leer_config(supa, clave, {}) or {}
        total += int(valor.get("total", 0))
        ejemplos += [e for e in valor.get("ejemplos", [])
                     if isinstance(e, dict) and e.get("pregunta") and e.get("respuesta")]
    return total, ejemplos


def empezar(supa, estado, usuario, forzar, avisar):
    nuevos, max_id = contar_nuevos(supa, estado.get("max_id") or 0)
    total_charla, charla = leer_charla(supa)
    charla_nueva = max(0, total_charla - int(estado.get("charla_usada") or 0))
    nuevos += charla_nueva * PESO_CHARLA
    toca, motivo = toca_entrenar(estado, nuevos, forzar)
    if not toca:
        avisar(f"No entreno todavía: {motivo}.")
        return 0
    version = int(estado.get("version") or 0) + 1
    filas = supa.leer_todo("arche_ejemplos", {"select": "frase,intencion,contenido,origen,retirado",
                                              "retirado": "is.false"})
    paquete = datos.construir(filas, version, charla=charla)
    meta = paquete["meta"]
    avisar(f"Entreno v{version} ({motivo}): {meta['entrenamiento']} para entrenar, {meta['validacion']} de "
           f"validación, {meta['intenciones']} intenciones. Limpieza: {meta['informe_limpieza']}")
    if meta["entrenamiento"] < 200 or meta["validacion"] < 20:
        estado.update(forzar=False, nota=f"muy pocos datos limpios para v{version} ({meta['entrenamiento']})")
        guardar_estado(supa, estado)
        avisar(estado["nota"])
        return 0
    carpeta = tempfile.mkdtemp(prefix="arche_datos_")
    datos.guardar(paquete, carpeta)
    situacion = subir_dataset(usuario, carpeta, version)
    estado.update(forzar=False, en_curso=version, max_id_en_curso=max_id, iniciado=iso(ahora()),
                  charla_usada_en_curso=total_charla,
                  rango_en_curso=elegir_rango(meta["entrenamiento"] + meta.get("charla_aprendida", 0), estado))
    avisar(f"Rango de la LoRA para v{version}: {estado['rango_en_curso']}")
    return seguir_con_dataset(supa, estado, usuario, situacion, avisar)


def seguir_con_dataset(supa, estado, usuario, situacion, avisar):
    version = estado["en_curso"]
    if situacion == "ready":
        lanzar_kernel(usuario, version, estado.get("rango_en_curso") or estado.get("rango_lora") or 16)
        estado.update(estado="entrenando", iniciado=iso(ahora()), nota=f"entrenando v{version} en Kaggle")
        guardar_estado(supa, estado)
        avisar(f"Lancé el entrenamiento v{version} en Kaggle (GPU {ACELERADOR}).")
        return 0
    if situacion.startswith(("sin acceso", "no existe")):
        estado.update(estado="libre", en_curso=None, nota=f"v{version}: Kaggle dice {situacion}")
        guardar_estado(supa, estado)
        avisar(estado["nota"])
        return 1
    if situacion == "failed":
        estado.update(estado="libre", en_curso=None, nota=f"Kaggle no pudo procesar el dataset de v{version}")
        guardar_estado(supa, estado)
        avisar(estado["nota"])
        return 1
    iniciado = de_iso(estado.get("iniciado") or "")
    if iniciado and (ahora() - iniciado).total_seconds() > 24 * 3600:
        estado.update(estado="libre", en_curso=None,
                      nota=f"el dataset de v{version} lleva un día sin quedar listo en Kaggle ({situacion})")
        guardar_estado(supa, estado)
        avisar(estado["nota"])
        return 1
    estado.update(estado="esperando_datos",
                  nota=f"v{version}: datos subidos, Kaggle todavía los procesa ({situacion}). Sigo en el próximo ciclo.")
    guardar_estado(supa, estado)
    avisar(estado["nota"])
    return 0


def revisar(supa, estado, usuario, avisar):
    version = estado.get("en_curso")
    situacion, texto = estado_kernel(usuario)
    iniciado = de_iso(estado.get("iniciado") or "")
    horas = (ahora() - iniciado).total_seconds() / 3600 if iniciado else 0
    if situacion in ("running", "queued"):
        if horas > MAX_HORAS_ENTRENANDO:
            estado.update(estado="libre", en_curso=None, nota=f"v{version} se quedó colgada en Kaggle ({horas:.0f} h)")
            guardar_estado(supa, estado)
            avisar(estado["nota"])
        else:
            avisar(f"v{version} sigue en Kaggle ({situacion}, {horas:.1f} h).")
        return 0
    if situacion != "complete":
        estado.update(estado="libre", en_curso=None, nota=f"v{version} falló en Kaggle: {texto[-300:]}")
        guardar_estado(supa, estado)
        avisar(estado["nota"])
        return 0

    carpeta = tempfile.mkdtemp(prefix="arche_salida_")
    kaggle("kernels", "output", f"{usuario}/{SLUG_KERNEL}", "-p", carpeta, "-o", "-q")
    ruta_metricas = os.path.join(carpeta, "metricas.json")
    if not os.path.exists(ruta_metricas):
        estado.update(estado="libre", en_curso=None, nota=f"v{version} terminó sin metricas.json (revisa el log en Kaggle)")
        guardar_estado(supa, estado)
        avisar(estado["nota"])
        return 0
    with open(ruta_metricas, encoding="utf-8") as f:
        metricas = json.load(f)
    nuevo, base = metricas["examen_nuevo"], metricas["examen_base"]
    resumen = (f"acierto {nuevo['acierto']:.1%} (base {base['acierto']:.1%}), JSON {nuevo['json_valido']:.0%}, "
               f"charla {nuevo['charla_ok']:.0%}")
    estado.update(estado="libre", en_curso=None, fecha=estado.get("iniciado"),
                  max_id=estado.pop("max_id_en_curso", estado.get("max_id")),
                  charla_usada=estado.pop("charla_usada_en_curso", estado.get("charla_usada", 0)))
    if metricas.get("aprobado") and metricas.get("gguf"):
        estado["candidato"] = publicar_en_hf(carpeta, version, metricas)
        estado["version"] = version
        estado["rango_lora"] = estado.pop("rango_en_curso", estado.get("rango_lora", 16))
        estado.pop("ultimo_rechazado_rango", None)
        estado["nota"] = f"v{version} aprobó en Kaggle: {resumen}. Tu PC la examina antes de usarla."
    else:
        estado["nota"] = f"v{version} NO aprobó: {'; '.join(metricas.get('motivos') or [])} ({resumen})"
        rechazado = estado.pop("rango_en_curso", None)
        if rechazado and int(rechazado) > int(estado.get("rango_lora") or 16):
            estado["ultimo_rechazado_rango"] = int(rechazado)   # no sigue subiendo hasta aprobar con este
    guardar_estado(supa, estado)
    avisar(estado["nota"])
    shutil.rmtree(carpeta, ignore_errors=True)
    return 0


def main(argv):
    faltan = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "KAGGLE_USERNAME", "HF_TOKEN")
              if not os.environ.get(n, "").strip()]
    if not (os.environ.get("KAGGLE_API_TOKEN") or os.environ.get("KAGGLE_KEY")):
        faltan.append("KAGGLE_API_TOKEN")
    if faltan:
        print("El entrenador todavía no está configurado. Faltan secretos: " + ", ".join(faltan) + ". No hice nada.")
        return 0
    supa = Supabase(os.environ["SUPABASE_URL"].strip(), os.environ["SUPABASE_SERVICE_KEY"].strip())
    usuario = os.environ["KAGGLE_USERNAME"].strip()
    codigo_profesor, profesor_corriendo = 0, False
    try:                                     # 1) si el profesor terminó, su trabajo entra a este mismo ciclo
        profesor_corriendo = recoger_profesor(supa, usuario, print)
    except ErrorTurno as e:
        print(f"El profesor no pudo terminar: {e}")
        codigo_profesor = 1
    try:                                     # 2) el entrenador, como siempre (una sola GPU a la vez)
        estado = leer_estado(supa)
        if estado["estado"] == "entrenando":
            codigo = revisar(supa, estado, usuario, print)
        elif estado["estado"] == "esperando_datos":
            codigo = seguir_con_dataset(supa, estado, usuario, esperar_dataset(usuario, minutos=10), print)
        elif profesor_corriendo:
            print("El entrenador espera: el profesor está usando la GPU de Kaggle.")
            codigo = 0
        else:
            codigo = empezar(supa, estado, usuario, "--forzar" in argv, print)
    except ErrorTurno as e:
        print(f"El entrenador no pudo terminar: {e}")
        return 1
    try:                                     # 3) si la GPU quedó libre, le toca al profesor
        if not profesor_corriendo and leer_estado(supa)["estado"] == "libre":
            lanzar_profesor_si_toca(supa, usuario, print)
    except ErrorTurno as e:
        print(f"No pude lanzar al profesor: {e}")
        codigo_profesor = 1
    return codigo or codigo_profesor


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))