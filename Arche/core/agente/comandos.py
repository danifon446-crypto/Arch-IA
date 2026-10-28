"""
comandos.py
-----------
Ubicacion: Arche/core/agente/comandos.py

La puerta de entrada desde el chat de Arché. manejar(frase) devuelve True si la
frase era del agente (y ya respondio) o False si no, para que main.py siga con
lo de siempre. Solo reacciona a frases que EMPIEZAN con "agente", "en minecraft"
o "juega minecraft", asi nunca se come una conversacion normal.

El agente trabaja en un hilo aparte: Arché sigue atendiendote mientras juega, y
"agente para" lo detiene en cualquier momento.

Comandos (ver tambien "agente ayuda"):
  en minecraft <objetivo>            ej.: en minecraft consigue 10 de madera
  agente <objetivo>                  usa el entorno por defecto (minecraft)
  agente simulado <objetivo>         practica en el mundo de juguete (sin Minecraft)
  agente prueba                      demostracion rapida en el mundo de juguete
  agente estado | para | memoria | olvida experiencias confirmo
  agente modelos | modelo <rol> <proveedor>
  agente conecta minecraft | desconecta minecraft | instala puente minecraft
  agente configura minecraft host=... puerto=... usuario=... version=... captura_pantalla=si
"""

from __future__ import annotations

import os
import re
import sys
import threading
import unicodedata

from core.agente import config
from core.agente import entornos as _entornos
from core.agente.coordinador import Agente
from core.agente.entorno import crear_entorno, entornos_disponibles
from core.agente.habilidades import Habilidades
from core.agente.memoria_experiencias import MemoriaExperiencias
from core.agente.modelos import ROLES, Enrutador

AYUDA = """Agente autónomo de Arché. Le das un objetivo y él planifica, actúa, verifica y aprende.
  en minecraft <objetivo>         ej.: en minecraft consigue 10 de madera
  agente <objetivo>               usa el entorno por defecto (minecraft)
  agente simulado <objetivo>      practica en un mundo de juguete, sin abrir Minecraft
  agente prueba                   demostración rápida en el mundo de juguete
  agente estado                   qué está haciendo ahora
  agente para                     lo detiene de inmediato
  agente memoria                  lo que ha aprendido (y 'agente olvida experiencias confirmo' lo borra)
  agente nube                     prueba la nube principal y las de respaldo (¿responden?)
  agente diagnostico              revisa todo: Node, puente, el mundo de Minecraft, modelos y nubes
  agente continua                 retoma el plan que quedó a medias (se cortó la nube, o lo paraste)
  agente pendiente                muestra qué quedó a medias
  agente investiga [tema]         lee la wiki del juego y aprende reglas por su cuenta (se hace sola la primera vez)
  agente reglas                   muestra lo que sabe del juego; 'agente reglas agrega <texto>' le suma una a mano
  agente habilidades              lo que ya sabe hacer sin consultar ningún modelo
  agente version
  agente modelos                  qué modelo usa cada rol
  agente modelo <rol> <modelo>    roles: planificador, decisor, verificador, reflexion, vision
                                  modelos: auto | nube | ollama | ollama:<nombre> | compat:<url>#<nombre>
  agente instala puente minecraft la primera vez (necesita Node.js 18+)
  agente conecta minecraft        entra al mundo (ábrelo a LAN antes) / agente desconecta minecraft
  agente configura minecraft host=localhost puerto=25565 usuario=Arche version=1.20.4 captura_pantalla=si"""

_lock = threading.Lock()
_lock_pantalla = threading.Lock()
_sesion: dict | None = None
_entornos_activos: dict = {}
_router = Enrutador()
_memoria: MemoriaExperiencias | None = None
_habilidades: Habilidades | None = None


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------

def _latido():
    """Mientras el agente trabaja, el piloto automatico de mejora de Arché no debe competir por los modelos."""
    try:
        from core import mejora_continua
        mejora_continua.latido()
    except Exception:
        pass


