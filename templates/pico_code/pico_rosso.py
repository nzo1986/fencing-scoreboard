import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "rosso", "192.168.1.110", 7777

LOCAL_VERSION = "5.1" # Aggiornamento OTA

def connect_wifi_and_ota():
    global LOCAL_VERSION
    try:
        with open("version.txt", "r") as f: 
            saved = f.read().strip()
            if saved: LOCAL_VERSION = saved
    except: pass
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        t = 0
        while not wlan.isconnected() and t < 15:
            time.sleep(0.5); t += 1
            
    if wlan.isconnected():
        try:
            r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/version", timeout=3)
            remote_ver = r.text.strip()
            r.close()
            if remote_ver != LOCAL_VERSION and remote_ver != "0" and len(remote_ver) < 15:
                r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/code", timeout=5)
                with open("temp.py", "w") as f: f.write(r.text)
                r.close()
                os.rename("temp.py", "main.py")
                with open("version.txt", "w") as f: f.write(remote_ver)
                time.sleep(0.5)
                machine.reset()
        except: pass

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
    
    # ----------------------------------------------------
    # LOGICA ELETTRICA FIE (Richiede Cavo GND in Comune)
    # ----------------------------------------------------
    pin15 = Pin(15, Pin.OUT); pin15.value(0) # COCCIA = MASSA FISSA (0V)
    pin13 = Pin(13, Pin.IN, Pin.PULL_UP)     # POLO 1 = 3.3V Costanti
    pin14 = Pin(14, Pin.IN, Pin.PULL_UP)     # POLO 2 = 3.3V Costanti
    
    b_was_pressed = False
    c_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = ""

    while True:
        try:
            current_time = time.ticks_ms()
            
            if time.ticks_diff(current_time, ping_next_time) >= 0:
                bat = get_battery_percentage()
                try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{bat}_{LOCAL_VERSION}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                ping_next_time = time.ticks_add(current_time, 2000)

            # --- FASE 1: CONTROLLO COCCIA (Propria o Avversaria) ---
            # Poiché le due Pico hanno il GND unito, se il Polo 1 (o Polo 2) 
            # sfiora la coccia, il voltaggio crolla a 0V istantaneamente.
            is_coccia = (pin13.value() == 0 or pin14.value() == 0)
            is_hit = False

            # --- FASE 2: CONTROLLO PUNTA ---
            if not is_coccia:
                # Inverte la polarità del Polo 1 per misurare la punta
                pin13.init(Pin.OUT); pin13.value(0)
                time.sleep_us(50)
                if pin14.value() == 0:
                    is_hit = True
                pin13.init(Pin.IN, Pin.PULL_UP) # Ripristina

            hit_val = 1 if is_hit else 0
            white_val = 1 if is_coccia else 0
            
            # --- FEEDBACK ---
            state_str = f"{hit_val}_{white_val}"
            if state_str != last_state_str:
                if hit_val == 1 or white_val == 1: onboard_led.value(1)
                else: onboard_led.value(0)
                
                debug_msg = "Coccia_Toccata" if white_val else ("Punta_Chiusa" if hit_val else "Nessuno")
                try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}_{debug_msg}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                last_state_str = state_str

            if white_val:
                if not c_was_pressed:
                    for _ in range(3):
                        try: udp_socket.sendto(f"COCCIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                        except: pass
                        time.sleep_ms(2)
                c_was_pressed = True
            else:
                c_was_pressed = False

            if hit_val:
                if not b_was_pressed and not in_lockout:
                    for _ in range(3):
                        try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                        except: pass
                        time.sleep_ms(2)
                    in_lockout = True
                    lockout_start_time = current_time
                b_was_pressed = True
            else:
                b_was_pressed = False

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
                in_lockout = False
                
        except Exception as e:
            time.sleep_ms(100)

while True:
    try: loop()
    except Exception as e: time.sleep(1)