import machine
import time
import sys
import select
import random

# Hardware Config
MIC_PIN = machine.ADC(machine.Pin(26))
MOTOR_L_PIN = 15
MOTOR_R_PIN = 16
LED_L = machine.Pin(14, machine.Pin.OUT)
LED_R = machine.Pin(17, machine.Pin.OUT)

vibe_L = machine.PWM(machine.Pin(MOTOR_L_PIN))
vibe_R = machine.PWM(machine.Pin(MOTOR_R_PIN))
vibe_L.freq(200); vibe_R.freq(200)

class HapticMicEngine:
    def __init__(self):
        """
        Creative Technologist Refactor: 
        High-Contrast engine with Exponential Braking and Adaptive Noise Floor.
        """
        self.envelope = 0.0
        self.bias = 32768
        self.calibrated = False
        self.gate_open = False
        self.fade_mult = 0.0
        self.prev_pwr = 0.0
        self.hold_counter = 0
        self.sensitivity = 1.8  # Increased to ensure Pico ADC signal is strong enough
        
        # --- SOUND ENGINEER PARAMETERS ---
        self.auto_bias_coeff = 0.005  # Faster adaptation to room noise
        self.feedback_damp = 0.10     # Lowered slightly to prevent self-cancelling
        self.last_pwr = 0.0
        
        self.set_profile("guitar")

    def set_profile(self, mode):
        """Maps UI modes to High-Fidelity DSP architectures."""
        self.mode = mode
        profiles = {
            # Guitar: Ultra-fast braking, high power law for 'snap'
            "guitar": {"open": 0.035, "close": 0.015, "rel": 0.65, "law": 5.0, "hold": 2},
            # Hush: Deep exponential suppression of background noise
            "hush":   {"open": 0.010, "close": 0.005, "rel": 0.40, "law": 10.0, "hold": 1},
            # Zoom: More natural, longer release for environmental textures
            "zoom":   {"open": 0.060, "close": 0.030, "rel": 0.85, "law": 3.0, "hold": 5}
        }
        p = profiles.get(mode, profiles["guitar"])
        self.open_threshold = p["open"]
        self.close_threshold = p["close"]
        self.release_coeff = p["rel"] # How fast it 'brakes'
        self.power_law = p["law"]
        self.hold_time = p["hold"]

    def calibrate(self):
        vibe_L.duty_u16(0); vibe_R.duty_u16(0)
        total = 0
        for _ in range(500):
            total += MIC_PIN.read_u16()
            time.sleep_us(50)
        self.bias = total // 500
        self.calibrated = True

    def process(self, val):
        if not self.calibrated: return 0.0

        # 1. Faster Adaptive Bias (Dynamic Zeroing)
        self.bias += (val - self.bias) * self.auto_bias_coeff
        
        # 2. Advanced Feedback Cancellation
        raw = abs(val - self.bias) / 32768.0
        # Use a soft-knee subtraction to avoid killing the signal
        anti_feedback = self.feedback_damp * (self.last_pwr ** 0.8) 
        sample = max(0.0, (raw * self.sensitivity) - anti_feedback)

        # 3. Dual-Rate Envelope (Instant Attack, Steep Decay)
        if sample > self.envelope:
            self.envelope = 0.50 * self.envelope + 0.50 * sample # Even faster attack
        else:
            self.envelope = 0.20 * self.envelope + 0.80 * sample

        # 4. Hysteresis Gating with Exponential Braking
        if self.envelope > self.open_threshold:
            if not self.gate_open:
                print("⚡ MIC TRIGGERED") # Console feedback for activation
            self.gate_open = True
            self.hold_counter = self.hold_time
            self.fade_mult = 1.0
        elif self.envelope < self.close_threshold:
            if self.hold_counter > 0:
                self.hold_counter -= 1
            else:
                # EXPONENTIAL BRAKING
                self.fade_mult *= self.release_coeff 
                if self.fade_mult < 0.05:
                    self.fade_mult = 0.0
                    self.gate_open = False

        # 5. The "Tactile Edge" (Transient Boosting)
        pwr = 0.0
        if self.gate_open:
            pwr = (self.envelope * self.fade_mult) ** self.power_law
            
            # Transient Kick: Only on initial breach to overcome motor stiction
            if self.prev_pwr == 0:
                pwr = min(1.0, pwr * 1.5)

        self.prev_pwr = pwr if self.gate_open else 0.0
        # Critical: last_pwr must be updated to feed the feedback loop
        self.last_pwr = pwr
        return pwr

def stream_haptics(profile="guitar", server_sock=None, ui_ref=None):
    engine = HapticMicEngine()
    engine.calibrate()
    engine.set_profile(profile)

    print(f"🚀 Sound-Engine Active [{profile.upper()}]")
    
    last_net_check = 0
    MOTOR_FLOOR = 12000 # Slightly higher floor for better responsiveness
    
    try:
        while True:
            val = MIC_PIN.read_u16()
            pwr = engine.process(val)
            
            if pwr > 0.002: 
                shimmer = (random.getrandbits(6) - 32)
                duty = int(MOTOR_FLOOR + (pwr * (65535 - MOTOR_FLOOR)) + shimmer)
                duty = max(0, min(65535, duty))
                
                vibe_L.duty_u16(duty); vibe_R.duty_u16(duty)
                LED_L.value(1); LED_R.value(1)
            else:
                vibe_L.duty_u16(0); vibe_R.duty_u16(0)
                LED_L.value(0); LED_R.value(0)
            
            # --- INTERRUPT CHECK ---
            now = time.ticks_ms()
            if server_sock is not None and ui_ref is not None and time.ticks_diff(now, last_net_check) > 60:
                last_net_check = now
                try:
                    # Non-blocking check for web commands
                    server_sock.settimeout(0)
                    conn, addr = server_sock.accept()
                    request = conn.recv(1024).decode()
                    # Acknowledge the potential for None in handle_request
                    new_mode, response = ui_ref.handle_request(request, "0.0.0.0")
                    conn.send(response); conn.close()
                    if new_mode != profile and new_mode != "idle":
                        return new_mode
                except OSError: pass

            readable = select.select([sys.stdin], [], [], 0)
            if readable and readable[0]:
                if sys.stdin.read(1).lower() == 'm': break
            
            time.sleep_us(120) 

    finally:
        vibe_L.duty_u16(0); vibe_R.duty_u16(0)
        LED_L.value(0); LED_R.value(0)