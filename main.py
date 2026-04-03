# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — System Entry Point
# ──────────────────────────────────────────────────────────────────────────────
# Boot sequence:
#   1. Load active profile from profiles.py
#   2. Mount SD card (if profile has one)
#   3. Connect to Wi-Fi
#   4. Start web server + mode manager loop
# ──────────────────────────────────────────────────────────────────────────────

import machine
import network
import socket
import select
import sys
import time
import uos

from config import ACTIVE_PROFILE, HOTSPOT_SSID, HOTSPOT_PASSWORD
from profiles import PROFILES
from mode_manager import ModeManager
from interface import HapticUI


# ──────────────────────────────────────────────────────────────────────────────
# BOOT
# ──────────────────────────────────────────────────────────────────────────────

def boot():
    print('\n' + '=' * 44)
    print('   HAPTISCAPE')
    print('=' * 44)

    profile = PROFILES[ACTIVE_PROFILE]
    print('Profile:', ACTIVE_PROFILE)

    _mount_sd(profile)
    ip = _connect_wifi()

    print('=' * 44)
    if ip:
        print('   Ready — http://' + ip)
    else:
        print('   Ready — offline mode')
    print('=' * 44 + '\n')

    return profile, ip


# ──────────────────────────────────────────────────────────────────────────────
# SD CARD
# ──────────────────────────────────────────────────────────────────────────────

def _mount_sd(profile):
    if 'sd' not in profile.get('hardware', {}):
        return

    pins = profile['hardware']['sd']
    print('[sd] Mounting...')
    try:
        if 'sd' in uos.listdir('/'):
            print('[sd] Already mounted')
            return
        import sdcard
        spi = machine.SPI(1, baudrate=40_000_000,
                          sck=machine.Pin(pins['sck']),
                          mosi=machine.Pin(pins['mosi']),
                          miso=machine.Pin(pins['miso']))
        cs  = machine.Pin(pins['cs'], machine.Pin.OUT)
        sd  = sdcard.SDCard(spi, cs)
        uos.mount(uos.VfsFat(sd), '/sd')
        wavs = [f for f in uos.listdir('/sd') if f.lower().endswith('.wav')]
        print('[sd] Mounted —', len(wavs), 'WAV file(s)')
    except Exception as e:
        print('[sd] Mount failed:', e)


# ──────────────────────────────────────────────────────────────────────────────
# WI-FI
# ──────────────────────────────────────────────────────────────────────────────

def _connect_wifi():
    print('[wifi] Connecting...')
    sta = network.WLAN(network.STA_IF)
    ap  = network.WLAN(network.AP_IF)
    if ap.active():
        ap.active(False)

    sta.active(True)
    sta.connect(HOTSPOT_SSID, HOTSPOT_PASSWORD)

    for _ in range(20):
        if sta.isconnected():
            ip = sta.ifconfig()[0]
            print('[wifi] Connected —', ip)
            return ip
        time.sleep(1)

    print('[wifi] Failed — offline mode')
    return None


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────

def run(profile, ip):
    ui      = HapticUI(ip)
    manager = ModeManager(profile)

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(socket.getaddrinfo('0.0.0.0', 80)[0][-1])
    server.listen(1)
    server.settimeout(0.05)

    print('[server] Listening on port 80')

    while True:

        # Web request
        try:
            conn, _ = server.accept()
            request = conn.recv(2048).decode('utf-8', 'ignore')
            new_mode, response = ui.handle_request(request)
            conn.send(response)
            conn.close()

            if new_mode == 'reconnect':
                ip = _connect_wifi()
                ui = HapticUI(ip)
            elif new_mode:
                manager.switch(new_mode)

        except OSError:
            pass

        # Console shortcuts (for quick testing without the web UI)
        try:
            if select.select([sys.stdin], [], [], 0)[0]:
                key = sys.stdin.read(1).lower()
                if key == 'm':
                    manager.switch('mic')
                elif key == 's':
                    manager.switch('sd_0')
                elif key == 'i':
                    manager.switch('idle')
                elif key == 'r':
                    machine.reset()
        except Exception:
            pass

        # Run active source
        manager.step()

        time.sleep(0.03)


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    profile, ip = boot()
    run(profile, ip)
