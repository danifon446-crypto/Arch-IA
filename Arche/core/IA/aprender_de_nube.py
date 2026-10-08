"""
aprender_de_nube.py
-------------------
Ubicacion: Arche/core/IA/aprender_de_nube.py

Que Arché APRENDA de la nube en vez de depender de ella para siempre, y sin
memorizar palabra por palabra:

  1. INTENCION. Cuando una frase libre no la entienden las redes de Arché, la
     nube dice que intencion del catalogo era (y el dato variable) y ademas da
     4-5 formas distintas de pedir lo mismo. Todo eso entra a aprendizaje.py:
     las redes se reentrenan y la proxima vez lo entienden SOLAS, aunque lo
     digas con otras palabras. (core/IA/enrutador_natural.py llama a resolver()).

  2. DATOS. Cuando la nube contesta una pregunta de conocimiento estable
     (como funciona algo, que es algo) se guarda la respuesta bajo varias
     formas de preguntarla (respuestas.py las reconoce por significado). Lo que
     depende de la fecha, de ti o del lugar (noticias, clima, opiniones) NO se
     guarda. (main.py llama a aprender_de_charla()).

Cuidados:
  * Todo va en segundo plano: no hace esperar la respuesta.
  * Con tope diario y pausa entre llamadas, para no gastar el limite gratuito.
  * Una parafrasis solo se acepta si conserva el dato variable tal cual; las
    intenciones delicadas (apagar, cerrar sesion, codigo...) no se aprenden solas.
  * Se puede ver lo aprendido ("que has aprendido de la nube"), apagar
    ("desactiva el aprendizaje de la nube") y borrar ("olvida lo que aprendiste
    de la nube": quita solo lo que vino de aqui).

Lo que toca el sistema/red esta en nube.responder(): se prueba sin conexion.
"""

import json
import os
import re
import threading
import time
import unicodedata
from datetime import date, datetime

from core.IA import catalogo, nube
from core.rutas import DATABASE

ARCHIVO = os.path.join(DATABASE, "aprendido_de_nube.json")

TOPE_DIARIO = 300            # llamadas (enrutar + aprender) por dia
TOPE_DIARIO_CHARLA = 100     # de esas, las de aprender de la charla
INTERVALO_CHARLA = 12        # segundos minimos entre aprendizajes de charla
PAUSA_POR_LIMITE = 60        # si la nube dice "voy muy rapido", se descansa un rato
MAX_PARAFRASIS = 5
MAX_LECCIONES = 200
MAX_RESPUESTA = 700
MIN_PALABRAS_CHARLA = 4
DOMINIOS_SIN_APRENDER_SOLO = {"codigo"}
# delicadas aunque tengan su propia confirmacion (acciones_pc): sus formas las pones tu, no la nube
INTENCIONES_SIN_APRENDER_SOLAS = {"apagar_pc", "reiniciar_pc", "cerrar_sesion", "suspender_pc", "cerrar_ventana",
                                  "cancelar_apagado"}

SISTEMA_JSON = ("Eres un componente de un asistente en español. Respondes SIEMPRE y SOLO con un objeto JSON válido, "
                "sin texto antes ni después y sin bloques de código.")

_lock = threading.Lock()
_ultima_charla = 0.0
_pausa_hasta = 0.0


# ------------------------------------------------------------------
# Estado guardado
# ------------------------------------------------------------------

def _estado_inicial():
    return {"activo": True, "dia": "", "llamadas_hoy": 0, "charla_hoy": 0,
            "total": {"intenciones": 0, "frases": 0, "respuestas": 0}, "lecciones": []}


def _cargar():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
        base = _estado_inicial()
        base.update(datos if isinstance(datos, dict) else {})
        base["total"] = {**_estado_inicial()["total"], **(base.get("total") or {})}
        return base
    except (OSError, ValueError):
        return _estado_inicial()


