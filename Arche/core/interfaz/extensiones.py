"""
extensiones.py
--------------
Ubicacion: Arche/core/interfaz/extensiones.py

Extensiones: paquetes pequeños (un .json en Database/extensiones) que añaden
cosas a Arché sin tocar su codigo. Son solo datos, nunca codigo: no pueden
ejecutar nada por su cuenta. Se activan y desactivan cuando quieras.

TIPOS (cada uno es una entrada del registro TIPOS; se pueden agregar mas):
  tema       colores y, si quiere, algunos ajustes visuales (tamaño, escena…)
  widget     un panel armado con BLOQUES (texto, botones, lista, temporizador,
             reloj, datos de Arché…; ver bloques_ext.py y LEEME.md)
  ejemplos   un paquete de frases ya clasificadas para entrenar a Arché

PERMISOS (cada extension declara los que usa; si usa uno que no declaro, se rechaza):
  comandos           los botones le mandan ordenes a Arché
  archivos_propios   lee .txt que viajan junto a la extension
  datos              muestra datos de Arché (redes, frases que no entendio…)
  ejemplos           agrega ejemplos de entrenamiento (y los puede quitar al desactivarla)
Un tema NUNCA pide permisos. Ninguna extension lee tus archivos personales ni
ejecuta comandos del sistema.

COMO AMPLIAR (sin tocar la ventana):
  - Un tipo nuevo:      registrar_tipo_ext("mi_tipo", validar, activar, desactivar, activa, resumen)
  - Un bloque nuevo:    bloques_ext.registrar_bloque(...)
  - Una fuente nueva:   bloques_ext.registrar_fuente(...)
  - Todo eso desde un archivo .py en core/interfaz/complementos/ que defina
    registrar(api): se carga solo al iniciar y al «volver a buscar».
  - Galeria: cualquier .json valido en core/interfaz/galeria aparece para instalar.
  - LEEME.md en Database/extensiones se regenera solo con lo que hay registrado.

Formato:
  {"arche_extension": 1, "nombre": "Mi panel", "tipo": "widget", "titulo": "…", "descripcion": "…",
   "permisos": ["comandos"], "bloques": [{"tipo": "texto", "texto": "Hola"},
   {"tipo": "botones", "botones": [{"texto": "Luz", "orden": "enciende la luz"}]}]}
  Opcional, solo en widgets: "aparece_si": "hay_no_entendidas" (el panel aparece solo cuando hay algo que hacer).
  Las condiciones: hay_avisos, algo_en_curso, hay_alarmas, hay_mejoras, redes_sin_entrenar, hay_no_entendidas,
  hay_dudosas, temporizador_activo, hay_en_lista, alerta_equipo.
"""

import importlib.util
import json
import os
import re
import shutil

from . import ajustes, bloques_ext, layout, tema

try:
    from core.rutas import DATABASE
except Exception:
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Database")

_AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(DATABASE, "extensiones")
GALERIA = os.path.join(_AQUI, "galeria")
COMPLEMENTOS = os.path.join(_AQUI, "complementos")
PERMISOS = ("comandos", "archivos_propios", "datos", "ejemplos")
_cargadas = {}          # nombre -> dict validado
_escaneado = False
errores = []            # por que se rechazo cada una
TIPOS = {}              # nombre -> {"validar", "activar", "desactivar", "activa", "resumen", "ayuda"}

# ajustes visuales que un tema puede traer (nada de comportamiento, cuentas ni archivos)
AJUSTES_TEMA = ("ui_escala", "texto_escala", "alto_contraste", "reducir_movimiento", "escena", "escena_intensidad",
                "escena_velocidad", "escena_brillo", "fluidez", "efecto_sombra", "efecto_borde_luminoso", "efecto_brillo",
                "efecto_profundidad", "efecto_particulas", "chat_vista", "chat_tam", "chat_ancho", "sistema_estilo",
                "estilo_voz", "orbe_tamano", "navegacion", "nav_etiquetas", "mascota", "anim_velocidad")


def _limpio(n):
    return re.sub(r"[^\w \-]", "", str(n)).strip()[:30]


def registrar_tipo_ext(nombre, validar, activar=None, desactivar=None, activa=None, resumen=None, ayuda=""):
    """Agrega un tipo de extension. validar(crudo, nombre, permisos, carpeta) -> (True, ext) | (False, motivo)."""
    TIPOS[nombre] = {"validar": validar, "activar": activar, "desactivar": desactivar, "activa": activa,
                     "resumen": resumen, "ayuda": ayuda}


