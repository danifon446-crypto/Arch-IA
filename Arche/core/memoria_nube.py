"""
memoria_nube.py  (Fase 2: memoria compartida)
---------------------------------------------
Ubicacion: Arche/core/memoria_nube.py

Que nada de lo que Arché aprende se pierda, y que aprenda tambien cuando
tu PC esta apagado:

  * SUBE a tu Supabase las frases de ordenes que aprendio en este PC
    (con origen y fecha) y cuantos ejemplos tiene cada intencion.
  * BAJA lo que aprendieron tus otros PC y lo que prepararon los turnos
    de la nube (nube/turno.py en GitHub Actions), lo aprende y reentrena
    sus redes una sola vez al final.

Privacidad ("nada de datos personales"):
  * Pasa por el MISMO filtro que la red de aprendizaje
    (core/compartir.preparar_leccion): nada de memoria, notas ni archivos
    con su dato (solo la forma: "anota algo"), nada con numeros largos,
    correos, enlaces o palabras como "clave"; nunca intenciones delicadas.
  * No sube charlas, respuestas, recuerdos, WhatsApp ni errores.

Seguridad:
  * Usa la clave SECRETA de Supabase (service_role / sb_secret). Se guarda
    CIFRADA en Database/memoria_nube_clave.txt (Database/ no se sube a GitHub).
  * Lo que baja vuelve a pasar el filtro antes de aprenderse.
  * Si en este PC ya aprendiste otra cosa para la misma frase, gana lo tuyo.
  * Todo lo que baja queda marcado (fuente "memoria_nube") y se puede quitar:
    "olvida lo de la memoria en la nube".

Comandos:
  conecta la memoria en la nube         (pide la direccion y la clave secreta)
  sincroniza la memoria en la nube
  estado de la memoria en la nube
  activa | desactiva la memoria en la nube
  apaga | prende los turnos de la nube  (interruptor de emergencia de los turnos sin PC)
  olvida lo de la memoria en la nube

Solo usa la libreria estandar (urllib): no hay que instalar nada.
"""

import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter

from core.rutas import DATABASE

ARCHIVO_CONFIG = os.path.join(DATABASE, "memoria_nube.json")
ARCHIVO_CLAVE = os.path.join(DATABASE, "memoria_nube_clave.txt")
ARCHIVO_SUBIDOS = os.path.join(DATABASE, "memoria_nube_subidos.json")

FUENTE = "memoria_nube"
INTERVALO_MIN = 30
PRIMERA_ESPERA_SEG = 45
LOTE_SUBIR = 200
LOTE_BAJAR = 500
TIMEOUT_SEG = 25

_lock = threading.Lock()
_detener = threading.Event()
_hilo = None
_estado = {"ultima": None, "ultimo_error": "", "subidas": 0, "bajadas": 0, "quitadas": 0}


class ErrorMemoria(Exception):
    pass


# ------------------------------------------------------------------
# Archivos locales
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


def _cfg():
    base = {"activo": False, "url": "", "pc_id": "", "desde_id": 0}
    base.update(_leer_json(ARCHIVO_CONFIG, {}))
    if not base["pc_id"]:
        base["pc_id"] = "pc-" + uuid.uuid4().hex[:10]     # anonimo: no lleva tu nombre ni el del PC
        _escribir_json(ARCHIVO_CONFIG, base)
    return base


def _guardar_cfg(cfg):
    with _lock:
        _escribir_json(ARCHIVO_CONFIG, cfg)


def _clave():
    env = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if env:
        return env
    try:
        from core.seguridad.cifrado import leer_secreto
        return leer_secreto(ARCHIVO_CLAVE)
    except Exception:
        return ""


def _guardar_clave(texto):
    from core.seguridad.cifrado import guardar_secreto
    guardar_secreto(ARCHIVO_CLAVE, texto.strip())


def configurada(cfg=None):
    cfg = cfg or _cfg()
    return bool(cfg["url"] and _clave())


def activo():
    cfg = _cfg()
    return bool(cfg["activo"]) and configurada(cfg)


