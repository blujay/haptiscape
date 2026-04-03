import machine

class ModeManager:
    def __init__(self, mic_engine=None, sd_session=None, ui=None):
        self.mic_engine = mic_engine
        self.sd_session = sd_session
        self.ui = ui
        self.current_mode = 'idle'

    def stop_current(self):
        if self.current_mode == 'mic' and self.mic_engine is not None:
            try:
                self.mic_engine.shutdown()
            except Exception:
                pass

        if self.current_mode.startswith('sd_') and self.sd_session is not None:
            try:
                self.sd_session.stop()
            except Exception:
                pass

    def switch(self, new_mode):
        if new_mode is None:
            return self.current_mode

        if new_mode == 'reset':
            print('🔁 Reset requested')
            machine.reset()

        if new_mode == self.current_mode:
            return self.current_mode

        self.stop_current()

        if new_mode == 'mic':
            if self.mic_engine is not None:
                if not getattr(self.mic_engine, 'calibrated', False):
                    try:
                        self.mic_engine.calibrate()
                    except Exception as e:
                        print('❌ Mic calibration failed:', e)
                try:
                    self.mic_engine.set_profile('guitar')
                except Exception as e:
                    print('❌ Mic set_profile failed:', e)
                self.mic_engine.enable()
                if self.ui is not None:
                    self.mic_engine.sensitivity = self.ui.current_sens
                print('🎤 Mode changed to: mic')
            else:
                print('⚠️ Mic mode requested but mic_engine is unavailable')

        elif new_mode == 'mic_disable':
            if self.mic_engine is not None:
                self.mic_engine.disable()
                print('🛑 Mic mode disabled by user')
            self.current_mode = 'idle'
            return self.current_mode

        elif new_mode == 'mic_enable':
            if self.mic_engine is not None:
                self.mic_engine.enable()
                if self.ui is not None:
                    self.mic_engine.sensitivity = self.ui.current_sens
                print('✅ Mic enabled by user')
            new_mode = 'mic'

        elif new_mode == 'mic_sens_up':
            if self.mic_engine is not None:
                self.mic_engine.change_sensitivity(0.1)
            new_mode = self.current_mode

        elif new_mode == 'mic_sens_down':
            if self.mic_engine is not None:
                self.mic_engine.change_sensitivity(-0.1)
            new_mode = self.current_mode

        elif new_mode == 'mic_record':
            if self.mic_engine is not None:
                self.mic_engine.start_recording()
            new_mode = self.current_mode

        elif new_mode == 'mic_stop_record':
            if self.mic_engine is not None:
                self.mic_engine.stop_recording()
            new_mode = self.current_mode

        elif new_mode == 'mic_playback':
            if self.mic_engine is not None:
                self.mic_engine.start_playback()
            new_mode = self.current_mode

        elif new_mode == 'mic_stop_playback':
            if self.mic_engine is not None:
                self.mic_engine.stop_playback()
            new_mode = self.current_mode

        elif new_mode == 'mic_toggle':
            if self.mic_engine is not None and self.ui is not None:
                self.mic_engine.enabled = self.ui.mic_enabled
            new_mode = self.current_mode

        elif new_mode == 'mic_sens_set':
            if self.mic_engine is not None and self.ui is not None:
                self.mic_engine.sensitivity = self.ui.current_sens
            new_mode = self.current_mode

        elif new_mode.startswith('sd_'):
            if self.sd_session is not None:
                try:
                    idx = int(new_mode.split('_', 1)[1])
                    self.sd_session.load_track(idx)
                    print(f'🎵 Mode changed to SD track {idx}')
                except Exception as e:
                    print('❌ SD mode initialization failed:', e)
                    new_mode = 'idle'
            else:
                print('⚠️ SD mode requested but sd_session is unavailable')
                new_mode = 'idle'

        elif new_mode == 'idle':
            print('⏹ Mode changed to idle')

        else:
            print('⚠️ Unknown mode requested, switching to idle:', new_mode)
            new_mode = 'idle'

        self.current_mode = new_mode
        return self.current_mode

    def step(self):
        if self.current_mode == 'mic' and self.mic_engine is not None:
            if self.mic_engine.enabled:
                self.mic_engine.step()
            else:
                # Ensure motors are silent if mic has been disabled
                try:
                    self.mic_engine.shutdown()
                except Exception:
                    pass

        elif self.current_mode.startswith('sd_') and self.sd_session is not None:
            status = self.sd_session.step()
            if status == 'done':
                print('✅ SD playback complete, switching to idle')
                self.switch('idle')
