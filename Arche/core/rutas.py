import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE = os.path.join(BASE, "Database")

os.makedirs(DATABASE, exist_ok=True)