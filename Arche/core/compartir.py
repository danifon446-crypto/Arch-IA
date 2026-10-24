"""
compartir.py  (red de aprendizaje)
----------------------------------
Ubicacion: Arche/core/compartir.py

Que Arché aprenda de TODOS los PC donde se usa, no solo del tuyo.

Cada PC tiene su Arché completo. Lo que aprende con el uso (formas nuevas de
pedir cosas) y los errores que le pasan se anotan en una cola local y, cada
pocos minutos, se suben a un "buzón" en la nube (Supabase). Del buzón se bajan
las lecciones que ya se aprobaron y Arché las aprende. Si no hay internet, la
cola espera y se sube después: no depende de que tu PC principal esté prendido.

Seguridad (lo importante, porque cualquiera con acceso puede enseñarle):
  * Cada persona tiene su propio TOKEN. Tú (el dueño) los creas y los quitas.
  * Lo que enseña otra persona NO entra directo: queda pendiente hasta que
    varias personas distintas enseñan lo mismo, o tú lo apruebas.
  * Las intenciones delicadas (apagar, reiniciar, codigo, las que piden
    confirmacion) nunca se comparten ni se aprenden de la red.
  * Si una leccion de la red choca con algo que aprendiste en TU PC, gana lo tuyo.
  * Antes de subir se quitan datos personales: la memoria y las notas se
    suben como plantilla ("anota algo"), y se descarta lo que tenga numeros
    largos, correos, enlaces o palabras como "clave".
  * Los errores se suben sin rutas de tu PC ni tu nombre de usuario.
  * Los cambios de codigo NO viajan por aqui (eso es la Fase 3, con firma).

Comandos:
  conecta la red de aprendizaje         (pide direccion, clave y token)
  unirme a la red ARCHE-...             (con el codigo que te dio el dueño)
  estado de la red / sincroniza ahora
  activa | desactiva la red de aprendizaje
  Solo el dueño:
  lecciones pendientes / aprueba leccion 12 / rechaza leccion 12
  errores de la red / error 3 arreglado (o ignorado)
  invita a Ana / quitale el acceso a Ana / usuarios de la red

Solo usa la libreria estandar (urllib): no hay que instalar nada.
"""

import base64
import hashlib
import json
import os
import platform
import re
import sys
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.request

from core.rutas import BASE as RAIZ_APP, DATABASE

ARCHIVO_CONFIG = os.path.join(DATABASE, "compartir.json")   # Database/ no se sube a GitHub
ARCHIVO_COLA = os.path.join(DATABASE, "compartir_cola.json")

INTERVALO_MIN = 5            # cada cuantos minutos sincroniza
PRIMERA_ESPERA_SEG = 30      # espera al arrancar, para no frenar el inicio
MAX_COLA_LECCIONES = 2000
MAX_COLA_ERRORES = 200
LOTE_LECCIONES = 100
LOTE_ERRORES = 25
TIMEOUT_SEG = 20

# de donde viene lo aprendido: solo se comparte lo que salio de USAR a Arché
FUENTES_COMPARTIBLES = {"control_pc", "enrutador_natural", "manual", "nube", "ollama"}
FUENTE_RED = "compartido"
DOMINIOS_PRIVADOS = {"memoria", "notas", "archivos"}   # se suben como plantilla, sin el dato
DOMINIOS_NUNCA = {"codigo"}
PALABRAS_PRIVADAS = ("clave", "contrasena", "password", "pin ", "tarjeta", "cuenta bancaria", "cedula")

_lock = threading.Lock()
_detener = threading.Event()
_hilo = None
_ganchos_puestos = False
_estado = {"ultima": None, "ultimo_error": "", "subidas": 0, "bajadas": 0, "retiradas": 0}


class ErrorRed(Exception):
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
    base = {"activo": False, "url": "", "clave": "", "token": "", "nombre": "", "rol": "", "desde": 0}
    base.update(_leer_json(ARCHIVO_CONFIG, {}))
    return base


def _guardar_cfg(cfg):
    with _lock:
        _escribir_json(ARCHIVO_CONFIG, cfg)


def _cola():
    c = _leer_json(ARCHIVO_COLA, {})
    return {"lecciones": c.get("lecciones", []), "errores": c.get("errores", [])}


def _guardar_cola(cola):
    _escribir_json(ARCHIVO_COLA, cola)


