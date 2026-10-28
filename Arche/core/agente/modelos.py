"""
modelos.py
----------
Ubicacion: Arche/core/agente/modelos.py

La capa de modelos de IA del agente. El resto del agente nunca habla con un
modelo concreto: le pide algo a un ROL ("planificador", "decisor",
"verificador", "reflexion", "vision") y el Enrutador decide que modelo lo
atiende. Asi se cambia o se agrega un modelo sin tocar nada mas.

Proveedores incluidos:
  ollama[:modelo]            modelos locales (si no dices cual, elige uno instalado)
  nube                       la nube de Arché (core/IA/nube.py: Groq, etc., con su respaldo)
  compat:<url>#<modelo>      cualquier servidor compatible con OpenAI (LM Studio,
                             llama.cpp, vLLM...). Ej.: compat:http://localhost:1234/v1#qwen2.5-7b
  auto                       (por defecto) nube si hay y funciona, si no Ollama

Para agregar otro proveedor: crea una subclase de Modelo y registrala con
registrar_proveedor("miprov", lambda argumento: MiModelo(argumento)).

Todo usa solo la libreria estandar (urllib), sin instalar nada.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from core.agente import config

ROLES = ("planificador", "decisor", "verificador", "reflexion", "vision")

_RE_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.S | re.I)


class ErrorModelo(Exception):
    """El modelo no respondio (no esta, no hay internet, limite de uso, etc.)."""


class _ErrorLimite(ErrorModelo):
    """La nube dijo "demasiadas peticiones" (429): suele ser el limite por minuto, que se pasa esperando."""


# Segundos de espera antes de cada reintento (la ventana de los limites por minuto es de 60 s).
ESPERAS_LIMITE = (25, 40, 65)


def quitar_pensamiento(texto: str) -> str:
    return _RE_PENSAMIENTO.sub("", texto or "").strip()


def _http_json(url, payload=None, encabezados=None, timeout=180):
    datos = json.dumps(payload).encode("utf-8") if payload is not None else None
    cab = {"Content-Type": "application/json", "User-Agent": "Arche-Agente/1.0"}
    cab.update(encabezados or {})
    req = urllib.request.Request(url, data=datos, headers=cab, method="POST" if datos is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        cuerpo = ""
        try:
            cuerpo = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise ErrorModelo(f"HTTP {e.code}: {cuerpo}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorModelo(f"no se pudo conectar ({e})") from None
    except ValueError:
        raise ErrorModelo("la respuesta no era JSON") from None


# ------------------------------------------------------------------
# Modelos
# ------------------------------------------------------------------

class Modelo:
    nombre = "modelo"
    soporta_imagenes = False

    def responder(self, mensajes, sistema=None, imagenes=None, max_tokens=700,
                  temperatura=0.2, formato_json=False) -> str:
        raise NotImplementedError

    def describir(self) -> str:
        return self.nombre


def _host_ollama() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip() or "127.0.0.1:11434"
    if not host.startswith("http"):
        host = "http://" + host
    return host.rstrip("/")


def listar_ollama(host=None) -> list[str]:
    """Nombres de los modelos instalados en Ollama ([] si no corre)."""
    try:
        datos = _http_json((host or _host_ollama()) + "/api/tags", timeout=4)
    except ErrorModelo:
        return []
    return [m.get("name", "") for m in datos.get("models", []) if m.get("name")]


_RE_VISION = re.compile(r"(llava|vision|qwen2\.5vl|qwen3-vl|minicpm-v|moondream|gemma3|bakllava)", re.I)
_RE_NO_TEXTO = re.compile(r"(embed|nomic|bge|minilm|arche)", re.I)
_PREFERIDOS = ("qwen3", "qwen2.5", "llama3.1", "llama3.2", "llama3", "mistral", "gemma", "phi", "deepseek-r1")


def elegir_modelo_texto(instalados: list[str]) -> str | None:
    utiles = [m for m in instalados if not _RE_NO_TEXTO.search(m)]
    for pref in _PREFERIDOS:
        for m in utiles:
            if m.lower().startswith(pref) and "coder" not in m.lower():
                return m
    return utiles[0] if utiles else None


def elegir_modelo_vision(instalados: list[str]) -> str | None:
    for m in instalados:
        if _RE_VISION.search(m) and not _RE_NO_TEXTO.search(m):
            return m
    return None


class ModeloOllama(Modelo):
    def __init__(self, modelo: str | None = None, vision: bool = False, host: str | None = None):
        self._modelo = modelo
        self._vision = vision
        self.host = host or _host_ollama()
        self.soporta_imagenes = vision or bool(modelo and _RE_VISION.search(modelo))

    @property
    def modelo(self) -> str:
        if not self._modelo:
            instalados = listar_ollama(self.host)
            elegido = elegir_modelo_vision(instalados) if self._vision else elegir_modelo_texto(instalados)
            if not elegido:
                raise ErrorModelo("Ollama no está corriendo o no tiene un modelo adecuado instalado"
                                  + (" (de visión)" if self._vision else ""))
            self._modelo = elegido
        return self._modelo

    @property
    def nombre(self):
        return f"ollama:{self._modelo or 'auto'}"

    def responder(self, mensajes, sistema=None, imagenes=None, max_tokens=700,
                  temperatura=0.2, formato_json=False) -> str:
        msgs = []
        if sistema:
            msgs.append({"role": "system", "content": sistema})
        msgs.extend({"role": m["role"], "content": m["content"]} for m in mensajes)
        if imagenes and msgs:
            for m in reversed(msgs):
                if m["role"] == "user":
                    m["images"] = [base64.b64encode(i).decode("ascii") for i in imagenes]
                    break
        carga = {"model": self.modelo, "messages": msgs, "stream": False, "keep_alive": "10m",
                 "options": {"num_predict": max_tokens, "temperature": temperatura}}
        if formato_json:
            carga["format"] = "json"
        datos = _http_json(self.host + "/api/chat", carga, timeout=300)
        texto = ((datos.get("message") or {}).get("content") or "").strip()
        if not texto:
            raise ErrorModelo("Ollama devolvió una respuesta vacía")
        return quitar_pensamiento(texto)


class ModeloNubeArche(Modelo):
    """La nube que Arché ya tiene configurada (Groq, etc., con su respaldo)."""
    nombre = "nube"
    enrutador = None          # lo pone el Enrutador; sirve para esperar sin bloquear la parada

    def _esperar(self, segundos: int, intento: int, total: int) -> bool:
        """Espera ante un limite de uso. Devuelve False si el usuario pidio parar."""
        r = self.enrutador
        if r is not None and r.avisar:
            r.avisar(f"La nube me pide ir más despacio (límite por minuto). Espero {segundos} s y reintento ({intento}/{total}).")
        if r is not None and r.parada is not None:
            return not r.parada.wait(segundos)
        time.sleep(segundos)
        return True

    def responder(self, mensajes, sistema=None, imagenes=None, max_tokens=700,
                  temperatura=0.2, formato_json=False) -> str:
        if imagenes:
            raise ErrorModelo("la nube de Arché no recibe imágenes aquí")
        esperas = ESPERAS_LIMITE
        for intento in range(len(esperas) + 1):
            try:
                return self._responder_una_vez(mensajes, sistema, max_tokens, temperatura)
            except _ErrorLimite as e:
                if intento >= len(esperas):
                    raise ErrorModelo(f"{e} Sigue el límite tras esperar {sum(esperas)} s: probablemente es el tope "
                                      "diario de la nube gratuita; se renueva en unas horas.") from None
                if not self._esperar(esperas[intento], intento + 1, len(esperas)):
                    raise ErrorModelo("Detenido por el usuario mientras esperaba el límite de la nube.") from None

    def _responder_una_vez(self, mensajes, sistema, max_tokens, temperatura) -> str:
        try:
            from core.IA import nube
        except Exception as e:
            raise ErrorModelo(f"no se pudo cargar la nube de Arché ({e})") from None
        msgs = []
        for m in mensajes:
            if msgs and msgs[-1]["role"] == m["role"]:
                msgs[-1]["content"] += "\n\n" + m["content"]
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        try:
            texto = nube.responder(msgs, sistema=sistema, max_tokens=max_tokens, temperature=temperatura)
        except nube.ErrorNube as e:
            if getattr(e, "codigo", None) == 429:
                raise _ErrorLimite(str(e)) from None
            raise ErrorModelo(str(e)) from None
        self._avisar_si_fue_respaldo(nube)
        return quitar_pensamiento(texto or "")

    _aviso_previo = ""

    def _avisar_si_fue_respaldo(self, nube):
        """Si contesto una nube de respaldo, que se note (una sola vez por motivo)."""
        try:
            uso = nube.ultimo_uso()
        except Exception:
            return
        aviso = uso.get("aviso") or ""
        r = self.enrutador
        if aviso and aviso != self._aviso_previo and r is not None and r.avisar:
            r.avisar(f"Contestó la nube de RESPALDO ({uso.get('proveedor')}): {aviso}")
        self._aviso_previo = aviso


class ModeloCompatibleOpenAI(Modelo):
    def __init__(self, base_url: str, modelo: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.modelo = modelo
        self.api_key = api_key or os.environ.get("ARCHE_AGENTE_CLAVE", "")
        self.soporta_imagenes = bool(_RE_VISION.search(modelo))

    @property
    def nombre(self):
        return f"compat:{self.base_url}#{self.modelo}"

    def responder(self, mensajes, sistema=None, imagenes=None, max_tokens=700,
                  temperatura=0.2, formato_json=False) -> str:
        msgs = []
        if sistema:
            msgs.append({"role": "system", "content": sistema})
        msgs.extend({"role": m["role"], "content": m["content"]} for m in mensajes)
        if imagenes:
            for m in reversed(msgs):
                if m["role"] == "user":
                    partes = [{"type": "text", "text": m["content"]}]
                    for img in imagenes:
                        url = "data:image/jpeg;base64," + base64.b64encode(img).decode("ascii")
                        partes.append({"type": "image_url", "image_url": {"url": url}})
                    m["content"] = partes
                    break
        cab = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        datos = _http_json(self.base_url + "/chat/completions",
                           {"model": self.modelo, "messages": msgs, "max_tokens": max_tokens,
                            "temperature": temperatura}, cab, timeout=300)
        try:
            texto = datos["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ErrorModelo("respuesta inesperada del servidor compatible") from None
        return quitar_pensamiento(texto or "")


class ModeloFalso(Modelo):
    """Para pruebas: responde con una funcion tuya y anota las llamadas."""
    soporta_imagenes = True

    def __init__(self, funcion, nombre="falso"):
        self.funcion = funcion
        self.nombre = nombre
        self.llamadas: list[dict] = []

    def responder(self, mensajes, sistema=None, imagenes=None, max_tokens=700,
                  temperatura=0.2, formato_json=False) -> str:
        self.llamadas.append({"mensajes": mensajes, "sistema": sistema, "imagenes": imagenes})
        return self.funcion(mensajes, sistema, imagenes)


# ------------------------------------------------------------------
# Registro de proveedores (aqui se agregan modelos nuevos)
# ------------------------------------------------------------------

_PROVEEDORES = {}


def registrar_proveedor(nombre: str, fabrica) -> None:
    """fabrica(argumento_o_None) -> Modelo."""
    _PROVEEDORES[nombre] = fabrica


registrar_proveedor("ollama", lambda arg: ModeloOllama(arg or None))
registrar_proveedor("nube", lambda arg: ModeloNubeArche())


def _compat(arg):
    if not arg or "#" not in arg:
        raise ErrorModelo("usa compat:<url>#<modelo>, por ejemplo compat:http://localhost:1234/v1#mi-modelo")
    url, modelo = arg.split("#", 1)
    return ModeloCompatibleOpenAI(url, modelo)


registrar_proveedor("compat", _compat)


def spec_valida(spec: str) -> bool:
    spec = (spec or "").strip()
    if spec in ("auto", ""):
        return True
    return spec.split(":", 1)[0] in _PROVEEDORES


# ------------------------------------------------------------------
# JSON que se le pide a los modelos
# ------------------------------------------------------------------

def _cargar(trozo: str):
    for intento in (trozo, re.sub(r",\s*([}\]])", r"\1", trozo)):
        try:
            return json.loads(intento)
        except ValueError:
            continue
    return None


def extraer_json(texto: str):
    """Saca el primer objeto JSON de la respuesta de un modelo (tolera ```json, texto alrededor, comas de sobra)."""
    t = re.sub(r"```(?:json)?", "", quitar_pensamiento(texto or ""))
    inicio = t.find("{")
    while inicio != -1:
        profundidad, en_cadena, escape = 0, False, False
        for i in range(inicio, len(t)):
            c = t[i]
            if en_cadena:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    en_cadena = False
                continue
            if c == '"':
                en_cadena = True
            elif c == "{":
                profundidad += 1
            elif c == "}":
                profundidad -= 1
                if profundidad == 0:
                    dato = _cargar(t[inicio:i + 1])
                    if isinstance(dato, dict):
                        return dato
                    break
        inicio = t.find("{", inicio + 1)
    return None


def pedir_json(router, rol, mensajes, sistema=None, validar=None, reintentos=2,
               max_tokens=700, temperatura=0.2, imagenes=None):
    """
    Le pide un JSON al rol. Si la respuesta no sirve, se lo vuelve a pedir
    diciendole que fallo. Devuelve el dict o None. Si no hay ningun modelo
    disponible lanza ErrorModelo.
    """
    historial = list(mensajes)
    for _ in range(reintentos + 1):
        texto = router.responder(rol, historial, sistema=sistema, max_tokens=max_tokens,
                                 temperatura=temperatura, formato_json=True, imagenes=imagenes)
        dato = extraer_json(texto)
        if dato is not None:
            problema = validar(dato) if validar else None
            if not problema:
                return dato
        else:
            problema = "no era un objeto JSON"
        historial = historial + [
            {"role": "assistant", "content": texto[:1500]},
            {"role": "user", "content": f"Tu respuesta no sirvió ({problema}). Responde SOLO con un objeto "
                                        "JSON válido con el formato pedido, sin texto antes ni después."},
        ]
    return None


# ------------------------------------------------------------------
# Enrutador: rol -> modelo
# ------------------------------------------------------------------

class Enrutador:
    def __init__(self, fijos: dict | None = None):
        """fijos: {rol: Modelo} para forzar modelos concretos (pruebas o uso programático)."""
        self._fijos = dict(fijos or {})
        self.parada = None          # threading.Event del agente: corta las esperas
        self.avisar = None          # funcion(texto) para contar que esta esperando
        self._cache: dict[str, Modelo] = {}
        self._nube_ok = (0.0, False)

    # --- configuracion ---------------------------------------------
    def specs(self) -> dict:
        guardado = config.leer_json("modelos.json", {}).get("roles", {})
        return {r: guardado.get(r, "auto") for r in ROLES}

    def spec(self, rol: str) -> str:
        return self.specs().get(rol, "auto")

    def fijar(self, rol: str, spec: str) -> None:
        if rol not in ROLES:
            raise ValueError(f"rol desconocido: {rol}. Roles: {', '.join(ROLES)}")
        if not spec_valida(spec):
            raise ValueError(f"proveedor desconocido: {spec}. Usa auto, nube, ollama[:modelo] o compat:<url>#<modelo>")
        datos = config.leer_json("modelos.json", {})
        datos.setdefault("roles", {})[rol] = spec
        config.guardar_json("modelos.json", datos)
        self._cache.pop(spec, None)

    # --- resolucion --------------------------------------------------
    def _nube_disponible(self) -> bool:
        ts, valor = self._nube_ok
        if time.time() - ts < 30:
            return valor
        try:
            from core.IA import nube
            valor = bool(nube.disponible())
        except Exception:
            valor = False
        self._nube_ok = (time.time(), valor)
        return valor

    def _crear(self, spec: str, rol: str) -> Modelo:
        if spec in self._cache:
            return self._cache[spec]
        nombre, _, arg = spec.partition(":")
        if rol == "vision" and nombre == "ollama" and not arg:
            modelo = ModeloOllama(None, vision=True)
        else:
            modelo = _PROVEEDORES[nombre](arg or None)
        if hasattr(modelo, "enrutador"):
            modelo.enrutador = self
        self._cache[spec] = modelo
        return modelo

    def candidatos(self, rol: str) -> list[Modelo]:
        if rol in self._fijos:
            return [self._fijos[rol]]
        spec = self.spec(rol)
        if spec != "auto":
            return [self._crear(spec, rol)]
        if rol == "vision":
            return [self._crear("ollama", "vision")]
        lista = []
        if self._nube_disponible():
            lista.append(self._crear("nube", rol))
        lista.append(self._crear("ollama", rol))
        return lista

    def modelo(self, rol: str) -> Modelo | None:
        c = self.candidatos(rol)
        return c[0] if c else None

    def hay_vision(self) -> bool:
        if "vision" in self._fijos:
            return True
        spec = self.spec("vision")
        if spec != "auto":
            return True
        return elegir_modelo_vision(listar_ollama()) is not None

    # --- uso ---------------------------------------------------------
    def responder(self, rol: str, mensajes, sistema=None, max_tokens=700, temperatura=0.2,
                  formato_json=False, imagenes=None) -> str:
        errores = []
        for m in self.candidatos(rol):
            if imagenes and not m.soporta_imagenes:
                errores.append(f"{m.nombre}: no recibe imágenes")
                continue
            try:
                return m.responder(mensajes, sistema=sistema, imagenes=imagenes, max_tokens=max_tokens,
                                   temperatura=temperatura, formato_json=formato_json)
            except ErrorModelo as e:
                errores.append(f"{m.nombre}: {e}")
        raise ErrorModelo(f"ningún modelo atendió el rol '{rol}' ({'; '.join(errores) or 'sin candidatos'})")

    def estado(self) -> str:
        filas = []
        for rol in ROLES:
            spec = self.spec(rol)
            if rol in self._fijos:
                spec = f"fijo ({self._fijos[rol].nombre})"
            elif spec == "auto":
                spec = "auto (nube si hay, si no Ollama)" if rol != "vision" else "auto (modelo de visión de Ollama si hay)"
            filas.append(f"  {rol}: {spec}")
        instalados = listar_ollama()
        filas.append("  Ollama instalado: " + (", ".join(instalados[:8]) if instalados else "no responde o sin modelos"))
        return "\n".join(filas)
