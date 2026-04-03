import machine
import os
import uos
import time
import network
import socket
import sys
import select

from interface import HapticUI
# Import configuration from config.py
try:
    import config
    MOTOR_PINS = config.MOTOR_PINS
    SD_SCK = config.SD_PINS['sck']
    SD_MOSI = config.SD_PINS['mosi']
    SD_MISO = config.SD_PINS['miso']
    SD_CS = config.SD_PINS['cs']
    SSID = config.HOTSPOT_SSID
    PASS = config.HOTSPOT_PASSWORD
except ImportError:
    print("⚠️ config.py not found. Falling back to defaults.")
    MOTOR_PINS = [15, 16]
    SD_SCK, SD_MOSI, SD_MISO, SD_CS = 10, 11, 12, 13
    SSID, PASS = "Your_Hotspot_SSID", "Your_Hotspot_Password"

# Hardware constants
LED_PIN = 14

# Attempt to import hardware feature modules
try:
    import main_mic
    MIC_SUPPORTED = True
except ImportError:
    MIC_SUPPORTED = False
    print("⚠️ main_mic.py not found. Microphone features will be disabled.")

try:
    import main_sd
    SD_PLAYBACK_SUPPORTED = True
except ImportError:
    SD_PLAYBACK_SUPPORTED = False
    print("⚠️ main_sd.py not found. SD playback features will be disabled.")


class HaptiscapeSystem:
    def __init__(self):
        print("\n" + "=" * 40)
        print("   HAPTISCAPE SYSTEM DIAGNOSTICS")
        print("=" * 40)

        self.led = machine.Pin(LED_PIN, machine.Pin.OUT)
        self.motors = []
        for p in MOTOR_PINS:
            try:
                m = machine.PWM(machine.Pin(p))
                m.freq(1000)
                m.duty_u16(0)
                self.motors.append(m)
            except Exception as e:
                print(f"⚠️ Motor init failed GP{p}: {e}")

        # Hardware pulse test
        print("📳 DIAGNOSTIC: Pulsing Motors & LED...")
        for _ in range(2):
            self.led.value(1)
            for m in self.motors:
                m.duty_u16(40000)
            time.sleep(0.2)
            self.led.value(0)
            for m in self.motors:
                m.duty_u16(0)
            time.sleep(0.1)
        print("  - Hardware response verified.")

        self.try_mount_sd()
        self.check_sd_contents()

        self.ip = self.connect_wifi()

        if self.ip:
            print("✨ CONNECTION CONFIRMED: Pulsing success signal...")
            for _ in range(2):
                self.led.value(1)
                for m in self.motors:
                    m.duty_u16(30000)
                time.sleep(0.1)
                self.led.value(0)
                for m in self.motors:
                    m.duty_u16(0)
                time.sleep(0.1)

        print("=" * 40)
        print("   SYSTEM READY - STARTING SERVER")
        if self.ip:
            print(f"   URL: http://{self.ip}")
        else:
            print("   OFFLINE MODE")
        print("=" * 40 + "\n")

    def try_mount_sd(self):
        print("💾 SD CARD: Attempting Mount...")
        try:
            if 'sd' in uos.listdir('/'):
                print("  - Status: ALREADY MOUNTED")
                return
            import sdcard
            spi = machine.SPI(1, baudrate=40000000,
                               sck=machine.Pin(SD_SCK),
                               mosi=machine.Pin(SD_MOSI),
                               miso=machine.Pin(SD_MISO))
            cs = machine.Pin(SD_CS, machine.Pin.OUT)
            sd = sdcard.SDCard(spi, cs)
            vfs = getattr(uos, 'VfsFat', None) or getattr(os, 'VfsFat', None)
            if not vfs:
                raise RuntimeError('VfsFat not available')
            uos.mount(vfs(sd), '/sd')
            print("  - Status: MOUNT SUCCESSFUL")
        except Exception as e:
            print(f"  ❌ Status: MOUNT FAILED ({e})")

    def check_sd_contents(self):
        print("📂 SD CARD: Checking contents...")
        try:
            if 'sd' in uos.listdir('/'):
                sd_files = uos.listdir('/sd')
                wav_files = [f for f in sd_files if f.lower().endswith('.wav')]
                print(f"  - WAV Tracks found: {len(wav_files)}")
                for i, track in enumerate(sorted(wav_files)):
                    print(f"    [{i+1}] {track}")
            else:
                print("  ⚠️ Status: SD MOUNT NOT FOUND")
        except Exception as e:
            print(f"  ❌ File System Error: {e}")

    def connect_wifi(self, fallback_to_ap=False):
        print("📡 NETWORK: Connecting to Wi-Fi (STA mode)...")

        sta = network.WLAN(network.STA_IF)
        ap = network.WLAN(network.AP_IF)

        if ap.active():
            print("  - Disabling AP mode before STA attempt")
            ap.active(False)

        if sta.isconnected():
            print("  - Already connected, disconnecting first")
            sta.disconnect()
            time.sleep(0.5)

        sta.active(True)

        attempts = 3
        for attempt in range(1, attempts + 1):
            print(f"  - STA connect attempt {attempt}/{attempts}")
            try:
                sta.connect(SSID, PASS)
            except Exception as e:
                print('⚠️ STA connect call failed:', e)

            wait = 20
            while wait > 0:
                status = sta.status()
                print(f"    > status={status}")
                if status == 3:
                    break
                if status == 4 or status < 0:
                    break
                self.led.value(1 if wait % 2 == 0 else 0)
                time.sleep(1)
                wait -= 1

            self.led.value(0)

            if sta.isconnected():
                ip = sta.ifconfig()[0]
                print("  - Status: CONNECTED (STA)")
                print(f"  - IP: {ip}")
                return ip

            print(f"  - STA attempt {attempt} failed (status={sta.status()})")

        print("  ❌ STA mode failed after retries")

        if not fallback_to_ap:
            print("  ❌ AP fallback disabled; returning None")
            return None

        print("  ℹ️ Falling back to AP mode")
        try:
            ap.active(True)
            ap.config(essid=SSID, password=PASS)

            wait_ap = 10
            while wait_ap > 0 and not ap.active():
                wait_ap -= 1
                time.sleep(0.1)

            if ap.active():
                ip = ap.ifconfig()[0]
                print("  - Status: AP MODE ACTIVE")
                print(f"  - AP IP: {ip}")
                return ip
            else:
                print("  ❌ AP mode failed to activate")
        except Exception as e:
            print('  ❌ AP mode error:', e)

        print("  ❌ No network mode available")
        return None

    def reconnect_wifi(self):
        print("📡 NETWORK: Reconnect requested")
        self.ip = self.connect_wifi()
        return self.ip