def configurada(cfg=None):
    cfg = cfg or _cfg()
    return bool(cfg["url"] and cfg["clave"] and cfg["token"])


def activo():
    cfg = _cfg()
    return cfg["activo"] and configurada(cfg)


def _version_arche():
    historial = _leer_json(os.path.join(RAIZ_APP, "core", "IA", "historial_versiones.json"), [])
    try:
        return str(historial[-1]["version"])
    except Exception:
        return "desconocida"


# ------------------------------------------------------------------
# Hablar con el buzon (Supabase, funciones RPC)
# ------------------------------------------------------------------
def _rpc(funcion, cfg=None, **parametros):
    cfg = cfg or _cfg()
    if not configurada(cfg):
        raise ErrorRed("la red no está configurada")
    url = cfg["url"].rstrip("/") + "/rest/v1/rpc/" + funcion
    cuerpo = json.dumps(dict(p_token=cfg["token"], **parametros), ensure_ascii=False).encode("utf-8")
    pedido = urllib.request.Request(url, data=cuerpo, method="POST", headers={
        "apikey": cfg["clave"], "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_SEG) as r:
            texto = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            detalle = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            detalle = ""
        raise ErrorRed(detalle or f"el buzón respondió {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorRed(f"sin conexión con el buzón ({getattr(e, 'reason', e)})")
    return json.loads(texto) if texto else None


# ------------------------------------------------------------------
# Que se puede compartir (filtro de privacidad y seguridad)
# ------------------------------------------------------------------
def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto)


def _parece_privado(texto):
    return (re.search(r"\d{4,}", texto) or "@" in texto or "http" in texto or "www." in texto
            or any(p in texto + " " for p in PALABRAS_PRIVADAS))


def _intencion_permitida(intencion):
    """La intencion existe, no pide confirmacion y no es delicada."""
    try:
        from core.IA import catalogo
        from core.IA.aprender_de_nube import INTENCIONES_SIN_APRENDER_SOLAS
    except Exception:
        return False
    entrada = catalogo.POR_ID.get(intencion)
    if not entrada or entrada.get("confirmar") or entrada.get("dominio") in DOMINIOS_NUNCA:
        return False
    return intencion not in INTENCIONES_SIN_APRENDER_SOLAS


def preparar_leccion(frase, intencion, contenido=""):
    """Devuelve el dict listo para subir, o None si no se debe compartir."""
    if not _intencion_permitida(intencion):
        return None
    from core.IA import catalogo
    frase, contenido = _norm(frase), _norm(contenido)
    if catalogo.POR_ID[intencion].get("dominio") in DOMINIOS_PRIVADOS and contenido:
        # "anota comprar leche" -> "anota algo": se comparte la forma, no tu dato
        if contenido not in frase:
            return None
        frase, contenido = frase.replace(contenido, "algo", 1), "algo"
    if not (2 <= len(frase) <= 150) or len(frase.split()) > 15:
        return None
    if len(contenido) > 40 or len(contenido.split()) > 4:
        return None
    if _parece_privado(frase) or _parece_privado(contenido):
        return None
    return {"frase": frase, "intencion": intencion, "contenido": contenido}


def encolar_leccion(frase, intencion, contenido=""):
    leccion = preparar_leccion(frase, intencion, contenido)
    if leccion is None:
        return False
    with _lock:
        cola = _cola()
        if leccion in cola["lecciones"]:
            return False
        cola["lecciones"] = (cola["lecciones"] + [leccion])[-MAX_COLA_LECCIONES:]
        _guardar_cola(cola)
    return True


# ------------------------------------------------------------------
# Errores: se anotan sin datos personales
# ------------------------------------------------------------------
def _limpiar_texto(texto):
    texto = str(texto or "")
    raiz = os.path.normcase(RAIZ_APP)
    texto = re.sub(re.escape(RAIZ_APP), "<arche>", texto, flags=re.I)
    texto = re.sub(re.escape(raiz), "<arche>", texto, flags=re.I)
    # archivos fuera de Arché (Python, librerias): solo el nombre, sin la carpeta
    texto = re.sub(r'File "(?!<arche>)[^"]*[\\/]([^"\\/]+)"', r'File "\1"', texto)
    texto = re.sub(r"[A-Za-z]:\\Users\\[^\\\"']+", r"<usuario>", texto, flags=re.I)
    texto = re.sub(r"/(home|Users)/[^/\"']+", r"<usuario>", texto)
    texto = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<correo>", texto)
    texto = re.sub(r"\d{6,}", "<numero>", texto)
    return texto


def _datos_error(tipo, error, tb):
    marcos = traceback.extract_tb(tb) if tb else []
    propios = [m for m in marcos if os.path.normcase(os.path.abspath(m.filename)).startswith(os.path.normcase(RAIZ_APP))]
    marco = (propios or marcos or [None])[-1]
    if marco is not None:
        archivo = os.path.relpath(marco.filename, RAIZ_APP) if propios else os.path.basename(marco.filename)
        archivo, funcion = archivo.replace("\\", "/"), marco.name
    else:
        archivo, funcion = "?", "?"
    nombre_tipo = getattr(tipo, "__name__", str(tipo))
    firma = hashlib.sha256(f"{nombre_tipo}|{archivo}|{funcion}".encode("utf-8")).hexdigest()[:32]
    traza = "".join(traceback.format_exception(tipo, error, tb))[-3500:]
    return {
        "firma": firma,
        "modulo": f"{archivo}:{funcion}",
        "tipo": nombre_tipo,
        "mensaje": _limpiar_texto(error)[:300],
        "traza": _limpiar_texto(traza),
        "version": _version_arche(),
        "sistema": f"{platform.system()} {platform.release()}"[:60],
    }


def reportar_error(error):
    """Se puede llamar desde cualquier modulo: except Exception as e: compartir.reportar_error(e)"""
    _anotar_error(type(error), error, error.__traceback__)


def _anotar_error(tipo, error, tb):
    if tipo in (KeyboardInterrupt, SystemExit) or not activo():
        return
    try:
        dato = _datos_error(tipo, error, tb)
        with _lock:
            cola = _cola()
            if not any(e["firma"] == dato["firma"] for e in cola["errores"]):
                cola["errores"] = (cola["errores"] + [dato])[-MAX_COLA_ERRORES:]
                _guardar_cola(cola)   # se guarda YA: si Arché se cierra por el error, no se pierde
    except Exception:
        pass   # reportar un error nunca debe causar otro


# ------------------------------------------------------------------
# Ganchos: escuchar lo que Arché aprende y los errores que no se atrapan
# ------------------------------------------------------------------
def instalar_ganchos():
    global _ganchos_puestos
    if _ganchos_puestos:
        return
    _ganchos_puestos = True

    from core.IA import aprendizaje
    aprender_original = aprendizaje.aprender

    def aprender_y_compartir(pregunta, accion, contenido, fuente="ollama"):
        resultado = aprender_original(pregunta, accion, contenido, fuente=fuente)
        if fuente in FUENTES_COMPARTIBLES and activo():
            try:
                encolar_leccion(pregunta, accion, contenido)
            except Exception:
                pass
        return resultado

    aprender_y_compartir.original = aprender_original
    aprendizaje.aprender = aprender_y_compartir

    gancho_anterior = sys.excepthook

    def gancho_errores(tipo, error, tb):
        _anotar_error(tipo, error, tb)
        gancho_anterior(tipo, error, tb)

    sys.excepthook = gancho_errores

    gancho_hilos_anterior = threading.excepthook

    def gancho_hilos(args):
        _anotar_error(args.exc_type, args.exc_value, args.exc_traceback)
        gancho_hilos_anterior(args)

    threading.excepthook = gancho_hilos


# ------------------------------------------------------------------
# Sincronizar: subir la cola, bajar lo aprobado
# ------------------------------------------------------------------
def _subir(cfg):
    with _lock:
        cola = _cola()
    subidas = 0
    while cola["lecciones"]:
        lote = cola["lecciones"][:LOTE_LECCIONES]
        _rpc("arche_subir_lecciones", cfg, p_lecciones=lote)
        with _lock:
            cola = _cola()
            cola["lecciones"] = [l for l in cola["lecciones"] if l not in lote]
            _guardar_cola(cola)
        subidas += len(lote)
    while cola["errores"]:
        lote = cola["errores"][:LOTE_ERRORES]
        _rpc("arche_reportar_errores", cfg, p_errores=lote)
        firmas = {e["firma"] for e in lote}
        with _lock:
            cola = _cola()
            cola["errores"] = [e for e in cola["errores"] if e["firma"] not in firmas]
            _guardar_cola(cola)
    return subidas


def _quitar_de_la_red(aprendizaje, frase, intencion):
    """Borra una leccion que vino de la red y luego se retiro (solo lo de la red)."""
    with aprendizaje._lock:
        datos = aprendizaje.cargar(estricto=True)
        quedan = [d for d in datos if not (d.get("fuente") == FUENTE_RED and d.get("pregunta") == frase
                                          and d.get("accion") == intencion)]
        if len(quedan) != len(datos):
            aprendizaje.guardar(quedan)
            return True
    return False


def _bajar(cfg):
    from core.IA import aprendizaje
    aprender = getattr(aprendizaje.aprender, "original", aprendizaje.aprender)
    nuevas = retiradas = 0
    while True:
        lote = _rpc("arche_bajar_lecciones", cfg, p_desde=int(cfg.get("desde") or 0)) or []
        if not lote:
            break
        locales = {d.get("pregunta"): d for d in aprendizaje.cargar()}
        for l in lote:
            frase, intencion = l["frase"], l["intencion"]
            if l["estado"] == "rechazada":
                retiradas += _quitar_de_la_red(aprendizaje, frase, intencion)
            elif _intencion_permitida(intencion):
                propia = locales.get(frase)
                # si en este PC ya se aprendio otra cosa para esa frase, gana lo de este PC
                if propia is None or propia.get("fuente") == FUENTE_RED:
                    aprender(frase, intencion, l.get("contenido", ""), fuente=FUENTE_RED)
                    nuevas += 1
            cfg["desde"] = max(int(cfg.get("desde") or 0), int(l["version"]))
        _guardar_cfg(cfg)
        if len(lote) < 500:
            break
    return nuevas, retiradas


def sincronizar_ahora():
    """Devuelve un texto corto con lo que paso."""
    cfg = _cfg()
    if not configurada(cfg):
        return "La red no está configurada. Di 'conecta la red de aprendizaje' o 'unirme a la red'."
    try:
        subidas = _subir(cfg)
        nuevas, retiradas = _bajar(cfg)
    except ErrorRed as e:
        _estado["ultimo_error"] = str(e)
        return f"No pude sincronizar: {e}. Lo pendiente queda guardado y lo intento después."
    _estado.update(ultima=time.time(), ultimo_error="")
    _estado["subidas"] += subidas
    _estado["bajadas"] += nuevas
    _estado["retiradas"] += retiradas
    texto = f"Sincronizado: subí {subidas} lecciones y aprendí {nuevas} de la red"
    return texto + (f" (y quité {retiradas} que se retiraron)." if retiradas else ".")


def _bucle():
    if _detener.wait(PRIMERA_ESPERA_SEG):
        return
    while not _detener.is_set():
        if activo():
            try:
                sincronizar_ahora()
            except Exception as e:      # el hilo nunca se debe caer
                _estado["ultimo_error"] = str(e)
        _detener.wait(INTERVALO_MIN * 60)


def iniciar():
    """Llamar una vez al arrancar Arché."""
    global _hilo
    try:
        instalar_ganchos()
    except Exception as e:
        _estado["ultimo_error"] = f"no pude poner los ganchos ({e})"
    if _hilo is None or not _hilo.is_alive():
        _detener.clear()
        _hilo = threading.Thread(target=_bucle, name="arche-red-aprendizaje", daemon=True)
        _hilo.start()


def detener():
    _detener.set()


# ------------------------------------------------------------------
# Codigo de invitacion: direccion + clave + token en un solo texto
# ------------------------------------------------------------------
def _armar_codigo(url, clave, token):
    crudo = json.dumps({"u": url, "c": clave, "t": token}, separators=(",", ":")).encode("utf-8")
    return "ARCHE-" + base64.urlsafe_b64encode(crudo).decode("ascii").rstrip("=")


def _leer_codigo(codigo):
    codigo = codigo.strip()
    if not codigo.upper().startswith("ARCHE-"):
        raise ValueError("el código debe empezar por ARCHE-")
    cuerpo = codigo[6:]
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)).decode("utf-8"))
    return datos["u"], datos["c"], datos["t"]


