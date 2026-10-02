#!/bin/bash

# Gestione uscita pulita: termina i processi in background alla chiusura
cleanup() {
    log "Arresto in corso..."
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    [ -n "$DISPLAY_PID" ] && kill "$DISPLAY_PID" 2>/dev/null
    pkill unclutter 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Directory base e variabili
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
pkill chromium 2>/dev/null
pkill unclutter 2>/dev/null

# Vai alla cartella dell'applicazione
cd "$APP_DIR" || {
    log "ERRORE: Cartella non trovata $APP_DIR"
    exit 1
}

# Avvia Server Flask in background
log "Avvio server Flask..."
python app.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Gestione Mouse: nascondi il cursore se connesso alla rete
IP=$(hostname -I | awk '{print $1}')
if [ -n "$IP" ]; then
    unclutter -idle 0.1 -root &
fi

# Avvio App Display Nativa
log "Avvio Display App..."
python kiosk_display.py >> "$LOG_FILE" 2>&1 &
DISPLAY_PID=$!

# Simulazione click per focus/audio (se xdotool è installato)
sleep 10
if command -v xdotool &> /dev/null; then
    xdotool mousemove 1 1 click 1
    xdotool mousemove 2000 2000
fi

# Attende la chiusura dell'interfaccia o del server
wait "$DISPLAY_PID"
