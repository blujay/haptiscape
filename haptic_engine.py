"""
================================================================================
  HAPTIC SENSE ENGINE — Pico W Real-Time Audio → ERM Haptic + LED PWM
  Generic audio input (voice, music, breath, percussion, strings, etc.)
  Wearable backtrack with 3D-printed ERM housing + sync'd LED response.

  Design principle: whisper should work. Silence should stop everything.
  The engine adapts its noise floor to the room so even quiet input drives
  full haptic + LED expression. Loud input never clips into a flat buzz.
================================================================================

WIRING
────────────────────────────────────────────────────────────────────────────────
  MIC (analog — e.g. MAX9814, KY-038, or electret + op-amp to 0–3.3V):
    MIC_ADC_PIN      → GPIO 26  (ADC0)
    Mic GND          → GND
    Mic VCC          → 3.3V

  ERM MOTOR LEFT (via NPN e.g. 2N2222, or DRV2605L — NOT direct GPIO):
    MOTOR_LEFT_PIN   → GPIO 15  → motor driver input
    Motor driver PWR → 5V external rail

  ERM MOTOR RIGHT:
    MOTOR_RIGHT_PIN  → GPIO 14  → motor driver input

  LED LEFT (direct from GPIO via 100Ω resistor, or MOSFET for strips):
    LED_LEFT_PIN     → GPIO 12
    LED cathode      → GND

  LED RIGHT:
    LED_RIGHT_PIN    → GPIO 13
    LED cathode      → GND

  OPTIONAL I2C (DRV2605L haptic driver):
    I2C_SDA_PIN      → GPIO 4
    I2C_SCL_PIN      → GPIO 5

LED BEHAVIOUR
────────────────────────────────────────────────────────────────────────────────
  LEDs are driven by PWM at LED_PWM_FREQ_HZ.
  Brightness tracks the processed haptic envelope in real time.
  Silence → both LEDs off. Whisper → faint glow. Shout → full brightness.
  Stereo: left LED mirrors left motor, right LED mirrors right motor.
  Pan of audio source (by spectral tilt / ZCR) moves brightness L↔R.

DYNAMICS DESIGN
────────────────────────────────────────────────────────────────────────────────
  KEY FEATURE — adaptive noise floor:
    The engine continuously measures ambient quiet (when below gate) and
    calibrates its zero point. So in a quiet room, a whisper is the loudest
    thing in the space and gets full treatment. In a loud room, the gate
    rises to reject background noise. Re-calibrates every ~2 seconds.

  Expression pipeline per frame:
    1. ADC frame → DC-coupled RMS
    2. Adaptive gate — reject room noise, recalibrate dynamically
    3. Upward expand below knee — whisper → full range mapping
    4. Soft-knee compress above knee — loud doesn't plateau
    5. Transient detect — sharp attack spikes for percussion/pluck/consonants
    6. Asymmetric envelope (fast attack, slow release) — smooth sustain
    7. Spectral tilt (ZCR) → L/R pan — tonal colour moves across back
    8. Constant-power pan law → motor duties + LED duties
    9. Hard silence gate: if envelope < silence floor → everything off

TUNING FOR DIFFERENT SOURCES
────────────────────────────────────────────────────────────────────────────────
  Voice / whisper:       NOISE_GATE_SENSITIVITY = 0.5  (more sensitive)
  Loud music / drums:    NOISE_GATE_SENSITIVITY = 2.0  (less sensitive)
  Cello / quiet strings: NOISE_GATE_SENSITIVITY = 0.8  (default)
  Release feel — legato: RELEASE_COEFF = 0.03 (slow, sustaining)
  Release feel — staccato/speech: RELEASE_COEFF = 0.15 (snappier)
================================================================================
"""

import machine
import utime
import math

# ──────────────────────────────────────────────────────────────────────────────
# PIN CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

MIC_ADC_PIN       = 26    # Analog mic input — GPIO 26 = ADC0
MOTOR_LEFT_PIN    = 15    # PWM → left ERM motor driver
MOTOR_RIGHT_PIN   = 14    # PWM → right ERM motor driver
LED_LEFT_PIN      = 12    # PWM → left LED (via resistor)
LED_RIGHT_PIN     = 13    # PWM → right LED (via resistor)

