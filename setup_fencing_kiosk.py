import os
import subprocess
import sys
import time
import shutil

# --- CONFIGURAZIONE ---
REPO_URL = "https://github.com/nzo1986/fencing-scoreboard.git" 
BASE_DIR = os.path.expanduser("~/fencing_scoreboard")
VENV_DIR = os.path.join(BASE_DIR, "venv")
Run_Script = os.path.join(BASE_DIR, "run_kiosk.sh")
AUTOSTART_DIR = os.path.expanduser("~/.config/lxsession/LXDE-pi")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "autostart")

def print_step(msg): print(f"\n\033[1;32m[STEP] {msg}\033[0m")

def run_command(command, shell=True, ignore_errors=False):
    try: subprocess.check_call(command, shell=shell)
    except subprocess.CalledProcessError as e:
        if not ignore_errors:
            print(f"\033[1;31m[ERRORE] Il comando ha fallito: {command}\033[0m")
            sys.exit(1)
        else: print(f"[INFO] Comando fallito (ignorato): {command}")

def check_internet():
    print_step("Controllo connessione Internet...")
    try:
        subprocess.check_call(["ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
        print("Connessione OK.")
        return True
    except:
        print("\033[1;33m[AVVISO] Nessuna connessione internet. Avvio offline.\033[0m")
        return False

def install_system_dependencies():
    print_step("Installazione dipendenze di sistema (apt)...")
    packages = "git xserver-xorg x11-xserver-utils xinit openbox python3-pip python3-venv python3-dev chromium xdotool unclutter network-manager fontconfig wireless-tools"
    run_command("sudo apt-get update", ignore_errors=True)
    run_command(f"sudo apt-get install -y --no-install-recommends {packages}", ignore_errors=True)

def fix_chromium_compatibility():
    print_step("Verifica compatibilità Browser...")
    browser_check = subprocess.call("which chromium-browser", shell=True, stdout=subprocess.DEVNULL)
    if browser_check != 0:
        chromium_check = subprocess.call("which chromium", shell=True, stdout=subprocess.DEVNULL)
        if chromium_check == 0:
            path = subprocess.check_output("which chromium", shell=True).decode().strip()
            run_command(f"sudo ln -sf {path} /usr/bin/chromium-browser", ignore_errors=True)

def setup_repository(has_internet):
    print_step("Sincronizzazione Codice da GitHub...")
    if not has_internet: return

    if os.path.exists(BASE_DIR):
        if os.path.exists(os.path.join(BASE_DIR, ".git")):
            os.chdir(BASE_DIR)
            temp_state1, temp_state2 = "/tmp/match_state.json", "/tmp/local_match_state.json"
            if os.path.exists("match_state.json"): shutil.copy2("match_state.json", temp_state1)
            if os.path.exists("local_match_state.json"): shutil.copy2("local_match_state.json", temp_state2)
            
            run_command("git fetch origin")
            run_command("git reset --hard origin/main")
            
            if os.path.exists(temp_state1): shutil.copy2(temp_state1, "match_state.json")
            if os.path.exists(temp_state2): shutil.copy2(temp_state2, "local_match_state.json")
        else:
            timestamp = int(time.time())
            backup_dir = f"{BASE_DIR}_backup_{timestamp}"
            os.rename(BASE_DIR, backup_dir)
            run_command(f"git clone {REPO_URL} {BASE_DIR}")
            os.chdir(BASE_DIR)
            old_photos, new_photos = os.path.join(backup_dir, "static", "photos"), os.path.join(BASE_DIR, "static", "photos")
            if not os.path.exists(new_photos): os.makedirs(new_photos)
            if os.path.exists(old_photos):
                try:
                    for item in os.listdir(old_photos):
                        s = os.path.join(old_photos, item)
                        if os.path.isfile(s): shutil.copy2(s, os.path.join(new_photos, item))
                except: pass
            for file_name in ["match_state.json", "local_match_state.json"]:
                if os.path.exists(os.path.join(backup_dir, file_name)): shutil.copy2(os.path.join(backup_dir, file_name), os.path.join(BASE_DIR, file_name))
    else:
        run_command(f"git clone {REPO_URL} {BASE_DIR}")
        os.chdir(BASE_DIR)

def setup_python_environment():
    print_step("Configurazione Ambiente Python (venv)...")
    if not os.path.exists(VENV_DIR): run_command(f"python3 -m venv {VENV_DIR}")
    pip_bin = os.path.join(VENV_DIR, "bin", "pip")
    pkgs = "Flask Flask-SocketIO eventlet requests werkzeug simple-websocket"
    run_command(f"{pip_bin} install --upgrade {pkgs}", ignore_errors=True)

def ensure_local_dirs():
    print_step("Verifica cartelle locali e file di avvio...")
    if not os.path.exists(os.path.join(BASE_DIR, "static", "photos")): os.makedirs(os.path.join(BASE_DIR, "static", "photos"))
    if not os.path.exists(os.path.join(BASE_DIR, "pico_code")): os.makedirs(os.path.join(BASE_DIR, "pico_code"))
    
    # Script Bash aggiornato con Auto-Click per saltare la schermata di Inizializzazione Audio
    run_script_content = """#!/bin/bash
export DISPLAY=:0

# 1. Impostazioni anti-stanby per la TV HDMI
xset s off
xset -dpms
xset s noblank

# 2. Nascondi il cursore del mouse
unclutter -idle 0.5 -root &

# --- FIX CRASH CHROMIUM (Sblocca il profilo se l'hostname e' cambiato) ---
rm -rf ~/.config/chromium/Singleton*
# -------------------------------------------------------------------------

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
"""
    with open(Run_Script, "w") as f: f.write(run_script_content)
    run_command(f"chmod +x {Run_Script}")

def configure_autostart():
    print_step("Configurazione Avvio Automatico (Autostart)...")
    if not os.path.exists(AUTOSTART_DIR): os.makedirs(AUTOSTART_DIR)
    autostart_content = f"@lxpanel --profile LXDE-pi\n@pcmanfm --desktop --profile LXDE-pi\n@xscreensaver -no-splash\n@lxterminal -e bash {Run_Script}\n"
    try:
        with open(AUTOSTART_FILE, "w") as f: f.write(autostart_content)
    except: pass

def restart_service():
    print_step("Riavvio Applicazione...")
    run_command("pkill -f 'python app.py'", ignore_errors=True)
    run_command("pkill chromium", ignore_errors=True)
    time.sleep(2)
    subprocess.Popen(f"nohup {Run_Script} >/dev/null 2>&1 &", shell=True, preexec_fn=os.setpgrp)

def main():
    print("\n=========================================\n   SCHERMA KIOSK SETUP & UPDATE TOOL\n=========================================")
    has_internet = check_internet()
    if has_internet:
        install_system_dependencies()
        fix_chromium_compatibility()
    setup_repository(has_internet)
    setup_python_environment()
    ensure_local_dirs()
    configure_autostart()
    restart_service()
    print("\n\033[1;32m[SUCCESS] Installazione completata! Il sistema si sta avviando.\033[0m")

if __name__ == "__main__":
    main()