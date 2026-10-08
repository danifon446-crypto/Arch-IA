"""
voz.py
------
Ubicacion: Arche/core/voz.py

Hace que Arché HABLE, con dos motores:

  * "natural" (por defecto): voz neuronal de Microsoft Edge (libreria
    edge-tts, necesita internet). Suena mucho mas humana. Se sintetiza a un
    mp3 temporal y se reproduce con la API de audio de Windows (winmm), sin
    instalar nada mas. Si no hay internet o falta la libreria, esa frase se
    dice con el motor del sistema: nunca se queda mudo.
  * "sistema": la voz que trae Windows (System.Speech, por PowerShell), sin
    internet ni instalaciones.

Como funciona el motor del sistema:
  * Se abre UN solo PowerShell que se queda esperando frases y las va
    diciendo en orden. Asi no se paga el arranque de PowerShell en cada
    respuesta.
  * instalar_en_consola() envuelve print() e input(): todo lo que Arché
    imprime con el prefijo "Arché:" se lee en voz alta (solo desde el hilo
    principal, para que el modo estudio o la autorevision en segundo plano
    no se pongan a hablar solos). Ningun modulo existente hay que tocarlo.
  * La voz se prende y apaga con comandos y queda guardada en la
    configuracion (clave "voz").

Todo lo que toca el sistema esta en funciones chicas con "_" adelante
(_lanzar_proceso, _correr_powershell) para poder probarlo sin Windows.
"""

import base64
import builtins
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading

from core import configuracion

ES_WINDOWS = os.name == "nt"

MAX_CARACTERES_VOZ = 380      # una respuesta larguisima no se lee entera
VELOCIDAD_MIN, VELOCIDAD_MAX = -6, 6

MOTORES = ("natural", "sistema")
VOZ_NATURAL_POR_DEFECTO = "es-CO-SalomeNeural"
VOCES_NATURALES = {
    "salome": "es-CO-SalomeNeural", "gonzalo": "es-CO-GonzaloNeural",
    "dalia": "es-MX-DaliaNeural", "jorge": "es-MX-JorgeNeural",
    "elvira": "es-ES-ElviraNeural", "alvaro": "es-ES-AlvaroNeural",
    "ximena": "es-ES-XimenaNeural",
    "elena": "es-AR-ElenaNeural", "tomas": "es-AR-TomasNeural",
    "paloma": "es-US-PalomaNeural", "alonso": "es-US-AlonsoNeural",
    "catalina": "es-CL-CatalinaNeural", "lorenzo": "es-CL-LorenzoNeural",
    "camila": "es-PE-CamilaNeural", "alex": "es-PE-AlexNeural",
    "paola": "es-VE-PaolaNeural", "sebastian": "es-VE-SebastianNeural",
}
# pais -> (voz de mujer, voz de hombre), para "usa la voz mexicana" o "voz de hombre"
VOCES_POR_PAIS = {
    "colombiana": ("salome", "gonzalo"), "mexicana": ("dalia", "jorge"),
    "espanola": ("elvira", "alvaro"), "argentina": ("elena", "tomas"),
    "estadounidense": ("paloma", "alonso"), "chilena": ("catalina", "lorenzo"),
    "peruana": ("camila", "alex"), "venezolana": ("paola", "sebastian"),
}
_PAISES_SINONIMOS = {"colombia": "colombiana", "mexico": "mexicana", "espana": "espanola",
                     "espanol": "espanola", "argentino": "argentina", "colombiano": "colombiana",
                     "mexicano": "mexicana", "chileno": "chilena", "peruano": "peruana",
                     "venezolano": "venezolana", "usa": "estadounidense", "latina": "mexicana"}
_HOMBRE = {"hombre", "masculina", "masculino", "chico", "varon"}
_MUJER = {"mujer", "femenina", "femenino", "chica"}
# TODAS las voces en español de Edge: codigo de pais -> (adjetivo, voz de mujer, voz de hombre)
VOCES_POR_CODIGO = {
    "AR": ("argentina", "Elena", "Tomas"), "BO": ("boliviana", "Sofia", "Marcelo"),
    "CL": ("chilena", "Catalina", "Lorenzo"), "CO": ("colombiana", "Salome", "Gonzalo"),
    "CR": ("costarricense", "Maria", "Juan"), "CU": ("cubana", "Belkys", "Manuel"),
    "DO": ("dominicana", "Ramona", "Emilio"), "EC": ("ecuatoriana", "Andrea", "Luis"),
    "ES": ("espanola", "Elvira", "Alvaro"), "GQ": ("ecuatoguineana", "Teresa", "Javier"),
    "GT": ("guatemalteca", "Marta", "Andres"), "HN": ("hondurena", "Karla", "Carlos"),
    "MX": ("mexicana", "Dalia", "Jorge"), "NI": ("nicaraguense", "Yolanda", "Federico"),
    "PA": ("panamena", "Margarita", "Roberto"), "PE": ("peruana", "Camila", "Alex"),
    "PR": ("puertorriquena", "Karina", "Victor"), "PY": ("paraguaya", "Tania", "Mario"),
    "SV": ("salvadorena", "Lorena", "Rodrigo"), "US": ("estadounidense", "Paloma", "Alonso"),
    "UY": ("uruguaya", "Valentina", "Mateo"), "VE": ("venezolana", "Paola", "Sebastian"),
}
# nombre en minusculas -> nombre completo (salome -> es-CO-SalomeNeural), y pais -> (mujer, hombre)
TODAS_LAS_VOCES = {}
for _cod, (_adj, _mujer, _hombre) in VOCES_POR_CODIGO.items():
    for _n in (_mujer, _hombre):
        TODAS_LAS_VOCES[_n.lower()] = f"es-{_cod}-{_n}Neural"
