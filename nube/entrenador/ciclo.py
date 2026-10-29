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


def estado_kernel(usuario):
    texto = kaggle("kernels", "status", f"{usuario}/{SLUG_KERNEL}").lower()
    for palabra in ("complete", "error", "cancel", "running", "queued"):
        if palabra in texto:
            return palabra, texto.strip()
    return "desconocido", texto.strip()


def estado_dataset(usuario):
    """'ready', 'failed', otro estado de Kaggle, o el texto del error."""
    texto = kaggle("datasets", "status", f"{usuario}/{SLUG_DATASET}", revisar=False).strip()
    return (texto.splitlines() or [""])[-1].strip().lower()


def subir_dataset(usuario, carpeta, version):
    """Sube el dataset y espera hasta ~15 min. Devuelve el ultimo estado que dio Kaggle."""
    with open(os.path.join(carpeta, "dataset-metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"title": SLUG_DATASET, "id": f"{usuario}/{SLUG_DATASET}",
                   "licenses": [{"name": "CC0-1.0"}]}, f)
    existe = subprocess.run(["kaggle", "datasets", "status", f"{usuario}/{SLUG_DATASET}"],
                            capture_output=True, text=True).returncode == 0
    if existe:
        kaggle("datasets", "version", "-p", carpeta, "-m", f"arche-lora v{version}", "-t", "-q")
    else:
        kaggle("datasets", "create", "-p", carpeta, "-t", "-q")       # privado por defecto
    return esperar_dataset(usuario, minutos=15)


def esperar_dataset(usuario, minutos):
    ultimo = ""
    for _ in range(minutos * 4):
        time.sleep(15)
        ultimo = estado_dataset(usuario)
        print(f"  Kaggle dice que el dataset está: {ultimo}", flush=True)
        if ultimo in ("ready", "failed"):
            break
    return ultimo


def lanzar_kernel(usuario, version):
    carpeta = tempfile.mkdtemp(prefix="arche_kernel_")
    with open(os.path.join(AQUI, "kaggle_entrenar.py"), encoding="utf-8") as f:
        codigo = f.read().replace('VERSION = "__VERSION__"', f'VERSION = "{version}"', 1)
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


def empezar(supa, estado, usuario, forzar, avisar):
    nuevos, max_id = contar_nuevos(supa, estado.get("max_id") or 0)
    toca, motivo = toca_entrenar(estado, nuevos, forzar)
    if not toca:
        avisar(f"No entreno todavía: {motivo}.")
        return 0
    version = int(estado.get("version") or 0) + 1
    filas = supa.leer_todo("arche_ejemplos", {"select": "frase,intencion,contenido,origen,retirado",
                                              "retirado": "is.false"})
    paquete = datos.construir(filas, version)
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
    estado.update(forzar=False, en_curso=version, max_id_en_curso=max_id, iniciado=iso(ahora()))
    return seguir_con_dataset(supa, estado, usuario, situacion, avisar)


def seguir_con_dataset(supa, estado, usuario, situacion, avisar):
    version = estado["en_curso"]
    if situacion == "ready":
        lanzar_kernel(usuario, version)
        estado.update(estado="entrenando", iniciado=iso(ahora()), nota=f"entrenando v{version} en Kaggle")
        guardar_estado(supa, estado)
        avisar(f"Lancé el entrenamiento v{version} en Kaggle (GPU {ACELERADOR}).")
        return 0
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
                  max_id=estado.pop("max_id_en_curso", estado.get("max_id")))
    if metricas.get("aprobado") and metricas.get("gguf"):
        estado["candidato"] = publicar_en_hf(carpeta, version, metricas)
        estado["version"] = version
        estado["nota"] = f"v{version} aprobó en Kaggle: {resumen}. Tu PC la examina antes de usarla."
    else:
        estado["nota"] = f"v{version} NO aprobó: {'; '.join(metricas.get('motivos') or [])} ({resumen})"
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
    try:
        estado = leer_estado(supa)
        if estado["estado"] == "entrenando":
            return revisar(supa, estado, usuario, print)
        if estado["estado"] == "esperando_datos":
            return seguir_con_dataset(supa, estado, usuario, esperar_dataset(usuario, minutos=10), print)
        return empezar(supa, estado, usuario, "--forzar" in argv, print)
    except ErrorTurno as e:
        print(f"El entrenador no pudo terminar: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))