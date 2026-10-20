"""
bloques_ext.py
--------------
Ubicacion: Arche/core/interfaz/bloques_ext.py

Las piezas con las que se arman los widgets de las extensiones. Un widget de
extension es una lista de BLOQUES (texto, botones, lista, temporizador, reloj,
datos de Arché...). Aqui viven los bloques de fabrica y las FUENTES de datos
(lo que Arché sabe de si misma: estado de las redes, frases que no entendio...).

Para agregar un bloque o una fuente nueva NO hay que tocar la ventana:

    registrar_bloque("mi_bloque", validar, alto, dibujar, permisos=(), ayuda="...")
    registrar_fuente("mi_fuente", funcion, permisos=("datos",), ayuda="...")

  validar(b, ext)                      -> (True, bloque_limpio) | (False, motivo)
  alto(v, b, ext, ancho, esc)          -> alto en pixeles que ocupa
  dibujar(v, b, ext, idx, x, y, w, esc)
  funcion(v, ext, max)                 -> {"filas": [(texto, color, [(chip, accion)])], "botones": [(texto, accion)]}

Se pueden registrar desde un archivo .py en core/interfaz/complementos (ver
extensiones.py). Las extensiones (.json) siguen siendo solo datos: usan estos
bloques, no pueden traer codigo propio.

Todo lo que lee disco (telemetria, archivos .txt) va en cache corta: se dibuja
en cada cuadro de la ventana y no puede costar nada.
"""

import datetime
import json
import math
import os
import re
import threading
import time

from . import en_vivo, tema

try:
    from core.rutas import DATABASE
except Exception:
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Database")

CARPETA = os.path.join(DATABASE, "extensiones")
_ARCHIVO_ESTADO = os.path.join(CARPETA, "_estado.json")
_lock = threading.RLock()

BLOQUES = {}        # nombre -> {"validar", "alto", "dibujar", "permisos", "ayuda"}
FUENTES = {}        # nombre -> {"fn", "permisos", "ayuda"}


def registrar_bloque(nombre, validar, alto, dibujar, permisos=(), ayuda=""):
    BLOQUES[nombre] = {"validar": validar, "alto": alto, "dibujar": dibujar, "permisos": tuple(permisos), "ayuda": ayuda}


def registrar_fuente(nombre, fn, permisos=("datos",), ayuda=""):
    FUENTES[nombre] = {"fn": fn, "permisos": tuple(permisos), "ayuda": ayuda}


# ------------------------------------------------------------------ estado propio de las extensiones
def _leer_estado():
    try:
        with open(_ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def estado_get(ext, clave, defecto=None):
    with _lock:
        return _leer_estado().get(ext, {}).get(clave, defecto)


def estado_set(ext, clave, valor):
    with _lock:
        d = _leer_estado()
        d.setdefault(ext, {})[clave] = valor
        try:
            os.makedirs(CARPETA, exist_ok=True)
            tmp = _ARCHIVO_ESTADO + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1, ensure_ascii=False)
            os.replace(tmp, _ARCHIVO_ESTADO)
        except OSError:
            pass


