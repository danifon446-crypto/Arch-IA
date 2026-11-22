"""
fuentes.py
----------
Ubicacion: Arche/core/nucleo/fuentes.py

Las PLATAFORMAS donde el Depredador sale a cazar. Cada una se busca con su propia API pública y
todas devuelven los repositorios con la MISMA forma (la de GitHub), así el resto del Depredador
no sabe de dónde vino cada presa:

    full_name, html_url, description, topics, license ({"spdx_id": "mit"} o None), size (KB),
    stargazers_count, pushed_at, default_branch, fork, archived,
    fuente ("github" | "gitlab" | "codeberg"), zip_url, licencia_por_archivo (True si la API
    no dice la licencia y hay que leerla del archivo LICENSE ya dentro de la cuarentena)

Plataformas:
  github    api.github.com          (licencia, estrellas y tamaño vienen en la búsqueda)
  gitlab    gitlab.com/api/v4       (licencia y estrellas vienen; el tamaño solo para quien tenga rol)
  codeberg  codeberg.org/api/v1     (Forgejo/Gitea: NO dice la licencia; se lee del archivo LICENSE)

Para agregar otra plataforma: una función buscar_<nombre>(consulta, get) que devuelva esa forma,
y anotarla en FUENTES. Aquí no se baja ni se ejecuta nada: solo se piden listas de repositorios.

Este archivo es parte del núcleo protegido: Arché no lo puede modificar sola.
"""

import urllib.parse

# nombre -> (cómo se llama para la persona, segundos de pausa entre búsquedas, token de la config)
FUENTES = {
    "github": ("GitHub", 2.0, "github_token"),
    "gitlab": ("GitLab", 1.0, "gitlab_token"),
    "codeberg": ("Codeberg", 1.0, "codeberg_token"),
}


def nombre_bonito(fuente):
    return FUENTES.get(fuente, (fuente,))[0]


def pausa(fuente):
    return FUENTES.get(fuente, ("", 1.0))[1]


def _q(texto):
    return urllib.parse.quote(texto or "", safe="")


def _entero(valor):
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------
# GitHub
# ------------------------------------------------------------------

def buscar_github(consulta, get):
    # orden por relevancia (no por estrellas: por estrellas salen repos famosos de otra cosa)
    datos = get(f"https://api.github.com/search/repositories?q={_q(consulta + ' language:python')}&per_page=20")
    salida = []
    for r in datos.get("items", []):
        r = dict(r)
        r["fuente"] = "github"
        r["zip_url"] = (f"https://codeload.github.com/{r.get('full_name')}/zip/refs/heads/"
                        f"{_q(r.get('default_branch') or 'main')}")
        salida.append(r)
    return salida


# ------------------------------------------------------------------
# GitLab
# ------------------------------------------------------------------

def _de_gitlab(r):
    clave = ((r.get("license") or {}).get("key") or "").lower()
    rama = r.get("default_branch") or "main"
    return {
        "full_name": "gitlab.com/" + str(r.get("path_with_namespace", "")),
        "html_url": r.get("web_url", ""),
        "description": r.get("description") or "",
        "topics": r.get("topics") or r.get("tag_list") or [],
        "license": {"spdx_id": clave} if clave else None,
        "licencia_por_archivo": not clave,
        # statistics solo la ven quienes tienen rol en el proyecto: sin dato -> 0 (el límite de descarga protege)
        "size": _entero((r.get("statistics") or {}).get("repository_size")) // 1024,
        "stargazers_count": _entero(r.get("star_count")),
        "pushed_at": r.get("last_activity_at") or "",
        "default_branch": rama,
        "fork": bool(r.get("forked_from_project")),
        "archived": bool(r.get("archived")),
        "fuente": "gitlab",
        "zip_url": f"https://gitlab.com/api/v4/projects/{r.get('id')}/repository/archive.zip?sha={_q(rama)}",
    }


def buscar_gitlab(consulta, get):
    datos = get("https://gitlab.com/api/v4/projects?search=" + _q(consulta) +
                "&order_by=star_count&sort=desc&per_page=20&license=true&with_programming_language=python")
    if not isinstance(datos, list):
        return []
    return [_de_gitlab(r) for r in datos if r.get("id") and r.get("path_with_namespace")]


# ------------------------------------------------------------------
# Codeberg (Forgejo / Gitea)
# ------------------------------------------------------------------

def _de_gitea(r, base):
    rama = r.get("default_branch") or "main"
    host = urllib.parse.urlparse(base).netloc
    nombre = str(r.get("full_name", ""))
    return {
        "full_name": f"{host}/{nombre}",
        "html_url": r.get("html_url", ""),
        "description": r.get("description") or "",
        "topics": r.get("topics") or [],
        "license": None,                              # Forgejo/Gitea no la dicen en la búsqueda
        "licencia_por_archivo": True,
        "size": _entero(r.get("size")),               # ya viene en KB
        "stargazers_count": _entero(r.get("stars_count")),
        "pushed_at": r.get("updated_at") or "",
        "default_branch": rama,
        "fork": bool(r.get("fork")),
        "archived": bool(r.get("archived")),
        "language": r.get("language") or "",
        "fuente": "codeberg",
        "zip_url": f"{base}/api/v1/repos/{nombre}/archive/{_q(rama)}.zip",
    }


def buscar_codeberg(consulta, get, base="https://codeberg.org"):
    datos = get(f"{base}/api/v1/repos/search?q={_q(consulta)}&sort=stars&order=desc&limit=20&mode=source")
    lista = datos.get("data", []) if isinstance(datos, dict) else []
    salida = []
    for r in lista:
        if not r.get("full_name"):
            continue
        if (r.get("language") or "").lower() != "python":     # la búsqueda no filtra por lenguaje
            continue
        salida.append(_de_gitea(r, base))
    return salida


_BUSCADORES = {"github": buscar_github, "gitlab": buscar_gitlab, "codeberg": buscar_codeberg}


def buscar(fuente, consulta, get):
    """Lista de repositorios (forma de GitHub) de esa plataforma. Puede lanzar errores de red:
    quien llama decide qué hacer (el Depredador sigue con las otras plataformas)."""
    return _BUSCADORES[fuente](consulta, get)
