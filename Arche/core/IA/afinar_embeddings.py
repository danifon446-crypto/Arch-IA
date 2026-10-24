"""
afinar_embeddings.py
--------------------
Ajusta ("afina") el modelo de embeddings con TUS ejemplos -- la idea de
SetFit (Tunstall et al., 2022): con pocos ejemplos por intención, lo que
más sube la precisión es enseñarle al propio modelo de embeddings que
las frases de la MISMA intención deben quedar juntas y las de
intenciones DISTINTAS, separadas.

El modelo de fábrica no sabe que para ti "pon el examen" y "detén el
examen" son órdenes opuestas; para él son casi la misma frase. Después
de afinarlo, sí lo sabe -- y eso mejora a la vez el vecino más cercano
y todas las redes, porque todas trabajan sobre esos vectores.

Cómo lo hace (sin trucos):
  1. Separa el 20% de tus ejemplos para EXAMINAR (el modelo nunca los ve
     mientras aprende).
  2. Mide cuánto acierta el modelo actual con ese 20%.
  3. Entrena con el otro 80% (aprendizaje contrastivo supervisado: en
     cada paso toma varias intenciones con varias frases cada una, y
     acerca las de la misma intención y aleja las demás).
  4. Vuelve a medir con el 20%. SOLO si mejora, lo vuelve a entrenar con
     el 100% de los ejemplos y lo guarda en core/IA/modelo_afinado/.
     Si no mejora, no guarda nada.

Uso (desde la carpeta Arche, con Arché cerrado):
    python -m core.IA.afinar_embeddings            (unos 10-30 min en CPU)
    python -m core.IA.afinar_embeddings 600        (más pasos de entrenamiento)

Después, para empezar a usarlo:
    python -m core.IA.recalcular_embeddings usar afinado

Cuando agregues muchos ejemplos nuevos, vuelve a correrlo: parte siempre
del modelo BASE (no del afinado), así no se acumulan errores.

Requiere: pip install sentence-transformers  (ya trae torch)
"""

import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

import numpy as np

from core.IA import embeddings as emb

PASOS = 300                 # pasos de entrenamiento
INTENCIONES_POR_PASO = 16   # cuántas intenciones distintas por paso
FRASES_POR_INTENCION = 4    # cuántas frases de cada una
TASA_APRENDIZAJE = 2e-5
TEMPERATURA = 0.05          # qué tan "exigente" es la separación
MEJORA_MINIMA = 0.005       # medio punto: menos que eso es ruido
SEMILLA = 42


def _base():
    """El modelo del que se parte: el elegido en la config, o el que se
    usó de base si lo actual ya es el afinado."""
    cfg = emb.leer_config()
    if cfg["nombre"] != "afinado":
        return cfg["nombre"], cfg["modelo"], cfg["prefijo"]
    info_ruta = os.path.join(emb.CARPETA_AFINADO, "arche_info.json")
    with open(info_ruta, "r", encoding="utf-8") as f:
        info = json.load(f)
    return info["base_nombre"], info["base_modelo"], info["prefijo"]


def _ejemplos():
    from core.IA import aprendizaje
    datos = [d for d in aprendizaje.cargar() if d.get("pregunta") and d.get("accion")]
    frases = [d["pregunta"] for d in datos]
    y = np.array([d["accion"] for d in datos])
    return frases, y


def _separar(y, proporcion=0.2):
    """Índices (entrenar, examinar). Solo se examinan intenciones con 5+
    ejemplos; las más chicas van enteras a entrenar."""
    rng = random.Random(SEMILLA)
    por_clase = defaultdict(list)
    for i, c in enumerate(y):
        por_clase[c].append(i)
    tr, te = [], []
    for c, idx in por_clase.items():
        rng.shuffle(idx)
        if len(idx) >= 5:
            k = max(1, int(round(len(idx) * proporcion)))
            te += idx[:k]
            tr += idx[k:]
        else:
            tr += idx
    return np.array(sorted(tr)), np.array(sorted(te))


def _medir(modelo, prefijo, frases, y, tr, te):
    """(acierto del vecino más cercano, acierto de una red rápida) sobre el
    20% de examen, usando solo el 80% de entrenamiento como referencia."""
    from core.IA.clasificador import armar_entrada, _nuevo_lineal
    E = emb.calcular_embeddings(frases, modelo=modelo, prefijo=prefijo)
    S = E[te] @ E[tr].T
    aciertos = y[tr][S.argmax(axis=1)] == y[te]
    vecino = float(aciertos.mean())
    _medir.ultimo = (S.max(axis=1), aciertos)   # para calibrar el umbral con el examen
    X = np.array([armar_entrada(e, f) for e, f in zip(E, frases)])
    lineal = _nuevo_lineal().fit(X[tr], y[tr])
    red = float((lineal.predict(X[te]) == y[te]).mean())
    return vecino, red


