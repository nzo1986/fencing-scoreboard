import os
import subprocess
import sys
import time
import shutil
import getpass

# --- CONFIGURAZIONE ---
REPO_URL = "https://github.com/nzo1986/fencing-scoreboard.git"
BASE_DIR = os.path.expanduser("~/fencing_scoreboard")
VENV_DIR = os.path.join(BASE_DIR, "venv")
RUN_SCRIPT = os.path.join(BASE_DIR, "run_kiosk.sh")
XINITRC_FILE = os.path.expanduser("~/.xinitrc")
BASH_PROFILE = os.path.expanduser("~/.bash_profile")
BASHRC_FILE = os.path.expanduser("~/.bashrc")
AUTOSTART_DIR = os.path.expanduser("~/.config/lxsession/LXDE-pi")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "autostart")
DESKTOP_AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
CURRENT_USER = getpass.getuser()

def print_step(msg):
    print(f"\n\033[1;32m[STEP] {msg}\033[0m")

def run_command(command, shell=True, ignore_errors=False):
    try:
        subprocess.check_call(command, shell=shell)
    except subprocess.CalledProcessError:
        if not ignore_errors:
            print(f"\033[1;31m[ERRORE] Il comando ha fallito: {command}\033[0m")
            sys.exit(1)
        else:
            print(f"[INFO] Comando fallito (ignorato): {command}")

def interactive_menu():
    """Mostra finestra interattiva (whiptail o menu testuale) per scegliere OS e Pagina di Avvio."""
    os_choice = "1"
    page_choice = "2"

    has_whiptail = shutil.which("whiptail") is not None

    if has_whiptail:
        try:
            res_os = subprocess.run(
                [
                    "whiptail", "--title", "FENCING SCOREBOARD - SISTEMA OPERATIVO",
                    "--menu", "Seleziona il sistema operativo installato sul Raspberry Pi:",
                    "15", "75", "2",
                    "1", "Raspberry Pi OS LITE (Senza Desktop - Veloce e Leggero)",
                    "2", "Raspberry Pi OS DESKTOP (Con interfaccia grafica completa)"
                ],
                stderr=subprocess.PIPE, text=True
            )
            if res_os.returncode == 0 and res_os.stderr.strip():
                os_choice = res_os.stderr.strip()

            res_page = subprocess.run(
                [
                    "whiptail", "--title", "FENCING SCOREBOARD - SCHERMATA DI AVVIO",
                    "--menu", "Cosa vuoi visualizzare sul monitor HDMI all'accensione?",
                    "15", "75", "2",
                    "1", "Tabellone Punteggi (/ - Display grande per il pubblico)",
                    "2", "Pannello Unificato (/pannello - Gestione Atleti, Gironi e Reset)"
                ],
                stderr=subprocess.PIPE, text=True
            )
            if res_page.returncode == 0 and res_page.stderr.strip():
                page_choice = res_page.stderr.strip()
            return os_choice, page_choice
        except Exception:
            pass

    print("\n\033[1;36m================================================================\033[0m")
    print("\033[1;32m   🤺 CONFIGURAZIONE INTERATTIVA FENCING SCOREBOARD KIOSK\033[0m")
    print("\033[1;36m================================================================\033[0m\n")

    print("\033[1;33m1) SELEZIONA IL SISTEMA OPERATIVO:\033[0m")
    print("   [1] Raspberry Pi OS LITE (Senza Desktop - Consigliato)")
    print("   [2] Raspberry Pi OS DESKTOP (Con interfaccia grafica)")
    c1 = input("Digita 1 o 2 [Default: 1]: ").strip()
    if c1 in ["1", "2"]:
        os_choice = c1

    print("\n\033[1;33m2) SELEZIONA COSA MOSTRARE ALL'AVVIO SUL MONITOR:\033[0m")
    print("   [1] Tabellone Punteggi (Display grande per il pubblico)")
    print("   [2] Pannello Unificato (Gestione Atleti + Gironi + Reset)")
    c2 = input("Digita 1 o 2 [Default: 2]: ").strip()
    if c2 in ["1", "2"]:
        page_choice = c2

    return os_choice, page_choice