def _msg(texto: str):
    """Habla desde el hilo del agente sin pisar el "Tú: " que espera tu escritura."""
    _latido()
    if threading.current_thread() is threading.main_thread():
        print(f"Arché: {texto}")          # respuesta directa a un comando: main.py ya pone el "Tú: "
        return
    with _lock_pantalla:
        sys.stdout.write("\r" + " " * 12 + "\r" + f"Arché: {texto}\n\nTú: ")
        sys.stdout.flush()


def _sin_tildes(texto: str) -> str:
    out = []
    for ch in str(texto).lower():
        d = unicodedata.normalize("NFD", ch)
        out.append("".join(c for c in d if unicodedata.category(c) != "Mn") or ch)
    return "".join(out)


def _memoria_global() -> MemoriaExperiencias:
    global _memoria
    if _memoria is None:
        _memoria = MemoriaExperiencias()
    return _memoria


def _habilidades_globales() -> Habilidades:
    global _habilidades
    if _habilidades is None:
        _habilidades = Habilidades()
    return _habilidades


def _obtener_entorno(nombre: str):
    _entornos.cargar_todos()
    if nombre == "simulado":
        return crear_entorno("simulado")                      # mundo nuevo cada vez
    if nombre not in _entornos_activos:
        _entornos_activos[nombre] = crear_entorno(nombre)
    return _entornos_activos[nombre]


# ----------------------------------------------------------------------
# Sesion en segundo plano
# ----------------------------------------------------------------------

def _resumen(informe) -> str:
    extra = f"{informe.pasos_totales} acciones, {informe.segundos} s, {informe.fallos} fallo(s)"
    if informe.replanificaciones:
        extra += f", {informe.replanificaciones} cambio(s) de estrategia"
    if informe.exito:
        return f"Objetivo cumplido: {informe.objetivo}. ({extra})"
    return f"No logré el objetivo: {informe.objetivo}. Motivo: {informe.motivo} ({extra})"


# ----------------------------------------------------------------------
# Plan pendiente: si algo externo corta el trabajo (limite de la nube, "agente para"),
# el plan queda guardado y "agente continua" lo retoma sin empezar de cero.
# ----------------------------------------------------------------------

def _guardar_pendiente(entorno_nombre: str, informe) -> None:
    if informe.plan is None or not informe.plan.pendientes():
        return
    plan = informe.plan
    config.guardar_json("pendiente.json", {
        "entorno": entorno_nombre, "objetivo": informe.objetivo, "motivo": informe.motivo,
        "plan": {"objetivo": plan.objetivo, "version": plan.version, "notas": plan.notas, "origen": plan.origen,
                 "pasos": [{"descripcion": p.descripcion, "criterio": p.criterio, "hecho": p.hecho, "meta": p.meta}
                           for p in plan.pasos]}})


def _cargar_pendiente():
    """-> (entorno, objetivo, Plan, motivo) o None."""
    d = config.leer_json("pendiente.json", None)
    if not d or "plan" not in d:
        return None
    from core.agente.tipos import Plan, Subobjetivo
    p = d["plan"]
    plan = Plan(p.get("objetivo", d.get("objetivo", "")),
                [Subobjetivo(x["descripcion"], x.get("criterio", ""), bool(x.get("hecho")), dict(x.get("meta") or {}))
                 for x in p.get("pasos", [])],
                int(p.get("version", 1)), p.get("notas", ""), p.get("origen", "modelo"))
    if not plan.pendientes():
        return None
    return d.get("entorno", "minecraft"), d.get("objetivo", plan.objetivo), plan, d.get("motivo", "")


def _borrar_pendiente() -> None:
    try:
        os.remove(config.ruta("pendiente.json"))
    except OSError:
        pass


def _texto_pendiente() -> str:
    p = _cargar_pendiente()
    if not p:
        return "No hay nada a medias."
    entorno, objetivo, plan, motivo = p
    return (f"Quedó a medias: «{objetivo}» en {entorno} (se cortó por: {motivo}).\n{plan.resumen()}\n"
            "Escribe «agente continua» para retomarlo.")


