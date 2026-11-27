#!/bin/bash
export DISPLAY=:0

# 1. Impostazioni anti-stanby per la TV HDMI
xset s off
xset -dpms
xset s noblank

# 2. Nascondi il cursore del mouse
unclutter -idle 0.5 -root &

cd ~/fencing_scoreboard
source venv/bin/activate
python app.py &
sleep 10

# 3. Avvia Chromium in background (la e commerciale & alla fine è fondamentale qui)
chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required http://127.0.0.1:5000 &

# 4. Attendi che Chromium carichi completamente la pagina
sleep 8

# 5. Simula un click del mouse al centro dello schermo (scavalca la richiesta di sblocco audio verde)
xdotool mousemove 500 500 click 1

# Mantiene in vita lo script bash
wait
