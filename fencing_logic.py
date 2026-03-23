import time
import eventlet
from config_state import current_state, save_state

last_hit_timestamp = 0
hit_sides_in_window = set()
last_massa_emit = {'left': 0, 'right': 0}
last_coccia_time = {'left': 0, 'right': 0}

def register_coccia(side):
    global last_coccia_time
    last_coccia_time[side] = time.time()

def emit_massa_visual(side, socketio):
    global last_massa_emit
    now = time.time()
    if now - last_massa_emit[side] > 0.5:
        socketio.emit('hw_massa', {'side': side})
        last_massa_emit[side] = now

def handle_hit_request(side, hit_timestamp, socketio):
    opp_side = 'right' if side == 'left' else 'left'
    
    # Pausa di 40ms per compensare la latenza del Wi-Fi e aspettare il segnale della coccia avversaria
    eventlet.sleep(0.04)
    
    if abs(last_coccia_time[opp_side] - hit_timestamp) < 0.1:
        emit_massa_visual(side, socketio)
        return
        
    evaluate_valid_hit(side, hit_timestamp, socketio)

def evaluate_valid_hit(side, hit_timestamp, socketio):
    global last_hit_timestamp, hit_sides_in_window
    if current_state.get('phase') != 'MATCH': return
    
    if not current_state['running']:
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
        eventlet.spawn(save_state)
        
    elif side not in hit_sides_in_window and (hit_timestamp - last_hit_timestamp <= lockout_ms):
        hit_sides_in_window.add(side)
        current_state[f'fencer_{side}']['score'] += 1
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)

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
                        red_count = 1
                        opponent['score'] += 1
                else:
                    if red_count < 2: red_count += 1
                    opponent['score'] += 1
            fencer['cards']['R_count'] = red_count
            fencer['cards']['R'] = (red_count > 0)

    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)