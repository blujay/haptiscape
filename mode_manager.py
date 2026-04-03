# ──────────────────────────────────────────────────────────────────────────────
# HAPTISCAPE — Mode Manager
# ──────────────────────────────────────────────────────────────────────────────
# Owns the active input source and coordinates switching between modes.
#
# Sources are imported lazily — only loaded into RAM when first used.
# This matters on a Pico with 264KB.
#
# MODES
# ──────────────────────────────────────────────────────────────────────────────
#   'idle'      — no source active, motors silent
#   'mic'       — live microphone input
#   'sd_N'      — SD card track N (e.g. 'sd_0', 'sd_1')
# ──────────────────────────────────────────────────────────────────────────────

import machine


class ModeManager:

    def __init__(self, profile):
        self.profile = profile
        self.mode    = 'idle'
        self.source  = None

        # Lazily populated on first use
        self._mic_source = None
        self._sd_source  = None

    # ── SWITCHING ─────────────────────────────────────────────────────────────

    def switch(self, new_mode):
        """Switch to a new mode. Stops the current source first."""
        if new_mode is None or new_mode == self.mode:
            return

        if new_mode == 'reset':
            machine.reset()

        self._stop_current()

        if new_mode == 'mic':
            self._start_mic()

        elif new_mode.startswith('sd_'):
            try:
                idx = int(new_mode.split('_', 1)[1])
                self._start_sd(idx)
            except (ValueError, IndexError):
                print('[mode] Bad SD mode:', new_mode)
                new_mode = 'idle'

        elif new_mode == 'idle':
            print('[mode] Idle')

        else:
            print('[mode] Unknown mode:', new_mode)
            new_mode = 'idle'

        self.mode = new_mode

    # ── STEP — called every loop tick ─────────────────────────────────────────

    def step(self):
        """Run one tick of the active source. Call this in the main loop."""
        if self.source is None:
            return

        result = self.source.step()

        if result == 'done':
            print('[mode] Source finished — going idle')
            self._stop_current()
            self.mode = 'idle'

    # ── INTERNAL ──────────────────────────────────────────────────────────────

    def _stop_current(self):
        if self.source is not None:
            try:
                self.source.stop()
            except Exception as e:
                print('[mode] Stop error:', e)
            self.source = None

    def _start_mic(self):
        if self._mic_source is None:
            from sources.mic import MicSource
            self._mic_source = MicSource(self.profile)
        try:
            self._mic_source.start()
            self.source = self._mic_source
            print('[mode] Mic active')
        except Exception as e:
            print('[mode] Mic start error:', e)
            self.source = None

    def _start_sd(self, index):
        if self._sd_source is None:
            from sources.sd import SDSource
            self._sd_source = SDSource(self.profile)
        try:
            if self._sd_source.load_track(index):
                self._sd_source.start()
                self.source = self._sd_source
            else:
                self.source = None
        except Exception as e:
            print('[mode] SD start error:', e)
            self.source = None
