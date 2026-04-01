import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

LOCAL_VERSION = "1.1"

def connect_wifi_and_ota():
    global LOCAL_VERSION
    
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
    
    PIN_14 = Pin(14, Pin.OUT); PIN_14.value(0) 
    PIN_15 = Pin(15, Pin.IN, Pin.PULL_UP)      
    
    b_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    
    led_timer = time.ticks_ms()
    led_is_on = False
    last_state_str = ""

    while True:
        current_time = time.ticks_ms()
        
        # --- PING DI MANTENIMENTO E VERSIONE ---
        if time.ticks_diff(current_time, ping_next_time) >= 0:
            try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}_{LOCAL_VERSION}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            ping_next_time = time.ticks_add(current_time, 2000)

        # --- LETTURA PUNTA ---
        is_hit = (PIN_15.value() == 0)

        # --- INVIO STATO DEBUG (Per controllare se rileva il tocco) ---
        hit_val = 1 if is_hit else 0
        state_str = f"{hit_val}_0"
        if state_str != last_state_str:
            try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            last_state_str = state_str

        # --- GESTIONE STOCCATA E FEEDBACK VISIVO LED ---
        if is_hit:
            onboard_led.value(1) # LED fisso per confermare il contatto fisico hardware
            
            if not b_was_pressed and not in_lockout:
                # Invio 3 pacchetti in rapida successione per azzerare il rischio di perdita dati Wi-Fi
                for _ in range(3):
                    try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                    time.sleep_ms(2)
                
                in_lockout = True
                lockout_start_time = current_time
            b_was_pressed = True
        else:
            b_was_pressed = False
            
            # --- GESTIONE LED LAMPEGGIANTE SE NON PREMUTO ---
            if not led_is_on and time.ticks_diff(current_time, led_timer) >= 4000:
                onboard_led.value(1)
                led_is_on = True
                led_timer = current_time 
            elif led_is_on and time.ticks_diff(current_time, led_timer) >= 100: 
                onboard_led.value(0)
                led_is_on = False
                led_timer = current_time 

        if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
            in_lockout = False
            
        time.sleep_ms(2) 

try: loop()
except Exception as e: print("CRASH:", e)