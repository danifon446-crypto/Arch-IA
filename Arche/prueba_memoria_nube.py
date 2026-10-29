"""
prueba_memoria_nube.py
----------------------
Prueba la memoria en la nube (core/memoria_nube.py) y los turnos sin PC
(nube/turno.py) SIN internet: Supabase y Groq se simulan en memoria.
No toca tu conocimiento.json real ni tu Supabase.

Uso (desde la carpeta Arche):   py prueba_memoria_nube.py
"""

import json
import os
import random
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "nube"))

FALLOS = []


def chequear(nombre, obtenido, esperado):
    ok = obtenido == esperado
    print(("  OK   " if ok else "  MAL  ") + nombre + ("" if ok else f"   (dio {obtenido!r}, esperaba {esperado!r})"))
    if not ok:
        FALLOS.append(nombre)


# ------------------------------------------------------------------
# Supabase de mentira (solo lo que usan los dos modulos)
# ------------------------------------------------------------------
class SupabaseFalso:
    UNICOS = {"arche_ejemplos": ("frase", "intencion"), "arche_conteos": ("intencion",), "arche_config": ("clave",)}

    def __init__(self):
        self.tablas = {"arche_ejemplos": [], "arche_conteos": [], "arche_turnos": [],
                       "arche_config": [{"clave": "turnos_activos", "valor": True},
                                        {"clave": "cuota_diaria", "valor": {"huecos": 120, "dificiles": 60}}]}
        self.siguiente = 1

    def _cumple(self, fila, campo, regla):
        op, _, valor = regla.partition(".")
        actual = fila.get(campo)
        if op == "eq":
            return str(actual) == valor
        if op == "neq":
            return str(actual) != valor
        if op == "gt":
            return (actual or 0) > int(valor) if campo == "id" else str(actual or "") > valor
        if op == "gte":
            return str(actual or "") >= valor
        if op == "is":
            return actual is (valor == "true")
        return True

    def pedir(self, metodo, tabla, params=None, cuerpo=None, prefer=None, cfg=None):
        params = dict(params or {})
        filas = self.tablas[tabla]
        if metodo == "GET":
            sel = params.pop("select", "*")
            orden = params.pop("order", "")
            limite = int(params.pop("limit", 100000))
            res = [f for f in filas if all(self._cumple(f, c, r) for c, r in params.items())]
            if orden:
                campo, _, sentido = orden.partition(".")
                res.sort(key=lambda f: f.get(campo) or 0, reverse=sentido == "desc")
            res = res[:limite]
            return [dict(f) if sel == "*" else {k: f.get(k) for k in sel.split(",")} for f in res]
        if metodo == "POST":
            unico = self.UNICOS.get(tabla)
            nuevas = []
            for fila in cuerpo:
                fila = dict(fila)
                previa = next((f for f in filas if unico and all(f.get(k) == fila.get(k) for k in unico)), None)
                if previa is not None:
                    if prefer and "merge-duplicates" in prefer:
                        previa.update(fila)
                    continue
                if tabla == "arche_ejemplos":
                    fila.setdefault("id", self.siguiente)
                    fila.setdefault("retirado", False)
                    fila.setdefault("pc", "")
                    fila.setdefault("creado", "2026-01-01T00:00:%02dZ" % (self.siguiente % 60))
                    self.siguiente += 1
                if tabla == "arche_turnos":
                    fila.setdefault("inicio", "2099-01-01T00:00:00Z")
                filas.append(fila)
                nuevas.append(fila)
            return nuevas
        if metodo == "PATCH":
            for f in filas:
                if all(self._cumple(f, c, r) for c, r in params.items()):
                    f.update(cuerpo)
            return None


def preparar_pc(memoria_nube, aprendizaje, carpeta, conocimiento):
    os.makedirs(carpeta, exist_ok=True)
    memoria_nube.ARCHIVO_CONFIG = os.path.join(carpeta, "cfg.json")
    memoria_nube.ARCHIVO_SUBIDOS = os.path.join(carpeta, "subidos.json")
    aprendizaje.ARCHIVO = os.path.join(carpeta, "conocimiento.json")
    aprendizaje.ARCHIVO_META = os.path.join(carpeta, "meta.json")
    if not os.path.exists(aprendizaje.ARCHIVO):
        with open(aprendizaje.ARCHIVO, "w", encoding="utf-8") as f:
            json.dump(conocimiento, f)
    cfg = memoria_nube._cfg()
    cfg.update(url="https://prueba.supabase.co", activo=True)
    memoria_nube._guardar_cfg(cfg)


