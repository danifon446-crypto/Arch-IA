"""
prueba_nucleo.py
----------------
Comprueba todo lo de core/nucleo SIN tocar tus datos reales, sin internet y sin Ollama
(todo lo que saldría a la red o al modelo se reemplaza por respuestas de mentira).

    python prueba_nucleo.py

Debe terminar diciendo "N/N pruebas pasaron".
"""

import io
import json
import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from datetime import datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
os.chdir(AQUI)
sys.path.insert(0, AQUI)

# Todo lo que se guarde va a una carpeta temporal, no a Database/
_TMP = tempfile.mkdtemp(prefix="arche_prueba_nucleo_")
import core.rutas  # noqa: E402
core.rutas.DATABASE = _TMP

from core import evolucion as evo  # noqa: E402
from core.nucleo import (comun, cuarentena, analista, depredador, ritmo, cronista, equipo, imaginacion,  # noqa: E402
                          guardian, voz_viva, avatar)
import core.nucleo as nucleo  # noqa: E402

PRUEBAS = []


def prueba(fn):
    PRUEBAS.append(fn)
    return fn


class Parche:
    """Reemplaza atributos y los devuelve a como estaban."""

    def __init__(self):
        self.guardados = []

    def poner(self, objeto, nombre, valor):
        self.guardados.append((objeto, nombre, getattr(objeto, nombre)))
        setattr(objeto, nombre, valor)

    def quitar(self):
        for objeto, nombre, valor in reversed(self.guardados):
            setattr(objeto, nombre, valor)


HABILIDAD_BUENA = '''
PALABRAS = ["celsius", "fahrenheit", "temperatura"]
DESCRIPCION = "Convierte temperaturas entre celsius y fahrenheit"

def ejecutar(texto):
    import re
    m = re.search(r"(-?\\d+(?:\\.\\d+)?)", texto)
    if not m:
        return "Dime un número"
    n = float(m.group(1))
    return f"{n * 9 / 5 + 32:.1f} F"

def probar():
    assert ejecutar("100 celsius") == "212.0 F"
    assert ejecutar("0 celsius") == "32.0 F"
    assert ejecutar("hola") == "Dime un número"
'''


def _zip(archivos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return buf.getvalue()


# ------------------------------------------------------------------
# Cuarentena
# ------------------------------------------------------------------

@prueba
def cuarentena_detecta_malware_y_deja_pasar_lo_limpio():
    casos_malos = {
        "base64_exec": "import base64\nexec(base64.b64decode('cHJpbnQoMSk='))\n",
        "webhook": "URL = 'https://discord.com/api/webhooks/123/abc'\n",
        "ladron": "ruta = r'AppData\\\\Local\\\\Google\\\\Chrome\\\\User Data\\\\Default\\\\Login Data'\n",
        "ransomware": ("import os\nfrom cryptography.fernet import Fernet\nf = Fernet(k)\n"
                       "for r, d, a in os.walk('C:/'):\n    for x in a:\n        data = f.encrypt(open(x,'rb').read())\n"
                       "        open(x, 'wb').write(data)\n"),
        "minero": "POOL = 'stratum+tcp://pool.example:3333'\n",
    }
    for nombre, codigo in casos_malos.items():
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "x.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        r = cuarentena.escanear(d, usar_defender=False)
        shutil.rmtree(d)
        assert r["veredicto"] == "peligroso", (nombre, r)
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "conv.py"), "w", encoding="utf-8") as f:
        f.write("def c_a_f(c):\n    return c * 9 / 5 + 32\n")
    r = cuarentena.escanear(d, usar_defender=False)
    shutil.rmtree(d)
    assert r["veredicto"] == "limpio", r


@prueba
def cuarentena_no_deja_salir_archivos_del_zip_ni_binarios():
    datos = _zip({"repo/a.py": "x = 1", "../../fuera.py": "malo", "repo/b.exe": "MZ", "repo/c.md": "hola"})
    d = tempfile.mkdtemp()
    n = cuarentena.descomprimir_seguro(datos, os.path.join(d, "cuarentena"))
    assert n == 2, n
    assert not os.path.exists(os.path.join(d, "fuera.py"))
    assert not any(f.endswith(".exe") for _, _, fs in os.walk(d) for f in fs)
    shutil.rmtree(d)


