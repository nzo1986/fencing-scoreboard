#!/bin/bash

APP_DIR="$HOME/fencing_scoreboard"
VENV_DIR="$APP_DIR/venv"
LOG_FILE="$HOME/kiosk.log"

cleanup() {
    # Evita loop ricorsivi del trap su EXIT
    trap - SIGINT SIGTERM EXIT
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    [ -n "$BROWSER_PID" ] && kill "$BROWSER_PID" 2>/dev/null
    pkill unclutter 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

export DISPLAY=:0

# Disattiva risparmio energetico schermo
xset s off
xset -dpms
xset s noblank

# Pulisce processi precedenti
pkill -f "python.*app.py" 2>/dev/null
pkill -f "chromium" 2>/dev/null
pkill unclutter 2>/dev/null

# Nasconde cursore
unclutter -idle 0.5 -root &

cd "$APP_DIR" || { echo "Errore: cartella $APP_DIR non trovata" >> "$LOG_FILE"; exit 1; }
source "$VENV_DIR/bin/activate" || { echo "Errore: virtualenv non trovato" >> "$LOG_FILE"; exit 1; }

# Legge URL scelto durante il setup (default: /pannello)
START_URL="http://127.0.0.1:5000/pannello"
if [ -f "$APP_DIR/startup_url.txt" ]; then
    # tr rimuove eventuali a capo o spazi residui nel file di testo
    START_URL=$(tr -d '[:space:]' < "$APP_DIR/startup_url.txt")
fi

# Avvia Server Flask
python app.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# Attende avvio di Flask sulla porta 5000 (max 30 secondi)
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:5000 >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Determina l'eseguibile di Chromium
CHROME_BIN="chromium"
if ! command -v chromium &> /dev/null; then
    CHROME_BIN="chromium-browser"
fi

# Evita banner di ripristino sessione dopo spegnimento
PREFS_FILE="$HOME/.config/chromium/Default/Preferences"
if [ -f "$PREFS_FILE" ]; then
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' "$PREFS_FILE" 2>/dev/null
    sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' "$PREFS_FILE" 2>/dev/null
fi

# Avvia Chromium Kiosk senza popup di traduzione
"$CHROME_BIN" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-translate \
    --disable-features=Translate,TranslateUI,OptimizationHints,MediaRouter \
    --no-first-run \
    --fast \
    --fast-start \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000 \
    "$START_URL" >/dev/null 2>&1 &
BROWSER_PID=$!

# Attende il caricamento della pagina e simula un click per il focus/autoplay
sleep 6
if command -v xdotool &> /dev/null; then
    xdotool mousemove 10 10 click 1
fi

# Mantiene lo script attivo finché il server Flask o il browser sono in esecuzione
wait "$SERVER_PID"
