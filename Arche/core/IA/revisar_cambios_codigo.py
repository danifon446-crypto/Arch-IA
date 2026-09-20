"""
revisar_cambios_codigo.py
---------------------------
Ubicacion: Arche/core/IA/revisar_cambios_codigo.py

Muestra cada propuesta de cambio de código pendiente (generada por
proponer_cambio_codigo.py) en LENGUAJE NATURAL -- sin jerga técnica,
sin mostrar código -- y pide aprobación explícita [s/n] antes de tocar
un solo archivo. El diff real solo se muestra si lo pedís con 'ver N'.

Flujo de seguridad, generalizado a cualquier archivo:
    1. Backup del archivo completo, con timestamp (nunca se sobreescribe
       un backup viejo).
    2. El cambio se arma primero en memoria.
    3. Si el archivo es .py, se valida que el resultado sea sintácticamente
       válido (ast.parse) ANTES de escribir nada al archivo real.
    4. ENTORNO AISLADO: antes de tocar el archivo real, se arma una copia
       completa de todo el código (.py) del proyecto en una carpeta
       temporal, se aplica el cambio SOLO ahí, y se intenta IMPORTAR el
       módulo modificado desde esa copia. Esto es distinto (y más fuerte)
       que solo validar sintaxis: código sintácticamente válido puede
       romper en tiempo de ejecución (ej. borrar algo que otro módulo
       referencia). Si el import falla o se cuelga, se descarta la copia
       temporal y se aborta -- el archivo real nunca se llega a tocar.
    5. Solo si el paso anterior pasó: se escribe el cambio al archivo real
       (con backup previo, por si la escritura en sí falla por otra razón,
       ej. disco lleno o permisos).
    6. Se registra el resultado en el log inmutable (cambios_codigo_log.jsonl).

Uso:
    python core/IA/revisar_cambios_codigo.py
"""

import ast
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# Igual que en autorevision.py: si este archivo se corre standalone
# (python core/IA/revisar_cambios_codigo.py), sys.path[0] apunta a
# core/IA, no a la raiz del proyecto -- hay que agregarla a mano ANTES
# de importar nada de core.IA.
_RAIZ_APP_TEMPRANO = Path(__file__).resolve().parents[2]
if str(_RAIZ_APP_TEMPRANO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP_TEMPRANO))

from core.IA.evaluar_confianza import evaluar_riesgo
from core.IA.verificar_cambio import verificar_cambio_con_ia

RAIZ_APP = Path(__file__).resolve().parents[2]
BASE = Path(__file__).parent

ARCHIVO_PENDIENTES = BASE / "cambios_codigo_pendientes.json"
ARCHIVO_LOG = BASE / "cambios_codigo_log.jsonl"
CARPETA_BACKUPS = BASE / "backups_codigo"

SMOKE_TEST_EXCLUIDOS = {"main.py"}
TIMEOUT_SMOKE_TEST_SEGUNDOS = 15