@prueba
def cuarentena_revisa_permisos_de_habilidades():
    assert cuarentena.revisar_habilidad(HABILIDAD_BUENA)[0]
    lee = HABILIDAD_BUENA.replace("def ejecutar(texto):", "def ejecutar(texto):\n    open('x.txt').read()")
    assert not cuarentena.revisar_habilidad(lee)[0]
    assert cuarentena.revisar_habilidad(lee, ("archivos",))[0]
    escribe = HABILIDAD_BUENA.replace("def ejecutar(texto):", "def ejecutar(texto):\n    open('x.txt', 'w')")
    assert not cuarentena.revisar_habilidad(escribe, ("archivos",))[0]
    con_replace = HABILIDAD_BUENA.replace("return f\"{n", "texto = texto.replace('a', 'b')\n    return f\"{n")
    assert cuarentena.revisar_habilidad(con_replace)[0]
    mueve = "import os\n" + HABILIDAD_BUENA.replace("def ejecutar(texto):", "def ejecutar(texto):\n    os.replace('a', 'b')")
    assert not cuarentena.revisar_habilidad(mueve, ("archivos",))[0]
    assert not cuarentena.revisar_habilidad("import subprocess\n" + HABILIDAD_BUENA, ("archivos", "red"))[0]


# ------------------------------------------------------------------
# Núcleo (analista)
# ------------------------------------------------------------------

@prueba
def nucleo_analiza_habilidades():
    assert analista.analizar_habilidad(HABILIDAD_BUENA)[0]
    generica = HABILIDAD_BUENA.replace('["celsius", "fahrenheit", "temperatura"]', '["que", "hola"]')
    assert not analista.analizar_habilidad(generica)[0]
    pocas = HABILIDAD_BUENA.replace('    assert ejecutar("0 celsius") == "32.0 F"\n', "").replace(
        '    assert ejecutar("hola") == "Dime un número"\n', "")
    ok, por_que, _ = analista.analizar_habilidad(pocas)
    assert not ok and "comprueba" in por_que


@prueba
def nucleo_niveles_de_habilidades_suben_bajan_y_descartan():
    assert analista.rango_de({"exitos": 0, "fallos": 0}) == "Aprendiz"
    assert analista.rango_de({"exitos": 5, "fallos": 1}) == "Confiable"
    assert analista.rango_de({"exitos": 15, "fallos": 2}) == "Experta"
    assert analista.rango_de({"exitos": 45, "fallos": 1}) == "Maestra"
    assert analista.rango_de({"exitos": 45, "fallos": 10}) == "Experta"
    assert analista.rango_de({"exitos": 0, "fallos": 0, "rango_minimo": "Experta"}) == "Experta"
    assert analista.rango_de({"exitos": 0, "fallos": 0, "rango_minimo": "Única"}) == "Aprendiz"   # dato viejo
    assert analista.debe_descartarse({"exitos": 2, "fallos": 6})
    assert not analista.debe_descartarse({"exitos": 10, "fallos": 6})


@prueba
def nucleo_rechaza_habilidad_mala_antes_de_la_caja_de_arena():
    p = Parche()
    llamadas = []
    p.poner(evo, "aplicar_cambio_autonomo", lambda c, m, prueba_extra=None: (llamadas.append(m), (True, "ok"))[1])
    analista._ganchos_instalados = False
    try:
        analista.instalar_ganchos()
        mala = HABILIDAD_BUENA.replace('["celsius", "fahrenheit", "temperatura"]', '["hola"]')
        ok, por_que = evo.aplicar_cambio_autonomo({"core/habilidades_auto/x.py": mala}, "prueba")
        assert not ok and "rechazó" in por_que and not llamadas
        ok, _ = evo.aplicar_cambio_autonomo({"core/habilidades_auto/x.py": HABILIDAD_BUENA}, "prueba")
        assert ok and llamadas == ["prueba"]
        assert "core/nucleo/cuarentena.py" in evo.NUCLEO_PROTEGIDO
    finally:
        p.quitar()
        analista._ganchos_instalados = False


