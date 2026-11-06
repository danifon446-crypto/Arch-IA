# ♟️ Arché juega ajedrez — guía

## 🎮 Efectos del público (estilo "juegos interactivos")

Arriba de la pantalla se muestran siempre las reglas, **acción = efecto**:

| TikTok | Twitch | Efecto |
|---|---|---|
| 💬 Comentar una jugada | 💬 Escribir una jugada | La más votada se juega |
| ➕ Seguir | (raid) | **+10 segundos** a la votación |
| 🌹 Rosa o regalo pequeño | 💜 Bits | El **voto vale x5** |
| 💎 Regalo de 99+ monedas | ⭐ Sub o 500 bits | **DESHACE** la última jugada de Ghost y el chat vuelve a votar |
| ❤️ Meta de likes | 🔥 Meta de mensajes | Ghost **se distrae** y juega muy mal |

También hay **TOP APOYO** (ranking con corona 👑), **MEJOR REGALO**, meta de **seguidores de hoy** y avisos animados en pantalla.

La pantalla cambia sola: en **vertical** (TikTok) o en **horizontal** (OBS en 1920x1080 para Twitch).

Se ajusta en `config_ajedrez.json`: `segundos_extra_seguir`, `monedas_deshacer`, `bits_deshacer`, `meta_likes`, `meta_mensajes_twitch`, `meta_seguidores`.

---

## 🟣 Transmitir en TWITCH (empieza aquí)

Twitch no pide mínimo de seguidores. El chat de Twitch vota las jugadas igual que en el modo TikTok:

- Cada turno hay **votación** y la gente escribe su jugada (`e4`, `Cf3`, `e2e4`, `enroque`).
- **Bits o suscripción 💜:** el próximo voto de esa persona vale más.
- **Meta de mensajes 💬:** cuando el chat escribe 40 mensajes, Arché "se distrae" y juega peor.
- **Raids 🚀:** Arché le da la bienvenida a la gente que llega.

Leer el chat de Twitch es **oficial y gratis**: Arché entra como espectador anónimo, sin contraseña ni token.

### 1. Crear la cuenta y preparar
1. Crea tu cuenta en **twitch.tv** y activa la verificación en dos pasos (Twitch la pide para transmitir).
2. Copia tu clave: **twitch.tv/dashboard → Configuración → Transmisión → Clave de transmisión principal**.
   🔒 No se la muestres a nadie.

### 2. Configurar Arché
En `config_ajedrez.json` pon tu canal, que es tu nombre de usuario de Twitch:
```
"canal_twitch": "tu_usuario_de_twitch",
```
Ensaya sin transmitir:
```
python arche_ajedrez.py --twitch-simulado
```

### 3. Configurar OBS (Twitch es horizontal)
1. Descarga **OBS Studio** (obsproject.com).
2. **Ajustes → Video**: resolución base y de salida **1920x1080**, a **30 FPS**.
3. **Ajustes → Emisión**: Servicio **Twitch** → *Conectar cuenta* (o pega la clave de transmisión).
4. **Ajustes → Salida**: tasa de bits de video entre **3000 y 4500 Kbps** (según tu internet).
5. En **Fuentes → + → Navegador**:
   - URL: `http://localhost:8765`
   - Ancho **1920**, alto **1080**
   La pantalla de Arché queda centrada, con espacio libre a los lados.
6. Agrega **Captura de audio de salida** para que se escuche la voz de Arché.
7. Opcional: en los costados, tu **cámara** (Fuentes → Dispositivo de captura de video) y un texto con las reglas: *"Escribe tu jugada en el chat: e4, Cf3..."*.

### 4. ¡En vivo!
1. Ejecuta:
   ```
   python arche_ajedrez.py --twitch
   ```
   Debe aparecer **"Conectada al chat de twitch.tv/tu_canal"**.
2. En OBS: **Iniciar transmisión**.
3. En el dashboard de Twitch pon título (ej. *"Una IA contra el CHAT ♟️ escribe tu jugada"*) y categoría **Chess**.

💡 Mientras creces, graba partidas con OBS (*Iniciar grabación*) y sube los mejores momentos a TikTok y YouTube Shorts con el mensaje *"juega contra Arché en vivo en Twitch"*.

---

## Modo TikTok (cuando tengas 1.000 seguidores)

Los lives que más enganchan en TikTok son **interactivos**: el público no solo mira, también controla el juego.
Por eso este modo funciona así:

