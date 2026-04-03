"""
================================================================================
  CELLO HAPTIC BACKTRACK — Pico W Real-Time Audio → ERM Haptic PWM Engine
  For use with: Raspberry Pi Pico W + PDM/analog mic + dual ERM motors
  Designed for: wearable 'back track' in 3D-printed housing, cello performance
  Author note: Engineered for maximum haptic expression across dynamic range.
================================================================================

WIRING GUIDE
────────────────────────────────────────────────────────────────────────────────
  MIC (analog, e.g. MAX9814 / INMP441 via I2S, or generic electret w/ op-amp):
    MIC_PIN (ADC)   → GPIO 26 (ADC0)  ← single analog output from mic module
    MIC_GND         → GND
    MIC_VCC         → 3.3V

  ERM MOTOR LEFT (via NPN transistor or DRV2605L):
    HAPTIC_LEFT_PIN → GPIO 15  ← PWM signal to motor driver gate/IN
    Motor driver    → external 5V supply (motors draw > 3.3V rail tolerance)

  ERM MOTOR RIGHT:
    HAPTIC_RIGHT_PIN → GPIO 16  ← PWM signal to motor driver gate/IN

  STATUS LEDs:
    LED_PIN_LEFT    → GPIO 14
    LED_PIN_RIGHT   → GPIO 17

  OPTIONAL — DRV2605L (I2C haptic driver for richer ERM control):
    I2C_SDA_PIN     → GPIO 4
    I2C_SCL_PIN     → GPIO 5

EXPRESSION DESIGN NOTES
────────────────────────────────────────────────────────────────────────────────
  Cello spans ~65 Hz (open C) to ~1047 Hz (high register), with rich harmonic
  content up to ~8 kHz. ERM motors respond to ~50–300 Hz vibration envelopes
  (not audio frequency directly — they react to PWM duty cycle = intensity).

  Expression layers in this script:
    1. RMS envelope    — overall bow pressure / volume → motor intensity
    2. Peak transient  — bow attacks, sforzando → sharp haptic burst
    3. Spectral centroid proxy — brightness (high vs low register) → L/R pan
    4. Sustain decay   — legato phrases → soft haptic fade, not hard cutoff
    5. Compression     — soft knee so pianissimo passages still register
    6. Gate            — silence below threshold = no buzz noise floor

HAPTIC ARCHITECTURE
────────────────────────────────────────────────────────────────────────────────
  Two ERM motors, left and right of spine in 3D-printed housing.
  Stereo pan is derived from spectral tilt (low freq bias → left body,
  high freq bias → right body) — giving spatial sensation mirroring
  cello register. Both motors share envelope intensity.

  PWM frequency: 200 Hz carrier — above human perception of individual
  pulses but well within ERM response bandwidth.

STARTUP DIAGNOSTICS SEQUENCE
────────────────────────────────────────────────────────────────────────────────
  On boot, before the main loop, the script runs:
    1. LED FLASH   — both LEDs flash 3× to confirm GPIO is live
    2. MIC TEST    — samples 1 second of audio, prints min/mid/max ADC values
                     confirms mic is wired and producing signal (not flat-line)
    3. LEFT MOTOR  — ramps 0→100% duty over 1s, holds 0.5s, ramps back down
                     LED_LEFT mirrors the ramp level
    4. RIGHT MOTOR — same ramp sequence independently
                     LED_RIGHT mirrors the ramp level
    5. BOTH MOTORS — simultaneous full-power pulse (0.5s) then off
                     confirms no power-rail sag or crosstalk dropout
    6. READY       — both LEDs double-flash, engine starts
================================================================================
"""

import machine
import utime
import math

# ──────────────────────────────────────────────────────────────────────────────
# PIN CONFIGURATION — edit these to match your wiring
# ──────────────────────────────────────────────────────────────────────────────

MIC_PIN           = 26   # ADC pin — analog mic output (GPIO 26 = ADC0)
HAPTIC_LEFT_PIN   = 15   # PWM out → left ERM motor driver
HAPTIC_RIGHT_PIN  = 16   # PWM out → right ERM motor driver
LED_PIN_LEFT      = 14   # Status LED left
LED_PIN_RIGHT     = 17   # Status LED right

