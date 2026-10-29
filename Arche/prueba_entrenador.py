"""
prueba_entrenador.py
--------------------
Prueba la Fase 4 (entrenador automatico de arche-lora) SIN internet, sin
GPU y sin tocar tu Ollama: Supabase, Kaggle, Hugging Face y Ollama se simulan.

  * datos.py: limpieza, particion estable (la validacion nunca se entrena).
  * ciclo.py: libre -> entrenando -> candidato publicado.
  * modelo_nuevo.py: descarga, examen contra tu modelo, cambio y vuelta atras.

Uso (desde la carpeta Arche):   py prueba_entrenador.py
"""

import json
import os
import random
import sys
import tempfile
import types

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "nube"))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "nube", "entrenador"))

FALLOS = []


def chequear(nombre, obtenido, esperado):
    ok = obtenido == esperado
    print(("  OK   " if ok else "  MAL  ") + nombre + ("" if ok else f"   (dio {obtenido!r}, esperaba {esperado!r})"))
    if not ok:
        FALLOS.append(nombre)


def filas_de_prueba():
    from core.IA import catalogo
    rng = random.Random(0)
    rellenos = ["ya", "porfa", "ahora", "oye", "rapido", "bien", "va", "dale", "listo", "sale", "pues", "eh"]
    filas = []
    for e in catalogo.ENTRADAS:
        for k in range(rng.randint(0, 12)):
            x = "spotify" if e.get("argumento") else ""
            base = catalogo.normalizar(e["semillas"][k % len(e["semillas"])].replace("{X}", x))
            filas.append({"frase": f"{base} {rellenos[k]}", "intencion": e["id"], "contenido": x, "origen": "turno_huecos"})
    filas.append({"frase": 'genera una frase: {"intencion": "abrir"}', "intencion": "abrir", "contenido": "", "origen": "x"})
    return filas


def probar_datos():
    import datos
    print("\nDataset (datos.py):")
    filas = filas_de_prueba()
    paquete = datos.construir(filas, 1)
    entrenar = {e["frase"] for e in paquete["entrenamiento"]}
    validar = {e["frase"] for e in paquete["validacion"]}
    chequear("ninguna frase de validación se entrena", entrenar & validar, set())
    chequear("quitó la frase contaminada", paquete["meta"]["informe_limpieza"].get("contaminadas"), 1)
    chequear("las frases normales con 'ejemplo' o 'contenido' NO son contaminadas",
             datos.contaminada("cuantos ejemplos tienes") or datos.contaminada("dime el contenido de la nota"), False)
    mas = filas + [{"frase": "una frase nueva cualquiera", "intencion": "hora", "contenido": "", "origen": "x"}]
    chequear("la validación es estable entre versiones", validar <= {e["frase"] for e in datos.construir(mas, 2)["validacion"]},
             True)
    chequear("lleva el formato de entrenamiento", paquete["meta"]["version_formato"], 1)
    return filas


def probar_ciclo(filas):
    import ciclo
    from prueba_memoria_nube import SupabaseFalso
    print("\nEntrenador en la nube (ciclo.py):")
    falso = SupabaseFalso()
    falso.pedir("POST", "arche_ejemplos", None, filas)

    class Supa:
        def leer(self, t, p):
            return falso.pedir("GET", t, p)

        def leer_todo(self, t, p):
            return falso.pedir("GET", t, p)

        def _pedir(self, m, t, p=None, c=None, extra=None):
            return falso.pedir(m, t, p, c, prefer=(extra or {}).get("Prefer"))

    supa, lanzados = Supa(), []
    originales = (ciclo.subir_dataset, ciclo.lanzar_kernel, ciclo.estado_kernel, ciclo.kaggle, ciclo.publicar_en_hf,
                  ciclo.MIN_NUEVOS)
    callar = lambda *_: None
    try:
        ciclo.subir_dataset = lambda u, c, v: lanzados.append(("dataset", v))
        ciclo.lanzar_kernel = lambda u, v: lanzados.append(("kernel", v))
        ciclo.MIN_NUEVOS = 10 ** 6
        ciclo.empezar(supa, ciclo.leer_estado(supa), "david", False, callar)
        chequear("sin datos suficientes no entrena", lanzados, [])
        ciclo.empezar(supa, ciclo.leer_estado(supa), "david", True, callar)
        estado = ciclo.leer_estado(supa)
        chequear("'entrena ya' lanza dataset y kernel", lanzados, [("dataset", 1), ("kernel", 1)])
        chequear("queda entrenando la v1", (estado["estado"], estado["en_curso"]), ("entrenando", 1))

        ciclo.estado_kernel = lambda u: ("complete", "")

        def kaggle_falso(*a, **k):
            if a[:2] == ("kernels", "output"):
                carpeta = a[a.index("-p") + 1]
                with open(os.path.join(carpeta, "metricas.json"), "w", encoding="utf-8") as f:
                    json.dump({"aprobado": True, "motivos": [], "gguf": {"archivo": "arche-lora-v1.gguf", "tipo": "Q4_K_M",
                                                                         "bytes": 5},
                               "examen_nuevo": {"acierto": .9, "json_valido": 1, "charla_ok": 1},
                               "examen_base": {"acierto": .1}}, f)
            return ""
        ciclo.kaggle = kaggle_falso
        ciclo.publicar_en_hf = lambda c, v, m: {"version": v, "repo": "david/arche-lora", "archivo": "v1/arche-lora-v1.gguf",
                                                "validacion": "v1/validacion.jsonl", "bytes": 5}
        ciclo.revisar(supa, ciclo.leer_estado(supa), "david", callar)
        estado = ciclo.leer_estado(supa)
        chequear("al terminar publica el candidato v1", (estado["estado"], (estado.get("candidato") or {}).get("version")),
                 ("libre", 1))
        chequear("y recuerda hasta qué ejemplo usó", estado["max_id"] > 0, True)
    finally:
        (ciclo.subir_dataset, ciclo.lanzar_kernel, ciclo.estado_kernel, ciclo.kaggle, ciclo.publicar_en_hf,
         ciclo.MIN_NUEVOS) = originales