VOCES_POR_PAIS.update({_adj: (_mujer.lower(), _hombre.lower())
                       for _adj, _mujer, _hombre in VOCES_POR_CODIGO.values()})
TODAS_LAS_VOCES.update({"ximena": "es-ES-XimenaNeural"})
_PAISES_SINONIMOS.update({"bolivia": "boliviana", "chile": "chilena", "peru": "peruana", "cuba": "cubana",
                          "ecuador": "ecuatoriana", "venezuela": "venezolana", "paraguay": "paraguaya",
                          "uruguay": "uruguaya", "panama": "panamena", "honduras": "hondurena",
                          "guatemala": "guatemalteca", "nicaragua": "nicaraguense", "salvador": "salvadorena",
                          "argentina": "argentina", "dominicana": "dominicana", "costarricense": "costarricense",
                          "costa": "costarricense", "estados": "estadounidense", "americana": "estadounidense",
                          "boliviano": "boliviana", "cubano": "cubana", "ecuatoriano": "ecuatoriana",
                          "paraguayo": "paraguaya", "uruguayo": "uruguaya", "panameno": "panamena",
                          "hondureno": "hondurena", "guatemalteco": "guatemalteca", "salvadoreno": "salvadorena",
                          "dominicano": "dominicana", "puertorriqueno": "puertorriquena", "ecuatoguineano": "ecuatoguineana"})
TONO_MIN, TONO_MAX = -6, 6
LECTURAS = ("completa", "corta")
ESPERA_SINCRONIA = 6.0        # segundos maximos esperando el audio antes de mostrar el texto igual
ESPERA_TURNO = 30.0           # segundos maximos esperando a que termine la frase anterior

_proceso = None
_candado = threading.Lock()
_cola_natural = queue.Queue()
_hilo_natural = None
_parar_natural = threading.Event()
_hablando_natural = threading.Event()
_alias_mci = "arche_voz"
_ultimo_mensaje = ""          # lo ultimo que Arché dijo (para "repite eso")
_instalada = False
_print_original = builtins.print
_input_original = builtins.input


# ------------------------------------------------------------------
# Estado (guardado en la configuracion de Arché)
# ------------------------------------------------------------------

def activa():
    return bool(configuracion.obtener("voz"))


def activar():
    configuracion.cambiar("voz", True)


def desactivar():
    configuracion.cambiar("voz", False)
    calla()


def velocidad():
    try:
        v = int(configuracion.obtener("voz_velocidad") or 0)
    except (TypeError, ValueError):
        v = 0
    return max(VELOCIDAD_MIN, min(VELOCIDAD_MAX, v))


def tono():
    try:
        v = int(configuracion.obtener("voz_tono") or 0)
    except (TypeError, ValueError):
        v = 0
    return max(TONO_MIN, min(TONO_MAX, v))


def volumen():
    """0 a 100 (100 = el normal)."""
    v = configuracion.obtener("voz_volumen")
    try:
        v = 100 if v is None else int(v)
    except (TypeError, ValueError):
        v = 100
    return max(0, min(100, v))


def sincronizada():
    """True (por defecto): el texto aparece justo cuando empieza la voz."""
    v = configuracion.obtener("voz_sincronizada")
    return True if v is None else bool(v)


def lectura():
    l = configuracion.obtener("voz_lectura")
    return l if l in LECTURAS else "completa"


def nombre_de_voz():
    return configuracion.obtener("voz_nombre") or ""


def motor():
    m = configuracion.obtener("voz_motor")
    return m if m in MOTORES else "natural"


def fijar_motor(nuevo):
    if nuevo not in MOTORES:
        raise ValueError(f"motor desconocido: {nuevo}")
    configuracion.cambiar("voz_motor", nuevo)
    calla()


def voz_natural():
    return configuracion.obtener("voz_natural") or VOZ_NATURAL_POR_DEFECTO


def fijar_voz_natural(nombre_corto):
    """nombre_corto: clave de VOCES_NATURALES. Devuelve el nombre completo o None."""
    completo = VOCES_NATURALES.get(nombre_corto)
    if completo:
        configuracion.cambiar("voz_natural", completo)
        calla()
    return completo


def hablando():
    """True mientras Arché esta diciendo algo (el microfono debe ignorarse
    para que no se escuche a si mismo)."""
    return _hablando_natural.is_set() or not _cola_natural.empty()


# ------------------------------------------------------------------
# Texto -> algo que suene bien hablado
# ------------------------------------------------------------------

_PREFIJO = re.compile(r"^\s*Arch[eé]:\s*", re.UNICODE)
_EMOJIS = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍■-◿←-⇿]",
    re.UNICODE)


