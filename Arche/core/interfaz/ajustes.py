"""
ajustes.py
----------
Ubicacion: Arche/core/interfaz/ajustes.py

Sistema central de configuracion de la cara de Arché. Todo lo que puedes
personalizar vive aqui, guardado en core/interfaz/config.json, separado del
codigo de la ventana.

  - Cada ajuste tiene un valor por defecto (DEFAULTS) y una regla (ESQUEMA):
    un valor invalido nunca se guarda ni rompe la interfaz.
  - Si config.json esta danado se aparta como config.json.danado-<hora> y
    Arché arranca con los valores por defecto.
  - Los ajustes "visuales" (todos menos los del equipo y la sesion) forman
    parte de los perfiles, de los puntos de restauracion y del deshacer.
"""

import json
import os
import re
import threading
import time

_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
_lock = threading.RLock()

DEFAULTS = {
    # --- comportamiento general ---
    "automatica": True,          # abrir la ventana al iniciar Arché
    "entrada_ventana": True,     # escribirle desde la ventana
    "recorrido_hecho": False,
    "sonidos": False,
    "intencion_en_vivo": True,   # mostrar que entendio Arché de cada orden
    "ambiente_auto": False,      # pasar solo al modo ambiente cuando no hay actividad
    "ambiente_minutos": 5,
    "celular": False,            # pagina de control para el celular (misma red wifi)
    "celular_pin": "",
    "celular_puerto": 8766,       # 8765 es el de WhatsApp
    "escucha": False,            # escuchar con el microfono ("oye asistente")
    "perfil": "general",         # perfil de interfaz activo
    # --- apariencia ---
    "tema": "arche",             # nombre de un tema (de fabrica o creado por ti)
    "tema_horario": False,       # cambiar de tema solo segun la hora
    "tema_dia": "neon",          # tema de 7:00 a 19:00 cuando tema_horario esta activo
    "tema_noche": "arche",       # tema de 19:00 a 7:00
    "fuente": "",                # "" = la del sistema (Segoe UI)
    "fondo": "",                 # archivo dentro de Database/fondos ("" = ninguno)
    "fondo_oscuridad": 55,       # 0-90: cuanto se oscurece el fondo para que se lea
    "fondo_desenfoque": 0,       # 0-20: desenfoque del fondo (necesita Pillow)
    "fondo_movimiento": True,    # False: el video o GIF se queda quieto (ahorra recursos)
    "escena": "ninguna",         # ninguna | gradiente | particulas | ondas | rejilla | nebulosa
    "escena_intensidad": 50,
    "escena_velocidad": 100,
    "escena_brillo": 60,
    # --- efectos ---
    "efecto_sombra": 30,         # 0-100
    "efecto_borde_luminoso": 25, # 0-100
    "efecto_brillo": 60,         # 0-100 (halos de la esfera y los indicadores)
    "efecto_profundidad": False, # capas y reflejos suaves en las tarjetas
    "efecto_particulas": 0,      # 0-100: chispas alrededor de la esfera
    "efectos_simultaneos": 6,    # 1-10: tope de efectos a la vez
    "anim_velocidad": 100,       # 25-300 %
    "anim_transiciones": True,   # los paneles se deslizan al cambiar de sitio
    "reducir_movimiento": False,
    # --- identidad visual / voz ---
    "estilo_voz": "esfera",      # esfera | ondas | anillos | nucleo | geometrica
    "orbe_tamano": 100,          # 50-160 %
    "orbe_color": "",            # "" = el del tema; o un HEX
    "orbe_velocidad": 100,
    "estado_indicador": "animacion",   # animacion | icono | texto | combinado
    "estado_colores": {},        # estado -> HEX (vacio = los del tema)
    # --- mascota ---
    "mascota": True,
    "mascota_personaje": "chispa",   # chispa | robot | gato | esfera | minimal | imagen
    "mascota_nombre": "Chispa",
    "mascota_tamano": 100,       # 50-200 %
    "mascota_opacidad": 100,     # 20-100 %
    "mascota_visibilidad": "siempre",   # siempre | temporal
    "mascota_reacciones": True,  # reacciona a lo que hace Arché
    "mascota_frecuencia": "normal",     # poca | normal | mucha (consejos)
    "mascota_flotante": False,   # ventanita aparte, sobre otras apps
    "consejos": True,
    # --- conversacion ---
    "chat_vista": "clasica",     # clasica | compacta | tecnica
    "chat_tam": 11,              # 8-20
    "chat_ancho": 100,           # 40-100 % del panel
    "chat_espacio": 8,           # 0-30 px entre mensajes
    "chat_alineacion": "izquierda",    # izquierda | derecha | alternada
    "chat_color_usuario": "",
    "chat_color_arche": "",
    "chat_marcas_tiempo": False,
    "chat_historial": 10,        # 4-40 mensajes
    "chat_indicador": True,      # "Arché está pensando…"
    "chat_entrada_arriba": False,
    "chat_entrada_alto": 34,     # 24-90
    # --- sistema ---
    "sistema_estilo": "barras",  # barras | circular | numeros | compacto
    "sistema_actualizacion": 1,  # segundos entre lecturas (1-10)
    "sistema_ocultar": [],       # cpu | ram | disco | bateria | grafica
    "limite_cpu": 90,
    "limite_ram": 90,
    "limite_disco": 95,
    # --- navegacion ---
    "navegacion": "pestanas",    # pestanas | iconos | lateral | menu
    "nav_orden": [],
    "nav_ocultas": [],
    "nav_iconos_tam": 100,
    "nav_etiquetas": True,
    "favoritos": [],             # ordenes fijadas en la barra de favoritos
    "atajos_rapidos": [],        # [{"texto": "...", "orden": "..."}]
    # --- ventanas ---
    "ventana_modo": "normal",    # normal | compacta | superpuesta
    "ventana_siempre_visible": False,
    "ventana_opacidad": 100,     # 30-100
    "ventana_sin_borde": False,
    "ventana_geometria": "",     # tamaño y posicion de la ventana principal
    "flotante": False,           # esfera flotante sobre otras apps
    "flotante_contenido": "esfera",    # esfera | mascota
    "flotante_tam": 150,
    "flotante_pos": "",
    "bandeja": False,            # icono en la bandeja del sistema (necesita pystray)
    "minimizar_sin_foco": False, # minimiza la ventana al usar otra app (solo si hay esfera flotante)
    # --- orden de la pantalla (orden.py) ---
    "orden_activo": True,        # interruptor general de las ocho ideas de orden
    "orden_auto": True,          # paneles «solo si hay algo»: que aparezcan y se vayan solos
    "orden_compactar": True,     # cerrar los huecos que dejan los paneles que se van o se pliegan
    "orden_rellenar": True,      # que el panel de abajo use el espacio que quedo libre
    "orden_plegar_boton": "al_pasar",   # al_pasar | siempre | nunca: boton «–» para plegar un panel
    "orden_plegar_auto": 20,     # segundos que un panel plegado se queda abierto tras tocarlo (0 = hasta que lo pliegues)
    "orden_carrusel_seg": 8,     # segundos por panel en un carrusel
    "orden_barra_paginas": "auto",      # auto | siempre | nunca
    "orden_boton_cajon": True,   # boton «Cajón» en la barra de abajo
    "orden_cajon_fijos": 3,      # extensiones que puedes fijar en pantalla (0 = sin limite)
    "orden_tope": 10,            # paneles por pagina antes de proponer ocultar (0 = sin tope)
    "orden_proponer": True,      # que Arché proponga solo cuando pases del tope
    "orden_modos_auto": True,    # cambiar de perfil por horario o por frase
    "orden_uso": {},             # clics reales por tipo de panel (sirve para proponer que ocultar)
    "orden_horarios": [],        # ["09:00-18:00=trabajo", ...]
    "orden_frases": {},          # {"modo tele": "entretenimiento"}
    # --- redes neuronales (vista y ejemplos) ---
    "ext_tema_previo": "",       # tema que tenias antes de activar el de una extension
    "redes_estilo": "diagrama",  # diagrama | arbol | lista
    "redes_neuronas": 10,        # 4-24: neuronas dibujadas por capa oculta (se muestrean; el numero real se indica)
    "redes_conexiones": 55,      # 0-100: cuantas lineas entre neuronas se ven
    "redes_pesos": True,         # color de las lineas segun el peso real (positivo / negativo)
    "redes_animar": True,        # pulso de luz al probar una frase
    "redes_color_pos": "#4aa3ff",
    "redes_color_neg": "#ff4d6d",
    "redes_leyenda": True,       # leyenda de colores
    "redes_cerca": True,         # "una neurona de cerca" en la vista grande
    "redes_etiquetas": True,     # nombre de cada intencion junto a las neuronas de salida
    "redes_ejemplos_max": 8,     # 3-30 ejemplos visibles por intencion
    "redes_probador": True,      # caja para probar una frase y ver las neuronas encenderse
    "redes_agregar": True,       # caja para agregar ejemplos desde la vista
    "redes_marcar_auto": True,   # marca «auto» los ejemplos que Arché clasifica sola
    "redes_umbral_auto": 85,     # 50-99 %: seguridad minima para agregar sin preguntar
    "redes_usar_nube": True,     # preguntar a la nube cuando la red duda
    "redes_proponer_nuevas": True,  # proponer una intencion nueva si ninguna encaja
    "redes_entrenar": "manual",  # manual (boton) | automatico (al agregar) | sistema (cada 5, como siempre)
    "redes_deshacer_segundos": 12,  # 4-60: cuanto dura el boton «deshacer» tras agregar sola
    # --- notificaciones ---
    "notif_segundos": 6,
    "notif_posicion": "arriba",  # arriba | abajo
    "notif_exito": True,
    "notif_error": True,
    "notif_info": True,
    "notif_silencio": False,
    # --- accesibilidad ---
    "ui_escala": 100,            # 60-200 %: tamaño de toda la interfaz
    "texto_escala": 100,         # 60-200 %: solo el texto
    "alto_contraste": False,
    "teclado_nav": True,         # Tab / Enter para moverte sin mouse
    "atajos": {"buscador": "Ctrl+Espacio", "editor": "Ctrl+E", "tv": "F11", "deshacer": "Ctrl+Z",
               "rehacer": "Ctrl+Y", "cajon": "Ctrl+J", "pagina_sig": "Alt+Derecha", "pagina_ant": "Alt+Izquierda"},
    # --- rendimiento ---
    "rendimiento": "normal",     # normal | ahorro | auto
    "fluidez": "alta",           # alta (30 cuadros/s) | normal (20) | ahorro (12)
    "rend_sugerir": True,        # Arché te propone ahorro si la interfaz va lenta
    # --- adaptacion al contexto (todo apagado: nada cambia sin tu permiso) ---
    "ctx_progreso": False,       # muestra un panel de progreso en tareas largas
    "ctx_resultados": False,     # abre los resultados de busqueda en una ventana temporal
    "ctx_reposo": False,         # sin actividad: se reduce a la esfera (modo ambiente)
    # --- pantallas y sincronizacion ---
    "pantallas": {},             # "pequena" | "normal" | "amplia" -> nombre de perfil
    "sync_carpeta": "",
    "sync_incluir": ["temas", "perfiles", "ajustes"],
    "notas": [],
}

