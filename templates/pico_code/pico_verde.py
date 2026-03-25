import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

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

connect_wifi_and_ota()

PIN_B_NUM = 14 # Punta (Spada/Sciabola) o Lamé (Fioretto)
PIN_C_NUM = 15 # Coccia (Spada) o Ritorno NC (Fioretto)

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

udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try: udp_socket.bind(('0.0.0.0', 7778))
except: pass
udp_socket.setblocking(False)

def loop():
    b_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_coccia_send = 0
    debug_next_time = 0
    current_weapon = "spada"

    while True:
        current_time = time.ticks_ms()
        
        try:
            data, addr = udp_socket.recvfrom(1024)
            msg = data.decode('utf-8')
            if msg.startswith("SET_WEAPON_"): current_weapon = msg.split("_")[2].lower()
            elif msg == "REBOOT_PICO": machine.reset() 
        except OSError: pass

        if time.ticks_diff(current_time, ping_next_time) >= 0:
            try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            ping_next_time = time.ticks_add(current_time, 2000)

        # --- LOGICA ARMI ---
        if current_weapon == "spada":
            Pin(13, Pin.OUT).value(0)
            PIN_B = Pin(PIN_B_NUM, Pin.IN, Pin.PULL_UP)
            PIN_C = Pin(PIN_C_NUM, Pin.OUT); PIN_C.value(0)
            time.sleep_us(500) 
            PIN_C = Pin(PIN_C_NUM, Pin.IN, Pin.PULL_UP)
            time.sleep_us(500)

            b_pressed, c_pressed = (PIN_B.value() == 0), (PIN_C.value() == 0)

            if time.ticks_diff(current_time, debug_next_time) >= 0:
                try: udp_socket.sendto(f"DEBUG_{PICO_NAME.upper()}_WPN:SPADA Punta:{b_pressed} Coccia:{c_pressed}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                debug_next_time = time.ticks_add(current_time, 1000)

            if b_pressed and not b_was_pressed and not in_lockout:
                if not c_pressed:
                    try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                    in_lockout = True; lockout_start_time = current_time

            if c_pressed and not b_pressed:
                if time.ticks_diff(current_time, last_coccia_send) > 80:
                    try: udp_socket.sendto(f"COCCIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                    last_coccia_send = current_time

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: in_lockout = False
            b_was_pressed = b_pressed

        elif current_weapon == "fioretto":
            pin_13 = Pin(13, Pin.OUT)
            pin_14 = Pin(PIN_B_NUM, Pin.OUT); pin_14.value(0) 
            pin_15 = Pin(PIN_C_NUM, Pin.IN, Pin.PULL_UP)      
            
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

            if time.ticks_diff(current_time, debug_next_time) >= 0:
                try: udp_socket.sendto(f"DEBUG_{PICO_NAME.upper()}_WPN:FIORETTO P1:{read_phase1} P2:{read_phase2}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                debug_next_time = time.ticks_add(current_time, 1000)

            if (is_valid_hit or is_off_target) and not b_was_pressed and not in_lockout:
                if is_valid_hit:
                    try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                else:
                    try: udp_socket.sendto(f"OFF_TARGET_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                in_lockout = True; lockout_start_time = current_time; b_was_pressed = True
                
            elif is_not_pressed:
                b_was_pressed = False
                
            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: in_lockout = False

        elif current_weapon == "sciabola":
            Pin(13, Pin.OUT).value(0)
            GP14 = Pin(PIN_B_NUM, Pin.IN, Pin.PULL_UP)
            touching_opp = (GP14.value() == 0)
            
            if time.ticks_diff(current_time, debug_next_time) >= 0:
                try: udp_socket.sendto(f"DEBUG_{PICO_NAME.upper()}_WPN:SCIABOLA Bersaglio:{touching_opp}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                debug_next_time = time.ticks_add(current_time, 1000)
                
            if touching_opp and not b_was_pressed and not in_lockout:
                try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                in_lockout = True; lockout_start_time = current_time; b_was_pressed = True
            elif not touching_opp:
                b_was_pressed = False

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: in_lockout = False

try: loop()
except: pass