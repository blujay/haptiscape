# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — SD Card Source
# ──────────────────────────────────────────────────────────────────────────────
# Reads WAV files from the SD card and drives haptic output from the envelope.
#
# Supports 16-bit stereo and mono WAV at any sample rate the SD card
# can serve reliably (44.1kHz stereo is the tested ceiling).
#
# Audio quality optimisations (pro streaming approach):
#  • 12-chunk (100ms) pre-buffer for smooth jitter-free playback
#  • DC offset removal (auto-measured from first chunk)
#  • Peak-based normalization (80% headroom to prevent clipping)
#  • Fade-in ramps (50ms) to eliminate click-on-start artifacts
#  • Real-time buffer refill to minimize read blocking
# ──────────────────────────────────────────────────────────────────────────────

import machine
import struct
import uos
import time

from output import HapticOutput
from processing import EnvelopeFollower, PanFollower


# Block of samples read per step — ~64 stereo frames per tick
CHUNK_FRAMES = 64


class SDSource:
    """
    SD card WAV playback source.
    Parses the WAV envelope frame-by-frame and drives haptic output.
    Non-blocking — step() reads one chunk per call so mode_manager
    stays responsive.
    """

    def __init__(self, profile):
        self._profile = profile
        self.output   = HapticOutput(profile)
        self.envelope_l = EnvelopeFollower(profile['feel'])
        self.envelope_r = EnvelopeFollower(profile['feel'])
        self.pan        = PanFollower(profile['feel'])

        self._file       = None
        self._active     = False
        self._data_size  = 0
        self._bytes_read = 0
        self._byte_rate  = 0
        self._channels   = 2
        self._bits       = 16
        self._frame_size = 4
        self._start_ms   = 0
        self._track_path = None
        self._data_start = 0
        self._buffer = []
        self._bytes_played = 0
        
        # Audio quality improvements
        self._dc_offset = 0.0
        self._peak_level = 0.0
        self._fade_in_samples = int(0.05 * 8000)  # 50ms fade-in at 8kHz
        self._fade_counter = 0  # 0 = pre-fade, >0 = fading in, -1 = no fade

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
        self.output.silence()
        self._track_path = None
        self._data_start = 0
        self._buffer = []
        self._bytes_played = 0
        self._dc_offset = 0.0
        self._peak_level = 0.0
        self._fade_counter = 0

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
            cs = machine.Pin(pins['cs'], machine.Pin.OUT)
            sd = _sdcard.SDCard(spi, cs)
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
            # Quick health-check — remount if the SD is unresponsive
            try:
                uos.listdir('/sd')
            except OSError:
                if not self._remount_sd():
                    return False

            tracks = sorted([f for f in uos.listdir('/sd') if f.lower().endswith('.wav')])
            if not tracks or index >= len(tracks):
                print('[sd] No track at index', index)
                return False

            path = '/sd/' + tracks[index]
            self._file = open(path, 'rb')
            self._track_path = path
            self._parse_wav_header()
            self._bytes_read = 0
            self._bytes_played = 0
            self._start_ms   = time.ticks_ms()
            self._active     = True
            self._buffer = []
            self._fade_counter = 0  # Start fade-in
            
            # Pre-buffer 12-15 chunks (~100-120ms) for smooth playback
            for i in range(15):
                if self._bytes_read >= self._data_size:
                    break
                try:
                    chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
                except OSError:
                    break
                if not chunk:
                    break
                self._buffer.append(chunk)
                self._bytes_read += len(chunk)
                
                # Analyze DC offset and peak from first chunk
                if i == 0 and chunk:
                    self._analyze_chunk_for_dc_and_peak(chunk)
            print('[sd] Playing:', path)
            return True

        except Exception as e:
            print('[sd] Load error:', e)
            self.stop()
            return False

    # ── STEP — called every loop tick by mode_manager ─────────────────────────

    def step(self):
        """
        Buffered WAV playback: uses a buffer of pre-read chunks for smooth playback,
        refills buffer in background. Falls back to direct read if buffer empty.
        Returns 'playing', 'done', or 'idle'.
        """
        if not self._active or not self._file:
            return 'idle'

        if not self._buffer:
            if self._bytes_played >= self._data_size:
                self.stop()
                return 'done'
            try:
                chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
            except OSError as e:
                print('[sd] Read error ({}) — attempting remount'.format(e.args[0] if e.args else e))
                if self._remount_sd():
                    time.sleep_ms(50)
                    if self._track_path:
                        try:
                            self._file = open(self._track_path, 'rb')
                            self._file.seek(self._data_start + self._bytes_played)
                            self._start_ms = time.ticks_ms() - int((self._bytes_played / self._byte_rate) * 1000)
                            self._bytes_read = self._bytes_played
                            print('[sd] Reopened at byte', self._bytes_played)
                            chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
                            if chunk:
                                self._bytes_read += len(chunk)
                            else:
                                self.stop()
                                return 'done'
                        except Exception as e2:
                            print('[sd] Failed to reopen file:', e2)
                            self.stop()
                            return 'done'
                    else:
                        self.stop()
                        return 'done'
                else:
                    self.stop()
                    return 'done'
            if not chunk:
                self.stop()
                return 'done'
            self._bytes_read += len(chunk)
        else:
            chunk = self._buffer.pop(0)

        l_max, r_max = self._parse_chunk(chunk)
        self._bytes_played += len(chunk)

        # Remove DC offset
        l_max_adj = max(0.0, (l_max / 32768.0) - self._dc_offset)
        r_max_adj = max(0.0, (r_max / 32768.0) - self._dc_offset)
        
        # Normalize to 80% headroom to prevent clipping
        headroom = 0.8
        if self._peak_level > 0:
            l_max_adj = (l_max_adj / self._peak_level) * headroom
            r_max_adj = (r_max_adj / self._peak_level) * headroom
        
        level_l = self.envelope_l.process(l_max_adj)
        level_r = self.envelope_r.process(r_max_adj)

        # Derive pan from relative channel levels
        total = level_l + level_r
        pan   = (level_r / total) if total > 0 else 0.5
        pan   = self.pan.process(pan)

        level = max(level_l, level_r)
        level = self._apply_fade(level)  # Fade-in
        self.output.set(level, pan)

        # Refill buffer to 12 chunks (~100ms)
        while len(self._buffer) < 12 and self._bytes_read < self._data_size:
            try:
                chunk2 = self._file.read(self._frame_size * CHUNK_FRAMES)
            except OSError:
                break
            if not chunk2:
                break
            self._buffer.append(chunk2)
            self._bytes_read += len(chunk2)

        return 'playing'

    # ── INTERNAL ──────────────────────────────────────────────────────────────

    def _parse_wav_header(self):
        if not self._file:
            raise RuntimeError('SDSource: no file open for WAV header parsing')
        f = self._file
        f.seek(22)
        self._channels = struct.unpack('<H', f.read(2))[0]
        f.seek(28)
        self._byte_rate = struct.unpack('<I', f.read(4))[0]
        f.seek(34)
        self._bits      = struct.unpack('<H', f.read(2))[0]
        self._frame_size = (self._channels * self._bits) // 8

        # Find 'data' chunk
        f.seek(12)
        while True:
            chunk_id  = f.read(4)
            if not chunk_id:
                break
            chunk_len = struct.unpack('<I', f.read(4))[0]
            if chunk_id == b'data':
                self._data_size = chunk_len
                self._data_start = f.tell()
                break
            f.seek(chunk_len, 1)

    def _parse_chunk(self, chunk):
        l_max = r_max = 0
        fs = self._frame_size

        if self._bits == 16:
            for i in range(0, len(chunk) - fs + 1, fs):
                if self._channels == 2:
                    l, r = struct.unpack('<hh', chunk[i:i + 4])
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

    def _analyze_chunk_for_dc_and_peak(self, chunk):
        """Measure DC offset and peak amplitude from first chunk for normalization."""
        if self._bits != 16 or self._channels != 2:
            return
        
        sum_l = sum_r = 0
        peak_l = peak_r = 0.0
        count = 0
        fs = self._frame_size
        
        for i in range(0, min(len(chunk), 512), fs):
            l, r = struct.unpack('<hh', chunk[i:i + 4])
            sum_l += l
            sum_r += r
            peak_l = max(peak_l, abs(l))
            peak_r = max(peak_r, abs(r))
            count += 1
        
        if count > 0:
            dc_l = sum_l / count / 32768.0
            dc_r = sum_r / count / 32768.0
            self._dc_offset = (dc_l + dc_r) / 2.0
            self._peak_level = max(peak_l, peak_r) / 32768.0
            print('[sd] DC offset: {:.3f}, peak: {:.3f}'.format(self._dc_offset, self._peak_level))
    
    def _apply_fade(self, level):
        """Apply fade-in (ramps from 0 to 1 over ~50ms)."""
        if self._fade_counter < 0:
            return level  # No fade
        elif self._fade_counter < self._fade_in_samples:
            fade = self._fade_counter / self._fade_in_samples
            self._fade_counter += CHUNK_FRAMES
            return level * fade
        else:
            self._fade_counter = -1  # Fade complete
            return level
