"""
Arché 3D
--------
Carpeta: Arche/core/tres_d/

Arché como ayudante de modelado e impresión 3D, con un taller para verlo todo.

  geometria.py   abrir/guardar STL y OBJ, medir, analizar para imprimir, girar, escalar, espejo
  piezas.py      catálogo de piezas a medida + recetas de formas (sólidos siempre cerrados)
  disenador.py   entiende lo que pides, guarda los modelos y sus recetas, piezas libres con IA
  servidor.py    la página del taller (solo en tu PC, con llave)
  web/           el taller: visor de modelos, núcleo de Arché, perro en 3D y mapa del cerebro

main.py solo llama a manejar(comando): devuelve None si la frase no es de 3D.
"""

import json
import os
import re
import shutil
import threading

from . import disenador as dis
from . import geometria as geo

_candado = threading.RLock()          # una orden de 3D a la vez (la consola y la página comparten modelos)


_local = threading.local()            # cuando la orden viene de la página, lo que se dice se junta aquí


def _out(texto=""):
    """Como print(), pero si la orden vino del taller 3D la respuesta vuelve a la página."""
    junta = getattr(_local, "lineas", None)
    if junta is not None:
        junta.append(str(texto))
    else:
        print(texto)


def _msg(texto):
    _out(f"Arché: {texto}")


def ejecutar_desde_pagina(texto):
    """La página manda una orden de 3D: devuelve (líneas de respuesta, la entendió)."""
    _local.lineas = []
    try:
        resultado = manejar(texto)
        lineas = [re.sub(r"^Arché: ", "", l).strip() for l in _local.lineas]
        return lineas, resultado is not None
    finally:
        _local.lineas = None


# ------------------------------------------------------------------
# Ajustes de impresión (se guardan en Modelos3D/_ajustes.json)
# ------------------------------------------------------------------

def _ruta_ajustes():
    return os.path.join(dis.carpeta(), "_ajustes.json")


def ajustes():
    datos = {"cama": list(geo.CAMA), "material": "pla"}
    try:
        with open(_ruta_ajustes(), "r", encoding="utf-8") as f:
            leido = json.load(f)
        if isinstance(leido.get("cama"), list) and len(leido["cama"]) == 3:
            datos["cama"] = [max(20.0, min(2000.0, float(v))) for v in leido["cama"]]
        if leido.get("material") in geo.DENSIDAD:
            datos["material"] = leido["material"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return datos


def _guardar_ajustes(datos):
    temporal = _ruta_ajustes() + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2)
    os.replace(temporal, _ruta_ajustes())


def analizar(nombre):
    """Análisis completo de un modelo guardado (dict)."""
    a = ajustes()
    return geo.analizar(dis.abrir(nombre), material=a["material"], cama=a["cama"])


def _contar(nombre, malla, prefijo):
    a = ajustes()
    analisis = geo.analizar(malla, material=a["material"], cama=a["cama"])
    _msg(prefijo)
    for linea in geo.resumen(analisis):
        _out(f"       {linea}")
    from . import servidor
    if servidor.activo():
        _out(f"       Ya lo tienes en el taller 3D: {servidor.direccion()}")
    else:
        _out("       Dime «abre el taller 3d» para verlo y girarlo.")


# ------------------------------------------------------------------
# Frases
# ------------------------------------------------------------------

_VERBOS = r"(?:crea|creame|haz|hazme|disena|disename|modela|modelame|genera|generame|fabrica|fabricame|construye|construyeme|necesito|quiero|arma|armame|imprime|imprimeme)"
_PISTA_3D = r"\b(?:3d|tres d|imprimir|impresion|stl|pieza|modelo|filamento)\b"
_EL_MODELO = r"(?:el modelo|la pieza|el stl|el archivo|esa pieza|ese modelo|esto|eso)"


def _objetivo(texto):
    """De 'analiza la pata.stl' saca el modelo: uno nombrado, o el actual."""
    t = dis._norm(texto)
    t = re.sub(r"\.(stl|obj)\b", "", t)
    if re.search(_EL_MODELO, t) or not t:
        return dis.ultimo()
    return dis.buscar(t) or None


