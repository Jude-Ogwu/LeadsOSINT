"""
Helper: starts cloudflared, captures the trycloudflare.com URL, writes it to tunnel_url.txt
Run this AFTER Flask is already running on port 5050.
"""
import subprocess, re, time, sys, os

CLOUDFLARED = r'C:\Users\JUDE\cloudflared.exe'
OUT_FILE    = r'C:\Users\JUDE\LeadsOSINT\tunnel_url.txt'
PORT        = 5050

print("[cloudflared] Starting Cloudflare Tunnel...")
proc = subprocess.Popen(
    [CLOUDFLARED, 'tunnel', '--url', f'http://localhost:{PORT}', '--no-autoupdate'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

tunnel_url = None
start = time.time()
for line in proc.stdout:
    line = line.strip()
    print(f"  cf> {line}")
    m = re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', line)
    if m:
        tunnel_url = m.group(0)
        break
    if time.time() - start > 45:
        print("[cloudflared] Timed out waiting for URL")
        break

if tunnel_url:
    with open(OUT_FILE, 'w') as f:
        f.write(tunnel_url)
    print(f"\n{'='*55}")
    print(f"  TUNNEL URL: {tunnel_url}")
    print(f"{'='*55}\n")
    sys.stdout.flush()
    # Keep proc alive
    proc.wait()
else:
    print("[cloudflared] Failed to get tunnel URL")
    proc.terminate()
    sys.exit(1)