# Optional I2C pins for DRV2605L haptic driver (unused if driving direct PWM)
I2C_SDA_PIN       = 4
I2C_SCL_PIN       = 5

# ──────────────────────────────────────────────────────────────────────────────
# AUDIO SAMPLING PARAMETERS
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE_HZ    = 8000   # ADC polling rate
BUFFER_SIZE       = 64     # Samples per processing frame (~8ms at 8kHz)
ADC_MIDPOINT      = 32768  # 16-bit midpoint (ADC gives 0–65535, we centre it)
ADC_MAX           = 32767  # Max amplitude after centering

# ──────────────────────────────────────────────────────────────────────────────
# PWM CARRIER PARAMETERS
# ──────────────────────────────────────────────────────────────────────────────

PWM_FREQ_HZ       = 200    # ERM carrier frequency — 200 Hz optimal for ERM
PWM_MAX_DUTY      = 65535  # MicroPython PWM duty is 16-bit (0–65535)

# ──────────────────────────────────────────────────────────────────────────────
# DIAGNOSTICS PARAMETERS
# ──────────────────────────────────────────────────────────────────────────────

DIAG_RAMP_STEPS        = 50     # Steps in each ramp (up or down)
DIAG_RAMP_STEP_MS      = 20     # ms per step → 1 second total ramp
DIAG_HOLD_MS           = 500    # Hold at peak power before ramping down
DIAG_BOTH_PULSE_MS     = 500    # Both-motors pulse duration
DIAG_MIC_SAMPLE_S      = 1      # Seconds of mic sampling in mic test
DIAG_LED_FLASH_COUNT   = 3      # Number of startup LED flashes
DIAG_LED_FLASH_ON_MS   = 150    # Flash on duration
DIAG_LED_FLASH_OFF_MS  = 150    # Flash off duration
DIAG_READY_FLASH_COUNT = 2      # Double-flash before engine starts
DIAG_MIC_FLAT_MARGIN   = 500    # ADC counts — if max-min below this, mic is suspect

# ──────────────────────────────────────────────────────────────────────────────
# EXPRESSION ENGINE PARAMETERS
# ──────────────────────────────────────────────────────────────────────────────

NOISE_GATE_THRESHOLD   = 0.02
SOFT_KNEE_LOW          = 0.05
SOFT_KNEE_HIGH         = 0.80
COMPRESSION_RATIO      = 0.55
MIN_HAPTIC_LEVEL       = 0.08
MAX_HAPTIC_LEVEL       = 1.00

ATTACK_COEFF           = 0.30
RELEASE_COEFF          = 0.06
TRANSIENT_BOOST        = 1.45
TRANSIENT_THRESHOLD    = 0.60

PAN_SMOOTHING          = 0.15
SPECTRAL_SPLIT_FREQ    = 300


# ──────────────────────────────────────────────────────────────────────────────
# HARDWARE INITIALISATION
# ──────────────────────────────────────────────────────────────────────────────

def init_hardware():
    """Initialise ADC, PWM outputs, and status LEDs."""

    adc = machine.ADC(MIC_PIN)

    pwm_left = machine.PWM(machine.Pin(HAPTIC_LEFT_PIN))
    pwm_left.freq(PWM_FREQ_HZ)
    pwm_left.duty_u16(0)

    pwm_right = machine.PWM(machine.Pin(HAPTIC_RIGHT_PIN))
    pwm_right.freq(PWM_FREQ_HZ)
    pwm_right.duty_u16(0)

    led_left  = machine.Pin(LED_PIN_LEFT,  machine.Pin.OUT)
    led_right = machine.Pin(LED_PIN_RIGHT, machine.Pin.OUT)
    led_left.value(0)
    led_right.value(0)

    return adc, pwm_left, pwm_right, led_left, led_right


# ──────────────────────────────────────────────────────────────────────────────
# DIAGNOSTICS ROUTINES
# ──────────────────────────────────────────────────────────────────────────────

def diag_led_flash(led_left, led_right, count, on_ms, off_ms):
    """Flash both LEDs [count] times."""
    for _ in range(count):
        led_left.value(1)
        led_right.value(1)
        utime.sleep_ms(on_ms)
        led_left.value(0)
        led_right.value(0)
        utime.sleep_ms(off_ms)