def _investigar_si_falta(nombre_entorno: str, forzar: bool = False, temas=None):
    """La primera vez que juega algo, Arché busca solo las reglas en la wiki (una vez; sin internet o sin nube, sigue igual)."""
    from core.agente import reglas
    if not forzar and not (config.cargar().get("reglas", {}).get("auto_investigar", True) and reglas.debe_investigar(nombre_entorno)):
        return
    _msg(f"Antes de jugar, investigo las reglas de {nombre_entorno} en su wiki (solo esta vez)...")
    try:
        _, texto = reglas.investigar(nombre_entorno, _router, temas, avisar=_msg)
    except Exception as e:
        texto = f"No pude investigar ahora ({e}). Sigo con lo que ya sé."
    _msg(texto)


def _iniciar(nombre_entorno: str, objetivo: str, plan=None):
    global _sesion
    with _lock:
        if _sesion is not None:
            _msg(f"Ya estoy trabajando en «{_sesion['objetivo']}». Escribe «agente para» y luego dame el nuevo objetivo.")
            return
        _sesion = {"objetivo": objetivo, "entorno": nombre_entorno, "agente": None}

    def trabajo():
        global _sesion
        try:
            entorno = _obtener_entorno(nombre_entorno)
            if not entorno.esta_conectado():
                _msg(f"Conectando con {nombre_entorno}...")
                _msg(entorno.conectar())
            # La vision (captura de pantalla + modelo de vision) solo se usa si la pides en la configuracion;
            # asi el agente no toca ningun modelo local (Ollama) que no hayas pedido.
            quiere_vision = bool(config.cargar().get("minecraft", {}).get("captura_pantalla")) if nombre_entorno == "minecraft" else False
            _investigar_si_falta(nombre_entorno)
            agente = Agente(entorno, router=_router, memoria=_memoria_global(), avisar=_msg, usar_vision=quiere_vision,
                            habilidades=_habilidades_globales())
            with _lock:
                if _sesion is not None:
                    _sesion["agente"] = agente
            informe = agente.ejecutar(objetivo, plan)
            _msg(_resumen(informe))
            if informe.exito:
                _borrar_pendiente()
            elif informe.recuperable:
                _guardar_pendiente(nombre_entorno, informe)
                _msg("Dejé el plan guardado. Cuando puedas, escribe «agente continua» para seguir donde quedé.")
        except Exception as e:
            _msg(f"El agente se detuvo: {e}")
        finally:
            with _lock:
                _sesion = None

    threading.Thread(target=trabajo, name="agente-arche", daemon=True).start()
    _msg(f"Entendido. Voy con «{objetivo}» en {nombre_entorno}. Puedes seguir hablándome; «agente para» me detiene.")


def detener_todo(desconectar: bool = True) -> str:
    """Para al agente (si trabaja) y, al salir, cierra Minecraft. Seguro de llamar siempre."""
    texto = "El agente estaba en reposo."
    with _lock:
        sesion = _sesion
    if sesion is not None and sesion.get("agente") is not None:
        sesion["agente"].detener()
        texto = "Detuve al agente."
    if desconectar:
        for entorno in list(_entornos_activos.values()):
            try:
                entorno.cerrar()
            except Exception:
                pass
        _entornos_activos.clear()
    return texto


def estado_texto() -> str:
    with _lock:
        sesion = _sesion
    if sesion is None:
        return "El agente está en reposo."
    agente = sesion.get("agente")
    return agente.estado_texto() if agente else f"Preparando: {sesion['objetivo']}"


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------

def _config_minecraft(cola: str) -> str:
    permitidas = {"host": str, "puerto": int, "usuario": str, "version": str, "auth": str, "puerto_puente": int}
    cambios = []
    for clave, valor in re.findall(r"(\w+)\s*=\s*(\S+)", cola):
        k = _sin_tildes(clave)
        if k == "captura_pantalla":
            config.fijar("minecraft.captura_pantalla", _sin_tildes(valor) in ("si", "true", "1", "yes", "on"))
            cambios.append(f"captura_pantalla={_sin_tildes(valor) in ('si', 'true', '1', 'yes', 'on')}")
        elif k in permitidas:
            try:
                config.fijar(f"minecraft.{k}", permitidas[k](valor))
                cambios.append(f"{k}={valor}")
            except ValueError:
                return f"El valor de {k} no es válido: {valor}"
        else:
            return f"No conozco el ajuste «{clave}». Los que hay: host, puerto, usuario, version, auth, captura_pantalla."
    if cambios:
        _entornos_activos.pop("minecraft", None)         # que la proxima conexion use lo nuevo
        return "Guardé: " + ", ".join(cambios) + "."
    cfg = config.cargar()["minecraft"]
    return "Ajustes de Minecraft: " + ", ".join(f"{k}={v}" for k, v in cfg.items())


