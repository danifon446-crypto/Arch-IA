"""
generar_changelog.py
---------------------
Ubicacion real en tu proyecto: Arche/core/IA/generar_changelog.py
(fijate: el archivo que subiste se llama "generar_chagelog.py", con una
letra de menos -- te recomiendo renombrarlo a "generar_changelog.py" para
que coincida con lo que espera introspeccion.py en su lista IGNORAR).

Genera automaticamente una entrada de changelog para Arche a partir del
historial de commits de git, usando Ollama (tu funcion real: conversar())
para redactarla en lenguaje natural. Nunca se guarda sin que vos la
confirmes o edites primero.

CORREGIDO respecto a la version anterior:
  1. Ya no busca ".git" en su propia carpeta (core/IA) -- ahora usa
     "git rev-parse --show-toplevel", que encuentra el repo real sin
     importar cuantos niveles de carpetas haya en el medio.
  2. Usa la funcion real de tu ollamaIA.py: conversar(prompt), importada
     como "from core.IA.ollamaIA import conversar" (import absoluto de
     paquete, igual que hace main.py), agregando la raiz del proyecto
     a sys.path para que el import funcione sin importar desde donde
     ejecutes este script.

Uso (desde cualquier carpeta dentro del proyecto):
    python core/IA/generar_changelog.py
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import date

# Este archivo vive en Arche/core/IA/generar_changelog.py
# parents[2] = Arche (la raiz real de la app, donde esta main.py)
RAIZ_APP = Path(__file__).resolve().parents[2]
HISTORIAL_PATH = Path(__file__).parent / "historial_versiones.json"

# Agregamos la raiz de la app a sys.path para poder hacer
# "from core.IA.ollamaIA import conversar" sin importar desde donde
# se ejecute este script.
if str(RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(RAIZ_APP))


def cargar_historial():
    if not HISTORIAL_PATH.exists():
        return []
    with open(HISTORIAL_PATH, "r", encoding="utf-8") as f:
        contenido = f.read().strip()
        return json.loads(contenido) if contenido else []


def guardar_historial(historial):
    with open(HISTORIAL_PATH, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)


def ultima_version_confirmada(historial):
    confirmadas = [h for h in historial if h.get("confirmada")]
    return confirmadas[-1] if confirmadas else None


def hay_repo_git():
    """Confirma que exista un repositorio git en algun nivel arriba de
    RAIZ_APP, sin usar la salida de texto de git como ruta (en Windows
    esa salida puede llegar con la codificacion de caracteres rota,
    ej. la 'e' de 'Arche', y producir una ruta invalida -> WinError 267).
    En vez de eso, usamos RAIZ_APP directamente como cwd para todo:
    git encuentra el repositorio real solo, sin importar los niveles
    de carpetas en el medio."""
    try:
        resultado = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=str(RAIZ_APP),
        )
        return resultado.returncode == 0
    except FileNotFoundError:
        return False


def commits_desde(commit_hash, cwd):
    rango = f"{commit_hash}..HEAD" if commit_hash else "HEAD"
    try:
        salida = subprocess.run(
            ["git", "log", rango, "--pretty=format:%H|%s"],
            capture_output=True, text=True, check=True, cwd=cwd,
            encoding="utf-8", errors="replace",
        )
    except subprocess.CalledProcessError as e:
        print("Error al leer commits de git:", e.stderr)
        sys.exit(1)
    lineas = [l for l in salida.stdout.splitlines() if l.strip()]
    commits = []
    for l in lineas:
        h, msg = l.split("|", 1)
        commits.append({"hash": h, "mensaje": msg})
    return commits


def obtener_diff(commit_hash, cwd):
    cmd = ["git", "diff", f"{commit_hash}..HEAD"] if commit_hash else ["git", "diff", "HEAD~1..HEAD"]
    salida = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd,
        encoding="utf-8", errors="replace",
    )
    return salida.stdout


def archivos_modificados(commit_hash, cwd):
    rango = f"{commit_hash}..HEAD" if commit_hash else "HEAD~1..HEAD"
    salida = subprocess.run(
        ["git", "diff", "--name-only", rango],
        capture_output=True, text=True, cwd=cwd,
        encoding="utf-8", errors="replace",
    )
    return [f for f in salida.stdout.splitlines() if f.strip()]


def siguiente_numero_version(historial):
    """Incrementa el ULTIMO segmento del numero de version, sin importar
    si tiene 2 partes (0.1 -> 0.2) o 3 partes (2.0.1 -> 2.0.2)."""
    if not historial:
        return "0.1"
    ultima = historial[-1]["version"]
    partes = ultima.split(".")
    try:
        partes[-1] = str(int(partes[-1]) + 1)
        return ".".join(partes)
    except ValueError:
        return ultima + ".1"


def redactar_con_ollama(commits, diff, archivos):
    try:
        from core.IA.ollamaIA import conversar
    except ImportError as e:
        print(f"No pude importar 'conversar' desde core.IA.ollamaIA: {e}")
        print("Verifica que este script se encuentre en Arche/core/IA/")
        sys.exit(1)

    mensajes_commits = "\n".join(f"- {c['mensaje']}" for c in commits)
    diff_recortado = diff[:4000]

    prompt = f"""Sos Arche, un asistente que describe sus propias mejoras de forma honesta y breve.