# ------------------------------------------------------------------ validar
def validar(crudo, carpeta=None):
    """(True, ext) o (False, motivo)."""
    if not isinstance(crudo, dict) or crudo.get("arche_extension") != 1:
        return False, "no es una extensión de Arché (falta arche_extension: 1)"
    nombre = _limpio(crudo.get("nombre"))
    if not nombre:
        return False, "falta el nombre"
    tipo = crudo.get("tipo")
    permisos = crudo.get("permisos") or []
    if not isinstance(permisos, list) or any(p not in PERMISOS for p in permisos):
        return False, "pide permisos que no existen (los válidos: " + ", ".join(PERMISOS) + ")"
    if tipo not in TIPOS:
        return False, "tipo desconocido (los que hay: " + ", ".join(TIPOS) + ")"
    ok, ext = TIPOS[tipo]["validar"](crudo, nombre, list(permisos), carpeta or CARPETA)
    if not ok:
        return False, ext
    ext.setdefault("tipo", tipo)
    ext["descripcion"] = str(crudo.get("descripcion") or "")[:160]
    # «aparece_si»: condicion con la que un widget aparece solo cuando hay algo (ver orden.CONDICIONES)
    from . import orden
    cond = str(crudo.get("aparece_si") or "")
    ext["aparece_si"] = cond if cond in orden.CONDICIONES else ""
    return True, ext


def _v_tema(crudo, nombre, permisos, carpeta):
    if permisos:
        return False, "un tema no puede pedir permisos"
    cols = {r: ajustes.normalizar_hex(v) for r, v in (crudo.get("colores") or {}).items() if r in tema.ROLES}
    cols = {r: v for r, v in cols.items() if v}
    aj = {}
    for k, val in (crudo.get("ajustes") or {}).items():
        if k not in AJUSTES_TEMA:
            return False, f"el ajuste «{k}» no se puede cambiar desde un tema (los permitidos: {', '.join(AJUSTES_TEMA)})"
        ok, v = ajustes.validar(k, val)
        if not ok:
            return False, f"ajuste «{k}»: {v}"
        aj[k] = v
    if not cols and not aj:
        return False, "el tema no trae ningún color ni ajuste válido"
    return True, {"nombre": nombre, "tipo": "tema", "colores": cols, "ajustes": aj, "permisos": []}


def _a_tema(ext):
    if ext["colores"] and tema.resolver("ext " + ext["nombre"]) is None:
        tema._cargar_personales()["ext " + ext["nombre"]] = {"nombre": "ext " + ext["nombre"], "base": "arche", "colores": ext["colores"]}
        tema._guardar_personales()
    previo = bloques_ext.estado_get(ext["nombre"], "previo")
    if previo is None:
        previo = {"tema": ajustes.obtener("tema"), "ajustes": {k: ajustes.obtener(k) for k in ext["ajustes"]}}
        bloques_ext.estado_set(ext["nombre"], "previo", previo)
    for k, v in ext["ajustes"].items():
        ajustes.fijar(k, v)
    if ext["colores"]:
        ajustes.fijar("tema", "ext " + ext["nombre"])
    bloques_ext.estado_set(ext["nombre"], "activo", True)
    return True, f"activé el tema «{ext['nombre']}»"


def _d_tema(ext):
    previo = bloques_ext.estado_get(ext["nombre"], "previo") or {}
    for k, v in (previo.get("ajustes") or {}).items():
        ajustes.fijar(k, v)
    if ajustes.obtener("tema") == "ext " + ext["nombre"]:
        p = previo.get("tema") or "arche"
        ajustes.fijar("tema", "arche" if (p == "ext " + ext["nombre"] or tema.resolver(p) is None) else p)
    bloques_ext.estado_borrar(ext["nombre"])
    return True, f"desactivé el tema «{ext['nombre']}»"


def _on_tema(ext):
    if ext["colores"]:
        return ajustes.obtener("tema") == "ext " + ext["nombre"]
    return bool(bloques_ext.estado_get(ext["nombre"], "activo"))


registrar_tipo_ext("tema", _v_tema, _a_tema, _d_tema, _on_tema,
                   lambda e: f"{len(e['colores'])} colores" + (f" · {len(e['ajustes'])} ajustes" if e["ajustes"] else ""),
                   ayuda='{"tipo":"tema","colores":{"fondo":"#140508"},"ajustes":{"ui_escala":140}}  (colores: ver tema.ROLES)')