def _conectar(url, clave, token):
    url = url.strip().rstrip("/")
    if not re.match(r"^https://[\w.-]+$", url):
        return "Esa dirección no parece de Supabase (debe ser como https://xxxx.supabase.co)."
    cfg = _cfg()
    prueba = dict(cfg, url=url, clave=clave.strip(), token=token.strip())
    try:
        yo = _rpc("arche_quien_soy", prueba)
    except ErrorRed as e:
        return f"No pude entrar: {e}."
    prueba.update(activo=True, nombre=yo["nombre"], rol=yo["rol"])
    if cfg.get("url") != url:
        prueba["desde"] = 0
    _guardar_cfg(prueba)
    iniciar()
    quien = "el dueño" if yo["rol"] == "dueno" else "usuario"
    return (f"Conectado a la red de aprendizaje como {yo['nombre']} ({quien}). "
            f"Sincronizo cada {INTERVALO_MIN} minutos; di 'sincroniza ahora' para no esperar.")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------
_RED = r"(la )?red( de aprendizaje)?"
_R = [
    ("red_configurar", re.compile(rf"^(conecta|configura|conectate a) {_RED}$")),
    ("red_unirse", re.compile(rf"^(unirme|unete|me uno|unir) (a )?{_RED}\b")),
    ("red_estado", re.compile(rf"^(estado|como va) (de )?{_RED}$")),
    ("red_sincronizar", re.compile(r"^sincroniza(r)?( (ahora|ya|la red))?$")),
    ("red_activar", re.compile(r"^(activa|prende|enciende) (la )?red de aprendizaje$")),
    ("red_desactivar", re.compile(r"^(desactiva|apaga) (la )?red de aprendizaje$")),
    ("red_pendientes", re.compile(r"^(lecciones|ensenanzas) pendientes( de la red)?$")),
    ("red_aprobar", re.compile(r"^(aprueba|acepta) (la )?leccion (?P<id>\d+)$")),
    ("red_rechazar", re.compile(r"^(rechaza|retira|quita) (la )?leccion (?P<id>\d+)$")),
    ("red_errores", re.compile(r"^errores (de la red|reportados|de los otros pc)$")),
    ("red_marcar_error", re.compile(r"^error (?P<id>\d+) (?P<estado>arreglado|ignorado|abierto)$")),
    ("red_invitar", re.compile(r"^(invita|dale acceso) a (?P<nombre>[a-z0-9 ]{2,30}?)( a la red)?$")),
    ("red_revocar", re.compile(r"^(quitale|quita|saca) (el )?acceso (de la red )?a (?P<nombre>[a-z0-9 ]{2,30})$")),
    ("red_usuarios", re.compile(r"^(usuarios|quienes estan|quien esta) (de|en) la red$")),
]


