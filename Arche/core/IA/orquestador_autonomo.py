"""
orquestador_autonomo.py
-------------------------
Ubicación: Arche/core/IA/orquestador_autonomo.py

Motor de Autonomía de Arché:
Modifica archivos directamente usando la API de Ollama, respaldado por 
un sistema de backups preventivos y Smoke Tests (AST) con auto-rollback.

REGLAS OBLIGATORIAS DE REPARACIÓN:
1. Si falta una función o variable (NameError), DEBES definir la función directamente en el archivo fallido.
2. NO agregues sentencias 'import' hacia funciones que no existan previamente en otros módulos.
3. Genera código Python válido en UTF-8 puro, sin usar caracteres especiales o acentos en cadenas de texto si no es necesario.

"""

import ast
import json
import urllib.request
import urllib.parse
import sys
from datetime import datetime
from pathlib import Path

# Configuración de importación de la raíz (Arche/)
_RAIZ_APP = Path(__file__).resolve().parents[2]
if str(_RAIZ_APP) not in sys.path:
    sys.path.insert(0, str(_RAIZ_APP))

from core.IA.proponer_cambio_codigo import RAIZ_APP, ARCHIVOS_PROTEGIDOS

DIR_IA = Path(__file__).parent
DIR_BACKUPS = DIR_IA / "backups_codigo"
DIR_BACKUPS.mkdir(exist_ok=True, parents=True)

IGNORAR_CARPETAS = {
    "__pycache__", ".git", "venv", ".venv", "env", "modelos", "Database",
    "backups_codigo", "backups_autoconocimiento", "build", "dist"
}


# ==============================================================================
# 1. MAPEO DEL PROYECTO
# ==============================================================================

