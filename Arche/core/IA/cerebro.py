"""
cerebro.py
----------
Ubicacion: Arche/core/IA/cerebro.py

Decide COMO piensa Arché cuando le hablas de verdad (charla, preguntas):

  1. Si la pregunta pide algo actual (noticias, precios, "hoy", "quien
     gano"...) y hay internet, primero busca en la web y le pasa lo que
     encontro al modelo para que conteste con datos de hoy.
  2. Si hay clave de la nube e internet, piensa con el modelo grande de la
     nube (con historial de la charla y lo que Arché sabe de ti).
  3. Si no, o si la nube falla, sigue como siempre: Ollama (conversar()).

El modo estudio y el entrenamiento NO pasan por aqui (siguen usando Ollama
directo), asi que la nube no gasta nada en eso.

Tambien trae los comandos de internet: investiga, clima, noticias, estado
de la nube, conectar la nube.
"""

import getpass
import re
from datetime import datetime

from core import configuracion, web
from core.IA import nube

_historial = []                 # charla con la nube (user/assistant)
LIMITE_HISTORIAL = 20


# ------------------------------------------------------------------
# Texto
# ------------------------------------------------------------------

def _sin_tildes(texto):
    t = str(texto).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u")):
        t = t.replace(a, b)
    return t


def _limpio(comando):
    t = re.sub(r"[¿?¡!,.;:]", " ", _sin_tildes(comando))
    return " ".join(t.split())


def _msg(texto):
    print(f"Arché: {texto}")


_PISTAS_ACTUALIDAD = re.compile(
    r"\b(hoy|ahora mismo|actualmente|ultim[oa]s?|recientes?|recientemente|esta semana|este mes|este ano|"
    r"noticias?|precio|cuanto (?:cuesta|vale|esta|sale)|cotizacion|dolar|euro|bitcoin|quien gano|"
    r"quien va ganando|resultado|marcador|en vivo|presidente actual|202[4-9])\b")


def necesita_internet(pregunta):
    """True si la pregunta parece pedir algo que cambia con el tiempo."""
    return bool(_PISTAS_ACTUALIDAD.search(_sin_tildes(pregunta)))


# ------------------------------------------------------------------
# Pensar (nube o Ollama)
# ------------------------------------------------------------------

def usa_nube():
    return nube.disponible()


_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def _fecha_en_español(ahora=None):
    # strftime("%A") sale en ingles en muchos Windows; se arma a mano.
    a = ahora or datetime.now()
    return f"{_DIAS[a.weekday()]} {a.day} de {_MESES[a.month - 1]} de {a.year}, {a.strftime('%H:%M')}"


def _sistema_para_nube():
    nombre = configuracion.obtener("nombre_usuario") or "tu usuario"
    partes = [
        f"Eres Arché, el asistente personal de {nombre}, y vives en su computador. "
        "Respondes en español, de forma natural y cercana. Tus respuestas se leen en voz alta, "
        "así que sé breve (1 a 4 frases salvo que pidan más), sin listas largas ni markdown. "
        "Si no sabes algo, dilo con honestidad. "
        f"Hoy es {_fecha_en_español()}."
    ]
    try:
        from core.memoria import resumen_para_contexto
        contexto = resumen_para_contexto()
        if contexto:
            partes.append("Cosas que ya sabes de la persona (úsalas solo si vienen al caso): " + contexto)
    except Exception:
        pass
    return " ".join(partes)


def _recortar():
    exceso = len(_historial) - LIMITE_HISTORIAL
    if exceso > 0:
        del _historial[:exceso]


def reiniciar_historial():
    _historial.clear()


def _con_contexto_web(pregunta, contexto_web):
    if not contexto_web:
        return pregunta
    return ("Usa estos resultados de internet para responder con datos actuales. Si no alcanzan para "
            "responder, dilo. No inventes datos que no estén aquí.\n\n"
            f"RESULTADOS:\n{contexto_web}\n\nPREGUNTA: {pregunta}")


def _ollama(prompt, num_predict=350):
    from core.IA.ollamaIA import conversar
    return conversar(prompt, num_predict=num_predict)


