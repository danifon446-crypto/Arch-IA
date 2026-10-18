"""
ensenar.py
----------
Ubicacion: Arche/core/IA/ensenar.py

Carga MANUAL de ejemplos de entrenamiento -- la contraparte de los
caminos automaticos (entrenar rapido / a fondo, estudio, examen).

  ensenar <frase> => <intencion>              un ejemplo a la vez
  ensenar <frase> => <intencion> => <dato>    con el dato variable (ver abajo)
  importar ejemplos                           varios de golpe, desde
                                              core/IA/ejemplos_manuales.txt
  intenciones [<dominio>]                     nombres validos + cuantos
                                              ejemplos tiene cada una

Todo pasa por aprendizaje.aprender(), el MISMO camino que usan los
demas: calcula el embedding, lo guarda en conocimiento.json y cuenta
para el reentreno automatico (cada pocos ejemplos se reentrenan solos
el clasificador y el jerarquico). Cargar el mismo ejemplo dos veces no
lo duplica: aprender() actualiza la frase que ya existia.

Seguridad: una intencion que no existe en el catalogo se RECHAZA (con
sugerencias de nombres parecidos) en vez de guardarse. Un ejemplo con
la intencion mal escrita contaminaria al clasificador con una clase
fantasma.

El "dato variable" (tercer campo) solo hace falta en intenciones con
argumento, como crear_nota ("anota compras" -> dato "compras"): le sirve
a aprender() para deducir la plantilla. Si no lo pones, la frase se
guarda literal, que tambien funciona.
"""

import os
from collections import Counter
from difflib import get_close_matches

from core.IA import catalogo

BASE = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_EJEMPLOS = os.path.join(BASE, "ejemplos_manuales.txt")

FUENTE = "manual"

PLANTILLA_ARCHIVO = """\
# ejemplos_manuales.txt
# Un ejemplo por linea, con este formato:
#
#     frase | intencion
#     frase | intencion | dato_variable      (solo si la intencion lleva argumento)
#
# Las lineas vacias y las que empiezan con # se ignoran.
# Para ver los nombres validos de intencion, en Arche escribe: intenciones
# Despues de editar este archivo, en Arche escribe: importar ejemplos
#
# Ejemplos (borra el # para usarlos):
#     que hora tienes ahorita | hora
#     anotame lo del dentista | crear_nota | lo del dentista
"""


def _norm(texto):
    return catalogo.normalizar(texto)


def _resolver_intencion(texto):
    """(id_valido | None, sugerencias). Acepta el id exacto o con
    espacios/guiones en vez de '_' ('crear nota' -> 'crear_nota')."""
    candidato = texto.strip().lower().replace(" ", "_").replace("-", "_")
    if candidato in catalogo.POR_ID:
        return candidato, []
    # sin tildes por si la escribieron con ellas
    candidato = _norm(texto).replace(" ", "_").replace("-", "_")
    if candidato in catalogo.POR_ID:
        return candidato, []
    return None, get_close_matches(candidato, list(catalogo.POR_ID), n=3, cutoff=0.7)


def ensenar(frase, intencion, contenido=""):
    """
    Agrega UN ejemplo. Devuelve (ok, mensaje). No lanza excepciones por
    datos malos: devuelve ok=False con la razon.
    """
    frase = (frase or "").strip()
    if not frase:
        return False, "La frase está vacía."
    id_intencion, sugerencias = _resolver_intencion(intencion or "")
    if id_intencion is None:
        extra = f" ¿Quisiste decir: {', '.join(sugerencias)}?" if sugerencias else ""
        return False, f"No existe la intención '{(intencion or '').strip()}'.{extra} ('intenciones' muestra todas)"

    from core.IA import aprendizaje
    aprendizaje.aprender(frase, id_intencion, (contenido or "").strip(), fuente=FUENTE)
    return True, f"Aprendido: «{frase}» → {id_intencion}"


def parsear_ensenanza(texto):
    """
    Separa 'frase => intencion [=> dato]' (o con '|', o con '->').
    Devuelve (frase, intencion, contenido) o None si no tiene el formato.
    """
    for separador in ("=>", "|", "->"):
        if separador in texto:
            partes = [p.strip() for p in texto.split(separador)]
            partes = [p for p in partes if p != ""]
            if len(partes) >= 2:
                return partes[0], partes[1], partes[2] if len(partes) > 2 else ""
            return None
    return None


def comando_ensenar(comando_original):
    """Maneja 'ensenar <frase> => <intencion>' tal como lo escribe el
    usuario en el chat (con o sin tilde en 'enseñar')."""
    cuerpo = comando_original.strip()
    for prefijo in ("enseñar", "ensenar", "Enseñar", "Ensenar"):
        if cuerpo.lower().startswith(prefijo.lower()):
            cuerpo = cuerpo[len(prefijo):].lstrip(" :")
            break

    partes = parsear_ensenanza(cuerpo)
    if partes is None:
        print("Arché: Usa el formato:  enseñar <frase> => <intención>\n"
              "       Ejemplo:         enseñar dime que hora es en este momento => hora\n"
              "       ('intenciones' muestra los nombres válidos.)")
        return False
    ok, mensaje = ensenar(*partes)
    print(f"Arché: {mensaje}")
    return ok


def _huella(ruta):
    """Resumen del contenido util del archivo (sin comentarios ni lineas vacias)."""
    import hashlib
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            lineas = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        return None
    return hashlib.sha1("\n".join(lineas).encode("utf-8")).hexdigest() if lineas else None