def interpretar(comando):
    t = _norm(comando).rstrip(".!?")
    for nombre, rx in _R:
        m = rx.match(t)
        if m:
            return nombre, m.groupdict()
    return None


def _preguntar(confirmar, texto):
    print("Arché: " + texto)
    try:
        return confirmar("Tú: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _texto_estado():
    cfg = _cfg()
    if not configurada(cfg):
        return "La red de aprendizaje no está configurada todavía."
    cola = _cola()
    partes = [f"Red de aprendizaje {'ACTIVA' if cfg['activo'] else 'apagada'}, conectado como "
              f"{cfg['nombre']} ({'dueño' if cfg['rol'] == 'dueno' else 'usuario'})."]
    partes.append(f"En cola: {len(cola['lecciones'])} lecciones y {len(cola['errores'])} errores por subir.")
    if _estado["ultima"]:
        partes.append(f"Última sincronización: {time.strftime('%H:%M', time.localtime(_estado['ultima']))}; "
                      f"en esta sesión subí {_estado['subidas']} y aprendí {_estado['bajadas']}.")
    if _estado["ultimo_error"]:
        partes.append(f"Último problema: {_estado['ultimo_error']}.")
    return " ".join(partes)


def manejar(comando, confirmar=input):
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, grupos = cual
    try:
        print("Arché: " + _ejecutar(intencion, grupos, comando, confirmar))
    except ErrorRed as e:
        print(f"Arché: No pude: {e}.")
    return (intencion, None)


def _ejecutar(intencion, grupos, comando, confirmar):
    cfg = _cfg()

    if intencion == "red_configurar":
        url = _preguntar(confirmar, "Pega la dirección del proyecto (Project URL, https://xxxx.supabase.co):")
        clave = _preguntar(confirmar, "Ahora la clave pública (publishable o anon key):")
        token = _preguntar(confirmar, "Y por último tu token (empieza por arche_):")
        if not (url and clave and token):
            return "Cancelado, no cambié nada."
        return _conectar(url, clave, token)

    if intencion == "red_unirse":
        m = re.search(r"ARCHE-[A-Za-z0-9_-]+", comando, flags=re.I)
        codigo = m.group(0) if m else _preguntar(confirmar, "Pega el código de invitación (empieza por ARCHE-):")
        try:
            url, clave, token = _leer_codigo(codigo)
        except Exception:
            return "Ese código no es válido. Pídele al dueño que te lo pase de nuevo."
        return _conectar(url, clave, token)

    if intencion == "red_estado":
        return _texto_estado()

    if intencion == "red_sincronizar":
        return sincronizar_ahora()

    if intencion in ("red_activar", "red_desactivar"):
        if not configurada(cfg):
            return "Primero hay que conectarla: di 'conecta la red de aprendizaje'."
        cfg["activo"] = intencion == "red_activar"
        _guardar_cfg(cfg)
        if cfg["activo"]:
            iniciar()
            return "Listo, la red de aprendizaje está activa."
        return "Listo, apagué la red: no subo ni bajo nada. Lo que ya aprendí se queda."

    # ---- de aqui para abajo, solo el dueño (el buzon tambien lo revisa)
    if intencion == "red_pendientes":
        filas = _rpc("arche_pendientes", cfg) or []
        if not filas:
            return "No hay lecciones pendientes."
        lineas = []
        for f in filas[:15]:
            extra = " ⚠ choca con otra" if f["choca"] else ""
            extra += " 🔒 protegida" if f["protegida"] else ""
            dato = f" [{f['contenido']}]" if f["contenido"] else ""
            lineas.append(f"  {f['id']}. \"{f['frase']}\" → {f['intencion']}{dato} ({f['votos']} votos){extra}")
        return ("Lecciones pendientes:\n" + "\n".join(lineas) +
                "\nDi 'aprueba leccion N' o 'rechaza leccion N'.")

    if intencion in ("red_aprobar", "red_rechazar"):
        r = _rpc("arche_decidir", cfg, p_id=int(grupos["id"]), p_aprobar=intencion == "red_aprobar")
        return f"Lección {r['id']} (\"{r['frase']}\" → {r['intencion']}) quedó {r['estado']}."

    if intencion == "red_errores":
        filas = _rpc("arche_ver_errores", cfg) or []
        if not filas:
            return "No hay errores abiertos en la red."
        lineas = [f"  {f['id']}. {f['tipo']} en {f['modulo']}: {f['mensaje'][:90]} "
                  f"({f['veces']} veces, {f['usuarios']} personas, v{f['version']}, {f['sistema']})"
                  for f in filas[:12]]
        return ("Errores que han pasado en los PC de la red (los más comunes primero):\n" + "\n".join(lineas) +
                "\nCuando arregles uno di 'error N arreglado'; si vuelve a pasar se reabre solo.")

    if intencion == "red_marcar_error":
        r = _rpc("arche_marcar_error", cfg, p_id=int(grupos["id"]), p_estado=grupos["estado"])
        return f"Error {r['id']} marcado como {r['estado']}."

    if intencion == "red_invitar":
        nombre = grupos["nombre"].strip().title()
        token = _rpc("arche_invitar", cfg, p_nombre=nombre)
        codigo = _armar_codigo(cfg["url"], cfg["clave"], token)
        return (f"Listo. Pásale a {nombre} este código (solo a esa persona, es su llave):\n\n{codigo}\n\n"
                f"En su Arché debe decir: unirme a la red {codigo[:14]}... (pegando el código completo). "
                f"Si lo pierde o lo filtra, di 'invita a {nombre}' otra vez y el código viejo deja de servir.")

    if intencion == "red_revocar":
        nombre = grupos["nombre"].strip()
        ok = _rpc("arche_revocar", cfg, p_nombre=nombre)
        return f"Le quité el acceso a {nombre.title()}." if ok else f"No encontré a {nombre.title()} en la red."

    if intencion == "red_usuarios":
        filas = _rpc("arche_usuarios_lista", cfg) or []
        lineas = [f"  {'✔' if f['activo'] else '✖'} {f['nombre']} ({'dueño' if f['rol'] == 'dueno' else 'usuario'}), "
                  f"{f['lecciones']} lecciones enseñadas" for f in filas]
        return "En la red:\n" + "\n".join(lineas)

    return "No entendí qué hacer con la red."