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

Subir a GitHub (push) solo pasa cuando tú lo pides: «sube los cambios a github».
Antes de subir revisa que no vayan claves/tokens, archivos gigantes ni cambios raros
(guardián). Si algo no cuadra, NO sube nada y te dice por qué.

Comandos:
  historial de autocambios / que commits hiciste    -> ultimos commits de Arché
  activa los commits automaticos / desactiva ...    -> prende o apaga los commits
  sube los cambios a github / sube al repo          -> commit + push de todo lo nuevo
  que hay sin subir                                 -> lista lo que falta subir
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
    if _R_SUBIR.match(t):
        ok, texto = subir()
        print("Arché: " + texto)
        return ("git_subir", ok)
    if _R_PENDIENTE.match(t):
        print("Arché: " + texto_pendientes())
        return ("git_pendiente", None)
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


# ------------------------------------------------------------------
# Subir a GitHub (push)
# ------------------------------------------------------------------


TIMEOUT_RED = 180
MAX_MB = 50                       # GitHub rechaza archivos de más de 100 MB; 50 ya es sospechoso
IGNORAR_SIEMPRE = ["Arche/logs/", "*.lock", "*.log"]      # registros de arche_fondo.pyw

_SECRETOS = [
    ("token de GitHub", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("token de Telegram", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("clave de OpenAI/Anthropic", re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{30,}")),
    ("clave de Google", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("token JWT (Supabase u otro)", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")),
    ("token de Meta/WhatsApp", re.compile(r"\bEAA[A-Za-z0-9]{60,}")),
    ("llave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("contraseña escrita", re.compile(r"""(?i)\b(password|contrase[nñ]a|clave_secreta|api_key|secret)\s*[=:]\s*["'][^"'\s]{6,}["']""")),
]


def _git_red(raiz, *args):
    """Como _git, pero con más tiempo y sin que git se quede esperando que escribas
    usuario/clave en una consola que no existe (el login lo hace la ventanita de Git)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(raiz), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_RED, env=env)


def _identidad(raiz):
    """Si tú ya configuraste git (user.name), los commits salen a tu nombre; si no, como Arché."""
    r = _git_red(raiz, "config", "user.name")
    if r.returncode == 0 and r.stdout.strip():
        return []
    return ["-c", f"user.name={AUTOR_NOMBRE}", "-c", f"user.email={AUTOR_CORREO}"]


def _asegurar_gitignore(raiz):
    ruta = raiz / ".gitignore"
    try:
        actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    except OSError:
        return
    faltan = [l for l in IGNORAR_SIEMPRE if l not in actual.splitlines()]
    if faltan:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(("\n" if actual and not actual.endswith("\n") else "") +
                    "# Registros de Arché en segundo plano\n" + "\n".join(faltan) + "\n")


def _arreglar_estado(raiz):
    """Si una subida anterior quedó a medias (rebase sin terminar), la deshace primero."""
    git_dir = raiz / ".git"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        _git_red(raiz, "rebase", "--abort")


def _sacar_ignorados(raiz):
    """Archivos que .gitignore dice que no van (registros, etc.) pero que quedaron dentro del repo
    en una subida vieja: los saca del repo SIN borrarlos de tu PC."""
    r = _git(raiz, "ls-files", "-ci", "--exclude-standard", "-z")
    sobran = [x for x in r.stdout.split("\0") if x]
    if sobran:
        _git(raiz, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", *sobran)


def _revisar_preparados(raiz):
    """Revisa lo que se va a subir. Devuelve lista de problemas (vacía = todo bien)."""
    problemas = []
    r = _git(raiz, "diff", "--cached", "--name-only", "--diff-filter=AM", "-z")
    for rel in [x for x in r.stdout.split("\0") if x]:
        ruta = raiz / rel
        try:
            if ruta.stat().st_size > MAX_MB * 1024 * 1024:
                problemas.append(f"{rel}: pesa más de {MAX_MB} MB")
        except OSError:
            pass
    # solo las líneas NUEVAS (lo que ya estaba subido no se vuelve a revisar)
    r = _git(raiz, "diff", "--cached", "-U0", "--no-color", "--diff-filter=AM")
    archivo = "?"
    for linea in r.stdout.splitlines():
        if linea.startswith("+++ "):
            archivo = linea[6:] if linea.startswith("+++ b/") else linea[4:]
        elif linea.startswith("+") and not linea.startswith("+++"):
            for nombre, patron in _SECRETOS:
                if patron.search(linea):
                    problemas.append(f"{archivo}: parece tener un {nombre}")
                    break
    return sorted(set(problemas))


def _guardian_ok():
    try:
        from core.seguridad import guardian
        r = guardian.verificar()
        if r.get("sellado") and guardian.hay_alerta(r):
            return False
    except Exception:
        pass
    return True


def pendientes():
    """Archivos que cambiaron y todavía no están en GitHub: [(estado, ruta)]."""
    raiz = raiz_repo()
    if raiz is None:
        return []
    r = _git(raiz, "status", "--porcelain")
    return [(l[:2].strip(), l[3:]) for l in r.stdout.splitlines() if l.strip()]


def texto_pendientes():
    if raiz_repo() is None:
        return _SIN_REPO
    raiz = raiz_repo()
    _asegurar_gitignore(raiz)
    p = pendientes()
    adelante = _git(raiz, "rev-list", "--count", "@{u}..HEAD").stdout.strip()
    if not p and adelante in ("", "0"):
        return "Todo está subido: GitHub tiene lo mismo que tu PC."
    nombres = {"M": "cambió", "A": "nuevo", "D": "borrado", "??": "nuevo", "R": "renombrado"}
    lineas = [f"{len(p)} archivo(s) sin subir:"] + [f"  • {nombres.get(e, e)}: {r}" for e, r in p[:15]]
    if len(p) > 15:
        lineas.append(f"  … y {len(p) - 15} más")
    if adelante not in ("", "0"):
        lineas.append(f"Además hay {adelante} commit(s) hechos que falta empujar.")
    lineas.append("Di «sube los cambios a github» para subirlos.")
    return "\n".join(lineas)


_SIN_REPO = ("Mi carpeta no es un clon de git, así que no puedo subir nada. Instala Git for Windows y "
             "clona tu repo:  git clone https://github.com/danifon446-crypto/Arch-IA  (y usa esa carpeta).")


def subir(mensaje=None):
    """git add + commit + pull --rebase + push. Devuelve (ok, texto para decirte)."""
    raiz = raiz_repo()
    if raiz is None:
        return False, _SIN_REPO
    if not _git(raiz, "remote").stdout.strip():
        return False, "El repo no tiene conexión con GitHub (no hay «origin»)."
    if not _guardian_ok():
        return False, ("No subo nada todavía: hay archivos cambiados que el guardián no ha aprobado. "
                       "Dale al botón «⇪ Subir a GitHub» de la burbuja (o al del ícono) y te pregunto "
                       "ahí si fuiste tú, con un botón para aprobar y subir.")
    try:
        _arreglar_estado(raiz)
        _asegurar_gitignore(raiz)
        _git(raiz, "add", "-A")
        _sacar_ignorados(raiz)
        hay_cambios = _git(raiz, "diff", "--cached", "--quiet").returncode != 0
        if hay_cambios:
            problemas = _revisar_preparados(raiz)
            if problemas:
                _git(raiz, "reset", "-q")                      # deja todo como estaba, sin subir
                return False, ("No subí nada porque encontré esto:\n  • " + "\n  • ".join(problemas[:10]) +
                               "\nSaca eso del archivo (o agrégalo a .gitignore) y me lo vuelves a pedir.")
            archivos = [x for x in _git(raiz, "diff", "--cached", "--name-only").stdout.splitlines() if x]
            if not mensaje:
                muestra = ", ".join(os.path.basename(a) for a in archivos[:4])
                mensaje = f"Arché: {len(archivos)} archivo(s) — {muestra}{'…' if len(archivos) > 4 else ''}"
            r = _git_red(raiz, *_identidad(raiz), "commit", "--no-verify", "-m", mensaje[:2000])
            if r.returncode != 0:
                return False, "No pude hacer el commit: " + (r.stderr or r.stdout).strip()[-250:]
        # traer lo que haya en GitHub (por ejemplo cambios del celular) antes de subir
        r = _git_red(raiz, "pull", "--rebase", "--autostash")
        if r.returncode != 0:
            _git_red(raiz, "rebase", "--abort")
            return False, ("GitHub tiene cambios que chocan con los tuyos y no los quise mezclar a ciegas. "
                           "Tus cambios están guardados en tu PC. Detalle: " + (r.stderr or r.stdout).strip()[-200:])
        # lo que vino de GitHub también puede traer archivos que no deben estar (registros viejos)
        _sacar_ignorados(raiz)
        if _git(raiz, "diff", "--cached", "--quiet").returncode != 0:
            _git_red(raiz, *_identidad(raiz), "commit", "--no-verify", "-q", "-m",
                     "Arché: saco del repo los registros y archivos ignorados")
            hay_cambios = True
        r = _git_red(raiz, "push")
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip()
            if "Authentication" in err or "could not read Username" in err or "403" in err:
                return False, ("GitHub no me dejó entrar. Abre una terminal, haz un  git push  una vez "
                               "e inicia sesión en la ventanita de GitHub; después ya lo hago yo sola.")
            if "no upstream" in err:
                r = _git_red(raiz, "push", "-u", "origin", "HEAD")
                if r.returncode == 0:
                    return True, "Subido a GitHub."
            return False, "No pude subir: " + err[-250:]
        if not hay_cambios and "Everything up-to-date" in (r.stderr + r.stdout):
            return True, "No había nada nuevo: GitHub ya tiene todo."
        h = _git(raiz, "rev-parse", "--short", "HEAD").stdout.strip()
        return True, f"Listo, subí los cambios a GitHub (commit {h})."
    except subprocess.TimeoutExpired:
        return False, "Se demoró demasiado (¿internet lento?). No se perdió nada; inténtalo otra vez."
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"No pude subir ({type(e).__name__}: {e})."


_R_SUBIR = re.compile(r"^(?:arche\s+)?(?:sube|subir|subelo|subelos|manda|empuja|guarda|actualiza|sincroniza)"
                      r"(?:\s+(?:los|mis|tus|todos\s+los|el|la))?\s*(?:cambios|archivos|codigo|todo|repo|repositorio)?"
                      r"\s*(?:a|al|en|con)?\s*(?:el\s+)?(?:github|repo|repositorio)$|^(?:haz\s+)?(?:git\s+)?push$")
_R_PENDIENTE = re.compile(r"^(?:que\s+(?:hay|falta|archivos\s+hay)\s+(?:sin|por)\s+subir|"
                          r"que\s+falta\s+subir(?:\s+a\s+github)?|estado\s+del\s+repo(?:sitorio)?)$")
