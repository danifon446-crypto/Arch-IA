"""
cronista.py
-----------
Ubicacion: Arche/core/nucleo/cronista.py

EL CRONISTA: te pone al día y te cuenta fracasos para aprender de ellos.

  * RESUMEN DE LA MAÑANA (sale solo, en el momento justo según tu ritmo — ver ritmo.py):
      - noticias generales de Colombia y del mundo (3)
      - noticias de tecnología, IA, robótica, espacio y ciberseguridad (5)
      - el FRACASO DEL DÍA: uno famoso de la tecnología, la ingeniería o la historia,
        con qué pasó, por qué falló y la lección
      - un fracaso reciente de las noticias, si hay
  * RESUMEN DE LA NOCHE: qué hicimos hoy, qué aprendí, habilidades nuevas, presas,
    misiones del equipo, alertas del guardián.
  * LECCIONES: cada fracaso que te cuento deja una lección guardada. El equipo y la
    Imaginación las consultan antes de actuar y te avisan:
        "Daniel, esto se parece a lo que le pasó a ___".

Comandos:
  ponme al dia / resumen de la mañana          fracaso del dia / otro fracaso
  cuentame un fracaso de <tema>                cuentame mas de la 2
  resumen de hoy / resumen de la noche         lecciones / lecciones de <tema>
  se parece a algun fracaso: <idea>            mis noticias (temas) / agrega X a mis noticias
  quita X de mis noticias                      tu ritmo / cuando me das las noticias
  dame las noticias a las 7 / a las 6:30       noticias a tu ritmo (quita la hora fija)
  resumen de la noche a las 22                 resumenes apagados / resumenes encendidos
"""

import random
import re
import threading

from core.nucleo import comun, ritmo
from core.nucleo.fracasos_semilla import FRACASOS

ARCH = comun.ruta("cronista.json")

TEMAS_DEFECTO = ["tecnología", "inteligencia artificial", "robótica", "espacio NASA SpaceX", "ciberseguridad"]
CONSULTAS_FRACASO_RECIENTE = ["falla tecnológica", "lanzamiento fallido cohete", "retiran producto defecto",
                              "ciberataque", "proyecto cancelado tecnología"]

_lock = threading.Lock()
_ultimas = {"items": []}             # para «cuéntame más de la 2»


def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("temas", list(TEMAS_DEFECTO))
    e.setdefault("contados", [])        # nombres de fracasos ya contados
    e.setdefault("lecciones", [])       # [{fracaso, leccion, claves, cuando}]
    return e


def _guardar(e):
    e["contados"] = e["contados"][-200:]
    e["lecciones"] = e["lecciones"][-300:]
    comun.guardar(ARCH, e)


# ------------------------------------------------------------------
# Noticias
# ------------------------------------------------------------------

def _web():
    from core import web
    return web


def _sin_repetidos(items):
    vistos, salida = [], []
    for it in items:
        if any(comun.parecido(it["titulo"], v) > 0.5 for v in vistos):
            continue
        vistos.append(it["titulo"])
        salida.append(it)
    return salida


def traer_noticias():
    """{"generales": [...], "tecnologia": [...]} con {titulo, fuente, url}. Listas vacías si no hay internet."""
    web = _web()
    if not web.hay_internet():
        return {"generales": [], "tecnologia": []}
    generales = _sin_repetidos(web.noticias(None, n=6))[:3]
    tecno = []
    for tema in _estado()["temas"]:
        tecno += web.noticias(tema, n=3)
    tecno = [t for t in _sin_repetidos(tecno) if all(comun.parecido(t["titulo"], g["titulo"]) <= 0.5 for g in generales)]
    return {"generales": generales, "tecnologia": tecno[:5]}


