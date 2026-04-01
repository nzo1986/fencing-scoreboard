import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "rosso", "192.168.1.110", 7777

# Versione di base. Verrà sovrascritta dal file version.txt se c'è un update OTA
LOCAL_VERSION = "1.0"

def connect_wifi_and_ota():
    global LOCAL_VERSION
    
    # Cerca di leggere la versione OTA salvata
    try:
        with open("version.txt", "r") as f: 
            saved_ver = f.read().strip()
            if saved_ver: LOCAL_VERSION = saved_ver
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
            remote_version = r.text.strip()
            r.close()
            
            if remote_version != LOCAL_VERSION and remote_version != "0" and len(remote_version) < 15:
                r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/code", timeout=5)
                with open("temp.py", "w") as f: f.write(r.text)
                r.close()
                os.rename("temp.py", "main.py")
                with open("version.txt", "w") as f: f.write(remote_version)
                time.sleep(0.5)
                machine.reset()
        except: pass

# Inizializza il LED interno (Compatibile con Pico W e Pico Standard)
try: onboard_led = Pin("LED", Pin.OUT)
except: onboard_led = Pin(25, Pin.OUT)

def get_battery_percentage():
    try:
        try: Pin(25, Pin.OUT).value(1)
        except: pass
        time.sleep_ms(10)
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
    
    # LOGICA ULTRA-SEMPLIFICATA: POLO 1 E POLO 2 SI CHIUDONO
    PIN_14 = Pin(14, Pin.OUT); PIN_14.value(0) # Polo 1 emette segnale basso
    PIN_15 = Pin(15, Pin.IN, Pin.PULL_UP)      # Polo 2 legge (se va a 0 = Chiuso)
    
    b_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    
    # Variabili per il lampeggio del LED
    led_timer = time.ticks_ms()
    led_is_on = False

    while True:
        current_time = time.ticks_ms()
        
        # --- GESTIONE LED LAMPEGGIANTE (Ogni 4s, dura 100ms) ---
        if not led_is_on and time.ticks_diff(current_time, led_timer) >= 4000:
            onboard_led.value(1)
            led_is_on = True
            led_timer = current_time 
        elif led_is_on and time.ticks_diff(current_time, led_timer) >= 100: 
            onboard_led.value(0)
            led_is_on = False
            led_timer = current_time 
        
        # --- PING DI MANTENIMENTO E VERSIONE ---
        if time.ticks_diff(current_time, ping_next_time) >= 0:
            try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}_{LOCAL_VERSION}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            ping_next_time = time.ticks_add(current_time, 2000)

        # --- LETTURA PUNTA (Polo 1 tocca Polo 2) ---
        is_hit = (PIN_15.value() == 0)

        if is_hit:
            if not b_was_pressed and not in_lockout:
                try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                in_lockout = True
                lockout_start_time = current_time
            b_was_pressed = True
        else:
            b_was_pressed = False

        if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
            in_lockout = False
            
        time.sleep_ms(2) 

try: loop()
except Exception as e: print("CRASH:", e)