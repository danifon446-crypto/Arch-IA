"""
interfaz
--------
Ubicacion: Arche/core/interfaz/

La cara de Arché: consola con Rich, ventana grafica (esfera, fondos, mascota,
controles y ajustes), modo TV/ambiente y control desde el celular.
main.py solo llama a manejar(comando); aqui se decide si la frase es suya.
"""

import re
import threading
import unicodedata

from . import ajustes, consola, datos, en_vivo, entrada, fondos, lenguaje, micro, perfiles, remoto, tema, ventana

_ESPERA_ARRANQUE = 2.5     # segundos: deja que Arché termine de cargar sus modulos antes de abrir la ventana


def automatica():
    """True si la ventana debe abrirse sola cuando arranca Arché (por defecto, si)."""
    return bool(ajustes.obtener("automatica"))


def fijar_automatica(valor):
    ajustes.fijar("automatica", bool(valor))


def entrada_en_ventana():
    """True si se puede escribir tambien desde la ventana (por defecto, si)."""
    return bool(ajustes.obtener("entrada_ventana"))


def _arranque_automatico():
    if ventana.disponible() and automatica() and not ventana.abierta():
        ventana.abrir(tv=False, foco=False)     # sin robar el teclado: sigues escribiendo en la consola
    if ajustes.obtener("celular"):
        remoto.iniciar()
    if ajustes.obtener("escucha"):
        micro.iniciar()


def _limpio(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¿?¡!,.;:]", " ", t)
    return " ".join(t.split())


def _msg(texto):
    print(f"Arché: {texto}")


_TEMAS = {"arche": "arche", "neon": "neon", "ambar": "ambar", "amber": "ambar", "esmeralda": "esmeralda",
          "verde": "esmeralda"}
_PERSONAJES = ("chispa", "robot", "gato")
_R_NOMBRE = re.compile(r"(?i)^(?:nombre de la mascota|llama a la mascota|ponle de nombre a la mascota|"
                       r"tu nombre es|te llamas|ponle a la mascota)\s+(.{1,20})$")