Archivos modificados: {', '.join(archivos) if archivos else 'ninguno detectado'}

Mensajes de commit:
{mensajes_commits}

Fragmento del diff de codigo (puede estar incompleto):
{diff_recortado}

Redacta una lista de 1 a 5 vinetas cortas (maximo 20 palabras cada una)
describiendo QUE cambio, en primera persona ("Cambie...", "Corregi...",
"Agregue..."). No inventes cambios que no esten reflejados en los commits
o el diff. Responde SOLO con las vinetas, una por linea, sin numeracion
ni texto adicional."""

    respuesta = conversar(prompt, num_predict=300)
    lineas = [l.strip("-*• ").strip() for l in respuesta.splitlines() if l.strip()]
    return lineas


def main():
    if not hay_repo_git():
        print("No encontre un repositorio git desde esta ubicacion.")
        print("Verifica que exista un .git en algun nivel arriba (ver GUIA_GIT.md).")
        sys.exit(1)

    cwd_git = str(RAIZ_APP)  # RAIZ_APP ya esta bien codificada; git encuentra el repo real solo

    historial = cargar_historial()
    ultima = ultima_version_confirmada(historial)
    hash_base = ultima.get("commit_hash") if ultima else None

    commits = commits_desde(hash_base, cwd_git)
    if not commits:
        print("No hay commits nuevos desde la ultima version registrada.")
        return

    diff = obtener_diff(hash_base, cwd_git)
    archivos = archivos_modificados(hash_base, cwd_git)
    nueva_version = siguiente_numero_version(historial)

    print(f"\nArche: Revise el historial desde la ultima vez que actualice mi "
          f"registro. Encontre {len(commits)} commit(s) y cambios en: "
          f"{', '.join(archivos) if archivos else 'sin archivos detectados'}.\n")

    cambios = redactar_con_ollama(commits, diff, archivos)

    print(f"Version {nueva_version} - {date.today().isoformat()}")
    for c in cambios:
        print(f"  - {c}")

    hash_actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=cwd_git,
        encoding="utf-8", errors="replace",
    ).stdout.strip()

    while True:
        resp = input("\n¿Confirmas esta entrada tal cual, la editas o la descartas? [s/e/n]: ").strip().lower()
        if resp == "s":
            entrada = {
                "version": nueva_version,
                "fecha": date.today().isoformat(),
                "cambios": cambios,
                "commit_hash": hash_actual,
                "confirmada": True,
            }
            historial.append(entrada)
            guardar_historial(historial)
            print(f"Arche: Listo, guarde la version {nueva_version} en mi historial.")
            break
        elif resp == "e":
            print("Edita cada linea (Enter vacio para dejarla igual):")
            nuevas = []
            for c in cambios:
                edit = input(f"  [{c}] -> ")
                nuevas.append(edit if edit.strip() else c)
            cambios = nuevas
            continue
        elif resp == "n":
            print("Descartado. No se guardo ninguna entrada.")
            break
        else:
            print("Responde 's', 'e' o 'n'.")


if __name__ == "__main__":
    main()