# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — SD Card Source
# ──────────────────────────────────────────────────────────────────────────────
# Reads WAV files from the SD card and drives haptic output.
#
# Shares the *shape* of the mic engine's DSP but with softer character:
# where mic goes for dynamic snap, SD goes for nuance — smoother gate,
# gentler power law, ramped motor floor, longer musical release.
# All SD-specific softening lives in the SD_* module constants below,
# so the mic engine and profiles.py stay untouched.
#
# Signal chain per chunk:
#   1. Pull chunk from pre-buffer (or direct read with gentle recovery)
#   2. Per-channel abs peak over the chunk
#   3. Adaptive peak normalisation — running max with moderate decay
#   4. Smoothstep soft gate — C1-continuous across the threshold band
#   5. Envelope follower — slower attack, longer release
#   6. Power law (softer exponents than mic) → output
#   7. Signal-scaled motor floor + shimmer → PWM duty
#   8. Timing sync — busy-wait to stay locked to actual audio rate
#
# Recovery (when the SD bus misbehaves):
#   • Debounced remount attempts (min 1 s between tries)
#   • Baudrate fallback chain — drops SPI clock on repeated failures
#   • Consecutive-failure cap — gives up cleanly, returns to idle
#   • Motors silenced and envelopes reset for the duration of recovery
# ──────────────────────────────────────────────────────────────────────────────

import machine
import struct
import uos
import time
import random


CHUNK_FRAMES = 64     # Stereo frames per chunk  (~1.5 ms at 44.1 kHz)

# ── Adaptive peak tracker ────────────────────────────────────────────────────
PEAK_INIT  = 4096     # Starting floor: ~12 % of 16-bit full scale.
PEAK_DECAY = 0.995    # Per-chunk decay — half-life ~210 ms at 1.5 ms/chunk.
                      # Fast enough that a loud transient doesn't suppress the
                      # next couple of seconds of quieter passage.

# ── SD-specific DSP softening ────────────────────────────────────────────────
# Applied AFTER reading profile params, so the mic engine is unaffected.
SD_POWER_LAW_L = 1.3  # vs mic's 2.0 — less contrast, more faithful to source
SD_POWER_LAW_R = 1.1  # vs mic's 1.5
SD_ATTACK      = 0.20 # slower attack, preserves natural swells
SD_RELEASE     = 0.93 # longer musical decay
SD_FLOOR_KNEE  = 0.15 # pwr level at which the ramped motor floor reaches full

# ── SD recovery behaviour ────────────────────────────────────────────────────
SD_REMOUNT_BAUDS           = (10_000_000, 5_000_000, 1_320_000)
SD_REMOUNT_MIN_INTERVAL_MS = 1000
SD_REMOUNT_MAX_CONSECUTIVE = 3
SD_REMOUNT_SETTLE_MS       = 150

# Recovery result codes returned by _try_recovery()
_REC_OK        = 0    # Remount + reopen succeeded — playback can resume
_REC_FAILED    = 1    # Genuine failure — counts toward the consecutive cap
_REC_DEBOUNCED = 2    # Too soon to retry — caller should wait, not count


