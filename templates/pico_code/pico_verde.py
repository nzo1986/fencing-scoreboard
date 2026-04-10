import network, time, machine, socket, os
try: import urequests as requests
except: pass
from machine import Pin, ADC, PWM, time_pulse_us

WIFI_SSID, WIFI_PASS = "RouterEnzoM", "Aurorapad5"
PICO_NAME, UDP_IP, UDP_PORT = "verde", "192.168.1.110", 7777

LOCAL_VERSION = "8.0"

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
    # FIRMA ELETTRICA VERDE: PWM a 250 Hz
    # L'impulso HIGH durerà esattamente ~2000 microsecondi
    # ----------------------------------------------------
    pwm13 = PWM(Pin(13))
    pwm13.freq(250)
    pwm13.duty_u16(32768) # Duty cycle 50%

    pin14 = Pin(14, Pin.IN, Pin.PULL_DOWN)
    pin15 = Pin(15, Pin.IN, Pin.PULL_DOWN) 
    
    b_was_pressed = False
    c_was_pressed = False
    in_lockout = False
    lockout_start_time = 0
    ping_next_time = time.ticks_ms()
    last_state_str = ""

    led_active = False
    led_turn_off_time = 0

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

            # --- 1. LETTURA PUNTA (Aspetto la MIA firma: ~2000us) ---
            # La punta della spada chiude il circuito tra 13 e 14.
            pw_14 = -1
            try: pw_14 = time_pulse_us(pin14, 1, 6000)
            except: pass
            
            if 1000 < pw_14 < 3000:
                is_hit = True
                debug_msg = "PUNTA_VERDE_CHIUSA"

            # --- 2. LETTURA COCCIA (Aspetto la MIA firma ~2000us o la ROSSA ~400us) ---
            pw_15 = -1
            try: pw_15 = time_pulse_us(pin15, 1, 6000)
            except: pass
            
            if 1000 < pw_15 < 3000:
                is_coccia = True
                debug_msg = "MIA_LAMA_SU_MIA_COCCIA"
            elif 150 < pw_15 < 650:
                is_coccia = True
                debug_msg = "LAMA_ROSSA_SU_MIA_COCCIA"

            hit_val = 1 if (is_hit and not is_coccia) else 0
            white_val = 1 if is_coccia else 0
            
            # --- FEEDBACK DISPLAY E LED ---
            state_str = f"{hit_val}_{white_val}"
            if state_str != last_state_str:
                if hit_val == 1 or white_val == 1: 
                    onboard_led.value(1)
                    led_active = True
                    led_turn_off_time = time.ticks_add(time.ticks_ms(), 500)
                
                try: udp_socket.sendto(f"STATE_{PICO_NAME.upper()}_{state_str}_{debug_msg}".encode('utf-8'), (UDP_IP, UDP_PORT))
                except: pass
                last_state_str = state_str

            if led_active and time.ticks_diff(time.ticks_ms(), led_turn_off_time) > 0:
                onboard_led.value(0)
                if hit_val == 0 and white_val == 0:
                    led_active = False

            # --- INVIO DATI AL RASPBERRY ---
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