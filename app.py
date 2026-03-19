import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit
import json
import os
import socket
import requests
import csv
import random
import copy
import subprocess
import glob
from werkzeug.utils import secure_filename
import time
import re
import zipfile
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = 'scherma_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- PERCORSI E FILE ASSOLUTI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.join(BASE_DIR, 'static', 'photos')
STATE_FILE = os.path.join(BASE_DIR, "local_match_state.json")
OLD_STATE_FILE = os.path.join(BASE_DIR, "match_state.json")

DEFAULT_SHEET_ID = "179tfN2PDrSTYtiAdVeFQKXF9OtwZj4k4EbQ1dWXH5Yg"

GIRONI_MAP_WRITE = { 'rosso': [2, 3], 'giallo': [7, 8], 'blu': [12, 13], 'verde': [17, 18], '32': [22, 23] }
GIRONI_MAP_READ = { 'rosso': [0, 1, 2, 3], 'giallo': [5, 6, 7, 8], 'blu': [10, 11, 12, 13], 'verde': [15, 16, 17, 18], '32': [20, 21, 22, 23] }

gironi_cache = {'rosso': [], 'giallo': [], 'blu': [], 'verde': [], '32': []}
history_stack = []

# --- VARIABILI HARDWARE ---
pico_last_seen = {'rosso': {'time': 0, 'bat': 100}, 'verde': {'time': 0, 'bat': 100}}
last_hit_time = 0
last_massa_time = {'left': 0, 'right': 0}
hit_sides_in_window = set()

# --- HELPERS ---
def letter_to_index(letter): return ord(letter.upper()) - 65 if letter else 0
def letter_to_sheet_col(letter): return ord(letter.upper()) - 64 if letter else 1
def clean_fencer_name(raw_name): return " ".join(re.sub(r'[^a-zA-Z0-9 ]', '', raw_name).split()) if raw_name else ""

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

def get_photo_url(name):
    if not name: return "/static/photos/default.png"
    for ext in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{name.strip()}.{ext}")): 
            return f"/static/photos/{name.strip()}.{ext}?v={random.randint(1,1000)}"
    clean = clean_fencer_name(name)
    for ext in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{clean}.{ext}")): 
            return f"/static/photos/{clean}.{ext}?v={random.randint(1,1000)}"
    return "/static/photos/default.png"

def new_fencer(name):
    return { "name": clean_fencer_name(name), "score": 0, "cards": {"Y": False, "R": False, "B": False, "R_count": 0}, "p_cards": {"Y": False, "R": False, "B": False}, "photo": get_photo_url(name) }

def get_system_fonts():
    try:
        output = subprocess.check_output(['fc-list', ':', 'family'], encoding='utf-8')
        fonts = set(f.strip() for line in output.splitlines() for f in line.split(',') if f.strip())
        return sorted(list(fonts))
    except: return ['Roboto Mono', 'Arial', 'Verdana']

default_columns = {'rosso': {'sx': 'A', 'psx': 'B', 'pdx': 'C', 'dx': 'D'}, 'giallo': {'sx': 'F', 'psx': 'G', 'pdx': 'H', 'dx': 'I'}, 'blu': {'sx': 'K', 'psx': 'L', 'pdx': 'M', 'dx': 'N'}, 'verde': {'sx': 'P', 'psx': 'Q', 'pdx': 'R', 'dx': 'S'}, '32': {'sx': 'U', 'psx': 'V', 'pdx': 'W', 'dx': 'X'} }
default_settings = {"weapon": "spada", "font_family": "Roboto Mono", "font_timer": 8.0, "font_score": 15.0, "font_name": 3.0, "font_list": 1.5, "col_center_width": 1.2, "list_padding": 0.5, "text_border": 0.0, "photo_size": 150, "time_match": 180, "time_break": 60, "time_medical": 300, "refresh_rate": 30, "buzzer_volume": 1.0, "default_name_left": "ATLETA SX", "default_name_right": "ATLETA DX", "google_script_url": "", "google_sheet_id": DEFAULT_SHEET_ID, "columns": default_columns}