def diag_mic_test(adc):
    """
    Sample mic for DIAG_MIC_SAMPLE_S seconds and report signal range.
    A flat-line (max - min < DIAG_MIC_FLAT_MARGIN) warns of a wiring issue.
    Returns True if mic looks healthy, False if suspect.
    """
    print("[DIAG] MIC TEST — sampling for {}s...".format(DIAG_MIC_SAMPLE_S))
    n_samples   = SAMPLE_RATE_HZ * DIAG_MIC_SAMPLE_S
    interval_us = int(1_000_000 / SAMPLE_RATE_HZ)

    adc_min =  65535
    adc_max =  0
    adc_sum =  0

    for _ in range(n_samples):
        val = adc.read_u16()
        if val < adc_min:
            adc_min = val
        if val > adc_max:
            adc_max = val
        adc_sum += val
        utime.sleep_us(interval_us)

    adc_mean  = adc_sum // n_samples
    adc_range = adc_max - adc_min

    print("[DIAG] MIC  min={}  mid={}  max={}  range={}".format(
        adc_min, adc_mean, adc_max, adc_range))

    if adc_range < DIAG_MIC_FLAT_MARGIN:
        print("[DIAG] *** WARNING: Mic signal appears flat — check wiring! ***")
        return False

    print("[DIAG] MIC OK")
    return True


def diag_motor_ramp(pwm, led, label):
    """
    Ramp a single motor 0 → max → 0.
    The corresponding LED brightens and dims in sync via PWM-proportion blinking,
    so you can see which side is being tested at a glance.
    """
    print("[DIAG] MOTOR {} — ramping up...".format(label))

    # Ramp UP — 0.0 → 1.0
    for step in range(DIAG_RAMP_STEPS + 1):
        frac     = step / DIAG_RAMP_STEPS
        duty     = int(frac * PWM_MAX_DUTY)
        pwm.duty_u16(duty)
        on_ms    = int(frac * DIAG_RAMP_STEP_MS)
        off_ms   = DIAG_RAMP_STEP_MS - on_ms
        if on_ms  > 0:
            led.value(1)
            utime.sleep_ms(on_ms)
        if off_ms > 0:
            led.value(0)
            utime.sleep_ms(off_ms)

    # Hold at peak
    print("[DIAG] MOTOR {} — PEAK POWER".format(label))
    led.value(1)
    pwm.duty_u16(PWM_MAX_DUTY)
    utime.sleep_ms(DIAG_HOLD_MS)

    # Ramp DOWN — 1.0 → 0.0
    print("[DIAG] MOTOR {} — ramping down...".format(label))
    for step in range(DIAG_RAMP_STEPS, -1, -1):
        frac     = step / DIAG_RAMP_STEPS
        duty     = int(frac * PWM_MAX_DUTY)
        pwm.duty_u16(duty)
        on_ms    = int(frac * DIAG_RAMP_STEP_MS)
        off_ms   = DIAG_RAMP_STEP_MS - on_ms
        if on_ms  > 0:
            led.value(1)
            utime.sleep_ms(on_ms)
        if off_ms > 0:
            led.value(0)
            utime.sleep_ms(off_ms)

    pwm.duty_u16(0)
    led.value(0)
    print("[DIAG] MOTOR {} — ramp complete".format(label))
    utime.sleep_ms(300)   # Brief pause between motor tests


def diag_both_pulse(pwm_left, pwm_right, led_left, led_right):
    """
    Full-power simultaneous pulse on both motors.
    Checks for power-rail sag or crosstalk that would cause one motor to drop out
    when the other is also running — the most common cause of 'right motor silent'
    when both fire together.
    """
    print("[DIAG] BOTH MOTORS — full-power pulse ({} ms)...".format(DIAG_BOTH_PULSE_MS))
    pwm_left.duty_u16(PWM_MAX_DUTY)
    pwm_right.duty_u16(PWM_MAX_DUTY)
    led_left.value(1)
    led_right.value(1)
    utime.sleep_ms(DIAG_BOTH_PULSE_MS)
    pwm_left.duty_u16(0)
    pwm_right.duty_u16(0)
    led_left.value(0)
    led_right.value(0)
    print("[DIAG] BOTH MOTORS — off")
    utime.sleep_ms(300)


