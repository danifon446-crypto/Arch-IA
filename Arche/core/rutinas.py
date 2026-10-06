"""
rutinas.py
----------
Ubicacion: Arche/core/rutinas.py

Rutinas / modos: tu mismo defines una serie de ordenes con un nombre y despues
las lanzas con una sola frase.

  crea la rutina estudio: abre chrome, sube el brillo, silencia el sonido
  modo estudio                      (o: ejecuta la rutina estudio)
  mis rutinas
  que hace la rutina estudio
  agrega a la rutina estudio: pon el volumen al 20
  borra la rutina estudio

Cada paso es CUALQUIER orden que Arché ya entiende (abrir, buscar, volumen,
alarmas, voz, apagar...). Una rutina no ejecuta nada por si sola: main.py
mete sus pasos en la misma cola que "abre chrome y luego ..." (con una pausa
de 2 segundos entre cada uno), asi que cada paso pasa por las mismas
confirmaciones de siempre (apagar el PC, cerrar programas...).

Se guardan en Database/rutinas.json.
"""

import json
import os
import re

from core.rutas import DATABASE

ARCHIVO = os.path.join(DATABASE, "rutinas.json")
MAX_PASOS = 15
PAUSA_ENTRE_PASOS = "espera 2"

# palabras que NO pueden ser el nombre de una rutina ("modo natural on" es un
# comando de Arché, no una rutina)
NOMBRES_RESERVADOS = {"natural", "natural on", "natural off", "voz", "nube", "ollama", "auto"}


def _sin_tildes(texto):
    t = str(texto).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


def _clave(nombre):
    return " ".join(re.sub(r"[¿?¡!,.;:]", " ", _sin_tildes(nombre)).split())


def _msg(texto):
    print(f"Arché: {texto}")


# ------------------------------------------------------------------
# Almacen
# ------------------------------------------------------------------

# Rutinas de ejemplo: se crean UNA sola vez, cuando todavia no existe el archivo.
# Despues son del usuario (las puede cambiar, ampliar o borrar).
RUTINAS_DE_EJEMPLO = {
    "estudio": ["silencia el sonido", "pon el brillo al 70"],
    "trabajo": ["pon el volumen al 20", "pon el brillo al 70"],
    "cine": ["pon el brillo al 30", "pon el volumen al 60", "muestra el escritorio"],
    "descanso": ["pausa la musica", "pon el brillo al 25"],
}


