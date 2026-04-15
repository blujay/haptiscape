# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — System Entry Point
# ──────────────────────────────────────────────────────────────────────────────
# Boot sequence:
#   1. Start Wi-Fi (non-blocking) + light onboard LED as "I'm alive"
#   2. Mount SD card (if profile has one)
#   3. Run motor diagnostics (Wi-Fi connects in the background during this)
#   4. Await Wi-Fi result — offline mode if not up yet, mic still starts either way
#   5. Start web server + mode manager loop
# ──────────────────────────────────────────────────────────────────────────────

import machine
import network
import rp2
import socket
import select
import sys
import time
import uos

from config import ACTIVE_PROFILE, HOTSPOT_SSID, HOTSPOT_PASSWORD
from profiles import PROFILES
from mode_manager import ModeManager
from interface import HapticUI


class RestartRequest(Exception):
    """Raised by the BOOTSEL restart hold. Caught at the entry point to
    re-run boot() + run() without dropping the USB/Thonny connection."""
    pass


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

    # Kick off Wi-Fi early (non-blocking). Also wakes the CYW43 chip,
    # which is required before the onboard LED can be driven on a Pico W.
    _begin_wifi()

    # "I'm alive" — onboard LED on as soon as CYW43 is up
    machine.Pin("LED", machine.Pin.OUT).on()

    return profile


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

def _begin_wifi():
    """Start Wi-Fi connection without waiting. Returns immediately."""
    print('[wifi] Connecting to', HOTSPOT_SSID, '...')
    sta = network.WLAN(network.STA_IF)
    ap  = network.WLAN(network.AP_IF)
    if ap.active():
        ap.active(False)
    sta.active(True)
    sta.connect(HOTSPOT_SSID, HOTSPOT_PASSWORD)


def _await_wifi(timeout_s=8):
    """
    Poll for an active Wi-Fi connection for up to timeout_s seconds.
    Returns the IP string on success, or None for offline mode.
    Call this after _begin_wifi() has had a chance to connect in the background.
    """
    sta = network.WLAN(network.STA_IF)
    for _ in range(timeout_s):
        if sta.isconnected():
            ip = sta.ifconfig()[0]
            print('[wifi] Connected —', HOTSPOT_SSID, ip)
            return ip
        time.sleep(1)
    print('[wifi] No connection — offline mode')
    return None


def _connect_wifi():
    """Blocking reconnect — used by the web UI 'reconnect' command."""
    _begin_wifi()
    return _await_wifi(timeout_s=15)


# ──────────────────────────────────────────────────────────────────────────────
# STARTUP DIAGNOSTICS
# ──────────────────────────────────────────────────────────────────────────────

def _run_motor_diagnostics(profile):
    """Ramp each motor from 0 → 100% over 2 s with its LED, then silence."""
    from output import HapticOutput

    hw = profile['hardware']
    n_motors = len(hw.get('motors', []))
    if n_motors == 0:
        print('[diag] No motors in profile — skipping motor test')
        return

    print('[diag] Motor test — ramping each motor 0→100% in 2 s')
    out = HapticOutput(profile)

    steps  = 100
    step_s = 2.0 / steps  # 20 ms per step

    for idx in range(n_motors):
        label = ('L', 'R', str(idx))[min(idx, 2)]
        pan   = 0.0 if idx == 0 else 1.0   # full-left / full-right in stereo
        print('[diag] Motor {} ...'.format(label))
        for step in range(steps + 1):
            level = step / steps
            out.set(level, pan)
            time.sleep(step_s)
        out.silence()
        time.sleep(0.2)

    print('[diag] Motor test complete\n')
    out.silence()
    # Release PWM objects so sources can re-initialise the same pins
    del out


def _list_sd_tracks():
    """Return a sorted list of WAV filenames on the SD card, or []."""
    try:
        if 'sd' not in uos.listdir('/'):
            return []
        all_files = uos.listdir('/sd')
    except Exception as e:
        print('[diag] SD read error:', e)
        return []

    print('\n[sd] /sd contents:')
    for f in sorted(all_files):
        print('       ', f)

    wavs = sorted(f for f in all_files if f.lower().endswith('.wav'))
    return wavs