def dato(p, a, c="", fuente="manual"):
    return {"pregunta": p, "accion": a, "contenido": c, "fuente": fuente, "template": p, "regex": p}


def main():
    print("Arché -- prueba de la memoria en la nube y los turnos sin PC")
    import turno
    from core import memoria_nube
    from core.IA import aprendizaje, catalogo, embeddings

    falso = SupabaseFalso()
    os.environ["SUPABASE_SERVICE_KEY"] = "sb_secret_de_prueba"
    originales = (memoria_nube._pedir, embeddings.calcular_embedding, aprendizaje.reentrenar_ahora,
                  aprendizaje.ARCHIVO, aprendizaje.ARCHIVO_META, memoria_nube.ARCHIVO_CONFIG,
                  memoria_nube.ARCHIVO_SUBIDOS)
    reentrenos = []
    memoria_nube._pedir = falso.pedir
    embeddings.calcular_embedding = lambda texto: [0.1, 0.2, 0.3]
    aprendizaje.reentrenar_ahora = lambda: reentrenos.append(1)
    tmp = tempfile.mkdtemp(prefix="arche_prueba_nube_")
    try:
        # ---------------- filtros del turno (sin gastar nube)
        print("\nFiltros del turno:")
        abrir = catalogo.POR_ID["abrir"]
        buenas = turno.filtrar_candidatas(abrir, [
            {"frase": "Ábreme Spotify porfa", "contenido": "spotify"},
            {"frase": "abre spotify y mandale a ana@correo.com", "contenido": "spotify"},
            {"frase": "abre la pagina 3001234567", "contenido": "3001234567"},
            {"frase": "abre netflix", "contenido": "youtube"},
            {"frase": "abreme spotify porfa", "contenido": "spotify"},
            "no soy un dict",
        ], set())
        chequear("solo pasa la frase limpia (sin correo, sin numero largo, sin dato falso, sin repetidas)",
                 [b["frase"] for b in buenas], ["abreme spotify porfa"])
        chequear("json con ```", turno.json_de('```json\n{"a": 1}\n```'), {"a": 1})
        chequear("json con texto alrededor", turno.json_de('Claro: {"a": 2} listo'), {"a": 2})
        chequear("json roto", turno.json_de("nada que ver"), None)
        permitidas = {e["id"] for e in turno.intenciones_permitidas()}
        chequear("nunca practica apagar el PC", "apagar_pc" in permitidas, False)
        chequear("nunca practica intenciones de codigo",
                 any(catalogo.POR_ID[i]["dominio"] == "codigo" for i in permitidas), False)

        # ---------------- un turno completo con Groq simulado
        print("\nTurno en la nube (Groq simulado):")
        actual = {}

        def groq_falso(modelo, sistema, prompt, temperatura):
            if prompt.startswith("Intenciones posibles"):
                frases = [l.split(". ", 1)[1] for l in prompt.splitlines() if l[:1].isdigit() and ". " in l]
                return json.dumps({"respuestas": ["ninguna" if f.startswith("trampa") else actual["id"]
                                                  for f in frases]})
            e = next(x for x in catalogo.ENTRADAS if f"persona: {x['descripcion']}." in prompt)
            actual["id"] = e["id"]
            dato_x = "spotify" if e.get("argumento") else ""
            base = catalogo.normalizar(e["semillas"][0].replace("{X}", dato_x))
            return json.dumps({"frases": [{"frase": f"oye arche {base} porfa", "contenido": dato_x},
                                          {"frase": f"trampa {base}", "contenido": dato_x}]})

        t = turno.Turno(_SupaTurno(falso), groq_falso, rng=random.Random(0), pausa=0, avisar=lambda *_: None)
        t.correr()
        nube = falso.tablas["arche_ejemplos"]
        chequear("el turno guardó ejemplos", len(nube) > 0, True)
        chequear("el juez descartó las trampas", any(f["frase"].startswith("trampa") for f in nube), False)
        chequear("todo queda marcado con su origen",
                 {f["origen"] for f in nube} <= {"turno_huecos", "turno_dificiles"}, True)
        chequear("anotó el turno en la bitácora", len(falso.tablas["arche_turnos"]), 2)

        falso.pedir("POST", "arche_config", None, [{"clave": "turnos_activos", "valor": False}],
                    prefer="resolution=merge-duplicates")
        antes = len(nube)
        t.correr()
        chequear("con el interruptor apagado no hace nada", len(nube), antes)

        # ---------------- PC A: sube sin datos personales y baja lo de la nube
        print("\nPC A:")
        preparar_pc(memoria_nube, aprendizaje, os.path.join(tmp, "A"), [
            dato("abre spotify", "abrir", "spotify"),
            dato("anota comprar leche", "crear_nota", "comprar leche"),
            dato("mi clave es 1234 abre", "abrir", "x"),
            dato("apaga el pc", "apagar_pc"),
            dato("ponme musica", "abrir", "musica", fuente="compartido"),
        ])
        memoria_nube.sincronizar_ahora()
        subidas = sorted(f["frase"] for f in nube if f["origen"] == "pc")
        chequear("subió solo órdenes, la nota como plantilla", subidas, ["abre spotify", "anota algo"])
        chequear("aprendió lo de la nube", sum(1 for d in aprendizaje.cargar()
                                                if d.get("fuente") == "memoria_nube"), antes)
        chequear("reentrenó una sola vez", len(reentrenos), 1)
        chequear("subió los conteos (solo números)",
                 all(set(f) == {"intencion", "ejemplos", "actualizado"} for f in falso.tablas["arche_conteos"]), True)

        # ---------------- PC B: gana lo propio, y lo retirado se quita
        print("\nPC B:")
        preparar_pc(memoria_nube, aprendizaje, os.path.join(tmp, "B"),
                    [dato("abre spotify", "buscar_en_sitio", "spotify")])
        memoria_nube.sincronizar_ahora()
        locales = {d["pregunta"]: d for d in aprendizaje.cargar()}
        chequear("si este PC ya sabía otra cosa, gana lo suyo", locales["abre spotify"]["accion"], "buscar_en_sitio")
        chequear("aprendió lo que enseñó el PC A", locales.get("anota algo", {}).get("fuente"), "memoria_nube")
        falso.pedir("PATCH", "arche_ejemplos", {"frase": "eq.anota algo"}, {"retirado": True})
        memoria_nube.sincronizar_ahora()
        chequear("lo retirado en la nube se quita del PC",
                 "anota algo" in {d["pregunta"] for d in aprendizaje.cargar()}, False)

        # ---------------- comandos
        print("\nComandos:")
        for frase, esperado in [("conecta la memoria en la nube", "memoria_conectar"),
                                ("Sincroniza la memoria en la nube", "memoria_sincronizar"),
                                ("estado de la memoria en la nube", "memoria_estado"),
                                ("apaga los turnos de la nube", "turnos_apagar"),
                                ("prende los turnos", "turnos_prender"),
                                ("estado de la red", None), ("que hora es", None)]:
            chequear(f"'{frase}'", memoria_nube.interpretar(frase), esperado)
        memoria_nube.fijar_turnos(True)
        chequear("prender los turnos cambia el interruptor en la nube",
                 next(f["valor"] for f in falso.tablas["arche_config"] if f["clave"] == "turnos_activos"), True)
    finally:
        (memoria_nube._pedir, embeddings.calcular_embedding, aprendizaje.reentrenar_ahora,
         aprendizaje.ARCHIVO, aprendizaje.ARCHIVO_META, memoria_nube.ARCHIVO_CONFIG,
         memoria_nube.ARCHIVO_SUBIDOS) = originales
        os.environ.pop("SUPABASE_SERVICE_KEY", None)

    print()
    if FALLOS:
        print(f"Arché: {len(FALLOS)} prueba(s) fallaron: " + ", ".join(FALLOS))
        return 1
    print("Arché: Todas las pruebas de la memoria en la nube pasaron.")
    return 0


class _SupaTurno:
    """Adapta el Supabase falso a la interfaz que usa nube/turno.py."""

    def __init__(self, falso):
        self.falso = falso

    def leer(self, tabla, params):
        return self.falso.pedir("GET", tabla, params)

    def leer_todo(self, tabla, params):
        return self.falso.pedir("GET", tabla, params)

    def insertar(self, tabla, filas, conflicto=None):
        return self.falso.pedir("POST", tabla, None, filas, prefer="resolution=ignore-duplicates")


if __name__ == "__main__":
    sys.exit(main())
