# Seguridad de Arché — cómo instalarla

## 1. Copiar los archivos
Descomprime el zip **encima** de tu carpeta `Arch-IA` (la que tiene `.gitignore` y la carpeta `Arche`).
Acepta reemplazar. Se agregan/cambian:

| Archivo | Qué hace |
|---|---|
| `Arche/core/seguridad/cifrado.py` | **Nuevo.** Cifra claves y tokens con DPAPI de Windows |
| `Arche/core/seguridad/guardian.py` | **Nuevo.** Huellas firmadas del código, escáner de código peligroso, bitácora encadenada |
| `Arche/core/seguridad/comandos.py` | **Nuevo.** "estado de seguridad" y "bitácora de seguridad" en el chat |
| `Arche/seguridad.py` | **Nuevo.** Panel de seguridad para la terminal |
| `Arche/prueba_cifrado_guardian.py` | **Nuevo.** Pruebas de todo lo anterior |
| `Arche/core/interfaz/remoto.py` | Control del celular blindado |
| `Arche/core/IA/nube.py`, `Arche/core/whatsapp.py` | Guardan claves y tokens cifrados |
| `Arche/core/IA/revisar_cambios_codigo.py`, `proponer_cambio_codigo.py`, `mejora_continua.py` | La autocodificación pasa por el escáner y avisa al guardián |
| `Arche/main.py` | Revisión de seguridad al arrancar |
| `Arche/prueba_seguridad.py` | Ya no escribe en tu bitácora real |
| `.gitignore` | Deja de subir `config.json` (tenía tu PIN) |

## 2. Probar
```
cd Arch-IA\Arche
python prueba_seguridad.py
python prueba_cifrado_guardian.py
```
Las dos deben terminar en `TODO OK`.

## 3. Tres pasos obligatorios (una sola vez)
```
python seguridad.py cifrar       # cifra las claves que ya tenías en texto plano
python seguridad.py nuevo-pin    # tu PIN del celular estaba publicado en GitHub
python seguridad.py sellar       # aprueba el código tal como está ahora
```
Y saca `config.json` de GitHub (el archivo se queda en tu PC):
```
cd ..
git rm --cached Arche/core/interfaz/config.json
git commit -am "Seguridad: cifrado, guardián y control remoto blindado"
git push
```

## 4. Uso diario
- En el chat: **"estado de seguridad"** o **"bitácora de seguridad"**.
- Si cambias código a mano, Arché te avisará al arrancar. Si fuiste tú: `python seguridad.py sellar`.
- Aprobar cambios **solo** se puede desde la terminal del PC, nunca por chat, celular ni WhatsApp.
