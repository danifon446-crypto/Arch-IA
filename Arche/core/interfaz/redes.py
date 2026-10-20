"""
redes.py
--------
Ubicacion: Arche/core/interfaz/redes.py

La parte de DATOS de la vista de redes neuronales (no dibuja nada):

  - lee las redes de verdad (las .pkl que entrena core/IA): su forma (entrada,
    capas ocultas, salida), su precision, cuantos ejemplos tiene cada
    intencion y cuantos ejemplos nuevos esperan un reentreno;
  - prueba una frase y devuelve la activacion REAL de las neuronas;
  - agrega ejemplos sin que escribas la intencion: la red decide si esta
    segura; si duda le pregunta a la nube; si nada encaja propone una
    intencion nueva (que tu confirmas);
  - reentrena una red o todas, en segundo plano.

Regla de oro: nada se inventa. Si una red no esta entrenada se dice; si la
nube no esta disponible se dice; un ejemplo agregado queda marcado «auto»
(configurable) y se puede deshacer.

Todo lo pesado (embeddings, nube, entrenamiento, leer conocimiento.json)
corre en hilos aparte: el hilo de la ventana solo lee snapshot() y estado.
"""

import collections
import json
import os
import pickle
import re
import threading
import time
import types

from . import ajustes, en_vivo

_lock = threading.RLock()
_mods = None

SIM_MIN_AUTO = 0.40          # parecido minimo (coseno) con algo conocido para agregar sin dudar
TOP_SUGERENCIAS = 3
MAX_EJEMPLOS_VISTA = 300     # ejemplos por intencion que guarda la vista (los mas recientes)
MAX_LOTE = 40


# ------------------------------------------------------------------ acceso perezoso a core/IA
def _ia():
    """Los modulos de core/IA, importados al primer uso (si falta alguno, la vista dice que no hay datos)."""
    global _mods
    if _mods is None:
        from core.IA import aprendizaje, catalogo, clasificador, clasificador_jerarquico, dominios
        _mods = types.SimpleNamespace(ap=aprendizaje, cat=catalogo, cl=clasificador, cj=clasificador_jerarquico, dom=dominios)
    return _mods


def disponible():
    try:
        _ia()
        return True
    except Exception:
        return False


def _np():
    import numpy
    return numpy


# ------------------------------------------------------------------ catalogo de redes
def catalogo_de_redes():
    """Todas las redes que PUEDE tener Arché, entrenadas o no:
    [{clave, nombre, nivel, tipo, dominio, padre, archivo, esperadas, trivial}]."""
    m = _ia()
    redes = [{"clave": "dominio", "nombre": "General · dominios", "nivel": 0, "tipo": "dominios", "dominio": None,
              "padre": None, "archivo": m.cj.ARCHIVO_MODELO_DOMINIO, "esperadas": sorted(m.dom.nombres_de_dominios()),
              "trivial": False}]
    for d in sorted(m.dom.nombres_de_dominios()):
        if m.dom.tiene_subdominios(d):
            subs = m.dom.subdominios_de(d)
            redes.append({"clave": f"{d} (subdominios)", "nombre": f"{d} · subdominios", "nivel": 1, "tipo": "subdominios",
                          "dominio": d, "padre": "dominio", "archivo": m.cj._archivo_subdominio(d),
                          "esperadas": sorted(subs), "trivial": False})
            for sub, ids in sorted(subs.items()):
                redes.append({"clave": f"{d}.{sub}", "nombre": f"{d} · {sub}", "nivel": 2, "tipo": "intenciones",
                              "dominio": d, "sub": sub, "padre": f"{d} (subdominios)",
                              "archivo": m.cj._archivo_submodelo_sub(d, sub), "esperadas": sorted(ids),
                              "trivial": len(ids) == 1})
        else:
            ids = m.dom.intenciones_de(d)
            redes.append({"clave": d, "nombre": d, "nivel": 1, "tipo": "intenciones", "dominio": d, "padre": "dominio",
                          "archivo": m.cj._archivo_submodelo(d), "esperadas": sorted(ids), "trivial": len(ids) == 1})
    redes.append({"clave": "clasica", "nombre": "Clásica · todas las intenciones", "nivel": 0, "tipo": "clasica",
                  "dominio": None, "padre": None, "archivo": m.cl.ARCHIVO_MODELO,
                  "esperadas": sorted(m.cat.POR_ID), "trivial": False})
    return redes


def _def_red(clave):
    for r in catalogo_de_redes():
        if r["clave"] == clave:
            return r
    return None


def redes_de_intencion(intencion):
    """Claves de las redes que aprenden de una intencion (para saber cuales reentrenar al agregarle ejemplos)."""
    m = _ia()
    claves = ["clasica", "dominio"]
    d = m.dom.dominio_de(intencion)
    if d is None:
        return ["clasica"]
    if m.dom.tiene_subdominios(d):
        sub = m.dom.subdominio_de(intencion)
        claves.append(f"{d} (subdominios)")
        if sub:
            claves.append(f"{d}.{sub}")
    else:
        claves.append(d)
    return claves


