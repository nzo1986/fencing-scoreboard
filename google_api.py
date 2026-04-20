import requests, csv, time, eventlet
from config_state import current_state, gironi_cache, GIRONI_MAP_READ, default_columns, letter_to_index, clean_fencer_name, get_photo_url, save_state, DEFAULT_SHEET_ID

def check_internet():
    try: requests.get('https://www.google.com', timeout=2); return True
    except: return False

def check_google():
    sid = current_state['settings'].get('google_sheet_id', '').strip()
    if not sid: sid = DEFAULT_SHEET_ID
    if not current_state['settings'].get('google_script_url'): return "missing"
    if not check_internet(): return "error"
    return "ok"

def update_all_gironi_data(socketio):
    try:
        sid = current_state['settings'].get('google_sheet_id', '').strip()
        if not sid: sid = DEFAULT_SHEET_ID
        r = requests.get(f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&sheet=display3gir&t={int(time.time())}", headers={'User-Agent': 'Mozilla/5.0'})
        r.encoding = 'utf-8'
        lines = r.text.strip().split('\n')
        
        new_cache = {k: [] for k in GIRONI_MAP_READ.keys()}
        cols_map = current_state['settings'].get('columns', default_columns)
        
        for i, line in enumerate(lines[1:]): 
            row_idx = i + 2
            parsed_line = list(csv.reader([line]))
            if not parsed_line: continue
            p = parsed_line[0]
            
            for girone in GIRONI_MAP_READ.keys():
                g_cols = cols_map.get(girone)
                if not g_cols: continue
                idx_sx, idx_psx, idx_pdx, idx_dx = letter_to_index(g_cols['sx']), letter_to_index(g_cols['psx']), letter_to_index(g_cols['pdx']), letter_to_index(g_cols['dx'])
                max_idx = max(idx_sx, idx_psx, idx_pdx, idx_dx)
                
                if len(p) > max_idx and p[idx_sx].strip() and p[idx_dx].strip():
                    name_sx, name_dx = clean_fencer_name(p[idx_sx]), clean_fencer_name(p[idx_dx])
                    if not name_sx or not name_dx or name_sx.isdigit() or name_dx.isdigit() or len(name_sx) < 2 or len(name_dx) < 2: continue
                    new_cache[girone].append({"sx": name_sx, "p_sx": p[idx_psx].strip() if p[idx_psx].strip() else "0", "p_dx": p[idx_pdx].strip() if p[idx_pdx].strip() else "0", "dx": name_dx, "row": row_idx})
        
        global gironi_cache
        gironi_cache.clear()
        gironi_cache.update(new_cache)
        socketio.emit('gironi_cache_update', gironi_cache)
        
        curr_row = current_state.get('current_row_idx')
        curr_gir = current_state.get('active_girone', current_state.get('current_girone', 'rosso'))
        updated_current = False
        
        matches_in_gir = gironi_cache.get(curr_gir, [])
        current_match_completed = False
        match_found = False

        if curr_row:
            for m in matches_in_gir:
                if m['row'] == curr_row:
                    match_found = True
                    try:
                        p_sx = int(float(m.get('p_sx', '0') or '0'))
                        p_dx = int(float(m.get('p_dx', '0') or '0'))
                    except:
                        p_sx, p_dx = 0, 0
                    
                    if p_sx != 0 or p_dx != 0:
                        current_match_completed = True
                    else:
                        target_l, target_r = (m['dx'], m['sx']) if current_state.get('swapped', False) else (m['sx'], m['dx'])
                        if current_state['fencer_left']['name'] != target_l or current_state['fencer_right']['name'] != target_r:
                            current_state['fencer_left']['name'] = target_l
                            current_state['fencer_left']['photo'] = get_photo_url(target_l)
                            current_state['fencer_right']['name'] = target_r
                            current_state['fencer_right']['photo'] = get_photo_url(target_r)
                            updated_current = True
                    break
            if not match_found:
                current_match_completed = True

        if current_match_completed or (not curr_row and current_state['fencer_left']['name'] == current_state['settings']['default_name_left']):
            next_match = None
            for m in matches_in_gir:
                try:
                    p_sx = int(float(m.get('p_sx', '0') or '0'))
                    p_dx = int(float(m.get('p_dx', '0') or '0'))
                except:
                    p_sx, p_dx = 0, 0
                if p_sx == 0 and p_dx == 0:
                    next_match = m
                    break
            
            if next_match:
                current_state['current_row_idx'] = next_match['row']
                current_state['fencer_left']['name'] = clean_fencer_name(next_match['sx'])
                current_state['fencer_right']['name'] = clean_fencer_name(next_match['dx'])
                current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
                current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
                current_state['fencer_left']['score'] = 0
                current_state['fencer_right']['score'] = 0
                current_state['swapped'] = False
                current_state['timer'] = float(current_state['settings']['time_match'])
                current_state['phase'] = 'MATCH'
                current_state['running'] = False
                current_state['priority'] = None
                for s in ['left','right']:
                    current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
                    current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
                updated_current = True
            elif current_match_completed:
                current_state['current_row_idx'] = None
                current_state['fencer_left']['name'] = current_state['settings']['default_name_left']
                current_state['fencer_right']['name'] = current_state['settings']['default_name_right']
                current_state['fencer_left']['photo'] = get_photo_url(current_state['fencer_left']['name'])
                current_state['fencer_right']['photo'] = get_photo_url(current_state['fencer_right']['name'])
                current_state['fencer_left']['score'] = 0
                current_state['fencer_right']['score'] = 0
                current_state['swapped'] = False
                current_state['timer'] = float(current_state['settings']['time_match'])
                current_state['phase'] = 'MATCH'
                current_state['running'] = False
                current_state['priority'] = None
                for s in ['left','right']:
                    current_state[f'fencer_{s}']['cards'] = {"Y":False,"R":False,"B":False,"R_count":0}
                    current_state[f'fencer_{s}']['p_cards'] = {"Y":False,"R":False,"B":False}
                updated_current = True

        cg = current_state.get('current_girone', 'rosso')
        current_state['match_list'] = gironi_cache.get(cg, [])
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
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
                    socketio.emit('upload_status', {'color': 'green'}); eventlet.sleep(5); socketio.emit('upload_status', {'color': 'none'}); return
            except: pass
    socketio.emit('upload_status', {'color': 'red'})