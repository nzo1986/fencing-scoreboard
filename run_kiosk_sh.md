#!/bin/bash

# Directory base
APP_DIR="$HOME/fencing_scoreboard"
VENV_DIR="$APP_DIR/venv"
LOG_FILE="$HOME/kiosk.log"

# Funzione di log
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "--- AVVIO KIOSK CON APP NATIVA ---"

# Attiva venv
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
else
    log "ERRORE: Virtual environment non trovato in $VENV_DIR"
    exit 1
fi

export DISPLAY=:0

# Pulizia processi precedenti
pkill -f 'python app.py'
pkill -f 'python kiosk_display.py'
pkill chromium
pkill unclutter

# Vai alla cartella
cd "$APP_DIR" || exit 1

# Avvia Server Python e logga output
log "Avvio server Flask..."
python app.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Gestione Mouse (sicurezza aggiuntiva)
IP=$(hostname -I | awk '{print $1}')
if [ -n "$IP" ]; then
    unclutter -idle 0.1 -root &
fi

# Avvio App Display Nativa (Invece di Chromium)
log "Avvio Display App..."
python kiosk_display.py &

# Simulazione click per focus/audio (se necessario)
sleep 10
if command -v xdotool &> /dev/null; then
    xdotool mousemove 1 1 click 1
    xdotool mousemove 2000 2000
fi

wait $SERVER_PID