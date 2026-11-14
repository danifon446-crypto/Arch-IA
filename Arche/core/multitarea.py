"""
multitarea.py
-------------
Ubicacion: Arche/core/multitarea.py

Deja que Arché use VARIAS HERRAMIENTAS A LA VEZ.

Antes, el bucle de main.py atendía una orden y se quedaba esperando a que
terminara: si le pedías "limpia el PC" no podías preguntarle nada más hasta
que acabara. Ahora puedes mandar órdenes a segundo plano y seguir hablando:

    en segundo plano busca archivos duplicados
    de fondo investiga sobre redes neuronales
    busca el clima en segundo plano
    a la vez: investiga sobre arduino y busca duplicados en descargas
    al mismo tiempo abre spotify y dime las noticias

Y para controlarlas:

    tareas                      -> qué está haciendo cada una
    resultado de la tarea 2     -> lo último que escribió esa tarea
    para la tarea 2             -> le pide que pare (o la saca de la fila)
    para todas las tareas
    tarea 2 sí  /  tarea 2 no   -> responder si una tarea te pide confirmación

CÓMO FUNCIONA (sin tocar ninguna herramienta)
  - main.py le pasa a configurar() la lista de herramientas: los mismos
    manejar() de cada módulo que ya usa en su bucle, en el mismo orden.
  - Cada tarea corre en su propio hilo y prueba esas herramientas en orden;
    la primera que reconoce la frase la ejecuta (igual que en primer plano).
  - Si NINGUNA herramienta la reconoce (por ejemplo una charla con Ollama),
    no se puede hacer de fondo: se le pasa al bucle normal como si la
    hubieras escrito, y te avisa.
  - Lo que imprime cada tarea sale con su etiqueta: "  [tarea 2] ...".
  - Si una tarea pregunta algo (input), NO se roba lo que escribes: te avisa
    y espera a que respondas "tarea 2 sí/no". Si no respondes en 5 minutos,
    toma "no" (lo más seguro).
  - Las herramientas que mueven el mouse/teclado/ventanas comparten la
    "pantalla": se turnan para no pelearse (una espera a la otra).
  - Máximo MAX_A_LA_VEZ tareas corriendo; las demás esperan en fila.

Las herramientas no se pueden "matar" a la fuerza (Python no lo permite sin
riesgo). "para la tarea N" la marca para parar: si estaba en la fila no
empieza; si ya corre, termina lo que estaba haciendo y su resultado se
descarta. Una herramienta que quiera parar antes puede revisar
multitarea.debe_parar() dentro de sus bucles.
"""

import builtins
import inspect
import re
import sys
import threading
import time
import unicodedata

MAX_A_LA_VEZ = 4                 # tareas corriendo al mismo tiempo
ESPERA_RESPUESTA_SEG = 300       # cuánto espera una confirmación antes de tomar "no"
LINEAS_GUARDADAS = 200           # cuántas líneas de salida recuerda cada tarea
TAREAS_TERMINADAS_A_GUARDAR = 15

# Herramientas que usan algo que no se puede compartir. Las que tienen el
# mismo recurso se turnan. (El nombre es el que se le da en configurar().)
RECURSOS = {
    "control del pc": "pantalla",
    "rutinas": "pantalla",
    "interfaz": "pantalla",
    "perro robot": "perro",
    "voz": "parlantes",
}

_herramientas = []               # [(nombre, funcion)]
_tareas = {}                     # id -> _Tarea
_por_hilo = {}                   # ident del hilo -> _Tarea
_candado = threading.RLock()
_turnos = threading.BoundedSemaphore(MAX_A_LA_VEZ)
_recursos = {}                   # recurso -> RLock
_dueno_recurso = {}              # recurso -> id de tarea que lo tiene
_siguiente_id = [1]
_instalado = {"salida": False}
_input_previo = [None]


# ------------------------------------------------------------------
# Una tarea
# ------------------------------------------------------------------