def _resumir_noticias(seccion, items):
    """Una línea clara por titular. Solo usa lo que dice el titular (nada inventado)."""
    if not items:
        return []
    titulares = "\n".join(f"{i}. {it['titulo']} ({it.get('fuente', '')})" for i, it in enumerate(items, 1))
    r = comun.pensar(
        f"Estos son titulares de noticias ({seccion}). Para CADA uno escribe una línea corta en español, clara para "
        "un estudiante de ingeniería, diciendo de qué se trata. NO inventes datos que no estén en el titular. "
        "Responde solo una lista JSON de textos, en el mismo orden.\n\n" + titulares,
        max_tokens=500, temperatura=0.2)
    lineas = comun.json_de(r)
    if isinstance(lineas, list) and len(lineas) == len(items):
        return [str(x).strip() for x in lineas]
    return [it["titulo"] for it in items]


def fracaso_reciente():
    """Un fracaso de las noticias de estos días, si el modelo encuentra uno de verdad."""
    web = _web()
    if not web.hay_internet():
        return None
    candidatos = []
    for q in random.sample(CONSULTAS_FRACASO_RECIENTE, 3):
        candidatos += web.noticias(q, n=4)
    candidatos = _sin_repetidos(candidatos)[:10]
    if not candidatos:
        return None
    lista = "\n".join(f"{i}. {c['titulo']}" for i, c in enumerate(candidatos, 1))
    r = comun.pensar(
        "De estos titulares, ¿cuál cuenta un FRACASO real de tecnología, ingeniería, ciencia o una empresa tecnológica "
        "(algo que falló, explotó, se canceló, se cayó o salió mal)? Responde JSON {\"numero\": N, \"resumen\": \"una "
        "frase\"} o {\"numero\": 0} si ninguno lo es. No inventes.\n\n" + lista, max_tokens=150, temperatura=0.1)
    datos = comun.json_de(r)
    if isinstance(datos, dict):
        try:
            n = int(datos.get("numero", 0))
        except (TypeError, ValueError):
            n = 0
        if 1 <= n <= len(candidatos):
            return dict(candidatos[n - 1], resumen=str(datos.get("resumen") or candidatos[n - 1]["titulo"]))
    return None


# ------------------------------------------------------------------
# Fracasos y lecciones
# ------------------------------------------------------------------

def elegir_fracaso(tema=None):
    e = _estado()
    if tema:
        puntuados = sorted(FRACASOS, key=lambda f: -max(
            comun.parecido(tema, f["nombre"] + " " + f["campo"] + " " + " ".join(f["claves"])),
            comun.parecido(tema, f["que"] + " " + f["causa"])))
        if puntuados and max(comun.parecido(tema, puntuados[0]["nombre"] + " " + puntuados[0]["campo"] + " " +
                                            " ".join(puntuados[0]["claves"])),
                             comun.parecido(tema, puntuados[0]["que"] + " " + puntuados[0]["causa"])) > 0.05:
            return puntuados[0]
        return None
    no_contados = [f for f in FRACASOS if f["nombre"] not in e["contados"]]
    if not no_contados:
        e["contados"] = []
        _guardar(e)
        no_contados = list(FRACASOS)
    ultimo_campo = next((f["campo"] for f in FRACASOS if e["contados"] and f["nombre"] == e["contados"][-1]), None)
    variados = [f for f in no_contados if f["campo"] != ultimo_campo] or no_contados
    return random.choice(variados)


def _contexto_wikipedia(fracaso):
    try:
        web = _web()
        if not web.hay_internet():
            return ""
        resultados = web.buscar(fracaso["busqueda"] + " wikipedia", 3)
        url = next((r["url"] for r in resultados if "wikipedia.org" in r.get("url", "")), None)
        return web.leer_pagina(url, maximo=2500) if url else ""
    except Exception:
        return ""


