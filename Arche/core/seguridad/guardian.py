"""
guardian.py
-----------
Ubicacion: Arche/core/seguridad/guardian.py

El guardian vigila que nadie (un malware, otra persona, o la propia Arché por
error) cambie el codigo de Arché a escondidas, y deja una bitacora que no se
puede editar sin que se note.

1. MANIFIESTO FIRMADO (integridad del codigo)
   Guarda la "huella" SHA-256 de cada .py de Arché en Database/integridad.json
   y firma ese archivo con HMAC-SHA256. La llave de la firma se guarda CIFRADA
   (core/seguridad/cifrado.py), asi que un programa que cambie un .py y luego
   intente "arreglar" el manifiesto no puede volver a firmarlo: el guardian lo
   detecta al arrancar.
   - sellar()               -> toma la foto de como esta el codigo ahora (tu lo apruebas)
   - verificar()            -> compara: archivos cambiados, nuevos o borrados
   - registrar_cambio_propio(rel) -> lo llaman los sistemas de autocambio de Arché
                              despues de aplicar un cambio aprobado, para que no
                              salte la alarma con sus propios arreglos.

2. ESCANER DE CODIGO PELIGROSO (para la autocodificacion)
   escanear_cambio(viejo, nuevo) dice si un cambio METE cosas que un malware
   usaria: ejecutar comandos, eval/exec, borrar carpetas, abrir conexiones,
   descargar de internet, ofuscar con base64, tocar el registro o el inicio de
   Windows, etc. Si las mete, el cambio NO se aplica solo: queda para que tu
   lo revises a mano.

3. BITACORA ENCADENADA (auditoria)
   auditar(evento, ...) escribe una linea en Database/auditoria.jsonl. Cada
   linea lleva el hash de la anterior y una firma HMAC, como una cadena:
   si alguien borra o edita una linea del medio, verificar_bitacora() lo nota.
"""

import ast
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from core.rutas import BASE, DATABASE
from core.seguridad import cifrado

RAIZ = Path(BASE)
ARCHIVO_MANIFIESTO = os.path.join(DATABASE, "integridad.json")
ARCHIVO_LLAVE = os.path.join(DATABASE, "integridad.llave")
ARCHIVO_BITACORA = os.path.join(DATABASE, "auditoria.jsonl")

# Carpetas que no son codigo vivo de Arché (respaldos, caches, entornos...)
CARPETAS_IGNORADAS = {"__pycache__", ".git", "venv", ".venv", "env", "Database", "backups_codigo",
                      "build", "dist", "node_modules", "Versiones de Arche"}
PREFIJOS_IGNORADOS = ("respaldo_",)
EXTENSIONES = {".py", ".pyw", ".bat", ".ps1", ".cmd", ".vbs"}

_lock = threading.RLock()
_llave_cache = None


# ------------------------------------------------------------------
# Llave de firma (cifrada en disco)
# ------------------------------------------------------------------

def _llave():
    global _llave_cache
    with _lock:
        if _llave_cache:
            return _llave_cache
        guardada = cifrado.leer_secreto(ARCHIVO_LLAVE)
        if not guardada:
            guardada = secrets.token_hex(32)
            cifrado.guardar_secreto(ARCHIVO_LLAVE, guardada)
        _llave_cache = guardada.encode("utf-8")
        return _llave_cache


