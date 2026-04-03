# Haptiscape hardware and network settings

# PWM motor pins (GP15 and GP16 recommended for ERM drivers)
MOTOR_PINS = (15, 16)

# Microphone ADC input pin (GP26 for ADC0)
MIC_PIN = 26

# SD card SPI pins for the Pico (customize to your wiring)
SD_PINS = {
    'sck': 10,   # GP10 (SPI0 SCK)
    'mosi': 11,  # GP11 (SPI0 MOSI)
    'miso': 12,  # GP12 (SPI0 MISO)
    'cs': 13     # GP13 (SPI0 CS)
}

# Main mode supported by the mic engine (single mic mode)
MIC_PROFILES = ['mic']

# Mobile hotspot credentials (set your own in secrets.py)
try:
    from secrets import HOTSPOT_SSID, HOTSPOT_PASSWORD
except ImportError:
    HOTSPOT_SSID = 'Your_Hotspot_SSID'
    HOTSPOT_PASSWORD = 'Your_Hotspot_Password'
