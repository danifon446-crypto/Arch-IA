"""
extensiones.py
--------------
Ubicacion: Arche/core/interfaz/extensiones.py

Extensiones visuales: paquetes pequeños (un .json) que añaden TEMAS o WIDGETS
sin tocar el codigo de Arché. Son solo datos, nunca codigo: no pueden
ejecutar nada por su cuenta.

Permisos (cada extension declara los que necesita; si usa uno que no declaro,
se rechaza):
  (ninguno)          un tema o un widget que solo muestra texto
  "comandos"         el widget tiene botones que le mandan ordenes a Arché
  "archivos_propios" el widget lee un .txt que viaja junto a la extension

Un tema NUNCA puede pedir permisos. Ninguna extension puede leer tus archivos
personales ni ejecutar comandos del sistema.

Formato (Database/extensiones/<nombre>.json):
  {"arche_extension": 1, "nombre": "Mi panel", "tipo": "widget",
   "titulo": "Estado de la casa", "lineas": ["Luz sala: apagada"],
   "botones": [{"texto": "Luz", "orden": "enciende la luz"}], "permisos": ["comandos"]}
  {"arche_extension": 1, "nombre": "Atardecer", "tipo": "tema", "colores": {"fondo": "#1a0f1f"}}
"""

import json
import os
import re
import shutil

from . import ajustes, layout, tema

try:
    from core.rutas import DATABASE
except Exception:
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Database")

CARPETA = os.path.join(DATABASE, "extensiones")
PERMISOS = ("comandos", "archivos_propios")
_cargadas = {}          # nombre -> dict validado
errores = []            # por que se rechazo cada una


def _limpio(n):
    return re.sub(r"[^\w \-]", "", str(n)).strip()[:30]


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
    if tipo == "tema":
        if permisos:
            return False, "un tema no puede pedir permisos"
        cols = {r: ajustes.normalizar_hex(v) for r, v in (crudo.get("colores") or {}).items() if r in tema.ROLES}
        cols = {r: v for r, v in cols.items() if v}
        if not cols:
            return False, "el tema no trae ningún color válido"
        return True, {"nombre": nombre, "tipo": "tema", "colores": cols, "permisos": []}
    if tipo == "widget":
        botones = []
        for b in crudo.get("botones") or []:
            if isinstance(b, dict) and b.get("orden") and b.get("texto"):
                botones.append({"texto": str(b["texto"])[:20], "orden": str(b["orden"])[:120]})
        if botones and "comandos" not in permisos:
            return False, "tiene botones pero no declara el permiso «comandos»"
        archivo = crudo.get("archivo")
        if archivo:
            if "archivos_propios" not in permisos:
                return False, "lee un archivo pero no declara el permiso «archivos_propios»"
            if os.path.basename(str(archivo)) != str(archivo) or not str(archivo).endswith(".txt"):
                return False, "el archivo debe ser un .txt junto a la extensión"
        lineas = [str(x)[:120] for x in (crudo.get("lineas") or [])][:30]
        return True, {"nombre": nombre, "tipo": "widget", "titulo": str(crudo.get("titulo") or nombre)[:30],
                      "lineas": lineas, "botones": botones[:8], "archivo": archivo or "",
                      "permisos": list(permisos), "carpeta": carpeta or CARPETA,
                      "ancho": 6, "alto": 4}
    return False, "tipo desconocido (usa «tema» o «widget»)"


def escanear():
    """Lee Database/extensiones y las registra. Una extension defectuosa se ignora, no rompe nada."""
    global _cargadas
    errores.clear()
    layout.olvidar_tipos_extra()
    _cargadas = {}
    try:
        os.makedirs(CARPETA, exist_ok=True)
        archivos = sorted(f for f in os.listdir(CARPETA) if f.endswith(".json"))
    except Exception:
        return []
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
                                                            "Extensión visual (" + ("con permisos: " + ", ".join(ext["permisos"]) if ext["permisos"] else "sin permisos") + ")."))
        elif ext["tipo"] == "tema":
            nombre_tema = "ext " + ext["nombre"]
            if tema.resolver(nombre_tema) is None:
                tema._cargar_personales()[nombre_tema] = {"nombre": nombre_tema, "base": "arche", "colores": ext["colores"]}
                tema._guardar_personales()
    return list(_cargadas)


def listar():
    return [(n, e["tipo"], e["permisos"]) for n, e in _cargadas.items()]