# ------------------------------------------------------------------ widget (bloques)
def _v_widget(crudo, nombre, permisos, carpeta):
    crudos = list(crudo.get("bloques") or [])
    # formato corto de siempre: lineas / botones / archivo
    if not crudos:
        for l in (crudo.get("lineas") or [])[:30]:
            crudos.append({"tipo": "texto", "texto": str(l)})
        if crudo.get("archivo"):
            crudos.append({"tipo": "lista", "archivo": crudo["archivo"], "marcable": False, "max": 10})
        if crudo.get("botones"):
            crudos.append({"tipo": "botones", "botones": crudo["botones"]})
    if not crudos:
        return False, "el widget no trae bloques"
    bloques, necesarios = [], set()
    for i, b in enumerate(crudos[:8]):
        if not isinstance(b, dict) or b.get("tipo") not in bloques_ext.BLOQUES:
            return False, f"bloque {i + 1}: tipo desconocido «{b.get('tipo') if isinstance(b, dict) else b}» (los que hay: {', '.join(bloques_ext.BLOQUES)})"
        spec = bloques_ext.BLOQUES[b["tipo"]]
        ok, nb = spec["validar"](b, {"nombre": nombre, "carpeta": carpeta})
        if not ok:
            return False, f"bloque {i + 1}: {nb}"
        necesarios.update(spec["permisos"])
        if nb["tipo"] == "dato":
            necesarios.update(bloques_ext.FUENTES[nb["fuente"]]["permisos"])
        bloques.append(nb)
    for p in sorted(necesarios):
        if p not in permisos:
            return False, f"usa bloques que necesitan el permiso «{p}» y no lo declara"
    ancho, alto = crudo.get("ancho", 6), crudo.get("alto", 5)
    ancho = ancho if isinstance(ancho, int) and 3 <= ancho <= 12 else 6
    alto = alto if isinstance(alto, int) and 2 <= alto <= 12 else 5
    return True, {"nombre": nombre, "tipo": "widget", "titulo": str(crudo.get("titulo") or nombre)[:30], "bloques": bloques,
                  "permisos": list(permisos), "carpeta": carpeta, "ancho": ancho, "alto": alto}


def _widgets_de(ext):
    from . import perfiles
    return [w for w in perfiles.layout_actual()["widgets"] if w["tipo"] == "ext:" + ext["nombre"]]


def _a_widget(ext):
    from . import perfiles
    existentes = _widgets_de(ext)
    if existentes:
        ok, msg = layout.mostrar(perfiles.layout_actual(), existentes[0]["id"])
    else:
        lay = perfiles.layout_actual()
        ok, msg = layout.anadir(lay, "ext:" + ext["nombre"])
        w = layout.buscar(lay, "ext:" + ext["nombre"])
        if ok and w:
            layout.redimensionar(lay, w["id"], ext["ancho"], ext["alto"])
            if ext.get("aparece_si"):
                w["opts"]["aparece"] = "si_hay"
        elif not ok:                                  # sin sitio en pantalla: queda en el cajon, no se pierde
            nuevo = layout.nuevo_widget("ext:" + ext["nombre"], id="ext-" + ext["nombre"].replace(" ", "-"), visible=False)
            lay["widgets"].append(nuevo)
            ok, msg = True, "no había sitio en esta página: la dejé en el cajón (Ctrl+J)"
    perfiles.marcar_sucio()
    return ok, (f"activé «{ext['nombre']}»" if ok else msg)


def _d_widget(ext):
    from . import perfiles
    for w in _widgets_de(ext):
        layout.ocultar(perfiles.layout_actual(), w["id"])
    perfiles.marcar_sucio()
    return True, f"desactivé «{ext['nombre']}»"


def _on_widget(ext):
    return any(w["visible"] or w.get("ventana") for w in _widgets_de(ext))


registrar_tipo_ext("widget", _v_widget, _a_widget, _d_widget, _on_widget,
                   lambda e: f"{len(e['bloques'])} bloque" + ("" if len(e["bloques"]) == 1 else "s"),
                   ayuda='{"tipo":"widget","titulo":"…","permisos":[…],"bloques":[…]}  (bloques: ver más abajo)')


# ------------------------------------------------------------------ ejemplos (paquetes de frases)
def _v_ejemplos(crudo, nombre, permisos, carpeta):
    if "ejemplos" not in permisos:
        return False, "un paquete de ejemplos debe declarar el permiso «ejemplos»"
    items = []
    for e in crudo.get("ejemplos") or []:
        if isinstance(e, dict) and str(e.get("frase", "")).strip() and e.get("intencion"):
            items.append({"frase": str(e["frase"]).strip()[:200], "intencion": str(e["intencion"]).strip()})
    archivo = crudo.get("archivo")
    if archivo:
        if "archivos_propios" not in permisos:
            return False, "lee un archivo pero no declara el permiso «archivos_propios»"
        if os.path.basename(str(archivo)) != str(archivo) or not str(archivo).endswith(".txt"):
            return False, "el archivo debe ser un .txt junto a la extensión (líneas «frase | intencion»)"
        try:
            with open(os.path.join(carpeta, archivo), "r", encoding="utf-8") as f:
                for l in f:
                    if "|" in l and not l.lstrip().startswith("#"):
                        fr, inten = (x.strip() for x in l.split("|", 1))
                        if fr and inten:
                            items.append({"frase": fr[:200], "intencion": inten})
        except OSError:
            return False, f"no encuentro {archivo}"
    if not items:
        return False, "el paquete no trae ejemplos"
    if len(items) > 500:
        return False, "máximo 500 ejemplos por paquete"
    try:
        from core.IA import catalogo
        malos = sorted({i["intencion"] for i in items if i["intencion"] not in catalogo.POR_ID})
        if malos:
            return False, "intenciones que no existen: " + ", ".join(malos[:5]) + " (en Arché: «intenciones» las lista)"
    except Exception:
        pass
    return True, {"nombre": nombre, "tipo": "ejemplos", "ejemplos": items, "permisos": list(permisos)}