# Optional I2C for DRV2605L
I2C_SDA_PIN       = 4
I2C_SCL_PIN       = 5

# ──────────────────────────────────────────────────────────────────────────────
# AUDIO SAMPLING
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE_HZ    = 8000   # ADC sample rate (8kHz captures voice + most music)
BUFFER_SIZE       = 64     # Samples per frame — ~8ms processing window
ADC_MIDPOINT      = 32768  # Centre of 0–65535 ADC range
ADC_MAX           = 32767  # Max possible amplitude after centering

# ──────────────────────────────────────────────────────────────────────────────
# PWM CARRIER FREQUENCIES
# ──────────────────────────────────────────────────────────────────────────────

MOTOR_PWM_FREQ_HZ = 200    # ERM carrier — 150–250 Hz is the sweet spot
LED_PWM_FREQ_HZ   = 1000   # LED PWM — high enough to be flicker-free
PWM_MAX_DUTY      = 65535  # 16-bit duty cycle max

# ──────────────────────────────────────────────────────────────────────────────
# ADAPTIVE NOISE FLOOR
# ──────────────────────────────────────────────────────────────────────────────

# How many frames of silence before we update the noise floor estimate
# At 8ms/frame: 256 frames ≈ 2 seconds
NOISE_FLOOR_UPDATE_FRAMES  = 256

# Multiplier above measured noise floor to set the gate threshold.
# Lower = more sensitive (whisper triggers haptics).
# Higher = more rejection of ambient noise.
# 0.5 → whisper-sensitive   |   2.0 → loud-room robust
NOISE_GATE_SENSITIVITY     = 0.8

# Absolute minimum noise floor — prevents gate collapsing to 0 in dead silence
# (which would make the slightest click trigger full output)
NOISE_FLOOR_MIN            = 0.004   # ~0.4% of ADC range

# Maximum noise floor — in very loud environments, cap so gate doesn't
# rise so high that normal audio can't get through
NOISE_FLOOR_MAX            = 0.15    # 15% of ADC range

# ──────────────────────────────────────────────────────────────────────────────
# DYNAMIC RANGE / COMPRESSION
# ──────────────────────────────────────────────────────────────────────────────

# Below this normalised level (relative to gate), expand upward aggressively
# so quiet audio gets mapped to a useful haptic range
EXPAND_KNEE            = 0.20    # Bottom 20% of post-gate range gets expanded

# Soft compression above this level — loud audio compressed, not clipped
COMPRESS_KNEE          = 0.70    # Top 30% above this gets compressed

# Compression ratio above the knee (0.4 = heavy, 0.7 = gentle)
COMPRESSION_RATIO      = 0.45

# Upward expansion ratio below the expand knee (>1 = expand quiet signals up)
EXPANSION_RATIO        = 2.2

# Minimum haptic level when signal is above gate (keeps ERM just alive)
MIN_HAPTIC_LEVEL       = 0.06

# Hard silence floor — below this post-envelope level, cut everything
SILENCE_FLOOR          = 0.012

# ──────────────────────────────────────────────────────────────────────────────
# ENVELOPE SHAPING
# ──────────────────────────────────────────────────────────────────────────────

# Fast attack — catches transients (percussive hits, consonants, bow attacks)
ATTACK_COEFF           = 0.45

# Slow release — sustains resonance, avoids chopping during gaps in audio
RELEASE_COEFF          = 0.055

# Transient boost: RMS spike above TRANSIENT_THRESHOLD triggers a punch
TRANSIENT_BOOST        = 1.55
TRANSIENT_THRESHOLD    = 0.55    # Normalised, relative to post-gate signal

# Hold time after transient before release begins (in frames)
TRANSIENT_HOLD_FRAMES  = 3

# ──────────────────────────────────────────────────────────────────────────────
# STEREO PAN (spectral tilt L/R)
# ──────────────────────────────────────────────────────────────────────────────