def _estado_nubes() -> str:
    """Prueba de verdad (una llamada minima) la nube principal y cada nube de respaldo con clave."""
    try:
        from core.IA import nube
    except Exception as e:
        return f"No pude cargar la nube de Arché ({e})."
    principal = nube.proveedor()
    respaldos = nube.proveedores_de_respaldo(principal)
    activo = nube.respaldo_activo()
    lineas = ["Probando las nubes (una llamada mínima a cada una)..."]
    for prov in [principal] + respaldos:
        ok, msg = nube.probar(prov)
        if prov == principal:
            rol = "PRINCIPAL"
        else:
            rol = "respaldo" if activo else "respaldo (APAGADO: di «usa la nube de respaldo»)"
        nombre = nube.PROVEEDORES[prov]["nombre"].split(" (")[0]
        lineas.append(f"  {rol}: {nombre}, modelo {nube.modelo(prov)}: " + ("FUNCIONA" if ok else f"FALLA, {msg}"))
    if not respaldos:
        lineas.append("  No hay ninguna nube de respaldo con clave. «conecta la nube de respaldo» agrega otra.")
    else:
        lineas.append("Si la principal falla o llega a su límite, el agente prueba las de respaldo en ese orden "
                      "y te avisa con «Contestó la nube de RESPALDO».")
    return "\n".join(lineas)


def _diagnostico() -> str:
    """Revisa de punta a punta todo lo que el agente necesita y dice qué falta y como arreglarlo."""
    import shutil
    import socket
    import subprocess
    from core.agente.entornos.minecraft import EntornoMinecraft
    cfg = config.cargar()["minecraft"]
    L = ["Diagnóstico del agente:"]

    def fila(ok, texto, arreglo=""):
        L.append(("  OK:    " if ok else "  FALTA: ") + texto + ("" if ok or not arreglo else f"  ->  {arreglo}"))

    try:
        v = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=8).stdout.strip()
        mayor = int(v.lstrip("v").split(".")[0]) if v else 0
        fila(mayor >= 18, f"Node.js {v or '(no responde)'}", "instala Node.js 18 o más desde nodejs.org y reabre Arché")
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        fila(False, "Node.js no encontrado", "instálalo desde nodejs.org (LTS) y reabre Arché")
    fila(EntornoMinecraft.puente_instalado(), "Puente de Minecraft instalado", "escribe: agente instala puente minecraft")
    L.append(f"  Configuración: host={cfg['host']} puerto={cfg['puerto']} usuario={cfg['usuario']} "
             f"version={cfg['version'] or '(automática)'}")
    try:
        with socket.create_connection((cfg["host"], int(cfg["puerto"])), timeout=2):
            fila(True, f"Hay un mundo escuchando en {cfg['host']}:{cfg['puerto']}")
    except OSError:
        fila(False, f"Nada responde en {cfg['host']}:{cfg['puerto']}",
             "abre tu mundo a LAN y copia el puerto que sale en el chat: agente configura minecraft puerto=<número>")
    entorno = _entornos_activos.get("minecraft")
    fila(bool(entorno and entorno.esta_conectado()), "Arché está dentro del mundo ahora mismo",
         "se conecta solo al darle un objetivo, o escribe: agente conecta minecraft")
    L.append("  Modelos por rol:\n" + "\n".join("  " + f for f in _router.estado().split("\n")))
    L.append(_estado_nubes())
    try:
        from core import agente as _a  # noqa: F401
        from core.agente import conocimiento as _kn, reglas as _rg
        import glob
        caches = glob.glob(config.ruta("conocimiento_*.json"))
        fila(bool(caches), "Recetas y herramientas del juego guardadas (planificar sin nube)" if caches
             else "Recetas del juego aún no descargadas", "" if caches else "se bajan solas la primera vez que Arché entra al mundo")
        L.append(f"  Reglas aprendidas de la wiki: {len(_rg.listar('minecraft'))}. Habilidades guardadas: {_habilidades_globales().total()}.")
    except Exception:
        pass
    L.append(f"  Memoria de experiencias: {_memoria_global().total()} guardadas. "
             + ("Hay un plan a medias: «agente continua»." if _cargar_pendiente() else "Nada a medias."))
    return "\n".join(L)