_importando = set()


def _a_ejemplos(ext):
    n = ext["nombre"]
    if n in _importando:
        return True, "ya se está importando"
    _importando.add(n)
    import threading
    threading.Thread(target=_importar, args=(ext,), name="arche-ext-ejemplos", daemon=True).start()
    return True, f"importando {len(ext['ejemplos'])} ejemplos de «{n}» en segundo plano"


def _importar(ext):
    from . import en_vivo, redes
    n = ext["nombre"]
    try:
        m = redes._ia()
        orig = m.ap.UMBRAL_REENTRENO
        m.ap.UMBRAL_REENTRENO = float("inf")            # un solo reentreno al final (lo decide tu ajuste)
        agregadas, ya, afectadas = [], 0, set()
        try:
            existentes = {d.get("pregunta"): d.get("accion") for d in m.ap.cargar()}
            for e in ext["ejemplos"]:
                norm = m.ap._normalizar(e["frase"])
                if norm in existentes:
                    ya += 1                              # nunca pisa un ejemplo que ya estaba
                    continue
                m.ap.aprender(e["frase"], e["intencion"], "", fuente="ext:" + n)
                existentes[norm] = e["intencion"]
                agregadas.append([norm, e["intencion"]])
                afectadas.update(redes.redes_de_intencion(e["intencion"]))
        finally:
            m.ap.UMBRAL_REENTRENO = orig
        bloques_ext.estado_set(n, "importadas", agregadas)
        redes.invalidar()
        en_vivo.avisar(f"«{n}»: {len(agregadas)} ejemplos agregados" + (f", {ya} ya existían" if ya else "") +
                       (". Entrénalas en la vista de redes." if agregadas and ajustes.obtener("redes_entrenar") != "automatico" else "."), "exito")
        if agregadas and ajustes.obtener("redes_entrenar") == "automatico":
            redes.entrenar(sorted(afectadas))
    except Exception as e:
        en_vivo.avisar(f"No pude importar «{n}»: {type(e).__name__}: {e}", "error")
    finally:
        _importando.discard(n)


def _d_ejemplos(ext):
    from . import redes
    n = ext["nombre"]
    pares = bloques_ext.estado_get(n, "importadas", [])
    if pares:
        try:
            m = redes._ia()
            quitar = {(p, a) for p, a in pares}
            with m.ap._lock:
                datos = m.ap.cargar(estricto=True)
                nuevos = [d for d in datos if (d.get("pregunta"), d.get("accion")) not in quitar or not str(d.get("fuente", "")).startswith("ext:")]
                m.ap.guardar(nuevos)
            redes.invalidar()
        except Exception as e:
            return False, f"no pude quitar los ejemplos ({type(e).__name__})"
    bloques_ext.estado_borrar(n)
    return True, f"quité los {len(pares)} ejemplos de «{n}»"


def _on_ejemplos(ext):
    return ext["nombre"] in _importando or bool(bloques_ext.estado_get(ext["nombre"], "importadas"))


registrar_tipo_ext("ejemplos", _v_ejemplos, _a_ejemplos, _d_ejemplos, _on_ejemplos,
                   lambda e: f"{len(e['ejemplos'])} frases",
                   ayuda='{"tipo":"ejemplos","permisos":["ejemplos"],"ejemplos":[{"frase":"…","intencion":"hora"}]}  o  "archivo":"x.txt" (líneas «frase | intencion»)')


# ------------------------------------------------------------------ frases: apodos, apps, jerga, voz (frase -> orden) y respuestas (frase -> texto)
import random
import time
import unicodedata

_RX_VAR = re.compile(r"\{(\w+)\}")
_recien = {}            # ordenes que una extension acaba de mandar (para no entrar en bucle)