# ------------------------------------------------------------------ modelos (.pkl) con cache por fecha
_cache_modelos = {}


def _paquete(archivo):
    try:
        mt = os.path.getmtime(archivo)
    except OSError:
        return None
    c = _cache_modelos.get(archivo)
    if c and c[0] == mt:
        return c[1]
    try:
        with open(archivo, "rb") as f:
            p = pickle.load(f)
        paquete = {"modelo": p["modelo"], "metadata": p["metadata"], "codificador": p["codificador"]}
    except Exception:
        return None
    _cache_modelos[archivo] = (mt, paquete)
    return paquete


def _mlp(modelo):
    return modelo.named_steps["red"] if hasattr(modelo, "named_steps") else modelo


def _activar(nombre, a):
    np = _np()
    if nombre == "tanh":
        return np.tanh(a)
    if nombre == "logistic":
        return 1.0 / (1.0 + np.exp(-a))
    if nombre == "identity":
        return a
    return np.maximum(a, 0.0)


def _normalizar_vista(v):
    np = _np()
    a = np.abs(np.asarray(v, dtype=float))
    mx = float(a.max()) if a.size else 0.0
    return (a / mx).tolist() if mx > 0 else [0.0] * int(a.size)


def forma_de(clave):
    """Forma real de una red entrenada: {entrada, ocultas, salida, activacion, clases, pesos} o None."""
    d = _def_red(clave)
    if d is None:
        return None
    p = _paquete(d["archivo"])
    if p is None:
        return None
    try:
        red = _mlp(p["modelo"])
        coefs = red.coefs_
        return {"entrada": int(coefs[0].shape[0]), "ocultas": [int(c.shape[1]) for c in coefs[:-1]],
                "salida": int(coefs[-1].shape[1]) if coefs[-1].shape[1] > 1 else 2,
                "activacion": red.activation, "clases": [str(c) for c in p["codificador"].classes_],
                "coefs": coefs, "intercepts": red.intercepts_}
    except Exception:
        return None


def forward(clave, emb):
    """Pasada hacia adelante REAL: (clases, probabilidades, activaciones_ocultas_normalizadas, entrada_normalizada) o None."""
    d = _def_red(clave)
    if d is None:
        return None
    p = _paquete(d["archivo"])
    if p is None:
        return None
    try:
        if len(emb) != p["metadata"].get("dimension_embedding"):
            return None
        np = _np()
        modelo = p["modelo"]
        red = _mlp(modelo)
        a = np.asarray(emb, dtype=float)
        acts = []
        for w, b in zip(red.coefs_[:-1], red.intercepts_[:-1]):
            a = _activar(red.activation, a @ w + b)
            acts.append(_normalizar_vista(a))
        probs = [float(x) for x in modelo.predict_proba([emb])[0]]
        clases = [str(c) for c in p["codificador"].classes_]
        return clases, probs, acts, _normalizar_vista(emb)
    except Exception:
        return None


# ------------------------------------------------------------------ ejemplos (conocimiento.json) y snapshot
_dc = {"auto_recientes": [], "clave": None, "con_emb": collections.Counter(), "conteo": collections.Counter(),
       "por_intencion": {}, "total": 0}
_snap = {"ts": 0.0, "listo": False, "redes": [], "conteo": {}, "por_intencion": {}, "total": 0,
         "propuestas": 0, "error": ""}
_refrescando = False
_sucio = True


def _stat(ruta):
    try:
        st = os.stat(ruta)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _leer_datos():
    m = _ia()
    clave = _stat(m.ap.ARCHIVO)
    if clave != _dc["clave"]:
        datos = m.ap.cargar() if clave else []
        conteo, con_emb, por = collections.Counter(), collections.Counter(), {}
        auto_rec = []
        for d in datos:
            a = d.get("accion")
            if not a:
                continue
            if str(d.get("fuente") or "").startswith("auto"):
                auto_rec.append({"pregunta": d.get("pregunta", ""), "accion": a})
            conteo[a] += 1
            if d.get("embedding"):
                con_emb[a] += 1
            por.setdefault(a, []).append({"pregunta": d.get("pregunta", ""), "fuente": str(d.get("fuente") or ""),
                                          "auto": str(d.get("fuente") or "").startswith("auto")})
        for a in por:
            por[a] = por[a][-MAX_EJEMPLOS_VISTA:][::-1]            # los mas recientes primero
        _dc.update(clave=clave, conteo=conteo, con_emb=con_emb, por_intencion=por, total=len(datos), auto_recientes=auto_rec[-40:][::-1])
    return _dc


