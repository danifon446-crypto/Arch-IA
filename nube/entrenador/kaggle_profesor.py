"""
kaggle_profesor.py  (corre en Kaggle, con GPU gratis)
-----------------------------------------------------
EL PROFESOR DE ARCHÉ. Un modelo abierto mucho más grande que arche-lora
(Qwen2.5-14B-Instruct, licencia Apache 2.0, que permite entrenar con sus
respuestas) hace tres cosas sobre los temas que Arché quiere aprender:

  1. PREGUNTA: inventa preguntas variadas, como las que tú le harías a Arché.
  2. RESPONDE: contesta cada una como Arché, bien y sin relleno.
  3. CALIFICA: se revisa a sí mismo con un juez estricto (1 a 10). Solo lo
     excelente (>= NOTA_MINIMA) sale de aquí.

De lo que sale:
  * profesor.jsonl -> ejemplos de charla para entrenar arche-lora.
  * examen.jsonl   -> un 15% que NUNCA se entrena: es el EXAMEN FIJO con el que
                      Arché se mide cada noche (así la nota de hoy se puede
                      comparar con la de ayer).

ciclo.py lo lanza cada pocos días (cuando la GPU no está entrenando), baja la
salida y la guarda en Supabase. No necesita secretos: solo baja el modelo de
Hugging Face (es público).

Si la GPU no alcanza para el 14B, baja solo al 7B y luego al 3B.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

TEMAS_JSON = "[]"                 # ciclo.py pone aquí los temas de Arché
SALIDA = os.environ.get("ARCHE_SALIDA", "/kaggle/working")
RAPIDO = os.environ.get("ARCHE_RAPIDO") == "1"

MODELOS = ["Qwen/Qwen2.5-14B-Instruct", "Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-3B-Instruct"]
PREGUNTAS_POR_TEMA = 3 if RAPIDO else 12
NOTA_MINIMA = 8
PORCENTAJE_EXAMEN = 15
TIEMPO_MAX = (10 if RAPIDO else 210) * 60       # segundos; Kaggle corta a las 12 h, aquí sobra
LOTE = 8

TEMAS_BASE = [
    "programación en Python para principiantes", "estructuras de datos básicas", "C++ básico: punteros y bucles",
    "electrónica básica: ley de Ohm, resistencias y LEDs", "servomotores y cómo se controlan con PWM",
    "ESP32 y Arduino: pines, sensores y comunicación", "robots cuadrúpedos: cómo caminan",
    "cálculo diferencial: límites y derivadas", "lógica digital y compuertas", "matemáticas discretas: conjuntos",
    "ajedrez: aperturas y tácticas básicas", "cómo funcionan las redes neuronales", "seguridad informática básica",
    "cómo organizar el tiempo para estudiar", "inglés básico para hispanohablantes", "cultura general y ciencia",
]

SISTEMA_ARCHE = ("Eres Arché, el asistente personal de IA de un estudiante de ingeniería en Colombia. "
                 "Respondes en español, de forma clara, correcta y útil, sin relleno. Si das pasos, numéralos. "
                 "Si algo no es seguro, lo dices.")


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def instalar_si_falta():
    faltan = []
    for modulo, paquete in (("accelerate", "accelerate"), ("bitsandbytes", "bitsandbytes>=0.43")):
        try:
            __import__(modulo)
        except ImportError:
            faltan.append(paquete)
    if faltan:
        log("Instalando", faltan)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + faltan)


def json_de(texto):
    texto = re.sub(r"```(?:json)?", "", texto or "")
    pares = sorted([("[", "]"), ("{", "}")], key=lambda p: texto.find(p[0]) if p[0] in texto else len(texto))
    for abre, cierra in pares:
        i, j = texto.find(abre), texto.rfind(cierra)
        if i != -1 and j > i:
            try:
                return json.loads(texto[i:j + 1])
            except ValueError:
                continue
    return None


def normalizar(texto):
    return re.sub(r"\s+", " ", (texto or "").lower()).strip()


def es_examen(pregunta):
    """Partición estable: la misma pregunta siempre cae del mismo lado."""
    return int(hashlib.md5(normalizar(pregunta).encode()).hexdigest(), 16) % 100 < PORCENTAJE_EXAMEN


# ------------------------------------------------------------------
# El modelo (se puede reemplazar por uno falso para probar sin GPU)
# ------------------------------------------------------------------
def cargar_generador():
    instalar_si_falta()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    cuant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
    for nombre in MODELOS[2:] if RAPIDO else MODELOS:
        try:
            log(f"Cargando profesor {nombre} en 4 bits...")
            tok = AutoTokenizer.from_pretrained(nombre)
            tok.padding_side = "left"
            if tok.pad_token is None:
                tok.pad_token = tok.eos_token
            modelo = AutoModelForCausalLM.from_pretrained(nombre, quantization_config=cuant, device_map="auto")
            modelo.eval()
            break
        except Exception as e:                       # sin memoria, sin red...: prueba el siguiente
            log(f"No pude con {nombre}: {str(e)[:200]}")
            modelo = None
            torch.cuda.empty_cache()
    if modelo is None:
        raise SystemExit("No pude cargar ningún modelo profesor.")

    @torch.no_grad()
    def generar(lista_mensajes, max_nuevos=400, temperatura=0.0):
        salidas = []
        for i in range(0, len(lista_mensajes), LOTE):
            textos = [tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
                      for m in lista_mensajes[i:i + LOTE]]
            parte = tok(textos, return_tensors="pt", padding=True).to(modelo.device)
            extra = {"do_sample": True, "temperature": temperatura, "top_p": 0.95} if temperatura > 0 \
                else {"do_sample": False}
            out = modelo.generate(**parte, max_new_tokens=max_nuevos, pad_token_id=tok.pad_token_id, **extra)
            for fila in out[:, parte["input_ids"].shape[1]:]:
                salidas.append(tok.decode(fila, skip_special_tokens=True).strip())
        return salidas

    return generar, nombre


# ------------------------------------------------------------------
# Las tres fases
# ------------------------------------------------------------------
def inventar_preguntas(generar, temas):
    pedidos = [[{"role": "user", "content":
                 f"Escribe {PREGUNTAS_POR_TEMA} preguntas DISTINTAS que un estudiante de ingeniería de Colombia "
                 f"le haría a su asistente de IA sobre: {tema}.\nMezcla tipos: explicar un concepto, cómo hacer "
                 "algo paso a paso, comparar dos cosas, un ejercicio con respuesta concreta, un error común.\n"
                 'Responde SOLO un JSON: ["pregunta 1", "pregunta 2", ...]'}] for tema in temas]
    preguntas = []
    for tema, texto in zip(temas, generar(pedidos, max_nuevos=700, temperatura=0.8)):
        for p in json_de(texto) or []:
            if isinstance(p, str) and 10 < len(p) < 300:
                preguntas.append({"tema": tema, "pregunta": p.strip()})
    return preguntas


def responder(generar, preguntas):
    pedidos = [[{"role": "system", "content": SISTEMA_ARCHE}, {"role": "user", "content": p["pregunta"]}]
               for p in preguntas]
    for p, r in zip(preguntas, generar(pedidos, max_nuevos=450)):
        p["respuesta"] = r
    return [p for p in preguntas if 15 < len(p.get("respuesta", "")) < 2500]


def calificar(generar, items):
    pedidos = [[{"role": "system", "content": "Eres un examinador universitario muy estricto."},
                {"role": "user", "content":
                 f"Pregunta: {p['pregunta']}\n\nRespuesta:\n{p['respuesta']}\n\n"
                 "Califica de 1 a 10 qué tan CORRECTA, completa y clara es. Un error de hecho = máximo 4. "
                 "Relleno o vaguedad = máximo 6. Además da de 1 a 3 palabras o números CLAVE que cualquier "
                 "respuesta correcta a esta pregunta debe contener (cortos, que estén en la respuesta).\n"
                 'Responde SOLO un JSON: {"nota": 0, "claves": ["..."]}'}] for p in items]
    for p, texto in zip(items, generar(pedidos, max_nuevos=80)):
        d = json_de(texto)
        try:
            p["nota"] = int(float(d.get("nota", 0))) if isinstance(d, dict) else 0
        except (TypeError, ValueError):
            p["nota"] = 0
        claves = d.get("claves", []) if isinstance(d, dict) else []
        p["claves"] = [c for c in claves if isinstance(c, str) and c.strip()
                       and normalizar(c) in normalizar(p["respuesta"])][:3]
    return items


def main(generar=None):
    inicio = time.time()
    temas = list(dict.fromkeys([t for t in json.loads(TEMAS_JSON) if isinstance(t, str) and t.strip()] + TEMAS_BASE))
    if RAPIDO:
        temas = temas[:3]
    nombre = "simulado"
    if generar is None:
        generar, nombre = cargar_generador()
    log(f"Profesor {nombre}: {len(temas)} temas")
    os.makedirs(SALIDA, exist_ok=True)
    rutas = {n: os.path.join(SALIDA, f"{n}.jsonl") for n in ("profesor", "examen")}
    for r in rutas.values():
        open(r, "w").close()
    vistas, cuenta = set(), {"profesor": 0, "examen": 0, "descartadas": 0}

    for i in range(0, len(temas), 4):                          # de a 4 temas: guarda avance seguido
        if time.time() - inicio > TIEMPO_MAX:
            log("Se acabó el tiempo: guardo lo que llevo.")
            break
        grupo = temas[i:i + 4]
        preguntas = [p for p in inventar_preguntas(generar, grupo) if normalizar(p["pregunta"]) not in vistas]
        vistas.update(normalizar(p["pregunta"]) for p in preguntas)
        items = calificar(generar, responder(generar, preguntas))
        for p in items:
            if p["nota"] < NOTA_MINIMA:
                cuenta["descartadas"] += 1
                continue
            destino = "examen" if es_examen(p["pregunta"]) else "profesor"
            if destino == "examen" and not p["claves"]:
                destino = "profesor"                           # sin claves no sirve para calificar
            with open(rutas[destino], "a", encoding="utf-8") as f:
                f.write(json.dumps({k: p[k] for k in ("tema", "pregunta", "respuesta", "nota", "claves")},
                                   ensure_ascii=False) + "\n")
            cuenta[destino] += 1
        log(f"Temas {i + 1}-{i + len(grupo)}: {cuenta}")

    resumen = {"modelo": nombre, "temas": len(temas), **cuenta, "minutos": round((time.time() - inicio) / 60, 1)}
    with open(os.path.join(SALIDA, "resumen_profesor.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    log("Listo:", resumen)
    return resumen


if __name__ == "__main__":
    main()
