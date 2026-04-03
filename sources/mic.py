# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Microphone Source
# ──────────────────────────────────────────────────────────────────────────────
# Reads live audio from the ADC microphone, processes it, and drives output.
#
# This file is intentionally thin — the interesting work happens in
# processing.py (signal shaping) and output.py (motor + LED driving).
# ──────────────────────────────────────────────────────────────────────────────

import machine
import utime

from config import SAMPLE_RATE_HZ, BUFFER_SIZE, ADC_MIDPOINT, ADC_MAX
from processing import (
    compute_rms, compute_zcr,
    NoiseFloorTracker, dynamic_map,
    EnvelopeFollower, PanFollower,
)
from output import HapticOutput


class MicSource:
    """
    Live microphone input source.
    Collects audio frames from the ADC and translates them into haptic output.
    """

    # Quiet baseline before the noise floor tracker takes over
    INITIAL_FLOOR = 0.01

    def __init__(self, profile):
        feel     = profile['feel']
        hw       = profile['hardware']

        self.adc      = machine.ADC(hw['mic']['adc'])
        self.output   = HapticOutput(profile)
        self.feel     = feel

        self.noise    = NoiseFloorTracker(self.INITIAL_FLOOR, feel)
        self.envelope = EnvelopeFollower(feel)
        self.pan      = PanFollower(feel)

        self._interval_us = int(1_000_000 / SAMPLE_RATE_HZ)

    # ── LIFECYCLE ─────────────────────────────────────────────────────────────

    def start(self):
        """Calibrate the noise floor before the main loop begins."""
        print('[mic] Calibrating noise floor — stay quiet for 1s...')
        n       = SAMPLE_RATE_HZ
        sq_sum  = 0
        for _ in range(n):
            v      = self.adc.read_u16()
            c      = v - ADC_MIDPOINT
            sq_sum += c * c
            utime.sleep_us(self._interval_us)
        import math
        rms = math.sqrt(sq_sum / n) / ADC_MAX
        self.noise = NoiseFloorTracker(max(rms, 0.004), self.feel)
        print('[mic] Ready. Noise floor: {:.4f}'.format(rms))

    def stop(self):
        self.output.silence()

    # ── STEP — called every loop tick by mode_manager ─────────────────────────

    def step(self):
        """Process one audio frame and update haptic output."""
        samples = self._collect_frame()

        raw_rms     = compute_rms(samples, ADC_MIDPOINT, ADC_MAX)
        floor       = self.noise.update(raw_rms)
        target      = dynamic_map(raw_rms, floor, self.feel)
        level       = self.envelope.process(target)
        zcr         = compute_zcr(samples, ADC_MIDPOINT, self.feel['zcr_max'])
        pan         = self.pan.process(zcr)

        self.output.set(level, pan)

    # ── INTERNAL ──────────────────────────────────────────────────────────────

    def _collect_frame(self):
        samples = []
        for _ in range(BUFFER_SIZE):
            samples.append(self.adc.read_u16())
            utime.sleep_us(self._interval_us)
        return samples