def contar_fracaso(fracaso, detallado=True):
    """Texto listo para mostrar. Con internet y modelo queda más vivo; si no, usa la ficha base."""
    base = (f"{fracaso['nombre']} ({fracaso['año']}) — {fracaso['campo']}\n"
            f"  Qué pasó: {fracaso['que']}\n"
            f"  Por qué falló: {fracaso['causa']}\n"
            f"  Lección: {fracaso['leccion']}")
    if not detallado:
        return base
    extra = _contexto_wikipedia(fracaso)
    r = comun.pensar(
        "Cuenta este fracaso para un estudiante de ingeniería de forma entretenida, en 5 a 7 frases, en español, "
        "con tres partes marcadas: 'Qué pasó:', 'Por qué falló:' y 'Lección:'. Usa SOLO los datos de la ficha y del "
        "texto de Wikipedia; si no estás seguro de un dato, no lo pongas.\n\n"
        f"FICHA:\n{base}\n\nWIKIPEDIA:\n{extra[:2500]}",
        max_tokens=450, temperatura=0.4)
    if r and "Lección" in r and len(r) > 120:
        return f"{fracaso['nombre']} ({fracaso['año']}) — {fracaso['campo']}\n{r.strip()}"
    return base


def guardar_leccion(fracaso):
    with _lock:
        e = _estado()
        if fracaso["nombre"] not in e["contados"]:
            e["contados"].append(fracaso["nombre"])
        if not any(l["fracaso"] == fracaso["nombre"] for l in e["lecciones"]):
            e["lecciones"].append({"fracaso": fracaso["nombre"], "leccion": fracaso["leccion"],
                                   "claves": fracaso.get("claves", []), "cuando": comun.ahora_txt()})
        _guardar(e)


def _raiz(palabra):
    """Raíz simple para que «baterías» y «batería», o «cargar» y «carga», cuenten igual."""
    return palabra[:5] if len(palabra) >= 5 else palabra


def advertir(texto, minimo=0.12):
    """Si 'texto' se parece a una lección de un fracaso conocido, devuelve el aviso; si no, None."""
    t = comun.norm(texto)
    raices = {_raiz(p) for p in comun.palabras(texto)}
    contados = {l["fracaso"] for l in _estado()["lecciones"]}
    mejor, puntaje = None, 0.0
    for f in FRACASOS:
        claves = [comun.norm(c) for c in f.get("claves", [])]
        frases = sum(1 for c in claves if " " in c and c in t)
        palabras = len(raices & {_raiz(p) for c in claves for p in comun.palabras(c)})
        p = frases * 0.3 + palabras * 0.12 + (0.05 if f["nombre"] in contados else 0)
        if p > puntaje:
            mejor, puntaje = f, p
    if mejor and puntaje >= minimo + 0.1:
        return f"Esto se parece a lo que pasó con {mejor['nombre']}: {mejor['leccion']}"
    return None


# ------------------------------------------------------------------
# Resúmenes
# ------------------------------------------------------------------

def resumen_matutino():
    n = comun.nombre_usuario()
    partes = [f"Buenos días, {n}. Esto es lo que tienes que saber hoy:"]
    noticias = traer_noticias()
    items = []
    if noticias["generales"]:
        lineas = _resumir_noticias("generales", noticias["generales"])
        partes.append("\n📰 NOTICIAS GENERALES")
        for it, linea in zip(noticias["generales"], lineas):
            items.append(it)
            partes.append(f"  {len(items)}. {linea}")
    if noticias["tecnologia"]:
        lineas = _resumir_noticias("tecnología", noticias["tecnologia"])
        partes.append("\n🔧 TECNOLOGÍA")
        for it, linea in zip(noticias["tecnologia"], lineas):
            items.append(it)
            partes.append(f"  {len(items)}. {linea}")
    if not items:
        partes.append("\n(No pude traer noticias: no hay internet.)")
    _ultimas["items"] = items

    reciente = fracaso_reciente() if items else None
    if reciente:
        items.append(reciente)
        partes.append(f"\n💥 FRACASO DE ESTOS DÍAS\n  {len(items)}. {reciente['resumen']}")

    f = elegir_fracaso()
    partes.append("\n🏛 FRACASO DEL DÍA\n" + contar_fracaso(f))
    guardar_leccion(f)
    if items:
        partes.append("\nDi «cuéntame más de la N» para ampliar una noticia.")
    pendiente = _estado().get("nocturno_pendiente")
    if pendiente:
        partes.append("\n🌙 ANOCHE NO ALCANCÉ A CONTARTE:\n" + pendiente)
        e = _estado(); e["nocturno_pendiente"] = ""; _guardar(e)
    return "\n".join(partes)