default_state = {
    "timer": 180.0, "running": False, "phase": "MATCH", "priority": None, 
    "fencer_left": new_fencer(default_settings["default_name_left"]), 
    "fencer_right": new_fencer(default_settings["default_name_right"]), 
    "period": 1, "admin_connected": False, "server_ip": get_local_ip(), 
    "ssid": get_current_ssid(), "match_list": [], "current_girone": "rosso", 
    "active_girone": "rosso", "current_row_idx": None, "manual_selection": False, 
    "swapped": False, "settings": default_settings.copy(), "wifi_connected": False
}

current_state = default_state.copy()

def save_state():
    try:
        with open(STATE_FILE, 'w') as f: json.dump(current_state, f)
    except: pass

def async_save(): 
    save_state()

def load_state():
    """Ricarica stabile alla versione precedente per non perdere dati"""
    global current_state
    file_to_load = STATE_FILE if os.path.exists(STATE_FILE) else OLD_STATE_FILE if os.path.exists(OLD_STATE_FILE) else None
    if file_to_load:
        try:
            with open(file_to_load, 'r') as f:
                data = json.load(f)
                data.update({'running': False, 'server_ip': get_local_ip(), 'ssid': get_current_ssid(), 'wifi_connected': get_local_ip() != '127.0.0.1'})
                saved_s = data.get('settings', {})
                data['settings'] = default_settings.copy()
                data['settings'].update(saved_s)
                if 'fencer_left' in data: data['fencer_left']['photo'] = get_photo_url(data['fencer_left']['name'])
                if 'fencer_right' in data: data['fencer_right']['photo'] = get_photo_url(data['fencer_right']['name'])
                current_state = data
            if file_to_load == OLD_STATE_FILE: save_state()
        except: pass

def push_history():
    global history_stack
    history_stack.append(copy.deepcopy(current_state))
    if len(history_stack) > 20: history_stack.pop(0)

# --- LOGICA ARMI E PUNTEGGI (CON FIE LOCKOUT E COCCIA) ---
def process_massa(side):
    global last_massa_time
    now = time.time()
    # Emette il suono e la luce bianca, MAI il punto. Debounce di 0.5s
    if now - last_massa_time[side] > 0.5:
        socketio.emit('hw_massa', {'side': side})
        last_massa_time[side] = now

def process_hw_hit(side):
    global last_hit_time, hit_sides_in_window
    now = time.time()
    
    if current_state.get('phase') != 'MATCH': return

    # 1. TEMPO FERMO: Suona e Illumina, ma NESSUN PUNTO
    if not current_state['running']:
        if now - last_hit_time > 0.5:
            socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': False})
            last_hit_time = now
        return

    # 2. TEMPO AVVIATO: Calcolo dell'Arma
    weapon = current_state['settings'].get('weapon', 'spada')
    lockout_ms = 0.045 # Spada (45 millisecondi)
    if weapon == 'fioretto': lockout_ms = 0.300 # Fioretto (300 millisecondi)
    elif weapon == 'sciabola': lockout_ms = 0.170 # Sciabola (170 millisecondi)

    # Prima Stoccata
    if current_state['running']:
        current_state['running'] = False
        last_hit_time = now
        hit_sides_in_window = {side}
        current_state[f'fencer_{side}']['score'] += 1
        
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)
        
    # Colpo Doppio (entro la tolleranza dell'arma)
    elif side not in hit_sides_in_window and (now - last_hit_time <= lockout_ms):
        hit_sides_in_window.add(side)
        current_state[f'fencer_{side}']['score'] += 1
        
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)

# --- ROUTES PAGINE ---
@app.route('/')
def index(): return render_template('index.html')
@app.route('/telecomando')
def telecomando(): return render_template('telecomando.html')
@app.route('/settings')
def settings(): return render_template('settings.html')
@app.route('/riferimenti')
def riferimenti(): return render_template('riferimenti.html')
@app.route('/wifi')
def wifi_page(): return render_template('wifi.html')
@app.route('/foto')
def foto_page(): return render_template('foto.html')
@app.route('/download')
def download_page(): return render_template('download.html')

# --- API REST ---
@app.route('/api/pico_status')
def get_pico_status():
    now = time.time()
    return jsonify({
        'rosso': {'active': (now - pico_last_seen['rosso']['time']) < 5, 'bat': pico_last_seen['rosso']['bat']},
        'verde': {'active': (now - pico_last_seen['verde']['time']) < 5, 'bat': pico_last_seen['verde']['bat']}
    })