def _suma_por_etiqueta(d, contador):
    """Cuantos ejemplos corresponden a cada etiqueta de salida de la red d."""
    m = _ia()
    sal = {}
    for et in d["esperadas"]:
        if d["tipo"] == "dominios":
            sal[et] = sum(contador.get(i, 0) for i in m.dom.intenciones_de(et))
        elif d["tipo"] == "subdominios":
            sal[et] = sum(contador.get(i, 0) for i in m.dom.subdominios_de(d["dominio"]).get(et, ()))
        else:
            sal[et] = contador.get(et, 0)
    return sal


def _info(d, dc):
    """Estado de UNA red, con datos reales."""
    m = _ia()
    p = _paquete(d["archivo"])
    meta = p["metadata"] if p else None
    por_et = _suma_por_etiqueta(d, dc["conteo"])
    por_et_emb = _suma_por_etiqueta(d, dc["con_emb"])
    entrenadas = [str(c) for c in p["codificador"].classes_] if p else []
    etiquetas = []
    for et in d["esperadas"]:
        etiquetas.append({"id": et, "ejemplos": por_et.get(et, 0), "en_red": et in entrenadas})
    for et in entrenadas:                                          # clases que la red conoce y el catalogo ya no
        if et not in d["esperadas"]:
            etiquetas.append({"id": et, "ejemplos": 0, "en_red": True})
    suficientes = sum(1 for n in por_et_emb.values() if n >= m.cl.MIN_EJEMPLOS_POR_CLASE)
    entrenable = (not d["trivial"]) and suficientes >= m.cl.MIN_CLASES
    actuales = sum(por_et_emb.values())
    info = {"clave": d["clave"], "nombre": d["nombre"], "nivel": d["nivel"], "tipo": d["tipo"], "dominio": d["dominio"],
            "padre": d["padre"], "trivial": d["trivial"], "activa": bool(p) or d["trivial"], "entrenada": bool(p),
            "precision": float(meta["score"]) if meta else 0.0, "ejemplos_red": int(meta["n_ejemplos"]) if meta else 0,
            "ejemplos_hoy": int(actuales), "pendientes": max(0, int(actuales) - int(meta["n_ejemplos"])) if meta else 0,
            "entrenable": bool(entrenable), "etiquetas": etiquetas,
            "min_por_clase": m.cl.MIN_EJEMPLOS_POR_CLASE, "forma": None}
    f = forma_de(d["clave"]) if p else None
    if f:
        info["forma"] = {k: f[k] for k in ("entrada", "ocultas", "salida", "activacion", "clases")}
    return info


def refrescar():
    """Recalcula todo (bloqueante: usalo desde un hilo). Devuelve el snapshot."""
    global _snap, _sucio
    try:
        dc = _leer_datos()
        redes = [_info(d, dc) for d in catalogo_de_redes()]
        _snap = {"ts": time.time(), "listo": True, "redes": redes, "conteo": dict(dc["conteo"]),
                 "por_intencion": dc["por_intencion"], "total": dc["total"], "propuestas": len(leer_propuestas()),
                 "error": ""}
    except Exception as e:
        _snap = dict(_snap, ts=time.time(), listo=True, error=f"{type(e).__name__}: {e}")
    _sucio = False
    return _snap


def _refrescar_hilo():
    global _refrescando
    try:
        refrescar()
    finally:
        _refrescando = False


def snapshot(max_edad=4.0):
    """Lo ultimo que se sabe de las redes (no bloquea: si esta viejo, recalcula en otro hilo)."""
    global _refrescando
    if (_sucio or time.time() - _snap["ts"] > max_edad) and not _refrescando and disponible():
        _refrescando = True
        threading.Thread(target=_refrescar_hilo, name="arche-redes-lectura", daemon=True).start()
    return _snap


def invalidar():
    global _sucio
    _sucio = True


def red_info(clave):
    for r in snapshot()["redes"]:
        if r["clave"] == clave:
            return r
    return None


def clave_valida(clave):
    return any(r["clave"] == clave for r in snapshot()["redes"])


def primera_clave():
    """La red que se muestra por defecto: la general si esta entrenada; si no, la primera entrenada; si no, la general."""
    redes = snapshot()["redes"]
    for r in redes:
        if r["clave"] == "dominio" and r["entrenada"]:
            return "dominio"
    for r in redes:
        if r["entrenada"]:
            return r["clave"]
    return "dominio"


def ejemplos_de(intencion):
    return snapshot()["por_intencion"].get(intencion, [])


# ------------------------------------------------------------------ estado compartido con la ventana
estado = {
    "resultados": collections.deque(maxlen=30),       # lo que paso al agregar frases (el mas nuevo primero)
    "agregando": 0,                                    # frases en cola
    "prueba": None,                                    # ultima prueba de frase
    "probando": False,
    "entreno": {"corriendo": False, "hecho": 0, "total": 0, "actual": "", "inicio": 0.0, "fin": 0.0,
                "resultado": [], "mensaje": ""},
    "siguiente_id": 1,
}


