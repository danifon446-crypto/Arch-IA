"""
Pruebas de la nube con varios proveedores (core/IA/nube.py), de sus comandos
(core/IA/cerebro.py) y de que Arché APRENDA de ella (core/IA/aprender_de_nube.py).
No usan internet, ni claves, ni tocan tu Database: todo va a una carpeta
temporal y la nube se simula.

Uso:  cd Arche && python prueba_nube_aprendizaje.py
"""

import contextlib
import io
import os
import sys
import tempfile
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import voz
from core.IA import aprender_de_nube as adn
from core.IA import aprendizaje, catalogo, cerebro, enrutador_natural, nube, respuestas

fallos = 0
CARPETA = tempfile.mkdtemp(prefix="arche_nube_")
AQUI = os.path.dirname(os.path.abspath(__file__))


def chequear(nombre, obtenido, esperado):
    global fallos
    ok = obtenido == esperado
    print(("OK   " if ok else "FALLA"), nombre)
    if not ok:
        fallos += 1
        print(f"      esperado: {esperado!r}\n      obtenido: {obtenido!r}")


def callado(f, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = f(*a, **k)
    return r, buf.getvalue()


def nube_aislada():
    """Config y claves de la nube en una carpeta temporal, sin variables de entorno."""
    d = tempfile.mkdtemp(dir=CARPETA)
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")}
    pila = contextlib.ExitStack()
    pila.enter_context(mock.patch.object(nube, "DATABASE", d))
    pila.enter_context(mock.patch.object(nube, "ARCHIVO_CONFIG", os.path.join(d, "nube.json")))
    pila.enter_context(mock.patch.object(nube, "ARCHIVO_CLAVE", os.path.join(d, "nube_clave.txt")))
    pila.enter_context(mock.patch.dict(os.environ, entorno, clear=True))
    return pila


# ---------------------------------------------------------------- proveedores
with nube_aislada():
    chequear("proveedor por defecto: groq (gratis)", nube.proveedor(), "groq")
    chequear("groq y gemini son gratis, anthropic no",
             [nube.PROVEEDORES[p]["gratis"] for p in ("groq", "gemini", "anthropic")], [True, True, False])
    chequear("modelo por defecto de groq", nube.modelo(), "openai/gpt-oss-120b")
    nube.fijar_proveedor("gemini")
    chequear("cambiar de proveedor", nube.proveedor(), "gemini")
    nube.fijar_modelo("gemini-x")
    nube.fijar_proveedor("groq")
    chequear("cada proveedor recuerda su modelo", (nube.modelo(), nube.modelo("gemini")), ("openai/gpt-oss-120b", "gemini-x"))
    try:
        nube.fijar_proveedor("nada")
        desconocido = "lo aceptó"
    except ValueError:
        desconocido = "ValueError"
    chequear("proveedor desconocido: error", desconocido, "ValueError")

    nube.guardar_clave("clave-groq", "groq")
    nube.guardar_clave("clave-claude", "anthropic")
    chequear("claves separadas por proveedor",
             (nube.clave("groq"), nube.clave("anthropic"), nube.clave("gemini")), ("clave-groq", "clave-claude", ""))
    chequear("la clave de anthropic sigue en el archivo de siempre",
             os.path.basename(nube._archivo_clave("anthropic")), "nube_clave.txt")
    with mock.patch.dict(os.environ, {"GROQ_API_KEY": "del-entorno"}):
        chequear("la variable de entorno manda sobre el archivo", nube.clave("groq"), "del-entorno")
    chequear("borrar la clave de uno no toca la otra",
             (nube.borrar_clave("groq"), nube.clave("groq"), nube.clave("anthropic")), (True, "", "clave-claude"))

    chequear("memoria: gratis -> no se comparte por defecto", nube.envia_memoria(), False)
    nube.fijar_proveedor("anthropic")
    chequear("memoria: de pago -> se comparte por defecto", nube.envia_memoria(), True)
    nube.fijar_envia_memoria(False)
    chequear("memoria: lo que tu digas manda", nube.envia_memoria(), False)

    # ---- formato OpenAI (groq / gemini)
    nube.fijar_proveedor("groq")
    nube.guardar_clave("k-groq", "groq")
    llamadas = []

    def post_ok(url, payload, encabezados, metodo="POST"):
        llamadas.append((url, payload, encabezados, metodo))
        return {"choices": [{"message": {"content": "<think>pienso...</think> Hola desde groq "}}]}

    with mock.patch.object(nube, "_post", post_ok):
        texto = nube.responder([{"role": "user", "content": "hola"}], sistema="eres arche", max_tokens=500)
    url, payload, enc, metodo = llamadas[0]
    chequear("groq: devuelve el texto sin el pensamiento", texto, "Hola desde groq")
    chequear("groq: url de chat", url, "https://api.groq.com/openai/v1/chat/completions")
    chequear("groq: clave como Bearer", enc.get("authorization"), "Bearer k-groq")
    chequear("groq: el sistema va primero", payload["messages"][0], {"role": "system", "content": "eres arche"})
    chequear("groq: piensa poco y deja margen para ello",
             (payload.get("reasoning_effort"), payload["max_tokens"]), ("low", 500 + nube.MARGEN_RAZONAMIENTO))

    pedidos = []

    def post_rechaza_razonamiento(url, payload, encabezados, metodo="POST"):
        pedidos.append(dict(payload))
        if "reasoning_effort" in payload:
            raise nube.ErrorNube("no", codigo=400)
        return {"choices": [{"message": {"content": "ok sin razonar"}}]}

    with mock.patch.object(nube, "_post", post_rechaza_razonamiento):
        texto = nube.responder([{"role": "user", "content": "hola"}])
    chequear("si el modelo no acepta 'reasoning_effort' reintenta sin él",
             (texto, len(pedidos), "reasoning_effort" in pedidos[1]), ("ok sin razonar", 2, False))

    with mock.patch.object(nube, "_post", lambda *a, **k: {"choices": [{"message": {"content": None}}]}):
        try:
            nube.responder([{"role": "user", "content": "hola"}])
            vacio = "no lanzó"
        except nube.ErrorNube as e:
            vacio = str(e)
    chequear("respuesta vacía -> error para que Ollama responda", vacio, "la nube no devolvió texto")

    def post_429(*a, **k):
        raise nube.ErrorNube("limite", codigo=429)

    with mock.patch.object(nube, "_post", post_429):
        try:
            nube.responder([{"role": "user", "content": "hola"}])
        except nube.ErrorNube as e:
            chequear("el código 429 se conserva en el error", e.codigo, 429)
    chequear("429 en gratis: lo explica como limite gratuito", "gratuito" in nube._explicar_http(429), True)
    nube.fijar_proveedor("anthropic")
    chequear("429 en de pago: mensaje distinto", "gratuito" in nube._explicar_http(429), False)

    # ---- formato Anthropic
    nube.guardar_clave("k-claude", "anthropic")
    llamadas.clear()

    def post_claude(url, payload, encabezados, metodo="POST"):
        llamadas.append((url, payload, encabezados))
        return {"content": [{"type": "text", "text": "Hola desde Claude"}]}

    with mock.patch.object(nube, "_post", post_claude):
        texto = nube.responder([{"role": "user", "content": "hola"}], sistema="eres arche")
    url, payload, enc = llamadas[0]
    chequear("anthropic: texto", texto, "Hola desde Claude")
    chequear("anthropic: url y encabezados", (url, enc.get("x-api-key"), "anthropic-version" in enc),
             ("https://api.anthropic.com/v1/messages", "k-claude", True))
    chequear("anthropic: el sistema va aparte", (payload.get("system"), "reasoning_effort" in payload), ("eres arche", False))

    # ---- modelos y prueba
    nube.fijar_proveedor("gemini")
    nube.guardar_clave("k-gem", "gemini")
    modelos = {"data": [{"id": "models/gemini-a"}, {"id": "models/gemini-b"}, {"id": "gemini-a"}]}
    with mock.patch.object(nube, "_post", lambda *a, **k: modelos):
        chequear("modelos disponibles: sin prefijo y sin repetidos", nube.modelos_disponibles(), ["gemini-a", "gemini-b"])

    def post_404(url, payload, encabezados, metodo="POST"):
        if metodo == "GET":
            return modelos
        raise nube.ErrorNube("no conozco el modelo", codigo=404)

    with mock.patch.object(nube, "_post", post_404):
        ok, mensaje = nube.probar()
    chequear("modelo que no existe: la prueba sugiere cuáles hay", (ok, "gemini-a" in mensaje), (False, True))

# ------------------------------------------------ claves y errores claros
chequear("limpiar clave: espacios, comillas y 'Bearer'", nube.limpiar_clave('  "Bearer gsk_abc123"\n'), "gsk_abc123")
chequear("limpiar clave: caracteres invisibles del pegado", nube.limpiar_clave("gsk_ab\x16c\u200b1"), "gsk_abc1")
with nube_aislada():
    nube.fijar_proveedor("groq")
    chequear("describir clave: la reconoce", nube.describir_clave("gsk_abcdef123456"),
             "Recibí una clave de 16 caracteres que empieza por «gsk_».")
    chequear("describir clave: avisa si no empieza como debe", "empiezan por «gsk_»" in nube.describir_clave("sk-ant-xxxx"), True)
    chequear("describir clave: nada pegado", nube.describir_clave("\x16"), "No recibí nada.")
    nube.guardar_clave('  "gsk_limpia"  ', "groq")
    chequear("guardar clave la guarda ya limpia", nube.clave("groq"), "gsk_limpia")
chequear("401: dice que la clave no es válida y el motivo",
         ("401" in nube._explicar_http(401, '{"error":{"message":"Invalid API Key"}}'),
          "Invalid API Key" in nube._explicar_http(401, '{"error":{"message":"Invalid API Key"}}')), (True, True))
msg = nube._explicar_http(403, "<html><body>error code: 1010</body></html>")
chequear("403: muestra el motivo real y sugiere red/VPN/antivirus", ("1010" in msg, "VPN" in msg, "clave no sirve" in msg), (True, True, False))

enviados = []


class RespuestaFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok": true}'


def abrir_falso(peticion, timeout=None):
    enviados.append(peticion)
    return RespuestaFalsa()


with mock.patch("urllib.request.urlopen", abrir_falso):
    nube._post("https://x.test/v1", {"a": 1}, {"authorization": "Bearer k"})
chequear("_post se identifica con un User-Agent propio (no el de Python)",
         enviados[0].get_header("User-agent"), nube.USER_AGENT)
chequear("_post conserva la clave", enviados[0].get_header("Authorization"), "Bearer k")

# ------------------------------------------------------------ cerebro: comandos
for frase, esperado in {
    "usa la nube de groq": ("proveedor_nube", "groq"), "usa gemini": ("proveedor_nube", "gemini"),
    "usa claude": ("proveedor_nube", "anthropic"), "usa el modelo qwen3.8-27b": ("modelo_nube", "qwen3.8-27b"),
    "que modelos hay en la nube": ("modelos_nube", None),
    "comparte mi memoria con la nube": ("compartir_memoria", True),
    "no compartas mi memoria con la nube": ("no_compartir_memoria", False),
}.items():
    chequear(f"cerebro entiende '{frase}'", cerebro.interpretar(frase), esperado)

for entrada, esperado in (("2", "gemini"), ("", "groq"), ("claude", "anthropic"), ("google", "gemini"),
                          ("1", "groq"), ("nada", None), ("9", None)):
    with nube_aislada():
        r, _ = callado(cerebro._elegir_proveedor, lambda p, e=entrada: e)
    chequear(f"elegir proveedor con '{entrada}'", r, esperado)

with nube_aislada():
    callado(cerebro.manejar, "usa la nube de gemini")
    chequear("manejar: cambia de proveedor", nube.proveedor(), "gemini")
    callado(cerebro.manejar, "comparte mi memoria con la nube")
    chequear("manejar: compartir memoria", nube.envia_memoria(), True)
    callado(cerebro.manejar, "no compartas mi memoria con la nube")
    chequear("manejar: no compartir memoria", nube.envia_memoria(), False)
    fake_memoria = mock.MagicMock()
    fake_memoria.resumen_para_contexto = lambda: "DATO PERSONAL"
    with mock.patch.dict(sys.modules, {"core.memoria": fake_memoria}), \
            mock.patch("core.configuracion.obtener", lambda k: "Hlo"):
        sin = cerebro._sistema_para_nube()
        nube.fijar_envia_memoria(True)
        con = cerebro._sistema_para_nube()
    chequear("sin permiso, el prompt de la nube NO lleva tu memoria", "DATO PERSONAL" in sin, False)
    chequear("con permiso, sí la lleva", "DATO PERSONAL" in con, True)

# ------------------------------------------------- aprender de la nube: intención
ESTADO = os.path.join(CARPETA, "aprendido.json")


class Mundo:
    """Nube simulada + aprendizaje simulado, para ver exactamente qué se aprende."""

    def __init__(self, respuesta_nube="", error=None, disponible=True):
        self.respuesta_nube, self.error, self.disponible = respuesta_nube, error, disponible
        self.pedidos, self.aprendido, self.guardado = [], [], []

    def __enter__(self):
        if os.path.exists(ESTADO):
            os.remove(ESTADO)
        adn._pausa_hasta, adn._ultima_charla = 0.0, 0.0

        def responder(mensajes, sistema=None, max_tokens=500, temperature=0.7):
            self.pedidos.append(mensajes[-1]["content"])
            if self.error:
                raise self.error
            return self.respuesta_nube

        self.pila = contextlib.ExitStack()
        e = self.pila.enter_context
        e(mock.patch.object(adn, "ARCHIVO", ESTADO))
        e(mock.patch.object(nube, "disponible", lambda: self.disponible))
        e(mock.patch.object(nube, "responder", responder))
        e(mock.patch.object(adn, "_en_segundo_plano", lambda f, *a: f(*a)))
        e(mock.patch.object(aprendizaje, "aprender", lambda p, a, c, fuente="ollama": self.aprendido.append((p, a, c, fuente))))
        e(mock.patch.object(respuestas, "guardar_respuesta", lambda p, r: self.guardado.append((p, r))))
        return self

    def __exit__(self, *a):
        self.pila.close()
        adn._pausa_hasta = 0.0


JSON_NOTA = ('{"intencion": "crear_nota", "contenido": "comprar leche", "parafrasis": ['
             '"anotame comprar leche", "guarda una nota de comprar leche", "apunta que hay que comprar leche", '
             '"recuerdame algo", "anotame comprar leche", "x"]}')

with Mundo(JSON_NOTA) as m:
    r = adn.resolver("oye apunta lo de la leche")
    chequear("resolver: devuelve la intención y el dato", r, ("crear_nota", "comprar leche"))
    chequear("aprende SOLO las formas que conservan el dato (sin repetidas ni sueltas)",
             [(p, a, c, f) for p, a, c, f in m.aprendido],
             [("anotame comprar leche", "crear_nota", "comprar leche", "nube"),
              ("guarda una nota de comprar leche", "crear_nota", "comprar leche", "nube"),
              ("apunta que hay que comprar leche", "crear_nota", "comprar leche", "nube")])
    est = adn._cargar()
    chequear("lo apunta: 1 intención, 3 formas", (est["total"]["intenciones"], est["total"]["frases"]), (1, 3))
    chequear("el pedido a la nube incluye el catálogo y la frase",
             ("crear_nota" in m.pedidos[0], "oye apunta lo de la leche" in m.pedidos[0]), (True, True))

with Mundo('{"intencion": "apagar_pc", "contenido": "", "parafrasis": ["apaga todo ya", "dale apaga el pc"]}') as m:
    r = adn.resolver("quiero dormir ya")
    chequear("intención delicada: se resuelve pero NO se aprenden formas solas", (r, m.aprendido), (("apagar_pc", ""), []))

with Mundo('{"intencion": "modificar_codigo", "contenido": "x", "parafrasis": ["cambia el codigo x"]}') as m:
    adn.resolver("toca tu codigo")
    chequear("dominio código: no se aprenden formas solas", m.aprendido, [])

with Mundo('{"intencion": "conversar", "contenido": "", "parafrasis": ["que tal tu dia"]}') as m:
    r = adn.resolver("que tal tu dia hoy")
    chequear("conversar: se devuelve y no se aprenden formas", (r, m.aprendido), (("conversar", ""), []))

with Mundo('{"intencion": "inventada", "contenido": ""}') as m:
    chequear("intención que no existe -> None", adn.resolver("lo que sea"), None)
with Mundo("esto no es json") as m:
    chequear("respuesta rara de la nube -> None", adn.resolver("lo que sea"), None)
with Mundo(JSON_NOTA, disponible=False) as m:
    chequear("sin nube: ni la llama", (adn.resolver("apunta algo"), m.pedidos), (None, []))
with Mundo(JSON_NOTA) as m:
    adn.activar(False)
    chequear("aprendizaje apagado: no hace nada", (adn.resolver("apunta algo"), m.pedidos), (None, []))
with Mundo(error=nube.ErrorNube("limite", codigo=429)) as m:
    chequear("la nube dice 'despacio' -> None", adn.resolver("apunta algo"), None)
    chequear("y descansa un rato antes de volver a pedir", adn._listo_para_nube(), False)
with Mundo(JSON_NOTA) as m:
    estado = adn._cargar()
    estado["dia"], estado["llamadas_hoy"] = adn._hoy(), adn.TOPE_DIARIO
    adn._guardar(estado)
    chequear("tope diario alcanzado -> no llama", (adn.resolver("apunta algo"), m.pedidos), (None, []))

# el enrutador usa la nube primero y Ollama de respaldo
with mock.patch.object(aprendizaje, "resolver", lambda t: None), \
        mock.patch.object(aprendizaje, "aprender", lambda *a, **k: None):
    with mock.patch.object(adn, "resolver", lambda t: ("crear_nota", "pan")), \
            mock.patch.object(enrutador_natural, "_resolver_con_ollama", lambda t: (_ for _ in ()).throw(AssertionError("no debía llamar a Ollama"))):
        chequear("enrutar: si la nube resuelve, no se llama a Ollama",
                 enrutador_natural.enrutar("apunta pan por ahi")[:2], ("crear_nota", "pan"))
    with mock.patch.object(adn, "resolver", lambda t: None), \
            mock.patch.object(enrutador_natural, "_resolver_con_ollama", lambda t: ("crear_nota", "sal")):
        chequear("enrutar: sin nube, Ollama de respaldo", enrutador_natural.enrutar("apunta sal por ahi")[:2], ("crear_nota", "sal"))

# --------------------------------------------- aprender de la charla (datos)
RESPUESTA = "Un transistor es un componente que amplifica o conmuta señales eléctricas y es la base de los chips."
JSON_ESTABLE = ('{"estable": true, "preguntas": ["que hace un transistor", "para que sirve un transistor en electronica", '
                '"explicame como funciona un transistor", "hola", "que hace un transistor"]}')

with Mundo(JSON_ESTABLE) as m:
    hilo = adn.aprender_de_charla("explicame que es un transistor", RESPUESTA)
    hilo = hilo or threading.current_thread()
    chequear("conocimiento estable: guarda la pregunta y sus formas (sin repetir ni basura)",
             [p for p, _ in m.guardado],
             ["explicame que es un transistor", "que hace un transistor", "para que sirve un transistor en electronica",
              "explicame como funciona un transistor"])
    chequear("guarda la respuesta tal cual para todas", {r for _, r in m.guardado}, {RESPUESTA})
    chequear("lo apunta como 4 respuestas guardadas", adn._cargar()["total"]["respuestas"], 4)
    otra = adn.aprender_de_charla("explicame que es un diodo", RESPUESTA)
    chequear("no aprende otra seguida (pausa entre aprendizajes)", otra, None)

with Mundo('{"estable": false, "preguntas": ["x y z"]}') as m:
    adn.aprender_de_charla("que opinas de la musica de hoy dia", RESPUESTA)
    chequear("no estable (opinión, fecha, persona): no guarda nada", m.guardado, [])
with Mundo(JSON_ESTABLE) as m:
    chequear("pregunta muy corta: ni se intenta", (adn.aprender_de_charla("hola que tal", RESPUESTA), m.pedidos), (None, []))
with Mundo(JSON_ESTABLE) as m:
    chequear("dato de internet (con fuente): ni se intenta",
             (adn.aprender_de_charla("quien gano el partido de ayer", RESPUESTA + "\n(Fuente: https://x.com)"), m.pedidos), (None, []))
with Mundo(JSON_ESTABLE) as m:
    chequear("pregunta de actualidad: ni se intenta",
             (adn.aprender_de_charla("cuanto cuesta hoy el dolar en colombia", RESPUESTA), m.pedidos), (None, []))
with Mundo(JSON_ESTABLE) as m:
    chequear("marcada como volátil: ni se intenta",
             (adn.aprender_de_charla("explicame que es un transistor", RESPUESTA, volatil=True), m.pedidos), (None, []))

# ------------------------------------------------------------ ver y olvidar
with Mundo(JSON_NOTA) as m:
    adn.resolver("oye apunta lo de la leche")
    texto = adn.resumen_texto()
    chequear("resumen: dice cuánto aprendió y qué", ("1 intenciones nuevas" in texto, "oye apunta lo de la leche" in texto), (True, True))

    conocimiento = [{"pregunta": "a", "fuente": "nube"}, {"pregunta": "b", "fuente": "enrutador_natural"},
                    {"pregunta": "c", "fuente": "nube"}]
    banco = [{"pregunta": "que hace un transistor"}, {"pregunta": "otra cosa mia"}]
    adn._apuntar({"tipo": "charla", "frase": "x", "preguntas": ["que hace un transistor"]}, respuestas=1)
    guardados = {}
    with mock.patch.object(aprendizaje, "cargar", lambda: list(conocimiento)), \
            mock.patch.object(aprendizaje, "guardar", lambda d: guardados.__setitem__("c", d)), \
            mock.patch.object(respuestas, "cargar", lambda: list(banco)), \
            mock.patch.object(respuestas, "guardar", lambda d: guardados.__setitem__("r", d)):
        r = adn.olvidar()
    chequear("olvidar: quita solo lo que vino de la nube", (r, guardados["c"], guardados["r"]),
             ((2, 1), [{"pregunta": "b", "fuente": "enrutador_natural"}], [{"pregunta": "otra cosa mia"}]))
    chequear("olvidar: deja las lecciones en cero", (adn._cargar()["lecciones"], adn._cargar()["total"]["frases"]), ([], 0))

for frase, esperado in {
    "activa el aprendizaje de la nube": "aprender_nube_on", "aprende de la nube": "aprender_nube_on",
    "desactiva el aprendizaje de la nube": "aprender_nube_off", "no aprendas de la nube": "aprender_nube_off",
    "que has aprendido de la nube": "ver_aprendido_nube", "olvida lo que aprendiste de la nube": "olvidar_aprendido_nube",
}.items():
    chequear(f"comando '{frase}'", (adn.interpretar(frase) or (None,))[0], esperado)

with Mundo() as m:
    callado(adn.manejar, "desactiva el aprendizaje de la nube")
    chequear("apagar se guarda", adn.activo(), False)
    callado(adn.manejar, "activa el aprendizaje de la nube")
    chequear("prender se guarda", adn.activo(), True)
    with mock.patch.object(adn, "olvidar", lambda: (1, 1)):
        _, salida = callado(adn.manejar, "olvida lo que aprendiste de la nube", lambda p: "s")
        chequear("olvidar pide confirmación y borra con 's'", "olvidé 1 ejemplos" in salida, True)
        _, salida = callado(adn.manejar, "olvida lo que aprendiste de la nube", lambda p: "n")
        chequear("con 'n' no borra", "no borré nada" in salida, True)

# ---------------------------------------------------------- catálogo y main
NUEVAS = ("proveedor_nube", "modelos_nube", "compartir_memoria", "no_compartir_memoria", "aprender_nube_on",
          "aprender_nube_off", "ver_aprendido_nube", "olvidar_aprendido_nube")
sin = []
for i in NUEVAS:
    e = catalogo.POR_ID.get(i)
    cmd = catalogo.armar_comando(e, catalogo.RELLENOS[e["argumento"]][0] if e["argumento"] else "") if e else ""
    cual = cerebro.interpretar(cmd) or adn.interpretar(cmd)
    if not (e and cual and cual[0] == i):
        sin.append((i, cmd, cual))
chequear("los 8 comandos nuevos del catálogo los entiende su módulo (con el mismo id)", sin, [])
for velocidad in catalogo.RELLENOS["velocidad"]:
    chequear(f"voz: 'habla mas {velocidad}' es velocidad_voz", (voz.interpretar(f"habla mas {velocidad}") or (None,))[0], "velocidad_voz")
chequear("confirmar: olvidar lo aprendido pide confirmación en el catálogo", catalogo.POR_ID["olvidar_aprendido_nube"]["confirmar"], True)

from core import alarmas
with mock.patch.object(alarmas, "ARCHIVO", os.path.join(CARPETA, "alarmas.json")), mock.patch.object(alarmas, "iniciar_vigilante", lambda: None):
    callado(alarmas.manejar, "pon un temporizador de 10 minutos")
    r, _ = callado(alarmas.manejar, "cancela todas las alarmas")
    chequear("cancelar todas devuelve su propia intención", r[0], "cancelar_todas_alarmas")
    callado(alarmas.manejar, "pon un temporizador de 10 minutos")
    r, _ = callado(alarmas.manejar, "cancela la alarma")
    chequear("cancelar una devuelve la suya", r[0], "cancelar_alarma")

fuente = open(os.path.join(AQUI, "main.py"), encoding="utf-8").read()
chequear("main.py: aprender_de_nube entre los módulos de comandos",
         "cerebro_nube, aprender_de_nube):" in fuente, True)
chequear("main.py: aprende de la charla tras contestar la nube", "aprender_de_nube.aprender_de_charla(" in fuente, True)
chequear("el enrutador natural consulta primero a la nube",
         "aprender_de_nube.resolver(texto)" in open(os.path.join(AQUI, "core/IA/enrutador_natural.py"), encoding="utf-8").read(), True)

# ---------------------------------------------------------------- dos nubes (respaldo)
with nube_aislada():
    nube.guardar_clave("gsk_" + "a" * 30, "groq")
    llamadas = []

    def post_dos(url, payload, enc, metodo="POST"):
        llamadas.append(url)
        if "groq" in url:
            raise nube.ErrorNube("limite de Groq", codigo=429)
        return {"choices": [{"message": {"content": "contesto gemini"}}]}

    with mock.patch.object(nube, "_post", post_dos):
        try:
            nube.responder([{"role": "user", "content": "hola"}])
            sin_respaldo = "respondió"
        except nube.ErrorNube:
            sin_respaldo = "falló"
        chequear("una sola nube que falla: falla", sin_respaldo, "falló")
        nube.guardar_clave("AIza" + "b" * 30, "gemini")
        chequear("respaldo: segundo modelo de Groq y la otra nube gratis con clave", nube.proveedores_de_respaldo(), ["groq_b", "gemini"])
        llamadas.clear()
        chequear("groq falla y contesta gemini", nube.responder([{"role": "user", "content": "hola"}]), "contesto gemini")
        chequear("probo primero groq y luego gemini", ["groq" in u for u in llamadas][:1] + [any("googleapis" in u for u in llamadas)], [True, True])
        uso = nube.ultimo_uso()
        chequear("avisa que uso el respaldo", (uso["proveedor"], "limite de Groq" in uso["aviso"]), ("gemini", True))
        nube.fijar_respaldo(False)
        try:
            nube.responder([{"role": "user", "content": "hola"}])
            apagado = "respondió"
        except nube.ErrorNube:
            apagado = "falló"
        chequear("respaldo apagado: no prueba la otra", apagado, "falló")
        nube.fijar_respaldo(True)
    nube.guardar_clave("sk-ant-" + "c" * 30, "anthropic")
    chequear("anthropic (de pago) nunca entra de respaldo", "anthropic" in nube.proveedores_de_respaldo(), False)
    def post_todas_fallan(url, payload, enc, metodo="POST"):
        raise nube.ErrorNube("sin red", codigo=None)
    with mock.patch.object(nube, "_post", post_todas_fallan):
        try:
            nube.responder([{"role": "user", "content": "hola"}])
            fin = "respondió"
        except nube.ErrorNube as e:
            fin = str(e)
        chequear("si todas fallan: error de la principal", fin, "sin red")
    chequear("estado menciona la nube de respaldo", "respaldo" in nube.estado_texto().lower(), True)
for frase, esperado in {"usa la nube de respaldo": ("nube_respaldo", True), "usa dos nubes": ("nube_respaldo", True),
                        "no uses la nube de respaldo": ("nube_respaldo", False),
                        "desactiva la nube de respaldo": ("nube_respaldo", False)}.items():
    chequear(f"cerebro entiende '{frase}'", cerebro.interpretar(frase), esperado)

# segundo modelo de Groq: respaldo sin crear nada nuevo
with nube_aislada():
    chequear("sin clave de Groq no hay respaldo de Groq", nube.proveedores_de_respaldo(), [])
    nube.guardar_clave("gsk_" + "a" * 30, "groq")
    chequear("con la clave de Groq aparece el segundo modelo", nube.proveedores_de_respaldo(), ["groq_b"])
    chequear("usa la misma clave y otro modelo", (nube.clave("groq_b") == nube.clave("groq"), nube.modelo("groq_b")),
             (True, "openai/gpt-oss-20b"))
    modelos_usados = []

    def post_modelos(url, payload, enc, metodo="POST"):
        modelos_usados.append(payload["model"])
        if payload["model"] == "openai/gpt-oss-120b":
            raise nube.ErrorNube("limite del modelo grande", codigo=429)
        return {"choices": [{"message": {"content": "contesto el segundo"}}]}

    with mock.patch.object(nube, "_post", post_modelos):
        chequear("el modelo grande se agota: contesta el segundo de Groq",
                 nube.responder([{"role": "user", "content": "hola"}]), "contesto el segundo")
    chequear("probo primero el grande y luego el segundo", modelos_usados[:1] + modelos_usados[-1:],
             ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
    chequear("el segundo modelo no sale en los menus de proveedores",
             [n for n, c in nube.PROVEEDORES.items() if not c.get("respaldo_de")], ["groq", "gemini", "anthropic"])

# conectar la segunda nube sin tocar la principal
with nube_aislada():
    nube.guardar_clave("gsk_" + "a" * 30, "groq")
    nube.fijar_proveedor("groq")
    chequear("cerebro entiende 'conecta la nube de respaldo'", cerebro.interpretar("conecta la nube de respaldo"), ("conectar_respaldo", None))
    chequear("cerebro entiende 'agrega otra nube'", cerebro.interpretar("agrega otra nube"), ("conectar_respaldo", None))
    with mock.patch.object(nube, "_post", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]}):
        # groq principal; entre gemini y anthropic solo gemini es gratis -> no pregunta
        ok, salida = callado(cerebro.conectar_respaldo, lambda *_: "", lambda: "AIza" + "z" * 30)
    chequear("respaldo: guarda la clave de gemini y prueba bien", (ok, nube.configurada("gemini")), (True, True))
    chequear("respaldo: la principal sigue siendo groq", nube.proveedor(), "groq")
    chequear("respaldo: queda como nube de respaldo", nube.proveedores_de_respaldo(), ["groq_b", "gemini"])
    with mock.patch.object(nube, "_post", lambda *a, **k: (_ for _ in ()).throw(nube.ErrorNube("clave mala", codigo=401))):
        ok, _s = callado(nube.probar)
    chequear("probar() mira solo la principal (no la respalda otra)", ok[0], False)
    ok, salida = callado(cerebro.conectar_respaldo, lambda *_: "", lambda: "")
    chequear("respaldo sin clave: no guarda nada", (ok, "No guardé nada" in salida), (None, True))

