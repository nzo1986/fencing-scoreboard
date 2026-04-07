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
    # Aggiorniamo il timestamp della coccia che è stata toccata
    last_coccia_time[side] = time.time()
    
    # Se la coccia di 'side' è stata toccata, la luce bianca va all'avversario (chi ha toccato)
    opp_side = 'right' if side == 'left' else 'left'
    emit_massa_visual(opp_side, socketio)

def handle_hit_request(side, hit_timestamp, socketio):
    global last_hit_timestamp, hit_sides_in_window
    
    if current_state.get('phase') != 'MATCH': 
        return
        
    # --- BUFFER DI LATENZA (IL SEGRETO DEL WIRELESS) ---
    # Aspettiamo 60 millisecondi prima di elaborare la stoccata.
    # In questo modo, se c'è un tocco sulla coccia, il pacchetto "COCCIA"
    # farà in tempo ad arrivare e annulleremo il punto.
    eventlet.sleep(0.06)
        
    opp_side = 'right' if side == 'left' else 'left'

    # INCROCIO FONDAMENTALE (Lama mia su Coccia sua)
    # Se il timestamp di questa stoccata è vicinissimo al momento in cui
    # la coccia avversaria ha rilevato un contatto: NIENTE PUNTO!
    if abs(hit_timestamp - last_coccia_time[opp_side]) < 0.25:
        emit_massa_visual(side, socketio) # Mostra luce bianca per sicurezza
        return

    # INCROCIO 2 (Lama mia su Coccia mia - anomalia)
    if abs(hit_timestamp - last_coccia_time[side]) < 0.25:
        return

    # Se passa i controlli coccia, valutiamo la stoccata vera e propria.
    # Tolleranza FIE per la Spada: 40-50 millisecondi.
    lockout_ms = 0.050 
    is_within_lockout = (hit_timestamp - last_hit_timestamp <= lockout_ms)

    if current_state['running']:
        # --- PRIMO COLPO ---
        current_state['running'] = False # Ferma il tempo istantaneamente
        last_hit_timestamp = hit_timestamp
        hit_sides_in_window = {side: hit_timestamp}
        
        current_state[f'fencer_{side}']['score'] += 1
            
        socketio.emit('hw_hit', {'side': side, 'is_double': False, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)
        
    elif side not in hit_sides_in_window and is_within_lockout:
        # --- SECONDO COLPO (DOPPIO) ---
        # Entro i 50ms, il tempo era già stato fermato dal primo colpo.
        hit_sides_in_window[side] = hit_timestamp
        
        current_state[f'fencer_{side}']['score'] += 1
            
        socketio.emit('hw_hit', {'side': side, 'is_double': True, 'score_added': True, 'is_manual': False})
        socketio.emit('state_update', current_state)
        socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
        eventlet.spawn(save_state)

    elif not current_state['running']:
        # --- TEST ARMI A TEMPO FERMO ---
        # Se il tempo è fermo da più di 1.5 secondi, fa accendere solo la luce 
        # e fa fare il Bip, ma senza assegnare punti.
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