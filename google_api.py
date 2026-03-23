import requests
import csv
import time
import eventlet
from config_state import current_state, gironi_cache, GIRONI_MAP_READ, default_columns, letter_to_index, clean_fencer_name, get_photo_url, save_state, DEFAULT_SHEET_ID

def check_internet():
    try: 
        requests.get('https://www.google.com', timeout=2)
        return True
    except: return False

def check_google():
    if not current_state['settings'].get('google_script_url'): return "missing"
    if not check_internet(): return "error"
    return "ok"

def update_all_gironi_data(socketio):
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
        
        global gironi_cache
        gironi_cache.clear()
        gironi_cache.update(new_cache)
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
        current_state['match_list'] = gironi_cache.get(cg, [])
        socketio.emit('state_update', current_state)
        if updated_current: eventlet.spawn(save_state)

    except Exception as e: print(f"Update error: {e}")

def process_background_upload(payload, girone, socketio):
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
        update_all_gironi_data(socketio)
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