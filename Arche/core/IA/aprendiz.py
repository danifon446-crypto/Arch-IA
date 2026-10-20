"""
aprendiz.py  (modo aprendiz)
----------------------------
Ubicacion: Arche/core/IA/aprendiz.py

Arche responde PRIMERO con su modelo local (Ollama). La nube solo contesta directo cuando la
pregunta pide datos de hoy (noticias, clima, precios...) o cuando Ollama falla. Mientras tanto,
en segundo plano, la nube contesta la MISMA pregunta y Arche compara:

  * si las dos respuestas coinciden en lo importante -> guarda la suya en su cache (la proxima vez
    contesta al instante, sin Ollama ni nube);
  * si difieren -> aprende la de la nube (guardada con varias formas de preguntar, vía
    aprender_de_nube.aprender_de_charla) y la proxima vez ya contesta bien sola.

Solo se aprende conocimiento estable (nada de datos de hoy, ni preguntas sobre Arche, ni ordenes).
Tiene cupo propio por dia (TOPE_REVISIONES_DIA) para no acabarse el cupo gratis de la nube.

Se prende/apaga con: 'responde tu primero' / 'responde la nube primero'. Estado: 'estado aprendiz'.
"""

import re
import threading
import unicodedata
from datetime import date

from core.IA import nube

TOPE_REVISIONES_DIA = 120
UMBRAL_COINCIDE = 0.40          # parecido minimo (0-1) para decir que las dos respuestas dicen lo mismo
MAX_TOKENS_REVISION = 400
SISTEMA_REVISION = ("Eres un asistente. Responde en español, claro y directo, en 2 a 5 frases, "
                    "sin saludar ni despedirte.")

_lock = threading.Lock()
_STOP = {"de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o", "que", "en", "es", "se",
         "por", "para", "con", "del", "al", "lo", "su", "sus", "a", "como", "mas", "muy", "son", "ser",
         "esta", "este", "esto", "eso", "ese", "si", "no", "me", "te", "le", "hay", "pero", "tambien"}


def _cfg():
    return nube._leer_config()


def activo():
    """Por defecto activado: Arche responde primero. 'responde la nube primero' lo apaga."""
    return bool(_cfg().get("charla_local", True))


def fijar(valor):
    with _lock:
        cfg = _cfg()
        cfg["charla_local"] = bool(valor)
        nube._guardar_config(cfg)


def _stats(cfg=None):
    cfg = cfg if cfg is not None else _cfg()
    st = dict(cfg.get("aprendiz", {}))
    if st.get("fecha") != date.today().isoformat():
        st["fecha"], st["hoy"] = date.today().isoformat(), 0
    for k in ("hoy", "revisadas", "coinciden", "corregidas"):
        st.setdefault(k, 0)
    return st


def _sumar(**campos):
    with _lock:
        cfg = _cfg()
        st = _stats(cfg)
        for k, v in campos.items():
            st[k] = st.get(k, 0) + v
        cfg["aprendiz"] = st
        nube._guardar_config(cfg)


def revisiones_restantes():
    return max(0, TOPE_REVISIONES_DIA - _stats()["hoy"])


def _norm(texto):
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9ñ]+", t)


def parecido(a, b):
    """0-1: cuanto de lo importante de la respuesta MAS CORTA aparece en la otra (palabras de contenido)."""
    pa = {w for w in _norm(a) if w not in _STOP and len(w) > 2}
    pb = {w for w in _norm(b) if w not in _STOP and len(w) > 2}
    if not pa or not pb:
        return 0.0
    corta, larga = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return len(corta & larga) / len(corta)


def coinciden(local, nube_texto):
    return parecido(local, nube_texto) >= UMBRAL_COINCIDE


def respuesta_local_usable(texto):
    from core.IA import respuestas
    t = (texto or "").strip()
    if len(t) < 2 or t.startswith("No puedo conectarme a Ollama"):
        return False
    return not respuestas.respuesta_inutil(t)


def debe_responder_local(pregunta):
    """True si esta pregunta se contesta primero con Ollama (no pide datos de hoy y el modo lo permite)."""
    from core.IA import cerebro
    return activo() and nube.modo() != "nube" and not cerebro.necesita_internet(pregunta)


def _vale_la_pena(pregunta):
    from core.IA import aprender_de_nube as an
    return an._vale_la_pena_charla(pregunta, "x" * 30)


def revisar(pregunta, texto_local, sincrono=False):
    """Lanza la revision en segundo plano (o aqui mismo si sincrono=True). Nunca lanza ni bloquea el chat."""
    try:
        if not nube.configurada() or revisiones_restantes() == 0 or not _vale_la_pena(pregunta):
            return None
    except Exception:
        return None
    if sincrono:
        _revisar(pregunta, texto_local)
        return None
    hilo = threading.Thread(target=_revisar, args=(pregunta, texto_local), daemon=True, name="aprendiz")
    hilo.start()
    return hilo


def _revisar(pregunta, texto_local):
    try:
        from core.IA import aprender_de_nube as an, respuestas
        if not an.activo() or not nube.disponible() or revisiones_restantes() == 0:
            return
        _sumar(hoy=1)
        try:
            texto_nube = nube.responder([{"role": "user", "content": pregunta}], sistema=SISTEMA_REVISION,
                                        max_tokens=MAX_TOKENS_REVISION, temperature=0.2)
        except nube.ErrorNube:
            return
        if not an._vale_la_pena_charla(pregunta, texto_nube):
            return
        if coinciden(texto_local, texto_nube):
            respuestas.guardar_respuesta(pregunta, texto_local)
            _sumar(revisadas=1, coinciden=1)
            an._apuntar({"tipo": "charla", "frase": pregunta, "preguntas": [an._normalizar(pregunta)],
                         "nota": "coincidia con la nube"})
        else:
            _sumar(revisadas=1, corregidas=1)
            an.aprender_de_charla(pregunta, texto_nube, volatil=False)
    except Exception:
        pass


def resumen_texto():
    st = _stats()
    if not st["revisadas"] and not st["hoy"]:
        return (f"Modo aprendiz: {'activado' if activo() else 'desactivado'}. "
                "Todavía no he comparado ninguna respuesta mía con la nube.")
    pct = int(100 * st["coinciden"] / st["revisadas"]) if st["revisadas"] else 0
    return (f"Modo aprendiz: {'activado' if activo() else 'desactivado'}. Comparé {st['revisadas']} respuestas mías "
            f"con la nube: {st['coinciden']} coincidían ({pct} %) y aprendí {st['corregidas']} correcciones. "
            f"Hoy usé {st['hoy']} de {TOPE_REVISIONES_DIA} revisiones.")