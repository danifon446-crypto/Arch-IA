"""
tiempo.py
---------
decir_hora() y decir_fecha() -- usadas por main.py para intencion
"hora" y "fecha" ("qué hora es", "qué día es hoy"). No existían en
ningún lado del proyecto; llamarlas crasheaba con NameError apenas
el clasificador reconocía esas intenciones.
"""

from datetime import datetime

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

DIAS = [
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
]


def decir_hora():
    ahora = datetime.now()
    print(f"Arché: Son las {ahora.strftime('%H:%M')}.")


def decir_fecha():
    hoy = datetime.now()
    dia_semana = DIAS[hoy.weekday()]
    mes = MESES[hoy.month - 1]
    print(f"Arché: Hoy es {dia_semana} {hoy.day} de {mes} de {hoy.year}.")
