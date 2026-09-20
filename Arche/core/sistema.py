"""
sistema.py
------------
Ubicacion: Arche/core/sistema.py

Control del sistema operativo (pilar 2 del objetivo de Arché):

  1) Estado de recursos: CPU, RAM, disco, y qué procesos consumen más.
  2) Búsqueda de archivos POR CONTENIDO -- archivos.py ya busca por
     NOMBRE; esto busca DENTRO del texto de los archivos.
  3) Limpieza profunda: SIEMPRE en dos pasos -- analizar_limpieza()
     solo mira y reporta, nunca borra nada; ejecutar_limpieza() borra
     pero SOLO las categorías que se le confirman explícitamente,
     usando las rutas que ya te mostró el análisis. Mismo principio
     de "autorización siempre" que rige el resto de Arché: nunca
     borra nada de tu disco sin que lo hayas visto y confirmado antes.

Reutiliza CARPETAS y cargar_indice() de archivos.py en vez de tener
su propio escaneo de carpetas -- mismo universo de "tus archivos"
que ya conocés de "buscar archivo X".
"""

import os
import shutil

import psutil

from core.archivos import CARPETAS, cargar_indice


# ------------------------- 1) RECURSOS DEL SISTEMA -------------------------


def _bytes_legibles(cantidad):
    cantidad = float(cantidad)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if cantidad < 1024:
            return f"{cantidad:.1f} {unidad}"
        cantidad /= 1024
    return f"{cantidad:.1f} PB"


def estado_sistema():
    """CPU, RAM y disco actuales, en crudo (para usar en código). Ver
    también hablar_estado_sistema() para la versión en lenguaje natural."""
    cpu_pct = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disco = psutil.disk_usage(os.path.abspath(os.sep))
    return {
        "cpu_pct": cpu_pct,
        "ram_pct": ram.percent,
        "ram_usada": ram.used,
        "ram_total": ram.total,
        "disco_pct": disco.percent,
        "disco_libre": disco.free,
        "disco_total": disco.total,
    }


def _frase_nivel(pct, bajo_ok=60, medio_ok=85):
    if pct < bajo_ok:
        return "tranquilo"
    if pct < medio_ok:
        return "con carga moderada"
    return "bastante exigido"


def hablar_estado_sistema():
    """Misma info que estado_sistema(), lista para decirte en voz alta."""
    e = estado_sistema()
    return (
        f"El procesador está {_frase_nivel(e['cpu_pct'])} ({e['cpu_pct']:.0f}% de uso). "
        f"La memoria está {_frase_nivel(e['ram_pct'])}: usando {_bytes_legibles(e['ram_usada'])} "
        f"de {_bytes_legibles(e['ram_total'])} ({e['ram_pct']:.0f}%). "
        f"En disco te quedan {_bytes_legibles(e['disco_libre'])} libres de "
        f"{_bytes_legibles(e['disco_total'])} ({e['disco_pct']:.0f}% usado)."
    )


def procesos_que_mas_consumen(top=5):
    """Los `top` procesos que más RAM están usando ahora mismo."""
    procesos = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            info = p.info
            if info["memory_info"] is None:
                continue
            procesos.append({"nombre": info["name"], "ram": info["memory_info"].rss})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    procesos.sort(key=lambda x: x["ram"], reverse=True)
    return procesos[:top]


def hablar_procesos_que_mas_consumen(top=5):
    procesos = procesos_que_mas_consumen(top)
    if not procesos:
        return "Arché: No pude leer los procesos ahora mismo."
    lineas = [f"  • {p['nombre']}: {_bytes_legibles(p['ram'])}" for p in procesos]
    return "Arché: Los procesos que más memoria están usando ahora son:\n" + "\n".join(lineas)


# ------------------------- 2) BÚSQUEDA POR CONTENIDO -------------------------

EXTENSIONES_LEGIBLES = {
    ".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".cfg",
    ".yaml", ".yml", ".js", ".html", ".xml", ".bat", ".ps1",
}
TAMANO_MAXIMO_BYTES = 5 * 1024 * 1024  # no tiene sentido leer línea a línea un archivo de varios MB