def _hechos_de_hoy():
    hoy = comun.hoy()
    hechos = {"informes": [], "evolucion": {}, "ordenes": 0}
    for r in comun.leer_bitacora(comun.ARCH_INFORMES, desde=hoy):
        hechos["informes"].append(r)
    try:
        from core import evolucion as evo
        for r in comun.leer_bitacora(evo.ARCH_DIARIO, desde=hoy):
            hechos["evolucion"][r.get("tipo", "?")] = hechos["evolucion"].get(r.get("tipo", "?"), 0) + 1
    except Exception:
        pass
    try:
        dia = ritmo._estado()["dias"].get(ritmo._dia_logico(comun.ahora()), {})
        hechos["ordenes"] = int(dia.get("muestras", 0))
        hechos["primera"] = ritmo._hhmm(dia.get("primera", 0)) if dia else ""
    except Exception:
        pass
    return hechos


def resumen_nocturno():
    n = comun.nombre_usuario()
    h = _hechos_de_hoy()
    lineas = [f"Resumen del día, {n}:"]
    if h.get("primera"):
        lineas.append(f"  • Empezaste a las {h['primera']}.")
    evo = h["evolucion"]
    if evo:
        nombres = {"cambio_aplicado": "cambios a mi código", "habilidad_descartada": "habilidades descartadas",
                   "aprendido": "cosas aprendidas", "analista_rechazo": "habilidades que el núcleo rechazó",
                   "cambio_descartado": "cambios que probé y descarté"}
        detalle = ", ".join(f"{v} {nombres.get(k, k)}" for k, v in sorted(evo.items(), key=lambda x: -x[1])[:5])
        lineas.append(f"  • Mi evolución hoy: {detalle}.")
    por_origen = {}
    for r in h["informes"]:
        por_origen.setdefault(r.get("origen") or "otros", []).append(r["texto"])
    titulos = {"depredador": "Depredador", "analista": "Núcleo", "equipo": "Equipo", "guardian": "Guardián del PC",
               "imaginacion": "Imaginación"}
    for origen, textos in por_origen.items():
        if origen in titulos:
            lineas.append(f"  • {titulos[origen]}: " + " | ".join(t.split("\n")[0][:110] for t in textos[-3:]))
    e = _estado()
    if e["lecciones"]:
        l = e["lecciones"][-1]
        lineas.append(f"  • Lección del día ({l['fracaso']}): {l['leccion']}")
    if len(lineas) == 1:
        lineas.append("  • Día tranquilo: nada especial que reportar.")
    lineas.append("Descansa. Si me dejas prendida, sigo mejorándome mientras duermes.")
    return "\n".join(lineas)


# ------------------------------------------------------------------
# Reloj
# ------------------------------------------------------------------

_trabajando = threading.Event()


def revisar():
    """La llama el reloj del núcleo cada minuto."""
    e = _estado()
    if not e["activo"] or _trabajando.is_set():
        return
    for tipo, funcion, titulo in (("matutino", resumen_matutino, "Tu resumen de la mañana"),
                                  ("nocturno", resumen_nocturno, "Resumen del día")):
        if ritmo.momento_para(tipo):
            ritmo.marcar_entregado(tipo)
            _trabajando.set()

            def _entregar(funcion=funcion, titulo=titulo):
                try:
                    comun.informe(funcion(), titulo=titulo, importante=True, origen="cronista", con_prefijo=False)
                finally:
                    _trabajando.clear()
            comun.en_hilo(_entregar, nombre=f"arche-cronista-{tipo}")
            return
    # si se acabó el día sin entregar el nocturno, se guarda para la mañana
    ahora = comun.ahora()
    if ahora.hour == 3 and ahora.minute < 2 and not ritmo.ya_entregado("nocturno"):
        e["nocturno_pendiente"] = resumen_nocturno()
        _guardar(e)
        ritmo.marcar_entregado("nocturno")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_PONME = re.compile(r"^(?:ponme al dia|ponme al tanto|resumen de (?:la )?manana|resumen matutino|"
                      r"que paso hoy en el mundo|noticias resumidas|mi resumen de noticias)$")