@prueba
def nucleo_combina_dos_habilidades():
    p = Parche()
    tmp = tempfile.mkdtemp()
    p.poner(evo, "CARPETA_HABILIDADES", tmp)
    p.poner(evo, "ARCH_HABILIDADES", os.path.join(tmp, "hab.json"))
    p.poner(comun, "pensar", lambda *a, **k: "")
    p.poner(comun, "informe", lambda *a, **k: None)
    escritos = {}
    p.poner(evo, "aplicar_cambio_autonomo", lambda c, m, prueba_extra=None: (escritos.update(c), (True, "ok"))[1])
    try:
        for n, palabras in (("conv_temp", '["celsius"]'), ("conv_dist", '["kilometros"]')):
            with open(os.path.join(tmp, n + ".py"), "w", encoding="utf-8") as f:
                f.write(HABILIDAD_BUENA.replace('["celsius", "fahrenheit", "temperatura"]', palabras))
        evo._guardar(evo.ARCH_HABILIDADES, {"conv_temp": {"tarea": "temperaturas", "usos": 20},
                                            "conv_dist": {"tarea": "distancias", "usos": 20}})
        ok, que = analista.fusionar("conv_temp", "conv_dist", avisar=False)
        assert ok, que
        hab = evo._cargar(evo.ARCH_HABILIDADES, {})
        assert "conv_temp" not in hab and any(k.startswith("combinada_") for k in hab)
        codigo = next(iter(escritos.values()))
        assert evo._codigo_seguro(codigo)[0] and "celsius" in codigo and "kilometros" in codigo
    finally:
        p.quitar()
        shutil.rmtree(tmp)


# ------------------------------------------------------------------
# Imaginación
# ------------------------------------------------------------------

@prueba
def imaginacion_ve_que_quitar_una_funcion_usada_rompe():
    p = Parche()
    p.poner(comun, "pensar", lambda *a, **k: "")
    try:
        with open(os.path.join(AQUI, "core", "web.py"), encoding="utf-8") as f:
            original = f.read()
        sin_noticias = original.replace("def noticias(", "def _noticias_viejas(")
        v = imaginacion.imaginar_cambio({"core/web.py": sin_noticias}, "quitar noticias", usar_modelo=False)
        assert v["decision"] == "descartar" and "noticias" in v["por_que"], v["por_que"]
        solo_cuerpo = original.replace('USER_AGENT = "', 'USER_AGENT = "x')
        v = imaginacion.imaginar_cambio({"core/web.py": solo_cuerpo}, "cambiar agente", usar_modelo=False)
        assert v["decision"] == "aplicar", v
        d = imaginacion.comparar("def a(x):\n    return 1\n", "def a(x, y):\n    return 1\ndef b():\n    pass\n")
        assert d["firma_cambiada"] == ["a"] and d["agregadas"] == ["b"]
    finally:
        p.quitar()


@prueba
def pensamiento_en_paralelo_junta_varias_lineas():
    p = Parche()
    vistas = []

    def _falso(prompt, **k):
        vistas.append(prompt[:30])
        return "FINAL" if "juez" in prompt else "idea"
    p.poner(comun, "pensar", _falso)
    try:
        assert imaginacion.pensamiento_en_paralelo("¿qué servo uso?") == "FINAL"
        assert len(vistas) == 4            # 3 líneas + el juez (Núcleo 1.0)
    finally:
        p.quitar()


# ------------------------------------------------------------------
# Ritmo y Cronista
# ------------------------------------------------------------------

