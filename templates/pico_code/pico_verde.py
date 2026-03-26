import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

current_weapon = "spada"
udp_socket = None

def connect_wifi_and_ota():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        t = 0
        while not wlan.isconnected() and t < 15:
            time.sleep(0.5)
            t += 1
            
    if wlan.isconnected():
        try:
            try:
                with open("version.txt", "r") as f: LOCAL_VERSION = f.read().strip()
            except: LOCAL_VERSION = "0"
            
            print(f"[OTA] Connesso. Versione locale: {LOCAL_VERSION}")
            r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/version", timeout=3)
            remote_version = r.text.strip()
            r.close()
            
            if remote_version != LOCAL_VERSION and remote_version != "0" and len(remote_version) < 15:
                print(f"[OTA] Scarico aggiornamento {remote_version}...")
                r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/code", timeout=5)
                with open("temp.py", "w") as f: f.write(r.text)
                r.close()
                os.rename("temp.py", "main.py")
                with open("version.txt", "w") as f: f.write(remote_version)
                print("[OTA] Fatto. Riavvio!")
                time.sleep(0.5)
                machine.reset()
        except Exception as e:
            print("[OTA] Errore o server irraggiungibile:", e)

def get_battery_percentage():
    try:
        try: Pin(25, Pin.OUT).value(1)
        except: pass
        try: Pin("WL_GPIO2", Pin.OUT).value(1)
        except: pass
        time.sleep_ms(10)
        try: raw = ADC(29).read_u16()
        except: raw = ADC(3).read_u16()
        if raw < 5000: raw = ADC(3).read_u16()
        try: Pin(25, Pin.OUT).value(0)
        except: pass
        try: Pin("WL_GPIO2", Pin.OUT).value(0)
        except: pass
        voltage = raw * (3.3 / 65535) * 3.0
        if voltage < 1.0: return 0
        pct = int(((voltage - 3.2) / (4.2 - 3.2)) * 100)
        return max(0, min(100, pct)) 
    except: return 0

def check_udp_messages():
    global current_weapon
    try:
        data, addr = udp_socket.recvfrom(1024)
        msg = data.decode('utf-8')
        if msg.startswith("SET_WEAPON_"):
            current_weapon = msg.split("_")[2].lower()
        elif msg == "REBOOT_PICO":
            machine.reset() 
    except OSError:
        pass

def ping_server(ping_next_time, current_time):
    if time.ticks_diff(current_time, ping_next_time) >= 0:
        try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}".encode('utf-8'), (UDP_IP, UDP_PORT))
        except: pass
        return time.ticks_add(current_time, 2000)
    return ping_next_time

# ==========================================
# MOTORE 1: SPADA (LOGICA POLI EXACT)
# ==========================================
def run_spada():
    global current_weapon
    PIN_13 = Pin(13, Pin.OUT); PIN_13.value(0) # Coccia sempre a GND
    PIN_14 = Pin(14, Pin.IN, Pin.PULL_UP)      # Polo 1
    PIN_15 = Pin(15, Pin.IN, Pin.PULL_UP)      # Polo 2
    
    b_was_pressed = False
    c_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = "0_0"

    while current_weapon == "spada":
        current_time = time.ticks_ms()
        check_udp_messages()
        if current_weapon != "spada": break
        ping_next_time = ping_server(ping_next_time, current_time)

        # FASE 1: Lettura contatto con Coccia avversaria (Massa Esterna)
        PIN_15.init(Pin.IN, Pin.PULL_UP)
        PIN_14.init(Pin.IN, Pin.PULL_UP)
        time.sleep_us(300)
        touching_coccia = (PIN_14.value() == 0) or (PIN_15.value() == 0)

        # FASE 2: Lettura chiusura Punta
        PIN_15.init(Pin.OUT); PIN_15.value(0)
        time.sleep_us(300)
        tip_pressed = (PIN_14.value() == 0)
        PIN_15.init(Pin.IN, Pin.PULL_UP) # Ripristino
        
        hit_val = 1 if (tip_pressed and not touching_coccia) else 0
        white_val = 1 if touching_coccia else 0
        
        state_str = f"{hit_val}_{white_val}"
        if state_str != last_state_str:
            try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            last_state_str = state_str

        # Logica invio stoccate al tabellone
        if white_val:
            if not c_was_pressed:
                try: udp_socket.sendto(f"MASSA_MIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
            c_was_pressed = True
        else:
            c_was_pressed = False

        if hit_val:
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

# ==========================================
# MOTORE 2: FIORETTO (LOGICA NC)
# ==========================================
def run_fioretto():
    global current_weapon
    pin_13 = Pin(13, Pin.OUT)
    pin_14 = Pin(14, Pin.OUT)
    pin_15 = Pin(15, Pin.IN, Pin.PULL_UP)
    
    b_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = "0_0"

    while current_weapon == "fioretto":
        current_time = time.ticks_ms()
        check_udp_messages()
        if current_weapon != "fioretto": break
        ping_next_time = ping_server(ping_next_time, current_time)

        pin_14.value(0)
        pin_13.value(0)
        time.sleep_us(500)
        read_phase1 = pin_15.value()
        
        pin_13.value(1)
        time.sleep_us(500)
        read_phase2 = pin_15.value()
        
        pin_13.value(0) 
        
        is_off_target = (read_phase1 == 1)
        is_valid_hit = (read_phase1 == 0 and read_phase2 == 0)
        is_not_pressed = (read_phase1 == 0 and read_phase2 == 1)
        
        hit_val = 1 if is_valid_hit else 0
        white_val = 1 if is_off_target else 0

        state_str = f"{hit_val}_{white_val}"
        if state_str != last_state_str:
            try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            last_state_str = state_str

        if (is_valid_hit or is_off_target) and not b_was_pressed and not in_lockout:
            if is_valid_hit:
                try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
            else:
                try: udp_socket.sendto(f"OFF_TARGET_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
            in_lockout = True
            lockout_start_time = current_time
            b_was_pressed = True
            
        elif is_not_pressed:
            b_was_pressed = False
            
        if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
            in_lockout = False

# ==========================================
# MOTORE 3: SCIABOLA
# ==========================================
def run_sciabola():
    global current_weapon
    Pin(13, Pin.OUT).value(0)
    GP14 = Pin(14, Pin.IN, Pin.PULL_UP)
    
    b_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = "0_0"

    while current_weapon == "sciabola":
        current_time = time.ticks_ms()
        check_udp_messages()
        if current_weapon != "sciabola": break
        ping_next_time = ping_server(ping_next_time, current_time)

        touching_opp = (GP14.value() == 0)
        
        hit_val = 1 if touching_opp else 0
        state_str = f"{hit_val}_0"
        if state_str != last_state_str:
            try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            last_state_str = state_str
            
        if touching_opp and not b_was_pressed and not in_lockout:
            try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            in_lockout = True
            lockout_start_time = current_time
            b_was_pressed = True
        elif not touching_opp:
            b_was_pressed = False

        if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: 
            in_lockout = False

def loop():
    global udp_socket
    connect_wifi_and_ota()
    
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: udp_socket.bind(('0.0.0.0', 7778))
    except: pass
    udp_socket.setblocking(False)

    while True:
        if current_weapon == "spada": run_spada()
        elif current_weapon == "fioretto": run_fioretto()
        elif current_weapon == "sciabola": run_sciabola()
        else: time.sleep(0.1)

try: loop()
except Exception as e: print("CRASH:", e)