def probar_modelo_nuevo():
    print("\nModelo nuevo en tu PC (modelo_nuevo.py):")
    falso_ollama = types.ModuleType("ollama")
    modelos = {"arche-lora": "original"}

    def chat(model, messages, **kw):
        texto = messages[-1]["content"]
        if messages[0]["role"] == "system" and "clasificador" in messages[0]["content"]:
            buena = texto.split("|")[1]
            return {"message": {"content": json.dumps({"intencion": buena if modelos[model] != "original" else "hora",
                                                        "contenido": ""})}}
        if "Frase de la persona" in texto:
            return {"message": {"content": '{"intencion": "hora", "contenido": ""}'}}
        return {"message": {"content": "Hola, claro que te ayudo con eso."}}
    falso_ollama.chat = chat
    real = sys.modules.get("ollama")
    sys.modules["ollama"] = falso_ollama
    from core.IA import formato_lora, ollamaIA
    ollama_antes = ollamaIA.ollama
    ollamaIA.ollama = falso_ollama
    from core.IA import modelo_nuevo as mn
    tmp = tempfile.mkdtemp(prefix="arche_prueba_modelo_")
    originales = (mn.ARCHIVO_ESTADO, mn.CARPETA_MODELOS, mn._descargar, mn._ollama, mn.estado_nube,
                  formato_lora._archivo_modelo_activo)
    validacion = [{"frase": f"frase {i}|{['abrir', 'hora', 'buscar'][i % 3]}", "intencion": ['abrir', 'hora', 'buscar'][i % 3],
                   "dominio": ['web', 'tiempo', 'web'][i % 3]} for i in range(30)]

    def descargar(repo, ruta, destino, b=None):
        with open(destino, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(v) for v in validacion) if ruta.endswith(".jsonl") else "GGUF")
        return destino

    def ollama_cli(*a):
        if a[0] == "list":
            return "NAME ID\n" + "\n".join(f"{m}:latest x" for m in modelos)
        if a[0] == "create":
            modelos[a[1]] = "nuevo"
        if a[0] == "cp":
            modelos[a[2]] = modelos[a[1]]
        return ""
    try:
        mn.ARCHIVO_ESTADO, mn.CARPETA_MODELOS = os.path.join(tmp, "estado.json"), tmp
        mn._descargar, mn._ollama = descargar, ollama_cli
        formato_lora._archivo_modelo_activo = lambda: os.path.join(tmp, "modelo_activo.json")
        mn.estado_nube = lambda: {"candidato": {"version": 1, "repo": "d/arche-lora", "archivo": "v1/x.gguf",
                                                "validacion": "v1/validacion.jsonl", "bytes": 4}}
        os.environ["HF_TOKEN"] = "hf_prueba"
        mensaje = mn.revisar_candidato(avisar=lambda *_: None)
        chequear("el modelo nuevo gana el examen contra el actual", "Ganó el examen" in mensaje, True)
        chequear("no reemplaza nada sin tu permiso", modelos["arche-lora"], "original")
        mn._ejecutar("usar", input)
        chequear("'usa el modelo nuevo' lo cambia", (modelos["arche-lora"], formato_lora.usa_formato_corto()),
                 ("nuevo", True))
        chequear("y guarda el anterior", modelos.get("arche-lora-anterior"), "original")
        mn._ejecutar("volver", input)
        chequear("'vuelve al modelo anterior' lo deshace", (modelos["arche-lora"], formato_lora.usa_formato_corto()),
                 ("original", False))
    finally:
        (mn.ARCHIVO_ESTADO, mn.CARPETA_MODELOS, mn._descargar, mn._ollama, mn.estado_nube,
         formato_lora._archivo_modelo_activo) = originales
        ollamaIA.ollama = ollama_antes
        if real is not None:
            sys.modules["ollama"] = real
        os.environ.pop("HF_TOKEN", None)


def main():
    print("Arché -- prueba del entrenador automático (Fase 4)")
    filas = probar_datos()
    probar_ciclo(filas)
    probar_modelo_nuevo()
    print()
    if FALLOS:
        print(f"Arché: {len(FALLOS)} prueba(s) fallaron: " + ", ".join(FALLOS))
        return 1
    print("Arché: Todas las pruebas del entrenador pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
