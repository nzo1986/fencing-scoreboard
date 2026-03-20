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

# VARIABILI CRITICHE PER L'ALGORITMO ANTI-COCCIA
last_hit_timestamp = 0
hit_sides_in_window = set()
last_coccia_time = {'left': 0, 'right': 0}
last_massa_emit = {'left': 0, 'right': 0}

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
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{name.strip()}.{ext}")): return f"/static/photos/{name.strip()}.{ext}?v={random.randint(1,1000)}"
    clean = clean_fencer_name(name)
    for ext in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
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

default_columns = {'rosso': {'sx': 'A', 'psx': 'B', 'pdx': 'C', 'dx': 'D'}, 'giallo': {'sx': 'F', 'psx': 'G', 'pdx': 'H', 'dx': 'I'}, 'blu': {'sx': 'K', 'psx': 'L', 'pdx': 'M', 'dx': 'N'}, 'verde': {'sx': 'P', 'psx': 'Q', 'pdx': 'R', 'dx': 'S'}, '32': {'sx': 'U', 'psx': 'V', 'pdx': 'W', 'dx': 'X'} }
default_settings = {"weapon": "spada", "font_family": "Roboto Mono", "font_timer": 8.0, "font_score": 15.0, "font_name": 3.0, "font_list": 1.5, "col_center_width": 1.2, "list_padding": 0.5, "text_border": 0.0, "photo_size": 150, "time_match": 180, "time_break": 60, "time_medical": 300, "refresh_rate": 30, "buzzer_volume": 1.0, "default_name_left": "ATLETA SX", "default_name_right": "ATLETA DX", "google_script_url": "", "google_sheet_id": DEFAULT_SHEET_ID, "columns": copy.deepcopy(default_columns)}
default_state = {"timer": 180.0, "running": False, "phase": "MATCH", "priority": None, "fencer_left": new_fencer(default_settings["default_name_left"]), "fencer_right": new_fencer(default_settings["default_name_right"]), "period": 1, "admin_connected": False, "server_ip": get_local_ip(), "ssid": get_current_ssid(), "match_list": [], "current_girone": "rosso", "active_girone": "rosso", "current_row_idx": None, "manual_selection": False, "swapped": False, "settings": copy.deepcopy(default_settings), "wifi_connected": False}

current_state = copy.deepcopy(default_state)

def save_state():
    try:
        with open(STATE_FILE, 'w') as f: json.dump(current_state, f)
    except: pass
def async_save(): save_state()

def load_state():
    global current_state
    file_to_load = STATE_FILE if os.path.exists(STATE_FILE) else OLD_STATE_FILE if os.path.exists(OLD_STATE_FILE) else None
    if file_to_load:
        try:
            with open(file_to_load, 'r') as f:
                data = json.load(f)
                if 'settings' in data: current_state['settings'].update(data['settings'])
                if 'fencer_left' in data:
                    if 'cards' in data['fencer_left']: current_state['fencer_left']['cards'].update(data['fencer_left']['cards'])
                    if 'p_cards' in data['fencer_left']: current_state['fencer_left']['p_cards'].update(data['fencer_left']['p_cards'])
                    for k, v in data['fencer_left'].items():
                        if k not in ['cards', 'p_cards']: current_state['fencer_left'][k] = v
                    current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left'].get('name', ''))
                if 'fencer_right' in data:
                    if 'cards' in data['fencer_right']: current_state['fencer_right']['cards'].update(data['fencer_right']['cards'])
                    if 'p_cards' in data['fencer_right']: current_state['fencer_right']['p_cards'].update(data['fencer_right']['p_cards'])
                    for k, v in data['fencer_right'].items():
                        if k not in ['cards', 'p_cards']: current_state['fencer_right'][k] = v
                    current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right'].get('name', ''))
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

# --- NUOVO ALGORITMO CORRELAZIONE COCCIA ---
def process_massa_emit(side):
    global last_massa_emit
    now = time.time()
    if now - last_massa_emit[side] > 0.5:
        socketio.emit('hw_massa', {'side': side})
        last_massa_emit[side] = now

def handle_hit_async(side, hit_timestamp):
    """Questa funzione attende una frazione di secondo per vedere se l'avversario segnala coccia"""
    opp_side = 'right' if side == 'left' else 'left'
    
    # Aspetta 40 millisecondi per dare tempo al pacchetto UDP dell'avversario di arrivare
    eventlet.sleep(0.04)
    
    # Se il server ha ricevuto un segnale di COCCIA dall'avversario nello stesso momento della stoccata...
    if abs(last_coccia_time[opp_side] - hit_timestamp) < 0.1:
        # COLPO ANNULLATO: È STATO SULLA COCCIA AVVERSARIA!
        process_massa_emit(side) # Fa lampeggiare di bianco chi ha attaccato
        return
    
    # Se non c'è stata coccia, la stoccata è buona
    process_valid_hit(side, hit_timestamp)

