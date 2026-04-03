# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Profiles
# ──────────────────────────────────────────────────────────────────────────────
# A profile is a complete description of one setup — both the physical hardware
# and how sound should be shaped into sensation.
#
# HARDWARE section: which pins connect to which components.
#   Add only the components your build actually has.
#   If 'sd' is missing, SD playback simply won't be available.
#   If 'speaker' isn't there yet, that's fine — add it when you need it.
#
# FEEL section: the numbers that shape the haptic character.
#   You don't need to understand the engineering to experiment here.
#   The comments describe what each value does in plain terms.
#
# To create a new profile:
#   1. Copy an existing block below
#   2. Give it a new name
#   3. Adjust hardware pins to match your wiring
#   4. Adjust feel values to match your intent
#   5. Set ACTIVE_PROFILE in config.py to your new name
# ──────────────────────────────────────────────────────────────────────────────

PROFILES = {

    'cello': {

        'hardware': {
            'motors':         [15, 16],   # PWM pins → ERM motor drivers
            'motor_pwm_freq': 200,        # Carrier frequency in Hz (ERM: 150–250)
            'leds':           [14, 17],   # GPIO pins → status LEDs
            'mic':            {'adc': 26},
            'sd':             {'sck': 10, 'mosi': 11, 'miso': 12, 'cs': 13},
        },

        'feel': {
            # How sensitive to background noise before haptics start
            # Lower = triggers on quieter sounds   Higher = ignores more background
            'noise_gate':            0.8,

            # How quickly the vibration responds to a new sound
            # Lower = slower, smoother             Higher = snappier, more reactive
            'attack':                0.30,

            # How long vibration lingers after a sound fades
            # Lower = longer fade                  Higher = cuts off faster
            'release':               0.06,

            # Where quiet sounds start getting lifted into a feelable range
            'expand_knee':           0.20,

            # Where loud sounds start getting reined in
            'compress_knee':         0.70,

            # How much loud sounds are tamed above the compress point
            # Lower = more compression             Higher = more dynamic range
            'compress_ratio':        0.45,

            # How much a sudden attack (bow hit, pluck) gets a burst of intensity
            'transient_boost':       1.45,

            # How prominent a sound needs to be to count as a transient
            'transient_threshold':   0.60,

            # How fluidly vibration moves left to right across the body
            # Lower = slow, drifting pan           Higher = quick, reactive
            'pan_smoothing':         0.15,

            # Spectral ceiling for L/R pan calculation
            'zcr_max':               16.0,

            # LED brightness curve — 2.2 matches how the eye perceives light
            'led_gamma':             2.2,
        },
    },

    'voice': {

        'hardware': {
            'motors':         [15, 16],
            'motor_pwm_freq': 200,
            'leds':           [14, 17],
            'mic':            {'adc': 26},
            'sd':             {'sck': 10, 'mosi': 11, 'miso': 12, 'cs': 13},
        },

        'feel': {
            'noise_gate':            0.5,    # More sensitive — picks up quiet speech
            'attack':                0.45,
            'release':               0.055,  # Slow release — follows breath and phrase
            'expand_knee':           0.20,
            'compress_knee':         0.70,
            'compress_ratio':        0.45,
            'transient_boost':       1.55,
            'transient_threshold':   0.55,
            'pan_smoothing':         0.12,
            'zcr_max':               20.0,   # Higher — voice has more high-freq content
            'led_gamma':             2.2,
        },
    },

    'guitar': {

        'hardware': {
            'motors':         [15, 16],
            'motor_pwm_freq': 200,
            'leds':           [14, 17],
            'mic':            {'adc': 26},
            'sd':             {'sck': 10, 'mosi': 11, 'miso': 12, 'cs': 13},
        },

        'feel': {
            'noise_gate':            1.2,    # Less sensitive — cuts through a loud room
            'attack':                0.50,   # Fast — catches picks and strums
            'release':               0.65,   # Quick decay — staccato feel
            'expand_knee':           0.15,
            'compress_knee':         0.75,
            'compress_ratio':        0.50,
            'transient_boost':       1.6,    # Strong kick for pick attack
            'transient_threshold':   0.50,
            'pan_smoothing':         0.18,
            'zcr_max':               18.0,
            'led_gamma':             2.2,
        },
    },
}