def _entrenar(modelo, prefijo, frases, y, indices, pasos, mostrar=True):
    import torch
    import torch.nn.functional as F

    rng = random.Random(SEMILLA)
    torch.manual_seed(SEMILLA)
    por_clase = defaultdict(list)
    for i in indices:
        por_clase[y[i]].append(i)
    clases = [c for c, idx in por_clase.items() if len(idx) >= 2]
    if len(clases) < 2:
        raise RuntimeError("se necesitan al menos 2 intenciones con 2+ ejemplos")

    dispositivo = modelo.device
    modelo.train()
    optimizador = torch.optim.AdamW(modelo.parameters(), lr=TASA_APRENDIZAJE)
    inicio = time.time()

    for paso in range(1, pasos + 1):
        elegidas = rng.sample(clases, min(INTENCIONES_POR_PASO, len(clases)))
        textos, etiquetas = [], []
        for k, c in enumerate(elegidas):
            idx = por_clase[c]
            muestra = rng.sample(idx, FRASES_POR_INTENCION) if len(idx) >= FRASES_POR_INTENCION \
                else [rng.choice(idx) for _ in range(FRASES_POR_INTENCION)]
            textos += [prefijo + frases[i] for i in muestra]
            etiquetas += [k] * len(muestra)

        # 'preprocess' en sentence-transformers nuevos, 'tokenize' en los viejos
        preparar = getattr(modelo, "preprocess", None) or modelo.tokenize
        entrada = preparar(textos)
        entrada = {k: (v.to(dispositivo) if hasattr(v, "to") else v) for k, v in entrada.items()}
        z = F.normalize(modelo(entrada)["sentence_embedding"], dim=-1)

        # Pérdida contrastiva supervisada (SupCon): para cada frase, que
        # las de su misma intención sean las más parecidas del lote.
        e = torch.tensor(etiquetas, device=dispositivo)
        sim = z @ z.T / TEMPERATURA
        n = len(etiquetas)
        no_yo = ~torch.eye(n, dtype=torch.bool, device=dispositivo)
        positivos = (e[:, None] == e[None, :]) & no_yo
        sim = sim.masked_fill(~no_yo, -1e9)
        log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
        perdida = -(log_prob * positivos).sum(1) / positivos.sum(1).clamp(min=1)
        perdida = perdida.mean()

        optimizador.zero_grad()
        perdida.backward()
        torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
        optimizador.step()

        if mostrar and (paso % 25 == 0 or paso == 1):
            restante = (time.time() - inicio) / paso * (pasos - paso)
            print(f"   paso {paso}/{pasos}  pérdida {perdida.item():.3f}  (faltan ~{restante / 60:.0f} min)")

    modelo.eval()
    return modelo


def afinar(pasos=PASOS):
    base_nombre, base_modelo, prefijo = _base()
    frases, y = _ejemplos()
    conteo = Counter(y)
    if len(frases) < 100 or sum(1 for n in conteo.values() if n >= 5) < 5:
        print("Arché: todavía hay muy pocos ejemplos para afinar el modelo "
              "(se necesitan 100+ y al menos 5 intenciones con 5+ ejemplos).")
        return False

    tr, te = _separar(y)
    print(f"Arché: afinando '{base_nombre}' con {len(frases)} ejemplos de {len(conteo)} intenciones.")
    print(f"       Entreno con {len(tr)} y examino con {len(te)} que el modelo no verá.")

    modelo = emb.cargar_modelo_por_nombre(base_modelo)
    vecino_antes, red_antes = _medir(modelo, prefijo, frases, y, tr, te)
    print(f"   ANTES:   vecino {vecino_antes:.1%} | red rápida {red_antes:.1%}")

    _entrenar(modelo, prefijo, frases, y, tr, pasos)
    vecino_despues, red_despues = _medir(modelo, prefijo, frases, y, tr, te)
    print(f"   DESPUÉS: vecino {vecino_despues:.1%} | red rápida {red_despues:.1%}")

    # Cuentan las DOS cosas: el vecino más cercano es lo que Arché usa en
    # vivo (paso 3 de aprendizaje.resolver) y la red rápida aproxima las
    # redes. Se acepta si una mejora claramente y la otra no empeora.
    mejora_red = red_despues - red_antes
    mejora_vecino = vecino_despues - vecino_antes
    mejora_clara = mejora_red >= MEJORA_MINIMA or mejora_vecino >= 4 * MEJORA_MINIMA
    sin_empeorar = mejora_red >= -MEJORA_MINIMA and mejora_vecino >= -0.01
    if not (mejora_clara and sin_empeorar):
        print("Arché: el modelo afinado NO mejoró lo suficiente con los ejemplos de examen. "
              "No guardo nada (sigues con el de siempre).")
        return False

    # Umbral de parecido calibrado con el EXAMEN (frases que el modelo no
    # vio). Después se reentrena con el 100% y ya no habría frases nuevas
    # con que medirlo honestamente.
    from core.IA.recalcular_embeddings import calibrar_umbral
    umbral_examen = calibrar_umbral(*_medir.ultimo)

    print(f"Arché: mejoró (red {mejora_red * 100:+.1f}, vecino {mejora_vecino * 100:+.1f} puntos). "
          f"Lo vuelvo a entrenar con el 100% de los ejemplos...")
    modelo = emb.cargar_modelo_por_nombre(base_modelo)
    _entrenar(modelo, prefijo, frases, y, np.arange(len(frases)), pasos)

    os.makedirs(emb.CARPETA_AFINADO, exist_ok=True)
    modelo.save(emb.CARPETA_AFINADO)
    with open(os.path.join(emb.CARPETA_AFINADO, "arche_info.json"), "w", encoding="utf-8") as f:
        json.dump({
            "base_nombre": base_nombre, "base_modelo": base_modelo, "prefijo": prefijo,
            "fecha": time.strftime("%Y-%m-%d %H:%M"), "pasos": pasos, "n_ejemplos": len(frases),
            "examen_antes": {"vecino": vecino_antes, "red": red_antes},
            "examen_despues": {"vecino": vecino_despues, "red": red_despues},
            "umbral_semantico": umbral_examen,
        }, f, ensure_ascii=False, indent=2)

    print(f"Arché: modelo afinado guardado en {emb.CARPETA_AFINADO}")
    print("       Para usarlo:  python -m core.IA.recalcular_embeddings usar afinado")
    return True


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    pasos = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else PASOS
    afinar(pasos)
