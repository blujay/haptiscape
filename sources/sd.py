# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — SD Card Source
# ──────────────────────────────────────────────────────────────────────────────
# Reads WAV files from the SD card and drives haptic output.
#
# Signal chain per chunk:
#   1. Pull chunk from pre-buffer (or direct from SD with remount recovery)
#   2. Per-channel abs peak over the chunk
#   3. Adaptive peak normalisation — running max with slow decay.
#      Prevents the first-chunk over-drive that caused harsh startup.
#   4. Per-channel hysteresis gate (open/close threshold + hold + fade)
#   5. Envelope follower — fast attack, moderate release
#   6. Power law → high-contrast output
#   7. Motor floor + shimmer → PWM duty
#      Same floor as mic engine — ERMs ramp gracefully, no snap-on.
#   8. Timing sync — busy-wait to stay locked to actual audio rate
#
# Uses the same feel parameters as the mic engine (open_threshold,
# close_threshold, release_coeff, power_law_l/r, motor_floor, hold_time_ms)
# so both modes feel consistent and are tuned from one place.
# ──────────────────────────────────────────────────────────────────────────────

import machine
import struct
import uos
import time
import random


CHUNK_FRAMES = 64     # Stereo frames per chunk  (~1.5 ms at 44.1 kHz)

# Adaptive peak tracker — prevents normalisation blowing up on quiet intros.
PEAK_INIT  = 4096     # Starting floor: ~12 % of 16-bit full scale.
PEAK_DECAY = 0.9992   # Per-chunk decay — slowly forgets old peaks.


class SDSource:
    """
    SD card WAV playback source.

    Drives haptic motors with the same gate / envelope / power-law pipeline
    as MicSource, so the two modes feel consistent and share profile tuning.
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

        # Feel parameters — shared with mic engine, tuned in profiles.py
        self._open_thr  = feel['open_threshold']
        self._close_thr = feel['close_threshold']
        self._rel_coeff = feel['release_coeff']
        self._floor     = feel['motor_floor']
        self._pw_l      = feel['power_law_l']
        self._pw_r      = feel['power_law_r']
        self._hold_ms   = feel['hold_time_ms']

        # Envelope time constants for chunk-rate processing.
        # At 44.1 kHz / 64 frames each chunk is ~1.5 ms.
        # atk=0.35 → 65 % blend per chunk  (~3 ms to peak)
        # rel=0.88 → keeps 88 % per chunk  (~15 ms release)
        self._atk = 0.35
        self._rel = 0.88

        # Per-channel DSP state  [0 = L, 1 = R]
        self._env       = [0.0, 0.0]
        self._gate      = [False, False]
        self._fade      = [0.0, 0.0]
        self._hold_ctr  = [0, 0]
        self._hold_chunks = 6          # Recalculated after WAV header parse
        self._peak      = [float(PEAK_INIT), float(PEAK_INIT)]

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
        self._env      = [0.0, 0.0]
        self._gate     = [False, False]
        self._fade     = [0.0, 0.0]
        self._hold_ctr = [0, 0]
        self._peak     = [float(PEAK_INIT), float(PEAK_INIT)]

    def silence(self):
        for m in self.motors:
            m.duty_u16(0)
        for led in self.leds:
            led.duty_u16(0)

    # ── SD REMOUNT ────────────────────────────────────────────────────────────

    def _remount_sd(self):
        """Unmount and remount the SD card to recover from a bus error."""
        pins = self._profile['hardware'].get('sd')
        if not pins:
            return False
        print('[sd] Remounting...')
        try:
            uos.umount('/sd')
        except Exception:
            pass
        try:
            import sdcard as _sdcard
            spi = machine.SPI(1, baudrate=20_000_000,
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

            # Convert hold_time_ms into chunks now that byte_rate is known.
            chunk_ms = (self._frame_size * CHUNK_FRAMES / self._byte_rate) * 1000
            self._hold_chunks = max(1, int(self._hold_ms / chunk_ms))

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
                self.stop()
                return 'done'

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

        return 'playing'

    # ── DSP — per channel ─────────────────────────────────────────────────────

    def _dsp(self, ch, norm, pw):
        """
        Hysteresis gate → envelope follower → power law.
        Mirrors MicSource._process() but applied per chunk instead of per sample.
        ch = 0 (L) or 1 (R).
        """
        # Hysteresis gate with hold and exponential fade — same logic as mic engine
        if norm > self._open_thr:
            self._gate[ch]     = True
            self._hold_ctr[ch] = self._hold_chunks
            self._fade[ch]     = 1.0
        elif norm < self._close_thr:
            if self._hold_ctr[ch] > 0:
                self._hold_ctr[ch] -= 1
            else:
                self._fade[ch] *= self._rel_coeff
                if self._fade[ch] < 0.01:
                    self._fade[ch] = 0.0
                    self._gate[ch] = False

        if not self._gate[ch]:
            self._env[ch] = 0.0
            return 0.0

        # Envelope follower — fast attack, moderate release
        if norm > self._env[ch]:
            self._env[ch] = self._atk * self._env[ch] + (1.0 - self._atk) * norm
        else:
            self._env[ch] = self._rel * self._env[ch] + (1.0 - self._rel) * norm

        # Power law + gate fade
        return min(1.0, (self._env[ch] * self._fade[ch]) ** pw)

    # ── DRIVE ─────────────────────────────────────────────────────────────────

    def _drive(self, pwr_l, pwr_r):
        """Write PWM duties to motors and LEDs. Mirrors MicSource._drive()."""
        PWM_MAX = 65535
        floor   = self._floor

        if pwr_l > 0.002 or pwr_r > 0.002:
            shimmer = random.getrandbits(5) - 16

            n = len(self.motors)
            if n >= 2:
                d_l = int(floor + pwr_l * (PWM_MAX - floor)) + shimmer
                d_r = int(floor + pwr_r * (PWM_MAX - floor)) + shimmer
                self.motors[0].duty_u16(max(0, min(PWM_MAX, d_l)))
                self.motors[1].duty_u16(max(0, min(PWM_MAX, d_r)))
            elif n == 1:
                d = int(floor + max(pwr_l, pwr_r) * (PWM_MAX - floor)) + shimmer
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
        Read one chunk from SD. Returns bytes on success, None on EOF or error.
        Attempts a remount + seek-resume on OSError.
        """
        try:
            chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
            if chunk:
                self._bytes_read += len(chunk)
            return chunk if chunk else None
        except OSError as e:
            print('[sd] Read error ({}) — attempting remount'.format(
                e.args[0] if e.args else e))
            if self._remount_sd():
                time.sleep_ms(50)
                if self._track_path:
                    try:
                        self._file = open(self._track_path, 'rb')
                        self._file.seek(self._data_start + self._bytes_played)
                        self._start_ms   = time.ticks_ms() - int(
                            (self._bytes_played / self._byte_rate) * 1000)
                        self._bytes_read = self._bytes_played
                        print('[sd] Reopened at byte', self._bytes_played)
                        chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
                        if chunk:
                            self._bytes_read += len(chunk)
                        return chunk if chunk else None
                    except Exception as e2:
                        print('[sd] Failed to reopen file:', e2)
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