def _modelo(cola: str, cola_original: str) -> str:
    partes = cola_original.split()
    if len(partes) < 2:
        return "Usa: agente modelo <rol> <modelo>. Roles: " + ", ".join(ROLES) + ". Mira «agente ayuda»."
    rol = _sin_tildes(partes[0])
    rol = {"reflexión": "reflexion", "visión": "vision"}.get(rol, rol)
    try:
        _router.fijar(rol, partes[1])
    except ValueError as e:
        return str(e)
    return f"Listo: el rol «{rol}» ahora usa «{partes[1]}»."


def _subcomando(n: str, cola_orig: str) -> bool | None:
    """Comandos de control. Devuelve True si lo manejo; None si no es un subcomando (es un objetivo)."""
    if n in ("", "ayuda", "help", "comandos"):
        _msg(AYUDA)
        return True
    if n in ("estado", "que haces", "como vas"):
        _msg(estado_texto())
        return True
    if re.fullmatch(r"(?:para|parate|detente|detener|stop|alto|basta|cancela|cancelar)(?: ya| ahora)?", n):
        _msg(detener_todo(desconectar=False))
        return True
    if n in ("memoria", "experiencias", "que aprendiste", "que has aprendido"):
        _msg(_memoria_global().resumen())
        return True
    if n.startswith(("olvida experiencias", "olvida todo", "borra memoria", "borra experiencias")):
        total = _memoria_global().total()
        if "confirmo" in n:
            _memoria_global().olvidar()
            _msg(f"Borré {total} experiencia(s).")
        else:
            _msg(f"Tengo {total} experiencia(s). Para borrarlas todas escribe: agente olvida experiencias confirmo")
        return True
    if n == "modelos":
        _msg("Modelos por rol:\n" + _router.estado())
        return True
    if n in ("diagnostico", "diagnostica", "revisa todo", "revision"):
        _msg(_diagnostico())
        return True
    if n in ("version", "versión"):
        from core.agente import VERSION
        _msg(f"Agente autónomo de Arché, versión {VERSION}. Entornos: {', '.join(entornos_disponibles()) or 'ninguno cargado todavía'}.")
        return True
    m = re.match(r"(?i)(?:investiga|investigar|estudia|aprende las reglas)\b\s*(?:de\s+|en\s+)?(?:minecraft\b)?\s*(.*)$", cola_orig)
    if m and n.split()[0] in ("investiga", "investigar", "estudia", "aprende"):
        tema = m.group(1).strip()
        threading.Thread(target=lambda: _investigar_si_falta("minecraft", True, [tema] if tema else None),
                         name="agente-investiga", daemon=True).start()
        return True
    if n in ("habilidades", "que sabes hacer", "que sabes hacer solo"):
        _msg(_habilidades_globales().resumen())
        return True
    if n.startswith("olvida habilidades"):
        if "confirmo" in n:
            _habilidades_globales().olvidar()
            _msg("Borré mis habilidades guardadas.")
        else:
            _msg(f"Tengo {_habilidades_globales().total()} habilidad(es). Para borrarlas: agente olvida habilidades confirmo")
        return True
    m = re.match(r"(?i)reglas?\b\s*(?:de\s+)?(?:minecraft\b)?\s*(.*)$", cola_orig)
    if m and n.split()[0] in ("regla", "reglas"):
        from core.agente import reglas
        resto = m.group(1).strip()
        mm = re.match(r"(?i)(?:agrega|agregar|anade|anadir|a.ade|a.adir|suma|sumar)\s*(.*)$", resto)
        if mm:
            texto = mm.group(1).strip()
            _msg(f"Listo, guardé {reglas.anadir('minecraft', texto)} regla(s) nueva(s)." if texto
                 else "Dime la regla: agente reglas agrega <texto>")
        elif re.match(r"(?i)(?:borra|olvida|borrar)", resto):
            _msg(f"Borré {reglas.borrar_todo('minecraft')} regla(s)." if "confirmo" in resto.lower()
                 else "Para borrar todas mis reglas aprendidas: agente reglas borra confirmo")
        else:
            _msg(reglas.resumen("minecraft"))
        return True
    if n in ("pendiente", "pendientes"):
        _msg(_texto_pendiente())
        return True
    if n in ("continua", "continuar", "sigue", "retoma", "retomar", "continua el plan"):
        p = _cargar_pendiente()
        if not p:
            _msg("No hay nada a medias para continuar.")
        else:
            entorno, objetivo, plan, _ = p
            _iniciar(entorno, objetivo, plan)
        return True
    if n in ("nube", "nubes", "estado nube", "estado de la nube", "respaldo", "prueba nube", "prueba la nube"):
        _msg(_estado_nubes())
        return True
    m = re.match(r"modelo\s+(.*)", n)
    if m:
        _msg(_modelo(m.group(1), cola_orig[len("modelo"):].strip()))
        return True
    if n.startswith("instala puente"):
        from core.agente.entornos.minecraft import instalar_puente
        ok, texto = instalar_puente(_msg)
        _msg(texto)
        return True
    if re.match(r"conecta(?:r)?\s+minecraft", n):
        def conectar():
            try:
                _msg(_obtener_entorno("minecraft").conectar())
            except Exception as e:
                _msg(f"No pude conectar con Minecraft: {e}")
        threading.Thread(target=conectar, daemon=True).start()
        return True
    if re.match(r"desconecta(?:r)?\s+minecraft", n):
        entorno = _entornos_activos.pop("minecraft", None)
        if entorno:
            entorno.cerrar()
        _msg("Me desconecté de Minecraft.")
        return True
    m = re.match(r"config(?:ura|urar)?\s+minecraft\s*(.*)", n)
    if m:
        _msg(_config_minecraft(m.group(1)))
        return True
    if n == "prueba":
        _iniciar("simulado", "consigue 1 pico de piedra")
        return True
    return None


