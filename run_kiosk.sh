#!/bin/bash

# Directory base
APP_DIR="$HOME/fencing_scoreboard"
VENV_DIR="$APP_DIR/venv"
LOG_FILE="$HOME/kiosk.log"

# Funzione di log
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "--- AVVIO KIOSK ---"

# Attiva venv
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
else
    log "ERRORE: Virtual environment non trovato in $VENV_DIR"
    exit 1
fi

export DISPLAY=:0

# Pulizia
pkill -f 'python app.py'
pkill chromium
pkill unclutter

# Vai alla cartella
cd "$APP_DIR" || exit 1

# Avvia Server Python e logga output
log "Avvio server Flask..."
python app.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Attesa intelligente del server (max 30 secondi)
log "In attesa che il server (porta 5000) sia pronto..."
attempt=0
while ! nc -z localhost 5000; do   
  sleep 1
  attempt=$((attempt+1))
  if [ $attempt -ge 30 ]; then
      log "TIMEOUT: Il server non ha risposto dopo 30 secondi."
      break
  fi
done

if nc -z localhost 5000; then
    log "Server rilevato attivo!"
else
    log "ATTENZIONE: Avvio browser forzato, ma il server sembra spento."
fi

# Gestione Mouse
IP=$(hostname -I | awk '{print $1}')
if [ -z "$IP" ]; then
    log "Offline mode"
else
    unclutter -idle 0.1 -root &
fi

# Avvio Browser
log "Avvio Chromium..."
# Tenta di trovare il browser corretto
BROWSER_CMD="chromium"
if command -v chromium-browser &> /dev/null; then
    BROWSER_CMD="chromium-browser"
fi

$BROWSER_CMD --noerrdialogs --disable-infobars --kiosk http://localhost:5000 --autoplay-policy=no-user-gesture-required &

# Simulazione click per focus/audio
sleep 10
if command -v xdotool &> /dev/null; then
    xdotool mousemove 1 1 click 1
    xdotool mousemove 2000 2000
fi

wait $SERVER_PID