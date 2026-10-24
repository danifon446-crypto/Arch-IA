"""
web
---
Ubicacion: Arche/core/interfaz/web/

La interfaz nueva de Arché: una pagina (index.html + estilo.css + app.js) que
Arché sirve SOLO en tu computador (127.0.0.1) y que se abre en su propia
ventana con pywebview. Si pywebview no esta instalado, se abre en Edge/Chrome
en modo aplicacion (sin barra de direcciones) o en el navegador normal.

Como se conecta con Arché (sin caminos raros):
  - lo que escribes o los botones que tocas llegan a entrada.enviar(), la misma
    puerta que usa la consola, asi que main.py no cambia;
  - lo que Arché responde se lee de la consola (cada linea "Arché: ...");
  - los ajustes son los mismos de ajustes.py (config.json): la ventana clasica
    y la web comparten temas, chat, mascota, etc.

Seguridad: solo escucha en 127.0.0.1, cada vez con un puerto y una llave nueva;
sin la llave la API no responde. Nunca ejecuta codigo que venga de la pagina:
solo manda frases a Arché o cambia ajustes validados.

Instalar la ventana propia (opcional, recomendado):   pip install pywebview
"""

import collections
import datetime
import hmac
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import ajustes, datos, en_vivo, entrada, personalizacion, tema

try:
    from core.rutas import DATABASE
except Exception:
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Database")

AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA_DATOS = os.path.join(DATABASE, "web")
ARCHIVO_HOY = os.path.join(CARPETA_DATOS, "hoy.json")          # pendientes y gastos
ARCHIVO_CHAT = os.path.join(CARPETA_DATOS, "chat.json")        # ultimos mensajes (para verlos al reabrir)
CARPETA_NOTAS = os.path.join(DATABASE, "Notas")                 # las mismas notas de notas.py
ARCHIVO_CSS_PROPIO = os.path.join(CARPETA_DATOS, "mi_estilo.css")   # tu CSS (se edita en Ajustes)
CARPETA_EXPORTES = os.path.join(CARPETA_DATOS, "exportes")

_servidor = None
_hilo = None
_llave = ""
_puerto = 0
_proceso = None                 # la ventana de pywebview (proceso aparte)
_ultimo_contacto = 0.0          # ultima vez que la pagina pidio algo
_lock = threading.RLock()

ESTATICOS = {"/": ("index.html", "text/html; charset=utf-8"),
             "/index.html": ("index.html", "text/html; charset=utf-8"),
             "/estilo.css": ("estilo.css", "text/css; charset=utf-8"),
             "/app.js": ("app.js", "application/javascript; charset=utf-8"),
             "/mascota.js": ("mascota.js", "application/javascript; charset=utf-8")}


# =====================================================================
# Chat: lo que dices y lo que Arché contesta (todas sus lineas, no solo la ultima)
# =====================================================================
_chat = collections.deque(maxlen=300)
_id_msg = 0
_ultima_orden = ""
_ultima_orden_ts = 0.0
_ult_arche_ts = 0.0
_pensando_desde = 0.0
_ecos = collections.deque(maxlen=20)       # ordenes mandadas desde la pagina: la consola las repite
_RE_ARCHE = re.compile(r"^\s*Arch[eé]\s*:\s*")
_RE_TU = re.compile(r"^\s*(?:T[uú]\s*:\s*)+")
_RE_RUIDO = re.compile(r"^\s*(\[[\w\- ]+\]|Traceback|  File \"|DEBUG|INFO:|WARNING:)")


def _nuevo_msg(quien, texto, origen="", fondo=False):
    global _id_msg
    with _lock:
        if fondo and _chat and _chat[-1].get("fondo") and _chat[-1]["t"] == texto:
            return                                   # el mismo aviso repetido seguido: una sola vez
        _id_msg += 1
        m = {"id": _id_msg, "q": quien, "t": texto, "ts": time.time(), "origen": origen}
        if fondo:
            m["fondo"] = True
        _chat.append(m)


def _al_recibir(texto, origen):
    global _ultima_orden, _pensando_desde, _ultima_orden_ts
    with _lock:
        _ultima_orden = str(texto).strip()
        _ultima_orden_ts = time.time()
        _pensando_desde = time.time()
    _nuevo_msg("tu", str(texto), origen)


def _linea_de_consola(linea):
    """Cada linea completa que Arché imprime pasa por aqui."""
    global _ult_arche_ts, _pensando_desde, _id_msg
    linea = linea.rstrip("\r")
    era_tuya = bool(_RE_TU.match(linea))
    linea = _RE_TU.sub("", linea)            # el «Tú: » que queda pegado del input()
    if not linea.strip():
        return
    ahora = time.time()
    m = _RE_ARCHE.match(linea)
    if not m and (era_tuya or linea.strip() in _ecos):
        try:
            _ecos.remove(linea.strip())      # el eco de lo que mandaste (desde aqui o el celular)
        except ValueError:
            pass
        return
    if m:
        texto = linea[m.end():].strip()
        if texto:
            # lo que no es respuesta a una orden tuya (hilos de fondo, arranque) se marca como aviso de fondo
            desde_orden = time.time() - _ultima_orden_ts
            reciente = bool(_pensando_desde) or desde_orden < 120
            otro_hilo = threading.current_thread() is not threading.main_thread()
            fondo = not reciente or (otro_hilo and desde_orden > 20)
            _nuevo_msg("arche", texto, fondo=fondo)
            _ult_arche_ts = ahora
            _pensando_desde = 0.0
        return
    if _RE_RUIDO.match(linea):
        return
    # continuacion de una respuesta (listas, tablas...): se pega al ultimo mensaje de Arché
    with _lock:
        if _chat and _chat[-1]["q"] == "arche" and ahora - _ult_arche_ts < 4:
            _chat[-1]["t"] += "\n" + linea.rstrip()
            _id_msg += 1
            _chat[-1]["id"] = _id_msg      # que la pagina sepa que cambio
            _ult_arche_ts = ahora


class _Espejo:
    """Envuelve sys.stdout: escribe igual que siempre y ademas le pasa las lineas al chat."""

    def __init__(self, real):
        self._real = real
        self._buf = ""

    def write(self, s):
        try:
            n = self._real.write(s)
        except Exception:
            n = len(s)
        try:
            self._buf += s
            if len(self._buf) > 20000:
                self._buf = self._buf[-20000:]
            while "\n" in self._buf:
                linea, self._buf = self._buf.split("\n", 1)
                _linea_de_consola(linea)
        except Exception:
            pass
        return n

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass

    def __getattr__(self, nombre):            # encoding, isatty, fileno... los del real
        return getattr(self._real, nombre)


def _instalar_espejo():
    if not isinstance(sys.stdout, _Espejo):
        sys.stdout = _Espejo(sys.stdout)


def _cargar_chat():
    try:
        with open(ARCHIVO_CHAT, "r", encoding="utf-8") as f:
            viejos = json.load(f)
        global _id_msg
        for m in viejos[-150:]:
            _id_msg += 1
            m["id"] = _id_msg
            m["viejo"] = True
            _chat.append(m)
    except Exception:
        pass


def _guardar_chat():
    try:
        os.makedirs(CARPETA_DATOS, exist_ok=True)
        with _lock:
            lista = [{k: m[k] for k in ("q", "t", "ts", "fondo") if k in m} for m in list(_chat)[-150:]]
        tmp = ARCHIVO_CHAT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False)
        os.replace(tmp, ARCHIVO_CHAT)
    except Exception:
        pass


def limpiar_chat():
    with _lock:
        _chat.clear()
    _guardar_chat()


# =====================================================================
# Pendientes, gastos y notas (lo del Inicio)
# =====================================================================
def _leer_hoy():
    try:
        with open(ARCHIVO_HOY, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("pendientes", [])
            d.setdefault("gastos", [])
            return d
    except Exception:
        pass
    return {"pendientes": [], "gastos": []}


def _guardar_hoy(d):
    os.makedirs(CARPETA_DATOS, exist_ok=True)
    tmp = ARCHIVO_HOY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, ARCHIVO_HOY)


def _sig_id(lista):
    return max([x.get("id", 0) for x in lista] + [0]) + 1


