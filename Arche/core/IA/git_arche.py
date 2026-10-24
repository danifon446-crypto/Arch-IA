"""
git_arche.py
------------
Ubicacion: Arche/core/IA/git_arche.py

Historial exacto de todo lo que Arché se cambia a si misma, usando git.

Cada cambio automatico (una reparacion, un parche de la mejora continua, la
prueba nueva que demuestra una reparacion, o deshacer un lote) queda como un
commit propio, con autor "Arché (auto)", que solo incluye los archivos que
Arché toco. Tus otros cambios sin commitear NO se meten en esos commits.

Si la carpeta no es un repositorio git, o git no esta instalado, todo sigue
funcionando igual: simplemente no se hace commit (los respaldos .bak de
siempre siguen existiendo).

Nunca hace push: subir los cambios a GitHub lo decides tu.

Comandos:
  historial de autocambios / que commits hiciste    -> ultimos commits de Arché
  activa los commits automaticos / desactiva ...    -> prende o apaga los commits
"""

import json
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from core.rutas import DATABASE

RAIZ_APP = Path(__file__).resolve().parents[2]          # Arche/
ARCHIVO_CONFIG = os.path.join(DATABASE, "git_arche.json")
AUTOR_NOMBRE = "Arché (auto)"
AUTOR_CORREO = "arche@localhost"
TIMEOUT = 60


def _cfg():
    try:
        with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def activo():
    return bool(_cfg().get("activo", True))


def fijar_activo(valor):
    d = _cfg()
    d["activo"] = bool(valor)
    os.makedirs(DATABASE, exist_ok=True)
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def raiz_repo():
    """Carpeta raiz del repositorio git que contiene a Arché, o None."""
    if shutil.which("git") is None:
        return None
    for carpeta in [RAIZ_APP, *RAIZ_APP.parents]:
        if (carpeta / ".git").exists():
            return carpeta
    return None


def _git(raiz, *args):
    return subprocess.run(
        ["git", "-c", f"user.name={AUTOR_NOMBRE}", "-c", f"user.email={AUTOR_CORREO}",
         "-c", "core.quotepath=false", *args],
        cwd=str(raiz), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT,
    )


def commit(archivos_rel_app, mensaje):
    """
    Hace un commit SOLO con esos archivos (rutas relativas a Arche/, como
    'core/notas.py'). Incluye archivos nuevos y borrados.
    Devuelve (ok, texto): texto es el hash corto o el motivo por el que no se hizo.
    """
    if not activo():
        return False, "commits automáticos desactivados"
    raiz = raiz_repo()
    if raiz is None:
        return False, "no es un repositorio git (o git no está instalado)"
    rutas = []
    for rel in archivos_rel_app or []:
        absoluta = (RAIZ_APP / rel).resolve()
        try:
            rutas.append(absoluta.relative_to(raiz).as_posix())
        except ValueError:
            continue
    rutas = sorted(set(rutas))
    if not rutas:
        return False, "no hay archivos para guardar"
    try:
        # add -A sobre esas rutas: agrega nuevos, modificados y borrados
        r = _git(raiz, "add", "-A", "--", *rutas)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()[-300:]
        r = _git(raiz, "diff", "--cached", "--quiet", "--", *rutas)
        if r.returncode == 0:
            return False, "sin cambios que guardar"
        r = _git(raiz, "commit", "--no-verify", "-m", mensaje[:2000], "--only", "--", *rutas)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()[-300:]
        h = _git(raiz, "rev-parse", "--short", "HEAD")
        return True, h.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{type(e).__name__}: {e}"


def historial(n=10):
    """[(hash, fecha, mensaje)] de los ultimos commits automaticos de Arché."""
    raiz = raiz_repo()
    if raiz is None:
        return []
    try:
        r = _git(raiz, "log", f"-{int(n)}", f"--author={AUTOR_CORREO}", "--date=format:%d/%m %H:%M",
                 "--pretty=format:%h\x1f%ad\x1f%s")
    except (OSError, subprocess.SubprocessError):
        return []
    salida = []
    for linea in r.stdout.splitlines():
        partes = linea.split("\x1f")
        if len(partes) == 3:
            salida.append(tuple(partes))
    return salida


# ------------------------------------------------------------------
# Comandos
# ------------------------------------------------------------------

def _norm(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[¿?¡!,.;:]", " ", t).split())


_R_HISTORIAL = re.compile(r"^(?:historial\s+de\s+(?:auto)?cambios|historial\s+de\s+tus\s+cambios|"
                          r"que\s+commits\s+(?:hiciste|has\s+hecho)|tus\s+commits|commits\s+de\s+arche)$")
_R_ON = re.compile(r"^(?:activa|prende|enciende)\s+los\s+commits(?:\s+automaticos)?$")
_R_OFF = re.compile(r"^(?:desactiva|apaga)\s+los\s+commits(?:\s+automaticos)?$")


def manejar(comando):
    t = _norm(comando)
    if _R_HISTORIAL.match(t):
        if raiz_repo() is None:
            print("Arché: Mi carpeta no es un repositorio git (o git no está instalado), así que no llevo historial en commits.")
            return ("historial_git", None)
        h = historial(10)
        if not h:
            print("Arché: Todavía no hice ningún commit automático.")
        else:
            print("Arché: Mis últimos cambios automáticos (en git):")
            for hsh, fecha, msg in h:
                print(f"  • {fecha}  {hsh}  {msg}")
            print("       Para deshacer uno a mano: git revert <hash>")
        return ("historial_git", None)
    if _R_ON.match(t):
        fijar_activo(True)
        print("Arché: Listo, cada cambio que me haga a mí misma quedará como un commit en git.")
        return ("git_commits", True)
    if _R_OFF.match(t):
        fijar_activo(False)
        print("Arché: Listo, ya no hago commits de mis cambios (los respaldos .bak siguen).")
        return ("git_commits", False)
    return None
