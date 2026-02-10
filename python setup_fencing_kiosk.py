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

# Percorsi Autostart LXDE
AUTOSTART_DIR = os.path.expanduser("~/.config/lxsession/LXDE-pi")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "autostart")

def print_step(msg):
    print(f"\n\033[1;32m[STEP] {msg}\033[0m")

def run_command(command, shell=True, ignore_errors=False):
    """Esegue comandi shell gestendo gli errori."""
    try:
        subprocess.check_call(command, shell=shell)
    except subprocess.CalledProcessError as e:
        if not ignore_errors:
            print(f"\033[1;31m[ERRORE] Il comando ha fallito: {command}\033[0m")
            sys.exit(1)
        else:
            print(f"[INFO] Comando fallito (ignorato): {command}")

def check_internet():
    print_step("Controllo connessione Internet...")
    try:
        subprocess.check_call(["ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
        print("Connessione OK.")
    except:
        print("\033[1;31m[ERRORE] Nessuna connessione internet. Impossibile scaricare l'app.\033[0m")
        sys.exit(1)

def install_system_dependencies():
    print_step("Installazione dipendenze di sistema (apt)...")
    
    packages = (
        "git "
        "xserver-xorg x11-xserver-utils xinit openbox "
        "python3-pip python3-venv python3-dev "
        "chromium xdotool unclutter "
        "network-manager fontconfig wireless-tools"
    )
    
    run_command("sudo apt-get update")
    run_command(f"sudo apt-get install -y --no-install-recommends {packages}")

def fix_chromium_compatibility():
    print_step("Verifica compatibilità Browser...")
    browser_check = subprocess.call("which chromium-browser", shell=True, stdout=subprocess.DEVNULL)
    
    if browser_check != 0:
        chromium_check = subprocess.call("which chromium", shell=True, stdout=subprocess.DEVNULL)
        if chromium_check == 0:
            print("Creo symlink: chromium-browser -> chromium")
            path = subprocess.check_output("which chromium", shell=True).decode().strip()
            run_command(f"sudo ln -sf {path} /usr/bin/chromium-browser", ignore_errors=True)
        else:
            print("\033[1;33m[WARNING] Ne 'chromium' ne 'chromium-browser' trovati.\033[0m")
    else:
        print("Browser command OK.")

def setup_repository():
    print_step("Sincronizzazione Codice da GitHub...")
    
    if os.path.exists(BASE_DIR):
        if os.path.exists(os.path.join(BASE_DIR, ".git")):
            print(f"Repository Git rilevato in {BASE_DIR}. Aggiorno...")
            os.chdir(BASE_DIR)
            run_command("git fetch origin")
            run_command("git reset --hard origin/main")
        else:
            print(f"\033[1;33m[AVVISO] La cartella {BASE_DIR} esiste ma non è collegata a GitHub.\033[0m")
            timestamp = int(time.time())
            backup_dir = f"{BASE_DIR}_backup_{timestamp}"
            print(f"Sposto la vecchia cartella in: {backup_dir}")
            os.rename(BASE_DIR, backup_dir)
            
            print(f"Clonazione pulita da {REPO_URL}...")
            run_command(f"git clone {REPO_URL} {BASE_DIR}")
            os.chdir(BASE_DIR)
            
            # --- RECUPERO DATI DAL BACKUP ---
            print_step("Ripristino dati dal backup...")
            old_photos = os.path.join(backup_dir, "static", "photos")
            new_photos = os.path.join(BASE_DIR, "static", "photos")
            
            if not os.path.exists(new_photos):
                os.makedirs(new_photos)

            if os.path.exists(old_photos):
                try:
                    for item in os.listdir(old_photos):
                        s = os.path.join(old_photos, item)
                        d = os.path.join(new_photos, item)
                        if os.path.isfile(s):
                            shutil.copy2(s, d)
                    print(f"Foto ripristinate.")
                except Exception as e:
                    print(f"Errore ripristino foto: {e}")
            
            old_state = os.path.join(backup_dir, "match_state.json")
            new_state = os.path.join(BASE_DIR, "match_state.json")
            if os.path.exists(old_state):
                shutil.copy2(old_state, new_state)
                print("Stato partita (punti/nomi) ripristinato.")

    else:
        print(f"Clonazione nuovo repository da {REPO_URL}...")
        run_command(f"git clone {REPO_URL} {BASE_DIR}")
        os.chdir(BASE_DIR)

    if os.path.exists(Run_Script):
        run_command(f"chmod +x {Run_Script}")

def setup_python_environment():
    print_step("Configurazione Ambiente Python (venv)...")
    
    if not os.path.exists(VENV_DIR):
        print("Creazione virtual environment...")
        run_command(f"python3 -m venv {VENV_DIR}")
    
    pip_bin = os.path.join(VENV_DIR, "bin", "pip")
    
    # Installazione librerie con versioni compatibili
    print("Installazione librerie Python...")
    pkgs = "Flask Flask-SocketIO eventlet requests werkzeug simple-websocket"
    run_command(f"{pip_bin} install --upgrade {pkgs}")

def ensure_local_dirs():
    print_step("Verifica cartelle locali...")
    photos_dir = os.path.join(BASE_DIR, "static", "photos")
    if not os.path.exists(photos_dir):
        os.makedirs(photos_dir)
        print(f"Creata cartella {photos_dir}")

def configure_autostart():
    print_step("Configurazione Avvio Automatico (Autostart)...")
    
    if not os.path.exists(AUTOSTART_DIR):
        os.makedirs(AUTOSTART_DIR)
        print(f"Creata directory {AUTOSTART_DIR}")

    # Ottieni il percorso assoluto dello script corrente (questo file python)
    current_script = os.path.abspath(__file__)
    
    # Contenuto del file autostart
    # Usa @lxterminal -e per mostrare il processo di aggiornamento all'avvio
    autostart_content = f"""@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xscreensaver -no-splash
@lxterminal -e python3 {current_script}
"""
    
    # Scrivi il file
    try:
        with open(AUTOSTART_FILE, "w") as f:
            f.write(autostart_content)
        print(f"✅ Autostart configurato in: {AUTOSTART_FILE}")
        print(f"   Al riavvio verrà eseguito: {current_script}")
    except Exception as e:
        print(f"\033[1;31m[ERRORE] Impossibile scrivere autostart: {e}\033[0m")

def restart_service():
    print_step("Riavvio Applicazione...")
    
    run_command("pkill -f 'python app.py'", ignore_errors=True)
    run_command("pkill chromium", ignore_errors=True)
    
    time.sleep(2)
    
    print("Avvio run_kiosk.sh in background...")
    subprocess.Popen(
        f"nohup {Run_Script} >/dev/null 2>&1 &", 
        shell=True, 
        preexec_fn=os.setpgrp
    )

def main():
    print("\n=========================================")
    print("   SCHERMA KIOSK SETUP & UPDATE TOOL")
    print("=========================================")
    
    check_internet()
    install_system_dependencies()
    fix_chromium_compatibility()
    setup_repository()
    setup_python_environment()
    ensure_local_dirs()
    
    # Nuova funzione che imposta l'avvio automatico
    configure_autostart()
    
    restart_service()

    print("\n\033[1;32m[SUCCESS] Installazione completata! Il sistema si sta avviando.\033[0m")
    print("Se non vedi il browser entro 30 secondi, controlla i log o riavvia.")

if __name__ == "__main__":
    main()