def buscar_por_contenido(texto, extensiones=None, max_resultados=20):
    """
    Busca `texto` DENTRO del contenido de tus archivos ya indexados
    (Desktop, Documents, Downloads, etc. -- las mismas carpetas que
    "buscar archivo" en archivos.py). Para buscar por NOMBRE de
    archivo, esa es archivos.buscar(), no esta.
    """
    texto_lower = (texto or "").lower().strip()
    if not texto_lower:
        return []

    extensiones_validas = {e.lower() for e in extensiones} if extensiones else EXTENSIONES_LEGIBLES

    indice = cargar_indice()
    resultados = []
    for elemento in indice:
        if len(resultados) >= max_resultados:
            break
        if elemento["tipo"] != "archivo":
            continue
        if elemento["extension"] not in extensiones_validas:
            continue
        if elemento["peso"] > TAMANO_MAXIMO_BYTES:
            continue
        try:
            with open(elemento["ruta"], "r", encoding="utf-8", errors="ignore") as f:
                for numero_linea, linea in enumerate(f, start=1):
                    if texto_lower in linea.lower():
                        resultados.append({
                            "ruta": elemento["ruta"],
                            "linea": numero_linea,
                            "contexto": linea.strip()[:160],
                        })
                        break  # una coincidencia por archivo alcanza para el listado
        except (OSError, UnicodeDecodeError):
            continue
    return resultados


def mostrar_resultados_contenido(resultados, texto):
    if not resultados:
        print(f"Arché: No encontré '{texto}' en el contenido de tus archivos. "
              f"(Si no corriste 'actualizar indice' recientemente, puede que falte algo nuevo.)")
        return
    print(f"\nArché: Encontré '{texto}' en {len(resultados)} archivo(s):\n")
    for i, r in enumerate(resultados, start=1):
        print(f"{i}. {os.path.basename(r['ruta'])}  (línea {r['linea']})")
        print(f"   ...{r['contexto']}...")
        print(f"   {r['ruta']}")
        print()


# ------------------------- 3) LIMPIEZA PROFUNDA -------------------------
#
# Deliberadamente conservador en esta primera versión: solo caché de
# Python (__pycache__), archivos *.tmp sueltos, y la carpeta Temp de
# Windows del usuario. NO toca la Papelera de reciclaje ni nada dentro
# de Documents/Desktop/etc. -- el riesgo de borrar algo que en
# realidad importaba no vale la pena todavía para esas zonas.

CATEGORIAS_LIMPIEZA = ("pycache", "archivos_tmp", "temporales_windows")

_NOMBRES_CATEGORIA = {
    "pycache": "carpetas de caché de Python (__pycache__)",
    "archivos_tmp": "archivos temporales sueltos (.tmp)",
    "temporales_windows": "lo que hay en tu carpeta Temp de Windows",
}


def _tamano_de(ruta):
    if os.path.isdir(ruta):
        total = 0
        for raiz, _carpetas, archivos in os.walk(ruta):
            for nombre in archivos:
                try:
                    total += os.path.getsize(os.path.join(raiz, nombre))
                except OSError:
                    pass
        return total
    try:
        return os.path.getsize(ruta)
    except OSError:
        return 0


def analizar_limpieza():
    """
    SOLO mira, no borra nada. Devuelve un dict {categoria: {rutas,
    cantidad, peso}} para que veas qué hay antes de decidir si
    confirmás alguna categoría con ejecutar_limpieza().
    """
    candidatos = {c: [] for c in CATEGORIAS_LIMPIEZA}

    for carpeta_base in CARPETAS:
        for raiz, carpetas, _archivos in os.walk(carpeta_base):
            if "__pycache__" in carpetas:
                candidatos["pycache"].append(os.path.join(raiz, "__pycache__"))

    for elemento in cargar_indice():
        if elemento["tipo"] == "archivo" and elemento["extension"] == ".tmp":
            candidatos["archivos_tmp"].append(elemento["ruta"])

    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp and os.path.isdir(temp):
        try:
            for nombre in os.listdir(temp):
                candidatos["temporales_windows"].append(os.path.join(temp, nombre))
        except OSError:
            pass

    reporte = {}
    for categoria, rutas in candidatos.items():
        peso_total = sum(_tamano_de(r) for r in rutas)
        reporte[categoria] = {"rutas": rutas, "cantidad": len(rutas), "peso": peso_total}
    return reporte


