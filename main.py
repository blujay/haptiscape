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

    # Debug: check SD mount and list files
    try:
        if 'sd' in uos.listdir('/'):
            all_files = uos.listdir('/sd')
            wavs = [f for f in all_files if f.lower().endswith('.wav')]
            print('[debug] SD mounted — all files:', all_files)
        else:
            print('[debug] SD not mounted')
    except Exception as e:
        print('[debug] SD check error:', e)

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
        vfs_cls = getattr(uos, 'VfsFat', None)
        if vfs_cls is None:
            raise RuntimeError('VfsFat not available in uos')
        uos.mount(vfs_cls(sd), '/sd')
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
            print('[wifi] Connected —', HOTSPOT_SSID, ip)
            return ip
        time.sleep(1)

    print('[wifi] Failed — offline mode')
    return None


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────

def _start_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    for attempt in range(8):
        server = None
        try:
            server = socket.socket()
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(addr)
            server.listen(1)
            server.settimeout(0.05)
            print('[server] Listening on port 80')
            return server
        except OSError as e:
            err_no = e.args[0] if isinstance(e, OSError) and e.args else None
            if err_no == 98:  # EADDRINUSE
                print('[server] Port 80 already in use; retrying (%d/8)...' % (attempt + 1))
                if server is not None:
                    try:
                        server.close()
                    except Exception:
                        pass
                time.sleep(1)
                continue
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass
            raise
    raise OSError('[server] Failed to bind port 80 after retries')


def run(profile, ip):
    ui      = HapticUI(ip)
    manager = ModeManager(profile)

    server = _start_server()

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
            sel = select.select([sys.stdin], [], [], 0)
            if sel and sel[0]:
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
