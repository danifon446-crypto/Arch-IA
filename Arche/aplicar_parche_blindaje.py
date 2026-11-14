"""
aplicar_parche_blindaje.py
--------------------------
Se corre UNA vez, con Arché cerrado, desde la carpeta Arche (donde está main.py):

    python aplicar_parche_blindaje.py

EL PROBLEMA QUE ARREGLA
  El bucle principal de main.py no tenía ninguna protección: si CUALQUIER
  orden daba un error inesperado (un módulo con un bug, un archivo dañado,
  internet que se cae a mitad...), Arché se cerraba entero. En segundo
  plano (arche_fondo.pyw) eso significa que Arché desaparece sin avisar.

QUÉ HACE
  Envuelve el cuerpo del bucle en un try/except. Ahora, si una orden falla:
    - Arché te dice que esa orden dio error y SIGUE funcionando,
    - el error queda anotado en registro_errores (el mismo registro que
      usa la autorreparación), con la frase que lo causó,
    - se vacía la cola de pasos pendientes (no sigue una cadena rota).
  "adiós", Ctrl+C y el cierre de la consola funcionan igual que siempre.
  Si hay 8 errores seguidos en 20 segundos (algo está roto de verdad),
  deja pasar el error y se cierra, como antes, en vez de quedarse en bucle.

SEGURIDAD DEL PARCHE
  - Hace copia de respaldo (main_antes_blindaje_FECHA.py).
  - Solo cambia la sangría del bucle (4 espacios más); comprueba con el
    analizador de Python que el código del bucle quedó IDÉNTICO al de antes.
  - Si algo no cuadra, deja main.py como estaba.
  - Se puede correr dos veces sin problema.
"""

import ast
import io
import os
import py_compile
import shutil
import sys
import time
import tokenize

MAIN = "main.py"
MARCA = "_error_orden"

ANTES_DEL_BUCLE = (
    "# BLINDAJE: una orden que falla ya no cierra a Arché (ver aplicar_parche_blindaje.py)\n"
    "_errores_seguidos = []\n"
    "\n"
)

DESPUES_DEL_BUCLE = (
    "    except (EOFError, KeyboardInterrupt):\n"
    "        raise                              # cerrar la consola / Ctrl+C: igual que siempre\n"
    "    except Exception as _error_orden:\n"
    "        _ahora_error = time.time()\n"
    "        _errores_seguidos[:] = [t for t in _errores_seguidos if _ahora_error - t < 20] + [_ahora_error]\n"
    "        if len(_errores_seguidos) >= 8:\n"
    "            raise                          # algo está roto de fondo: mejor cerrar que quedar en bucle\n"
    "        del _cola_comandos_naturales[:]    # no seguir con los pasos de una cadena rota\n"
    "        try:\n"
    "            from core.IA import registro_errores as _registro_errores\n"
    "            _registro_errores.registrar(_error_orden, frase=globals().get(\"comando_original\", \"\"),\n"
    "                                        origen=\"comando\")\n"
    "        except Exception:\n"
    "            pass\n"
    "        print(f\"Arché: Esa orden me dio un error ({type(_error_orden).__name__}: \"\n"
    "              f\"{str(_error_orden)[:150]}). Lo anoté para repararlo y sigo aquí.\")\n"
)


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def _lineas_dentro_de_cadenas(texto):
    """Números de línea que están DENTRO de una cadena de varias líneas
    (a esas no se les puede cambiar la sangría sin cambiar el texto)."""
    dentro = set()
    for tok in tokenize.generate_tokens(io.StringIO(texto).readline):
        nombre = tokenize.tok_name.get(tok.type, "")
        if nombre in ("STRING", "FSTRING_MIDDLE", "FSTRING_START", "FSTRING_END") or tok.type == tokenize.STRING:
            for n in range(tok.start[0] + 1, tok.end[0] + 1):
                dentro.add(n)
    return dentro


def parchar(texto):
    if MARCA in texto:
        return texto, False
    nl = "\r\n" if "\r\n" in texto else "\n"
    arbol = ast.parse(texto)
    bucles = [n for n in arbol.body if isinstance(n, ast.While)
              and isinstance(n.test, ast.Constant) and n.test.value is True]
    if len(bucles) != 1:
        raise RuntimeError("No encontré un único «while True:» principal en main.py. No se tocó nada.")
    bucle = bucles[0]
    if arbol.body[-1] is not bucle or bucle.orelse:
        raise RuntimeError("El bucle principal no es lo último de main.py. No se tocó nada.")

    lineas = texto.splitlines(keepends=True)
    if lineas and not lineas[-1].endswith(("\n", "\r")):
        lineas[-1] += nl
    n_while = bucle.lineno                       # 1 = primera línea
    if lineas[n_while - 1].strip() != "while True:":
        raise RuntimeError("La línea del bucle principal no es exactamente «while True:». No se tocó nada.")

    protegidas = _lineas_dentro_de_cadenas(texto)
    nuevas = lineas[:n_while - 1]
    nuevas.append(ANTES_DEL_BUCLE.replace("\n", nl))
    nuevas.append(lineas[n_while - 1])
    nuevas.append("    try:" + nl)
    for i in range(n_while, len(lineas)):        # i es índice 0 -> línea i+1
        linea = lineas[i]
        if (i + 1) in protegidas or not linea.strip():
            nuevas.append(linea)
        else:
            nuevas.append("    " + linea)
    nuevas.append(DESPUES_DEL_BUCLE.replace("\n", nl))
    nuevo = "".join(nuevas)

    # comprobación: el cuerpo del bucle debe ser EXACTAMENTE el mismo código
    arbol_nuevo = ast.parse(nuevo)
    bucle_nuevo = arbol_nuevo.body[-1]
    ok = (isinstance(bucle_nuevo, ast.While) and len(bucle_nuevo.body) == 1
          and isinstance(bucle_nuevo.body[0], ast.Try)
          and ast.dump(ast.Module(body=bucle_nuevo.body[0].body, type_ignores=[]))
          == ast.dump(ast.Module(body=bucle.body, type_ignores=[])))
    if not ok:
        raise RuntimeError("Al comprobar, el bucle no quedó idéntico al original. No se tocó nada.")
    return nuevo, True


def main():
    if not os.path.exists(MAIN):
        sys.exit("Corre esto desde la carpeta Arche (donde está main.py).")
    original = _leer(MAIN)
    try:
        nuevo, cambio = parchar(original)
    except (RuntimeError, SyntaxError) as e:
        sys.exit(str(e))
    if not cambio:
        print("main.py ya tenía el blindaje. No hice nada.")
        return
    respaldo = f"main_antes_blindaje_{time.strftime('%Y%m%d_%H%M%S')}.py"
    shutil.copy2(MAIN, respaldo)
    _escribir(MAIN, nuevo)
    try:
        py_compile.compile(MAIN, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(respaldo, MAIN)
        sys.exit(f"El main.py nuevo no compila; lo dejé como estaba.\n{e}")
    print(f"Listo: una orden que falle ya no cierra a Arché. Copia de respaldo: {respaldo}")


if __name__ == "__main__":
    main()
