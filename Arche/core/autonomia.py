"""
autonomia.py
------------
Ubicacion: Arche/core/autonomia.py

Que Arché se adelante, como Jarvis, sin que se lo pidas cada vez, pero con
limites claros. Tres niveles (se cambia con "nivel de autonomia <nivel>"):

  * apagada   -> no hace nada por su cuenta.
  * avisos    -> (por defecto) te AVISA y te SUGIERE; nunca ejecuta nada solo.
  * proactiva -> ademas, repite por su cuenta los habitos que tu le aprobaste
                 con "siempre", y solo si son acciones seguras.

Que vigila (cada minuto, en segundo plano):
  * bateria baja sin cargar, memoria o procesador al limite sostenido, disco casi lleno.
  * un resumen al empezar el dia (hora, alarmas pendientes, bateria).
  * habitos: si repites la misma orden segura a la misma hora en 3 dias distintos,
    te pregunta si la quiere hacer por ti ("si" / "no" / "siempre").

Seguridad:
  * Solo se aprenden y se automatizan ordenes de una lista corta y segura (abrir,
    poner musica, volumen, brillo, rutinas). Nada que apague, cierre, borre,
    mueva, teclee o toque archivos: eso SIEMPRE lo pides tu.
  * Cada aviso tiene enfriamiento para no repetirse, y todo se puede apagar.
  * Los habitos y avisos se guardan en Database/autonomia.json; "olvida mis habitos" los borra.

Lo que toca el sistema (sensores, ejecutar una orden, el reloj) esta en funciones
"_" para poder probarlo sin Windows.
"""

import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta

from core import configuracion
from core.rutas import DATABASE

ARCHIVO = os.path.join(DATABASE, "autonomia.json")
NIVELES = ("apagada", "avisos", "proactiva")
INTERVALO = 60                    # segundos entre revisiones
USOS_PARA_HABITO = 3              # dias distintos a la misma hora
VENTANA_HORAS = 1                 # +- horas para considerar "la misma hora"
RECHAZOS_MAX = 3                  # tras tantos "no", deja de sugerir ese habito
ESPERA_RESPUESTA = 10 * 60        # segundos que dura abierta una sugerencia
ENFRIAMIENTO = {"bateria": 30 * 60, "memoria": 60 * 60, "cpu": 30 * 60, "disco": 24 * 3600}

# Solo estas ordenes se aprenden como habito y se pueden automatizar.
_SEGURAS = re.compile(
    r"^(?:abre|abrir|ejecuta\s+la\s+rutina|pon|ponme|reproduce|toca|sube\s+el\s+(?:volumen|brillo)|"
    r"baja\s+el\s+(?:volumen|brillo)|silencia\s+el\s+sonido|busca\s+.+\s+en\s+(?:youtube|spotify|google))\b")
_PROHIBIDAS = re.compile(
    r"\b(apaga|apagar|reinicia|cierra|cerrar|borra|borrar|elimina|eliminar|limpia|limpiar|mueve|mover|teclea|"
    r"presiona|bloquea|suspende|formatea|desinstala|instala|libera|restaura|sesion)\b")

_lock = threading.Lock()
_estado = {"cuentas": {"memoria": 0, "cpu": 0}, "ultimo_aviso": {}, "ultima_vez_resumen": None}
_pendiente = None                  # {"cmd", "clave", "hasta", "tipo"}
_hilo = None
_detener = threading.Event()


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------

def _msg(texto):
    print(f"Arché: {texto}")


