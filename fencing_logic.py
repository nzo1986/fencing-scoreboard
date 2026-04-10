import time
import eventlet
from config_state import current_state, save_state

last_hit_timestamp = 0
hit_sides_in_window = {}
exchange_can_score = False 

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
    
    # Segnala visivamente che la coccia è stata toccata
    # La luce bianca va all'avversario (chi ha toccato)
    opp_side = 'right' if side == 'left' else 'left'
    emit_massa_visual(opp_side, socketio)

def handle_hit_request(side, hit_timestamp, socketio):
    global last_hit_timestamp, hit_sides_in_window, exchange_can_score
    
    if current_state.get('phase') != 'MATCH': 
        return
        
    # BUFFER DI LATENZA: Attende 60ms per permettere ai pacchetti 'COCCIA' di arrivare via Wi-Fi
    eventlet.sleep(0.06)
        
    opp_side = 'right' if side == 'left' else 'left'

    # Se c'è un tocco sulla coccia avvenuto quasi in contemporanea, ANNULLA PUNTO
    if abs(hit_timestamp - last_coccia_time[opp_side]) < 0.25:
        emit_massa_visual(side, socketio)
        return

    # Corto circuito lama propria su coccia propria
    if abs(hit_timestamp - last_coccia_time[side]) < 0.25:
        return

    # Tolleranza per colpo doppio FIE Spada: 45-50ms
    lockout_ms = 0.050 
    is_within_lockout = (hit_timestamp - last_hit_timestamp <= lockout_ms)

    if current_state['running']:
        # PRIMO COLPO
        current_state['running'] = False 
        last_hit_timestamp = hit_timestamp
        hit_sides_in_window = {side: hit_timestamp}
        exchange_can_score = True 
        
        current_state[f'fencer_{side}']['score'] += 1
            
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)
        
    elif side not in hit_sides_in_window and is_within_lockout:
        # DOPPIO (entro 50ms)
        hit_sides_in_window[side] = hit_timestamp
        
        if exchange_can_score:
            current_state[f'fencer_{side}']['score'] += 1
            socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True, 'is_manual': False})
            socketio.emit('state_update', current_state)
            socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
            eventlet.spawn(save_state)
        else:
            # Doppio a tempo fermo (test armi, nessun punto)
            socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': False, 'is_manual': False})

    elif not current_state['running']:
        # TEST ARMI (tempo fermo, nessun punto)
        if (hit_timestamp - last_hit_timestamp) > 1.5:
            exchange_can_score = False 
            last_hit_timestamp = hit_timestamp
            hit_sides_in_window = {side: hit_timestamp}
            
            socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': False, 'is_manual': False})

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