class _Tarea:
    def __init__(self, ident, orden):
        self.id = ident
        self.orden = orden
        self.estado = "en fila"          # en fila, corriendo, esperando ..., terminada, falló, cancelada
        self.herramienta = None
        self.inicio = None
        self.fin = None
        self.salida = []                 # líneas que imprimió
        self.parar = threading.Event()
        self.pregunta = None             # texto de la pregunta pendiente
        self._respuesta = None
        self._hay_respuesta = threading.Event()
        self.hilo = None

    def viva(self):
        return self.estado not in ("terminada", "falló", "cancelada", "pasada al bucle")

    def duracion(self):
        if not self.inicio:
            return 0
        return (self.fin or time.time()) - self.inicio


# ------------------------------------------------------------------
# Salida: lo que imprime cada tarea sale con su etiqueta, en líneas enteras
# ------------------------------------------------------------------

class _SalidaMultitarea:
    """Envuelve sys.stdout. El hilo principal escribe igual que siempre;
    los hilos de las tareas escriben línea por línea con "[tarea N]"."""

    def __init__(self, real):
        self._real = real
        self._pendiente = {}            # ident del hilo -> texto sin salto de línea aún
        self._lock = threading.Lock()

    def write(self, texto):
        tarea = _por_hilo.get(threading.get_ident())
        if tarea is None:
            return self._real.write(texto)
        ident = threading.get_ident()
        with self._lock:
            buf = self._pendiente.get(ident, "") + str(texto)
            lineas = buf.split("\n")
            self._pendiente[ident] = lineas.pop()
            for linea in lineas:
                self._linea(tarea, linea)
        return len(texto)

    def terminar_hilo(self, tarea):
        """Al terminar una tarea, saca lo que haya quedado sin salto de línea."""
        ident = threading.get_ident()
        with self._lock:
            resto = self._pendiente.pop(ident, "")
            if resto.strip():
                self._linea(tarea, resto)

    def _linea(self, tarea, linea):
        if not linea.strip():
            return
        tarea.salida.append(linea)
        if len(tarea.salida) > LINEAS_GUARDADAS:
            del tarea.salida[:-LINEAS_GUARDADAS]
        if tarea.parar.is_set():
            return                       # cancelada: lo que diga ya no se muestra
        limpio = re.sub(r"^\s*Arch[eé]:\s*", "", linea)
        try:
            self._real.write(f"  [tarea {tarea.id}] {limpio}\n")
            self._real.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass

    def __getattr__(self, nombre):      # encoding, isatty, fileno... los del real
        return getattr(self._real, nombre)


def _avisar(texto):
    """Mensaje de Arché sobre las tareas, venga del hilo que venga."""
    try:
        destino = sys.stdout
        if isinstance(destino, _SalidaMultitarea):
            destino = destino._real
        destino.write(f"Arché: {texto}\n")
        destino.flush()
    except Exception:
        pass


# ------------------------------------------------------------------
# Entrada: una tarea que pregunta algo no se roba lo que escribes
# ------------------------------------------------------------------

def _input_de_tarea(prompt=""):
    """Reemplaza a input() SOLO dentro de los hilos de las tareas."""
    tarea = _por_hilo.get(threading.get_ident())
    if tarea is None:                     # hilo principal u otro: input de siempre
        previo = _input_previo[0] or _input_original
        return previo(prompt)
    pregunta = re.sub(r"\s*T[uú]:\s*$", "", str(prompt or "")).strip()
    pregunta = re.sub(r"^\s*Arch[eé]:\s*", "", pregunta) or "¿Sigo?"
    tarea.pregunta = pregunta
    estado_antes = tarea.estado
    tarea.estado = "esperando tu respuesta"
    tarea._hay_respuesta.clear()
    _avisar(f"La tarea {tarea.id} ({tarea.orden}) pregunta: {pregunta}\n"
            f"       Respóndeme con «tarea {tarea.id} sí» o «tarea {tarea.id} no».")
    llego = False
    limite = time.time() + ESPERA_RESPUESTA_SEG
    while time.time() < limite and not tarea.parar.is_set():
        if tarea._hay_respuesta.wait(0.5):
            llego = True
            break
    respuesta = tarea._respuesta if llego else "n"
    if not llego and not tarea.parar.is_set():
        _avisar(f"La tarea {tarea.id} no recibió respuesta; tomé «no».")
    tarea.pregunta = None
    tarea._respuesta = None
    tarea.estado = estado_antes
    return respuesta