_BOOL, _INT, _OPC, _HEX, _TXT, _LISTA, _DICT = "bool", "int", "opc", "hex", "txt", "lista", "dict"


def _i(a, b):
    return (_INT, a, b)


def _o(*ops):
    return (_OPC, tuple(ops))


ESQUEMA = {
    "ext_tema_previo": (_TXT, 60), "tema_dia": (_TXT, 40), "tema_noche": (_TXT, 40), "tema": (_TXT, 40), "fuente": (_TXT, 60),
    "fondo": (_TXT, 200), "fondo_oscuridad": _i(0, 90), "fondo_desenfoque": _i(0, 20),
    "escena": _o("ninguna", "gradiente", "particulas", "ondas", "rejilla", "nebulosa"),
    "escena_intensidad": _i(0, 100), "escena_velocidad": _i(25, 300), "escena_brillo": _i(10, 100),
    "efecto_sombra": _i(0, 100), "efecto_borde_luminoso": _i(0, 100), "efecto_brillo": _i(0, 100),
    "efecto_particulas": _i(0, 100), "efectos_simultaneos": _i(1, 10), "anim_velocidad": _i(25, 300),
    "estilo_voz": _o("esfera", "ondas", "anillos", "nucleo", "geometrica"),
    "orbe_tamano": _i(50, 160), "orbe_color": (_HEX,), "orbe_velocidad": _i(25, 300),
    "estado_indicador": _o("animacion", "icono", "texto", "combinado"),
    "mascota_personaje": _o("chispa", "robot", "gato", "esfera", "minimal", "imagen"),
    "mascota_nombre": (_TXT, 20), "mascota_tamano": _i(50, 200), "mascota_opacidad": _i(20, 100),
    "mascota_visibilidad": _o("siempre", "temporal"), "mascota_frecuencia": _o("poca", "normal", "mucha"),
    "chat_vista": _o("clasica", "compacta", "tecnica"), "chat_tam": _i(8, 20), "chat_ancho": _i(40, 100),
    "chat_espacio": _i(0, 30), "chat_alineacion": _o("izquierda", "derecha", "alternada"),
    "chat_color_usuario": (_HEX,), "chat_color_arche": (_HEX,), "chat_historial": _i(4, 40),
    "chat_entrada_alto": _i(24, 90),
    "sistema_estilo": _o("barras", "circular", "numeros", "compacto"), "sistema_actualizacion": _i(1, 10),
    "limite_cpu": _i(50, 100), "limite_ram": _i(50, 100), "limite_disco": _i(50, 100),
    "navegacion": _o("pestanas", "iconos", "lateral", "menu"), "nav_iconos_tam": _i(60, 200),
    "ventana_modo": _o("normal", "compacta", "superpuesta"), "ventana_opacidad": _i(30, 100),
    "ventana_geometria": (_TXT, 40), "flotante_contenido": _o("esfera", "mascota"),
    "flotante_tam": _i(80, 400), "flotante_pos": (_TXT, 20),
    "notif_segundos": _i(2, 30), "notif_posicion": _o("arriba", "abajo"),
    "ui_escala": _i(60, 200), "texto_escala": _i(60, 200),
    "rendimiento": _o("normal", "ahorro", "auto"), "fluidez": _o("alta", "normal", "ahorro"),
    "ambiente_minutos": _i(1, 240), "celular_puerto": _i(1024, 65535), "celular_pin": (_TXT, 12),
    "redes_estilo": _o("diagrama", "arbol", "lista"), "redes_neuronas": _i(4, 24), "redes_conexiones": _i(0, 100),
    "redes_color_pos": (_HEX,), "redes_color_neg": (_HEX,), "redes_ejemplos_max": _i(3, 30),
    "redes_umbral_auto": _i(50, 99), "redes_entrenar": _o("manual", "automatico", "sistema"),
    "redes_deshacer_segundos": _i(4, 60),
    "perfil": (_TXT, 40), "sync_carpeta": (_TXT, 300),
    "orden_plegar_boton": _o("al_pasar", "siempre", "nunca"), "orden_plegar_auto": _i(0, 600),
    "orden_carrusel_seg": _i(3, 120), "orden_barra_paginas": _o("auto", "siempre", "nunca"),
    "orden_cajon_fijos": _i(0, 20), "orden_tope": _i(0, 30),
    "orden_uso": (_DICT,), "orden_frases": (_DICT,), "orden_horarios": (_LISTA,),
    "estado_colores": (_DICT,), "atajos": (_DICT,), "pantallas": (_DICT,),
    "sistema_ocultar": (_LISTA,), "nav_orden": (_LISTA,), "nav_ocultas": (_LISTA,), "favoritos": (_LISTA,),
    "atajos_rapidos": (_LISTA,), "sync_incluir": (_LISTA,), "notas": (_LISTA,),
}
for _k, _v in DEFAULTS.items():                    # los booleanos se deducen de los valores por defecto
    if isinstance(_v, bool):
        ESQUEMA[_k] = (_BOOL,)