def start_server(system):
    ui = HapticUI(system.ip)
    server = socket.socket()
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(1)
    server.settimeout(0.1)

    print("🚀 Web Interface Live...")

    mic_engine = None
    sd_session = None

    if MIC_SUPPORTED and hasattr(main_mic, 'HapticMicEngine'):
        mic_engine = main_mic.HapticMicEngine()

    if SD_PLAYBACK_SUPPORTED and hasattr(main_sd, 'SDPlayerSession'):
        sd_session = main_sd.SDPlayerSession()

    from mode_manager import ModeManager
    mode_manager = ModeManager(mic_engine=mic_engine, sd_session=sd_session, ui=ui)

    while True:
        try:
            conn, addr = server.accept()
            request = conn.recv(2048).decode('utf-8', 'ignore')

            new_mode, response = ui.handle_request(request)
            conn.send(response)
            conn.close()

            if new_mode == 'reset':
                machine.reset()

            if new_mode == 'reconnect':
                system.reconnect_wifi()
                ui = HapticUI(system.ip)
                new_mode = 'idle'
            elif new_mode is not None:
                mode_manager.switch(new_mode)

        except OSError:
            # Connection timeout; continue loop for step updates
            pass
        except Exception:
            pass

        # Local console shortcuts
        try:
            ready = select.select([sys.stdin], [], [], 0)
            if ready and ready[0]:
                c = sys.stdin.read(1).lower()
                if c == '1':
                    mode_manager.switch('mic')
                elif c == 's':
                    mode_manager.switch('sd_0')
                elif c == 'i':
                    mode_manager.switch('idle')
                elif c == 'r':
                    machine.reset()
        except Exception:
            pass

        # Run mode logic
        mode_manager.step()

        time.sleep(0.03)


if __name__ == '__main__':
    system = HaptiscapeSystem()
    if system.ip is not None:
        start_server(system)
    else:
        print('⚠️ Wi-Fi not available. Running in offline mode. Press key 1 for mic; s for sd_0.')
        start_server(system)