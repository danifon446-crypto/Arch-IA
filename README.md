# Arché

Asistente personal en Python que entiende órdenes en español, controla el PC, aprende de lo que le enseñas y trabaja con modelos locales (Ollama) y en la nube (Groq). Está en desarrollo continuo.

## Qué incluye

| Carpeta | Qué hace |
|---|---|
| `Arche/main.py` | Punto de entrada: consola, comandos y módulos. |
| `Arche/core/IA/` | Cerebro: clasificador de intenciones, aprendizaje, examen, autoedición de código. |
| `Arche/core/interfaz/` | Ventana gráfica, panel web y control desde el celular. |
| `Arche/core/agente/` | Agente autónomo (Minecraft y entornos simulados). |
| `Arche/core/tres_d/` | Diseño de piezas 3D con gestos de mano. |
| `Arche/Perro_robotico/` | Perro robótico con ESP32 y celular como cámara. |
| `Arche/core/whatsapp.py` | Responder por WhatsApp (solo números autorizados). |
| `nube/` | Aprendizaje en la nube: turnos con Groq y entrenador de `arche-lora`. |

## Instalar

En Windows, un solo comando en PowerShell:

```powershell
irm https://raw.githubusercontent.com/danifon446-crypto/Arch-IA/main/instalar.ps1 | iex
```

A mano:

```bash
pip install -r requirements.txt
cd Arche
python main.py
```

Necesita Python 3.10 o superior. Para el modelo local, instala [Ollama](https://ollama.com).

## Probar que todo funciona

```bash
cd Arche
python correr_pruebas.py          # todas las pruebas
python core/IA/autotest.py        # autoprueba de Arché
```

GitHub corre las pruebas solas en cada subida (`.github/workflows/pruebas.yml`).

## Medir si Arché mejora

```bash
cd Arche
python evaluar_examen_fijo.py --congelar   # una sola vez: crea el examen (ya viene hecho)
python evaluar_examen_fijo.py              # mide y guarda en core/IA/historial_precision.jsonl
python evaluar_examen_fijo.py --ver        # evolución de la precisión
```

La cifra que importa es **precisión en frases no vistas**: las que Arché no ha estudiado. El examen fijo (`core/IA/examen_fijo.jsonl`) no se edita ni se usa para entrenar. Si la precisión baja más de 2 puntos, el script termina con error.

## Seguridad

- **Control por celular:** apagado por defecto, pide PIN de 6 números y bloquea tras varios intentos. Para cifrarlo con HTTPS: `python crear_certificado_celular.py` y reinicia el acceso. Sin certificado funciona en HTTP, y el PIN viaja sin cifrar.
- **WhatsApp:** verifica la firma de Meta y solo responde a números autorizados; las órdenes que modifican código están bloqueadas por ese canal.
- **Cambios de código propios:** se validan, se prueban en un entorno aislado y se respaldan antes de aplicarse. Ver `LEEME-SEGURIDAD.md`.
- **Claves:** nunca van en el repo; se guardan cifradas en tu PC o como secretos de GitHub Actions.
- `clasificador.pkl` es un archivo `pickle`: no cargues uno que no hayas entrenado tú.

## Estado de los datos

Lo que Arché genera al usarse (conocimiento, logs, modelos) no se sube al repo; está en `.gitignore`. El historial de precisión sí se sube.