def estado_borrar(ext):
    with _lock:
        d = _leer_estado()
        if d.pop(ext, None) is not None:
            try:
                with open(_ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
                    json.dump(d, f, indent=1, ensure_ascii=False)
            except OSError:
                pass


# ------------------------------------------------------------------ utilidades
_COLORES = ("texto", "tenue", "azul", "morado", "rojo", "ok", "atencion", "alerta")


def _col(nombre):
    return {"texto": tema.TEXTO, "tenue": tema.TENUE, "azul": tema.AZUL_CLARO, "morado": tema.MORADO_CLARO,
            "rojo": tema.ROJO_CLARO, "ok": tema.OK, "atencion": tema.ATENCION, "alerta": tema.ALERTA}.get(nombre or "texto", tema.TEXTO)


_cache = {}


def _memo(clave, ttl, fn):
    ahora = time.time()
    c = _cache.get(clave)
    if c and ahora - c[0] < ttl:
        return c[1]
    try:
        v = fn()
    except Exception:
        v = c[1] if c else None
    _cache[clave] = (ahora, v)
    return v


def _lineas_archivo(ext, archivo):
    """Lineas utiles de un .txt que viaja junto a la extension (sin vacias ni #comentarios)."""
    ruta = os.path.join(ext.get("carpeta") or CARPETA, archivo)

    def leer():
        try:
            mt = os.path.getmtime(ruta)
        except OSError:
            return None
        with open(ruta, "r", encoding="utf-8") as f:
            return [l.strip() for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith("#")][:300]
    return _memo("txt:" + ruta, 2.0, leer)


def _recortar(v, texto, ancho, tam=9):
    maxc = max(4, int(ancho / (tam * v._esc() * 0.6)))
    return texto if len(texto) <= maxc else texto[:maxc - 1] + "…"


def _ok_txt(b, ext, clave="archivo"):
    a = b.get(clave)
    if not a or os.path.basename(str(a)) != str(a) or not str(a).endswith(".txt"):
        return False
    return True


# ------------------------------------------------------------------ bloque: texto
def _v_texto(b, ext):
    t = str(b.get("texto") or "").strip()[:240]
    if not t:
        return False, "el bloque «texto» no trae texto"
    tam = b.get("tam", 9)
    tam = tam if isinstance(tam, int) and 7 <= tam <= 28 else 9
    col = b.get("color") if b.get("color") in _COLORES else "texto"
    return True, {"tipo": "texto", "texto": t, "tam": tam, "color": col}


def _a_texto(v, b, ext, w, esc):
    lineas = 1 + int(len(b["texto"]) * b["tam"] * 0.6 * esc // max(60, w))
    return (lineas * (b["tam"] + 5) + 4) * esc


def _d_texto(v, b, ext, idx, x, y, w, esc):
    v._texto(x, y + 2 * esc, b["texto"], b["tam"], _col(b["color"]), ancho=int(w), negrita=b["tam"] >= 16)


registrar_bloque("texto", _v_texto, _a_texto, _d_texto, ayuda='{"tipo":"texto","texto":"…","tam":9,"color":"texto|tenue|azul|morado|rojo|ok|atencion|alerta"}')


# ------------------------------------------------------------------ bloque: botones
def _v_botones(b, ext):
    bs = []
    for x in b.get("botones") or []:
        if isinstance(x, dict) and x.get("orden") and x.get("texto"):
            bs.append({"texto": str(x["texto"])[:20], "orden": str(x["orden"])[:120]})
    if not bs:
        return False, "el bloque «botones» no trae botones"
    return True, {"tipo": "botones", "botones": bs[:12], "grande": bool(b.get("grande"))}


def _filas_botones(b, w, esc):
    filas, x = 1, 0.0
    for x_ in b["botones"]:
        a = ((len(x_["texto"]) * 7.2 + 28) if b["grande"] else (len(x_["texto"]) * 6.6 + 20)) * esc
        if x > 0 and x + a > w:
            filas += 1
            x = 0.0
        x += a + 6 * esc
    return filas


def _a_botones(v, b, ext, w, esc):
    return _filas_botones(b, w, esc) * (34 if b["grande"] else 28) * esc


def _d_botones(v, b, ext, idx, x, y, w, esc):
    cx, fila = 0.0, 0
    for x_ in b["botones"]:
        if b["grande"]:
            a = (len(x_["texto"]) * 7.2 + 28) * esc
        else:
            a = (len(x_["texto"]) * 6.6 + 20) * esc
        if cx > 0 and cx + a > w:
            fila += 1
            cx = 0.0
        if b["grande"]:
            v._boton(x + cx + a, y + fila * 34 * esc + 28 * esc, x_["texto"], ("orden", x_["orden"]), tema.MORADO_CLARO)
        else:
            v._chip(x + cx, y + fila * 28 * esc, x_["texto"], ("orden", x_["orden"]), False, tema.MORADO_CLARO, a)
        cx += a + 6 * esc


registrar_bloque("botones", _v_botones, _a_botones, _d_botones, permisos=("comandos",),
                 ayuda='{"tipo":"botones","botones":[{"texto":"Luz","orden":"enciende la luz"}],"grande":false}')


# ------------------------------------------------------------------ bloque: lista (pendientes) desde un .txt
def _v_lista(b, ext):
    if not _ok_txt(b, ext):
        return False, "el bloque «lista» necesita un «archivo» .txt junto a la extensión"
    mx = b.get("max", 6)
    return True, {"tipo": "lista", "archivo": b["archivo"], "marcable": bool(b.get("marcable", True)),
                  "max": mx if isinstance(mx, int) and 1 <= mx <= 20 else 6}


def _a_lista(v, b, ext, w, esc):
    n = len(_lineas_archivo(ext, b["archivo"]) or [None])
    return (min(n, b["max"]) + (1 if n > b["max"] else 0)) * 19 * esc + 4 * esc


def _d_lista(v, b, ext, idx, x, y, w, esc):
    lineas = _lineas_archivo(ext, b["archivo"])
    if lineas is None:
        v._texto(x, y + 8 * esc, f"No encuentro {b['archivo']}.", 9, tema.TENUE)
        return
    if not lineas:
        v._texto(x, y + 8 * esc, "La lista está vacía.", 9, tema.TENUE)
        return
    hechos = set(estado_get(ext["nombre"], "hechos:" + b["archivo"], []))
    for i, t in enumerate(lineas[:b["max"]]):
        yy = y + i * 19 * esc
        hecho = t in hechos
        v._redondo(x, yy + 3 * esc, x + 13 * esc, yy + 16 * esc, 3 * esc, fill=tema.OK if hecho else tema.PANEL_2, outline=tema.BORDE)
        if hecho:
            v._texto(x + 6.5 * esc, yy + 10 * esc, "✔", 8, tema.FONDO if hasattr(tema, "FONDO") else tema.TEXTO, ancla="center")
        v._texto(x + 20 * esc, yy + 10 * esc, _recortar(v, t, w - 20 * esc), 9, tema.TENUE if hecho else tema.TEXTO)
        if b["marcable"]:
            v.zonas.append((x, yy, x + w, yy + 19 * esc, ("ext", "marcar", ext["nombre"], b["archivo"], t)))
    if len(lineas) > b["max"]:
        v._texto(x, y + b["max"] * 19 * esc + 9 * esc, f"+{len(lineas) - b['max']} más", 8, tema.TENUE)


registrar_bloque("lista", _v_lista, _a_lista, _d_lista, permisos=("archivos_propios",),
                 ayuda='{"tipo":"lista","archivo":"pendientes.txt","marcable":true,"max":6}  (una tarea por línea; tocar marca hecho)')


# ------------------------------------------------------------------ bloque: temporizador (pomodoro)
_temps = {}


def _clave_t(ext, idx):
    return f"{ext}#{idx}"


def _v_temp(b, ext):
    m, d = b.get("minutos", 25), b.get("descanso", 5)
    if not (isinstance(m, int) and 1 <= m <= 240 and isinstance(d, int) and 0 <= d <= 120):
        return False, "«minutos» va de 1 a 240 y «descanso» de 0 a 120"
    return True, {"tipo": "temporizador", "minutos": m, "descanso": d, "etiqueta": str(b.get("etiqueta") or "Temporizador")[:24]}


def _estado_temp(ext, idx, b):
    return _temps.setdefault(_clave_t(ext["nombre"], idx), {"fase": "trabajo", "resta": b["minutos"] * 60.0, "fin": None})


def _tick_temp(ext, idx, b):
    t = _estado_temp(ext, idx, b)
    if t["fin"] is not None:
        resta = t["fin"] - time.time()
        if resta <= 0:
            if t["fase"] == "trabajo" and b["descanso"]:
                t["fase"], dur = "descanso", b["descanso"] * 60.0
                en_vivo.avisar(f"{b['etiqueta']}: ¡a descansar {b['descanso']} min!", "exito")
            else:
                t["fase"], dur = "trabajo", b["minutos"] * 60.0
                en_vivo.avisar(f"{b['etiqueta']}: terminó" + (" el descanso." if b["descanso"] else "."), "exito")
            t["resta"], t["fin"] = dur, None
        else:
            t["resta"] = resta
    return t


def _a_temp(v, b, ext, w, esc):
    return 92 * esc


def _d_temp(v, b, ext, idx, x, y, w, esc):
    t = _tick_temp(ext, idx, b)
    corriendo = t["fin"] is not None
    seg = int(math.ceil(t["resta"]))
    v._texto(x, y + 8 * esc, f"{b['etiqueta']} · {'trabajo' if t['fase'] == 'trabajo' else 'descanso'}", 9, tema.TENUE)
    v._texto(x, y + 38 * esc, f"{seg // 60:02d}:{seg % 60:02d}", 28, tema.OK if t["fase"] == "descanso" else tema.TEXTO, negrita=True)
    v._chip(x, y + 64 * esc, "Pausar" if corriendo else "Iniciar", ("ext", "temp", ext["nombre"], idx, "alternar"), corriendo, tema.MORADO_CLARO, 78 * esc)
    v._chip(x + 86 * esc, y + 64 * esc, "Reiniciar", ("ext", "temp", ext["nombre"], idx, "reiniciar"), False, None, 82 * esc)


registrar_bloque("temporizador", _v_temp, _a_temp, _d_temp,
                 ayuda='{"tipo":"temporizador","minutos":25,"descanso":5,"etiqueta":"Pomodoro"}  (avisa al terminar cada tramo)')


# ------------------------------------------------------------------ bloque: reloj mundial
_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _hora_en(tz):
    tz = str(tz).strip()
    m = re.fullmatch(r"(?i)(?:utc|gmt)\s*([+-]\d{1,2})(?::?(\d{2}))?", tz)
    ahora = datetime.datetime.now(datetime.timezone.utc)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0) * (1 if h >= 0 else -1)
        return ahora.astimezone(datetime.timezone(datetime.timedelta(hours=h, minutes=mi)))
    from zoneinfo import ZoneInfo
    return ahora.astimezone(ZoneInfo(tz))


def _v_reloj(b, ext):
    zs = []
    for z in b.get("zonas") or []:
        if isinstance(z, dict) and z.get("tz"):
            zs.append({"nombre": str(z.get("nombre") or z["tz"])[:20], "tz": str(z["tz"])[:40]})
    if not zs:
        return False, "el bloque «reloj» necesita «zonas»: [{\"nombre\":\"Bogotá\",\"tz\":\"America/Bogota\"}]"
    return True, {"tipo": "reloj", "zonas": zs[:6]}


def _a_reloj(v, b, ext, w, esc):
    return len(b["zonas"]) * 24 * esc + 4 * esc


def _d_reloj(v, b, ext, idx, x, y, w, esc):
    for i, z in enumerate(b["zonas"]):
        yy = y + i * 24 * esc
        try:
            h = _hora_en(z["tz"])
            hora, dia = h.strftime("%H:%M"), f"{_DIAS[h.weekday()]} {h.day}"
        except Exception:
            hora, dia = "—", "sin datos de zona (instala tzdata)"
        v._texto(x, yy + 12 * esc, z["nombre"], 10, tema.TEXTO)
        v._texto(x + w, yy + 12 * esc, f"{dia}  {hora}", 10, tema.MORADO_CLARO, ancla="e", negrita=True)


registrar_bloque("reloj", _v_reloj, _a_reloj, _d_reloj,
                 ayuda='{"tipo":"reloj","zonas":[{"nombre":"Bogotá","tz":"America/Bogota"},{"nombre":"Madrid","tz":"UTC+1"}]}')


# ------------------------------------------------------------------ bloque: frase del dia
def _v_frase(b, ext):
    if b.get("archivo"):
        if not _ok_txt(b, ext):
            return False, "«archivo» debe ser un .txt junto a la extensión"
        return True, {"tipo": "frase_del_dia", "archivo": b["archivo"], "frases": []}
    fr = [str(f)[:160] for f in (b.get("frases") or []) if str(f).strip()][:60]
    if not fr:
        return False, "el bloque «frase_del_dia» necesita «frases» o un «archivo»"
    return True, {"tipo": "frase_del_dia", "archivo": "", "frases": fr}


def _frase_de_hoy(ext, b):
    fr = _lineas_archivo(ext, b["archivo"]) if b["archivo"] else b["frases"]
    if not fr:
        return None
    return fr[datetime.date.today().toordinal() % len(fr)]


def _a_frase(v, b, ext, w, esc):
    f = _frase_de_hoy(ext, b) or "x"
    return (1 + int(len(f) * 9 * 0.6 * esc // max(60, w))) * 14 * esc + 14 * esc


def _d_frase(v, b, ext, idx, x, y, w, esc):
    f = _frase_de_hoy(ext, b)
    v._texto(x, y + 4 * esc, "FRASE DEL DÍA", 7, tema.TENUE, negrita=True)
    v._texto(x, y + 18 * esc, f or "Aún no hay frases.", 9, tema.TEXTO, ancho=int(w))


registrar_bloque("frase_del_dia", _v_frase, _a_frase, _d_frase, ayuda='{"tipo":"frase_del_dia","frases":["…"]}  o  {"archivo":"frases.txt"}  (una distinta cada día)')


# ------------------------------------------------------------------ bloque: suma (gastos)
def _numero(txt):
    t = txt.replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    return float(t)


def _parsear_gastos(lineas):
    sal = []
    for l in lineas:
        fecha = None
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(.*)", l)
        if m:
            fecha, l = m.group(1), m.group(2)
        m = re.match(r"(.*?)[:\s]\s*(-?[\d.,]+)\s*$", l)
        if not m:
            continue
        try:
            sal.append((fecha, m.group(1).strip(" :-") or "(sin nombre)", _numero(m.group(2))))
        except ValueError:
            continue
    return sal


def _v_suma(b, ext):
    if not _ok_txt(b, ext):
        return False, "el bloque «suma» necesita un «archivo» .txt (líneas como «almuerzo: 12000»)"
    return True, {"tipo": "suma", "archivo": b["archivo"], "moneda": str(b.get("moneda") or "$")[:4]}


def _fmt_monto(x, mon):
    return f"{mon}{x:,.0f}".replace(",", ".") if abs(x - round(x)) < 0.005 else f"{mon}{x:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _a_suma(v, b, ext, w, esc):
    return 86 * esc


def _d_suma(v, b, ext, idx, x, y, w, esc):
    lineas = _lineas_archivo(ext, b["archivo"])
    if lineas is None:
        v._texto(x, y + 8 * esc, f"No encuentro {b['archivo']}.", 9, tema.TENUE)
        return
    datos = _parsear_gastos(lineas)
    total = sum(m for _f, _n, m in datos)
    hoy = datetime.date.today().isoformat()
    hoy_total = sum(m for f, _n, m in datos if f == hoy)
    v._texto(x, y + 10 * esc, "TOTAL", 7, tema.TENUE, negrita=True)
    v._texto(x, y + 28 * esc, _fmt_monto(total, b["moneda"]), 16, tema.TEXTO, negrita=True)
    if any(f for f, _n, _m in datos):
        v._texto(x + w, y + 28 * esc, "hoy " + _fmt_monto(hoy_total, b["moneda"]), 10, tema.MORADO_CLARO, ancla="e")
    for i, (_f, n, m) in enumerate(datos[-2:][::-1]):
        v._texto(x, y + 50 * esc + i * 15 * esc, _recortar(v, n, w - 80 * esc, 8), 8, tema.TENUE)
        v._texto(x + w, y + 50 * esc + i * 15 * esc, _fmt_monto(m, b["moneda"]), 8, tema.TENUE, ancla="e")


registrar_bloque("suma", _v_suma, _a_suma, _d_suma, permisos=("archivos_propios",),
                 ayuda='{"tipo":"suma","archivo":"gastos.txt","moneda":"$"}  (líneas «almuerzo: 12000» o «2026-10-14 almuerzo 12.000»)')


# ------------------------------------------------------------------ bloque: fechas (cumpleaños)
def _proximas(lineas, hoy, n=4, dias=90):
    sal = []
    for l in lineas:
        m = re.match(r"(\d{1,2})[-/](\d{1,2})\s+(.+)", l)
        if not m:
            continue
        d, mes = int(m.group(1)), int(m.group(2))
        for anio in (hoy.year, hoy.year + 1):
            try:
                f = datetime.date(anio, mes, d)
            except ValueError:
                break
            if f >= hoy:
                if (f - hoy).days <= dias:
                    sal.append(((f - hoy).days, m.group(3).strip()))
                break
    return sorted(sal)[:n]


def _v_fechas(b, ext):
    if not _ok_txt(b, ext):
        return False, "el bloque «fechas» necesita un «archivo» .txt (líneas como «14-10 Cumpleaños de Ana»)"
    return True, {"tipo": "fechas", "archivo": b["archivo"]}


def _a_fechas(v, b, ext, w, esc):
    n = len(_proximas(_lineas_archivo(ext, b["archivo"]) or [], datetime.date.today())) or 1
    return n * 19 * esc + 4 * esc


def _d_fechas(v, b, ext, idx, x, y, w, esc):
    lineas = _lineas_archivo(ext, b["archivo"])
    if lineas is None:
        v._texto(x, y + 8 * esc, f"No encuentro {b['archivo']}.", 9, tema.TENUE)
        return
    prox = _proximas(lineas, datetime.date.today())
    if not prox:
        v._texto(x, y + 8 * esc, "Nada en los próximos 90 días.", 9, tema.TENUE)
        return
    for i, (dias, nombre) in enumerate(prox):
        yy = y + i * 19 * esc
        cuando = "hoy" if dias == 0 else ("mañana" if dias == 1 else f"en {dias} días")
        v._texto(x, yy + 10 * esc, _recortar(v, nombre, w - 90 * esc), 9, tema.TEXTO)
        v._texto(x + w, yy + 10 * esc, cuando, 9, tema.ATENCION if dias <= 1 else tema.MORADO_CLARO, ancla="e")


registrar_bloque("fechas", _v_fechas, _a_fechas, _d_fechas, permisos=("archivos_propios",),
                 ayuda='{"tipo":"fechas","archivo":"fechas.txt"}  (líneas «DD-MM Nombre»; muestra las próximas)')


# ------------------------------------------------------------------ bloque: indicador de estado grande
_ESTADOS = {"reposo": ("En reposo", "ok"), "escuchando": ("Escuchando", "azul"), "pensando": ("Pensando…", "atencion"),
            "hablando": ("Hablando", "morado")}


def _v_ind(b, ext):
    return True, {"tipo": "indicador"}


def _a_ind(v, b, ext, w, esc):
    return 74 * esc


def _d_ind(v, b, ext, idx, x, y, w, esc):
    est = en_vivo.estado_visual()
    txt, col = _ESTADOS.get(est, (est, "texto"))
    r = 26 * esc
    c = _col(col)
    v.canvas.create_oval(x + 4 * esc, y + 6 * esc, x + 4 * esc + 2 * r, y + 6 * esc + 2 * r, fill=c, outline="", tags=v._tag)
    v._texto(x + 2 * r + 20 * esc, y + 6 * esc + r, txt, 18, tema.TEXTO, negrita=True)


registrar_bloque("indicador", _v_ind, _a_ind, _d_ind, permisos=("datos",),
                 ayuda='{"tipo":"indicador"}  (círculo grande del estado de Arché: reposo, escuchando, pensando, hablando)')


# ------------------------------------------------------------------ bloque: dato (lo que Arché sabe de si misma)
def _v_dato(b, ext):
    f = b.get("fuente")
    if f not in FUENTES:
        return False, f"fuente desconocida «{f}» (las que hay: {', '.join(FUENTES)})"
    mx = b.get("max", 5)
    return True, {"tipo": "dato", "fuente": f, "max": mx if isinstance(mx, int) and 1 <= mx <= 12 else 5}


def _datos(v, b, ext):
    try:
        r = FUENTES[b["fuente"]]["fn"](v, ext, b["max"]) or {}
    except Exception as e:
        r = {"filas": [(f"No pude leer esos datos ({type(e).__name__}).", "tenue", [])]}
    return r.get("filas", []), r.get("botones", [])


def _a_dato(v, b, ext, w, esc):
    filas, botones = _datos(v, b, ext)
    return (max(1, len(filas)) * 21 + (30 if botones else 0)) * esc + 4 * esc


def _d_dato(v, b, ext, idx, x, y, w, esc):
    filas, botones = _datos(v, b, ext)
    if not filas:
        v._texto(x, y + 10 * esc, "Nada que mostrar todavía.", 9, tema.TENUE)
    for i, (texto, color, chips) in enumerate(filas):
        yy = y + i * 21 * esc
        ancho_chips = sum((len(c[0]) * 6.6 + 16) * esc + 4 * esc for c in chips)
        v._texto(x, yy + 11 * esc, _recortar(v, texto, w - ancho_chips - 6 * esc, 9), 9, _col(color))
        cx = x + w
        for etq, acc in reversed(chips):
            a = (len(etq) * 6.6 + 16) * esc
            cx -= a
            v._chip(cx, yy + 1 * esc, etq, acc, False, None, a)
            cx -= 4 * esc
    if botones:
        yy = y + max(1, len(filas)) * 21 * esc + 6 * esc
        cx = x
        for etq, acc in botones:
            a = (len(etq) * 6.6 + 20) * esc
            v._chip(cx, yy, etq, acc, False, tema.MORADO_CLARO, a)
            cx += a + 6 * esc


registrar_bloque("dato", _v_dato, _a_dato, _d_dato, ayuda='{"tipo":"dato","fuente":"redes_salud","max":5}  (fuentes: ver LEEME.md)')


# ------------------------------------------------------------------ telemetria (lo que Arché entendio)
def _telemetria():
    """Ultimos comandos registrados en core/IA/telemetria.jsonl: [{comando, intencion, resuelto_por, fallo, timestamp}]."""
    def leer():
        from core.IA import telemetria
        ruta = telemetria.ARCHIVO_LOG
        if not os.path.exists(ruta):
            return []
        with open(ruta, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            datos = f.read().decode("utf-8", "ignore").splitlines()
        sal = []
        for l in datos:
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("tipo") == "comando":
                sal.append(e)
        return sal
    return _memo("telemetria", 5.0, leer) or []


def _ignoradas():
    return set(estado_get("_global", "ignoradas", []))


def _norm(t):
    return re.sub(r"\s+", " ", str(t).lower()).strip()


_VIA = {"determinístico": "regla fija (sin red neuronal)", "determinístico": "regla fija (sin red neuronal)",
        "plantilla": "plantilla aprendida", "similitud_caracteres": "parecido de letras",
        "embeddings": "significado (embeddings)", "clasificador": "red neuronal", "ollama": "IA externa (nube/Ollama)",
        "cache_propio": "respuesta guardada", "pregunta_frecuente": "pregunta frecuente",
        "cache_respuestas": "respuesta guardada", "ollama_sin_respuesta": "IA externa sin respuesta"}


# ------------------------------------------------------------------ fuentes de datos
def _f_redes_salud(v, ext, n):
    from . import redes
    s = redes.snapshot()
    if not s["listo"]:
        return {"filas": [("Leyendo las redes…", "tenue", [])]}
    rs = [r for r in s["redes"] if r["entrenada"] or r["entrenable"]]
    rs.sort(key=lambda r: (-r["pendientes"], r["precision"]))
    filas = []
    for r in rs[:n]:
        pend = f" · +{r['pendientes']} sin entrenar" if r["pendientes"] else ""
        filas.append((f"{r['nombre']} · {r['precision'] * 100:.0f}%{pend}" if r["entrenada"] else f"{r['nombre']} · sin entrenar",
                      "atencion" if r["pendientes"] or not r["entrenada"] else "texto", []))
    if not filas:
        filas = [("Ninguna red tiene ejemplos suficientes todavía.", "tenue", [])]
    ent = redes.estado["entreno"]
    botones = [("Entrenando…" if ent["corriendo"] else "Entrenar todas", ("redes", "entrenar", "todas")), ("Vista grande", ("redes", "abrir"))]
    return {"filas": filas, "botones": botones}


def _f_no_entendidas(v, ext, n):
    ign, vistas, filas = _ignoradas(), set(), []
    for e in reversed(_telemetria()):
        if not e.get("fallo"):
            continue
        k = _norm(e.get("comando"))
        if not k or k in ign or k in vistas:
            continue
        vistas.add(k)
        filas.append((e["comando"], "texto", [("Enseñar", ("ext", "ensenar", e["comando"])), ("✕", ("ext", "ignorar", e["comando"]))]))
        if len(filas) >= n:
            break
    return {"filas": filas or [("No hay frases sin entender. ✔", "tenue", [])]}


def _f_dudosas(v, ext, n):
    ign, vistas, filas, corte = _ignoradas(), set(), [], time.time() - 7 * 86400
    from . import redes
    ids = None
    try:
        ids = redes._ia().cat.POR_ID
    except Exception:
        pass
    for e in reversed(_telemetria()):
        if e.get("fallo") or "ollama" not in str(e.get("resuelto_por", "")) or e.get("timestamp", 0) < corte:
            continue
        k = _norm(e.get("comando"))
        if not k or k in ign or k in vistas or e.get("intencion") in (None, "conversar", "desconocido"):
            continue
        vistas.add(k)
        chips = [("Aprender", ("ext", "aprender", e["comando"], e["intencion"]))] if (ids is None or e["intencion"] in ids) else []
        filas.append((f"{e['comando']} → {e['intencion']}", "texto", chips + [("✕", ("ext", "ignorar", e["comando"]))]))
        if len(filas) >= n:
            break
    return {"filas": filas or [("Nada dudoso esta semana. ✔", "tenue", [])]}


def _f_revision(v, ext, n):
    from . import redes
    rec = redes.recientes_auto(n)
    filas = [(f"{r['pregunta']} → {r['accion']}", "texto",
              [("✔", ("ext", "revisar", r["pregunta"], r["accion"], True)), ("✘", ("ext", "revisar", r["pregunta"], r["accion"], False))])
             for r in rec]
    return {"filas": filas or [("No hay ejemplos automáticos por revisar. ✔", "tenue", [])]}


def _f_explica(v, ext, n):
    from . import redes
    if not en_vivo.intenciones:
        return {"filas": [("Dime algo y te explico cómo lo entendí.", "tenue", [])]}
    ult = en_vivo.intenciones[-1]
    filas = [(f"«{ult['cmd']}»", "texto", []),
             (f"→ {ult['intencion']} · por {_VIA.get(ult['via'], ult['via'] or 'desconocido')}" + (f" · {ult['seg']} s" if ult.get("seg") else ""), "morado", [])]
    p = redes.estado["prueba"]
    if p and p.get("frase") == ult["cmd"] and p.get("pasos"):
        filas.append(("   " + "  →  ".join(f"{s['etiqueta']} {s['confianza'] * 100:.0f}%" for s in p["pasos"]), "azul", []))
    elif redes.estado["probando"]:
        filas.append(("   Calculando las neuronas…", "tenue", []))
    return {"filas": filas[:max(3, n)], "botones": [("Ver el detalle de la red", ("ext", "explicar", ult["cmd"]))]}


def _f_mas_usadas(v, ext, n):
    from collections import Counter
    c = Counter()
    for e in _telemetria():
        if e.get("intencion") in ("conversar", "desconocido") or not e.get("comando"):
            continue
        c[_norm(e["comando"])] += 1
    filas = [(f"{k}  ×{q}", "texto", [("Repetir", ("orden", k))]) for k, q in c.most_common(n)]
    return {"filas": filas or [("Aún no hay órdenes registradas.", "tenue", [])]}


def _f_nube(v, ext, n):
    filas = []
    try:
        from core.IA import nube
        filas.append((f"Proveedor: {nube.proveedor()} · modo {nube.modo()}", "texto", []))
        uso = nube.ultimo_uso()
        if uso.get("proveedor"):
            filas.append((f"Última respuesta: {uso['proveedor']}" + (f" ({uso['aviso']})" if uso.get("aviso") else ""), "tenue", []))
    except Exception:
        filas.append(("No pude leer la configuración de la nube.", "tenue", []))
    hoy = time.mktime(datetime.date.today().timetuple())
    ev = [e for e in _telemetria() if e.get("timestamp", 0) >= hoy and "ollama" in str(e.get("resuelto_por", ""))]
    filas.append((f"Consultas a la IA externa hoy: {len(ev)}", "atencion" if len(ev) > 100 else "texto", []))
    sin = sum(1 for e in ev if e.get("resuelto_por") == "ollama_sin_respuesta")
    if sin:
        filas.append((f"Sin respuesta: {sin}", "alerta", []))
    filas.append(("El límite de tu proveedor no se puede leer desde aquí.", "tenue", []))
    return {"filas": filas}


def _f_errores(v, ext, n):
    ev = [e for e in list(v.eventos)[::-1] if e[1] in ("error", "aviso")][:n]
    return {"filas": [(f"{time.strftime('%H:%M', time.localtime(t))}  {txt}", "alerta" if tp == "error" else "atencion", []) for t, tp, txt in ev]
            or [("Sin errores recientes. ✔", "tenue", [])]}


def _f_temperatura(v, ext, n):
    filas = []
    try:
        import psutil
        temp = None
        if hasattr(psutil, "sensors_temperatures"):
            st = psutil.sensors_temperatures() or {}
            vals = [t.current for lst in st.values() for t in lst if t.current]
            temp = max(vals) if vals else None
        if temp is None:
            filas.append(("Temperatura: no disponible en este equipo", "tenue", []))
        else:
            filas.append((f"Temperatura: {temp:.0f} °C" + (" · ¡se calienta!" if temp >= 75 else ""), "alerta" if temp >= 75 else ("atencion" if temp >= 65 else "ok"), []))
        filas.append((f"CPU {psutil.cpu_percent():.0f}% · RAM {psutil.virtual_memory().percent:.0f}%", "texto", []))
    except Exception:
        filas.append(("No puedo leer el equipo (falta psutil).", "tenue", []))
    return {"filas": filas}


registrar_fuente("redes_salud", _f_redes_salud, ayuda="precisión de cada red, cuáles tienen ejemplos sin entrenar, botón de entrenar")
registrar_fuente("no_entendidas", _f_no_entendidas, ayuda="órdenes que Arché no entendió; «Enseñar» deja que ella decida la intención")
registrar_fuente("dudosas", _f_dudosas, ayuda="órdenes de la semana que solo resolvió la IA externa; «Aprender» las guarda con la intención que dijo")
registrar_fuente("revision", _f_revision, ayuda="ejemplos que Arché agregó sola, con ✔ / ✘ para revisarlos")
registrar_fuente("explica", _f_explica, ayuda="cómo entendió tu última orden (intención, capa que decidió, confianza)")
registrar_fuente("mas_usadas", _f_mas_usadas, permisos=("datos", "comandos"), ayuda="tus órdenes más repetidas, con botón «Repetir»")
registrar_fuente("nube", _f_nube, ayuda="proveedor de la nube y cuántas consultas hizo hoy")
registrar_fuente("errores", _f_errores, ayuda="errores y avisos recientes de la ventana")
registrar_fuente("temperatura", _f_temperatura, ayuda="temperatura, CPU y RAM (útil en Raspberry Pi)")


# ------------------------------------------------------------------ acciones de los bloques
def accion(v, a):
    """('ext', sub, ...) desde un boton de un bloque. Devuelve True si la atendio."""
    sub = a[1] if len(a) > 1 else ""
    try:
        if sub == "marcar":
            _, _, ext, archivo, texto = a
            hechos = list(estado_get(ext, "hechos:" + archivo, []))
            hechos.remove(texto) if texto in hechos else hechos.append(texto)
            estado_set(ext, "hechos:" + archivo, hechos[-300:])
        elif sub == "temp":
            _, _, ext, idx, que = a
            t = _temps.get(_clave_t(ext, idx))
            b = _bloque_de(ext, idx)
            if t is None or b is None:
                return True
            if que == "alternar":
                if t["fin"] is None:
                    t["fin"] = time.time() + t["resta"]
                else:
                    t["resta"], t["fin"] = max(1.0, t["fin"] - time.time()), None
            else:
                t.update(fase="trabajo", resta=b["minutos"] * 60.0, fin=None)
        elif sub == "ensenar":
            from . import redes
            frase = a[2]
            redes.agregar(frase)
            _ignorar(frase)
            en_vivo.avisar(f"Clasificando «{frase}»… mira el resultado en la vista de redes.", "info")
            v._accion(("redes", "abrir"))
        elif sub == "aprender":
            from . import redes
            frase, inten = a[2], a[3]
            if redes.agregar_a(frase, inten):
                en_vivo.avisar(f"Aprendiendo «{frase}» → {inten}", "info")
            _ignorar(frase)
        elif sub == "ignorar":
            _ignorar(a[2])
        elif sub == "revisar":
            from . import redes
            redes.revisar_ejemplo(a[2], a[3], bool(a[4]))
        elif sub == "explicar":
            from . import redes
            redes.probar(a[2], None)
        else:
            return False
    except Exception as e:
        en_vivo.avisar(f"La extensión no pudo hacerlo ({type(e).__name__}).", "error")
    return True


def _ignorar(frase):
    ign = list(estado_get("_global", "ignoradas", []))
    k = _norm(frase)
    if k not in ign:
        ign.append(k)
        estado_set("_global", "ignoradas", ign[-300:])


def _bloque_de(ext, idx):
    from . import extensiones
    e = extensiones._buscar(ext)
    try:
        return e["bloques"][idx] if e else None
    except (KeyError, IndexError):
        return None