def manejar(frase: str) -> bool:
    texto = (frase or "").strip()
    n = _sin_tildes(texto)
    if len(n) != len(texto):          # por seguridad, si algo cambio de largo trabajamos con la version sin tildes
        texto = n

    m = re.match(r"(?:arche\s+)?agente\b[\s:,]*(.*)$", n)
    if m:
        cola_n, cola = m.group(1).strip(), texto[m.start(1):].strip()
        r = _subcomando(cola_n, cola)
        if r:
            return True
        m_ent = re.match(r"(?:en\s+)?(\w+)\s*[:,]?\s+(.+)$", cola_n)
        if m_ent and m_ent.group(1) in ("minecraft", "simulado"):
            objetivo = texto[len(texto) - len(cola) + m_ent.start(2):].strip()
            _iniciar(m_ent.group(1), objetivo)
            return True
        _iniciar(config.cargar()["entorno"], cola)
        return True

    m = re.match(r"(?:en|dentro de)\s+minecraft\b[\s:,]*(?:y\s+)?(.*)$", n) or \
        re.match(r"(?:juega|jugar)\s+(?:a\s+)?minecraft\b[\s:,]*(?:y\s+)?(.*)$", n) or \
        re.match(r"minecraft\s*:\s*(.*)$", n)
    if m:
        cola = texto[m.start(1):].strip()
        if not cola:
            _msg("¿Qué quieres que haga en Minecraft? Por ejemplo: en minecraft consigue 10 de madera. "
                 "Mira «agente ayuda».")
        else:
            _iniciar("minecraft", cola)
        return True
    return False