@prueba
def ritmo_aprende_a_que_hora_empiezas():
    lunes = datetime(2026, 11, 2, 0, 0)
    for semana in range(2):
        for dia in range(5):
            base = lunes + timedelta(days=7 * semana + dia)
            ritmo.anotar_actividad(base.replace(hour=6, minute=40))
            ritmo.anotar_actividad(base.replace(hour=12, minute=0))
            ritmo.anotar_actividad(base.replace(hour=23, minute=30))
    hoy = datetime(2026, 11, 16, 9, 0)
    real = comun.ahora
    try:
        comun.ahora = lambda: hoy
        assert ritmo.inicio_habitual(hoy) == 6 * 60 + 40
        assert ritmo.fin_habitual(hoy) == 23 * 60 + 30
        assert ritmo.momento_para("matutino", hoy.replace(hour=6, minute=15), esta_presente=True)
        assert not ritmo.momento_para("matutino", hoy.replace(hour=5, minute=30), esta_presente=True)
        assert not ritmo.momento_para("matutino", hoy.replace(hour=7), esta_presente=False)
        assert ritmo.momento_para("nocturno", hoy.replace(hour=23, minute=5), esta_presente=True)
        assert not ritmo.momento_para("nocturno", hoy.replace(hour=20), esta_presente=True)
        ritmo.marcar_entregado("matutino", hoy.replace(hour=7))
        assert not ritmo.momento_para("matutino", hoy.replace(hour=8), esta_presente=True)
    finally:
        comun.ahora = real


@prueba
def cronista_biblioteca_de_fracasos_completa():
    from core.nucleo.fracasos_semilla import FRACASOS
    assert len(FRACASOS) >= 40
    for f in FRACASOS:
        for campo in ("nombre", "año", "campo", "que", "causa", "leccion", "claves", "busqueda"):
            assert f.get(campo), (f.get("nombre"), campo)
    assert len({f["nombre"] for f in FRACASOS}) == len(FRACASOS)


@prueba
def cronista_avisa_cuando_algo_se_parece_a_un_fracaso():
    a = cronista.advertir("voy a subir la actualización a todos los PC a la vez")
    assert a and "CrowdStrike" in a, a
    a = cronista.advertir("que Arché aprenda y se entrene con todo lo que le escriben los usuarios sin filtro")
    assert a and "Tay" in a, a
    a = cronista.advertir("las baterías de litio del perro se calientan al cargar")
    assert a and "Note 7" in a, a
    assert cronista.advertir("me gusta el color azul") is None


@prueba
def cronista_resumen_sin_internet_igual_trae_el_fracaso():
    from core import web
    p = Parche()
    p.poner(web, "hay_internet", lambda forzar=False: False)
    p.poner(comun, "pensar", lambda *a, **k: "")
    try:
        texto = cronista.resumen_matutino()
        assert "FRACASO DEL DÍA" in texto and "Lección" in texto and comun.nombre_usuario() in texto
        assert cronista._estado()["lecciones"]
    finally:
        p.quitar()


@prueba
def cronista_resumen_con_noticias():
    from core import web
    p = Parche()
    p.poner(web, "hay_internet", lambda forzar=False: True)
    p.poner(web, "noticias", lambda tema=None, n=5: [{"titulo": f"Titular {tema or 'general'} {i}", "fuente": "X",
                                                     "url": ""} for i in range(n)])
    p.poner(web, "buscar", lambda q, n=5: [])
    p.poner(comun, "pensar", lambda *a, **k: "")
    try:
        texto = cronista.resumen_matutino()
        assert "NOTICIAS GENERALES" in texto and "TECNOLOGÍA" in texto
        assert len(cronista._ultimas["items"]) >= 4
    finally:
        p.quitar()


@prueba
def cronista_comandos_de_hora():
    salida = []
    p = Parche()
    p.poner(comun, "msg", lambda t: salida.append(t))
    try:
        assert cronista.manejar("dame las noticias a las 6:30")
        assert ritmo._estado()["hora_fija"]["matutino"] == "06:30"
        assert cronista.manejar("Dame las noticias a las 7 de la mañana")
        assert ritmo._estado()["hora_fija"]["matutino"] == "07:00"
        assert cronista.manejar("noticias a tu ritmo")
        assert "matutino" not in ritmo._estado()["hora_fija"]
        assert cronista.manejar("agrega drones a mis noticias") and "drones" in cronista._estado()["temas"]
        assert not cronista.manejar("dame las noticias")       # esa la sigue atendiendo cerebro.py
    finally:
        p.quitar()


# ------------------------------------------------------------------
# Equipo
# ------------------------------------------------------------------

