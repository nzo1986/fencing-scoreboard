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
    # Emette la luce bianca solo se è passato almeno un terzo di secondo dall'ultima 
    # per evitare che sfarfalli troppo velocemente
    if now - last_massa_emit[side] > 0.3:
        socketio.emit('hw_massa', {'side': side})
        last_massa_emit[side] = now

def handle_hit_request(side, hit_timestamp, socketio):
    opp_side = 'right' if side == 'left' else 'left'

    # Attesa millimetrica (80ms) per dare tempo al pacchetto UDP della coccia di arrivare
    eventlet.sleep(0.08)

    # Se è stato toccato il bersaglio non valido (Coccia avversaria)
    # in una finestra di ± 300 millisecondi, annulliamo il punto ed emettiamo il bagliore bianco.
    if abs(last_coccia_time[opp_side] - hit_timestamp) < 0.3:
        emit_massa_visual(side, socketio)
        return

    # Altrimenti, proseguiamo alla valutazione del punto valido
    evaluate_valid_hit(side, hit_timestamp, socketio)

def evaluate_valid_hit(side, hit_timestamp, socketio):
    global last_hit_timestamp, hit_sides_in_window
    
    if current_state.get('phase') != 'MATCH': 
        return
        
    weapon = current_state['settings'].get('weapon', 'spada')
    lockout_ms = 0.045 # Spada: 45ms di tolleranza (Colpo Doppio)
    if weapon == 'fioretto': lockout_ms = 0.300
    elif weapon == 'sciabola': lockout_ms = 0.170 
    
    # Verifica se siamo all'interno della finestra di lockout
    is_within_lockout = (hit_timestamp - last_hit_timestamp <= lockout_ms)

    if current_state['running']:
        # PRIMO COLPO
        current_state['running'] = False
        last_hit_timestamp = hit_timestamp
        hit_sides_in_window = {side}
        current_state[f'fencer_{side}']['score'] += 1
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)
        
    elif side not in hit_sides_in_window and is_within_lockout:
        # SECONDO COLPO (DOPPIO): Arrivato entro i 45ms!
        hit_sides_in_window.add(side)
        current_state[f'fencer_{side}']['score'] += 1
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)

    elif not current_state['running']:
        # ASSALTO FERMO O COLPO FUORI TEMPO MAX
        # Se è passato più di 1.5 secondi dall'ultimo colpo, permette il "test armi" a vuoto
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