def _sin_tildes(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[¿?¡!,.;:]", " ", t).split())


def _ahora():
    return datetime.now()


def _cargar():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(datos):
    try:
        os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
        with open(ARCHIVO, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def nivel():
    n = configuracion.obtener("autonomia")
    return n if n in NIVELES else "avisos"


def fijar_nivel(nuevo):
    if nuevo not in NIVELES:
        raise ValueError(nuevo)
    configuracion.cambiar("autonomia", nuevo)


def es_segura(cmd):
    t = _sin_tildes(cmd)
    return bool(t) and bool(_SEGURAS.match(t)) and not _PROHIBIDAS.search(t) and len(t.split()) <= 12


# ------------------------------------------------------------------
# Habitos
# ------------------------------------------------------------------

def registrar(cmd, ahora=None):
    """Anota que el usuario pidio `cmd` ahora. Solo ordenes seguras; nunca lanza."""
    try:
        if nivel() == "apagada" or not es_segura(cmd):
            return False
        clave = _sin_tildes(cmd)
        ahora = ahora or _ahora()
        with _lock:
            datos = _cargar()
            h = datos.setdefault("habitos", {}).setdefault(
                clave, {"cmd": cmd.strip(), "usos": [], "rechazos": 0, "aprobado": False, "sugerido": None,
                        "ultima_auto": None})
            h["usos"] = (h["usos"] + [ahora.isoformat(timespec="minutes")])[-30:]
            _guardar(datos)
        return True
    except Exception:
        return False


def _hora_cercana(h1, h2):
    d = abs(h1 - h2)
    return min(d, 24 - d) <= VENTANA_HORAS


def _dias_a_esta_hora(habito, ahora):
    """Cuantos DIAS distintos se pidio cerca de esta hora (sin contar hoy)."""
    dias = set()
    for u in habito.get("usos", []):
        try:
            t = datetime.fromisoformat(u)
        except ValueError:
            continue
        if t.date() != ahora.date() and _hora_cercana(t.hour + t.minute / 60, ahora.hour + ahora.minute / 60):
            dias.add(t.date())
    return len(dias)


def _ya_hoy(habito, ahora, campo):
    v = habito.get(campo)
    try:
        return bool(v) and datetime.fromisoformat(v).date() == ahora.date()
    except ValueError:
        return False


def habitos_para_ahora(ahora=None):
    """[(clave, habito)] que coinciden con esta hora y todavia no se sugirieron hoy."""
    ahora = ahora or _ahora()
    salida = []
    for clave, h in (_cargar().get("habitos") or {}).items():
        if h.get("rechazos", 0) >= RECHAZOS_MAX:
            continue
        if _dias_a_esta_hora(h, ahora) < USOS_PARA_HABITO:
            continue
        # si ya lo pidio el mismo hoy cerca de esta hora, no hace falta adelantarse
        if any(datetime.fromisoformat(u).date() == ahora.date() for u in h.get("usos", [])):
            continue
        salida.append((clave, h))
    return salida


# ------------------------------------------------------------------
# Sensores y reglas (la regla es pura: recibe lo medido)
# ------------------------------------------------------------------

def _leer_sensores():
    """{'bateria': %, 'cargando': bool, 'memoria': %, 'cpu': %, 'disco_libre': %} (lo que se pueda)."""
    s = {}
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is not None:
            s["bateria"], s["cargando"] = float(b.percent), bool(b.power_plugged)
        s["memoria"] = float(psutil.virtual_memory().percent)
        s["cpu"] = float(psutil.cpu_percent(interval=0.5))
        d = psutil.disk_usage(os.path.abspath(os.sep))
        s["disco_libre"] = 100.0 - float(d.percent)
    except Exception:
        pass
    return s


def evaluar(sensores, estado=None):
    """Que avisos corresponden a lo medido. [(clave, texto, comando_sugerido_o_None)].
    `estado` lleva cuentas de lecturas seguidas (la memoria o el CPU altos un instante no avisan)."""
    estado = estado if estado is not None else _estado
    avisos = []
    bat = sensores.get("bateria")
    if bat is not None and not sensores.get("cargando") and bat <= 20:
        avisos.append(("bateria", f"Te queda {bat:.0f}% de batería y no está cargando. Conecta el cargador.", None))
    mem = sensores.get("memoria")
    estado["cuentas"]["memoria"] = estado["cuentas"].get("memoria", 0) + 1 if mem is not None and mem >= 90 else 0
    if estado["cuentas"]["memoria"] >= 3:
        avisos.append(("memoria", f"La memoria lleva rato al {mem:.0f}%. ¿Quieres que te muestre qué cerrar?",
                       "libera memoria"))
    cpu = sensores.get("cpu")
    estado["cuentas"]["cpu"] = estado["cuentas"].get("cpu", 0) + 1 if cpu is not None and cpu >= 95 else 0
    if estado["cuentas"]["cpu"] >= 5:
        avisos.append(("cpu", f"El procesador lleva rato al {cpu:.0f}%. ¿Miramos qué lo está usando?",
                       "que consume mas cpu"))
    disco = sensores.get("disco_libre")
    if disco is not None and disco < 10:
        avisos.append(("disco", f"Solo te queda {disco:.0f}% de espacio en el disco. ¿Veo qué se puede limpiar?",
                       "que puedo limpiar"))
    return avisos


def _en_enfriamiento(clave, ahora):
    ultimo = _estado["ultimo_aviso"].get(clave)
    return ultimo is not None and (ahora - ultimo).total_seconds() < ENFRIAMIENTO.get(clave, 3600)


# ------------------------------------------------------------------
# Ejecutar una orden por su cuenta
# ------------------------------------------------------------------

def _ejecutar(cmd):
    """Corre `cmd` por los mismos modulos que main.py. True si algun modulo la manejo."""
    from core import acciones_pc, alarmas, control_pc, pc_avanzado, rutinas, voz
    for modulo in (voz, alarmas, rutinas, pc_avanzado, acciones_pc):
        try:
            if modulo.manejar(cmd):
                return True
        except Exception:
            continue
    rep = control_pc.interpretar_reproduccion(cmd)
    if rep:
        from core import medios
        medios.reproducir(*rep)
        return True
    bus = control_pc.interpretar_busqueda(cmd)
    if bus:
        control_pc.buscar_en_sitio(*bus)
        return True
    m = re.match(r"^(?:abre|abrir)\s+(.+)$", _sin_tildes(cmd))
    if m:
        try:
            from core import programas
            if m.group(1) in programas.programa:
                programas.abrir_programa(m.group(1))
                return True
        except Exception:
            pass
    return False


# ------------------------------------------------------------------
# Revisar (lo que hace el vigilante cada minuto)
# ------------------------------------------------------------------

def _sugerir(cmd, clave, texto, tipo, ahora):
    global _pendiente
    _msg(texto)
    _pendiente = {"cmd": cmd, "clave": clave, "tipo": tipo, "hasta": ahora + timedelta(seconds=ESPERA_RESPUESTA)}


def revisar(ahora=None, sensores=None):
    """Una pasada. Devuelve los textos que dijo (para probar)."""
    ahora = ahora or _ahora()
    dicho = []
    n = nivel()
    if n == "apagada":
        return dicho
    sensores = _leer_sensores() if sensores is None else sensores
    for clave, texto, sugerido in evaluar(sensores):
        if _en_enfriamiento(clave, ahora):
            continue
        _estado["ultimo_aviso"][clave] = ahora
        dicho.append(texto)
        if sugerido:
            _sugerir(sugerido, clave, texto + " (di «sí» y lo hago)", "sensor", ahora)
        else:
            _msg(texto)

    for clave, h in habitos_para_ahora(ahora):
        if _ya_hoy(h, ahora, "sugerido") or _ya_hoy(h, ahora, "ultima_auto"):
            continue
        with _lock:
            datos = _cargar()
            real = datos["habitos"][clave]
            if n == "proactiva" and real.get("aprobado"):
                real["ultima_auto"] = ahora.isoformat(timespec="minutes")
                _guardar(datos)
                _msg(f"Como casi todos los días a esta hora, hago esto por ti: {real['cmd']}.")
                dicho.append(f"auto:{real['cmd']}")
                threading.Thread(target=_ejecutar, args=(real["cmd"],), daemon=True).start()
                continue
            real["sugerido"] = ahora.isoformat(timespec="minutes")
            _guardar(datos)
        txt = (f"Sueles pedir «{h['cmd']}» a esta hora. ¿Lo hago? Di «sí», «no», o «siempre» "
               f"(así lo haré solo cuando estés en modo proactivo).")
        dicho.append(txt)
        _sugerir(h["cmd"], clave, txt, "habito", ahora)
    return dicho


def resumen_del_dia(ahora=None, forzar=False):
    """Una vez por dia, al arrancar: hora, alarmas, bateria. Devuelve las lineas dichas."""
    ahora = ahora or _ahora()
    if nivel() == "apagada":
        return []
    hoy = ahora.date().isoformat()
    datos = _cargar()
    if not forzar and datos.get("ultimo_resumen") == hoy:
        return []
    datos["ultimo_resumen"] = hoy
    _guardar(datos)
    saludo = "Buenos días" if ahora.hour < 12 else "Buenas tardes" if ahora.hour < 19 else "Buenas noches"
    lineas = [f"{saludo}. Son las {ahora.strftime('%H:%M')}."]
    try:
        from core import alarmas
        pend = alarmas.pendientes()
        if pend:
            lineas.append(f"Tienes {len(pend)} alarma(s) o aviso(s) pendientes ('mis alarmas' para verlas).")
    except Exception:
        pass
    s = _leer_sensores()
    if s.get("bateria") is not None and not s.get("cargando") and s["bateria"] <= 30:
        lineas.append(f"Ojo: la batería está en {s['bateria']:.0f}%.")
    for l in lineas:
        _msg(l)
    return lineas


# ------------------------------------------------------------------
# Vigilante
# ------------------------------------------------------------------

def _bucle():
    while not _detener.wait(INTERVALO):
        try:
            revisar()
        except Exception:
            pass


def iniciar_vigilante():
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, name="arche-autonomia", daemon=True)
    _hilo.start()


def detener_vigilante():
    _detener.set()


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_NIVEL = re.compile(r"^(?:nivel\s+de\s+autonomia|autonomia)\s+(apagada|avisos|proactiva|baja|media|alta)$")
_R_PROACTIVA = re.compile(r"^(?:se\s+mas\s+autonomo|actua\s+por\s+tu\s+cuenta|adelantate|se\s+proactiva|"
                          r"hazlo\s+solo|quiero\s+que\s+te\s+adelantes)$")
_R_AVISOS = re.compile(r"^(?:solo\s+avisame|solo\s+avisos|avisame\s+pero\s+no\s+hagas\s+nada)$")
_R_APAGAR = re.compile(r"^(?:no\s+me\s+avises\s+nada|apaga\s+la\s+autonomia|desactiva\s+la\s+autonomia|"
                       r"deja\s+de\s+adelantarte)$")
_R_ESTADO = re.compile(r"^(?:estado\s+de\s+la\s+autonomia|que\s+has\s+notado|que\s+habitos\s+has\s+notado|"
                       r"mis\s+habitos|que\s+vigilas|para\s+que\s+te\s+adelantas)$")
_R_OLVIDAR = re.compile(r"^(?:olvida\s+mis\s+habitos|borra\s+mis\s+habitos|olvida\s+lo\s+que\s+notaste)$")
_R_SI = re.compile(r"^(?:si|sii+|dale|hazlo|ok|okay|claro|por\s+favor|va|listo|de\s+una|si\s+hazlo|si\s+por\s+favor)$")
_R_NO = re.compile(r"^(?:no|nop|ahora\s+no|no\s+gracias|nada|no\s+hagas\s+nada|dejalo)$")
_R_SIEMPRE = re.compile(r"^(?:siempre|si\s+siempre|hazlo\s+siempre|siempre\s+a\s+esa\s+hora|hazlo\s+solo\s+siempre)$")
_R_NUNCA = re.compile(r"^(?:nunca|deja\s+de\s+sugerirme\s+eso|no\s+me\s+sugieras\s+eso|nunca\s+mas)$")
_MAPA_NIVEL = {"baja": "apagada", "media": "avisos", "alta": "proactiva"}


def _pendiente_vigente(ahora=None):
    ahora = ahora or _ahora()
    return _pendiente if _pendiente and ahora <= _pendiente["hasta"] else None


def interpretar(comando):
    t = _sin_tildes(comando)
    if not t:
        return None
    m = _R_NIVEL.match(t)
    if m:
        return ("nivel_autonomia", _MAPA_NIVEL.get(m.group(1), m.group(1)))
    if _R_PROACTIVA.match(t):
        return ("nivel_autonomia", "proactiva")
    if _R_AVISOS.match(t):
        return ("nivel_autonomia", "avisos")
    if _R_APAGAR.match(t):
        return ("nivel_autonomia", "apagada")
    if _R_OLVIDAR.match(t):
        return ("olvidar_habitos", None)
    if _R_ESTADO.match(t):
        return ("estado_autonomia", None)
    if _pendiente_vigente():
        if _R_SIEMPRE.match(t):
            return ("responder_sugerencia", "siempre")
        if _R_NUNCA.match(t):
            return ("responder_sugerencia", "nunca")
        if _R_SI.match(t):
            return ("responder_sugerencia", "si")
        if _R_NO.match(t):
            return ("responder_sugerencia", "no")
    return None


def _describir_estado():
    n = nivel()
    descr = {"apagada": "apagada: no hago nada por mi cuenta",
             "avisos": "avisos: te aviso y te sugiero, pero no hago nada solo",
             "proactiva": "proactiva: además hago solo los hábitos seguros que me aprobaste con «siempre»"}[n]
    _msg(f"Autonomía {descr}.")
    habitos = (_cargar().get("habitos") or {})
    frecuentes = sorted(habitos.values(), key=lambda h: len(h.get("usos", [])), reverse=True)[:5]
    if frecuentes:
        _msg("Lo que he notado que repites:")
        for h in frecuentes:
            marca = " (lo hago solo)" if h.get("aprobado") else (" (no me lo sugieras más)" if h.get("rechazos", 0) >= RECHAZOS_MAX else "")
            print(f"  • {h['cmd']}: {len(h.get('usos', []))} vez/veces{marca}")
    else:
        _msg("Todavía no he notado hábitos; los voy anotando mientras me pides cosas seguras (abrir, música, volumen...).")
    _msg("Vigilo: batería baja, memoria o procesador al límite y disco casi lleno. "
         "Cambia el nivel con 'nivel de autonomia avisos|proactiva|apagada'.")


def manejar(comando):
    global _pendiente
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual
    if intencion == "nivel_autonomia":
        fijar_nivel(arg)
        if arg == "apagada":
            _msg("Listo: no te aviso ni hago nada por mi cuenta.")
        elif arg == "avisos":
            _msg("Listo: te aviso y te sugiero cosas, pero no hago nada sin que me lo pidas.")
        else:
            _msg("Listo: además de avisarte, haré solo los hábitos seguros que me apruebes con «siempre». "
                 "Nunca apago, cierro ni borro nada sin que me lo pidas.")
    elif intencion == "estado_autonomia":
        _describir_estado()
    elif intencion == "olvidar_habitos":
        datos = _cargar()
        datos["habitos"] = {}
        _guardar(datos)
        _msg("Listo, olvidé los hábitos que había notado.")
    elif intencion == "responder_sugerencia":
        p, _pendiente = _pendiente, None
        datos = _cargar()
        h = (datos.get("habitos") or {}).get(p["clave"])
        if arg == "no":
            if h is not None:
                h["rechazos"] = h.get("rechazos", 0) + 1
                _guardar(datos)
            _msg("Vale, no lo hago.")
        elif arg == "nunca":
            if h is not None:
                h["rechazos"] = RECHAZOS_MAX
                _guardar(datos)
            _msg("Entendido, no te vuelvo a sugerir eso.")
        else:
            if arg == "siempre" and h is not None and p["tipo"] == "habito":
                h["aprobado"] = True
                _guardar(datos)
                _msg("Anotado: lo haré solo a esa hora cuando estés en modo proactivo "
                     "('nivel de autonomia proactiva').")
            if not _ejecutar(p["cmd"]):
                _msg("No pude hacerlo ahora; dímelo tú directamente.")
    return (intencion, arg)