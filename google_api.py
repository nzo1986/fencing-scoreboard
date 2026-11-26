import requests, csv, time
from config_state import (
    current_state,
    gironi_cache,
    GIRONI_MAP_READ,
    default_columns,
    letter_to_index,
    clean_fencer_name,
    get_photo_url,
    save_state,
    DEFAULT_SHEET_ID
)

def check_internet():
    try:
        requests.get('https://www.google.com', timeout=2)
        return True
    except Exception:
        return False

def check_google():
    sid = current_state['settings'].get('google_sheet_id', '').strip()
    if not sid:
        sid = DEFAULT_SHEET_ID
    if not current_state['settings'].get('google_script_url'):
        return "missing"
    if not check_internet():
        return "error"
    return "ok"

def parse_score_info(val):
    s = str(val or '').strip().upper()
    has_v = s.startswith('V')
    num_str = s[1:].strip() if has_v else s
    try:
        num = int(float(num_str)) if num_str != '' else 0
    except Exception:
        num = 0
    return num, has_v, s

def safe_get(lst, idx, default=""):
    return lst[idx].strip() if idx < len(lst) else default

def update_all_gironi_data(socketio):
    try:
        sid = current_state['settings'].get('google_sheet_id', '').strip()
        if not sid:
            sid = DEFAULT_SHEET_ID
        rows_data = None
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
            lines = r.text.strip().split('\n')
            rows_data = []
            for line in lines:
                parsed_line = list(csv.reader([line]))
                rows_data.append(parsed_line[0] if parsed_line else [])

        new_cache = {k: [] for k in GIRONI_MAP_READ.keys()}
        cols_map = current_state['settings'].get('columns', default_columns)
        
        for i, p in enumerate(rows_data[1:37]):  # Si ferma esattamente alla riga 37 
            row_idx = i + 2
            if not p:
                continue
            
            for girone in GIRONI_MAP_READ.keys():
                g_cols = cols_map.get(girone)
                if not g_cols:
                    continue
                
                idx_sx = letter_to_index(g_cols['sx'])
                idx_psx = letter_to_index(g_cols['psx'])
                idx_pdx = letter_to_index(g_cols['pdx'])
                idx_dx = letter_to_index(g_cols['dx'])
                
                name_sx = clean_fencer_name(safe_get(p, idx_sx))
                name_dx = clean_fencer_name(safe_get(p, idx_dx))

                if name_sx and name_dx and not name_sx.isdigit() and not name_dx.isdigit() and len(name_sx) >= 2 and len(name_dx) >= 2:
                    p_sx = safe_get(p, idx_psx) or "0"
                    p_dx = safe_get(p, idx_pdx) or "0"
                    new_cache[girone].append({"sx": name_sx, "p_sx": p_sx, "p_dx": p_dx, "dx": name_dx, "row": row_idx})
        
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
                    p_sx, v_sx, _ = parse_score_info(m.get('p_sx', '0'))
                    p_dx, v_dx, _ = parse_score_info(m.get('p_dx', '0'))
                    if p_sx != 0 or p_dx != 0 or v_sx or v_dx:
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
                p_sx, v_sx, _ = parse_score_info(m.get('p_sx', '0'))
                p_dx, v_dx, _ = parse_score_info(m.get('p_dx', '0'))
                if p_sx == 0 and p_dx == 0 and not v_sx and not v_dx:
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
                for s in ['left', 'right']:
                    current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
                    current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
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
                for s in ['left', 'right']:
                    current_state[f'fencer_{s}']['cards'] = {"Y": False, "R": False, "B": False, "R_count": 0}
                    current_state[f'fencer_{s}']['p_cards'] = {"Y": False, "R": False, "B": False}
                updated_current = True

        cg = current_state.get('current_girone', 'rosso')
        current_state['match_list'] = gironi_cache.get(cg, [])
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        if updated_current:
            socketio.start_background_task(save_state)
    except Exception as e:
        print(f"Update error: {e}")

def process_background_upload(payload, girone, socketio):
    try:
        url = current_state['settings']['google_script_url']
        r = requests.post(url, json=payload, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code != 200 or "success" not in r.text:
            socketio.emit('upload_status', {'color': 'red'})
            return
    except Exception:
        socketio.emit('upload_status', {'color': 'red'})
        return

    for wait_time in [10, 30, 60]:
        if wait_time > 10:
            socketio.emit('upload_status', {'color': 'yellow'})
        socketio.sleep(wait_time)
        update_all_gironi_data(socketio)
        match_data = next((m for m in gironi_cache.get(girone, []) if m['row'] == int(payload['row'])), None)
        if match_data:
            try:
                msx, mvsx, _ = parse_score_info(match_data.get('p_sx', '0'))
                mdx, mvdx, _ = parse_score_info(match_data.get('p_dx', '0'))
                vsx, vvsx, _ = parse_score_info(payload.get('val_sx', '0'))
                vdx, vvdx, _ = parse_score_info(payload.get('val_dx', '0'))
                
                if msx == vsx and mdx == vdx and mvsx == vvsx and mvdx == vvdx:
                    socketio.emit('upload_status', {'color': 'green'})
                    socketio.sleep(5)
                    socketio.emit('upload_status', {'color': 'none'})
                    return
            except Exception:
                pass
            
    socketio.emit('upload_status', {'color': 'red'})
