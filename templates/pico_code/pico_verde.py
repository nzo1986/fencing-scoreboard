import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

LOCAL_VERSION = "2.0"

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
    
    PIN_COCCIA = Pin(15, Pin.IN, Pin.PULL_DOWN) 
    PIN_POLO1 = Pin(13, Pin.IN, Pin.PULL_DOWN)  
    PIN_POLO2 = Pin(14, Pin.IN, Pin.PULL_DOWN)  
    
    b_was_pressed = False
    c_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    led_timer = time.ticks_ms()
    led_is_on = False

    while True:
        current_time = time.ticks_ms()
        
        # Ping e Batteria
        if time.ticks_diff(current_time, ping_next_time) >= 0:
            try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}_{LOCAL_VERSION}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            ping_next_time = time.ticks_add(current_time, 2000)

        # Riavvio OTA On-The-Fly
        try:
            data, _ = udp_socket.recvfrom(1024)
            if data.decode('utf-8') == "REBOOT_PICO": machine.reset()
        except OSError: pass

        is_hit = False
        is_coccia = False

        # --- INVIO PACCHETTO A (Polo 1) ---
        PIN_POLO1.init(Pin.OUT); PIN_POLO1.value(1)
        time.sleep_us(150)
        if PIN_POLO2.value() == 1: is_hit = True
        if PIN_COCCIA.value() == 1: is_coccia = True
        PIN_POLO1.value(0); PIN_POLO1.init(Pin.IN, Pin.PULL_DOWN)

        # --- INVIO PACCHETTO B (Polo 2) ---
        PIN_POLO2.init(Pin.OUT); PIN_POLO2.value(1)
        time.sleep_us(150)
        if PIN_POLO1.value() == 1: is_hit = True
        if PIN_COCCIA.value() == 1: is_coccia = True
        PIN_POLO2.value(0); PIN_POLO2.init(Pin.IN, Pin.PULL_DOWN)

        # --- INVIO PACCHETTO C (Coccia) ---
        PIN_COCCIA.init(Pin.OUT); PIN_COCCIA.value(1)
        time.sleep_us(150)
        if PIN_POLO1.value() == 1: is_coccia = True
        if PIN_POLO2.value() == 1: is_coccia = True
        PIN_COCCIA.value(0); PIN_COCCIA.init(Pin.IN, Pin.PULL_DOWN)

        # --- ASCOLTO PASSIVO (Cattura pacchetti avversario) ---
        for _ in range(8):
            if PIN_COCCIA.value() == 1: is_coccia = True
            time.sleep_us(150)

        # --- LOGICA E TRASMISSIONE ---
        if is_coccia:
            onboard_led.value(1)
            if not c_was_pressed:
                for _ in range(3): 
                    try: udp_socket.sendto(f"MASSA_MIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
            c_was_pressed = True
        else:
            c_was_pressed = False

        if is_hit and not is_coccia:
            onboard_led.value(1)
            if not b_was_pressed and not in_lockout:
                for _ in range(3):
                    try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                in_lockout = True
                lockout_start_time = current_time
            b_was_pressed = True
        else:
            b_was_pressed = False

        if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
            in_lockout = False

        # Feedback Led
        if not is_hit and not is_coccia:
            if not led_is_on and time.ticks_diff(current_time, led_timer) >= 4000:
                onboard_led.value(1); led_is_on = True; led_timer = current_time 
            elif led_is_on and time.ticks_diff(current_time, led_timer) >= 100: 
                onboard_led.value(0); led_is_on = False; led_timer = current_time

try: loop()
except Exception as e: print("CRASH:", e)