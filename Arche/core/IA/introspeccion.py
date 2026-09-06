"""
introspeccion.py
-----------------
Ubicacion real en tu proyecto: Arche/core/IA/introspeccion.py

Analiza el codigo fuente de TODO el proyecto Arche (recursivamente, sin
importar desde que carpeta lo ejecutes) para medir que proporcion de sus
funciones dependen de Ollama frente a las que son deterministas/locales.

CORREGIDO respecto a la version anterior: antes usaba directorio="." que
dependia de desde donde corrieras el script (por eso si lo corrias desde
core/IA solo veia los .py de esa carpeta). Ahora calcula la raiz real del
proyecto (la carpeta Arche/, dos niveles arriba de este archivo) y recorre
todo de forma recursiva con rglob.

Uso:
    python core/IA/introspeccion.py   (desde la carpeta Arche/, o desde
                                        cualquier lado, ya no importa)
    o bien, importado desde main.py:
        from core.IA.introspeccion import reporte_texto
        print(reporte_texto())
"""

import ast
from pathlib import Path

# AJUSTAR si tu modulo de conexion con Ollama tiene otro nombre de archivo
MODULO_OLLAMA = "ollamaIA"

# Este archivo vive en Arche/core/IA/introspeccion.py
# parents[0] = core/IA, parents[1] = core, parents[2] = Arche (raiz real)
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Nombres de archivo que no tiene sentido analizar
IGNORAR_ARCHIVOS = {
    "introspeccion.py",
    "generar_changelog.py",
    "generar_chagelog.py",  # nombre actual con la erratita, por si acaso
    "__init__.py",
}

# Carpetas que no queremos recorrer (entornos virtuales, cache, etc.)
IGNORAR_CARPETAS = {"__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database"}


class DetectorDependenciaOllama(ast.NodeVisitor):
    def __init__(self):
        self.alias_modulo = set()
        self.funciones_totales = []
        self._depende_actual = False
        self._funcion_actual = None

    def visit_Import(self, node):
        for alias in node.names:
            # cubre tanto "import ollamaIA" como "import core.IA.ollamaIA"
            if alias.name == MODULO_OLLAMA or alias.name.endswith("." + MODULO_OLLAMA):
                self.alias_modulo.add(alias.asname or alias.name.split(".")[-1])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        modulo = node.module or ""
        if modulo == MODULO_OLLAMA or modulo.endswith("." + MODULO_OLLAMA):
            for alias in node.names:
                self.alias_modulo.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        func_anterior = self._funcion_actual
        depende_anterior = self._depende_actual
        self._funcion_actual = node.name
        self._depende_actual = False

        self.generic_visit(node)

        self.funciones_totales.append((self._funcion_actual, self._depende_actual))
        self._funcion_actual = func_anterior
        self._depende_actual = depende_anterior

    def visit_Call(self, node):
        nombre = self._nombre_llamada(node.func)
        if nombre and (
            nombre in self.alias_modulo
            or nombre.split(".")[0] in self.alias_modulo
        ):
            self._depende_actual = True
        self.generic_visit(node)

    @staticmethod
    def _nombre_llamada(nodo_func):
        if isinstance(nodo_func, ast.Name):
            return nodo_func.id
        if isinstance(nodo_func, ast.Attribute):
            partes = []
            actual = nodo_func
            while isinstance(actual, ast.Attribute):
                partes.append(actual.attr)
                actual = actual.value
            if isinstance(actual, ast.Name):
                partes.append(actual.id)
            return ".".join(reversed(partes))
        return None


def analizar_archivo(ruta: Path):
    try:
        codigo = ruta.read_text(encoding="utf-8")
        arbol = ast.parse(codigo, filename=str(ruta))
    except (SyntaxError, UnicodeDecodeError):
        return []
    detector = DetectorDependenciaOllama()
    detector.visit(arbol)
    return [(str(ruta.relative_to(RAIZ_PROYECTO)), fn, dep) for fn, dep in detector.funciones_totales]


def analizar_proyecto(directorio=None):
    """
    directorio: si no se pasa nada, usa la raiz real del proyecto
    (calculada desde la ubicacion de este archivo, no desde el cwd).
    """
    raiz = Path(directorio) if directorio else RAIZ_PROYECTO
    resultados = []
    for archivo in raiz.rglob("*.py"):
        if archivo.name in IGNORAR_ARCHIVOS:
            continue
        if any(parte in IGNORAR_CARPETAS for parte in archivo.parts):
            continue
        resultados.extend(analizar_archivo(archivo))
    return resultados


def resumen(resultados):
    total = len(resultados)
    if total == 0:
        return {
            "total_funciones": 0,
            "dependientes_ollama": 0,
            "porcentaje_dependencia": 0.0,
            "detalle": [],
        }
    dependientes = [r for r in resultados if r[2]]
    porcentaje = round(100 * len(dependientes) / total, 1)
    return {
        "total_funciones": total,
        "dependientes_ollama": len(dependientes),
        "porcentaje_dependencia": porcentaje,
        "detalle": resultados,
    }


def reporte_texto(directorio=None):
    r = resumen(analizar_proyecto(directorio))
    if r["total_funciones"] == 0:
        return "No encontre funciones para analizar en este directorio."
    independientes = r["total_funciones"] - r["dependientes_ollama"]
    return (
        f"De {r['total_funciones']} funciones analizadas en mi codigo, "
        f"{r['dependientes_ollama']} dependen de Ollama en algun punto "
        f"({r['porcentaje_dependencia']}%) y {independientes} son "
        f"completamente locales/deterministas. (Nota: esto mide dependencia "
        f"directa; una funcion que llama a otra que usa Ollama puede no "
        f"quedar marcada aqui)."
    )


if __name__ == "__main__":
    print(f"Analizando proyecto en: {RAIZ_PROYECTO}\n")
    print(reporte_texto())
    print()
    print("Detalle por funcion:")
    for archivo, funcion, depende in analizar_proyecto():
        marca = "OLLAMA" if depende else "local"
        print(f"  [{marca:6}] {archivo} :: {funcion}")