def _hilo(nombre, fn, *args):
    t = threading.Thread(target=fn, args=args, name="arche-redes-" + nombre, daemon=True)
    t.start()
    return t


def _msg(texto, tipo="info"):
    try:
        en_vivo.avisar(texto, tipo)
    except Exception:
        pass


# ------------------------------------------------------------------ embeddings y parecido
def _embedding(frase):
    m = _ia()
    from core.IA.embeddings import calcular_embedding
    return calcular_embedding(m.ap._normalizar(frase))


_emb_cache = {"clave": None, "M": None, "etq": []}
_sem_cache = {"M": None, "etq": []}


def _matriz_conocidos():
    """(matriz de embeddings, intenciones) de todos los ejemplos guardados."""
    m = _ia()
    clave = _stat(m.ap.ARCHIVO)
    if clave != _emb_cache["clave"] or _emb_cache["M"] is None:
        np = _np()
        datos = m.ap.cargar() if clave else []
        filas, etq = [], []
        for d in datos:
            if d.get("embedding") and d.get("accion"):
                filas.append(d["embedding"])
                etq.append(d["accion"])
        _emb_cache.update(clave=clave, M=np.asarray(filas, dtype=np.float32) if filas else None, etq=etq)
    return _emb_cache["M"], _emb_cache["etq"]


def _matriz_semillas():
    """Embeddings de las frases de ejemplo del catalogo (una vez por sesion): sirven cuando una intencion aun no tiene ejemplos."""
    if _sem_cache["M"] is None:
        m = _ia()
        np = _np()
        filas, etq = [], []
        for e in m.cat.ENTRADAS:
            for s in list(e.get("semillas") or [])[:8]:
                try:
                    filas.append(_embedding(s))
                    etq.append(e["id"])
                except Exception:
                    break
        _sem_cache.update(M=np.asarray(filas, dtype=np.float32) if filas else np.zeros((0, 1), dtype=np.float32), etq=etq)
    return _sem_cache["M"], _sem_cache["etq"]


def _similitudes(emb):
    """[(intencion, parecido 0-1)] de mayor a menor: lo mas parecido entre ejemplos guardados y semillas del catalogo."""
    np = _np()
    v = np.asarray(emb, dtype=np.float32)
    mejor = {}
    for M, etq in (_matriz_conocidos(), _matriz_semillas()):
        if M is None or not len(etq) or M.shape[1] != v.shape[0]:
            continue
        for a, s in zip(etq, (M @ v).tolist()):
            if s > mejor.get(a, -1.0):
                mejor[a] = s
    return sorted(mejor.items(), key=lambda kv: -kv[1])


def _intenciones_en_dominio(d, emb):
    m = _ia()
    if m.dom.tiene_subdominios(d):
        ps = forward(f"{d} (subdominios)", emb)
        if not ps:
            return []
        out = []
        orden = sorted(range(len(ps[0])), key=lambda i: -ps[1][i])[:2]
        for i in orden:
            sub, p_s = ps[0][i], ps[1][i]
            ids = m.dom.subdominios_de(d).get(sub, ())
            if len(ids) == 1:
                out.append((next(iter(ids)), p_s))
            else:
                pi = forward(f"{d}.{sub}", emb)
                if pi:
                    out += [(l, p_s * p) for l, p in zip(pi[0], pi[1])]
        return out
    ids = m.dom.intenciones_de(d)
    if len(ids) == 1:
        return [(next(iter(ids)), 1.0)]
    pi = forward(d, emb)
    return list(zip(pi[0], pi[1])) if pi else []


def _probs_intenciones(emb):
    """({intencion: probabilidad}, origen). Jerarquica (dominio -> ... -> intencion); si no, la clasica; si no, vacio."""
    pd = forward("dominio", emb)
    if pd:
        joint = {}
        for i in sorted(range(len(pd[0])), key=lambda k: -pd[1][k])[:2]:
            if pd[1][i] < 0.05:
                continue
            for a, p in _intenciones_en_dominio(pd[0][i], emb):
                joint[a] = max(joint.get(a, 0.0), pd[1][i] * p)
        if joint:
            return joint, "jerárquica"
    pc = forward("clasica", emb)
    if pc:
        return dict(zip(pc[0], pc[1])), "clásica"
    return {}, None