@app.route('/api/scan_wifi')
def api_scan(): return jsonify(scan_wifi_networks())
@app.route('/api/saved_wifi')
def api_saved(): return jsonify(get_saved_networks())
@app.route('/api/connect_wifi', methods=['POST'])
def api_connect():
    data = request.json
    success = connect_to_wifi(data['ssid'], data['password'])
    if success:
        eventlet.sleep(3)
        current_state['server_ip'] = get_local_ip()
        current_state['ssid'] = get_current_ssid()
        current_state['wifi_connected'] = True
        return jsonify({"status": "success", "ip": current_state['server_ip']})
    else: return jsonify({"status": "error"}), 400

@app.route('/api/delete_wifi', methods=['POST'])
def api_delete_wifi():
    data = request.json
    success = delete_wifi(data['ssid'])
    return jsonify({"status": "success" if success else "error"})

@app.route('/api/upload_photo', methods=['POST'])
def upload_photo():
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    name = request.form.get('name')
    clean_name_file = clean_fencer_name(name)
    is_default = request.form.get('is_default') == 'true'
    if file.filename == '': return jsonify({"error": "No filename"}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    if ext not in ['jpg', 'jpeg', 'png']: return jsonify({"error": "Invalid type"}), 400
    
    if is_default:
        filename = "default.png"
        for e in ['jpg', 'png', 'jpeg']:
            p = os.path.join(PHOTOS_DIR, f"default.{e}")
            if os.path.exists(p): os.remove(p)
    else:
        for e in ['jpg', 'png', 'jpeg']:
            p = os.path.join(PHOTOS_DIR, f"{clean_name_file}.{e}")
            if os.path.exists(p): os.remove(p)
        filename = f"{clean_name_file}.{ext}"
    
    file.save(os.path.join(PHOTOS_DIR, filename))
    if not is_default:
        l = clean_fencer_name(current_state['fencer_left']['name'])
        r = clean_fencer_name(current_state['fencer_right']['name'])
        if l == clean_name_file: current_state['fencer_left']['photo'] = get_photo_url(clean_name_file)
        if r == clean_name_file: current_state['fencer_right']['photo'] = get_photo_url(clean_name_file)
        socketio.emit('state_update', current_state)
    return jsonify({"success": True})

@app.route('/api/get_athletes')
def get_athletes():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        sid = current_state['settings'].get('google_sheet_id', DEFAULT_SHEET_ID)
        url = f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=Rank"
        r = requests.get(url, headers=headers)
        r.encoding = 'utf-8'
        lines = r.text.strip().split('\n')
        atleti = []
        reader = csv.reader(lines)
        rows = list(reader)
        for i, row in enumerate(rows):
            if i >= 2:
                if len(row) > 4:
                    val = row[4].strip()
                    if val: atleti.append(clean_fencer_name(val))
        result = []
        for a in atleti:
            if not a: continue
            url = get_photo_url(a) 
            has_photo = "/static/photos/default.png" not in url
            result.append({"name": a, "has_photo": has_photo, "photo_url": url})
        return jsonify(result)
    except: return jsonify([])

@app.route('/api/maxi_upload', methods=['POST'])
def maxi_upload():
    if 'files[]' not in request.files: return jsonify({"error": "No files"}), 400
    files = request.files.getlist('files[]')
    try:
        r = requests.get("http://localhost:5000/api/get_athletes")
        valid_athletes = [x['name'] for x in r.json()]
    except: valid_athletes = []
    count = 0
    for file in files:
        if file.filename:
            raw_name = os.path.splitext(file.filename)[0]
            clean_name_file = clean_fencer_name(raw_name).lower()
            match = None
            for ath in valid_athletes:
                if ath.lower() == clean_name_file:
                    match = ath
                    break
            if match:
                ext = file.filename.rsplit('.', 1)[1].lower()
                for e in ['jpg', 'png', 'jpeg']:
                    p = os.path.join(PHOTOS_DIR, f"{match}.{e}")
                    if os.path.exists(p): os.remove(p)
                file.save(os.path.join(PHOTOS_DIR, f"{match}.{ext}"))
                count += 1
    return jsonify({"processed": count})

@app.route('/api/download_photos')
def download_photos():
    try:
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(PHOTOS_DIR):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        filepath = os.path.join(root, file)
                        zf.write(filepath, arcname=file)
        memory_file.seek(0)
        return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name='foto_atleti.zip')
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/get_fonts')
def api_get_fonts(): return jsonify(get_system_fonts())


