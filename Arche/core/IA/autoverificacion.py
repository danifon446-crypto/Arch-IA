"""
autoverificacion.py
-------------------
Ubicacion: Arche/core/IA/autoverificacion.py

"¿Cómo sé que la autorreparación sirve?" -> se lo preguntas a Arché y ella
misma lo comprueba DE VERDAD, de punta a punta, y te contesta con ✅ / ❌ y,
si algo falla, qué decirle para arreglarlo.

Comando: "verifica tu autonomia" / "prueba tu autorreparacion" / "te funciona la autorreparacion"

Qué comprueba:
  1. Que anota los errores reales (provoca uno a proposito en un archivo temporal).
  2. Que tiene un modelo que le escriba arreglos (nube o Ollama) y que responde.
  3. Que se ARREGLA DE VERDAD: con ese mismo error temporal, el modelo real
     escribe el arreglo y la prueba, se demuestra en un entorno aislado
     (falla antes, pasa después), se aplica al archivo temporal y se comprueba
     que el código ya no falla. (Para que tarde poco, aquí no corre el autotest
     completo; en las reparaciones de verdad, sí.)
  4. Que las pruebas aprendidas (los errores que ya arregló) siguen pasando.
  5. Que guarda historial en git.
  6. Que el modo automático está encendido.

No toca tu código real ni tus datos: todo lo de la prueba va a archivos
temporales que se borran al terminar, aunque algo falle.
"""

import importlib
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

RAIZ_APP = Path(__file__).resolve().parents[2]          # Arche/
MODULO_TMP = "core._verificacion_arche_tmp"
REL_TMP = "core/_verificacion_arche_tmp.py"
CODIGO_CON_ERROR = (
    "def promedio(numeros):\n"
    "    \"\"\"Promedio de una lista de numeros.\"\"\"\n"
    "    total = sum(numeros)\n"
    "    return total / len(numeros)\n"
)

OK, MAL, AVISO = "✅", "❌", "⚠️"


def _msg(texto):
    print(f"Arché: {texto}")


def _paso(estado, titulo, detalle="", como=""):
    print(f"  {estado} {titulo}" + (f" — {detalle}" if detalle else ""))
    if como:
        print(f"       → {como}")
    return estado


def _quien_programa():
    """Texto de quien escribe el codigo ahora: 'la nube (Groq)' u 'Ollama (modelo)'."""
    try:
        from core.IA import nube, nube_tareas
        if nube_tareas.activa("codigo") and nube.disponible():
            return "la nube (" + nube.PROVEEDORES[nube.proveedor()]["nombre"].split(" (")[0] + ")", True
    except Exception:
        pass
    try:
        from core.IA import ollamaIA
        return f"Ollama ({ollamaIA.MODELO_CODIGO})", False
    except Exception:
        return "Ollama", False


# ------------------------------------------------------------------
# La prueba de punta a punta, aislada
# ------------------------------------------------------------------