def cadena(emb):
    """El camino de una frase por el arbol: [{clave, nombre, etiqueta, confianza, probs}] (solo redes entrenadas)."""
    m = _ia()
    pasos = []

    def paso(clave, nombre):
        f = forward(clave, emb)
        if not f:
            return None
        i = max(range(len(f[1])), key=lambda k: f[1][k])
        pasos.append({"clave": clave, "nombre": nombre, "etiqueta": f[0][i], "confianza": f[1][i],
                      "probs": sorted(zip(f[0], f[1]), key=lambda kv: -kv[1])})
        return f[0][i]

    d = paso("dominio", "dominio")
    if d is None:
        return pasos
    if m.dom.tiene_subdominios(d):
        sub = paso(f"{d} (subdominios)", f"{d} · subdominio")
        if sub is None:
            return pasos
        if len(m.dom.subdominios_de(d).get(sub, ())) > 1:
            paso(f"{d}.{sub}", f"{d}.{sub}")
    elif len(m.dom.intenciones_de(d)) > 1:
        paso(d, d)
    return pasos


# ------------------------------------------------------------------ probar una frase
def probar(frase, clave=None):
    """Prueba una frase (en un hilo aparte). La ventana lee estado['prueba']."""
    frase = (frase or "").strip()
    if not frase:
        return
    if estado["probando"]:
        return
    estado["probando"] = True
    _hilo("probar", _probar, frase, clave)


def _probar(frase, clave):
    try:
        emb = _embedding(frase)
        pasos = cadena(emb)
        clave = clave if clave and clave_valida(clave) else (pasos[-1]["clave"] if pasos else primera_clave())
        f = forward(clave, emb)
        res = {"frase": frase, "clave": clave, "ts": time.time(), "pasos": pasos, "error": ""}
        if f:
            clases, probs, acts, entrada = f
            res.update(clases=clases, probs=probs, ocultas=acts, entrada=entrada)
        else:
            res["error"] = "Esa red todavía no está entrenada: no tengo activaciones reales que mostrar."
        estado["prueba"] = res
    except Exception as e:
        estado["prueba"] = {"frase": frase, "clave": clave, "ts": time.time(), "pasos": [], "error": _explicar(e)}
    finally:
        estado["probando"] = False


def _explicar(e):
    t = f"{type(e).__name__}: {e}"
    if isinstance(e, ImportError):
        return "Falta una librería (sentence-transformers) para entender frases: " + str(e)
    return t


# ------------------------------------------------------------------ agregar ejemplos sin decir la intencion
def _propuestas_ruta():
    from core.rutas import DATABASE
    return os.path.join(DATABASE, "intenciones_propuestas.json")


