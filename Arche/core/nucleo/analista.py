"""
analista.py
-----------
Ubicacion: Arche/core/nucleo/analista.py

El NÚCLEO DE ARCHÉ como cerebro de la fábrica de habilidades (la Fase 6 de core/evolucion.py).

  1. ANÁLISIS PREVIO: antes de que una habilidad nueva entre a Arché (la fabrique ella,
     la cace el Depredador o salga de una combinación), el núcleo la revisa: que tenga
     pruebas de verdad (3+ asserts), palabras clave que no secuestren la charla
     ("hola", "que"...), descripción, tamaño razonable. Si no pasa, no entra.
  2. NIVELES: cada habilidad sube de nivel según cómo le va de verdad:
        Aprendiz -> Confiable (5 aciertos) -> Experta (15) -> Maestra (40, casi sin fallos)
     Si falla mucho baja, y si falla más de lo que acierta se descarta.
     Di «la habilidad falló» cuando una respuesta de habilidad esté mal.
  3. COMBINAR: dos habilidades se combinan en una mejor («combina X y Y», o sola cuando
     hay dos Expertas). Pasa por la misma caja de arena que todo lo demás.
  4. VERSIONES DEL NÚCLEO: con puntos (habilidades, presas, combinaciones, misiones del equipo)
     el núcleo sube de versión:
        Núcleo 1.0              avisos con «Respuesta:», piensa con 3 enfoques, 1 presa por día, equipo de 3 a la vez
        Núcleo 2.0 (100 puntos) avisos con «Informe:», piensa con 5 enfoques, 2 presas, equipo de 4,
                                imagina futuros antes de CADA cambio de su código
        Núcleo 3.0 (300 puntos) 3 presas por día, equipo de 5 a la vez

Se conecta solo (instalar_ganchos): no hay que tocar core/evolucion.py.
"""

import ast
import os
import re
import threading

from core.nucleo import comun

ARCH_ESTADO = comun.ruta("analista.json")

RANGOS = ["Aprendiz", "Confiable", "Experta", "Maestra"]
VALOR_RANGO = {"Aprendiz": 1, "Confiable": 3, "Experta": 8, "Maestra": 20}
VERSIONES = [(1, 0), (2, 100), (3, 300)]          # (versión, puntos necesarios)

_PALABRAS_GENERICAS = {"que", "hola", "como", "para", "por", "dime", "quiero", "puedes", "haz", "hacer", "arche",
                       "esto", "eso", "algo", "cosa", "cual", "donde", "cuando", "the", "and", "una", "uno"}

_lock = threading.RLock()
_estado_memoria = {"ultimo_usado": None}
_ganchos_instalados = False


# ------------------------------------------------------------------
# Estado
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH_ESTADO, {})
    e.setdefault("version", 1)
    e.setdefault("habilidades", {})
    e.setdefault("fusiones", 0)
    e.setdefault("evolucionado_en", "")
    e.setdefault("ultima_fusion_auto", "")
    return e


def _guardar(e):
    comun.guardar(ARCH_ESTADO, e)


def version():
    try:
        return max(1, min(3, int(_estado().get("version", 1))))
    except (TypeError, ValueError):
        return 1


def nombre_etapa():
    return f"Núcleo {version()}.0"


def _evo():
    from core import evolucion
    return evolucion


def _habilidades_registradas():
    try:
        evo = _evo()
        return evo._cargar(evo.ARCH_HABILIDADES, {})
    except Exception:
        return {}


def _rango(h):
    r = h.get("rango", "Aprendiz")
    return r if r in RANGOS else "Aprendiz"


# ------------------------------------------------------------------
# 1. Análisis previo de una habilidad
# ------------------------------------------------------------------

