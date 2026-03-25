import network, time, machine, socket, os
import urequests as requests
from machine import Pin, ADC

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "rosso", "192.168.1.110", 7777

def check_ota():
    try:
        with open("version.txt", "r") as f: LOCAL_VERSION = f.read().strip()
    except: LOCAL_VERSION = "0"

    print(f"[OTA] Controllo aggiornamenti. Data file locale: {LOCAL_VERSION}")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    t = 0
    while not wlan.isconnected() and t < 10:
        time.sleep(1)
        t += 1
        
    if wlan.isconnected():
        try:
            r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/version")
            remote_version = r.text.strip()
            r.close()
            print(f"[OTA] Data file sul Raspberry: {remote_version}")
            
            if remote_version != LOCAL_VERSION and remote_version != "0" and len(remote_version) < 15:
                print(f"[OTA] File modificato rilevato! Scarico il nuovo codice...")
                r = requests.get(f"http://{UDP_IP}:5000/api/ota/{PICO_NAME}/code")
                with open("temp.py", "w") as f:
                    f.write(r.text)
                r.close()
                os.rename("temp.py", "main.py")
                
                with open("version.txt", "w") as f:
                    f.write(remote_version)
                    
                print("[OTA] Aggiornamento installato! Riavvio in corso...")
                time.sleep(1)
                machine.reset()
        except Exception as e:
            print("[OTA] Nessun aggiornamento o server offline:", e)

check_ota()

# PIN_A = Massa (Pelle/Lama)
PIN_A = Pin(13, Pin.OUT); PIN_A.value(0)
PIN_B_NUM = 14
PIN_C_NUM = 15 
udp_socket = None

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

def connect_wifi():
    global udp_socket
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected(): wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected(): time.sleep(0.5)
    
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(('0.0.0.0', 7778))
    udp_socket.setblocking(False)

def loop():
    connect_wifi()
    b_was_pressed, in_lockout, lockout_start_time = False, False, 0
    ping_next_time, last_coccia_send = time.ticks_ms(), 0
    current_weapon = "spada" # Arma predefinita all'avvio

    while True:
        current_time = time.ticks_ms()
        
        # Ascolto messaggi in arrivo dal server
        try:
            data, addr = udp_socket.recvfrom(1024)
            msg = data.decode('utf-8')
            if msg.startswith("SET_WEAPON_"):
                current_weapon = msg.split("_")[2].lower()
            elif msg == "REBOOT_PICO":
                machine.reset() # Riavvio forzato dal server OTA
        except OSError:
            pass

        # Ping del segnale di vita (e invio batteria)
        if time.ticks_diff(current_time, ping_next_time) >= 0:
            try: udp_socket.sendto(f"PING_{PICO_NAME.upper()}_{get_battery_percentage()}".encode('utf-8'), (UDP_IP, UDP_PORT))
            except: pass
            ping_next_time = time.ticks_add(current_time, 2000)

        # ----------------------- LOGICA ARMI ----------------------- #
        if current_weapon == "spada":
            PIN_B = Pin(PIN_B_NUM, Pin.IN, Pin.PULL_UP)
            PIN_C = Pin(PIN_C_NUM, Pin.OUT); PIN_C.value(0)
            time.sleep_ms(3) 
            PIN_C = Pin(PIN_C_NUM, Pin.IN, Pin.PULL_UP)
            time.sleep_ms(1)

            b_pressed, c_pressed = (PIN_B.value() == 0), (PIN_C.value() == 0)

            if b_pressed and not b_was_pressed and not in_lockout:
                if not c_pressed:
                    try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                    in_lockout = True
                    lockout_start_time = current_time

            if c_pressed and not b_pressed:
                if time.ticks_diff(current_time, last_coccia_send) > 80:
                    try: udp_socket.sendto(f"COCCIA_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                    last_coccia_send = current_time

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: in_lockout = False
            b_was_pressed = b_pressed

        elif current_weapon == "fioretto":
            # LETTURA NORMALMENTE CHIUSO (NC)
            GP14 = Pin(PIN_B_NUM, Pin.IN, Pin.PULL_UP)
            GP15 = Pin(PIN_C_NUM, Pin.IN, Pin.PULL_UP)
            
            # 1. Controlliamo se l'interruttore fisico è CHIUSO
            GP14.init(Pin.OUT); GP14.value(0)
            time.sleep_us(100)
            is_closed = (GP15.value() == 0)
            
            # 2. Resettiamo e controlliamo se tocca il bersaglio avversario (Massa)
            GP14.init(Pin.IN, Pin.PULL_UP)
            time.sleep_us(100)
            touching_opp = (GP14.value() == 0 or GP15.value() == 0)

            # Se l'interruttore si è appena APERTO (Bottone schiacciato)
            if not is_closed and not b_was_pressed and not in_lockout:
                if touching_opp:
                    # Tocca la massa -> Bersaglio Valido
                    try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                else:
                    # Non tocca la massa -> Bersaglio Non Valido (Luce Bianca)
                    try: udp_socket.sendto(f"OFF_TARGET_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                    except: pass
                in_lockout = True
                lockout_start_time = current_time
                b_was_pressed = True
                
            # Se l'interruttore è chiuso, resettiamo lo stato
            elif is_closed:
                b_was_pressed = False
                
            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: in_lockout = False

        elif current_weapon == "sciabola":
            GP14 = Pin(PIN_B_NUM, Pin.IN, Pin.PULL_UP)
            if GP14.value() == 0 and not b_was_pressed and not in_lockout:
                try: udp_socket.sendto(f"HIT_{PICO_NAME.upper()}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                in_lockout = True
                lockout_start_time = current_time
                b_was_pressed = True
            elif GP14.value() == 1:
                b_was_pressed = False

            if in_lockout and time.ticks_diff(current_time, lockout_start_time) >= 800: in_lockout = False

try: loop()
except: pass