# --- SOCKET WEBSOCKET HANDLERS ---
@socketio.on('connect')
def handle_connect(): 
    current_state['server_ip'] = get_local_ip()
    current_state['ssid'] = get_current_ssid()
    current_state['wifi_connected'] = current_state['server_ip'] != '127.0.0.1'
    emit('status_check', {'internet': check_internet(), 'google': check_google()})
    emit('wifi_info', {'ssid': current_state['ssid'], 'ip': current_state['server_ip']})
    emit('state_update', current_state)
    emit('gironi_cache_update', gironi_cache)

@socketio.on('undo')
def undo():
    global current_state
    if history_stack:
        prev = history_stack.pop()
        for k in ['timer','fencer_left','fencer_right','priority','phase','match_list','current_row_idx','current_girone','manual_selection','swapped']:
            current_state[k] = prev.get(k, current_state[k])
        current_state['running'] = False
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)

@socketio.on('update_score')
def handle_score(d):
    push_history()
    side = d['side']
    current_state[f'fencer_{side}']['score'] = max(0, current_state[f'fencer_{side}']['score'] + d['delta'])
    current_state['running'] = False
    
    if d['delta'] > 0: 
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': True})
        
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)
    
@socketio.on('toggle_timer')
def handle_toggle():
    current_state['running'] = not current_state['running']
    socketio.emit('state_update', current_state)
    eventlet.spawn(async_save)

@socketio.on('adjust_time')
def handle_adjust_time(data):
    push_history()
    current_state['timer'] = max(0, current_state['timer'] + float(data.get('delta',0)))
    current_state['running'] = False 
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

@socketio.on('card_action')
def handle_card(d):
    push_history()
    side = d['side']
    card_type = d['card']
    fencer = current_state[f'fencer_{side}']
    opp_side = 'right' if side == 'left' else 'left'
    opponent = current_state[f'fencer_{opp_side}']
    
    current_state['running'] = False

    if card_type.startswith('P_'):
        k = card_type.split('_')[1]
        fencer['p_cards'][k] = not fencer['p_cards'][k]
    else:
        has_yellow = fencer['cards']['Y']
        red_count = fencer['cards'].get('R_count', 0)
        has_black = fencer['cards']['B']

        if card_type == 'B': fencer['cards']['B'] = True
        elif card_type in ['Y', 'R']:
            if has_black: pass
            else:
                if not has_yellow and red_count == 0:
                    if card_type == 'Y': fencer['cards']['Y'] = True
                    elif card_type == 'R':
                        red_count = 1
                        opponent['score'] += 1
                else:
                    if red_count < 2: red_count += 1
                    opponent['score'] += 1
            fencer['cards']['R_count'] = red_count
            fencer['cards']['R'] = (red_count > 0)

    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

@socketio.on('double_hit')
def db_hit():
    push_history()
    current_state['fencer_left']['score'] += 1
    current_state['fencer_right']['score'] += 1
    current_state['running'] = False 
    
    socketio.emit('hw_hit', {'side': 'double', 'is_double': True, 'score_added': True, 'is_manual': True})
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

@socketio.on('toggle_priority')
def toggle_prio():
    push_history()
    if current_state['priority']: current_state['priority'] = None
    else: 
        current_state['priority'] = 'animating'
        eventlet.spawn(resolve_priority_animation)
    socketio.emit('state_update', current_state)
    eventlet.spawn(async_save)

@socketio.on('reset_all')
def r_all():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    current_state['priority'] = None
    current_state['manual_selection'] = False 
    current_state['swapped'] = False 
    for s in ['left','right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
    current_state['fencer_left']['name'] = current_state['settings']['default_name_left']
    current_state['fencer_right']['name'] = current_state['settings']['default_name_right']
    current_state['fencer_left']['photo'] = get_photo_url(None)
    current_state['fencer_right']['photo'] = get_photo_url(None)
    current_state['current_row_idx'] = None
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)
    eventlet.spawn(update_all_gironi_data)