def _cargar():
    if not os.path.exists(ARCHIVO):
        ejemplo = {k: {"nombre": k, "pasos": list(v)} for k, v in RUTINAS_DE_EJEMPLO.items()}
        try:
            _guardar(ejemplo)
        except OSError:
            pass
        return ejemplo
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            datos = json.load(f)
            return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(datos):
    os.makedirs(DATABASE, exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def listar():
    """{clave: {"nombre": ..., "pasos": [...]}}"""
    return _cargar()


def obtener(nombre):
    return _cargar().get(_clave(nombre))


def guardar(nombre, pasos):
    datos = _cargar()
    datos[_clave(nombre)] = {"nombre": nombre.strip(), "pasos": list(pasos)}
    _guardar(datos)


def borrar(nombre):
    datos = _cargar()
    if _clave(nombre) in datos:
        del datos[_clave(nombre)]
        _guardar(datos)
        return True
    return False


# ------------------------------------------------------------------
# Pasos
# ------------------------------------------------------------------

_CONECTORES = re.compile(r"\s*(?:;|,|\by\s+luego\b|\by\s+despues\b|\bluego\b|\bdespues\b|\bentonces\b)\s*", re.I)


def _verbos():
    from core import acciones_pc
    return acciones_pc.VERBOS_DE_PASO


def dividir_pasos(texto):
    """'abre chrome, sube el brillo y silencia' -> ['abre chrome', 'sube el brillo', 'silencia'].
    Un ' y ' solo separa si lo que sigue empieza como una orden (asi 'busca gatos y perros' no se parte)."""
    verbos = _verbos()
    pasos = []
    for trozo in _CONECTORES.split(texto or ""):
        trozo = trozo.strip(" .")
        if not trozo:
            continue
        actual = []
        for palabra_y in re.split(r"\s+y\s+", trozo):
            primera = _sin_tildes(palabra_y).split(" ")[0] if palabra_y.strip() else ""
            if actual and primera in verbos:
                pasos.append(" y ".join(actual))
                actual = [palabra_y]
            else:
                actual.append(palabra_y)
        if actual:
            pasos.append(" y ".join(actual))
    return [p.strip() for p in pasos if p.strip()]


def _es_anidada(paso):
    t = _clave(paso)
    return bool(re.match(r"^(?:ejecuta\s+|activa\s+|inicia\s+|lanza\s+|corre\s+)?(?:la\s+)?(?:rutina|modo)\b", t))


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

_NOMBRE = r"([a-z0-9][a-z0-9 ]{0,30}?)"
_R_CREAR = re.compile(
    rf"^(?:crea(?:r)?|guarda(?:r)?|define|arma(?:r)?|haz)\s+(?:la\s+|una\s+|el\s+|un\s+)?(?:rutina|modo)\s+(?:de\s+|llamad[oa]\s+)?{_NOMBRE}"
    r"(?:\s*(?::|=>|->|=)\s*|\s+(?:con|que\s+(?:haga|abra|haga)|para\s+que)\s+)(.+)$")
_R_CREAR_VACIA = re.compile(
    rf"^(?:crea(?:r)?|define|arma(?:r)?|haz|nueva)\s+(?:la\s+|una\s+|el\s+|un\s+)?(?:rutina|modo)\s+(?:de\s+|llamad[oa]\s+)?{_NOMBRE}$")
_R_EJECUTAR = re.compile(
    rf"^(?:(?:ejecuta(?:r)?|corre|lanza|inicia(?:r)?|activa(?:r)?|pon(?:er)?|haz)\s+)?(?:la\s+|el\s+)?(?:rutina|modo)\s+(?:de\s+)?{_NOMBRE}$")
_R_VER_TODAS = re.compile(r"^(?:mis|ver|muestra(?:me)?|lista(?:r)?|que)\s+(?:mis\s+)?(?:rutinas|modos)(?:\s+tengo|\s+hay)?$|^lista\s+de\s+rutinas$")
_R_VER_UNA = re.compile(rf"^(?:que\s+hace|ver|muestra(?:me)?|dime)\s+(?:la\s+|el\s+)?(?:rutina|modo)\s+(?:de\s+)?{_NOMBRE}$")
_R_BORRAR = re.compile(rf"^(?:borra(?:r)?|elimina(?:r)?|quita(?:r)?|olvida)\s+(?:la\s+|el\s+)?(?:rutina|modo)\s+(?:de\s+)?{_NOMBRE}$")
_R_AGREGAR = re.compile(rf"^(?:agrega(?:r)?|anade|suma|pon)\s+(?:a|en)\s+(?:la\s+|el\s+)?(?:rutina|modo)\s+(?:de\s+)?{_NOMBRE}\s*(?::|=>|->)\s*(.+)$")


def interpretar(comando):
    """(intencion, datos) o None. No toca nada."""
    texto = " ".join(str(comando).split())
    t = _clave(texto)
    if not t:
        return None
    # para crear/agregar se conserva el texto original de los pasos (mayusculas, tildes)
    sin_t = _sin_tildes(texto)
    for rx, que in ((_R_AGREGAR, "agregar_paso_rutina"), (_R_CREAR, "crear_rutina")):
        m = rx.match(sin_t.strip())
        if m:
            inicio_pasos = m.start(2)
            return (que, {"nombre": m.group(1).strip(), "pasos": dividir_pasos(texto.strip()[inicio_pasos:])})
    if _R_VER_TODAS.match(t):
        return ("ver_rutinas", None)
    m = _R_VER_UNA.match(t)
    if m:
        return ("ver_rutina", {"nombre": m.group(1).strip()})
    m = _R_BORRAR.match(t)
    if m:
        return ("borrar_rutina", {"nombre": m.group(1).strip()})
    m = _R_CREAR_VACIA.match(t)
    if m:
        return ("crear_rutina", {"nombre": m.group(1).strip(), "pasos": None})
    m = _R_EJECUTAR.match(t)
    if m:
        nombre = m.group(1).strip()
        if obtener(nombre) is not None:
            return ("ejecutar_rutina", {"nombre": nombre})
        # "modo natural on", "modo nube"... no son rutinas: que sigan su camino
        if nombre not in NOMBRES_RESERVADOS and re.match(r"^(?:ejecuta|corre|lanza|inicia|activa|pon|haz)\b", t):
            return ("rutina_inexistente", {"nombre": nombre})
    return None


def _preguntar_pasos():
    """Modo conversacion: un paso por linea, vacio para terminar."""
    _msg("Dime los pasos, uno por línea (cualquier orden que yo entienda). Línea vacía para terminar.")
    pasos = []
    while len(pasos) < MAX_PASOS:
        linea = input(f"  paso {len(pasos) + 1}: ").strip()
        if not linea:
            break
        pasos.append(linea)
    return pasos


def manejar(comando):
    """Gestiona rutinas. Devuelve (intencion, contenido) o None.
    Para 'ejecutar_rutina' el contenido es {"nombre", "pasos"}: main.py los encola."""
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, datos = cual

    if intencion == "crear_rutina":
        nombre = datos["nombre"]
        if _clave(nombre) in NOMBRES_RESERVADOS:
            _msg(f"'{nombre}' es un comando mío, elige otro nombre para la rutina.")
            return (intencion, None)
        pasos = datos["pasos"]
        if pasos is None:
            pasos = _preguntar_pasos()
        if not pasos:
            _msg("No me diste pasos, así que no creé nada. Ejemplo: 'crea la rutina estudio: abre chrome, sube el brillo'.")
            return (intencion, None)
        anidados = [p for p in pasos if _es_anidada(p)]
        if anidados:
            _msg("Una rutina no puede llamar a otra rutina (por seguridad, para que no se enrede). "
                 f"Quita este paso: '{anidados[0]}'.")
            return (intencion, None)
        if len(pasos) > MAX_PASOS:
            _msg(f"Máximo {MAX_PASOS} pasos por rutina; me diste {len(pasos)}.")
            return (intencion, None)
        existia = obtener(nombre) is not None
        guardar(nombre, pasos)
        lista = "\n".join(f"  {i}. {p}" for i, p in enumerate(pasos, start=1))
        _msg(f"{'Actualicé' if existia else 'Creé'} la rutina '{nombre}' con {len(pasos)} paso(s):\n{lista}\n"
             f"Lánzala con 'modo {nombre}'.")
        return (intencion, nombre)

    if intencion == "agregar_paso_rutina":
        r = obtener(datos["nombre"])
        if r is None:
            _msg(f"No tengo una rutina llamada '{datos['nombre']}'. Mira 'mis rutinas'.")
            return (intencion, None)
        nuevos = datos["pasos"]
        if any(_es_anidada(p) for p in nuevos):
            _msg("Una rutina no puede llamar a otra rutina.")
            return (intencion, None)
        if len(r["pasos"]) + len(nuevos) > MAX_PASOS:
            _msg(f"Esa rutina ya casi llena: máximo {MAX_PASOS} pasos.")
            return (intencion, None)
        guardar(r["nombre"], r["pasos"] + nuevos)
        _msg(f"Agregué {len(nuevos)} paso(s) a '{r['nombre']}'. Ahora tiene {len(r['pasos']) + len(nuevos)}.")
        return (intencion, r["nombre"])

    if intencion == "ver_rutinas":
        todas = listar()
        if not todas:
            _msg("Aún no tienes rutinas. Crea una así: 'crea la rutina estudio: abre chrome, sube el brillo, silencia el sonido'.")
        else:
            lineas = [f"  • {r['nombre']} ({len(r['pasos'])} paso{'s' if len(r['pasos']) != 1 else ''})" for r in todas.values()]
            _msg("Tus rutinas (lánzalas con 'modo <nombre>'):\n" + "\n".join(lineas))
        return (intencion, None)

    if intencion == "ver_rutina":
        r = obtener(datos["nombre"])
        if r is None:
            _msg(f"No tengo una rutina llamada '{datos['nombre']}'.")
        else:
            lista = "\n".join(f"  {i}. {p}" for i, p in enumerate(r["pasos"], start=1))
            _msg(f"La rutina '{r['nombre']}' hace:\n{lista}")
        return (intencion, None)

    if intencion == "borrar_rutina":
        if borrar(datos["nombre"]):
            _msg(f"Listo, borré la rutina '{datos['nombre']}'.")
        else:
            _msg(f"No tengo una rutina llamada '{datos['nombre']}'.")
        return (intencion, None)

    if intencion == "rutina_inexistente":
        _msg(f"No tengo una rutina llamada '{datos['nombre']}'. Mira 'mis rutinas' o créala con "
             f"'crea la rutina {datos['nombre']}: paso uno, paso dos'.")
        return (intencion, None)

    if intencion == "ejecutar_rutina":
        r = obtener(datos["nombre"])
        _msg(f"Iniciando la rutina '{r['nombre']}' ({len(r['pasos'])} pasos).")
        return (intencion, {"nombre": r["nombre"], "pasos": list(r["pasos"])})

    return (intencion, datos)


def pasos_con_pausas(pasos):
    """Lista lista para la cola de main.py: paso, pausa, paso, pausa, paso."""
    salida = []
    for i, paso in enumerate(pasos):
        if i:
            salida.append(PAUSA_ENTRE_PASOS)
        salida.append(paso)
    return salida