def process_valid_hit(side, hit_timestamp):
    global last_hit_timestamp, hit_sides_in_window
    
    if current_state.get('phase') != 'MATCH': return
    
    if not current_state['running']:
        # Tempo fermo: Nessun punto (suona solo). is_manual = False (1.5s)
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': False, 'is_manual': False})
        return
        
    weapon = current_state['settings'].get('weapon', 'spada')
    lockout_ms = 0.045 
    if weapon == 'fioretto': lockout_ms = 0.300
    elif weapon == 'sciabola': lockout_ms = 0.170 
    
    if current_state['running']:
        current_state['running'] = False
        last_hit_timestamp = hit_timestamp
        hit_sides_in_window = {side}
        current_state[f'fencer_{side}']['score'] += 1
        
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)
        
    elif side not in hit_sides_in_window and (hit_timestamp - last_hit_timestamp <= lockout_ms):
        hit_sides_in_window.add(side)
        current_state[f'fencer_{side}']['score'] += 1
        
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)

@app.route('/api/pico_status')
def get_pico_status():
    now = time.time()
    return jsonify({
        'rosso': {'active': (now - pico_last_seen['rosso']['time']) < 5, 'bat': pico_last_seen['rosso']['bat']},
        'verde': {'active': (now - pico_last_seen['verde']['time']) < 5, 'bat': pico_last_seen['verde']['bat']}
    })

@app.route('/api/scan_wifi')
def api_scan(): return jsonify([]) 
@app.route('/api/saved_wifi')
def api_saved(): return jsonify([]) 
@app.route('/api/connect_wifi', methods=['POST'])
def api_connect(): return jsonify({"status": "error"}), 400
@app.route('/api/delete_wifi', methods=['POST'])
def api_delete_wifi(): return jsonify({"status": "error"})
@app.route('/api/upload_photo', methods=['POST'])
def upload_photo(): return jsonify({"success": True})
@app.route('/api/get_athletes')
def get_athletes(): return jsonify([])
@app.route('/api/maxi_upload', methods=['POST'])
def maxi_upload(): return jsonify({"processed": 0})
@app.route('/api/download_photos')
def download_photos(): return jsonify({"error": "not implemented"})
@app.route('/api/get_fonts')
def api_get_fonts(): return jsonify(get_system_fonts())

@socketio.on('connect')
def handle_connect(): 
    current_state['server_ip'] = get_local_ip()
    current_state['ssid'] = get_current_ssid()
    current_state['wifi_connected'] = current_state['server_ip'] != '127.0.0.1'
    emit('status_check', {'internet': False, 'google': 'missing'})
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
        # is_manual: True dice al frontend di fare il suono corto di 0.5s
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
        eventlet.sleep(2.5)
        current_state['priority'] = random.choice(['left','right'])
        current_state['timer'] = 60.0
        current_state['running'] = False
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
    current_state['current_row_idx'] = None
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(async_save)

@socketio.on('reset_scores')
def r_scores():
    push_history()
    current_state['running'] = False
    for s in ['left','right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
    socketio.emit('state_update', current_state)
    eventlet.spawn(async_save)
    
@socketio.on('reset_timer')
def r_timer():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    socketio.emit('state_update', current_state)
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
    socketio.emit('state_update', current_state)

@socketio.on('load_match')
def l_match(d):
    push_history()
    current_state['active_girone'] = d.get('girone', current_state.get('current_girone', 'rosso'))
    current_state['manual_selection'] = True
    current_state['swapped'] = False 
    current_state['current_row_idx'] = d['row']
    current_state['fencer_left']['name'] = clean_fencer_name(d['sx'])
    current_state['fencer_right']['name'] = clean_fencer_name(d['dx'])
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
    eventlet.spawn(async_save)

@socketio.on('swap_fencers')
def handle_swap():
    current_state['swapped'] = not current_state['swapped']
    current_state['fencer_left'], current_state['fencer_right'] = current_state['fencer_right'], current_state['fencer_left']
    socketio.emit('state_update', current_state)
    eventlet.spawn(async_save)

@socketio.on('send_result')
def handle_send_result():
    socketio.emit('action_feedback', {'status': 'error', 'msg': 'Invio risultati disabilitato in questa versione.'})

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
            now = time.time()
            
            # 1. Stoccate lanciate in background per controllare la coccia
            if msg == "HIT_ROSSO": eventlet.spawn(handle_hit_async, "left", now)
            elif msg == "HIT_VERDE": eventlet.spawn(handle_hit_async, "right", now)
            
            # 2. La mia coccia è stata toccata dall'avversario
            elif msg == "COCCIA_ROSSO": last_coccia_time['left'] = now
            elif msg == "COCCIA_VERDE": last_coccia_time['right'] = now
            
            # 3. Ho toccato la MIA STESSA coccia
            elif msg == "MASSA_MIA_ROSSO": process_massa_emit("left")
            elif msg == "MASSA_MIA_VERDE": process_massa_emit("right")
            
            # Ping
            elif msg.startswith("PING_ROSSO"):
                parts = msg.split('_')
                bat = parts[2] if len(parts) > 2 else 100
                pico_last_seen['rosso'] = {'time': now, 'bat': bat}
            elif msg.startswith("PING_VERDE"):
                parts = msg.split('_')
                bat = parts[2] if len(parts) > 2 else 100
                pico_last_seen['verde'] = {'time': now, 'bat': bat}
        except: pass
        eventlet.sleep(0.005)

eventlet.spawn(timer_thread)
eventlet.spawn(udp_listener_thread) 

if __name__ == '__main__':
    load_state()
    socketio.run(app, host='0.0.0.0', port=5000)