@prueba
def equipo_sube_de_nivel_solo_con_experiencia():
    p0 = Parche()
    p0.poner(comun, "informe", lambda *a, **k: None)
    try:
        texto = equipo.nombrar("investigador", "Nova")
        s = equipo._estado()["equipo"]["investigador"]
        assert s["nombre"] == "Nova" and equipo.nivel(s) == 0 and "Novato" in texto     # el nombre no da poder
        for _ in range(5):
            equipo._ganar_xp("investigador", 2)
        assert equipo.rango_de(equipo._estado()["equipo"]["investigador"]) == "Competente"
        assert equipo.niveles_del_equipo() >= 1
    finally:
        p0.quitar()
    salida = []
    p = Parche()
    p.poner(comun, "msg", lambda t: salida.append(t))
    try:
        assert equipo.manejar("ponle Max al programador")
        assert equipo._estado()["equipo"]["programador"]["nombre"] == "Max"
    finally:
        p.quitar()


@prueba
def equipo_extrae_archivos_de_la_respuesta():
    assert equipo._extraer_archivos('{"a.py": "print(1)", "b.py": "x=2"}') == {"a.py": "print(1)", "b.py": "x=2"}
    r = equipo._extraer_archivos("Aquí está:\n```python\n# archivo: calc.py\nprint(2)\n```")
    assert list(r) == ["calc.py"]


@prueba
def equipo_mision_completa_en_paralelo():
    from core import web
    p = Parche()
    p.poner(web, "hay_internet", lambda forzar=False: True)
    p.poner(web, "buscar", lambda q, n=5: [{"titulo": "Servo MG996R", "url": "https://x/1", "resumen": "torque 10kg"}])
    p.poner(web, "leer_pagina", lambda url, maximo=3000: "El MG996R tiene unos 10 kg·cm.")
    p.poner(comun, "informe", lambda *a, **k: None)

    def _pensar(prompt, **k):
        if "Parte la misión" in prompt:
            return json.dumps([{"rol": "investigador", "tarea": "torque de servos", "depende": []},
                               {"rol": "programador", "tarea": "calcula el torque", "depende": [0]},
                               {"rol": "probador", "tarea": "prueba", "depende": [1]},
                               {"rol": "cronista", "tarea": "informe", "depende": [0, 1, 2]}])
        if "Escribe el código" in prompt or "Revisa este código" in prompt:
            return "```python\n# archivo: main.py\nprint('torque', 10 * 2)\n```"
        if "informe final" in prompt:
            return "# Informe\nTodo bien."
        return "resumen"
    p.poner(comun, "pensar", _pensar)
    try:
        id_m, ruta = equipo.ejecutar_mision("calcular el torque de las patas del perro")
        assert ruta and os.path.exists(ruta), ruta
        with open(os.path.join(os.path.dirname(ruta), "detalle.json"), encoding="utf-8") as f:
            detalle = json.load(f)
        prob = next(r for r in detalle["resultados"] if r["rol"] == "probador")
        assert prob["ok"] and "torque 20" in prob["resultado"], prob
        assert equipo.misiones_completadas() >= 1
    finally:
        p.quitar()


# ------------------------------------------------------------------
# Depredador
# ------------------------------------------------------------------

def _repo(nombre, **extra):
    r = {"full_name": nombre, "html_url": f"https://github.com/{nombre}", "stargazers_count": 300, "size": 100,
         "license": {"spdx_id": "MIT"}, "pushed_at": datetime.now().strftime("%Y-%m-%dT00:00:00Z"),
         "default_branch": "main", "fork": False}
    r.update(extra)
    return r


@prueba
def depredador_filtra_presas():
    assert depredador.es_buena_presa(_repo("a/b"))[0]
    assert not depredador.es_buena_presa(_repo("a/b", license={"spdx_id": "GPL-3.0"}))[0]
    assert not depredador.es_buena_presa(_repo("a/b", stargazers_count=2))[0]
    assert not depredador.es_buena_presa(_repo("a/b", size=99999))[0]
    assert not depredador.es_buena_presa(_repo("a/b", pushed_at="2015-01-01T00:00:00Z"))[0]
    assert not depredador.es_buena_presa(_repo("a/b"), lista_negra=["a/b"])[0]


