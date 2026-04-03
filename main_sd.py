import machine
import struct
import time
import uos
import random

# Optimized constants for Pico PWM motors
PWM_FREQ = 200
MOTOR_FLOOR = 14000  # Minimum duty to actually feel vibration
MOTOR_MAX = 65535
GAIN_EXPONENT = 1.8   # Controls the "Whisper to Roar" curve (1.5-2.2 is ideal)

class HapticEngine:
    """
    Optimized Haptic Engine for the Pi Pico.
    Uses logarithmic scaling for high-contrast 'Whisper to Roar' dynamics.
    """
    def __init__(self):
        self.envelope = 0.0
        self.attack = 0.92
        self.release = 0.15
        
        # Noise gate thresholds
        self.gate_threshold = 0.015
        self.gate_active = False

    def process(self, block_max):
        # Smooth envelope tracking
        coeff = self.attack if block_max > self.envelope else self.release
        self.envelope = (coeff * self.envelope) + ((1 - coeff) * block_max)

        if self.envelope < self.gate_threshold:
            self.gate_active = False
            return 0
        
        self.gate_active = True
        
        # Exponential scaling for "Whisper to Roar"
        # Normalizes 0.0-1.0 to a curve, then maps to motor range
        scaled = pow(self.envelope, GAIN_EXPONENT)
        
        duty = int(MOTOR_FLOOR + (scaled * (MOTOR_MAX - MOTOR_FLOOR)))
        return max(0, min(MOTOR_MAX, duty))

class SDPlayerSession:
    """
    Lean, non-blocking SD track player designed to work with ModeManager.
    """
    def __init__(self):
        self.vibe_L = machine.PWM(machine.Pin(15))
        self.vibe_R = machine.PWM(machine.Pin(16))
        self.vibe_L.freq(PWM_FREQ)
        self.vibe_R.freq(PWM_FREQ)
        
        self.engine_L = HapticEngine()
        self.engine_R = HapticEngine()

        self.trackfile = None
        self.active = False
        self.data_size = 0
        self.bytes_read = 0
        self.byte_rate = 0
        self.num_channels = 2
        self.bits_per_sample = 16
        self.start_time = 0

    def load_track(self, track_idx):
        try:
            tracks = sorted([f for f in uos.listdir("/sd") if f.lower().endswith(".wav")])
            if not tracks or track_idx >= len(tracks): return False
            
            self.stop() # Clean up previous
            
            filename = "/sd/" + tracks[track_idx]
            self.trackfile = open(filename, 'rb')
            
            # Fast-parse WAV Header
            self.trackfile.seek(22)
            self.num_channels = struct.unpack('<H', self.trackfile.read(2))[0]
            self.trackfile.seek(24)
            sample_rate = struct.unpack('<I', self.trackfile.read(4))[0]
            self.trackfile.seek(28)
            self.byte_rate = struct.unpack('<I', self.trackfile.read(4))[0]
            self.trackfile.seek(34)
            self.bits_per_sample = struct.unpack('<H', self.trackfile.read(2))[0]
            
            # Find the 'data' chunk (handling potential metadata blocks)
            self.trackfile.seek(12)
            while True:
                chunk_id = self.trackfile.read(4)
                if not chunk_id: break
                chunk_len = struct.unpack('<I', self.trackfile.read(4))[0]
                if chunk_id == b'data':
                    self.data_size = chunk_len
                    break
                else:
                    self.trackfile.seek(chunk_len, 1) # Skip unknown chunks
            
            self.bytes_read = 0
            self.start_time = time.ticks_ms()
            self.active = True
            print(f"Playing: {filename} ({sample_rate}Hz, {self.num_channels}ch)")
            return True
        except Exception as e:
            print(f"SD Load Error: {e}")
            return False

    def stop(self):
        self.active = False
        if self.trackfile:
            try: self.trackfile.close()
            except: pass
            self.trackfile = None
        self.vibe_L.duty_u16(0)
        self.vibe_R.duty_u16(0)

    def step(self):
        if not self.active or not self.trackfile:
            return 'idle'

        # Timing sync: prevent the Pico from reading faster than the audio plays
        elapsed_ms = time.ticks_diff(time.ticks_ms(), self.start_time)
        expected_bytes = int((elapsed_ms / 1000) * self.byte_rate)
        
        # Buffer lead-ahead (about 250ms of data)
        if self.bytes_read > expected_bytes + (self.byte_rate // 4):
            return 'playing'

        # Block size proportional to format (e.g., 4 bytes for 16-bit Stereo)
        frame_size = (self.num_channels * self.bits_per_sample) // 8
        chunk = self.trackfile.read(frame_size * 64) 
        
        if not chunk or self.bytes_read >= self.data_size:
            self.stop()
            return 'done'

        self.bytes_read += len(chunk)

        l_max, r_max = 0, 0
        
        # Optimized parser for 16-bit Stereo/Mono
        if self.bits_per_sample == 16:
            for i in range(0, len(chunk), frame_size):
                if self.num_channels == 2:
                    l_val, r_val = struct.unpack('<hh', chunk[i:i+4])
                    l_max = max(l_max, abs(l_val))
                    r_max = max(r_max, abs(r_val))
                else:
                    val = struct.unpack('<h', chunk[i:i+2])[0]
                    l_max = r_max = max(l_max, abs(val))
        
        # 8-bit handling
        elif self.bits_per_sample == 8:
            for i in range(0, len(chunk), frame_size):
                # 8-bit WAV is unsigned (128 is center)
                if self.num_channels == 2:
                    l_val = abs(chunk[i] - 128) * 256
                    r_val = abs(chunk[i+1] - 128) * 256
                    l_max = max(l_max, l_val)
                    r_max = max(r_max, r_val)
                else:
                    val = abs(chunk[i] - 128) * 256
                    l_max = r_max = max(l_max, val)

        # Convert to 0.0-1.0 range
        duty_L = self.engine_L.process(l_max / 32768.0)
        duty_R = self.engine_R.process(r_max / 32768.0)

        # Apply motors
        shimmer = random.getrandbits(5) - 16
        self.vibe_L.duty_u16(max(0, min(MOTOR_MAX, duty_L + shimmer)) if duty_L > 0 else 0)
        self.vibe_R.duty_u16(max(0, min(MOTOR_MAX, duty_R + shimmer)) if duty_R > 0 else 0)

        return 'playing'