def interpretar(comando):
    c = _limpio(comando)
    m = _R_NOMBRE.match(str(comando).strip())
    if m:
        return ("mascota_nombre", m.group(1).strip().strip("\"'").title())
    # --- ventana ---
    if re.match(r"^(activa|enciende|pon|deja)( la| mi)? (interfaz|ventana)( de arche)? (automatica|siempre|al iniciar|al arrancar)$", c):
        return ("auto_si", None)
    if re.match(r"^(desactiva|apaga|quita|no abras)( la| mi)? (interfaz|ventana)( de arche)? (automatica|siempre|al iniciar|al arrancar)$", c):
        return ("auto_no", None)
    if re.match(r"^(cierra|cerrar|quita|oculta)( la)? (interfaz|ventana)( de arche)?$", c):
        return ("cerrar_interfaz", None)
    if re.match(r"^(sal|salir|salte) del modo tv$|^(cierra|quita|apaga) (el )?modo tv$", c):
        return ("salir_modo_tv", None)
    if re.match(r"^(activa|abre|pon|enciende|ver en|muestra en)( el)?( modo)? (tv|television|pantalla grande)( modo)?$|^modo tv$", c):
        return ("modo_tv", None)
    if re.match(r"^(abre|abrir|muestra|mostrar|enciende|activa|lanza)( la| mi)? (interfaz|ventana)( grafica| de arche)?$|^interfaz$", c):
        return ("abrir_interfaz", None)
    if re.match(r"^(ajustes de la interfaz|personalizar interfaz|personaliza la interfaz|ajustes visuales|"
                r"personalizar la ventana|personaliza la ventana)$", c):
        return ("ir_ajustes", None)
    if re.match(r"^(modo )?ambiente$|^(activa|pon|enciende)( el)? modo ambiente$", c):
        return ("ambiente_si", None)
    if re.match(r"^(sal del|quita( el)?|apaga( el)?) modo ambiente$", c):
        return ("ambiente_no", None)
    if re.match(r"^(activa|pon) (el )?ambiente automatico$", c):
        return ("ambiente_auto_si", None)
    if re.match(r"^(desactiva|quita|apaga) (el )?ambiente automatico$", c):
        return ("ambiente_auto_no", None)
    # --- aspecto ---
    m = re.match(r"^(?:(?:cambia|pon|usa)(?: el)? )?(?:tema|colores|paleta)(?: a| de)? (arche|neon|ambar|amber|esmeralda|verde)$", c)
    if m:
        return ("tema", _TEMAS[m.group(1)])
    if re.match(r"^(siguiente|otro|cambia el) (tema|color|colores)$|^cambia( los)? colores$", c):
        return ("tema_sig", None)
    if re.match(r"^(?:pon|usa|quiero|cambia a)(?: la| el)? (esfera|bola|circulo|orbe)$|^estilo(?: de voz)? (esfera|circulo)$", c):
        return ("estilo", "esfera")
    if re.match(r"^(?:pon|usa|quiero|cambia a)(?: las)? (ondas|lineas|barras)$|^estilo(?: de voz)? (ondas|lineas)$", c):
        return ("estilo", "ondas")
    if re.match(r"^(fondo siguiente|siguiente fondo|cambia( el)? fondo|otro fondo)$", c):
        return ("fondo_sig", None)
    if re.match(r"^(fondo anterior|fondo previo)$", c):
        return ("fondo_ant", None)
    if re.match(r"^(quita|sin|apaga|borra)( el)? fondo$|^fondo ninguno$", c):
        return ("fondo_ninguno", None)
    if re.match(r"^(que fondos (hay|tengo)|lista de fondos|mis fondos|fondos)$", c):
        return ("fondo_lista", None)
    m = re.match(r"^(?:pon|usa|cambia)(?: de)? fondo (.+)$|^fondo (.+)$", c)
    if m:
        return ("fondo_poner", (m.group(1) or m.group(2)).strip())
    m = re.match(r"^oscuridad(?: del fondo)? (\d{1,2})$", c)
    if m:
        return ("fondo_oscuridad", int(m.group(1)))
    # --- mascota ---
    if re.match(r"^(muestra|activa|pon|enciende|quiero)( a)?( la| mi)? mascota$", c):
        return ("mascota_si", None)
    if re.match(r"^(oculta|quita|apaga|desactiva)( a)?( la| mi)? mascota$", c):
        return ("mascota_no", None)
    m = re.match(r"^(?:mascota|personaje) (chispa|robot|gato)$|^(?:pon|usa|cambia a)(?: el| la)? (?:mascota )?(chispa|robot|gato)$", c)
    if m:
        return ("personaje", m.group(1) or m.group(2))
    if re.match(r"^(activa|quiero|pon)( los)? consejos$", c):
        return ("consejos_si", None)
    if re.match(r"^(desactiva|quita|no quiero|apaga)( los)? consejos$", c):
        return ("consejos_no", None)
    if re.match(r"^(recorrido|tour|haz el recorrido|ensename la ventana|muestrame la ventana)$", c):
        return ("recorrido", None)
    if re.match(r"^(activa|pon|enciende)( los)? sonidos( de la interfaz)?$", c):
        return ("sonidos_si", None)
    if re.match(r"^(desactiva|quita|apaga)( los)? sonidos( de la interfaz)?$", c):
        return ("sonidos_no", None)
    # --- escucha y celular ---
    if re.match(r"^(activa|enciende|pon)( la)? escucha$|^escuchame$|^ya puedes escucharme$", c):
        return ("escucha_si", None)
    if re.match(r"^(desactiva|apaga|quita)( la)? escucha$|^deja de escucharme$", c):
        return ("escucha_no", None)
    if re.match(r"^(activa|enciende|pon)( el)? control (del |por |desde )?(celular|telefono|movil)$", c):
        return ("celular_si", None)
    if re.match(r"^(desactiva|apaga|quita)( el)? control (del |por |desde )?(celular|telefono|movil)$", c):
        return ("celular_no", None)
    if re.match(r"^(pin|clave)( del)?( celular)?$|^direccion del celular$", c):
        return ("celular_info", None)
    if re.match(r"^(pin|clave) nuevo$|^cambia( el)? pin$", c):
        return ("celular_pin", None)
    # --- consola ---
    if re.match(r"^(panel|paneles|mostrar panel|muestra( el)? panel|panel de arche|dashboard)$", c):
        return ("panel", None)
    if re.match(r"^(procesos|ver procesos|panel de procesos|segundo plano|en segundo plano|que haces en segundo plano|"
                r"que estas haciendo|que haces|que estas haciendo en segundo plano|tareas en segundo plano|"
                r"procesos en segundo plano|muestra( los)? procesos)$", c):
        return ("procesos", None)
    if re.match(r"^(panel de estado|muestra( el)? estado visual|estado visual)$", c):
        return ("panel_estado", None)
    if re.match(r"^(panel de aprendizaje|muestra( el)? panel de aprendizaje|progreso visual)$", c):
        return ("panel_aprendizaje", None)
    return None