# Para las pestañas de la ventana y los comandos: las opciones cerradas
OPCIONES = {k: v[1] for k, v in ESQUEMA.items() if v[0] == _OPC}

# Lo que NO forma parte del aspecto: no va a perfiles, puntos de restauracion ni deshacer.
NO_VISUALES = {"automatica", "entrada_ventana", "recorrido_hecho", "celular", "celular_pin", "celular_puerto",
               "escucha", "perfil", "ventana_geometria", "flotante_pos", "sync_carpeta", "sync_incluir",
               "notas", "pantallas", "favoritos", "atajos_rapidos", "mascota_nombre", "atajos", "ext_tema_previo",
               "orden_uso", "orden_horarios", "orden_frases", "orden_modos_auto", "orden_proponer"}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
_datos = None
_oyentes = []
problemas = []          # lo que se descarto al leer config.json (para mostrarlo en la ventana)


def normalizar_hex(valor):
    """'#abc' / 'ABCDEF' / '(10,20,30)' -> '#aabbcc'. None si no es un color."""
    if valor is None:
        return None
    s = str(valor).strip()
    m = _HEX_RE.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return "#" + h.lower()
    m = re.match(r"^\(?\s*(\d{1,3})\s*[,; ]\s*(\d{1,3})\s*[,; ]\s*(\d{1,3})\s*\)?$", s)
    if m:
        r, g, b = (int(x) for x in m.groups())
        if max(r, g, b) <= 255:
            return "#%02x%02x%02x" % (r, g, b)
    return None


