import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import os, time, random

from config_state import current_state, load_state, save_state, push_history, gironi_cache, get_photo_url, clean_fencer_name, PHOTOS_DIR, get_system_fonts, letter_to_sheet_col, default_columns, BASE_DIR
from fencing_logic import apply_card
from google_api import update_all_gironi_data, process_background_upload, check_internet, check_google

app = Flask(__name__)
app.config['SECRET_KEY'] = 'scherma_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

@app.route('/')
def index(): return render_template('index.html')
@app.route('/telecomando')
def telecomando(): return render_template('telecomando.html')
@app.route('/settings')
def settings(): return render_template('settings.html')
@app.route('/riferimenti')
def riferimenti(): return render_template('riferimenti.html')
@app.route('/inserisci_punti')
def inserisci_punti(): return render_template('inserisci_punti.html')
@app.route('/wifi')
def wifi_page(): return render_template('wifi.html')
@app.route('/foto')
def foto_page(): return render_template('foto.html')
@app.route('/download')
def download_page(): return render_template('download.html')

@app.route('/api/get_fencers')
def get_fencers():
    names = set()
    for g, matches in gironi_cache.items():
        for m in matches:
            if m.get('sx'): names.add(m['sx'])
            if m.get('dx'): names.add(m['dx'])
    names.add(current_state['fencer_left']['name'])
    names.add(current_state['fencer_right']['name'])
    fencers = []
    for n in sorted(list(names)):
        if n and len(n.strip()) > 1:
            fencers.append({'name': n, 'photo': get_photo_url(n)})
    return jsonify(fencers)

@app.route('/api/upload_photo', methods=['POST'])
def upload_photo():
    if 'photo' not in request.files or 'name' not in request.form: return jsonify({"status": "error", "msg": "Dati mancanti"})
    file = request.files['photo']
    name = request.form['name']
    if file.filename == '': return jsonify({"status": "error", "msg": "Nessun file selezionato"})
    clean_name = clean_fencer_name(name)
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
    filename = f"{clean_name}.{ext}"
    filepath = os.path.join(PHOTOS_DIR, filename)
    for e in ['jpg', 'png', 'jpeg', 'JPG', 'PNG']:
        old_path = os.path.join(PHOTOS_DIR, f"{clean_name}.{e}")
        if os.path.exists(old_path):
            try: os.remove(old_path)
            except: pass
    file.save(filepath)
    new_url = f"/static/photos/{filename}?v={int(time.time())}"
    updated = False
    if current_state['fencer_left']['name'] == name:
        current_state['fencer_left']['photo'] = new_url; updated = True
    if current_state['fencer_right']['name'] == name:
        current_state['fencer_right']['photo'] = new_url; updated = True
    if updated:
        socketio.emit('state_update', current_state)
        eventlet.spawn(save_state)
    return jsonify({"status": "success", "url": new_url})

@app.route('/api/update_system', methods=['POST'])
def update_system():
    def run_update_process():
        import subprocess
        cmd = ['python', 'setup_fencing_kiosk.py']
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=BASE_DIR)
            for line in iter(process.stdout.readline, ''):
                if line: socketio.emit('update_log', {'msg': line.strip()})
            process.stdout.close()
            process.wait()
            socketio.emit('update_complete')
            os.system("nohup bash -c 'sleep 2 && pkill -f \"python app.py\" || true; source venv/bin/activate && python app.py' >/dev/null 2>&1 &")
        except Exception as e:
            socketio.emit('update_log', {'msg': f"[ERRORE FATALE] {str(e)}"})
            socketio.emit('update_complete')
    eventlet.spawn(run_update_process)
    return jsonify({"status": "updating"})

@app.route('/api/get_fonts')
def api_get_fonts(): return jsonify(get_system_fonts())

@socketio.on('connect')
def handle_connect(): 
    emit('status_check', {'internet': check_internet(), 'google': check_google()})
    emit('wifi_info', {'ssid': current_state['ssid'], 'ip': current_state['server_ip']})
    emit('state_update', current_state)
    emit('gironi_cache_update', gironi_cache)

