"""
prueba_cupo_nube.py
-------------------
Ubicacion: Arche/prueba_cupo_nube.py

Prueba (sin internet, sin Ollama, sin tocar tu Database) el cupo diario de la nube para
programar y la autorevision por lotes:

  * el cupo diario se cuenta, se reinicia al cambiar de dia y se puede cambiar
  * si la nube esta en solo-Ollama o no esta disponible, NO hay tope (como siempre)
  * si la nube hace el trabajo, el lote no pasa del cupo que queda
  * lo que no entra queda PENDIENTE (no se marca como revisado) y la proxima pasada lo retoma
  * si la nube choca con su limite a mitad del lote, se para en vez de seguir con Ollama

Correr:  python prueba_cupo_nube.py
"""

import contextlib
import os
import sys
import time
from unittest import mock

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from core.IA import autorevision, nube, nube_tareas  # noqa: E402

fallos = []


def chequear(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}", file=sys.__stdout__)
    else:
        print(f"FALLA {nombre}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}", file=sys.__stdout__)
        fallos.append(nombre)


class Mundo(contextlib.ExitStack):
    """Config de la nube en memoria + un proyecto falso de N funciones."""

    def __init__(self, funciones=10, nube_activa=True, nube_disponible=True, cupo=None):
        super().__init__()
        self.cfg = {"tareas": {"codigo": nube_activa}}
        if cupo is not None:
            self.cfg["cupo_diario"] = {"codigo": cupo}
        self.funciones = funciones
        self.nube_disponible = nube_disponible
        self.cache = {}
        self.revisadas = []
        self.limite_en = None      # tras cuantas revisiones la "nube" choca con su limite

    def _revisar(self, rel, fn):
        self.revisadas.append(fn["nombre"])
        if nube_tareas.activa("codigo") and self.nube_disponible:
            nube_tareas._contar("codigo", "nube")
            if self.limite_en is not None and len(self.revisadas) >= self.limite_en:
                nube_tareas._pausa_hasta = time.time() + 120   # como un 429 real
        return None, None

    def __enter__(self):
        super().__enter__()
        nube_tareas._pausa_hasta = 0.0
        self.enter_context(mock.patch.object(nube, "_leer_config", lambda: self.cfg))
        self.enter_context(mock.patch.object(nube, "_guardar_config", lambda d: self.cfg.update(d)))
        self.enter_context(mock.patch.object(nube, "disponible", lambda: self.nube_disponible))
        self.enter_context(mock.patch.object(autorevision, "ejecutar_capa_1", lambda: {
            "duplicados": [], "imports_sin_usar": [],
            "codigo_muerto": {"alta_confianza": [], "revisar_con_cuidado": []},
            "except_desnudos": []}))
        archivo = mock.Mock()
        archivo.name = "modulo_falso.py"
        self.enter_context(mock.patch.object(autorevision, "_archivos_del_proyecto",
                                             lambda: [(archivo, "core/modulo_falso.py")]))
        fns = [{"nombre": f"f{i}", "codigo": f"def f{i}(): return {i}"} for i in range(self.funciones)]
        self.enter_context(mock.patch.object(autorevision, "_funciones_de", lambda a: fns))
        self.enter_context(mock.patch.object(autorevision, "_cargar_cache", lambda: self.cache))
        self.enter_context(mock.patch.object(autorevision, "_guardar_cache", lambda c: None))
        self.enter_context(mock.patch.object(autorevision, "revisar_funcion_con_ollama", self._revisar))
        self.enter_context(contextlib.redirect_stdout(open(os.devnull, "w")))
        return self


# ---- cupo diario ------------------------------------------------------------------------
with Mundo() as m:
    chequear("cupo: por defecto el codigo tiene tope", nube_tareas.cupo_diario("codigo"), 600)
    chequear("cupo: el estudio no tiene tope", nube_tareas.cupo_diario("estudio"), None)
    chequear("cupo: arranca sin gastar", nube_tareas.usadas_hoy("codigo"), 0)
    nube_tareas._contar("codigo", "nube")
    nube_tareas._contar("codigo", "nube")
    nube_tareas._contar("codigo", "respaldo")
    chequear("cupo: cuenta solo lo que fue a la nube", nube_tareas.usadas_hoy("codigo"), 2)
    chequear("cupo: restante", nube_tareas.cupo_restante("codigo"), 598)
    m.cfg["tareas_dia"]["fecha"] = "2000-01-01"
    chequear("cupo: otro dia vuelve a cero", nube_tareas.usadas_hoy("codigo"), 0)
    nube_tareas.fijar_cupo("codigo", 5)
    chequear("cupo: se puede cambiar", nube_tareas.cupo_diario("codigo"), 5)
    nube_tareas.fijar_cupo("codigo", None)
    chequear("cupo: se puede quitar", nube_tareas.cupo_diario("codigo"), None)

