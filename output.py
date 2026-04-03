# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Haptic + LED Output
# ──────────────────────────────────────────────────────────────────────────────
# The single output contract for the whole system.
# Every source calls output.set(level, pan) — this file handles everything else.
#
# WHAT THIS DOES
# ──────────────────────────────────────────────────────────────────────────────
#   - Owns the motor and LED hardware objects
#   - Applies constant-power pan law → left/right motor levels
#   - Applies gamma correction → LED brightness feels natural
#   - Adds shimmer (tiny random variation) to keep ERMs from flatlining
#   - Silences everything cleanly when level is below the silence floor
#
# USAGE
# ──────────────────────────────────────────────────────────────────────────────
#   from output import HapticOutput
#   out = HapticOutput(profile)   # pass the full profile dict
#   out.set(level, pan)           # level and pan are 0.0–1.0
#   out.silence()                 # call on shutdown or mode change
# ──────────────────────────────────────────────────────────────────────────────

import machine
import math
import random

from config import PWM_MAX, LED_PWM_FREQ


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

SILENCE_FLOOR   = 0.012   # Below this level, everything cuts to zero
LED_MIN_LEVEL   = 0.04    # Minimum LED glow when signal is above silence floor
SHIMMER_RANGE   = 16      # ± random duty variation to prevent ERM flatline buzz


# ──────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────────────────────────────────────

class HapticOutput:
    """
    Initialises motors and LEDs from a hardware profile and exposes a single
    set(level, pan) method that every source uses to drive output.
    """

    def __init__(self, profile):
        hw           = profile['hardware']
        feel         = profile['feel']
        self.gamma   = feel['led_gamma']
        self.pwm_max = PWM_MAX

        # Motors
        motor_freq    = hw['motor_pwm_freq']
        self.motors   = []
        for pin in hw['motors']:
            m = machine.PWM(machine.Pin(pin))
            m.freq(motor_freq)
            m.duty_u16(0)
            self.motors.append(m)

        # LEDs — PWM for smooth brightness control
        self.leds = []
        for pin in hw.get('leds', []):
            led = machine.PWM(machine.Pin(pin))
            led.freq(LED_PWM_FREQ)
            led.duty_u16(0)
            self.leds.append(led)

        # Determine stereo layout
        # Two motors → left/right pan. One motor or four → treat differently.
        self.stereo = len(self.motors) == 2

    # ── MAIN OUTPUT CALL ──────────────────────────────────────────────────────

    def set(self, level, pan=0.5):
        """
        Drive motors and LEDs from a normalised level and pan position.

        level  — 0.0 (silent) to 1.0 (full intensity)
        pan    — 0.0 (full left) to 0.5 (centre) to 1.0 (full right)
        """
        if level < SILENCE_FLOOR:
            self.silence()
            return

        if self.stereo:
            gain_l, gain_r = self._pan_gains(pan)
        else:
            gain_l = gain_r = 1.0

        shimmer = (random.getrandbits(5) - 16)   # ± small variation

        self._write_motors(level, gain_l, gain_r, shimmer)
        self._write_leds(level, gain_l, gain_r)

    # ── SILENCE ───────────────────────────────────────────────────────────────

    def silence(self):
        """Cut all output immediately. Call on shutdown or mode change."""
        for m in self.motors:
            m.duty_u16(0)
        for led in self.leds:
            led.duty_u16(0)

    # ── INTERNAL ──────────────────────────────────────────────────────────────

    def _pan_gains(self, pan):
        """Constant-power pan law → (gain_left, gain_right)."""
        angle   = pan * (math.pi / 2)
        return math.cos(angle), math.sin(angle)

    def _write_motors(self, level, gain_l, gain_r, shimmer):
        gains = [gain_l, gain_r] if self.stereo else [1.0] * len(self.motors)
        for i, motor in enumerate(self.motors):
            duty = int(level * gains[i] * self.pwm_max) + shimmer
            motor.duty_u16(max(0, min(self.pwm_max, duty)))

    def _write_leds(self, level, gain_l, gain_r):
        if not self.leds:
            return
        gains = [gain_l, gain_r] if self.stereo else [1.0] * len(self.leds)
        for i, led in enumerate(self.leds):
            raw     = max(LED_MIN_LEVEL, level * gains[i % len(gains)])
            gamma   = raw ** self.gamma
            duty    = int(gamma * self.pwm_max)
            led.duty_u16(max(0, min(self.pwm_max, duty)))
