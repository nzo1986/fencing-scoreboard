#!/bin/bash

echo "============================================="
echo "   🤺 FENCING SCOREBOARD INSTALLER"
echo "============================================="
echo ""

# 1. Scarica lo script Python di setup (sovrascrivendo se esiste)
echo "⬇️  Scaricamento installer..."
cd /home/pi
wget -q -O setup_fencing_kiosk.py https://raw.githubusercontent.com/nzo1986/fencing-scoreboard/main/setup_fencing_kiosk.py

# 2. Esegue lo script Python
echo "🚀 Avvio installazione..."
python3 setup_fencing_kiosk.py