"""
generar_changelog.py
---------------------
Genera automaticamente una entrada de changelog para Arche a partir del
historial de commits de git, usando Ollama para redactarla en lenguaje
natural. Nunca se guarda sin que vos la confirmes o edites primero
(Opcion C: automatico con validacion minima).

Requisitos:
    - El proyecto debe estar versionado con git (ver GUIA_GIT.md).
    - ollamaIA.py debe existir en el mismo directorio.
    - IMPORTANTE: revisa la funcion redactar_con_ollama() mas abajo y
      ajusta el nombre de la funcion que usas para consultar a Ollama
      (se asume una funcion `preguntar(prompt) -> str`).

Uso:
    python generar_changelog.py
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import date

HISTORIAL_PATH = Path(__file__).parent / "historial_versiones.json"


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


def commits_desde(commit_hash):
    rango = f"{commit_hash}..HEAD" if commit_hash else "HEAD"
    try:
        salida = subprocess.run(
            ["git", "log", rango, "--pretty=format:%H|%s"],
            capture_output=True, text=True, check=True
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


def obtener_diff(commit_hash):
    cmd = ["git", "diff", f"{commit_hash}..HEAD"] if commit_hash else ["git", "diff", "HEAD~1..HEAD"]
    salida = subprocess.run(cmd, capture_output=True, text=True)
    return salida.stdout


def archivos_modificados(commit_hash):
    rango = f"{commit_hash}..HEAD" if commit_hash else "HEAD~1..HEAD"
    salida = subprocess.run(
        ["git", "diff", "--name-only", rango],
        capture_output=True, text=True
    )
    return [f for f in salida.stdout.splitlines() if f.strip()]


def siguiente_numero_version(historial):
    if not historial:
        return "0.1"
    ultima = historial[-1]["version"]
    try:
        mayor, menor = ultima.split(".")
        return f"{mayor}.{int(menor) + 1}"
    except ValueError:
        return ultima + ".1"


def redactar_con_ollama(commits, diff, archivos):
    # --- AJUSTAR ESTE IMPORT AL NOMBRE REAL DE TU FUNCION EN ollamaIA.py ---
    try:
        from ollamaIA import preguntar  # <-- cambiar 'preguntar' si tu funcion se llama distinto
    except ImportError:
        print("No pude importar una funcion 'preguntar' desde ollamaIA.py.")
        print("Abri este script y ajusta el import en redactar_con_ollama()")
        print("para que apunte al nombre real de tu funcion de consulta a Ollama.")
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

    respuesta = preguntar(prompt)
    lineas = [l.strip("-*• ").strip() for l in respuesta.splitlines() if l.strip()]
    return lineas


def main():
    if not (Path(__file__).parent / ".git").exists():
        print("No encontre un repositorio git en esta carpeta.")
        print("Corre 'git init' primero (ver GUIA_GIT.md).")
        sys.exit(1)

    historial = cargar_historial()
    ultima = ultima_version_confirmada(historial)
    hash_base = ultima.get("commit_hash") if ultima else None

    commits = commits_desde(hash_base)
    if not commits:
        print("No hay commits nuevos desde la ultima version registrada.")
        return

    diff = obtener_diff(hash_base)
    archivos = archivos_modificados(hash_base)
    nueva_version = siguiente_numero_version(historial)

    print(f"\nArche: Revise el historial desde la ultima vez que actualice mi "
          f"registro. Encontre {len(commits)} commit(s) y cambios en: "
          f"{', '.join(archivos) if archivos else 'sin archivos detectados'}.\n")

    cambios = redactar_con_ollama(commits, diff, archivos)

    print(f"Version {nueva_version} - {date.today().isoformat()}")
    for c in cambios:
        print(f"  - {c}")

    hash_actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
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