_input_original = builtins.input


def _asegurar_input():
    """Pone _input_de_tarea encima de lo que haya ahora en input() (la voz y la
    ventana también lo envuelven y a veces lo cambian). Se llama seguido."""
    actual = builtins.input
    if actual is _input_de_tarea:
        return
    _input_previo[0] = actual
    builtins.input = _input_de_tarea


def _asegurar_salida():
    if not isinstance(sys.stdout, _SalidaMultitarea) and not _hay_en_cadena(sys.stdout):
        sys.stdout = _SalidaMultitarea(sys.stdout)
        _instalado["salida"] = True


def _hay_en_cadena(salida, profundidad=0):
    """True si ya hay un _SalidaMultitarea adentro (otra envoltura lo tapó)."""
    if profundidad > 6 or salida is None:
        return False
    if isinstance(salida, _SalidaMultitarea):
        return True
    return _hay_en_cadena(getattr(salida, "_real", None), profundidad + 1)


def _salida_mt():
    s, n = sys.stdout, 0
    while s is not None and n < 7:
        if isinstance(s, _SalidaMultitarea):
            return s
        s, n = getattr(s, "_real", None), n + 1
    return None


# ------------------------------------------------------------------
# Lo que usan main.py y las herramientas
# ------------------------------------------------------------------

def configurar(herramientas):
    """main.py la llama una vez con [(nombre, funcion_manejar), ...] en el
    mismo orden en que su bucle las prueba."""
    global _herramientas
    _herramientas = [(str(n), f) for n, f in herramientas if callable(f)]
    _asegurar_salida()
    _asegurar_input()


def debe_parar():
    """Para usar dentro de una herramienta larga: True si le pidieron parar
    a la tarea que la está corriendo (en el hilo principal siempre False)."""
    tarea = _por_hilo.get(threading.get_ident())
    return bool(tarea and tarea.parar.is_set())


def en_tarea():
    """True si el código que llama está corriendo dentro de una tarea de fondo."""
    return threading.get_ident() in _por_hilo


def lanzar(orden):
    """Manda una orden a segundo plano. Devuelve la tarea creada."""
    orden = (orden or "").strip()
    with _candado:
        tarea = _Tarea(_siguiente_id[0], orden)
        _siguiente_id[0] += 1
        _tareas[tarea.id] = tarea
        _limpiar_viejas()
    _asegurar_salida()
    _asegurar_input()
    hilo = threading.Thread(target=_correr, args=(tarea,), name=f"arche-tarea-{tarea.id}", daemon=True)
    tarea.hilo = hilo
    hilo.start()
    return tarea


def detener_todo():
    """Al cerrar Arché: pide parar a todas."""
    for tarea in list(_tareas.values()):
        if tarea.viva():
            tarea.parar.set()
            tarea._hay_respuesta.set()


def tareas_vivas():
    return [t for t in _tareas.values() if t.viva()]


# ------------------------------------------------------------------
# Ejecutar una tarea
# ------------------------------------------------------------------

