import os
os.environ['EVENTLET_NO_GREENDNS'] = 'yes'

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

ASYNC_MODE = 'threading'

import sys, time, random, io, zipfile, subprocess, socket
import base64, requests, urllib.request, urllib.error

from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit

from config_state import (
    current_state, load_state, save_state, push_history, gironi_cache,
    get_photo_url, clean_fencer_name, PHOTOS_DIR, get_system_fonts,
    letter_to_sheet_col, default_columns, BASE_DIR, get_local_ip, get_current_ssid
)
from fencing_logic import apply_card
from google_api import update_all_gironi_data, process_background_upload, check_internet, check_google

app = Flask(__name__)
app.config['SECRET_KEY'] = 'scherma_secret_key_windows'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=ASYNC_MODE)

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
@app.route('/inserisci_atleti')
def inserisci_atleti(): return render_template('inserisci_atleti.html')
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
    if 'photo' not in request.files or 'name' not in request.form:
        return jsonify({"status": "error", "msg": "Dati mancanti"})
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
            except Exception: pass

    file.save(filepath)
    new_url = f"/static/photos/{filename}?v={int(time.time())}"
    updated = False
    
    if current_state['fencer_left']['name'] == name:
        current_state['fencer_left']['photo'] = new_url; updated = True
    if current_state['fencer_right']['name'] == name:
        current_state['fencer_right']['photo'] = new_url; updated = True

    if updated:
        socketio.emit('state_update', current_state)
        socketio.start_background_task(save_state)

    return jsonify({"status": "success", "url": new_url})

@app.route('/api/download_photos')
def download_photos():
    try:
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(PHOTOS_DIR):
                for file in files:
                    filepath = os.path.join(root, file)
                    zf.write(filepath, arcname=file)
        memory_file.seek(0)
        return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name='foto_atleti.zip')
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/api/upload_zip_bulk', methods=['POST'])
def upload_zip_bulk():
    if 'zipfile' not in request.files: return jsonify({"status": "error", "msg": "Nessun file ricevuto."})
    file = request.files['zipfile']
    if file.filename == '': return jsonify({"status": "error", "msg": "Nessun file selezionato."})
        
    try:
        conteggio = 0
        with zipfile.ZipFile(file) as zf:
            for filename in zf.namelist():
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')) and not '__MACOSX' in filename:
                    base_name = os.path.basename(filename)
                    if not base_name: continue
                    clean_name = clean_fencer_name(os.path.splitext(base_name)[0])
                    ext = base_name.rsplit('.', 1)[1].lower()
                    with open(os.path.join(PHOTOS_DIR, f"{clean_name}.{ext}"), 'wb') as f:
                        f.write(zf.read(filename))
                    conteggio += 1
        return jsonify({"status": "success", "msg": f"{conteggio} foto estratte e salvate!"})
    except Exception as e: return jsonify({"status": "error", "msg": f"File ZIP non valido: {str(e)}"})

