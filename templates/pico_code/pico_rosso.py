import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "rosso", "192.168.1.110", 7777

LOCAL_VERSION = "5.0"

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
    
    pin13 = Pin(13, Pin.IN, Pin.PULL_DOWN) # D
    pin14 = Pin(14, Pin.IN, Pin.PULL_DOWN) # E
    pin15 = Pin(15, Pin.IN, Pin.PULL_DOWN) # F (Coccia)
    
    b_was_pressed = False
    c_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = ""

    while True:
        try:
            current_time = time.ticks_ms()
            
            # --- PING E COMANDI REMOTI ---
            if time.ticks_diff(current_time, ping_next_time) >= 0:
                try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}_{LOCAL_VERSION}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                ping_next_time = time.ticks_add(current_time, 2000)

            try:
                data, _ = udp_socket.recvfrom(1024)
                if data.decode('utf-8') == "REBOOT_PICO": machine.reset()
            except OSError: pass

            is_hit = False
            is_coccia = False

            # --- IMPULSO D (Polo 1) ---
            pin13.init(Pin.OUT); pin13.value(1)
            time.sleep_us(100)
            if pin14.value() == 1: is_hit = True
            if pin15.value() == 1: is_coccia = True
            pin13.value(0); pin13.init(Pin.IN, Pin.PULL_DOWN)

            # --- IMPULSO E (Polo 2) ---
            pin14.init(Pin.OUT); pin14.value(1)
            time.sleep_us(100)
            if pin13.value() == 1: is_hit = True
            if pin15.value() == 1: is_coccia = True
            pin14.value(0); pin14.init(Pin.IN, Pin.PULL_DOWN)

            # --- IMPULSO F (Coccia) ---
            pin15.init(Pin.OUT); pin15.value(1)
            time.sleep_us(100)
            if pin13.value() == 1 or pin14.value() == 1: is_coccia = True
            pin15.value(0); pin15.init(Pin.IN, Pin.PULL_DOWN)

            # --- ASCOLTO PASSIVO (Per captare gli impulsi A, B, C della Pico Verde) ---
            for _ in range(5):
                if pin15.value() == 1: is_coccia = True
                time.sleep_us(100)

            hit_val = 1 if (is_hit and not is_coccia) else 0
            white_val = 1 if is_coccia else 0
            
            # --- FEEDBACK FISICO LED ---
            if hit_val == 1: onboard_led.value(1)
            else: onboard_led.value(0)
            
            # --- COMUNICAZIONE CAMBI DI STATO AL TERMINALE WEB ---
            state_str = f"{hit_val}_{white_val}"
            if state_str != last_state_str:
                try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                last_state_str = state_str

            # --- INVIO COMANDI AL SERVER ---
            if white_val:
                if not c_was_pressed:
                    try: udp_socket.sendto(f"MASSA_MIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                c_was_pressed = True
            else:
                c_was_pressed = False

            if hit_val:
                if not b_was_pressed and not in_lockout:
                    for _ in range(2): # 2 pacchetti rapidissimi per anti-lag
                        try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                        except: pass
                    in_lockout = True
                    lockout_start_time = current_time
                b_was_pressed = True
            else:
                b_was_pressed = False

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
                in_lockout = False
                
        except Exception as e:
            time.sleep_ms(100)

# Doppio scudo protettivo per evitare spegnimenti improvvisi
while True:
    try: loop()
    except Exception as e: time.sleep(1)