def limpiar_para_voz(texto, maximo=MAX_CARACTERES_VOZ):
    """Quita emojis, markdown, enlaces, barras de progreso y rutas largas, y
    corta en un final de frase. Devuelve '' si no queda nada que valga leer."""
    if not texto:
        return ""
    t = str(texto)
    t = _PREFIJO.sub("", t, count=1)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)            # bloques de codigo
    t = re.sub(r"https?://\S+", " enlace ", t)
    t = re.sub(r"[A-Za-z]:\\[^\s]+", " ", t)                 # rutas de Windows
    t = re.sub(r"(?:/[\w.\-]+){3,}", " ", t)                 # rutas tipo unix
    t = _EMOJIS.sub(" ", t)
    t = re.sub(r"[█▓▒░■□▪▫●○◆◇─━│┃┌┐└┘├┤┬┴┼═║╔╗╚╝]+", " ", t)
    t = re.sub(r"[*_`#>|~]+", " ", t)
    t = re.sub(r"^\s*[-•·]\s+", "", t, flags=re.M)
    t = t.replace("\r", "\n")
    # lineas que son puro numero/simbolo (tablas, porcentajes sueltos) no se leen
    lineas = [l.strip() for l in t.split("\n")]
    lineas = [l for l in lineas if re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{2,}", l)]
    t = ". ".join(l.rstrip(".:;,") for l in lineas)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > maximo:
        corte = t[:maximo]
        punto = max(corte.rfind(". "), corte.rfind("? "), corte.rfind("! "))
        t = corte[:punto + 1] if punto > maximo * 0.4 else corte.rsplit(" ", 1)[0]
    return t.strip()


# ------------------------------------------------------------------
# Sistema: PowerShell con la voz de Windows
# ------------------------------------------------------------------

def _entrecomillar(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def _script_de_voz():
    return (
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        f"$s.Rate = {velocidad()}\n"
        f"$s.Volume = {max(1, volumen())}\n"
        f"$nombre = {_entrecomillar(nombre_de_voz())}\n"
        "if ($nombre) { try { $s.SelectVoice($nombre) } catch {} } else {\n"
        "  $es = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and "
        "$_.VoiceInfo.Culture.Name -like 'es*' } | Select-Object -First 1\n"
        "  if ($es) { $s.SelectVoice($es.VoiceInfo.Name) } }\n"
        "while ($true) {\n"
        "  $l = [Console]::In.ReadLine()\n"
        "  if ($l -eq $null) { break }\n"
        "  try { $t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($l)); $s.Speak($t) } catch {}\n"
        "}\n"
    )


def _codificar_powershell(script):
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _lanzar_proceso():
    """Abre el PowerShell que se queda esperando frases. Devuelve el Popen."""
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-EncodedCommand", _codificar_powershell(_script_de_voz())]
    flags = 0x08000000 if ES_WINDOWS else 0   # CREATE_NO_WINDOW
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)


def _correr_powershell(script, timeout=20):
    """Corre un script suelto y devuelve su salida de texto ('' si falla)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", _codificar_powershell(script)],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000 if ES_WINDOWS else 0)
        return r.stdout or ""
    except Exception:
        return ""


def _proceso_vivo():
    global _proceso
    if _proceso is not None and _proceso.poll() is None:
        return _proceso
    _proceso = _lanzar_proceso()
    return _proceso


def _enviar(texto):
    """Manda una frase al PowerShell (reabre si se cayo). True si salio."""
    for _ in range(2):
        try:
            p = _proceso_vivo()
            linea = base64.b64encode(texto.encode("utf-8")) + b"\n"
            p.stdin.write(linea)
            p.stdin.flush()
            return True
        except Exception:
            _reiniciar()
    return False


def _reiniciar():
    global _proceso
    p, _proceso = _proceso, None
    if p is not None:
        try:
            p.kill()
        except Exception:
            pass


# ------------------------------------------------------------------
# Motor natural: edge-tts (internet) + reproduccion con winmm
# ------------------------------------------------------------------

def edge_tts_instalado():
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


def _porcentaje_de_velocidad():
    """-6..6 de Arché -> '+0%' ... estilo edge-tts (cada punto = 8 %)."""
    return f"{velocidad() * 8:+d}%"


def _hz_de_tono():
    """-6..6 -> '+0Hz' ... (cada punto = 4 Hz)."""
    return f"{tono() * 4:+d}Hz"


def _porcentaje_de_volumen():
    """0..100 -> '+0%' (normal) ... '-50%' (a la mitad)."""
    return f"{volumen() - 100:+d}%"


def _sintetizar(texto, ruta_mp3):
    """Pide la voz a Edge y la guarda en ruta_mp3. Lanza si no hay internet o
    falta la libreria (el que llama cae al motor del sistema)."""
    import asyncio
    import edge_tts
    asyncio.run(edge_tts.Communicate(
        texto, voz_natural(), rate=_porcentaje_de_velocidad(),
        pitch=_hz_de_tono(), volume=_porcentaje_de_volumen()).save(ruta_mp3))


def _mci(comando):
    import ctypes
    buf = ctypes.create_unicode_buffer(255)
    ctypes.windll.winmm.mciSendStringW(comando, buf, 254, 0)
    return buf.value


def _reproducir(ruta_mp3):
    """Reproduce el mp3 y espera a que termine (o a que calla() lo corte)."""
    import time
    _mci(f'close {_alias_mci}')
    _mci(f'open "{ruta_mp3}" type mpegvideo alias {_alias_mci}')
    _mci(f'play {_alias_mci}')
    while not _parar_natural.is_set():
        if _mci(f'status {_alias_mci} mode') != "playing":
            break
        time.sleep(0.05)
    _mci(f'stop {_alias_mci}')
    _mci(f'close {_alias_mci}')


def _preparar_audio(texto, espera=None):
    """Sintetiza el mp3 YA (para poder mostrar el texto justo cuando empiece a
    sonar). Devuelve la ruta o None si no se pudo o tardo demasiado."""
    espera = ESPERA_SINCRONIA if espera is None else espera
    fd, ruta = tempfile.mkstemp(suffix=".mp3", prefix="arche_voz_")
    os.close(fd)
    resultado = {}

    def trabajo():
        try:
            _sintetizar(texto, ruta)
            resultado["ok"] = os.path.getsize(ruta) > 0
        except Exception:
            resultado["ok"] = False

    hilo = threading.Thread(target=trabajo, name="arche-voz-sintesis", daemon=True)
    hilo.start()
    hilo.join(espera)
    if resultado.get("ok"):
        return ruta
    if not hilo.is_alive():          # fallo rapido: se borra ya
        try:
            os.remove(ruta)
        except OSError:
            pass
        return None
    # tardo demasiado: se borra cuando el hilo termine
    def limpiar():
        hilo.join(30)
        try:
            os.remove(ruta)
        except OSError:
            pass
    threading.Thread(target=limpiar, daemon=True).start()
    return None


def _hablar_natural(texto, ruta_lista=None):
    """Una frase completa con la voz natural. False si no se pudo (sin
    internet / sin libreria): el llamador usa entonces el motor del sistema.
    Si ya hay un mp3 listo (ruta_lista) lo usa y lo borra al terminar."""
    if ruta_lista:
        ruta = ruta_lista
    else:
        fd, ruta = tempfile.mkstemp(suffix=".mp3", prefix="arche_voz_")
        os.close(fd)
    try:
        if not ruta_lista:
            _sintetizar(texto, ruta)
        if _parar_natural.is_set():
            return True          # la cortaron: no hay que decirla con otro motor
        if os.path.getsize(ruta) == 0:
            return False
        _reproducir(ruta)
        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


def _bucle_natural():
    while True:
        item = _cola_natural.get()
        texto, ruta = item if isinstance(item, tuple) else (item, None)
        if _parar_natural.is_set():
            if ruta:
                try:
                    os.remove(ruta)
                except OSError:
                    pass
            continue
        _hablando_natural.set()
        try:
            ok = _hablar_natural(texto, ruta) if ruta else _hablar_natural(texto)
            if not ok:
                with _candado:
                    _enviar(texto)        # respaldo: voz del sistema
        finally:
            _hablando_natural.clear()


def _encolar_natural(texto, ruta=None):
    global _hilo_natural
    _parar_natural.clear()
    if _hilo_natural is None or not _hilo_natural.is_alive():
        _hilo_natural = threading.Thread(target=_bucle_natural, name="arche-voz", daemon=True)
        _hilo_natural.start()
    _cola_natural.put((texto, ruta) if ruta else texto)
    return True


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

def _segun_lectura(limpio):
    """Modo 'corta': solo la primera frase (hasta ~170 letras)."""
    if lectura() != "corta" or not limpio:
        return limpio
    m = re.match(r"^(.+?[.!?])(?:\s|$)", limpio)
    primera = m.group(1) if m else limpio
    if len(primera) > 170:
        primera = primera[:170].rsplit(" ", 1)[0]
    return primera


def decir(texto, forzar=False):
    """Dice `texto` en voz alta (si la voz esta activa, o si forzar=True).
    No bloquea: la frase queda en cola. Devuelve True si la mando a hablar."""
    limpio = _segun_lectura(limpiar_para_voz(texto))
    if not limpio:
        return False
    if not (activa() or forzar):
        return False
    if not ES_WINDOWS:      # no hay winmm ni System.Speech (las pruebas ponen ES_WINDOWS=True)
        return False
    if motor() == "natural":
        return _encolar_natural(limpio)
    with _candado:
        return _enviar(limpio)


def calla():
    """Corta lo que esta diciendo y vacia la cola. La voz sigue activa."""
    _parar_natural.set()
    try:
        while True:
            _cola_natural.get_nowait()
    except queue.Empty:
        pass
    with _candado:
        _reiniciar()


def voces_instaladas():
    """[(nombre, idioma)] de las voces de Windows."""
    salida = _correr_powershell(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object "
        "{ $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name }\n")
    voces = []
    for linea in salida.splitlines():
        if "|" in linea:
            nombre, idioma = linea.strip().split("|", 1)
            voces.append((nombre, idioma))
    return voces


def fijar_voz(nombre):
    configuracion.cambiar("voz_nombre", nombre)
    calla()


def fijar_velocidad(valor):
    valor = max(VELOCIDAD_MIN, min(VELOCIDAD_MAX, int(valor)))
    configuracion.cambiar("voz_velocidad", valor)
    calla()
    return valor


def ultimo_mensaje():
    return _ultimo_mensaje


# ------------------------------------------------------------------
# Enganche en print() e input()
# ------------------------------------------------------------------

def _es_hilo_principal():
    return threading.current_thread() is threading.main_thread()


def _esperar_turno():
    """Espera a que termine la frase anterior, para que cada linea de texto
    salga justo cuando empieza SU voz y no antes."""
    import time
    limite = time.time() + ESPERA_TURNO
    while hablando() and time.time() < limite and not _parar_natural.is_set():
        time.sleep(0.05)


def _imprimir_sincronizado(texto, args, kwargs):
    """Pide el audio primero y muestra el texto en el instante en que empieza
    a sonar. Devuelve True si lo logro (si no, el que llama imprime normal)."""
    if not (activa() and sincronizada() and ES_WINDOWS and motor() == "natural"
            and edge_tts_instalado()):
        return False
    limpio = _segun_lectura(limpiar_para_voz(texto))
    if not limpio:
        return False
    ruta = _preparar_audio(limpio)
    if not ruta:
        return False
    _esperar_turno()
    _print_original(*args, **kwargs)
    try:
        _encolar_natural(limpio, ruta)
    except Exception:
        pass
    return True


def _print_con_voz(*args, **kwargs):
    global _ultimo_mensaje
    impreso = False
    try:
        if len(args) == 1 and isinstance(args[0], str) and kwargs.get("file") in (None, sys.stdout):
            texto = args[0]
            if re.match(r"^\s*Arch[eé]:", texto) and _es_hilo_principal():
                _ultimo_mensaje = texto
                impreso = _imprimir_sincronizado(texto, args, kwargs)
                if not impreso:
                    _print_original(*args, **kwargs)
                    impreso = True
                    if activa():
                        decir(texto)
                return
    except Exception:
        pass   # la voz nunca debe romper una respuesta
    if not impreso:
        _print_original(*args, **kwargs)


def _input_con_voz(prompt=""):
    global _ultimo_mensaje
    try:
        if isinstance(prompt, str) and re.match(r"^\s*Arch[eé]:", prompt) and _es_hilo_principal():
            pregunta = prompt.split("\nT", 1)[0]
            _ultimo_mensaje = pregunta
            if activa():
                decir(pregunta)
    except Exception:
        pass
    return _input_original(prompt)


def instalar_en_consola():
    """Activa la lectura en voz alta de lo que Arché imprime. Idempotente."""
    global _instalada
    if _instalada:
        return
    builtins.print = _print_con_voz
    builtins.input = _input_con_voz
    _instalada = True


def desinstalar_de_consola():
    global _instalada
    builtins.print = _print_original
    builtins.input = _input_original
    _instalada = False


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

def _limpio(comando):
    t = re.sub(r"[¿?¡!,.;:]", " ", str(comando).lower())
    t = (t.replace("á", "a").replace("é", "e").replace("í", "i")
          .replace("ó", "o").replace("ú", "u").replace("ü", "u").replace("ñ", "n"))
    return " ".join(t.split())


def _msg(texto):
    print(f"Arché: {texto}")


def _aviso_sin_windows():
    _msg("La voz solo la sé usar en Windows (uso la voz del sistema).")


_RE_ACTIVAR = re.compile(
    r"^(?:activa(?:r)?|prende(?:r)?|pon(?:er)?|enciende|encender)\s+(?:la\s+|mi\s+)?voz$|"
    r"^voz\s+(?:on|activada)$|^(?:quiero\s+que\s+)?(?:hablame|habla|hables|puedes\s+hablar|empieza\s+a\s+hablar)$|"
    r"^habla\s+(?:conmigo|en\s+voz\s+alta)$|^(?:ya\s+)?puedes\s+hablar$")
_RE_DESACTIVAR = re.compile(
    r"^(?:desactiva(?:r)?|apaga(?:r)?|quita(?:r)?)\s+(?:la\s+|mi\s+)?voz$|^voz\s+(?:off|desactivada)$|"
    r"^(?:no\s+hables|ya\s+no\s+hables|deja\s+de\s+hablar\s+siempre|modo\s+silencioso|hablame\s+solo\s+en\s+texto)$")
_RE_CALLAR = re.compile(r"^(?:calla|callate|silencio|para|basta|ya\s+callate|deja\s+de\s+hablar|"
                        r"cierra\s+la\s+boca|ya\s+entendi)$")
_RE_REPETIR = re.compile(r"^(?:repite|repiteme)(?:\s+(?:eso|lo\s+ultimo|la\s+ultima\s+respuesta|otra\s+vez|lo\s+que\s+dijiste))?$|"
                         r"^(?:que\s+dijiste|di\s+eso\s+otra\s+vez|lee\s+eso|leeme\s+eso|lee\s+en\s+voz\s+alta)$")
_RE_PROBAR = re.compile(r"^(?:prueba|probar|testea|test)\s+(?:la\s+)?voz$|^di\s+hola$|^como\s+suena\s+tu\s+voz$")
_RE_VOCES = re.compile(r"^(?:que|cuales|mis|ver|lista(?:r)?\s+(?:de\s+)?)\s*voces(?:\s+hay|\s+tengo|\s+instaladas)?$|"
                       r"^voces(?:\s+instaladas)?$|^(?:lista|listar)\s+voces$")
_RE_USAR_VOZ = re.compile(r"^(?:usa|pon|cambia\s+a|elige|quiero)\s+(?:la\s+)?voz\s+(?:de\s+)?(.+)$")
_RE_RAPIDO = re.compile(r"^habla\s+mas\s+(rapido|deprisa|lento|despacio)$|^(?:mas)\s+(rapido|lento|despacio)\s+(?:por\s+favor)?$")
_RE_VELOCIDAD = re.compile(r"^(?:velocidad\s+de\s+(?:la\s+)?voz|velocidad\s+de\s+habla)\s+(?:a\s+|en\s+)?(-?\d+)$")
_RE_MOTOR = re.compile(
    r"^(?:usa|pon|cambia\s+a|quiero|activa)\s+(?:la\s+)?voz\s+(natural|neuronal|online|del\s+sistema|de\s+windows|"
    r"robotica|offline|sin\s+internet)$|^voz\s+(natural|neuronal|del\s+sistema)$")
_RE_TONO = re.compile(r"^(?:voz|habla)\s+mas\s+(aguda|grave|fina|gruesa|delgada|profunda)$|"
                      r"^(?:tono|agudo)\s+de\s+(?:la\s+)?voz\s+(?:a\s+|en\s+)?(-?\d+)$")
_RE_VOLUMEN = re.compile(r"^volumen\s+de\s+(?:la\s+)?voz\s+(?:a\s+|en\s+|al\s+)?(\d{1,3})(?:\s*%)?$|"
                         r"^(?:voz|habla)\s+mas\s+(fuerte|suave|bajito|bajo)$")
_RE_SINCRO = re.compile(r"^(?:sincroniza(?:r)?|habla)\s+(?:la\s+voz\s+)?(?:junto|a\s+la\s+vez|al\s+mismo\s+tiempo)(?:\s+(?:con|que)\s+(?:el\s+)?texto)?$|"
                        r"^(?:sincroniza(?:r)?\s+la\s+voz(?:\s+con\s+el\s+texto)?|voz\s+sincronizada)$")
_RE_NO_SINCRO = re.compile(r"^(?:no\s+sincronices(?:\s+la\s+voz)?|voz\s+sin\s+sincronizar|"
                           r"habla\s+(?:despues|luego)\s+del\s+texto|desincroniza\s+la\s+voz)$")
_RE_LECTURA = re.compile(r"^(?:lectura|voz)\s+(corta|completa|resumida|breve|larga)$|"
                         r"^lee\s+(?:solo\s+)?(?:la\s+primera\s+frase|lo\s+principal|un\s+resumen)$|"
                         r"^lee\s+(?:todo|completo|las\s+respuestas\s+completas)$")
_RE_RESET = re.compile(r"^(?:restablece|resetea|reinicia|restaura)\s+(?:la\s+)?voz$|^voz\s+por\s+defecto$|"
                       r"^deja\s+la\s+voz\s+como\s+estaba$")
_RE_ONLINE = re.compile(r"^(?:voces\s+online|todas\s+las\s+voces(?:\s+online|\s+naturales)?|"
                        r"que\s+voces\s+online\s+hay|lista\s+completa\s+de\s+voces)$")
_RE_ESTADO = re.compile(r"^(?:estado\s+de\s+(?:la\s+)?voz|estas\s+hablando|tienes\s+voz)$")


def interpretar(comando):
    """(intencion, argumento) o None. Sin efectos: solo entiende la frase."""
    t = _limpio(comando)
    if not t:
        return None
    if _RE_DESACTIVAR.match(t):
        return ("desactivar_voz", None)
    if _RE_ACTIVAR.match(t):
        return ("activar_voz", None)
    if _RE_CALLAR.match(t):
        return ("callar", None)
    if _RE_REPETIR.match(t):
        return ("repetir", None)
    if _RE_PROBAR.match(t):
        return ("probar_voz", None)
    if _RE_ONLINE.match(t):
        return ("voces_online", None)
    if _RE_VOCES.match(t):
        return ("listar_voces", None)
    if _RE_RESET.match(t):
        return ("restablecer_voz", None)
    if _RE_NO_SINCRO.match(t):
        return ("sincronia_voz", False)
    if _RE_SINCRO.match(t):
        return ("sincronia_voz", True)
    m = _RE_LECTURA.match(t)
    if m:
        corta = (m.group(1) in ("corta", "resumida", "breve")) if m.group(1) else \
            any(p in t for p in ("primera", "principal", "resumen"))
        return ("lectura_voz", "corta" if corta else "completa")
    m = _RE_TONO.match(t)
    if m:
        if m.group(1):
            return ("tono_voz", "+1" if m.group(1) in ("aguda", "fina", "delgada") else "-1")
        return ("tono_voz", int(m.group(2)))
    m = _RE_VOLUMEN.match(t)
    if m:
        if m.group(1) is not None:
            return ("volumen_voz", int(m.group(1)))
        return ("volumen_voz", "+15" if m.group(2) == "fuerte" else "-15")
    m = _RE_VELOCIDAD.match(t)
    if m:
        return ("velocidad_voz", int(m.group(1)))
    m = _RE_RAPIDO.match(t)
    if m:
        palabra = m.group(1) or m.group(2)
        return ("velocidad_voz", "+2" if palabra in ("rapido", "deprisa") else "-2")
    if _RE_ESTADO.match(t):
        return ("estado_voz", None)
    m = _RE_MOTOR.match(t)
    if m:
        palabra = m.group(1) or m.group(2)
        return ("motor_voz", "natural" if palabra in ("natural", "neuronal", "online") else "sistema")
    m = _RE_USAR_VOZ.match(t)
    if m:
        return ("elegir_voz", m.group(1).strip())
    return None


def buscar_voz_natural(texto):
    """'gonzalo', 'mexicana', 'de hombre', 'es-AR-ElenaNeural'... -> nombre completo o None."""
    crudo = str(texto or "").strip()
    m = re.search(r"\b([a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural)\b", crudo)
    if m:
        return m.group(1)
    palabras = _limpio(crudo).split()
    for p in palabras:
        if p in VOCES_NATURALES:
            return VOCES_NATURALES[p]
        if p in TODAS_LAS_VOCES:
            return TODAS_LAS_VOCES[p]
        if p.endswith("neural") and p[:-6] in TODAS_LAS_VOCES:      # "sofianeural"
            return TODAS_LAS_VOCES[p[:-6]]
    pais = next((_PAISES_SINONIMOS.get(p, p) for p in palabras
                 if _PAISES_SINONIMOS.get(p, p) in VOCES_POR_PAIS), None)
    quiere_hombre = any(p in _HOMBRE for p in palabras)
    quiere_mujer = any(p in _MUJER for p in palabras)
    if pais is None and not (quiere_hombre or quiere_mujer):
        return None
    if pais is None:                      # solo dijo hombre/mujer: mantiene el pais actual
        actual = next((c for c, (f, h) in VOCES_POR_PAIS.items()
                       if voz_natural() in (TODAS_LAS_VOCES.get(f), TODAS_LAS_VOCES.get(h))), "colombiana")
        pais = actual
    mujer, hombre = VOCES_POR_PAIS[pais]
    return TODAS_LAS_VOCES[hombre if quiere_hombre and not quiere_mujer else mujer]


def listar_voces_online():
    """Todas las voces en español de Edge (necesita internet). [] si no se pudo."""
    try:
        import asyncio
        import edge_tts
        voces = asyncio.run(edge_tts.list_voices())
        return sorted(v["ShortName"] for v in voces if str(v.get("Locale", "")).lower().startswith("es-"))
    except Exception:
        return []


def fijar_tono(valor):
    valor = max(TONO_MIN, min(TONO_MAX, int(valor)))
    configuracion.cambiar("voz_tono", valor)
    calla()
    return valor


def fijar_volumen(valor):
    valor = max(0, min(100, int(valor)))
    configuracion.cambiar("voz_volumen", valor)
    calla()
    return valor


def restablecer():
    for clave in ("voz_velocidad", "voz_tono", "voz_volumen", "voz_natural", "voz_nombre",
                  "voz_sincronizada", "voz_lectura"):
        configuracion.cambiar(clave, None)
    calla()


def manejar(comando):
    """Ejecuta la orden de voz. Devuelve (intencion, contenido) o None si la
    frase no es de voz (todo sigue su camino normal)."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, arg = cual

    if intencion in ("activar_voz", "probar_voz", "elegir_voz", "velocidad_voz", "listar_voces",
                     "repetir", "motor_voz", "tono_voz", "volumen_voz") and not ES_WINDOWS:
        _aviso_sin_windows()
        return (intencion, arg)

    if intencion == "activar_voz":
        activar()
        if motor() == "natural":
            if not edge_tts_instalado():
                _msg("Listo, ya hablo. Para la voz natural me falta la librería: instálala con "
                     "'pip install edge-tts' (mientras tanto uso la voz de Windows).")
            else:
                _msg("Listo, ya hablo con voz natural. Dime 'calla' si quieres que pare, "
                     "o 'desactiva la voz' para dejarme solo en texto.")
            return (intencion, arg)
        voces = voces_instaladas()
        if voces and not any(i.lower().startswith("es") for _, i in voces):
            _msg("Listo, ya hablo. Ojo: tu Windows no tiene voz en español, así que sonaré con acento. "
                 "Puedes agregarla en Configuración > Hora e idioma > Voz > Agregar voces.")
        else:
            _msg("Listo, ya hablo. Dime 'calla' si quieres que pare, o 'desactiva la voz' para dejarme solo en texto.")
    elif intencion == "desactivar_voz":
        desactivar()
        _msg("Listo, vuelvo a responder solo en texto.")
    elif intencion == "callar":
        calla()
        if not activa():
            _msg("No estoy hablando ahora; si quieres que lo haga, dime 'activa la voz'.")
    elif intencion == "repetir":
        previo = _ultimo_mensaje
        if not previo:
            _msg("Todavía no he dicho nada que repetir.")
        else:
            decir(previo, forzar=True)
    elif intencion == "probar_voz":
        decir("Hola, soy Arché. Así es como sueno.", forzar=True)
        _msg("Hola, soy Arché. Así es como sueno.")
    elif intencion == "motor_voz":
        fijar_motor(arg)
        activar()
        if arg == "natural":
            extra = "" if edge_tts_instalado() else " (falta 'pip install edge-tts'; mientras tanto suena la de Windows)"
            _msg("Listo, hablo con la voz natural, que necesita internet." + extra)
        else:
            _msg("Listo, hablo con la voz de Windows, que no necesita internet.")
        decir("Así suena ahora.", forzar=True)
    elif intencion == "voces_online":
        todas = listar_voces_online()
        if not todas:
            _msg("No pude traer la lista (necesito internet y la librería edge-tts).")
        else:
            _msg("Voces en español disponibles (usa 'usa la voz <nombre completo>'):")
            for v in todas:
                print(f"  • {v}{'  <- la que uso' if v == voz_natural() else ''}")
    elif intencion == "listar_voces" and motor() == "natural":
        _msg("Voces naturales (usa 'usa la voz <nombre>'):")
        for corto, completo in VOCES_NATURALES.items():
            marca = "  <- la que uso" if completo == voz_natural() else ""
            print(f"  • {corto} ({completo}){marca}")
        _msg("Tengo más: dime 'voces online' para ver todas las de español, o usa un país "
             "('la voz mexicana') o 'de hombre' / 'de mujer'.")
    elif intencion == "listar_voces":
        voces = voces_instaladas()
        if not voces:
            _msg("No pude leer las voces de Windows.")
        else:
            _msg("Estas son las voces que tienes (usa 'usa la voz <nombre>'):")
            for nombre, idioma in voces:
                marca = "  <- la que uso" if nombre.lower() == nombre_de_voz().lower() else ""
                print(f"  • {nombre} ({idioma}){marca}")
    elif intencion == "elegir_voz" and motor() == "natural":
        completo = buscar_voz_natural(arg)
        if completo is None:
            _msg(f"No conozco una voz natural llamada '{arg}'. Prueba con un nombre (gonzalo, dalia...), "
                 "un país ('la voz mexicana'), 'de hombre' o 'de mujer'; o dime 'que voces hay'.")
        else:
            configuracion.cambiar("voz_natural", completo)
            calla()
            activar()
            _msg(f"Listo, ahora hablo con la voz {completo}.")
            decir("Así suena esta voz.", forzar=True)
    elif intencion == "elegir_voz":
        voces = voces_instaladas()
        buscado = _limpio(arg)
        elegida = next((n for n, _ in voces if buscado and buscado in _limpio(n)), None)
        if elegida is None:
            _msg(f"No encontré una voz que se llame '{arg}'. Dime 'que voces hay' para ver cuáles tienes.")
        else:
            fijar_voz(elegida)
            activar()
            _msg(f"Listo, ahora hablo con la voz {elegida}.")
            decir("Así suena esta voz.", forzar=True)
    elif intencion == "tono_voz":
        nuevo = fijar_tono(tono() + int(arg) if isinstance(arg, str) else arg)
        _msg(f"Tono de la voz: {nuevo} (de {TONO_MIN} a {TONO_MAX}; negativo más grave, positivo más agudo)."
             + ("" if motor() == "natural" else " Ojo: el tono solo cambia con la voz natural."))
        decir("Así suena ahora.", forzar=True)
    elif intencion == "volumen_voz":
        nuevo = fijar_volumen(volumen() + int(arg) if isinstance(arg, str) else arg)
        _msg(f"Volumen de la voz: {nuevo} de 100 (el volumen general de tu PC no cambia).")
        decir("Así suena ahora.", forzar=True)
    elif intencion == "sincronia_voz":
        configuracion.cambiar("voz_sincronizada", bool(arg))
        if arg:
            _msg("Listo: mi texto saldrá justo cuando empiece a sonar la voz (con la voz natural).")
        else:
            _msg("Listo: el texto sale de una vez y la voz llega cuando esté lista.")
    elif intencion == "lectura_voz":
        configuracion.cambiar("voz_lectura", arg)
        _msg("Listo, leeré solo la primera frase de cada respuesta." if arg == "corta"
             else "Listo, leeré las respuestas completas (hasta donde se pueda).")
    elif intencion == "restablecer_voz":
        restablecer()
        _msg("Listo, dejé la voz como venía: velocidad, tono, volumen y voz por defecto.")
    elif intencion == "velocidad_voz":
        actual = velocidad()
        if isinstance(arg, str):
            nuevo = actual + int(arg)
        else:
            nuevo = arg
        nuevo = fijar_velocidad(nuevo)
        _msg(f"Velocidad de la voz: {nuevo} (de {VELOCIDAD_MIN} a {VELOCIDAD_MAX}, 0 es la normal).")
        decir("Así suena ahora.", forzar=True)
    elif intencion == "estado_voz":
        if motor() == "natural":
            _msg(f"La voz está {'activada' if activa() else 'desactivada'}. Motor natural (internet), "
                 f"voz {voz_natural()}, velocidad {velocidad()}, tono {tono()}, volumen {volumen()}, "
                 f"lectura {lectura()}, {'sincronizada con el texto' if sincronizada() else 'sin sincronizar'}"
                 f"{'' if edge_tts_instalado() else '. Falta pip install edge-tts: uso la voz de Windows'}.")
        else:
            _msg(f"La voz está {'activada' if activa() else 'desactivada'}. Motor del sistema, velocidad {velocidad()}. "
                 f"Voz: {nombre_de_voz() or 'la primera en español que tenga Windows'}.")
    return (intencion, arg)