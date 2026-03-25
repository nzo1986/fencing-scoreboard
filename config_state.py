import os, json, copy, random, re, socket, subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.join(BASE_DIR, 'static', 'photos')
STATE_FILE = os.path.join(BASE_DIR, "local_match_state.json")
OLD_STATE_FILE = os.path.join(BASE_DIR, "match_state.json")
DEFAULT_SHEET_ID = "179tfN2PDrSTYtiAdVeFQKXF9OtwZj4k4EbQ1dWXH5Yg"

GIRONI_MAP_WRITE = { 'rosso': [2, 3], 'giallo': [7, 8], 'blu': [12, 13], 'verde': [17, 18], '32': [22, 23] }
GIRONI_MAP_READ = { 'rosso': [0, 1, 2, 3], 'giallo': [5, 6, 7, 8], 'blu': [10, 11, 12, 13], 'verde': [15, 16, 17, 18], '32': [20, 21, 22, 23] }

gironi_cache = {'rosso': [], 'giallo': [], 'blu': [], 'verde': [], '32': []}
history_stack = []
pico_last_seen = {'rosso': {'time': 0, 'bat': 100}, 'verde': {'time': 0, 'bat': 100}}

def get_local_ip():
    try: 
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(('10.255.255.255',1))
        IP=s.getsockname()[0]
        s.close()
    except: IP='127.0.0.1'
    return IP

def get_current_ssid():
    try: return subprocess.check_output("iwgetid -r", shell=True).decode().strip() or "Nessuna Rete"
    except: return "Offline"

def clean_fencer_name(raw_name): return " ".join(re.sub(r'[^a-zA-Z0-9 ]', '', raw_name).split()) if raw_name else ""

def get_photo_url(name):
    if not name: return "/static/photos/default.png"
    clean = clean_fencer_name(name)
    for ext in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{name.strip()}.{ext}")): return f"/static/photos/{name.strip()}.{ext}?v={random.randint(1,1000)}"
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{clean}.{ext}")): return f"/static/photos/{clean}.{ext}?v={random.randint(1,1000)}"
    return "/static/photos/default.png"

def new_fencer(name):
    return { "name": clean_fencer_name(name), "score": 0, "cards": {"Y": False, "R": False, "B": False, "R_count": 0}, "p_cards": {"Y": False, "R": False, "B": False}, "photo": get_photo_url(name) }

def get_system_fonts():
    try:
        output = subprocess.check_output(['fc-list', ':', 'family'], encoding='utf-8')
        fonts = set(f.strip() for line in output.splitlines() for f in line.split(',') if f.strip())
        return sorted(list(fonts))
    except: return ['Roboto Mono', 'Arial', 'Verdana']

def letter_to_index(letter): return ord(letter.upper()) - 65 if letter else 0
def letter_to_sheet_col(letter): return ord(letter.upper()) - 64 if letter else 1

default_columns = {'rosso': {'sx': 'A', 'psx': 'B', 'pdx': 'C', 'dx': 'D'}, 'giallo': {'sx': 'F', 'psx': 'G', 'pdx': 'H', 'dx': 'I'}, 'blu': {'sx': 'K', 'psx': 'L', 'pdx': 'M', 'dx': 'N'}, 'verde': {'sx': 'P', 'psx': 'Q', 'pdx': 'R', 'dx': 'S'}, '32': {'sx': 'U', 'psx': 'V', 'pdx': 'W', 'dx': 'X'} }
default_settings = {"weapon": "spada", "font_family": "Roboto Mono", "font_timer": 8.0, "font_score": 15.0, "font_name": 3.0, "font_list": 1.5, "col_center_width": 1.2, "list_padding": 0.5, "text_border": 0.0, "photo_size": 150, "time_match": 180, "time_break": 60, "time_medical": 300, "refresh_rate": 30, "buzzer_volume": 1.0, "default_name_left": "ATLETA SX", "default_name_right": "ATLETA DX", "google_script_url": "", "google_sheet_id": DEFAULT_SHEET_ID, "columns": copy.deepcopy(default_columns)}

default_state = {
    "timer": 180.0, "running": False, "phase": "MATCH", "priority": None, 
    "fencer_left": new_fencer(default_settings["default_name_left"]), "fencer_right": new_fencer(default_settings["default_name_right"]), 
    "period": 1, "admin_connected": False, "server_ip": get_local_ip(), "ssid": get_current_ssid(), "match_list": [], 
    "current_girone": "rosso", "active_girone": "rosso", "current_row_idx": None, "manual_selection": False, 
    "swapped": False, "settings": copy.deepcopy(default_settings), "wifi_connected": False
}
current_state = copy.deepcopy(default_state)

def save_state():
    try:
        with open(STATE_FILE, 'w') as f: json.dump(current_state, f)
    except: pass

def load_state():
    global current_state
    file_to_load = STATE_FILE if os.path.exists(STATE_FILE) else OLD_STATE_FILE if os.path.exists(OLD_STATE_FILE) else None
    if file_to_load:
        try:
            with open(file_to_load, 'r') as f:
                data = json.load(f)
                if 'settings' in data: current_state['settings'].update(data['settings'])
                for side in ['fencer_left', 'fencer_right']:
                    if side in data:
                        if 'cards' in data[side]: current_state[side]['cards'].update(data[side]['cards'])
                        if 'p_cards' in data[side]: current_state[side]['p_cards'].update(data[side]['p_cards'])
                        for k, v in data[side].items():
                            if k not in ['cards', 'p_cards']: current_state[side][k] = v
                        current_state[side]['photo'] = get_photo_url(current_state[side].get('name', ''))
                for k, v in data.items():
                    if k not in ['settings', 'fencer_left', 'fencer_right']: current_state[k] = v
                current_state['running'] = False
                current_state['server_ip'] = get_local_ip()
                current_state['ssid'] = get_current_ssid()
                current_state['wifi_connected'] = current_state['server_ip'] != '127.0.0.1'
            if file_to_load == OLD_STATE_FILE: save_state()
        except: pass

def push_history():
    global history_stack
    history_stack.append(copy.deepcopy(current_state))
    if len(history_stack) > 20: history_stack.pop(0)