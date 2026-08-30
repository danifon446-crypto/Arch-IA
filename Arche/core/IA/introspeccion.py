"""
introspeccion.py
-----------------
Analiza el codigo fuente de Arche para medir, de forma real y verificable
(no estimada), que proporcion de sus funciones dependen de Ollama frente
a las que son deterministas/locales.

Como funciona:
    Recorre cada archivo .py del proyecto con el modulo `ast` (analisis
    sintactico de Python, no texto/regex) y detecta, funcion por funcion,
    si en su cuerpo hay una llamada a algo importado desde el modulo de
    Ollama (por defecto: ollamaIA.py).

Limitacion honesta:
    Esto detecta dependencia DIRECTA. Si una funcion A no llama a Ollama
    pero llama a una funcion B que si lo hace, A no queda marcada como
    dependiente en esta version. Es una metrica real pero conservadora,
    no una estimacion inflada.

Uso:
    python introspeccion.py
    o bien, importado desde main.py:
        from introspeccion import reporte_texto
        print(reporte_texto())
"""

import ast
from pathlib import Path

# AJUSTAR si tu modulo de conexion con Ollama tiene otro nombre de archivo
MODULO_OLLAMA = "ollamaIA"

# Archivos que no tiene sentido analizar (este mismo, generador de changelog, etc.)
IGNORAR = {"introspeccion.py", "generar_changelog.py", "__init__.py"}


class DetectorDependenciaOllama(ast.NodeVisitor):
    def __init__(self):
        self.alias_modulo = set()
        self.funciones_totales = []
        self._depende_actual = False
        self._funcion_actual = None

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == MODULO_OLLAMA:
                self.alias_modulo.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module == MODULO_OLLAMA:
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
    return [(ruta.name, fn, dep) for fn, dep in detector.funciones_totales]


def analizar_proyecto(directorio="."):
    directorio = Path(directorio)
    resultados = []
    for archivo in directorio.glob("*.py"):
        if archivo.name in IGNORAR:
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


def reporte_texto(directorio="."):
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
    print(reporte_texto())
    print()
    print("Detalle por funcion:")
    for archivo, funcion, depende in analizar_proyecto():
        marca = "OLLAMA" if depende else "local"
        print(f"  [{marca:6}] {archivo} :: {funcion}")