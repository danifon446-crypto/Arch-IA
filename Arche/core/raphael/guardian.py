"""
guardian.py
-----------
Ubicacion: Arche/core/raphael/guardian.py

GUARDIÁN DEL PC: vigila lo que un antivirus normal a veces deja pasar y te avisa ANTES
de que se vuelva un problema. (La batería, RAM, CPU y disco ya los vigila
core/autonomia.py; esto no los repite.)

Qué vigila (cada 2 minutos, en segundo plano, muy liviano):
  1. IMPOSTORES: programas con nombre de Windows (svchost.exe, lsass.exe...) que corren
     desde fuera de C:\\Windows, o con nombres casi iguales (scvhost.exe, svch0st.exe).
  2. PROGRAMAS NUEVOS en lugares raros: Temp, Descargas, Público... que nunca había visto,
     y si no tienen firma digital, lo dice.
  3. ARRANQUE AUTOMÁTICO: algo nuevo que se agregó para arrancar con Windows
     (registro Run/RunOnce y carpetas de Inicio).
  4. MINEROS: un programa que usa mucha CPU durante mucho rato mientras no estás usando el PC.
  5. TEMPERATURA (si Windows la deja leer; en muchos PC necesita permisos de administrador).

El primer día solo APRENDE qué es normal en tu PC (no avisa de programas nuevos).
Nunca cierra ni borra nada por su cuenta: te avisa y tú decides.

Comandos:
  estado del guardian / escanea mi pc     alertas del guardian
  confia en <programa>                     termina el proceso <número>   (solo uno que él marcó)
  guardian apagado / guardian encendido
"""

import os
import re
import subprocess
import threading
import time

from core.raphael import comun

ARCH = comun.ruta("guardian.json")
INTERVALO = 120                       # segundos entre revisiones
HORAS_APRENDIENDO = 24
ENFRIAMIENTO_ALERTA = 6 * 3600
CPU_MINERO = 50                       # % del total del equipo
MUESTRAS_MINERO = 4                   # revisiones seguidas (~8 min)
MINUTOS_INACTIVO_MINERO = 10
TEMPERATURA_MAXIMA = 90

SISTEMA = {"svchost.exe", "lsass.exe", "csrss.exe", "winlogon.exe", "services.exe", "smss.exe", "explorer.exe",
           "spoolsv.exe", "dllhost.exe", "taskhostw.exe", "conhost.exe", "rundll32.exe", "wininit.exe",
           "lsm.exe", "dwm.exe", "taskmgr.exe", "regsvr32.exe"}
PESADOS_NORMALES = {"python.exe", "pythonw.exe", "ollama.exe", "ollama_llama_server.exe", "ollama app.exe",
                    "msmpeng.exe", "searchindexer.exe", "tiworker.exe", "msiexec.exe", "trustedinstaller.exe",
                    "system", "system idle process", "idle", "memory compression", "mrt.exe", "compattelrunner.exe",
                    "ffmpeg.exe", "obs64.exe", "blender.exe", "cura.exe", "ultimaker-cura.exe", "prusaslicer.exe"}
CARPETAS_RARAS = ("\\appdata\\local\\temp\\", "\\windows\\temp\\", "\\downloads\\", "\\descargas\\", "\\users\\public\\",
                  "\\$recycle.bin\\", "\\programdata\\temp")

_lock = threading.Lock()
_cpu = {}                             # pid -> (proceso psutil, muestras_altas)
_ultima = {"revision": 0.0, "temperatura": 0.0}


# ------------------------------------------------------------------
# Estado
# ------------------------------------------------------------------

def _estado():
    e = comun.cargar(ARCH, {})
    e.setdefault("activo", True)
    e.setdefault("desde", comun.ahora_txt())
    e.setdefault("conocidos", {})          # exe (minúsculas) -> primera vez visto
    e.setdefault("inicio", {})             # clave -> comando
    e.setdefault("confiables", [])
    e.setdefault("alertas", [])
    e.setdefault("avisado", {})            # clave -> time
    e.setdefault("temperatura", None)      # "no disponible" o último valor
    return e


def _guardar(e):
    e["alertas"] = e["alertas"][-100:]
    if len(e["conocidos"]) > 5000:
        e["conocidos"] = dict(list(e["conocidos"].items())[-4000:])
    comun.guardar(ARCH, e)