def run_diagnostics(adc, pwm_left, pwm_right, led_left, led_right):
    """
    Full startup diagnostics sequence. Prints results to REPL.
    Engine starts regardless — warnings are advisory (useful in field).
    """
    print("")
    print("=" * 52)
    print("   HAPTIC ENGINE — STARTUP DIAGNOSTICS")
    print("=" * 52)

    print("[DIAG] Step 1: LED flash test")
    diag_led_flash(led_left, led_right,
                   DIAG_LED_FLASH_COUNT,
                   DIAG_LED_FLASH_ON_MS,
                   DIAG_LED_FLASH_OFF_MS)

    print("[DIAG] Step 2: Mic signal test  (make some noise!)")
    mic_ok = diag_mic_test(adc)

    print("[DIAG] Step 3: Left motor ramp")
    diag_motor_ramp(pwm_left, led_left, "LEFT")

    print("[DIAG] Step 4: Right motor ramp")
    diag_motor_ramp(pwm_right, led_right, "RIGHT")

    print("[DIAG] Step 5: Both motors simultaneous pulse")
    diag_both_pulse(pwm_left, pwm_right, led_left, led_right)

    print("[DIAG] Step 6: Ready signal")
    diag_led_flash(led_left, led_right, DIAG_READY_FLASH_COUNT, 80, 80)

    print("=" * 52)
    if mic_ok:
        print("   DIAGNOSTICS PASSED — starting engine")
    else:
        print("   DIAGNOSTICS WARNED — mic suspect, starting anyway")
    print("=" * 52)
    print("")

    return mic_ok


# ──────────────────────────────────────────────────────────────────────────────
# DSP — AUDIO ANALYSIS ENGINE
# ──────────────────────────────────────────────────────────────────────────────

def compute_rms(samples):
    """RMS of a frame — perceptual loudness / bow pressure proxy. Returns 0.0–1.0."""
    acc = 0
    for s in samples:
        centred = s - ADC_MIDPOINT
        acc += centred * centred
    rms = math.sqrt(acc / len(samples))
    return min(rms / ADC_MAX, 1.0)


def compute_spectral_tilt(samples):
    """
    Zero-crossing rate as a lightweight spectral tilt proxy (no FFT needed).
    High ZCR = high-frequency content → right motor.
    Low ZCR  = low-frequency content → left motor.
    Returns normalised 0.0 (low/left) → 1.0 (high/right).
    """
    crossings = 0
    for i in range(1, len(samples)):
        prev = samples[i-1] - ADC_MIDPOINT
        curr = samples[i]   - ADC_MIDPOINT
        if (prev >= 0) != (curr >= 0):
            crossings += 1
    # Cello range at 8kHz / 64 samples: ~1 crossing (low C) to ~14 (high A)
    return min(crossings / 16.0, 1.0)


def apply_soft_knee_compression(level):
    """
    Soft-knee compressor.
    Lifts quiet passages so pianissimo is still felt.
    Tames extremes so fortissimo doesn't plateau into a flat buzz.
    """
    if level < NOISE_GATE_THRESHOLD:
        return 0.0
    if level < SOFT_KNEE_LOW:
        ratio = level / SOFT_KNEE_LOW
        return MIN_HAPTIC_LEVEL + ratio * (SOFT_KNEE_LOW - MIN_HAPTIC_LEVEL)
    if level < SOFT_KNEE_HIGH:
        norm = (level - SOFT_KNEE_LOW) / (SOFT_KNEE_HIGH - SOFT_KNEE_LOW)
        return SOFT_KNEE_LOW + norm * (SOFT_KNEE_HIGH - SOFT_KNEE_LOW)
    excess     = level - SOFT_KNEE_HIGH
    compressed = SOFT_KNEE_HIGH + excess * COMPRESSION_RATIO
    return min(compressed, MAX_HAPTIC_LEVEL)


# ──────────────────────────────────────────────────────────────────────────────
# ENVELOPE STATE
# ──────────────────────────────────────────────────────────────────────────────

