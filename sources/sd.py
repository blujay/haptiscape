# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — SD Card Source
# ──────────────────────────────────────────────────────────────────────────────
# Reads WAV files from the SD card and drives haptic output from the envelope.
#
# Supports 16-bit stereo and mono WAV at any sample rate the SD card
# can serve reliably (44.1kHz stereo is the tested ceiling).
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

    # ── TRACK LOADING ─────────────────────────────────────────────────────────

    def load_track(self, index):
        """Load a WAV file by index (sorted alphabetically from /sd)."""
        self.stop()
        try:
            tracks = sorted([f for f in uos.listdir('/sd') if f.lower().endswith('.wav')])
            if not tracks or index >= len(tracks):
                print('[sd] No track at index', index)
                return False

            path = '/sd/' + tracks[index]
            self._file = open(path, 'rb')
            self._parse_wav_header()
            self._bytes_read = 0
            self._start_ms   = time.ticks_ms()
            self._active     = True
            print('[sd] Playing:', path)
            return True

        except Exception as e:
            print('[sd] Load error:', e)
            self.stop()
            return False

    # ── STEP — called every loop tick by mode_manager ─────────────────────────

    def step(self):
        """
        Read one chunk of WAV data and update haptic output.
        Returns 'playing', 'done', or 'idle'.
        """
        if not self._active or not self._file:
            return 'idle'

        # Timing gate — don't read faster than the audio plays
        elapsed_ms     = time.ticks_diff(time.ticks_ms(), self._start_ms)
        expected_bytes = int((elapsed_ms / 1000) * self._byte_rate)
        if self._bytes_read > expected_bytes + (self._byte_rate // 4):
            return 'playing'

        try:
            chunk = self._file.read(self._frame_size * CHUNK_FRAMES)
        except OSError as e:
            print('[sd] Read error ({}) — stopping'.format(e.args[0] if e.args else e))
            self.stop()
            return 'done'

        if not chunk or self._bytes_read >= self._data_size:
            self.stop()
            return 'done'

        self._bytes_read += len(chunk)

        l_max, r_max = self._parse_chunk(chunk)

        level_l = self.envelope_l.process(l_max / 32768.0)
        level_r = self.envelope_r.process(r_max / 32768.0)

        # Derive pan from relative channel levels
        total = level_l + level_r
        pan   = (level_r / total) if total > 0 else 0.5
        pan   = self.pan.process(pan)

        level = max(level_l, level_r)
        self.output.set(level, pan)

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
