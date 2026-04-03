# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — System Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Global constants that apply to every profile and setup.
# Hardware pins and feel parameters live in profiles.py instead.
# ──────────────────────────────────────────────────────────────────────────────

# ACTIVE PROFILE
# Change this to switch between hardware/feel setups.
# Profiles are defined in profiles.py.
ACTIVE_PROFILE = 'cello'

# ──────────────────────────────────────────────────────────────────────────────
# AUDIO SAMPLING
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_RATE_HZ = 8000   # ADC polling rate
BUFFER_SIZE    = 64     # Samples per processing frame (~8ms at 8kHz)
ADC_MIDPOINT   = 32768  # Centre of the 16-bit ADC range
ADC_MAX        = 32767  # Max amplitude after centring

# ──────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────────────────────────────────────

PWM_MAX       = 65535   # 16-bit PWM ceiling — universal on Pico
LED_PWM_FREQ  = 1000    # LED PWM frequency — high enough to avoid flicker

# ──────────────────────────────────────────────────────────────────────────────
# NETWORK
# ──────────────────────────────────────────────────────────────────────────────

try:
    from secrets import HOTSPOT_SSID, HOTSPOT_PASSWORD
except ImportError:
    HOTSPOT_SSID     = 'Your_Hotspot_SSID'
    HOTSPOT_PASSWORD = 'Your_Hotspot_Password'
