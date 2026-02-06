#!/bin/bash

# Directory del progetto
APP_DIR="$HOME/fencing_scoreboard"
VENV_DIR="$APP_DIR/venv"

# Attiva l'ambiente virtuale
source "$VENV_DIR/bin/activate"

# Imposta il display (necessario per comandi grafici)
export DISPLAY=:0

# Cleanup di vecchie sessioni
pkill -f 'python app.py'
pkill chromium
pkill unclutter

# Avvia il server Flask in background
cd "$APP_DIR"
python app.py &
SERVER_PID=$!

# Attendi che il server sia pronto
sleep 7

# Gestione cursore mouse
# Se c'è una rete attiva (IP assegnato), nasconde il mouse.
# Altrimenti lo lascia visibile per debug.
IP=$(hostname -I | awk '{print $1}')

if [ -z "$IP" ]; then
    echo "Offline: Mouse visibile"
else
    echo "Online: Nascondo mouse"
    unclutter -idle 0.1 -root &
fi

# Avvia Chromium in modalità Kiosk
chromium-browser --noerrdialogs --disable-infobars --kiosk http://localhost:5000 --autoplay-policy=no-user-gesture-required &
# Se chromium-browser non funziona sul tuo sistema, prova solo 'chromium'

# Simula click per attivare l'audio e togliere il focus da eventuali popup
sleep 15
xdotool mousemove 1 1 click 1
xdotool mousemove 2000 2000

# Attendi che il processo python termini (mantiene lo script attivo)
wait $SERVER_PID    