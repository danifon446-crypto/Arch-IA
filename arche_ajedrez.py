# -*- coding: utf-8 -*-
"""
ARCHÉ JUEGA AJEDREZ — módulo para streaming

MODOS:
  python arche_ajedrez.py --tiktok            -> "TikTok vs Arché": el chat del LIVE vota las jugadas
  python arche_ajedrez.py --tiktok-simulado   -> lo mismo, con espectadores falsos (para ensayar sin estar en vivo)
  python arche_ajedrez.py --twitch            -> "Chat vs Arché" en Twitch: el chat vota las jugadas
  python arche_ajedrez.py --twitch-simulado   -> modo Twitch con espectadores falsos
  python arche_ajedrez.py --prueba            -> Arché contra sí misma, sin internet
  python arche_ajedrez.py --convertir         -> convierte tu cuenta nueva de Lichess en BOT (una sola vez)
  python arche_ajedrez.py                     -> Arché juega en Lichess contra quien la rete

La pantalla para el stream (vertical 1080x1920) queda en:  http://localhost:8765
"""

import argparse
import json
import os
import queue
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import chess
    import chess.engine
    import chess.svg
    import requests
except ImportError:
    print("Faltan librerías. Ejecuta primero:  pip install -r requirements.txt")
    sys.exit(1)

CARPETA = os.path.dirname(os.path.abspath(__file__))
NOMBRE = "Ghost"   # nombre del personaje; se cambia en config_ajedrez.json ("nombre_personaje")
CONFIG_VOZ = {}    # se llena en main() con la configuración de la voz
API = "https://lichess.org"

PIEZAS = {
    chess.PAWN: "peón", chess.KNIGHT: "caballo", chess.BISHOP: "alfil",
    chess.ROOK: "torre", chess.QUEEN: "dama", chess.KING: "rey",
}


# ===========================================================================
# CONFIGURACIÓN
# ===========================================================================
CONFIG_POR_DEFECTO = {
    "token": "",
    "ruta_stockfish": "",
    "nivel_stockfish": 8,
    "voz_activa": True,
    "velocidad_voz": 175,
    "motor_voz": "natural",            # "natural" (voces neuronales, necesita internet) o "windows"
    "voz_natural": "es-CO-GonzaloNeural",
    "tono_voz": "-8Hz",                # más negativo = voz más grave
    "puerto_overlay": 8765,
    "nombre_personaje": "Ghost",
    "emoji_personaje": "👻",
    # --- Lichess ---
    "aceptar_retos": True,
    "tiempo_minimo_segundos": 60,
    "tiempo_maximo_segundos": 1200,
    "retar_bots_si_no_hay_rivales": True,
    "segundos_espera_antes_de_retar": 45,
    "reto_tiempo_segundos": 300,
    "reto_incremento": 3,
    "max_segundos_pensar": 4,
    "pausa_extra": 1.0,
    # --- TikTok vs Arché ---
    "usuario_tiktok": "@tu_usuario",
    "nivel_tiktok": 3,
    "segundos_votacion": 25,
    "peso_voto_regalo": 5,
    "meta_likes": 300,
    "segundos_extra_seguir": 10,
    "monedas_deshacer": 99,
    "meta_seguidores": 20,
    # --- Twitch ---
    "canal_twitch": "tu_canal",
    "meta_mensajes_twitch": 40,
    "bits_deshacer": 500,
}


def cargar_config():
    ruta = os.path.join(CARPETA, "config_ajedrez.json")
    cfg = dict(CONFIG_POR_DEFECTO)
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        print("[aviso] No encontré config_ajedrez.json, uso valores por defecto.")
    cfg["token"] = os.environ.get("LICHESS_TOKEN") or cfg.get("token", "")
    return cfg


# ===========================================================================
# ESTADO COMPARTIDO (lo que se ve en la pantalla del stream)
# ===========================================================================
COLORES = {
    "square light": "#e8e2f4",
    "square dark": "#7b61b8",
    "square light lastmove": "#9fe7f5",
    "square dark lastmove": "#3fb6cf",
    "margin": "#151026",
    "coord": "#cbbcf0",
}

STATS_INICIALES = {"victorias": 0, "derrotas": 0, "tablas": 0,
                   "gana_tiktok": 0, "gana_arche": 0, "tablas_tiktok": 0}


class Estado:
    def __init__(self):
        self._lock = threading.Lock()
        self._ruta_stats = os.path.join(CARPETA, "estadisticas.json")
        stats = dict(STATS_INICIALES)
        if os.path.exists(self._ruta_stats):
            try:
                with open(self._ruta_stats, "r", encoding="utf-8") as f:
                    stats.update(json.load(f))
            except (OSError, ValueError):
                pass
        self.datos = {
            "modo": "lichess",
            "tablero": chess.svg.board(chess.Board(), size=960, colors=COLORES),
            "pensamiento": "Encendiendo mi cerebro de ajedrez...",
            "rival": "", "rival_rating": "", "mi_color": "blancas",
            "eval": 0.0, "estado": "Esperando rival", "bot": "", "jugadas": 0,
            # modo TikTok
            "fase": "", "fin_votacion": 0, "votos": [], "votantes": 0,
            "likes": 0, "meta_likes": 300, "plataforma": "TikTok",
            "etiqueta_meta": "likes", "texto_regalo": "🎁 Un regalo hace que tu voto valga más",
            "leyenda": [], "ranking": [], "mejor_regalo": None, "seguidores_hoy": 0, "meta_seguidores": 20,
            "veces_meta": 0, "alerta": {"id": 0}, "dur_votacion": 25000, "apoyos": [], "color_tiktok": "blancas",
            "version": 0,
            **stats,
        }

    def actualizar(self, **cambios):
        with self._lock:
            self.datos.update(cambios)
            self.datos["version"] += 1

    def apoyo(self, texto):
        """Agrega una línea a la lista de 'gracias a...' (máximo 4)."""
        with self._lock:
            self.datos["apoyos"] = ([texto] + self.datos["apoyos"])[:4]
            self.datos["version"] += 1

    def alerta(self, tipo, titulo, texto=""):
        """Aviso grande y animado en la pantalla (deshacer, regalo, seguidor, meta)."""
        with self._lock:
            n = self.datos["alerta"].get("id", 0) + 1
            self.datos["alerta"] = {"id": n, "tipo": tipo, "titulo": titulo, "texto": texto}
            self.datos["version"] += 1

    def resultado(self, clave):
        with self._lock:
            self.datos[clave] += 1
            self.datos["version"] += 1
            stats = {k: self.datos[k] for k in STATS_INICIALES}
        try:
            with open(self._ruta_stats, "w", encoding="utf-8") as f:
                json.dump(stats, f)
        except OSError:
            pass

    def como_json(self):
        with self._lock:
            return json.dumps(self.datos, ensure_ascii=False)


ESTADO = Estado()


def dibujar_tablero(board, orientacion, ultimo=None):
    jaque = board.king(board.turn) if board.is_check() else None
    return chess.svg.board(board, orientation=orientacion, lastmove=ultimo, check=jaque,
                           size=960, colors=COLORES, coordinates=True)


