"""
coordinador.py
--------------
Ubicacion: Arche/core/agente/coordinador.py

El director del agente. Une las piezas y corre el ciclo completo:

    objetivo -> PLAN (planificador, con experiencias previas)
      por cada subobjetivo:
        OBSERVAR (percepcion) -> DECIDIR una accion (decisor, un modelo)
        -> EJECUTAR (ejecutor, sin modelo) -> VERIFICAR (verificador)
        -> repetir hasta cumplirlo, atascarse o chocar con un limite
      si un subobjetivo falla -> REPLANIFICAR con el motivo del fallo
    al final -> REFLEXIONAR: guardar la leccion en la memoria de experiencias

Protecciones: tope de pasos y de tiempo, fallos seguidos, deteccion de
"repito lo mismo y nada cambia", replanificaciones limitadas, y parada
inmediata con detener().

Quien decide (decisor/planificador) y quien actua (ejecutor) estan separados:
el decisor solo propone una Accion; el ejecutor la valida y la ejecuta.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque

from core.agente.decisor import Decisor
from core.agente.ejecutor import Ejecutor, Limites
from core.agente.habilidades import Habilidades
from core.agente.memoria_experiencias import MemoriaExperiencias
from core.agente.modelos import Enrutador, ErrorModelo, pedir_json
from core.agente.percepcion import Percepcion
from core.agente.planificador import Planificador
from core.agente.simbolico import Simbolico
from core.agente.tipos import Decision, Informe, Paso, Plan, Subobjetivo
from core.agente.verificador import Verificador


class Agente:
    def __init__(self, entorno, router: Enrutador | None = None, memoria: MemoriaExperiencias | None = None,
                 limites: Limites | None = None, avisar=None, confirmar=None, usar_vision: bool = True,
                 habilidades: Habilidades | None = None, usar_simbolico: bool = True):
        self.entorno = entorno
        self.router = router or Enrutador()
        self.memoria = memoria or MemoriaExperiencias()
        self.limites = limites or Limites.desde_config()
        self.avisar = avisar or (lambda texto: print(f"Arché: {texto}"))
        self.parada = threading.Event()
        self.router.parada = self.parada            # que "agente para" tambien corte las esperas de la nube
        self.router.avisar = self._log
        self.percepcion = Percepcion(entorno, self.router, usar_vision)
        self.planificador = Planificador(self.router, self.memoria)
        self.decisor = Decisor(self.router)
        self.ejecutor = Ejecutor(entorno, self.limites, confirmar, self.parada)
        self.verificador = Verificador(entorno, self.router)
        self.simbolico = Simbolico(entorno) if usar_simbolico else None   # planear/decidir sin modelo lo que el juego ya sabe
        self.habilidades = habilidades if habilidades is not None else Habilidades()
        self._replans_simb = 0
        self.eventos: deque = deque(maxlen=60)
        self.estado = {"activo": False, "objetivo": "", "subobjetivo": "", "pasos": 0, "fallos": 0, "ultima": ""}
        self._t0 = 0.0

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    def detener(self):
        self.parada.set()
        try:
            self.entorno.detener()
        except Exception:
            pass

    def _log(self, texto: str):
        self.eventos.append(texto)
        try:
            self.avisar(texto)
        except Exception:
            pass

    def estado_texto(self) -> str:
        e = self.estado
        if not e["activo"]:
            return "El agente está en reposo."
        return (f"Objetivo: {e['objetivo']}\nSubobjetivo: {e['subobjetivo']}\n"
                f"Pasos: {e['pasos']} (fallos: {e['fallos']}), llevo {int(time.time() - self._t0)} s.\n"
                f"Última acción: {e['ultima'] or '-'}")

    def _informe(self, objetivo, exito, motivo, plan=None, replans=0, recuperable=False) -> Informe:
        return Informe(objetivo, exito, motivo, self.estado["pasos"], round(time.time() - self._t0, 1),
                       plan, replans, self.estado["fallos"], recuperable)

    # ------------------------------------------------------------------
    # Ciclo principal
    # ------------------------------------------------------------------
    def ejecutar(self, objetivo: str, plan_inicial: Plan | None = None) -> Informe:
        """plan_inicial: para retomar un plan guardado (se salta lo ya hecho y no vuelve a planificar)."""
        self.parada.clear()
        self._t0 = time.time()
        self.estado.update(activo=True, objetivo=objetivo, subobjetivo="", pasos=0, fallos=0, ultima="")
        try:
            return self._ejecutar(objetivo, plan_inicial)
        finally:
            self.estado["activo"] = False

    def _estado_texto_actual(self) -> str:
        return Percepcion.texto_para_modelo(self.percepcion.observar())

    def _ejecutar(self, objetivo: str, plan_inicial: Plan | None = None) -> Informe:
        self._log(f"Objetivo recibido: {objetivo}")
        self._replans_simb = 0
        try:
            obs0 = self.percepcion.observar()
            estado = Percepcion.texto_para_modelo(obs0)
        except Exception as e:
            return self._informe(objetivo, False, f"No pude observar el entorno: {e}")
        if plan_inicial is not None:
            plan = plan_inicial
            self._log("Retomo el plan que dejé a medias:")
        else:
            plan = self.simbolico.crear_plan(objetivo, obs0.datos) if self.simbolico else None
            if plan is not None:
                self._log("Calculé el plan con las recetas del propio juego (sin consultar ningún modelo).")
            else:
                try:
                    plan = self.planificador.crear_plan(objetivo, self.entorno, estado)
                except ErrorModelo as e:
                    return self._informe(objetivo, False, f"No hay ningún modelo disponible para planificar ({e}).")
        self._mostrar_plan(plan)

        replans = 0
        ultimo_historial: list[Paso] = []
        while True:
            if self.parada.is_set():
                return self._informe(objetivo, False, "Detenido por el usuario.", plan, replans, recuperable=True)
            pendientes = plan.pendientes()
            if not pendientes:
                if self.verificador.rapido(objetivo) is False and replans < self.limites.max_replanificaciones:
                    replans += 1
                    self._log("Terminé los pasos, pero los datos del entorno dicen que el objetivo aún no se cumple. Replanifico.")
                    nuevo = self._replanificar(plan, Subobjetivo(objetivo), "los pasos se hicieron pero el objetivo no se cumple",
                                               ultimo_historial)
                    if isinstance(nuevo, Informe):
                        return nuevo
                    plan = nuevo
                    if not plan.pendientes():
                        break
                    continue
                break
            sub = pendientes[0]
            self.estado["subobjetivo"] = sub.descripcion
            self._log(f"Subobjetivo: {sub.descripcion}")
            codigo, motivo, historial = self._resolver(objetivo, sub)
            ultimo_historial = historial
            if codigo == "ok":
                sub.hecho = True
                self._log("  Cumplido.")
                continue
            if codigo in ("detenido", "limite", "modelo"):
                return self._informe(objetivo, False, motivo, plan, replans, recuperable=True)
            if replans >= self.limites.max_replanificaciones:
                self._reflexionar(objetivo, "", ultimo_historial, False, motivo)
                return self._informe(objetivo, False, f"Agoté los cambios de estrategia. Último motivo: {motivo}", plan, replans)
            replans += 1
            self._log(f"No lo logré ({motivo}). Cambio de estrategia {replans}/{self.limites.max_replanificaciones}.")
            nuevo = self._replanificar(plan, sub, motivo, historial)
            if isinstance(nuevo, Informe):
                return nuevo
            plan = nuevo

        comprobado = self.verificador.rapido(objetivo)
        if comprobado is False:
            self._reflexionar(objetivo, "", ultimo_historial, False, "el objetivo no se cumplió al final")
            return self._informe(objetivo, False, "Hice todos los pasos pero el objetivo no se cumple.", plan, replans)
        return self._informe(objetivo, True, "Objetivo cumplido.", plan, replans)

    def _replanificar(self, plan: Plan, fallido: Subobjetivo, motivo: str, historial: list[Paso]):
        # primero se recalcula con las recetas (el mundo cambio: ya hay cosas en el inventario); si eso no cambia
        # nada, entonces si se le pregunta a un modelo
        if self.simbolico and plan.origen == "simbolico" and self._replans_simb < 2:
            self._replans_simb += 1
            try:
                nuevo = self.simbolico.crear_plan(plan.objetivo, self.percepcion.observar().datos, plan.version + 1)
            except Exception:
                nuevo = None
            pend = nuevo.pendientes() if nuevo else []
            if nuevo is not None and (not pend or pend[0].descripcion != fallido.descripcion):
                self._mostrar_plan(nuevo)
                return nuevo
        try:
            estado = self._estado_texto_actual()
            nuevo = self.planificador.replanificar(plan, fallido, motivo, "\n".join(p.corto() for p in historial[-6:]),
                                                   self.entorno, estado)
        except ErrorModelo as e:
            return self._informe(plan.objetivo, False, f"No pude replanificar ({e}).", plan, recuperable=True)
        self._mostrar_plan(nuevo)
        return nuevo

    def _mostrar_plan(self, plan: Plan):
        self._log(f"Plan v{plan.version}:\n" + plan.resumen() + (f"\n  Notas: {plan.notas}" if plan.notas else ""))

    # ------------------------------------------------------------------
    # Un subobjetivo
    # ------------------------------------------------------------------
    def _limite_alcanzado(self) -> str:
        if self.estado["pasos"] >= self.limites.max_pasos:
            return f"Llegué al tope de {self.limites.max_pasos} acciones."
        if time.time() - self._t0 > self.limites.max_segundos:
            return f"Llegué al tope de tiempo ({self.limites.max_segundos} s)."
        return ""

    def _resolver(self, objetivo: str, sub: Subobjetivo):
        """-> (codigo, motivo, historial). codigo: ok | fallo | detenido | limite | modelo"""
        lecciones = self.memoria.buscar(self.entorno.nombre, f"{sub.descripcion} {objetivo}", k=4)
        ids = [e["id"] for e in lecciones]
        texto_lecciones = self.memoria.formatear(lecciones)
        if lecciones:
            self._log(f"  Recuerdo {len(lecciones)} experiencia(s) parecida(s).")
        historial: list[Paso] = []
        avisos: list[str] = []
        fallos_seguidos = falsos_terminados = repeticiones = 0
        ultima_firma = huella_previa = None

        hab = {"usada": None, "intentada": False}
        usar_simb = bool(self.simbolico and sub.meta)
        fallos_simb = 0

        def cerrar(exito: bool, motivo: str):
            self.memoria.marcar_uso(ids, exito)
            self._reflexionar(objetivo, sub.descripcion, historial, exito, motivo)
            if exito and not sub.meta:
                self._aprender_habilidad(sub, historial, hab["usada"])

        while True:
            if self.parada.is_set():
                return "detenido", "Detenido por el usuario.", historial
            tope = self._limite_alcanzado()
            if tope:
                cerrar(False, tope)
                return "limite", tope, historial
            try:
                obs = self.percepcion.observar()
            except Exception as e:
                return "fallo", f"no pude observar el entorno: {e}", historial
            estado = Percepcion.texto_para_modelo(obs)
            if sub.meta:
                if Simbolico.cumplido(sub, obs) is True:
                    cerrar(True, "comprobado en el inventario")
                    return "ok", "", historial
            elif self.verificador.rapido(sub.descripcion) is True:
                cerrar(True, "comprobado con datos del entorno")
                return "ok", "", historial

            dec = None
            if usar_simb:                                   # 1) calculado con las recetas, sin modelo
                dec = self.simbolico.decidir(sub, obs, historial)
                if dec is None:
                    usar_simb = False
            if dec is None and not sub.meta and not hab["intentada"]:    # 2) algo que ya me salio antes
                hab["intentada"] = True
                h = self.habilidades.buscar(self.entorno.nombre, sub.descripcion) if self.habilidades else None
                if h:
                    acciones_h = Habilidades.acciones(h)
                    hab["usada"] = h
                    self._log("  Ya sé hacer esto (habilidad guardada): lo repito sin consultar ningún modelo.")
                    dec = Decision("accion", acciones_h[0], "habilidad guardada", acciones_h[1:], "habilidad")
            if dec is None:                                 # 3) lo nuevo: se razona con un modelo
                try:
                    dec = self.decisor.decidir(objetivo, sub, estado, self.entorno.herramientas(), historial,
                                               texto_lecciones, avisos, self.entorno.descripcion_completa())
                except ErrorModelo as e:
                    return "modelo", f"El modelo de decisión no respondió ({e}).", historial

            if dec.tipo == "terminado" and dec.origen == "simbolico":
                cerrar(True, dec.razon)
                return "ok", "", historial
            if dec.tipo == "terminado":
                cumplido, razon = self.verificador.evaluar(sub.descripcion, sub.criterio, estado, historial)
                if cumplido:
                    cerrar(True, razon)
                    return "ok", "", historial
                falsos_terminados += 1
                avisos.append(f"Dijiste que estaba terminado, pero no se cumple: {razon}. Sigue trabajando.")
                if falsos_terminados >= 3:
                    cerrar(False, razon)
                    return "fallo", f"di el subobjetivo por cumplido sin que lo estuviera ({razon})", historial
                continue
            if dec.tipo == "bloqueado":
                cerrar(False, dec.razon)
                return "fallo", dec.razon or "bloqueado", historial

            accion = dec.accion
            firma = (accion.nombre, json.dumps(accion.args, sort_keys=True, default=str))
            huella = self.entorno.huella(obs)
            repeticiones = repeticiones + 1 if (firma == ultima_firma and huella == huella_previa) else 1
            if repeticiones >= self.limites.max_repeticiones:
                motivo = f"estoy repitiendo '{accion.corta()}' y nada cambia"
                cerrar(False, motivo)
                return "fallo", motivo, historial
            if repeticiones == self.limites.max_repeticiones - 1:
                avisos.append(f"Llevas repitiendo '{accion.corta()}' sin que cambie nada. Haz algo distinto.")
            ultima_firma, huella_previa = firma, huella

            for pos, act in enumerate([accion] + list(dec.siguientes)):
                if pos and (self.parada.is_set() or self._limite_alcanzado()):
                    break
                resultado = self.ejecutor.ejecutar(act)
                historial.append(Paso(act, resultado, dec.razon))
                self.estado["pasos"] += 1
                self.estado["ultima"] = act.corta()
                if resultado.ok:
                    fallos_seguidos = 0
                    self._log(f"  - {act.corta()}: ok" + (f" ({resultado.mensaje[:90]})" if resultado.mensaje else ""))
                    continue
                fallos_seguidos += 1
                self.estado["fallos"] += 1
                self._log(f"  - {act.corta()}: FALLÓ ({resultado.mensaje[:140]})")
                if dec.origen == "simbolico":
                    if not ("a la vista" in resultado.mensaje or "a la redonda" in resultado.mensaje):
                        fallos_simb += 1           # no verlo cerca no es un fallo: toca explorar
                    if fallos_simb >= 2:
                        usar_simb = False
                        avisos.append("El cálculo automático de materiales falló dos veces en este paso: razona con la "
                                      "situación actual y los errores de arriba.")
                elif dec.origen == "habilidad" and hab["usada"]:
                    self.habilidades.marcar(hab["usada"]["id"], False)
                    hab["usada"] = None
                if fallos_seguidos >= self.limites.max_fallos_seguidos:
                    motivo = f"{fallos_seguidos} fallos seguidos (último: {resultado.mensaje[:120]})"
                    cerrar(False, motivo)
                    return "fallo", motivo, historial
                break                      # si una acción falla, las que venían detrás ya no tienen sentido

    def _aprender_habilidad(self, sub: Subobjetivo, historial: list[Paso], usada: dict | None):
        if self.habilidades is None or not historial:
            return
        try:
            if usada is not None:
                self.habilidades.marcar(usada["id"], True)
            elif all(p.resultado.ok for p in historial):
                if self.habilidades.guardar(self.entorno.nombre, sub.descripcion, [p.accion for p in historial]):
                    self._log("  Guardé lo que hice como habilidad: la próxima vez no necesito consultar un modelo.")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Reflexion -> memoria de experiencias
    # ------------------------------------------------------------------
    def _reflexionar(self, objetivo: str, sub_desc: str, historial: list[Paso], exito: bool, motivo: str):
        if not historial:
            return
        fallos = [p for p in historial if not p.resultado.ok]
        if exito and not fallos and len(historial) < 3:
            return           # algo trivial: no vale la pena recordarlo
        oks = [p.accion.corta() for p in historial if p.resultado.ok][-8:]
        error = fallos[-1].resultado.mensaje if fallos else ""
        tema = sub_desc or objetivo
        # el modelo solo se gasta cuando hay algo que aprender (hubo fallos o no se cumplió)
        leccion = (self._leccion_con_modelo(tema, historial, exito, motivo) if (fallos or not exito) else "") or \
            self._leccion_heuristica(tema, historial, fallos, oks, exito, motivo)
        self.memoria.guardar(self.entorno.nombre, objetivo, sub_desc, "exito" if exito else "fracaso",
                             len(historial), oks, error, leccion)

    def _leccion_con_modelo(self, tema: str, historial: list[Paso], exito: bool, motivo: str) -> str:
        rastro = "\n".join(p.corto() for p in historial[-10:])
        prompt = (f"Entorno: {self.entorno.nombre}\nTarea: {tema}\n"
                  f"Resultado: {'cumplida' if exito else 'NO cumplida (' + motivo + ')'}\nPasos:\n{rastro}\n\n"
                  "Escribe UNA lección práctica, general y reutilizable (máximo 40 palabras, en español) sobre qué "
                  "hacer o evitar la próxima vez en una situación parecida. Si lo que falló fue un requisito o el "
                  "orden de los pasos, dilo. "
                  'Responde SOLO con JSON: {"leccion": "..."}')
        try:
            d = pedir_json(self.router, "reflexion", [{"role": "user", "content": prompt}],
                           validar=lambda d: None if str(d.get("leccion", "")).strip() else "falta 'leccion'",
                           reintentos=1, max_tokens=200)
        except ErrorModelo:
            return ""
        return str(d["leccion"]).strip() if d else ""

    @staticmethod
    def _leccion_heuristica(tema, historial, fallos, oks, exito, motivo) -> str:
        secuencia = " -> ".join(oks) if oks else "(nada)"
        if exito and fallos:
            return (f"Para «{tema}»: falló {fallos[0].accion.corta()} con «{fallos[0].resultado.mensaje[:120]}»; "
                    f"funcionó con: {secuencia}.")
        if exito:
            return f"Para «{tema}» funcionó esta secuencia: {secuencia}."
        ultimo = fallos[-1].resultado.mensaje[:120] if fallos else motivo
        return f"Para «{tema}» no funcionó: {motivo}. Se intentó: {secuencia}. Último error: «{ultimo}»."
