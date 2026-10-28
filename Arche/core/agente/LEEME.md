Agente autónomo de Arché
Carpeta: Arche/core/agente/

QUÉ ES
Arché recibe un objetivo ("en minecraft consigue 10 de madera"), mira el
entorno, razona, hace un plan, ejecuta acciones, comprueba con datos reales si
se cumplieron y guarda lecciones de lo que le salió bien o mal para la próxima.

CÓMO SE ORGANIZA (cada pieza se puede cambiar sin tocar las demás)
  conocimiento.py          las recetas y herramientas REALES del juego (las lee del propio Minecraft)
  simbolico.py             planifica y decide con esas recetas, SIN ningún modelo de IA
  habilidades.py           lo que ya le salió bien se repite sin consultar a nadie
  reglas.py                reglas del juego que Arché investiga solo en la wiki
  planificador.py          objetivo -> subobjetivos con un modelo (solo cuando lo simbólico no alcanza)
  decisor.py               elige la SIGUIENTE acción (solo la propone)
  ejecutor.py              valida y ejecuta (sin IA); límites y autorización
  verificador.py           datos reales del entorno primero; un modelo solo si no hay otra forma
  percepcion.py            observa; si hay imagen y modelo de visión, la describe en texto
  memoria_experiencias.py  lecciones que se reutilizan (suben o bajan según si ayudaron)
  coordinador.py           el ciclo completo + reflexión
  modelos.py               modelos por ROL, intercambiables
  entorno.py               el contrato de un mundo (Minecraft, otro juego, navegador, robot)
  entornos/                simulado.py (mundo de juguete) y minecraft.py
  puente_minecraft/        bot.js: el jugador-bot (Node + Mineflayer)
  comandos.py              los comandos del chat

INSTALAR
1. Copia la carpeta core/agente/ completa dentro de Arche/core/ y los dos archivos
   aplicar_parche_agente.py y prueba_agente.py dentro de Arche/.
2. Con Arché cerrado, en la carpeta Arche:   python aplicar_parche_agente.py
3. Comprueba que todo anda (sin Minecraft, sin Ollama):   python prueba_agente.py
4. Abre Arché y escribe:   agente prueba

MINECRAFT (Java)
1. Instala Node.js 18 o más (nodejs.org).
2. En Arché:   agente instala puente minecraft     (una sola vez)
3. Abre tu mundo en Minecraft y "Abrir a LAN"; mira el puerto que te muestra.
4. En Arché:   agente configura minecraft puerto=<el puerto> version=<tu versión, ej. 1.20.4>
5. En Arché:   en minecraft consigue 5 de madera
Para ver al bot en tu pantalla, entra tú también al mismo mundo (o usa un servidor).
"agente para" lo detiene en cualquier momento.

MODELOS (elige según tu equipo)
Por defecto cada rol usa "auto": la nube de Arché (Groq) si hay, y si no, Ollama.
  agente modelos                              ver qué usa cada rol
  agente modelo decisor ollama:qwen3:8b       forzar un modelo local
  agente modelo planificador nube             usar la nube
  agente modelo vision ollama:llava           modelo de visión local
  agente modelo decisor compat:http://localhost:1234/v1#mi-modelo     LM Studio, llama.cpp...
Para visión: agente configura minecraft captura_pantalla=si (necesita un modelo de visión).
Para agregar otro tipo de proveedor: modelos.py -> registrar_proveedor().

AGREGAR OTRO JUEGO O ENTORNO
Copia entornos/simulado.py (es el más corto), implementa observar(), herramientas()
y ejecutar(), regístralo con registrar_entorno() y agrega su nombre a IMPORTAR en
entornos/__init__.py. El planificador, decisor, verificador y la memoria no cambian.

CÓMO DECIDE (de lo más barato a lo más caro; la nube solo entra al final)
  1. Cálculo con las recetas del juego: "consigue un pico de piedra" lo resuelve él solo (madera, tablones,
     palos, mesa, pico de madera, piedra, pico de piedra), explorando si no ve árboles. Cero nube.
  2. Habilidades guardadas: si ese mismo paso ya le salió bien antes, repite las acciones. Cero nube.
  3. Un modelo (la nube): solo para lo nuevo o cuando 1 y 2 fallan (combate, fundir en horno, situaciones raras).
Con la nube caída o sin cuota sigue haciendo lo que ya sabe; lo demás queda guardado y lo retomas con «agente continua».

APRENDE LAS REGLAS SOLO
  - Recetas, herramientas por bloque y qué suelta cada uno: las lee del propio juego (no las escribe nadie).
  - Lo demás (monstruos, hambre, supervivencia): la primera vez que juega, lee la wiki del juego, un modelo
    saca reglas prácticas y las guarda. «agente investiga [tema]» lo repite cuando quieras;
    «agente reglas» las muestra; «agente reglas agrega <texto>» suma una tuya (opcional).
  - Lo que aprende jugando (errores y aciertos) va aparte, en la memoria de experiencias.