# ===========================================================================
# VOZ DE ARCHÉ
# ===========================================================================
class Voz:
    def __init__(self, activa=True, velocidad=175):
        self.activa = activa
        self.velocidad = velocidad
        self.cola = queue.Queue()
        if activa:
            threading.Thread(target=self._bucle, daemon=True).start()

    def decir(self, texto, mostrar=True, opcional=False):
        """opcional=True: solo lo dice si no hay otra frase esperando (para saludos/gracias)."""
        print(f"  {NOMBRE}: {texto}")
        if mostrar:
            ESTADO.actualizar(pensamiento=texto)
        if not self.activa:
            return
        limite = 1 if opcional else 2
        if self.cola.qsize() < limite:
            self.cola.put(texto)

    def _bucle(self):
        if CONFIG_VOZ.get("motor_voz", "natural") == "natural":
            if self._bucle_natural():
                return
            print("[aviso] Uso la voz de Windows como respaldo.")
        if os.name == "nt":
            if self._bucle_windows():
                return
            print("[aviso] La voz de Windows falló. Intento con pyttsx3...")
        self._bucle_pyttsx3()

    # --- Voz natural: voces neuronales de Microsoft (edge-tts) + reproducción con pygame ---
    def _bucle_natural(self):
        try:
            import asyncio
            import tempfile
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            import edge_tts
            import pygame
            pygame.mixer.init()
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] Falta algo para la voz natural ({e}). Ejecuta:  pip install edge-tts pygame")
            return False

        voz = CONFIG_VOZ.get("voz_natural", "es-CO-GonzaloNeural")
        porcentaje = round((self.velocidad - 175) / 175 * 100)
        velocidad = f"{porcentaje:+d}%"
        tono = CONFIG_VOZ.get("tono_voz", "-8Hz")
        carpeta = tempfile.mkdtemp(prefix="ghost_voz_")
        bucle = asyncio.new_event_loop()

        def generar(texto, ruta):
            bucle.run_until_complete(edge_tts.Communicate(texto, voz, rate=velocidad, pitch=tono).save(ruta))

        # Prueba inicial: si no hay internet o la voz no existe, se usa la de Windows
        try:
            generar("Listo.", os.path.join(carpeta, "prueba.mp3"))
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] La voz natural no está disponible ({type(e).__name__}). ¿Hay internet?")
            return False
        print(f"[ok] Voz natural lista: {voz}")

        n = 0
        while True:
            texto = self.cola.get()
            n += 1
            ruta = os.path.join(carpeta, f"frase{n % 3}.mp3")
            try:
                generar(texto, ruta)
                pygame.mixer.music.load(ruta)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
                pygame.mixer.music.unload()
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] No pude decir una frase ({type(e).__name__}: {e})")

    # --- Windows: usa la voz del sistema (System.Speech) en un proceso aparte. Es lo más confiable. ---
    PS_VOZ = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToDefaultAudioDevice()
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'es*' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = __RATE__
$s.Volume = 100
[Console]::Out.WriteLine('VOZ:' + $s.Voice.Name + ' (' + $s.Voice.Culture.Name + ')')
[Console]::Out.Flush()
while ($true) {
  $l = [Console]::In.ReadLine()
  if ($l -eq $null) { break }
  if ($l.Trim().Length -gt 0) {
    try { $s.Speak([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($l))) } catch { }
  }
  [Console]::Out.WriteLine('OK')
  [Console]::Out.Flush()
}
"""

    def _bucle_windows(self):
        import base64
        import subprocess
        rate = max(-10, min(10, round((self.velocidad - 175) / 25)))
        script = self.PS_VOZ.replace("__RATE__", str(rate))
        codificado = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="ascii", errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            primera = proc.stdout.readline().strip()
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] No pude abrir la voz de Windows ({e}).")
            return False
        if not primera.startswith("VOZ:"):
            print("[aviso] La voz de Windows no respondió.")
            return False
        voz = primera[4:]
        print(f"[ok] Voz lista: {voz}")
        if "(es" not in voz:
            print("[aviso] No hay voz en español instalada; se usará la que trae Windows.")
            print("        Instálala en: Configuración > Hora e idioma > Voz > Agregar voces > Español.")
        while True:
            texto = self.cola.get()
            try:
                proc.stdin.write(base64.b64encode(texto.encode("utf-8")).decode("ascii") + "\n")
                proc.stdin.flush()
                proc.stdout.readline()          # espera a que termine de hablar
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] Se cayó la voz ({e}).")
                return True

    # --- Otros sistemas (o si lo anterior falla) ---
    def _bucle_pyttsx3(self):
        try:
            import pyttsx3
            motor = pyttsx3.init()
            motor.setProperty("rate", self.velocidad)
            claves = ("spanish", "español", "espanol", "es-mx", "es-es", "es-us",
                      "es_mx", "es_es", "sabina", "helena", "pablo", "raul")
            for v in motor.getProperty("voices"):
                if any(k in f"{v.name} {v.id}".lower() for k in claves):
                    motor.setProperty("voice", v.id)
                    break
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] La voz no funciona ({e}). {NOMBRE} seguirá sin hablar.")
            return
        print("[ok] Voz lista (pyttsx3)")
        while True:
            texto = self.cola.get()
            try:
                motor.say(texto)
                motor.runAndWait()
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] Error de voz: {e}")


# ===========================================================================
# CEREBRO (elige jugadas)
# ===========================================================================
VALORES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
           chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
CENTRO = (chess.D4, chess.E4, chess.D5, chess.E5)
MATE = 100000


def evaluar_simple(board):
    """Puntos desde el punto de vista del que mueve."""
    if board.is_checkmate():
        return -MATE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    puntos = 0
    for tipo, valor in VALORES.items():
        puntos += valor * (len(board.pieces(tipo, chess.WHITE)) - len(board.pieces(tipo, chess.BLACK)))
    for casilla in CENTRO:
        pieza = board.piece_at(casilla)
        if pieza:
            puntos += 15 if pieza.color == chess.WHITE else -15
    return puntos if board.turn == chess.WHITE else -puntos


def negamax(board, profundidad, alfa, beta):
    if profundidad == 0 or board.is_game_over():
        return evaluar_simple(board)
    mejor = -MATE * 2
    for jugada in sorted(board.legal_moves, key=board.is_capture, reverse=True):
        board.push(jugada)
        valor = -negamax(board, profundidad - 1, -beta, -alfa)
        board.pop()
        mejor = max(mejor, valor)
        alfa = max(alfa, valor)
        if alfa >= beta:
            break
    return mejor


def buscar_stockfish(ruta):
    """Acepta la ruta del .exe o de la CARPETA donde está Stockfish (busca el ejecutable adentro)."""
    if not ruta:
        return ""
    ruta = os.path.expanduser(ruta.strip().strip('"'))
    if os.path.isfile(ruta):
        return ruta
    if not os.path.isdir(ruta):
        print(f"[aviso] No existe la ruta de Stockfish: {ruta}")
        return ""
    candidatos = []
    for carpeta, _, archivos in os.walk(ruta):
        for nombre in archivos:
            n = nombre.lower()
            es_programa = n.endswith(".exe") if os.name == "nt" else ("." not in n or n.endswith(".exe"))
            if n.startswith("stockfish") and es_programa:
                candidatos.append(os.path.join(carpeta, nombre))
    if not candidatos:
        print(f"[aviso] No encontré ningún stockfish*.exe dentro de {ruta}")
        return ""
    candidatos.sort(key=lambda c: ("avx2" not in c.lower(), len(c)))  # prefiere la versión AVX2
    return candidatos[0]


class Cerebro:
    def __init__(self, cfg, nivel=None):
        self.motor = None
        self.nivel = int(nivel if nivel is not None else cfg.get("nivel_stockfish", 8))
        ruta = buscar_stockfish(cfg.get("ruta_stockfish", ""))
        if ruta:
            try:
                self.motor = chess.engine.SimpleEngine.popen_uci(ruta)
                self.motor.configure({"Skill Level": self.nivel})
                print(f"[ok] Stockfish cargado (nivel {self.nivel}).")
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] No pude abrir Stockfish ({e}). Uso el cerebro simple.")
                self.motor = None
        else:
            print("[aviso] No hay Stockfish configurado. Uso el cerebro simple (juega flojo).")

    def elegir(self, board, segundos, debil=False):
        """Devuelve (jugada, evaluación en peones desde el lado de las blancas).
        debil=True: juega mucho peor (cuando el público 'la distrae')."""
        if self.motor:
            if debil:
                self.motor.configure({"Skill Level": 0})
            try:
                res = self.motor.play(board, chess.engine.Limit(time=0.05 if debil else segundos),
                                      info=chess.engine.INFO_SCORE)
            finally:
                if debil:
                    self.motor.configure({"Skill Level": self.nivel})
            puntaje = res.info.get("score")
            ev = puntaje.white().score(mate_score=1000) / 100 if puntaje else 0.0
            return res.move, ev

        profundidad = 0 if debil else 2
        mejor_valor, mejores = -MATE * 2, []
        for jugada in board.legal_moves:
            board.push(jugada)
            valor = -negamax(board, profundidad, -MATE * 2, MATE * 2)
            board.pop()
            if valor > mejor_valor:
                mejor_valor, mejores = valor, [jugada]
            elif valor == mejor_valor:
                mejores.append(jugada)
        if debil and random.random() < 0.5:
            mejores = list(board.legal_moves)
        ev = mejor_valor / 100 if board.turn == chess.WHITE else -mejor_valor / 100
        return random.choice(mejores), ev

    def cerrar(self):
        if self.motor:
            try:
                self.motor.quit()
            except Exception:  # noqa: BLE001
                pass


# ===========================================================================
# LENGUAJE: describir jugadas y comentar
# ===========================================================================
def el(nombre):
    """Artículo correcto: 'la torre', 'el caballo'."""
    return f"la {nombre}" if nombre in ("torre", "dama") else f"el {nombre}"


def san_es(san):
    """Notación en español: Nf3 -> Cf3, Qh5 -> Dh5, Rd1 -> Td1, Bc4 -> Ac4, Ke2 -> Re2."""
    return san.translate(str.maketrans("NBRQK", "CATDR"))


def describir(board, jugada):
    """Frase corta para decir en voz alta: 'caballo a f3', 'enroque corto'."""
    if board.is_kingside_castling(jugada):
        return "enroque corto"
    if board.is_queenside_castling(jugada):
        return "enroque largo"
    pieza = board.piece_at(jugada.from_square)
    nombre = PIEZAS.get(pieza.piece_type, "pieza") if pieza else "pieza"
    destino = chess.square_name(jugada.to_square)
    if board.is_capture(jugada):
        return f"{nombre} captura en {destino}"
    return f"{nombre} a {destino}"


def comentario(board, jugada, ev_mia, ev_anterior, publico=False):
    """board = posición ANTES de la jugada. ev_* = evaluación desde el lado de Arché.
    publico=True: le habla al chat de TikTok (ustedes) en vez de a un rival (tú)."""
    pieza = board.piece_at(jugada.from_square)
    destino = chess.square_name(jugada.to_square)
    nombre = PIEZAS.get(pieza.piece_type, "pieza") if pieza else "pieza"
    su = "su" if publico else "tu"

    despues = board.copy()
    despues.push(jugada)
    if despues.is_checkmate():
        return "¡Jaque mate! Gané esta partida." + (" ¿Quieren la revancha?" if publico else "")

    frases = []
    if ev_anterior is not None:
        cambio = ev_mia - ev_anterior
        if cambio > 2.5:
            frases.append(random.choice(
                ["Creo que se equivocaron, chat. Gracias por el regalo.", "Uy chat, esa jugada me ayudó mucho.",
                 "¿Seguros de esa votación? Ahora me toca a mí."] if publico else
                ["Creo que te equivocaste. Gracias por el regalo.", "Uy, ese movimiento me ayudó mucho.",
                 "Lo vi. Ahora me toca a mí."]))
        elif cambio < -2.5:
            frases.append(random.choice(
                ["Buena jugada, chat. No la vi venir.", "Hmm, el chat está jugando en serio.",
                 "Me la pusieron difícil."] if publico else
                ["Buena jugada, no la vi venir.", "Hmm, esto se complicó.", "Me la hiciste difícil, rival."]))

    if board.is_castling(jugada):
        frases.append("Enroco para proteger a mi rey.")
    elif jugada.promotion:
        frases.append(f"¡Corono! Nueva {PIEZAS[jugada.promotion]}.")
    elif board.is_capture(jugada):
        if board.is_en_passant(jugada):
            capturada = "peón"
        else:
            p = board.piece_at(jugada.to_square)
            capturada = PIEZAS.get(p.piece_type, "pieza") if p else "pieza"
        mio = "mía" if capturada in ("torre", "dama") else "mío"
        ese = "Esa" if capturada in ("torre", "dama") else "Ese"
        frases.append(random.choice([f"Me como {su} {capturada}.",
                                     f"Capturo {el(capturada)} con mi {nombre}.",
                                     f"{ese} {capturada} ahora es {mio}."]))
    else:
        frases.append(random.choice([f"{nombre.capitalize()} a {destino}.", f"Muevo mi {nombre} a {destino}.",
                                     f"Voy con {el(nombre)} a {destino}.", f"Pongo {el(nombre)} en {destino}."]))

    if despues.is_check():
        frases.append("¡Jaque!")
    elif ev_mia > 4 and random.random() < 0.3:
        frases.append("Creo que voy ganando." if not publico else "Chat, necesitan distraerme si quieren ganar...")
    elif ev_mia < -4 and random.random() < 0.3:
        frases.append("Esto se puso feo para mí.")
    return " ".join(frases)


PENSANDO = ["Déjame pensar...", "Calculando...", "Mmm, interesante.",
            "Estoy revisando varias opciones.", "Analizando el tablero..."]


# ===========================================================================
# LEER JUGADAS ESCRITAS EN EL CHAT ("e4", "Cf3", "nf3", "e2e4", "O-O", "enroque")
# ===========================================================================
ES_A_EN = {"C": "N", "A": "B", "T": "R", "D": "Q", "R": "K"}
UCI = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")


def leer_jugada(texto, board):
    """Devuelve la jugada (chess.Move) si el comentario es una jugada legal, si no None."""
    t = texto.strip().lower()
    if not t:
        return None
    candidatos_enroque = []
    if "enroque largo" in t or t.replace("-", "").replace(" ", "") in ("ooo", "000"):
        candidatos_enroque.append("O-O-O")
    elif "enroque" in t or t.replace("-", "").replace(" ", "") in ("oo", "00"):
        candidatos_enroque.append("O-O")
    for san in candidatos_enroque:
        try:
            return board.parse_san(san)
        except ValueError:
            return None

    token = texto.strip().split()[0].strip("!¡?¿.,;:")
    token = token.replace("-", "").replace("+", "").replace("#", "")
    if not token:
        return None

    # 1) Formato de casillas: e2e4
    if UCI.match(token.lower()):
        try:
            m = chess.Move.from_uci(token.lower())
            if m in board.legal_moves:
                return m
        except ValueError:
            pass

    # 2) Notación algebraica: tal cual, en inglés y en español
    candidatos = [token, token.lower()]          # "E4" -> "e4"
    if re.match(r"^[a-hA-H][18][qrbndtacQRBNDTAC]$", token):
        candidatos.append(token[:2].lower() + "=" + token[2])   # "e8D" -> "e8=D"
    primera, resto = token[0], token[1:]
    if primera.upper() in "NBRQK":
        candidatos.append(primera.upper() + resto)
    if primera.upper() in ES_A_EN:
        candidatos.append(ES_A_EN[primera.upper()] + resto)
    for c in list(candidatos):  # coronación en español: e8=D
        if "=" in c:
            base, prom = c.split("=", 1)
            if prom[:1].upper() in ES_A_EN and prom[:1].upper() != "R":
                candidatos.append(base + "=" + ES_A_EN[prom[:1].upper()])
            candidatos.append(base + "=" + prom.upper())
    for c in candidatos:
        try:
            return board.parse_san(c)
        except ValueError:
            continue
    return None


# ===========================================================================
# PANTALLA DEL STREAM (servidor web local)
# ===========================================================================
class ManejadorOverlay(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/estado"):
            cuerpo = ESTADO.como_json().encode("utf-8")
            tipo = "application/json; charset=utf-8"
        elif self.path.split("?")[0] == "/personaje.png":
            ruta = os.path.join(CARPETA, "personaje.png")
            if not os.path.exists(ruta):
                self.send_response(404)
                self.end_headers()
                return
            with open(ruta, "rb") as f:
                cuerpo = f.read()
            tipo = "image/png"
        else:
            with open(os.path.join(CARPETA, "overlay.html"), "rb") as f:
                cuerpo = f.read()
            tipo = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        pass


def iniciar_overlay(puerto):
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), ManejadorOverlay)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"[ok] Pantalla del stream lista en:  http://localhost:{puerto}")


# ===========================================================================
# TIKTOK LIVE: leer comentarios, regalos, likes y seguidores
# ===========================================================================
class ConectorTikTok:
    """Usa la librería TikTokLive (no oficial). Manda eventos a una cola:
    ("comentario", usuario, texto) / ("regalo", usuario, (nombre, cantidad))
    ("like", usuario, cantidad) / ("seguidor", usuario, "") / ("compartir", usuario, "")"""

    def __init__(self, usuario, cola):
        self.usuario = usuario if usuario.startswith("@") else "@" + usuario
        self.cola = cola

    def iniciar(self):
        threading.Thread(target=self._correr, daemon=True).start()

    @staticmethod
    def _nombre(ev):
        u = getattr(ev, "user", None)
        return (getattr(u, "nickname", None) or getattr(u, "unique_id", None) or "alguien") if u else "alguien"

    def _correr(self):
        try:
            import asyncio
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import (CommentEvent, ConnectEvent, FollowEvent,
                                           GiftEvent, LikeEvent, ShareEvent)
        except ImportError:
            print("[error] Falta la librería de TikTok. Ejecuta:  pip install TikTokLive")
            return

        while True:
            asyncio.set_event_loop(asyncio.new_event_loop())
            cliente = TikTokLiveClient(unique_id=self.usuario)

            @cliente.on(ConnectEvent)
            async def _conectado(ev):
                print(f"[ok] Conectada al LIVE de {self.usuario}")

            @cliente.on(CommentEvent)
            async def _comentario(ev):
                self.cola.put(("comentario", self._nombre(ev), getattr(ev, "comment", "") or ""))

            @cliente.on(GiftEvent)
            async def _regalo(ev):
                regalo = getattr(ev, "gift", None)
                if regalo is None:
                    return
                if getattr(regalo, "type", 0) == 1:          # regalo en racha
                    if getattr(ev, "streaking", False):      # todavía no termina la racha
                        return
                    cantidad = getattr(ev, "repeat_count", 1) or 1
                else:
                    cantidad = 1
                valor = (getattr(regalo, "diamond_count", 1) or 1) * cantidad   # monedas que costó
                self.cola.put(("regalo", self._nombre(ev), (getattr(regalo, "name", "un regalo"), cantidad, valor)))

            @cliente.on(LikeEvent)
            async def _like(ev):
                self.cola.put(("like", self._nombre(ev), getattr(ev, "count", 1) or 1))

            @cliente.on(FollowEvent)
            async def _seguidor(ev):
                self.cola.put(("seguidor", self._nombre(ev), ""))

            @cliente.on(ShareEvent)
            async def _compartir(ev):
                self.cola.put(("compartir", self._nombre(ev), ""))

            try:
                cliente.run()
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] No pude conectarme al LIVE ({type(e).__name__}: {e}).")
                print("        ¿Ya estás EN VIVO? ¿El usuario en config es correcto? Reintento en 15 s...")
            time.sleep(15)


class SimuladorTikTok:
    """Espectadores falsos para ensayar el modo TikTok sin estar en vivo."""
    NOMBRES = ["lau_gamer", "juanpa_07", "ajedrez_col", "mafe.r", "elprofe_99", "nico🔥", "dani.xd", "sofi_chess"]

    def __init__(self, cola, partida):
        self.cola = cola
        self.partida = partida
        self.twitch = getattr(partida, "plataforma", "") == "Twitch"

    def iniciar(self):
        threading.Thread(target=self._correr, daemon=True).start()

    def _correr(self):
        t = 0
        while True:
            time.sleep(random.uniform(0.6, 1.6))
            t += 1
            quien = random.choice(self.NOMBRES)
            tablero = self.partida.tablero_para_votar()
            if tablero is not None and random.random() < 0.75:
                jugadas = list(tablero.legal_moves)
                # El "chat" tiende a repetir unas pocas jugadas populares
                random.seed(len(tablero.move_stack))
                populares = random.sample(jugadas, min(3, len(jugadas)))
                random.seed()
                m = random.choice(populares) if random.random() < 0.8 else random.choice(jugadas)
                forma = random.choice(["san", "es", "uci", "minus"])
                san = tablero.san(m)
                texto = {"san": san, "es": san_es(san), "uci": m.uci(), "minus": san.lower()}[forma]
                self.cola.put(("comentario", quien, texto))
            elif random.random() < 0.3:
                self.cola.put(("comentario", quien, random.choice(["hola arché!", "vamos chat", "jajaja", "🔥🔥"])))
            if self.twitch:
                self.cola.put(("like", quien, 1))   # en Twitch la meta se llena con mensajes
            elif random.random() < 0.5:
                self.cola.put(("like", quien, random.randint(5, 25)))
            if t % 30 == 0:
                if self.twitch:
                    self.cola.put(("regalo", quien, ("100 bits", 1, 100)))
                else:
                    nombre, precio = random.choice([("Rosa", 1), ("TikTok", 1), ("Dona", 30), ("Perfume", 20)])
                    n = random.randint(1, 3)
                    self.cola.put(("regalo", quien, (nombre, n, precio * n)))
            if t % 75 == 0:   # regalo grande: deshace la jugada de Ghost
                if self.twitch:
                    self.cola.put(("regalo", quien, ("una suscripción", 1, 500)))
                else:
                    self.cola.put(("regalo", quien, ("Galaxia", 1, 1000)))
            if t % 20 == 0 and not self.twitch:
                self.cola.put(("seguidor", quien, ""))


# ===========================================================================
# TWITCH: leer el chat (oficial, sin cuenta ni contraseña, solo lectura)
# ===========================================================================
class ConectorTwitch:
    """Se conecta al chat de Twitch como espectador anónimo y manda a la cola:
    ("comentario", usuario, texto) / ("regalo", usuario, (nombre, cantidad))
    ("seguidor", usuario, "") para raids / ("like", usuario, 1) por cada mensaje (mide el 'hype')."""

    SERVIDOR = ("irc.chat.twitch.tv", 6697)

    def __init__(self, canal, cola):
        self.canal = canal.lower().lstrip("#").strip()
        self.cola = cola

    def iniciar(self):
        threading.Thread(target=self._correr, daemon=True).start()

    @staticmethod
    def _etiquetas(crudo):
        datos = {}
        for par in crudo.lstrip("@").split(";"):
            clave, _, valor = par.partition("=")
            datos[clave] = valor.replace("\\s", " ")
        return datos

    def _linea(self, linea):
        etiquetas = {}
        if linea.startswith("@"):
            crudo, _, linea = linea.partition(" ")
            etiquetas = self._etiquetas(crudo)
        partes = linea.split(" ", 3)
        if len(partes) < 3:
            return
        prefijo, comando = partes[0], partes[1]
        usuario = etiquetas.get("display-name") or prefijo.lstrip(":").split("!")[0] or "alguien"
        texto = partes[3][1:] if len(partes) > 3 and partes[3].startswith(":") else ""

        if comando == "PRIVMSG":
            bits = int(etiquetas.get("bits", "0") or 0)
            if bits > 0:
                self.cola.put(("regalo", usuario, (f"{bits} bits", max(1, bits // 100), bits)))
                texto = re.sub(r"\b[a-zA-Z]{5,}\d+\b", "", texto).strip()  # quita "cheer200"
            self.cola.put(("comentario", usuario, texto))
            self.cola.put(("like", usuario, 1))
        elif comando == "USERNOTICE":
            tipo = etiquetas.get("msg-id", "")
            if tipo in ("sub", "resub"):
                self.cola.put(("regalo", usuario, ("una suscripción", 1, 500)))
            elif tipo in ("subgift", "submysterygift"):
                n = int(etiquetas.get("msg-param-mass-gift-count", "1") or 1)
                self.cola.put(("regalo", usuario, ("suscripciones de regalo", n, 500 * n)))
            elif tipo == "raid":
                gente = etiquetas.get("msg-param-viewerCount", "")
                self.cola.put(("seguidor", usuario, f"raid {gente}"))

    def _correr(self):
        import socket
        import ssl
        while True:
            try:
                contexto = ssl.create_default_context()
                with socket.create_connection(self.SERVIDOR, timeout=330) as crudo:
                    with contexto.wrap_socket(crudo, server_hostname=self.SERVIDOR[0]) as sock:
                        enviar = lambda t: sock.sendall((t + "\r\n").encode("utf-8"))
                        enviar("CAP REQ :twitch.tv/tags twitch.tv/commands")
                        enviar(f"NICK justinfan{random.randint(10000, 99999)}")
                        enviar(f"JOIN #{self.canal}")
                        print(f"[ok] Conectada al chat de twitch.tv/{self.canal}")
                        resto = ""
                        while True:
                            datos = sock.recv(4096)
                            if not datos:
                                raise ConnectionError("Twitch cerró la conexión")
                            resto += datos.decode("utf-8", errors="ignore")
                            *lineas, resto = resto.split("\r\n")
                            for linea in lineas:
                                if linea.startswith("PING"):
                                    enviar("PONG" + linea[4:])
                                elif linea:
                                    self._linea(linea)
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] Se cortó el chat de Twitch ({e}). Reconecto en 10 s...")
                time.sleep(10)


# ===========================================================================
# MODO "TIKTOK vs ARCHÉ"
# ===========================================================================
class PartidaTikTok:
    def __init__(self, cfg, simulado=False, plataforma="TikTok"):
        self.cfg = cfg
        self.plataforma = plataforma
        es_twitch = plataforma == "Twitch"
        self.meta = cfg["meta_mensajes_twitch"] if es_twitch else cfg["meta_likes"]
        self.voz = Voz(cfg["voz_activa"], cfg["velocidad_voz"])
        self.cerebro = Cerebro(cfg, nivel=cfg["nivel_tiktok"])
        self.cola = queue.Queue()
        self.lock = threading.Lock()
        self.votando = False
        self.tablero_voto = None
        self.votos = {}          # usuario -> jugada
        self.bonus = {}          # usuario -> peso extra de voto (por regalos)
        self.likes = 0
        self.distraida = False
        self.saludados = set()
        self.juegos = 0
        self.puntos = {}         # usuario -> puntos de apoyo (ranking)
        self.mejor = None        # (valor, usuario, nombre del regalo)
        self.seguidores = 0
        self.veces_meta = 0
        self.extra = 0           # segundos extra para la votación actual (por seguidores)
        self.deshacer = []       # usuarios que pidieron deshacer la jugada de Ghost
        self.umbral = cfg["bits_deshacer"] if es_twitch else cfg["monedas_deshacer"]
        if simulado:
            SimuladorTikTok(self.cola, self).iniciar()
        elif es_twitch:
            ConectorTwitch(cfg["canal_twitch"], self.cola).iniciar()
        else:
            ConectorTikTok(cfg["usuario_tiktok"], self.cola).iniciar()
        threading.Thread(target=self._procesar_eventos, daemon=True).start()
        ESTADO.actualizar(leyenda=self._leyenda(), meta_seguidores=cfg["meta_seguidores"], ranking=[],
                          seguidores_hoy=0, veces_meta=0, mejor_regalo=None)
        ESTADO.actualizar(modo="tiktok", meta_likes=self.meta, plataforma=plataforma,
                          etiqueta_meta="mensajes" if es_twitch else "likes",
                          texto_regalo=("💜 Bits o sub = tu voto vale más" if es_twitch
                                        else "🎁 Un regalo hace que tu voto valga más"),
                          bot=(cfg["canal_twitch"] if es_twitch else cfg["usuario_tiktok"].lstrip("@")))

    def _leyenda(self):
        """Las reglas que se muestran arriba de la pantalla: acción = efecto (cortas, que se lean de un vistazo)."""
        if self.plataforma == "Twitch":
            return [
                {"icono": "💬", "accion": "ESCRIBE TU JUGADA", "efecto": "SE VOTA"},
                {"icono": "💜", "accion": "BITS", "efecto": "VOTO x5"},
                {"icono": "⭐", "accion": f"SUB / {self.umbral} BITS", "efecto": "DESHACE JUGADA"},
                {"icono": "🔥", "accion": f"{self.meta} MENSAJES", "efecto": f"{NOMBRE.upper()} SE DISTRAE"},
            ]
        return [
            {"icono": "💬", "accion": "COMENTA TU JUGADA", "efecto": "SE VOTA"},
            {"icono": "➕", "accion": "SEGUIR", "efecto": f"+{self.cfg['segundos_extra_seguir']} SEG"},
            {"icono": "🌹", "accion": "ROSA / REGALO", "efecto": "VOTO x5"},
            {"icono": "💎", "accion": f"{self.umbral}+ MONEDAS", "efecto": "DESHACE JUGADA"},
        ]

    def _sumar(self, usuario, puntos):
        with self.lock:
            self.puntos[usuario] = self.puntos.get(usuario, 0) + puntos
            top = sorted(self.puntos.items(), key=lambda x: -x[1])[:3]
        ESTADO.actualizar(ranking=[{"nombre": u, "puntos": p} for u, p in top])

    # --- usado por el simulador ---
    def tablero_para_votar(self):
        with self.lock:
            return self.tablero_voto.copy() if self.votando and self.tablero_voto else None

    # --- eventos del LIVE ---
    def _procesar_eventos(self):
        while True:
            tipo, usuario, dato = self.cola.get()
            try:
                if tipo == "comentario":
                    self._comentario(usuario, dato)
                elif tipo == "regalo":
                    self._regalo(usuario, *dato)
                    self._sumar(usuario, 10 * (dato[2] if len(dato) > 2 else dato[1]))
                elif tipo == "like":
                    self._like(usuario, dato)
                    self._sumar(usuario, dato)
                elif tipo == "seguidor":
                    with self.lock:
                        if self.votando:
                            self.extra += self.cfg["segundos_extra_seguir"]
                    if str(dato).startswith("raid"):
                        ESTADO.apoyo(f"🚀 Raid de {usuario}")
                        ESTADO.alerta("raid", "🚀 ¡RAID!", usuario)
                        self.voz.decir(f"¡Llegó un raid de {usuario}! Bienvenidos. Comenten una jugada para votar.",
                                       mostrar=False)
                    else:
                        self.seguidores += 1
                        ESTADO.actualizar(seguidores_hoy=self.seguidores)
                        ESTADO.apoyo(f"➕ {usuario} siguió")
                        ESTADO.alerta("seguir", f"➕ +{self.cfg['segundos_extra_seguir']}s", f"{usuario} siguió")
                        self.voz.decir(f"¡Gracias por seguirme, {usuario}!", mostrar=False, opcional=True)
                elif tipo == "compartir":
                    ESTADO.apoyo(f"↗ {usuario} compartió")
            except Exception as e:  # noqa: BLE001  (un evento raro no debe tumbar el stream)
                print(f"[aviso] Evento ignorado ({e})")

    def _comentario(self, usuario, texto):
        with self.lock:
            if self.votando and self.tablero_voto is not None:
                jugada = leer_jugada(texto, self.tablero_voto)
                if jugada:
                    nuevo = usuario not in self.votos
                    self.votos[usuario] = jugada  # solo cuenta el último voto de cada persona
                    if nuevo:
                        self.puntos[usuario] = self.puntos.get(usuario, 0) + 3
                    return
        if "hola" in texto.lower() and usuario not in self.saludados:
            self.saludados.add(usuario)
            self.voz.decir(f"¡Hola {usuario}! Comenta una jugada para ayudar al chat.",
                           mostrar=False, opcional=True)

    def _regalo(self, usuario, nombre, cantidad, valor=None):
        valor = valor if valor is not None else cantidad
        texto = f"{cantidad}x {nombre}" if cantidad > 1 else nombre
        with self.lock:
            if self.mejor is None or valor > self.mejor[0]:
                self.mejor = (valor, usuario, texto)
                ESTADO.actualizar(mejor_regalo={"nombre": usuario, "regalo": texto})
        ESTADO.apoyo(f"🎁 {usuario}: {texto}")
        if valor >= self.umbral:
            with self.lock:
                self.deshacer.append(usuario)
            ESTADO.alerta("deshacer", "↩ ¡DESHACER!", f"{usuario} · {texto}")
            self.voz.decir(f"¡{usuario} mandó {texto}! En la próxima votación deshago mi última jugada.",
                           mostrar=False)
            return
        with self.lock:
            self.bonus[usuario] = self.bonus.get(usuario, 0) + self.cfg["peso_voto_regalo"] * cantidad
        ESTADO.alerta("regalo", "🌹 VOTO x5", f"{usuario} · {texto}")
        self.voz.decir(f"¡Gracias {usuario} por {texto}! Tu próximo voto vale más.", mostrar=False)

    def _like(self, usuario, cantidad):
        with self.lock:
            self.likes += cantidad
            llego = self.likes >= self.meta and not self.distraida
            if llego:
                self.distraida = True
                self.likes = 0
                self.veces_meta += 1
        ESTADO.actualizar(likes=self.likes, veces_meta=self.veces_meta)
        if llego:
            ESTADO.alerta("meta", "🔥 ¡META LOGRADA!", f"{NOMBRE} se distrae")
            if self.plataforma == "Twitch":
                ESTADO.apoyo(f"💬 ¡Meta de chat! {NOMBRE} distraído")
                self.voz.decir("¡Tanto chat me distrae! Mi próxima jugada va a ser mucho peor.")
            else:
                ESTADO.apoyo(f"❤️ ¡Meta de likes! {NOMBRE} distraído")
                self.voz.decir("¡Tantos likes me distraen! Mi próxima jugada va a ser mucho peor.")

    # --- votación ---
    def _conteo(self):
        """Lista [(jugada, puntos)] ordenada, con el peso extra de quienes dieron regalos."""
        puntos = {}
        for usuario, jugada in self.votos.items():
            puntos[jugada] = puntos.get(jugada, 0) + 1 + self.bonus.get(usuario, 0)
        return sorted(puntos.items(), key=lambda x: -x[1])

    def _publicar_votos(self, board):
        with self.lock:
            conteo = self._conteo()[:4]
            votantes = len(self.votos)
        ESTADO.actualizar(votos=[{"jugada": san_es(board.san(j)), "n": n} for j, n in conteo],
                          votantes=votantes)

    def _votacion(self, board):
        with self.lock:
            self.votos = {}
            self.tablero_voto = board.copy()
            self.votando = True
        intentos = 0
        while True:
            duracion = self.cfg["segundos_votacion"] if intentos == 0 else 15
            fin = time.time() + duracion
            ESTADO.actualizar(fase="votando", fin_votacion=int(fin * 1000), dur_votacion=duracion * 1000,
                              votos=[], votantes=0,
                              estado="¡Vota tu jugada!")
            if intentos == 0:
                self.voz.decir(random.choice(["¡Su turno, chat! Comenten su jugada.",
                                              "Les toca. ¿Qué juegan?",
                                              "Voten en los comentarios. Tienen poco tiempo."]))
            while time.time() < fin:
                with self.lock:
                    extra, self.extra = min(self.extra, 30), 0
                    pide_deshacer = bool(self.deshacer) and len(board.move_stack) >= 2
                if pide_deshacer:
                    with self.lock:
                        self.votando = False
                        self.tablero_voto = None
                    return "DESHACER"
                if extra:
                    fin += extra
                    duracion += extra
                    ESTADO.actualizar(fin_votacion=int(fin * 1000), dur_votacion=duracion * 1000)
                self._publicar_votos(board)
                time.sleep(0.4)
            with self.lock:
                conteo = self._conteo()
            if conteo or intentos >= 1:
                break
            intentos += 1
            self.voz.decir("Nadie votó... les doy 15 segundos más. ¡Escriban una jugada, como e4!")

        with self.lock:
            self.votando = False
            self.tablero_voto = None
            usados = [u for u in self.votos if u in self.bonus]
            for u in usados:          # el bono de regalo se gasta al usarse
                self.bonus.pop(u, None)
            votantes = len(self.votos)

        if not conteo:
            jugada, _ = self.cerebro.elegir(board, 0.3, debil=True)
            self.voz.decir(f"Como nadie votó, juego por ustedes: {describir(board, jugada)}.")
            return jugada

        mejor = conteo[0][1]
        empatadas = [j for j, n in conteo if n == mejor]
        jugada = random.choice(empatadas)
        extra = " Hubo empate, lo decidí al azar." if len(empatadas) > 1 else ""
        self.voz.decir(f"El chat eligió {describir(board, jugada)}, con {votantes} "
                       f"{'votante' if votantes == 1 else 'votantes'}.{extra}")
        return jugada

    # --- partida ---
    def correr(self):
        self.voz.decir(f"Bienvenidos al juego de {NOMBRE}. "
                       "Ustedes contra mí: comenten su jugada y la más votada se juega.")
        time.sleep(4)
        try:
            while True:
                self._partida()
                time.sleep(8)
        finally:
            self.cerebro.cerrar()

    def _partida(self):
        board = chess.Board()
        color_chat = chess.WHITE if self.juegos % 2 == 0 else chess.BLACK
        self.juegos += 1
        ev_anterior = None
        ESTADO.actualizar(tablero=dibujar_tablero(board, color_chat), eval=0.0, jugadas=0,
                          color_tiktok="blancas" if color_chat == chess.WHITE else "negras",
                          rival=f"Equipo {self.plataforma}", fase="", votos=[])
        self.voz.decir(f"Nueva partida. El chat juega con "
                       f"{'blancas' if color_chat == chess.WHITE else 'negras'}.")
        time.sleep(3)

        while not board.is_game_over(claim_draw=True):
            if board.turn == color_chat:
                jugada = self._votacion(board)
                if jugada == "DESHACER":
                    with self.lock:
                        quien = self.deshacer.pop(0)
                    board.pop()
                    board.pop()
                    ev_anterior = None
                    ultimo = board.peek() if board.move_stack else None
                    ESTADO.actualizar(tablero=dibujar_tablero(board, color_chat, ultimo),
                                      jugadas=len(board.move_stack), votos=[])
                    self.voz.decir(f"¡Noo! {quien} deshizo mi jugada. Chat, vuelvan a votar.")
                    time.sleep(2)
                    continue
                board.push(jugada)
                ESTADO.actualizar(tablero=dibujar_tablero(board, color_chat, jugada),
                                  jugadas=len(board.move_stack), fase="arche", votos=[])
                if board.is_checkmate():
                    break
            else:
                ESTADO.actualizar(fase="arche", estado=f"{NOMBRE} está pensando...")
                with self.lock:
                    debil = self.distraida
                    self.distraida = False
                if random.random() < 0.2 and not debil:
                    self.voz.decir(random.choice(PENSANDO))
                jugada, ev_blancas = self.cerebro.elegir(board, 1.5, debil=debil)
                time.sleep(self.cfg["pausa_extra"])
                ev_mia = -ev_blancas if color_chat == chess.WHITE else ev_blancas
                texto = comentario(board, jugada, ev_mia, ev_anterior, publico=True)
                if debil:
                    texto = "Uff, con tanto alboroto no me concentro... " + texto
                ev_anterior = ev_mia
                board.push(jugada)
                ESTADO.actualizar(tablero=dibujar_tablero(board, color_chat, jugada),
                                  eval=round(ev_blancas, 2), jugadas=len(board.move_stack))
                self.voz.decir(texto)
                time.sleep(1.5)

        resultado = board.result(claim_draw=True)
        ESTADO.actualizar(fase="final")
        if resultado == "1/2-1/2":
            ESTADO.resultado("tablas_tiktok")
            ESTADO.actualizar(estado="Tablas")
            self.voz.decir("¡Tablas! El chat me aguantó. Buena partida.")
        elif (resultado == "1-0") == (color_chat == chess.WHITE):
            ESTADO.resultado("gana_tiktok")
            ESTADO.actualizar(estado="¡GANÓ EL CHAT!")
            self.voz.decir(f"¡No puede ser! El chat me ganó. Bien jugado, {self.plataforma}.")
        else:
            ESTADO.resultado("gana_arche")
            ESTADO.actualizar(estado=f"Ganó {NOMBRE}")
            self.voz.decir("¡Gané! ¿Quieren la revancha?")


# ===========================================================================
# CONEXIÓN CON LICHESS
# ===========================================================================
class Lichess:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}"})

    def _revisar(self, r):
        if r.status_code == 429:
            print("[aviso] Lichess pidió esperar (demasiadas peticiones). Espero 60 s.")
            time.sleep(60)
        return r

    def cuenta(self):
        r = self.s.get(f"{API}/api/account", timeout=15)
        r.raise_for_status()
        return r.json()

    def convertir_a_bot(self):
        return self.s.post(f"{API}/api/bot/account/upgrade", timeout=15)

    def _stream(self, url):
        with self.s.get(url, stream=True, timeout=(15, 90)) as r:
            r.raise_for_status()
            for linea in r.iter_lines():
                if linea:
                    yield json.loads(linea.decode("utf-8"))

    def eventos(self):
        return self._stream(f"{API}/api/stream/event")

    def partida(self, gid):
        return self._stream(f"{API}/api/bot/game/stream/{gid}")

    def aceptar(self, cid):
        self._revisar(self.s.post(f"{API}/api/challenge/{cid}/accept", timeout=15))

    def rechazar(self, cid, razon="generic"):
        self._revisar(self.s.post(f"{API}/api/challenge/{cid}/decline", data={"reason": razon}, timeout=15))

    def mover(self, gid, uci):
        r = self._revisar(self.s.post(f"{API}/api/bot/game/{gid}/move/{uci}", timeout=15))
        return r.status_code == 200

    def chat(self, gid, texto, sala="player"):
        try:
            self.s.post(f"{API}/api/bot/game/{gid}/chat", data={"room": sala, "text": texto[:140]}, timeout=15)
        except requests.RequestException:
            pass

    def bots_en_linea(self, cuantos=30):
        try:
            return list(self._stream(f"{API}/api/bot/online?nb={cuantos}"))
        except (requests.RequestException, ValueError):
            return []

    def retar(self, usuario, limite, incremento):
        datos = {"rated": "false", "clock.limit": limite, "clock.increment": incremento,
                 "color": "random", "variant": "standard"}
        return self._revisar(self.s.post(f"{API}/api/challenge/{usuario}", data=datos, timeout=15))


class ArcheBot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lichess = Lichess(cfg["token"])
        self.voz = Voz(cfg["voz_activa"], cfg["velocidad_voz"])
        self.cerebro = Cerebro(cfg)
        self.yo = ""
        self.jugando = threading.Event()
        self.ultima_partida = time.time()

    def iniciar(self):
        try:
            info = self.lichess.cuenta()
        except requests.RequestException as e:
            print(f"[error] No me pude conectar a Lichess: {e}\nRevisa tu token e internet.")
            return
        self.yo = info["id"]
        if info.get("title") != "BOT":
            print("[error] Esta cuenta todavía no es BOT. Ejecuta:  python arche_ajedrez.py --convertir")
            return
        ESTADO.actualizar(bot=info["username"], modo="lichess")
        print(f"[ok] Conectada a Lichess como {info['username']}")
        self.voz.decir(f"Soy {NOMBRE}. Estoy listo para jugar. Rétame en lichess, usuario {info['username']}.")
        if self.cfg["retar_bots_si_no_hay_rivales"]:
            threading.Thread(target=self._buscar_rivales, daemon=True).start()
        while True:
            try:
                for ev in self.lichess.eventos():
                    self._evento(ev)
            except (requests.RequestException, ValueError) as e:
                print(f"[aviso] Se cortó la conexión ({e}). Reconectando en 5 s...")
                time.sleep(5)

    def _evento(self, ev):
        tipo = ev.get("type")
        if tipo == "challenge":
            self._reto(ev["challenge"])
        elif tipo == "gameStart":
            juego = ev.get("game", {})
            gid = juego.get("gameId") or juego.get("id")
            if gid and not self.jugando.is_set():
                self.jugando.set()
                threading.Thread(target=self._jugar, args=(gid,), daemon=True).start()

    def _reto(self, reto):
        if reto.get("challenger", {}).get("id", "") == self.yo:
            return
        cid = reto["id"]
        nombre = reto.get("challenger", {}).get("name", "alguien")
        control = reto.get("timeControl", {})
        if not self.cfg["aceptar_retos"]:
            return self.lichess.rechazar(cid, "generic")
        if reto.get("variant", {}).get("key") != "standard":
            return self.lichess.rechazar(cid, "standard")
        if control.get("type") != "clock":
            return self.lichess.rechazar(cid, "timeControl")
        if control.get("limit", 0) < self.cfg["tiempo_minimo_segundos"]:
            return self.lichess.rechazar(cid, "tooFast")
        if control.get("limit", 0) > self.cfg["tiempo_maximo_segundos"]:
            return self.lichess.rechazar(cid, "tooSlow")
        if self.jugando.is_set():
            return self.lichess.rechazar(cid, "later")
        print(f"[reto] {nombre} me retó. Acepto.")
        self.voz.decir(f"{nombre} me retó. ¡Acepto!")
        self.lichess.aceptar(cid)

    def _buscar_rivales(self):
        espera = self.cfg["segundos_espera_antes_de_retar"]
        while True:
            time.sleep(10)
            if self.jugando.is_set() or time.time() - self.ultima_partida < espera:
                continue
            bots = [b for b in self.lichess.bots_en_linea() if b.get("id") != self.yo]
            if not bots:
                continue
            rival = random.choice(bots)
            print(f"[reto] Nadie me reta. Reto al bot {rival['username']}...")
            ESTADO.actualizar(estado=f"Retando a {rival['username']}...")
            self.lichess.retar(rival["username"], self.cfg["reto_tiempo_segundos"], self.cfg["reto_incremento"])
            self.ultima_partida = time.time()

    def _jugar(self, gid):
        info = {"color": chess.WHITE, "fen": chess.STARTING_FEN, "ultimo_n": -1,
                "ev_anterior": None, "terminada": False}
        print(f"[partida] Empieza https://lichess.org/{gid}")
        try:
            for ev in self.lichess.partida(gid):
                tipo = ev.get("type")
                if tipo == "gameFull":
                    blancas, negras = ev.get("white", {}), ev.get("black", {})
                    soy_blancas = blancas.get("id") == self.yo
                    info["color"] = chess.WHITE if soy_blancas else chess.BLACK
                    rival = negras if soy_blancas else blancas
                    if ev.get("initialFen") and ev["initialFen"] != "startpos":
                        info["fen"] = ev["initialFen"]
                    nombre = rival.get("name") or rival.get("id") or "Anónimo"
                    ESTADO.actualizar(rival=nombre, rival_rating=str(rival.get("rating", "")),
                                      mi_color="blancas" if soy_blancas else "negras",
                                      estado="Jugando", eval=0.0)
                    self.voz.decir(f"Juego contra {nombre}. Yo llevo las {'blancas' if soy_blancas else 'negras'}. ¡Suerte!")
                    self.lichess.chat(gid, f"Hola, soy {NOMBRE}. ¡Buena suerte! ♟️")
                    self._estado(gid, ev["state"], info)
                elif tipo == "gameState":
                    self._estado(gid, ev, info)
                elif tipo == "chatLine":
                    if ev.get("username", "").lower() != self.yo and "hola" in ev.get("text", "").lower():
                        self.lichess.chat(gid, "¡Hola! Gracias por jugar conmigo.")
                if info["terminada"]:
                    break
        except (requests.RequestException, ValueError) as e:
            print(f"[aviso] Se cortó la partida ({e}).")
        finally:
            self.jugando.clear()
            self.ultima_partida = time.time()
            ESTADO.actualizar(estado="Esperando rival")

    def _estado(self, gid, st, info):
        board = chess.Board(info["fen"])
        jugadas = st.get("moves", "").split()
        for m in jugadas:
            board.push_uci(m)
        ultimo = board.peek() if board.move_stack else None
        ESTADO.actualizar(tablero=dibujar_tablero(board, info["color"], ultimo), jugadas=len(jugadas))
        if st.get("status", "started") != "started":
            self._final(gid, st, info)
            return
        if board.turn != info["color"] or len(jugadas) == info["ultimo_n"]:
            return
        info["ultimo_n"] = len(jugadas)
        mi_reloj = st.get("wtime" if info["color"] == chess.WHITE else "btime", 60000)
        inc = st.get("winc" if info["color"] == chess.WHITE else "binc", 0)
        if not isinstance(mi_reloj, (int, float)):
            mi_reloj = 60000
        segundos = (mi_reloj / 1000) / 40 + (inc / 1000) * 0.7
        segundos = max(0.1, min(segundos, self.cfg["max_segundos_pensar"]))
        if random.random() < 0.15:
            self.voz.decir(random.choice(PENSANDO))
        jugada, ev_blancas = self.cerebro.elegir(board, segundos)
        if mi_reloj > 30000:
            time.sleep(self.cfg["pausa_extra"])
        ev_mia = ev_blancas if info["color"] == chess.WHITE else -ev_blancas
        texto = comentario(board, jugada, ev_mia, info["ev_anterior"])
        info["ev_anterior"] = ev_mia
        if self.lichess.mover(gid, jugada.uci()):
            ESTADO.actualizar(eval=round(ev_blancas, 2))
            self.voz.decir(texto)
        else:
            info["ultimo_n"] = -1

    def _final(self, gid, st, info):
        if info["terminada"]:
            return
        info["terminada"] = True
        estado, ganador = st.get("status"), st.get("winner")
        mi_color = "white" if info["color"] == chess.WHITE else "black"
        if estado in ("aborted", "noStart"):
            self.voz.decir("La partida se canceló.")
            return
        if ganador == mi_color:
            ESTADO.resultado("victorias")
            ESTADO.actualizar(estado=f"¡Ganó {NOMBRE}!")
            self.voz.decir(random.choice(["¡Gané! Buena partida.", f"¡Victoria para {NOMBRE}!", "Gané esta. ¿Quién sigue?"]))
        elif ganador:
            ESTADO.resultado("derrotas")
            ESTADO.actualizar(estado=f"Perdió {NOMBRE}")
            self.voz.decir(random.choice(["Perdí. Bien jugado, rival.", "Me ganaste. La próxima será mía."]))
        else:
            ESTADO.resultado("tablas")
            ESTADO.actualizar(estado="Tablas")
            self.voz.decir("Quedamos en tablas. Partida pareja.")
        self.lichess.chat(gid, "GG, gracias por jugar ♟️")
        print(f"[partida] Terminó: {estado} (ganador: {ganador or 'nadie'})")


# ===========================================================================
# MODO PRUEBA (sin internet): Arché contra Arché
# ===========================================================================
def modo_prueba(cfg, max_jugadas=None):
    voz = Voz(cfg["voz_activa"], cfg["velocidad_voz"])
    cerebro = Cerebro(cfg)
    ESTADO.actualizar(modo="lichess", bot=NOMBRE, rival=f"{NOMBRE} (espejo)", rival_rating="?",
                      estado="Partida de prueba")
    voz.decir("Modo prueba. Voy a jugar contra mí mismo.")
    try:
        while True:
            board = chess.Board()
            ev_ant = {chess.WHITE: None, chess.BLACK: None}
            ESTADO.actualizar(tablero=dibujar_tablero(board, chess.WHITE), eval=0.0, jugadas=0)
            time.sleep(2)
            while not board.is_game_over() and (max_jugadas is None or len(board.move_stack) < max_jugadas):
                jugada, ev_b = cerebro.elegir(board, min(1.0, cfg["max_segundos_pensar"]))
                ev_mia = ev_b if board.turn == chess.WHITE else -ev_b
                texto = comentario(board, jugada, ev_mia, ev_ant[board.turn])
                ev_ant[board.turn] = ev_mia
                board.push(jugada)
                ESTADO.actualizar(tablero=dibujar_tablero(board, chess.WHITE, jugada),
                                  eval=round(ev_b, 2), jugadas=len(board.move_stack))
                voz.decir(texto)
                time.sleep(cfg["pausa_extra"] + 0.5)
            if max_jugadas is not None:
                return board
            res = board.result()
            ESTADO.resultado("victorias" if res != "1/2-1/2" else "tablas")
            voz.decir(f"Fin de la partida de prueba: {res}.")
            time.sleep(5)
    finally:
        cerebro.cerrar()


# ===========================================================================
def main():
    p = argparse.ArgumentParser(description="Arché juega ajedrez")
    p.add_argument("--tiktok", action="store_true", help="TikTok vs Arché: el chat del LIVE vota las jugadas")
    p.add_argument("--tiktok-simulado", action="store_true", help="Modo TikTok con espectadores falsos")
    p.add_argument("--twitch", action="store_true", help="Chat de Twitch vs Arché")
    p.add_argument("--twitch-simulado", action="store_true", help="Modo Twitch con espectadores falsos")
    p.add_argument("--prueba", action="store_true", help="Arché contra sí misma, sin internet")
    p.add_argument("--probar-voz", action="store_true", help="Solo prueba que la voz funcione")
    p.add_argument("--convertir", action="store_true", help="Convertir la cuenta de Lichess en BOT")
    args = p.parse_args()
    cfg = cargar_config()
    global NOMBRE
    NOMBRE = cfg.get("nombre_personaje", "Ghost")
    CONFIG_VOZ.update(cfg)
    ESTADO.actualizar(personaje=NOMBRE, emoji=cfg.get("emoji_personaje", "👻"))

    if args.probar_voz:
        voz = Voz(True, cfg["velocidad_voz"])
        voz.decir(f"Hola, soy {NOMBRE}. Si me escuchas, la voz funciona.")
        voz.decir("Comenten su jugada.")
        time.sleep(12)
        return

    if args.convertir:
        if not cfg["token"] or "PEGA_AQUI" in cfg["token"]:
            print("[error] Primero pega tu token en config_ajedrez.json")
            return
        print("ATENCIÓN: esto es PERMANENTE. La cuenta solo podrá jugar como bot.")
        print("La cuenta debe ser nueva (sin partidas jugadas).")
        if input("Escribe SI para continuar: ").strip().upper() != "SI":
            print("Cancelado.")
            return
        r = Lichess(cfg["token"]).convertir_a_bot()
        print("[ok] ¡Cuenta convertida en BOT!" if r.status_code == 200 else f"[error] {r.status_code}: {r.text}")
        return

    iniciar_overlay(cfg["puerto_overlay"])

    try:
        if args.twitch or args.twitch_simulado:
            if args.twitch and cfg["canal_twitch"] in ("", "tu_canal"):
                print("[error] Pon tu canal de Twitch en config_ajedrez.json (\"canal_twitch\").")
                return
            PartidaTikTok(cfg, simulado=args.twitch_simulado, plataforma="Twitch").correr()
            return
        if args.tiktok or args.tiktok_simulado:
            if args.tiktok and "tu_usuario" in cfg["usuario_tiktok"]:
                print("[error] Pon tu usuario de TikTok en config_ajedrez.json (\"usuario_tiktok\").")
                return
            PartidaTikTok(cfg, simulado=args.tiktok_simulado).correr()
            return
        if args.prueba:
            modo_prueba(cfg)
            return
        if not cfg["token"] or "PEGA_AQUI" in cfg["token"]:
            print("[error] Falta el token de Lichess en config_ajedrez.json")
            return
        bot = ArcheBot(cfg)
        try:
            bot.iniciar()
        finally:
            bot.cerebro.cerrar()
    except KeyboardInterrupt:
        print(f"\nApagando a {NOMBRE}...")


if __name__ == "__main__":
    main()
