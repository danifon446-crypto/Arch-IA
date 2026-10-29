"""
turno.py  (Arché sin tu PC)
---------------------------
Ubicacion: Arch-IA/nube/turno.py

Un "turno" de aprendizaje que corre en GitHub Actions cada pocas horas,
aunque tu PC este apagado. En cada turno Arché:

  1. Mira en Supabase cuantos ejemplos tiene cada intencion (los numeros
     los sube tu PC; aqui no llega ninguna frase tuya).
  2. HUECOS: a las intenciones con menos ejemplos les pide a la nube
     (Groq, gpt-oss-120b) frases nuevas y variadas.
  3. DIFICILES: a otras les pide variantes dificiles (errores de tipeo,
     ordenes implicitas, frases largas) para que las redes no se confien.
  4. FILTRA todo antes de guardarlo:
       - mismas reglas de privacidad que la red de aprendizaje
         (core/compartir.py: sin numeros largos, correos, enlaces, claves);
       - nunca intenciones delicadas (apagar, codigo, las que piden confirmar);
       - un SEGUNDO modelo (gpt-oss-20b) tiene que adivinar la intencion de
         cada frase sin saber cual era: si no coincide, se descarta.
  5. Guarda lo aprobado en Supabase (tabla arche_ejemplos) con su origen.
     Tu PC lo descarga al encenderse, lo aprende y reentrena sus redes.

Cuidados:
  * Cuota diaria por tarea (tabla arche_config -> cuota_diaria). Si se
    acaba, el turno termina sin error y sigue al dia siguiente.
  * Interruptor: si arche_config.turnos_activos = false, no hace nada.
    (Desde Arché: "apaga los turnos de la nube".)
  * Las claves solo se leen de variables de entorno (GitHub Secrets):
      SUPABASE_URL, SUPABASE_SERVICE_KEY, GROQ_API_KEY
    Si falta alguna, avisa y sale sin error.

Solo usa la libreria estandar: no hay que instalar nada.

Uso:  python nube/turno.py            (un turno normal)
      python nube/turno.py --probar   (solo revisa conexion y cuotas, no gasta)
"""

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ_ARCHE = os.path.join(os.path.dirname(AQUI), "Arche")
if RAIZ_ARCHE not in sys.path:
    sys.path.insert(0, RAIZ_ARCHE)

from core import compartir                 # noqa: E402  (mismas reglas de privacidad)
from core.IA import catalogo               # noqa: E402  (todas las intenciones de Arché)

URL_GROQ = "https://api.groq.com/openai/v1/chat/completions"
MODELO_PROFESOR = "openai/gpt-oss-120b"
MODELO_JUEZ = "openai/gpt-oss-20b"
TIMEOUT = 60

META_EJEMPLOS = 30                 # una intencion con menos que esto tiene "hueco"
FRASES_POR_PEDIDO = 8
INTENCIONES_POR_TURNO = {"huecos": 10, "dificiles": 5}
CUOTA_POR_DEFECTO = {"huecos": 120, "dificiles": 60}
PAUSA_ENTRE_LLAMADAS = 2.5         # Groq gratis: ~30 pedidos/minuto
OTRAS_OPCIONES_JUEZ = 11           # cuantas intenciones "trampa" ve el juez ademas de la correcta


class ErrorTurno(Exception):
    pass


class CupoAgotado(ErrorTurno):
    """Groq dijo 429 (limite gratis): se para la tarea sin error."""