def _correr(tarea):
    # esperar turno (máximo MAX_A_LA_VEZ a la vez)
    while not _turnos.acquire(timeout=0.5):
        if tarea.parar.is_set():
            tarea.estado = "cancelada"
            tarea.fin = time.time()
            return
    try:
        if tarea.parar.is_set():
            tarea.estado = "cancelada"
            return
        _por_hilo[threading.get_ident()] = tarea
        tarea.estado = "corriendo"
        tarea.inicio = time.time()
        reconocida = _despachar(tarea, tarea.orden)
        mt = _salida_mt()
        if mt:
            mt.terminar_hilo(tarea)
        tarea.fin = time.time()
        if tarea.parar.is_set():
            tarea.estado = "cancelada"
        elif not reconocida:
            tarea.estado = "pasada al bucle"
            _avisar(f"«{tarea.orden}» no la puedo hacer de fondo (ninguna herramienta la reconoce sola). "
                    "La hago ahora de la forma normal.")
            _al_bucle(tarea.orden)
        else:
            tarea.estado = "terminada"
            _avisar(f"✔ Terminé la tarea {tarea.id} ({tarea.orden}) en {_tiempo(tarea.duracion())}.")
    except Exception as e:
        tarea.fin = time.time()
        tarea.estado = "falló"
        tarea.salida.append(f"Error: {e}")
        _avisar(f"✖ La tarea {tarea.id} ({tarea.orden}) falló: {e}")
        try:
            from core.IA import registro_errores
            registro_errores.registrar(e, frase=tarea.orden, origen="tarea_de_fondo")
        except Exception:
            pass
    finally:
        _por_hilo.pop(threading.get_ident(), None)
        _turnos.release()


def _despachar(tarea, orden, nivel=0):
    """Prueba las herramientas en orden; la primera que reconoce la orden la
    hace. Devuelve True si alguna la reconoció.
    Si una herramienta necesita un recurso que OTRA tarea está usando (por
    ejemplo la pantalla), primero se prueban las demás y esa se deja para el
    final: así "investiga X" no se queda esperando a que termine una rutina."""
    diferidas = []
    for nombre, funcion in _herramientas:
        if tarea.parar.is_set():
            return True
        recurso = RECURSOS.get(nombre)
        if recurso and not _tomar_recurso(tarea, recurso, esperar=False):
            diferidas.append((nombre, funcion))
            continue
        hecho = _probar(tarea, nombre, funcion, orden, recurso, nivel)
        if hecho:
            return True
    for nombre, funcion in diferidas:
        if tarea.parar.is_set():
            return True
        recurso = RECURSOS.get(nombre)
        if not _tomar_recurso(tarea, recurso, esperar=True):
            return True                  # la cancelaron mientras esperaba
        if _probar(tarea, nombre, funcion, orden, recurso, nivel):
            return True
    tarea.herramienta = None
    return False


def _probar(tarea, nombre, funcion, orden, recurso, nivel):
    """Llama a una herramienta (con su recurso ya tomado). True si la reconoció."""
    _asegurar_input()
    try:
        tarea.herramienta = nombre
        resultado = _llamar(funcion, orden)
    finally:
        if recurso:
            _soltar_recurso(recurso)
    if not resultado:
        return False
    # el perro robot devuelve el texto de la respuesta
    if isinstance(resultado, str):
        print(f"Arché: {resultado}")
    # una rutina devuelve sus pasos: se hacen aquí mismo, uno tras otro
    elif (isinstance(resultado, tuple) and len(resultado) == 2 and resultado[0] == "ejecutar_rutina"
          and isinstance(resultado[1], dict) and resultado[1].get("pasos") and nivel < 3):
        for paso in resultado[1]["pasos"]:
            if tarea.parar.is_set():
                break
            m = re.match(r"^\s*espera\s+(\d{1,3})", str(paso), re.IGNORECASE)
            if m:
                _dormir(tarea, int(m.group(1)))
                continue
            if not _despachar(tarea, str(paso), nivel + 1):
                print(f"Arché: El paso «{paso}» no se puede hacer de fondo; lo salto.")
    return True


def _llamar(funcion, orden):
    """Llama a manejar(orden). Si la función recibe 'confirmar' (varias lo
    tienen como confirmar=input), le pasamos la versión segura para tareas."""
    try:
        parametros = inspect.signature(funcion).parameters
    except (TypeError, ValueError):
        parametros = {}
    if "confirmar" in parametros:
        return funcion(orden, confirmar=_input_de_tarea)
    return funcion(orden)


