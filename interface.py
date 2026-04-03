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
            return sorted([f for f in uos.listdir("/sd") if f.lower().endswith(".wav")])
        except:
            return []

    def get_html(self):
        tracks = self.get_track_list()
        track_html = "".join([f'<li class="file-item" onclick="playFile({i})"><span>{t}</span><span>▶</span></li>' for i, t in enumerate(tracks)])
        
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
        body {{ background: var(--bg); color: var(--text); font-family: sans-serif; margin: 0; display: flex; justify-content: center; align-items: center; height: 100vh; }}
        .app {{ background: rgba(255,255,255,0.05); padding: 20px; border-radius: 20px; width: 90%; max-width: 400px; border: 1px solid rgba(255,255,255,0.1); }}
        .tab-btn {{ background: #1e293b; color: white; border: none; padding: 10px; border-radius: 10px; flex: 1; cursor: pointer; }}
        .btn-active {{ background: var(--accent); color: black; }}
        #mic-btn {{ width: 100px; height: 100px; border-radius: 50%; border: 4px solid #333; background: #111; color: white; margin: 20px auto; display: block; }}
        #mic-btn.on {{ border-color: #00ff87; box-shadow: 0 0 15px #00ff87; }}
        .file-item {{ background: rgba(255,255,255,0.05); margin: 5px 0; padding: 10px; border-radius: 10px; display: flex; justify-content: space-between; cursor: pointer; }}
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
            <input type="range" min="0" max="100" value="{sens_val}" onchange="location.href='/mic_sens_set?val='+this.value">
        </div>

        <div id="sd-panel" style="display: {sd_panel_display}; flex-direction: column;">
            <ul style="list-style:none; padding:0;">{track_html if track_html else "<li>No Files</li>"}</ul>
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
        if "GET /mic " in request or "GET /mic?" in request:
            self.current_mode = "mic"
        elif "GET /sd_list" in request:
            self.current_mode = "sd"
        elif "GET /play_" in request:
            try:
                idx = int(request.split('/play_')[1].split(' ')[0])
                tracks = self.get_track_list()
                if 0 <= idx < len(tracks):
                    self.current_mode = f"sd_{idx}"
            except: pass
        elif "GET /mic_toggle" in request:
            self.mic_enabled = not self.mic_enabled
        elif "GET /mic_sens_set" in request:
            try:
                val = request.split('val=')[1].split(' ')[0]
                self.current_sens = 0.2 + (int(val) / 100) * 2.8
            except: pass
            
        header = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
        return self.current_mode, header + self.get_html()