# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Profiles
# ──────────────────────────────────────────────────────────────────────────────
# A profile is a complete description of one setup — both the physical hardware
# and how sound should be shaped into sensation.
#
# FEEL section has two groups of parameters:
#
#   MIC ENGINE (sources/mic.py — new high-contrast per-sample engine)
#   SD / legacy (sources/sd.py + processing.py — frame-based pipeline)
#
# The mic engine parameters are the ones to tune for live performance.
# The SD parameters are used for WAV playback and are less critical.
#
# ── MIC ENGINE QUICK-TUNE GUIDE ──────────────────────────────────────────────
#   sensitivity      Raise if motors barely respond. Lower if always triggering.
#   open_threshold   Lower = gate opens on quieter sounds. Start: 0.025.
#   release_coeff    0.80 = 10ms snap. 0.90 = 20ms. 0.95 = 40ms legato.
#   power_law_l/r    Higher = harder contrast (more silence vs more punch).
#                    Try 2.0–5.0. Lower for smoother continuous feel.
#   motor_floor      Raise if motors stall at low signals (ERM stiction).
#                    Lower for truly silent background. Try 6000–15000.
#   hold_time_ms     How long gate stays open after signal drops. Raise for
#                    legato/voice phrases. Lower for tight staccato.
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

            # ── MIC ENGINE ───────────────────────────────────────────────────
            # Input gain. Raise first if motors don't respond. Lower if
            # background noise keeps the gate open.
            'sensitivity':      3.0,

            # DC offset tracking speed. Leave at 0.003 unless ADC drifts badly.
            'auto_bias_coeff':  0.003,

            # Motor vibration → mic feedback cancellation. Raise if the motors
            # make the mic think there is signal when the room is quiet.
            'feedback_damp':    0.05,

            # Gate opens when fast envelope exceeds this level.
            # Lower = more sensitive.   Typical range: 0.015 – 0.060
            'open_threshold':   0.025,

            # Gate closes when fast envelope drops below this level.
            # Must stay below open_threshold to prevent chatter.
            'close_threshold':  0.010,

            # How long (ms) the gate holds open after the signal drops.
            # Raise for legato/voice. Lower for tight percussive staccato.
            'hold_time_ms':     20,

            # Per-sample fade rate once gate closes.
            # 0.80 = ~10ms release   0.90 = ~20ms   0.95 = ~40ms
            'release_coeff':    0.90,

            # Motor L — fast envelope (transients/attacks).
            # Higher power law = harder contrast between silence and output.
            'power_law_l':      2.0,

            # Motor R — slow envelope (sustained energy/texture).
            # Lower than L for smoother continuous feel.
            'power_law_r':      1.5,

            # Minimum PWM duty when gate is open.
            # Ensures ERMs spin reliably. Range: 6000–15000.
            # Lower = quieter floor but risk of stall. Higher = always audible buzz.
            'motor_floor':      8000,

            # ── SD / LEGACY (used by sources/sd.py + processing.py) ──────────
            'noise_gate':            0.8,
            'attack':                0.30,
            'release':               0.06,
            'expand_knee':           0.20,
            'compress_knee':         0.70,
            'compress_ratio':        0.45,
            'transient_boost':       1.45,
            'transient_threshold':   0.60,
            'pan_smoothing':         0.15,
            'zcr_max':               16.0,
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

            # ── MIC ENGINE ───────────────────────────────────────────────────
            # Tuned for spoken voice: moderate sensitivity, longer phrases.
            'sensitivity':      3.5,     # Slightly higher — voice can be quiet
            'auto_bias_coeff':  0.003,
            'feedback_damp':    0.05,
            'open_threshold':   0.020,   # Lower — reacts to quiet speech
            'close_threshold':  0.008,
            'hold_time_ms':     40,      # Longer hold — keeps gate open across syllables
            'release_coeff':    0.93,    # Slower fade — follows phrase breath
            'power_law_l':      1.8,     # Less contrast — voice is naturally dynamic
            'power_law_r':      1.4,
            'motor_floor':      7000,

            # ── SD / LEGACY ───────────────────────────────────────────────────
            'noise_gate':            0.5,
            'attack':                0.45,
            'release':               0.055,
            'expand_knee':           0.20,
            'compress_knee':         0.70,
            'compress_ratio':        0.45,
            'transient_boost':       1.55,
            'transient_threshold':   0.55,
            'pan_smoothing':         0.12,
            'zcr_max':               20.0,
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

            # ── MIC ENGINE ───────────────────────────────────────────────────
            # Tuned for percussion / guitar: very snappy, high contrast.
            'sensitivity':      2.5,     # Lower — instrument is loud
            'auto_bias_coeff':  0.003,
            'feedback_damp':    0.05,
            'open_threshold':   0.035,   # Higher — ignores quiet background
            'close_threshold':  0.015,
            'hold_time_ms':     10,      # Short hold — staccato feel
            'release_coeff':    0.82,    # Fast snap off
            'power_law_l':      3.0,     # High contrast — snap on/off
            'power_law_r':      2.0,
            'motor_floor':      10000,   # Higher floor — needs punch through noise

            # ── SD / LEGACY ───────────────────────────────────────────────────
            'noise_gate':            1.2,
            'attack':                0.50,
            'release':               0.65,
            'expand_knee':           0.15,
            'compress_knee':         0.75,
            'compress_ratio':        0.50,
            'transient_boost':       1.6,
            'transient_threshold':   0.50,
            'pan_smoothing':         0.18,
            'zcr_max':               18.0,
            'led_gamma':             2.2,
        },
    },
}