with Mundo(cupo=2) as m:
    chequear("intentar: con cupo, no esta agotado", nube_tareas.cupo_restante("codigo"), 2)
    nube_tareas._contar("codigo", "nube")
    nube_tareas._contar("codigo", "nube")
    with mock.patch.object(nube, "responder", side_effect=AssertionError("no debia llamar a la nube")):
        chequear("intentar: cupo agotado -> None sin llamar a la nube",
                 nube_tareas.intentar("codigo", "hola"), None)

with Mundo(cupo=3) as m:
    with mock.patch.object(nube, "responder", return_value="respuesta"):
        textos = [nube_tareas.intentar("codigo", "hola") for _ in range(5)]
    chequear("intentar: gasta exactamente el cupo", textos, ["respuesta"] * 3 + [None] * 2)

# ---- cupo para un lote -------------------------------------------------------------------
with Mundo(nube_activa=False) as m:
    chequear("lote: solo-Ollama -> sin tope", nube_tareas.cupo_para_lote("codigo"), None)
    chequear("lote: solo-Ollama -> nunca en pausa", nube_tareas.lote_en_pausa("codigo"), "")
with Mundo(nube_disponible=False) as m:
    chequear("lote: sin nube disponible -> sin tope (trabaja Ollama)", nube_tareas.cupo_para_lote("codigo"), None)
with Mundo(cupo=7) as m:
    chequear("lote: con nube -> el cupo que queda", nube_tareas.cupo_para_lote("codigo"), 7)

# ---- autorevision por lotes --------------------------------------------------------------
with Mundo(funciones=10, cupo=4) as m:
    r = autorevision.autorevisar(usar_ollama=True)
    chequear("autorevision: revisa solo lo que cabe en el cupo", len(m.revisadas), 4)
    chequear("autorevision: lo demas queda pendiente", r["revision_ia"]["pendientes_para_despues"], 6)
    chequear("autorevision: lo pendiente NO entra al cache", len(m.cache), 4)
    chequear("autorevision: cupo gastado", nube_tareas.cupo_restante("codigo"), 0)
    r2 = autorevision.autorevisar(usar_ollama=True)
    chequear("autorevision: sin cupo no revisa nada", len(m.revisadas), 4)
    chequear("autorevision: sin cupo avisa por que", r2["revision_ia"]["pausada_por"], "cupo")
    m.cfg["tareas_dia"]["fecha"] = "2000-01-01"          # "manana": cupo nuevo
    r3 = autorevision.autorevisar(usar_ollama=True)
    chequear("autorevision: al dia siguiente retoma lo pendiente", sorted(set(m.revisadas)), [f"f{i}" for i in range(8)])
    chequear("autorevision: no repite lo ya revisado", len(m.revisadas), 8)

with Mundo(funciones=10, cupo=100) as m:
    m.limite_en = 3                                       # la nube choca con su limite tras 3
    r = autorevision.autorevisar(usar_ollama=True)
    chequear("autorevision: si la nube choca con su limite, para", len(m.revisadas), 3)
    chequear("autorevision: dice que fue por el limite", r["revision_ia"]["pausada_por"], "limite")
    chequear("autorevision: el resto queda pendiente", r["revision_ia"]["pendientes_para_despues"], 7)
    chequear("autorevision: lo no revisado no entra al cache", len(m.cache), 3)

with Mundo(funciones=10, nube_activa=False) as m:
    r = autorevision.autorevisar(usar_ollama=True)
    chequear("autorevision: solo-Ollama revisa todo como siempre", len(m.revisadas), 10)
    chequear("autorevision: solo-Ollama no deja pendientes", r["revision_ia"]["pendientes_para_despues"], 0)

with Mundo(funciones=10, nube_activa=False) as m:
    r = autorevision.autorevisar(usar_ollama=True, limite_nuevas=4)
    chequear("autorevision: limite_nuevas sigue funcionando", len(m.revisadas), 4)

with Mundo(funciones=10, cupo=100) as m:
    r = autorevision.autorevisar(usar_ollama=True, limite_nuevas=3)
    chequear("autorevision: limite_nuevas menor que el cupo gana", len(m.revisadas), 3)

with Mundo(funciones=6, cupo=100) as m:
    r = autorevision.autorevisar(usar_ollama=False)
    chequear("autorevision: sin IA no revisa funciones", len(m.revisadas), 0)

# ---- el resumen de la nube muestra el cupo ----------------------------------------------
with Mundo(cupo=50) as m:
    nube_tareas._contar("codigo", "nube")
    texto = " ".join(nube_tareas.resumen_texto())
    chequear("resumen: muestra el cupo de hoy", "Cupo de hoy: 1 de 50" in texto, True)

print(file=sys.__stdout__)
print("TODO OK" if not fallos else f"FALLARON {len(fallos)}: " + "; ".join(fallos), file=sys.__stdout__)
sys.exit(1 if fallos else 0)