@socketio.on('reset_scores')
def r_scores():
    push_history()
    current_state['running'] = False
    for s in ['left','right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)
    
@socketio.on('reset_timer')
def r_timer():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

@socketio.on('update_settings')
def up_set(d):
    for k,v in d.items(): 
        if k == 'columns': current_state['settings']['columns'] = v
        elif k in current_state['settings']: 
            if isinstance(current_state['settings'][k], (int, float)):
                try: current_state['settings'][k] = float(v)
                except: pass
            else: current_state['settings'][k] = str(v)
    socketio.emit('state_update', current_state)
    eventlet.spawn(async_save)

@socketio.on('admin_heartbeat')
def hb(d):
    current_state['admin_connected'] = d.get('active', False)
    emit('admin_status', {'connected': current_state['admin_connected']})

@socketio.on('fetch_sheet')
def f_sheet(d=None):
    if d and 'girone' in d:
        current_state['current_girone'] = d['girone']
        current_state['manual_selection'] = False 
        eventlet.spawn(async_save)
    current_state['match_list'] = []
    socketio.emit('state_update', current_state)
    update_all_gironi_data()

@socketio.on('load_match')
def l_match(d):
    push_history()
    if 'girone' in d: current_state['active_girone'] = d['girone']
    else: current_state['active_girone'] = current_state.get('current_girone', 'rosso')
    
    current_state['manual_selection'] = True
    current_state['swapped'] = False 
    current_state['current_row_idx'] = d['row']
    current_state['fencer_left']['name'] = clean_fencer_name(d['sx'])
    current_state['fencer_right']['name'] = clean_fencer_name(d['dx'])
    current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
    current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
    try: current_state['fencer_left']['score'] = int(float(d['p_sx']))
    except: current_state['fencer_left']['score'] = 0
    try: current_state['fencer_right']['score'] = int(float(d['p_dx']))
    except: current_state['fencer_right']['score'] = 0
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH' 
    current_state['running'] = False
    current_state['priority'] = None
    for s in ['left','right']:
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}

    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

@socketio.on('swap_fencers')
def handle_swap():
    current_state['swapped'] = not current_state['swapped']
    current_state['fencer_left'], current_state['fencer_right'] = current_state['fencer_right'], current_state['fencer_left']
    socketio.emit('state_update', current_state)
    eventlet.spawn(async_save)

@socketio.on('send_result')
def handle_send_result():
    if not current_state['settings'].get('google_script_url'):
        socketio.emit('action_feedback', {'status': 'error', 'msg': 'Manca URL Script nelle Impostazioni!'})
        return
    if not current_state['current_row_idx']:
        socketio.emit('action_feedback', {'status': 'error', 'msg': 'Nessun assalto caricato.'})
        return

    g = current_state.get('active_girone', current_state.get('current_girone', 'rosso'))
    cols_map = current_state['settings'].get('columns', default_columns)
    cols = cols_map.get(g, default_columns['rosso']) 
    c_psx = letter_to_sheet_col(cols['psx'])
    c_pdx = letter_to_sheet_col(cols['pdx'])
    
    val_sx_sheet = current_state['fencer_left']['score']
    val_dx_sheet = current_state['fencer_right']['score']
    if current_state.get('swapped', False):
        val_sx_sheet = current_state['fencer_right']['score']
        val_dx_sheet = current_state['fencer_left']['score']
    
    payload = {
        "sheet_name": "display3gir", "row": current_state['current_row_idx'],
        "col_sx": c_psx, "val_sx": val_sx_sheet, "col_dx": c_pdx, "val_dx": val_dx_sheet
    }
    socketio.emit('upload_status', {'color': 'blue'})
    socketio.emit('action_feedback', {'status': 'info', 'msg': 'Invio in background...'})
    eventlet.spawn(process_background_upload, payload, g)

    matches = gironi_cache.get(g, [])
    current_row = int(payload['row'])
    next_match = next((m for m in matches if m['row'] > current_row and int(float(m.get('p_sx',1))) == 0 and int(float(m.get('p_dx',1))) == 0), None)
            
    if next_match:
        current_state['active_girone'] = g
        current_state['manual_selection'] = True
        current_state['swapped'] = False 
        current_state['current_row_idx'] = next_match['row']
        current_state['fencer_left']['name'] = clean_fencer_name(next_match['sx'])
        current_state['fencer_right']['name'] = clean_fencer_name(next_match['dx'])
        current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
        current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
        current_state['fencer_left']['score'] = 0
        current_state['fencer_right']['score'] = 0
        current_state['timer'] = float(current_state['settings']['time_match'])
        current_state['phase'] = 'MATCH' 
        current_state['running'] = False
        current_state['priority'] = None
        for s in ['left','right']:
            current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
            current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
            
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        socketio.emit('action_feedback', {'status': 'success', 'msg': f'Prossimo: {next_match["sx"]} vs {next_match["dx"]}'})