def _ayuda():
    _msg("Esto sé hacer en 3D:")
    _out("  CREAR PIEZAS A MEDIDA (en milímetros; también entiendo cm)")
    for datos in dis.piezas.CATALOGO.values():
        _out(f"    · {datos['descripcion']}  →  «{datos['ejemplo']}»")
    _out("  CAMBIAR LA ÚLTIMA:  «hazla más alta», «cambia el ancho a 60», «ponle tapa», «hazla al doble»")
    _out("  PIEZAS LIBRES (las arma la IA):  «diseña en 3d un llavero con forma de hueso»")
    _out("  REVISAR PARA IMPRIMIR:  «analiza el modelo», «analiza pata» (medidas, gramos, tiempo, soportes)")
    _out("  QUE ARCHÉ TE AYUDE:  «qué me recomiendas» (arreglos con números), «arregla la pieza», «aplica la sugerencia 2»,")
    _out("                       «repara el modelo», «crea un engranaje compañero de 40 dientes»")
    _out("  TRANSFORMAR:  «escala el modelo al 150%», «rota el modelo 90 en x», «espejo del modelo», «orienta el modelo»")
    _out("  TUS ARCHIVOS:  «importa C:\\ruta\\pieza.stl», «modelos 3d», «abre la carpeta de modelos», «borra el modelo X»")
    _out("  IMPRESORA:  «mi impresora es de 220x220x250», «uso petg»")
    _out("  VERLO TODO:  «abre el taller 3d» (modelos, núcleo de Arché, perro y cerebro en 3D)")
    _out("  COMO BLENDER:  «abre el modelador» / «quiero esculpir» / «edita pata en modelar» (esculpir, extruir caras, modificadores)")
    _out("  CON LAS MANOS:  «controla con las manos» (la cámara ve tus manos: pellizca para girar, dos manos para acercar)")


def manejar(comando):
    """Devuelve ('tres_d', detalle) si la frase era de 3D (ya respondió), o None."""
    original = (comando or "").strip()
    t = dis._norm(original)
    if not t:
        return None
    with _candado:
        try:
            return _manejar(original, t)
        except (ValueError, RuntimeError, OSError) as e:
            _msg(f"No pude con eso: {e}")
            return ("tres_d", "error")