_R_FRACASO = re.compile(r"^(?:fracaso del dia|otro fracaso|cuentame (?:un|otro) fracaso|un fracaso|"
                        r"dame un fracaso|historia de un fracaso)$")
_R_FRACASO_TEMA = re.compile(r"^(?:cuentame|dame|hay)\s+(?:un|algun)\s+fracaso\s+(?:de|sobre|con)\s+(.+)$")
_R_MAS = re.compile(r"^(?:cuentame|dime|amplia)\s+mas\s+(?:de|sobre)\s+la\s+(?:noticia\s+)?(\d+)$")
_R_NOCHE = re.compile(r"^(?:resumen de hoy|resumen de la noche|resumen nocturno|que hicimos hoy)$")
_R_LECCIONES = re.compile(r"^(?:lecciones|tus lecciones|que lecciones tienes)(?:\s+(?:de|sobre)\s+(.+))?$")
_R_SEPARECE = re.compile(r"^(?:se parece a algun fracaso|esto se parece a algun fracaso|esto ya ha fallado antes)\s*:?\s*(.+)$")
_R_TEMAS = re.compile(r"^(?:mis noticias|temas de (?:mis )?noticias|de que me das noticias)$")
_R_AGREGA = re.compile(r"^(?:agrega|añade|anade|pon)\s+(.+?)\s+a\s+(?:mis|las)\s+noticias$")
_R_QUITA = re.compile(r"^(?:quita|saca|elimina)\s+(.+?)\s+de\s+(?:mis|las)\s+noticias$")
_R_RITMO = re.compile(r"^(?:tu ritmo|mi ritmo|mis rutinas|cuando me das las noticias|a que hora me das las noticias|"
                      r"que sabes de mi horario)$")
_R_HORA = re.compile(r"^(?:dame|quiero)\s+(?:las noticias|el resumen de la manana|mi resumen)\s+a\s+las\s+"
                     r"(\d{1,2})(?:[:.\s](\d{2}))?(?:\s*(am|pm|de la manana|de la noche))?$")
_R_HORA_NOCHE = re.compile(r"^(?:dame\s+)?(?:el\s+)?resumen de la noche a las\s+(\d{1,2})(?:[:.\s](\d{2}))?$")


def _hora_desde(h, m, sufijo=None):
    h, m = int(h), int(m or 0)
    if sufijo in ("pm", "de la noche") and h < 12:
        h += 12
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return f"{h:02d}:{m:02d}"


