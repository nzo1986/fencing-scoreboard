import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

LOCAL_VERSION = "7.0"

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
                
                try: os.remove("main.py")
                except: pass
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
    # LOGICA "DOMINIO TEMPORALE" (Completamente Wireless)
    # ----------------------------------------------------
    pin13 = Pin(13, Pin.IN, Pin.PULL_DOWN)
    pin14 = Pin(14, Pin.IN, Pin.PULL_DOWN)
    pin15 = Pin(15, Pin.IN, Pin.PULL_DOWN) # Coccia in ascolto passivo
    
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

            is_hit = False
            is_coccia = False
            debug_msg = "Nessuno"

            # --- FASE 1: OUTPUT POLO 1 ---
            pin13.init(Pin.OUT); pin13.value(1)
            time.sleep_ms(1)
            if pin14.value() == 1: 
                is_hit = True
                debug_msg = "Punta_Chiusa_P1->P2"
            pin13.value(0); pin13.init(Pin.IN, Pin.PULL_DOWN)

            # --- FASE 2: OUTPUT POLO 2 ---
            if not is_hit:
                pin14.init(Pin.OUT); pin14.value(1)
                time.sleep_ms(1)
                if pin13.value() == 1: 
                    is_hit = True
                    debug_msg = "Punta_Chiusa_P2->P1"
                pin14.value(0); pin14.init(Pin.IN, Pin.PULL_DOWN)

            # --- FASE 3: ASCOLTO PASSIVO (Verifica Esterna) ---
            # Mi ammutolisco e ascolto se arriva corrente dall'altra Pico!
            time.sleep_ms(2) 
            
            if pin15.value() == 1:
                # La mia coccia (15) legge corrente: l'avversario ha toccato la mia coccia
                is_coccia = True
                debug_msg = "Sua_Lama_su_Mia_Coccia"
            elif pin13.value() == 1 or pin14.value() == 1:
                # I miei poli (spenti) leggono corrente esterna:
                # Sto toccando la SUA coccia o la SUA lama. In ogni caso la stoccata va annullata!
                is_coccia = True
                debug_msg = "Mia_Lama_su_Sua_Coccia_o_Lama"

            # Processo i risultati
            hit_val = 1 if (is_hit and not is_coccia) else 0
            white_val = 1 if is_coccia else 0
            
            # --- AGGIORNAMENTO TERMINALE E LED ---
            state_str = f"{hit_val}_{white_val}"
            if state_str != last_state_str:
                if hit_val == 1 or white_val == 1: onboard_led.value(1)
                else: onboard_led.value(0)
                
                try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}_{debug_msg}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                last_state_str = state_str

            # --- TRASMISSIONE EVENTI AL RASPBERRY ---
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
                
            # --- SINCRONIZZAZIONE NUMERI PRIMI (Anticollisione) ---
            # La verde aspetta 7ms, la rossa aspetta 11ms. Non collideranno mai in loop continui.
            time.sleep_ms(7) 

        except Exception as e:
            time.sleep_ms(100)

while True:
    try: loop()
    except Exception as e: time.sleep(1)