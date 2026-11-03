"""
LeadsOSINT Server Launcher with Cloudflare Tunnel
- Starts Flask app on port 5050
- Starts cloudflared tunnel pointing to localhost:5050
- Reads tunnel URL from cloudflared output and saves to tunnel_url.txt
- Runs until Ctrl+C or window close
- Lid close is fine — only shutdown stops it
"""
import subprocess
import sys
import os
import time
import re
import signal
import threading

FLASK_APP   = r'C:\Users\JUDE\LeadsOSINT\app.py'
CLOUDFLARED = r'C:\Users\JUDE\cloudflared.exe'
PORT        = 5050
URL_FILE    = r'C:\Users\JUDE\LeadsOSINT\tunnel_url.txt'

flask_proc  = None
tunnel_proc = None

def kill_all():
    global flask_proc, tunnel_proc
    for p in [flask_proc, tunnel_proc]:
        if p:
            try: p.terminate()
            except: pass

def signal_handler(sig, frame):
    print('\n\nShutting down...')
    kill_all()
    sys.exit(0)

signal.signal(signal.SIGINT,  signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

print('=' * 60)
print('  LeadsOSINT  —  Local Server + Cloudflare Tunnel')
print('=' * 60)

# Kill anything on TCP port 5050
os.system('for /f "tokens=5" %a in (\'netstat -aon ^| findstr ":5050 "\') do taskkill /F /PID %a >nul 2>&1')
time.sleep(1)

# ── 1. Start Flask ──────────────────────────────────────────
print('\n[1/2] Starting Flask on port 5050...')
flask_proc = subprocess.Popen(
    [sys.executable, FLASK_APP],
    cwd=r'C:\Users\JUDE\LeadsOSINT',
    creationflags=subprocess.CREATE_NO_WINDOW
)
time.sleep(4)
print(f'      Flask PID: {flask_proc.pid}')

# ── 2. Start cloudflared ────────────────────────────────────
print('\n[2/2] Starting Cloudflare Tunnel...')
tunnel_proc = subprocess.Popen(
    [CLOUDFLARED, 'tunnel', '--url', f'http://localhost:{PORT}', '--no-autoupdate'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

tunnel_url = None
print('      Waiting for tunnel URL (up to 60s)...')
start = time.time()
for line in tunnel_proc.stdout:
    line = line.strip()
    m = re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', line)
    if m:
        tunnel_url = m.group(0)
        break
    if 'error' in line.lower() and 'failed' in line.lower():
        print(f'      Tunnel error: {line}')
        break
    if time.time() - start > 60:
        print('      Timeout waiting for tunnel URL')
        break

if tunnel_url:
    # Save URL to file
    with open(URL_FILE, 'w') as f:
        f.write(tunnel_url)
    print(f'\n{"=" * 60}')
    print(f'  ✅ LeadsOSINT is LIVE!')
    print(f'  🌐 Public URL : {tunnel_url}')
    print(f'  🏠 Local URL  : http://localhost:{PORT}')
    print(f'  📄 URL saved  : tunnel_url.txt')
    print(f'{"=" * 60}')
    print(f'\n  Closing the lid is fine — server stays on.')
    print(f'  Only shutdown/sleep stops it.')
    print(f'  Press Ctrl+C to stop.\n')
else:
    print('\n  ⚠️  Could not get tunnel URL. Check cloudflared.exe exists and internet is on.')

# ── Keep running, restart Flask if it crashes ───────────────
# Keep reading cloudflared stdout in background
def drain_tunnel():
    if tunnel_proc and tunnel_proc.stdout:
        for _ in tunnel_proc.stdout:
            pass

threading.Thread(target=drain_tunnel, daemon=True).start()

try:
    while True:
        if flask_proc.poll() is not None:
            print('\n[!] Flask crashed — restarting...')
            flask_proc = subprocess.Popen(
                [sys.executable, FLASK_APP],
                cwd=r'C:\Users\JUDE\LeadsOSINT',
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print(f'    Flask restarted (PID {flask_proc.pid})')
        time.sleep(5)
except KeyboardInterrupt:
    signal_handler(None, None)