def pensar(pregunta, contexto_web=None, max_tokens=500):
    """(texto, fuente, aviso). fuente: 'nube' | 'ollama'. aviso: por que se uso el respaldo, o ''."""
    aviso = ""
    if nube.modo() != "ollama" and nube.configurada():
        if nube.disponible():
            try:
                mensajes = list(_historial) + [{"role": "user", "content": _con_contexto_web(pregunta, contexto_web)}]
                texto = nube.responder(mensajes, sistema=_sistema_para_nube(), max_tokens=max_tokens)
                _historial.append({"role": "user", "content": pregunta})
                _historial.append({"role": "assistant", "content": texto})
                _recortar()
                return texto, "nube", ""
            except nube.ErrorNube as e:
                aviso = f"La nube no respondió ({e})."
                if nube.modo() == "nube":
                    return aviso + " Estás en modo solo nube; di 'usa la nube' para que use Ollama de respaldo.", "nube", ""
        elif nube.modo() == "nube":
            return "Estás en modo solo nube y no tengo internet ahora mismo.", "nube", ""
    texto = _ollama(_con_contexto_web(pregunta, contexto_web))
    if aviso:
        aviso += " Respondo con Ollama."
    return texto, "ollama", aviso


# ------------------------------------------------------------------
# Web como contexto
# ------------------------------------------------------------------

def _contexto_web(consulta, n=4, leer_primera=True):
    """(texto_para_el_modelo, [resultados]) o (None, [])."""
    resultados = web.buscar(consulta, n)
    if not resultados:
        return None, []
    trozos = []
    for i, r in enumerate(resultados, start=1):
        trozos.append(f"[{i}] {r['titulo']}\n{r['resumen']}\n{r['url']}")
    if leer_primera:
        cuerpo = web.leer_pagina(resultados[0]["url"], maximo=1800)
        if cuerpo:
            trozos.append(f"Texto de [1]: {cuerpo}")
    return "\n\n".join(trozos), resultados


def responder(pregunta):
    """
    Respuesta a una charla normal. Devuelve dict:
      texto, fuente ('nube'|'ollama'), aviso, web (bool), cacheable (bool)
    """
    contexto, resultados = None, []
    if necesita_internet(pregunta) and web.hay_internet():
        contexto, resultados = _contexto_web(pregunta)
    texto, fuente, aviso = pensar(pregunta, contexto)
    if resultados:
        texto += "\n(Fuente: " + resultados[0]["url"] + ")"
    return {
        "texto": texto, "fuente": fuente, "aviso": aviso, "web": bool(resultados),
        # solo lo que contesta Ollama sin internet se guarda en el cache de respuestas
        "cacheable": fuente == "ollama" and not resultados and not aviso,
    }


def investigar(tema):
    """Busca en la web y resume lo encontrado. Imprime la respuesta y las fuentes."""
    if not web.hay_internet():
        _msg("No tengo internet ahora mismo, así que no puedo investigar eso.")
        return
    _msg(f"Investigando '{tema}'...")
    contexto, resultados = _contexto_web(tema, n=5)
    if not resultados:
        _msg("No encontré nada en la web sobre eso (o la búsqueda no respondió).")
        return
    pregunta = (f"Resume en 3 a 5 frases claras lo que dicen los resultados sobre: {tema}. "
                "Responde directo, sin saludar.")
    texto, fuente, aviso = pensar(pregunta, contexto, max_tokens=450)
    if aviso:
        _msg(aviso)
    _msg(texto)
    print("  Fuentes:")
    for i, r in enumerate(resultados[:4], start=1):
        print(f"   {i}. {r['titulo']} - {r['url']}")


# ------------------------------------------------------------------
# Clima y noticias
# ------------------------------------------------------------------

def ciudad_guardada():
    return (configuracion.obtener("ciudad") or "").strip()


def _preguntar(texto):
    return input(texto).strip()