def _norm_frase(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s{}]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _v_frases(clave, valor_es_orden):
    def validar(crudo, nombre, permisos, carpeta):
        if valor_es_orden and "comandos" not in permisos:
            return False, "manda órdenes a Arché: debe declarar el permiso «comandos»"
        crudo_map = crudo.get(clave)
        if not isinstance(crudo_map, dict) or not crudo_map:
            return False, f"falta «{clave}»: {{\"frase\": ...}}"
        if len(crudo_map) > 300:
            return False, "máximo 300 frases por extensión"
        limpio = {}
        for frase, val in crudo_map.items():
            f = _norm_frase(frase)
            if len(f) < 2:
                continue
            vals = val if isinstance(val, list) else [val]
            vals = [str(x).strip()[:300] for x in vals if str(x).strip()]
            if not vals:
                continue
            if valor_es_orden:
                vals = vals[:1]
                vars_f, vars_o = set(_RX_VAR.findall(f)), set(_RX_VAR.findall(vals[0]))
                if vars_o - vars_f:
                    return False, f"«{frase}»: la orden usa {{{sorted(vars_o - vars_f)[0]}}} y la frase no"
                if _norm_frase(vals[0]) == f:
                    continue
            limpio[f] = vals
        if not limpio:
            return False, "no trae ninguna frase válida"
        return True, {"nombre": nombre, "tipo": "alias" if valor_es_orden else "respuestas", "frases": limpio,
                      "permisos": list(permisos), "orden": valor_es_orden}
    return validar


def _a_frases(ext):
    bloques_ext.estado_set(ext["nombre"], "activa", True)
    _recompilar()
    return True, f"activé «{ext['nombre']}» ({len(ext['frases'])} frases)"


def _d_frases(ext):
    bloques_ext.estado_set(ext["nombre"], "activa", False)
    _recompilar()
    return True, f"desactivé «{ext['nombre']}»"


def _on_frases(ext):
    return bool(bloques_ext.estado_get(ext["nombre"], "activa", False))


_reglas = []            # [(regex, valores, es_orden, nombre_ext)]


def _recompilar():
    global _reglas
    reglas = []
    for n, e in _cargadas.items():
        if e["tipo"] not in ("alias", "respuestas") or not _on_frases(e):
            continue
        for frase, vals in e["frases"].items():
            rx = re.escape(frase).replace(r"\{", "{").replace(r"\}", "}")
            rx = _RX_VAR.sub(lambda m: f"(?P<{m.group(1)}>.+)", rx)
            reglas.append((re.compile("^" + rx + "$"), vals, e["orden"], n))
    _reglas = reglas


def responder_frase(comando):
    """Si la frase es de una extension activa: ('orden', texto) o ('texto', respuesta). Si no, None."""
    if not _escaneado:
        escanear()
    if not _reglas:
        return None
    c = _norm_frase(comando)
    ahora = time.time()
    for k in [k for k, t in _recien.items() if ahora - t > 15]:
        _recien.pop(k, None)
    if c in _recien:
        return None
    for rx, vals, es_orden, _n in _reglas:
        m = rx.match(c)
        if not m:
            continue
        val = random.choice(vals)
        for k, x in m.groupdict().items():
            val = val.replace("{" + k + "}", x)
        if es_orden:
            _recien[_norm_frase(val)] = ahora
            return ("orden", val)
        return ("texto", val)
    return None


registrar_tipo_ext("alias", _v_frases("alias", True), _a_frases, _d_frases, _on_frases,
                   lambda e: f"{len(e['frases'])} frase" + ("" if len(e["frases"]) == 1 else "s"),
                   ayuda='{"tipo":"alias","permisos":["comandos"],"alias":{"abre mi editor":"abre visual studio code","llama a {x}":"manda mensaje a {x}"}}  (apodos, apps, jerga, comandos de voz propios)')
registrar_tipo_ext("respuestas", _v_frases("respuestas", False), _a_frases, _d_frases, _on_frases,
                   lambda e: f"{len(e['frases'])} frase" + ("" if len(e["frases"]) == 1 else "s"),
                   ayuda='{"tipo":"respuestas","respuestas":{"buenos dias":["Buenos días, jefe","¡Arriba!"]}}  (Arché contesta con tu texto; si pones una lista, elige una al azar)')


# ------------------------------------------------------------------ complementos (codigo propio, tuyo)
class _API:
    registrar_tipo_ext = staticmethod(registrar_tipo_ext)
    registrar_bloque = staticmethod(bloques_ext.registrar_bloque)
    registrar_fuente = staticmethod(bloques_ext.registrar_fuente)


_complementos_cargados = {}


def _cargar_complementos():
    """core/interfaz/complementos/*.py con una funcion registrar(api). Es TU codigo: las extensiones .json no pueden traerlo."""
    if not os.path.isdir(COMPLEMENTOS):
        return
    for f in sorted(os.listdir(COMPLEMENTOS)):
        if not f.endswith(".py") or f.startswith("_"):
            continue
        ruta = os.path.join(COMPLEMENTOS, f)
        try:
            mt = os.path.getmtime(ruta)
            if _complementos_cargados.get(f) == mt:
                continue
            spec = importlib.util.spec_from_file_location("arche_complemento_" + f[:-3], ruta)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.registrar(_API)
            _complementos_cargados[f] = mt
        except Exception as e:
            errores.append(f"complemento {f}: {type(e).__name__}: {e}")