COMANDOS ÚTILES
  agente investiga [tema]      lee la wiki y aprende reglas   |  agente reglas       las muestra
  agente habilidades           lo que ya sabe hacer sin modelo |  agente olvida habilidades confirmo
  en minecraft <objetivo>      trabajar en tu mundo (ej. "en minecraft consigue una mesa de crafteo y un pico de madera")
  agente <objetivo>            lo mismo en el entorno configurado
  agente para                  detenerlo ya
  agente estado                qué está haciendo
  agente diagnostico           revisa Node, puente, conexión al mundo, nube y memoria (úsalo si algo no anda)
  agente nube                  prueba la nube principal y la de respaldo
  agente pendiente / continua  si algo externo lo cortó (límite de la nube), retoma el plan donde quedó
  agente memoria               lecciones aprendidas (agente olvida experiencias confirmo: las borra)
  agente version               versión del agente
Herramientas de Minecraft: buscar_bloque, ir_a, ir_a_bloque, recolectar, craftear, colocar, equipar,
atacar, comer, dormir, alejarse, subir_a_superficie, esperar, decir.

VERSIÓN DE MINECRAFT
Mineflayer soporta hasta 1.21.11 (y 26.1). Si tu launcher tiene una versión más nueva, crea una
instalación 1.21.11 y un mundo nuevo, ábrelo a LAN y pon puerto= y version= en "agente configura minecraft".

QUÉ ESTÁ PROBADO Y QUÉ NO
Probado automáticamente: el ciclo completo con un cerebro simulado (prueba_agente.py, 10 secciones:
errores y lecciones, protecciones, parada, lotes de acciones, verificación de objetivos compuestos,
reintentos de la nube, respaldo, y retomar planes a medias).
Probado contra un servidor local: conectar, leer estado, caminar, picar, colocar, subir a la superficie
y mensajes de error claros.
Probado por ti en tu Minecraft: conseguir madera y piedra, fabricar mesa y pico de madera.
También probado: el agente completo sin ningún modelo (0 llamadas) consiguiendo un pico de madera y 5 de
piedra desde cero en un mundo de pruebas; explorar cuando no ve árboles; guardar y repetir habilidades;
leer las recetas reales desde el puente (702 recetas en 1.20.4).
NO probado todavía: combate, dormir, comer, visión (captura de pantalla + modelo de visión),
y la lectura de la wiki contra internet real (en mi entorno no hay acceso; está probada con una wiki simulada).
Fundir en horno (hierro, comida cocinada) todavía no se calcula solo: se le deja a un modelo.
Esas partes se validan en tu equipo; si algo falla, pásame el mensaje que sale.

SEGURIDAD
- El puente solo escucha en 127.0.0.1.
- El bot no puede ejecutar comandos del juego (/...), solo escribir en el chat.
- Hay tope de acciones (60) y de tiempo (15 min) por objetivo, corte por fallos seguidos
  y por repetir lo mismo sin cambios (ajustable en Database/agente/config.json).
- Las herramientas marcadas "peligrosas" no corren sin autorización (hoy no hay ninguna).
- Datos en Database/agente/ (config.json, modelos.json, experiencias.jsonl).

HOJA DE RUTA (la meta: que Arché sea un agente autónomo general)
Ya existe la base común: objetivo -> plan -> acción -> verificación -> lección, con modelos intercambiables
por rol y entornos intercambiables. Cada idea siguiente es agregar piezas, no rehacer:
1. Agente de computador: un entorno nuevo (navegador/PC) con sus herramientas, con confirmación en lo peligroso.
2. Planificador inteligente: ya calcula materiales con las recetas, divide en subobjetivos, replanifica y explora; falta fundir (horno), prioridades y estrategias alternativas.
3. Aprender por experiencia en simulación: entornos simulados para practicar sin riesgo; la memoria ya guarda lecciones.
4. Auto-mejora de Arché: proponer cambios a su propio código y aplicarlos solo con tu autorización explícita.
5. Inteligencia general en juegos: cada juego es un entorno que implementa el mismo contrato (entorno.py).
6. Mundo físico (ESP32, robots): un entorno con parada de emergencia y herramientas marcadas "peligrosas".
7. Memoria a largo plazo: ya persisten experiencias, habilidades y reglas; falta resumirlas y compartirlas entre entornos.
8. Agentes especializados (investigar, planear, ejecutar, verificar) con un coordinador: los roles ya están separados.
