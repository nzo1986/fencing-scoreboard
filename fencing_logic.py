import time
import eventlet
from config_state import current_state, save_state

last_hit_timestamp = 0
first_hit_side = None
hit_sides_in_window = {}
last_massa_emit = {'left': 0, 'right': 0}
last_coccia_time = {'left': 0, 'right': 0}

def register_coccia(side):
    global last_coccia_time
    last_coccia_time[side] = time.time()

def emit_massa_visual(side, socketio):
    global last_massa_emit
    now = time.time()
    if now - last_massa_emit[side] > 0.3:
        socketio.emit('hw_massa', {'side': side})
        last_massa_emit[side] = now

def handle_hit_request(side, hit_timestamp, socketio, hit_type="HIT"):
    opp_side = 'right' if side == 'left' else 'left'
    weapon = current_state['settings'].get('weapon', 'spada')
    
    if weapon == 'spada' and hit_type == 'HIT':
        eventlet.sleep(0.08)
        if abs(last_coccia_time[opp_side] - hit_timestamp) < 0.3:
            emit_massa_visual(side, socketio)
            return

    evaluate_valid_hit(side, hit_timestamp, socketio, hit_type)

def evaluate_valid_hit(side, hit_timestamp, socketio, hit_type):
    global last_hit_timestamp, hit_sides_in_window, first_hit_side
    
    if current_state.get('phase') != 'MATCH': 
        return
        
    weapon = current_state['settings'].get('weapon', 'spada')
    
    lockout_ms = 0.045
    if weapon == 'fioretto': lockout_ms = 0.300
    elif weapon == 'sciabola': lockout_ms = 0.170 
    
    is_within_lockout = (hit_timestamp - last_hit_timestamp <= lockout_ms)

    if current_state['running']:
        current_state['running'] = False
        last_hit_timestamp = hit_timestamp
        first_hit_side = side
        hit_sides_in_window = {side: hit_timestamp}
        
        if weapon == 'spada':
            current_state[f'fencer_{side}']['score'] += 1
            score_added = True
        else:
            score_added = False
            
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': score_added, 'is_manual': False, 'hit_type': hit_type})
        socketio.emit('state_update', current_state)
        
        color = "Rosso" if side == "left" else "Verde"
        t_type = "Valida" if hit_type == "HIT" else "Non Valida (Bianca)"
        icon = "🎯" if hit_type == "HIT" else "⚪"
        socketio.emit('debug_log', {'time': time.strftime('%H:%M:%S'), 'ip': 'SYS', 'msg': f"{icon} Stoccata: {color} [{t_type}]"})
        
        eventlet.spawn(save_state)
        
    elif side not in hit_sides_in_window and is_within_lockout:
        hit_sides_in_window[side] = hit_timestamp
        diff_ms = int((hit_timestamp - last_hit_timestamp) * 1000)
        
        if weapon == 'spada':
            current_state[f'fencer_{side}']['score'] += 1
            score_added = True
        else:
            score_added = False
            
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': score_added, 'is_manual': False, 'hit_type': hit_type})
        socketio.emit('state_update', current_state)
        
        first_color = "Rosso" if first_hit_side == "left" else "Verde"
        second_color = "Rosso" if side == "left" else "Verde"
        t_type = "Valida" if hit_type == "HIT" else "Non Valida (Bianca)"
        icon = "🎯" if hit_type == "HIT" else "⚪"
        socketio.emit('debug_log', {'time': time.strftime('%H:%M:%S'), 'ip': 'SYS', 'msg': f"⚔️ Doppia: {first_color} > {diff_ms}ms > {second_color} [{t_type}]"})
        
        eventlet.spawn(save_state)

    elif not current_state['running']:
        if (hit_timestamp - last_hit_timestamp) > 1.5:
            socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': False, 'is_manual': False, 'hit_type': hit_type})
            last_hit_timestamp = hit_timestamp

def apply_card(side, card_type, socketio):
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
                        red_count = 1; opponent['score'] += 1
                else:
                    if red_count < 2: red_count += 1
                    opponent['score'] += 1
            fencer['cards']['R_count'] = red_count
            fencer['cards']['R'] = (red_count > 0)

    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)