def _parches_caza(p, repos_zip, codigo_habilidad):
    from core import web
    p.poner(web, "hay_internet", lambda forzar=False: True)
    p.poner(depredador.time, "sleep", lambda s: None)
    informes = []
    p.poner(comun, "informe", lambda t, **k: informes.append(t))

    def _get(url, binario=False, **k):
        if "api.github.com/search" in url:
            return {"items": [_repo(n) for n in repos_zip]}
        for n, z in repos_zip.items():
            if n in url:
                return z
        raise ValueError("url inesperada")
    p.poner(depredador, "_get", _get)
    p.poner(comun, "pensar", lambda prompt, **k: codigo_habilidad if "Depredador" in prompt else '["temperature converter"]')
    aplicados = {}
    tmp = tempfile.mkdtemp()
    p.poner(evo, "ARCH_HABILIDADES", os.path.join(tmp, "hab.json"))
    p.poner(evo, "aplicar_cambio_autonomo", lambda c, m, prueba_extra=None: (aplicados.update(c), (True, "ok"))[1])
    return informes, aplicados


@prueba
def depredador_caza_una_habilidad_limpia():
    p = Parche()
    try:
        z = _zip({"conv-main/conv/temperatura.py": "def c_a_f(c):\n    return c * 9 / 5 + 32\n",
                  "conv-main/README.md": "Convierte temperaturas"})
        informes, aplicados = _parches_caza(p, {"bueno/conv": z}, HABILIDAD_BUENA)
        ok, que = depredador.cazar("convertir temperaturas", manual=True, avisar=lambda t: None)
        assert ok and que == "absorbida", que
        codigo = next(v for k, v in aplicados.items() if "presa_" in k)
        assert "Absorbida por el Depredador" in codigo and "licencia MIT" in codigo
        assert depredador.presas_absorbidas() >= 1
        assert not os.listdir(depredador.CARPETA_CUARENTENA)     # la cuarentena quedó vacía
    finally:
        p.quitar()


@prueba
def depredador_bloquea_presa_peligrosa():
    p = Parche()
    try:
        z = _zip({"malo-main/x.py": "import base64\nexec(base64.b64decode('cHJpbnQoMSk='))\n"})
        informes, aplicados = _parches_caza(p, {"malo/repo": z}, HABILIDAD_BUENA)
        ok, que = depredador.cazar("algo malo", manual=True, avisar=lambda t: None)
        assert not ok and not aplicados
        assert "malo/repo" in depredador._estado()["lista_negra"]
        assert any("PELIGROSO" in t for t in informes)
    finally:
        p.quitar()


@prueba
def depredador_pide_permiso_si_necesita_archivos():
    p = Parche()
    try:
        con_archivos = "# NECESITA: archivos\n" + HABILIDAD_BUENA.replace(
            "def ejecutar(texto):", "def ejecutar(texto):\n    if texto.endswith('.txt'):\n        return open(texto).read()")
        z = _zip({"pdf-main/lector.py": "def leer(r):\n    return open(r).read()\n"})
        informes, aplicados = _parches_caza(p, {"lector/pdf": z}, con_archivos)
        ok, que = depredador.cazar("leer archivos de texto", manual=True, avisar=lambda t: None)
        assert ok and "permiso" in que and not aplicados, que
        presa = next(x for x in depredador._estado()["presas"] if x.get("estado") == "pendiente_permiso")
        ok, _ = depredador.absorber_pendiente(presa["id"])
        assert ok and aplicados
    finally:
        p.quitar()


# ------------------------------------------------------------------
# Guardián
# ------------------------------------------------------------------

@prueba
def guardian_reconoce_impostores():
    assert guardian.es_impostor("svchost.exe", r"C:\Users\d\AppData\Local\Temp\svchost.exe")[0]
    assert not guardian.es_impostor("svchost.exe", r"C:\Windows\System32\svchost.exe")[0]
    assert guardian.es_impostor("scvhost.exe", r"C:\x\scvhost.exe")[0]
    assert not guardian.es_impostor("chrome.exe", r"C:\Program Files\Google\chrome.exe")[0]