def analizar_habilidad(codigo):
    """(ok, motivo, datos). Lo que el núcleo exige antes de dejar entrar una habilidad."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError as e:
        return False, f"error de sintaxis (línea {e.lineno})", {}
    datos = {"lineas": len(codigo.splitlines()), "palabras": [], "asserts": 0, "descripcion": ""}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(getattr(t, "id", "") == "PALABRAS" for t in nodo.targets):
            try:
                datos["palabras"] = [str(p) for p in ast.literal_eval(nodo.value)]
            except (ValueError, SyntaxError):
                return False, "PALABRAS no es una lista fija", datos
        if isinstance(nodo, ast.Assign) and any(getattr(t, "id", "") == "DESCRIPCION" for t in nodo.targets):
            if isinstance(nodo.value, ast.Constant):
                datos["descripcion"] = str(nodo.value.value)
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "probar":
            datos["asserts"] = sum(isinstance(n, ast.Assert) for n in ast.walk(nodo)) + \
                sum(1 for n in ast.walk(nodo) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "probar")
    if datos["lineas"] > 400:
        return False, "es demasiado larga para una habilidad (más de 400 líneas)", datos
    if not datos["palabras"]:
        return False, "no tiene PALABRAS que la activen", datos
    utiles = [p for p in datos["palabras"] if comun.norm(p) not in _PALABRAS_GENERICAS and len(comun.norm(p)) >= 3]
    if not utiles:
        return False, "sus PALABRAS son tan comunes que se robaría la conversación", datos
    if datos["asserts"] < 3:
        return False, f"su probar() solo comprueba {datos['asserts']} cosa(s); exijo 3 o más", datos
    if not datos["descripcion"]:
        return False, "no tiene DESCRIPCION", datos
    return True, "ok", datos


# ------------------------------------------------------------------
# 2. Niveles
# ------------------------------------------------------------------

def rango_de(info):
    e, f = int(info.get("exitos", 0)), int(info.get("fallos", 0))
    piso = info.get("rango_minimo", "Aprendiz")
    if piso not in RANGOS:
        piso = "Aprendiz"
    if e >= 40 and f <= 2:
        r = "Maestra"
    elif e >= 15 and f * 3 <= e:
        r = "Experta"
    elif e >= 5 and f * 2 <= e:
        r = "Confiable"
    else:
        r = "Aprendiz"
    return r if RANGOS.index(r) >= RANGOS.index(piso) or f > e else piso


def debe_descartarse(info):
    e, f = int(info.get("exitos", 0)), int(info.get("fallos", 0))
    return f >= 5 and f > e


def registrar_exito(nombre):
    with _lock:
        e = _estado()
        h = e["habilidades"].setdefault(nombre, {"exitos": 0, "fallos": 0, "origen": "fabrica"})
        h["exitos"] = int(h.get("exitos", 0)) + 1
        _guardar(e)
    _estado_memoria["ultimo_usado"] = nombre


def registrar_fallo(nombre=None):
    nombre = nombre or _estado_memoria.get("ultimo_usado")
    if not nombre:
        return None
    with _lock:
        e = _estado()
        h = e["habilidades"].setdefault(nombre, {"exitos": 0, "fallos": 0, "origen": "fabrica"})
        h["fallos"] = int(h.get("fallos", 0)) + 1
        _guardar(e)
    return nombre


def registrar_origen(nombre, origen, **extra):
    with _lock:
        e = _estado()
        h = e["habilidades"].setdefault(nombre, {"exitos": 0, "fallos": 0})
        h["origen"] = origen
        h.update(extra)
        _guardar(e)


def sincronizar_y_rangos(avisar=True):
    """Pone al día los niveles con lo que realmente pasó. Devuelve la lista de cambios."""
    cambios = []
    registradas = _habilidades_registradas()
    with _lock:
        e = _estado()
        for nombre, info_evo in registradas.items():
            h = e["habilidades"].setdefault(nombre, {"exitos": 0, "fallos": 0, "origen": "fabrica"})
            h["exitos"] = max(int(h.get("exitos", 0)), int(info_evo.get("usos", 0)))
            h.setdefault("tarea", info_evo.get("tarea", nombre))
            nuevo = rango_de(h)
            viejo = _rango(h)
            h["rango"] = nuevo
            if nuevo != viejo:
                cambios.append((nombre, viejo, nuevo, RANGOS.index(nuevo) > RANGOS.index(viejo)))
        _guardar(e)
    for nombre, viejo, nuevo, sube in cambios:
        if avisar:
            tarea = e["habilidades"][nombre].get("tarea", nombre)
            if sube:
                comun.informe(f"La habilidad «{tarea}» subió de nivel: {viejo} → {nuevo}.", nivel="logro",
                              origen="analista")
            else:
                comun.informe(f"La habilidad «{tarea}» bajó de nivel por fallar: {viejo} → {nuevo}.",
                              origen="analista")
    return cambios


def descartar_las_malas():
    descartadas = []
    registradas = _habilidades_registradas()
    e = _estado()
    for nombre, h in list(e["habilidades"].items()):
        if nombre in registradas and debe_descartarse(h):
            try:
                evo = _evo()
                with evo._lock:
                    hab = evo._cargar(evo.ARCH_HABILIDADES, {})
                    hab.pop(nombre, None)
                    evo._guardar(evo.ARCH_HABILIDADES, hab)
            except Exception:
                continue
            h["descartada"] = comun.ahora_txt()
            descartadas.append(h.get("tarea", nombre))
    _guardar(e)
    for t in descartadas:
        comun.informe(f"Descarté la habilidad «{t}»: fallaba más de lo que acertaba. La anoto otra vez como "
                      "algo que no sé, para intentarlo mejor.", origen="analista")
        try:
            _evo().anotar_no_se(t, "tarea")
        except Exception:
            pass
    return descartadas


# ------------------------------------------------------------------
# 3. Combinar habilidades
# ------------------------------------------------------------------

def _leer_habilidad(nombre):
    try:
        with open(os.path.join(_evo().CARPETA_HABILIDADES, nombre + ".py"), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _palabras_de(codigo):
    try:
        for n in ast.parse(codigo).body:
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PALABRAS" for t in n.targets):
                return [str(p) for p in ast.literal_eval(n.value)]
    except Exception:
        pass
    return []


def plantilla_fusion(a, b, desc_a, desc_b, palabras):
    return (
        f'"""Combinación de dos habilidades de Arché: {a} + {b}. Hecha por el {nombre_etapa()}."""\n'
        f"from core.habilidades_auto import {a} as _h1\n"
        f"from core.habilidades_auto import {b} as _h2\n\n"
        f"PALABRAS = {sorted(set(palabras))!r}\n"
        f"DESCRIPCION = {('Combinación: ' + desc_a + ' + ' + desc_b)[:200]!r}\n\n\n"
        "def ejecutar(texto):\n"
        "    respuestas = []\n"
        "    for h in (_h1, _h2):\n"
        "        try:\n"
        "            r = h.ejecutar(texto)\n"
        "        except Exception:\n"
        "            r = ''\n"
        "        if r:\n"
        "            respuestas.append(str(r))\n"
        "    return '\\n'.join(respuestas)\n\n\n"
        "def probar():\n"
        "    _h1.probar()\n"
        "    _h2.probar()\n"
        "    assert isinstance(ejecutar('prueba'), str)\n"
    )


def _buscar_nombre(texto):
    """De lo que dices ('la de conversiones') a un nombre de habilidad registrado."""
    registradas = _habilidades_registradas()
    t = comun.norm(texto)
    if t.replace(" ", "_") in registradas:
        return t.replace(" ", "_")
    mejor, puntaje = None, 0.0
    for nombre, info in registradas.items():
        p = max(comun.parecido(t, nombre.replace("_", " ")), comun.parecido(t, info.get("tarea", "")))
        if p > puntaje:
            mejor, puntaje = nombre, p
    return mejor if puntaje >= 0.2 else None


def fusionar(a, b, avisar=True):
    """Combina dos habilidades registradas. Devuelve (ok, explicación)."""
    evo = _evo()
    registradas = _habilidades_registradas()
    if a not in registradas or b not in registradas or a == b:
        return False, "necesito dos habilidades distintas que ya tenga"
    cod_a, cod_b = _leer_habilidad(a), _leer_habilidad(b)
    if not cod_a or not cod_b:
        return False, "no encontré el código de alguna de las dos"
    desc_a = registradas[a].get("tarea", a)
    desc_b = registradas[b].get("tarea", b)
    palabras = _palabras_de(cod_a) + _palabras_de(cod_b)
    nombre = re.sub(r"[^a-z0-9_]", "", f"combinada_{a[:18]}_{b[:18]}")[:48]

    candidatos = []
    r = comun.pensar(
        "Combina estas dos habilidades de Arché en UNA sola, mejor que la suma: que entienda las dos tareas y, "
        "si tiene sentido, las combine. Mismo formato:\n"
        "  def ejecutar(texto: str) -> str\n  def probar() -> None   # 4+ asserts\n"
        "  PALABRAS = [...]\n  DESCRIPCION = '...'\n"
        "Reglas: sin internet, sin archivos, sin os ni subprocess, sin eval/exec. Solo el código.\n\n"
        f"HABILIDAD A ({desc_a}):\n{cod_a[:3500]}\n\nHABILIDAD B ({desc_b}):\n{cod_b[:3500]}",
        temperatura=0.2, codigo=True, max_tokens=1400)
    codigo_llm = re.sub(r"```(?:python)?", "", r or "").strip()
    if codigo_llm:
        candidatos.append(("mejorada", codigo_llm))
    candidatos.append(("unida", plantilla_fusion(a, b, desc_a, desc_b, palabras)))

    for tipo, codigo in candidatos:
        ok, _ = evo._codigo_seguro(codigo)
        if not ok:
            continue
        ok, _, _ = analizar_habilidad(codigo)
        if not ok:
            continue
        rel = f"core/habilidades_auto/{nombre}.py"
        prueba = (f"import sys; sys.path.insert(0, '.')\nfrom core.habilidades_auto import {nombre} as h\n"
                  "h.probar()\nprint('ok')\n")
        aplicado, _ = evo.aplicar_cambio_autonomo({rel: codigo}, f"combinar habilidades: {a} + {b}",
                                                  prueba_extra=prueba)
        if not aplicado:
            continue
        with evo._lock:
            hab = evo._cargar(evo.ARCH_HABILIDADES, {})
            hab[nombre] = {"tarea": f"{desc_a} + {desc_b}", "creada": comun.ahora_txt(), "usos": 0,
                           "fusion_de": [a, b]}
            # la combinada reemplaza a las dos (sus archivos se quedan: la unida los usa por dentro)
            hab.pop(a, None)
            hab.pop(b, None)
            evo._guardar(evo.ARCH_HABILIDADES, hab)
        with _lock:
            e = _estado()
            ra, rb = _rango(e["habilidades"].get(a, {})), _rango(e["habilidades"].get(b, {}))
            piso = "Maestra" if ra == rb == "Experta" or "Maestra" in (ra, rb) else \
                ("Experta" if "Confiable" in (ra, rb) or "Experta" in (ra, rb) else "Confiable")
            e["habilidades"][nombre] = {"exitos": 0, "fallos": 0, "origen": "fusion", "fusion_de": [a, b],
                                        "tarea": f"{desc_a} + {desc_b}", "rango_minimo": piso, "rango": piso}
            e["fusiones"] = int(e.get("fusiones", 0)) + 1
            _guardar(e)
        if avisar:
            comun.informe(f"Combiné «{desc_a}» y «{desc_b}» en una habilidad de nivel {piso}.", importante=True,
                          nivel="logro", origen="analista")
        return True, f"listo ({tipo}, nivel {piso})"
    return False, "ninguna versión de la combinación pasó mis pruebas"


def fusion_automatica():
    """Una vez al día: si hay dos habilidades Expertas sin combinar, las intenta combinar."""
    e = _estado()
    if e.get("ultima_fusion_auto") == comun.hoy():
        return None
    registradas = _habilidades_registradas()
    expertas = [n for n, h in e["habilidades"].items()
                if n in registradas and _rango(h) in ("Experta", "Maestra") and h.get("origen") != "fusion"]
    if len(expertas) < 2:
        return None
    e["ultima_fusion_auto"] = comun.hoy()
    _guardar(e)
    return fusionar(expertas[0], expertas[1])


# ------------------------------------------------------------------
# 4. Versiones del núcleo
# ------------------------------------------------------------------

def puntos():
    e = _estado()
    registradas = _habilidades_registradas()
    total = sum(VALOR_RANGO[_rango(h)] for n, h in e["habilidades"].items() if n in registradas)
    total += 10 * int(e.get("fusiones", 0))
    try:
        from core.nucleo import depredador
        total += 5 * depredador.presas_absorbidas()
    except Exception:
        pass
    try:
        from core.nucleo import equipo
        total += 2 * equipo.misiones_completadas() + 3 * equipo.niveles_del_equipo()
    except Exception:
        pass
    return total


_MEJORAS = {
    2: ["Mis avisos ahora empiezan con «Informe:».",
        "Pienso en paralelo con 5 enfoques en vez de 3.",
        "El Depredador caza hasta 2 presas por día.",
        "El equipo trabaja con 4 miembros a la vez.",
        "Imagino futuros antes de cada cambio a mi código."],
    3: ["El Depredador caza hasta 3 presas por día.",
        "El equipo trabaja con 5 miembros a la vez."],
}


def revisar_evolucion():
    """Sube de versión si ya tiene los puntos. Devuelve True si subió."""
    actual = version()
    p = puntos()
    nueva = actual
    for v, necesarios in VERSIONES:
        if p >= necesarios:
            nueva = max(nueva, v)
    if nueva <= actual:
        return False
    e = _estado()
    e["version"] = nueva
    e["evolucionado_en"] = comun.ahora_txt()
    _guardar(e)
    mejoras = [m for v in range(actual + 1, nueva + 1) for m in _MEJORAS.get(v, [])]
    comun.informe(
        f"{comun.nombre_usuario()}, mi núcleo se actualizó: Núcleo {actual}.0 → Núcleo {nueva}.0.\n" +
        "\n".join(f"  • {m}" for m in mejoras),
        importante=True, nivel="logro", origen="analista", con_prefijo=False)
    return True


def revisar():
    """La llama el reloj del núcleo cada pocos minutos."""
    sincronizar_y_rangos()
    descartar_las_malas()
    fusion_automatica()
    revisar_evolucion()


# ------------------------------------------------------------------
# Ganchos sobre core/evolucion.py (sin modificar ese archivo)
# ------------------------------------------------------------------

def instalar_ganchos():
    global _ganchos_instalados
    if _ganchos_instalados:
        return
    evo = _evo()

    # core/nucleo es núcleo protegido: Arché no lo puede reescribir sola.
    carpeta = os.path.dirname(os.path.abspath(__file__))
    for nombre in os.listdir(carpeta):
        if nombre.endswith(".py"):
            evo.NUCLEO_PROTEGIDO.add(f"core/nucleo/{nombre}")

    original_usar = evo.usar_habilidad

    def usar_habilidad_con_niveles(texto):
        antes = {n: i.get("usos", 0) for n, i in _habilidades_registradas().items()}
        respuesta = original_usar(texto)
        if respuesta:
            for n, i in _habilidades_registradas().items():
                if i.get("usos", 0) > antes.get(n, 0):
                    registrar_exito(n)
                    break
        return respuesta

    evo.usar_habilidad = usar_habilidad_con_niveles

    original_aplicar = evo.aplicar_cambio_autonomo

    def aplicar_con_analisis(cambios, motivo, prueba_extra=None):
        for rel, texto in (cambios or {}).items():
            rel_n = rel.replace("\\", "/")
            if rel_n.startswith("core/habilidades_auto/") and not rel_n.endswith("__init__.py"):
                ok, por_que, _ = analizar_habilidad(texto)
                if not ok:
                    try:
                        evo._diario("analista_rechazo", f"{rel_n}: {por_que}", motivo=motivo)
                    except Exception:
                        pass
                    return False, f"el núcleo la rechazó: {por_que}"
        return original_aplicar(cambios, motivo, prueba_extra=prueba_extra)

    evo.aplicar_cambio_autonomo = aplicar_con_analisis
    _ganchos_instalados = True


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_FUSIONA = re.compile(r"^(?:combina|fusiona|une|junta)\s+(?:las?\s+habilidad(?:es)?\s+)?(.+?)\s+(?:y|con)\s+(.+)$")
_R_FALLO = re.compile(r"^(?:esa|la|tu)\s+habilidad\s+(?:fallo|estuvo mal|se equivoco)$|"
                      r"^la\s+ultima\s+habilidad\s+(?:fallo|estuvo mal)$")


def _texto_estado():
    e = _estado()
    registradas = _habilidades_registradas()
    activas = {n: h for n, h in e["habilidades"].items() if n in registradas}
    por_rango = {r: 0 for r in RANGOS}
    for h in activas.values():
        por_rango[_rango(h)] += 1
    p = puntos()
    v = version()
    siguiente = next(((ver, n) for ver, n in VERSIONES if ver > v), None)
    cabeza = f"Núcleo {v}.0" + (f" — subo al {siguiente[0]}.0 con {siguiente[1]} puntos: llevo {p}." if siguiente
                                 else f" — versión máxima ({p} puntos).")
    linea = ", ".join(f"{r}: {n}" for r, n in por_rango.items())
    return (f"{cabeza}\n  Habilidades activas: {len(activas)} ({linea})\n"
            f"  Combinaciones: {e.get('fusiones', 0)}\n"
            "  Puntos: habilidades por nivel (1/3/8/20) + combinaciones x10 + presas x5 + misiones x2 "
            "+ niveles del equipo x3")


def manejar(comando):
    c = comun.norm(comando)
    if c in ("estado del nucleo", "nucleo", "tu nucleo", "version del nucleo", "en que version estas",
             "tu evolucion", "como va tu evolucion", "como va el nucleo"):
        comun.msg(_texto_estado())
        return True
    if c in ("rangos", "niveles de habilidades", "tus niveles", "habilidades con nivel", "nivel de tus habilidades"):
        sincronizar_y_rangos(avisar=False)
        e = _estado()
        registradas = _habilidades_registradas()
        filas = [(_rango(h), h.get("tarea", n), h.get("exitos", 0), h.get("fallos", 0), h.get("origen", ""))
                 for n, h in e["habilidades"].items() if n in registradas]
        if not filas:
            comun.msg("Todavía no tengo habilidades con nivel. Aparecen cuando la fábrica o el Depredador consiguen una.")
        else:
            filas.sort(key=lambda f: (-RANGOS.index(f[0]), -f[2]))
            comun.msg("Mis habilidades:\n" + "\n".join(
                f"  [{r}] {t} — {ex} aciertos, {fa} fallos" + (f" ({o})" if o and o != "fabrica" else "")
                for r, t, ex, fa, o in filas))
        return True
    m = _R_FUSIONA.match(c)
    if m:
        a, b = _buscar_nombre(m.group(1)), _buscar_nombre(m.group(2))
        if not a or not b:
            comun.msg("No reconocí alguna de las dos habilidades. Di «rangos» para ver cuáles tengo.")
            return True
        comun.msg(f"Voy a combinar «{a}» y «{b}». Lo pruebo en una copia aparte; te aviso.")
        comun.en_hilo(lambda: comun.msg("Combinación: " + fusionar(a, b)[1]), nombre="arche-combinar")
        return True
    if _R_FALLO.match(c):
        nombre = registrar_fallo()
        comun.msg(f"Anotado: la habilidad «{nombre}» falló. Si sigue fallando, baja de nivel o la descarto."
                  if nombre else "No he usado ninguna habilidad fabricada todavía en esta sesión.")
        return True
    if c in ("revisa tu evolucion", "actualiza tu nucleo"):
        if not revisar_evolucion():
            comun.msg(_texto_estado())
        return True
    return False