@socketio.on('update_score')
def handle_score(d):
    push_history()
    side = d['side']
    current_state[f'fencer_{side}']['score'] = max(0, current_state[f'fencer_{side}']['score'] + d['delta'])
    current_state['running'] = False
    if d['delta'] > 0: socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': True})
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)

@socketio.on('double_hit')
def db_hit():
    push_history()
    current_state['fencer_left']['score'] += 1
    current_state['fencer_right']['score'] += 1
    current_state['running'] = False 
    socketio.emit('hw_hit', {'side': 'double', 'is_double': True, 'score_added': True, 'is_manual': True})
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)

@socketio.on('card_action')
def handle_card(d):
    push_history()
    apply_card(d['side'], d['card'], socketio)

@socketio.on('reset_cards')
def handle_reset_cards(data):
    push_history()
    side = data['side']
    current_state[f'fencer_{side}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
    current_state[f'fencer_{side}']['p_cards'] = {"Y": False, "R": False, "B": False}
    socketio.emit('state_update', current_state)
    eventlet.spawn(save_state)

@socketio.on('toggle_timer')
def handle_toggle():
    current_state['running'] = not current_state['running']
    socketio.emit('state_update', current_state)
    eventlet.spawn(save_state)

@socketio.on('adjust_time')
def handle_adjust_time(data):
    push_history()
    current_state['timer'] = max(0, current_state['timer'] + float(data.get('delta',0)))
    current_state['running'] = False 
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)

@socketio.on('toggle_priority')
def handle_priority():
    push_history()
    curr = current_state.get('priority')
    if curr:
        current_state['priority'] = None
        socketio.emit('state_update', current_state)
        eventlet.spawn(save_state)
    else:
        winner = random.choice(['left', 'right'])
        socketio.emit('priority_animation', {'duration': 2500})
        def apply_priority():
            eventlet.sleep(2.5)
            current_state['priority'] = winner
            current_state['timer'] = 60.0 
            current_state['running'] = False
            socketio.emit('state_update', current_state)
            socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
            save_state()
        eventlet.spawn(apply_priority)

@socketio.on('reset_scores')
def r_scores():
    push_history()
    current_state['running'] = False
    for s in ['left','right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
    socketio.emit('state_update', current_state)
    eventlet.spawn(save_state)

@socketio.on('reset_timer')
def r_timer():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    current_state['priority'] = None
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)

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
    current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
    current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
    current_state['current_row_idx'] = None
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)

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
    eventlet.spawn(save_state)

@socketio.on('swap_fencers')
def handle_swap():
    current_state['swapped'] = not current_state['swapped']
    current_state['fencer_left'], current_state['fencer_right'] = current_state['fencer_right'], current_state['fencer_left']
    curr = current_state.get('priority')
    if curr == 'left': current_state['priority'] = 'right'
    elif curr == 'right': current_state['priority'] = 'left'
    socketio.emit('state_update', current_state)
    eventlet.spawn(save_state)

@socketio.on('load_match')
def l_match(d):
    push_history()
    current_state['active_girone'] = d.get('girone', current_state.get('current_girone', 'rosso'))
    current_state['current_girone'] = current_state['active_girone'] # Sincronizza il girone per il display
    current_state['match_list'] = gironi_cache.get(current_state['active_girone'], []) # Aggiorna la lista del display immediatamente
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
    eventlet.spawn(save_state)

