import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

LOCAL_VERSION = "9.0"

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
                codice_nuovo = r.text
                r.close()
                if len(codice_nuovo) > 1000:
                    with open("temp.py", "w") as f: f.write(codice_nuovo)
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
    # TEST ESTREMO "RADAR" (Senza Massa Comune)
    # ----------------------------------------------------
    pin13 = Pin(13, Pin.OUT)
    pin14 = Pin(14, Pin.IN, Pin.PULL_DOWN)
    
    # Rimuoviamo la resistenza di Pull-Down per rendere il pin "FLOTTANTE"
    # Si comporterà come un'antenna estremamente sensibile
    pin15 = Pin(15, Pin.IN) 
    
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

            # 1. EMISSIONE COSTANTE 3.3V SULLA LAMA
            pin13.value(1)
            
            # 2. LETTURA PUNTA PROPRIA
            is_hit = (pin14.value() == 1)

            # 3. ASCOLTO RADAR COCCIA (Scansione ultra-rapida)
            noise_count = 0
            for _ in range(1000): # 1000 letture alla massima velocità del processore
                if pin15.value() == 1:
                    noise_count += 1
            
            is_coccia = False
            debug_msg = "SILENZIO"

            # Se capta anche solo 2 microscopici picchi di tensione, li segnala!
            if noise_count > 2:
                is_coccia = True
                debug_msg = f"RUMORE_CAPTATO:_{noise_count}_PICCHI"

            if is_hit and not is_coccia: debug_msg = "PUNTA_MIA_CHIUSA"

            # --- TRASMISSIONE DATI AL RASPBERRY PER DEBUG VISIVO ---
            hit_val = 1 if is_hit else 0
            white_val = 1 if is_coccia else 0
            
            state_str = f"{hit_val}_{white_val}"
            
            # Invia lo stato al terminale solo se cambia, OPPURE se c'è rumore
            if state_str != last_state_str or is_coccia:
                if hit_val == 1 or white_val == 1: onboard_led.value(1)
                else: onboard_led.value(0)
                
                try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}_{debug_msg}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                last_state_str = state_str
                
                # Se abbiamo stampato un rumore, dormiamo un attimo per non floodare il terminale
                if is_coccia: time.sleep_ms(100)

            time.sleep_ms(2) 

        except Exception as e:
            time.sleep_ms(100)

while True:
    try: loop()
    except Exception as e: time.sleep(1)