def aprendiendo(e=None):
    e = e or _estado()
    try:
        desde = time.mktime(time.strptime(e["desde"], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, KeyError):
        return False
    return time.time() - desde < HORAS_APRENDIENDO * 3600


# ------------------------------------------------------------------
# Reglas (funciones puras: se prueban sin Windows)
# ------------------------------------------------------------------

def _distancia(a, b):
    """Distancia de edición contando letras cambiadas, de más, de menos o volteadas (scvhost / svchost = 1)."""
    if abs(len(a) - len(b)) > 2:
        return 3
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            costo = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + costo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def es_impostor(nombre, exe):
    """(bool, por_que)."""
    n = (nombre or "").lower()
    ruta = (exe or "").lower().replace("/", "\\")
    if n in SISTEMA:
        if ruta and not (ruta.startswith("c:\\windows\\") or "\\windows\\system32\\" in ruta or
                         "\\windows\\syswow64\\" in ruta):
            return True, f"se llama {n} como un programa de Windows, pero corre desde {exe}"
        return False, ""
    for real in SISTEMA:
        if n.endswith(".exe") and 0 < _distancia(n, real) <= 1 and len(n) >= 7:
            return True, f"se llama {n}, casi igual a {real} (truco típico de virus)"
    return False, ""


def en_carpeta_rara(exe):
    ruta = (exe or "").lower().replace("/", "\\")
    return any(c in ruta for c in CARPETAS_RARAS)


def evaluar_procesos(procesos, e, confiables=None, aprendiendo_ahora=False):
    """
    procesos: [{"pid", "nombre", "exe"}]. Marca como conocidos los nuevos.
    Devuelve [(clave, gravedad 1-3, texto, pid)].
    """
    confiables = {c.lower() for c in (confiables if confiables is not None else e["confiables"])}
    hallazgos = []
    for p in procesos:
        nombre, exe, pid = (p.get("nombre") or ""), (p.get("exe") or ""), p.get("pid")
        if nombre.lower() in confiables or exe.lower() in confiables:
            continue
        impostor, por_que = es_impostor(nombre, exe)
        if impostor:
            hallazgos.append((f"impostor:{exe.lower() or nombre.lower()}", 3, f"⚠ Programa impostor: {por_que} (proceso {pid}).", pid))
            continue
        clave = (exe or nombre).lower()
        if not clave:
            continue
        nuevo = clave not in e["conocidos"]
        if nuevo:
            e["conocidos"][clave] = comun.ahora_txt()
        if nuevo and not aprendiendo_ahora and en_carpeta_rara(exe):
            hallazgos.append((f"raro:{clave}", 2, f"Apareció un programa nuevo corriendo desde una carpeta rara: {exe} "
                                                  f"(proceso {pid}).", pid))
    return hallazgos


def comparar_inicio(viejo, actual):
    """Entradas de arranque nuevas: [(clave, comando)]."""
    return [(k, v) for k, v in actual.items() if k not in viejo]


# ------------------------------------------------------------------
# Lo que toca Windows
# ------------------------------------------------------------------

def _psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _procesos():
    ps = _psutil()
    if not ps:
        return []
    salida = []
    for p in ps.process_iter(["pid", "name", "exe"]):
        try:
            salida.append({"pid": p.info["pid"], "nombre": p.info.get("name") or "", "exe": p.info.get("exe") or ""})
        except Exception:
            continue
    return salida


def _entradas_de_inicio():
    entradas = {}
    if os.name != "nt":
        return entradas
    try:
        import winreg
        for raiz, nombre_raiz in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            for sub in (r"Software\Microsoft\Windows\CurrentVersion\Run", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"):
                try:
                    with winreg.OpenKey(raiz, sub) as k:
                        i = 0
                        while True:
                            try:
                                n, v, _ = winreg.EnumValue(k, i)
                            except OSError:
                                break
                            entradas[f"{nombre_raiz}\\{sub.split(chr(92))[-1]}\\{n}"] = str(v)
                            i += 1
                except OSError:
                    continue
    except ImportError:
        pass
    for carpeta in (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
                    os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\StartUp")):
        try:
            for n in os.listdir(carpeta):
                entradas[f"Inicio\\{n}"] = os.path.join(carpeta, n)
        except OSError:
            continue
    return entradas


def _firma(exe):
    """'firmado' | 'sin firma' | None (no se pudo saber)."""
    if os.name != "nt" or not exe:
        return None
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-AuthenticodeSignature -LiteralPath '{exe.replace(chr(39), chr(39) * 2)}').Status"],
                           capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        estado = (r.stdout or "").strip().lower()
        return "firmado" if estado == "valid" else ("sin firma" if estado else None)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _temperatura():
    """Grados °C o None. Necesita WMI (en muchos PC, permisos de administrador)."""
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                            "-ErrorAction Stop | Measure-Object -Property CurrentTemperature -Maximum).Maximum"],
                           capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        valor = float((r.stdout or "").strip())
        return round(valor / 10 - 273.15, 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _mineros(minutos_inactivo):
    ps = _psutil()
    if not ps:
        return []
    nucleos = ps.cpu_count() or 1
    vistos = set()
    hallazgos = []
    propio = os.getpid()
    for p in ps.process_iter(["pid", "name", "exe"]):
        pid = p.info["pid"]
        vistos.add(pid)
        if pid == propio or (p.info.get("name") or "").lower() in PESADOS_NORMALES:
            continue
        if pid not in _cpu:
            try:
                p.cpu_percent(None)            # la primera lectura siempre da 0: se "ceba"
            except Exception:
                continue
            _cpu[pid] = [p, 0]
            continue
        try:
            uso = _cpu[pid][0].cpu_percent(None) / nucleos
        except Exception:
            continue
        if uso >= CPU_MINERO and minutos_inactivo >= MINUTOS_INACTIVO_MINERO:
            _cpu[pid][1] += 1
        else:
            _cpu[pid][1] = 0
        if _cpu[pid][1] == MUESTRAS_MINERO:
            hallazgos.append((f"cpu:{(p.info.get('exe') or p.info.get('name') or '').lower()}", 2,
                              f"{p.info.get('name')} (proceso {pid}) lleva ~{MUESTRAS_MINERO * INTERVALO // 60} minutos "
                              f"usando {uso:.0f}% de la CPU mientras no estás usando el PC. Así se comportan los mineros "
                              "de criptomonedas escondidos.", pid))
    for pid in list(_cpu):
        if pid not in vistos:
            _cpu.pop(pid, None)
    return hallazgos


# ------------------------------------------------------------------
# Revisión
# ------------------------------------------------------------------

def _avisar(e, hallazgos):
    nuevas = []
    for clave, gravedad, texto, pid in hallazgos:
        if time.time() - float(e["avisado"].get(clave, 0)) < ENFRIAMIENTO_ALERTA:
            continue
        e["avisado"][clave] = time.time()
        e["alertas"].append({"cuando": comun.ahora_txt(), "clave": clave, "gravedad": gravedad, "texto": texto,
                             "pid": pid})
        nuevas.append((gravedad, texto, pid))
    for gravedad, texto, pid in sorted(nuevas, reverse=True):
        extra = (f"\n  Si no lo reconoces: «termina el proceso {pid}». Si es tuyo: «confía en ...»."
                 if pid else "")
        comun.informe("Guardián: " + texto + extra, importante=gravedad >= 2, nivel="alerta", origen="guardian")
    return nuevas


def revisar(forzar=False):
    """La llama el reloj de Raphael cada minuto; trabaja cada INTERVALO segundos."""
    if not forzar and time.time() - _ultima["revision"] < INTERVALO:
        return []
    _ultima["revision"] = time.time()
    with _lock:
        e = _estado()
        if not e["activo"] and not forzar:
            return []
        apr = aprendiendo(e)
        hallazgos = []
        procesos = _procesos()
        hallazgos += evaluar_procesos(procesos, e, aprendiendo_ahora=apr)
        for i, (clave, grav, texto, pid) in enumerate(hallazgos):
            if clave.startswith("raro:") and i < 3:
                exe = next((p["exe"] for p in procesos if p["pid"] == pid), "")
                firma = _firma(exe)
                if firma == "firmado":
                    hallazgos[i] = (clave, 1, texto + " Tiene firma digital válida.", pid)
                elif firma == "sin firma":
                    hallazgos[i] = (clave, 3, texto + " NO tiene firma digital.", pid)
        actuales = _entradas_de_inicio()
        if e["inicio"] or not apr:
            for clave, cmd in comparar_inicio(e["inicio"], actuales):
                if any(c.lower() in cmd.lower() for c in e["confiables"]):
                    continue
                hallazgos.append((f"inicio:{clave.lower()}", 2,
                                  f"Algo nuevo se agregó para arrancar con Windows: «{clave.split(chr(92))[-1]}» → {cmd}", None))
        e["inicio"] = actuales
        try:
            from core.raphael import ritmo
            inactivo = ritmo.minutos_inactivo()
        except Exception:
            inactivo = 0
        hallazgos += [h for h in _mineros(inactivo) if not any(c.lower() in h[0] for c in e["confiables"])]
        if time.time() - _ultima["temperatura"] > 600 and e.get("temperatura") != "no disponible":
            _ultima["temperatura"] = time.time()
            t = _temperatura()
            if t is None:
                e["temperatura"] = "no disponible"
            else:
                e["temperatura"] = t
                if t >= TEMPERATURA_MAXIMA:
                    hallazgos.append(("temperatura", 2, f"El PC está a {t} °C. Revisa que las rejillas no estén "
                                                        "tapadas y que el ventilador funcione.", None))
        nuevas = _avisar(e, hallazgos)
        _guardar(e)
        return nuevas


def resumen():
    e = _estado()
    hoy = comun.hoy()
    alertas_hoy = [a for a in e["alertas"] if a["cuando"].startswith(hoy)]
    temp = e.get("temperatura")
    return (f"Guardián {'activo' if e['activo'] else 'apagado'}"
            + (" (todavía aprendiendo lo normal de tu PC)" if aprendiendo(e) else "")
            + f". Conozco {len(e['conocidos'])} programas y {len(e['inicio'])} cosas que arrancan con Windows. "
            f"Alertas hoy: {len(alertas_hoy)}. Temperatura: "
            + (f"{temp} °C" if isinstance(temp, (int, float)) else "no la puedo leer en este PC (necesita permisos)"
               if temp == "no disponible" else "todavía no la he medido") + ".")


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_R_CONFIA = re.compile(r"^(?:confia|confiar)\s+en\s+(.+)$")
_R_TERMINA = re.compile(r"^(?:termina|cierra|mata)\s+el\s+proceso\s+(\d+)$")


def manejar(comando):
    c = comun.norm(comando)
    if c in ("estado del guardian", "guardian", "como esta mi pc de seguridad"):
        comun.msg(resumen())
        return True
    if c in ("escanea mi pc", "guardian revisa", "guardian revisa ahora", "revisa la seguridad del pc", "busca virus"):
        comun.msg("Reviso procesos, arranque automático y temperatura...")
        nuevas = revisar(forzar=True)
        if not nuevas:
            comun.msg("No vi nada raro. " + resumen())
        return True
    if c in ("alertas del guardian", "alertas de seguridad del pc", "que alertas hay"):
        e = _estado()
        if not e["alertas"]:
            comun.msg("El guardián no ha encontrado nada raro.")
        else:
            comun.msg("Últimas alertas:\n" + "\n".join(f"  • {a['cuando'][:16]} {a['texto'][:160]}" for a in e["alertas"][-8:]))
        return True
    if c in ("guardian apagado", "apaga el guardian"):
        e = _estado(); e["activo"] = False; _guardar(e)
        comun.msg("Guardián apagado. Di «guardián encendido» para volver a vigilar.")
        return True
    if c in ("guardian encendido", "activa el guardian", "enciende el guardian"):
        e = _estado(); e["activo"] = True; _guardar(e)
        comun.msg("Guardián vigilando.")
        return True
    m = _R_CONFIA.match(c)
    if m and len(m.group(1)) >= 3:
        e = _estado()
        e["confiables"].append(m.group(1).strip())
        _guardar(e)
        comun.msg(f"Listo, confío en «{m.group(1)}» y no te aviso más por eso.")
        return True
    m = _R_TERMINA.match(c)
    if m:
        pid = int(m.group(1))
        e = _estado()
        if not any(a.get("pid") == pid for a in e["alertas"][-30:]):
            comun.msg("Solo cierro procesos que yo mismo marqué como raros. Ese no está en mis alertas.")
            return True
        ps = _psutil()
        try:
            ps.Process(pid).terminate()
            comun.msg(f"Cerré el proceso {pid}. Si vuelve a aparecer, pásale un antivirus completo.")
        except Exception as err:
            comun.msg(f"No pude cerrarlo ({err}). Puede que necesite permisos de administrador.")
        return True
    return False
