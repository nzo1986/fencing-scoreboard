import os, shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
full_path = os.path.join(BASE_DIR, "google_api.py")
shutil.copy2(full_path, full_path + ".bak4")

with open(full_path, "r", encoding="utf-8") as f:
    code = f.read()

old_loop = "for i, p in enumerate(rows_data[1:]):"
new_loop = "for i, p in enumerate(rows_data[1:37]):  # Si ferma esattamente alla riga 37"

assert old_loop in code, "Riga di ciclo non trovata in google_api.py"
code = code.replace(old_loop, new_loop, 1)

with open(full_path, "w", encoding="utf-8") as f:
    f.write(code)

print("[OK] google_api.py aggiornato: lettura fermata alla riga 37!")
