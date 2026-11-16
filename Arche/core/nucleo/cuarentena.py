"""
cuarentena.py
-------------
Ubicacion: Arche/core/nucleo/cuarentena.py

La CUARENTENA del Depredador: donde queda encerrado el código que Arché baja de internet
ANTES de que toque nada. Aquí el código NUNCA se ejecuta: solo se lee.

  descomprimir_seguro()  -> saca del .zip solo texto (.py, .md, .txt...), sin rutas raras
                            (zip-slip), sin archivos gigantes y con un tope de archivos.
  escanear()             -> revisa el código como lo haría un antivirus "de reglas":
                            ejecución escondida (exec/eval, base64+exec, marshal), comandos del
                            sistema, robo de contraseñas/cookies del navegador, keyloggers,
                            cifrado masivo de archivos (ransomware), persistencia en el inicio
                            de Windows, webhooks de Discord/Telegram (robo de datos), código
                            ofuscado, instaladores con trucos (setup.py con cmdclass, .pth).
                            Si Windows Defender está, también lo pasa por Defender.
  revisar_habilidad()    -> la última revisión de lo que Arché ESCRIBIÓ a partir de la presa,
                            con dos niveles: 'seguro' (igual que la fábrica: sin red ni archivos)
                            y 'con_permisos' (puede leer archivos o pedir páginas, nunca borrar,
                            ejecutar comandos ni abrir sockets).

Este archivo es parte del núcleo protegido: Arché no lo puede modificar sola.
"""

import ast
import io
import os
import re
import shutil
import subprocess
import zipfile

EXTENSIONES_TEXTO = {".py", ".md", ".txt", ".rst", ".toml", ".cfg", ".ini", ".json", ".yml", ".yaml", ".pth"}
MAX_ARCHIVOS = 400
MAX_BYTES_ARCHIVO = 300_000
MAX_BYTES_TOTAL = 12_000_000

