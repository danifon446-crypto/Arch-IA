"""
revisar_fallos.py
-----------------
Los ejemplos que MÁS mejoran a las redes son las frases que TÚ dijiste y
Arché entendió mal o dudó. Este módulo junta esas frases en una lista
(para_revisar.jsonl) para que las confirmes o corrijas en un minuto.

Entran a la lista:
  - frases donde el vecino más cercano y la red no estaban de acuerdo
    (aprendizaje._resolver_semantico), y
  - frases que resolvió la nube u Ollama y se aprendieron SOLAS
    (enrutador_natural.enrutar): si la nube se equivocó, Arché aprendió
    algo mal sin que nadie lo revisara. Acá lo puedes corregir.

Uso (desde la carpeta Arche):
    python -m core.IA.revisar_fallos

Por cada frase:
    1, 2, ...   enseñarla con esa intención
    <nombre>    enseñarla con otra intención (ej. crear_nota)
    c           es charla / pregunta general (conversar)
    b           está bien así / no importa: sacarla de la lista
    Enter       saltar (queda para la próxima)
    q           salir

Al terminar, si corregiste algo, reentrena las redes una sola vez.
"""

import json
import os
import threading
import time

BASE = os.path.dirname(__file__)
ARCHIVO = os.path.join(BASE, "para_revisar.jsonl")
MAXIMO = 300  # no dejar crecer la lista sin fin

_lock = threading.Lock()


def _leer():
    if not os.path.exists(ARCHIVO):
        return []
    items = []
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea:
                    try:
                        items.append(json.loads(linea))
                    except ValueError:
                        pass
    except OSError:
        pass
    return items


def _escribir(items):
    tmp = ARCHIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for it in items[-MAXIMO:]:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(tmp, ARCHIVO)


def anotar(frase, motivo, opciones=None, detalle=None):
    """Agrega (o actualiza) una frase en la lista. Nunca lanza excepción."""
    try:
        frase = (frase or "").strip()
        if not frase:
            return
        opciones = [o for o in (opciones or []) if o]
        with _lock:
            items = _leer()
            for it in items:
                if it.get("frase") == frase:
                    it["veces"] = it.get("veces", 1) + 1
                    it["motivo"] = motivo
                    it["opciones"] = list(dict.fromkeys(opciones + it.get("opciones", [])))
                    break
            else:
                items.append({"frase": frase, "motivo": motivo, "opciones": opciones,
                              "detalle": detalle or {}, "veces": 1, "fecha": time.time()})
            _escribir(items)
    except Exception:
        pass


def pendientes():
    return len(_leer())


def revisar():
    from core.IA import catalogo
    from core.IA.ensenar import ensenar

    items = _leer()
    if not items:
        print("Arché: No hay frases para revisar. ¡Bien!")
        return

    # primero las que más se repiten
    items.sort(key=lambda it: -it.get("veces", 1))
    quedan, corregidas = [], 0
    print(f"Arché: {len(items)} frase(s) para revisar. (q = salir)\n")

    # como en 'importar ejemplos': no reentrenar a cada rato, solo al final
    from core.IA import aprendizaje
    umbral_original = aprendizaje.UMBRAL_REENTRENO
    aprendizaje.UMBRAL_REENTRENO = float("inf")
    try:
        _recorrer(items, quedan, catalogo, ensenar)
    finally:
        aprendizaje.UMBRAL_REENTRENO = umbral_original
    corregidas = sum(1 for it in items if it.get("_ok"))

    with _lock:
        # conservar lo que se anotó mientras revisabas
        revisadas = {it["frase"] for it in items}
        nuevas = [it for it in _leer() if it.get("frase") not in revisadas]
        _escribir([{k: v for k, v in it.items() if k != "_ok"} for it in quedan] + nuevas)

    print(f"\nArché: Corregiste/confirmaste {corregidas} frase(s). Quedan {len(quedan) + len(nuevas)}.")
    if corregidas:
        print("Arché: Reentreno las redes una sola vez...")
        aprendizaje.reentrenar_ahora()


def _recorrer(items, quedan, catalogo, ensenar):
    for n, it in enumerate(items):
        print(f"[{n + 1}/{len(items)}] «{it['frase']}»   ({it.get('motivo', '')}, {it.get('veces', 1)} vez/veces)")
        opciones = it.get("opciones", [])
        for i, op in enumerate(opciones, start=1):
            desc = catalogo.POR_ID.get(op, {}).get("descripcion", "")
            print(f"    {i}) {op}  - {desc}")
        resp = input("    ¿Qué intención es? > ").strip()

        if resp.lower() == "q":
            quedan.extend(items[n:])
            break
        if resp == "":
            quedan.append(it)
            continue
        if resp.lower() == "b":
            continue
        if resp.lower() == "c":
            intencion = "conversar"
        elif resp.isdigit() and 1 <= int(resp) <= len(opciones):
            intencion = opciones[int(resp) - 1]
        else:
            intencion = resp

        ok, mensaje = ensenar(it["frase"], intencion, "")
        print(f"    {mensaje}")
        if ok:
            it["_ok"] = True
        else:
            quedan.append(it)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    revisar()