@prueba
def guardian_aprende_y_luego_avisa_de_lo_nuevo_y_raro():
    e = {"conocidos": {}, "confiables": []}
    procs = [{"pid": 1, "nombre": "code.exe", "exe": r"C:\Program Files\Code\code.exe"}]
    assert guardian.evaluar_procesos(procs, e, aprendiendo_ahora=True) == []
    raro = [{"pid": 7, "nombre": "update.exe", "exe": r"C:\Users\d\Downloads\update.exe"}]
    h = guardian.evaluar_procesos(raro, e, aprendiendo_ahora=False)
    assert len(h) == 1 and h[0][3] == 7
    assert guardian.evaluar_procesos(raro, e, aprendiendo_ahora=False) == []       # ya conocido
    e2 = {"conocidos": {}, "confiables": ["update.exe"]}
    assert guardian.evaluar_procesos(raro, e2) == []
    assert guardian.comparar_inicio({"a": "1"}, {"a": "1", "b": "2"}) == [("b", "2")]


# ------------------------------------------------------------------
# Voz viva y avatar
# ------------------------------------------------------------------

@prueba
def voz_viva_ventana_y_filtros():
    v = voz_viva.VentanaConversacion(20)
    v.abrir(100)
    assert v.abierta(110) and not v.abierta(121)
    v.extender(115)
    assert v.abierta(130)
    v.cerrar()
    assert not v.abierta(116)
    assert voz_viva.es_ruido("gracias por ver el video")
    assert voz_viva.es_ruido("mmm")
    assert not voz_viva.es_ruido("abre chrome")
    assert not voz_viva.es_ruido("si")
    assert voz_viva.es_cierre("gracias, eso es todo")


@prueba
def voz_viva_huella_distingue_dos_voces():
    try:
        import numpy as np
    except ImportError:
        return
    rng = np.random.default_rng(1)

    def voz(f0, formantes, semilla):
        t = np.arange(16000 * 2) / 16000
        r = np.random.default_rng(semilla)
        s = sum(np.sin(2 * np.pi * f0 * k * t) / k * (1 + sum(np.exp(-((f0 * k - f) / 150) ** 2) * 4 for f in formantes))
                for k in range(1, 25))
        return (s * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)) + r.normal(0, 0.05, len(t))).astype(np.float32)
    a1, a2 = voz(115, [700, 1200, 2600], 1), voz(118, [700, 1200, 2600], 2)
    b = voz(230, [400, 2300, 3100], 3)
    h1, h2, hb = (voz_viva.huella_de(x) for x in (a1, a2, b))
    assert voz_viva.similitud(h1, h2) > voz_viva.similitud(h1, hb)
    u = voz_viva.umbral_desde_muestras([h1, h2, voz_viva.huella_de(voz(116, [700, 1200, 2600], 4))])
    assert voz_viva.similitud(h1, hb) < u <= voz_viva.similitud(h1, h2) + 0.08
    del rng


@prueba
def avatar_muestra_el_mismo_estado_que_la_interfaz():
    assert avatar.estado_actual("hablando", False, 0, 12) == "hablando"
    assert avatar.estado_actual("escuchando", False, 0, 12) == "escuchando"
    assert avatar.estado_actual("reposo", True, 0, 12) == "pensando"          # el equipo o el Depredador trabajan
    assert avatar.estado_actual("reposo", False, 45, 12) == "desconectado"    # llevas rato sin usar el PC
    assert avatar.estado_actual("reposo", False, 0, 3) == "desconectado"      # madrugada
    assert avatar.estado_actual("reposo", False, 0, 12) == "reposo"


@prueba
def avatar_usa_el_mismo_dibujo_de_app_js():
    with open(avatar.APP_JS, encoding="utf-8") as f:
        app = f.read()
    codigo, nombres = avatar.funciones_de_dibujo(app)
    assert {"dibujarOrbe", "esferaBase", "rgba", "hexRgb"} <= nombres, nombres
    assert avatar.extraer_funcion(app, "dibujarOrbe") in codigo           # copiado tal cual, sin cambios
    js = avatar.js_avatar()
    assert "function dibujarOrbe" in js and "/api/avatar" in js
    falso = "function a(x) { const s = '}{'; return b(x) + `${'{'}`; }\nfunction b(y) { /* } */ return y; }\nfunction c() {}"
    cod, usadas = avatar.funciones_de_dibujo(falso, "a")
    assert usadas == {"a", "b"} and "function c" not in cod