# (patron, peso, explicación). Peso >= 10 en un solo hallazgo = peligroso.
_REGLAS_TEXTO = [
    (r"(?i)Login Data|Local State|\\Cookies\b|key4\.db|logins\.json|Web Data", 10,
     "lee contraseñas o cookies del navegador"),
    (r"(?i)discord(?:app)?\.com/api/webhooks", 10, "manda datos a un webhook de Discord"),
    (r"(?i)api\.telegram\.org/bot[0-9]{6,}:", 8, "manda datos a un bot de Telegram"),
    (r"(?i)Start Menu\\\\?Programs\\\\?Startup|CurrentVersion\\\\?Run\b", 8,
     "se instala para arrancar con Windows"),
    (r"(?i)\b(?:vssadmin|bcdedit|wevtutil\s+cl|cipher\s+/w|schtasks\s+/create)\b", 10,
     "comando de sistema típico de malware"),
    (r"(?i)\b(?:wallet\.dat|metamask|exodus|electrum)\b", 8, "busca billeteras de criptomonedas"),
    (r"(?i)stratum\+tcp://|xmrig|cryptonight", 10, "minero de criptomonedas"),
    (r"(?i)\bpowershell(?:\.exe)?\b[^\n]{0,60}-(?:enc|encodedcommand|w\s+hidden|windowstyle\s+hidden)", 10,
     "PowerShell escondido o codificado"),
    (r"(?i)\b(?:pastebin\.com/raw|transfer\.sh|anonfiles|ngrok\.io)\b", 6, "descarga o sube a sitios anónimos"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b", 3, "se conecta a una IP fija"),
    (r"[A-Za-z0-9+/]{400,}={0,2}", 5, "trae un bloque codificado muy largo (posible código escondido)"),
    (r"(?:_0x[0-9a-f]{4,}.*){5,}", 6, "nombres ofuscados"),
]

_MODULOS_SISTEMA = {"subprocess", "ctypes", "winreg", "_winreg", "socket", "pty", "telnetlib", "ftplib", "smtplib",
                    "paramiko", "pynput", "keyboard", "mouse", "pyHook", "win32api", "win32con", "win32crypt",
                    "browser_cookie3", "mss", "pyautogui"}
_LLAMADAS_EJECUCION = {"exec", "eval", "compile", "__import__"}
_LLAMADAS_SISTEMA = {"system", "popen", "spawnl", "spawnv", "startfile", "execv", "execl", "execvp"}
_LLAMADAS_BORRAR = {"remove", "unlink", "rmtree", "rmdir", "removedirs", "truncate"}


def descomprimir_seguro(datos_zip, destino):
    """Extrae solo archivos de texto chicos, sin salirse de 'destino'. Devuelve cuántos extrajo."""
    os.makedirs(destino, exist_ok=True)
    destino_real = os.path.realpath(destino)
    total = extraidos = 0
    with zipfile.ZipFile(io.BytesIO(datos_zip)) as z:
        for info in z.infolist():
            if info.is_dir() or extraidos >= MAX_ARCHIVOS:
                continue
            nombre = info.filename.replace("\\", "/")
            ext = os.path.splitext(nombre)[1].lower()
            if ext not in EXTENSIONES_TEXTO or info.file_size > MAX_BYTES_ARCHIVO:
                continue
            if nombre.startswith("/") or ".." in nombre.split("/"):
                continue
            total += info.file_size
            if total > MAX_BYTES_TOTAL:
                break
            ruta = os.path.realpath(os.path.join(destino, nombre))
            if not ruta.startswith(destino_real + os.sep):
                continue
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with z.open(info) as origen, open(ruta, "wb") as f:
                f.write(origen.read(MAX_BYTES_ARCHIVO))
            extraidos += 1
    return extraidos


def _nombre_llamada(nodo):
    f = nodo.func
    if isinstance(f, ast.Name):
        return f.id, ""
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else ""
        return f.attr, base
    return "", ""


def _escanear_python(texto, rel):
    hallazgos = []
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError):
        return hallazgos
    importados = set()
    usa_walk = escribe_binario = cifra = decodifica = False
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add((nodo.module or "").split(".")[0])
        elif isinstance(nodo, ast.Call):
            nombre, base = _nombre_llamada(nodo)
            if nombre in _LLAMADAS_EJECUCION and not (nodo.args and isinstance(nodo.args[0], ast.Constant)):
                hallazgos.append((6, rel, f"ejecuta código armado en el momento ({nombre})"))
            if nombre in _LLAMADAS_SISTEMA or (base == "os" and nombre in ("system", "popen")):
                hallazgos.append((4, rel, f"ejecuta comandos del sistema ({nombre})"))
            if nombre in ("loads", "load") and base in ("marshal", "pickle", "dill"):
                hallazgos.append((5, rel, f"carga objetos binarios ({base}.{nombre})"))
            if nombre in ("b64decode", "decompress", "a85decode", "b85decode", "unhexlify"):
                decodifica = True
            if nombre == "walk":
                usa_walk = True
            if nombre in ("encrypt", "Fernet", "AES") or base in ("Fernet", "AES"):
                cifra = True
            if nombre == "open" and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "w" in a.value
                                        and "b" in a.value for a in nodo.args[1:2]):
                escribe_binario = True
            if nombre in _LLAMADAS_BORRAR:
                hallazgos.append((1, rel, f"borra archivos ({nombre})"))
    peligrosos = importados & _MODULOS_SISTEMA
    if peligrosos:
        hallazgos.append((2 * len(peligrosos), rel, "usa " + ", ".join(sorted(peligrosos))))
    if {"pynput", "keyboard", "pyHook"} & importados and re.search(r"(?i)on_press|hook|Listener", texto):
        hallazgos.append((8, rel, "escucha el teclado (posible keylogger)"))
    if decodifica and re.search(r"\b(?:exec|eval)\s*\(", texto):
        hallazgos.append((10, rel, "decodifica algo y lo ejecuta (código escondido)"))
    if usa_walk and cifra and escribe_binario:
        hallazgos.append((10, rel, "recorre carpetas y cifra archivos (patrón de ransomware)"))
    return hallazgos


def _escanear_setup(texto, rel):
    hallazgos = []
    base = os.path.basename(rel).lower()
    if base == "setup.py" and re.search(r"cmdclass\s*=", texto):
        hallazgos.append((5, rel, "el instalador ejecuta código propio al instalar (cmdclass)"))
    if base.endswith(".pth") and re.search(r"(?m)^\s*import\s", texto):
        hallazgos.append((8, rel, "archivo .pth que ejecuta código al abrir Python"))
    return hallazgos


def _defender(carpeta):
    """True = Defender encontró algo, False = limpio, None = no se pudo usar."""
    if os.name != "nt":
        return None
    exe = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Windows Defender", "MpCmdRun.exe")
    if not os.path.exists(exe):
        return None
    try:
        r = subprocess.run([exe, "-Scan", "-ScanType", "3", "-File", carpeta, "-DisableRemediation"],
                           capture_output=True, text=True, timeout=300)
        return r.returncode == 2
    except (OSError, subprocess.TimeoutExpired):
        return None


