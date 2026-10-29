"""
kaggle_entrenar.py  (corre en Kaggle, con GPU gratis)
-----------------------------------------------------
Entrena una version nueva de arche-lora y la examina. Lo sube y lo
lanza nube/entrenador/ciclo.py; no hace falta abrirlo a mano.

Pasos (lo mismo que tu notebook de Colab, pero con examen):
  1. Lee el dataset (entrenamiento / validacion / repaso) que preparo ciclo.py.
  2. REPASO: el modelo base contesta preguntas de charla general; esas
     respuestas se mezclan con el entrenamiento para que no olvide conversar.
  3. Entrena LoRA sobre Qwen2.5-1.5B-Instruct, midiendo la perdida en
     validacion cada epoca y parando si empieza a memorizar.
  4. EXAMEN: modelo base vs modelo nuevo sobre la validacion (frases que
     nunca vio): JSON valido, acierto de intencion (total y por dominio)
     y charla (que no conteste con JSON cuando le hablan normal).
  5. Si aprueba: fusiona, convierte a GGUF (Q4_K_M) y deja en la salida
     arche-lora-vN.gguf + metricas.json + validacion.jsonl.

Variables para probarlo fuera de Kaggle (sin GPU, con un modelo chico):
  ARCHE_BASE, ARCHE_DATOS, ARCHE_SALIDA, ARCHE_SIN_GGUF=1, ARCHE_RAPIDO=1
"""

import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict

VERSION = "__VERSION__"                 # ciclo.py lo reemplaza antes de subirlo
BASE = os.environ.get("ARCHE_BASE", "Qwen/Qwen2.5-1.5B-Instruct")
SALIDA = os.environ.get("ARCHE_SALIDA", "/kaggle/working")
TMP = os.environ.get("ARCHE_TMP", "/tmp/arche")         # fuera de /kaggle/working: no se guarda como salida
RAPIDO = os.environ.get("ARCHE_RAPIDO") == "1"

MAX_EPOCAS = 1 if RAPIDO else 3
LR = 2e-4
LORA_R, LORA_ALPHA, LORA_DROPOUT = 16, 32, 0.05
LOTE, ACUMULAR = (2, 1) if RAPIDO else (8, 2)
MAX_TOKENS = 384
MAX_EXAMEN = 40 if RAPIDO else 400
REPASO_MAX_TOKENS = 24 if RAPIDO else 220

# Reglas para aprobar (si no las cumple, no se publica)
MIN_JSON_VALIDO = 0.95
MIN_CHARLA_OK = 0.75
TOLERANCIA_DOMINIO = 0.02    # un dominio puede bajar como mucho 2 puntos frente al base


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def instalar_si_falta():
    # Kaggle trae torchao 0.10 y peft nuevo se niega a funcionar con un torchao viejo
    # ("Found an incompatible version of torchao"). No lo usamos: se quita.
    import importlib.util
    if importlib.util.find_spec("torchao") is not None:
        log("Quito torchao (version vieja de Kaggle que choca con peft).")
        subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"])
    faltan = []
    for modulo, paquete in (("peft", "peft>=0.11"), ("accelerate", "accelerate")):
        try:
            __import__(modulo)
        except ImportError:
            faltan.append(paquete)
    if faltan:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + faltan)


def buscar_datos():
    if os.environ.get("ARCHE_DATOS"):
        return os.environ["ARCHE_DATOS"]
    for meta in glob.glob("/kaggle/input/**/meta.json", recursive=True):
        return os.path.dirname(meta)
    raise SystemExit("No encontré el dataset (meta.json) en /kaggle/input.")


def leer_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def parsear(texto):
    texto = (texto or "").strip()
    i, j = texto.find("{"), texto.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(texto[i:j + 1])
    except ValueError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("intencion"), str):
        return None
    c = d.get("contenido")
    return d["intencion"].strip(), (c if isinstance(c, str) else "").strip()


