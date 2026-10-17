#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wagner Martins and minitela-re contributors
"""
Minitela Web Control Panel & Virtual Display Preview
A modern web UI to control the notebook mini-display, preview the screen,
manage system stats, trigger WhatsApp alerts, and play animations.
"""

import http.server
import json
import os
import socketserver
import urllib.parse
from minitela import (
    MinitelaDevice,
    PAGE_WHATSAPP,
    PAGE_REMINDERS,
    PAGE_SYSTEM_INFO,
    PAGE_WEATHER,
    PAGE_GIF_1,
    PAGE_GIF_2,
    PAGE_GIF_3,
    get_battery_percent,
    get_cpu_percent
)
from minitela_client import MinitelaClient


def daemon_available():
    return MinitelaClient(timeout=1.0).ping().get("ok", False)


def _direct(fn):
    """Fallback path: talk to the device directly when the daemon is absent."""
    with MinitelaDevice() as dev:
        result = fn(dev)
    if isinstance(result, dict):
        return {"ok": True, **result}
    return {"ok": True}

PORT = 8080
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Minitela Control Center</title>
<style>
  :root {
    --bg: #0f172a;
    --card: #1e293b;
    --accent: #38bdf8;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --border: #334155;
  }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 24px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  h1 { margin-bottom: 4px; font-size: 1.8rem; }
  p.subtitle { color: var(--text-muted); margin-top: 0; margin-bottom: 24px; font-size: 0.95rem; }
  .grid {
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: 24px;
    max-width: 900px;
    width: 100%;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  }
  .preview-container {
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .screen-bezel {
    width: 240px;
    height: 240px;
    background: #000;
    border-radius: 50%;
    border: 8px solid #334155;
    box-shadow: inset 0 0 20px rgba(0,0,0,0.8), 0 0 15px rgba(56, 189, 248, 0.2);
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 12px;
    box-sizing: border-box;
  }
  .screen-bezel .title { font-weight: 700; font-size: 1.1rem; color: #38bdf8; margin-bottom: 6px; }
  .screen-bezel .value { font-size: 2.2rem; font-weight: 800; }
  .screen-bezel .desc { font-size: 0.8rem; color: #94a3b8; }
  .control-group { margin-bottom: 20px; }
  .control-group label { display: block; font-weight: 600; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
  .btn-row { display: flex; flex-wrap: wrap; gap: 8px; }
  button {
    background: #334155;
    color: var(--text);
    border: none;
    padding: 10px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 600;
    font-size: 0.9rem;
    transition: all 0.15s ease;
  }
  button:hover { background: #475569; transform: translateY(-1px); }
  button.active { background: #0284c7; color: #fff; }
  button.primary { background: #2563eb; }
  button.primary:hover { background: #1d4ed8; }
  input[type="range"] {
    width: 100%;
    accent-color: var(--accent);
    cursor: pointer;
  }
  input[type="text"] {
    width: 100%;
    padding: 10px;
    background: #0f172a;
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    margin-bottom: 10px;
    box-sizing: border-box;
  }
  .status-badge {
    display: inline-block;
    padding: 4px 8px;
    border-radius: 12px;
    font-size: 0.75rem;
    background: rgba(34, 197, 94, 0.2);
    color: #4ade80;
    margin-top: 8px;
  }
</style>
</head>
<body>

<h1>Minitela Control Center</h1>
<p class="subtitle">Hardware Mini Display (240x240 GC9002 Controller /dev/ttyACM1)</p>

<div class="grid">
  <!-- Left Column: Virtual Screen Preview -->
  <div class="card preview-container">
    <div class="control-group" style="width: 100%; text-align: center;">
      <label>Virtual Display Preview</label>
    </div>
    <div class="screen-bezel" id="screen">
      <div class="title" id="screen-title">STATUS</div>
      <div class="value" id="screen-val">--%</div>
      <div class="desc" id="screen-desc">Battery & CPU</div>
    </div>
    <div class="status-badge" id="port-status">Device Connected</div>
  </div>

  <!-- Right Column: Controls -->
  <div class="card">
    <!-- Brightness -->
    <div class="control-group">
      <label>Backlight Brightness (<span id="bright-val">80</span>%)</label>
      <input type="range" id="brightness" min="0" max="100" value="80" oninput="setBrightness(this.value)">
    </div>

    <!-- Page Switcher -->
    <div class="control-group">
      <label>Switch Display Screen</label>
      <div class="btn-row">
        <button onclick="setPage(3, 'STATUS', 'System Stats', 'Battery / CPU / WiFi')">Status</button>
        <button onclick="setPage(1, 'WHATSAPP', 'No Messages', 'Messages & Alerts')">WhatsApp</button>
        <button onclick="setPage(4, 'WEATHER', '24°C', 'Sunny / Clima')">Weather</button>
        <button onclick="setPage(2, 'REMINDERS', 'Daily Tasks', 'Agenda')">Tasks</button>
        <button onclick="setGif(1)">GIF 1</button>
        <button onclick="setGif(2)">GIF 2</button>
        <button onclick="setGif(3)">GIF 3</button>
      </div>
    </div>

    <!-- WhatsApp Alert Sender -->
    <div class="control-group">
      <label>Send WhatsApp / Alert to Screen</label>
      <input type="text" id="wa-sender" placeholder="Contact name (e.g. Maria, John)" value="WhatsApp">
      <input type="text" id="wa-msg" placeholder="Message content..." value="Meeting at 2:00 PM">
      <button class="primary" onclick="sendWhatsApp()">Push Alert to Mini Display</button>
    </div>

    <!-- Quick Status Sync -->
    <div class="control-group" style="margin-bottom: 0;">
      <button onclick="syncLiveStatus()">Sync Live System Status</button>
    </div>
  </div>
</div>

<script>
function api(endpoint, params = {}) {
  const q = new URLSearchParams(params).toString();
  return fetch('/api/' + endpoint + (q ? '?' + q : ''))
    .then(r => r.json())
    .catch(console.error);
}

function setBrightness(val) {
  document.getElementById('bright-val').innerText = val;
  api('brightness', { val });
}

function setPage(page, title, val, desc) {
  document.getElementById('screen-title').innerText = title;
  document.getElementById('screen-val').innerText = val;
  document.getElementById('screen-desc').innerText = desc;
  api('page', { page });
}

function setGif(slot) {
  document.getElementById('screen-title').innerText = 'ANIMATION';
  document.getElementById('screen-val').innerText = 'GIF ' + slot;
  document.getElementById('screen-desc').innerText = 'Playing slot ' + slot;
  api('gif', { slot });
}

function sendWhatsApp() {
  const sender = document.getElementById('wa-sender').value;
  const msg = document.getElementById('wa-msg').value;
  document.getElementById('screen-title').innerText = 'WHATSAPP';
  document.getElementById('screen-val').innerText = sender;
  document.getElementById('screen-desc').innerText = msg;
  api('whatsapp', { sender, msg });
}

function syncLiveStatus() {
  api('status').then(data => {
    document.getElementById('screen-title').innerText = 'STATUS';
    document.getElementById('screen-val').innerText = data.battery + '%';
    document.getElementById('screen-desc').innerText = 'CPU: ' + data.cpu + '%';
  });
}

// Auto-sync status on start
window.onload = syncLiveStatus;
</script>

</body>
</html>
"""

class MinitelaHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Quiet logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        if path.startswith("/api/"):
            action = path[5:]
            response = {"ok": True}

            try:
                client = MinitelaClient(timeout=3.0)
                via_daemon = client.ping().get("ok", False)

                if action == "brightness":
                    val = int(query.get("val", [80])[0])
                    response = (client.set_brightness(val) if via_daemon
                                else _direct(lambda d: d.set_brightness(val)))
                elif action == "page":
                    page = int(query.get("page", [3])[0])
                    response = (client.set_page(page) if via_daemon
                                else _direct(lambda d: d.set_page(page)))
                elif action == "gif":
                    slot = int(query.get("slot", [1])[0])
                    response = (client.gif(slot) if via_daemon
                                else _direct(lambda d: d.show_gif(slot)))
                elif action == "whatsapp":
                    sender = query.get("sender", ["WhatsApp"])[0]
                    msg = query.get("msg", ["New message"])[0]
                    response = (client.notify(sender, msg) if via_daemon
                                else _direct(lambda d: d.send_whatsapp_notification(sender, msg)))
                elif action == "status":
                    cpu, bat = get_cpu_percent(), get_battery_percent()
                    if via_daemon:
                        response = client.status()
                    else:
                        response = _direct(lambda d: d.update_system_status(
                            cpu_percent=cpu, battery_percent=bat))
                    response["cpu"], response["battery"] = cpu, bat
            except Exception as e:
                response = {"ok": False, "error": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), MinitelaHandler) as httpd:
        print(f"Minitela Web Control Server running at http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run_server()
