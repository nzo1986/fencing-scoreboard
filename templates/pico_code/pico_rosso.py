import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "rosso", "192.168.1.110", 7777

LOCAL_VERSION = "4.1" # Versione aggiornata per forzare l'OTA

def connect_wifi_and_ota():
    global LOCAL_VERSION
    print(f"\n[{PICO_NAME.upper()}] === AVVIO SISTEMA ===")
    print(f"[{PICO_NAME.upper()}] Versione attuale codice: {LOCAL_VERSION}")
    
    try:
        with open("version.txt", "r") as f: 
            saved = f.read().strip()
            if saved: LOCAL_VERSION = saved
            print(f"[{PICO_NAME.upper()}] Versione letta da memoria: {LOCAL_VERSION}")
    except: 
        print(f"[{PICO_NAME.upper()}] Nessun file version.txt trovato.")
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"[{PICO_NAME.upper()}] Connessione alla rete Wi-Fi '{WIFI_SSID}' in corso...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        t = 0
        while not wlan.isconnected() and t < 15:
            print(f"[{PICO_NAME.upper()}] Attesa Wi-Fi... ({t}/15)")
            time.sleep(0.5); t += 1
            
    if wlan.isconnected():
        print(f"[{PICO_NAME.upper()}] Wi-Fi CONNESSO! IP assegnato: {wlan.ifconfig()[0]}")
        try:
            print(f"[{PICO_NAME.upper()}] Controllo aggiornamenti OTA dal server {UDP_IP}...")
            r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/version", timeout=3)
            remote_ver = r.text.strip()
            r.close()
            print(f"[{PICO_NAME.upper()}] Versione sul Server: {remote_ver}")
            
            if remote_ver != LOCAL_VERSION and remote_ver != "0" and len(remote_ver) < 15:
                print(f"[{PICO_NAME.upper()}] >>> NUOVO AGGIORNAMENTO TROVATO! Download in corso...")
                r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/code", timeout=5)
                with open("temp.py", "w") as f: f.write(r.text)
                r.close()
                os.rename("temp.py", "main.py")
                with open("version.txt", "w") as f: f.write(remote_ver)
                print(f"[{PICO_NAME.upper()}] >>> Aggiornamento completato. RIAVVIO!")
                time.sleep(0.5)
                machine.reset()
            else:
                print(f"[{PICO_NAME.upper()}] Nessun aggiornamento necessario.")
        except Exception as e: 
            print(f"[{PICO_NAME.upper()}] Errore durante il controllo OTA: {e}")
    else:
        print(f"[{PICO_NAME.upper()}] IMPOSSIBILE CONNETTERSI AL WI-FI. Continuo offline.")

try: onboard_led = Pin("LED", Pin.OUT)
except: onboard_led = Pin(25, Pin.OUT)

def get_battery_percentage():
    try:
        try: Pin(25, Pin.OUT).value(1); time.sleep_ms(5)
        except: pass
        raw = ADC(29).read_u16()
        try: Pin(25, Pin.OUT).value(0)
        except: pass
        voltage = raw * (3.3 / 65535) * 3.0
        pct = int(((voltage - 3.2) / (4.2 - 3.2)) * 100)
        return max(0, min(100, pct)) 
    except: return 0

def loop():
    connect_wifi_and_ota()
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[{PICO_NAME.upper()}] Socket UDP inizializzato.")
    
    pin13 = Pin(13, Pin.IN, Pin.PULL_DOWN)
    pin14 = Pin(14, Pin.IN, Pin.PULL_DOWN)
    pin15 = Pin(15, Pin.IN, Pin.PULL_DOWN)
    
    b_was_pressed = False
    c_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = ""

    print(f"[{PICO_NAME.upper()}] *** MOTORE LOGICO (TDM) AVVIATO ***")

    while True:
        try:
            current_time = time.ticks_ms()
            
            if time.ticks_diff(current_time, ping_next_time) >= 0:
                bat = get_battery_percentage()
                try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{bat}_{LOCAL_VERSION}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                # print(f"[{PICO_NAME.upper()}] Ping inviato. Batteria: {bat}%") # Decommentare per log continuo
                ping_next_time = time.ticks_add(current_time, 2000)

            is_hit = False
            is_coccia = False

            # --- IMPULSO D (Polo 1) ---
            pin13.init(Pin.OUT); pin13.value(1)
            time.sleep_ms(1) # Rilassato a 1ms per stabilità MicroPython
            if pin14.value() == 1: is_hit = True
            if pin15.value() == 1: is_coccia = True
            pin13.value(0); pin13.init(Pin.IN, Pin.PULL_DOWN)

            # --- IMPULSO E (Polo 2) ---
            pin14.init(Pin.OUT); pin14.value(1)
            time.sleep_ms(1)
            if pin13.value() == 1: is_hit = True
            if pin15.value() == 1: is_coccia = True
            pin14.value(0); pin14.init(Pin.IN, Pin.PULL_DOWN)

            # --- IMPULSO F (Coccia) ---
            pin15.init(Pin.OUT); pin15.value(1)
            time.sleep_ms(1)
            if pin13.value() == 1 or pin14.value() == 1: is_coccia = True
            pin15.value(0); pin15.init(Pin.IN, Pin.PULL_DOWN)

            # --- ASCOLTO PASSIVO ---
            time.sleep_ms(2)
            if pin15.value() == 1: is_coccia = True

            hit_val = 1 if (is_hit and not is_coccia) else 0
            white_val = 1 if is_coccia else 0
            
            # --- FEEDBACK E STAMPE THONNY ---
            state_str = f"{hit_val}_{white_val}"
            if state_str != last_state_str:
                if hit_val == 1: 
                    print(f"\n[{PICO_NAME.upper()}] ---> STOCCATA RILEVATA! (Punta chiusa)")
                    onboard_led.value(1)
                elif white_val == 1: 
                    print(f"\n[{PICO_NAME.upper()}] ---> COCCIA RILEVATA! (Massa in contatto)")
                    onboard_led.value(1)
                else:
                    print(f"[{PICO_NAME.upper()}] Rilasciato.")
                    onboard_led.value(0)
                    
                try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: print(f"[{PICO_NAME.upper()}] Errore invio pacchetto STATE")
                last_state_str = state_str

            # --- INVIO COMANDI ---
            if white_val:
                if not c_was_pressed:
                    try: udp_socket.sendto(f"MASSA_MIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: print(f"[{PICO_NAME.upper()}] Fallito invio MASSA")
                c_was_pressed = True
            else:
                c_was_pressed = False

            if hit_val:
                if not b_was_pressed and not in_lockout:
                    print(f"[{PICO_NAME.upper()}] Invio pacchetto HIT_ROSSO al server...")
                    for _ in range(2): 
                        try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                        except: pass
                    in_lockout = True
                    lockout_start_time = current_time
                b_was_pressed = True
            else:
                b_was_pressed = False

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
                in_lockout = False
                print(f"[{PICO_NAME.upper()}] Lockout terminato, pronto per nuovo colpo.")
                
        except Exception as e:
            print(f"[{PICO_NAME.upper()}] ERRORE NEL LOOP PRINCIPALE: {e}")
            time.sleep_ms(500)

while True:
    try: 
        loop()
    except Exception as e: 
        print(f"[{PICO_NAME.upper()}] CRASH FATALE: {e}. Riavvio loop tra 2 secondi...")
        time.sleep(2)