# --- MOTORE SINCRONIZZAZIONE DRIVE IN BACKGROUND (UNA AD UNA) ---
@socketio.on('start_drive_sync')
def start_drive_sync(data):
    link = data.get('link', '')
    direction = data.get('direction', 'import')
    script_url = current_state['settings'].get('google_script_url')

    if not script_url:
        socketio.emit('sync_status', {'status': 'error', 'msg': 'Manca URL Apps Script nelle Impostazioni.'})
        return
        
    def run_sync():
        try:
            if direction == 'export':
                files = []
                for root, _, filenames in os.walk(PHOTOS_DIR):
                    for f in filenames:
                        if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                            files.append(os.path.join(root, f))
                            
                total = len(files)
                if total == 0:
                    socketio.emit('sync_status', {'status': 'error', 'msg': 'Nessuna foto locale da esportare.'})
                    return
                    
                socketio.emit('sync_progress', {'current': 0, 'total': total, 'msg': 'Inizio esportazione foto...'})
                
                success_count = 0
                for i, filepath in enumerate(files):
                    filename = os.path.basename(filepath)
                    socketio.emit('sync_progress', {'current': i, 'total': total, 'msg': f'Caricamento in corso: {filename}...'})
                    
                    with open(filepath, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode('utf-8')
                        
                    payload = {
                        "action": "backup_single_photo",
                        "folder_url": link,
                        "filename": filename,
                        "base64_data": b64
                    }
                    res = requests.post(script_url, json=payload, timeout=60)
                    if res.status_code == 200 and res.json().get('status') == 'success':
                        success_count += 1
                    
                socketio.emit('sync_status', {'status': 'success', 'msg': f'Esportate correttamente {success_count} su {total} foto!'})

            elif direction == 'import':
                socketio.emit('sync_progress', {'current': 0, 'total': 0, 'msg': 'Lettura della cartella Drive in corso...'})
                payload = { "action": "list_drive_photos", "folder_url": link }
                res = requests.post(script_url, json=payload, timeout=60)
                
                if res.status_code != 200 or res.json().get('status') != 'success':
                    socketio.emit('sync_status', {'status': 'error', 'msg': 'Errore lettura cartella Drive (Permessi ok?).'})
                    return
                    
                file_list = res.json().get('files', [])
                total = len(file_list)
                
                if total == 0:
                    socketio.emit('sync_status', {'status': 'error', 'msg': 'Cartella Drive vuota o senza foto valide.'})
                    return
                    
                success_count = 0
                for i, drive_file in enumerate(file_list):
                    fname = drive_file['name']
                    fid = drive_file['id']
                    socketio.emit('sync_progress', {'current': i, 'total': total, 'msg': f'Scaricamento in corso: {fname}...'})
                    
                    payload_file = { "action": "get_drive_photo", "file_id": fid }
                    res_file = requests.post(script_url, json=payload_file, timeout=60)
                    
                    if res_file.status_code == 200 and res_file.json().get('status') == 'success':
                        b64_data = res_file.json().get('base64')
                        if b64_data:
                            clean_name = clean_fencer_name(os.path.splitext(fname)[0])
                            ext = fname.rsplit('.', 1)[1].lower() if '.' in fname else 'png'
                            filepath = os.path.join(PHOTOS_DIR, f"{clean_name}.{ext}")
                            with open(filepath, 'wb') as f:
                                f.write(base64.b64decode(b64_data))
                            success_count += 1
                            
                socketio.emit('sync_status', {'status': 'success', 'msg': f'Importate correttamente {success_count} su {total} foto!'})

        except Exception as e:
            socketio.emit('sync_status', {'status': 'error', 'msg': f'Errore Imprevisto: {str(e)}'})

    # Lancia il processo lento in un thread parallelo per non bloccare Flask
    socketio.start_background_task(run_sync)

@app.route('/api/scan_wifi')
def scan_wifi():
    ssids = []
    if os.name == 'nt':
        try:
            cmd = "netsh wlan show networks"
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('latin1', errors='ignore')
            for line in output.splitlines():
                if "SSID" in line and ":" in line:
                    ssid = line.split(":", 1)[1].strip()
                    if ssid and ssid not in ssids: ssids.append(ssid)
        except Exception: pass
    else:
        try:
            out = subprocess.check_output("nmcli -t -f SSID dev wifi list", shell=True).decode()
            ssids = [s.strip() for s in out.splitlines() if s.strip()]
        except Exception: pass
    if not ssids: ssids = [get_current_ssid()]
    return jsonify(list(dict.fromkeys(ssids)))

@app.route('/api/saved_wifi')
def saved_wifi():
    saved = []
    if os.name == 'nt':
        try:
            cmd = "netsh wlan show profiles"
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('latin1', errors='ignore')
            for line in output.splitlines():
                if ":" in line and ("All User Profile" in line or "Profilo utente" in line):
                    profile = line.split(":", 1)[1].strip()
                    if profile: saved.append(profile)
        except Exception: pass
    return jsonify(saved)

@app.route('/api/connect_wifi', methods=['POST'])
def connect_wifi():
    data = request.json or {}
    ssid = data.get('ssid', '')
    if os.name == 'nt':
        try:
            subprocess.run(f'netsh wlan connect name="{ssid}"', shell=True)
            return jsonify({"status": "success", "ip": get_local_ip()})
        except Exception as e: return jsonify({"status": "error", "msg": str(e)})
    return jsonify({"status": "success", "ip": get_local_ip()})

@app.route('/api/delete_wifi', methods=['POST'])
def delete_wifi():
    data = request.json or {}
    ssid = data.get('ssid', '')
    if os.name == 'nt':
        try:
            subprocess.run(f'netsh wlan delete profile name="{ssid}"', shell=True)
            return jsonify({"status": "success"})
        except Exception as e: return jsonify({"status": "error", "msg": str(e)})
    return jsonify({"status": "success"})

@app.route('/api/ota/<pico_name>/version')
def ota_version(pico_name): return "9.0"

@app.route('/api/ota/<pico_name>/code')
def ota_code(pico_name):
    filename = f"pico_{pico_name.lower()}.py"
    path = os.path.join(BASE_DIR, "templates", "pico_code", filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f: return f.read()
    return "# File not found"

@app.route('/api/get_fonts')
def api_get_fonts(): return jsonify(get_system_fonts())

@app.route('/api/update_system', methods=['POST'])
def update_system():
    def run_update_process():
        try:
            socketio.emit('update_log', {'msg': 'Verifica aggiornamenti git...'})
            res = subprocess.run(['git', 'pull'], cwd=BASE_DIR, capture_output=True, text=True)
            socketio.emit('update_log', {'msg': res.stdout or res.stderr or 'Aggiornamento completato.'})
            socketio.emit('update_complete')
        except Exception as e:
            socketio.emit('update_log', {'msg': f"[ERRORE] {str(e)}"})
            socketio.emit('update_complete')
    socketio.start_background_task(run_update_process)
    return jsonify({"status": "updating"})

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
    socketio.start_background_task(save_state)

@socketio.on('double_hit')
def db_hit():
    push_history()
    current_state['fencer_left']['score'] += 1
    current_state['fencer_right']['score'] += 1
    current_state['running'] = False
    socketio.emit('hw_hit', {'side': 'double', 'is_double': True, 'score_added': True, 'is_manual': True})
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    socketio.start_background_task(save_state)

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
    socketio.start_background_task(save_state)

@socketio.on('toggle_timer')
def handle_toggle():
    current_state['running'] = not current_state['running']
    socketio.emit('state_update', current_state)
    socketio.start_background_task(save_state)

@socketio.on('adjust_time')
def handle_adjust_time(data):
    push_history()
    current_state['timer'] = max(0.0, current_state['timer'] + float(data.get('delta', 0)))
    current_state['running'] = False
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    socketio.start_background_task(save_state)

@socketio.on('toggle_priority')
def handle_priority():
    push_history()
    curr = current_state.get('priority')
    if curr:
        current_state['priority'] = None
        socketio.emit('state_update', current_state)
        socketio.start_background_task(save_state)
    else:
        winner = random.choice(['left', 'right'])
        socketio.emit('priority_animation', {'duration': 2500})
        def apply_priority():
            socketio.sleep(2.5)
            current_state['priority'] = winner
            current_state['timer'] = 60.0
            current_state['running'] = False
            socketio.emit('state_update', current_state)
            socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
            save_state()
        socketio.start_background_task(apply_priority)

@socketio.on('reset_scores')
def r_scores():
    push_history()
    current_state['running'] = False
    for s in ['left', 'right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
    socketio.emit('state_update', current_state)
    socketio.start_background_task(save_state)

@socketio.on('reset_timer')
def r_timer():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    current_state['priority'] = None
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    socketio.start_background_task(save_state)

@socketio.on('reset_all')
def r_all():
    push_history()
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    current_state['priority'] = None
    current_state['manual_selection'] = False
    current_state['swapped'] = False
    for s in ['left', 'right']:
        current_state[f'fencer_{s}']['score'] = 0
        current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
    current_state['fencer_left']['name'] = current_state['settings']['default_name_left']
    current_state['fencer_right']['name'] = current_state['settings']['default_name_right']
    current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
    current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
    current_state['current_row_idx'] = None
    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    socketio.start_background_task(save_state)

@socketio.on('update_settings')
def up_set(d):
    for k, v in d.items():
        if k == 'columns': current_state['settings']['columns'] = v
        elif k in current_state['settings']:
            if isinstance(current_state['settings'][k], (int, float)):
                try: current_state['settings'][k] = float(v)
                except Exception: pass
            else: current_state['settings'][k] = str(v)
    socketio.emit('state_update', current_state)
    socketio.start_background_task(save_state)

@socketio.on('swap_fencers')
def handle_swap():
    current_state['swapped'] = not current_state['swapped']
    current_state['fencer_left'], current_state['fencer_right'] = current_state['fencer_right'], current_state['fencer_left']
    curr = current_state.get('priority')
    if curr == 'left': current_state['priority'] = 'right'
    elif curr == 'right': current_state['priority'] = 'left'
    socketio.emit('state_update', current_state)
    socketio.start_background_task(save_state)

@socketio.on('load_match')
def l_match(d):
    push_history()
    current_state['active_girone'] = d.get('girone', current_state.get('current_girone', 'rosso'))
    current_state['current_girone'] = current_state['active_girone']
    current_state['match_list'] = gironi_cache.get(current_state['active_girone'], [])
    current_state['manual_selection'] = True
    current_state['swapped'] = False
    current_state['current_row_idx'] = d['row']
    current_state['fencer_left']['name'] = clean_fencer_name(d['sx'])
    current_state['fencer_right']['name'] = clean_fencer_name(d['dx'])
    current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
    current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
    try: current_state['fencer_left']['score'] = int(float(d['p_sx']))
    except Exception: current_state['fencer_left']['score'] = 0
    try: current_state['fencer_right']['score'] = int(float(d['p_dx']))
    except Exception: current_state['fencer_right']['score'] = 0
    current_state['timer'] = float(current_state['settings']['time_match'])
    current_state['phase'] = 'MATCH'
    current_state['running'] = False
    current_state['priority'] = None
    for s in ['left', 'right']:
        current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
        current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
    socketio.emit('state_update', current_state)
    socketio.start_background_task(save_state)

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
    payload = {
        "sheet_name": "display3gir", "row": current_state['current_row_idx'],
        "col_sx": letter_to_sheet_col(cols['psx']), "val_sx": val_sx,
        "col_dx": letter_to_sheet_col(cols['pdx']), "val_dx": val_dx
    }
    socketio.emit('action_feedback', {'status': 'info', 'msg': 'Invio in background...'})
    socketio.start_background_task(process_background_upload, payload, g, socketio)

    matches = gironi_cache.get(g, [])
    next_match = None
    for m in matches:
        if m['row'] != current_state['current_row_idx']:
            try: p_sx = int(float(m.get('p_sx', '0') or '0'))
            except Exception: p_sx = 0
            try: p_dx = int(float(m.get('p_dx', '0') or '0'))
            except Exception: p_dx = 0
            if p_sx == 0 and p_dx == 0:
                next_match = m
                break
    if next_match:
        current_state['active_girone'] = g
        current_state['current_girone'] = g
        current_state['match_list'] = gironi_cache.get(g, [])
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
        for s in ['left', 'right']:
            current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
            current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        socketio.emit('action_feedback', {'status': 'success', 'msg': f"Caricato: {next_match['sx']} vs {next_match['dx']}"})
        socketio.start_background_task(save_state)
    else:
        current_state['active_girone'] = g
        current_state['current_girone'] = g
        current_state['match_list'] = gironi_cache.get(g, [])
        current_state['manual_selection'] = False
        current_state['swapped'] = False
        current_state['current_row_idx'] = None
        current_state['fencer_left']['name'] = current_state['settings']['default_name_left']
        current_state['fencer_right']['name'] = current_state['settings']['default_name_right']
        current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
        current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
        current_state['fencer_left']['score'] = 0
        current_state['fencer_right']['score'] = 0
        current_state['timer'] = float(current_state['settings']['time_match'])
        current_state['phase'] = 'MATCH'
        current_state['running'] = False
        current_state['priority'] = None
        for s in ['left', 'right']:
            current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
            current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        socketio.emit('action_feedback', {'status': 'info', 'msg': 'Girone completato! Display ripristinato.'})
        socketio.start_background_task(save_state)

@socketio.on('send_background_result')
def handle_send_background_result(data):
    if not current_state['settings'].get('google_script_url'):
        socketio.emit('action_feedback', {'status': 'error', 'msg': 'Errore: URL Google Script mancante nelle impostazioni.'})
        return
    g = data['girone']
    cols_map = current_state['settings'].get('columns', default_columns)
    cols = cols_map.get(g, default_columns['rosso']) 
    payload = { 
        "sheet_name": "display3gir", "row": data['row'], 
        "col_sx": letter_to_sheet_col(cols['psx']), "val_sx": data['val_sx'], 
        "col_dx": letter_to_sheet_col(cols['pdx']), "val_dx": data['val_dx'] 
    }
    socketio.emit('action_feedback', {'status': 'info', 'msg': f"Invio risultato {data['sx']} vs {data['dx']} in background..."})
    socketio.start_background_task(process_background_upload, payload, g, socketio)

@socketio.on('save_bulk_atleti')
def handle_save_bulk_atleti(data):
    url = current_state['settings'].get('google_script_url')
    if not url:
        socketio.emit('action_feedback', {'status': 'error', 'msg': 'URL Apps Script mancante. Vai in Impostazioni.'})
        return
    
    def send_bulk():
        try:
            payload = {
                "action": "update_atleti", "sheet_name": "Atleti",
                "formula": data.get('formula', {}), "data": data.get('atleti', [])
            }
            res = requests.post(url, json=payload, timeout=15)
            if res.status_code == 200:
                socketio.emit('upload_status', {'color': 'green'})
                socketio.emit('action_feedback', {'status': 'success', 'msg': 'Dati Atleti inviati a Google Sheets!'})
            else:
                socketio.emit('upload_status', {'color': 'red'})
                socketio.emit('action_feedback', {'status': 'error', 'msg': f'Errore salvataggio Google: HTTP {res.status_code}'})
        except Exception as e:
            socketio.emit('upload_status', {'color': 'red'})
            socketio.emit('action_feedback', {'status': 'error', 'msg': f'Errore di rete: {str(e)}'})
            
    socketio.emit('upload_status', {'color': 'yellow'})
    socketio.emit('action_feedback', {'status': 'info', 'msg': 'Salvataggio Atleti in corso...'})
    socketio.start_background_task(send_bulk)

@socketio.on('fetch_sheet')
def f_sheet(d=None):
    if d and 'girone' in d:
        current_state['current_girone'] = d['girone']
        current_state['manual_selection'] = False
        socketio.start_background_task(save_state)
    socketio.start_background_task(update_all_gironi_data, socketio)

def timer_thread():
    while True:
        if current_state['running']:
            if current_state['timer'] > 0:
                current_state['timer'] -= 0.1
                if current_state['timer'] < 0: current_state['timer'] = 0.0
                socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase', 'MATCH')})
                if current_state['timer'] <= 0:
                    socketio.emit('time_expired')
                    if current_state.get('phase') != 'PRIORITY_MINUTE':
                        current_state['timer'] = 60.0; current_state['phase'] = 'PRIORITY_MINUTE'
                    else:
                        current_state['timer'] = float(current_state['settings']['time_match'])
                        current_state['phase'] = 'MATCH'; current_state['priority'] = None

                    current_state['running'] = False
                    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
                    socketio.emit('state_update', current_state)
                    socketio.start_background_task(save_state)
            else:
                current_state['running'] = False
                socketio.start_background_task(save_state)
        socketio.sleep(0.1)

def pico_udp_listener():
    UDP_PORT = 7777
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', UDP_PORT))
        print(f"[Pico UDP] In ascolto su porta UDP {UDP_PORT}...")
    except Exception as e:
        print(f"[Pico UDP Warning] Impossibile avviare socket UDP: {e}"); return

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode('utf-8', errors='ignore').strip()
            if msg.startswith("STATE_"):
                parts = msg.split("_")
                if len(parts) >= 4:
                    pico_side = 'left' if parts[1].upper() == 'ROSSO' else 'right'
                    hit = parts[2] == '1'
                    massa = parts[3] == '1'

                    if hit: socketio.emit('hw_hit', {'side': pico_side, 'is_double': False, 'score_added': False, 'is_manual': False, 'hit_type': 'TARGET'})
                    elif massa: socketio.emit('hw_massa', {'side': pico_side})
        except Exception: socketio.sleep(0.1)

socketio.start_background_task(timer_thread)
socketio.start_background_task(pico_udp_listener)

if __name__ == '__main__':
    load_state()
    socketio.start_background_task(update_all_gironi_data, socketio)
    local_ip = get_local_ip()
    print("=" * 60)
    print("   🤺 FENCING SCOREBOARD ATTIVO (CROSS-PLATFORM)")
    print("=" * 60)
    print(f" > Display Principale: http://localhost:5000")
    print(f" > Telecomando Smartphone: http://{local_ip}:5000/telecomando")
    print("=" * 60)
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