def escanear(carpeta, usar_defender=True):
    """
    Revisa todo lo que hay en la cuarentena. Devuelve
      {"veredicto": "limpio"|"sospechoso"|"peligroso", "puntos": int, "hallazgos": [(peso, archivo, por_que)],
       "defender": True/False/None}
    """
    hallazgos = []
    for raiz, _, archivos in os.walk(carpeta):
        for nombre in archivos:
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, carpeta).replace("\\", "/")
            try:
                with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                    texto = f.read(MAX_BYTES_ARCHIVO)
            except OSError:
                continue
            for patron, peso, por_que in _REGLAS_TEXTO:
                if re.search(patron, texto):
                    hallazgos.append((peso, rel, por_que))
            if nombre.endswith(".py"):
                hallazgos += _escanear_python(texto, rel)
            hallazgos += _escanear_setup(texto, rel)
    defender = _defender(carpeta) if usar_defender else None
    if defender:
        hallazgos.append((20, "(toda la carpeta)", "Windows Defender detectó una amenaza"))
    puntos = sum(p for p, _, _ in hallazgos)
    maximo = max((p for p, _, _ in hallazgos), default=0)
    if maximo >= 10 or puntos >= 30:
        veredicto = "peligroso"
    elif puntos >= 12:
        veredicto = "sospechoso"
    else:
        veredicto = "limpio"
    hallazgos.sort(key=lambda h: -h[0])
    return {"veredicto": veredicto, "puntos": puntos, "hallazgos": hallazgos[:25], "defender": defender}


def vaciar(carpeta):
    shutil.rmtree(carpeta, ignore_errors=True)


# ------------------------------------------------------------------
# Revisión final de la habilidad que Arché escribió a partir de la presa
# ------------------------------------------------------------------

_PROHIBIDO_SIEMPRE_IMPORT = {"subprocess", "socket", "ctypes", "winreg", "multiprocessing", "shutil", "pickle",
                             "marshal", "ftplib", "smtplib", "telnetlib", "pty", "pynput", "keyboard"}
_PROHIBIDO_SIEMPRE_LLAMADA = {"eval", "exec", "compile", "__import__", "system", "popen", "remove", "unlink",
                              "rmdir", "rmtree", "removedirs", "kill", "spawn", "startfile", "chmod",
                              "write_text", "write_bytes", "touch", "mkdir", "makedirs", "symlink_to", "truncate"}
# Estas solo son peligrosas sobre os (texto.replace() es normal; os.replace() mueve archivos).
_PROHIBIDO_SOBRE_OS = {"rename", "replace", "renames", "chdir", "putenv"}
_PERMISOS = {
    "archivos": {"imports": {"os", "pathlib", "glob", "csv", "io", "zipfile"}, "llamadas": {"open"}},
    "red": {"imports": {"urllib", "http", "requests"}, "llamadas": set()},
}


def revisar_habilidad(codigo, permisos=()):
    """
    Revisa el código de una habilidad. permisos: () -> como la fábrica (sin red ni archivos);
    ('archivos',), ('red',) o ambos -> se permite eso y nada más.
    Devuelve (ok, motivo).
    """
    try:
        arbol = ast.parse(codigo)
    except SyntaxError:
        return False, "error de sintaxis"
    imports_ok = set()
    llamadas_ok = set()
    for p in permisos:
        imports_ok |= _PERMISOS.get(p, {}).get("imports", set())
        llamadas_ok |= _PERMISOS.get(p, {}).get("llamadas", set())
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Import, ast.ImportFrom)):
            nombres = [a.name for a in nodo.names] if isinstance(nodo, ast.Import) else [nodo.module or ""]
            for n in nombres:
                raiz = n.split(".")[0]
                if raiz in _PROHIBIDO_SIEMPRE_IMPORT:
                    return False, f"importa {n}"
                if raiz in {"os", "pathlib", "glob", "urllib", "http", "requests", "zipfile", "io", "csv"} \
                        and raiz not in imports_ok:
                    return False, f"importa {n} sin tener permiso"
        if isinstance(nodo, ast.Call):
            nombre, base = _nombre_llamada(nodo)
            if nombre in _PROHIBIDO_SIEMPRE_LLAMADA:
                return False, f"usa {nombre}()"
            if base in ("os", "shutil") and nombre in _PROHIBIDO_SOBRE_OS:
                return False, f"usa {base}.{nombre}()"
            if nombre == "open":
                if "open" not in llamadas_ok:
                    return False, "abre archivos sin tener permiso"
                modo = nodo.args[1] if len(nodo.args) > 1 else next(
                    (k.value for k in nodo.keywords if k.arg == "mode"), None)
                if modo is not None and not (isinstance(modo, ast.Constant) and set(str(modo.value)) <= set("rbt")):
                    return False, "intenta escribir archivos (solo se permite leer)"
        if isinstance(nodo, ast.Attribute) and nodo.attr.startswith("__") and nodo.attr not in ("__name__", "__init__"):
            return False, f"usa {nodo.attr}"
    funciones = {n.name for n in arbol.body if isinstance(n, ast.FunctionDef)}
    if not {"ejecutar", "probar"} <= funciones:
        return False, "le falta ejecutar() o probar()"
    return True, "ok"