def _tomar_recurso(tarea, recurso, esperar=True):
    """Toma el recurso. Con esperar=False devuelve False enseguida si otra
    tarea lo tiene; con esperar=True espera su turno (False si la cancelan)."""
    with _candado:
        lock = _recursos.setdefault(recurso, threading.RLock())
    if not esperar:
        if lock.acquire(blocking=False):
            _dueno_recurso[recurso] = tarea.id
            return True
        return False
    while not lock.acquire(timeout=0.5):
        if tarea.parar.is_set():
            return False
        dueno = _dueno_recurso.get(recurso)
        tarea.estado = f"esperando la {recurso}" + (f" (la usa la tarea {dueno})" if dueno else "")
    _dueno_recurso[recurso] = tarea.id
    tarea.estado = "corriendo"
    return True


def _soltar_recurso(recurso):
    lock = _recursos.get(recurso)
    if lock is None:
        return
    try:
        lock.release()
    except RuntimeError:
        return
    # RLock: si la misma tarea lo sigue teniendo (rutina adentro de rutina), no se borra el dueño
    if not getattr(lock, "_is_owned", lambda: False)():
        _dueno_recurso.pop(recurso, None)


def _dormir(tarea, segundos):
    limite = time.time() + segundos
    while time.time() < limite and not tarea.parar.is_set():
        time.sleep(0.2)


def _al_bucle(orden):
    """Le pasa la orden al bucle principal como si la hubieras escrito."""
    entrada = sys.modules.get("core.interfaz.entrada")
    try:
        from core import canales
        if canales._estado.get("via_entrada") and entrada is not None:
            entrada.enviar(orden)
        else:
            canales.poner("consola", None, orden)
    except Exception:
        _avisar(f"No pude pasarla sola; escríbela otra vez: {orden}")


def _limpiar_viejas():
    terminadas = [t for t in _tareas.values() if not t.viva()]
    sobran = len(terminadas) - TAREAS_TERMINADAS_A_GUARDAR
    for t in sorted(terminadas, key=lambda t: t.id)[:max(0, sobran)]:
        _tareas.pop(t.id, None)


# ------------------------------------------------------------------
# Frases que entiende
# ------------------------------------------------------------------

