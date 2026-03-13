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

STATE_FILE = "local_match_state.json"
OLD_STATE_FILE = "match_state.json"

DEFAULT_SHEET_ID = "179tfN2PDrSTYtiAdVeFQKXF9OtwZj4k4EbQ1dWXH5Yg"

GIRONI_MAP_WRITE = { 'rosso': [2, 3], 'giallo': [7, 8], 'blu': [12, 13], 'verde': [17, 18], '32': [22, 23] }
GIRONI_MAP_READ = { 'rosso': [0, 1, 2, 3], 'giallo': [5, 6, 7, 8], 'blu': [10, 11, 12, 13], 'verde': [15, 16, 17, 18], '32': [20, 21, 22, 23] }

gironi_cache = {'rosso': [], 'giallo': [], 'blu': [], 'verde': [], '32': []}
history_stack = []
last_google_status = "ok"

pico_last_seen = {'rosso': 0, 'verde': 0}
last_hit_time = 0
hit_sides_in_window = set()

def letter_to_index(letter):
    if not letter: return 0
    return ord(letter.upper()) - 65

def letter_to_sheet_col(letter):
    if not letter: return 1
    return ord(letter.upper()) - 64

def clean_fencer_name(raw_name):
    if not raw_name: return ""
    cleaned = re.sub(r'[^a-zA-Z0-9 ]', '', raw_name)
    return " ".join(cleaned.split())

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
        s.close()
    except Exception: IP = '127.0.0.1'
    return IP

def get_current_ssid():
    try:
        ssid = subprocess.check_output("iwgetid -r", shell=True).decode().strip()
        return ssid if ssid else "Nessuna Rete"
    except: return "Offline"

def get_photo_url(name):
    if not name: return "/static/photos/default.png"
    safe_name = name.strip()
    for ext in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{safe_name}.{ext}")):
            return f"/static/photos/{safe_name}.{ext}?v={random.randint(1,1000)}"
    clean = clean_fencer_name(name)
    for ext in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
        if os.path.exists(os.path.join(PHOTOS_DIR, f"{clean}.{ext}")):
            return f"/static/photos/{clean}.{ext}?v={random.randint(1,1000)}"
    return "/static/photos/default.png"

def new_fencer(name):
    c_name = clean_fencer_name(name)
    return { 
        "name": c_name, "score": 0, 
        "cards": {"Y": False, "R": False, "B": False, "R_count": 0}, 
        "p_cards": {"Y": False, "R": False, "B": False}, 
        "photo": get_photo_url(name) 
    }

def get_system_fonts():
    try:
        output = subprocess.check_output(['fc-list', ':', 'family'], encoding='utf-8')
        fonts = set()
        for line in output.splitlines():
            for family in line.split(','):
                f = family.strip()
                if f: fonts.add(f)
        return sorted(list(fonts))
    except: return ['Roboto Mono', 'Arial', 'Verdana', 'Courier New']

default_columns = {
    'rosso': {'sx': 'A', 'psx': 'B', 'pdx': 'C', 'dx': 'D'}, 
    'giallo': {'sx': 'F', 'psx': 'G', 'pdx': 'H', 'dx': 'I'}, 
    'blu': {'sx': 'K', 'psx': 'L', 'pdx': 'M', 'dx': 'N'}, 
    'verde': {'sx': 'P', 'psx': 'Q', 'pdx': 'R', 'dx': 'S'}, 
    '32': {'sx': 'U', 'psx': 'V', 'pdx': 'W', 'dx': 'X'} 
}

default_settings = {
    "weapon": "spada", "font_family": "Roboto Mono", "font_timer": 8.0, "font_score": 15.0, "font_name": 3.0, "font_list": 1.5,
    "col_center_width": 1.2, "list_padding": 0.5, "text_border": 0.0, "photo_size": 150,
    "time_match": 180, "time_break": 60, "time_medical": 300, "refresh_rate": 30, "buzzer_volume": 1.0,
    "default_name_left": "ATLETA SX", "default_name_right": "ATLETA DX", 
    "google_script_url": "", "google_sheet_id": DEFAULT_SHEET_ID, "columns": default_columns
}

