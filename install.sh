#!/bin/bash

echo "="
echo "   🤺 FENCING SCOREBOARD INSTALLER"
echo "="
echo ""

echo "⬇️  Scaricamento installer aggiornato da GitHub..."
cd "$HOME" || exit 1
wget -q -O setup_fencing_kiosk.py https://raw.githubusercontent.com/nzo1986/fencing-scoreboard/main/setup_fencing_kiosk.py

echo "🚀 Avvio configurazione interattiva..."
python3 setup_fencing_kiosk.py
