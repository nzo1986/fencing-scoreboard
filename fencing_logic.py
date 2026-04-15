import eventlet
from config_state import current_state, save_state

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
        
        if card_type == 'B': 
            fencer['cards']['B'] = True
        elif card_type in ['Y', 'R']:
            if not has_black:
                if not has_yellow and red_count == 0:
                    if card_type == 'Y': 
                        fencer['cards']['Y'] = True
                    elif card_type == 'R':
                        red_count = 1
                        opponent['score'] += 1
                else:
                    if red_count < 2: 
                        red_count += 1
                    opponent['score'] += 1
                    
            fencer['cards']['R_count'] = red_count
            fencer['cards']['R'] = (red_count > 0)

    socketio.emit('state_update', current_state)
    socketio.emit('timer_update', {'time': current_state['timer'], 'phase': current_state.get('phase')})
    eventlet.spawn(save_state)