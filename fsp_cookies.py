"""
fsp_cookies.py  —  Extract Chrome's live FSP cookies & fetch FSP pages directly.

How it works:
  1. Reads Chrome's encrypted cookie DB (makes a temp copy so Chrome's lock is bypassed)
  2. Decrypts each cookie using Chrome's AES key (stored in Local State, DPAPI-protected)
  3. Passes cf_clearance + other FSP cookies with every request → Cloudflare lets us through
  4. Direct requests.get() with real browser headers → gets real FSP HTML
"""
import os, json, shutil, sqlite3, base64, tempfile, time
import requests, urllib3
from datetime import datetime

urllib3.disable_warnings()

# ── Cookie decryption ─────────────────────────────────────────────────────────
def _get_chrome_aes_key():
    """Decrypt Chrome's AES-256-GCM key using Windows DPAPI."""
    state_path = os.path.join(
        os.environ.get('LOCALAPPDATA', ''),
        'Google', 'Chrome', 'User Data', 'Local State'
    )
    if not os.path.exists(state_path):
        return None
    with open(state_path, 'r', encoding='utf-8') as f:
        local_state = json.load(f)
    enc_key_b64 = local_state['os_crypt']['encrypted_key']
    enc_key     = base64.b64decode(enc_key_b64)[5:]   # strip 'DPAPI' prefix
    import win32crypt
    return win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]


def _decrypt_cookie(encrypted_value, key):
    """Decrypt an AES-256-GCM encrypted Chrome cookie value."""
    if not encrypted_value or len(encrypted_value) < 15:
        return ''
    prefix = encrypted_value[:3]
    if prefix == b'v10' or prefix == b'v11':
        from Crypto.Cipher import AES
        nonce       = encrypted_value[3:15]
        ciphertext  = encrypted_value[15:]
        cipher      = AES.new(key, AES.MODE_GCM, nonce=nonce)
        try:
            return cipher.decrypt(ciphertext)[:-16].decode('utf-8', errors='replace')
        except Exception:
            return ''
    else:
        # Old-style DPAPI encrypted
        try:
            import win32crypt
            return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode('utf-8')
        except Exception:
            return ''


def get_fsp_cookies(browser='chrome'):
    """
    Extract FastPeopleSearch cookies from Chrome.
    Returns dict of {name: value} ready to pass to requests.get(cookies=...).
    """
    # Cookie DB paths for Chrome (and Edge as fallback)
    paths = [
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google',    'Chrome', 'User Data', 'Default', 'Network', 'Cookies'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google',    'Chrome', 'User Data', 'Default', 'Cookies'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Edge',   'User Data', 'Default', 'Network', 'Cookies'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Edge',   'User Data', 'Default', 'Cookies'),
    ]

    db_path = next((p for p in paths if os.path.exists(p)), None)
    if not db_path:
        print("  [cookies] Chrome/Edge cookie DB not found")
        return {}

    # Get AES key
    try:
        key = _get_chrome_aes_key()
    except Exception as e:
        print(f"  [cookies] AES key error: {e}")
        key = None

    # Copy DB to temp location (Chrome keeps file locked)
    tmp = os.path.join(tempfile.gettempdir(), f'fsp_cookies_{int(time.time())}.db')
    try:
        shutil.copy2(db_path, tmp)
    except Exception as e:
        print(f"  [cookies] DB copy error: {e}")
        return {}

    cookies = {}
    try:
        conn = sqlite3.connect(tmp)
        cur  = conn.cursor()
        cur.execute(
            "SELECT name, value, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%fastpeoplesearch%'",
        )
        for name, value, encrypted_value in cur.fetchall():
            if value:
                cookies[name] = value
            elif encrypted_value and key:
                dec = _decrypt_cookie(encrypted_value, key)
                if dec:
                    cookies[name] = dec
        conn.close()
    except Exception as e:
        print(f"  [cookies] SQLite error: {e}")
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    print(f"  [cookies] Extracted {len(cookies)} cookies for FSP: {list(cookies.keys())}")
    return cookies


# ── Direct FSP fetch using browser cookies ────────────────────────────────────
FSP_HEADERS = {
    'User-Agent':       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept':           'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language':  'en-US,en;q=0.9',
    'Accept-Encoding':  'gzip, deflate, br',
    'Connection':       'keep-alive',
    'Referer':          'https://www.fastpeoplesearch.com/',
    'Sec-Fetch-Dest':   'document',
    'Sec-Fetch-Mode':   'navigate',
    'Sec-Fetch-Site':   'same-origin',
    'Upgrade-Insecure-Requests': '1',
}

_fsp_session   = None
_cookies_ts    = 0
COOKIE_TTL_SEC = 3600  # Refresh cookies every hour


def get_fsp_session():
    """Return a requests Session pre-loaded with fresh FSP cookies."""
    global _fsp_session, _cookies_ts
    now = time.time()
    if _fsp_session is None or (now - _cookies_ts) > COOKIE_TTL_SEC:
        _fsp_session = requests.Session()
        _fsp_session.headers.update(FSP_HEADERS)
        _fsp_session.verify = False
        cookies = get_fsp_cookies()
        for name, value in cookies.items():
            _fsp_session.cookies.set(name, value, domain='.fastpeoplesearch.com')
        _cookies_ts = now
    return _fsp_session


def fsp_fetch_direct(url, retries=3):
    """
    Fetch an FSP page using the user's live Chrome cookies.
    Falls back to BD API if cookies aren't present.
    Returns HTML string or None.
    """
    sess = get_fsp_session()
    for attempt in range(retries):
        try:
            r = sess.get(url, timeout=30, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 1000:
                # Check it's not a block page
                low = r.text[:500].lower()
                if 'been blocked' in low or 'security challenge' in low:
                    print(f"  [direct] Attempt {attempt+1}: blocked page returned")
                    time.sleep(5)
                    continue
                print(f"  [direct] OK: {len(r.text):,} bytes from {url[-50:]}")
                return r.text
            else:
                print(f"  [direct] Attempt {attempt+1}: HTTP {r.status_code}, {len(r.text)} bytes")
        except Exception as e:
            print(f"  [direct] Attempt {attempt+1} error: {e}")
        time.sleep(3 * (attempt + 1))
    return None


if __name__ == '__main__':
    # Quick test
    print("Testing FSP cookie extraction + direct fetch...")
    cookies = get_fsp_cookies()
    print(f"Cookies: {cookies}")

    if 'cf_clearance' in cookies:
        print("\ncf_clearance found! Testing direct fetch...")
        html = fsp_fetch_direct('https://www.fastpeoplesearch.com/name/michelle-hegedis_oh/')
        if html:
            print(f"SUCCESS: got {len(html):,} bytes")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            # Try to find a result card
            cards = soup.find_all('div', class_='card')
            print(f"Found {len(cards)} cards on page")
        else:
            print("FAILED: no HTML returned")
    else:
        print("\nNOTE: No cf_clearance cookie found.")
        print("Please open https://www.fastpeoplesearch.com in Chrome first,")
        print("browse any page, then re-run this script.")