class _Aislamiento:
    """Redirige todo lo que la reparacion escribe a archivos temporales y lo restaura al salir."""

    def __enter__(self):
        from core.IA import autorreparar as ar, registro_errores as re_
        from core.IA import proponer_cambio_codigo as pc, revisar_cambios_codigo as rc
        self.ar, self.re_, self.pc, self.rc = ar, re_, pc, rc
        self.tmp = Path(tempfile.mkdtemp(prefix="arche_verificacion_"))
        self.carpeta_pruebas = RAIZ_APP / "core" / "_verificacion_pruebas_tmp"
        self.guardado = {
            "re_archivo": re_.ARCHIVO, "carpeta": ar.CARPETA_PRUEBAS, "aplicar": ar._aplicar_con_barandas,
            "anexar": ar._anexar_prueba_al_ultimo_lote, "commit": ar._commit, "cupo": ar._sumar_cupo,
            "pc_pend": pc.ARCHIVO_PENDIENTES, "pc_log": pc.ARCHIVO_LOG, "rc_log": rc.ARCHIVO_LOG,
        }
        re_.ARCHIVO = str(self.tmp / "errores.json")
        ar.CARPETA_PRUEBAS = self.carpeta_pruebas
        pc.ARCHIVO_PENDIENTES = self.tmp / "pendientes.json"
        pc.ARCHIVO_LOG = self.tmp / "log.jsonl"
        rc.ARCHIVO_LOG = self.tmp / "log.jsonl"
        ar._sumar_cupo = lambda n: None
        ar._anexar_prueba_al_ultimo_lote = lambda rel: None
        ar._commit = lambda archivos, mensaje: (False, "verificación: sin commit")
        # Camino de aplicacion real (sintaxis + entorno aislado + respaldo), sin el autotest completo
        ar._aplicar_con_barandas = lambda prop: (["ok"], []) if rc.aplicar_propuesta(prop) else ([], ["no se aplicó"])
        (RAIZ_APP / REL_TMP).write_text(CODIGO_CON_ERROR, encoding="utf-8")
        sys.modules.pop(MODULO_TMP, None)
        return self

    def __exit__(self, *exc):
        g, ar, re_, pc, rc = self.guardado, self.ar, self.re_, self.pc, self.rc
        re_.ARCHIVO = g["re_archivo"]
        ar.CARPETA_PRUEBAS = g["carpeta"]
        ar._aplicar_con_barandas = g["aplicar"]
        ar._anexar_prueba_al_ultimo_lote = g["anexar"]
        ar._commit = g["commit"]
        ar._sumar_cupo = g["cupo"]
        pc.ARCHIVO_PENDIENTES = g["pc_pend"]
        pc.ARCHIVO_LOG = g["pc_log"]
        rc.ARCHIVO_LOG = g["rc_log"]
        (RAIZ_APP / REL_TMP).unlink(missing_ok=True)
        shutil.rmtree(self.carpeta_pruebas, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        for b in (RAIZ_APP / "core" / "IA" / "backups_codigo").glob("core___verificacion_arche_tmp*"):
            b.unlink(missing_ok=True)
        sys.modules.pop(MODULO_TMP, None)
        return False


def _provocar_error(re_):
    modulo = importlib.import_module(MODULO_TMP)
    try:
        modulo.promedio([])
    except ZeroDivisionError as e:
        return re_.registrar(e, frase="verificación: promedio de una lista vacía")
    return None


def _correr_pruebas_aprendidas():
    """(pasan, total, nombres_que_fallan)."""
    from core.IA import autorreparar
    archivos = sorted(autorreparar.CARPETA_PRUEBAS.glob("prueba_*.py")) if autorreparar.CARPETA_PRUEBAS.is_dir() else []
    if not archivos:
        return 0, 0, []
    entorno = autorreparar._entorno_aislado()
    fallan = []
    try:
        for ruta in archivos:
            paso, _ = autorreparar.correr_prueba(ruta.read_text(encoding="utf-8"), entorno=entorno)
            if not paso:
                fallan.append(ruta.stem[len("prueba_"):])
    finally:
        shutil.rmtree(entorno, ignore_errors=True)
    return len(archivos) - len(fallan), len(archivos), fallan


def verificar():
    """Corre la verificacion completa e imprime el informe. Devuelve True si todo lo esencial esta bien."""
    from core import mejora_continua
    if mejora_continua._trabajando:
        _msg("Ahora mismo estoy en mi ciclo de mejora; pídemelo de nuevo en unos minutos.")
        return False

    inicio = time.time()
    _msg("Me voy a comprobar de verdad: provoco un error a propósito en un archivo temporal, me lo arreglo con "
         "mi modelo de código y miro si quedó bien. No toco tu código. Puede tardar 1 o 2 minutos...")
    print()
    esenciales = []

    with _Aislamiento() as ais:
        # 1) registro
        err = _provocar_error(ais.re_)
        if err and err.get("archivo") == REL_TMP and err.get("estado") == "pendiente":
            esenciales.append(_paso(OK, "Anoto mis errores", f"atrapé un {err['tipo']} con su archivo, línea y variables"))
        else:
            esenciales.append(_paso(MAL, "Anoto mis errores", "no quedó registrado",
                                    "copia de nuevo core/IA/registro_errores.py"))
            err = None

        # 2) modelo
        quien, es_nube = _quien_programa()
        t0 = time.time()
        respuesta = ais.ar._generar("Responde únicamente con la palabra LISTO.")
        if respuesta.strip():
            esenciales.append(_paso(OK, "Tengo quién me escriba arreglos", f"{quien}, respondió en {time.time() - t0:.0f}s"))
            modelo_ok = True
        else:
            como = ("revisa tu conexión y 'estado de la nube'" if es_nube
                    else "dime 'usa la nube para programar' (recomendado) o abre Ollama")
            esenciales.append(_paso(MAL, "Tengo quién me escriba arreglos", f"{quien} no respondió", como))
            modelo_ok = False

        # 3) reparacion real
        if err and modelo_ok:
            t0 = time.time()
            estado, texto, intentos = "reintentar", "", 0
            while estado == "reintentar" and intentos < 2:
                intentos += 1
                estado, texto = ais.ar.reparar(ais.re_.buscar(err["firma"]))
            arreglado = False
            if estado == "resuelto":
                sys.modules.pop(MODULO_TMP, None)
                try:
                    importlib.import_module(MODULO_TMP).promedio([])
                    arreglado = True
                except Exception:
                    arreglado = False
            if arreglado:
                esenciales.append(_paso(OK, "Me arreglo de verdad",
                                        f"escribí el arreglo y una prueba, demostré que falla antes y pasa después, "
                                        f"lo apliqué y ya no falla ({time.time() - t0:.0f}s)"))
            else:
                como = ("con la nube suele salir; dime 'usa la nube para programar'" if not es_nube
                        else "vuelve a intentarlo; si se repite, pásale este mensaje a quien te ayude con mi código")
                esenciales.append(_paso(MAL, "Me arreglo de verdad", texto or estado, como))
        elif err:
            _paso(AVISO, "Me arreglo de verdad", "no lo pude probar porque no hay modelo de código")
            esenciales.append(MAL)

    # 4) pruebas aprendidas
    pasan, total, fallan = _correr_pruebas_aprendidas()
    if total == 0:
        _paso(AVISO, "Vigilo que los errores no vuelvan", "todavía no arreglé ningún error real, así que no hay pruebas guardadas")
    elif fallan:
        _paso(MAL, "Vigilo que los errores no vuelvan", f"{len(fallan)} de {total} volvieron: {', '.join(fallan[:5])}",
              "dime 'reparate' (o 'deshaz el ultimo cambio' si fue un cambio mío)")
    else:
        _paso(OK, "Vigilo que los errores no vuelvan", f"las {total} pruebas de errores que ya arreglé siguen pasando")

    # 5) git
    try:
        from core.IA import git_arche
        if not git_arche.activo():
            _paso(AVISO, "Guardo historial en git", "los commits automáticos están apagados", "dime 'activa los commits'")
        elif git_arche.raiz_repo() is None:
            _paso(AVISO, "Guardo historial en git", "mi carpeta no es un repositorio git o git no está instalado",
                  "igual guardo respaldos .bak; para el historial instala git")
        else:
            n = len(git_arche.historial(50))
            _paso(OK, "Guardo historial en git", f"{n} cambio(s) míos guardados ('historial de autocambios')")
    except Exception as e:
        _paso(AVISO, "Guardo historial en git", f"no pude revisarlo ({e})")

    # 6) modo automatico
    if mejora_continua.nivel() == "total":
        _paso(OK, "Me reparo sola sin que me lo pidas", "modo total encendido (trabajo cuando llevas 5 min sin escribirme)")
    else:
        _paso(AVISO, "Me reparo sola sin que me lo pidas", f"estoy en modo '{mejora_continua.nivel()}'",
              "dime 'mejorate sola'")

    # resumen de errores reales
    try:
        from core.IA import registro_errores
        todos = registro_errores.todos()
        cuenta = {}
        for e in todos:
            cuenta[e.get("estado")] = cuenta.get(e.get("estado"), 0) + 1
        if todos:
            print(f"       Errores reales hasta hoy: {cuenta.get('resuelto', 0)} arreglados, "
                  f"{cuenta.get('pendiente', 0)} pendientes, "
                  f"{cuenta.get('no_pude', 0) + cuenta.get('necesita_humano', 0)} para ti ('errores registrados').")
    except Exception:
        pass

    print()
    bien = all(e == OK for e in esenciales)
    if bien:
        _msg(f"Funciono: me arreglé sola un error de verdad en {time.time() - inicio:.0f}s. "
             f"Lo de la prueba ya lo borré.")
    else:
        _msg("Algo de lo esencial no está bien (los ❌ de arriba). Haz lo que dice la flecha y pídeme "
             "'verifica tu autonomia' otra vez.")
    return bien


# ------------------------------------------------------------------
# Comando
# ------------------------------------------------------------------

def _norm(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[¿?¡!,.;:]", " ", t).split())


_R_VERIFICAR = re.compile(
    r"^(?:verifica(?:te)?\s+tu\s+autonomia|prueba\s+tu\s+auto(?:r)?reparacion|verifica\s+tu\s+auto(?:r)?reparacion|"
    r"te\s+funciona\s+la\s+auto(?:r)?reparacion|funciona\s+tu\s+auto(?:r)?reparacion|sirve\s+tu\s+auto(?:r)?reparacion|"
    r"como\s+se\s+que\s+(?:te\s+)?(?:reparas|arreglas|funcionas)(?:\s+sola)?|"
    r"comprueba\s+que\s+te\s+(?:reparas|arreglas)(?:\s+sola)?|autoverificacion|autoverificate)$")


def manejar(comando):
    if _R_VERIFICAR.match(_norm(comando)):
        verificar()
        return ("verificar_autonomia", None)
    return None


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ_APP))
    verificar()