def _cargar_pendientes():
    if not ARCHIVO_PENDIENTES.exists():
        return []
    try:
        return json.loads(ARCHIVO_PENDIENTES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _guardar_pendientes(props):
    ARCHIVO_PENDIENTES.write_text(
        json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _log_inmutable(evento):
    evento["timestamp"] = datetime.now().isoformat()
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _hacer_backup(ruta_real: Path, archivo_norm: str):
    CARPETA_BACKUPS.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    nombre_seguro = archivo_norm.replace("/", "__")
    destino = CARPETA_BACKUPS / f"{nombre_seguro}.bak.{marca}"
    if ruta_real.exists():
        shutil.copy2(ruta_real, destino)
    return destino


def _calcular_contenido_nuevo(propuesta, contenido_actual):
    if propuesta["buscar"]:
        return contenido_actual.replace(propuesta["buscar"], propuesta["reemplazar"], 1)
    return propuesta["reemplazar"]


def _diff(contenido_actual, contenido_nuevo, archivo):
    return "\n".join(difflib.unified_diff(
        contenido_actual.splitlines(),
        contenido_nuevo.splitlines(),
        fromfile=f"{archivo} (actual)",
        tofile=f"{archivo} (propuesto)",
        lineterm="",
    ))


def _ruta_a_modulo(archivo_norm: str):
    sin_extension = archivo_norm[:-3] if archivo_norm.endswith(".py") else archivo_norm
    return sin_extension.replace("/", ".")


CARPETAS_EXCLUIDAS_DEL_ENTORNO = {"__pycache__", ".git", "venv", ".venv", "env", "backups_codigo"}


def _copiar_codigo_a_entorno_aislado():
    """
    Copia todos los .py del proyecto a una carpeta temporal nueva,
    preservando la estructura de paquetes (core/, core/IA/, etc.) para
    que los imports relativos ('core.IA.x') funcionen igual que en el
    proyecto real. No copia caches, backups ni datos -- solo código.
    """
    destino = Path(tempfile.mkdtemp(prefix="arche_entorno_aislado_"))
    for archivo in RAIZ_APP.rglob("*.py"):
        if any(parte in CARPETAS_EXCLUIDAS_DEL_ENTORNO for parte in archivo.parts):
            continue
        rel = archivo.relative_to(RAIZ_APP)
        destino_archivo = destino / rel
        destino_archivo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archivo, destino_archivo)
    return destino


def _probar_en_entorno_aislado(archivo_norm: str, contenido_nuevo: str):
    """
    Aplica el cambio SOLO sobre una copia temporal del proyecto y
    verifica ahí que el módulo modificado se pueda importar. El
    archivo real no se toca en ningún momento de esta función --
    eso es justamente el punto: probar antes de arriesgar nada real.
    """
    if archivo_norm in SMOKE_TEST_EXCLUIDOS:
        return True, "prueba en entorno aislado saltada (archivo en SMOKE_TEST_EXCLUIDOS)"

    modulo = _ruta_a_modulo(archivo_norm)
    entorno = None
    try:
        entorno = _copiar_codigo_a_entorno_aislado()

        ruta_en_entorno = entorno / archivo_norm
        ruta_en_entorno.parent.mkdir(parents=True, exist_ok=True)
        ruta_en_entorno.write_text(contenido_nuevo, encoding="utf-8")

        try:
            resultado = subprocess.run(
                [sys.executable, "-c", f"import {modulo}"],
                capture_output=True, text=True, cwd=str(entorno),
                timeout=TIMEOUT_SMOKE_TEST_SEGUNDOS,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return False, (
                f"El import de '{modulo}' se colgó más de "
                f"{TIMEOUT_SMOKE_TEST_SEGUNDOS}s en el entorno aislado "
                f"(posible bucle infinito o input() a nivel de módulo)."
            )

        if resultado.returncode != 0:
            return False, resultado.stderr.strip()[-800:]

        return True, "import correcto en entorno aislado"
    finally:
        if entorno is not None:
            shutil.rmtree(entorno, ignore_errors=True)


def aplicar_propuesta(propuesta):
    ruta = RAIZ_APP / propuesta["archivo"]
    contenido_actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""

    if propuesta["buscar"] and contenido_actual.count(propuesta["buscar"]) != 1:
        print("Arché: El archivo cambió desde que se generó la propuesta "
              "(el fragmento ya no es único o ya no existe). Aborto sin tocar nada.")
        _log_inmutable({"tipo": "cambio_codigo_fallido", "id": propuesta["id"], "error": "fragmento_no_coincide"})
        return False

    contenido_nuevo = _calcular_contenido_nuevo(propuesta, contenido_actual)

    if ruta.suffix == ".py":
        try:
            ast.parse(contenido_nuevo, filename=str(ruta))
        except SyntaxError as e:
            print(f"Arché: El cambio no genera código Python válido, lo aborto sin tocar nada. Error: {e}")
            _log_inmutable({"tipo": "cambio_codigo_fallido", "id": propuesta["id"], "error": str(e)})
            return False

        ok, detalle = _probar_en_entorno_aislado(propuesta["archivo"], contenido_nuevo)
        if not ok:
            print(f"Arché: El cambio pasó la validación de sintaxis pero falló al probarlo en un entorno aislado.")
            print(f"       Detalle: {detalle}")
            print(f"       No toqué el archivo real -- nada quedó modificado.")
            _log_inmutable({
                "tipo": "cambio_codigo_fallido_entorno_aislado",
                "id": propuesta["id"],
                "archivo": propuesta["archivo"],
                "detalle": detalle,
            })
            return False

        # "Reasoning sandwich" -- segunda punta: lo mecánico (sintaxis +
        # entorno aislado) ya confirmó que el cambio NO ESTÁ ROTO, pero
        # nunca confirma que HACE lo que dice que hace. Para cambios que
        # evaluar_confianza.py marcó como medio riesgo o para revisar con
        # cuidado, se lo suma a un chequeo con espíritu crítico antes de
        # tocar el archivo real. Los de bajo riesgo no pagan este costo
        # extra -- ya están bien cubiertos con lo mecánico.
        nivel_riesgo, motivo_riesgo = evaluar_riesgo(propuesta)
        if nivel_riesgo != "bajo":
            aprobado, detalle_problema = verificar_cambio_con_ia(propuesta, nivel_riesgo, motivo_riesgo)
            if not aprobado:
                print(f"Arché: Antes de aplicar esto (era de riesgo {nivel_riesgo}), lo revisé una vez más y encontré algo que no me cierra:")
                print(f"       {detalle_problema}")
                print(f"       No lo apliqué -- si igual querés este cambio, decímelo y lo aplico, o ajustá el pedido y lo regenero.")
                _log_inmutable({
                    "tipo": "cambio_codigo_fallido_verificacion_ia",
                    "id": propuesta["id"],
                    "archivo": propuesta["archivo"],
                    "nivel_riesgo": nivel_riesgo,
                    "detalle": detalle_problema,
                })
                return False

    backup_path = _hacer_backup(ruta, propuesta["archivo"])

    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido_nuevo, encoding="utf-8")
    except Exception as e:
        print(f"Arché: Error al escribir el archivo, restaurando backup automáticamente. ({e})")
        if backup_path.exists():
            shutil.copy2(backup_path, ruta)
        _log_inmutable({"tipo": "cambio_codigo_fallido_escritura", "id": propuesta["id"], "error": str(e)})
        return False

    print(f"Arché: Listo, probé el cambio en un entorno aislado antes de aplicarlo y ya quedó en {propuesta['archivo']}. Backup guardado en {backup_path.name}.")
    _log_inmutable({
        "tipo": "cambio_codigo_aplicado",
        "id": propuesta["id"],
        "archivo": propuesta["archivo"],
        "backup": backup_path.name,
    })
    return True


MAX_ITEMS_POR_LOTE = 8

from core.IA.narrador import (
    ETIQUETA_ORIGEN,
    MAPA_AREAS_NATURALES,
    area_natural as _area_natural,
    texto_amigable_que as _texto_amigable_que,
    frase_confianza as _frase_confianza,
)


def _mostrar_item_resumen(indice, propuesta):
    nivel, motivo = evaluar_riesgo(propuesta)
    origen_texto = ETIQUETA_ORIGEN.get(propuesta.get("origen", ""), propuesta.get("origen", "no sé bien de dónde salió"))
    area = _area_natural(propuesta["archivo"])
    que_natural = _texto_amigable_que(propuesta["que"])
    confianza = _frase_confianza(nivel, motivo)

    print(f" [{indice}] En {area}: {que_natural}")
    print(f"     {origen_texto.capitalize()}. {confianza}")
    if propuesta.get("por_que"):
        print(f"     {propuesta['por_que']}")


def _mostrar_diff_item(propuesta):
    ruta = RAIZ_APP / propuesta["archivo"]
    contenido_actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    contenido_nuevo = _calcular_contenido_nuevo(propuesta, contenido_actual)
    print(f"\nArchivo real: {propuesta['archivo']}")
    print("\nDIFF (código real, lo que vas a ver aplicado si aprobás):")
    diff_texto = _diff(contenido_actual, contenido_nuevo, propuesta["archivo"])
    print(diff_texto if diff_texto else "(archivo nuevo, sin contenido previo)")


def _parsear_respuesta(resp, cantidad):
    resp = resp.strip().lower()
    if resp == "s":
        return set(range(1, cantidad + 1))
    if resp == "n":
        return set()
    if resp.startswith("s "):
        try:
            return {int(x) for x in resp[2:].replace(",", " ").split()}
        except ValueError:
            return None
    return None


def _armar_lotes(pendientes):
    por_origen = {}
    for p in pendientes:
        por_origen.setdefault(p.get("origen", "usuario_directo"), []).append(p)

    lotes = []
    for origen, items in por_origen.items():
        for i in range(0, len(items), MAX_ITEMS_POR_LOTE):
            lotes.append(items[i:i + MAX_ITEMS_POR_LOTE])
    return lotes


def _procesar_lote(lote, numero_lote, total_lotes):
    if total_lotes == 1:
        print(f"\nTengo {len(lote)} cosa(s) para contarte:")
    else:
        print(f"\nGrupo {numero_lote} de {total_lotes} ({len(lote)} cosa(s) en este grupo):")

    for i, propuesta in enumerate(lote, start=1):
        _mostrar_item_resumen(i, propuesta)

    print("\n¿Qué hacemos? 's' = aprobar todo | 'n' = descartar todo | "
          "'s 1,3' = aprobar solo esos | 'ver N' = mostrarte el código de ese ítem")

    aprobados = None
    while aprobados is None:
        resp = input("\nTu respuesta: ").strip().lower()

        if resp.startswith("ver "):
            try:
                idx = int(resp[4:].strip())
                if 1 <= idx <= len(lote):
                    _mostrar_diff_item(lote[idx - 1])
                else:
                    print(f"No hay ítem {idx} acá (son {len(lote)}).")
            except ValueError:
                print("Usá 'ver N' con el número del ítem, ej: ver 2")
            continue

        aprobados = _parsear_respuesta(resp, len(lote))
        if aprobados is None:
            print("No te entendí. Usá 's', 'n', 's 1,3' o 'ver N'.")

    resultados = []
    for i, propuesta in enumerate(lote, start=1):
        if i in aprobados:
            aplicada = aplicar_propuesta(propuesta)
            propuesta["estado"] = "aplicada" if aplicada else "fallida"
            resultados.append((i, propuesta, propuesta["estado"]))
        else:
            propuesta["estado"] = "rechazada"
            _log_inmutable({"tipo": "cambio_codigo_rechazado", "id": propuesta["id"]})
            resultados.append((i, propuesta, "rechazada"))

    print()
    for i, propuesta, estado in resultados:
        area = _area_natural(propuesta["archivo"])
        if estado == "aplicada":
            print(f"  ✔ Listo, ya está aplicado en {area}.")
        elif estado == "fallida":
            print(f"  ✘ Lo intenté en {area} pero falló una verificación, no quedó aplicado (no se rompió nada, se restauró solo).")
        else:
            print(f"  – Descartado el cambio en {area}.")


def main():
    propuestas = _cargar_pendientes()
    pendientes = [p for p in propuestas if p["estado"] == "pendiente"]

    if not pendientes:
        print("Arché: No tengo nada pendiente para mostrarte por ahora.")
        return

    lotes = _armar_lotes(pendientes)
    for numero, lote in enumerate(lotes, start=1):
        _procesar_lote(lote, numero, len(lotes))

    _guardar_pendientes(propuestas)


if __name__ == "__main__":
    main()