def _firmar(texto):
    return hmac.new(_llave(), texto.encode("utf-8"), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------
# 1. Manifiesto de integridad
# ------------------------------------------------------------------

def _archivos_vigilados():
    for ruta in RAIZ.rglob("*"):
        if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES:
            continue
        partes = ruta.relative_to(RAIZ).parts
        if any(p in CARPETAS_IGNORADAS or p.startswith(PREFIJOS_IGNORADOS) for p in partes[:-1]):
            continue
        yield ruta


def _rel(ruta):
    return Path(ruta).resolve().relative_to(RAIZ.resolve()).as_posix()


def huella(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def _cuerpo_firmable(archivos):
    return json.dumps(archivos, sort_keys=True, ensure_ascii=False)


def _leer_manifiesto():
    """Devuelve (archivos, valido). valido=False si falta o si la firma no cuadra."""
    try:
        with open(ARCHIVO_MANIFIESTO, "r", encoding="utf-8") as f:
            m = json.load(f)
        archivos = m["archivos"]
        firma = m["firma"]
    except (OSError, ValueError, KeyError, TypeError):
        return None, False
    return archivos, hmac.compare_digest(firma, _firmar(_cuerpo_firmable(archivos)))


def _escribir_manifiesto(archivos):
    datos = {"version": 1, "sellado": time.strftime("%Y-%m-%d %H:%M:%S"),
             "archivos": archivos, "firma": _firmar(_cuerpo_firmable(archivos))}
    os.makedirs(DATABASE, exist_ok=True)
    tmp = ARCHIVO_MANIFIESTO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ARCHIVO_MANIFIESTO)


def sellado():
    return os.path.exists(ARCHIVO_MANIFIESTO)


def sellar(motivo="sellado manual"):
    """Toma la huella de todo el codigo actual y la firma. Devuelve cuantos archivos."""
    with _lock:
        archivos = {_rel(r): huella(r) for r in _archivos_vigilados()}
        _escribir_manifiesto(archivos)
    auditar("codigo_sellado", archivos=len(archivos), motivo=motivo)
    return len(archivos)


def verificar():
    """
    Compara el codigo con el manifiesto firmado. Devuelve un dict:
      {"sellado": bool, "firma_valida": bool, "cambiados": [...], "nuevos": [...], "borrados": [...]}
    """
    with _lock:
        archivos, valido = _leer_manifiesto()
        if archivos is None:
            return {"sellado": False, "firma_valida": False, "cambiados": [], "nuevos": [], "borrados": []}
        actuales = {_rel(r): r for r in _archivos_vigilados()}
        cambiados = sorted(rel for rel, r in actuales.items() if rel in archivos and huella(r) != archivos[rel])
        nuevos = sorted(rel for rel in actuales if rel not in archivos)
        borrados = sorted(rel for rel in archivos if rel not in actuales)
    return {"sellado": True, "firma_valida": valido, "cambiados": cambiados, "nuevos": nuevos, "borrados": borrados}


def hay_alerta(resultado=None):
    r = resultado or verificar()
    return bool(r["sellado"] and (not r["firma_valida"] or r["cambiados"] or r["nuevos"] or r["borrados"]))


def registrar_cambio_propio(rel, motivo="cambio propio de Arché"):
    """
    Lo llaman los sistemas de autocambio de Arché DESPUES de aplicar un cambio aprobado,
    para actualizar solo ese archivo en el manifiesto. Si el manifiesto ya estaba
    alterado (firma invalida), NO lo re-firma: la alarma se queda hasta que tu revises.
    """
    if not sellado():
        return False
    with _lock:
        archivos, valido = _leer_manifiesto()
        if not valido:
            auditar("cambio_propio_sin_resellar", archivo=rel, razon="manifiesto con firma invalida")
            return False
        ruta = RAIZ / rel
        if ruta.exists():
            archivos[Path(rel).as_posix()] = huella(ruta)
        else:
            archivos.pop(Path(rel).as_posix(), None)
        _escribir_manifiesto(archivos)
    auditar("cambio_propio_registrado", archivo=rel, motivo=motivo)
    return True


def resumen_texto(resultado=None):
    r = resultado or verificar()
    if not r["sellado"]:
        return "El código todavía no está sellado. Corre:  python seguridad.py sellar"
    if not r["firma_valida"]:
        return ("⚠ ALERTA: el registro de integridad fue modificado por alguien que no es Arché "
                "(la firma no coincide). Revisa tu PC con Windows Defender antes de seguir.")
    partes = []
    for clave, nombre in (("cambiados", "cambiados"), ("nuevos", "nuevos"), ("borrados", "borrados")):
        if r[clave]:
            lista = ", ".join(r[clave][:5]) + (f" y {len(r[clave]) - 5} más" if len(r[clave]) > 5 else "")
            partes.append(f"{len(r[clave])} {nombre} ({lista})")
    if not partes:
        return "Código íntegro: nada cambió desde el último sellado."
    return ("⚠ Archivos de Arché que cambiaron sin pasar por su sistema de cambios: " + "; ".join(partes) +
            ". Si fuiste tú, corre  python seguridad.py sellar  para aprobarlo.")


# ------------------------------------------------------------------
# 2. Escaner de codigo peligroso
# ------------------------------------------------------------------

# (nombre, explicacion, patron). Se busca en el codigo SIN comentarios.
PATRONES_PELIGROSOS = [
    ("ejecutar_comandos", "ejecuta comandos del sistema",
     r"\bsubprocess\.|\bos\.(system|popen|exec\w*|spawn\w*|startfile)\b|\bpty\.spawn"),
    ("eval_exec", "ejecuta texto como código (eval/exec/compile)",
     r"(?<![\w.])(eval|exec|compile|__import__)\s*\("),
    ("borrado_masivo", "borra carpetas o archivos",
     r"\bshutil\.rmtree\b|\bos\.(remove|unlink|rmdir|removedirs)\b|\.unlink\(|\.rmdir\(|send2trash"),
    ("red_cruda", "abre conexiones de red directas",
     r"\bsocket\.(socket|create_connection)\b|\bparamiko\b|\btelnetlib\b|\bftplib\b|\bsmtplib\b"),
    ("descargas", "descarga o envía cosas a internet",
     r"\burllib\.request\b|\burlopen\(|\brequests\.(get|post|put|request)\b|\bhttpx\.|\bwget\b|\bcurl\b"),
    ("ofuscacion", "decodifica código escondido (base64/zlib/marshal)",
     r"\bb(ase)?64decode\b|\bbase64\.b\d+decode\b|\bzlib\.decompress\b|\bmarshal\.loads\b|\bcodecs\.decode\b"),
    ("deserializacion", "carga objetos que pueden ejecutar código (pickle/shelve/yaml.load)",
     r"\bpickle\.loads?\b|\bdill\.|\bshelve\.open\b|\byaml\.load\("),
    ("bajo_nivel", "llama funciones internas de Windows o del sistema (ctypes)",
     r"\bctypes\b|\bwin32api\b|\bwin32con\b"),
    ("persistencia", "se instala en el inicio de Windows o toca el registro",
     r"\bwinreg\b|\b_winreg\b|CurrentVersion\\\\?Run|\bschtasks\b|Startup|shell:startup|\breg\s+add\b"),
    ("espionaje", "captura teclado, pantalla o portapapeles",
     r"\bpynput\b|\bkeyboard\.(hook|on_press|record)\b|\bImageGrab\b|\bpyperclip\.paste\b|\bmss\("),
    ("credenciales", "lee claves, cookies o contraseñas guardadas",
     r"Login Data|\bCookies\b|\bkeyring\.get_password\b|nube_clave|integridad\.llave|\.llave_arche"),
    ("toca_seguridad", "intenta modificar el propio sistema de seguridad",
     r"core[/\\.]seguridad|\bguardian\.(sellar|_escribir_manifiesto)|ARCHIVOS_PROTEGIDOS|"
     r"ARCHE_CELULAR_PERMITE_TODO|SOLO_ESTOS_ARCHIVOS_NUNCA"),
]
_PATRONES = [(n, e, re.compile(p, re.IGNORECASE)) for n, e, p in PATRONES_PELIGROSOS]


def _sin_comentarios(codigo):
    """Quita comentarios y docstrings para no alarmarse por texto explicativo."""
    try:
        arbol = ast.parse(codigo)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                cuerpo = getattr(nodo, "body", [])
                if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(getattr(cuerpo[0], "value", None),
                                                                              ast.Constant) \
                        and isinstance(cuerpo[0].value.value, str):
                    cuerpo[0].value.value = ""
        codigo = ast.unparse(arbol)       # ast.unparse ya no trae comentarios
    except (SyntaxError, ValueError, AttributeError):
        codigo = "\n".join(l.split("#", 1)[0] for l in codigo.splitlines())
    return codigo


def _contar(codigo):
    limpio = _sin_comentarios(codigo or "")
    return {n: len(p.findall(limpio)) for n, _, p in _PATRONES}


def escanear_cambio(codigo_viejo, codigo_nuevo):
    """
    Devuelve la lista de hallazgos que el cambio AGREGA (no los que ya estaban):
    [{"tipo": ..., "que_hace": ..., "antes": n, "despues": m}, ...]. Lista vacia = limpio.
    """
    antes, despues = _contar(codigo_viejo), _contar(codigo_nuevo)
    hallazgos = []
    for nombre, explicacion, _ in _PATRONES:
        if despues[nombre] > antes[nombre]:
            hallazgos.append({"tipo": nombre, "que_hace": explicacion,
                              "antes": antes[nombre], "despues": despues[nombre]})
    return hallazgos


def describir_hallazgos(hallazgos):
    return "; ".join(f"{h['que_hace']} ({h['tipo']})" for h in hallazgos)


# ------------------------------------------------------------------
# 3. Bitacora encadenada
# ------------------------------------------------------------------

def _ultima_linea():
    try:
        with open(ARCHIVO_BITACORA, "rb") as f:
            f.seek(0, os.SEEK_END)
            tam = f.tell()
            f.seek(max(0, tam - 8192))
            lineas = [l for l in f.read().splitlines() if l.strip()]
        return json.loads(lineas[-1]) if lineas else None
    except (OSError, ValueError, IndexError):
        return None


def auditar(evento, **detalle):
    """Agrega un evento a la bitacora. Nunca lanza error (la seguridad no debe tumbar a Arché)."""
    try:
        with _lock:
            previa = _ultima_linea()
            registro = {"n": (previa["n"] + 1) if previa else 1, "t": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "evento": str(evento), "detalle": detalle,
                        "previo": previa["hash"] if previa else "0" * 64}
            cuerpo = json.dumps(registro, sort_keys=True, ensure_ascii=False, default=str)
            registro["hash"] = hashlib.sha256(cuerpo.encode("utf-8")).hexdigest()
            registro["firma"] = _firmar(registro["hash"])
            os.makedirs(DATABASE, exist_ok=True)
            with open(ARCHIVO_BITACORA, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def verificar_bitacora():
    """Devuelve (ok, mensaje). Recorre toda la cadena comprobando hashes y firmas."""
    try:
        with open(ARCHIVO_BITACORA, "r", encoding="utf-8") as f:
            lineas = [l for l in f if l.strip()]
    except OSError:
        return True, "La bitácora está vacía."
    previo, esperado_n = "0" * 64, 1
    for i, linea in enumerate(lineas, 1):
        try:
            r = json.loads(linea)
            h, firma = r.pop("hash"), r.pop("firma")
        except (ValueError, KeyError):
            return False, f"Línea {i} dañada o editada a mano."
        if r.get("previo") != previo or r.get("n") != esperado_n:
            return False, f"La cadena se rompe en la línea {i}: borraron o movieron registros."
        cuerpo = json.dumps(r, sort_keys=True, ensure_ascii=False, default=str)
        if hashlib.sha256(cuerpo.encode("utf-8")).hexdigest() != h:
            return False, f"La línea {i} fue modificada."
        if not hmac.compare_digest(firma, _firmar(h)):
            return False, f"La firma de la línea {i} no es de Arché."
        previo, esperado_n = h, esperado_n + 1
    return True, f"Bitácora íntegra ({len(lineas)} registros)."


def ultimos_eventos(n=15):
    try:
        with open(ARCHIVO_BITACORA, "r", encoding="utf-8") as f:
            lineas = [l for l in f if l.strip()][-n:]
        return [json.loads(l) for l in lineas]
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------
# Revision al arrancar
# ------------------------------------------------------------------

def revision_al_iniciar():
    """
    La llama main.py al arrancar. Devuelve un texto corto para decir/mostrar,
    o '' si todo esta bien. Nunca lanza error.
    """
    try:
        r = verificar()
        if not r["sellado"]:
            n = sellar("primer arranque con el guardián")
            return f"Guardián de seguridad activado: selle {n} archivos de mi código."
        ok_bit, msg_bit = verificar_bitacora()
        alertas = []
        if hay_alerta(r):
            alertas.append(resumen_texto(r))
            auditar("alerta_integridad", cambiados=r["cambiados"][:20], nuevos=r["nuevos"][:20],
                    borrados=r["borrados"][:20], firma_valida=r["firma_valida"])
        if not ok_bit:
            alertas.append("⚠ La bitácora de seguridad fue alterada: " + msg_bit)
        auditar("arranque", integridad="alerta" if alertas else "ok")
        return "\n".join(alertas)
    except Exception as e:
        return f"(El guardián no pudo revisar el código: {e})"