default_state = {
    "timer": 180.0, "running": False, "phase": "MATCH", "priority": None,
    "fencer_left": new_fencer(default_settings["default_name_left"]), 
    "fencer_right": new_fencer(default_settings["default_name_right"]),
    "period": 1, "admin_connected": False, "server_ip": get_local_ip(), "ssid": get_current_ssid(),
    "match_list": [], "current_girone": "rosso", "active_girone": "rosso", "current_row_idx": None,
    "manual_selection": False, "swapped": False, "settings": default_settings.copy(), "wifi_connected": False
}

current_state = default_state.copy()

def save_state():
    try:
        with open(STATE_FILE, 'w') as f: json.dump(current_state, f)
    except: pass

def load_state():
    global current_state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                data['running'] = False
                data['server_ip'] = get_local_ip()
                data['ssid'] = get_current_ssid()
                data['wifi_connected'] = data['server_ip'] != '127.0.0.1'
                if 'settings' not in data: data['settings'] = default_settings.copy()
                current_state = data
        except: pass

def push_history():
    global history_stack
    history_stack.append(copy.deepcopy(current_state))
    if len(history_stack) > 20: history_stack.pop(0)

def async_save():
    save_state()

# --- ROUTES ---
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

# --- LOGICA PUNTEGGI ISTANTANEA DA UDP ---
def process_hw_hit(side, delta=1):
    global last_hit_time, hit_sides_in_window
    now = time.time()
    
    if current_state.get('phase') != 'MATCH' or current_state['timer'] <= 0:
        return
        
    if current_state['running']:
        current_state['running'] = False # STOP IMMEDIATO TEMPO
        last_hit_time = now
        hit_sides_in_window = {side}
        current_state[f'fencer_{side}']['score'] += delta
        
        socketio.emit('hw_hit', {'side': side, 'is_double': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)
        
    elif side not in hit_sides_in_window and (now - last_hit_time < 0.2): # Colpo doppio in 200ms
        hit_sides_in_window.add(side)
        current_state[f'fencer_{side}']['score'] += delta
        
        socketio.emit('hw_hit', {'side': side, 'is_double': True})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(async_save)

@app.route('/api/pico_status')
def get_pico_status():
    now = time.time()
    return jsonify({'rosso': (now - pico_last_seen['rosso']) < 5, 'verde': (now - pico_last_seen['verde']) < 5})

# --- SOCKET ---
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
        emit('state_update', current_state, broadcast=True)
        emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
        eventlet.spawn(async_save)

@socketio.on('update_score')
def handle_score(d):
    push_history()
    side = d['side']
    current_state[f'fencer_{side}']['score'] = max(0, current_state[f'fencer_{side}']['score'] + d['delta'])
    
    # QUALSIASI CAMBIO PUNTO DAL TELECOMANDO FERMA IL TEMPO
    current_state['running'] = False
    
    if d['delta'] > 0: 
        socketio.emit('hw_hit', {'side': side, 'is_double': False}, broadcast=True) 
    
    emit('state_update', current_state, broadcast=True)
    emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
    eventlet.spawn(async_save) # SALVATAGGIO ASINCRONO = ZERO LAG
    
@socketio.on('toggle_timer')
def handle_toggle():
    current_state['running'] = not current_state['running']
    emit('state_update', current_state, broadcast=True)
    eventlet.spawn(async_save)

@socketio.on('adjust_time')
def handle_adjust_time(data):
    push_history()
    current_state['timer'] = max(0, current_state['timer'] + float(data.get('delta',0)))
    emit('state_update', current_state, broadcast=True)
    emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
    eventlet.spawn(async_save)

@socketio.on('card_action')
def handle_card(d):
    push_history()
    side = d['side']
    card_type = d['card']
    fencer = current_state[f'fencer_{side}']
    opponent = current_state[f"fencer_{'right' if side == 'left' else 'left'}"]

    if card_type.startswith('P_'):
        k = card_type.split('_')[1]
        fencer['p_cards'][k] = not fencer['p_cards'][k]
    else:
        has_yellow = fencer['cards']['Y']
        red_count = fencer['cards'].get('R_count', 0)
        has_black = fencer['cards']['B']

        if card_type == 'B':
            fencer['cards']['B'] = True
            current_state['running'] = False
        elif card_type in ['Y', 'R']:
            if not has_black:
                if not has_yellow and red_count == 0:
                    if card_type == 'Y': fencer['cards']['Y'] = True
                    elif card_type == 'R':
                        red_count = 1
                        opponent['score'] += 1
                        current_state['running'] = False
                else:
                    if red_count < 2: red_count += 1
                    opponent['score'] += 1
                    current_state['running'] = False
            fencer['cards']['R_count'] = red_count
            fencer['cards']['R'] = (red_count > 0)

    emit('state_update', current_state, broadcast=True)
    emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
    eventlet.spawn(async_save)

@socketio.on('double_hit')
def db_hit():
    push_history()
    current_state['fencer_left']['score'] += 1
    current_state['fencer_right']['score'] += 1
    current_state['running'] = False
    socketio.emit('hw_hit', {'side': 'double', 'is_double': True}, broadcast=True)
    emit('state_update', current_state, broadcast=True)
    emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
    eventlet.spawn(async_save)

@socketio.on('toggle_priority')
def toggle_prio():
    push_history()
    if current_state['priority']: current_state['priority'] = None
    else: 
        current_state['priority'] = 'animating'
        eventlet.spawn(resolve_priority_animation)
    emit('state_update', current_state, broadcast=True)
    eventlet.spawn(async_save)

@socketio.on('reset_all')
def r_all():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH' 
    current_state['running'] = False
    current_state['priority'] = None
    for s in ['left','right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
    emit('state_update', current_state, broadcast=True)
    emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
    eventlet.spawn(async_save)

@socketio.on('reset_scores')
def r_scores():
    push_history()
    for s in ['left','right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
    emit('state_update', current_state, broadcast=True)
    eventlet.spawn(async_save)
    
@socketio.on('reset_timer')
def r_timer():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH' 
    current_state['running'] = False
    emit('state_update', current_state, broadcast=True)
    emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')}, broadcast=True)
    eventlet.spawn(async_save)

def udp_listener_thread():
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.bind(('0.0.0.0', 7777))
    while True:
        try:
            data, addr = udp_sock.recvfrom(1024)
            msg = data.decode('utf-8')
            
            # GESTIONE FULMINEA PUNTEGGI DA UDP
            if "HIT_ROSSO" in msg:
                process_hw_hit("left")
            elif "HIT_VERDE" in msg:
                process_hw_hit("right")
            elif "PING_ROSSO" in msg:
                pico_last_seen['rosso'] = time.time()
            elif "PING_VERDE" in msg:
                pico_last_seen['verde'] = time.time()
        except: pass
        eventlet.sleep(0.005) # Loop ad altissima frequenza per lag zero

def timer_thread():
    while True:
        try:
            if current_state['running']:
                if current_state['timer'] > 0:
                    current_state['timer'] -= 0.1
                    if current_state['timer'] < 0: current_state['timer'] = 0
                    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase','MATCH')})
                    if current_state['timer'] <= 0:
                        socketio.emit('time_expired')
                        current_state['running'] = False
                        socketio.emit('state_update', current_state)
                        eventlet.spawn(async_save)
                else:
                    current_state['running'] = False
                    eventlet.spawn(async_save)
        except: pass
        eventlet.sleep(0.1)

# API Rest & Google omitted for brevity but remain identical 
# (You can append your existing Google Sheet functions here as they don't affect latency)

def check_internet():
    try:
        requests.get('https://www.google.com', timeout=2)
        return True
    except: return False

def check_google(): return "ok"

eventlet.spawn(timer_thread)
eventlet.spawn(udp_listener_thread) 

if __name__ == '__main__':
    load_state()
    socketio.run(app, host='0.0.0.0', port=5000)