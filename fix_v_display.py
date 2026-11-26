import os, re, shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def read_file(rel_path):
    full_path = os.path.join(BASE_DIR, *rel_path.split("/"))
    shutil.copy2(full_path, full_path + ".bak3")
    with open(full_path, "r", encoding="utf-8") as f:
        return full_path, f.read()

def write_file(full_path, content):
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Aggiornato: {full_path}")

# ---------------------------------------------------------
# 1. AGGIORNA google_api.py (legge display3gir via Apps Script per preservare "V2")
# ---------------------------------------------------------
path, code = read_file("google_api.py")

old_fetch_block = '''        r = requests.get(
            f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=display3gir&t={int(time.time())}",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        r.encoding = 'utf-8'
        lines = r.text.strip().split('\\n')

        new_cache = {k: [] for k in GIRONI_MAP_READ.keys()}
        cols_map = current_state['settings'].get('columns', default_columns)
        
        for i, line in enumerate(lines[1:]): 
            row_idx = i + 2
            parsed_line = list(csv.reader([line]))
            if not parsed_line:
                continue
            p = parsed_line[0]'''

new_fetch_block = '''        rows_data = None
        script_url = current_state['settings'].get('google_script_url', '').strip()
        if script_url:
            try:
                sep = '&' if '?' in script_url else '?'
                r_js = requests.get(
                    f"{script_url}{sep}azione=leggi_tabellone&sheetName=display3gir&t={int(time.time())}",
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=8
                )
                if r_js.status_code == 200:
                    parsed_json = r_js.json()
                    if isinstance(parsed_json, list) and len(parsed_json) > 1:
                        rows_data = parsed_json
            except Exception:
                rows_data = None

        if rows_data is None:
            r = requests.get(
                f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=display3gir&t={int(time.time())}",
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=8
            )
            r.encoding = 'utf-8'
            lines = r.text.strip().split('\\n')
            rows_data = []
            for line in lines:
                parsed_line = list(csv.reader([line]))
                rows_data.append(parsed_line[0] if parsed_line else [])

        new_cache = {k: [] for k in GIRONI_MAP_READ.keys()}
        cols_map = current_state['settings'].get('columns', default_columns)
        
        for i, p in enumerate(rows_data[1:]): 
            row_idx = i + 2
            if not p:
                continue'''

if old_fetch_block in code:
    code = code.replace(old_fetch_block, new_fetch_block, 1)
    write_file(path, code)
else:
    print("[INFO] google_api.py già aggiornato.")

# ---------------------------------------------------------
# 2. AGGIORNA templates/pannello_unificato.html (no a capo su nomi/cognomi + refresh sincronizzato)
# ---------------------------------------------------------
path, code = read_file("templates/pannello_unificato.html")

# A. Nomi e cognomi sempre su una sola riga nella tabella girone e nella lista assalti
code = code.replace('<th class="text-left">ATLETA</th>', '<th class="text-left whitespace-nowrap">ATLETA</th>')
code = code.replace('<th class="text-center w-20">CAT/SOC</th>', '<th class="text-center whitespace-nowrap px-3">CAT/SOC</th>')
code = code.replace(
    '<td class="font-bold text-neutral-900">${f.active ? f.nome : \'<span class="text-neutral-400">-</span>\'}</td>',
    '<td class="font-bold text-neutral-900 whitespace-nowrap">${f.active ? f.nome : \'<span class="text-neutral-400">-</span>\'}</td>'
)
code = code.replace(
    '<td class="text-center text-neutral-600">${f.cognome}</td>',
    '<td class="text-center text-neutral-600 whitespace-nowrap px-3">${f.cognome}</td>'
)

# B. Nomi atleti nella colonna assalti a destra senza troncamento né a capo + colonna più larga
code = code.replace(
    '<div class="flex-1 text-right text-xs font-extrabold text-neutral-800 truncate" title="${b.sx}">${b.sx}</div>',
    '<div class="flex-1 text-right text-xs font-extrabold text-neutral-800 whitespace-nowrap" title="${b.sx}">${b.sx}</div>'
)
code = code.replace(
    '<div class="flex-1 text-left text-xs font-extrabold text-neutral-800 truncate" title="${b.dx}">${b.dx}</div>',
    '<div class="flex-1 text-left text-xs font-extrabold text-neutral-800 whitespace-nowrap" title="${b.dx}">${b.dx}</div>'
)
code = code.replace('w-[430px]', 'w-[520px]')

# C. Quando si clicca "Aggiorna" nel tabellone, sincronizza anche gli assalti dal server
old_manual_refresh = '''        function manualRefreshTabellone() {
            forceResumeTabelloneRefresh();
            loadTabelloneData(true);
        }'''
new_manual_refresh = '''        function manualRefreshTabellone() {
            forceResumeTabelloneRefresh();
            socket.emit('fetch_sheet');
            loadTabelloneData(true);
        }'''
if old_manual_refresh in code:
    code = code.replace(old_manual_refresh, new_manual_refresh, 1)

# D. Forza maiuscolo nei campi punteggio rapido
code = code.replace('value="${m.p_sx}"', 'value="${String(m.p_sx ?? \'\').toUpperCase()}"')
code = code.replace('value="${m.p_dx}"', 'value="${String(m.p_dx ?? \'\').toUpperCase()}"')

write_file(path, code)
print("\n[OK] TUTTO AGGIORNATO CORRETTAMENTE!")
