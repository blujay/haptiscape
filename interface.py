import uos

class HapticUI:
    def __init__(self, connected_ip=None):
        self.current_mode = "mic"
        self.connected_ip = connected_ip
        self.mic_enabled = True
        self.current_sens = 1.1

    def get_status_text(self):
        status = f"IP: {self.connected_ip}" if self.connected_ip else "Offline"
        micro = "ON" if self.mic_enabled else "OFF"
        return f"{status} | Mic {micro} | Sens {self.current_sens:.1f}"

    def get_track_list(self):
        try:
            if 'sd' not in uos.listdir('/'):
                return []
            return sorted([f for f in uos.listdir('/sd') if f.lower().endswith('.wav')])
        except Exception as e:
            print('[ui] get_track_list error:', e)
            return []

    def get_html(self):
        tracks = self.get_track_list()
        track_html = "".join([f'<li class="file-item" onclick="playFile({i})"><span>{t}</span><span>▶</span></li>' for i, t in enumerate(tracks)])
        sd_state = "no-sd"
        if tracks:
            sd_state = "has-files"
        else:
            try:
                if 'sd' in uos.listdir('/'):
                    sd_state = "empty"
                else:
                    sd_state = "not-mounted"
            except Exception:
                sd_state = "error"

        # UI State Variables
        mic_active_class = "on" if self.mic_enabled else ""
        sens_val = int((self.current_sens - 0.2) / 2.8 * 100)
        mic_panel_display = "flex" if self.current_mode == "mic" else "none"
        sd_panel_display = "flex" if self.current_mode.startswith("sd") else "none"
        mic_tab_class = "tab-btn btn-active" if self.current_mode == "mic" else "tab-btn"
        sd_tab_class = "tab-btn btn-active" if self.current_mode.startswith("sd") else "tab-btn"

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{ --bg: #05070a; --accent: #00d2ff; --text: #ffffff; }}
        body {{ background: var(--bg); color: var(--text); font-family: sans-serif; margin: 0; display: flex; justify-content: center; align-items: center; height: 100vh; -webkit-tap-highlight-color: transparent; }}
        .app {{ background: rgba(255,255,255,0.05); padding: 20px; border-radius: 20px; width: 90%; max-width: 400px; border: 1px solid rgba(255,255,255,0.1); }}
        .tab-btn {{ background: #1e293b; color: white; border: none; padding: 15px 20px; border-radius: 10px; flex: 1; cursor: pointer; font-size: 16px; touch-action: manipulation; }}
        .btn-active {{ background: var(--accent); color: black; }}
        #mic-btn {{ width: 120px; height: 120px; border-radius: 50%; border: 4px solid #333; background: #111; color: white; margin: 20px auto; display: block; font-size: 14px; touch-action: manipulation; }}
        #mic-btn.on {{ border-color: #00ff87; box-shadow: 0 0 15px #00ff87; }}
        .file-item {{ background: rgba(255,255,255,0.05); margin: 5px 0; padding: 15px; border-radius: 10px; display: flex; justify-content: space-between; cursor: pointer; touch-action: manipulation; }}
        .slider-container {{ margin: 20px 0; text-align: center; }}
        .slider-label {{ font-size: 14px; margin-bottom: 10px; }}
        input[type="range"] {{ width: 80%; height: 10px; -webkit-appearance: none; background: #333; border-radius: 5px; touch-action: manipulation; }}
        input[type="range"]::-webkit-slider-thumb {{ -webkit-appearance: none; width: 20px; height: 20px; background: var(--accent); border-radius: 50%; cursor: pointer; }}
    </style>
</head>
<body>
    <div class="app">
        <h2 style="text-align:center; letter-spacing:2px;">HAPTISCAPE</h2>
        <p style="font-size:0.7rem; text-align:center; opacity:0.6;">{self.get_status_text()}</p>
        
        <div style="display:flex; gap:10px; margin-bottom: 20px;">
            <button class="{mic_tab_class}" onclick="location.href='/mic'">MIC</button>
            <button class="{sd_tab_class}" onclick="location.href='/sd_list'">SD CARD</button>
        </div>

        <div id="mic-panel" style="display: {mic_panel_display}; flex-direction: column; text-align: center;">
            <button id="mic-btn" class="{mic_active_class}" onclick="location.href='/mic_toggle'">Toggle Mic</button>
            <div class="slider-container">
                <div class="slider-label">Mic Sensitivity: {self.current_sens:.1f}</div>
                <input type="range" min="0" max="100" value="{sens_val}" onchange="location.href='/mic_sens_set?val='+this.value">
            </div>
        </div>

        <div id="sd-panel" style="display: {sd_panel_display}; flex-direction: column;">
            <ul style="list-style:none; padding:0;">{track_html if track_html else ('<li>No WAV files in /sd</li>' if sd_state == 'empty' else ('<li>SD card not mounted</li>' if sd_state == 'not-mounted' else '<li>No Files</li>'))}</ul>
        </div>
    </div>

    <script>
        function playFile(idx) {{
            location.href = '/play_' + idx;
        }}
    </script>
</body>
</html>
"""

    def handle_request(self, request):
        new_mode = None

        if "GET /mic " in request or "GET /mic?" in request:
            self.current_mode = "mic"
            new_mode = "mic"

        elif "GET /sd_list" in request:
            self.current_mode = "sd"
            new_mode = None  # UI-only state; don't switch playback mode

        elif "GET /play_" in request:
            try:
                idx = int(request.split('/play_')[1].split(' ')[0])
                tracks = self.get_track_list()
                if 0 <= idx < len(tracks):
                    self.current_mode = f"sd_{idx}"
                    new_mode = self.current_mode
            except:
                pass

        elif "GET /mic_toggle" in request:
            self.mic_enabled = not self.mic_enabled
            new_mode = None

        elif "GET /mic_sens_set" in request:
            try:
                val = request.split('val=')[1].split(' ')[0]
                self.current_sens = 0.2 + (int(val) / 100) * 2.8
            except:
                pass
            if self.current_mode == "mic":
                new_mode = "mic"  # Restart mic with new sensitivity
            else:
                new_mode = None

        header = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
        return new_mode, header + self.get_html()