def pendiente(accion, id_=None, texto=""):
    with _lock:
        d = _leer_hoy()
        p = d["pendientes"]
        if accion == "agregar" and str(texto).strip():
            p.append({"id": _sig_id(p), "texto": str(texto).strip()[:200], "hecho": False, "ts": time.time()})
        elif accion == "marcar":
            for x in p:
                if x["id"] == id_:
                    x["hecho"] = not x.get("hecho")
        elif accion == "borrar":
            d["pendientes"] = [x for x in p if x["id"] != id_]
        elif accion == "limpiar_hechos":
            d["pendientes"] = [x for x in p if not x.get("hecho")]
        _guardar_hoy(d)
        return d["pendientes"]


def gasto(accion, id_=None, concepto="", valor=0):
    with _lock:
        d = _leer_hoy()
        g = d["gastos"]
        if accion == "agregar":
            try:
                v = float(str(valor).replace(".", "").replace(",", ".")) if isinstance(valor, str) else float(valor)
            except Exception:
                v = 0
            if v > 0:
                g.append({"id": _sig_id(g), "fecha": datetime.date.today().isoformat(),
                          "concepto": str(concepto).strip()[:60] or "gasto", "valor": round(v, 2)})
        elif accion == "borrar":
            d["gastos"] = [x for x in g if x["id"] != id_]
        d["gastos"] = d["gastos"][-500:]
        _guardar_hoy(d)
        return d["gastos"]


def habito(accion, id_=None, nombre=""):
    """Habitos de cada dia: agregar, marcar (hoy), borrar, renombrar."""
    with _lock:
        d = _leer_hoy()
        h = d.setdefault("habitos", [])
        hoy = datetime.date.today().isoformat()
        if accion == "agregar" and str(nombre).strip():
            h.append({"id": _sig_id(h), "nombre": str(nombre).strip()[:50], "hechos": []})
        for x in h:
            if x["id"] != id_:
                continue
            if accion == "marcar":
                x["hechos"] = [f for f in x["hechos"] if f != hoy] if hoy in x["hechos"] else (x["hechos"] + [hoy])[-400:]
            elif accion == "renombrar" and str(nombre).strip():
                x["nombre"] = str(nombre).strip()[:50]
        if accion == "borrar":
            d["habitos"] = [x for x in h if x["id"] != id_]
        _guardar_hoy(d)
        return _resumen_habitos(d["habitos"])


def _resumen_habitos(habitos):
    hoy = datetime.date.today()
    sal = []
    for x in habitos or []:
        hechos = set(x.get("hechos") or [])
        racha, dia = 0, hoy if hoy.isoformat() in hechos else hoy - datetime.timedelta(days=1)
        while dia.isoformat() in hechos:
            racha += 1
            dia -= datetime.timedelta(days=1)
        semana = [(hoy - datetime.timedelta(days=i)).isoformat() in hechos for i in range(6, -1, -1)]
        sal.append({"id": x["id"], "nombre": x["nombre"], "hoy": hoy.isoformat() in hechos, "racha": racha,
                    "semana": semana, "total": len(hechos)})
    return sal


def _resumen_gastos(gastos):
    hoy = datetime.date.today()
    lunes = hoy - datetime.timedelta(days=hoy.weekday())
    d_hoy = [x for x in gastos if x.get("fecha") == hoy.isoformat()]
    semana = [x for x in gastos if x.get("fecha", "") >= lunes.isoformat()]
    mes = [x for x in gastos if x.get("fecha", "")[:7] == hoy.isoformat()[:7]]
    por_dia = []
    for i in range(6, -1, -1):
        dia = (hoy - datetime.timedelta(days=i)).isoformat()
        por_dia.append({"dia": dia, "total": sum(x["valor"] for x in gastos if x.get("fecha") == dia)})
    return {"hoy": d_hoy, "total_hoy": sum(x["valor"] for x in d_hoy),
            "total_semana": sum(x["valor"] for x in semana), "total_mes": sum(x["valor"] for x in mes),
            "por_dia": por_dia}


def _nombre_nota(nombre):
    n = re.sub(r"[^\w áéíóúñü\-]", "", str(nombre)).strip().lower()[:60]
    return n


def notas():
    try:
        os.makedirs(CARPETA_NOTAS, exist_ok=True)
        sal = []
        for f in os.listdir(CARPETA_NOTAS):
            if f.endswith(".txt"):
                ruta = os.path.join(CARPETA_NOTAS, f)
                with open(ruta, "r", encoding="utf-8", errors="replace") as fh:
                    txt = fh.read(4000)
                sal.append({"nombre": f[:-4], "texto": txt, "ts": os.path.getmtime(ruta)})
        return sorted(sal, key=lambda x: -x["ts"])
    except Exception:
        return []


def guardar_nota(nombre, texto):
    n = _nombre_nota(nombre)
    if not n:
        return False
    os.makedirs(CARPETA_NOTAS, exist_ok=True)
    with open(os.path.join(CARPETA_NOTAS, n + ".txt"), "w", encoding="utf-8") as f:
        f.write(str(texto)[:20000])
    return True


def borrar_nota(nombre):
    n = _nombre_nota(nombre)
    ruta = os.path.join(CARPETA_NOTAS, n + ".txt")
    if n and os.path.isfile(ruta):
        papelera = os.path.join(CARPETA_DATOS, "notas_borradas")      # nada se pierde del todo
        os.makedirs(papelera, exist_ok=True)
        shutil.move(ruta, os.path.join(papelera, f"{n}-{int(time.time())}.txt"))
        return True
    return False


# =====================================================================
# Lo que muestra cada seccion
# =====================================================================
_cache = {}


def _con_cache(clave, seg, fn, defecto=None):
    ahora = time.time()
    v = _cache.get(clave)
    if v and ahora - v[0] < seg:
        return v[1]
    try:
        r = fn()
    except Exception:
        r = v[1] if v else defecto
    _cache[clave] = (ahora, r)
    return r


_procs_vistos = {}


def _pesados():
    """Los programas que mas memoria usan ahora (agrupados por nombre), con su CPU."""
    def _leer():
        import psutil
        propio = os.getpid()
        nucleos = psutil.cpu_count() or 1
        grupos = {}
        vivos = set()
        for pr in psutil.process_iter(["name", "memory_info"]):
            try:
                if pr.pid in (0, propio) or not pr.info["name"]:
                    continue
                nombre = pr.info["name"]
                if nombre.lower() in ("system idle process", "system", "registry", "memory compression", "idle"):
                    continue
                vivos.add(pr.pid)
                viejo = _procs_vistos.setdefault(pr.pid, pr)
                cpu = viejo.cpu_percent(None) / nucleos
                g = grupos.setdefault(nombre, {"nombre": nombre, "ram_mb": 0.0, "cpu": 0.0, "procesos": 0})
                g["ram_mb"] += (pr.info["memory_info"].rss if pr.info["memory_info"] else 0) / 1048576
                g["cpu"] += cpu
                g["procesos"] += 1
            except Exception:
                continue
        for pid in list(_procs_vistos):
            if pid not in vivos:
                _procs_vistos.pop(pid, None)
        lista = sorted(grupos.values(), key=lambda g: -g["ram_mb"])[:7]
        for g in lista:
            g["ram_mb"] = round(g["ram_mb"])
            g["cpu"] = round(g["cpu"], 1)
        return lista
    return _con_cache("pesados", 3, _leer, [])


def _estado_visual():
    """reposo | escuchando | pensando | hablando (lo que muestra la esfera)."""
    try:
        from core import voz
        if voz.hablando():
            return "hablando"
    except Exception:
        pass
    if _pensando_desde and time.time() - _pensando_desde < 20:
        return "pensando"
    try:
        from .. import micro
        if ajustes.obtener("escucha") and micro.activa():
            return "escuchando"
    except Exception:
        pass
    return "reposo"


def _colores_tema():
    nombre = tema.actual()
    p = dict(tema.colores_de(nombre))
    try:
        if ajustes.obtener("alto_contraste"):
            p = tema._contraste(p)
    except Exception:
        pass
    p.setdefault("ok", p["azul_claro"])
    p.setdefault("atencion", p["morado_claro"])
    p.setdefault("alerta", p["rojo_claro"])
    return {"nombre": nombre, "colores": p}


