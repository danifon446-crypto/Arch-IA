"""
prueba_cifrado_guardian.py
--------------------------
Ubicacion: Arche/prueba_cifrado_guardian.py

Prueba (sin internet, sin Ollama, sin tocar tu Database real) el modulo de
seguridad nuevo:

  * core/seguridad/cifrado.py: cifra y descifra, no deja texto plano en el disco,
    migra solas las claves viejas, y detecta un secreto alterado.
  * core/IA/nube.py y core/whatsapp.py: guardan las claves/tokens cifrados.
  * core/seguridad/guardian.py: sella el codigo, detecta archivos cambiados,
    nuevos y borrados, detecta un manifiesto falsificado, la bitacora encadenada
    nota si borran o editan una linea, y el escaner bloquea codigo peligroso.
  * core/interfaz/remoto.py: solo acepta conexiones de casa / Tailscale.

Correr:  python prueba_cifrado_guardian.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

from core.seguridad import cifrado, guardian  # noqa: E402

fallos = []


def chequear(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}")
    else:
        print(f"FALLA {nombre}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")
        fallos.append(nombre)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    db = tmp / "Database"
    db.mkdir()
    codigo = tmp / "app"
    (codigo / "core").mkdir(parents=True)

    with mock.patch.object(cifrado, "DATABASE", str(db)), \
            mock.patch.object(cifrado, "ARCHIVO_LLAVE", str(db / ".llave_arche")), \
            mock.patch.object(guardian, "DATABASE", str(db)), \
            mock.patch.object(guardian, "RAIZ", codigo), \
            mock.patch.object(guardian, "ARCHIVO_MANIFIESTO", str(db / "integridad.json")), \
            mock.patch.object(guardian, "ARCHIVO_LLAVE", str(db / "integridad.llave")), \
            mock.patch.object(guardian, "ARCHIVO_BITACORA", str(db / "auditoria.jsonl")), \
            mock.patch.object(guardian, "_llave_cache", None):

        # ---------------- cifrado ----------------
        secreto = "gsk_EstoEsUnaClaveSuperSecreta123"
        c = cifrado.cifrar(secreto)
        chequear("cifrado: lleva prefijo", cifrado.esta_cifrado(c), True)
        chequear("cifrado: no contiene el secreto", secreto in c, False)
        chequear("cifrado: descifra igual", cifrado.descifrar(c), secreto)
        chequear("cifrado: cifrar dos veces no lo daña", cifrado.descifrar(cifrado.cifrar(c)), secreto)
        chequear("cifrado: texto viejo sin prefijo se devuelve tal cual", cifrado.descifrar("abc"), "abc")

        ruta = str(db / "nube_clave_groq.txt")
        cifrado.guardar_secreto(ruta, secreto)
        chequear("archivo: en disco NO esta en texto plano", secreto in open(ruta, encoding="utf-8").read(), False)
        chequear("archivo: se lee bien", cifrado.leer_secreto(ruta), secreto)

        Path(ruta).write_text("clave_vieja_en_plano", encoding="utf-8")
        chequear("migracion: la clave vieja se sigue leyendo", cifrado.leer_secreto(ruta), "clave_vieja_en_plano")
        chequear("migracion: y quedo cifrada en el disco",
                 cifrado.esta_cifrado(Path(ruta).read_text(encoding="utf-8")), True)

        if cifrado.metodo() == "fernet":
            alterado = c[:-6] + ("AAAAAA" if not c.endswith("AAAAAA") else "BBBBBB")
            try:
                cifrado.descifrar(alterado)
                detecto = False
            except cifrado.ErrorCifrado:
                detecto = True
            chequear("cifrado: un secreto alterado se detecta", detecto, True)

        # ---------------- nube.py ----------------
        from core.IA import nube
        with mock.patch.object(nube, "DATABASE", str(db)), \
                mock.patch.object(nube, "ARCHIVO_CLAVE", str(db / "nube_clave.txt")), \
                mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            nube.guardar_clave(" gsk_desdeNube123456 ", "groq")
            crudo = (db / "nube_clave_groq.txt").read_text(encoding="utf-8")
            chequear("nube: la clave se guarda cifrada", ("gsk_desdeNube" in crudo, cifrado.esta_cifrado(crudo)),
                     (False, True))
            chequear("nube: clave() la devuelve descifrada", nube.clave("groq"), "gsk_desdeNube123456")

        # ---------------- whatsapp.py ----------------
        from core import whatsapp
        with mock.patch.object(whatsapp, "ARCHIVO", str(db / "whatsapp.json")):
            whatsapp._guardar({"token": "EAAGtokenSecreto", "verify_token": "verif123", "phone_id": "555",
                               "permitidos": ["573000000000"]})
            crudo = (db / "whatsapp.json").read_text(encoding="utf-8")
            chequear("whatsapp: token cifrado en disco", "EAAGtokenSecreto" in crudo, False)
            chequear("whatsapp: phone_id sigue legible", json.loads(crudo)["phone_id"], "555")
            d = whatsapp._cargar()
            chequear("whatsapp: al cargar vuelve el token", (d["token"], d["verify_token"]),
                     ("EAAGtokenSecreto", "verif123"))
            (db / "whatsapp.json").write_text(json.dumps({"token": "plano_viejo", "phone_id": "1"}), encoding="utf-8")
            chequear("whatsapp: token viejo se lee", whatsapp._cargar()["token"], "plano_viejo")
            chequear("whatsapp: y quedo migrado a cifrado",
                     "plano_viejo" in (db / "whatsapp.json").read_text(encoding="utf-8"), False)

        # ---------------- guardian: integridad ----------------
        (codigo / "main.py").write_text("print('hola')\n", encoding="utf-8")
        (codigo / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (codigo / "core" / "__pycache__").mkdir()
        (codigo / "core" / "__pycache__" / "a.cpython.py").write_text("basura", encoding="utf-8")
        (codigo / "respaldo_antes_x").mkdir()
        (codigo / "respaldo_antes_x" / "viejo.py").write_text("viejo", encoding="utf-8")

        chequear("guardian: sin sellar", guardian.verificar()["sellado"], False)
        chequear("guardian: sella solo el codigo vivo (ignora caches y respaldos)", guardian.sellar(), 2)
        r = guardian.verificar()
        chequear("guardian: recien sellado todo limpio", guardian.hay_alerta(r), False)
        chequear("guardian: llave de firma guardada cifrada",
                 cifrado.esta_cifrado((db / "integridad.llave").read_text(encoding="utf-8")), True)

        (codigo / "core" / "a.py").write_text("x = 1\nimport os; os.system('malo')\n", encoding="utf-8")
        (codigo / "core" / "intruso.py").write_text("print('soy nuevo')\n", encoding="utf-8")
        (codigo / "main.py").unlink()
        r = guardian.verificar()
        chequear("guardian: detecta cambiado", r["cambiados"], ["core/a.py"])
        chequear("guardian: detecta nuevo", r["nuevos"], ["core/intruso.py"])
        chequear("guardian: detecta borrado", r["borrados"], ["main.py"])
        chequear("guardian: hay alerta", bool(guardian.hay_alerta(r)), True)

        # cambio propio de Arché: se registra y deja de alertar ese archivo
        guardian.registrar_cambio_propio("core/a.py")
        chequear("guardian: cambio propio registrado ya no alerta", guardian.verificar()["cambiados"], [])

        # un malware edita el manifiesto para esconder su cambio
        m = json.loads((db / "integridad.json").read_text(encoding="utf-8"))
        m["archivos"]["core/intruso.py"] = guardian.huella(codigo / "core" / "intruso.py")
        (db / "integridad.json").write_text(json.dumps(m), encoding="utf-8")
        r = guardian.verificar()
        chequear("guardian: manifiesto falsificado -> firma invalida", r["firma_valida"], False)
        chequear("guardian: con firma invalida no acepta re-registrar", guardian.registrar_cambio_propio("core/a.py"),
                 False)
        chequear("guardian: el aviso habla de ALERTA", "ALERTA" in guardian.resumen_texto(r), True)

        guardian.sellar("prueba")
        chequear("guardian: tras sellar de nuevo queda limpio", guardian.hay_alerta(), False)

        # ---------------- guardian: bitacora encadenada ----------------
        for i in range(4):
            guardian.auditar("prueba", i=i)
        chequear("bitacora: integra", guardian.verificar_bitacora()[0], True)
        lineas = (db / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()
        editada = json.loads(lineas[2])
        editada["evento"] = "nada que ver aqui"
        (db / "auditoria.jsonl").write_text("\n".join(lineas[:2] + [json.dumps(editada)] + lineas[3:]) + "\n",
                                            encoding="utf-8")
        chequear("bitacora: detecta una linea editada", guardian.verificar_bitacora()[0], False)
        (db / "auditoria.jsonl").write_text("\n".join(lineas[:2] + lineas[3:]) + "\n", encoding="utf-8")
        chequear("bitacora: detecta una linea borrada", guardian.verificar_bitacora()[0], False)

        # ---------------- guardian: revision al iniciar ----------------
        (db / "auditoria.jsonl").unlink()
        (db / "integridad.json").unlink()
        chequear("arranque: primer arranque sella solo", "selle" in guardian.revision_al_iniciar(), True)
        chequear("arranque: segundo arranque sin novedad", guardian.revision_al_iniciar(), "")
        (codigo / "core" / "a.py").write_text("cambiado = True\n", encoding="utf-8")
        chequear("arranque: avisa si cambiaron codigo", "⚠" in guardian.revision_al_iniciar(), True)

# ---------------- escaner de codigo peligroso ----------------
viejo = "def sumar(a, b):\n    return a + b\n"
casos_peligrosos = {
    "ejecutar_comandos": "import subprocess\nsubprocess.run('del /q C:\\\\*', shell=True)\n",
    "eval_exec": "exec(texto_de_internet)\n",
    "borrado_masivo": "import shutil\nshutil.rmtree('C:/Users')\n",
    "ofuscacion": "import base64\nx = base64.b64decode('cHJpbnQoMSk=')\n",
    "persistencia": "import winreg\n",
    "red_cruda": "import socket\ns = socket.socket()\n",
    "toca_seguridad": "open('core/seguridad/guardian.py', 'w')\n",
    "credenciales": "open('Database/nube_clave.txt').read()\n",
}
for tipo, extra in casos_peligrosos.items():
    hall = [h["tipo"] for h in guardian.escanear_cambio(viejo, viejo + extra)]
    chequear(f"escaner: detecta {tipo}", tipo in hall, True)

chequear("escaner: un cambio normal pasa limpio",
         guardian.escanear_cambio(viejo, viejo.replace("a + b", "int(a) + int(b)")), [])
chequear("escaner: comentarios que mencionan subprocess no alarman",
         guardian.escanear_cambio(viejo, viejo + "# aqui antes usabamos subprocess.run\n"), [])
con_sub = "import subprocess\nsubprocess.run(['notepad'])\n"
chequear("escaner: lo que YA estaba no cuenta como nuevo",
         guardian.escanear_cambio(con_sub + viejo, con_sub + viejo.replace("a + b", "b + a")), [])

# ---------------- remoto: solo casa / Tailscale ----------------
from core.interfaz import remoto  # noqa: E402
for ip, esperado in [("127.0.0.1", True), ("192.168.1.40", True), ("10.0.0.5", True), ("100.101.102.103", True),
                     ("::1", True), ("8.8.8.8", False), ("181.50.10.2", False), ("basura", False)]:
    chequear(f"remoto: ip {ip} permitida={esperado}", remoto.ip_permitida(ip), esperado)
chequear("remoto: el PIN nuevo tiene 6 digitos", len(remoto._pin_aleatorio()) == 6 and remoto._pin_aleatorio().isdigit(),
         True)

# ---------------- protegidos: Arché no puede tocar su seguridad ----------------
from core.IA.proponer_cambio_codigo import ARCHIVOS_PROTEGIDOS  # noqa: E402
for rel in ("core/seguridad/cifrado.py", "core/seguridad/guardian.py", "core/interfaz/remoto.py", "seguridad.py"):
    chequear(f"protegido de la autocodificacion: {rel}", rel in ARCHIVOS_PROTEGIDOS, True)

print()
print("TODO OK" if not fallos else f"FALLARON {len(fallos)}: " + "; ".join(fallos))
sys.exit(1 if fallos else 0)