def _startup_track_select(manager, wavs):
    """
    Print the WAV track list and wait up to 5 s for a digit keypress.
    Starts the chosen track, or defaults to mic mode.
    """
    if wavs:
        print('\n[sd] WAV tracks:')
        for i, name in enumerate(wavs):
            print('  [{}] {}'.format(i, name))
        limit = min(len(wavs), 10)
        print('\n  Press 0–{} to play a track, or wait 5 s for mic mode...'.format(limit - 1))
    else:
        print('[diag] No WAV files found — starting mic mode')
        manager.switch('mic')
        return

    deadline_ms = time.ticks_add(time.ticks_ms(), 5000)
    while time.ticks_diff(deadline_ms, time.ticks_ms()) > 0:
        try:
            sel = select.select([sys.stdin], [], [], 0)
            if sel and sel[0]:
                key = sys.stdin.read(1)
                if key.isdigit():
                    idx = int(key)
                    if idx < len(wavs):
                        print('[diag] Playing track {}: {}'.format(idx, wavs[idx]))
                        manager.switch('sd_{}'.format(idx))
                        return
                # Any non-digit key → fall through to mic
                break
        except Exception:
            pass

    print('[diag] Starting mic mode')
    manager.switch('mic')


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
            server.settimeout(0.01)   # 10ms — keeps main loop responsive for mic
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


def run(profile):
    manager = ModeManager(profile)

    # ── Motor diagnostics ─────────────────────────────────────────────────────
    # Wi-Fi is connecting in the background during this ~4 s window.
    _run_motor_diagnostics(profile)

    # ── Wi-Fi result ──────────────────────────────────────────────────────────
    # By now Wi-Fi has usually finished. Allow up to 5 more seconds if needed.
    ip = _await_wifi(timeout_s=5)

    ui = HapticUI(ip)
    manager = ModeManager(profile, ui)

    print('=' * 44)
    if ip:
        print('   Ready — http://' + ip)
    else:
        print('   Ready — offline mode (mic still active)')
    print('=' * 44 + '\n')

    # ── Mode select ───────────────────────────────────────────────────────────
    wavs = _list_sd_tracks()
    _startup_track_select(manager, wavs)
    ui.current_mode = manager.mode

    # ── Web server (binds even in offline mode; only reachable if Wi-Fi is up) ─
    server = _start_server()

    # ── BOOTSEL button state ──────────────────────────────────────────────────
    # Long hold (≥2 s): first → silence all haptics; second → machine.reset()
    _bootsel_start    = None   # ticks_ms when press began, or None
    _bootsel_consumed = False  # True = action fired this hold; wait for release
    _haptic_halted    = False  # True = silenced by BOOTSEL, waiting for reset hold

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
                manager.ui = ui
            elif new_mode:
                manager.switch(new_mode)
                ui.current_mode = manager.mode
                _haptic_halted = False   # Manual mode change clears halted state

        except OSError:
            pass

        # Console shortcuts (for quick testing without the web UI)
        # m=mic  i=idle  r=reset  0-9=sd track  l=list tracks
        try:
            sel = select.select([sys.stdin], [], [], 0)
            if sel and sel[0]:
                key = sys.stdin.read(1).lower()
                if key == 'm':
                    manager.switch('mic')
                    _haptic_halted = False
                elif key == 'i':
                    manager.switch('idle')
                elif key == 'r':
                    machine.reset()
                elif key == 'l':
                    w = _list_sd_tracks()
                    if w:
                        print('[sd] WAV tracks:')
                        for i, name in enumerate(w):
                            print('  [{}] {}'.format(i, name))
                elif key.isdigit():
                    idx = int(key)
                    manager.switch('sd_{}'.format(idx))
                    _haptic_halted = False
        except Exception:
            pass

        # ── BOOTSEL long-hold detection ───────────────────────────────────────
        # Long hold (≥2 s) while running → silence everything (idle)
        # Short press while halted       → restart application
        if rp2.bootsel_button():
            if not _bootsel_consumed:
                if _bootsel_start is None:
                    _bootsel_start = time.ticks_ms()
                elif time.ticks_diff(time.ticks_ms(), _bootsel_start) >= 2000:
                    _bootsel_consumed = True   # Don't re-fire while still held
                    if not _haptic_halted:
                        print('[bootsel] Long hold — haptics halted. Press to restart.')
                        manager.switch('idle')
                        _haptic_halted = True
        else:
            # Button released — check for short press while halted
            if _haptic_halted and _bootsel_start is not None and not _bootsel_consumed:
                print('[bootsel] Restarting application...')
                _bootsel_start    = None
                _bootsel_consumed = False
                raise RestartRequest()
            _bootsel_start    = None
            _bootsel_consumed = False

        # Run active source
        manager.step()

        time.sleep(0.001)   # step() handles its own timing; this just yields briefly


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    while True:
        try:
            profile = boot()
            run(profile)
        except RestartRequest:
            # Software restart — USB/Thonny connection stays alive.
            # boot() and run() re-initialise everything from scratch.
            print('[system] --- RESTART ---\n')
