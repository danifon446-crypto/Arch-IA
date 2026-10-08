"""
alarmas.py
----------
Ubicacion: Arche/core/alarmas.py

Alarmas, temporizadores y avisos que SUENAN de verdad mientras Arché esta
abierto (sonido + mensaje + voz si la tienes activada).

  "avisame en 20 minutos que saque la ropa"
  "recuerdame a las 5 llamar a mama"
  "pon una alarma a las 7 de la mañana"
  "pon un temporizador de 10 minutos"
  "mis alarmas" / "cancela la alarma" / "cancela todas las alarmas"
  "posponer 5 minutos"   (despues de que suene una)

Se guardan en Database/alarmas.json: si cierras Arché y una hora ya paso,
al abrirlo te dice cuales se te pasaron.

Esto es APARTE de core/recordatorio.py (recordatorios con fecha y
prioridad que se muestran al iniciar): no lo reemplaza.

El interprete de horas (parsear) no depende del reloj: recibe "ahora", asi
se prueba con cualquier fecha. Lo que suena esta en _beep().
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

from core.rutas import DATABASE

ARCHIVO = os.path.join(DATABASE, "alarmas.json")
ES_WINDOWS = os.name == "nt"

_candado = threading.RLock()
_hilo = None
_detener = threading.Event()
_ultima_sonada = None     # para "posponer"


# ------------------------------------------------------------------
# Texto
# ------------------------------------------------------------------

def _sin_tildes(texto):
    t = str(texto).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


def _msg(texto):
    print(f"Arché: {texto}")


_NUMEROS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
            "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15,
            "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60}
_CANT = r"(\d+(?:[.,]\d+)?|" + "|".join(sorted(_NUMEROS, key=len, reverse=True)) + r")"
_UNIDAD = r"(segundos?|segs?|minutos?|mins?|horas?|hrs?|dias?)"
_DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def _numero(texto):
    t = texto.replace(",", ".")
    if t in _NUMEROS:
        return float(_NUMEROS[t])
    return float(t)


def _segundos_de(unidad):
    u = unidad[:3]
    return {"seg": 1, "min": 60, "hor": 3600, "hrs": 3600, "dia": 86400}.get(u, 60)


# ------------------------------------------------------------------
# Interprete de tiempos
# ------------------------------------------------------------------

_R_MEDIA_HORA = re.compile(r"\bmedia\s+hora\b")
_R_CUARTO = re.compile(r"\bun\s+cuarto\s+de\s+hora\b")
_R_Y_MEDIA = re.compile(rf"\b{_CANT}\s+horas?\s+y\s+media\b")
_R_CANTIDAD = re.compile(rf"\b{_CANT}\s*{_UNIDAD}\b")
_R_SEP = re.compile(r"\s*(?:,|y|con|e)?\s*")


def _duracion_desde(texto, pos):
    """Lee una duracion ('20 minutos', '1 hora y media', '2 horas 15 minutos') que
    empieza en `pos`. Devuelve (segundos, fin) o None."""
    total, fin, hubo = 0.0, pos, False
    while True:
        actual = fin
        m = None
        for rx, calc in ((_R_Y_MEDIA, lambda mm: _numero(mm.group(1)) * 3600 + 1800),
                         (_R_MEDIA_HORA, lambda mm: 1800),
                         (_R_CUARTO, lambda mm: 900),
                         (_R_CANTIDAD, lambda mm: _numero(mm.group(1)) * _segundos_de(mm.group(2)))):
            m = rx.match(texto, actual)
            if m:
                total += calc(m)
                fin = m.end()
                hubo = True
                break
        if not m:
            break
        sep = _R_SEP.match(texto, fin)
        sig = sep.end() if sep else fin
        if sig == fin and not texto[fin:fin + 1].isspace():
            break
        # solo se sigue si lo que viene es otra cantidad
        if not any(rx.match(texto, sig) for rx in (_R_Y_MEDIA, _R_MEDIA_HORA, _R_CUARTO, _R_CANTIDAD)):
            break
        fin = sig
    return (int(total), fin) if hubo and total > 0 else None


def _buscar_duracion(texto_norm):
    """Primera duracion en cualquier parte: (segundos, inicio, fin) o None."""
    for m in re.finditer(r"\b(?:en|dentro\s+de|de|por)\s+(?=\S)", texto_norm):
        r = _duracion_desde(texto_norm, m.end())
        if r:
            return r[0], m.start(), r[1]
    for m in re.finditer(r"\b(?=" + _CANT + r"\s*" + _UNIDAD + r"|media\s+hora|un\s+cuarto\s+de\s+hora)", texto_norm):
        r = _duracion_desde(texto_norm, m.start())
        if r:
            return r[0], m.start(), r[1]
    return None


_R_HORA = re.compile(
    r"\ba\s+las?\s+(\d{1,2})(?:\s*[:.h]\s*(\d{2}))?"
    r"(?:\s+y\s+(media|cuarto)|\s+menos\s+(cuarto|veinte|diez|cinco))?"
    r"(?:\s*(a\.?\s?m\.?|p\.?\s?m\.?))?"
    r"(?:\s+de\s+la\s+(manana|tarde|noche|madrugada)|\s+del\s+(mediodia))?\b")
_R_MEDIODIA = re.compile(r"\ba(?:l)?\s+(mediodia|medianoche)\b")
_R_DIA = re.compile(r"\b(pasado\s+manana|manana|hoy|esta\s+noche|esta\s+tarde|el\s+(?:proximo\s+)?(" +
                    "|".join(_DIAS_SEMANA) + r"))\b")


def _resolver_hora(h, minutos, meridiem, ahora, dia_dado):
    """Hora de reloj -> (hora24, minuto) o None. Si no dicen am/pm adivina lo razonable."""
    if h > 23 or minutos > 59:
        return None
    if h >= 13 or h == 0:
        return h, minutos
    if meridiem == "pm":
        return (h % 12) + 12, minutos
    if meridiem == "am":
        return h % 12, minutos
    # sin am/pm: lo mas probable
    if h == 12:
        return 12, minutos
    candidatas = [(h, minutos), (h + 12, minutos)]
    if dia_dado:                       # "manana a las 5": 7-11 -> mañana, 1-6 -> tarde
        return candidatas[0] if h >= 7 else candidatas[1]
    futuras = []
    for hh, mm in candidatas:
        c = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if c <= ahora:
            c += timedelta(days=1)
        futuras.append(c)
    elegida = min(futuras)
    return elegida.hour, elegida.minute


def parsear(texto, ahora=None):
    """
    Entiende cuando hay que avisar. Devuelve {"cuando": datetime, "resto": str, "forma": "relativa"|"hora"|"temporizador"}
    o None si no encuentra ninguna hora/duracion. `resto` es lo que queda de la frase sin la parte de tiempo.
    """
    ahora = ahora or datetime.now()
    norm = _sin_tildes(texto)

    # ---- hora de reloj ("a las 5:30 pm", "a las 8 y media", "al mediodia")
    cortes = []
    m = _R_HORA.search(norm)
    cuando = None
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        mer = (m.group(5) or "").replace(".", "").replace(" ", "")
        palabra = m.group(6) or ("mediodia" if m.group(7) else "")
        if palabra in ("tarde", "noche"):
            mer = "pm"
        elif palabra in ("manana", "madrugada"):
            mer = "am"
        if m.group(3) == "media":
            mi += 30
        elif m.group(3) == "cuarto":
            mi += 15
        elif m.group(4):
            menos = {"cuarto": 15, "veinte": 20, "diez": 10, "cinco": 5}[m.group(4)]
            h = (h - 1) if mi == 0 else h
            mi = 60 - menos if mi == 0 else mi - menos
        cortes.append((m.start(), m.end()))
        resto_norm = norm[:m.start()] + (" " * (m.end() - m.start())) + norm[m.end():]
        md = _R_DIA.search(resto_norm)
        dia_dado = md is not None
        r = _resolver_hora(h, mi, mer, ahora, dia_dado)
        if r is None:
            return None
        if palabra == "noche" and h == 12:
            r = (0, mi)
        base = ahora.replace(hour=r[0], minute=r[1], second=0, microsecond=0)
        if md:
            cortes.append((md.start(), md.end()))
            palabra_dia = md.group(1)
            if palabra_dia.startswith("pasado"):
                base += timedelta(days=2)
            elif palabra_dia == "manana":
                base += timedelta(days=1)
            elif md.group(2):
                objetivo = _DIAS_SEMANA.index(md.group(2))
                faltan = (objetivo - ahora.weekday()) % 7
                if faltan == 0 and base <= ahora:
                    faltan = 7
                base += timedelta(days=faltan)
            elif palabra_dia in ("esta noche", "esta tarde") and r[0] < 12:
                base = base.replace(hour=r[0] + 12) if r[0] + 12 < 24 else base
        if base <= ahora and not md:
            base += timedelta(days=1)
        if base <= ahora:
            return None
        cuando, forma = base, "hora"
    else:
        mm = _R_MEDIODIA.search(norm)
        if mm:
            h = 12 if mm.group(1) == "mediodia" else 0
            base = ahora.replace(hour=h, minute=0, second=0, microsecond=0)
            md = _R_DIA.search(norm)
            if md and md.group(1) == "manana":
                base += timedelta(days=1)
                cortes.append((md.start(), md.end()))
            if base <= ahora:
                base += timedelta(days=1)
            cortes.append((mm.start(), mm.end()))
            cuando, forma = base, "hora"

    # ---- duracion ("en 20 minutos", "de 10 minutos")
    if cuando is None:
        d = _buscar_duracion(norm)
        if d is None:
            return None
        segundos, ini, fin = d
        cuando = ahora + timedelta(seconds=segundos)
        cortes.append((ini, fin))
        forma = "relativa"

    # ---- lo que sobra de la frase
    resto = texto
    for ini, fin in sorted(cortes, reverse=True):
        resto = resto[:ini] + " " + resto[fin:]
    return {"cuando": cuando.replace(microsecond=0), "resto": " ".join(resto.split()), "forma": forma}


_R_DISPARADOR = re.compile(
    r"^(?:por\s+favor\s+)?(?:avisame|avisenme|recuerdame|recordame|dime|despiertame|"
    r"(?:pon(?:me|er)?|programa(?:me)?|crea(?:me)?|activa(?:me)?|ponme)\s+(?:una?\s+)?(?:alarma|recordatorio|aviso|temporizador|timer)"
    r"|(?:alarma|temporizador|timer|recordatorio))\b\s*", re.I)
_R_RELLENO = re.compile(r"^(?:que|de|para|por\s+favor|a|y|para\s+que)\s+", re.I)


def _texto_del_aviso(resto):
    t = _sin_tildes(resto)
    m = _R_DISPARADOR.match(t)
    corte = m.end() if m else 0
    out = resto[corte:].strip(" ,.;:")
    for _ in range(3):
        n = _R_RELLENO.sub("", _sin_tildes(out))
        if len(n) == len(_sin_tildes(out)):
            break
        out = out[len(out) - len(n):].strip(" ,.;:")
    return out.strip(" ,.;:")


# ------------------------------------------------------------------
# Almacen
# ------------------------------------------------------------------

def _cargar():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
            return datos if isinstance(datos, list) else []
    except (OSError, ValueError):
        return []


def _guardar(lista):
    os.makedirs(DATABASE, exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(lista, f, indent=2, ensure_ascii=False)


def pendientes():
    with _candado:
        r = [a for a in _cargar() if a.get("estado") == "pendiente"]
    return sorted(r, key=lambda a: a["cuando"])


def agregar(cuando, texto, tipo="aviso"):
    with _candado:
        lista = _cargar()
        nuevo_id = max([a.get("id", 0) for a in lista] + [0]) + 1
        alarma = {"id": nuevo_id, "cuando": cuando.strftime("%Y-%m-%d %H:%M:%S"), "texto": texto,
                  "tipo": tipo, "estado": "pendiente",
                  "creada": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        lista.append(alarma)
        _guardar(lista)
    return alarma


def _marcar(ids, estado):
    with _candado:
        lista = _cargar()
        n = 0
        for a in lista:
            if a.get("id") in ids and a.get("estado") == "pendiente":
                a["estado"] = estado
                n += 1
        _guardar(lista)
    return n


def _fecha(a):
    return datetime.strptime(a["cuando"], "%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------
# Texto para decir cuando sera
# ------------------------------------------------------------------

def describir_cuando(cuando, ahora=None):
    ahora = ahora or datetime.now()
    hora = cuando.strftime("%I:%M %p").lstrip("0").replace("AM", "a. m.").replace("PM", "p. m.")
    dif = (cuando.date() - ahora.date()).days
    if dif == 0:
        dia = "hoy"
    elif dif == 1:
        dia = "mañana"
    elif dif < 7:
        dia = "el " + ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[cuando.weekday()]
    else:
        dia = cuando.strftime("el %d/%m")
    restante = cuando - ahora
    seg = max(int(restante.total_seconds()), 0)
    if seg < 90:
        falta = f"{seg} segundos"
    elif seg < 3600:
        falta = f"{round(seg / 60)} minutos"
    elif seg < 86400:
        h, m = divmod(seg // 60, 60)
        falta = f"{h} h" + (f" {m} min" if m else "")
    else:
        falta = f"{seg // 86400} día(s)"
    return f"{dia} a las {hora} (faltan {falta})"


def _nombre_para_mostrar(a):
    if a.get("tipo") == "alarma":
        return "Alarma"
    if a.get("tipo") == "temporizador":
        return "Temporizador" + (f": {a['texto']}" if a.get("texto") else "")
    return a.get("texto") or "Aviso"


# ------------------------------------------------------------------
# Sonar
# ------------------------------------------------------------------

def _beep():
    """Pitidos de aviso. Unico punto de sonido."""
    if ES_WINDOWS:
        try:
            import winsound
            for _ in range(3):
                winsound.Beep(1000, 350)
                time.sleep(0.12)
            return
        except Exception:
            pass
    print("\a", end="", flush=True)


def _frase_de_aviso(a):
    if a.get("tipo") == "alarma":
        return f"¡Es la hora! Sonó tu alarma de las {_fecha(a).strftime('%H:%M')}."
    if a.get("tipo") == "temporizador":
        return f"¡Terminó el temporizador! {a.get('texto', '')}".strip()
    return f"Recordatorio: {a.get('texto') or 'tenías un aviso'}"


def _sonar(a, perdida=False):
    global _ultima_sonada
    _ultima_sonada = a
    frase = _frase_de_aviso(a)
    if perdida:
        frase = f"(Se te pasó a las {_fecha(a).strftime('%H:%M')}) " + frase
    _beep()
    print(f"\nArché: ⏰ {frase}")
    try:
        from core import voz
        voz.decir(frase)
    except Exception:
        pass


def revisar(ahora=None):
    """Hace sonar lo que ya llego. Devuelve cuantas sonaron. Lo llama el vigilante cada segundo."""
    ahora = ahora or datetime.now()
    vencidas = [a for a in pendientes() if _fecha(a) <= ahora]
    for a in vencidas:
        if _marcar({a["id"]}, "sonada"):
            _sonar(a)
    return len(vencidas)


def avisar_perdidas(ahora=None):
    """Al abrir Arché: lo que se paso mientras estaba cerrado."""
    ahora = ahora or datetime.now()
    perdidas = [a for a in pendientes() if _fecha(a) <= ahora]
    if not perdidas:
        return 0
    _msg(f"Mientras no estaba se pasaron {len(perdidas)} aviso(s):")
    for a in perdidas:
        if _marcar({a["id"]}, "sonada"):
            print(f"   • {_nombre_para_mostrar(a)} (era a las {_fecha(a).strftime('%H:%M')} del {_fecha(a).strftime('%d/%m')})")
    return len(perdidas)


def _bucle():
    while not _detener.wait(1.0):
        try:
            revisar()
        except Exception:
            pass


def iniciar_vigilante():
    """Arranca (una sola vez) el hilo que vigila las alarmas."""
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, name="alarmas", daemon=True)
    _hilo.start()


def detener_vigilante():
    _detener.set()


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_VER = re.compile(r"^(?:mis|ver|muestra(?:me)?|lista(?:r)?)\s+(?:mis\s+)?(?:alarmas|temporizadores|avisos|timers)$|"
                    r"^(?:que|cuales)\s+(?:alarmas|temporizadores|avisos)\s+(?:tengo|hay)(?:\s+puestas?)?$|"
                    r"^cuanto\s+falta(?:\s+para\s+(?:la|el)\s+(?:alarma|temporizador|aviso))?$")
_R_CANCELAR = re.compile(r"^(?:cancela(?:r)?|borra(?:r)?|elimina(?:r)?|quita(?:r)?|apaga(?:r)?|detener|deten)\s+"
                         r"(?:la\s+|el\s+|mi\s+|mis\s+|las\s+|los\s+|todas\s+las\s+|todos\s+los\s+|todo\s+)?"
                         r"(alarmas?|temporizadores?|avisos?|timers?|recordatorios?\s+de\s+tiempo)"
                         r"(?:\s+(\d+))?$")
_R_POSPONER = re.compile(r"^(?:posponer?|pospon|aplaza(?:r)?|snooze)\s*(?:(?:en|por|de)?\s*(.+))?$|"
                         r"^(\d+|cinco|diez|quince)\s+minutos?\s+mas$")


def _segundos_posponer(cantidad):
    """'5 minutos', '10', 'diez', '' -> segundos (5 minutos si no dicen)."""
    t = cantidad.strip()
    if not t:
        return 300
    if not re.search(_UNIDAD, t):
        t += " minutos"
    r = _duracion_desde(t, 0)
    return r[0] if r else 300


def _aviso_creado(a):
    cuando = describir_cuando(_fecha(a))
    if a["tipo"] == "alarma":
        _msg(f"Listo, alarma puesta para {cuando}.")
    elif a["tipo"] == "temporizador":
        _msg(f"Temporizador en marcha: suena {cuando}.")
    else:
        _msg(f"Anotado: te aviso {cuando}: {a['texto']}.")


def interpretar(comando, ahora=None):
    """(intencion, datos) o None. No toca nada: solo entiende la frase."""
    norm = " ".join(re.sub(r"[¿?¡!,;]", " ", _sin_tildes(comando)).split())
    if not norm:
        return None
    if _R_VER.match(norm):
        return ("ver_alarmas", None)
    m = _R_CANCELAR.match(norm)
    if m:
        # plural / "todas" / "mis" -> todas; singular -> la proxima (o la numero N)
        todas = bool(re.search(r"\b(todas|todos|todo|mis|las|los)\b", norm))
        return ("cancelar_alarma", {"todas": todas, "numero": int(m.group(2)) if m.group(2) else None})
    m = _R_POSPONER.match(norm)
    if m:
        if _ultima_sonada is None:
            return None          # no hay alarma sonando: no hay nada que posponer
        return ("posponer_alarma", {"segundos": _segundos_posponer(m.group(1) or m.group(2) or "")})

    # crear: tiene que haber una hora o duracion Y una palabra de aviso
    es_temporizador = bool(re.search(r"\b(temporizador|timer|cronometro)\b", norm))
    es_alarma = bool(re.search(r"\b(alarma|despiertame)\b", norm))
    es_aviso = bool(re.match(r"^(?:por favor )?(?:avisame|recuerdame|recordame|dime)\b", norm))
    if not (es_temporizador or es_alarma or es_aviso):
        return None
    p = parsear(comando, ahora)
    if p is None:
        return ("falta_hora", {"tipo": "temporizador" if es_temporizador else "alarma" if es_alarma else "aviso"}) \
            if (es_temporizador or es_alarma) else None
    texto = _texto_del_aviso(p["resto"])
    if es_temporizador:
        tipo = "temporizador"
    elif es_alarma and not texto:
        tipo = "alarma"
    else:
        tipo = "aviso"
    if tipo == "aviso" and not texto:
        texto = "Tenías un aviso pendiente."
    return ("crear_alarma", {"cuando": p["cuando"], "texto": texto, "tipo": tipo})


def manejar(comando, ahora=None):
    """Ejecuta el comando de alarmas. (intencion, contenido) o None."""
    cual = interpretar(comando, ahora)
    if cual is None:
        return None
    intencion, datos = cual

    if intencion == "crear_alarma":
        a = agregar(datos["cuando"], datos["texto"], datos["tipo"])
        iniciar_vigilante()
        _aviso_creado(a)
        return ({"alarma": "poner_alarma", "temporizador": "poner_temporizador"}.get(a["tipo"], "crear_aviso"),
                a["texto"])
    if intencion == "falta_hora":
        _msg("¿Para cuándo? Dime algo como 'a las 7' o 'en 20 minutos'.")
        return ("poner_alarma", None)
    if intencion == "ver_alarmas":
        lista = pendientes()
        if not lista:
            _msg("No tienes alarmas ni avisos pendientes.")
        else:
            lineas = [f"{i}. {_nombre_para_mostrar(a)} — {describir_cuando(_fecha(a))}"
                      for i, a in enumerate(lista, start=1)]
            _msg("Esto tienes pendiente:\n" + "\n".join(lineas))
        return ("ver_alarmas", None)
    if intencion == "cancelar_alarma":
        lista = pendientes()
        if not lista:
            _msg("No hay nada pendiente que cancelar.")
        elif datos["numero"]:
            n = datos["numero"]
            if 1 <= n <= len(lista):
                _marcar({lista[n - 1]["id"]}, "cancelada")
                _msg(f"Cancelé: {_nombre_para_mostrar(lista[n - 1])}.")
            else:
                _msg(f"No tienes una número {n}. Mira 'mis alarmas'.")
        elif datos["todas"]:
            _marcar({a["id"] for a in lista}, "cancelada")
            _msg(f"Listo, cancelé {len(lista)} pendiente(s).")
        else:
            proxima = lista[0]
            _marcar({proxima["id"]}, "cancelada")
            _msg(f"Cancelé la próxima: {_nombre_para_mostrar(proxima)} ({describir_cuando(_fecha(proxima))}).")
        return ("cancelar_todas_alarmas" if datos["todas"] and not datos["numero"] else "cancelar_alarma", None)
    if intencion == "posponer_alarma":
        base = _ultima_sonada or {}
        cuando = (ahora or datetime.now()) + timedelta(seconds=datos["segundos"])
        a = agregar(cuando, base.get("texto", ""), base.get("tipo", "aviso"))
        iniciar_vigilante()
        _msg(f"Pospuesto: vuelve a sonar {describir_cuando(_fecha(a), ahora)}.")
        return ("posponer_alarma", None)
    return (intencion, datos)