# ------------------------------------------------------------------
# Hablar con Supabase (PostgREST)
# ------------------------------------------------------------------
def _pedir(metodo, tabla, params=None, cuerpo=None, prefer=None, cfg=None):
    cfg = cfg or _cfg()
    clave = _clave()
    if not (cfg["url"] and clave):
        raise ErrorMemoria("la memoria en la nube no está conectada")
    url = cfg["url"].rstrip("/") + "/rest/v1/" + tabla
    if params:
        url += "?" + urllib.parse.urlencode(params, safe="(),.*:")
    encabezados = {"apikey": clave, "Content-Type": "application/json", "Accept": "application/json"}
    if clave.startswith("eyJ"):                       # clave vieja (JWT service_role)
        encabezados["Authorization"] = "Bearer " + clave
    if prefer:
        encabezados["Prefer"] = prefer
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
    pedido = urllib.request.Request(url, data=datos, method=metodo, headers=encabezados)
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEG) as r:
            texto = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8", "replace")
        if e.code == 404 or "does not exist" in cuerpo_error or "PGRST205" in cuerpo_error:
            raise ErrorMemoria("faltan las tablas en Supabase: corre el archivo nube/arche_nube.sql en el SQL Editor")
        if e.code in (401, 403):
            raise ErrorMemoria("Supabase no aceptó la clave (usa la clave SECRETA, no la pública)")
        raise ErrorMemoria(f"Supabase respondió {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorMemoria(f"sin conexión con Supabase ({getattr(e, 'reason', e)})")
    return json.loads(texto) if texto.strip() else None


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").strip().lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


# ------------------------------------------------------------------
# Subir
# ------------------------------------------------------------------
def _clave_ejemplo(frase, intencion):
    return f"{frase}|{intencion}"


def _subir(cfg):
    from core import compartir
    from core.IA import aprendizaje
    datos = aprendizaje.cargar()
    with _lock:
        subidos = set(_leer_json(ARCHIVO_SUBIDOS, []))

    nuevas, claves_nuevas = [], []
    for d in datos:
        if not isinstance(d, dict) or not d.get("pregunta") or not d.get("accion"):
            continue
        if d.get("fuente") in (FUENTE, compartir.FUENTE_RED):   # lo que vino de afuera no se re-sube
            continue
        k = _clave_ejemplo(d["pregunta"], d["accion"])
        if k in subidos:
            continue
        leccion = compartir.preparar_leccion(d["pregunta"], d["accion"], d.get("contenido") or "")
        claves_nuevas.append(k)                      # tambien las que no pasan el filtro: no se revisan cada vez
        if leccion is not None:
            nuevas.append(dict(leccion, origen="pc", pc=cfg["pc_id"]))

    for i in range(0, len(nuevas), LOTE_SUBIR):
        _pedir("POST", "arche_ejemplos", {"on_conflict": "frase,intencion"}, nuevas[i:i + LOTE_SUBIR],
               prefer="return=minimal,resolution=ignore-duplicates", cfg=cfg)
    if claves_nuevas:
        with _lock:
            subidos = set(_leer_json(ARCHIVO_SUBIDOS, [])) | set(claves_nuevas)
            _escribir_json(ARCHIVO_SUBIDOS, sorted(subidos))

    # Solo numeros: cuantos ejemplos tiene cada intencion (para que la nube sepa donde hay huecos)
    conteo = Counter(d["accion"] for d in datos if isinstance(d, dict) and d.get("accion"))
    ahora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    filas = [{"intencion": k, "ejemplos": v, "actualizado": ahora} for k, v in conteo.items()]
    if filas:
        _pedir("POST", "arche_conteos", {"on_conflict": "intencion"}, filas,
               prefer="return=minimal,resolution=merge-duplicates", cfg=cfg)
    return len(nuevas)


# ------------------------------------------------------------------
# Bajar
# ------------------------------------------------------------------
def _quitar_retirados(cfg, aprendizaje):
    retirados = _pedir("GET", "arche_ejemplos", {"select": "frase,intencion", "retirado": "is.true",
                                                 "limit": "5000"}, cfg=cfg) or []
    if not retirados:
        return 0
    fuera = {(aprendizaje._normalizar(r["frase"]), r["intencion"]) for r in retirados}
    with aprendizaje._lock:
        datos = aprendizaje.cargar(estricto=True)
        quedan = [d for d in datos if not (d.get("fuente") == FUENTE and (d.get("pregunta"), d.get("accion")) in fuera)]
        if len(quedan) != len(datos):
            aprendizaje.guardar(quedan)
    return len(datos) - len(quedan)


def _bajar(cfg):
    from core import compartir
    from core.IA import aprendizaje, catalogo
    aprender = getattr(aprendizaje.aprender, "original", aprendizaje.aprender)
    nuevas = 0
    umbral = aprendizaje.UMBRAL_REENTRENO
    aprendizaje.UMBRAL_REENTRENO = float("inf")          # como 'importar ejemplos': reentrena una vez al final
    try:
        while True:
            lote = _pedir("GET", "arche_ejemplos", {
                "select": "id,frase,intencion,contenido", "id": f"gt.{int(cfg.get('desde_id') or 0)}",
                "pc": f"neq.{cfg['pc_id']}", "retirado": "is.false", "order": "id.asc", "limit": str(LOTE_BAJAR),
            }, cfg=cfg) or []
            if not lote:
                break
            locales = {d.get("pregunta"): d for d in aprendizaje.cargar() if isinstance(d, dict)}
            for fila in lote:
                intencion = catalogo.unificar(fila.get("intencion", ""))
                leccion = compartir.preparar_leccion(fila.get("frase", ""), intencion, fila.get("contenido") or "")
                if leccion is not None:
                    propia = locales.get(aprendizaje._normalizar(leccion["frase"]))
                    if propia is None or (propia.get("fuente") == FUENTE and propia.get("accion") != intencion):
                        aprender(leccion["frase"], intencion, leccion["contenido"], fuente=FUENTE)
                        nuevas += 1
                cfg["desde_id"] = max(int(cfg.get("desde_id") or 0), int(fila["id"]))
            _guardar_cfg(cfg)
            if len(lote) < LOTE_BAJAR:
                break
        quitadas = _quitar_retirados(cfg, aprendizaje)
    finally:
        aprendizaje.UMBRAL_REENTRENO = umbral
    if nuevas or quitadas:
        aprendizaje.reentrenar_ahora()
    return nuevas, quitadas


def sincronizar_ahora():
    cfg = _cfg()
    if not configurada(cfg):
        return "La memoria en la nube no está conectada. Di 'conecta la memoria en la nube'."
    try:
        nuevas, quitadas = _bajar(cfg)
        subidas = _subir(cfg)
    except ErrorMemoria as e:
        _estado["ultimo_error"] = str(e)
        return f"No pude sincronizar la memoria: {e}. Lo intento más tarde."
    _estado.update(ultima=time.time(), ultimo_error="")
    _estado["subidas"] += subidas
    _estado["bajadas"] += nuevas
    _estado["quitadas"] += quitadas
    texto = f"Memoria sincronizada: subí {subidas} ejemplo(s) y aprendí {nuevas} nuevo(s) de la nube"
    return texto + (f" (quité {quitadas} retirado(s))." if quitadas else ".")


def _bucle():
    if _detener.wait(PRIMERA_ESPERA_SEG):
        return
    while not _detener.is_set():
        if activo():
            try:
                sincronizar_ahora()
            except Exception as e:          # el hilo nunca se debe caer
                _estado["ultimo_error"] = str(e)
        _detener.wait(INTERVALO_MIN * 60)


def iniciar():
    """Llamar una vez al arrancar Arché."""
    global _hilo
    if _hilo is None or not _hilo.is_alive():
        _detener.clear()
        _hilo = threading.Thread(target=_bucle, name="arche-memoria-nube", daemon=True)
        _hilo.start()


def detener():
    _detener.set()


# ------------------------------------------------------------------
# Turnos de la nube (interruptor) y estado
# ------------------------------------------------------------------
def fijar_turnos(activos):
    _pedir("POST", "arche_config", {"on_conflict": "clave"}, [{"clave": "turnos_activos", "valor": bool(activos)}],
           prefer="return=minimal,resolution=merge-duplicates")


def _texto_estado():
    cfg = _cfg()
    if not configurada(cfg):
        return "La memoria en la nube no está conectada todavía. Di 'conecta la memoria en la nube'."
    partes = [f"La memoria en la nube está {'activa' if cfg['activo'] else 'apagada'} en este PC."]
    if _estado["ultima"]:
        partes.append(f"Última sincronización: {time.strftime('%H:%M', time.localtime(_estado['ultima']))} "
                      f"(en esta sesión subí {_estado['subidas']} y aprendí {_estado['bajadas']}).")
    if _estado["ultimo_error"]:
        partes.append(f"Último problema: {_estado['ultimo_error']}.")
    try:
        config = {f["clave"]: f["valor"] for f in _pedir("GET", "arche_config", {"select": "clave,valor"}) or []}
        partes.append("Turnos sin PC: " + ("encendidos." if config.get("turnos_activos", True) is not False
                                            else "APAGADOS."))
        turnos = _pedir("GET", "arche_turnos", {"select": "tarea,inicio,aceptados,nota", "order": "id.desc",
                                                "limit": "4"}) or []
        if turnos:
            lineas = [f"  {t['inicio'][:16].replace('T', ' ')} UTC  {t['tarea']}: +{t['aceptados']}"
                      + (f" ({t['nota'][:60]})" if t.get("nota") else "") for t in turnos]
            partes.append("Últimos turnos en la nube:\n" + "\n".join(lineas))
        else:
            partes.append("Todavía no ha corrido ningún turno en la nube.")
        total = _pedir("GET", "arche_ejemplos", {"select": "id", "retirado": "is.false", "order": "id.desc",
                                                 "limit": "1"}) or []
        if total:
            partes.append(f"La nube guarda hasta ahora unos {total[0]['id']} ejemplos.")
    except ErrorMemoria as e:
        partes.append(f"No pude leer la nube: {e}.")
    return "\n".join(partes)


def _olvidar_lo_bajado():
    from core.IA import aprendizaje
    with aprendizaje._lock:
        datos = aprendizaje.cargar(estricto=True)
        quedan = [d for d in datos if d.get("fuente") != FUENTE]
        if len(quedan) != len(datos):
            aprendizaje.guardar(quedan)
    quitadas = len(datos) - len(quedan)
    cfg = _cfg()
    cfg["activo"] = False
    _guardar_cfg(cfg)
    if quitadas:
        aprendizaje.reentrenar_ahora()
    return (f"Listo: quité {quitadas} ejemplo(s) que había bajado de la nube y apagué la memoria en la nube "
            f"en este PC. Lo que aprendiste aquí sigue intacto.")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------
_M = r"(la )?memoria (en|de) la nube"
_R = [
    ("memoria_conectar", re.compile(rf"^(conecta|configura|conectar|configurar) {_M}$")),
    ("memoria_sincronizar", re.compile(rf"^(sincroniza|sincronizar|actualiza) {_M}( ahora)?$")),
    ("memoria_estado", re.compile(rf"^((como (va|esta)|estado de) {_M}|{_M})$")),
    ("memoria_activar", re.compile(rf"^(activa|prende|enciende) {_M}$")),
    ("memoria_desactivar", re.compile(rf"^(desactiva|apaga) {_M}$")),
    ("turnos_apagar", re.compile(r"^(apaga|desactiva|deten|para) (los )?turnos( de la nube| sin pc)?$")),
    ("turnos_prender", re.compile(r"^(prende|activa|enciende|reanuda) (los )?turnos( de la nube| sin pc)?$")),
    ("memoria_olvidar", re.compile(rf"^olvida (lo|todo lo) (de|que bajaste de) {_M}$")),
]


def interpretar(comando):
    texto = re.sub(r"\s+", " ", _norm(comando)).strip(" .!?¿¡")
    for nombre, regex in _R:
        if regex.match(texto):
            return nombre
    return None


def _preguntar(confirmar, texto):
    print(f"Arché: {texto}")
    try:
        return confirmar("Tú: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _conectar(confirmar):
    url = _preguntar(confirmar, "Pega la dirección de tu proyecto de Supabase (Project URL, como https://xxxx.supabase.co):")
    url = url.strip().rstrip("/")
    if not re.match(r"^https://[a-z0-9-]+\.supabase\.co$", url):
        return "Esa dirección no parece de Supabase (debe ser como https://xxxx.supabase.co). No cambié nada."
    clave = _preguntar(confirmar, "Ahora pega la clave SECRETA (service_role o sb_secret_...). Se guarda cifrada:")
    if not (clave.startswith("sb_secret_") or clave.startswith("eyJ")):
        return ("Esa no parece la clave secreta (empieza con 'sb_secret_' o es la 'service_role' que empieza con "
                "'eyJ'). No uses la pública. No cambié nada.")
    cfg = _cfg()
    cfg["url"] = url
    anterior = _leer_secreto_seguro()
    _guardar_clave(clave)
    try:
        _pedir("GET", "arche_config", {"select": "clave", "limit": "1"}, cfg=cfg)
    except ErrorMemoria as e:
        if anterior:
            _guardar_clave(anterior)
        else:
            try:
                os.remove(ARCHIVO_CLAVE)
            except OSError:
                pass
        return f"No pude entrar: {e}. No cambié nada."
    cfg["activo"] = True
    _guardar_cfg(cfg)
    iniciar()
    return ("Conectado. Desde ahora lo que aprendo (solo órdenes, sin datos personales) se guarda en tu Supabase "
            "y aprendo lo que preparen los turnos de la nube. ") + sincronizar_ahora()


def _leer_secreto_seguro():
    try:
        from core.seguridad.cifrado import leer_secreto
        return leer_secreto(ARCHIVO_CLAVE)
    except Exception:
        return ""


def _ejecutar(intencion, confirmar):
    if intencion == "memoria_conectar":
        return _conectar(confirmar)
    if intencion == "memoria_sincronizar":
        return sincronizar_ahora()
    if intencion == "memoria_estado":
        return _texto_estado()
    if intencion in ("memoria_activar", "memoria_desactivar"):
        cfg = _cfg()
        if not configurada(cfg):
            return "Primero hay que conectarla: di 'conecta la memoria en la nube'."
        cfg["activo"] = intencion == "memoria_activar"
        _guardar_cfg(cfg)
        if cfg["activo"]:
            iniciar()
            return "Listo, la memoria en la nube está activa."
        return "Listo, apagué la memoria en la nube en este PC: no subo ni bajo nada. Lo aprendido se queda."
    if intencion in ("turnos_apagar", "turnos_prender"):
        fijar_turnos(intencion == "turnos_prender")
        return ("Listo, los turnos de la nube están encendidos: aprendo cada 6 horas aunque tu PC esté apagado."
                if intencion == "turnos_prender" else
                "Listo, apagué los turnos de la nube: no voy a gastar cupo ni guardar nada hasta que digas "
                "'prende los turnos de la nube'.")
    if intencion == "memoria_olvidar":
        respuesta = _preguntar(confirmar, "¿Seguro que quito todo lo que bajé de la nube? (sí / no)")
        if _norm(respuesta) not in ("si", "s", "dale", "hazlo"):
            return "Cancelado, no quité nada."
        return _olvidar_lo_bajado()
    return "No entendí qué hacer con la memoria en la nube."


def manejar(comando, confirmar=input):
    intencion = interpretar(comando)
    if intencion is None:
        return None
    try:
        print("Arché: " + _ejecutar(intencion, confirmar))
    except ErrorMemoria as e:
        print(f"Arché: No pude: {e}.")
    return (intencion, None)
