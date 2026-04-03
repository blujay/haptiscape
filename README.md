# Haptiscape

A wearable haptic feedback system built on the Raspberry Pi Pico W. Haptiscape listens to audio and data in real time from a variety of input sources and translates them into vibration patterns via LRA and ERM motors — creating a physical sensation that mirrors what's being heard or sensed.

The cello variant (`cello_haptic.py`) is designed for live performance use, worn on the back so the performer feels the instrument from the inside.

---

## Hardware

- **MCU:** Raspberry Pi Pico W (dual-core RP2040, MicroPython)
- **Motors:** ERM (eccentric rotating mass) and LRA (linear resonant actuator), PWM-driven
- **Audio input:** ADC-connected microphone(s); optional stereo dual-mic setup
- **Storage:** SPI SD card (FAT filesystem, mounted at `/sd`), WAV files only
- **Connectivity:** Wi-Fi (2.4GHz, STA mode preferred); mobile web UI served from the Pico itself
- **Integration:** Unity Timeline via Bluetooth/Wi-Fi signal

### Key hardware constraints
- 264KB RAM; no hardware float unit — keep DSP lean
- ADC is 12-bit native (0–4095), reads as 16-bit scaled (0–65535) in MicroPython
- PWM is 16-bit duty (0–65535); ERM carrier runs at 200Hz
- SD card: stereo 16-bit WAV at 44.1kHz works reliably; higher sample rates may stutter

---

## Input modes

| Mode | Description |
|---|---|
| Live mic audio | Real-time audio from one or two mics (mono/stereo) |
| Stored audio | WAV file playback from the onboard SD card |
| Unity timeline signal | WAV patterns or triggers sent from a Unity Timeline |
| Live data stream | Haptic interpretation of a live data stream |
| Stored data | Playback from a spreadsheet, JSON file, or similar |
| Live Unity spatial | Spatial sound output from a Unity headset listener |
| Pattern library | Selectable haptic pulse pattern library |
| Generative audio | Camera feed converted to generative audio → haptics |

---

## Codebase

| File | Purpose |
|---|---|
| `cello_haptic.py` | Standalone cello-specific haptic engine with full diagnostics |
| `haptic_engine.py` | Generic haptic engine for any audio source (voice, music, breath) |
| `main.py` | Web-served system with Wi-Fi, UI, SD playback, and mode switching |
| `main_mic.py` | Mic DSP engine with adaptive noise floor |
| `main_sd.py` | WAV file player with envelope-driven haptics |
| `mode_manager.py` | State machine for switching between input modes |
| `interface.py` | Mobile web UI served from the Pico |
| `config.py` | Hardware pin assignments |
| `secrets.py` | Wi-Fi credentials (not committed) |
| `sdcard.py` | SD card SPI driver |

---

## Getting started

1. Copy your Wi-Fi credentials into `secrets.py`.
2. Flash MicroPython to your Pico W if not already done.
3. Upload all `.py` files to the Pico root.
4. For SD playback, format the card as FAT and place 16-bit stereo WAV files in `/sd`.
5. Power on — the Pico will connect to Wi-Fi and serve the control UI at its IP address.

For the cello performance variant, run `cello_haptic.py` directly. It includes startup motor diagnostics and does not require Wi-Fi.

---

## Design intent

Haptiscape is a performance instrument as much as a technical system. The haptic output is meant to feel expressive, not mechanical. Motor intensity, envelope shape, and panning all contribute to how the vibration reads on the body — and those qualities matter as much as signal accuracy.

---

## Working with Claude on this project

This repo includes a `CLAUDE.md` file that Claude reads automatically at the start of each session — covering project context, hardware constraints, and how the collaboration works.