def manejar(comando):
    texto = (comando or "").strip()
    c = comun.norm(texto)

    if _R_PONME.match(c):
        comun.msg("Dame un momento, reviso las noticias y te elijo un fracaso...")
        comun.en_hilo(lambda: comun.msg(resumen_matutino()), nombre="arche-cronista")
        return True
    if _R_FRACASO.match(c):
        f = elegir_fracaso()
        guardar_leccion(f)
        comun.en_hilo(lambda: comun.msg(contar_fracaso(f)), nombre="arche-cronista")
        return True
    m = _R_FRACASO_TEMA.match(c)
    if m:
        f = elegir_fracaso(m.group(1))
        if not f:
            comun.msg(f"No tengo un fracaso famoso de «{m.group(1)}» en mi biblioteca. Te cuento otro.")
            f = elegir_fracaso()
        guardar_leccion(f)
        comun.en_hilo(lambda: comun.msg(contar_fracaso(f)), nombre="arche-cronista")
        return True
    m = _R_MAS.match(c)
    if m:
        i = int(m.group(1)) - 1
        if not (0 <= i < len(_ultimas["items"])):
            comun.msg("No tengo esa noticia. Pídeme primero «ponme al día».")
            return True
        it = _ultimas["items"][i]

        def _ampliar():
            web = _web()
            cuerpo = web.leer_pagina(it.get("url", ""), maximo=3500) if it.get("url") else ""
            r = comun.pensar(f"Resume en 5 frases en español esta noticia: «{it['titulo']}». Usa solo este texto; si "
                             f"está vacío o no sirve, dilo.\n\n{cuerpo}", max_tokens=350, temperatura=0.2)
            comun.msg(r or f"No pude leer la noticia completa. Título: {it['titulo']}\n{it.get('url', '')}")
        comun.en_hilo(_ampliar, nombre="arche-cronista")
        return True
    if _R_NOCHE.match(c):
        comun.msg(resumen_nocturno())
        return True
    m = _R_LECCIONES.match(c)
    if m:
        e = _estado()
        lecciones = e["lecciones"]
        if m.group(1):
            lecciones = [l for l in lecciones if comun.parecido(m.group(1), l["fracaso"] + " " + l["leccion"] + " " +
                                                                " ".join(l.get("claves", []))) > 0.05]
        if not lecciones:
            comun.msg("Todavía no tengo lecciones guardadas de eso. Pídeme «fracaso del día».")
        else:
            comun.msg("Lecciones que aprendí de fracasos:\n" +
                      "\n".join(f"  • {l['fracaso']}: {l['leccion']}" for l in lecciones[-10:]))
        return True
    m = _R_SEPARECE.match(c)
    if m:
        aviso = advertir(m.group(1), minimo=0.0)
        comun.msg(aviso or "No se parece a ningún fracaso que conozca. Buena señal.")
        return True
    if _R_TEMAS.match(c):
        comun.msg("Te traigo noticias generales y de estos temas: " + ", ".join(_estado()["temas"]) +
                  ". Di «agrega X a mis noticias» o «quita X de mis noticias».")
        return True
    m = _R_AGREGA.match(c)
    if m:
        e = _estado()
        if m.group(1) not in e["temas"]:
            e["temas"].append(m.group(1))
            _guardar(e)
        comun.msg(f"Listo, también te traigo noticias de {m.group(1)}.")
        return True
    m = _R_QUITA.match(c)
    if m:
        e = _estado()
        antes = len(e["temas"])
        e["temas"] = [t for t in e["temas"] if comun.parecido(t, m.group(1)) < 0.5 and comun.norm(t) != m.group(1)]
        _guardar(e)
        comun.msg("Quitado." if len(e["temas"]) < antes else "Ese tema no estaba en tus noticias.")
        return True
    if _R_RITMO.match(c):
        comun.msg(ritmo.describir())
        return True
    m = _R_HORA.match(c)
    if m:
        hhmm = _hora_desde(m.group(1), m.group(2), m.group(3))
        if not hhmm:
            comun.msg("Esa hora no me cuadra. Prueba «dame las noticias a las 6:30».")
            return True
        ritmo.fijar_hora("matutino", hhmm)
        comun.msg(f"Listo: tu resumen de la mañana sale a las {hhmm} (o apenas llegues al PC después de esa hora).")
        return True
    m = _R_HORA_NOCHE.match(c)
    if m:
        hhmm = _hora_desde(m.group(1), m.group(2), "pm" if int(m.group(1)) < 12 else None)
        ritmo.fijar_hora("nocturno", hhmm)
        comun.msg(f"Listo: el resumen de la noche sale a las {hhmm}.")
        return True
    if c in ("noticias a tu ritmo", "aprende cuando darme las noticias", "quita la hora fija"):
        ritmo.fijar_hora("matutino", None)
        ritmo.fijar_hora("nocturno", None)
        comun.msg("Listo: vuelvo a darte los resúmenes según tu ritmo.")
        return True
    if c in ("resumenes apagados", "no me des resumenes", "apaga los resumenes"):
        e = _estado(); e["activo"] = False; _guardar(e)
        comun.msg("Listo, no te mando resúmenes solos. Puedes pedirlos con «ponme al día».")
        return True
    if c in ("resumenes encendidos", "activa los resumenes", "mandame resumenes"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg("Listo, te mando el resumen de la mañana y el de la noche en el momento justo.")
        return True
    return False