def validar(clave, valor):
    """(True, valor_limpio) o (False, motivo)."""
    if clave not in DEFAULTS:
        return False, "ese ajuste no existe"
    regla = ESQUEMA.get(clave)
    if regla is None:
        return (True, valor) if type(valor) is type(DEFAULTS[clave]) else (False, "tipo incorrecto")
    tipo = regla[0]
    if tipo == _BOOL:
        if isinstance(valor, bool):
            return True, valor
        return False, "debe ser si o no"
    if tipo == _INT:
        try:
            if isinstance(valor, bool):
                raise ValueError
            n = int(float(valor))
        except Exception:
            return False, "debe ser un numero"
        return True, max(regla[1], min(regla[2], n))
    if tipo == _OPC:
        if valor in regla[1]:
            return True, valor
        return False, "opciones: " + ", ".join(regla[1])
    if tipo == _HEX:
        if valor in ("", None):
            return True, ""
        h = normalizar_hex(valor)
        return (True, h) if h else (False, "no es un color (usa #RRGGBB o R,G,B)")
    if tipo == _TXT:
        if not isinstance(valor, str):
            return False, "debe ser texto"
        return True, valor.strip()[:regla[1]]
    if tipo == _LISTA:
        return (True, list(valor)[:200]) if isinstance(valor, (list, tuple)) else (False, "debe ser una lista")
    if tipo == _DICT:
        return (True, dict(valor)) if isinstance(valor, dict) else (False, "debe ser un diccionario")
    return False, "regla desconocida"