def obtener_mapa_proyecto():
    """Recorre Arché/ y extrae la estructura de archivos."""
    mapa = {}
    for archivo in RAIZ_APP.rglob("*.py"):
        rel = archivo.relative_to(RAIZ_APP).as_posix()
        if any(p in IGNORAR_CARPETAS for p in archivo.parts) or rel in ARCHIVOS_PROTEGIDOS:
            continue
        try:
            contenido = archivo.read_text(encoding="utf-8")
            arbol = ast.parse(contenido, filename=str(archivo))
            funciones = [n.name for n in ast.walk(arbol) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            clases = [n.name for n in ast.walk(arbol) if isinstance(n, ast.ClassDef)]
            mapa[rel] = {"clases": clases, "funciones": funciones}
        except Exception:
            continue
    return mapa


# ==============================================================================
# 2. SEGURIDAD, BACKUP Y SMOKE TEST
# ==============================================================================

def crear_backup_emergencia(archivo_rel):
    """Crea una copia física antes de modificar cualquier código."""
    ruta_origen = RAIZ_APP / archivo_rel
    if not ruta_origen.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_backup = f"{archivo_rel.replace('/', '_')}_{timestamp}.bak"
    ruta_backup = DIR_BACKUPS / nombre_backup
    ruta_backup.write_text(ruta_origen.read_text(encoding="utf-8"), encoding="utf-8")
    return ruta_backup


def restaurar_backup_emergencia(archivo_rel, ruta_backup):
    """Restaura el archivo si la modificación falla la compilación."""
    if ruta_backup and ruta_backup.exists():
        ruta_destino = RAIZ_APP / archivo_rel
        ruta_destino.write_text(ruta_backup.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    return False


def validar_smoke_test(archivo_rel):
    """Verifica sintaxis y validez del árbol sintáctico (AST)."""
    ruta_abs = RAIZ_APP / archivo_rel
    if not ruta_abs.exists():
        return False, f"El archivo {archivo_rel} no existe tras la operación."

    try:
        contenido = ruta_abs.read_text(encoding="utf-8")
        ast.parse(contenido, filename=str(ruta_abs))
    except SyntaxError as se:
        return False, f"SyntaxError en línea {se.lineno}: {se.msg}"
    except Exception as e:
        return False, f"Error en lectura de AST: {str(e)}"

    return True, "Sintaxis válida."


# ==============================================================================
# 3. MOTOR DE EDICIÓN VÍA OLLAMA API
# ==============================================================================

def modificar_codigo_con_ollama(instruccion: str, archivo_target: str, modelo: str = "arche-lora") -> tuple[bool, str]:
    """
    Envía el contenido actual del archivo a Ollama y reescribe el archivo con el código generado.
    """
    ruta_abs = RAIZ_APP / archivo_target
    contenido_actual = ""
    if ruta_abs.exists():
        contenido_actual = ruta_abs.read_text(encoding="utf-8")

    prompt = (
        f"Eres un asistente experto en Python. Tu tarea es modificar el código del archivo de forma precisa.\n\n"
        f"CÓDIGO ACTUAL DE {archivo_target}:\n"
        f"```python\n{contenido_actual}\n```\n\n"
        f"INSTRUCCIÓN: {instruccion}\n\n"
        f"REGLAS:\n"
        f"1. Devuelve ÚNICAMENTE el código Python completo y modificado dentro de un bloque ```python ... ```.\n"
        f"2. No agregues explicaciones, saludos ni texto adicional fuera del bloque de código."
    )

    datos = json.dumps({
        "model": modelo,
        "prompt": prompt,
        "stream": False
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=datos,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as respuesta:
            res_json = json.loads(respuesta.read().decode("utf-8"))
            texto_generado = res_json.get("response", "")

            # Extraer el bloque ```python ```
            if "```python" in texto_generado:
                codigo_nuevo = texto_generado.split("```python")[1].split("```")[0].strip()
            elif "```" in texto_generado:
                codigo_nuevo = texto_generado.split("```")[1].split("```")[0].strip()
            else:
                codigo_nuevo = texto_generado.strip()

            if not codigo_nuevo:
                return False, "Ollama devolvió un código vacío."

            # Escribir el nuevo código en el archivo de destino
            ruta_abs.write_text(codigo_nuevo + "\n", encoding="utf-8")
            return True, "Código actualizado correctamente."

    except Exception as e:
        return False, f"Error en la conexión con Ollama: {str(e)}"


# ==============================================================================
# 4. ORQUESTADOR AUTÓNOMO
# ==============================================================================

class OrquestadorAutonomo:
    def __init__(self, reintentos_max=3):
        self.reintentos_max = reintentos_max

    def _inferir_archivo_objetivo(self, orden_usuario):
        """Infiere el archivo a modificar en base a la orden del usuario."""
        for rel in obtener_mapa_proyecto().keys():
            if Path(rel).name.lower() in orden_usuario.lower() or rel.lower() in orden_usuario.lower():
                return rel

        try:
            from core.IA.enrutar_cambio import enrutar_instruccion
            archivo = enrutar_instruccion(orden_usuario)
            if archivo:
                return archivo
        except Exception:
            pass

        return "core/utilidades.py"

    def ejecutar_meta(self, orden_usuario: str):
        print("\n" + "=" * 60)
        print(f"🤖 [ORQUESTADOR AUTÓNOMO] Meta: '{orden_usuario}'")
        print("=" * 60)

        archivo_target = self._inferir_archivo_objetivo(orden_usuario)
        print(f"🎯 Archivo seleccionado: {archivo_target}")

        backup_file = crear_backup_emergencia(archivo_target)
        print("📝 Backup preventivo creado.")

        print(f"⚙️ Procesando modificación vía Ollama local...")
        exito, msj = modificar_codigo_con_ollama(orden_usuario, archivo_target)

        if not exito:
            print(f"❌ Error durante la generación:\n{msj}")
            if backup_file:
                restaurar_backup_emergencia(archivo_target, backup_file)
            return False

        ok_test, detalle_test = validar_smoke_test(archivo_target)
        if ok_test:
            print(f"✅ Smoke Test APROBADO: {detalle_test}")
            print("🎉 Cambio aplicado e integrado exitosamente.")
            return True
        else:
            print(f"⚠️ Smoke Test FALLIDO: {detalle_test}")
            print("🔄 Ejecutando rollback...")
            restaurar_backup_emergencia(archivo_target, backup_file)
            return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        meta = " ".join(sys.argv[1:])
        orquestador = OrquestadorAutonomo()
        orquestador.ejecutar_meta(meta)
    else:
        print("Uso: python core/IA/orquestador_autonomo.py \"<instrucción>\"")