def decir_clima(ciudad=None):
    if not web.hay_internet():
        _msg("No tengo internet ahora mismo, no puedo ver el clima.")
        return
    ciudad = (ciudad or "").strip() or ciudad_guardada()
    if not ciudad:
        ciudad = _preguntar("Arché: ¿De qué ciudad quieres el clima? (la recuerdo para la próxima)\nTú: ")
        if not ciudad:
            return
        configuracion.cambiar("ciudad", ciudad)
    texto = web.clima(ciudad)
    if texto is None:
        _msg(f"No pude conseguir el clima de '{ciudad}'. Revisa el nombre o prueba con otra ciudad.")
        return
    _msg(texto)


def decir_noticias(tema=None):
    if not web.hay_internet():
        _msg("No tengo internet ahora mismo, no puedo traer noticias.")
        return
    items = web.noticias(tema, n=5)
    if not items:
        _msg("No encontré noticias (o el servicio no respondió).")
        return
    titulo = f"Titulares sobre {tema}:" if tema else "Titulares de hoy:"
    lineas = [f"{i}. {n['titulo']}" + (f" ({n['fuente']})" if n["fuente"] else "")
              for i, n in enumerate(items, start=1)]
    _msg(titulo + "\n" + "\n".join(lineas))


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_CONECTAR = re.compile(r"^(?:conecta(?:r)?|configura(?:r)?|activa(?:r)?|pon(?:er)?)\s+(?:la\s+)?nube$|"
                         r"^conecta(?:te)?\s+a\s+la\s+nube$|^(?:pon|guarda|cambia)\s+(?:mi\s+)?clave(?:\s+de\s+la\s+nube)?$")
_R_BORRAR_CLAVE = re.compile(r"^(?:borra|elimina|quita)\s+(?:mi\s+|la\s+)?clave(?:\s+de\s+la\s+nube)?$")
_R_NUBE_AUTO = re.compile(r"^usa\s+(?:la\s+)?nube$|^modo\s+(?:nube\s+)?auto(?:matico)?$|^piensa\s+con\s+la\s+nube$")
_R_NUBE_SOLO = re.compile(r"^(?:usa\s+)?solo\s+(?:la\s+)?nube$|^modo\s+solo\s+nube$")
_R_OLLAMA = re.compile(r"^usa\s+(?:solo\s+)?ollama$|^(?:usa\s+)?solo\s+ollama$|^modo\s+(?:local|ollama)$|"
                       r"^piensa\s+(?:solo\s+)?(?:con\s+ollama|en\s+local)$")
_R_MODELO = re.compile(r"^usa\s+el\s+modelo\s+(\S+)$")
_R_ESTADO = re.compile(r"^(?:estado\s+de\s+(?:la\s+)?(?:nube|internet)|estas\s+conectado(?:\s+a\s+internet)?|"
                       r"tienes\s+internet|hay\s+internet|con\s+que\s+(?:piensas|modelo\s+piensas)|que\s+modelo\s+usas)$")
_R_INVESTIGAR = re.compile(r"^(?:investiga|averigua|indaga)\s+(?:sobre\s+|acerca\s+de\s+|que\s+es\s+|quien\s+es\s+)?(.+)$|"
                           r"^busca\s+informacion\s+(?:sobre|de|acerca\s+de)\s+(.+)$")
_R_CLIMA = re.compile(r"^(?:el\s+)?clima(?:\s+(?:en|de|para)\s+(.+?))?(?:\s+hoy)?$|"
                      r"^como\s+esta\s+el\s+(?:clima|tiempo)(?:\s+(?:en|de|para)\s+(.+?))?(?:\s+hoy)?$|"
                      r"^que\s+(?:clima|tiempo)\s+hace(?:\s+(?:en|de|para)\s+(.+?))?(?:\s+hoy)?$|"
                      r"^(?:va\s+a\s+llover|llueve|hace\s+(?:frio|calor))(?:\s+(?:en|de|para)\s+(.+?))?(?:\s+hoy)?$")
_R_NOTICIAS = re.compile(r"^(?:dame\s+)?(?:las\s+)?noticias(?:\s+(?:de|del|sobre|acerca\s+de)\s+(.+))?$|"
                         r"^que\s+hay\s+de\s+nuevo(?:\s+(?:en|sobre|de)\s+(.+))?$|"
                         r"^que\s+esta\s+pasando(?:\s+(?:en|con)\s+(.+))?$")