@socketio.on('send_result')
def handle_send_result():
    if not current_state['settings'].get('google_script_url') or not current_state['current_row_idx']:
        socketio.emit('action_feedback', {'status': 'error', 'msg': 'Errore URL o Assalto.'})
        return
    g = current_state.get('active_girone', current_state.get('current_girone', 'rosso'))
    cols_map = current_state['settings'].get('columns', default_columns)
    cols = cols_map.get(g, default_columns['rosso']) 
    val_sx = current_state['fencer_right']['score'] if current_state.get('swapped') else current_state['fencer_left']['score']
    val_dx = current_state['fencer_left']['score'] if current_state.get('swapped') else current_state['fencer_right']['score']
    payload = { "sheet_name": "display3gir", "row": current_state['current_row_idx'], "col_sx": letter_to_sheet_col(cols['psx']), "val_sx": val_sx, "col_dx": letter_to_sheet_col(cols['pdx']), "val_dx": val_dx }
    socketio.emit('action_feedback', {'status': 'info', 'msg': 'Invio in background...'})
    eventlet.spawn(process_background_upload, payload, g, socketio)

    matches = gironi_cache.get(g, [])
    next_match = None
    for m in matches:
        if m['row'] != current_state['current_row_idx']:
            try: p_sx = int(float(m.get('p_sx', '0') or '0'))
            except: p_sx = 0
            try: p_dx = int(float(m.get('p_dx', '0') or '0'))
            except: p_dx = 0
            if p_sx == 0 and p_dx == 0:
                next_match = m
                break
    if next_match:
        current_state['active_girone'] = g
        current_state['current_girone'] = g # Sincronizza il girone per il display
        current_state['match_list'] = gironi_cache.get(g, []) # Aggiorna la lista
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
        socketio.emit('action_feedback', {'status': 'success', 'msg': f"Caricato: {next_match['sx']} vs {next_match['dx']}"})
        eventlet.spawn(save_state)
    else:
        socketio.emit('action_feedback', {'status': 'info', 'msg': 'Nessun altro assalto a 0 nel girone!'})

@socketio.on('send_background_result')
def handle_send_background_result(data):
    if not current_state['settings'].get('google_script_url'):
        socketio.emit('action_feedback', {'status': 'error', 'msg': 'Errore: URL Google Script mancante nelle impostazioni.'})
        return
    g = data['girone']
    cols_map = current_state['settings'].get('columns', default_columns)
    cols = cols_map.get(g, default_columns['rosso']) 
    payload = { 
        "sheet_name": "display3gir", 
        "row": data['row'], 
        "col_sx": letter_to_sheet_col(cols['psx']), 
        "val_sx": data['val_sx'], 
        "col_dx": letter_to_sheet_col(cols['pdx']), 
        "val_dx": data['val_dx'] 
    }
    socketio.emit('action_feedback', {'status': 'info', 'msg': f"Invio risultato {data['sx']} vs {data['dx']} in background..."})
    eventlet.spawn(process_background_upload, payload, g, socketio)

@socketio.on('fetch_sheet')
def f_sheet(d=None):
    if d and 'girone' in d:
        current_state['current_girone'] = d['girone']
        current_state['manual_selection'] = False 
        eventlet.spawn(save_state)
    eventlet.spawn(update_all_gironi_data, socketio)

def timer_thread():
    while True:
        if current_state['running']:
            if current_state['timer'] > 0:
                current_state['timer'] -= 0.1
                if current_state['timer'] < 0: current_state['timer'] = 0
                socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase','MATCH')})
                if current_state['timer'] <= 0:
                    socketio.emit('time_expired')
                    
                    # Se finisce il tempo regolare, passa al minuto di priorità
                    if current_state.get('phase') != 'PRIORITY_MINUTE':
                        current_state['timer'] = 60.0
                        current_state['phase'] = 'PRIORITY_MINUTE'
                    else:
                        current_state['timer'] = float(current_state['settings']['time_match'])
                        current_state['phase'] = 'MATCH'
                        current_state['priority'] = None
                        
                    current_state['running'] = False
                    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
                    socketio.emit('state_update', current_state)
                    eventlet.spawn(save_state)
            else:
                current_state['running'] = False
                eventlet.spawn(save_state)
        eventlet.sleep(0.1)

eventlet.spawn(timer_thread)

if __name__ == '__main__':
    load_state()
    eventlet.spawn(update_all_gironi_data, socketio)
    socketio.run(app, host='0.0.0.0', port=5000)