- **El chat juega contra Arché.** Cada turno hay una votación de 25 s y la gente **comenta su jugada** (`e4`, `Cf3`, `e2e4`, `enroque`...). La más votada se juega.
- **Regalos 🎁:** el próximo voto de quien manda un regalo vale **+5** por cada regalo. Arché le da las gracias en voz alta.
- **Likes ❤️:** al llegar a la meta (300), Arché "se distrae" y su siguiente jugada es mucho peor. Así el público tiene una razón para dar likes.
- **Seguidores ➕:** Arché los saluda por su nombre.
- Marcador **Chat vs Arché**, reloj de votación y votos en vivo **arriba de la pantalla**, porque TikTok pone sus comentarios y botones en la parte de abajo.
- Cada partida se alternan los colores. Arché juega a **nivel bajo** (`nivel_tiktok: 3`) para que el chat pueda ganarle.

---

## Paso 1 — Instalar

Necesitas **Python 3.10 o más nuevo** (para la librería de TikTok). En la terminal, **dentro de la carpeta `arche_ajedrez`**:

```
pip install -r requirements.txt
```

## Paso 2 — Ensayar sin estar en vivo

```
python arche_ajedrez.py --tiktok-simulado
```

Abre **http://localhost:8765**: espectadores falsos votan, dan likes y regalos. Para detener: `Ctrl + C`.

## Paso 3 — Stockfish (opcional pero recomendado)

1. Descarga Stockfish desde **stockfishchess.org/download**
2. Descomprímelo (ej. `C:/stockfish/`)
3. Pon la ruta del `.exe` en `"ruta_stockfish"` (con `/`, no `\`)

Sin Stockfish, Arché usa un cerebro propio más débil (que en modo TikTok también sirve).

## Paso 4 — En vivo

1. Pon tu usuario en `config_ajedrez.json` → `"usuario_tiktok": "@tu_usuario"`.
2. **Primero inicia el LIVE en TikTok**. La conexión solo funciona cuando ya estás en vivo; si no, el programa reintenta cada 15 s.
3. Luego ejecuta:

```
python arche_ajedrez.py --tiktok
```

### Cómo mostrar la pantalla en el LIVE

**TikTok LIVE Studio (PC):** agrega una captura de ventana del navegador con `http://localhost:8765` en pantalla completa (F11), elige formato **vertical** y agrega el **audio del escritorio** para que se escuche la voz de Arché.

**OBS:** *Ajustes → Video* en **1080x1920**. Agrega una fuente **Navegador** con `http://localhost:8765`, ancho 1080 y alto 1920, más "Captura de audio de salida".

⚠️ TikTok normalmente pide **18+ años** y un mínimo de seguidores para hacer LIVE. Revisa en tu app si ya tienes la opción.

⚠️ La librería `TikTokLive` **no es oficial** (TikTok no tiene API pública para leer el chat del LIVE). Funciona bien, pero si TikTok cambia algo puede dejar de funcionar hasta que la actualicen (`pip install -U TikTokLive`).

---

## Consejos para el stream

- **Explica las reglas al inicio** (Arché lo hace sola, pero repítelo cuando entre gente nueva).
- **25 s por votación** es un buen punto: suficiente para escribir y lo bastante rápido para que no aburra. Ajusta `segundos_votacion` según cuánta gente haya.
- Si casi nadie vota, baja `meta_likes` y `segundos_votacion`.
- Si el chat gana demasiado fácil, sube `nivel_tiktok` (0–20).
- Habla tú también: los lives con una persona reaccionando retienen más que los 100 % automáticos.

---

## Otros modos

| Comando | Qué hace |
|---|---|
| `python arche_ajedrez.py --prueba` | Arché contra sí misma, sin internet |
| `python arche_ajedrez.py` | Arché en **Lichess** contra quien la rete (necesita cuenta BOT) |
| `python arche_ajedrez.py --convertir` | Convierte una cuenta **nueva** de Lichess en BOT (permanente) |

Para el modo Lichess: crea una cuenta nueva en lichess.org, genera un token en **lichess.org/account/oauth/token/create** con el permiso `bot:play`, pégalo en `"token"` y ejecuta `--convertir` una vez.

🔒 No subas `config_ajedrez.json` a GitHub si tiene tu token. Agrégalo al `.gitignore`.

## Problemas comunes

- **No habla:** instala una voz en español en Windows (*Configuración → Hora e idioma → Voz*).
- **"No pude conectarme al LIVE":** inicia el LIVE primero y revisa el usuario (con `@`).
- **No cuenta mis votos:** solo cuentan durante la votación, y solo jugadas legales.
- **La página no cambia:** el programa no está corriendo.