def main():
    instalar_si_falta()
    import torch
    from peft import LoraConfig, get_peft_model
    try:      # segundo seguro: si torchao no se pudo quitar, peft hace como si no existiera
        import peft.import_utils as _pi
        import peft.tuners.lora.torchao as _pt
        _pi.is_torchao_available = _pt.is_torchao_available = lambda: False
    except Exception:
        pass
    from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq,
                              EarlyStoppingCallback, Trainer, TrainingArguments)

    carpeta = buscar_datos()
    with open(os.path.join(carpeta, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    if str(meta.get("version")) != str(VERSION) and VERSION != "__VERSION__":
        raise SystemExit(f"El dataset es de la version {meta.get('version')} y este script de la {VERSION}: "
                         f"Kaggle todavia no termino de procesar el dataset nuevo. Se reintenta en el proximo ciclo.")
    entrenamiento = leer_jsonl(os.path.join(carpeta, "entrenamiento.jsonl"))
    validacion = leer_jsonl(os.path.join(carpeta, "validacion.jsonl"))
    with open(os.path.join(carpeta, "repaso.json"), encoding="utf-8") as f:
        repaso = json.load(f)
    if RAPIDO:
        entrenamiento, validacion = entrenamiento[:64], validacion[:MAX_EXAMEN]
        repaso = {"entrenar": repaso["entrenar"][:6], "validar": repaso["validar"][:3]}
    sis_clasificar, sis_charla = meta["sistema_clasificar"], meta["sistema_charla"]
    log(f"Version {VERSION}: {len(entrenamiento)} para entrenar, {len(validacion)} de validacion.")

    gpu = torch.cuda.is_available()
    bf16 = gpu and torch.cuda.is_bf16_supported()
    tipo = torch.bfloat16 if bf16 else torch.float32       # en P100/T4 sin bf16: pesos fp32 + autocast fp16
    tok = AutoTokenizer.from_pretrained(BASE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    import transformers
    v5 = int(transformers.__version__.split(".")[0]) >= 5      # en la v5 'torch_dtype' pasó a llamarse 'dtype'
    modelo = AutoModelForCausalLM.from_pretrained(BASE, **({"dtype": tipo} if v5 else {"torch_dtype": tipo}))
    modelo = modelo.to("cuda" if gpu else "cpu")
    dispositivo = modelo.device

    def prompt(mensajes):
        return tok.apply_chat_template(mensajes, tokenize=False, add_generation_prompt=True)

    def m_clasificar(frase):
        return [{"role": "system", "content": sis_clasificar}, {"role": "user", "content": frase}]

    def m_charla(pregunta):
        return [{"role": "system", "content": sis_charla}, {"role": "user", "content": pregunta}]

    @torch.no_grad()
    def generar(m, textos, max_nuevos, lote=16):
        m.eval()
        tok.padding_side = "left"
        salidas = []
        for i in range(0, len(textos), lote):
            parte = tok(textos[i:i + lote], return_tensors="pt", padding=True).to(dispositivo)
            with torch.autocast("cuda", dtype=torch.float16, enabled=gpu and not bf16):
                out = m.generate(**parte, max_new_tokens=max_nuevos, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
            for fila in out[:, parte["input_ids"].shape[1]:]:
                salidas.append(tok.decode(fila, skip_special_tokens=True))
        tok.padding_side = "right"
        return salidas

    def examinar(m, nombre):
        textos = [prompt(m_clasificar(e["frase"])) for e in validacion]
        respuestas = generar(m, textos, 48)
        por_dominio = defaultdict(lambda: [0, 0])
        validos = aciertos = 0
        fallos = []
        for e, r in zip(validacion, respuestas):
            p = parsear(r)
            ok = p is not None and p[0] == e["intencion"]
            validos += p is not None
            aciertos += ok
            por_dominio[e["dominio"]][0] += ok
            por_dominio[e["dominio"]][1] += 1
            if not ok and len(fallos) < 25:
                fallos.append({"frase": e["frase"], "esperada": e["intencion"], "dijo": r[:120]})
        charla = generar(m, [prompt(m_charla(q)) for q in repaso["validar"]], 120)
        charla_ok = sum(1 for c in charla if len(c.strip()) >= 8 and parsear(c) is None)
        n = max(1, len(validacion))
        res = {"json_valido": validos / n, "acierto": aciertos / n,
               "por_dominio": {d: a / t for d, (a, t) in sorted(por_dominio.items())},
               "charla_ok": charla_ok / max(1, len(charla)), "ejemplos": len(validacion),
               "fallos": fallos, "charla_muestra": [{"pregunta": q, "respuesta": c[:300]}
                                                    for q, c in zip(repaso["validar"], charla)]}
        log(f"Examen {nombre}: acierto {res['acierto']:.1%}, JSON valido {res['json_valido']:.1%}, "
            f"charla {res['charla_ok']:.0%}")
        return res

    # ---- 1. examen del modelo base y respuestas de repaso (antes de tocarlo)
    examen_base = examinar(modelo, "base")
    log("Generando respuestas de repaso con el modelo base...")
    respuestas_repaso = generar(modelo, [prompt(m_charla(q)) for q in repaso["entrenar"]], REPASO_MAX_TOKENS)

    # ---- 2. dataset tokenizado (solo se aprende la respuesta, no la pregunta)
    def ejemplo(mensajes, respuesta):
        entrada = tok(prompt(mensajes), add_special_tokens=False)["input_ids"]
        objetivo = tok(respuesta + tok.eos_token, add_special_tokens=False)["input_ids"]
        ids = (entrada + objetivo)[:MAX_TOKENS]
        etiquetas = ([-100] * len(entrada) + objetivo)[:MAX_TOKENS]
        return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": etiquetas}

    def salida_json(e):
        return json.dumps({"intencion": e["intencion"], "contenido": e.get("contenido", "")}, ensure_ascii=False)

    filas = [ejemplo(m_clasificar(e["frase"]), salida_json(e)) for e in entrenamiento]
    filas += [ejemplo(m_charla(q), r.strip()) for q, r in zip(repaso["entrenar"], respuestas_repaso) if r.strip()]
    filas_val = [ejemplo(m_clasificar(e["frase"]), salida_json(e)) for e in validacion]
    log(f"Filas de entrenamiento: {len(filas)} (con {len(respuestas_repaso)} de repaso)")

    class Lista(torch.utils.data.Dataset):
        def __init__(self, f):
            self.f = f

        def __len__(self):
            return len(self.f)

        def __getitem__(self, i):
            return self.f[i]

    # ---- 3. LoRA
    modelo.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    modelo.enable_input_require_grads()
    modelo.config.use_cache = False
    lora = LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    modelo = get_peft_model(modelo, lora)
    modelo.print_trainable_parameters()
    # 5% de calentamiento, en pasos enteros (warmup_ratio ya no existe en transformers 5)
    calentamiento = max(1, int(0.05 * MAX_EPOCAS * math.ceil(len(filas) / (LOTE * ACUMULAR))))
    args = TrainingArguments(
        output_dir=os.path.join(TMP, "checkpoints"), num_train_epochs=MAX_EPOCAS, learning_rate=LR,
        per_device_train_batch_size=LOTE, per_device_eval_batch_size=LOTE, gradient_accumulation_steps=ACUMULAR,
        lr_scheduler_type="cosine", warmup_steps=calentamiento, weight_decay=0.0, logging_steps=10,
        eval_strategy="epoch", save_strategy="epoch", save_total_limit=2, load_best_model_at_end=True,
        metric_for_best_model="eval_loss", greater_is_better=False, report_to=[],
        fp16=gpu and not bf16, bf16=bf16, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False}, use_cpu=not gpu,
    )
    trainer = Trainer(model=modelo, args=args, train_dataset=Lista(filas), eval_dataset=Lista(filas_val),
                      data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                      callbacks=[EarlyStoppingCallback(early_stopping_patience=1)])
    trainer.train()
    historia = [{k: v for k, v in h.items() if k in ("epoch", "loss", "eval_loss")} for h in trainer.state.log_history]
    modelo.config.use_cache = True

    # ---- 4. examen del modelo nuevo
    examen_nuevo = examinar(modelo, "nuevo")
    peores = {d: (examen_base["por_dominio"].get(d, 0), v) for d, v in examen_nuevo["por_dominio"].items()
              if v < examen_base["por_dominio"].get(d, 0) - TOLERANCIA_DOMINIO}
    motivos = []
    if examen_nuevo["acierto"] <= examen_base["acierto"]:
        motivos.append("no mejora el acierto del modelo base")
    if examen_nuevo["json_valido"] < MIN_JSON_VALIDO:
        motivos.append(f"JSON valido {examen_nuevo['json_valido']:.0%} (< {MIN_JSON_VALIDO:.0%})")
    if examen_nuevo["charla_ok"] < MIN_CHARLA_OK:
        motivos.append(f"la charla se rompio ({examen_nuevo['charla_ok']:.0%})")
    if peores:
        motivos.append("empeora en: " + ", ".join(sorted(peores)))
    if os.environ.get("ARCHE_PRUEBA_APROBAR") == "1":      # solo para probar el camino completo sin GPU
        motivos = []
    metricas = {"version": VERSION, "base": BASE, "aprobado": not motivos, "motivos": motivos,
                "examen_base": examen_base, "examen_nuevo": examen_nuevo, "historia": historia,
                "datos": {k: meta[k] for k in ("entrenamiento", "validacion", "intenciones", "informe_limpieza")},
                "version_formato": meta.get("version_formato"), "fecha": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    os.makedirs(SALIDA, exist_ok=True)
    shutil.copy(os.path.join(carpeta, "validacion.jsonl"), os.path.join(SALIDA, "validacion.jsonl"))

    if motivos:
        log("NO APROBADO: " + "; ".join(motivos))
    else:
        # ---- 5. fusionar y convertir a GGUF
        fusionado = os.path.join(TMP, "fusionado")
        modelo = modelo.merge_and_unload()
        modelo = modelo.to(torch.float16) if gpu else modelo
        modelo.save_pretrained(fusionado, safe_serialization=True)
        tok.save_pretrained(fusionado)
        log("Modelo fusionado guardado.")
        del modelo, trainer
        if gpu:
            torch.cuda.empty_cache()
        if os.environ.get("ARCHE_SIN_GGUF") == "1":
            metricas["gguf"] = None
        else:
            metricas["gguf"] = convertir_gguf(fusionado, os.path.join(SALIDA, f"arche-lora-v{VERSION}.gguf"))
            if not metricas["gguf"]:
                metricas["aprobado"] = False
                metricas["motivos"].append("no se pudo convertir a GGUF")
    with open(os.path.join(SALIDA, "metricas.json"), "w", encoding="utf-8") as f:
        json.dump(metricas, f, ensure_ascii=False, indent=2)
    log("Listo. aprobado=" + str(metricas["aprobado"]))


def convertir_gguf(carpeta_modelo, destino):
    """HF -> GGUF f16 -> Q4_K_M (como tu notebook). Si no se puede compilar el cuantizador, deja Q8_0."""
    llama = os.path.join(TMP, "llama.cpp")
    if not os.path.isdir(llama):
        subprocess.check_call(["git", "clone", "--depth", "1", "https://github.com/ggml-org/llama.cpp", llama])
    subprocess.call([sys.executable, "-m", "pip", "install", "-q", "gguf", "sentencepiece", "protobuf"])
    f16 = os.path.join(TMP, "arche-f16.gguf")
    subprocess.check_call([sys.executable, os.path.join(llama, "convert_hf_to_gguf.py"), carpeta_modelo,
                           "--outtype", "f16", "--outfile", f16])
    try:
        subprocess.check_call(["cmake", "-S", llama, "-B", os.path.join(llama, "build"), "-DGGML_CUDA=OFF",
                               "-DLLAMA_CURL=OFF", "-DCMAKE_BUILD_TYPE=Release"])
        subprocess.check_call(["cmake", "--build", os.path.join(llama, "build"), "--target", "llama-quantize",
                               "-j", str(os.cpu_count() or 2)])
        cuantizador = glob.glob(os.path.join(llama, "build", "**", "llama-quantize"), recursive=True)[0]
        subprocess.check_call([cuantizador, f16, destino, "Q4_K_M"])
        tipo = "Q4_K_M"
    except Exception as e:
        log(f"No pude cuantizar a Q4_K_M ({e}); lo dejo en Q8_0.")
        subprocess.check_call([sys.executable, os.path.join(llama, "convert_hf_to_gguf.py"), carpeta_modelo,
                               "--outtype", "q8_0", "--outfile", destino])
        tipo = "Q8_0"
    tam = os.path.getsize(destino)
    log(f"GGUF listo: {os.path.basename(destino)} ({tipo}, {tam / 1e9:.2f} GB)")
    return {"archivo": os.path.basename(destino), "tipo": tipo, "bytes": tam}


if __name__ == "__main__":
    main()