_SIMPLES = {   # intencion -> (clave de ajuste, valor, mensaje)
    "mascota_si": ("mascota", True, "¡Aquí estoy! Me quedo en la ventana."),
    "mascota_no": ("mascota", False, "Vale, me escondo. Dime «muestra la mascota» cuando me quieras de vuelta."),
    "consejos_si": ("consejos", True, "Listo, te daré consejos de vez en cuando."),
    "consejos_no": ("consejos", False, "Listo, sin consejos."),
    "sonidos_si": ("sonidos", True, "Sonidos activados."),
    "sonidos_no": ("sonidos", False, "Sonidos apagados."),
    "ambiente_auto_si": ("ambiente_auto", True, "Pasaré sola al modo ambiente cuando lleves rato sin usarme."),
    "ambiente_auto_no": ("ambiente_auto", False, "Ya no pasaré sola al modo ambiente."),
}


def _buscar_fondo(consulta):
    q = _limpio(consulta)
    for f in fondos.listar():
        stem = _limpio(f.rsplit(".", 1)[0])
        if q == stem or q in stem:
            return f
    return None


def manejar(comando):
    """Devuelve (intencion, contenido) si la frase era de la interfaz, o None."""
    # Personalizar con frases normales («haz la interfaz más minimalista», «mueve el chat a la izquierda»…)
    try:
        respuesta = lenguaje.responder(comando)
    except Exception as e:
        print(f"[interfaz] la personalización por frases falló ({e}); la frase sigue su camino normal.")
        respuesta = None
    if respuesta:
        _msg(respuesta)
        return ("personalizar_interfaz", None)
    cual = interpretar(comando)
    if cual is None:
        return None
    intencion, dato = cual

    if intencion in ("abrir_interfaz", "modo_tv", "salir_modo_tv"):
        if not ventana.disponible():
            _msg("A este Python le falta Tkinter. En Windows viene incluido; en la Raspberry instala "
                 "'sudo apt install python3-tk'. Mientras tanto uso la consola: dime 'panel'.")
            return cual
        if intencion == "salir_modo_tv":
            if ventana.abierta():
                ventana.abrir(tv=False)
                _msg("Salí del modo TV.")
            else:
                _msg("El modo TV no está abierto.")
            return cual
        tv = intencion == "modo_tv"
        ventana.abrir(tv=tv)
        _msg("Listo, abrí mi pantalla en modo TV (Esc para salir)." if tv
             else "Listo, abrí mi ventana. Puedes seguir hablándome por aquí.")
    elif intencion == "auto_si":
        fijar_automatica(True)
        _msg("Listo, mi ventana se abrirá sola cada vez que arranque.")
        if ventana.disponible() and not ventana.abierta():
            ventana.abrir(tv=False)
    elif intencion == "auto_no":
        fijar_automatica(False)
        _msg("Listo, ya no abriré la ventana al arrancar. Dime 'abre la interfaz' cuando la quieras.")
    elif intencion == "cerrar_interfaz":
        _msg("Cerré la ventana." if ventana.cerrar() else "La ventana no estaba abierta.")
    elif intencion == "ir_ajustes":
        if not ventana.abierta():
            ventana.abrir(tv=False)
        ventana.ir_a_pestana("ajustes")
        _msg("Te abrí los ajustes en mi ventana.")
    elif intencion in ("ambiente_si", "ambiente_no"):
        if intencion == "ambiente_si" and not ventana.abierta():
            ventana.abrir(tv=False, foco=False)
        ok = ventana.poner_ambiente(intencion == "ambiente_si")
        _msg(("Modo ambiente: toca la pantalla o pulsa una tecla para volver." if intencion == "ambiente_si"
              else "Salí del modo ambiente.") if ok else "Necesito la ventana abierta: dime 'abre la interfaz'.")
    elif intencion == "tema":
        ajustes.fijar("tema", dato)
        _msg(f"Tema {dato} puesto.")
    elif intencion == "tema_sig":
        _msg(f"Tema {ajustes.siguiente('tema')} puesto.")
    elif intencion == "estilo":
        ajustes.fijar("estilo_voz", dato)
        _msg("Mi voz ahora se ve como una esfera." if dato == "esfera" else "Mi voz ahora se ve como ondas.")
    elif intencion in ("fondo_sig", "fondo_ant"):
        nuevo = fondos.siguiente(ajustes.obtener("fondo"), 1 if intencion == "fondo_sig" else -1)
        ajustes.fijar("fondo", nuevo)
        _msg(f"Fondo: {nuevo}." if nuevo else "Sin fondo.")
        if not fondos.listar():
            _msg("Aún no tengo fondos: copia imágenes, GIF o videos a la carpeta Database/fondos.")
    elif intencion == "fondo_ninguno":
        ajustes.fijar("fondo", "")
        _msg("Quité el fondo.")
    elif intencion == "fondo_lista":
        lista = fondos.listar()
        if lista:
            _msg("Fondos disponibles: " + ", ".join(lista) + ". Dime «pon de fondo <nombre>».")
        else:
            _msg("No hay fondos todavía: copia imágenes, GIF o videos a Database/fondos.")
    elif intencion == "fondo_poner":
        f = _buscar_fondo(dato)
        if f:
            ajustes.fijar("fondo", f)
            _msg(f"Fondo puesto: {f}.")
        else:
            _msg(f"No encuentro un fondo que se llame «{dato}». Dime «fondos» para ver la lista.")
    elif intencion == "fondo_oscuridad":
        v = ajustes.fijar("fondo_oscuridad", max(0, min(90, dato)))
        _msg(f"Oscuridad del fondo: {v}%.")
    elif intencion == "personaje":
        ajustes.fijar("mascota_personaje", dato)
        ajustes.fijar("mascota", True)
        _msg(f"Ahora soy {dato}.")
    elif intencion == "mascota_nombre":
        ajustes.fijar("mascota_nombre", dato)
        _msg(f"¡Me gusta! Ahora me llamo {dato}.")
    elif intencion == "recorrido":
        ajustes.fijar("recorrido_hecho", False)
        ajustes.fijar("mascota", True)
        if not ventana.abierta():
            ventana.abrir(tv=False)
        _msg("¡Vamos! Mírame en la ventana.")
    elif intencion in _SIMPLES:
        clave, valor, texto = _SIMPLES[intencion]
        ajustes.fijar(clave, valor)
        _msg(texto)
    elif intencion == "escucha_si":
        micro.iniciar()
        _msg("Te escucho. Di «oye asistente» y tu orden. Si falta algo del micrófono te aviso en la ventana.")
    elif intencion == "escucha_no":
        micro.detener()
        _msg("Dejé de escuchar el micrófono.")
    elif intencion == "celular_si":
        ok, msg = remoto.iniciar()
        if ok:
            _msg(f"Control por celular listo. En el celular (misma wifi) abre {msg} y usa el PIN {ajustes.obtener('celular_pin')}.")
        else:
            _msg(msg)
    elif intencion == "celular_no":
        remoto.detener()
        _msg("Control por celular apagado.")
    elif intencion == "celular_info":
        if remoto.activo():
            _msg(f"Abre {remoto.direccion()} en el celular (misma wifi). PIN: {ajustes.obtener('celular_pin')}.")
        else:
            _msg("El control por celular está apagado. Dime «activa el control del celular».")
    elif intencion == "celular_pin":
        _msg(f"PIN nuevo: {remoto.nuevo_pin()}.")
    elif intencion == "panel":
        consola.panel_completo()
    elif intencion == "procesos":
        consola.panel_procesos()
    elif intencion == "panel_estado":
        consola.panel_estado()
    elif intencion == "panel_aprendizaje":
        consola.panel_aprendizaje()
    return cual


# Ordenes, intencion detectada y avisos: se engancha antes de que carguen los demas modulos.
try:
    en_vivo.instalar()
except Exception:
    pass

# Escribir desde la ventana: input() pasa a leer de la consola Y de la ventana.
if ventana.disponible() and entrada_en_ventana():
    entrada.instalar()

# Tema guardado
try:
    if not tema.aplicar(ajustes.obtener("tema")):
        tema.aplicar("arche")
    perfiles.layout_actual()            # carga (y repara) tu perfil activo
except Exception as e:
    print(f"[interfaz] no pude cargar tu perfil de interfaz ({e}); uso el de fábrica.")

# La ventana vive con Arché: al cargar este modulo (arranque) se abre sola, un momento despues.
_t = threading.Timer(_ESPERA_ARRANQUE, _arranque_automatico)
_t.daemon = True
_t.start()