def hablar_analisis_limpieza(reporte):
    lineas = []
    total_general = 0
    for categoria in CATEGORIAS_LIMPIEZA:
        datos = reporte.get(categoria, {"cantidad": 0, "peso": 0})
        if datos["cantidad"] == 0:
            continue
        total_general += datos["peso"]
        lineas.append(f"  • {_NOMBRES_CATEGORIA[categoria]}: {datos['cantidad']} elemento(s), {_bytes_legibles(datos['peso'])}")

    if not lineas:
        return "Arché: Revisé y no encontré basura obvia para limpiar por ahora."

    texto = "Arché: Esto es lo que encontré para limpiar (todavía no borré nada):\n" + "\n".join(lineas)
    texto += (
        f"\n\nEn total liberarías más o menos {_bytes_legibles(total_general)}. "
        f"Decime 'limpia <categoría>' (pycache / tmp / temporales windows) o "
        f"'limpia todo' para que borre de verdad lo que te mostré."
    )
    return texto


def ejecutar_limpieza(reporte, categorias):
    """
    Borra SOLO las categorías confirmadas, usando las rutas exactas
    que ya te mostró analizar_limpieza() (no vuelve a escanear, para
    borrar justo lo que viste, ni un archivo nuevo que haya aparecido
    después). Cada error de permiso o archivo en uso se salta sin
    frenar el resto -- es normal que algo en Temp esté siendo usado
    por otro programa en este momento.
    """
    liberado = 0
    borrados = 0
    fallos = 0
    for categoria in categorias:
        for ruta in reporte.get(categoria, {}).get("rutas", []):
            try:
                peso = _tamano_de(ruta)
                if os.path.isdir(ruta):
                    shutil.rmtree(ruta)
                else:
                    os.remove(ruta)
                liberado += peso
                borrados += 1
            except OSError:
                fallos += 1
    return {"borrados": borrados, "fallos": fallos, "liberado": liberado}


def hablar_resultado_limpieza(resultado):
    texto = f"Arché: Listo -- borré {resultado['borrados']} elemento(s) y liberé {_bytes_legibles(resultado['liberado'])}."
    if resultado["fallos"]:
        texto += f" {resultado['fallos']} no los pude borrar (seguramente estaban en uso) -- no pasa nada, los salté."
    return texto


def interpretar_categorias_limpieza(texto):
    """
    Convierte lo que Daniel escribió ('limpia tmp', 'limpia todo',
    'limpia temporales de windows', 'limpia pycache y tmp') en la
    lista de categorías de CATEGORIAS_LIMPIEZA a las que se refiere.
    Separado de main.py para poder probarlo solo, sin correr todo el
    loop de comandos.
    """
    texto = (texto or "").lower()

    if "todo" in texto:
        return list(CATEGORIAS_LIMPIEZA)

    categorias = []
    if "pycache" in texto or "cache" in texto:
        categorias.append("pycache")
    if "windows" in texto or "temporales de windows" in texto or "temp de windows" in texto:
        categorias.append("temporales_windows")
    # "tmp"/"temporal" cuenta para archivos_tmp SOLO si no se refería a
    # la carpeta de windows (ya cubierta arriba) -- evita que "limpia
    # temporales de windows" tambien dispare archivos_tmp por matchear
    # la palabra "temporal".
    if ("tmp" in texto or "temporal" in texto) and "windows" not in texto:
        categorias.append("archivos_tmp")

    return list(dict.fromkeys(categorias))  # sin duplicados, mismo orden
