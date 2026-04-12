# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Microphone Source  (high-contrast engine)
# ──────────────────────────────────────────────────────────────────────────────
# Per-sample tight loop inside step() for low latency.
# Dual-envelope stereo texture from a mono mic:
#   Motor L — fast envelope: transients, attacks, rhythm
#   Motor R — slow envelope: sustained energy, ambient texture
#
# DSP chain per sample:
#   ADC read → adaptive bias → gain + feedback cancellation
#   → dual envelopes → hysteresis gate → exponential fade
#   → power law → motor floor → PWM out
#
# Tune via profiles.py feel dict. Key parameters and tuning directions:
#   sensitivity     — raise if too quiet, lower if triggers on background
#   open_threshold  — lower = more sensitive gate
#   release_coeff   — 0.80 = snappy 10ms, 0.90 = 20ms, 0.95 = 40ms
#   power_law_l/r   — higher = more silence/punch contrast
#   motor_floor     — raise if motors don't spin at low levels
# ──────────────────────────────────────────────────────────────────────────────

import machine
import utime
import random


class MicSource:

    STEP_MS   = 25    # How long step() runs the tight loop (ms)
    SAMPLE_US = 100   # Microseconds between samples (~10 kHz)
    CALIB_N   = 500   # Samples used for initial bias calibration

    def __init__(self, profile):
        hw   = profile['hardware']
        feel = profile['feel']

        self.adc = machine.ADC(hw['mic']['adc'])

        # Initialise motors directly — bypasses HapticOutput for tight-loop speed
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

        # DSP parameters — all sourced from feel profile
        self.sensitivity  = feel['sensitivity']
        self.bias_coeff   = feel['auto_bias_coeff']
        self.fb_damp      = feel['feedback_damp']
        self.open_thr     = feel['open_threshold']
        self.close_thr    = feel['close_threshold']
        self.hold_samples = int(feel['hold_time_ms'] * 1000 / self.SAMPLE_US)
        self.rel_coeff    = feel['release_coeff']
        self.pw_l         = feel['power_law_l']
        self.pw_r         = feel['power_law_r']
        self.floor        = feel['motor_floor']        # raw duty 0–65535

        # DSP state
        self.bias       = 32768.0
        self.env_l      = 0.0   # Fast envelope → Motor L (transients)
        self.env_r      = 0.0   # Slow envelope → Motor R (sustained)
        self.gate_open  = False
        self.fade       = 0.0
        self.hold_ctr   = 0
        self.prev_pwr_l = 0.0
        self.last_pwr   = 0.0

    # ── LIFECYCLE ─────────────────────────────────────────────────────────────

    def start(self):
        self.silence()
        print('[mic] Calibrating...')
        total = 0
        for _ in range(self.CALIB_N):
            total += self.adc.read_u16()
            utime.sleep_us(100)
        self.bias = total / self.CALIB_N
        print('[mic] Ready — bias: {:.0f}'.format(self.bias))

    def stop(self):
        self.silence()

    def silence(self):
        for m in self.motors:
            m.duty_u16(0)
        for led in self.leds:
            led.duty_u16(0)

    # ── STEP — called every main loop tick ────────────────────────────────────

    def step(self):
        """
        Runs a tight per-sample loop for STEP_MS milliseconds.
        Processes and outputs every sample individually for low latency.
        """
        deadline = utime.ticks_add(utime.ticks_ms(), self.STEP_MS)
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            val = self.adc.read_u16()
            pwr_l, pwr_r = self._process(val)
            self._drive(pwr_l, pwr_r)
            utime.sleep_us(self.SAMPLE_US)

    # ── DSP ───────────────────────────────────────────────────────────────────

    def _process(self, val):
        # 1. Adaptive bias — low-pass tracks DC centre, ignores AC signal
        self.bias += (val - self.bias) * self.bias_coeff

        # 2. Rectified sample with feedback cancellation
        #    (subtracts a fraction of last output to reduce motor→mic coupling)
        raw    = abs(val - self.bias) / 32768.0
        anti   = self.fb_damp * (self.last_pwr ** 0.8) if self.last_pwr > 0 else 0.0
        sample = max(0.0, raw * self.sensitivity - anti)

        # 3. Dual envelopes — same signal, different time constants
        #
        # Fast (Motor L): snaps to loud transients, drops quickly in silence.
        # Slow (Motor R): builds gradually, sustains long after the sound fades.
        if sample > self.env_l:
            self.env_l = 0.50 * self.env_l + 0.50 * sample   # fast attack
        else:
            self.env_l = 0.12 * self.env_l + 0.88 * sample   # fast release

        if sample > self.env_r:
            self.env_r = 0.95 * self.env_r + 0.05 * sample   # slow attack
        else:
            self.env_r = 0.98 * self.env_r + 0.02 * sample   # slow release

        # 4. Hysteresis gate — driven by the fast envelope
        #    Open threshold > close threshold prevents rapid chatter.
        if self.env_l > self.open_thr:
            self.gate_open = True
            self.hold_ctr  = self.hold_samples
            self.fade      = 1.0
        elif self.env_l < self.close_thr:
            if self.hold_ctr > 0:
                # Hold: don't release immediately after a dip (e.g. syllable gaps)
                self.hold_ctr -= 1
            else:
                # Exponential braking — multiplied per sample, so it curves naturally
                self.fade *= self.rel_coeff
                if self.fade < 0.01:
                    self.fade      = 0.0
                    self.gate_open = False

        # 5. Output power via power law for high contrast
        #    Low signals get heavily suppressed; peaks hit hard.
        if self.gate_open:
            pwr_l = min(1.0, (self.env_l * self.fade) ** self.pw_l)
            pwr_r = min(1.0, (self.env_r * self.fade) ** self.pw_r)

            # Transient kick on first trigger — overcomes ERM stiction at startup
            if self.prev_pwr_l == 0.0 and pwr_l > 0.0:
                pwr_l = min(1.0, pwr_l * 1.5)

            self.prev_pwr_l = pwr_l
        else:
            pwr_l = pwr_r   = 0.0
            self.prev_pwr_l = 0.0

        self.last_pwr = max(pwr_l, pwr_r)
        return pwr_l, pwr_r

    # ── OUTPUT ────────────────────────────────────────────────────────────────

    def _drive(self, pwr_l, pwr_r):
        PWM_MAX = 65535
        floor   = self.floor

        if pwr_l > 0.002 or pwr_r > 0.002:
            shimmer = random.getrandbits(5) - 16   # ±16 counts of texture

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