def check_internet():
    print_step("Controllo connessione Internet...")
    try:
        subprocess.check_call(["ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
        print("Connessione OK.")
        return True
    except Exception:
        print("\033[1;33m[AVVISO] Nessuna connessione internet. Continuo in modalita' locale.\033[0m")
        return False

def install_system_dependencies(os_choice):
    print_step("Installazione dipendenze di sistema (apt)...")
    run_command("sudo apt-get update", ignore_errors=True)
    base_pkgs = "git xserver-xorg x11-xserver-utils xinit openbox python3-pip python3-venv python3-dev xdotool unclutter network-manager fontconfig wireless-tools"
    run_command(f"sudo apt-get install -y --no-install-recommends {base_pkgs}", ignore_errors=True)
    # Installa chromium (nome pacchetto varia tra Debian Bullseye/Bookworm/Trixie)
    run_command("sudo apt-get install -y --no-install-recommends chromium || sudo apt-get install -y --no-install-recommends chromium-browser", ignore_errors=True)

def setup_repository(has_internet):
    print_step("Sincronizzazione Codice da GitHub...")
    if not has_internet:
        return

    if os.path.exists(BASE_DIR):
        if os.path.exists(os.path.join(BASE_DIR, ".git")):
            os.chdir(BASE_DIR)
            temp_state1, temp_state2 = "/tmp/match_state.json", "/tmp/local_match_state.json"
            if os.path.exists("match_state.json"):
                shutil.copy2("match_state.json", temp_state1)
            if os.path.exists("local_match_state.json"):
                shutil.copy2("local_match_state.json", temp_state2)

            run_command("git fetch origin", ignore_errors=True)
            run_command("git reset --hard origin/main", ignore_errors=True)

            if os.path.exists(temp_state1):
                shutil.copy2(temp_state1, "match_state.json")
            if os.path.exists(temp_state2):
                shutil.copy2(temp_state2, "local_match_state.json")
        else:
            timestamp = int(time.time())
            backup_dir = f"{BASE_DIR}_backup_{timestamp}"
            os.rename(BASE_DIR, backup_dir)
            run_command(f"git clone {REPO_URL} {BASE_DIR}")
            os.chdir(BASE_DIR)
            old_photos = os.path.join(backup_dir, "static", "photos")
            new_photos = os.path.join(BASE_DIR, "static", "photos")
            os.makedirs(new_photos, exist_ok=True)
            if os.path.exists(old_photos):
                for item in os.listdir(old_photos):
                    s = os.path.join(old_photos, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, os.path.join(new_photos, item))
            for file_name in ["match_state.json", "local_match_state.json"]:
                if os.path.exists(os.path.join(backup_dir, file_name)):
                    shutil.copy2(os.path.join(backup_dir, file_name), os.path.join(BASE_DIR, file_name))
    else:
        run_command(f"git clone {REPO_URL} {BASE_DIR}")
        os.chdir(BASE_DIR)

def setup_python_environment():
    print_step("Configurazione Ambiente Python (venv senza eventlet)...")
    if not os.path.exists(VENV_DIR):
        run_command(f"python3 -m venv {VENV_DIR}")
    pip_bin = os.path.join(VENV_DIR, "bin", "pip")
    run_command(f"{pip_bin} install --upgrade pip", ignore_errors=True)
    # Rimuove eventlet se presente da vecchie installazioni
    run_command(f"{pip_bin} uninstall -y eventlet", ignore_errors=True)
    pkgs = "Flask Flask-SocketIO requests werkzeug simple-websocket"
    run_command(f"{pip_bin} install --upgrade {pkgs}", ignore_errors=True)

def create_startup_scripts(os_choice, page_choice):
    print_step("Creazione script di avvio Kiosk anti-popup...")
    os.makedirs(os.path.join(BASE_DIR, "static", "photos"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "templates", "pico_code"), exist_ok=True)

    target_url = "http://127.0.0.1:5000/pannello" if page_choice == "2" else "http://127.0.0.1:5000/"

    with open(os.path.join(BASE_DIR, "startup_url.txt"), "w") as f:
        f.write(target_url)

    run_script_content = f"""#!/bin/bash
export DISPLAY=:0

# Disattiva standby e screensaver
xset s off
xset -dpms
xset s noblank

# Nasconde cursore mouse dopo inattivita'
unclutter -idle 0.5 -root &

# Pulisce eventuali processi rimasti appesi
pkill -f 'python app.py' 2>/dev/null
pkill -f 'chromium' 2>/dev/null

cd "{BASE_DIR}" || exit 1
source "{VENV_DIR}/bin/activate"

# Avvia server Flask
python app.py >> "$HOME/kiosk.log" 2>&1 &
SERVER_PID=$!

# Attende che la porta 5000 sia attiva
for i in $(seq 1 30); do
    if nc -z 127.0.0.1 5000 2>/dev/null || curl -s http://127.0.0.1:5000 >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Determina eseguibile Chromium
CHROME_BIN="chromium"
if ! command -v chromium &> /dev/null; then
    CHROME_BIN="chromium-browser"
fi

# Rimuove avvisi di crash precedenti di Chromium
sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' ~/.config/chromium/Default/Preferences 2>/dev/null
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' ~/.config/chromium/Default/Preferences 2>/dev/null

# Avvia Chromium in modalita' Kiosk pura senza popup di traduzione o barre
$CHROME_BIN \\
  --kiosk \\
  --noerrdialogs \\
  --disable-infobars \\
  --disable-translate \\
  --disable-features=Translate,TranslateUI,OptimizationHints,MediaRouter \\
  --no-first-run \\
  --fast \\
  --fast-start \\
  --disable-session-crashed-bubble \\
  --disable-restore-session-state \\
  --autoplay-policy=no-user-gesture-required \\
  --check-for-update-interval=31536000 \\
  "{target_url}" &

BROWSER_PID=$!

# Simula click iniziale per sbloccare l'audio del browser
sleep 6
if command -v xdotool &> /dev/null; then
    xdotool mousemove 10 10 click 1
fi

wait $SERVER_PID
"""
    with open(RUN_SCRIPT, "w") as f:
        f.write(run_script_content)
    run_command(f"chmod +x {RUN_SCRIPT}")

    if os_choice == "1":
        print_step("Configurazione avvio automatico per Raspberry Pi OS LITE...")
        xinitrc_content = f"""#!/bin/sh
openbox-session &
exec "{RUN_SCRIPT}"
"""
        with open(XINITRC_FILE, "w") as f:
            f.write(xinitrc_content)
        run_command(f"chmod +x {XINITRC_FILE}")

        startx_line = '\n# Avvio automatico Kiosk Scherma su tty1\nif [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then\n    startx\nfi\n'
        for rc_path in [BASH_PROFILE, BASHRC_FILE]:
            existing = ""
            if os.path.exists(rc_path):
                with open(rc_path, "r") as f:
                    existing = f.read()
            if "startx" not in existing:
                with open(rc_path, "a") as f:
                    f.write(startx_line)

        # Configura autologin su tty1 via systemd
        autologin_dir = "/etc/systemd/system/getty@tty1.service.d"
        autologin_conf = f"[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin {CURRENT_USER} --noclear %I $TERM\n"
        run_command(f"sudo mkdir -p {autologin_dir}", ignore_errors=True)
        with open("/tmp/autologin.conf", "w") as f:
            f.write(autologin_conf)
        run_command(f"sudo mv /tmp/autologin.conf {autologin_dir}/autologin.conf", ignore_errors=True)
        run_command("sudo systemctl daemon-reload", ignore_errors=True)
    else:
        print_step("Configurazione avvio automatico per Raspberry Pi OS DESKTOP...")
        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        autostart_content = f"@lxpanel --profile LXDE-pi\n@pcmanfm --desktop --profile LXDE-pi\n@xscreensaver -no-splash\n@{RUN_SCRIPT}\n"
        try:
            with open(AUTOSTART_FILE, "w") as f:
                f.write(autostart_content)
        except Exception:
            pass

        os.makedirs(DESKTOP_AUTOSTART_DIR, exist_ok=True)
        desktop_entry = f"""[Desktop Entry]
Type=Application
Name=Fencing Scoreboard Kiosk
Exec={RUN_SCRIPT}
X-GNOME-Autostart-enabled=true
"""
        try:
            with open(os.path.join(DESKTOP_AUTOSTART_DIR, "fencing_kiosk.desktop"), "w") as f:
                f.write(desktop_entry)
        except Exception:
            pass

def main():
    os_choice, page_choice = interactive_menu()
    has_internet = check_internet()
    if has_internet:
        install_system_dependencies(os_choice)
    setup_repository(has_internet)
    setup_python_environment()
    create_startup_scripts(os_choice, page_choice)

    scelta_str = "Pannello Unificato (/pannello)" if page_choice == "2" else "Tabellone Punteggi (/)"
    os_str = "Raspberry Pi OS Lite" if os_choice == "1" else "Raspberry Pi OS Desktop"

    print("\n\033[1;32m================================================================\033[0m")
    print("\033[1;32m ✅ INSTALLAZIONE COMPLETATA CON SUCCESSO!\033[0m")
    print(f" > Sistema configurato: {os_str}")
    print(f" > Schermata d'avvio:   {scelta_str}")
    print("\033[1;32m================================================================\033[0m\n")

    riavvia = input("Vuoi riavviare il Raspberry Pi ora per avviare il Kiosk? (s/n) [Default: s]: ").strip().lower()
    if riavvia in ["", "s", "si", "y", "yes"]:
        run_command("sudo reboot")

if __name__ == "__main__":
    main()