def _archivo_registro():
    from core.rutas import DATABASE
    return os.path.join(DATABASE, "ejemplos_importados.json")


def _leer_registro():
    import json
    try:
        with open(_archivo_registro(), "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def marcar_importado(ruta):
    """Recuerda que el archivo, tal como esta ahora, ya entro al banco."""
    import json
    datos = _leer_registro()
    datos[os.path.basename(ruta)] = _huella(ruta)
    try:
        os.makedirs(os.path.dirname(_archivo_registro()), exist_ok=True)
        with open(_archivo_registro(), "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
    except OSError:
        pass


def lineas_pendientes(ruta=None):
    """Lineas utiles del archivo que aun no se importaron (0 si no cambio desde la ultima importacion)."""
    ruta = ruta or ARCHIVO_EJEMPLOS
    huella = _huella(ruta)
    if huella is None or _leer_registro().get(os.path.basename(ruta)) == huella:
        return 0
    with open(ruta, "r", encoding="utf-8") as f:
        return sum(1 for l in f if l.strip() and not l.lstrip().startswith("#"))


def importar_ejemplos(ruta=None, silencioso=False):
    """
    Lee un archivo de lineas 'frase | intencion [| dato]' y las carga
    todas. Las lineas invalidas NO frenan al resto: se cuentan y se
    informan con su numero de linea. Devuelve
    {"agregados": n, "rechazados": [(n_linea, motivo)], "ruta": ruta}.
    Si el archivo no existe, crea la plantilla para que la completes.
    """
    ruta = ruta or ARCHIVO_EJEMPLOS
    if not os.path.exists(ruta):
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(PLANTILLA_ARCHIVO)
            if not silencioso:
                print(f"Arché: No existía {os.path.basename(ruta)}; te dejé una plantilla en {ruta}. "
                      f"Agrega tus ejemplos ahí y vuelve a decir 'importar ejemplos'.")
        except OSError as e:
            if not silencioso:
                print(f"Arché: No pude crear la plantilla ({e}).")
        return {"agregados": 0, "rechazados": [], "ruta": ruta}

    agregados, rechazados = 0, []
    with open(ruta, "r", encoding="utf-8") as f:
        lineas = f.readlines()

    # aprender() reentrena las redes cada pocos ejemplos; con un archivo
    # grande eso seria reentrenar decenas de veces. Se desactiva durante la
    # carga y se reentrena UNA sola vez al final.
    from core.IA import aprendizaje
    umbral_original = aprendizaje.UMBRAL_REENTRENO
    aprendizaje.UMBRAL_REENTRENO = float("inf")
    try:
        for numero, linea in enumerate(lineas, start=1):
            limpia = linea.strip()
            if not limpia or limpia.startswith("#"):
                continue
            partes = [p.strip() for p in limpia.split("|")]
            if len(partes) < 2 or not partes[0] or not partes[1]:
                rechazados.append((numero, "formato: frase | intencion"))
                continue
            try:
                ok, mensaje = ensenar(partes[0], partes[1], partes[2] if len(partes) > 2 else "")
            except Exception as e:
                ok, mensaje = False, f"error al aprender ({type(e).__name__}: {e})"
            if ok:
                agregados += 1
            else:
                rechazados.append((numero, mensaje))
    finally:
        aprendizaje.UMBRAL_REENTRENO = umbral_original

    if not rechazados:
        marcar_importado(ruta)

    if agregados:
        if not silencioso:
            print(f"Arché: Cargué {agregados} ejemplo(s); reentreno las redes una sola vez (puede tardar un poco)...")
        aprendizaje.reentrenar_ahora()

    if not silencioso:
        print(f"Arché: Importé {agregados} ejemplo(s) de {os.path.basename(ruta)}.")
        for numero, motivo in rechazados:
            print(f"  ⚠️ línea {numero}: {motivo}")
        if rechazados:
            print("  (Las líneas con error no se cargaron; corrígelas y vuelve a importar -- "
                  "las que ya entraron no se duplican.)")
    return {"agregados": agregados, "rechazados": rechazados, "ruta": ruta}


def listar_intenciones(dominio=None):
    """Texto con las intenciones validas agrupadas por dominio, con su
    descripcion y cuantos ejemplos tiene cada una hoy."""
    conteo = Counter()
    try:
        from core.IA import aprendizaje
        conteo = Counter(d.get("accion") for d in aprendizaje.cargar())
    except Exception:
        pass  # sin conteo igual sirve para saber los nombres

    por_dominio = catalogo.dominios_del_catalogo()
    if dominio:
        buscado = _norm(dominio)
        por_dominio = {d: ids for d, ids in por_dominio.items() if buscado in _norm(d)}
        if not por_dominio:
            return f"No hay un dominio '{dominio.strip()}'. Los que hay: {', '.join(catalogo.dominios_del_catalogo())}."

    lineas = [""]
    for nombre, ids in por_dominio.items():
        lineas.append(f"• {nombre.upper()}")
        for id_intencion in ids:
            lineas.append(f"    {id_intencion:<26} {conteo.get(id_intencion, 0):>3} ej.  {catalogo.descripcion_de(id_intencion)}")
        lineas.append("")
    lineas.append("Uso:  enseñar <frase> => <intención>   ·   importar ejemplos")
    return "\n".join(lineas)