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

EXTENSIONES_TEXTO = {".py", ".md", ".txt", ".rst", ".toml", ".cfg", ".ini", ".json", ".yml", ".yaml", ".pth",
                     ".yar", ".yara", ".rules"}                   # las últimas: reglas de detección (solo se LEEN)
MAX_ARCHIVOS = 400
MAX_BYTES_ARCHIVO = 300_000
MAX_BYTES_TOTAL = 12_000_000
# Los archivos de licencia no tienen extensión (LICENSE, COPYING...): se dejan pasar para poder leer la licencia.
_R_ARCHIVO_LICENCIA = re.compile(r"(?i)^(?:licen[sc]e|copying|unlicense)(?:[-_.][\w.-]*)?$")
# Lo que SÍ se considera código que se podría ejecutar (todo lo demás es texto o datos que solo se leen).
_EXT_CODIGO = {".py", ".pth"}

# (patron, peso, explicación). Peso >= 10 en un solo hallazgo = peligroso.
_REGLAS_TEXTO = [
    (r"(?i)(?:ignore|disregard)\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions"
     r"|ignora\s+(?:todas\s+)?las\s+instrucciones\s+anteriores"
     r"|you\s+are\s+now\s+(?:an?\s+)?(?:unrestricted|jailbroken|dan)\b", 6,
     "trae órdenes escondidas dirigidas a la IA que lo lee"),
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
            es_licencia = bool(_R_ARCHIVO_LICENCIA.match(os.path.basename(nombre)))
            if (ext not in EXTENSIONES_TEXTO and not es_licencia) or info.file_size > MAX_BYTES_ARCHIVO:
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


# ------------------------------------------------------------------
# Licencia (para plataformas cuya API no la dice, como Codeberg)
# ------------------------------------------------------------------

_NO_LIBRES = {"gpl", "agpl", "lgpl", "cc-by", "personalizada", "bsd-4-clause"}


def clasificar_licencia(texto):
    """Reconoce por su texto las licencias libres más comunes. Devuelve el identificador SPDX en minúsculas
    ('mit', 'apache-2.0'...), uno de _NO_LIBRES si es copyleft o rara, o '' si no la reconoce."""
    t = re.sub(r"\s+", " ", (texto or "").lower())
    if "gnu affero general public license" in t:
        return "agpl"
    if "gnu lesser general public license" in t:
        return "lgpl"
    if "gnu general public license" in t:
        return "gpl"
    if "commons clause" in t or "non-commercial" in t or "noncommercial" in t:
        return "personalizada"
    if "cc0 1.0 universal" in t:
        return "cc0-1.0"
    if "creative commons" in t:
        return "cc-by"
    if "do what the fuck you want" in t:
        return "wtfpl"
    if "free and unencumbered software released into the public domain" in t:
        return "unlicense"
    if "mozilla public license" in t and "2.0" in t:
        return "mpl-2.0"
    if "apache license" in t and "version 2.0" in t:
        return "apache-2.0"
    if "permission is hereby granted, free of charge" in t:
        return "mit"
    if "altered source versions must be plainly marked" in t:
        return "zlib"
    if "redistribution and use in source and binary forms" in t:
        if "all advertising materials" in t:
            return "bsd-4-clause"
        return "bsd-3-clause" if ("neither the name" in t or "may be used to endorse" in t) else "bsd-2-clause"
    if re.search(r"permission to use, copy, modify, and(?:/or)? distribute this software for any purpose "
                 r"with or without fee is hereby granted", t):
        return "isc" if "provided that the above copyright notice" in t else "0bsd"
    return ""


def detectar_licencia(carpeta):
    """Lee los archivos LICENSE/COPYING de la cuarentena (hasta 2 carpetas de profundidad) y devuelve su
    licencia ('' si no hay o no la reconoce). Si hay varias y alguna es copyleft, gana esa (lo prudente)."""
    encontradas = []
    base = os.path.abspath(carpeta)
    for raiz, dirs, archivos in os.walk(base):
        if os.path.relpath(raiz, base).count(os.sep) >= 2:
            dirs[:] = []
        for nombre in sorted(archivos):
            if not _R_ARCHIVO_LICENCIA.match(nombre):
                continue
            try:
                with open(os.path.join(raiz, nombre), "r", encoding="utf-8", errors="replace") as f:
                    clase = clasificar_licencia(f.read(40_000))
            except OSError:
                continue
            if clase:
                encontradas.append(clase)
    for c in encontradas:
        if c in _NO_LIBRES:
            return c
    return encontradas[0] if encontradas else ""


def _nombre_llamada(nodo):
    f = nodo.func
    if isinstance(f, ast.Name):
        return f.id, ""
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else ""
        return f.attr, base
    return "", ""


def _escanear_python(texto, rel, ejecutable=None):
    """ejecutable: el mismo texto sin comentarios, docstrings ni listas de datos (para los regex)."""
    ejecutable = texto if ejecutable is None else ejecutable
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
            # eval/exec/compile de Python son llamadas sueltas; model.eval() (PyTorch) o re.compile() no lo son
            es_suelta = isinstance(nodo.func, ast.Name) or base == "builtins"
            if es_suelta and nombre in _LLAMADAS_EJECUCION and not (nodo.args and isinstance(nodo.args[0], ast.Constant)):
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
    if {"pynput", "keyboard", "pyHook"} & importados and re.search(r"(?i)on_press|hook|Listener", ejecutable):
        hallazgos.append((8, rel, "escucha el teclado (posible keylogger)"))
    if decodifica and re.search(r"(?<![.\w])(?:exec|eval)\s*\(", ejecutable):
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


def _es_dato(n):
    """True si el nodo es solo datos fijos (textos, números, listas/diccionarios de eso, re.compile('...'))."""
    if isinstance(n, ast.Constant):
        return True
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        return _es_dato(n.operand)
    if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
        return all(_es_dato(e) for e in n.elts)
    if isinstance(n, ast.Dict):
        return all(k is not None and _es_dato(k) and _es_dato(v) for k, v in zip(n.keys, n.values))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "compile" \
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "re":
        return all(_es_dato(a) for a in n.args) and all(_es_dato(k.value) for k in n.keywords)
    return False


def texto_ejecutable(texto):
    """El código SIN lo que no se ejecuta ni decide nada: comentarios, docstrings y listas/diccionarios de
    datos fijos (como las listas de 'cosas que buscar' de un antivirus). Un programa de seguridad menciona
    'Login Data' o 'CurrentVersion\\Run' en esas listas para DETECTAR; un ladrón las usa para ROBAR, y eso
    se ve en cómo las usa, no en que existan. Si el archivo no se puede analizar, se devuelve entero."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    try:
        arbol = ast.parse(texto)
    except (SyntaxError, ValueError, RecursionError):
        return texto
    crudo = texto.encode("utf-8", "replace")
    inicios = [0]
    for linea in crudo.split(b"\n"):
        inicios.append(inicios[-1] + len(linea) + 1)
    borrar, ocultos = [], set()
    for nodo in ast.walk(arbol):
        if id(nodo) in ocultos:
            continue
        es_docstring = isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.Constant) \
            and isinstance(nodo.value.value, str)
        es_lista = isinstance(nodo, (ast.List, ast.Tuple, ast.Set, ast.Dict)) and _es_dato(nodo)
        if not (es_docstring or es_lista) or not hasattr(nodo, "end_lineno"):
            continue
        try:
            a = inicios[nodo.lineno - 1] + nodo.col_offset
            b = inicios[nodo.end_lineno - 1] + nodo.end_col_offset
        except IndexError:
            continue
        borrar.append((a, b))
        ocultos.update(id(h) for h in ast.walk(nodo))
    sobra = bytearray(crudo)
    for a, b in borrar:
        sobra[a:b] = b" " * (b - a)
    limpio = sobra.decode("utf-8", "replace")
    return re.sub(r"(?m)^[ \t]*#.*$", "", limpio)


def escanear(carpeta, usar_defender=True):
    """
    Revisa todo lo que hay en la cuarentena. Devuelve
      {"veredicto": "limpio"|"sospechoso"|"peligroso", "puntos": int, "hallazgos": [(peso, archivo, por_que)],
       "menciones": [(archivo, por_que)], "defender": True/False/None}

    hallazgos: lo que está en CÓDIGO que se podría ejecutar (decide el veredicto).
    menciones: lo mismo, pero solo escrito en documentos, comentarios o listas de datos (README, reglas de
               detección, listas de rutas a vigilar). NO sube el veredicto —así un buen programa de seguridad
               no se confunde con un ladrón—, pero el Depredador no se queda esa presa sin tu permiso.
    """
    hallazgos, menciones = [], []
    for raiz, _, archivos in os.walk(carpeta):
        for nombre in archivos:
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, carpeta).replace("\\", "/")
            try:
                with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                    texto = f.read(MAX_BYTES_ARCHIVO)
            except OSError:
                continue
            es_codigo = os.path.splitext(nombre)[1].lower() in _EXT_CODIGO or nombre.lower() == "setup.py"
            ejecutable = texto_ejecutable(texto) if nombre.endswith(".py") else texto
            for patron, peso, por_que in _REGLAS_TEXTO:
                if not re.search(patron, texto):
                    continue
                if es_codigo and re.search(patron, ejecutable):
                    hallazgos.append((peso, rel, por_que))
                elif por_que.startswith("trae órdenes"):
                    hallazgos.append((peso, rel, por_que))      # órdenes a la IA: cuentan donde estén
                else:
                    menciones.append((rel, por_que))
            if nombre.endswith(".py"):
                hallazgos += _escanear_python(texto, rel, ejecutable)
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
    unicas = list(dict.fromkeys(menciones))
    return {"veredicto": veredicto, "puntos": puntos, "hallazgos": hallazgos[:25], "menciones": unicas[:25],
            "defender": defender}


def vaciar(carpeta):
    shutil.rmtree(carpeta, ignore_errors=True)


# ------------------------------------------------------------------
# Revisión final de la habilidad que Arché escribió a partir de la presa
# ------------------------------------------------------------------

_PROHIBIDO_SIEMPRE_IMPORT = {"subprocess", "socket", "ctypes", "winreg", "multiprocessing", "shutil", "pickle",
                             "marshal", "ftplib", "smtplib", "telnetlib", "pty", "pynput", "keyboard"}
_PROHIBIDO_SIEMPRE_LLAMADA = {"eval", "exec", "compile", "__import__", "system", "popen", "remove", "unlink",
                              "rmdir", "rmtree", "removedirs", "kill", "terminate", "send_signal", "spawn", "startfile", "chmod",
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
            suelta = isinstance(nodo.func, ast.Name) or base == "builtins"
            if nombre in _LLAMADAS_EJECUCION and not suelta:
                pass                                       # re.compile(), model.eval(): no son las de Python
            elif nombre in _PROHIBIDO_SIEMPRE_LLAMADA:
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
