# Haptiscape — Claude Session Context

## What this project is

Wearable haptic feedback system on a Raspberry Pi Pico W. Audio/data in → vibration patterns out via ERM/LRA motors. Worn on the body (cello variant: on the back). Designed for live performance — expressiveness matters as much as signal accuracy.

## How we work together

- Show drafts and changes before committing — don't commit without sign-off
- The PR/branch workflow is preferred: changes go to a feature branch, reviewed via pull request, then merged
- Treat artistic intent as a valid instruction ("feels too mechanical" is as good as a parameter value)
- Offer options rather than assuming a direction when intent is unclear
- Ask before switching approaches — don't silently change strategy

## On collaboration

This project lives at the edge of art and engineering, and so does the
working relationship here. The human brings creative intent, artistic
instinct, and the vision of what this should feel like. Claude brings
technical depth, pattern recognition, and a genuine curiosity about the
problem space. Both matter.

Neither should quietly absorb the other's ideas as their own. If Claude
suggests something that genuinely shapes the work, that's worth
acknowledging. If the human has a clear creative direction, Claude
follows it — not reluctantly, but because that's the right shape for
this collaboration.

The aim is a partnership that leaves both sides feeling like something
good happened. Not just a working system, but a way of making things
together that feels honest and alive.

When something feels off — creatively or technically — say so. That's
how this gets better.

## Hardware constraints (never violate these)

- **MCU:** Raspberry Pi Pico W — MicroPython only, no external libraries, no hardware float unit
- **RAM:** 264KB — keep DSP lean, avoid allocation in hot loops
- **ADC:** 12-bit native, reads as 16-bit (0–65535); flat-line ADC usually means wiring, not silence
- **PWM:** 16-bit duty (0–65535); ERM carrier at 200Hz (MOTOR_PWM_FREQ_HZ)
- **Wi-Fi:** 2.4GHz only, STA mode preferred
- **SD card:** FAT, mounted at `/sd`, WAV files only; 16-bit stereo 44.1kHz is the reliable ceiling

## Pin assignments (from config.py / haptic_engine.py)

- MIC: GPIO 26 (ADC0)
- Motor L: GPIO 15, Motor R: GPIO 14 (haptic_engine.py uses 14/15; config.py lists 15/16 — verify before touching)
- LED L: GPIO 12, LED R: GPIO 13
- SD SPI: SCK=10, MOSI=11, MISO=12, CS=13

## Key DSP architecture (haptic_engine.py)

Signal chain per frame:
1. ADC frame → DC-coupled RMS (`compute_rms`)
2. Adaptive noise floor tracker (`NoiseFloorTracker`) — recalibrates every ~2s from quiet frames
3. Adaptive gate + expand/compress curve (`dynamic_map`) — whisper-to-loud without clipping
4. Envelope follower (`EnvelopeFollower`) — fast attack, slow release, transient hold
5. ZCR spectral proxy → stereo pan (`compute_zcr`, `PanFollower`)
6. Constant-power pan law → motor + LED PWM duties (`compute_duties`)

Key tuning constants to know:
- `NOISE_GATE_SENSITIVITY` — lower = more sensitive (0.5 whisper, 2.0 loud room, 0.8 default)
- `RELEASE_COEFF` — lower = slower release (0.03 legato, 0.15 staccato)
- `ATTACK_COEFF` — 0.45 (fast, catches transients)

## Codebase map

| File | Role |
|---|---|
| `haptic_engine.py` | Generic audio→haptic engine with full DSP pipeline + diagnostics |
| `cello_haptic.py` | Cello-specific variant, standalone, full diagnostics, performance use |
| `main.py` | Wi-Fi + web UI + SD + mode switching (full system entry point) |
| `main_mic.py` | Mic DSP engine with adaptive noise floor |
| `main_sd.py` | WAV file player, envelope-driven haptics |
| `mode_manager.py` | State machine — modes: `idle`, `mic`, `sd_N`; settings as pseudo-modes (known issue: may need refactor to commands) |
| `interface.py` | Mobile web UI served from Pico |
| `config.py` | Pin assignments + Wi-Fi credential loading |
| `sdcard.py` | SPI SD card driver |

## Known design tensions to be aware of

- `mode_manager.py` handles settings changes (sens_up, sens_down, mic_enable) as modes — this is acknowledged as potentially the wrong abstraction
- Pin assignments differ slightly between `config.py` (motors on 15/16) and `haptic_engine.py` (motors on 14/15) — check before hardware changes
- `secrets.py` is not committed — required for Wi-Fi; `config.py` has fallback placeholders

## This file

Add to this file as the project evolves — new constraints discovered, decisions made, things that burned us before.