def _alarmas():
    def _leer():
        from core import alarmas
        sal = []
        for a in alarmas.pendientes()[:8]:
            try:
                cuando = alarmas._fecha(a)
                txt_cuando = alarmas.describir_cuando(cuando)
            except Exception:
                txt_cuando = a.get("cuando", "")
            sal.append({"id": a.get("id"), "texto": a.get("texto", ""), "cuando": a.get("cuando", ""),
                        "describe": txt_cuando, "tipo": a.get("tipo", "aviso")})
        return sal
    return _con_cache("alarmas", 3, _leer, [])


def _nombre_usuario():
    def _leer():
        for ruta in (os.path.join(DATABASE, "usuario.json"), os.path.join(DATABASE, "perfil.json"),
                     os.path.join(DATABASE, "memoria.json")):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    for k in ("nombre", "nombre_usuario", "usuario"):
                        if isinstance(d.get(k), str) and d[k].strip():
                            return d[k].strip()
            except Exception:
                continue
        return ""
    return _con_cache("usuario", 60, _leer, "")


def estado(desde=0):
    """Lo que la pagina pide cada segundo."""
    global _ultimo_contacto
    _ultimo_contacto = time.time()
    with _lock:
        msgs = [m for m in _chat if m["id"] > desde]
        ultimo = _id_msg
    hoy_ = _leer_hoy()
    try:
        intenciones = list(en_vivo.intenciones)[-8:]
    except Exception:
        intenciones = []
    return {
        "estado": _estado_visual(),
        "mensajes": msgs, "ultimo_id": ultimo,
        "equipo": datos.equipo(),
        "voz": datos.voz(),
        "controles": datos.controles(),
        "procesos": datos.procesos(),
        "alarmas": _alarmas(),
        "pendientes": hoy_["pendientes"],
        "habitos": _resumen_habitos(hoy_.get("habitos")),
        "pesados": _pesados(),
        "gastos": _resumen_gastos(hoy_["gastos"]),
        "intenciones": intenciones,
        "avisos": en_vivo.tomar_avisos() if not _ventana_tk_abierta() else [],
        "tema": _colores_tema(),
        "ajustes": {k: ajustes.obtener(k) for k in _AJUSTES_PAGINA},
        "usuario": _nombre_usuario(),
        "modo": _modo_actual(),
        "hora_servidor": time.time(),
    }


def _modo_actual():
    try:
        from .. import perfiles
        n = perfiles.activo()
        return {"nombre": n, "texto": _NOMBRES_MODO.get(n, n.capitalize())}
    except Exception:
        return {"nombre": "", "texto": ""}


def _ventana_tk_abierta():
    try:
        from .. import ventana
        return ventana.abierta()
    except Exception:
        return False


def arche_info():
    """Lo de la seccion «Arché»: redes, examen, nube, mejora."""
    def _mejora():
        from core import mejora_continua as m
        return [{"ts": h.get("t", 0), "texto": h.get("texto", "")} for h in (m._cargar().get("historial") or [])[-10:]][::-1]
    return {"examen": datos.examen(), "nube": datos.nube(),
            "mejora": _con_cache("mejora", 10, _mejora, []), "controles": datos.controles()}


def _muestras(n_real, n):
    """Indices repartidos de 0 a n_real-1 (para dibujar n neuronas de una capa grande)."""
    if n_real <= n:
        return list(range(n_real))
    return sorted({round(i * (n_real - 1) / (n - 1)) for i in range(n)})


def _lista_redes(snap):
    sal = []
    for r in snap.get("redes", []):
        sal.append({k: r.get(k) for k in ("clave", "nombre", "nivel", "tipo", "trivial", "activa", "entrenada", "precision",
                                          "ejemplos_red", "ejemplos_hoy", "pendientes", "entrenable", "forma")}
                   | {"etiquetas": r.get("etiquetas", [])[:60]})
    return sal


def redes_estado(clave=None, neuronas=10, seguir_prueba=False):
    """Todo lo de la vista de redes: lista, la red elegida dibujable, la última prueba y lo que se agregó."""
    try:
        from .. import redes as R
    except Exception as e:
        return {"error": f"No pude cargar el módulo de redes ({e})."}
    if not R.disponible():
        return {"error": "Faltan los módulos de core/IA para leer las redes."}
    snap = R.snapshot()
    sal = {"listo": bool(snap.get("listo")), "error": snap.get("error", ""), "total": snap.get("total", 0),
           "propuestas": snap.get("propuestas", 0), "redes": _lista_redes(snap)}
    if not sal["listo"]:
        return sal
    pr0 = R.estado.get("prueba")
    if seguir_prueba and pr0 and pr0.get("clave") and R.clave_valida(pr0.get("clave")):
        clave = pr0["clave"]
    if not clave or not R.clave_valida(clave):
        clave = R.primera_clave()
    sal["clave"] = clave
    neuronas = max(4, min(24, int(neuronas or 10)))
    f = R.forma_de(clave) if clave else None
    idx = None
    if f:
        idx = [_muestras(f["entrada"], neuronas)] + [_muestras(n, neuronas) for n in f["ocultas"]] + [list(range(min(len(f["clases"]), 16)))]
        pesos = []
        for i, w in enumerate(f["coefs"]):
            a, b = idx[i], idx[i + 1]
            if w.shape[1] == 1:                       # salida binaria: una sola columna
                b = [0]
            sub = w[a][:, b]
            mx = float(abs(sub).max()) or 1.0
            pesos.append([[round(float(x) / mx, 2) for x in fila] for fila in sub])
        sal["dibujo"] = {"capas": [{"real": f["entrada"], "nombre": "entrada"}] +
                                  [{"real": n, "nombre": f"oculta {k + 1}"} for k, n in enumerate(f["ocultas"])] +
                                  [{"real": len(f["clases"]), "nombre": "salida"}],
                         "muestras": [len(x) for x in idx], "pesos": pesos, "clases": f["clases"][:16],
                         "activacion": f["activacion"]}
    pr = R.estado.get("prueba")
    if pr:
        p = {"frase": pr.get("frase"), "clave": pr.get("clave"), "error": pr.get("error", ""), "ts": pr.get("ts"),
             "pasos": [{"nombre": x["nombre"], "etiqueta": x["etiqueta"], "confianza": round(float(x["confianza"]), 3),
                        "top": [[c, round(float(v), 3)] for c, v in x["probs"][:4]]} for x in pr.get("pasos", [])]}
        if pr.get("clases") and pr.get("clave") == clave and idx:
            p["activaciones"] = [[round(float(pr["entrada"][i]), 2) for i in idx[0]]] + \
                                [[round(float(capa[i]), 2) for i in idx[k + 1]] for k, capa in enumerate(pr.get("ocultas", []))] + \
                                [[round(float(pr["probs"][i]), 3) for i in idx[-1] if i < len(pr["probs"])]]
            p["probs"] = sorted([[c, round(float(v), 3)] for c, v in zip(pr["clases"], pr["probs"])], key=lambda x: -x[1])[:6]
        sal["prueba"] = p
    sal["probando"] = bool(R.estado.get("probando"))
    sal["agregando"] = R.estado.get("agregando", 0)
    sal["resultados"] = [{k: it.get(k) for k in ("id", "frase", "estado", "intencion", "metodo", "mensaje", "auto", "deshecho")}
                         | {"opciones": [o.get("intencion") if isinstance(o, dict) else str(o) for o in (it.get("opciones") or [])][:4]}
                         for it in list(R.estado.get("resultados", []))[:8]]
    e = R.estado.get("entreno", {})
    sal["entreno"] = {k: e.get(k) for k in ("corriendo", "hecho", "total", "actual", "mensaje")}
    return sal


def redes_accion(cuerpo):
    from .. import redes as R
    a = cuerpo.get("accion")
    texto = str(cuerpo.get("texto", ""))[:2000]
    if a == "probar":
        R.probar(texto, cuerpo.get("clave"))
    elif a == "agregar":
        return {"ok": True, "n": R.agregar(texto)}
    elif a == "elegir":
        R.elegir(int(cuerpo.get("id")), str(cuerpo.get("intencion")))
    elif a == "deshacer":
        R.deshacer(int(cuerpo.get("id")))
    elif a == "descartar":
        R.descartar(int(cuerpo.get("id")))
    elif a == "entrenar":
        clave = cuerpo.get("clave") or "todas"
        ok = R.entrenar(clave)
        if not ok:
            return {"ok": False, "error": R.estado["entreno"].get("mensaje") or "Ya hay un entrenamiento en marcha."}
    R.invalidar()
    return {"ok": True}