# Smoothing coefficient for pan position (prevents jitter)
PAN_SMOOTHING          = 0.12

# ZCR (zero-crossing rate) normalisation ceiling
# At 8kHz / 64 samples: speech/music spans ~2 to ~30 crossings per frame
ZCR_MAX_CROSSINGS      = 20.0

# ──────────────────────────────────────────────────────────────────────────────
# LED RESPONSE
# ──────────────────────────────────────────────────────────────────────────────

# LED gamma correction — human eye perceives LEDs logarithmically
# 2.2 = standard gamma, 1.0 = linear
LED_GAMMA              = 2.2

# LED minimum brightness when signal is above silence floor (avoids harsh on/off)
LED_MIN_LEVEL          = 0.04


# ──────────────────────────────────────────────────────────────────────────────
# HARDWARE INITIALISATION
# ──────────────────────────────────────────────────────────────────────────────

def init_hardware():
    """Initialise ADC mic, PWM motor outputs, and PWM LED outputs."""

    adc = machine.ADC(MIC_ADC_PIN)

    motor_l = machine.PWM(machine.Pin(MOTOR_LEFT_PIN))
    motor_l.freq(MOTOR_PWM_FREQ_HZ)
    motor_l.duty_u16(0)

    motor_r = machine.PWM(machine.Pin(MOTOR_RIGHT_PIN))
    motor_r.freq(MOTOR_PWM_FREQ_HZ)
    motor_r.duty_u16(0)

    # LEDs driven by PWM for smooth brightness control
    led_l = machine.PWM(machine.Pin(LED_LEFT_PIN))
    led_l.freq(LED_PWM_FREQ_HZ)
    led_l.duty_u16(0)

    led_r = machine.PWM(machine.Pin(LED_RIGHT_PIN))
    led_r.freq(LED_PWM_FREQ_HZ)
    led_r.duty_u16(0)

    return adc, motor_l, motor_r, led_l, led_r


# ──────────────────────────────────────────────────────────────────────────────
# STARTUP DIAGNOSTICS
# ──────────────────────────────────────────────────────────────────────────────