def instalar(ruta):
    """Copia una extension a Database/extensiones despues de validarla."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        return False, f"no pude leer el archivo ({e})"
    ok, ext = validar(crudo)
    if not ok:
        return False, ext
    os.makedirs(CARPETA, exist_ok=True)
    destino = os.path.join(CARPETA, re.sub(r"[^\w\-]+", "_", ext["nombre"]) + ".json")
    shutil.copyfile(ruta, destino)
    if ext.get("archivo"):
        origen = os.path.join(os.path.dirname(os.path.abspath(ruta)), ext["archivo"])
        if os.path.isfile(origen):
            shutil.copyfile(origen, os.path.join(CARPETA, ext["archivo"]))
    escanear()
    pide = ("pide permiso para: " + ", ".join(ext["permisos"])) if ext["permisos"] else "no pide permisos"
    return True, f"«{ext['nombre']}» instalada ({pide})"


def quitar(nombre):
    ext = _cargadas.get(nombre) or next((e for n, e in _cargadas.items() if n.lower() == str(nombre).lower()), None)
    if ext is None:
        return False, f"no tengo una extensión «{nombre}»"
    try:
        desactivar(ext["nombre"])           # si era el tema en uso, vuelve al anterior
    except Exception:
        pass
    for f in os.listdir(CARPETA):
        if f.endswith(".json"):
            try:
                with open(os.path.join(CARPETA, f), "r", encoding="utf-8") as fh:
                    if _limpio(json.load(fh).get("nombre")) == ext["nombre"]:
                        os.remove(os.path.join(CARPETA, f))
            except Exception:
                continue
    escanear()
    return True, f"quité «{ext['nombre']}»"


def _buscar(nombre):
    return _cargadas.get(nombre) or next((e for n, e in _cargadas.items() if n.lower() == str(nombre).lower()), None)


def _widgets_de(ext):
    from . import perfiles
    return [w for w in perfiles.layout_actual()["widgets"] if w["tipo"] == "ext:" + ext["nombre"]]


def activa(nombre):
    """Un tema esta activo si es el tema en uso; un widget, si esta visible en la distribucion."""
    ext = _buscar(nombre)
    if ext is None:
        return False
    if ext["tipo"] == "tema":
        return ajustes.obtener("tema") == "ext " + ext["nombre"]
    return any(w["visible"] or w.get("ventana") for w in _widgets_de(ext))


def activar(nombre):
    from . import perfiles
    ext = _buscar(nombre)
    if ext is None:
        return False, f"no tengo una extensión «{nombre}»"
    if ext["tipo"] == "tema":
        actual = ajustes.obtener("tema")
        if actual != "ext " + ext["nombre"]:
            ajustes.fijar("ext_tema_previo", actual)
        ajustes.fijar("tema", "ext " + ext["nombre"])
        return True, f"activé el tema «{ext['nombre']}»"
    existentes = _widgets_de(ext)
    if existentes:
        ok, msg = layout.mostrar(perfiles.layout_actual(), existentes[0]["id"])
    else:
        ok, msg = layout.anadir(perfiles.layout_actual(), "ext:" + ext["nombre"])
    perfiles.marcar_sucio()
    return ok, (f"activé «{ext['nombre']}»" if ok else msg)


def desactivar(nombre):
    from . import perfiles
    ext = _buscar(nombre)
    if ext is None:
        return False, f"no tengo una extensión «{nombre}»"
    if ext["tipo"] == "tema":
        if ajustes.obtener("tema") == "ext " + ext["nombre"]:
            previo = ajustes.obtener("ext_tema_previo") or "arche"
            if previo == "ext " + ext["nombre"] or tema.resolver(previo) is None:
                previo = "arche"
            ajustes.fijar("tema", previo)
        return True, f"desactivé el tema «{ext['nombre']}»"
    for w in _widgets_de(ext):
        layout.ocultar(perfiles.layout_actual(), w["id"])
    perfiles.marcar_sucio()
    return True, f"desactivé «{ext['nombre']}»"


def dibujar(v, wd, x, y, w, h, esc):
    """Dibuja un widget de extension dentro de su rectangulo."""
    ext = _cargadas.get(wd["tipo"][4:])
    if ext is None:
        v._tarjeta(x, y, w, h, "EXTENSIÓN", tema.TENUE)
        v._texto(x + 16 * esc, y + 50 * esc, "La extensión ya no está instalada.", 9, tema.TENUE)
        return
    col = wd.get("color") or tema.MORADO_CLARO
    v._tarjeta(x, y, w, h, (wd.get("titulo") or ext["titulo"]).upper(), col)
    px, yy, bw = x + 16 * esc, y + 44 * esc, w - 32 * esc
    lineas = list(ext["lineas"])
    if ext["archivo"] and "archivos_propios" in ext["permisos"]:
        try:
            with open(os.path.join(ext["carpeta"], ext["archivo"]), "r", encoding="utf-8") as f:
                lineas += [l.strip()[:120] for l in f.read().splitlines()[:30] if l.strip()]
        except Exception:
            lineas.append("(no pude leer el archivo)")
    maxc = int(bw / (9 * esc * 0.6))
    for l in lineas:
        if yy + 18 * esc > y + h - (30 * esc if ext["botones"] else 6 * esc):
            break
        v._texto(px, yy, l[:maxc], 9, tema.TEXTO)
        yy += 18 * esc
    if ext["botones"] and "comandos" in ext["permisos"]:
        cx, fy = px, y + h - 32 * esc
        for b in ext["botones"]:
            ancho = (len(b["texto"]) * 6.6 + 20) * esc
            if cx + ancho > px + bw:
                break
            v._chip(cx, fy, b["texto"], ("orden", b["orden"]), False, col, ancho)
            cx += ancho + 6 * esc
