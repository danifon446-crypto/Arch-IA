"""
pc_avanzado.py
--------------
Ubicacion: Arche/core/pc_avanzado.py

Control "de asistente" del PC: cosas utiles que se piden con intenciones,
no con clics.

  dame un diagnostico de mi pc            -> CPU, memoria, disco, bateria y que gasta mas
  que consume mas cpu / memoria
  libera memoria                          -> te muestra lo mas pesado y cierras lo que elijas
  espacio de mis discos
  que ocupa mas espacio                   -> archivos mas grandes
  busca archivos duplicados  /  mueve los duplicados a la papelera
  revisa mis descargas  /  limpia las descargas viejas
  que puedo limpiar  /  limpia todo | tmp | pycache
  busca mis archivos sobre la tesis       -> por nombre Y por contenido
  abre el 2                               -> abre un resultado de la lista anterior
  restaura la papelera de arche

Seguridad: NADA se borra directo. Lo que "limpias" de duplicados y descargas
viejas se MUEVE a la papelera de Arché (Database/papelera_arche/) y se puede
devolver con "restaura la papelera de arche". Antes de mover o borrar siempre
muestra cuanto es y pide confirmacion. Cerrar programas usa el mismo cierre
con confirmacion de acciones_pc ("cierra chrome").

Reutiliza lo que Arché ya tenia: sistema.py (estado, limpieza, busqueda por
contenido), archivos.py (indice de archivos) y acciones_pc.py (cerrar).
Lo que toca el sistema esta en funciones chicas con "_" para probarlo sin Windows.
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timedelta

try:
    import psutil
except ImportError:
    psutil = None

from core import archivos, sistema
from core.rutas import DATABASE

PAPELERA = os.path.join(DATABASE, "papelera_arche")
MANIFIESTO = os.path.join(PAPELERA, "manifiesto.json")
DIAS_DESCARGAS_VIEJAS = 60
MIN_PESO_DUPLICADO = 10 * 1024          # ignora archivos de menos de 10 KB
PRESUPUESTO_DUPLICADOS_S = 25
PRESUPUESTO_CONTENIDO_S = 10
VIGENCIA_RESULTADOS_S = 900             # "abre el 2" vale 15 minutos
CARPETAS_IGNORADAS = ("__pycache__", ".git", "node_modules", ".venv", "site-packages")

_EXT_TEXTO = {".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".cfg", ".yaml", ".yml", ".js",
              ".html", ".xml", ".bat", ".ps1", ".rtf", ".tex"}

_ultimos = {"cuando": 0.0, "items": []}      # para "abre el N"
_pendiente = {"duplicados": None, "descargas": None, "limpieza": None}


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------

def _sin_tildes(texto):
    t = str(texto).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


def _limpio(comando):
    return " ".join(re.sub(r"[¿?¡!,;:]", " ", _sin_tildes(comando)).split())


def _msg(texto):
    print(f"Arché: {texto}")


def _peso(n):
    return sistema._bytes_legibles(n)


def _confirmar(pregunta):
    from core import acciones_pc
    return acciones_pc._confirmar(pregunta)


def _indice():
    return archivos.cargar_indice()


def _abrir(ruta):
    """Abre un archivo/carpeta con el programa por defecto. Unico punto del 'abrir'."""
    if hasattr(os, "startfile"):
        os.startfile(ruta)
    else:
        subprocess.Popen(["xdg-open", ruta])


def _mostrar_en_carpeta(ruta):
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(ruta)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(ruta)])


def _recordar_lista(items):
    _ultimos["cuando"] = time.time()
    _ultimos["items"] = list(items)


def _ignorada(ruta):
    partes = set(re.split(r"[\\/]", ruta))
    return any(c in partes for c in CARPETAS_IGNORADAS)


def _carpeta_corta(ruta):
    d = os.path.dirname(ruta)
    home = os.path.expanduser("~")
    return ("~" + d[len(home):]) if d.startswith(home) else d


# ------------------------------------------------------------------
# Procesos / diagnostico
# ------------------------------------------------------------------

_SISTEMA_IGNORADO = {"system idle process", "system", "memory compression", "registry", "idle"}


def _procesos(con_cpu=False):
    """[{nombre, pids, ram, cpu}] AGRUPADO por programa (chrome = todos sus procesos)."""
    if psutil is None:
        return []
    from core import acciones_pc
    propios = acciones_pc._pids_propios()
    protegidos = acciones_pc.PROCESOS_PROTEGIDOS
    lista = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            if p.pid in propios:
                continue
            if con_cpu:
                p.cpu_percent(None)
            lista.append(p)
        except Exception:
            continue
    if con_cpu:
        time.sleep(0.6)
    nucleos = psutil.cpu_count() or 1
    grupos = {}
    for p in lista:
        try:
            nombre = (p.info.get("name") or "").lower()
            base = os.path.splitext(nombre)[0]
            if not nombre or nombre in _SISTEMA_IGNORADO or base in protegidos:
                continue
            mem = p.info.get("memory_info")
            g = grupos.setdefault(base, {"nombre": base, "pids": [], "ram": 0, "cpu": 0.0})
            g["pids"].append(p.pid)
            g["ram"] += mem.rss if mem else 0
            if con_cpu:
                g["cpu"] += p.cpu_percent(None) / nucleos
        except Exception:
            continue
    return list(grupos.values())


def _top(campo, n=5, con_cpu=False):
    return sorted(_procesos(con_cpu), key=lambda g: g[campo], reverse=True)[:n]


def _tiempo_encendido():
    if psutil is None:
        return ""
    try:
        seg = int(time.time() - psutil.boot_time())
    except Exception:
        return ""
    d, resto = divmod(seg, 86400)
    h, m = divmod(resto // 60, 60)
    if d:
        return f"{d} día(s) y {h} h"
    return f"{h} h {m} min" if h else f"{m} min"


def _bateria_texto():
    if psutil is None or not hasattr(psutil, "sensors_battery"):
        return ""
    try:
        b = psutil.sensors_battery()
    except Exception:
        return ""
    if b is None:
        return ""
    return f"Batería al {round(b.percent)}%" + (" (cargando)" if b.power_plugged else " (sin cargador)")


def diagnostico():
    """Texto de diagnostico + lista de sugerencias."""
    e = sistema.estado_sistema()
    top = _top("ram", 3)
    sugerencias = []
    if e["ram_pct"] >= 80 and top:
        sugerencias.append(f"la memoria está alta: puedes cerrar {top[0]['nombre']} "
                           f"({_peso(top[0]['ram'])}); di 'libera memoria'")
    if e["disco_pct"] >= 90:
        sugerencias.append("el disco está casi lleno: di 'que ocupa mas espacio' o 'que puedo limpiar'")
    if e["cpu_pct"] >= 85:
        sugerencias.append("el procesador está al límite: di 'que consume mas cpu'")
    estado = "con problemas" if sugerencias else "bien"
    partes = [
        f"Tu PC está {estado}. Procesador al {e['cpu_pct']:.0f}%, memoria al {e['ram_pct']:.0f}% "
        f"({_peso(e['ram_usada'])} de {_peso(e['ram_total'])}), disco al {e['disco_pct']:.0f}% "
        f"({_peso(e['disco_libre'])} libres)."
    ]
    bateria = _bateria_texto()
    if bateria:
        partes.append(bateria + ".")
    enc = _tiempo_encendido()
    if enc:
        partes.append(f"Lleva encendido {enc}.")
    if top:
        partes.append("Lo que más memoria gasta: " + ", ".join(f"{g['nombre']} ({_peso(g['ram'])})" for g in top) + ".")
    return " ".join(partes), sugerencias


def decir_diagnostico():
    if psutil is None:
        _msg("Necesito la librería psutil para eso (pip install psutil).")
        return
    texto, sugerencias = diagnostico()
    _msg(texto)
    for s in sugerencias:
        print(f"  • Ojo: {s}.")


def decir_top(campo):
    if psutil is None:
        _msg("Necesito la librería psutil para eso (pip install psutil).")
        return
    top = _top(campo, 5, con_cpu=(campo == "cpu"))
    if not top:
        _msg("No pude leer los programas ahora mismo.")
        return
    if campo == "cpu":
        _msg("Esto es lo que más procesador está usando ahora:")
        for g in top:
            print(f"  • {g['nombre']}: {g['cpu']:.1f}%")
    else:
        _msg("Esto es lo que más memoria está usando ahora:")
        for g in top:
            print(f"  • {g['nombre']}: {_peso(g['ram'])} ({len(g['pids'])} proceso/s)")


def liberar_memoria():
    """Muestra lo mas pesado y deja cerrar lo que elijas (con el cierre seguro de acciones_pc)."""
    if psutil is None:
        _msg("Necesito la librería psutil para eso (pip install psutil).")
        return
    top = _top("ram", 5)
    if not top:
        _msg("No encontré programas pesados que puedas cerrar.")
        return
    _msg("Esto es lo que más memoria gasta (nada de esto es del sistema). ¿Cuál cierro?")
    for i, g in enumerate(top, start=1):
        print(f"  {i}. {g['nombre']}: {_peso(g['ram'])}")
    from core import control_pc
    respuesta = _sin_tildes(control_pc._preguntar("Número, nombre, o 'ninguno'\nTú: ")).strip()
    if respuesta in ("", "ninguno", "nada", "no", "cancela", "cancelar"):
        _msg("Está bien, no cierro nada.")
        return
    elegido = None
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(top):
        elegido = top[int(respuesta) - 1]["nombre"]
    else:
        elegido = next((g["nombre"] for g in top if respuesta in g["nombre"]), None)
    if elegido is None:
        _msg("No entendí cuál. Intenta otra vez con 'libera memoria'.")
        return
    from core import acciones_pc
    acciones_pc._a_cerrar({"x": elegido})


# ------------------------------------------------------------------
# Discos y archivos grandes
# ------------------------------------------------------------------

def decir_discos():
    if psutil is None:
        _msg("Necesito la librería psutil para eso (pip install psutil).")
        return
    lineas = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in (part.opts or "") or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue
        lineas.append(f"  • {part.mountpoint}  {_peso(u.free)} libres de {_peso(u.total)} ({u.percent:.0f}% usado)")
    if not lineas:
        _msg("No pude leer los discos.")
        return
    _msg("Tus discos:")
    for l in lineas:
        print(l)


def archivos_grandes(n=10):
    """Los n archivos mas pesados del indice (que aun existan)."""
    grandes = []
    for e in sorted((e for e in _indice() if e.get("tipo") == "archivo"), key=lambda e: e.get("peso", 0), reverse=True):
        if _ignorada(e["ruta"]) or not os.path.exists(e["ruta"]):
            continue
        grandes.append({"ruta": e["ruta"], "peso": e["peso"]})
        if len(grandes) >= n:
            break
    return grandes


def decir_archivos_grandes():
    if not _indice():
        _msg("Todavía no indexé tus archivos. Dime 'actualizar archivos' primero y vuelve a preguntarme.")
        return
    grandes = archivos_grandes()
    if not grandes:
        _msg("No encontré archivos grandes.")
        return
    _msg(f"Esto es lo que más espacio ocupa en tus carpetas (el más grande pesa {_peso(grandes[0]['peso'])}):")
    for i, g in enumerate(grandes, start=1):
        print(f"  {i}. {_peso(g['peso']):>10}  {os.path.basename(g['ruta'])}   ({_carpeta_corta(g['ruta'])})")
    print("  (Di 'abre el 3' para abrir uno, o 'abre la carpeta del 3'.)")
    _recordar_lista(grandes)


# ------------------------------------------------------------------
# Papelera de Arché (recuperable)
# ------------------------------------------------------------------

def _leer_manifiesto():
    try:
        with open(MANIFIESTO, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _guardar_manifiesto(m):
    os.makedirs(PAPELERA, exist_ok=True)
    with open(MANIFIESTO, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)


def mover_a_papelera(rutas):
    """Mueve a Database/papelera_arche/<fecha>/ y anota de donde salio. (movidos, fallos, bytes)."""
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta = os.path.join(PAPELERA, sello)
    os.makedirs(carpeta, exist_ok=True)
    manifiesto = _leer_manifiesto()
    movidos = fallos = total = 0
    for ruta in rutas:
        try:
            peso = os.path.getsize(ruta)
            base = os.path.basename(ruta)
            destino = os.path.join(carpeta, base)
            k = 1
            while os.path.exists(destino):
                nombre, ext = os.path.splitext(base)
                destino = os.path.join(carpeta, f"{nombre} ({k}){ext}")
                k += 1
            shutil.move(ruta, destino)
            manifiesto.append({"origen": ruta, "destino": destino, "peso": peso, "fecha": sello})
            movidos += 1
            total += peso
        except OSError:
            fallos += 1
    _guardar_manifiesto(manifiesto)
    return movidos, fallos, total


def restaurar_papelera():
    """Devuelve a su lugar lo que hay en la papelera (si el lugar sigue libre)."""
    manifiesto = _leer_manifiesto()
    if not manifiesto:
        _msg("La papelera de Arché está vacía.")
        return
    quedan, devueltos, omitidos = [], 0, 0
    for item in manifiesto:
        if not os.path.exists(item["destino"]):
            continue
        if os.path.exists(item["origen"]):
            omitidos += 1
            quedan.append(item)
            continue
        try:
            os.makedirs(os.path.dirname(item["origen"]), exist_ok=True)
            shutil.move(item["destino"], item["origen"])
            devueltos += 1
        except OSError:
            omitidos += 1
            quedan.append(item)
    _guardar_manifiesto(quedan)
    texto = f"Devolví {devueltos} archivo(s) a su lugar."
    if omitidos:
        texto += f" {omitidos} no pude (ya hay algo en ese lugar o falló)."
    _msg(texto)


def vaciar_papelera():
    manifiesto = [m for m in _leer_manifiesto() if os.path.exists(m["destino"])]
    if not manifiesto:
        _msg("La papelera de Arché ya está vacía.")
        return
    total = sum(m.get("peso", 0) for m in manifiesto)
    if not _confirmar(f"Esto borra para siempre {len(manifiesto)} archivo(s) ({_peso(total)}) de la papelera de Arché. ¿Seguro?"):
        _msg("Cancelado, no borré nada.")
        return
    shutil.rmtree(PAPELERA, ignore_errors=True)
    _msg(f"Listo, vacié la papelera y liberé {_peso(total)}.")


# ------------------------------------------------------------------
# Duplicados
# ------------------------------------------------------------------

def _huella(ruta, peso):
    """Hash barato y fiable: tamaño + inicio + final (archivos grandes) o todo (chicos)."""
    h = hashlib.md5()
    h.update(str(peso).encode())
    with open(ruta, "rb") as f:
        if peso <= 8 * 1024 * 1024:
            for bloque in iter(lambda: f.read(1024 * 1024), b""):
                h.update(bloque)
        else:
            h.update(f.read(1024 * 1024))
            f.seek(max(peso - 1024 * 1024, 0))
            h.update(f.read(1024 * 1024))
    return h.hexdigest()


def buscar_duplicados(presupuesto=PRESUPUESTO_DUPLICADOS_S):
    """[[ruta, ruta, ...], ...] grupos de archivos identicos (mismo contenido), mas pesados primero."""
    por_peso = {}
    for e in _indice():
        if e.get("tipo") != "archivo" or e.get("peso", 0) < MIN_PESO_DUPLICADO or _ignorada(e["ruta"]):
            continue
        por_peso.setdefault(e["peso"], []).append(e["ruta"])
    inicio = time.time()
    grupos = []
    for peso, rutas in sorted(por_peso.items(), reverse=True):
        if len(rutas) < 2:
            continue
        if time.time() - inicio > presupuesto:
            break
        por_huella = {}
        for r in rutas:
            try:
                if not os.path.exists(r):
                    continue
                por_huella.setdefault(_huella(r, peso), []).append(r)
            except OSError:
                continue
        for lista in por_huella.values():
            # el mismo archivo visto por dos caminos (OneDrive) no es un duplicado
            unicas = []
            for r in lista:
                if not any(_es_el_mismo(r, u) for u in unicas):
                    unicas.append(r)
            if len(unicas) >= 2:
                grupos.append(unicas)
    grupos.sort(key=lambda g: os.path.getsize(g[0]) * (len(g) - 1) if os.path.exists(g[0]) else 0, reverse=True)
    return grupos


def _es_el_mismo(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _cual_conservar(grupo):
    """El mas viejo (el original); si empatan, el de ruta mas corta."""
    return min(grupo, key=lambda r: (os.path.getmtime(r) if os.path.exists(r) else float("inf"), len(r)))


def _sobrantes(grupos):
    sobran = []
    for g in grupos:
        keep = _cual_conservar(g)
        sobran.extend(r for r in g if r != keep)
    return sobran


def decir_duplicados():
    if not _indice():
        _msg("Todavía no indexé tus archivos. Dime 'actualizar archivos' primero.")
        return
    _msg("Buscando duplicados (puede tardar un poco)...")
    grupos = buscar_duplicados()
    _pendiente["duplicados"] = grupos
    if not grupos:
        _msg("No encontré archivos duplicados en tus carpetas.")
        return
    sobran = _sobrantes(grupos)
    desperdicio = sum(os.path.getsize(r) for r in sobran if os.path.exists(r))
    _msg(f"Encontré {len(grupos)} grupo(s) de archivos repetidos; sobran {len(sobran)} copias que ocupan {_peso(desperdicio)}.")
    for g in grupos[:6]:
        keep = _cual_conservar(g)
        print(f"  • {os.path.basename(keep)} ({_peso(os.path.getsize(keep))}) x{len(g)}")
        for r in g:
            print(f"      {'(me quedo con)' if r == keep else '(copia)       '} {_carpeta_corta(r)}")
    if len(grupos) > 6:
        print(f"  ... y {len(grupos) - 6} grupo(s) más.")
    print("  Di 'mueve los duplicados a la papelera' y dejo el más antiguo de cada grupo (se pueden recuperar).")


def mover_duplicados():
    grupos = _pendiente["duplicados"]
    if grupos is None:
        _msg("Primero dime 'busca archivos duplicados' para que te los muestre.")
        return
    sobran = [r for r in _sobrantes(grupos) if os.path.exists(r)]
    if not sobran:
        _msg("No hay copias que mover (o ya las moviste).")
        return
    total = sum(os.path.getsize(r) for r in sobran)
    if not _confirmar(f"Voy a mover {len(sobran)} copia(s) repetida(s) ({_peso(total)}) a la papelera de Arché, "
                      "dejando una de cada grupo. Se pueden devolver. ¿Sigo?"):
        _msg("Cancelado, no moví nada.")
        return
    movidos, fallos, peso = mover_a_papelera(sobran)
    _pendiente["duplicados"] = None
    _msg(f"Listo: moví {movidos} archivo(s) y liberé {_peso(peso)}."
         + (f" {fallos} no pude moverlos (en uso?)." if fallos else "")
         + " Si te arrepientes: 'restaura la papelera de arche'.")


# ------------------------------------------------------------------
# Descargas viejas
# ------------------------------------------------------------------

def _carpeta_descargas():
    for c in archivos.CARPETAS:
        if os.path.basename(c).lower() in ("downloads", "descargas"):
            return c
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else None


def descargas_viejas(dias=DIAS_DESCARGAS_VIEJAS):
    """[{ruta, peso, dias}] de archivos sueltos en Descargas sin tocar hace `dias`."""
    carpeta = _carpeta_descargas()
    if not carpeta:
        return []
    limite = time.time() - dias * 86400
    viejas = []
    try:
        nombres = os.listdir(carpeta)
    except OSError:
        return []
    for nombre in nombres:
        ruta = os.path.join(carpeta, nombre)
        try:
            if not os.path.isfile(ruta):
                continue
            mod = max(os.path.getmtime(ruta), os.path.getatime(ruta))
            if mod < limite:
                viejas.append({"ruta": ruta, "peso": os.path.getsize(ruta),
                               "dias": int((time.time() - mod) // 86400)})
        except OSError:
            continue
    return sorted(viejas, key=lambda v: v["peso"], reverse=True)


def decir_descargas():
    viejas = descargas_viejas()
    _pendiente["descargas"] = viejas
    if not viejas:
        _msg(f"Tus descargas están al día: nada sin tocar hace más de {DIAS_DESCARGAS_VIEJAS} días.")
        return
    total = sum(v["peso"] for v in viejas)
    _msg(f"Tienes {len(viejas)} archivo(s) en Descargas sin tocar hace más de {DIAS_DESCARGAS_VIEJAS} días, "
         f"que ocupan {_peso(total)}.")
    for v in viejas[:6]:
        print(f"  • {_peso(v['peso']):>10}  {os.path.basename(v['ruta'])}  ({v['dias']} días)")
    if len(viejas) > 6:
        print(f"  ... y {len(viejas) - 6} más.")
    print("  Di 'limpia las descargas viejas' y las muevo a la papelera de Arché (se pueden recuperar).")


def limpiar_descargas():
    viejas = _pendiente["descargas"]
    if viejas is None:
        viejas = descargas_viejas()
    viejas = [v for v in viejas if os.path.exists(v["ruta"])]
    if not viejas:
        _msg("No hay descargas viejas que mover.")
        return
    total = sum(v["peso"] for v in viejas)
    if not _confirmar(f"Voy a mover {len(viejas)} archivo(s) de Descargas ({_peso(total)}) a la papelera de Arché. "
                      "Se pueden devolver. ¿Sigo?"):
        _msg("Cancelado, no moví nada.")
        return
    movidos, fallos, peso = mover_a_papelera([v["ruta"] for v in viejas])
    _pendiente["descargas"] = None
    _msg(f"Listo: moví {movidos} archivo(s) y liberé {_peso(peso)}."
         + (f" {fallos} no pude moverlos." if fallos else "")
         + " Si te arrepientes: 'restaura la papelera de arche'.")


# ------------------------------------------------------------------
# Limpieza profunda (core/sistema.py, que ya existia pero ningun comando llamaba)
# ------------------------------------------------------------------

def decir_analisis_limpieza():
    _msg("Revisando qué puedo limpiar (no borro nada todavía)...")
    reporte = sistema.analizar_limpieza()
    _pendiente["limpieza"] = reporte
    print(sistema.hablar_analisis_limpieza(reporte))


def limpiar_pc(texto):
    categorias = sistema.interpretar_categorias_limpieza(texto)
    if not categorias:
        decir_analisis_limpieza()
        return
    reporte = _pendiente["limpieza"]
    if reporte is None:
        _msg("Primero reviso qué hay...")
        reporte = sistema.analizar_limpieza()
        _pendiente["limpieza"] = reporte
    nombres = [sistema._NOMBRES_CATEGORIA[c] for c in categorias]
    cantidad = sum(reporte.get(c, {}).get("cantidad", 0) for c in categorias)
    peso = sum(reporte.get(c, {}).get("peso", 0) for c in categorias)
    if cantidad == 0:
        _msg("No encontré nada de eso para limpiar.")
        return
    if not _confirmar(f"Voy a BORRAR {cantidad} elemento(s) ({_peso(peso)}): {', '.join(nombres)}. "
                      "Esto no va a la papelera. ¿Sigo?"):
        _msg("Cancelado, no borré nada.")
        return
    resultado = sistema.ejecutar_limpieza(reporte, categorias)
    _pendiente["limpieza"] = None
    print(sistema.hablar_resultado_limpieza(resultado))


# ------------------------------------------------------------------
# Archivos por tema (nombre + contenido)
# ------------------------------------------------------------------

_STOP = {"el", "la", "los", "las", "de", "del", "sobre", "un", "una", "unos", "unas", "y", "en", "con", "para",
         "que", "mi", "mis", "tema", "acerca", "relacionados", "relacionado", "hablen", "habla", "al", "a", "o"}


def _palabras_clave(tema):
    palabras = [p for p in re.split(r"\W+", _sin_tildes(tema)) if len(p) >= 3 and p not in _STOP]
    return list(dict.fromkeys(palabras))


def _texto_de(ruta, ext, peso):
    """Texto legible de un archivo (None si no se puede). Soporta texto plano y .docx."""
    try:
        if ext in _EXT_TEXTO and peso <= 2 * 1024 * 1024:
            with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
                return _sin_tildes(f.read(200_000))
        if ext == ".docx" and peso <= 15 * 1024 * 1024:
            with zipfile.ZipFile(ruta) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
            return _sin_tildes(re.sub(r"<[^>]+>", " ", xml)[:300_000])
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    return None


def buscar_archivos_tema(tema, maximo=10, presupuesto=PRESUPUESTO_CONTENIDO_S):
    """[{ruta, puntaje, motivo}] por nombre Y por contenido, mejores primero."""
    claves = _palabras_clave(tema)
    if not claves:
        return []
    entradas = [e for e in _indice() if e.get("tipo") == "archivo" and not _ignorada(e["ruta"])]
    resultados = []
    inicio = time.time()
    # primero lo reciente: es lo que mas probablemente buscas
    entradas.sort(key=lambda e: e.get("modificado", ""), reverse=True)
    for e in entradas:
        ruta_n = _sin_tildes(e["ruta"])
        nombre_n = _sin_tildes(os.path.splitext(os.path.basename(e["ruta"]))[0])
        en_nombre = sum(1 for c in claves if c in nombre_n)
        en_carpeta = sum(1 for c in claves if c in ruta_n and c not in nombre_n)
        puntaje, motivos = en_nombre * 5 + en_carpeta, []
        if en_nombre:
            motivos.append("el nombre coincide")
        elif en_carpeta:
            motivos.append("está en una carpeta del tema")
        if time.time() - inicio < presupuesto:
            texto = _texto_de(e["ruta"], e.get("extension", ""), e.get("peso", 0))
            if texto:
                presentes = [c for c in claves if c in texto]
                if len(presentes) >= max(1, math.ceil(len(claves) * 0.6)):
                    apariciones = sum(texto.count(c) for c in presentes)
                    puntaje += len(presentes) * 2 + min(apariciones, 8)
                    motivos.append("lo menciona dentro")
        if puntaje > 0:
            resultados.append({"ruta": e["ruta"], "puntaje": puntaje, "motivo": " y ".join(motivos)})
    resultados.sort(key=lambda r: r["puntaje"], reverse=True)
    return resultados[:maximo]


def decir_archivos_tema(tema):
    if not _indice():
        _msg("Todavía no indexé tus archivos. Dime 'actualizar archivos' primero (tarda un rato la primera vez).")
        return
    _msg(f"Buscando tus archivos sobre '{tema}' por nombre y por contenido...")
    res = buscar_archivos_tema(tema)
    if not res:
        _msg(f"No encontré archivos sobre '{tema}'. (Si son nuevos, di 'actualizar archivos'; "
             "por dentro solo leo texto plano y Word.)")
        return
    _msg(f"Encontré {len(res)} archivo(s) sobre '{tema}'. Di 'abre el 1' (o 'abre la carpeta del 1'):")
    for i, r in enumerate(res, start=1):
        print(f"  {i}. {os.path.basename(r['ruta'])}   ({_carpeta_corta(r['ruta'])}) — {r['motivo']}")
    _recordar_lista(res)


_ORDINALES = {"primero": 1, "primer": 1, "segundo": 2, "tercero": 3, "tercer": 3, "cuarto": 4, "quinto": 5,
              "sexto": 6, "septimo": 7, "octavo": 8, "noveno": 9, "decimo": 10}


def abrir_resultado_n(texto_n, carpeta=False):
    """Abre el N de la ultima lista. Devuelve False si no hay lista vigente (la frase sigue su camino)."""
    if not _ultimos["items"] or time.time() - _ultimos["cuando"] > VIGENCIA_RESULTADOS_S:
        return False
    items = _ultimos["items"]
    n = len(items) if texto_n == "ultimo" else int(texto_n) if texto_n.isdigit() else _ORDINALES.get(texto_n)
    if not n or not 1 <= n <= len(items):
        _msg(f"Esa lista tiene {len(items)} elemento(s); dime un número entre 1 y {len(items)}.")
        return True
    ruta = items[n - 1]["ruta"]
    if not os.path.exists(ruta):
        _msg("Ese archivo ya no está en su lugar.")
        return True
    try:
        if carpeta:
            _mostrar_en_carpeta(ruta)
            _msg(f"Te muestro dónde está {os.path.basename(ruta)}.")
        else:
            _abrir(ruta)
            _msg(f"Abriendo {os.path.basename(ruta)}...")
    except Exception:
        _msg("No pude abrir ese archivo.")
    return True


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_ORD = "|".join(list(_ORDINALES) + ["ultimo"])
_R_DIAGNOSTICO = re.compile(
    r"^(?:dame\s+|haz(?:me)?\s+|hazme\s+)?(?:un\s+|el\s+)?(?:diagnostico|chequeo|check\s*up|revision(?:\s+completa)?)"
    r"(?:\s+(?:de|a)\s+(?:mi\s+|el\s+)?(?:pc|computador|computadora|compu|laptop|portatil|equipo|sistema))?$|"
    r"^(?:revisa|chequea|diagnostica)\s+(?:mi\s+|el\s+)?(?:pc|computador|computadora|compu|laptop|portatil|equipo|sistema)$|"
    r"^(?:mi\s+(?:pc|computador|compu|laptop|portatil)\s+(?:va|esta|anda)\s+(?:muy\s+)?(?:lenta?|pesad[ao])|"
    r"por\s+que\s+(?:esta|va)\s+(?:tan\s+)?lent[ao]\s+(?:mi\s+)?(?:pc|computador|compu|laptop|portatil))$")
_R_CPU = re.compile(r"^(?:que|cual)\s+(?:programa\s+|proceso\s+|programas\s+|procesos\s+|app\s+)?(?:consume|gasta|usa|esta\s+usando|esta\s+gastando)\s+mas\s+(?:cpu|procesador)$|"
                    r"^(?:uso\s+de\s+(?:cpu|procesador)|programas\s+que\s+mas\s+(?:cpu|procesador)\s+usan)$")
_R_MEMORIA = re.compile(r"^(?:que|cual)\s+(?:programa\s+|proceso\s+|programas\s+|procesos\s+|app\s+)?(?:consume|gasta|usa|esta\s+usando|esta\s+gastando)\s+mas\s+(?:memoria|ram)$|"
                        r"^(?:uso\s+de\s+(?:memoria|ram)|programas\s+que\s+mas\s+(?:memoria|ram)\s+usan)$")
_R_LIBERAR = re.compile(r"^(?:libera(?:r)?|liberame)\s+(?:memoria|ram)$|^cierra\s+(?:lo\s+que\s+mas\s+consume|los\s+programas\s+pesados|lo\s+pesado)$|"
                        r"^(?:hay\s+que\s+)?(?:libera(?:r)?|aligera(?:r)?)\s+(?:el\s+|mi\s+)?(?:pc|computador|compu|sistema)$|^me\s+falta\s+memoria$")
_R_DISCOS = re.compile(r"^(?:espacio|capacidad)\s+(?:de\s+)?(?:mis\s+|los\s+|cada\s+)?discos?$|^cuanto\s+espacio\s+(?:tengo|queda|me\s+queda)\s+(?:en\s+)?(?:cada\s+|mis\s+|los\s+)?discos?$|"
                       r"^(?:mis\s+)?discos$|^unidades$")
_R_GRANDES = re.compile(r"^(?:que|cuales)\s+(?:es\s+lo\s+que\s+|archivos\s+)?(?:ocupa|ocupan|pesa|pesan|gasta|gastan)\s+mas(?:\s+(?:espacio|disco))?$|"
                        r"^(?:archivos|cosas)\s+(?:mas\s+)?(?:grandes|pesados|pesadas)$|^que\s+me\s+(?:llena|esta\s+llenando)\s+el\s+disco$|"
                        r"^archivos\s+que\s+mas\s+(?:pesan|ocupan)$")
_R_DUPLICADOS = re.compile(r"^(?:busca(?:r)?|encuentra|hay|detecta|revisa)\s+(?:los\s+|mis\s+)?(?:archivos\s+)?(?:duplicados|repetidos)$|"
                           r"^(?:archivos\s+)?(?:duplicados|repetidos)$|^tengo\s+(?:archivos\s+)?(?:duplicados|repetidos)$")
_R_MOVER_DUP = re.compile(r"^(?:mueve|manda|pasa|limpia|borra|elimina)\s+(?:los\s+|las\s+)?(?:archivos\s+)?(?:duplicados|repetidos|copias)(?:\s+a\s+la\s+papelera(?:\s+de\s+arche)?)?$")
_R_DESCARGAS = re.compile(r"^(?:revisa|mira|ver|analiza)\s+(?:mis\s+|las\s+)?descargas(?:\s+viejas)?$|^descargas\s+viejas$|^que\s+hay\s+en\s+(?:mis\s+)?descargas$")
_R_LIMPIAR_DESC = re.compile(r"^(?:limpia|limpiar|mueve|borra|ordena)\s+(?:mis\s+|las\s+)?descargas(?:\s+viejas)?(?:\s+a\s+la\s+papelera(?:\s+de\s+arche)?)?$")
_R_ANALIZAR_LIMP = re.compile(r"^(?:que\s+(?:puedo|podemos)\s+limpiar|analiza\s+(?:la\s+)?limpieza|cuanta\s+basura\s+tengo|limpieza\s+profunda|"
                              r"analiza\s+(?:mi\s+)?(?:pc|computador|compu)\s+para\s+limpiar|que\s+basura\s+hay)$")
_R_LIMPIAR = re.compile(r"^(?:limpia|libera)\s+(todo|tmp|temporales(?:\s+de\s+windows)?|pycache|cache|(?:los\s+)?archivos\s+temporales|"
                        r"temp\s+de\s+windows|pycache\s+y\s+tmp|tmp\s+y\s+pycache)$|^limpia\s+(?:mi\s+|el\s+)?(?:pc|computador|compu)$")
_R_TEMA = re.compile(r"^(?:busca(?:me)?|encuentra(?:me)?|dame|trae(?:me)?|ubica)\s+(?:mis\s+|los\s+|todos\s+los\s+|las\s+)?"
                     r"(?:archivos|documentos|papeles|trabajos|apuntes|informes)\s+"
                     r"(?:sobre|de|del|acerca\s+de|que\s+hablen\s+de|relacionados\s+con|con)\s+(.+)$")
_R_ABRIR_N = re.compile(rf"^abre\s+(?:el\s+|la\s+)?(\d+|{_ORD})(?:\s+(?:archivo|resultado|de\s+la\s+lista))?$")
_R_ABRIR_CARPETA_N = re.compile(rf"^(?:abre|muestra(?:me)?|ver)\s+(?:la\s+)?carpeta\s+(?:del|de\s+el|de\s+la)\s+(\d+|{_ORD})$")
_R_RESTAURAR = re.compile(r"^(?:restaura|devuelve|recupera|deshaz)\s+(?:lo\s+de\s+)?(?:la\s+)?(?:papelera(?:\s+de\s+arche)?|lo\s+que\s+(?:moviste|limpiaste))$")
_R_VACIAR = re.compile(r"^(?:vacia|borra\s+para\s+siempre|elimina\s+para\s+siempre)\s+(?:la\s+)?papelera(?:\s+de\s+arche)?$")


def interpretar(comando):
    """(intencion, argumento) o None. No ejecuta nada."""
    t = _limpio(comando)
    if not t:
        return None
    for rx, nombre in ((_R_RESTAURAR, "restaurar_papelera"), (_R_VACIAR, "vaciar_papelera"),
                       (_R_MOVER_DUP, "mover_duplicados"), (_R_DUPLICADOS, "buscar_duplicados"),
                       (_R_LIMPIAR_DESC, "limpiar_descargas"), (_R_DESCARGAS, "descargas_viejas"),
                       (_R_ANALIZAR_LIMP, "analizar_limpieza"), (_R_DIAGNOSTICO, "diagnostico_pc"),
                       (_R_CPU, "programas_cpu"), (_R_MEMORIA, "programas_memoria"), (_R_LIBERAR, "liberar_memoria"),
                       (_R_DISCOS, "espacio_discos"), (_R_GRANDES, "archivos_grandes")):
        if rx.match(t):
            return (nombre, None)
    m = _R_LIMPIAR.match(t)
    if m:
        return ("limpiar_pc", t)
    m = _R_TEMA.match(t)
    if m:
        return ("buscar_archivos_tema", m.group(1).strip())
    m = _R_ABRIR_CARPETA_N.match(t)
    if m:
        return ("abrir_carpeta_resultado", m.group(1))
    m = _R_ABRIR_N.match(t)
    if m:
        return ("abrir_resultado", m.group(1))
    return None


def manejar(comando):
    """Ejecuta una orden de control avanzado. (intencion, contenido) o None."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual

    # "abre el 2" solo cuenta si hay una lista reciente; si no, que la frase siga su camino
    if intencion in ("abrir_resultado", "abrir_carpeta_resultado"):
        if not abrir_resultado_n(arg, carpeta=(intencion == "abrir_carpeta_resultado")):
            return None
        return (intencion, arg)

    if intencion == "diagnostico_pc":
        decir_diagnostico()
    elif intencion == "programas_cpu":
        decir_top("cpu")
    elif intencion == "programas_memoria":
        decir_top("ram")
    elif intencion == "liberar_memoria":
        liberar_memoria()
    elif intencion == "espacio_discos":
        decir_discos()
    elif intencion == "archivos_grandes":
        decir_archivos_grandes()
    elif intencion == "buscar_duplicados":
        decir_duplicados()
    elif intencion == "mover_duplicados":
        mover_duplicados()
    elif intencion == "descargas_viejas":
        decir_descargas()
    elif intencion == "limpiar_descargas":
        limpiar_descargas()
    elif intencion == "analizar_limpieza":
        decir_analisis_limpieza()
    elif intencion == "limpiar_pc":
        limpiar_pc(arg)
    elif intencion == "buscar_archivos_tema":
        decir_archivos_tema(arg)
    elif intencion == "restaurar_papelera":
        restaurar_papelera()
    elif intencion == "vaciar_papelera":
        vaciar_papelera()
    return (intencion, arg)