_R_CIUDAD = re.compile(r"^(?:mi\s+ciudad\s+es|vivo\s+en)\s+(.+)$")


def _primero(m):
    return next((g for g in m.groups() if g), None)


def interpretar(comando):
    """(intencion, argumento) o None."""
    t = _limpio(comando)
    if not t:
        return None
    if _R_BORRAR_CLAVE.match(t):
        return ("borrar_clave_nube", None)
    if _R_CONECTAR.match(t):
        return ("conectar_nube", None)
    if _R_NUBE_SOLO.match(t):
        return ("solo_nube", None)
    if _R_NUBE_AUTO.match(t):
        return ("usar_nube", None)
    if _R_OLLAMA.match(t):
        return ("usar_ollama", None)
    m = _R_MODELO.match(t)
    if m:
        return ("modelo_nube", m.group(1))
    if _R_ESTADO.match(t):
        return ("estado_nube", None)
    m = _R_INVESTIGAR.match(t)
    if m:
        return ("investigar", _primero(m))
    m = _R_NOTICIAS.match(t)
    if m:
        return ("noticias", _primero(m))
    m = _R_CLIMA.match(t)
    if m:
        return ("clima", _primero(m))
    m = _R_CIUDAD.match(t)
    if m:
        return ("fijar_ciudad", m.group(1).strip())
    return None


def _pedir_clave():
    return getpass.getpass("Arché: Pega tu clave de la API (no se verá al escribir) y da Enter: ").strip()


def manejar(comando):
    """Ejecuta un comando de internet/nube. (intencion, contenido) o None."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual

    if intencion == "conectar_nube":
        _msg("Para usar un modelo grande en la nube necesito una clave de API de Anthropic "
             "(la creas en console.anthropic.com). Se guarda solo en tu PC, en Database/nube_clave.txt, "
             "que no se sube a GitHub.")
        try:
            k = _pedir_clave()
        except (EOFError, KeyboardInterrupt):
            k = ""
        if not k:
            _msg("No guardé nada.")
            return (intencion, arg)
        nube.guardar_clave(k)
        _msg("Probando la clave...")
        ok, detalle = nube.probar()
        if ok:
            nube.fijar_modo("auto")
            _msg("¡Conectada! Desde ahora pienso con la nube y dejo a Ollama de respaldo.")
        else:
            _msg(f"Guardé la clave pero la prueba falló: {detalle}")
    elif intencion == "borrar_clave_nube":
        _msg("Listo, borré la clave." if nube.borrar_clave() else "No había ninguna clave guardada.")
    elif intencion == "usar_nube":
        if not nube.configurada():
            _msg("Todavía no tengo clave de la nube. Dime 'conecta la nube' para ponerla.")
        else:
            nube.fijar_modo("auto")
            _msg("Listo: uso la nube cuando haya internet y Ollama si no.")
    elif intencion == "solo_nube":
        if not nube.configurada():
            _msg("Todavía no tengo clave de la nube. Dime 'conecta la nube' para ponerla.")
        else:
            nube.fijar_modo("nube")
            _msg("Listo: solo la nube (sin internet no te podré contestar charla).")
    elif intencion == "usar_ollama":
        nube.fijar_modo("ollama")
        _msg("Listo: pienso solo con Ollama, sin salir a la nube.")
    elif intencion == "modelo_nube":
        nube.fijar_modelo(arg)
        _msg(f"Listo, la nube usará el modelo {arg}.")
    elif intencion == "estado_nube":
        _msg(nube.estado_texto())
    elif intencion == "investigar":
        investigar(arg)
    elif intencion == "noticias":
        decir_noticias(arg)
    elif intencion == "clima":
        decir_clima(arg)
    elif intencion == "fijar_ciudad":
        ciudad = arg.strip().title()
        configuracion.cambiar("ciudad", ciudad)
        _msg(f"Anotado: tu ciudad es {ciudad}. Cuando pidas el clima sin decir ciudad uso esa.")
    return (intencion, arg)x