def _guardar(datos):
    os.makedirs(DATABASE, exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def activo():
    return bool(_cargar().get("activo", True))


def activar(valor):
    with _lock:
        datos = _cargar()
        datos["activo"] = bool(valor)
        _guardar(datos)


def _hoy():
    return date.today().isoformat()


def _gastar_llamada(charla=False):
    """Cuenta una llamada del dia. False si ya se llego al tope."""
    with _lock:
        datos = _cargar()
        if datos.get("dia") != _hoy():
            datos["dia"], datos["llamadas_hoy"], datos["charla_hoy"] = _hoy(), 0, 0
        if datos["llamadas_hoy"] >= TOPE_DIARIO or (charla and datos["charla_hoy"] >= TOPE_DIARIO_CHARLA):
            return False
        datos["llamadas_hoy"] += 1
        if charla:
            datos["charla_hoy"] += 1
        _guardar(datos)
        return True


def _apuntar(leccion, frases=0, respuestas=0, intenciones=0):
    with _lock:
        datos = _cargar()
        leccion["fecha"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        datos["lecciones"] = (datos["lecciones"] + [leccion])[-MAX_LECCIONES:]
        datos["total"]["frases"] += frases
        datos["total"]["respuestas"] += respuestas
        datos["total"]["intenciones"] += intenciones
        _guardar(datos)


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------

def _normalizar(texto):
    t = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[¿?¡!,.;:\"']", " ", t).split())


def _json_de(texto):
    """El primer objeto JSON dentro del texto, o {} si no hay uno valido."""
    try:
        ini, fin = texto.find("{"), texto.rfind("}") + 1
        datos = json.loads(texto[ini:fin])
        return datos if isinstance(datos, dict) else {}
    except (ValueError, AttributeError):
        return {}


def _listo_para_nube():
    return activo() and time.time() >= _pausa_hasta and nube.disponible()


def _llamar(prompt, max_tokens):
    """Una llamada a la nube. Devuelve el texto o None (y descansa si hay limite)."""
    global _pausa_hasta
    try:
        return nube.responder([{"role": "user", "content": prompt}], sistema=SISTEMA_JSON,
                              max_tokens=max_tokens, temperature=0)
    except nube.ErrorNube as e:
        if e.codigo == 429:
            _pausa_hasta = time.time() + PAUSA_POR_LIMITE
        return None


def _en_segundo_plano(funcion, *args):
    hilo = threading.Thread(target=funcion, args=args, daemon=True, name="aprender-nube")
    hilo.start()
    return hilo


def _formas_validas(candidatas, original, contenido=""):
    """Limpia la lista que dio la nube: solo frases distintas, razonables y que
    conserven el dato variable tal cual."""
    vistas = {_normalizar(original)}
    limpias = []
    dato = _normalizar(contenido)
    for c in candidatas if isinstance(candidatas, list) else []:
        if not isinstance(c, str):
            continue
        c = c.strip()
        norm = _normalizar(c)
        if not (3 <= len(c) <= 140) or norm in vistas or len(norm.split()) < 2:
            continue
        if dato and dato not in norm:
            continue            # perdio el dato variable: no sirve para generalizar
        vistas.add(norm)
        limpias.append(c)
        if len(limpias) >= MAX_PARAFRASIS:
            break
    return limpias


# ------------------------------------------------------------------
# 1) Intencion
# ------------------------------------------------------------------

def _prompt_enrutar(texto):
    from core.IA import enrutador_natural
    base = enrutador_natural._armar_prompt(texto)
    corte = base.find("Formato exacto")
    if corte != -1:
        base = base[:corte]
    return base + (
        'Formato exacto (solo JSON):\n'
        '{"intencion": "id_exacto_de_la_lista", "contenido": "dato variable o vacío", '
        '"parafrasis": ["otra forma de pedir lo mismo", "..."]}\n\n'
        'Reglas de "parafrasis": 4 o 5 formas DISTINTAS de pedir lo mismo, en español natural, como hablaría una '
        'persona real (informal, algunas cortas). Cada una debe conservar EXACTAMENTE el mismo dato variable del campo '
        '"contenido", copiado igual. No repitas la frase original. Si la intención es "desconocido" o "conversar", '
        'deja "parafrasis" vacío.\n\n'
        f"Frase de la persona: {texto}\n")


def resolver(texto):
    """
    Enrutar con la nube: (id_intencion, contenido) o None si no hay nube, no se
    pudo, o no reconocio ninguna intencion. Las parafrasis se aprenden aparte,
    en segundo plano.
    """
    if not _listo_para_nube() or not _gastar_llamada():
        return None
    crudo = _llamar(_prompt_enrutar(texto), 400)
    if not crudo:
        return None
    datos = _json_de(crudo)
    id_intencion = datos.get("intencion")
    if id_intencion not in catalogo.POR_ID:
        return None
    contenido = str(datos.get("contenido") or "").strip()
    if id_intencion != "desconocido":
        entrada = catalogo.POR_ID[id_intencion]
        if (id_intencion != "conversar" and not entrada.get("confirmar")
                and id_intencion not in INTENCIONES_SIN_APRENDER_SOLAS
                and entrada["dominio"] not in DOMINIOS_SIN_APRENDER_SOLO):
            formas = _formas_validas(datos.get("parafrasis"), texto, contenido)
            if formas:
                _en_segundo_plano(_aprender_formas, texto, id_intencion, contenido, formas)
    return id_intencion, contenido


def _aprender_formas(texto, id_intencion, contenido, formas):
    from core.IA import aprendizaje
    aprendidas = 0
    for forma in formas:
        try:
            aprendizaje.aprender(forma, id_intencion, contenido, fuente="nube")
            aprendidas += 1
        except Exception:
            pass
    if aprendidas:
        _apuntar({"tipo": "intencion", "frase": texto, "intencion": id_intencion, "formas": formas[:aprendidas]},
                 frases=aprendidas, intenciones=1)


# ------------------------------------------------------------------
# 2) Datos de la charla
# ------------------------------------------------------------------

def _recortar_respuesta(texto):
    texto = (texto or "").strip()
    if len(texto) <= MAX_RESPUESTA:
        return texto
    corte = texto[:MAX_RESPUESTA]
    punto = max(corte.rfind(". "), corte.rfind("? "), corte.rfind("! "))
    return corte[:punto + 1] if punto > MAX_RESPUESTA * 0.4 else corte.rsplit(" ", 1)[0]


_RE_SOBRE_ARCHE = re.compile(r"\b(tu|tus|tienes|tienen|eres|puedes|podrias|sabes|estas|crees|piensas|aprendes|"
                             r"recuerdas|haces|ti|contigo)\b")
_RE_ORDEN_PC = re.compile(r"^(sube|baja|pon|ponme|abre|cierra|activa|desactiva|enciende|apaga|reproduce|silencia|"
                          r"bloquea|reinicia|lanza|minimiza|maximiza|muestra|toma)\b")
_RE_NEGATIVA = re.compile(r"\b(no tengo acceso|no puedo (?:hacer|abrir|cambiar|controlar|modificar|acceder|cambiar mi)|"
                          r"lo siento, no puedo|no tengo (?:la )?capacidad|no estoy aprendiendo|no guardo nada)\b")


def _vale_la_pena_charla(pregunta, respuesta):
    """Solo se guarda conocimiento general y estable. Nunca: preguntas sobre Arché mismo (la nube no
    sabe como es Arché de verdad), ordenes para el PC dichas de otra forma, ni respuestas del tipo 'no puedo'."""
    from core.IA import cerebro
    norm = _normalizar(pregunta or "")
    if _RE_SOBRE_ARCHE.search(norm) or _RE_ORDEN_PC.match(norm) or _RE_NEGATIVA.search(_normalizar(respuesta or "")):
        return False
    if len((pregunta or "").split()) < MIN_PALABRAS_CHARLA or not (20 <= len(respuesta or "") <= 4000):
        return False
    if "(Fuente:" in respuesta or cerebro.necesita_internet(pregunta):
        return False                 # dato de hoy: mañana ya no sirve
    return True


def aprender_de_charla(pregunta, respuesta, volatil=False):
    """
    Llamar tras una respuesta de la nube. En segundo plano decide si fue
    conocimiento estable y, si si, lo guarda bajo varias formas de preguntarlo.
    Devuelve el hilo (para pruebas) o None si no hay nada que hacer ahora.
    """
    global _ultima_charla
    if volatil or not _listo_para_nube() or not _vale_la_pena_charla(pregunta, respuesta):
        return None
    ahora = time.time()
    if ahora - _ultima_charla < INTERVALO_CHARLA:
        return None
    if not _gastar_llamada(charla=True):
        return None
    _ultima_charla = ahora
    return _en_segundo_plano(_tarea_charla, pregunta, respuesta)


def _tarea_charla(pregunta, respuesta):
    prompt = (
        "Una persona le preguntó esto a un asistente y recibió esta respuesta.\n\n"
        f"Pregunta: {pregunta}\n\nRespuesta: {_recortar_respuesta(respuesta)}\n\n"
        "Decide si es conocimiento ESTABLE: algo que seguirá siendo cierto mañana y que no depende de quién pregunta "
        "(definiciones, explicaciones, cómo funciona algo). Si depende de la fecha, del lugar, de la persona, es una "
        "opinión, una charla casual o una orden, NO es estable.\n\n"
        'Responde solo JSON: {"estable": true o false, "preguntas": ["4 formas DISTINTAS de preguntar lo mismo, '
        'como hablaría una persona real, que conserven el tema exacto"]}')
    crudo = _llamar(prompt, 350)
    datos = _json_de(crudo or "")
    if datos.get("estable") is not True:
        return
    formas = _formas_validas(datos.get("preguntas"), pregunta)
    guardar = [pregunta] + formas
    from core.IA import respuestas
    texto = _recortar_respuesta(respuesta)
    guardadas = []
    for q in guardar:
        try:
            respuestas.guardar_respuesta(q, texto)
            guardadas.append(_normalizar(q))
        except Exception:
            pass
    if guardadas:
        _apuntar({"tipo": "charla", "frase": pregunta, "preguntas": guardadas}, respuestas=len(guardadas))


# ------------------------------------------------------------------
# Ver y borrar lo aprendido
# ------------------------------------------------------------------

def resumen_texto(cuantas=6):
    datos = _cargar()
    t = datos["total"]
    partes = [f"Aprendizaje de la nube: {'activado' if datos.get('activo', True) else 'desactivado'}.",
              f"Hasta ahora: {t['intenciones']} intenciones nuevas ({t['frases']} formas de decirlas) y "
              f"{t['respuestas']} respuestas guardadas."]
    ultimas = datos["lecciones"][-cuantas:]
    if ultimas:
        partes.append("Lo último que aprendí:")
        for l in reversed(ultimas):
            if l.get("tipo") == "intencion":
                partes.append(f"  • «{l['frase']}» era '{l['intencion']}' (+{len(l.get('formas', []))} formas)")
            else:
                partes.append(f"  • respuesta guardada: «{l['frase']}» (+{max(0, len(l.get('preguntas', [])) - 1)} formas)")
    else:
        partes.append("Todavía no he aprendido nada de la nube.")
    return "\n".join(partes)


def olvidar():
    """Borra SOLO lo que vino de la nube. Devuelve (ejemplos_de_intencion, respuestas) borrados."""
    from core.IA import aprendizaje, respuestas
    with _lock:
        datos = _cargar()
        preguntas = {q for l in datos["lecciones"] if l.get("tipo") == "charla" for q in l.get("preguntas", [])}
    borradas_i = borradas_r = 0
    conocimiento = aprendizaje.cargar()
    quedan = [d for d in conocimiento if d.get("fuente") != "nube"]
    borradas_i = len(conocimiento) - len(quedan)
    if borradas_i:
        aprendizaje.guardar(quedan)
    banco = respuestas.cargar()
    quedan_r = [d for d in banco if d.get("pregunta") not in preguntas]
    borradas_r = len(banco) - len(quedan_r)
    if borradas_r:
        respuestas.guardar(quedan_r)
    with _lock:
        datos = _cargar()
        datos["lecciones"] = []
        datos["total"] = _estado_inicial()["total"]
        _guardar(datos)
    return borradas_i, borradas_r


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_ON = re.compile(r"^(?:activa(?:r)?|prende(?:r)?|enciende)\s+(?:el\s+)?aprendizaje\s+(?:de\s+)?(?:la\s+)?nube$|"
                   r"^aprende\s+de\s+la\s+nube$")
_R_OFF = re.compile(r"^(?:desactiva(?:r)?|apaga(?:r)?|deten(?:er)?)\s+(?:el\s+)?aprendizaje\s+(?:de\s+)?(?:la\s+)?nube$|"
                    r"^no\s+aprendas\s+de\s+la\s+nube$")
_R_VER = re.compile(r"^(?:que|cuanto)\s+(?:has\s+)?aprendido\s+(?:de|con|gracias\s+a)\s+la\s+nube$|"
                    r"^lo\s+que\s+aprendiste\s+de\s+la\s+nube$|^mis\s+lecciones\s+de\s+la\s+nube$")
_R_OLVIDAR = re.compile(r"^(?:olvida|borra)\s+(?:todo\s+)?(?:lo\s+)?(?:que\s+)?(?:aprendiste|aprendido)\s+de\s+la\s+nube$")


def interpretar(comando):
    """(intencion, None) o None. Sin efectos."""
    t = _normalizar(comando)
    for rx, nombre in ((_R_OFF, "aprender_nube_off"), (_R_ON, "aprender_nube_on"),
                       (_R_VER, "ver_aprendido_nube"), (_R_OLVIDAR, "olvidar_aprendido_nube")):
        if rx.match(t):
            return (nombre, None)
    return None


def manejar(comando, confirmar=input):
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion = cual[0]
    if intencion == "aprender_nube_on":
        activar(True)
        print("Arché: Listo: aprendo de lo que me enseña la nube (intenciones y datos que no cambian), "
              "en segundo plano y con tope diario.")
    elif intencion == "aprender_nube_off":
        activar(False)
        print("Arché: Listo: dejo de aprender de la nube. Lo que ya aprendí se queda.")
    elif intencion == "ver_aprendido_nube":
        print("Arché: " + resumen_texto())
    elif intencion == "olvidar_aprendido_nube":
        print("Arché: Voy a borrar SOLO lo que aprendí de la nube (lo demás no se toca). ¿Seguro? [s/n]")
        try:
            ok = confirmar("Tú: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ok = ""
        if ok in ("s", "si", "sí"):
            i, r = olvidar()
            print(f"Arché: Listo, olvidé {i} ejemplos y {r} respuestas que venían de la nube.")
        else:
            print("Arché: Dale, no borré nada.")
    return (intencion, None)