class SDSource:
    """
    SD card WAV playback source.
    Non-blocking — step() processes one chunk per call.
    """

    def __init__(self, profile):
        self._profile = profile
        hw   = profile['hardware']
        feel = profile['feel']

        # Own motors + LEDs directly (same as MicSource) so motor_floor applies.
        freq = hw['motor_pwm_freq']
        self.motors = []
        for pin in hw['motors']:
            m = machine.PWM(machine.Pin(pin))
            m.freq(freq)
            m.duty_u16(0)
            self.motors.append(m)

        self.leds = []
        for pin in hw.get('leds', []):
            led = machine.PWM(machine.Pin(pin))
            led.freq(1000)
            led.duty_u16(0)
            self.leds.append(led)

        # Gate thresholds + motor floor come from the profile so both modes
        # share the same loudness reference…
        self._open_thr  = feel['open_threshold']
        self._close_thr = feel['close_threshold']
        self._floor     = feel['motor_floor']

        # …but the power law and envelope character are overridden with the
        # softer SD defaults above. profiles.py stays untouched.
        self._pw_l = SD_POWER_LAW_L
        self._pw_r = SD_POWER_LAW_R
        self._atk  = SD_ATTACK
        self._rel  = SD_RELEASE

        # Per-channel DSP state  [0 = L, 1 = R]
        self._env  = [0.0, 0.0]
        self._peak = [float(PEAK_INIT), float(PEAK_INIT)]

        # Recovery state
        self._remount_baud_idx   = 0
        self._last_remount_ms    = 0
        self._remount_fail_count = 0

        # Playback state
        self._file         = None
        self._active       = False
        self._data_size    = 0
        self._bytes_read   = 0
        self._bytes_played = 0
        self._byte_rate    = 0
        self._channels     = 2
        self._bits         = 16
        self._frame_size   = 4
        self._data_start   = 0
        self._track_path   = None
        self._start_ms     = 0
        self._buffer       = []

    # ── LIFECYCLE ─────────────────────────────────────────────────────────────

    def start(self):
        pass   # Track loaded separately via load_track()

    def stop(self):
        self._active = False
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        self.silence()
        self._track_path   = None
        self._buffer       = []
        self._bytes_played = 0
        self._bytes_read   = 0
        self._env          = [0.0, 0.0]
        self._peak         = [float(PEAK_INIT), float(PEAK_INIT)]
        # Fresh track gets a fresh shot at the full SPI speed.
        self._remount_baud_idx   = 0
        self._last_remount_ms    = 0
        self._remount_fail_count = 0

    def silence(self):
        for m in self.motors:
            m.duty_u16(0)
        for led in self.leds:
            led.duty_u16(0)

    # ── SD REMOUNT ────────────────────────────────────────────────────────────

    def _remount_sd(self):
        """Remount SD at the current fallback baudrate. Returns True on success."""
        pins = self._profile['hardware'].get('sd')
        if not pins:
            return False
        baud = SD_REMOUNT_BAUDS[min(self._remount_baud_idx,
                                    len(SD_REMOUNT_BAUDS) - 1)]
        print('[sd] Remounting at {:.2f} MHz...'.format(baud / 1_000_000))
        try:
            uos.umount('/sd')
        except Exception:
            pass
        try:
            import sdcard as _sdcard
            spi = machine.SPI(1, baudrate=baud,
                              sck=machine.Pin(pins['sck']),
                              mosi=machine.Pin(pins['mosi']),
                              miso=machine.Pin(pins['miso']))
            cs  = machine.Pin(pins['cs'], machine.Pin.OUT)
            sd  = _sdcard.SDCard(spi, cs)
            vfs = getattr(uos, 'VfsFat', None)
            if vfs is None:
                raise RuntimeError('VfsFat unavailable')
            uos.mount(vfs(sd), '/sd')
            print('[sd] Remounted OK')
            return True
        except Exception as e:
            print('[sd] Remount failed:', e)
            return False

    def _advance_remount_baud(self):
        """Drop to the next slower SPI rate for the next recovery attempt."""
        if self._remount_baud_idx < len(SD_REMOUNT_BAUDS) - 1:
            self._remount_baud_idx += 1

    def _try_recovery(self):
        """
        Debounced remount + reopen + seek.
        Returns one of _REC_OK / _REC_FAILED / _REC_DEBOUNCED so the caller
        can distinguish "too soon, wait" from "genuine failure, count it".
        """
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_remount_ms) < SD_REMOUNT_MIN_INTERVAL_MS:
            return _REC_DEBOUNCED
        self._last_remount_ms = now

        if not self._remount_sd():
            self._advance_remount_baud()
            return _REC_FAILED

        time.sleep_ms(SD_REMOUNT_SETTLE_MS)

        if not self._track_path:
            return _REC_FAILED

        try:
            self._file = open(self._track_path, 'rb')
            self._file.seek(self._data_start + self._bytes_played)
            self._start_ms   = time.ticks_ms() - int(
                (self._bytes_played / self._byte_rate) * 1000)
            self._bytes_read = self._bytes_played
            print('[sd] Resumed at byte', self._bytes_played)
            return _REC_OK
        except Exception as e:
            print('[sd] Reopen failed:', e)
            self._advance_remount_baud()
            return _REC_FAILED

    # ── TRACK LOADING ─────────────────────────────────────────────────────────

    def load_track(self, index):
        """Load a WAV file by index (sorted alphabetically from /sd)."""
        self.stop()
        try:
            try:
                uos.listdir('/sd')
            except OSError:
                if not self._remount_sd():
                    return False

            tracks = sorted([f for f in uos.listdir('/sd') if f.lower().endswith('.wav')])
            if not tracks or index >= len(tracks):
                print('[sd] No track at index', index)
                return False

            path             = '/sd/' + tracks[index]
            self._file       = open(path, 'rb')
            self._track_path = path
            self._parse_wav_header()

            self._bytes_read   = 0
            self._bytes_played = 0
            self._start_ms     = time.ticks_ms()
            self._active       = True
            self._buffer       = []

            # Pre-buffer ~15 chunks (~100 ms) for a smooth, click-free start.
            for _ in range(15):
                if self._bytes_read >= self._data_size:
                    break
                c = self._file.read(self._frame_size * CHUNK_FRAMES)
                if not c:
                    break
                self._buffer.append(c)
                self._bytes_read += len(c)

            print('[sd] Playing:', path)
            return True

        except Exception as e:
            print('[sd] Load error:', e)
            self.stop()
            return False

    # ── STEP ──────────────────────────────────────────────────────────────────

    def step(self):
        """
        Process one chunk: read → normalise → DSP → drive → sync.
        Returns 'playing', 'done', or 'idle'.
        """
        if not self._active or not self._file:
            return 'idle'

        # Pull from pre-buffer, or read directly if the buffer has drained.
        if self._buffer:
            chunk = self._buffer.pop(0)
        else:
            if self._bytes_played >= self._data_size:
                self.stop()
                return 'done'
            chunk = self._read_chunk()
            if not chunk:
                # If recovery gave up, stop() was already called inside _read_chunk
                # and self._active is False — we just propagate done.
                if not self._active:
                    return 'done'
                # Transient failure mid-recovery: stay 'playing', try again next tick.
                return 'playing'

        l_max, r_max = self._parse_chunk(chunk)
        self._bytes_played += len(chunk)

        # Adaptive peak normalisation.
        self._peak[0] = max(self._peak[0] * PEAK_DECAY, float(l_max))
        self._peak[1] = max(self._peak[1] * PEAK_DECAY, float(r_max))

        l_norm = min(1.0, l_max / self._peak[0])
        r_norm = min(1.0, r_max / self._peak[1])

        pwr_l = self._dsp(0, l_norm, self._pw_l)
        pwr_r = self._dsp(1, r_norm, self._pw_r)

        self._drive(pwr_l, pwr_r)

        # Refill buffer up to ~12 chunks in the background.
        while len(self._buffer) < 12 and self._bytes_read < self._data_size:
            c = self._read_chunk()
            if not c:
                break
            self._buffer.append(c)

        # Timing sync — busy-wait to stay locked to the actual audio rate.
        target_ms = int((self._bytes_played / self._byte_rate) * 1000)
        while time.ticks_diff(time.ticks_ms(), self._start_ms) < target_ms:
            pass

        # Recovery mid-refill may have called stop() — tell mode_manager now
        # rather than waiting for the next tick to return 'idle'.
        if not self._active:
            return 'done'
        return 'playing'

    # ── DSP — per channel ─────────────────────────────────────────────────────

    def _dsp(self, ch, norm, pw):
        """
        Smoothstep soft gate → envelope follower → power law.
        Replaces the mic engine's hard hysteresis gate with a continuous
        attenuation curve for a more nuanced playback feel.
        ch = 0 (L) or 1 (R).
        """
        # Smoothstep gate factor across the [close_thr, open_thr] band.
        if norm <= self._close_thr:
            g = 0.0
        elif norm >= self._open_thr:
            g = 1.0
        else:
            t = (norm - self._close_thr) / (self._open_thr - self._close_thr)
            g = t * t * (3.0 - 2.0 * t)

        if g <= 0.0:
            self._env[ch] = 0.0
            return 0.0

        # Envelope follower — softer attack / longer release than mic engine.
        if norm > self._env[ch]:
            self._env[ch] = self._atk * self._env[ch] + (1.0 - self._atk) * norm
        else:
            self._env[ch] = self._rel * self._env[ch] + (1.0 - self._rel) * norm

        # Power law modulated by the soft gate.
        return min(1.0, (self._env[ch] * g) ** pw)

    # ── DRIVE ─────────────────────────────────────────────────────────────────

    def _drive(self, pwr_l, pwr_r):
        """
        PWM output with a signal-scaled motor floor:
        at pwr = 0 the floor is 0 (true silence — no snap-on),
        at pwr >= SD_FLOOR_KNEE the floor reaches its full configured value
        and behaviour converges on the mic engine's.
        """
        PWM_MAX = 65535
        floor   = self._floor

        if pwr_l > 0.001 or pwr_r > 0.001:
            shimmer = random.getrandbits(5) - 16

            n = len(self.motors)
            if n >= 2:
                sf_l = int(floor * min(1.0, pwr_l / SD_FLOOR_KNEE))
                sf_r = int(floor * min(1.0, pwr_r / SD_FLOOR_KNEE))
                d_l  = sf_l + int(pwr_l * (PWM_MAX - sf_l)) + shimmer
                d_r  = sf_r + int(pwr_r * (PWM_MAX - sf_r)) + shimmer
                self.motors[0].duty_u16(max(0, min(PWM_MAX, d_l)))
                self.motors[1].duty_u16(max(0, min(PWM_MAX, d_r)))
            elif n == 1:
                p  = max(pwr_l, pwr_r)
                sf = int(floor * min(1.0, p / SD_FLOOR_KNEE))
                d  = sf + int(p * (PWM_MAX - sf)) + shimmer
                self.motors[0].duty_u16(max(0, min(PWM_MAX, d)))

            n_led = len(self.leds)
            if n_led >= 2:
                self.leds[0].duty_u16(min(PWM_MAX, int(pwr_l * PWM_MAX)))
                self.leds[1].duty_u16(min(PWM_MAX, int(pwr_r * PWM_MAX)))
            elif n_led == 1:
                self.leds[0].duty_u16(min(PWM_MAX, int(max(pwr_l, pwr_r) * PWM_MAX)))
        else:
            self.silence()

    # ── INTERNAL ──────────────────────────────────────────────────────────────

    def _read_chunk(self):
        """
        Read one chunk from SD. Returns bytes on success, None on EOF or
        unrecoverable error. On an I/O error, attempts a gentle recovery:
        debounce → remount (with baudrate fallback) → settle → reopen → seek.
        After SD_REMOUNT_MAX_CONSECUTIVE failed recoveries, calls stop()
        so the mode manager falls back to idle.
        """
        if not self._file:
            return None
        try:
            chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
            if chunk:
                self._bytes_read += len(chunk)
                self._remount_fail_count = 0
            return chunk if chunk else None

        except OSError as e:
            print('[sd] Read error ({})'.format(e.args[0] if e.args else e))
            # Drop motors + reset envelope so recovery doesn't resume mid-state.
            self.silence()
            self._env = [0.0, 0.0]

            result = self._try_recovery()

            if result == _REC_DEBOUNCED:
                # Too soon since last attempt — wait, don't count as failure.
                return None

            if result == _REC_FAILED:
                self._remount_fail_count += 1
                if self._remount_fail_count >= SD_REMOUNT_MAX_CONSECUTIVE:
                    print('[sd] Giving up after {} recovery attempts'.format(
                        self._remount_fail_count))
                    self.stop()
                return None

            # _REC_OK — try one read. A failure here counts as a real attempt.
            try:
                chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
                if chunk:
                    self._bytes_read += len(chunk)
                    self._remount_fail_count = 0
                    return chunk
                return None
            except OSError as e2:
                print('[sd] Read after recovery failed:', e2)
                self._remount_fail_count += 1
                if self._remount_fail_count >= SD_REMOUNT_MAX_CONSECUTIVE:
                    print('[sd] Giving up after {} recovery attempts'.format(
                        self._remount_fail_count))
                    self.stop()
                return None

    def _parse_wav_header(self):
        """Parse channels, byte rate, bit depth, and locate the data chunk."""
        f = self._file
        f.seek(22)
        self._channels   = struct.unpack('<H', f.read(2))[0]
        f.seek(28)
        self._byte_rate  = struct.unpack('<I', f.read(4))[0]
        f.seek(34)
        self._bits       = struct.unpack('<H', f.read(2))[0]
        self._frame_size = (self._channels * self._bits) // 8

        # Walk sub-chunks to find 'data' — handles non-standard headers.
        f.seek(12)
        while True:
            chunk_id  = f.read(4)
            if not chunk_id or len(chunk_id) < 4:
                break
            chunk_len = struct.unpack('<I', f.read(4))[0]
            if chunk_id == b'data':
                self._data_size  = chunk_len
                self._data_start = f.tell()
                break
            f.seek(chunk_len, 1)

    def _parse_chunk(self, chunk):
        """Return abs peak (l_max, r_max) across all frames in the chunk."""
        l_max = r_max = 0
        fs = self._frame_size

        if self._bits == 16:
            for i in range(0, len(chunk) - fs + 1, fs):
                if self._channels == 2:
                    l, r  = struct.unpack('<hh', chunk[i:i + 4])
                    l_max = max(l_max, abs(l))
                    r_max = max(r_max, abs(r))
                else:
                    v     = struct.unpack('<h', chunk[i:i + 2])[0]
                    l_max = r_max = max(l_max, abs(v))
        elif self._bits == 8:
            for i in range(0, len(chunk) - fs + 1, fs):
                if self._channels == 2:
                    l_max = max(l_max, abs(chunk[i]     - 128) * 256)
                    r_max = max(r_max, abs(chunk[i + 1] - 128) * 256)
                else:
                    l_max = r_max = max(l_max, abs(chunk[i] - 128) * 256)

        return l_max, r_max