def _cargar():
    global _datos
    if _datos is not None:
        return _datos
    with _lock:
        if _datos is not None:
            return _datos
        _datos = {}
        try:
            with open(_ARCHIVO, "r", encoding="utf-8") as f:
                leido = json.load(f)
            if not isinstance(leido, dict):
                raise ValueError("no es un diccionario")
            for k, v in leido.items():
                ok, limpio = validar(k, v)
                if ok:
                    _datos[k] = limpio
                elif k in DEFAULTS:
                    problemas.append(f"{k}: {limpio}")
        except FileNotFoundError:
            pass
        except Exception as e:
            problemas.append(f"config.json danado ({e}); lo aparte y uso los valores por defecto")
            try:
                os.replace(_ARCHIVO, _ARCHIVO + ".danado-" + time.strftime("%Y%m%d-%H%M%S"))
            except Exception:
                pass
        return _datos


def _guardar():
    try:
        tmp = _ARCHIVO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_datos, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _ARCHIVO)
    except Exception:
        pass


def obtener(clave):
    d = _cargar()
    if clave in d:
        return d[clave]
    v = DEFAULTS.get(clave)
    return list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)


def fijar(clave, valor):
    """Guarda un ajuste validado. Devuelve el valor que quedo (el anterior si el nuevo no sirve)."""
    ok, limpio = validar(clave, valor)
    if not ok:
        return obtener(clave)
    with _lock:
        d = _cargar()
        viejo = obtener(clave)
        if viejo == limpio and clave in d:
            return limpio
        d[clave] = limpio
        _guardar()
    for fn in list(_oyentes):
        try:
            fn(clave, limpio, viejo)
        except Exception:
            pass
    return limpio


def fijar_varios(cambios):
    """Aplica varios ajustes de una vez. Devuelve (aplicados, rechazados)."""
    ok, mal = {}, {}
    for k, v in dict(cambios).items():
        valido, res = validar(k, v)
        if valido:
            fijar(k, res)
            ok[k] = res
        else:
            mal[k] = res
    return ok, mal


def alternar(clave):
    return fijar(clave, not bool(obtener(clave)))


def siguiente(clave, paso=1):
    """Pasa a la siguiente opcion de un ajuste cerrado (esfera -> ondas -> esfera...)."""
    ops = OPCIONES[clave]
    actual = obtener(clave)
    i = ops.index(actual) if actual in ops else 0
    return fijar(clave, ops[(i + paso) % len(ops)])


def restablecer(clave):
    return fijar(clave, DEFAULTS[clave])


def suscribir(fn):
    """fn(clave, nuevo, viejo) se llama en cada cambio."""
    if fn not in _oyentes:
        _oyentes.append(fn)


def claves_visuales():
    return [k for k in DEFAULTS if k not in NO_VISUALES]


def captura(claves=None):
    """Copia de los ajustes (por defecto, los visuales)."""
    return {k: obtener(k) for k in (claves or claves_visuales())}


def aplicar_captura(snap):
    """Restaura una captura (ignora lo invalido). Devuelve cuantos ajustes cambiaron."""
    n = 0
    for k, v in dict(snap or {}).items():
        if k in DEFAULTS and obtener(k) != v:
            ok, limpio = validar(k, v)
            if ok:
                fijar(k, limpio)
                n += 1
    return n