def leer_propuestas():
    try:
        with open(_propuestas_ruta(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _guardar_propuestas(lista):
    ruta = _propuestas_ruta()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ruta)


def _nombre_intencion(texto):
    m = _ia()
    t = m.cat.normalizar(texto).replace(" ", "_")
    t = re.sub(r"[^a-z0-9_]", "", t).strip("_")[:40]
    return t if len(t) >= 3 else ""


def _nuevos_items(texto):
    frases = [f.strip(" \t•-") for f in re.split(r"[\n;]+", texto or "") if f.strip(" \t•-")]
    items = []
    for f in frases[:MAX_LOTE]:
        it = {"id": estado["siguiente_id"], "frase": f, "estado": "pensando", "intencion": "", "metodo": "",
              "opciones": [], "nueva": None, "mensaje": "Pensando…", "ts": time.time(), "auto": False,
              "pregunta_norm": "", "deshecho": False}
        estado["siguiente_id"] += 1
        estado["resultados"].appendleft(it)
        items.append(it)
    with _lock:
        estado["agregando"] += len(items)
    return items


def agregar(texto):
    """Agrega una o varias frases (una por linea o separadas por ';'). Decide la intencion solo."""
    items = _nuevos_items(texto)
    if items:
        _hilo("agregar", _procesar_lote, items)
    return len(items)


def agregar_a(texto, intencion):
    """Igual, pero TU eliges la intencion (no se pregunta nada a la red ni a la nube)."""
    if intencion not in _ia().cat.POR_ID:
        return 0
    items = _nuevos_items(texto)
    if items:
        _hilo("agregar-a", _procesar_lote, items, intencion)
    return len(items)


def _procesar_lote(items, forzada=None):
    afectadas = set()
    try:
        for it in items:
            try:
                if forzada:
                    _forzar(it, forzada)
                else:
                    _decidir_y_agregar(it)
            except Exception as e:
                it.update(estado="error", mensaje=_explicar(e))
            if it["estado"] == "agregada":
                afectadas.update(redes_de_intencion(it["intencion"]))
            with _lock:
                estado["agregando"] = max(0, estado["agregando"] - 1)
    finally:
        with _lock:
            estado["agregando"] = 0
        invalidar()
    if afectadas and ajustes.obtener("redes_entrenar") == "automatico":
        entrenar(sorted(afectadas))


def _forzar(it, intencion):
    m = _ia()
    norm = m.ap._normalizar(it["frase"])
    it["pregunta_norm"] = norm
    previo = next((d for d in m.ap.cargar() if d.get("pregunta") == norm), None)
    if previo and previo.get("accion") and previo["accion"] != intencion:
        it.update(estado="duplicada", intencion=previo["accion"],
                  mensaje=f"Ya estaba en «{previo['accion']}»; no la cambié (bórrala de ahí si quieres moverla).")
        return
    _guardar(it, intencion, "tu elección", auto=False)


def _analizar(frase):
    emb = _embedding(frase)
    probs, origen = _probs_intenciones(emb)
    red = sorted(probs.items(), key=lambda kv: -kv[1])
    sim = _similitudes(emb)
    return {"emb": emb, "red": red, "origen": origen, "sim": sim}


def _decidir_y_agregar(it):
    m = _ia()
    frase = it["frase"]
    norm = m.ap._normalizar(frase)
    it["pregunta_norm"] = norm
    previo = next((d for d in m.ap.cargar() if d.get("pregunta") == norm), None)
    if previo and previo.get("accion"):
        it.update(estado="duplicada", intencion=previo["accion"],
                  mensaje=f"Ya la tenía en «{previo['accion']}»; no la cambié.")
        return
    if m.cat.es_comando_fijo(frase):
        it.update(estado="error", mensaje="Es un comando fijo de Arché: no hace falta enseñarlo.")
        return

    an = _analizar(frase)
    umbral = ajustes.obtener("redes_umbral_auto") / 100.0
    red_top, red_conf = (an["red"][0] if an["red"] else (None, 0.0))
    sim_top, sim_val = (an["sim"][0] if an["sim"] else (None, 0.0))
    sim_de = dict(an["sim"])

    # 1) la red esta muy segura (y la frase se parece de verdad a algo conocido de esa intencion)
    if red_top and red_conf >= umbral and sim_de.get(red_top, 0.0) >= SIM_MIN_AUTO:
        _guardar(it, red_top, f"red {red_conf * 100:.0f}%", auto=True)
        return

    # candidatas para preguntar / mostrar
    cand = []
    for a, p in an["red"][:4]:
        cand.append({"intencion": a, "puntaje": p, "origen": "red"})
    for a, s in an["sim"][:4]:
        if a not in [c["intencion"] for c in cand]:
            cand.append({"intencion": a, "puntaje": s, "origen": "parecido"})

    # 2) duda: la nube opina
    nube = None
    if ajustes.obtener("redes_usar_nube"):
        nube = _preguntar_nube(frase, an, cand)
    if nube and nube.get("intencion") and nube["intencion"] != "NINGUNA":
        elegido = nube["intencion"]
        coincide = (elegido == red_top) or (red_top is None and elegido == sim_top)
        if coincide:
            _guardar(it, elegido, "red + nube" if red_top else "parecido + nube", auto=True)
            return
        opciones = [{"intencion": elegido, "puntaje": None, "origen": "nube"}]
        for c in cand:
            if c["intencion"] != elegido and len(opciones) < TOP_SUGERENCIAS:
                opciones.append(c)
        it.update(estado="elegir", opciones=opciones,
                  mensaje="La nube y mi red no coinciden: elige cuál es.")
        return

    # 3) ninguna encaja segun la nube -> intencion nueva (la confirmas tu)
    if nube and nube.get("intencion") == "NINGUNA" and ajustes.obtener("redes_proponer_nuevas"):
        nombre = _nombre_intencion(nube.get("nueva") or "") or _nombre_intencion(frase)[:24]
        it.update(estado="nueva", nueva={"nombre": nombre, "descripcion": (nube.get("descripcion") or "").strip()[:120]},
                  opciones=cand[:TOP_SUGERENCIAS],
                  mensaje="Ninguna intención encaja. ¿Creo una nueva?")
        return

    # 4) sin nube (o apagada) y sin seguridad: opciones para que elijas
    if cand:
        it.update(estado="elegir", opciones=cand[:TOP_SUGERENCIAS],
                  mensaje="No estoy segura" + ("" if nube is not None else " y no pude consultar la nube") + ": elige cuál es.")
    else:
        it.update(estado="error", mensaje="No encontré con qué compararla: aún no hay ejemplos ni red entrenada.")


def _guardar(it, intencion, metodo, auto):
    """Agrega el ejemplo de verdad (con aprendizaje.aprender, el mismo camino de siempre)."""
    m = _ia()
    marcar = ajustes.obtener("redes_marcar_auto")
    fuente = "auto" if (auto and marcar) else ("manual" if not auto else "interfaz")
    original = m.ap.UMBRAL_REENTRENO
    if ajustes.obtener("redes_entrenar") != "sistema":
        m.ap.UMBRAL_REENTRENO = float("inf")           # el reentreno lo decides tu (boton) o se hace al final del lote
    try:
        m.ap.aprender(it["frase"], intencion, "", fuente=fuente)
    finally:
        m.ap.UMBRAL_REENTRENO = original
    it.update(estado="agregada", intencion=intencion, metodo=metodo, auto=(fuente == "auto"), opciones=[],
              mensaje=f"Agregada a «{intencion}» ({metodo})")
    invalidar()


def _preguntar_nube(frase, an, cand):
    """Pregunta a la nube cual intencion es. Devuelve {intencion, nueva, descripcion} o None si no se pudo."""
    m = _ia()
    try:
        from core.IA import nube
        if not nube.disponible():
            return None
        ids = []
        for a, _p in an["red"][:6]:
            if a not in ids:
                ids.append(a)
        for a, _s in an["sim"][:10]:
            if a not in ids:
                ids.append(a)
        for c in cand:
            if c["intencion"] not in ids:
                ids.append(c["intencion"])
        ids = [i for i in ids if i in m.cat.POR_ID][:14]
        lista = "\n".join(f"- {i}: {m.cat.descripcion_de(i)}" for i in ids)
        prompt = (f'Frase del usuario: "{frase}"\n\nIntenciones posibles (id: qué hace):\n{lista}\n\n'
                  'Responde SOLO con JSON en una línea: {"intencion": "<id exacto de la lista o NINGUNA>", '
                  '"nueva": "<si es NINGUNA: nombre_en_snake_case sugerido>", "descripcion": "<si es NINGUNA: qué haría, en pocas palabras>"}. '
                  'Elige NINGUNA solo si de verdad ninguna intención de la lista encaja.')
        texto = nube.responder([{"role": "user", "content": prompt}],
                               sistema="Eres el clasificador de intenciones de un asistente personal llamado Arché. Respondes solo JSON.",
                               max_tokens=200, temperature=0)
        mm = re.search(r"\{.*\}", texto, re.S)
        if not mm:
            return None
        datos = json.loads(mm.group(0))
        inte = str(datos.get("intencion", "")).strip()
        if inte != "NINGUNA" and inte not in m.cat.POR_ID:
            return None
        return {"intencion": inte, "nueva": str(datos.get("nueva", "")), "descripcion": str(datos.get("descripcion", ""))}
    except Exception:
        return None


def _buscar(item_id):
    for it in estado["resultados"]:
        if it["id"] == item_id:
            return it
    return None


def elegir(item_id, intencion):
    """Tu elegiste la intencion de una frase que Arché dudaba."""
    it = _buscar(item_id)
    if not it or it["estado"] not in ("elegir", "nueva") or intencion not in _ia().cat.POR_ID:
        return
    it.update(estado="pensando", mensaje="Agregando…")
    _hilo("elegir", _elegir, it, intencion)


def _elegir(it, intencion):
    try:
        _guardar(it, intencion, "tu elección", auto=False)
        if ajustes.obtener("redes_entrenar") == "automatico":
            entrenar(redes_de_intencion(intencion))
    except Exception as e:
        it.update(estado="error", mensaje=_explicar(e))


def proponer(item_id):
    """Confirmas la intencion nueva: queda como propuesta (con la frase) para crearle su accion."""
    it = _buscar(item_id)
    if not it or it["estado"] != "nueva" or not it.get("nueva"):
        return
    nombre = it["nueva"]["nombre"] or "intencion_nueva"
    with _lock:
        lista = leer_propuestas()
        p = next((x for x in lista if x.get("nombre") == nombre), None)
        if p is None:
            p = {"nombre": nombre, "descripcion": it["nueva"].get("descripcion", ""), "frases": [], "estado": "pendiente",
                 "creada": time.strftime("%Y-%m-%d %H:%M")}
            lista.append(p)
        if it["frase"] not in p["frases"]:
            p["frases"].append(it["frase"])
        _guardar_propuestas(lista)
    it.update(estado="propuesta", mensaje=f"Guardé la propuesta «{nombre}» con tu frase. Le falta su acción para funcionar.")
    invalidar()


def descartar(item_id):
    it = _buscar(item_id)
    if it and it["estado"] in ("elegir", "nueva", "error", "duplicada"):
        it.update(estado="descartada", mensaje="Descartada.")


def deshacer(item_id):
    """Quita un ejemplo que acaba de agregarse (por si Arché se equivoco)."""
    it = _buscar(item_id)
    if not it or it["estado"] != "agregada" or it.get("deshecho"):
        return
    _hilo("deshacer", _quitar, it["pregunta_norm"], it["intencion"], it)


def quitar_ejemplo(pregunta_norm, intencion):
    _hilo("quitar", _quitar, pregunta_norm, intencion, None)


def _quitar(pregunta_norm, intencion, it):
    m = _ia()
    try:
        with m.ap._lock:
            datos = m.ap.cargar(estricto=True)
            nuevos = [d for d in datos if not (d.get("pregunta") == pregunta_norm and d.get("accion") == intencion)]
            if len(nuevos) != len(datos):
                m.ap.guardar(nuevos)
        if it is not None:
            it.update(estado="deshecha", deshecho=True, mensaje="Deshecho: ya no está en los ejemplos.")
    except Exception as e:
        if it is not None:
            it["mensaje"] = "No pude deshacerlo: " + _explicar(e)
    invalidar()


def recientes_auto(n=5):
    """Los ultimos ejemplos que Arché clasifico sola y nadie ha revisado: [{pregunta, accion}]."""
    snapshot()
    return list(_dc.get("auto_recientes", []))[:n]


def revisar_ejemplo(pregunta_norm, intencion, bueno):
    """Revision rapida: bueno=True lo da por correcto (deja de marcarse «auto»); False lo borra de los ejemplos."""
    if not bueno:
        quitar_ejemplo(pregunta_norm, intencion)
        return
    _hilo("revisar", _marcar_revisado, pregunta_norm, intencion)


def _marcar_revisado(pregunta_norm, intencion):
    m = _ia()
    try:
        with m.ap._lock:
            datos = m.ap.cargar(estricto=True)
            for d in datos:
                if d.get("pregunta") == pregunta_norm and d.get("accion") == intencion:
                    d["fuente"] = "revisado"
            m.ap.guardar(datos)
    except Exception:
        pass
    invalidar()


# ------------------------------------------------------------------ entrenar
def entrenar(claves=None):
    """Reentrena en un hilo aparte. claves: lista de claves, una clave, o None/'todas' para todas las entrenables."""
    e = estado["entreno"]
    if e["corriendo"]:
        return False
    if isinstance(claves, str) and claves != "todas":
        claves = [claves]
    if claves in (None, "todas"):
        claves = [r["clave"] for r in snapshot()["redes"] if r["entrenable"]]
        todas = True
    else:
        todas = False
    e.update(corriendo=True, hecho=0, total=len(claves), actual="", inicio=time.time(), fin=0.0, resultado=[], mensaje="")
    if not claves:
        e.update(corriendo=False, fin=time.time(), mensaje="Ninguna red tiene ejemplos suficientes todavía (mínimo 5 por intención en 2 o más).")
        return False
    _hilo("entrenar", _entrenar, list(claves), todas)
    return True


def _datos_para(d, datos):
    m = _ia()
    if d["tipo"] == "dominios":
        return m.cj._preparar_dataset_dominio(datos)
    if d["tipo"] == "subdominios":
        return m.cj._preparar_dataset_subdominio(datos, d["dominio"])
    if d["tipo"] == "clasica":
        return None
    if d.get("sub"):
        return m.cj._preparar_dataset_intencion_en_subdominio(datos, d["sub"])
    return m.cj._preparar_dataset_intencion(datos, d["dominio"])


def _entrenar(claves, todas):
    e = estado["entreno"]
    m = _ia()
    try:
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        datos = m.ap.cargar()
        for i, clave in enumerate(claves):
            d = _def_red(clave)
            e["actual"] = d["nombre"] if d else clave
            e["hecho"] = i
            antes = (red_info(clave) or {}).get("precision", 0.0) if (red_info(clave) or {}).get("entrenada") else None
            try:
                if d is None or d["trivial"]:
                    ok = False
                elif d["tipo"] == "clasica":
                    ok = bool(m.cl.entrenar(silencioso=True))
                else:
                    X, y = _datos_para(d, datos)
                    ok = bool(m.cj._entrenar_una_red(X, y, d["archivo"], d["nombre"], True))
            except Exception:
                ok = False
            paq = _paquete(d["archivo"]) if d else None
            despues = float(paq["metadata"]["score"]) if paq else None
            e["resultado"].append({"clave": clave, "nombre": d["nombre"] if d else clave, "ok": ok, "antes": antes, "despues": despues})
        e["hecho"] = len(claves)
        if todas:
            try:
                with open(m.ap.ARCHIVO_META, "w", encoding="utf-8") as f:
                    json.dump({"pendientes": 0}, f)
            except OSError:
                pass
        mejoradas = sum(1 for r in e["resultado"] if r["ok"])
        e["mensaje"] = (f"Listo: {mejoradas} red(es) actualizada(s)"
                        + (f", {len(claves) - mejoradas} sin cambios (la nueva no superaba a la actual, o faltan ejemplos)." if len(claves) > mejoradas else "."))
        _msg(e["mensaje"], "exito" if mejoradas else "info")
    except Exception as ex:
        e["mensaje"] = "El entrenamiento falló: " + _explicar(ex)
        _msg(e["mensaje"], "error")
    finally:
        e["corriendo"] = False
        e["fin"] = time.time()
        invalidar()