def run_diagnostics(adc, motor_l, motor_r, led_l, led_r):
    """
    On boot:
      1. LED sweep — confirms LED PWM wiring (both fade up/down)
      2. Mic baseline — reads ambient noise floor, prints ADC range
      3. Motor test — left then right ramp, with LED mirroring
      4. Both motors + both LEDs — full power pulse
      5. Ready flash
    """
    print("")
    print("=" * 54)
    print("  HAPTIC SENSE ENGINE — STARTUP DIAGNOSTICS")
    print("=" * 54)

    interval_us = int(1_000_000 / SAMPLE_RATE_HZ)

    # Step 1: LED sweep
    print("[DIAG] 1/5  LED sweep...")
    for i in range(0, PWM_MAX_DUTY + 1, PWM_MAX_DUTY // 100):
        led_l.duty_u16(i)
        led_r.duty_u16(i)
        utime.sleep_ms(8)
    for i in range(PWM_MAX_DUTY, -1, -(PWM_MAX_DUTY // 100)):
        led_l.duty_u16(i)
        led_r.duty_u16(i)
        utime.sleep_ms(8)
    led_l.duty_u16(0)
    led_r.duty_u16(0)
    print("[DIAG]      LED sweep OK")

    # Step 2: Mic baseline (stay quiet during this)
    print("[DIAG] 2/5  Mic baseline — stay quiet for 1.5s...")
    n = SAMPLE_RATE_HZ + SAMPLE_RATE_HZ // 2
    adc_sum = 0
    adc_min = 65535
    adc_max = 0
    sq_sum  = 0
    for _ in range(n):
        v = adc.read_u16()
        adc_sum += v
        if v < adc_min: adc_min = v
        if v > adc_max: adc_max = v
        c = v - ADC_MIDPOINT
        sq_sum += c * c
        utime.sleep_us(interval_us)
    mean = adc_sum // n
    rms  = math.sqrt(sq_sum / n) / ADC_MAX
    rng  = adc_max - adc_min
    print("[DIAG]      mean={}  rms={:.4f}  range={}".format(mean, rms, rng))
    if rng < 300:
        print("[DIAG]      *** WARNING: mic appears flat — check wiring ***")
    else:
        print("[DIAG]      Mic OK. Ambient RMS = {:.4f}".format(rms))

    # Step 3: Motor ramps (left then right), LEDs mirror
    for pin_m, pin_l, label in [(motor_l, led_l, "LEFT"), (motor_r, led_r, "RIGHT")]:
        print("[DIAG] 3-4/5 {} motor ramp...".format(label))
        for step in range(101):
            d = int((step / 100) * PWM_MAX_DUTY)
            pin_m.duty_u16(d)
            pin_l.duty_u16(d)
            utime.sleep_ms(10)
        utime.sleep_ms(300)
        for step in range(100, -1, -1):
            d = int((step / 100) * PWM_MAX_DUTY)
            pin_m.duty_u16(d)
            pin_l.duty_u16(d)
            utime.sleep_ms(10)
        pin_m.duty_u16(0)
        pin_l.duty_u16(0)

    # Step 4: Both motors + LEDs simultaneously
    print("[DIAG] 5/5  Both motors + LEDs — full pulse")
    motor_l.duty_u16(PWM_MAX_DUTY)
    motor_r.duty_u16(PWM_MAX_DUTY)
    led_l.duty_u16(PWM_MAX_DUTY)
    led_r.duty_u16(PWM_MAX_DUTY)
    utime.sleep_ms(400)
    motor_l.duty_u16(0)
    motor_r.duty_u16(0)
    led_l.duty_u16(0)
    led_r.duty_u16(0)

    # Step 5: Ready double flash on LEDs
    for _ in range(3):
        led_l.duty_u16(PWM_MAX_DUTY)
        led_r.duty_u16(PWM_MAX_DUTY)
        utime.sleep_ms(80)
        led_l.duty_u16(0)
        led_r.duty_u16(0)
        utime.sleep_ms(80)

    print("=" * 54)
    print("  DIAGNOSTICS COMPLETE — ENGINE STARTING")
    print("=" * 54)
    print("")

    # Return ambient RMS as the initial noise floor estimate
    return max(rms, NOISE_FLOOR_MIN)


# ──────────────────────────────────────────────────────────────────────────────
# DSP — AUDIO ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def compute_rms(samples):
    """RMS amplitude of one frame, normalised 0.0–1.0."""
    acc = 0
    for s in samples:
        c = s - ADC_MIDPOINT
        acc += c * c
    return min(math.sqrt(acc / len(samples)) / ADC_MAX, 1.0)


def compute_zcr(samples):
    """
    Zero-crossing rate as spectral tilt proxy.
    Returns normalised 0.0 (low/dark tonal) → 1.0 (high/bright/sibilant).
    Works for any audio: low singing → left, consonants/highs → right.
    """
    crossings = 0
    for i in range(1, len(samples)):
        prev = samples[i-1] - ADC_MIDPOINT
        curr = samples[i]   - ADC_MIDPOINT
        if (prev >= 0) != (curr >= 0):
            crossings += 1
    return min(crossings / ZCR_MAX_CROSSINGS, 1.0)


def dynamic_map(raw_rms, noise_floor):
    """
    Map raw RMS to haptic level using:
      - Adaptive gate (noise floor × sensitivity)
      - Upward expansion below expand knee (lifts whispers)
      - Linear mid zone (faithful expression)
      - Soft-knee compression above compress knee (tames loud peaks)

    Returns 0.0 if below gate, else 0.0–1.0 haptic level.
    """
    gate = noise_floor * NOISE_GATE_SENSITIVITY

    if raw_rms <= gate:
        return 0.0

    # Normalise to 0.0–1.0 relative to gate (gate = 0, full scale = 1.0)
    # Use a range of (1.0 - gate) so the entire ADC range above gate maps to 0–1
    norm = min((raw_rms - gate) / (1.0 - gate), 1.0)

    if norm < EXPAND_KNEE:
        # Upward expansion zone — whispers get lifted into useful haptic range
        ratio  = norm / EXPAND_KNEE
        mapped = ratio ** (1.0 / EXPANSION_RATIO) * EXPAND_KNEE
    elif norm < COMPRESS_KNEE:
        # Linear mid zone — faithful 1:1 dynamics
        mapped = norm
    else:
        # Soft compression above compress knee
        excess = norm - COMPRESS_KNEE
        mapped = COMPRESS_KNEE + excess * COMPRESSION_RATIO

    # Apply minimum haptic level (keeps ERM spinning once triggered)
    return max(MIN_HAPTIC_LEVEL, min(1.0, mapped))


# ──────────────────────────────────────────────────────────────────────────────
# ENVELOPE & PAN STATE
# ──────────────────────────────────────────────────────────────────────────────

class EnvelopeFollower:
    """
    Asymmetric attack/release envelope.
    Fast attack for transients, slow release for sustain.
    Transient hold prevents release from firing immediately after a spike.
    """
    def __init__(self):
        self.level      = 0.0
        self.hold_count = 0
        self.prev_input = 0.0

    def process(self, target):
        # Transient detection
        delta = target - self.prev_input
        self.prev_input = target

        if delta > 0 and target > TRANSIENT_THRESHOLD:
            boosted = min(target * TRANSIENT_BOOST, 1.0)
            self.hold_count = TRANSIENT_HOLD_FRAMES
        else:
            boosted = target

        if boosted > self.level:
            # Attack
            self.level += ATTACK_COEFF * (boosted - self.level)
        elif self.hold_count > 0:
            # Hold — don't decay yet
            self.hold_count -= 1
        else:
            # Release
            self.level += RELEASE_COEFF * (boosted - self.level)

        return self.level


class PanFollower:
    """Smoothed stereo pan. Prevents jarring L/R jumps."""
    def __init__(self):
        self.pan = 0.5   # Start centred

    def process(self, zcr_norm):
        self.pan += PAN_SMOOTHING * (zcr_norm - self.pan)
        return self.pan


# ──────────────────────────────────────────────────────────────────────────────
# OUTPUT CALCULATION
# ──────────────────────────────────────────────────────────────────────────────

def gamma_correct(level, gamma):
    """Apply gamma curve to linearise LED perceived brightness."""
    if level <= 0.0:
        return 0.0
    return level ** gamma


def compute_duties(env_level, pan):
    """
    Constant-power pan law → (motor_left, motor_right, led_left, led_right)
    all as 16-bit PWM duty values.

    If envelope is below silence floor, everything is zero.
    LEDs get gamma correction for perceptual linearity.
    """
    if env_level < SILENCE_FLOOR:
        return 0, 0, 0, 0

    angle      = pan * (math.pi / 2)
    gain_l     = math.cos(angle)
    gain_r     = math.sin(angle)

    motor_l = max(0, min(PWM_MAX_DUTY, int(env_level * gain_l * PWM_MAX_DUTY)))
    motor_r = max(0, min(PWM_MAX_DUTY, int(env_level * gain_r * PWM_MAX_DUTY)))

    # LEDs: apply gamma, add minimum level, pan mirrors motors
    led_raw_l   = max(LED_MIN_LEVEL, env_level * gain_l)
    led_raw_r   = max(LED_MIN_LEVEL, env_level * gain_r)
    led_l_duty  = int(gamma_correct(led_raw_l, LED_GAMMA) * PWM_MAX_DUTY)
    led_r_duty  = int(gamma_correct(led_raw_r, LED_GAMMA) * PWM_MAX_DUTY)
    led_l_duty  = max(0, min(PWM_MAX_DUTY, led_l_duty))
    led_r_duty  = max(0, min(PWM_MAX_DUTY, led_r_duty))

    return motor_l, motor_r, led_l_duty, led_r_duty


# ──────────────────────────────────────────────────────────────────────────────
# SAMPLE COLLECTION
# ──────────────────────────────────────────────────────────────────────────────

def collect_frame(adc, n_samples, sample_rate_hz):
    """Collect n_samples ADC readings at ~sample_rate_hz. Returns list of u16."""
    interval_us = int(1_000_000 / sample_rate_hz)
    samples = []
    for _ in range(n_samples):
        samples.append(adc.read_u16())
        utime.sleep_us(interval_us)
    return samples


# ──────────────────────────────────────────────────────────────────────────────
# ADAPTIVE NOISE FLOOR TRACKER
# ──────────────────────────────────────────────────────────────────────────────

class NoiseFloorTracker:
    """
    Tracks the ambient noise floor by watching quiet frames.
    When a frame is below the current gate, it contributes to the floor estimate.
    Updates every NOISE_FLOOR_UPDATE_FRAMES frames.
    """
    def __init__(self, initial_floor):
        self.floor          = max(initial_floor, NOISE_FLOOR_MIN)
        self.quiet_acc      = 0.0
        self.quiet_count    = 0
        self.frame_counter  = 0

    def update(self, raw_rms):
        """Call every frame with the raw RMS. Returns current noise floor."""
        self.frame_counter += 1
        gate = self.floor * NOISE_GATE_SENSITIVITY

        if raw_rms < gate:
            # This frame is 'quiet' — use it to track floor
            self.quiet_acc   += raw_rms
            self.quiet_count += 1

        if self.frame_counter >= NOISE_FLOOR_UPDATE_FRAMES:
            if self.quiet_count > 0:
                measured = self.quiet_acc / self.quiet_count
                # Slow-track toward measured floor (don't jump suddenly)
                self.floor = 0.85 * self.floor + 0.15 * measured
                self.floor = max(NOISE_FLOOR_MIN, min(NOISE_FLOOR_MAX, self.floor))
            # Reset accumulators
            self.frame_counter  = 0
            self.quiet_acc      = 0.0
            self.quiet_count    = 0

        return self.floor


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("=== HAPTIC SENSE ENGINE — Initialising ===")
    adc, motor_l, motor_r, led_l, led_r = init_hardware()

    initial_floor = run_diagnostics(adc, motor_l, motor_r, led_l, led_r)

    envelope    = EnvelopeFollower()
    pan_follow  = PanFollower()
    noise_track = NoiseFloorTracker(initial_floor)

    frame_num   = 0

    print("=== LISTENING — make any sound ===")
    print("    (whisper = soft glow+buzz  |  silence = everything off)")
    print("")

    try:
        while True:
            # 1. Collect audio frame from mic
            samples = collect_frame(adc, BUFFER_SIZE, SAMPLE_RATE_HZ)

            # 2. Raw RMS — the signal before any processing
            raw_rms = compute_rms(samples)

            # 3. Update adaptive noise floor
            noise_floor = noise_track.update(raw_rms)

            # 4. Map RMS through adaptive gate + expand/compress curve
            haptic_target = dynamic_map(raw_rms, noise_floor)

            # 5. Envelope follower — shapes attack/hold/release
            env_level = envelope.process(haptic_target)

            # 6. Spectral tilt → stereo pan
            zcr   = compute_zcr(samples)
            pan   = pan_follow.process(zcr)

            # 7. Compute all output duties (motors + LEDs)
            m_l, m_r, l_l, l_r = compute_duties(env_level, pan)

            # 8. Write outputs
            motor_l.duty_u16(m_l)
            motor_r.duty_u16(m_r)
            led_l.duty_u16(l_l)
            led_r.duty_u16(l_r)

            # 9. Debug — uncomment to monitor in REPL
            # if frame_num % 20 == 0:
            #     print("raw={:.4f} floor={:.4f} tgt={:.3f} env={:.3f} pan={:.2f} ML={} MR={} LL={} LR={}".format(
            #         raw_rms, noise_floor, haptic_target, env_level, pan, m_l, m_r, l_l, l_r))

            frame_num += 1

    except KeyboardInterrupt:
        # Clean stop — silence everything
        motor_l.duty_u16(0)
        motor_r.duty_u16(0)
        led_l.duty_u16(0)
        led_r.duty_u16(0)
        print("")
        print("=== ENGINE STOPPED ===")


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
