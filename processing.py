# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Signal Processing
# ──────────────────────────────────────────────────────────────────────────────
# Pure signal processing — no hardware, no pins, no PWM.
# All functions and classes work with normalised values (0.0–1.0).
#
# This file can be tested on a laptop. Nothing here touches the Pico hardware.
#
# WHAT THIS DOES
# ──────────────────────────────────────────────────────────────────────────────
# Takes raw audio samples from any source and shapes them into expressive
# haptic levels. The pipeline per frame:
#
#   1. RMS          — how loud is this moment? (bow pressure, voice volume)
#   2. Noise floor  — what counts as silence in this room right now?
#   3. Dynamic map  — lift quiet sounds up, tame loud ones, gate silence out
#   4. Envelope     — fast to respond, slow to let go (feel, not accuracy)
#   5. ZCR          — spectral tilt proxy → left/right pan
#   6. Pan follow   — smooth the pan so it drifts rather than jumps
#
# Each class takes a 'feel' dict from profiles.py so behaviour is tunable
# without touching this file.
# ──────────────────────────────────────────────────────────────────────────────

import math


# ──────────────────────────────────────────────────────────────────────────────
# RMS — loudness per frame
# ──────────────────────────────────────────────────────────────────────────────

def compute_rms(samples, midpoint, adc_max):
    """
    Root mean square amplitude of one audio frame.
    Returns 0.0–1.0, where 1.0 is the loudest possible signal.

    midpoint  — centre of the ADC range (32768 for 16-bit)
    adc_max   — max amplitude after centring (32767 for 16-bit)
    """
    acc = 0
    for s in samples:
        c = s - midpoint
        acc += c * c
    return min(math.sqrt(acc / len(samples)) / adc_max, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# ZCR — spectral tilt proxy for stereo pan
# ──────────────────────────────────────────────────────────────────────────────

def compute_zcr(samples, midpoint, zcr_max):
    """
    Zero-crossing rate — a lightweight way to sense whether the sound is
    tonally low (slow crossings → left motor) or high (fast crossings → right).
    No FFT needed. Returns 0.0 (low/left) → 1.0 (high/right).

    zcr_max — expected ceiling of crossings per frame (from feel profile)
    """
    crossings = 0
    for i in range(1, len(samples)):
        prev = samples[i - 1] - midpoint
        curr = samples[i]     - midpoint
        if (prev >= 0) != (curr >= 0):
            crossings += 1
    return min(crossings / zcr_max, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# NOISE FLOOR TRACKER — adaptive silence reference
# ──────────────────────────────────────────────────────────────────────────────

class NoiseFloorTracker:
    """
    Watches quiet frames and continuously recalibrates what silence means
    in the current room. Recalibrates roughly every 2 seconds.

    In a quiet studio, a whisper is the loudest thing and gets full treatment.
    In a loud venue, the floor rises to reject background noise automatically.
    """

    FLOOR_MIN = 0.004   # Prevents the gate collapsing to zero in dead silence
    FLOOR_MAX = 0.15    # Prevents the gate rising so high nothing gets through
    UPDATE_FRAMES = 256 # Frames between recalibrations (~2s at 8kHz/64 samples)

    def __init__(self, initial_floor, feel):
        self.floor         = max(initial_floor, self.FLOOR_MIN)
        self.sensitivity   = feel['noise_gate']
        self.quiet_acc     = 0.0
        self.quiet_count   = 0
        self.frame_counter = 0

    def update(self, raw_rms):
        """Call every frame. Returns the current noise floor estimate."""
        self.frame_counter += 1
        gate = self.floor * self.sensitivity

        if raw_rms < gate:
            self.quiet_acc   += raw_rms
            self.quiet_count += 1

        if self.frame_counter >= self.UPDATE_FRAMES:
            if self.quiet_count > 0:
                measured   = self.quiet_acc / self.quiet_count
                self.floor = 0.85 * self.floor + 0.15 * measured
                self.floor = max(self.FLOOR_MIN, min(self.FLOOR_MAX, self.floor))
            self.frame_counter = 0
            self.quiet_acc     = 0.0
            self.quiet_count   = 0

        return self.floor


# ──────────────────────────────────────────────────────────────────────────────
# DYNAMIC MAP — gate, expand, compress
# ──────────────────────────────────────────────────────────────────────────────

def dynamic_map(raw_rms, noise_floor, feel):
    """
    Maps raw RMS to a haptic level using three zones:

      Below gate     → silence, returns 0.0
      Quiet zone     → expanded upward so whispers feel like something
      Mid zone       → faithful, 1:1 dynamics
      Loud zone      → soft compression so peaks don't plateau into a buzz

    Returns 0.0–1.0.
    """
    gate = noise_floor * feel['noise_gate']

    if raw_rms <= gate:
        return 0.0

    norm = min((raw_rms - gate) / (1.0 - gate), 1.0)

    expand_knee   = feel['expand_knee']
    compress_knee = feel['compress_knee']
    compress_ratio = feel['compress_ratio']

    if norm < expand_knee:
        # Quiet zone — lift it into a feelable range
        ratio  = norm / expand_knee
        mapped = (ratio ** 0.5) * expand_knee
    elif norm < compress_knee:
        # Mid zone — honest dynamics
        mapped = norm
    else:
        # Loud zone — tame the peaks
        excess = norm - compress_knee
        mapped = compress_knee + excess * compress_ratio

    return max(0.06, min(1.0, mapped))


# ──────────────────────────────────────────────────────────────────────────────
# ENVELOPE FOLLOWER — attack and release shaping
# ──────────────────────────────────────────────────────────────────────────────

class EnvelopeFollower:
    """
    Shapes how the haptic level responds over time.
    Fast attack catches transients (bow hits, consonants, plucks).
    Slow release sustains the sensation so legato phrases feel continuous.
    Transient hold prevents the release from firing immediately after a spike.
    """

    HOLD_FRAMES = 3   # Frames to hold before release begins after a transient

    def __init__(self, feel):
        self.attack    = feel['attack']
        self.release   = feel['release']
        self.t_boost   = feel['transient_boost']
        self.t_thresh  = feel['transient_threshold']
        self.level     = 0.0
        self.hold      = 0
        self.prev      = 0.0

    def process(self, target):
        delta     = target - self.prev
        self.prev = target

        if delta > 0 and target > self.t_thresh:
            boosted   = min(target * self.t_boost, 1.0)
            self.hold = self.HOLD_FRAMES
        else:
            boosted = target

        if boosted > self.level:
            self.level += self.attack * (boosted - self.level)
        elif self.hold > 0:
            self.hold -= 1
        else:
            self.level += self.release * (boosted - self.level)

        return self.level


# ──────────────────────────────────────────────────────────────────────────────
# PAN FOLLOWER — smooth stereo position
# ──────────────────────────────────────────────────────────────────────────────

class PanFollower:
    """
    Smooths the left/right pan position so it drifts rather than jumps.
    0.0 = full left body, 0.5 = centre, 1.0 = full right body.
    """

    def __init__(self, feel):
        self.smoothing = feel['pan_smoothing']
        self.pan       = 0.5

    def process(self, zcr_norm):
        self.pan += self.smoothing * (zcr_norm - self.pan)
        return self.pan