# ------------------------------------------------------------------
# Supabase (PostgREST)
# ------------------------------------------------------------------
class Supabase:
    def __init__(self, url, clave):
        self.base = url.rstrip("/") + "/rest/v1/"
        self.clave = clave

    def _encabezados(self, extra=None):
        h = {"apikey": self.clave, "Content-Type": "application/json", "Accept": "application/json"}
        if self.clave.startswith("eyJ"):          # clave vieja (JWT service_role)
            h["Authorization"] = "Bearer " + self.clave
        h.update(extra or {})
        return h

    def _pedir(self, metodo, tabla, params=None, cuerpo=None, extra=None):
        url = self.base + tabla
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="(),.*:")
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
        pedido = urllib.request.Request(url, data=datos, method=metodo, headers=self._encabezados(extra))
        try:
            with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r:
                texto = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            raise ErrorTurno(f"Supabase respondió {e.code} en {tabla}: {detalle}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErrorTurno(f"sin conexión con Supabase ({getattr(e, 'reason', e)})")
        return json.loads(texto) if texto.strip() else None

    def leer(self, tabla, params):
        return self._pedir("GET", tabla, params) or []

    def leer_todo(self, tabla, params, lote=1000):
        filas, desde = [], 0
        while True:
            parte = self._pedir("GET", tabla, params, extra={"Range-Unit": "items",
                                                             "Range": f"{desde}-{desde + lote - 1}"}) or []
            filas += parte
            if len(parte) < lote:
                return filas
            desde += lote

    def insertar(self, tabla, filas, conflicto=None):
        if not filas:
            return []
        params = {"on_conflict": conflicto} if conflicto else None
        prefer = "return=representation" + (",resolution=ignore-duplicates" if conflicto else "")
        return self._pedir("POST", tabla, params, filas, extra={"Prefer": prefer}) or []


# ------------------------------------------------------------------
# Groq
# ------------------------------------------------------------------
def _llamar_groq(clave, modelo, sistema, prompt, max_tokens=1200, temperatura=0.9):
    payload = {"model": modelo, "temperature": temperatura, "max_tokens": max_tokens,
               "reasoning_effort": "low",
               "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}]}
    try:
        return _post_groq(clave, payload)
    except ErrorTurno as e:
        if " 400:" not in str(e):
            raise
        payload.pop("reasoning_effort")          # ese modelo no lo acepta: igual que core/IA/nube.py
        return _post_groq(clave, payload)


def _post_groq(clave, payload):
    modelo = payload["model"]
    pedido = urllib.request.Request(URL_GROQ, data=json.dumps(payload).encode("utf-8"), method="POST",
                                    headers={"Authorization": "Bearer " + clave, "Content-Type": "application/json",
                                             "User-Agent": "Arche-turnos/1.0"})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise CupoAgotado(f"Groq: límite gratis alcanzado en {modelo}")
        raise ErrorTurno(f"Groq respondió {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorTurno(f"sin conexión con Groq ({getattr(e, 'reason', e)})")
    try:
        texto = datos["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        texto = ""
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.S | re.I)


def json_de(texto):
    """Saca el primer objeto JSON de una respuesta (aunque venga con ```json o texto alrededor)."""
    texto = (texto or "").strip()
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.M).strip()
    try:
        return json.loads(texto)
    except ValueError:
        pass
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fin > inicio:
        try:
            return json.loads(texto[inicio:fin + 1])
        except ValueError:
            return None
    return None


# ------------------------------------------------------------------
# Que intenciones se pueden trabajar
# ------------------------------------------------------------------
def intenciones_permitidas():
    """Las mismas que la red de aprendizaje deja compartir (nada delicado)."""
    return [e for e in catalogo.ENTRADAS if compartir._intencion_permitida(e["id"])]


SISTEMA = ("Eres un generador de datos de entrenamiento para un asistente de voz en español (Colombia/Latinoamérica). "
           "Respondes SIEMPRE y SOLO con un objeto JSON válido, sin texto adicional.")

ESTILOS = {
    "huecos": ("Escribe {n} formas DISTINTAS y naturales en que una persona le pediría esto a su asistente. "
               "Varía el vocabulario, el orden y la cortesía (tú/usted, con y sin 'por favor'). "
               "Frases cortas (máximo 12 palabras), en minúsculas, sin signos raros."),
    "dificiles": ("Escribe {n} formas DIFÍCILES pero realistas de pedir esto: con errores de tipeo comunes, "
                  "pedidos implícitos (sin el verbo obvio), relleno al inicio ('oye arche', 'mmm'), "
                  "o palabras coloquiales. Máximo 15 palabras, en minúsculas. "
                  "Deben seguir significando EXACTAMENTE lo mismo (nada de negaciones)."),
}


def prompt_generar(entrada, estilo, n=FRASES_POR_PEDIDO):
    semillas = [s.replace("{X}", "<dato>") for s in entrada["semillas"][:6]]
    if entrada.get("argumento"):
        dato = (f"La orden lleva un dato variable ({entrada['argumento']}). Inventa un dato distinto y realista "
                f"en cada frase y escríbelo también en 'contenido', copiado EXACTAMENTE como aparece en la frase. "
                f"Nunca uses nombres reales de personas, números de teléfono, correos ni enlaces.")
        formato = '{"frases": [{"frase": "...", "contenido": "..."}]}'
    else:
        dato = "La orden no lleva datos variables: deja 'contenido' vacío."
        formato = '{"frases": [{"frase": "...", "contenido": ""}]}'
    return (f"Qué quiere la persona: {entrada['descripcion']}.\n"
            f"Ejemplos que ya existen (no los repitas): {json.dumps(semillas, ensure_ascii=False)}\n"
            f"{ESTILOS[estilo].format(n=n)}\n{dato}\nFormato: {formato}")


def opciones_para_juez(entrada, todas, rng):
    """La intencion correcta mezclada con 'trampas': primero las del mismo dominio."""
    mismo = [e for e in todas if e["dominio"] == entrada["dominio"] and e["id"] != entrada["id"]]
    otras = [e for e in todas if e["dominio"] != entrada["dominio"]]
    rng.shuffle(mismo)
    rng.shuffle(otras)
    elegidas = (mismo[:8] + otras)[:OTRAS_OPCIONES_JUEZ] + [entrada]
    rng.shuffle(elegidas)
    return elegidas


def prompt_juez(frases, opciones):
    lista = "\n".join(f"- {e['id']}: {e['descripcion']}" for e in opciones)
    numeradas = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(frases))
    return (f"Intenciones posibles:\n{lista}\n\nPara cada frase, di cuál intención de la lista es "
            f"(o 'ninguna' si no encaja claramente con una).\nFrases:\n{numeradas}\n\n"
            'Formato: {"respuestas": ["id_de_la_frase_1", "id_de_la_frase_2", ...]}')


# ------------------------------------------------------------------
# Filtros
# ------------------------------------------------------------------
def filtrar_candidatas(entrada, crudas, ya_existen):
    """Reglas fijas (sin gastar nube). Devuelve lista de dicts {frase, intencion, contenido}."""
    buenas, vistas = [], set(ya_existen)
    semillas = {compartir._norm(s) for s in entrada["semillas"]}
    for item in crudas if isinstance(crudas, list) else []:
        if not isinstance(item, dict):
            continue
        frase = compartir._norm(item.get("frase", ""))
        contenido = compartir._norm(item.get("contenido", "") or "")
        frase = re.sub(r"[¿?¡!\"“”]", "", frase).strip(" .,")
        if entrada.get("argumento"):
            if not contenido or contenido not in frase:
                continue
        else:
            contenido = ""
        if frase in semillas:
            continue
        leccion = compartir.preparar_leccion(frase, entrada["id"], contenido)
        if leccion is None:
            continue
        clave = (leccion["frase"], leccion["intencion"])
        if clave in vistas:
            continue
        vistas.add(clave)
        buenas.append(leccion)
    return buenas


# ------------------------------------------------------------------
# El turno
# ------------------------------------------------------------------
def _hoy_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")


class Turno:
    def __init__(self, supa, llamar, rng=None, pausa=PAUSA_ENTRE_LLAMADAS, avisar=print):
        self.supa = supa
        self.llamar = llamar          # llamar(modelo, sistema, prompt, temperatura) -> texto
        self.rng = rng or random.Random()
        self.pausa = pausa
        self.avisar = avisar

    # --- configuracion y cuotas -----------------------------------
    def config(self):
        cfg = {f["clave"]: f["valor"] for f in self.supa.leer("arche_config", {"select": "clave,valor"})}
        cuota = dict(CUOTA_POR_DEFECTO)
        if isinstance(cfg.get("cuota_diaria"), dict):
            cuota.update({k: int(v) for k, v in cfg["cuota_diaria"].items() if str(v).isdigit()})
        return {"activos": cfg.get("turnos_activos", True) is not False, "cuota": cuota}

    def gastado_hoy(self, tarea):
        filas = self.supa.leer("arche_turnos", {"select": "pedidos", "tarea": f"eq.{tarea}",
                                                "inicio": f"gte.{_hoy_utc()}"})
        return sum(int(f.get("pedidos") or 0) for f in filas)

    # --- cuantos ejemplos hay por intencion ------------------------
    def conteos(self):
        conteo = {f["intencion"]: int(f.get("ejemplos") or 0)
                  for f in self.supa.leer("arche_conteos", {"select": "intencion,ejemplos"})}
        # lo de la nube que el PC todavia no bajo tambien cuenta
        del_pc_hasta = max((f.get("actualizado") or "" for f in
                            self.supa.leer("arche_conteos", {"select": "actualizado", "order": "actualizado.desc",
                                                             "limit": "1"})), default="")
        params = {"select": "intencion", "origen": "neq.pc", "retirado": "is.false"}
        if del_pc_hasta:
            params["creado"] = f"gt.{del_pc_hasta}"
        for f in self.supa.leer_todo("arche_ejemplos", params):
            conteo[f["intencion"]] = conteo.get(f["intencion"], 0) + 1
        return conteo

    def frases_existentes(self, intencion):
        filas = self.supa.leer_todo("arche_ejemplos", {"select": "frase,intencion", "intencion": f"eq.{intencion}"})
        return {(f["frase"], f["intencion"]) for f in filas}

    # --- elegir en que trabajar ------------------------------------
    def elegir(self, tarea, todas, conteo, cuantas):
        if tarea == "huecos":
            con_hueco = [e for e in todas if conteo.get(e["id"], 0) < META_EJEMPLOS]
            self.rng.shuffle(con_hueco)                      # desempate al azar
            con_hueco.sort(key=lambda e: conteo.get(e["id"], 0))
            return con_hueco[:cuantas]
        # dificiles: al azar, pero mas probable para las que ya tienen ejemplos (ahi conviene apretar)
        pesos = [1 + min(conteo.get(e["id"], 0), META_EJEMPLOS) for e in todas]
        elegidas, pool = [], list(zip(todas, pesos))
        while pool and len(elegidas) < cuantas:
            total = sum(p for _, p in pool)
            r, acum = self.rng.uniform(0, total), 0
            for i, (e, p) in enumerate(pool):
                acum += p
                if acum >= r:
                    elegidas.append(e)
                    pool.pop(i)
                    break
        return elegidas

    # --- trabajar una intencion -----------------------------------
    def _llamar_con_respaldo(self, modelos, prompt, temperatura):
        ultimo = None
        for modelo in modelos:
            try:
                return self.llamar(modelo, SISTEMA, prompt, temperatura), modelo
            except CupoAgotado as e:
                ultimo = e
        raise ultimo

    def trabajar(self, entrada, estilo, todas):
        """Devuelve (filas_aprobadas, llamadas_gastadas, rechazadas)."""
        llamadas = 0
        texto, _ = self._llamar_con_respaldo([MODELO_PROFESOR, MODELO_JUEZ], prompt_generar(entrada, estilo), 0.9)
        llamadas += 1
        datos = json_de(texto) or {}
        candidatas = filtrar_candidatas(entrada, datos.get("frases"), self.frases_existentes(entrada["id"]))
        crudas = len(datos.get("frases") or [])
        if not candidatas:
            return [], llamadas, crudas
        time.sleep(self.pausa)

        opciones = opciones_para_juez(entrada, todas, self.rng)
        texto, juez = self._llamar_con_respaldo([MODELO_JUEZ, MODELO_PROFESOR],
                                                prompt_juez([c["frase"] for c in candidatas], opciones), 0.0)
        llamadas += 1
        respuestas = (json_de(texto) or {}).get("respuestas") or []
        aprobadas = []
        for i, c in enumerate(candidatas):
            veredicto = str(respuestas[i]).strip() if i < len(respuestas) else ""
            if veredicto == entrada["id"]:
                aprobadas.append(dict(c, origen=f"turno_{estilo}", pc="nube", validado_por=juez))
        return aprobadas, llamadas, crudas - len(aprobadas)

    # --- una tarea completa ---------------------------------------
    def tarea(self, nombre, cfg, todas, conteo):
        gastado = self.gastado_hoy(nombre)
        disponible = cfg["cuota"].get(nombre, 0) - gastado
        if disponible < 2:
            self.avisar(f"[{nombre}] cuota de hoy usada ({gastado}/{cfg['cuota'].get(nombre, 0)}). Sigo mañana.")
            return
        cuantas = min(INTENCIONES_POR_TURNO[nombre], disponible // 2)
        elegidas = self.elegir(nombre, todas, conteo, cuantas)
        if not elegidas:
            self.avisar(f"[{nombre}] no hay intenciones con hueco. ¡Todo cubierto!")
            return
        pedidos = aceptados = rechazados = 0
        nota = ""
        for entrada in elegidas:
            try:
                filas, gasto, malas = self.trabajar(entrada, nombre, todas)
            except CupoAgotado as e:
                nota = str(e)
                self.avisar(f"[{nombre}] {e}. Paro por hoy sin error.")
                break
            except ErrorTurno as e:
                nota = str(e)[:200]
                self.avisar(f"[{nombre}] {entrada['id']}: {e}")
                pedidos += 1
                continue
            pedidos += gasto
            guardadas = self.supa.insertar("arche_ejemplos", filas, conflicto="frase,intencion")
            aceptados += len(guardadas)
            rechazados += malas + (len(filas) - len(guardadas))
            self.avisar(f"[{nombre}] {entrada['id']}: +{len(guardadas)} (descarté {malas})")
            time.sleep(self.pausa)
        self.supa.insertar("arche_turnos", [{"tarea": nombre, "pedidos": pedidos, "aceptados": aceptados,
                                             "rechazados": rechazados, "nota": nota}])
        self.avisar(f"[{nombre}] listo: {aceptados} ejemplos nuevos, {rechazados} descartados, {pedidos} llamadas.")

    def correr(self, solo_probar=False):
        cfg = self.config()        # esta lectura tambien mantiene despierto a Supabase
        if not cfg["activos"]:
            self.avisar("Los turnos están apagados (arche_config.turnos_activos = false). No hago nada.")
            return 0
        todas = intenciones_permitidas()
        conteo = self.conteos()
        huecos = sum(1 for e in todas if conteo.get(e["id"], 0) < META_EJEMPLOS)
        self.avisar(f"Arché en la nube: {len(todas)} intenciones que se pueden practicar, {huecos} con hueco.")
        if solo_probar:
            for t in ("huecos", "dificiles"):
                self.avisar(f"  {t}: {self.gastado_hoy(t)}/{cfg['cuota'].get(t, 0)} llamadas usadas hoy")
            return 0
        for nombre in ("huecos", "dificiles"):
            self.tarea(nombre, cfg, todas, conteo)
        return 0


def main(argv):
    url, clave, groq = (os.environ.get(n, "").strip() for n in
                        ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GROQ_API_KEY"))
    faltan = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", clave), ("GROQ_API_KEY", groq)) if not v]
    if faltan:
        print("Faltan secretos: " + ", ".join(faltan) + ". Agrégalos en GitHub -> Settings -> "
              "Secrets and variables -> Actions. No hice nada.")
        return 0
    supa = Supabase(url, clave)

    def llamar(modelo, sistema, prompt, temperatura):
        return _llamar_groq(groq, modelo, sistema, prompt, temperatura=temperatura)

    try:
        return Turno(supa, llamar).correr(solo_probar="--probar" in argv)
    except ErrorTurno as e:
        print(f"El turno no pudo terminar: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