def inicio():
    """Clima, noticias, frase del dia y fechas (lo lento, con cache)."""
    ciudad = ajustes.obtener("web_ciudad") or "Bogotá"

    def _clima():
        return clima_detallado(ciudad)

    def _noticias():
        from core import web as w
        return w.noticias(None, 6)

    sal = {"ciudad": ciudad}
    if ajustes.obtener("web_clima"):
        sal["clima"] = _con_cache("clima:" + ciudad, 900, _clima, None)
    if ajustes.obtener("web_noticias"):
        sal["noticias"] = _con_cache("noticias", 1200, _noticias, [])
    sal["frase"] = _frase_del_dia()
    sal["fechas"] = _con_cache("fechas", 300, _fechas, [])
    sal["notas"] = notas()[:12]
    return sal


_ESTADOS_CLIMA = {0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado", 45: "Niebla",
                  48: "Niebla", 51: "Llovizna ligera", 53: "Llovizna", 55: "Llovizna fuerte", 61: "Lluvia ligera",
                  63: "Lluvia", 65: "Lluvia fuerte", 80: "Chubascos ligeros", 81: "Chubascos", 82: "Chubascos fuertes",
                  95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta fuerte"}


def clima_detallado(ciudad):
    """{lugar, actual:{temp, sensacion, humedad, viento, codigo, estado}, dias:[{fecha, max, min, lluvia, codigo, estado}]}"""
    from urllib.parse import quote
    from core import web as w
    geo = json.loads(w._get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=es&name=" + quote(ciudad)))
    lugar = (geo.get("results") or [None])[0]
    if not lugar:
        return {"error": f"No encontré la ciudad «{ciudad}»."}
    d = json.loads(w._get(
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lugar['latitude']}&longitude={lugar['longitude']}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&timezone=auto&forecast_days=5"))
    a, dd = d["current"], d["daily"]
    cod = int(a.get("weather_code", -1))
    return {
        "lugar": lugar.get("name", ciudad) + (", " + lugar["country"] if lugar.get("country") else ""),
        "actual": {"temp": round(a["temperature_2m"]), "sensacion": round(a["apparent_temperature"]),
                   "humedad": round(a["relative_humidity_2m"]), "viento": round(a.get("wind_speed_10m") or 0),
                   "codigo": cod, "estado": _ESTADOS_CLIMA.get(cod, "Variable")},
        "dias": [{"fecha": dd["time"][i], "max": round(dd["temperature_2m_max"][i]), "min": round(dd["temperature_2m_min"][i]),
                  "lluvia": round(dd["precipitation_probability_max"][i] or 0), "codigo": int(dd["weather_code"][i]),
                  "estado": _ESTADOS_CLIMA.get(int(dd["weather_code"][i]), "Variable")} for i in range(len(dd["time"]))],
    }


def _frase_del_dia():
    frases = []
    try:
        with open(os.path.join(AQUI, "..", "galeria", "frase_del_dia.json"), "r", encoding="utf-8") as f:
            for b in json.load(f).get("bloques", []):
                frases += b.get("frases") or []
    except Exception:
        pass
    frases = frases or ["Hecho es mejor que perfecto."]
    return frases[datetime.date.today().toordinal() % len(frases)]


def _fechas():
    """Proximas fechas de fechas.txt (las mismas del panel de la ventana clasica): «14-10 Cumpleaños de Ana»."""
    lineas = []
    for ruta in (os.path.join(DATABASE, "extensiones", "fechas.txt"), os.path.join(AQUI, "..", "galeria", "fechas.txt")):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                lineas = [x.strip() for x in f if x.strip()]
            break
        except Exception:
            continue
    hoy = datetime.date.today()
    sal = []
    for l in lineas:
        m = re.match(r"^(\d{1,2})[-/](\d{1,2})\s+(.+)$", l)
        if not m:
            continue
        try:
            d = datetime.date(hoy.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        if d < hoy:
            d = d.replace(year=hoy.year + 1)
        sal.append({"fecha": d.isoformat(), "dias": (d - hoy).days, "texto": m.group(3)})
    return sorted(sal, key=lambda x: x["dias"])[:6]


def comandos():
    def _leer():
        from core import guia_comandos as g
        return [{"categoria": c, "items": [{"comando": i["comando"], "descripcion": i.get("descripcion") or "",
                                             "alias": i.get("alias") or []} for i in items]}
                for c, items in g.construir_guia().items()]
    return _con_cache("comandos", 120, _leer, [])


# =====================================================================
# Ajustes: se leen de ajustes.py (sus secciones y comentarios) para no repetir nada
# =====================================================================
# Ajustes que la pagina necesita en cada cuadro
_AJUSTES_PAGINA = tuple(dict.fromkeys((
    "tema", "alto_contraste", "ui_escala", "texto_escala", "reducir_movimiento", "anim_velocidad",
    "chat_tam", "chat_espacio", "chat_alineacion", "chat_color_usuario", "chat_color_arche",
    "chat_marcas_tiempo", "chat_indicador", "chat_entrada_arriba", "chat_ancho", "chat_vista",
    "orbe_tamano", "orbe_color", "orbe_velocidad", "estilo_voz", "efecto_brillo",
    "efecto_borde_luminoso", "efecto_sombra", "efecto_particulas", "escena", "escena_intensidad",
    "escena_velocidad", "escena_brillo", "fondo", "fondo_oscuridad", "fondo_desenfoque",
    "mascota", "mascota_nombre", "consejos",
    "sistema_estilo", "sistema_actualizacion", "sistema_ocultar", "limite_cpu", "limite_ram", "limite_disco",
    "notif_segundos", "notif_posicion", "notif_exito", "notif_error", "notif_info", "notif_silencio",
    "fuente", "favoritos", "intencion_en_vivo", "escucha", "sonidos", "interfaz_tipo", "automatica",
) + tuple(o["clave"] for o in personalizacion.OPCIONES)))
WEB_USA = set(_AJUSTES_PAGINA)

# Nombres claros para la pantalla (los demas se arman con el comentario de ajustes.py)
ETIQUETAS = {
    "automatica": "Abrir la interfaz al iniciar Arché", "entrada_ventana": "Escribirle desde la ventana",
    "sonidos": "Sonidos de la interfaz", "intencion_en_vivo": "Mostrar qué entendió de cada orden",
    "ambiente_auto": "Modo ambiente automático", "ambiente_minutos": "Minutos para el modo ambiente",
    "celular": "Control desde el celular", "celular_puerto": "Puerto del celular", "escucha": "Escuchar con el micrófono",
    "tema_horario": "Cambiar de tema según la hora", "tema_dia": "Tema de día", "tema_noche": "Tema de noche",
    "fuente": "Fuente", "fondo": "Imagen de fondo", "fondo_oscuridad": "Oscurecer el fondo",
    "fondo_desenfoque": "Desenfocar el fondo", "fondo_movimiento": "Fondos animados en movimiento",
    "escena": "Escena de fondo", "escena_intensidad": "Intensidad de la escena", "escena_velocidad": "Velocidad de la escena",
    "escena_brillo": "Brillo de la escena", "efecto_sombra": "Sombras", "efecto_borde_luminoso": "Bordes luminosos",
    "efecto_brillo": "Brillo de la esfera", "efecto_profundidad": "Profundidad en las tarjetas",
    "efecto_particulas": "Chispas alrededor de la esfera", "efectos_simultaneos": "Efectos a la vez",
    "anim_velocidad": "Velocidad de las animaciones", "anim_transiciones": "Transiciones al moverse",
    "reducir_movimiento": "Reducir movimiento", "estilo_voz": "Forma de la esfera", "orbe_tamano": "Tamaño de la esfera",
    "orbe_color": "Color de la esfera", "orbe_velocidad": "Velocidad de la esfera",
    "estado_indicador": "Cómo se ve mi estado", "mascota": "Mostrar la mascota", "mascota_personaje": "Personaje",
    "mascota_nombre": "Nombre de la mascota", "mascota_tamano": "Tamaño de la mascota",
    "mascota_opacidad": "Opacidad de la mascota", "mascota_visibilidad": "Cuándo se ve la mascota",
    "mascota_reacciones": "La mascota reacciona", "mascota_frecuencia": "Consejos de la mascota",
    "mascota_flotante": "Mascota flotante", "consejos": "Consejos",
    "chat_vista": "Estilo del chat", "chat_tam": "Tamaño del texto del chat", "chat_ancho": "Ancho de los mensajes",
    "chat_espacio": "Espacio entre mensajes", "chat_alineacion": "Alineación de los mensajes",
    "chat_color_usuario": "Color de tus mensajes", "chat_color_arche": "Color de los míos",
    "chat_marcas_tiempo": "Mostrar la hora de cada mensaje", "chat_historial": "Mensajes visibles (ventana clásica)",
    "chat_indicador": "Mostrar «Arché está pensando»", "chat_entrada_arriba": "Caja de texto arriba",
    "chat_entrada_alto": "Alto de la caja de texto", "sistema_estilo": "Cómo se ve el estado del equipo",
    "sistema_actualizacion": "Segundos entre lecturas", "limite_cpu": "Avisar si la CPU pasa de",
    "limite_ram": "Avisar si la RAM pasa de", "limite_disco": "Avisar si el disco pasa de",
    "navegacion": "Navegación (ventana clásica)", "nav_iconos_tam": "Tamaño de los iconos", "nav_etiquetas": "Mostrar etiquetas",
    "ventana_modo": "Modo de la ventana", "ventana_siempre_visible": "Siempre encima", "ventana_opacidad": "Opacidad de la ventana",
    "ventana_sin_borde": "Sin borde", "flotante": "Esfera flotante", "flotante_contenido": "Qué flota",
    "flotante_tam": "Tamaño de lo que flota", "bandeja": "Icono en la bandeja", "minimizar_sin_foco": "Minimizar sin foco",
    "notif_segundos": "Segundos que dura un aviso", "notif_posicion": "Dónde salen los avisos",
    "notif_exito": "Avisos de éxito", "notif_error": "Avisos de error", "notif_info": "Avisos informativos",
    "notif_silencio": "No molestar", "ui_escala": "Tamaño de toda la interfaz", "texto_escala": "Tamaño del texto",
    "alto_contraste": "Alto contraste", "teclado_nav": "Moverse con el teclado",
    "rendimiento": "Rendimiento", "fluidez": "Fluidez", "rend_sugerir": "Proponer ahorro si va lenta",
    "ctx_progreso": "Panel de progreso en tareas largas", "ctx_resultados": "Resultados en ventana temporal",
    "ctx_reposo": "Reducirse a la esfera sin actividad",
    "interfaz_tipo": "Interfaz que se abre", "web_ciudad": "Ciudad para el clima", "web_inicio": "Sección al abrir",
    "web_lateral_compacta": "Barra lateral solo con iconos", "web_densidad": "Densidad",
    "web_noticias": "Titulares en el Inicio", "web_clima": "Clima en el Inicio", "web_reloj_24h": "Hora en formato 24 h",
    "web_enter_envia": "Enter envía el mensaje", "web_sonido_envio": "Sonido al enviar", "web_radio": "Redondeo de las tarjetas",
    "redes_estilo": "Vista de las redes", "redes_neuronas": "Neuronas dibujadas por capa",
    "redes_conexiones": "Conexiones visibles", "redes_pesos": "Color según el peso", "redes_animar": "Animar al probar",
    "redes_color_pos": "Color de pesos positivos", "redes_color_neg": "Color de pesos negativos",
    "redes_leyenda": "Leyenda de colores", "redes_cerca": "Neurona de cerca", "redes_etiquetas": "Nombres de intenciones",
    "redes_ejemplos_max": "Ejemplos visibles", "redes_probador": "Probador de frases", "redes_agregar": "Caja para agregar ejemplos",
    "redes_marcar_auto": "Marcar ejemplos automáticos", "redes_umbral_auto": "Seguridad mínima para agregar sola",
    "redes_usar_nube": "Preguntar a la nube cuando duda", "redes_proponer_nuevas": "Proponer intenciones nuevas",
    "redes_entrenar": "Cuándo entrenar", "redes_deshacer_segundos": "Segundos para deshacer",
    "orden_activo": "Orden automático de paneles", "orden_auto": "Paneles que aparecen solos",
    "orden_compactar": "Cerrar huecos", "orden_rellenar": "Usar el espacio libre", "orden_plegar_boton": "Botón para plegar",
    "orden_plegar_auto": "Segundos abierto tras tocar", "orden_carrusel_seg": "Segundos por panel en carrusel",
    "orden_barra_paginas": "Barra de páginas", "orden_boton_cajon": "Botón «Cajón»", "orden_cajon_fijos": "Extensiones fijas",
    "orden_tope": "Paneles por página", "orden_proponer": "Proponer qué ocultar", "orden_modos_auto": "Cambiar de perfil solo",
}
OPCIONES_TEXTO = {
    "web": "Nueva (web)", "clasica": "Clásica", "comoda": "Cómoda", "compacta": "Compacta", "inicio": "Inicio",
    "chat": "Chat", "pc": "Control del PC", "sistema": "Sistema", "arche": "Arché", "comandos": "Comandos",
    "ajustes": "Ajustes", "esfera": "Esfera", "ondas": "Ondas", "anillos": "Anillos", "nucleo": "Núcleo",
    "geometrica": "Geométrica", "ninguna": "Ninguna", "gradiente": "Gradiente", "particulas": "Partículas",
    "rejilla": "Rejilla", "nebulosa": "Nebulosa", "clasica_chat": "Clásica", "tecnica": "Técnica",
    "izquierda": "Izquierda", "derecha": "Derecha", "alternada": "Alternada", "barras": "Barras", "circular": "Circular",
    "numeros": "Números", "compacto": "Compacto", "arriba": "Arriba", "abajo": "Abajo", "normal": "Normal",
    "ahorro": "Ahorro", "auto": "Automático", "alta": "Alta", "animacion": "Animación", "icono": "Icono",
    "texto": "Texto", "combinado": "Combinado", "siempre": "Siempre", "temporal": "A ratos", "poca": "Poca",
    "mucha": "Mucha", "chispa": "Chispa", "robot": "Robot", "gato": "Gato", "minimal": "Mínima", "imagen": "Imagen",
    "diagrama": "Diagrama", "arbol": "Árbol", "lista": "Lista", "manual": "Manual", "automatico": "Automático",
    "al_pasar": "Al pasar el mouse", "nunca": "Nunca", "superpuesta": "Superpuesta", "pestanas": "Pestañas",
    "iconos": "Iconos", "lateral": "Lateral", "menu": "Menú", "mascota": "Mascota",
}
_OCULTOS = {"ext_tema_previo", "ventana_geometria", "flotante_pos", "celular_pin", "perfil", "recorrido_hecho",
            "tema", "sync_carpeta", "entrada_ventana"}
_NOMBRES_SECCION = {"comportamiento general": "General", "apariencia": "Apariencia", "efectos": "Efectos",
                    "identidad visual / voz": "Esfera y voz", "mascota": "Mascota", "conversacion": "Conversación",
                    "sistema": "Estado del equipo", "navegacion": "Navegación", "ventanas": "Ventanas",
                    "orden de la pantalla (orden.py)": "Orden de paneles (ventana clásica)",
                    "redes neuronales (vista y ejemplos)": "Redes neuronales", "notificaciones": "Avisos",
                    "accesibilidad": "Accesibilidad", "rendimiento": "Rendimiento",
                    "adaptacion al contexto (todo apagado: nada cambia sin tu permiso)": "Adaptación al contexto",
                    "pantallas y sincronizacion": "Pantallas", "interfaz web (core/interfaz/web)": "Interfaz nueva"}


def _sin_tildes(t):
    import unicodedata
    t = unicodedata.normalize("NFD", str(t).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip(" .")


def catalogo_ajustes():
    """[{seccion, items:[{clave, etiqueta, ayuda, tipo, valor, min, max, opciones, web}]}]"""
    def _leer():
        ruta = os.path.join(os.path.dirname(AQUI), "ajustes.py")
        with open(ruta, "r", encoding="utf-8") as f:
            fuente = f.read()
        cuerpo = fuente.split("DEFAULTS = {", 1)[1].split("\n}\n", 1)[0]
        secciones, actual = [], {"seccion": "General", "items": []}
        for linea in cuerpo.splitlines():
            ms = re.match(r"^\s*#\s*---\s*(.+?)\s*---", linea)
            if ms:
                if actual["items"]:
                    secciones.append(actual)
                nombre = ms.group(1).strip()
                actual = {"seccion": _NOMBRES_SECCION.get(nombre, nombre.capitalize()), "items": []}
                continue
            mk = re.match(r'^\s*"(\w+)"\s*:.*?(?:#\s*(.*))?$', linea)
            if mk:
                actual["items"].append((mk.group(1), (mk.group(2) or "").strip()))
        if actual["items"]:
            secciones.append(actual)
        return secciones
    estructura = _con_cache("cat_ajustes", 3600, _leer, [])
    temas_ = [n for n, _, _ in tema.listar()]
    sal = []
    for sec in estructura:
        items = []
        for clave, ayuda in sec["items"]:
            if clave in _OCULTOS or clave not in ajustes.DEFAULTS or clave in _CLAVES_PERS:
                continue
            regla = ajustes.ESQUEMA.get(clave)
            if not regla:
                continue
            tipo = regla[0]
            etiqueta = ETIQUETAS.get(clave, clave.replace("_", " ").capitalize())
            if "|" in ayuda or _sin_tildes(ayuda) == _sin_tildes(etiqueta):
                ayuda = ""                     # la lista de opciones ya se ve en el selector
            it = {"clave": clave, "etiqueta": etiqueta,
                  "ayuda": ayuda, "valor": ajustes.obtener(clave), "web": clave in WEB_USA}
            if clave in ("tema_dia", "tema_noche"):
                it.update(tipo="opc", opciones=[[t, t] for t in temas_])
            elif clave == "fondo":
                try:
                    from .. import fondos
                    lista = fondos.listar()
                except Exception:
                    lista = []
                it.update(tipo="opc", opciones=[["", "Ninguno"]] + [[x, x] for x in lista])
            elif tipo == "bool":
                it["tipo"] = "bool"
            elif tipo == "int":
                it.update(tipo="int", min=regla[1], max=regla[2])
            elif tipo == "opc":
                it.update(tipo="opc", opciones=[[o, OPCIONES_TEXTO.get(o, o.capitalize())] for o in regla[1]])
            elif tipo == "hex":
                it["tipo"] = "hex"
            elif tipo == "txt":
                it.update(tipo="txt", max=regla[1])
            else:
                continue
            items.append(it)
        if items:
            sal.append({"seccion": sec["seccion"], "items": items})
    # la seccion de la interfaz nueva primero
    sal.sort(key=lambda s: 0 if s["seccion"] == "Interfaz nueva" else 1)
    return sal


_CLAVES_PERS = {o["clave"] for o in personalizacion.OPCIONES}


def catalogo_personalizacion():
    """Las opciones de personalizacion.py agrupadas por seccion, con su valor actual."""
    sal = []
    for sec in personalizacion.secciones():
        items = []
        for o in personalizacion.OPCIONES:
            if o["seccion"] != sec or o.get("oculto"):
                continue
            it = {k: v for k, v in o.items() if k not in ("defecto",)}
            it["valor"] = ajustes.obtener(o["clave"])
            it["web"] = True
            items.append(it)
        if items:
            sal.append({"seccion": sec, "items": items})
    return sal


def aplicacion_personalizacion():
    """Lo que la pagina necesita para aplicar cada opcion sola: clave -> {css, unidad, tipo}."""
    return {o["clave"]: {"css": o.get("css"), "unidad": o.get("unidad", ""), "tipo": o["tipo"]}
            for o in personalizacion.OPCIONES}


def exportar_personalizacion():
    claves = [k for k in ajustes.claves_visuales()] + [o["clave"] for o in personalizacion.OPCIONES]
    return {"arche_personalizacion": 1, "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
            "ajustes": {k: ajustes.obtener(k) for k in dict.fromkeys(claves)},
            "temas_propios": tema.todos_los_propios()}


def importar_personalizacion(d):
    if not isinstance(d, dict) or "ajustes" not in d:
        return False, "ese archivo no es una personalización de Arché"
    n = 0
    permitidas = set(ajustes.claves_visuales()) | _CLAVES_PERS
    for k, v in (d.get("ajustes") or {}).items():
        if k in permitidas and k != "tema":
            ok, _ = fijar_ajuste(k, v)
            n += bool(ok)
    if isinstance(d.get("temas_propios"), dict) and d["temas_propios"]:
        try:
            actuales = tema.todos_los_propios()
            actuales.update(d["temas_propios"])
            tema.reemplazar_propios(actuales)
        except Exception:
            pass
    if "tema" in (d.get("ajustes") or {}):
        ok, _ = fijar_ajuste("tema", d["ajustes"]["tema"])
        n += bool(ok)
    return True, n


def restablecer(seccion=None):
    """Vuelve a los valores de fabrica las opciones de una seccion (o todas las de personalizacion)."""
    n = 0
    for o in personalizacion.OPCIONES:
        if o.get("oculto") and seccion not in (None, "__orden__"):
            continue
        if seccion == "__orden__" and o["clave"] not in ("web_secciones", "web_hoy_pestanas"):
            continue
        if seccion in (None, "__orden__") or o["seccion"] == seccion:
            if o["clave"] == "web_botones" and seccion is None:
                continue                     # tus botones no se borran al restablecer el aspecto
            ajustes.restablecer(o["clave"])
            n += 1
    return n


# --------- lo que entra en las listas se limpia (nunca se guarda basura) ---------
_SECCIONES = ("inicio", "hoy", "equipo", "mente", "ajustes")
_PESTANAS_HOY = ("tareas", "enfoque", "dinero", "notas", "mundo")
_ICONOS = ("inicio", "chat", "pc", "sistema", "arche", "comandos", "ajustes", "voz", "sol", "captura", "candado",
           "luna", "carpeta", "app", "escoba", "campana", "nota", "dinero", "nube", "diario", "calendario", "cpu",
           "estrella", "rayo", "musica", "libro", "casa", "corazon", "play", "check")


def _limpiar_lista(clave, valor):
    if not isinstance(valor, list):
        return None
    if clave == "web_botones":
        sal = []
        for b in valor[:24]:
            if isinstance(b, dict) and str(b.get("texto", "")).strip() and str(b.get("orden", "")).strip():
                sal.append({"texto": str(b["texto"]).strip()[:40], "orden": str(b["orden"]).strip()[:300],
                            "icono": b.get("icono") if b.get("icono") in _ICONOS else "rayo"})
        return sal
    if clave == "web_secciones":
        vistos, sal = set(), []
        for x in valor:
            if isinstance(x, dict) and x.get("id") in _SECCIONES and x["id"] not in vistos:
                vistos.add(x["id"])
                sal.append({"id": x["id"], "ver": bool(x.get("ver", True)) or x["id"] in ("inicio", "ajustes")})
        return sal
    if clave == "web_hoy_pestanas":
        vistos, sal = set(), []
        for x in valor:
            if isinstance(x, dict) and x.get("id") in _PESTANAS_HOY and x["id"] not in vistos:
                vistos.add(x["id"])
                sal.append({"id": x["id"], "ver": bool(x.get("ver", True))})
        return sal
    if clave == "web_inicio_paneles":
        vistos, sal = set(), []
        for x in valor[:40]:
            if isinstance(x, dict) and re.match(r"^[\w\-]{1,30}$", str(x.get("id", ""))) and x["id"] not in vistos:
                vistos.add(x["id"])
                ancho = x.get("ancho", 0)
                sal.append({"id": x["id"], "ver": bool(x.get("ver", True)),
                            "ancho": ancho if ancho in (0, 3, 4, 5, 6, 7, 8, 12) else 0})
        return sal
    if clave == "favoritos":
        return [str(x).strip()[:200] for x in valor if str(x).strip()][:20]
    return valor[:200]


_NOMBRES_MODO = {"general": "General", "programar": "Programar", "tecnico": "Técnico", "trabajo": "Trabajo",
                 "minimalista": "Minimalista", "ambiente": "Ambiente", "entretenimiento": "Entretenimiento"}


# Lo que es tuyo en cualquier modo (la mascota, tus botones, la ciudad...)
_GLOBALES_WEB = ("mascota", "mascota_personaje", "mascota_nombre", "mascota_tamano", "consejos", "mascota_frecuencia",
                 "mascota_reacciones", "web_ciudad", "web_botones", "web_secciones", "web_hoy_pestanas", "estilo_voz")


def modos():
    try:
        from .. import perfiles
        return {"activo": perfiles.activo(),
                "lista": [{"nombre": n, "texto": _NOMBRES_MODO.get(n, n.capitalize()), "descripcion": d, "integrado": i}
                          for n, d, i in perfiles.listar()]}
    except Exception as e:
        return {"activo": "", "lista": [], "error": str(e)}


def activar_modo(nombre):
    from .. import perfiles
    real = perfiles.resolver(nombre)
    if not real:
        return False, f"no conozco el modo «{nombre}»"
    guardado_antes = set((perfiles._cargar()["perfiles"].get(real, {}).get("ajustes") or {}).keys())
    globales = {k: ajustes.obtener(k) for k in _GLOBALES_WEB}      # esto no cambia con el modo
    ok, msg = perfiles.activar(real)
    for k, v in globales.items():
        ajustes.fijar(k, v)
    if not ok:
        return False, msg
    for k, v in getattr(personalizacion, "WEB_POR_MODO", {}).get(real, {}).items():
        if k not in guardado_antes:                 # la primera vez; después el modo recuerda lo tuyo
            fijar_ajuste(k, v)
    try:
        tema.aplicar(ajustes.obtener("tema"))
    except Exception:
        pass
    return True, _NOMBRES_MODO.get(real, real)


def estilos_rapidos():
    return [{"nombre": n, "descripcion": e.get("descripcion", "")} for n, e in getattr(personalizacion, "ESTILOS", {}).items()]


def aplicar_estilo(nombre):
    e = getattr(personalizacion, "ESTILOS", {}).get(nombre)
    if not e:
        return False, "no conozco ese estilo"
    n = 0
    for k, v in (e.get("valores") or {}).items():
        ok, _ = fijar_ajuste(k, v)
        n += bool(ok)
    return True, n


def temas_disponibles():
    sal = []
    for nombre, texto, propio in tema.listar():
        try:
            c = tema.colores_de(nombre)
        except Exception:
            continue
        sal.append({"nombre": nombre, "texto": texto, "propio": propio,
                    "muestra": [c["fondo"], c["panel"], c["azul_claro"], c["morado_claro"], c["rojo_claro"], c["texto"]]})
    return sal


def fijar_ajuste(clave, valor):
    if clave not in ajustes.DEFAULTS or clave in _OCULTOS - {"tema"}:
        return False, "ese ajuste no se cambia desde aquí"
    regla = ajustes.ESQUEMA.get(clave, ("?",))
    if regla[0] not in ("bool", "int", "opc", "hex", "txt", "lista"):
        return False, "ese ajuste no se cambia desde aquí"
    if regla[0] == "lista":
        valor = _limpiar_lista(clave, valor)
        if valor is None:
            return False, "debe ser una lista"
    if clave == "tema":
        real = tema.resolver(valor)
        if not real:
            return False, "no conozco ese tema"
        valor = real
    ok, limpio = ajustes.validar(clave, valor)
    if not ok:
        return False, limpio
    nuevo = ajustes.fijar(clave, limpio)
    if clave in ("tema", "alto_contraste"):
        try:
            tema.aplicar(ajustes.obtener("tema"))
        except Exception:
            pass
    if clave == "escucha":
        try:
            from .. import micro
            micro.iniciar() if nuevo else micro.detener()
        except Exception:
            pass
    return True, nuevo


def css_propio():
    try:
        with open(ARCHIVO_CSS_PROPIO, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def guardar_css_propio(texto):
    os.makedirs(CARPETA_DATOS, exist_ok=True)
    texto = str(texto)[:100000].replace("</style", "")
    with open(ARCHIVO_CSS_PROPIO, "w", encoding="utf-8") as f:
        f.write(texto)


_EXT_FONDOS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def subir_fondo(nombre, datos_b64):
    """Guarda una imagen en Database/fondos y la pone de fondo."""
    import base64
    from .. import fondos
    nombre = re.sub(r"[^\w\-. ]", "", os.path.basename(str(nombre))).strip()[:80] or "fondo.png"
    if not nombre.lower().endswith(_EXT_FONDOS):
        return False, "solo imágenes: png, jpg, webp, gif o bmp"
    if "," in datos_b64[:100]:
        datos_b64 = datos_b64.split(",", 1)[1]
    crudo = base64.b64decode(datos_b64, validate=False)
    if len(crudo) > 15 * 1024 * 1024:
        return False, "la imagen pesa más de 15 MB"
    os.makedirs(fondos.CARPETA, exist_ok=True)
    base, ext = os.path.splitext(nombre)
    final, k = nombre, 2
    while os.path.exists(os.path.join(fondos.CARPETA, final)):
        final = f"{base} {k}{ext}"
        k += 1
    with open(os.path.join(fondos.CARPETA, final), "wb") as f:
        f.write(crudo)
    ajustes.fijar("fondo", final)
    return True, final


def lista_fondos():
    try:
        from .. import fondos
        return [f for f in fondos.listar() if f.lower().endswith(_EXT_FONDOS)]
    except Exception:
        return []


def rutinas():
    try:
        from core import rutinas as r
        return [{"clave": k, "nombre": v.get("nombre", k), "pasos": v.get("pasos", [])} for k, v in r.listar().items()]
    except Exception:
        return []


def rutina(accion, nombre, pasos=None):
    from core import rutinas as r
    nombre = str(nombre or "").strip()[:40]
    if not nombre:
        return False
    if accion == "guardar":
        pasos = [str(p).strip()[:200] for p in (pasos or []) if str(p).strip()][:20]
        if not pasos:
            return False
        r.guardar(nombre, pasos)
    elif accion == "borrar":
        r.borrar(nombre)
    return True


def exportar_chat():
    os.makedirs(CARPETA_EXPORTES, exist_ok=True)
    ruta = os.path.join(CARPETA_EXPORTES, "chat-" + time.strftime("%Y%m%d-%H%M") + ".txt")
    with _lock:
        lista = list(_chat)
    with open(ruta, "w", encoding="utf-8") as f:
        dia = ""
        for m in lista:
            t = time.localtime(m["ts"])
            d = time.strftime("%Y-%m-%d", t)
            if d != dia:
                dia = d
                f.write(f"\n===== {d} =====\n")
            quien = "Tú" if m["q"] == "tu" else "Arché"
            f.write(f"[{time.strftime('%H:%M', t)}] {quien}: {m['t']}\n")
    if os.name == "nt":
        try:
            os.startfile(ruta)
        except Exception:
            pass
    return ruta


# =====================================================================
# Servidor HTTP (solo 127.0.0.1)
# =====================================================================
class _Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8", extra=None):
        datos_ = cuerpo if isinstance(cuerpo, bytes) else cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos_)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(datos_)
        except Exception:
            pass

    def _json(self, obj, codigo=200):
        self._responder(codigo, json.dumps(obj, ensure_ascii=False, default=str))

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{_puerto}", f"localhost:{_puerto}")

    def _llave_ok(self):
        return hmac.compare_digest(self.headers.get("X-Llave") or "", _llave)

    def do_GET(self):
        if not self._host_ok():
            return self._responder(403, "{}")
        u = urlparse(self.path)
        if u.path in ESTATICOS:
            archivo, tipo = ESTATICOS[u.path]
            try:
                with open(os.path.join(AQUI, archivo), "rb") as f:
                    return self._responder(200, f.read(), tipo,
                                           {"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                                                                       "style-src 'self' 'unsafe-inline'; script-src 'self'"})
            except OSError:
                return self._responder(404, "falta " + archivo, "text/plain; charset=utf-8")
        if u.path.startswith("/fondo/"):
            return self._fondo(u.path[len("/fondo/"):])
        if u.path == "/mi_estilo.css":
            return self._responder(200, css_propio(), "text/css; charset=utf-8")
        if not u.path.startswith("/api/"):
            return self._responder(404, "{}")
        if not self._llave_ok():
            return self._json({"error": "sin llave"}, 401)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/estado":
                return self._json(estado(int((q.get("desde") or ["0"])[0] or 0)))
            if u.path == "/api/inicio":
                return self._json(inicio())
            if u.path == "/api/redes":
                return self._json(redes_estado((q.get("clave") or [None])[0], (q.get("n") or ["10"])[0],
                                                (q.get("prueba") or ["0"])[0] == "1"))
            if u.path == "/api/arche":
                return self._json(arche_info())
            if u.path == "/api/ajustes":
                return self._json({"catalogo": catalogo_ajustes(), "personalizacion": catalogo_personalizacion(),
                                   "temas": temas_disponibles(), "fondos": lista_fondos(), "estilos": estilos_rapidos(),
                                   "css_propio": css_propio(), "pywebview": _hay_pywebview()})
            if u.path == "/api/aplicar":
                return self._json(aplicacion_personalizacion())
            if u.path == "/api/personalizacion":
                return self._json(exportar_personalizacion())
            if u.path == "/api/modos":
                return self._json(modos())
            if u.path == "/api/rutinas":
                return self._json(rutinas())
            if u.path == "/api/comandos":
                return self._json(comandos())
            if u.path == "/api/notas":
                return self._json(notas())
        except Exception as e:
            return self._json({"error": str(e)}, 500)
        return self._json({"error": "no existe"}, 404)

    def _fondo(self, nombre):
        try:
            from .. import fondos
            from urllib.parse import unquote
            nombre = unquote(nombre)
            if nombre not in fondos.listar():
                return self._responder(404, "{}")
            ruta = fondos.ruta(nombre)
            ext = os.path.splitext(nombre)[1].lower()
            tipo = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext)
            if not tipo:
                return self._responder(415, "{}")
            with open(ruta, "rb") as f:
                return self._responder(200, f.read(), tipo, {"Cache-Control": "max-age=3600"})
        except Exception:
            return self._responder(404, "{}")

    def do_POST(self):
        if not self._host_ok() or not self._llave_ok():
            return self._json({"error": "sin llave"}, 401)
        try:
            tope = 22_000_000 if self.path == "/api/fondo_subir" else 300_000
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > tope:
                return self._json({"error": "demasiado grande"}, 413)
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            if not isinstance(cuerpo, dict):
                raise ValueError
        except Exception:
            return self._json({"error": "json invalido"}, 400)
        p = self.path
        try:
            if p == "/api/enviar":
                texto = str(cuerpo.get("texto", "")).strip()[:2000]
                if texto:
                    _ecos.append(texto)
                    entrada.enviar(texto, "web")
                return self._json({"ok": bool(texto)})
            if p == "/api/ajuste":
                ok, r = fijar_ajuste(str(cuerpo.get("clave")), cuerpo.get("valor"))
                return self._json({"ok": ok, "valor" if ok else "error": r})
            if p == "/api/pendiente":
                return self._json({"ok": True, "pendientes": pendiente(cuerpo.get("accion"), cuerpo.get("id"),
                                                                          cuerpo.get("texto", ""))})
            if p == "/api/gasto":
                return self._json({"ok": True, "gastos": _resumen_gastos(gasto(cuerpo.get("accion"), cuerpo.get("id"),
                                                                                   cuerpo.get("concepto", ""),
                                                                                   cuerpo.get("valor", 0)))})
            if p == "/api/nota":
                ok = guardar_nota(cuerpo.get("nombre", ""), cuerpo.get("texto", ""))
                return self._json({"ok": ok, "notas": notas()})
            if p == "/api/nota_borrar":
                ok = borrar_nota(cuerpo.get("nombre", ""))
                return self._json({"ok": ok, "notas": notas()})
            if p == "/api/chat_limpiar":
                limpiar_chat()
                return self._json({"ok": True})
            if p == "/api/habito":
                return self._json({"ok": True, "habitos": habito(cuerpo.get("accion"), cuerpo.get("id"), cuerpo.get("nombre", ""))})
            if p == "/api/mi_estilo":
                guardar_css_propio(cuerpo.get("css", ""))
                return self._json({"ok": True})
            if p == "/api/fondo_subir":
                ok, r = subir_fondo(cuerpo.get("nombre", ""), str(cuerpo.get("datos", "")))
                return self._json({"ok": ok, "fondo" if ok else "error": r, "fondos": lista_fondos()})
            if p == "/api/personalizacion_importar":
                ok, r = importar_personalizacion(cuerpo)
                return self._json({"ok": ok, "cambios" if ok else "error": r})
            if p == "/api/redes":
                return self._json(redes_accion(cuerpo))
            if p == "/api/modo":
                ok, r = activar_modo(str(cuerpo.get("nombre", "")))
                return self._json({"ok": ok, "modo" if ok else "error": r})
            if p == "/api/estilo":
                ok, r = aplicar_estilo(str(cuerpo.get("nombre", "")))
                return self._json({"ok": ok, "cambios" if ok else "error": r})
            if p == "/api/restablecer":
                return self._json({"ok": True, "cambios": restablecer(cuerpo.get("seccion"))})
            if p == "/api/rutina":
                return self._json({"ok": rutina(cuerpo.get("accion"), cuerpo.get("nombre"), cuerpo.get("pasos")),
                                   "rutinas": rutinas()})
            if p == "/api/chat_exportar":
                return self._json({"ok": True, "ruta": exportar_chat()})
            if p == "/api/clasica":
                _abrir_clasica()
                return self._json({"ok": True})
        except Exception as e:
            return self._json({"error": str(e)}, 500)
        return self._json({"error": "no existe"}, 404)


def _puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _guardado_periodico():
    while _servidor is not None:
        time.sleep(20)
        _guardar_chat()
        try:
            from .. import perfiles
            perfiles.volcar()           # lo que cambies se queda en el modo activo
        except Exception:
            pass


def iniciar():
    """Arranca el servidor (idempotente). Devuelve la direccion con la llave."""
    global _servidor, _hilo, _llave, _puerto
    with _lock:
        if _servidor is not None:
            return direccion()
        _llave = secrets.token_urlsafe(24)
        _puerto = _puerto_libre()
        _instalar_espejo()
        try:
            entrada.instalar()                # escribir desde la pagina = escribir en la consola
            entrada.al_recibir(_al_recibir)
        except Exception:
            pass
        if not _chat:
            _cargar_chat()
        _servidor = ThreadingHTTPServer(("127.0.0.1", _puerto), _Manejador)
        _servidor.daemon_threads = True
        _hilo = threading.Thread(target=_servidor.serve_forever, name="arche-web", daemon=True)
        _hilo.start()
        threading.Thread(target=_guardado_periodico, name="arche-web-chat", daemon=True).start()
    return direccion()


def detener():
    global _servidor
    with _lock:
        if _servidor is not None:
            _guardar_chat()
            try:
                _servidor.shutdown()
            except Exception:
                pass
            _servidor = None


def direccion():
    return f"http://127.0.0.1:{_puerto}/#llave={_llave}"


def _hay_pywebview():
    return importlib.util.find_spec("webview") is not None


def _navegador_app(url):
    """Edge o Chrome en modo aplicacion (ventana limpia, sin barra). True si se pudo."""
    candidatos = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidatos += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                               os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    else:
        candidatos += [shutil.which(n) or "" for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
    for exe in candidatos:
        if exe and os.path.isfile(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1320,860"])
                return True
            except Exception:
                continue
    return False


def abrir():
    """Abre la interfaz nueva. Devuelve (ok, como) — como: 'ventana', 'app' o 'navegador'."""
    global _proceso
    url = iniciar()
    if abierta():
        return True, "ya"
    if _hay_pywebview():
        try:
            # se lanza por ruta (no como modulo) para no volver a cargar core.interfaz en el otro proceso
            extra = {"creationflags": 0x08000000} if os.name == "nt" else {}     # sin consola extra en Windows
            _proceso = subprocess.Popen([sys.executable, os.path.join(AQUI, "ventana_web.py"), url,
                                         tema.colores_de(tema.actual())["fondo"]],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
            return True, "ventana"
        except Exception:
            pass
    if _navegador_app(url):
        return True, "app"
    webbrowser.open(url)
    return True, "navegador"


def abierta():
    if _proceso is not None and _proceso.poll() is None:
        return True
    return _servidor is not None and time.time() - _ultimo_contacto < 6


def cerrar():
    global _proceso
    cerrada = False
    if _proceso is not None and _proceso.poll() is None:
        try:
            _proceso.terminate()
            cerrada = True
        except Exception:
            pass
    _proceso = None
    _guardar_chat()
    return cerrada


def _al_salir():
    cerrar()
    detener()


import atexit as _atexit
_atexit.register(_al_salir)


def _abrir_clasica():
    try:
        from .. import ventana
        if ventana.disponible() and not ventana.abierta():
            ventana.abrir(tv=False)
    except Exception:
        pass