def _norm(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip(" .!¡?¿")


_PREFIJOS_FONDO = r"(?:en segundo plano|de fondo|en el fondo|mientras tanto|mientras)"
_PREFIJOS_A_LA_VEZ = r"(?:a la vez|al mismo tiempo|en paralelo|simultaneamente|todo a la vez)"
_RE_SUFIJO_FONDO = re.compile(r"^(?P<orden>.+?)[\s,]+(?:en segundo plano|de fondo|en paralelo)$", re.IGNORECASE)
_RE_SEPARAR = re.compile(r"\s*;\s*|\s*,\s*(?:y\s+)?|\s+y\s+(?:al mismo tiempo|a la vez|tambien|también|ademas|además)?\s*",
                         re.IGNORECASE)

# Verbos con los que empieza una orden (para no partir "busca gatos y perros").
VERBOS = {
    "abre", "abrir", "busca", "buscame", "buscar", "sube", "baja", "pon", "ponme", "minimiza", "maximiza",
    "cierra", "teclea", "presiona", "pulsa", "captura", "toma", "haz", "hazme", "silencia", "pausa",
    "reproduce", "bloquea", "pasa", "cambia", "enfoca", "trae", "ve", "copia", "acomoda", "muestra",
    "muestrame", "organiza", "ordena", "limpia", "investiga", "descarga", "crea", "creame", "juega",
    "entrena", "estudia", "analiza", "revisa", "calcula", "dime", "di", "lee", "escribe", "anota",
    "anotame", "recuerdame", "inicia", "empieza", "comprime", "escanea", "diagnostica", "sincroniza",
    "guarda", "manda", "envia", "traduce", "resume", "aprende", "elimina", "borra", "mueve", "programa",
    "activa", "desactiva", "apaga", "prende", "enciende", "dame", "cuentame", "explica", "genera",
    "agente", "camina", "sientate", "saluda", "corre", "detente", "sigue", "consigue",
}


def _es_orden(trozo):
    n = _norm(trozo)
    primera = n.split(" ")[0] if n else ""
    return primera in VERBOS or n.startswith("en minecraft ")


def partir_ordenes(texto):
    """'investiga X y busca duplicados' -> ['investiga X', 'busca duplicados'].
    Si algún pedazo no empieza como una orden, NO se parte."""
    partes = [p.strip(" ,;") for p in _RE_SEPARAR.split(texto or "") if p and p.strip(" ,;")]
    if len(partes) > 1 and all(_es_orden(p) for p in partes):
        return partes
    return [texto.strip()]


def _numero(texto):
    m = re.search(r"\b(\d{1,4})\b", texto)
    if m:
        return int(m.group(1))
    palabras = {"uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
                "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    for p, n in palabras.items():
        if re.search(rf"\b{p}\b", texto):
            return n
    return None


def _tiempo(seg):
    seg = int(seg)
    if seg < 60:
        return f"{seg} s"
    if seg < 3600:
        return f"{seg // 60} min {seg % 60} s"
    return f"{seg // 3600} h {(seg % 3600) // 60} min"


def _listar():
    with _candado:
        todas = sorted(_tareas.values(), key=lambda t: t.id)
    if not todas:
        print("Arché: No tengo tareas de fondo. Prueba: «en segundo plano busca archivos duplicados».")
        return
    vivas = [t for t in todas if t.viva()]
    print(f"Arché: Tengo {len(vivas)} tarea(s) activa(s)" + (" y estas recientes:" if len(todas) > len(vivas) else ":"))
    for t in todas:
        icono = {"corriendo": "▶", "en fila": "⏳", "terminada": "✔", "falló": "✖",
                 "cancelada": "■", "pasada al bucle": "↪"}.get(t.estado, "…")
        extra = f" · usando {t.herramienta}" if t.herramienta and t.viva() else ""
        tiempo = f" · {_tiempo(t.duracion())}" if t.inicio else ""
        print(f"  {icono} tarea {t.id}: {t.orden}  —  {t.estado}{extra}{tiempo}")
        if t.pregunta:
            print(f"      pregunta: {t.pregunta}  (responde «tarea {t.id} sí/no»)")


def _resultado(n):
    t = _tareas.get(n)
    if t is None:
        print(f"Arché: No encuentro la tarea {n}. Escribe «tareas» para ver cuáles hay.")
        return
    print(f"Arché: Tarea {n} ({t.orden}) — {t.estado}.")
    if not t.salida:
        print("  (todavía no ha dicho nada)")
    for linea in t.salida[-25:]:
        print(f"  {linea}")


def _cancelar(n):
    t = _tareas.get(n)
    if t is None or not t.viva():
        print(f"Arché: La tarea {n} no está activa.")
        return
    t.parar.set()
    t._hay_respuesta.set()
    if t.estado == "en fila":
        print(f"Arché: Listo, saqué de la fila la tarea {n}.")
    else:
        print(f"Arché: Le pedí a la tarea {n} que pare. Si la herramienta no se puede interrumpir, "
              "termina lo que estaba haciendo y descarto su resultado.")


def _responder(n, texto):
    t = _tareas.get(n)
    if t is None or not t.pregunta:
        print(f"Arché: La tarea {n} no me está preguntando nada ahora.")
        return
    nt = _norm(texto)
    if nt in ("si", "s", "dale", "ok", "hazlo", "claro", "yes"):
        valor = "s"
    elif nt in ("no", "n", "cancela", "mejor no"):
        valor = "n"
    else:
        valor = texto.strip()
    t._respuesta = valor
    t._hay_respuesta.set()
    print(f"Arché: Le pasé tu respuesta a la tarea {n}.")


def manejar(comando):
    """Hook para main.py. Devuelve True si la frase era de multitarea."""
    original = (comando or "").strip()
    t = _norm(original)
    if not t:
        return False

    # --- control de tareas ---
    if re.fullmatch(r"(?:que |cuales )?(?:tareas|tareas de fondo|tareas en segundo plano)(?: hay| tienes| activas)?"
                    r"|que estas haciendo(?: de fondo| en segundo plano)?|(?:ver|muestra(?:me)?|lista(?:r)?) (?:las )?tareas", t):
        _listar()
        return True
    if re.fullmatch(r"(?:para|deten|cancela|detener|parar|cancelar) (?:todas las tareas|las tareas|tareas de fondo|todo lo de fondo)", t):
        vivas = tareas_vivas()
        detener_todo()
        print(f"Arché: Le pedí parar a {len(vivas)} tarea(s)." if vivas else "Arché: No hay tareas activas.")
        return True
    m = re.fullmatch(r"(?:para|deten|cancela|detener|parar|cancelar|quita) (?:la )?tarea (\S+)", t)
    if m and _numero(m.group(1)):
        _cancelar(_numero(m.group(1)))
        return True
    m = re.fullmatch(r"(?:resultado|salida|que dijo|que hizo|como va|como vas con)(?: de)?(?: la)? tarea (\S+)", t)
    if m and _numero(m.group(1)):
        _resultado(_numero(m.group(1)))
        return True
    m = re.match(r"^tarea (\d{1,4})[:,]?\s+(.+)$", original.strip(), re.IGNORECASE) or \
        re.match(r"^tarea (\d{1,4})[:,]?\s+(.+)$", t)
    if m and _tareas.get(int(m.group(1))) is not None and (
            _tareas[int(m.group(1))].pregunta or _norm(m.group(2)) in ("si", "no", "s", "n")):
        _responder(int(m.group(1)), m.group(2))
        return True

    # --- mandar cosas a segundo plano ---
    ordenes = None
    m = re.match(rf"^{_PREFIJOS_A_LA_VEZ}\s*[:,]?\s+(.+)$", original, re.IGNORECASE) or \
        re.match(rf"^{_PREFIJOS_A_LA_VEZ}\s*[:,]?\s+(.+)$", t)
    if m:
        ordenes = partir_ordenes(m.group(1))
    if ordenes is None:
        m = re.match(rf"^{_PREFIJOS_FONDO}\s*[:,]?\s+(.+)$", original, re.IGNORECASE) or \
            re.match(rf"^{_PREFIJOS_FONDO}\s*[:,]?\s+(.+)$", t)
        if m and _es_orden(m.group(1)):
            ordenes = partir_ordenes(m.group(1))
    if ordenes is None:
        m = _RE_SUFIJO_FONDO.match(original) or _RE_SUFIJO_FONDO.match(t)
        if m and _es_orden(m.group("orden")):
            ordenes = partir_ordenes(m.group("orden"))
    if ordenes is None:
        # "investiga X y al mismo tiempo busca duplicados"
        if re.search(r"\s+y\s+(?:al mismo tiempo|a la vez)\s+", original, re.IGNORECASE):
            partes = partir_ordenes(original)
            if len(partes) > 1:
                ordenes = partes
    if not ordenes:
        return False

    if not _herramientas:
        print("Arché: La multitarea no está conectada todavía (falta correr aplicar_parche_multitarea.py).")
        return True
    nuevas = [lanzar(o) for o in ordenes if o]
    if len(nuevas) == 1:
        print(f"Arché: Va de fondo como tarea {nuevas[0].id}: {nuevas[0].orden}. Puedes seguir hablándome.")
    else:
        lista = ", ".join(f"{x.id} ({x.orden})" for x in nuevas)
        print(f"Arché: Hago {len(nuevas)} cosas a la vez: tareas {lista}. Escribe «tareas» para ver cómo van.")
    return True