# ------------------------------------------------------------------ escanear
def escanear():
    """Lee Database/extensiones y las registra. Una extension defectuosa se ignora, no rompe nada."""
    global _cargadas, _escaneado
    _escaneado = True
    errores.clear()
    _cargar_complementos()
    layout.olvidar_tipos_extra()
    _cargadas = {}
    try:
        os.makedirs(CARPETA, exist_ok=True)
        archivos = sorted(f for f in os.listdir(CARPETA) if f.endswith(".json") and not f.startswith("_"))
    except Exception:
        return []
    escribir_leeme()
    for f in archivos:
        try:
            with open(os.path.join(CARPETA, f), "r", encoding="utf-8") as fh:
                crudo = json.load(fh)
        except Exception as e:
            errores.append(f"{f}: no se pudo leer ({e})")
            continue
        ok, ext = validar(crudo)
        if not ok:
            errores.append(f"{f}: {ext}")
            continue
        _cargadas[ext["nombre"]] = ext
        if ext["tipo"] == "widget":
            layout.registrar_tipo("ext:" + ext["nombre"], (ext["titulo"], "Extensiones", ext["ancho"], ext["alto"], 3, 2, False,
                                                            "Extensión (" + ("con permisos: " + ", ".join(ext["permisos"]) if ext["permisos"] else "sin permisos") + ")."))
        elif ext["tipo"] == "tema" and ext["colores"]:
            nombre_tema = "ext " + ext["nombre"]
            if tema.resolver(nombre_tema) is None:
                tema._cargar_personales()[nombre_tema] = {"nombre": nombre_tema, "base": "arche", "colores": ext["colores"]}
                tema._guardar_personales()
    _recompilar()
    return list(_cargadas)


def listar():
    return [(n, e["tipo"], e["permisos"]) for n, e in _cargadas.items()]


def _buscar(nombre):
    return _cargadas.get(nombre) or next((e for n, e in _cargadas.items() if n.lower() == str(nombre).lower()), None)


def info(nombre):
    """{nombre, tipo, permisos, descripcion, resumen, activa} para la lista de la ventana."""
    e = _buscar(nombre)
    if e is None:
        return None
    t = TIPOS.get(e["tipo"], {})
    try:
        res = t["resumen"](e) if t.get("resumen") else ""
    except Exception:
        res = ""
    return {"nombre": e["nombre"], "tipo": e["tipo"], "permisos": e["permisos"], "descripcion": e.get("descripcion", ""),
            "resumen": res, "activa": activa(nombre)}


# ------------------------------------------------------------------ activar / desactivar
def activa(nombre):
    ext = _buscar(nombre)
    if ext is None:
        return False
    f = TIPOS[ext["tipo"]].get("activa")
    try:
        return bool(f(ext)) if f else False
    except Exception:
        return False


def activar(nombre):
    ext = _buscar(nombre)
    if ext is None:
        return False, f"no tengo una extensión «{nombre}»"
    f = TIPOS[ext["tipo"]].get("activar")
    return f(ext) if f else (False, "esa extensión no se puede activar")


def desactivar(nombre):
    ext = _buscar(nombre)
    if ext is None:
        return False, f"no tengo una extensión «{nombre}»"
    f = TIPOS[ext["tipo"]].get("desactivar")
    return f(ext) if f else (False, "esa extensión no se puede desactivar")


