import time
import eventlet
from config_state import current_state, save_state

last_hit_timestamp = 0
hit_sides_in_window = {}

last_massa_emit = {'left': 0, 'right': 0}
last_coccia_time = {'left': 0, 'right': 0}

def emit_massa_visual(side, socketio):
    global last_massa_emit
    now = time.time()
    if now - last_massa_emit[side] > 0.5: 
        socketio.emit('hw_massa', {'side': side})
        last_massa_emit[side] = now

def register_coccia(side, socketio):
    global last_coccia_time
    last_coccia_time[side] = time.time()
    emit_massa_visual(side, socketio)

def handle_hit_request(side, hit_timestamp, socketio):
    global last_hit_timestamp, hit_sides_in_window
    
    if current_state.get('phase') != 'MATCH': 
        return
        
    opp_side = 'right' if side == 'left' else 'left'

    # INCROCIO FONDAMENTALE: 
    # Se il ROSSO invia "HIT", ma la coccia del VERDE (opp_side) è stata toccata di recente,
    # significa che il ROSSO è sulla coccia del VERDE. IL PUNTO DEVE ESSERE ANNULLATO!
    if abs(hit_timestamp - last_coccia_time[opp_side]) < 0.25:
        return

    # INCROCIO 2: Corto circuito sull'arma stessa (Lama su propria coccia)
    if abs(hit_timestamp - last_coccia_time[side]) < 0.25:
        return

    # Se passa i controlli coccia, valutiamo il punto/doppio
    lockout_ms = 0.045 # Spada: 45ms per doppio
    is_within_lockout = (hit_timestamp - last_hit_timestamp <= lockout_ms)

    if current_state['running']:
        # Primo colpo
        current_state['running'] = False
        last_hit_timestamp = hit_timestamp
        hit_sides_in_window = {side: hit_timestamp}
        
        current_state[f'fencer_{side}']['score'] += 1
            
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)
        
    elif side not in hit_sides_in_window and is_within_lockout:
        # Secondo colpo (Doppio) entro 45ms
        hit_sides_in_window[side] = hit_timestamp
        
        current_state[f'fencer_{side}']['score'] += 1
            
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)

    elif not current_state['running']:
        # Test armi (dopo 1.5s dall'ultimo colpo non da punto, fa solo luce)
        if (hit_timestamp - last_hit_timestamp) > 1.5:
            socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': False, 'is_manual': False})
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