def _manejar(original, t):
    from . import servidor

    # ---- Arché te ayuda con la pieza ----
    r = re.fullmatch(r"(?:que (?:me )?(?:recomiendas|sugieres|le cambiarias|le mejorarias)|como (?:la|lo) mejoro|sugerencias|"
                     r"ayudame|ayudame con|revisa y mejora|que le falta|que tiene de malo)(?: (?:para |con |a )?(.+))?", t)
    if r and (r.group(1) is None or re.search(_EL_MODELO, r.group(1)) or dis.buscar(r.group(1))):
        nombre = _objetivo(r.group(1) or "el modelo")
        if not nombre:
            _msg("Todavía no hay ninguna pieza. Crea una o importa un .stl y te digo cómo mejorarla.")
            return ("tres_d", "error")
        from . import asistente
        dis._estado["ultimo"] = nombre
        lista = asistente.sugerencias(nombre)["sugerencias"]
        if not lista:
            _msg(f"{nombre}.stl está bien para imprimir: cerrada, cabe y casi sin soportes. No le cambiaría nada.")
            return ("tres_d", nombre)
        _msg(f"Esto le haría a {nombre}.stl:")
        for i, sug in enumerate(lista, 1):
            cambio = f"  ({sug['antes']} → {sug['despues']})" if sug["antes"] and sug["despues"] else ""
            _out(f"  {i}. {sug['titulo']}{cambio}")
            _out(f"     {sug['por_que']}")
        if any(sug["orden"] for sug in lista):
            _out("     Dime «aplica la sugerencia 1» (o el número que quieras), o «arregla la pieza» para el arreglo principal.")
        return ("tres_d", nombre)
    r = re.fullmatch(r"(?:aplica|haz|usa)(?: la)? sugerencia(?: (?:numero |n )?(\d+))?|arregla(?:la|lo)?(?: (?:la pieza|el modelo|esto|eso))?", t)
    if r:
        nombre = dis.ultimo()
        if not nombre:
            _msg("No hay ninguna pieza para arreglar.")
            return ("tres_d", "error")
        from . import asistente
        lista = asistente.sugerencias(nombre)["sugerencias"]
        if r.group(1):
            i = int(r.group(1)) - 1
            sug = lista[i] if 0 <= i < len(lista) else None
            if sug is None:
                _msg(f"No hay sugerencia {i + 1}; tengo {len(lista)}.")
                return ("tres_d", "error")
        else:
            sug = next((x for x in lista if x["tipo"] == "arreglo"), None)
            if sug is None:
                _msg(f"{nombre}.stl no necesita arreglos. Dime «qué me recomiendas» para ver ideas.")
                return ("tres_d", nombre)
        if not sug["orden"]:
            _msg(f"«{sug['titulo']}» se ajusta en el slicer, no en la pieza: {sug['por_que']}")
            return ("tres_d", nombre)
        _msg(f"Aplico: {sug['titulo']}.")
        return _manejar(sug["orden"], dis._norm(sug["orden"])) or ("tres_d", nombre)
    r = re.fullmatch(r"repara(?:r)?(?: el| la)? (?:modelo|pieza|malla|stl)(?: (.+))?", t)
    if r:
        nombre = _objetivo(r.group(1) or "el modelo")
        if not nombre:
            _msg("No hay ningún modelo para reparar.")
            return ("tres_d", "error")
        malla = dis.abrir(nombre)
        if malla.cerrada():
            _msg(f"{nombre}.stl ya está cerrada; no hay nada que reparar.")
            return ("tres_d", nombre)
        from . import asistente
        nueva, ok = asistente.reparar(malla)
        if not ok:
            _msg(f"No pude cerrar {nombre}.stl: tiene huecos de verdad, no solo puntos sueltos. Ábrela en PrusaSlicer "
                 "(clic derecho → «Reparar») o en 3D Builder de Windows y vuelve a importarla.")
            return ("tres_d", "error")
        _respaldar(nombre)
        dis.guardar(nombre, nueva, dict(dis.leer_receta(nombre), transformado="reparado", pieza=None))
        _contar(nombre, nueva, f"Reparé {nombre}.stl: ahora la malla está cerrada.")
        return ("tres_d", nombre)
    r = re.fullmatch(r"(?:crea|haz|hazme|hazle|disena|genera)(?: un| el| su)? (?:engranaje |pinon )?companero(?: (?:de|con) (\d+) dientes)?", t)
    if r:
        base = dis.ultimo()
        receta = dis.leer_receta(base) if base else {}
        if receta.get("pieza") != "engranaje":
            _msg("Para hacer el compañero, primero elige un engranaje (o crea uno: «crea un engranaje de 20 dientes»).")
            return ("tres_d", "error")
        m1 = receta["medidas"]
        z1 = int(round(m1["dientes"]))
        z2 = int(r.group(1)) if r.group(1) else z1
        archivo, malla, finales, notas = dis.crear_del_catalogo(
            "engranaje", {"dientes": z2, "modulo": m1["modulo"], "grosor": m1["grosor"], "agujero": m1["agujero"]},
            "engranaje", como=dis.nombre_libre(f"engranaje_{z2}_companero"))
        distancia = m1["modulo"] * (z1 + finales["dientes"]) / 2
        relacion = finales["dientes"] / z1
        _contar(archivo, malla, f"Hice {archivo}.stl: {finales['dientes']:g} dientes, módulo {m1['modulo']:g}, para engranar con {base}.")
        _out(f"       Pon los ejes a {distancia:.1f} mm uno del otro (súmale 0,2 mm de holgura: {distancia + 0.2:.1f} mm).")
        if relacion > 1.01:
            _out(f"       Relación {z1}:{finales['dientes']:g}: si mueves {base} con el motor, el nuevo gira {relacion:.2f} veces "
                 f"más lento y con {relacion:.2f} veces más fuerza.")
        elif relacion < 0.99:
            _out(f"       Relación {z1}:{finales['dientes']:g}: si mueves {base} con el motor, el nuevo gira {1 / relacion:.2f} veces "
                 "más rápido, pero con menos fuerza.")
        return ("tres_d", archivo)

    # ---- Construir: armar una pieza propia con partes ----
    r = re.fullmatch(r"(?:abre|abrir|ve a|vamos a|activa|entra a|entra en|quiero)?\s*(?:el )?(?:modo )?construir(?: (?:una pieza|en 3d|piezas))?"
                     r"|(?:quiero )?(?:armar|construir|disenar) (?:mi propia|una) pieza(?: con (?:partes|formas))?"
                     r"|(?:edita|editar|abre)(?: el modelo| la pieza)? (.+?) en construir", t)
    if r:
        modelo = None
        if r.group(1):
            modelo = dis.buscar(r.group(1))
            if not modelo:
                _msg(f"No tengo un modelo que se llame «{r.group(1)}».")
                return ("tres_d", "error")
        ok, detalle = servidor.iniciar()
        if not ok:
            _msg(f"No pude abrir el taller 3D: {detalle}")
            return ("tres_d", "error")
        if getattr(_local, "lineas", None) is not None or servidor.pagina_abierta():
            servidor.pedir_vista("construir", modelo)
        else:
            servidor.abrir_navegador("construir" + (f"+{modelo}" if modelo else ""))
        _msg("Abrí Construir" + (f" con {modelo}" if modelo else "") + ": agrega formas, agárralas con la mano, "
             "estíralas con las dos manos y ábreles agujeros. Pulgar arriba la guarda.")
        return ("tres_d", "construir")

    # ---- Modelar: estilo Blender (esculpir, editar caras, modificadores) ----
    r = re.fullmatch(r"(?:abre|abrir|ve a|vamos a|activa|entra a|entra en|quiero|pon)?\s*(?:el )?(?:modo )?"
                     r"(?:modelar|modelador|esculpir|escultura|estilo blender|como (?:en )?blender|blender)(?: en 3d| con (?:las |mis )?manos)?"
                     r"|(?:quiero )?(?:esculpir|modelar) (?:una pieza|algo|en 3d|con (?:las |mis )?manos)"
                     r"|(?:edita|editar|esculpe|abre)(?: el modelo| la pieza)? (.+?) en (?:modelar|el modelador|blender)", t)
    if r:
        modelo = None
        if r.group(1):
            modelo = dis.buscar(r.group(1))
            if not modelo:
                _msg(f"No tengo un modelo que se llame «{r.group(1)}».")
                return ("tres_d", "error")
        ok, detalle = servidor.iniciar()
        if not ok:
            _msg(f"No pude abrir el taller 3D: {detalle}")
            return ("tres_d", "error")
        if getattr(_local, "lineas", None) is not None or servidor.pagina_abierta():
            servidor.pedir_vista("modelar", modelo)
        else:
            servidor.abrir_navegador("modelar" + (f"+{modelo}" if modelo else ""))
        _msg("Abrí Modelar" + (f" con {modelo}" if modelo else "") + " (como Blender): modo Objeto, Edición y Escultura. "
             "Pellizca una cara y jala para extruirla, o esculpe con el dedo. Pulgar arriba la guarda.")
        return ("tres_d", "modelar")

    # ---- control con las manos (cámara) ----
    if re.fullmatch(r"(?:activa|enciende|prende|pon|usa|quiero usar|inicia)?\s*(?:el )?(?:control (?:con|de) (?:las |mis )?manos|modo manos|"
                    r"(?:las |mis )?manos(?: en 3d| para el 3d)?)|(?:controla|maneja|mueve)(?: (?:el|la) (?:modelo|pieza|vista|3d))? con (?:las |mis )?manos", t) \
            and not re.fullmatch(r"(?:las |mis )?manos", t):
        ok, detalle = servidor.iniciar()
        if not ok:
            _msg(f"No pude abrir el taller 3D: {detalle}")
            return ("tres_d", "error")
        if getattr(_local, "lineas", None) is not None:
            _msg("Toca el botón «Manos» (a la izquierda) para encender la cámara.")
            return ("tres_d", "manos")
        if servidor.pagina_abierta():
            servidor.pedir_manos()
            _msg("Encendí el control con las manos en el taller 3D que tienes abierto. Ponte frente a la cámara.")
        else:
            servidor.abrir_navegador("taller+manos")
            _msg(f"Abrí el taller 3D con el control de manos ({servidor.direccion()}). Si el navegador pide permiso "
                 "para la cámara, acéptalo.")
        _out("       Pellizca (índice y pulgar) y mueve: giras. Con las dos manos pellizcando: separa para acercar.")
        _out("       Palma abierta quieta un segundo: vuelve al inicio. La imagen de la cámara no sale de tu PC.")
        return ("tres_d", "manos")

    # ---- el taller ----
    r = re.fullmatch(r"(?:abre|abrir|abreme|muestra|muestrame|inicia|lanza|pon|ver|ve al)?\s*(?:el |la |al )?"
                     r"(?:(taller|visor|estudio|modo|laboratorio) (?:3d|en 3d|tres d)|arche 3d|3d|"
                     r"(nucleo|cerebro|perro|robot)(?: de arche)? (?:3d|en 3d))", t)
    if r:
        pestana = {"nucleo": "nucleo", "cerebro": "cerebro", "perro": "perro", "robot": "perro"}.get(r.group(2) or "", "taller")
        ok, detalle = servidor.iniciar()
        if not ok:
            _msg(f"No pude abrir el taller 3D: {detalle}")
            return ("tres_d", "error")
        if getattr(_local, "lineas", None) is not None:
            _msg("Ya estás en el taller 3D.")
            return ("tres_d", "abrir")
        servidor.abrir_navegador(pestana)
        _msg(f"Abrí el taller 3D en tu navegador ({servidor.direccion()}). Solo se puede ver desde este PC.")
        return ("tres_d", "abrir")
    if re.fullmatch(r"(?:cierra|apaga|deten|para) (?:el )?(?:taller|visor|estudio|modo) (?:3d|en 3d)", t):
        servidor.detener()
        _msg("Cerré el taller 3D.")
        return ("tres_d", "cerrar")
    if re.fullmatch(r"(?:ayuda|comandos|que sabes hacer|que puedes hacer)(?: de| en| del)? (?:3d|modelado|impresion 3d|modelos 3d)"
                    r"|(?:que|cuales) piezas (?:sabes|puedes) (?:hacer|crear|fabricar)|catalogo (?:3d|de piezas)", t):
        _ayuda()
        return ("tres_d", "ayuda")

    # ---- impresora ----
    r = re.fullmatch(rf"(?:mi )?(?:impresora|cama)(?: 3d)? (?:es|mide|tiene)(?: de)? {dis._NUM}\s*(?:x|por)\s*{dis._NUM}\s*(?:x|por)\s*{dis._NUM}(?: mm)?", t)
    if r:
        datos = ajustes()
        datos["cama"] = [max(20.0, min(2000.0, float(g.replace(",", ".")))) for g in r.groups()]
        _guardar_ajustes(datos)
        _msg(f"Anotado: tu impresora imprime hasta {datos['cama'][0]:g} × {datos['cama'][1]:g} × {datos['cama'][2]:g} mm.")
        return ("tres_d", "impresora")
    r = re.fullmatch(r"(?:uso|imprimo|voy a imprimir|imprime)(?: en| con)? (pla|petg|abs|tpu)", t)
    if r:
        datos = ajustes()
        datos["material"] = r.group(1)
        _guardar_ajustes(datos)
        _msg(f"Listo: calculo los pesos en {r.group(1).upper()}.")
        return ("tres_d", "material")

    # ---- la lista y la carpeta ----
    if re.fullmatch(r"(?:muestra(?:me)? |lista(?:r)? |ver |dime )?(?:mis |los |la lista de )?modelos(?: 3d| en 3d)?|que modelos (?:tengo|hay)", t):
        modelos = dis.listar()
        if not modelos:
            _msg("Todavía no hay modelos. Prueba: «crea una caja de 80x50x30 con tapa».")
        else:
            _msg(f"Tienes {len(modelos)} modelo(s) en {dis.carpeta()}:")
            actual = dis.ultimo()
            for m in modelos[:30]:
                que = m["receta"].get("alias") or ("pieza libre" if m["receta"].get("receta") else "importado")
                _out(f"  {'▶' if m['nombre'] == actual else ' '} {m['nombre']}.stl  ({que}, {m['bytes'] / 1024:.0f} KB)")
        return ("tres_d", "lista")
    if re.fullmatch(r"abre (?:la )?carpeta de (?:los )?modelos(?: 3d)?", t):
        ruta = dis.carpeta()
        try:
            os.startfile(ruta)                    # Windows
        except AttributeError:
            pass
        _msg(f"Tus modelos están en {ruta}")
        return ("tres_d", "carpeta")

    # ---- importar un archivo del PC ----
    r = re.match(r"^(?:importa|importar|trae|carga|agrega)(?: el| la)?(?: modelo| archivo| pieza)?\s+(.+\.(?:stl|obj))\s*$", original, re.IGNORECASE)
    if r:
        ruta = os.path.expanduser(r.group(1).strip().strip('"').strip("'"))
        if not os.path.isfile(ruta):
            _msg(f"No encuentro ese archivo: {ruta}")
            return ("tres_d", "error")
        malla = geo.apoyar(geo.leer_modelo(ruta))
        nombre = dis.guardar(dis.nombre_libre(os.path.basename(ruta)), malla, {"importado": os.path.basename(ruta)})
        _contar(nombre, malla, f"Importé {nombre}.stl.")
        return ("tres_d", nombre)

    # ---- usar / borrar ----
    r = re.fullmatch(r"(?:usa|trabaja con|selecciona|elige|abre)(?: el| la)? (?:modelo|pieza) (.+)", t)
    if r:
        nombre = dis.buscar(r.group(1))
        if not nombre:
            _msg(f"No tengo un modelo que se llame «{r.group(1)}». Dime «modelos 3d» para verlos.")
            return ("tres_d", "error")
        dis._estado["ultimo"] = nombre
        dis._estado["version"] += 1
        _msg(f"Ahora trabajo con {nombre}.stl.")
        return ("tres_d", nombre)
    r = re.fullmatch(r"(?:borra|elimina|quita)(?: el| la)? (?:modelo|pieza)(?: 3d)? (.+)", t)
    if r:
        nombre = dis.buscar(r.group(1))
        if nombre and dis.borrar(nombre):
            _msg(f"Pasé {nombre}.stl a la papelera de modelos (Modelos3D/_papelera).")
        else:
            _msg(f"No tengo un modelo que se llame «{r.group(1)}».")
        return ("tres_d", "borrar")

    # ---- analizar ----
    r = re.fullmatch(r"(?:analiza|analizame|revisa|inspecciona|mide|evalua)(?: para imprimir)? (.+?)(?: para imprimir)?"
                     r"|(?:cuanto (?:pesa|mide|filamento (?:gasta|usa|necesita)|tarda(?: en imprimirse)?)|se puede imprimir|cabe en (?:la|mi) impresora) (.+)", t)
    if r:
        texto_objetivo = r.group(1) or r.group(2)
        es_de_3d = re.search(_EL_MODELO, texto_objetivo) or re.search(r"\.(stl|obj)\b", texto_objetivo) or dis.buscar(texto_objetivo)
        if es_de_3d:
            nombre = _objetivo(texto_objetivo)
            if not nombre:
                _msg("No hay ningún modelo todavía. Crea uno o importa un .stl.")
                return ("tres_d", "error")
            dis._estado["ultimo"] = nombre
            _contar(nombre, dis.abrir(nombre), f"Esto veo en {nombre}.stl:")
            return ("tres_d", nombre)

    # ---- transformar ----
    r = re.fullmatch(rf"(?:escala|escalar|agranda|achica|reduce)(?: (?!a\b|al\b|por\b)(.+?))? (?:al doble|(?:a|al) (?:la )?mitad|(?:a|al|en|por)(?: un)? {dis._NUM} ?(%|por ciento|veces)?)", t)
    if r and (r.group(1) is None or re.search(_EL_MODELO, r.group(1)) or dis.buscar(r.group(1))):
        nombre = _objetivo(r.group(1) or "el modelo")
        if not nombre:
            _msg("No hay ningún modelo para escalar.")
            return ("tres_d", "error")
        if "doble" in t:
            factor = 2.0
        elif "mitad" in t:
            factor = 0.5
        else:
            numero = float(r.group(2).replace(",", "."))
            factor = numero / 100.0 if (r.group(3) in ("%", "por ciento") or numero > 10) else numero
        if not 0.01 <= factor <= 100:
            _msg("Esa escala no tiene sentido (uso entre 1 % y 10000 %).")
            return ("tres_d", "error")
        malla = geo.escalar(dis.abrir(nombre), factor)
        _respaldar(nombre)
        dis.guardar(nombre, malla, dict(dis.leer_receta(nombre), transformado=f"escala x{factor:g}", pieza=None))
        _contar(nombre, malla, f"Escalé {nombre}.stl al {factor * 100:g} %.")
        return ("tres_d", nombre)
    r = re.fullmatch(rf"(?:rota|gira|voltea)(?: (.+?))? (-?\d+(?:[.,]\d+)?)(?: grados| °)?(?: en| sobre| alrededor de)?(?: el)?(?: eje)? ([xyz])", t)
    if r and (r.group(1) is None or re.search(_EL_MODELO, r.group(1)) or dis.buscar(r.group(1))):
        nombre = _objetivo(r.group(1) or "el modelo")
        if not nombre:
            _msg("No hay ningún modelo para girar.")
            return ("tres_d", "error")
        grados = float(r.group(2).replace(",", "."))
        malla = geo.rotar(dis.abrir(nombre), r.group(3), grados)
        _respaldar(nombre)
        dis.guardar(nombre, malla, dict(dis.leer_receta(nombre), transformado=f"giro {grados:g}° en {r.group(3)}", pieza=None))
        _contar(nombre, malla, f"Giré {nombre}.stl {grados:g}° en {r.group(3).upper()}.")
        return ("tres_d", nombre)
    r = re.fullmatch(r"(?:haz |hazme |crea )?(?:el |un |una )?(?:espejo|reflejo|copia espejo|version espejo)(?: de| del)? ?(.*?)(?: en(?: el eje)? ([xyz]))?"
                     r"|refleja (.+?)(?: en(?: el eje)? ([xyz]))?", t)
    if r:
        texto_objetivo = (r.group(1) or r.group(3) or "el modelo").strip() or "el modelo"
        texto_objetivo = re.sub(r"^(?:l )", "el ", texto_objetivo)          # "del modelo" -> "(de)l modelo"
        nombre = _objetivo("el modelo" if texto_objetivo in ("modelo", "l modelo", "la pieza", "pieza") else texto_objetivo)
        if not nombre:
            _msg("No hay ningún modelo para reflejar.")
            return ("tres_d", "error")
        eje = r.group(2) or r.group(4) or "x"
        malla = geo.espejo(dis.abrir(nombre), eje)
        nuevo = dis.guardar(dis.nombre_libre(nombre + "_espejo"), malla, {"espejo_de": nombre, "eje": eje})
        _contar(nuevo, malla, f"Hice {nuevo}.stl: el espejo de {nombre} (en {eje.upper()}). Sirve para la pieza del otro lado.")
        return ("tres_d", nuevo)
    r = re.fullmatch(r"(?:orienta|acomoda|acuesta|pon)(?: (.+?))? (?:para imprimir|para la impresion|en la mejor posicion|como mejor se imprima)"
                     r"|orienta (.+)", t)
    if r:
        texto_objetivo = r.group(1) or r.group(2) or "el modelo"
        if re.search(_EL_MODELO, texto_objetivo) or dis.buscar(texto_objetivo):
            nombre = _objetivo(texto_objetivo)
            if not nombre:
                _msg("No hay ningún modelo para orientar.")
                return ("tres_d", "error")
            malla = dis.abrir(nombre)
            antes = geo._voladizo(geo.apoyar(malla))[0]
            mejor = geo.mejor_orientacion(malla)[0]
            if mejor["eje"] is None or mejor["soporte_mm2"] >= antes - 1.0:
                _msg(f"{nombre}.stl ya está en la mejor posición para imprimir.")
                return ("tres_d", nombre)
            malla = geo.rotar(malla, mejor["eje"], mejor["grados"])
            _respaldar(nombre)
            dis.guardar(nombre, malla, dict(dis.leer_receta(nombre), transformado="orientado para imprimir", pieza=None))
            _contar(nombre, malla, f"Dejé {nombre}.stl {mejor['nombre']}: el voladizo bajó de "
                                   f"{antes / 100:.1f} a {mejor['soporte_mm2'] / 100:.1f} cm².")
            return ("tres_d", nombre)

    # ---- crear una pieza del catálogo ----
    r = re.match(rf"^{_VERBOS} (?:un |una |el |la |otro |otra )?(.+)$", t)
    if r:
        resto = r.group(1)
        nombre_pieza, alias = dis.pieza_en(resto)
        # en la página del taller todo lo que se pide es 3D
        con_pista = bool(re.search(_PISTA_3D, t)) or getattr(_local, "lineas", None) is not None
        if nombre_pieza:
            tiene_numero = bool(re.search(r"\d", resto))
            # la pieza debe ser lo que se pide (no "crea una nota sobre la caja")
            al_inicio = re.match(rf"^(?:modelo (?:3d )?de |pieza (?:3d )?de |(?:un |una ))?(?:{re.escape(dis._norm(alias))})", resto)
            if al_inicio and (alias not in dis._AMBIGUOS or tiene_numero or con_pista):
                medidas = dis.medidas_de(resto, nombre_pieza)
                archivo, malla, finales, notas = dis.crear_del_catalogo(nombre_pieza, medidas, alias)
                _contar(archivo, malla, f"Listo, hice {archivo}.stl: {dis.explicar_medidas(nombre_pieza, finales)} (mm).")
                for nota in notas:
                    _out(f"       Ojo: {nota}.")
                return ("tres_d", archivo)
        # ---- pieza libre: hay que pedirla claramente en 3D ----
        libre = re.match(r"^(?:en 3d |un modelo 3d de |un modelo de |una pieza 3d de |para imprimir(?: en 3d)? )(.+)$", resto) \
            or re.match(r"^(.+?) (?:en 3d|para imprimir(?: en 3d)?|para la impresora 3d|en stl)$", resto)
        if libre:
            pedido = libre.group(1).strip()
            _msg(f"Voy a diseñar «{pedido}». Dame un momento...")
            try:
                archivo, malla, _receta = dis.crear_libre(pedido)
            except Exception as e:
                _msg(f"No me salió esa pieza: {e} Las piezas libres las arma la IA con formas básicas; "
                     "con «ayuda 3d» ves las que hago exactas.")
                return ("tres_d", "error")
            _contar(archivo, malla, f"Hice {archivo}.stl. Es un primer diseño con formas básicas: míralo en el taller antes de imprimir.")
            return ("tres_d", archivo)

    # ---- cambiar la última pieza ----
    if re.match(r"^(?:hazl[aeo]s?|ponl[aeo]s?|dejal[aeo]|quitale|que sea |que tenga |cambia(?:le)? |ahora |mejor |mas )", t) and dis.ultimo():
        cambio = dis.modificar(original)
        if cambio:
            archivo, malla, finales, notas, que = cambio
            receta = dis.leer_receta(archivo)
            _contar(archivo, malla, f"Cambié {archivo}.stl ({', '.join(c.replace('_', ' ') for c in que)}): "
                                    f"{dis.explicar_medidas(receta.get('pieza'), finales)} (mm).")
            for nota in notas:
                _out(f"       Ojo: {nota}.")
            return ("tres_d", archivo)
    return None


def _respaldar(nombre):
    """Antes de transformar un modelo en su sitio, guarda cómo estaba en la papelera."""
    try:
        papelera = os.path.join(dis.carpeta(), "_papelera")
        os.makedirs(papelera, exist_ok=True)
        import time
        shutil.copy2(dis.ruta_stl(nombre), os.path.join(papelera, f"{time.strftime('%Y%m%d_%H%M%S')}_{nombre}.stl"))
    except OSError:
        pass


def detener_todo():
    try:
        from . import servidor
        servidor.detener()
    except Exception:
        pass