@prueba
def avatar_se_sirve_desde_la_interfaz_web_y_sigue_los_ajustes():
    import urllib.request
    from core.interfaz import web, ajustes
    archivo_real = ajustes._ARCHIVO
    p = Parche()
    p.poner(ajustes, "_ARCHIVO", os.path.join(_TMP, "config_interfaz.json"))
    p.poner(ajustes, "_datos", None)
    try:
        avatar.instalar_en_servidor()
        web.iniciar()
        base = f"http://127.0.0.1:{web._puerto}"

        def pedir(ruta, llave=True):
            req = urllib.request.Request(base + ruta, headers={"X-Llave": web._llave} if llave else {})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, b""
        assert pedir("/avatar", False)[0] == 200 and pedir("/avatar.js", False)[0] == 200
        assert pedir("/api/avatar", llave=False)[0] == 401
        ajustes.fijar("estilo_voz", "geometrica")
        d = json.loads(pedir("/api/avatar")[1])
        assert d["ajustes"]["estilo_voz"] == "geometrica" and "colores" in d["tema"]
        ajustes.fijar("estilo_voz", "anillos")                       # cambias la interfaz...
        assert json.loads(pedir("/api/avatar")[1])["ajustes"]["estilo_voz"] == "anillos"   # ...y el avatar también
        assert pedir("/api/estado")[0] == 200                         # la interfaz normal sigue igual
    finally:
        p.quitar()
        ajustes._datos = None
        assert ajustes._ARCHIVO == archivo_real


# ------------------------------------------------------------------
# Conjunto
# ------------------------------------------------------------------

@prueba
def nucleo_atiende_lo_suyo_y_deja_pasar_lo_demas():
    salida = []
    p = Parche()
    p.poner(comun, "msg", lambda t: salida.append(t))
    p.poner(comun, "en_hilo", lambda *a, **k: None)
    try:
        for frase in ("qué hay de nuevo", "estado del núcleo", "rangos", "presas", "tu equipo", "misiones",
                      "estado del guardián", "alertas del guardián", "tu ritmo", "lecciones", "fracaso del día",
                      "estado de la voz viva", "misión: investiga los mejores servos para un perro robot",
                      "piensa a fondo: ¿conviene MG996R o DS3218?", "caza leer códigos QR"):
            assert nucleo.manejar(frase), frase
        for frase in ("abre chrome", "dame las noticias", "hola", "tus habilidades", "qué hora es",
                      "crea una caja de 80x50x30", "en minecraft consigue madera"):
            assert not nucleo.manejar(frase), frase
    finally:
        p.quitar()


@prueba
def parche_de_main_se_aplica_una_vez_y_compila():
    import aplicar_parche_nucleo as parche
    with open("main.py", encoding="utf-8") as f:
        original = f.read()
    nuevo, cambio = parche.parchar(original)
    assert cambio
    for trozo in (parche.IMPORT, parche.ARRANQUE, "nucleo_arche.manejar(comando_original)", parche.DETENER):
        assert nuevo.count(trozo) == 1, trozo
    compile(nuevo, "main.py", "exec")
    assert nuevo.index("nucleo_arche.manejar") < nuevo.index("# VARIOS PASOS")
    assert nuevo.index("nucleo_arche.manejar") > nuevo.index("multitarea_arche.manejar(comando_original)")
    assert parche.parchar(nuevo) == (nuevo, False)
    crlf, cambio = parche.parchar(original.replace("\n", "\r\n"))
    assert cambio and "\r\n        nucleo_arche.registrar_actividad" in crlf


def main():
    bien = 0
    for fn in PRUEBAS:
        try:
            fn()
            print(f"  BIEN {fn.__name__}")
            bien += 1
        except Exception:
            print(f"  MAL  {fn.__name__}")
            traceback.print_exc(limit=4)
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{bien}/{len(PRUEBAS)} pruebas pasaron")
    return 0 if bien == len(PRUEBAS) else 1


if __name__ == "__main__":
    sys.exit(main())