# --- WORKERS BACKGROUND ---
def process_background_upload(payload, girone):
    try:
        url = current_state['settings']['google_script_url']
        r = requests.post(url, json=payload, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code != 200 or "success" not in r.text:
            socketio.emit('upload_status', {'color': 'red'})
            return
    except:
        socketio.emit('upload_status', {'color': 'red'})
        return

    for wait_time in [10, 30, 60]:
        if wait_time > 10: socketio.emit('upload_status', {'color': 'yellow'})
        eventlet.sleep(wait_time)
        update_all_gironi_data()
        match_data = next((m for m in gironi_cache.get(girone, []) if m['row'] == int(payload['row'])), None)
        if match_data:
            try:
                if int(float(match_data['p_sx'])) == int(payload['val_sx']) and int(float(match_data['p_dx'])) == int(payload['val_dx']):
                    socketio.emit('upload_status', {'color': 'green'}) 
                    eventlet.sleep(5)
                    socketio.emit('upload_status', {'color': 'none'})
                    return
            except: pass
    socketio.emit('upload_status', {'color': 'red'})

def check_internet():
    try: requests.get('https://www.google.com', timeout=2); return True
    except: return False

def check_google():
    if not current_state['settings'].get('google_script_url'): return "missing"
    if not check_internet(): return "error"
    return "ok" 

def check_status_thread_logic(): 
    socketio.emit('status_check', {'internet': check_internet(), 'google': check_google()})

def update_all_gironi_data():
    global gironi_cache
    try:
        sid = current_state['settings'].get('google_sheet_id', DEFAULT_SHEET_ID)
        r = requests.get(f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=display3gir&t={int(time.time())}", headers={'User-Agent': 'Mozilla/5.0'})
        r.encoding = 'utf-8'
        lines = r.text.strip().split('\n')
        new_cache = {k: [] for k in GIRONI_MAP_READ.keys()}
        cols_map = current_state['settings'].get('columns', default_columns)
        
        for i, line in enumerate(lines[1:]): 
            row_idx = i + 2
            p = list(csv.reader([line]))[0]
            for girone in GIRONI_MAP_READ.keys():
                g_cols = cols_map.get(girone)
                if not g_cols: continue
                idx_sx, idx_psx, idx_pdx, idx_dx = letter_to_index(g_cols['sx']), letter_to_index(g_cols['psx']), letter_to_index(g_cols['pdx']), letter_to_index(g_cols['dx'])
                max_idx = max(idx_sx, idx_psx, idx_pdx, idx_dx)
                
                if len(p) > max_idx and p[idx_sx] and p[idx_dx]:
                    name_sx, name_dx = clean_fencer_name(p[idx_sx]), clean_fencer_name(p[idx_dx])
                    if not name_sx or not name_dx or name_sx.isdigit() or name_dx.isdigit() or len(name_sx) < 2 or len(name_dx) < 2: continue
                    new_cache[girone].append({"sx": name_sx, "p_sx": p[idx_psx] if p[idx_psx] else "0", "p_dx": p[idx_pdx] if p[idx_pdx] else "0", "dx": name_dx, "row": row_idx})
        
        gironi_cache = new_cache
        socketio.emit('gironi_cache_update', gironi_cache)
        
        curr_row = current_state.get('current_row_idx')
        curr_gir = current_state.get('active_girone')
        updated_current = False
        
        if curr_row and curr_gir in gironi_cache:
            for m in gironi_cache[curr_gir]:
                if m['row'] == curr_row:
                    target_l, target_r = (m['dx'], m['sx']) if current_state.get('swapped', False) else (m['sx'], m['dx'])
                    if current_state['fencer_left']['name'] != target_l or current_state['fencer_right']['name'] != target_r:
                        current_state['fencer_left']['name'] = target_l
                        current_state['fencer_left']['photo'] = get_photo_url(target_l)
                        current_state['fencer_right']['name'] = target_r
                        current_state['fencer_right']['photo'] = get_photo_url(target_r)
                        updated_current = True
                    break

        cg = current_state.get('current_girone', 'rosso')
        current_state['match_list'] = new_cache.get(cg, [])
        socketio.emit('state_update', current_state)
        if updated_current: eventlet.spawn(async_save)
            
        if not current_state.get('manual_selection') and not current_state['running'] and current_state['timer'] == float(current_state['settings']['time_match']):
             next_match = next((m for m in new_cache.get(cg, []) if (int(float(m['p_sx'])) == 0 and int(float(m['p_dx'])) == 0)), None)
             if not next_match:
                 current_state['fencer_left']['name'] = current_state['settings']['default_name_left']
                 current_state['fencer_right']['name'] = current_state['settings']['default_name_right']
                 current_state['fencer_left']['photo'], current_state['fencer_right']['photo'] = get_photo_url(None), get_photo_url(None)
                 current_state['current_row_idx'] = None
                 current_state['fencer_left']['score'] = current_state['fencer_right']['score'] = 0
                 current_state['swapped'] = False
                 current_state['active_girone'] = cg 
             elif (current_state['fencer_left']['name'] != next_match['sx'] or current_state['fencer_right']['name'] != next_match['dx']):
                 current_state['fencer_left']['name'] = next_match['sx']
                 current_state['fencer_right']['name'] = next_match['dx']
                 current_state['fencer_left']['photo'], current_state['fencer_right']['photo'] = get_photo_url(next_match['sx']), get_photo_url(next_match['dx'])
                 current_state['current_row_idx'] = next_match['row']
                 current_state['fencer_left']['score'] = current_state['fencer_right']['score'] = 0
                 current_state['swapped'] = False
                 current_state['active_girone'] = cg 
             socketio.emit('state_update', current_state)
             eventlet.spawn(async_save)
    except Exception as e: print(f"Update error: {e}")

def data_refresh_thread():
    while True:
        update_all_gironi_data()
        eventlet.sleep(max(10, float(current_state['settings'].get('refresh_rate', 30))))

def status_check_thread():
    while True:
        check_status_thread_logic()
        eventlet.sleep(10)

def timer_thread():
    while True:
        if current_state['running']:
            if current_state['timer'] > 0:
                current_state['timer'] -= 0.1
                if current_state['timer'] < 0: current_state['timer'] = 0
                socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase','MATCH')})
                if current_state['timer'] <= 0:
                    socketio.emit('time_expired')
                    if current_state.get('phase') == 'MATCH':
                        current_state['phase'], current_state['timer'], current_state['running'] = 'BREAK', float(current_state['settings']['time_break']), True
                    else:
                        current_state['phase'], current_state['timer'], current_state['running'] = 'MATCH', float(current_state['settings']['time_match']), False
                    socketio.emit('state_update', current_state)
                    eventlet.spawn(async_save)
            else:
                current_state['running'] = False
                eventlet.spawn(async_save)
        eventlet.sleep(0.1)

def udp_listener_thread():
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.bind(('0.0.0.0', 7777))
    while True:
        try:
            data, addr = udp_sock.recvfrom(1024)
            msg = data.decode('utf-8')
            
            if msg == "HIT_ROSSO": process_hw_hit("left")
            elif msg == "HIT_VERDE": process_hw_hit("right")
            elif msg == "MASSA_ROSSO": process_massa("left")
            elif msg == "MASSA_VERDE": process_massa("right")
            elif msg.startswith("PING_ROSSO"):
                parts = msg.split('_')
                bat = parts[2] if len(parts) > 2 else 100
                pico_last_seen['rosso'] = {'time': time.time(), 'bat': bat}
            elif msg.startswith("PING_VERDE"):
                parts = msg.split('_')
                bat = parts[2] if len(parts) > 2 else 100
                pico_last_seen['verde'] = {'time': time.time(), 'bat': bat}
        except: pass
        eventlet.sleep(0.005)

eventlet.spawn(timer_thread)
eventlet.spawn(data_refresh_thread)
eventlet.spawn(status_check_thread)
eventlet.spawn(udp_listener_thread) 

def resolve_priority_animation():
    eventlet.sleep(2.5)
    current_state['priority'] = random.choice(['left','right'])
    current_state['timer'] = 60.0
    current_state['running'] = False
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': 60.0, 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

if __name__ == '__main__':
    load_state()
    eventlet.spawn(update_all_gironi_data)
    socketio.run(app, host='0.0.0.0', port=5000)