class EnvelopeFollower:
    """Asymmetric attack/release. Fast attack catches bow transients,
    slow release sustains legato phrases."""
    def __init__(self):
        self.level = 0.0

    def process(self, target):
        coeff = ATTACK_COEFF if target > self.level else RELEASE_COEFF
        self.level += coeff * (target - self.level)
        return self.level


class PanFollower:
    """Smoothed stereo pan — prevents jittery L/R switching."""
    def __init__(self):
        self.pan = 0.5

    def process(self, target_pan):
        self.pan += PAN_SMOOTHING * (target_pan - self.pan)
        return self.pan


# ──────────────────────────────────────────────────────────────────────────────
# HAPTIC OUTPUT
# ──────────────────────────────────────────────────────────────────────────────

def haptic_duties(envelope_level, pan):
    """
    Constant-power pan law → (duty_left, duty_right) as 16-bit PWM values.
    pan 0.0 = full left body, 0.5 = centre, 1.0 = full right body.
    """
    if envelope_level <= 0.0:
        return 0, 0
    angle      = pan * (math.pi / 2)
    gain_left  = math.cos(angle)
    gain_right = math.sin(angle)
    duty_left  = max(0, min(PWM_MAX_DUTY, int(envelope_level * gain_left  * PWM_MAX_DUTY)))
    duty_right = max(0, min(PWM_MAX_DUTY, int(envelope_level * gain_right * PWM_MAX_DUTY)))
    return duty_left, duty_right


# ──────────────────────────────────────────────────────────────────────────────
# SAMPLE COLLECTION
# ──────────────────────────────────────────────────────────────────────────────

def collect_frame(adc, n_samples, sample_rate_hz):
    """Collect n_samples from ADC at ~sample_rate_hz. Returns list of u16 values."""
    interval_us = int(1_000_000 / sample_rate_hz)
    samples = []
    for _ in range(n_samples):
        samples.append(adc.read_u16())
        utime.sleep_us(interval_us)
    return samples


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("=== CELLO HAPTIC ENGINE — Initialising ===")
    adc, pwm_left, pwm_right, led_left, led_right = init_hardware()

    # Startup diagnostics — motors, mic, and LEDs tested before performance
    run_diagnostics(adc, pwm_left, pwm_right, led_left, led_right)

    envelope   = EnvelopeFollower()
    pan_follow = PanFollower()
    prev_rms   = 0.0
    frame_count = 0

    # Both LEDs on = engine running
    led_left.value(1)
    led_right.value(1)

    print("=== RUNNING — Listening for cello... ===")

    try:
        while True:
            # 1. Collect audio frame
            samples = collect_frame(adc, BUFFER_SIZE, SAMPLE_RATE_HZ)

            # 2. Compute RMS (loudness / bow pressure)
            raw_rms = compute_rms(samples)

            # 3. Transient detection — bow attacks / pizzicato
            delta = raw_rms - prev_rms
            if delta > 0 and raw_rms > TRANSIENT_THRESHOLD:
                boosted_rms = min(raw_rms * TRANSIENT_BOOST, 1.0)
            else:
                boosted_rms = raw_rms
            prev_rms = raw_rms

            # 4. Soft-knee compression
            compressed = apply_soft_knee_compression(boosted_rms)

            # 5. Envelope follower (attack/release shaping)
            env_level = envelope.process(compressed)

            # 6. Spectral tilt → stereo pan
            tilt = compute_spectral_tilt(samples)
            pan  = pan_follow.process(tilt)

            # 7. Constant-power pan → PWM duties
            duty_l, duty_r = haptic_duties(env_level, pan)

            # 8. Write to motors
            pwm_left.duty_u16(duty_l)
            pwm_right.duty_u16(duty_r)

            # 9. Heartbeat — alternate LEDs every 256 frames (~2s)
            frame_count += 1
            if frame_count % 256 == 0:
                led_left.toggle()
                led_right.toggle()

            # Debug — uncomment to monitor in REPL during testing:
            # print("RMS:{:.3f} ENV:{:.3f} PAN:{:.2f} L:{} R:{}".format(
            #     raw_rms, env_level, pan, duty_l, duty_r))

    except KeyboardInterrupt:
        pwm_left.duty_u16(0)
        pwm_right.duty_u16(0)
        led_left.value(0)
        led_right.value(0)
        print("=== HAPTIC ENGINE STOPPED ===")


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