# ---------------------------------------------------------------- guia compacta
from core import guia_comandos as guia
_, resumen = callado(guia.mostrar_guia, None, False)
_, entera = callado(guia.mostrar_guia, None, False, True)
chequear("guia: el resumen es mucho mas corto que la lista entera", len(resumen.splitlines()) * 2 < len(entera.splitlines()), True)
chequear("guia: el resumen dice como ver mas", all(x in resumen for x in ("comandos buscar", "comandos todo")), True)
chequear("guia: la lista entera trae un comando de la nube", "prueba la nube" in entera, True)
res, salida = callado(guia.buscar_en_guia, "volumen")
chequear("guia: buscar 'volumen' encuentra comandos de voz y de sonido", (len(res) >= 2, "volumen" in salida.lower()), (True, True))
res, salida = callado(guia.buscar_en_guia, "zzzqqq")
chequear("guia: buscar algo inexistente lo dice", (res, "No encontré" in salida), ([], True))
fuente_main = open(os.path.join(AQUI, "main.py"), encoding="utf-8").read()
chequear("main.py conoce 'comandos todo' y 'comandos buscar'", all(x in fuente_main for x in ("comandos todo", "comandos buscar ", "mostrar_guia(completo=True)")), True)

print()
print("TODO OK" if not fallos else f"{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)