# ------------------------------------------------------------------ instalar / quitar
def _guardar_copia(crudo, ruta_origen_dir):
    ok, ext = validar(crudo, ruta_origen_dir)
    if not ok:
        return False, ext
    os.makedirs(CARPETA, exist_ok=True)
    destino = os.path.join(CARPETA, re.sub(r"[^\w\-]+", "_", ext["nombre"]) + ".json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(crudo, f, indent=2, ensure_ascii=False)
    # los .txt que usa viajan con ella; nunca pisan uno que ya tengas (son tus datos)
    usados = set()
    for b in ext.get("bloques", []):
        if b.get("archivo"):
            usados.add(b["archivo"])
    if crudo.get("archivo"):
        usados.add(crudo["archivo"])
    for a in usados:
        origen, dest = os.path.join(ruta_origen_dir, a), os.path.join(CARPETA, a)
        if os.path.isfile(origen) and not os.path.exists(dest):
            shutil.copyfile(origen, dest)
        elif not os.path.exists(dest) and a.endswith(".txt"):
            open(dest, "w", encoding="utf-8").close()
    escanear()
    pide = ("pide permiso para: " + ", ".join(ext["permisos"])) if ext["permisos"] else "no pide permisos"
    return True, f"«{ext['nombre']}» instalada ({pide})"


def instalar(ruta):
    """Copia una extension a Database/extensiones despues de validarla."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        return False, f"no pude leer el archivo ({e})"
    return _guardar_copia(crudo, os.path.dirname(os.path.abspath(ruta)))


def quitar(nombre):
    ext = _buscar(nombre)
    if ext is None:
        return False, f"no tengo una extensión «{nombre}»"
    try:
        desactivar(ext["nombre"])           # si estaba en uso, deja todo como estaba
    except Exception:
        pass
    for f in os.listdir(CARPETA):
        if f.endswith(".json") and not f.startswith("_"):
            try:
                with open(os.path.join(CARPETA, f), "r", encoding="utf-8") as fh:
                    if _limpio(json.load(fh).get("nombre")) == ext["nombre"]:
                        os.remove(os.path.join(CARPETA, f))
            except Exception:
                continue
    bloques_ext.estado_borrar(ext["nombre"])
    escanear()
    return True, f"quité «{ext['nombre']}» (tus archivos .txt se quedan)"


# ------------------------------------------------------------------ galeria
def galeria():
    """[(nombre, descripcion, tipo, instalada)] de core/interfaz/galeria (y de Database/galeria si existe)."""
    sal = []
    for base in (GALERIA, os.path.join(DATABASE, "galeria")):
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(base, f), "r", encoding="utf-8") as fh:
                    crudo = json.load(fh)
                ok, ext = validar(crudo, base)
            except Exception:
                continue
            if ok:
                sal.append((ext["nombre"], ext.get("descripcion", ""), ext["tipo"], ext["nombre"] in _cargadas, os.path.join(base, f)))
    return [(n, d, t, i) for n, d, t, i, _r in sal]


def _ruta_galeria(nombre):
    for base in (GALERIA, os.path.join(DATABASE, "galeria")):
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(base, f), "r", encoding="utf-8") as fh:
                        crudo = json.load(fh)
                except Exception:
                    continue
                if _limpio(crudo.get("nombre")).lower() == str(nombre).strip().lower():
                    return os.path.join(base, f)
    return None


def instalar_de_galeria(nombre):
    ruta = _ruta_galeria(nombre)
    if ruta is None:
        return False, f"no hay «{nombre}» en la galería (di «galería de extensiones»)"
    return instalar(ruta)


def instalar_todas_de_galeria():
    n, mal = 0, []
    for nombre, _d, _t, ya in galeria():
        if ya:
            continue
        ok, msg = instalar_de_galeria(nombre)
        n += 1 if ok else 0
        if not ok:
            mal.append(f"{nombre}: {msg}")
    return n, mal


# ------------------------------------------------------------------ crear una extension desde una plantilla
def crear_plantilla(tipo, nombre):
    """Deja un .json de ejemplo listo para editar en Database/extensiones (no pisa uno existente)."""
    tipo = {"panel": "widget", "tema": "tema", "widget": "widget", "ejemplos": "ejemplos", "paquete": "ejemplos", "apodos": "alias", "atajos": "alias"}.get(str(tipo).lower(), tipo)
    nombre = _limpio(nombre)
    if tipo not in TIPOS:
        return False, f"no conozco el tipo «{tipo}» (los que hay: {', '.join(TIPOS)})"
    if not nombre:
        return False, "dime cómo se llamará"
    base = {"arche_extension": 1, "nombre": nombre, "tipo": tipo, "descripcion": "Escribe aquí para qué sirve."}
    if tipo == "widget":
        base.update(titulo=nombre, ancho=6, alto=4, permisos=["comandos"],
                    bloques=[{"tipo": "texto", "texto": "Hola desde " + nombre},
                             {"tipo": "botones", "botones": [{"texto": "Hora", "orden": "qué hora es"}]}])
    elif tipo == "tema":
        base.update(colores={"fondo": "#101820", "morado_claro": "#59c3c3"}, ajustes={})
    elif tipo == "ejemplos":
        try:
            from core.IA import catalogo
            inten = sorted(catalogo.POR_ID)[0]
        except Exception:
            inten = "hora"
        base.update(permisos=["ejemplos"], ejemplos=[{"frase": "escribe aquí una frase", "intencion": inten}])
    elif tipo == "alias":
        base.update(permisos=["comandos"], alias={"abre mi editor": "abre visual studio code"})
    elif tipo == "respuestas":
        base.update(respuestas={"buenos dias": ["Buenos días", "¡Arriba, a darle!"]})
    else:
        base.update(permisos=[])
    destino = os.path.join(CARPETA, re.sub(r"[^\w\-]+", "_", nombre) + ".json")
    if os.path.exists(destino):
        return False, f"ya existe {os.path.basename(destino)}"
    os.makedirs(CARPETA, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2, ensure_ascii=False)
    escanear()
    return True, f"creé {os.path.basename(destino)} en Database/extensiones; edítalo y di «busca extensiones»"


# ------------------------------------------------------------------ LEEME.md (siempre al dia con lo registrado)
def escribir_leeme():
    t = ["# Extensiones de Arché", "",
         "Cada extensión es un archivo `.json` en esta carpeta. Son solo datos: no pueden ejecutar código.",
         "Se activan y desactivan en PERSONALIZA › Extensiones, o diciendo «activa la extensión X».", "",
         "Comandos: `galería de extensiones` · `instala la extensión X` · `crea una extensión widget llamada X` · "
         "`activa/desactiva/quita la extensión X` · `busca extensiones`", "",
         "## Permisos", "",
         "- `comandos`: los botones mandan órdenes a Arché",
         "- `archivos_propios`: lee `.txt` que están junto a la extensión (en esta carpeta)",
         "- `datos`: muestra datos de Arché (redes, frases que no entendió…)",
         "- `ejemplos`: agrega ejemplos de entrenamiento (y los quita al desactivarla)",
         "- Un tema nunca pide permisos.", "", "## Tipos", ""]
    for n, d in TIPOS.items():
        t.append(f"- **{n}** — `{d['ayuda']}`" if d["ayuda"] else f"- **{n}**")
    t += ["", "## Bloques de un widget", ""]
    for n, d in bloques_ext.BLOQUES.items():
        extra = f" _(permiso: {', '.join(d['permisos'])})_" if d["permisos"] else ""
        t.append(f"- **{n}**{extra} — `{d['ayuda']}`" if d["ayuda"] else f"- **{n}**{extra}")
    t += ["", "## Fuentes de datos (bloque `dato`)", ""]
    for n, d in bloques_ext.FUENTES.items():
        t.append(f"- **{n}** _(permisos: {', '.join(d['permisos'])})_ — {d['ayuda']}")
    t += ["", "## Ajustes que un tema puede traer", "", ", ".join(f"`{a}`" for a in AJUSTES_TEMA), "",
          "## Ampliar", "",
          "Un archivo `.py` en `core/interfaz/complementos/` con `def registrar(api)` puede agregar tipos, bloques y fuentes nuevos "
          "(`api.registrar_tipo_ext`, `api.registrar_bloque`, `api.registrar_fuente`). Es código tuyo: las extensiones `.json` no pueden traerlo.", ""]
    texto = "\n".join(t)
    ruta = os.path.join(CARPETA, "LEEME.md")
    try:
        if not os.path.exists(ruta) or open(ruta, "r", encoding="utf-8").read() != texto:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(texto)
    except OSError:
        pass


# ------------------------------------------------------------------ dibujo y acciones
def dibujar(v, wd, x, y, w, h, esc):
    """Dibuja un widget de extension dentro de su rectangulo, bloque por bloque."""
    ext = _cargadas.get(wd["tipo"][4:])
    if ext is None:
        v._tarjeta(x, y, w, h, "EXTENSIÓN", tema.TENUE)
        v._texto(x + 16 * esc, y + 50 * esc, "La extensión ya no está instalada.", 9, tema.TENUE)
        return
    col = wd.get("color") or tema.MORADO_CLARO
    v._tarjeta(x, y, w, h, (wd.get("titulo") or ext["titulo"]).upper(), col)
    px, yy, bw = x + 16 * esc, y + 44 * esc, w - 32 * esc
    for i, b in enumerate(ext["bloques"]):
        spec = bloques_ext.BLOQUES.get(b["tipo"])
        if spec is None:
            v._texto(px, yy + 8 * esc, f"(el bloque «{b['tipo']}» ya no está disponible)", 8, tema.TENUE)
            yy += 20 * esc
            continue
        try:
            alto = spec["alto"](v, b, ext, bw, esc)
            if yy + alto > y + h - 6 * esc:
                v._texto(px, min(yy + 6 * esc, y + h - 12 * esc), "… agranda el panel para ver el resto", 8, tema.TENUE)
                break
            spec["dibujar"](v, b, ext, i, px, yy, bw, esc)
            yy += alto + 8 * esc
        except Exception as e:
            v._texto(px, yy + 8 * esc, f"(error en el bloque «{b['tipo']}»: {type(e).__name__})", 8, tema.ALERTA)
            yy += 20 * esc


def accion(v, a):
    """('ext', ...) desde la ventana: instalar de la galeria, activar/desactivar o el boton de un bloque."""
    sub = a[1] if len(a) > 1 else ""
    if sub == "instalar":
        ok, msg = instalar_de_galeria(a[2])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "error")
        return True
    if sub == "instalar_todas":
        n, mal = instalar_todas_de_galeria()
        v.avisar(f"Instalé {n} extensión(es)" + (f"; falló: {'; '.join(mal[:2])}" if mal else "."), "error" if mal else "exito")
        return True
    if sub in ("activar", "desactivar"):
        ok, msg = (activar if sub == "activar" else desactivar)(a[2])
        v.avisar(msg[:1].upper() + msg[1:], "exito" if ok else "error")
        return True
    return bloques_ext.accion(v, a)
