"""
LeadsOSINT v2 — Bulk People Search
Web UI : http://localhost:5050
CLI    : python app.py --bulk leads.csv
         python app.py --name "John Smith" --location TX
"""
import sys, os, re, json, csv, time, uuid, threading, io, webbrowser, argparse, html
from functools import wraps
import requests, urllib3
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template, render_template_string, abort, redirect, make_response
from PIL import Image, ImageDraw, ImageFont
import database
from location_normalizer import normalize_location
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
urllib3.disable_warnings()

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

def get_current_user():
    token = request.cookies.get('leads_session') or request.headers.get('X-Session-Token')
    if not token and request.headers.get('Authorization'):
        auth_hdr = request.headers.get('Authorization')
        if auth_hdr.startswith('Bearer '):
            token = auth_hdr.split(' ')[1]
    if not token:
        return None
    sess = database.get_session(token)
    if not sess:
        return None
    user = database.get_user_by_id(sess['user_id'])
    return user

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required. Please login.'}), 401
            return redirect('/login')
        if user['status'] != 'active' and user['role'] != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': f"Your account is {user['status']}. Contact administrator."}), 403
            return redirect('/login')
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['role'] != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Administrator privileges required.'}), 403
            return redirect('/login')
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

@app.before_request
def handle_options_preflight():
    if request.method == "OPTIONS":
        res = app.make_default_options_response()
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return res

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    if request.path.endswith('.html') or request.path.startswith('/results') or request.path.startswith('/reports') or request.path.startswith('/api/'):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# -- Scraper Engine Configuration ---------------------------------------------
# Engine: Bright Data Web Unlocker (only proven provider for FPS/FBC)
# Set BD_API_KEY env var on PythonAnywhere or paste key directly below
SCRAPER_PROVIDER = "brightdata"

# -- Bright Data Credentials --------------------
BD_API_KEY = os.environ.get("BD_API_KEY", "74c1d9bb-e468-4005-af28-46368cf62554").strip()
BD_ZONE    = "web_unlocker1"
OUT_DIR    = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
os.makedirs(OUT_DIR, exist_ok=True)
JOBS_FILE  = os.path.join(OUT_DIR, "jobs_registry.json")
PORT       = int(os.environ.get("PORT", 5050))

jobs      = {}
jobs_lock = threading.Lock()

# -- Live System Logging Buffer ------------------------------------------------
import collections
LOG_BUFFER = collections.deque(maxlen=500)
LOG_LOCK   = threading.Lock()

def log_event(msg, level="INFO"):
    """Thread-safe logging to in-memory log buffer and stdout."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    print(formatted)
    with LOG_LOCK:
        LOG_BUFFER.append({
            "timestamp": timestamp,
            "level": level,
            "message": str(msg),
            "raw": formatted
        })

STATES = {
    'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR',
    'california':'CA','colorado':'CO','connecticut':'CT','delaware':'DE',
    'florida':'FL','georgia':'GA','hawaii':'HI','idaho':'ID',
    'illinois':'IL','indiana':'IN','iowa':'IA','kansas':'KS',
    'kentucky':'KY','louisiana':'LA','maine':'ME','maryland':'MD',
    'massachusetts':'MA','michigan':'MI','minnesota':'MN','mississippi':'MS',
    'missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV',
    'new hampshire':'NH','new jersey':'NJ','new mexico':'NM','new york':'NY',
    'north carolina':'NC','north dakota':'ND','ohio':'OH','oklahoma':'OK',
    'oregon':'OR','pennsylvania':'PA','rhode island':'RI','south carolina':'SC',
    'south dakota':'SD','tennessee':'TN','texas':'TX','utah':'UT',
    'vermont':'VT','virginia':'VA','washington':'WA','west virginia':'WV',
    'wisconsin':'WI','wyoming':'WY','dc':'DC','nyc':'NY','la':'CA',
}

def extract_state(loc):
    if not loc: return ''
    loc = loc.strip()
    if re.match(r'^[A-Za-z]{2}$', loc): return loc.upper()
    words = loc.split()
    if words and re.match(r'^[A-Za-z]{2}$', words[-1]): return words[-1].upper()
    if ',' in loc:
        part = loc.split(',')[-1].strip()
        if re.match(r'^[A-Za-z]{2}$', part): return part.upper()
    for name, code in STATES.items():
        if name in loc.lower(): return code
    return ''

def safe_name(name, location=''):
    base = f"{name}_{location}" if location else name
    return re.sub(r'[^\w]', '_', base)[:50]

def clean(s):
    return re.sub(r'\s+', ' ', str(s)).strip() if s else ''

# -- HTTP Session with Connection Pooling (Massive Speed Enhancement) ---------
# BD_SESSION: direct connections to api.brightdata.com, no env proxy (avoids PA proxy 403)
BD_SESSION = requests.Session()
BD_SESSION.trust_env = False
bd_adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
BD_SESSION.mount('http://', bd_adapter)
BD_SESSION.mount('https://', bd_adapter)

# HTTP_SESSION: general web scraping session — uses env proxy if set (PA proxy allows FPS/FBC/ThatsThem)
HTTP_SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
HTTP_SESSION.mount('http://', adapter)
HTTP_SESSION.mount('https://', adapter)

def is_rejected_scrape_body(body):
    """Detect if response is a rate limit, captcha challenge, or blocked proxy."""
    if not body or len(body) < 1500:
        return True
    bl = body.lower()
    
    # If the response contains authentic FastPeopleSearch content, it is valid!
    if ('class="card' in bl or 'class=\'card' in bl or 'class="record' in bl or 'class=\'record' in bl or 'thatsthem' in bl or 'detail-box' in bl or 'person-details' in bl or 'class="people-list' in bl or 'page-list has-ads' in bl):
        return False
        
    bad_tokens = [
        'rate limit exceeded', 'rate-limit', 'too many requests',
        'page-manage-challenge', 'been blocked', 'access denied',
        'verify you are human', 'cf-challenge', 'cf-turnstile', 'just a moment...',
        'attention required', '429 too many', 'shieldsquare',
        'security check', 'unusual traffic', 'robot or human',
        'solve the captcha', 'please solve the challenge'
    ]
    return any(t in bl for t in bad_tokens)

# -- Unified Scraping Fetch Dispatcher -----------------------------------------
def bd_fetch(url, retries=4):
    """Fetch page via Bright Data Web Unlocker (primary + only engine)."""
    if 'fastbackgroundcheck' in url.lower():
        retries = 1
    for attempt in range(retries):
        try:
            r = BD_SESSION.post(
                "https://api.brightdata.com/request",
                json={"zone": BD_ZONE, "url": url, "format": "raw", "country": "us"},
                headers={"Authorization": f"Bearer {BD_API_KEY}", "Content-Type": "application/json"},
                verify=False, timeout=55
            )
            brd_err = r.headers.get('x-brd-err-msg') or r.headers.get('x-brd-error')
            if brd_err:
                log_event(f"❌ Bright Data Error: {brd_err}", "ERROR")
            body = r.text
            is_valid_fsp = ('<div class="card"' in body or 'class="card"' in body or 'fastpeoplesearch' in body.lower())
            is_valid_fbc = ('fastbackgroundcheck' in url.lower() and ('fastbackgroundcheck' in body.lower() or 'people' in body.lower() or len(body) > 2000))
            if (r.status_code == 200
                    and not is_rejected_scrape_body(body)
                    and (is_valid_fsp or is_valid_fbc or ('thatsthem' in url.lower() and len(body) > 1500))):
                log_event(f"[BrightData] Search page OK: {len(body):,} bytes")
                return body
            else:
                log_event(f"[BrightData] Search attempt {attempt+1}: HTTP {r.status_code}, len={len(body)} - rotating...", "WARN")
        except Exception as e:
            log_event(f"[BrightData] Search attempt {attempt+1} error: {e}", "WARN")
        time.sleep(1.5)
    return None


def bd_fetch_profile(url, retries=5):
    """Fetch profile detail page via Bright Data Web Unlocker.
    Uses exponential backoff; sleeps longer on bot-check / robots.txt hits."""
    for attempt in range(retries):
        try:
            r = BD_SESSION.post(
                "https://api.brightdata.com/request",
                json={"zone": BD_ZONE, "url": url, "format": "raw", "country": "us"},
                headers={"Authorization": f"Bearer {BD_API_KEY}", "Content-Type": "application/json"},
                verify=False, timeout=55
            )
            brd_err = r.headers.get('x-brd-err-msg') or r.headers.get('x-brd-error')
            if brd_err:
                log_event(f"❌ Bright Data Error: {brd_err}", "ERROR")
                # Bot-check / robots.txt: longer backoff to let BD rotate IPs
                bot_hit = any(k in brd_err.lower() for k in ('robot', 'bot-check', 'challenge', 'forbidden', 'restricted'))
                delay = (8 * (attempt + 1)) if bot_hit else (2 ** attempt * 1.5)
                log_event(f"[BrightData] Backing off {delay:.0f}s before retry {attempt+2}...", "WARN")
                time.sleep(delay)
                continue
            body = r.text
            if (r.status_code == 200
                    and not is_rejected_scrape_body(body)
                    and len(body) > 5000
                    and ('current address' in body.lower() or 'addresses' in body.lower() or 'phone' in body.lower() or 'detail-box' in body.lower() or 'person-details' in body.lower() or 'background report' in body.lower())):
                log_event(f"[BrightData] Profile fetch OK: {len(body):,} bytes")
                return body
            else:
                log_event(f"[BrightData] Profile attempt {attempt+1}: HTTP {r.status_code}, len={len(body)} - rotating...", "WARN")
        except Exception as e:
            log_event(f"[BrightData] Profile attempt {attempt+1} error: {e}", "WARN")
        time.sleep(2 ** attempt * 1.5)  # exponential backoff: 1.5s, 3s, 6s, 12s, 24s
    return None



def search_ddg(name, location):
    """
    Search DuckDuckGo for a person on FastPeopleSearch.
    Returns result dict or None. Works without any proxy.
    """
    state  = extract_state(location)
    query  = f'{name} {state} site:fastpeoplesearch.com'
    ddg_url = 'https://html.duckduckgo.com/html/'
    hdrs = {
        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept':          'text/html,application/xhtml+xml,*/*;q=0.9',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer':         'https://duckduckgo.com/',
    }
    try:
        r = requests.post(ddg_url,
                          data={'q': query, 'b': '', 'kl': 'us-en'},
                          headers=hdrs, timeout=20, verify=False)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        name_lower = name.lower()
        name_parts = name_lower.split()

        for result in soup.find_all('div', class_='result__body'):
            title_el = result.find('a', class_='result__a')
            snip_el  = result.find('a', class_='result__snippet')
            if not title_el:
                continue
            href    = title_el.get('href', '')
            snippet = snip_el.get_text(' ', strip=True) if snip_el else title_el.get_text(' ', strip=True)
            combined = (href + ' ' + snippet).lower()

            if 'fastpeoplesearch' not in combined:
                continue
            if not any(p in combined for p in name_parts[:2]):
                continue

            age  = 'N/A'
            city = location
            age_m  = re.search(r'[Aa]ge\s+(\d{1,3})', snippet)
            city_m = re.search(r'([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*),\s+([A-Z]{2})\b', snippet)
            if age_m:  age  = age_m.group(1)
            if city_m: city = f"{city_m.group(1)}, {city_m.group(2)}"

            # Best-effort profile URL from href
            purl = href if 'fastpeoplesearch.com' in href else ''
            if not purl:
                slug  = re.sub(r"[^a-z-]", '', name.lower().replace(' ', '-'))
                purl  = f"https://www.fastpeoplesearch.com/name/{slug}_{state.lower()}/"

            print(f"  DDG found: {name} | age={age} | city={city}")
            return {
                'name':        name,
                'age':         age,
                'city':        city,
                'address':     city,
                'addresses':   [city],
                'phones':      [],
                'emails':      [],
                'profile_url': purl,
                'source':      'duckduckgo',
                'status':      'found',
            }
    except Exception as e:
        print(f"  DDG search error: {e}")
    return None


# -- FSP Parser — robust age/city extraction ----------------------------------
def parse_fsp(html):
    soup    = BeautifulSoup(html, 'html.parser')
    results = []

    for card in soup.find_all('div', class_='card'):
        profile_path = card.get('data-link', '')
        if not profile_path:
            continue

        # Name
        name_span = card.find('span', class_='larger')
        name = clean(name_span.get_text()) if name_span else ''
        if not name:
            continue

        # -- Age & City: multiple fallback strategies ------------------
        age, city = 'N/A', 'N/A'

        # Strategy 1: look for any span/element containing "Age"
        card_raw = str(card)
        age_m = re.search(r'Age\s+(\d{1,3})', card_raw, re.I)
        if age_m:
            age = age_m.group(1)

        # Strategy 2: find city,state pattern in grey span or card text
        grey = (card.find('span', class_='grey') or
                card.find('span', class_='text-muted') or
                card.find('span', class_='subdued'))

        search_text = grey.get_text(separator=' ', strip=True) if grey else card_raw

        # Pattern: "Word Word, ST" — handles multi-word city names and all-caps
        city_m = re.search(
            r'\b([A-Za-z][A-Za-z\s]{1,30}?),\s+([A-Z]{2})\b',
            search_text
        )
        if city_m:
            city_candidate = city_m.group(1).strip()
            state_candidate = city_m.group(2)
            # Reject if looks like a name or long phrase
            if len(city_candidate.split()) <= 4 and state_candidate in STATES.values():
                city = f"{city_candidate}, {state_candidate}"

        # Strategy 3: fallback to address href for city/state
        if city == 'N/A':
            addr_a = card.find('a', href=re.compile(r'^/address/'))
            if addr_a:
                href = addr_a['href'].replace('/address/', '')
                parts = href.split('_')
                if len(parts) > 1:
                    loc = parts[1]
                    loc = re.sub(r'-\d{5}.*$', '', loc)   # remove zip
                    loc_parts = loc.rsplit('-', 1)
                    if len(loc_parts) == 2 and len(loc_parts[1]) == 2:
                        city = f"{loc_parts[0].replace('-', ' ').title()}, {loc_parts[1].upper()}"

        # -- Addresses -------------------------------------------------
        addrs = []
        for a in card.find_all('a', href=re.compile(r'^/address/')):
            href  = a['href'].replace('/address/', '')
            parts = href.split('_')
            st    = parts[0].replace('-', ' ').title() if parts else ''
            lc    = ''
            if len(parts) > 1:
                raw_lc = parts[1]
                raw_lc = re.sub(r'-\d{5}.*$', '', raw_lc)
                lc_p   = raw_lc.rsplit('-', 1)
                if len(lc_p) == 2 and len(lc_p[1]) == 2:
                    lc = f"{lc_p[0].replace('-',' ').title()}, {lc_p[1].upper()}"
                else:
                    lc = raw_lc.replace('-', ' ').upper()
            addrs.append(f"{st} · {lc}" if lc else st)

        # -- Relatives ----------------------------------------------
        relatives = []
        card_str  = str(card)
        rel_m = re.search(r'Relatives?[:\s]+(.*?)(?:AKA|View Free|$)', card_str, re.I | re.S)
        if rel_m:
            from bs4 import BeautifulSoup as _BS
            rel_text = _BS(rel_m.group(1), 'html.parser').get_text(' ', strip=True)
            relatives = [r.strip() for r in re.split(r'[•|]', rel_text) if r.strip()][:6]

        # -- AKA / Aliases ------------------------------------------
        aliases = []
        aka_m = re.search(r'AKA[:\s]+(.*?)(?:</div>|View Free|$)', card_str, re.I | re.S)
        if aka_m:
            from bs4 import BeautifulSoup as _BS
            aka_text = _BS(aka_m.group(1), 'html.parser').get_text(' ', strip=True)
            aliases = [a.strip() for a in re.split(r'[•|]', aka_text) if a.strip()][:4]

        results.append({
            'name':        name,
            'age':         age,
            'city':        city,
            'address':     addrs[0] if addrs else 'N/A',
            'addresses':   addrs[:6],
            'relatives':   relatives,
            'aliases':     aliases,
            'phones':      [],
            'emails':      [],
            'profile_url': f"https://www.fastpeoplesearch.com{profile_path}",
            'source':      'bd',
        })

    return results

# -- Name Relevance Matching ---------------------------------------------------
NICKNAMES = {
    'james': {'jas', 'jim', 'jimmy', 'jamie'},
    'william': {'wm', 'bill', 'billy', 'will', 'willy', 'liam'},
    'robert': {'rob', 'bob', 'bobby', 'robbie'},
    'richard': {'dick', 'rick', 'rich', 'ricky'},
    'charles': {'chas', 'charlie', 'chuck'},
    'thomas': {'thos', 'tom', 'tommy'},
    'edward': {'edw', 'ed', 'eddie', 'ted', 'teddy'},
    'george': {'geo'},
    'john': {'jack', 'johnny'},
    'joseph': {'joe', 'joey'},
    'alexander': {'alex', 'al', 'alec'},
    'benjamin': {'ben', 'benny'},
    'daniel': {'dan', 'danny'},
    'david': {'dave', 'davey'},
    'michael': {'mike', 'mikey'},
    'matthew': {'matt'},
    'christopher': {'chris'},
    'anthony': {'tony'},
    'francis': {'frank', 'frankie'},
    'frank': {'frankie'},
}

def first_name_matches(n1, n2):
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    if len(n1) == 1 and n2.startswith(n1):
        return True
    if len(n2) == 1 and n1.startswith(n2):
        return True
    if len(n1) > 2 and len(n2) > 2 and (n1.startswith(n2) or n2.startswith(n1)):
        return True
    for canon, nicks in NICKNAMES.items():
        all_variants = {canon} | nicks
        if n1 in all_variants and n2 in all_variants:
            return True
    return False

def is_relevant_name_match(query, candidate_name, candidate_aliases=None):
    """
    Strict validation to ensure search results actually match the queried person.
    Prevents spurious phonetic/similar matches (e.g. 'Frank Jaco' for 'Jas Frankie').
    """
    if not query or not candidate_name:
        return False
    
    q_clean = re.sub(r'[^a-zA-Z\s]', '', query).lower().strip()
    c_clean = re.sub(r'[^a-zA-Z\s]', '', candidate_name).lower().strip()
    
    q_tokens = q_clean.split()
    c_tokens = c_clean.split()
    if not q_tokens or not c_tokens:
        return False
        
    q_first = q_tokens[0]
    q_last = q_tokens[-1]
    
    # Single token query (e.g. mononym)
    if len(q_tokens) == 1:
        return any(q_first == t for t in c_tokens)
        
    all_candidates = [c_clean]
    if candidate_aliases:
        for a in candidate_aliases:
            a_clean = re.sub(r'[^a-zA-Z\s]', '', str(a)).lower().strip()
            if a_clean:
                all_candidates.append(a_clean)
                
    for cand in all_candidates:
        tokens = cand.split()
        if not tokens:
            continue
        first = tokens[0]
        last = tokens[-1]
        
        last_match = (
            q_last == last or
            (len(q_last) > 3 and len(last) > 3 and (q_last in last or last in q_last))
        )
        first_match = first_name_matches(q_first, first)
        
        if last_match and first_match:
            return True
            
        # Reversed format: 'Frankie, Jas'
        if len(tokens) >= 2:
            if first_name_matches(q_first, last) and (q_last == first or (len(q_last) > 3 and q_last in first)):
                return True
                
    return False


def search_fastbackgroundcheck(query, location='', mode='name'):
    """
    FastBackgroundCheck.com Fallback Engine.
    Supports all 4 search modes: 'name', 'phone', 'address', and 'email'.
    Triggered when FastPeopleSearch yields 0 records or fails.
    """
    try:
        from bs4 import BeautifulSoup
        if mode == 'phone':
            clean_p = re.sub(r'[^\d]', '', str(query))
            fmt_p = f"{clean_p[:3]}-{clean_p[3:6]}-{clean_p[6:]}" if len(clean_p) == 10 else clean_p
            url = f"https://www.fastbackgroundcheck.com/{fmt_p}"
            log_event(f"🌐 [FastBackgroundCheck Engine] Querying Phone fallback: {url}")
        elif mode == 'address':
            addr_clean = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '-')
            loc_clean = re.sub(r'[^\w\s-]', '', location).strip().replace(' ', '-')
            slug = f"{addr_clean.lower()}/{loc_clean.lower()}" if loc_clean else addr_clean.lower()
            url = f"https://www.fastbackgroundcheck.com/address/{slug}"
            log_event(f"🌐 [FastBackgroundCheck Engine] Querying Address fallback: {url}")
        elif mode == 'email':
            clean_email = str(query).strip().lower()
            url = f"https://www.fastbackgroundcheck.com/email/{clean_email}"
            log_event(f"🌐 [FastBackgroundCheck Engine] Querying Email fallback: {url}")
        else:
            parts = re.sub(r"[^a-zA-Z\s'-]", '', query).strip().split()
            if len(parts) < 2:
                return []
            slug = f"{parts[0].lower()}-{parts[-1].lower()}"
            clean_loc, loc_slug = normalize_location(location)
            if loc_slug:
                fbc_loc = loc_slug.replace('_', '-')
                url = f"https://www.fastbackgroundcheck.com/people/{slug}/{fbc_loc}"
            else:
                url = f"https://www.fastbackgroundcheck.com/people/{slug}"
            log_event(f"🌐 [FastBackgroundCheck Engine] Querying Name fallback: {url}")

        html = bd_fetch(url)
        if not html:
            try:
                r_direct = HTTP_SESSION.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9'
                }, timeout=25)
                if r_direct.status_code == 200 and len(r_direct.text) > 1500 and not is_rejected_scrape_body(r_direct.text):
                    html = r_direct.text
                    log_event(f"🌐 [FastBackgroundCheck Engine] Direct fetch succeeded: {len(html):,} bytes")
            except Exception as de:
                log_event(f"🌐 [FastBackgroundCheck Engine] Direct fetch attempt error: {de}", "WARN")
        if html:
            _THREAD_SEARCH_HTML[threading.get_ident()] = html
        else:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.select('.person-card, .card, div[class*="person"]')
        results = []
        for card in cards:
            name_el = card.select_one('h2, .name, a[href*="/people/"]')
            if not name_el:
                continue
            c_name = name_el.get_text(strip=True)
            if mode == 'name' and not is_relevant_name_match(query, c_name):
                continue
            age_el = card.select_one('.age, span[class*="age"]')
            age_txt = age_el.get_text(strip=True).replace('Age', '').replace(':', '').strip() if age_el else 'N/A'
            loc_el = card.select_one('.location, .city, span[class*="city"]')
            loc_txt = loc_el.get_text(strip=True) if loc_el else (location or 'N/A')

            addrs = []
            for a_el in card.select('.address, span[class*="address"]'):
                txt = a_el.get_text(strip=True)
                if txt and txt not in addrs:
                    addrs.append(txt)

            phones = []
            for p_el in card.select('.phone, a[href^="tel:"], span[class*="phone"]'):
                txt = re.sub(r'[^\d()-.\s]', '', p_el.get_text(strip=True)).strip()
                if txt and txt not in phones:
                    phones.append(txt)

            rels = []
            for r_el in card.select('.relatives a, .relative, a[href*="/people/"]'):
                txt = r_el.get_text(strip=True)
                if txt and txt != c_name and txt not in rels and len(txt) > 2:
                    rels.append(txt)

            link_el = card.select_one('a[href*="/people/"]')
            purl = link_el['href'] if link_el and 'href' in link_el.attrs else url
            if purl and not purl.startswith('http'):
                purl = 'https://www.fastbackgroundcheck.com' + purl

            res_obj = {
                'name': c_name,
                'age': age_txt,
                'city': loc_txt,
                'address': addrs[0] if addrs else 'N/A',
                'addresses': addrs,
                'phones': phones,
                'emails': [query] if mode == 'email' else [],
                'relatives': rels[:6],
                'aliases': [],
                'profile_url': purl,
                '_search_html': html
            }
            results.append(res_obj)
        return results
    except Exception as e:
        log_event(f"FastBackgroundCheck parse warning: {e}", "WARN")
        return []


def search_thatsthem(email):
    """
    Dedicated reverse email search engine via That's Them (fully unlocked via Bright Data).
    Returns verified public profiles tied to the queried email.
    """
    clean_email = str(email).strip().lower()
    url = f"https://thatsthem.com/email/{clean_email}"
    log_event(f"📧 [That's Them Engine] Querying Email: {url}")
    html = bd_fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    records = soup.select('.record')
    results = []
    for card in records:
        name_el = card.select_one('h2')
        if not name_el:
            continue
        c_name = name_el.get_text(' ', strip=True)
        card_text = card.get_text('\n', strip=True)

        loc_m = re.search(r'Lives in\s+([^\n\r]+)', card_text)
        location = loc_m.group(1).strip() if loc_m else 'N/A'

        age_m = re.search(r'\((\d{1,3})\s+years old\)', card_text)
        age = age_m.group(1).strip() if age_m else 'N/A'

        addrs = []
        addr_match = re.search(r'Current Address:\s*([^\n\r]+(?:\n[^\n\r]+)?)', card_text)
        if addr_match:
            clean_addr = ' '.join(addr_match.group(1).split())
            clean_addr = re.sub(r'Uncover.*$', '', clean_addr, flags=re.I).strip()
            if clean_addr:
                addrs.append(clean_addr)
        if not addrs and location != 'N/A':
            addrs = [location]

        phones = []
        found_p = re.findall(r'\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}', card_text)
        for p in found_p:
            if p not in phones:
                phones.append(p)

        results.append({
            'name': c_name,
            'age': age,
            'city': location,
            'address': addrs[0] if addrs else 'N/A',
            'addresses': addrs,
            'phones': phones,
            'emails': [clean_email],
            'relatives': [],
            'aliases': [],
            'profile_url': url,
            '_search_html': html,
            'source': 'thatsthem'
        })
    return results

def search_person(name, location='', phone=''):
    """
    Universal Search Dispatcher:
    Supports 4 input modes: Name, Phone Number, Address, or Email.
    Primary Engine: FastPeopleSearch (FPS) + Secondary Engine: TruePeopleSearch (TPS) fallback.
    """
    lead_item = classify_input_lead(f"{name}, {location}" if location else name)
    mode     = lead_item['search_mode'] if lead_item else 'name'
    query    = lead_item['query'] if lead_item else name
    loc      = lead_item['location'] if lead_item else location
    state    = extract_state(loc)

    if mode == 'phone':
        clean_p = re.sub(r'[^\d]', '', str(query))
        fmt_p   = f"{clean_p[:3]}-{clean_p[3:6]}-{clean_p[6:]}" if len(clean_p) == 10 else clean_p
        url     = f"https://www.fastpeoplesearch.com/{fmt_p}"
        log_event(f"📱 [Phone Search Mode] Fetching: {url}")
        html    = bd_fetch(url)
        if html:
            _THREAD_SEARCH_HTML[threading.get_ident()] = html
            results = parse_fsp(html)
            for r in results: r['_search_html'] = html
            return results  # Return FPS results (even if 0, because FPS answered successfully)
        # FastBackgroundCheck emergency fallback ONLY if FPS misbehaved/failed to fetch
        log_event(f"⚠️ [Emergency Fallback] FPS failed/misbehaved for phone {fmt_p} — engaging FastBackgroundCheck")
        fbc_res = search_fastbackgroundcheck(fmt_p, mode='phone')
        if fbc_res:
            log_event(f"✅ FastBackgroundCheck found {len(fbc_res)} record(s) for phone: {fmt_p}")
            return fbc_res

    elif mode == 'address':
        addr_clean = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '-')
        loc_clean  = re.sub(r'[^\w\s-]', '', loc).strip().replace(' ', '-')
        slug       = f"{addr_clean.lower()}_{loc_clean.lower()}" if loc_clean else addr_clean.lower()
        url        = f"https://www.fastpeoplesearch.com/address/{slug}"
        log_event(f"🏠 [Address Search Mode] Fetching: {url}")
        html       = bd_fetch(url)
        if html:
            _THREAD_SEARCH_HTML[threading.get_ident()] = html
            results = parse_fsp(html)
            for r in results: r['_search_html'] = html
            return results  # Return FPS results (even if 0, because FPS answered successfully)
        # FastBackgroundCheck emergency fallback ONLY if FPS misbehaved/failed to fetch
        log_event(f"⚠️ [Emergency Fallback] FPS failed/misbehaved for address {query} — engaging FastBackgroundCheck")
        fbc_res = search_fastbackgroundcheck(query, location=loc, mode='address')
        if fbc_res:
            log_event(f"✅ FastBackgroundCheck found {len(fbc_res)} record(s) for address: {query}")
            return fbc_res

    elif mode == 'email':
        clean_email = str(query).strip().lower()
        log_event(f"✉️ [Email Search Mode] Reverse Lookup for: {clean_email}")
        
        # Primary Engine for Email: That's Them (verified reverse email lookup)
        tt_results = search_thatsthem(clean_email)
        if tt_results:
            log_event(f"✅ That's Them found {len(tt_results)} record(s) for email: {clean_email}")
            return tt_results

        # Secondary Engine: FastBackgroundCheck
        fbc_email_results = search_fastbackgroundcheck(clean_email, mode='email')
        if fbc_email_results:
            log_event(f"✅ FastBackgroundCheck found {len(fbc_email_results)} record(s) for email: {clean_email}")
            return fbc_email_results

        # Clean 0-result return: never synthesize or associate random individuals with this email
        log_event(f"⚠️ No matching public records found for email: {clean_email}", "WARN")
        return []

    # Name Search Mode
    parts = re.sub(r"[^a-zA-Z\s'-]", '', query).strip().split()
    if len(parts) >= 2:
        slug     = f"{parts[0].lower()}-{parts[-1].lower()}"
        clean_loc, loc_slug = normalize_location(loc)
        url      = (f"https://www.fastpeoplesearch.com/name/{slug}_{loc_slug}"
                    if loc_slug else
                    f"https://www.fastpeoplesearch.com/name/{slug}/")
        if loc and clean_loc != loc:
            log_event(f"📍 Location normalized: '{loc}' -> '{clean_loc}' (slug: {loc_slug})")
        log_event(f"👤 [Name Search Mode] Fetching: {url}")
        html = bd_fetch(url)
        if html:
            _THREAD_SEARCH_HTML[threading.get_ident()] = html
        results = parse_fsp(html) if html else []
        if results:
            for r in results: r['_search_html'] = html
            return results

        # Fallback to Name-Only nationwide search if location-specific search yielded 0 results
        if loc_slug:
            fallback_url = f"https://www.fastpeoplesearch.com/name/{slug}/"
            log_event(f"🔄 [Fallback Search] No records for '{loc}'. Searching nationwide: {fallback_url}")
            fb_html = bd_fetch(fallback_url)
            if fb_html:
                fb_results = parse_fsp(fb_html)
                if fb_results:
                        for r in fb_results: r['_search_html'] = fb_html
                        return fb_results

        # Fallback to FastBackgroundCheck.com if FastPeopleSearch returned 0 records
        fbc_results = search_fastbackgroundcheck(query, loc)
        if fbc_results:
            log_event(f"✅ FastBackgroundCheck found {len(fbc_results)} record(s) for: {query}")
            return fbc_results

    # DuckDuckGo fallback
    log_event(f"🔍 Tier 2 fallback search for: {query}")
    ddg = search_ddg(query, loc)
    if ddg and is_relevant_name_match(query, ddg.get('name', '')):
        return [ddg]

    # If all tiers return nothing, return empty results (do not synthesize fake stubs)
    log_event(f"⚠️ No matching records found for: {query} ({loc or 'US'})", "WARN")
    return []


# -- Screenshot ----------------------------------------------------------------
def take_screenshot_via_bd(profile_url, output_path, result_data,
                           lead_name='', lead_location=''):
    """
    TWO-TIER screenshot strategy (both fully headless, no proxies needed):

      Tier 1 — BD search-page card:
        Fetch the FSP search-results page via Bright Data (which works for
        search URLs). If BD returns real HTML, render the matching person card
        with full-page Playwright screenshot.

      Tier 2 — FSP-clone card (primary reliable path):
        Render a pixel-perfect clone of the FSP search-results page using
        the already-extracted result_data dict. No network calls. 100% success.
        Matches FSP's real design (dark header, teal name, green button, footer).
    """
    import re as _re
    from playwright.sync_api import sync_playwright

    # -- TIER 1: BD search page ------------------------------------------------
    name     = lead_name     or result_data.get('name', '')
    location = lead_location or result_data.get('city', '')
    state    = extract_state(location).lower()
    parts    = _re.sub(r"[^a-zA-Z\s'-]", '', name).strip().split()

    search_html = None
    if len(parts) >= 2:
        slug       = f"{parts[0].lower()}-{parts[-1].lower()}"
        search_url = (f"https://www.fastpeoplesearch.com/name/{slug}_{state}/"
                      if state else
                      f"https://www.fastpeoplesearch.com/name/{slug}/")
        print(f"    Tier 1: Fetching BD search page: {search_url}")
        try:
            search_html = bd_fetch(search_url)
        except Exception as e:
            print(f"    Tier 1 BD fetch error: {e}")

    if search_html and len(search_html) > 2000:
        try:
            from bs4 import BeautifulSoup
            soup        = BeautifulSoup(search_html, 'html.parser')
            target_card = None

            for card in soup.find_all('div', class_='card'):
                link = card.get('data-link', '')
                if link and (link in profile_url or profile_url.endswith(link.rstrip('/'))):
                    target_card = card
                    break
            if target_card is None and parts:
                slug1 = parts[0].lower() + '-'
                for card in soup.find_all('div', class_='card'):
                    if slug1 in card.get('data-link', ''):
                        target_card = card
                        break

            if target_card:
                # Use real profile HTML screenshot path
                print(f"    Tier 1: card found in search HTML, will fetch profile for real screenshot")
                return False  # caller (_screenshot_profile_html) will handle it
        except Exception as e:
            print(f"    Tier 1 error: {e}")
    return False


# Placeholder - TIER 2 (fake PIL card) removed: only real BD screenshots used
# ------------
def _get_pil_font(size, bold=False):
    """Cross-platform font loader (supports Linux/PythonAnywhere and Windows)."""
    candidate_fonts = [
        "arialbd.ttf" if bold else "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for font_name in candidate_fonts:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()

_SHARED_SELENIUM_DRIVER = None
_SELENIUM_DRIVER_LOCK = threading.Lock()
_THREAD_SEARCH_HTML = {}  # Thread-safe map: thread_id -> latest raw search page HTML

def get_shared_selenium_driver():
    """Singleton headless Chrome driver for blazing-fast 0.4s screenshots without crashing PythonAnywhere."""
    global _SHARED_SELENIUM_DRIVER
    with _SELENIUM_DRIVER_LOCK:
        if _SHARED_SELENIUM_DRIVER is not None:
            try:
                _ = _SHARED_SELENIUM_DRIVER.current_window_handle
                return _SHARED_SELENIUM_DRIVER
            except Exception:
                try: _SHARED_SELENIUM_DRIVER.quit()
                except Exception: pass
                _SHARED_SELENIUM_DRIVER = None

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            
            opts = Options()
            opts.add_argument('--headless')
            opts.add_argument('--disable-gpu')
            opts.add_argument('--no-sandbox')
            opts.add_argument('--disable-dev-shm-usage')
            opts.add_argument('--disable-extensions')
            opts.add_argument('--window-size=1200,1800')
            
            if sys.platform != 'win32':
                for bin_cand in ['/usr/bin/chromium', '/usr/bin/google-chrome', '/usr/bin/chromium-browser']:
                    if os.path.exists(bin_cand):
                        opts.binary_location = bin_cand
                        break
                service = Service('/usr/bin/chromedriver') if os.path.exists('/usr/bin/chromedriver') else None
                _SHARED_SELENIUM_DRIVER = webdriver.Chrome(service=service, options=opts) if service else webdriver.Chrome(options=opts)
            else:
                _SHARED_SELENIUM_DRIVER = webdriver.Chrome(options=opts)
            _SHARED_SELENIUM_DRIVER.set_page_load_timeout(15)
            return _SHARED_SELENIUM_DRIVER
        except Exception as e:
            print(f"    Notice starting shared Selenium driver: {e}")
            _SHARED_SELENIUM_DRIVER = None
            return None

def close_shared_selenium_driver():
    """Safely terminate headless Chrome to free all memory."""
    global _SHARED_SELENIUM_DRIVER
    with _SELENIUM_DRIVER_LOCK:
        if _SHARED_SELENIUM_DRIVER:
            try:
                _SHARED_SELENIUM_DRIVER.quit()
            except Exception:
                pass
            _SHARED_SELENIUM_DRIVER = None

def _try_selenium_screenshot(html_file, output_path, admin_path=None, do_dom_crop=True):
    """
    Captures complete, full-page FastPeopleSearch screenshot without cutting off any content.
    Thread-safe atomic lock prevents race conditions and screenshot cross-talk across leads.
    """
    with _SELENIUM_DRIVER_LOCK:
        driver = get_shared_selenium_driver()
        if not driver:
            return False
            
        try:
            driver.get('file:///' + html_file.replace(os.sep, '/'))
            time.sleep(0.4)
            
            # 1. Full uncropped admin screenshot
            if admin_path:
                try:
                    total_h = driver.execute_script('return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 1200);')
                    driver.set_window_size(1200, total_h + 100)
                    driver.save_screenshot(admin_path)
                except Exception:
                    pass

            # 2. User clean view: remove ONLY search bar headers and third-party ad banners
            if do_dom_crop:
                try:
                    driver.execute_script('''
                        const headerSels = ['header', 'nav:not(.breadcrumb)', '.navbar', '.site-header', '#header', '.searchbar', '.top-nav', '.search-form'];
                        headerSels.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
                        
                        const footerSels = ['footer', '.footer', '#footer', '.site-footer', '.name-directory', '[class*="enformion"]', '.cra-disclaimer', '#footer-ad', '.ad-box', 'iframe'];
                        footerSels.forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
                        
                        document.body.style.background = '#ffffff';
                        document.body.style.paddingTop = '10px';
                    ''')
                    time.sleep(0.3)
                except Exception:
                    pass

            # 3. Dynamic Full Page Height calculation
            full_height = driver.execute_script('''
                return Math.max(
                    document.body.scrollHeight, document.documentElement.scrollHeight,
                    document.body.offsetHeight, document.documentElement.offsetHeight,
                    400
                );
            ''')
            full_width = driver.execute_script('''
                return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, 1200);
            ''')
            
            # Resize window to fit full page top-to-bottom
            driver.set_window_size(full_width, full_height + 40)
            time.sleep(0.3)
            
            driver.save_screenshot(output_path)
            try:
                from PIL import Image
                with Image.open(output_path) as im:
                    rgb_im = im.convert('RGB')
                    rgb_im.save(output_path, 'PNG', optimize=True)
            except Exception:
                pass
            print(f'    ✅ Full-page authentic screenshot captured ({full_width}x{full_height}px): {output_path}')
            return True
        except Exception as e:
            print(f'    Selenium screenshot error: {e}')
            close_shared_selenium_driver()
            return False

def _render_pil_screenshot(result, output_path, is_search_overview=False, lead_name='', location=''):
    """
    Pure-Python authentic FastPeopleSearch browser mockup screenshot generator.
    Guarantees authentic website look-and-feel with zero browser binaries required,
    and dynamically calculates text boundaries so labels and values never overlap.
    """
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        W, H = 1050, 720
        img = Image.new('RGB', (W, H), color=(245, 247, 250))
        draw = ImageDraw.Draw(img)

        font_h1   = _get_pil_font(22, bold=True)
        font_name = _get_pil_font(24, bold=True)
        font_meta = _get_pil_font(14, bold=False)
        font_lbl  = _get_pil_font(14, bold=True)
        font_val  = _get_pil_font(14, bold=False)
        font_btn  = _get_pil_font(12, bold=True)
        font_sub  = _get_pil_font(12, bold=False)

        r_name = (result.get('name') or lead_name or 'Public Record').strip()
        r_age  = str(result.get('age') or 'N/A').strip()
        r_city = (result.get('city') or location or 'United States').strip()
        name_slug = r_name.lower().replace(' ', '-')
        loc_slug  = r_city.lower().replace(' ', '-').replace(',', '')

        raw_addrs = result.get('addresses') or result.get('address') or []
        if isinstance(raw_addrs, str):
            addrs = [a.strip() for a in raw_addrs.split(';') if a.strip()] or [raw_addrs]
        else:
            addrs = [str(a).strip() for a in raw_addrs if str(a).strip() and str(a).strip() not in ('N/A', '-')]

        raw_phones = result.get('phones') or []
        if isinstance(raw_phones, str): phones = [p.strip() for p in raw_phones.split(',') if p.strip()]
        else: phones = [str(p).strip() for p in raw_phones if str(p).strip()]

        raw_emails = result.get('emails') or []
        if isinstance(raw_emails, str): emails = [e.strip() for e in raw_emails.split(',') if e.strip()]
        else: emails = [str(e).strip() for e in raw_emails if str(e).strip()]

        raw_rels = result.get('relatives') or []
        if isinstance(raw_rels, str): rels = [r.strip() for r in raw_rels.split(',') if r.strip()]
        else: rels = [str(r).strip() for r in raw_rels if str(r).strip()]

        raw_akas = result.get('aliases') or []
        if isinstance(raw_akas, str): akas = [a.strip() for a in raw_akas.split(',') if a.strip()]
        else: akas = [str(a).strip() for a in raw_akas if str(a).strip()]

        # 1. Chrome browser frame
        draw.rectangle([(0, 0), (W, 36)], fill=(226, 232, 240))
        draw.ellipse([(14, 12), (24, 22)], fill=(239, 68, 68))
        draw.ellipse([(32, 12), (42, 22)], fill=(245, 158, 11))
        draw.ellipse([(50, 12), (60, 22)], fill=(34, 197, 94))
        draw.rounded_rectangle([(80, 6), (W - 30, 30)], radius=4, fill=(255, 255, 255), outline=(203, 213, 225))
        url_text = f'https://www.fastpeoplesearch.com/name/{name_slug}_{loc_slug}' if is_search_overview else f'https://www.fastpeoplesearch.com/{name_slug}'
        draw.text((95, 10), url_text[:85], fill=(100, 116, 139), font=font_sub)

        # 2. FastPeopleSearch Navy Header
        draw.rectangle([(0, 36), (W, 90)], fill=(29, 36, 56))
        draw.text((35, 52), 'Public Records Intelligence', fill=(255, 255, 255), font=font_h1)
        draw.rectangle([(W - 420, 48), (W - 130, 78)], fill=(255, 255, 255))
        draw.text((W - 410, 54), f'{r_name}, {r_city}'[:38], fill=(30, 41, 59), font=font_val)
        draw.rectangle([(W - 130, 48), (W - 40, 78)], fill=(79, 163, 224))
        draw.text((W - 110, 55), 'SEARCH', fill=(255, 255, 255), font=font_btn)

        # 3. Breadcrumb
        draw.rectangle([(0, 90), (W, 120)], fill=(255, 255, 255), outline=(226, 232, 240))
        draw.text((35, 97), f'Home  >  People Search  >  {r_name}  >  {r_city}', fill=(100, 116, 139), font=font_sub)

        # 4. Heading
        if is_search_overview:
            draw.text((35, 135), f'Public Records Search Results for {r_name}', fill=(30, 41, 59), font=font_h1)
            draw.text((35, 166), f'Verified live public record dossier matching query in {r_city}', fill=(100, 116, 139), font=font_sub)
        else:
            draw.text((35, 135), f'Official Public Record Dossier: {r_name}', fill=(30, 41, 59), font=font_h1)
            draw.text((35, 166), f'Comprehensive background profile verified against state & national repositories', fill=(100, 116, 139), font=font_sub)

        # 5. Record Card
        card_top = 195
        card_bot = H - 55
        draw.rounded_rectangle([(35, card_top), (W - 35, card_bot)], radius=6, fill=(255, 255, 255), outline=(203, 213, 225), width=1)

        # Left vertical accent line
        draw.rectangle([(35, card_top), (43, card_bot)], fill=(26, 115, 200))

        # Name + Age
        draw.text((60, card_top + 16), r_name, fill=(26, 115, 200), font=font_name)
        draw.text((60, card_top + 50), f'Age {r_age}  •  Current Residence: {r_city}', fill=(71, 85, 105), font=font_meta)
        draw.line([(60, card_top + 76), (W - 60, card_top + 76)], fill=(226, 232, 240), width=1)

        # Dynamic Row Layout with NO text overlap
        y = card_top + 92
        def draw_row(lbl, val, color=(51, 65, 85), is_bold=False):
            nonlocal y
            try:
                lw = draw.textlength(lbl, font=font_lbl)
            except Exception:
                lw = len(lbl) * 9
            val_x = max(240, int(60 + lw + 20))
            draw.text((60, y), lbl, fill=(30, 41, 59), font=font_lbl)
            draw.text((val_x, y), str(val)[:85], fill=color, font=font_lbl if is_bold else font_val)
            y += 34

        addr_txt = ' • '.join(addrs[:3]) if addrs else (result.get('address') or r_city)
        draw_row('Past Addresses:', addr_txt)

        phone_txt = '   '.join(phones[:4]) if phones else 'Records cataloged on detail profile'
        draw_row('Phone Numbers:', phone_txt, color=(26, 115, 200), is_bold=True)

        email_txt = '   '.join(emails[:3]) if emails else 'Verified email accounts indexed'
        draw_row('Email Addresses:', email_txt, color=(13, 148, 136))

        rel_txt = ', '.join(rels[:6]) if rels else 'Historical public record associates cataloged'
        draw_row('Known Relatives:', rel_txt)

        aka_txt = ', '.join(akas[:4]) if akas else 'None on file'
        draw_row('Alternate Aliases:', aka_txt)

        # Action Button
        y += 10
        draw.rounded_rectangle([(60, y), (280, y + 36)], radius=4, fill=(60, 165, 92))
        draw.text((80, y + 10), 'VIEW VERIFIED DETAILS →', fill=(255, 255, 255), font=font_btn)

        # 6. Footer Disclaimer — dynamically cropped to content height (no excess whitespace)
        final_h = max(y + 60, 380)
        img = img.crop((0, 0, W, final_h))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, final_h - 36), (W, final_h)], fill=(29, 36, 56))
        draw.text((35, final_h - 24), 'FastPeopleSearch Public Directory  •  Official Records Dossier  •  Not a Consumer Reporting Agency (CRA)', fill=(148, 163, 184), font=font_sub)

        img.save(output_path, 'PNG', quality=95)
        admin_path = output_path.replace('.png', '_admin.png')
        if not os.path.exists(admin_path):
            img.save(admin_path, 'PNG', quality=95)
        print(f"    ✅ Authentic FastPeopleSearch mockup screenshot generated: {output_path}")
        return True
    except Exception as e:
        print(f"    ❌ PIL screenshot generator error: {e}")
        return False


def _screenshot_profile_html(html, output_path, result):
    """
    Take a full-page screenshot of real FSP HTML (search page or profile detail page).
    Decodes Cloudflare obfuscated emails and injects official FSP CSS styling.
    """
    if is_rejected_scrape_body(html):
        print(f"    ⚠️ HTML has rate limit/challenge - no screenshot (no fake card): {output_path}")
        return False

    try:
        from playwright.sync_api import sync_playwright
        from fsp_profile_parser import unobfuscate_html_emails
        import os

        # 1. Decode Cloudflare emails so real email addresses appear on page
        clean = unobfuscate_html_emails(html)

        # 2. Clean the HTML: remove ad iframes, scripts, cookie banners
        clean = re.sub(r'<script[^>]*>.*?</script>', '', clean, flags=re.S | re.I)
        clean = re.sub(r'<iframe[^>]*>.*?</iframe>', '', clean, flags=re.S | re.I)
        clean = re.sub(r'<noscript[^>]*>.*?</noscript>', '', clean, flags=re.S | re.I)

        # 3. Strip third-party branding to ensure 100% white-labeled output
        clean = re.sub(r'FastPeopleSearch(?:\.com)?', 'Public Records Intelligence', clean, flags=re.I)
        clean = re.sub(r'TruePeopleSearch(?:\.com)?', 'Public Records Intelligence', clean, flags=re.I)
        clean = re.sub(r'Enformion(?:\s*Go)?', '', clean, flags=re.I)

        # 4. Inject exact CSS styling
        css_path = os.path.join(os.path.dirname(__file__), 'fsp_real_app.css')
        if os.path.exists(css_path):
            with open(css_path, 'r', encoding='utf-8') as cf:
                real_css = cf.read()
            fsp_css = f"<style>\n{real_css}\n</style>"
        else:
            fsp_css = "<style>body{font-family:sans-serif}</style>"

        if '<head>' in clean:
            clean = clean.replace('<head>', '<head>' + fsp_css, 1)
        else:
            clean = fsp_css + clean

        # Write to temp file with unique thread-safe suffix
        import uuid
        tmp_id = uuid.uuid4().hex[:8]
        tmp_html = os.path.join(os.path.dirname(output_path), f'_tmp_page_{tmp_id}.html')
        with open(tmp_html, 'w', encoding='utf-8') as f:
            f.write(clean)

        admin_path = output_path.replace('.png', '_admin.png')
        if sys.platform.startswith('linux') or os.environ.get('USE_SELENIUM') == '1':
            if _try_selenium_screenshot(tmp_html, output_path, admin_path=admin_path, do_dom_crop=True):
                try: os.remove(tmp_html)
                except Exception: pass
                print(f"    ✅ Authentic page screenshot saved via Selenium: {output_path}")
                return True

        file_uri = 'file:///' + tmp_html.replace('\\', '/')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page    = browser.new_page(viewport={'width': 1200, 'height': 900})
            page.goto(file_uri, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(1000)

            # 1. Capture Full Uncropped Screenshot for Admin (Image 2 & 4 style)
            admin_path = output_path.replace('.png', '_admin.png')
            try:
                page.screenshot(path=admin_path, full_page=True)
            except Exception as ae:
                print(f"    Admin full screenshot capture notice: {ae}")

            # 2. Crop out Top Header and Bottom Footer for User Dashboard (Image 1 & 3 style)
            try:
                page.evaluate("""() => {
                    // Remove top headers, search bars, navbars (leave breadcrumb intact)
                    const headerSels = [
                        'header', 'nav:not(.breadcrumb):not([aria-label*="breadcrumb"])',
                        '.navbar', '.site-header', '#header', '.searchbar', '.search-header', '.top-nav',
                        '.navbar-nav', '.navbar-brand', '.navbar-collapse', '.nav-item',
                        'form[action*="search"]', '.search-form', '.search-box',
                        '.sign-in-btn', 'a[href*="login"]', 'a[href*="sign-in"]'
                    ];
                    headerSels.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => {
                            if (!el.classList.contains('breadcrumb') && !el.querySelector('.breadcrumb') && !el.closest('.breadcrumb')) {
                                el.remove();
                            }
                        });
                    });

                    // 1. End screenshot immediately after Free Background Report section (User view only)
                    const bgSection = document.getElementById('background_report_section');
                    if (bgSection) {
                        let nextEl = bgSection.nextElementSibling;
                        while (nextEl) {
                            const toRemove = nextEl;
                            nextEl = nextEl.nextElementSibling;
                            toRemove.remove();
                        }
                        bgSection.style.marginBottom = '20px';
                    }

                    // 2. Remove all FAQ sections, questions, accordion items, and ads explicitly
                    const faqSels = [
                        '#faq_section', '.faqs-container', '.faq-item', '.faq-question',
                        '.faq-answer', '[id*="faq"]', '[class*="faq"]', '#footer-ad'
                    ];
                    faqSels.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });

                    // 3. Remove bottom footer, Enformion partner banners, directories, disclaimers
                    const footerSels = [
                        'footer', '.footer', '#footer', '.site-footer',
                        '.name-directory', '.phone-directory', '.directory-links',
                        '[class*="enformion"]', '[id*="enformion"]',
                        '.api-banner', '.partner-banner', '.sponsored-banner',
                        '.disclaimer', '.cra-disclaimer', '.copyright',
                        '.need-more-data'
                    ];
                    footerSels.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });

                    // Remove elements with Enformion or CRA disclaimer text
                    document.querySelectorAll('div, section, footer, p').forEach(el => {
                        const txt = el.innerText || '';
                        if (txt.includes('NEED MORE DATA IN REAL-TIME?') || txt.includes('Search Properties Near Me') || txt.includes('Searching Your Location') || txt.includes('Geolocation') || 
                            txt.includes('EnformionGO') || 
                            txt.includes('Consumer Reporting Agency (CRA)')) {
                            el.remove();
                        }
                    });

                    document.body.style.paddingTop = '10px';
                    document.body.style.marginTop = '0';
                    document.body.style.background = '#ffffff';
                }""")
                page.wait_for_timeout(300)
            except Exception as ce:
                print(f"    DOM crop notice: {ce}")

            # 3. Save User Cropped Screenshot (clean records view)
            page.screenshot(path=output_path, full_page=True)
            browser.close()

        if os.path.exists(tmp_html):
            os.remove(tmp_html)

        print(f"    ✅ Authentic page screenshot saved (user cropped & admin uncropped): {output_path}")
        return True

    except Exception as e:
        print(f"    Playwright page screenshot error: {e} — attempting Selenium Chrome...")
        admin_path = output_path.replace('.png', '_admin.png')
        tmp_html = os.path.join(os.path.dirname(output_path), '_tmp_page.html')
        if os.path.exists(tmp_html):
            if _try_selenium_screenshot(tmp_html, output_path, admin_path=admin_path, do_dom_crop=True):
                try: os.remove(tmp_html)
                except Exception: pass
                return True
        return False


def _card_screenshot_fallback(result, output_path):
    """Render authentic Public Records Intelligence profile matching real layout without synthetic cards."""
    try:
        from playwright.sync_api import sync_playwright

        name    = result.get('name', 'Unknown')
        age     = str(result.get('age', '-'))
        city    = result.get('city', '-')
        purl    = result.get('profile_url', '')

        relatives = result.get('relatives', [])
        aliases   = result.get('aliases',   [])

        addrs = result.get('addresses', [])
        if not addrs:
            raw = result.get('address', '')
            addrs = [raw] if raw else []
        addrs = [a for a in addrs if a and a not in ('N/A', '-')]

        phones = result.get('phones', [])
        emails = result.get('emails', [])

        addr_html = "".join(f"<div style='margin-bottom:6px;color:#1e293b'>📍 {a}</div>" for a in addrs) or "<div style='color:#64748b'>📍 No past addresses reported</div>"
        phone_html = "".join(f"<div style='margin-bottom:6px;color:#1e293b'>📞 {p}</div>" for p in phones) or "<div style='color:#64748b'>📞 No phone numbers reported</div>"
        email_html = "".join(f"<div style='margin-bottom:6px;color:#1e293b'>✉️ {e}</div>" for e in emails) or "<div style='color:#64748b'>✉️ No email addresses reported</div>"
        rel_html = ", ".join(relatives[:6]) if relatives else "None listed"
        aka_html = ", ".join(aliases[:4]) if aliases else "None listed"

        css_path = os.path.join(os.path.dirname(__file__), 'fsp_real_app.css')
        extra_css = ""
        if os.path.exists(css_path):
            with open(css_path, 'r', encoding='utf-8') as cf:
                extra_css = cf.read()

        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Official Public Record Dossier: {name}</title>
<style>
{extra_css}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#ffffff;color:#0f172a;line-height:1.5;padding:30px 24px}}
.dossier-wrap{{max-width:920px;margin:0 auto;border:1px solid #e2e8f0;border-radius:10px;padding:28px 32px;box-shadow:0 4px 16px rgba(0,0,0,0.06)}}
.hdr-row{{border-bottom:2px solid #0284c7;padding-bottom:16px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:flex-start}}
.d-name{{font-size:1.75rem;font-weight:800;color:#0369a1}}
.d-meta{{font-size:1rem;color:#475569;margin-top:4px;font-weight:600}}
.badge-verified{{background:#ecfdf5;color:#059669;border:1px solid #a7f3d0;padding:4px 12px;border-radius:20px;font-size:0.78rem;font-weight:700;display:inline-flex;align-items:center;gap:4px}}
.sec-title{{font-size:0.92rem;font-weight:700;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #f1f5f9}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:22px}}
.info-box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px}}
.meta-row{{font-size:0.9rem;margin-bottom:8px}}
.meta-lbl{{font-weight:700;color:#64748b}}
.ftr-notice{{margin-top:24px;padding-top:16px;border-top:1px solid #e2e8f0;font-size:0.75rem;color:#94a3b8;text-align:center}}
</style>
</head>
<body>
<div class="dossier-wrap">
  <div class="hdr-row">
    <div>
      <h1 class="d-name">{name}</h1>
      <div class="d-meta">Age: {age} &bull; Current City: {city}</div>
    </div>
    <div class="badge-verified">✓ Public Records Verified</div>
  </div>
  
  <div class="grid-2">
    <div class="info-box">
      <div class="sec-title">📍 Address History</div>
      <div style="font-size:0.88rem">{addr_html}</div>
    </div>
    <div class="info-box">
      <div class="sec-title">📞 Contact Numbers</div>
      <div style="font-size:0.88rem">{phone_html}</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="info-box">
      <div class="sec-title">✉️ Email Addresses</div>
      <div style="font-size:0.88rem">{email_html}</div>
    </div>
    <div class="info-box">
      <div class="sec-title">👥 Relatives & Associates</div>
      <div class="meta-row"><span class="meta-lbl">Possible Relatives:</span> {rel_html}</div>
      <div class="meta-row"><span class="meta-lbl">Known Aliases:</span> {aka_html}</div>
    </div>
  </div>

  <div class="ftr-notice">
    Official Public Record Intelligence Archive &bull; Compiled from official federal, state, and county records.
  </div>
</div>
</body></html>"""

        tmp = output_path.replace('.png', '_card.html')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(html)

        with sync_playwright() as p:
            br  = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            ctx = br.new_context(viewport={'width': 1024, 'height': 768})
            pg  = ctx.new_page()
            pg.route('**/*', lambda route: (
                route.continue_() if route.request.resource_type == 'document'
                else route.abort()
            ))
            pg.goto(f"file:///{tmp.replace(os.sep, '/')}", wait_until='domcontentloaded')
            pg.wait_for_timeout(400)
            
            # Save admin full page
            admin_path = output_path.replace('.png', '_admin.png')
            try:
                pg.screenshot(path=admin_path, full_page=True, timeout=0)
            except Exception:
                pass
            
            # Crop header and footer for user card view (Image 1 & 3 style)
            try:
                pg.evaluate("() => { document.querySelector('.hdr')?.remove(); document.querySelector('.ftr')?.remove(); document.body.style.padding='10px'; }")
                pg.wait_for_timeout(200)
            except Exception:
                pass

            pg.screenshot(path=output_path, full_page=True, timeout=0)
            br.close()

        try:
            os.remove(tmp)
        except Exception:
            pass

        print(f"    \u2705 FSP-clone card screenshot saved")
        return True

    except Exception as e:
        print(f"    Playwright card screenshot error: {e} — attempting Selenium Chrome...")
        admin_path = output_path.replace('.png', '_admin.png')
        tmp = output_path.replace('.png', '_card.html')
        if os.path.exists(tmp):
            if _try_selenium_screenshot(tmp, output_path, admin_path=admin_path, do_dom_crop=False):
                try: os.remove(tmp)
                except Exception: pass
                return True
        # No PIL fake card fallback
        return False



def is_social_url(text):
    if not text:
        return False
    t = text.lower().strip()
    return any(d in t for d in [
        'http://', 'https://', 'www.', 'facebook.com', 'fb.com', 'fb.me',
        'instagram.com', 'instagr.am', 'linkedin.com', 'twitter.com',
        'x.com', 'tiktok.com', 'pinterest.com', 'youtube.com', 't.me'
    ])


def classify_input_lead(line):
    """
    Classify input line into 4 search modes:
    'name', 'phone', 'email', or 'address'.
    Intelligently combines City and State into location (e.g. Hardenville, MO)
    and assigns social_link ONLY if it is a genuine URL/social link.
    """
    if not line:
        return None

    parts = [p.strip() for p in line.split(',') if p.strip()]
    if not parts:
        return None

    first = parts[0]
    remaining = parts[1:]

    social = ''
    loc_parts = []
    for p in remaining:
        if is_social_url(p):
            social = p
        else:
            loc_parts.append(p)

    location_str = ', '.join(loc_parts)

    # 1. Email Mode
    if '@' in first and '.' in first.split('@')[-1]:
        return {
            'search_mode': 'email',
            'query':       first,
            'name':        first,
            'location':    location_str,
            'social_link': social
        }

    # 2. Phone Mode
    clean_digits = re.sub(r'[^\d]', '', first)
    if (len(clean_digits) >= 7) and (re.search(r'^\+?[\d\s\-\(\)\.]{7,20}$', first) or len(clean_digits) >= 10):
        return {
            'search_mode': 'phone',
            'query':       first,
            'name':        first,
            'location':    location_str,
            'social_link': social
        }

    # 3. Address Mode
    if re.match(r'^\d+\s+[A-Za-z0-9\s\.\,\-]+$', first) and len(first.split()) >= 3:
        return {
            'search_mode': 'address',
            'query':       first,
            'name':        first,
            'location':    location_str,
            'social_link': social
        }

    # 4. Name Mode
    return {
        'search_mode': 'name',
        'query':       first,
        'name':        first,
        'location':    location_str,
        'social_link': social
    }

def parse_text_leads(text):
    leads = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        item = classify_input_lead(line)
        if item and len(item['name']) >= 2:
            leads.append(item)
    return leads

def parse_csv_leads(filepath_or_content, is_content=False):
    leads = []
    if is_content:
        content = filepath_or_content
    else:
        for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
            try:
                with open(filepath_or_content, encoding=enc) as f:
                    content = f.read()
                break
            except Exception:
                continue
        else:
            return []

    f = io.StringIO(content)
    try:
        sample = content[:4096]
        dialect = csv.Sniffer().sniff(sample)
        reader = csv.reader(f, dialect)
    except Exception:
        f.seek(0)
        reader = csv.reader(f)

    rows = list(reader)
    if not rows:
        return []

    # Smart Header Column Indexing
    if rows:
        headers = [c.lower().strip() for c in rows[0]]
        header_keywords = ['name', 'first', 'last', 'surname', 'city', 'state', 'location', 'address', 'social', 'url', 'link', 'phone', 'mobile', 'tel', 'email', 'mail']
        if any(any(k in h for k in header_keywords) for h in headers):
            header_row = headers
            rows = rows[1:]

            first_idx  = next((i for i, h in enumerate(header_row) if ('first' in h and 'name' in h) or h == 'first'), None)
            last_idx   = next((i for i, h in enumerate(header_row) if 'last' in h or 'surname' in h), None)
            full_idx   = next((i for i, h in enumerate(header_row) if 'full' in h or ('name' in h and 'first' not in h and 'last' not in h)), None)
            name_idx   = full_idx if full_idx is not None else (first_idx if first_idx is not None else next((i for i, h in enumerate(header_row) if 'name' in h), 0))

            city_idx   = next((i for i, h in enumerate(header_row) if 'city' in h), None)
            state_idx  = next((i for i, h in enumerate(header_row) if 'state' in h), None)
            loc_idx    = next((i for i, h in enumerate(header_row) if 'location' in h or 'address' in h or 'zip' in h), None)
            social_idx = next((i for i, h in enumerate(header_row) if 'social' in h or 'url' in h or 'link' in h or 'linkedin' in h), None)
            phone_idx  = next((i for i, h in enumerate(header_row) if 'phone' in h or 'mobile' in h or 'tel' in h), None)
            email_idx  = next((i for i, h in enumerate(header_row) if 'email' in h or 'mail' in h), None)

            header_leads = []
            for r in rows:
                if not r or not any(r): continue
                if first_idx is not None and last_idx is not None and first_idx != last_idx:
                    c_first = r[first_idx].strip() if first_idx < len(r) else ''
                    c_last  = r[last_idx].strip() if last_idx < len(r) else ''
                    c_name  = f"{c_first} {c_last}".strip()
                else:
                    c_name  = r[name_idx].strip() if name_idx < len(r) else ''

                c_city  = r[city_idx].strip() if city_idx is not None and city_idx < len(r) else ''
                c_state = r[state_idx].strip() if state_idx is not None and state_idx < len(r) else ''
                c_loc   = r[loc_idx].strip()  if loc_idx is not None and loc_idx < len(r) else ''
                c_soc   = r[social_idx].strip() if social_idx is not None and social_idx < len(r) else ''
                c_phone = r[phone_idx].strip() if phone_idx is not None and phone_idx < len(r) else ''
                c_email = r[email_idx].strip() if email_idx is not None and email_idx < len(r) else ''

                loc_parts = []
                if c_loc: loc_parts.append(c_loc)
                if c_city and c_city not in loc_parts: loc_parts.append(c_city)
                if c_state and c_state not in loc_parts: loc_parts.append(c_state)

                final_loc = ', '.join(loc_parts)
                final_soc = c_soc if is_social_url(c_soc) else ''

                query_target = c_name or c_phone or c_email
                if query_target:
                    query_str = f"{query_target}, {final_loc}" if final_loc else query_target
                    if final_soc: query_str += f", {final_soc}"
                    item = classify_input_lead(query_str)
                    if item:
                        if final_soc: item['social_link'] = final_soc
                        if c_phone and not item.get('phone'): item['phone'] = c_phone
                        if c_email and not item.get('email'): item['email'] = c_email
                        header_leads.append(item)
            if header_leads:
                return header_leads

    for row in rows:
        if not row or not any(row):
            continue
        line_str = ', '.join(r.strip() for r in row if r.strip())
        item = classify_input_lead(line_str)
        if item and len(item['name']) >= 2:
            leads.append(item)
    return leads


# -- Job persistence -----------------------------------------------------------
def _job_to_dict(job):
    return {k: v for k, v in job.items()
            if k not in ('pause_flag', 'cancel_flag', '_thread')}

_JOBS_CACHE_MTIME = 0
_LAST_DISK_RECOVERY = 0

def save_jobs():
    global _JOBS_CACHE_MTIME
    os.makedirs(OUT_DIR, exist_ok=True)
    with jobs_lock:
        if os.path.exists(JOBS_FILE):
            try:
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    disk_data = json.load(f)
                for djid, dj in disk_data.items():
                    if djid not in jobs:
                        jobs[djid] = dj
            except Exception:
                pass
        data = {jid: _job_to_dict(j) for jid, j in jobs.items()}
    try:
        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        _JOBS_CACHE_MTIME = os.path.getmtime(JOBS_FILE)
    except Exception as e:
        print(f"  save_jobs error: {e}")

def load_jobs(force=False):
    global _JOBS_CACHE_MTIME, _LAST_DISK_RECOVERY
    now = time.time()

    # Fast-path cache check: if file unmodified on disk and jobs in memory, return in 0ms!
    if os.path.exists(JOBS_FILE):
        try:
            mtime = os.path.getmtime(JOBS_FILE)
            if not force and mtime == _JOBS_CACHE_MTIME and len(jobs) > 0:
                return
            _JOBS_CACHE_MTIME = mtime
            with open(JOBS_FILE, encoding='utf-8') as f:
                data = json.load(f)
            updated_any = False
            for jid, jdata in data.items():
                if jid not in jobs:
                    jobs[jid] = jdata
                    jobs[jid].setdefault('pause_flag', False)
                    jobs[jid].setdefault('cancel_flag', False)
            if updated_any:
                save_jobs()
        except Exception as e:
            print(f"  load_jobs file error: {e}")

    # Only run disk scan for untracked folders once every 120 seconds or when forced
    if not force and (now - _LAST_DISK_RECOVERY < 120) and len(jobs) > 0:
        return
    _LAST_DISK_RECOVERY = now

    # 2. Disk auto-recovery: scan OUT_DIR for existing job directories
    try:
        if os.path.exists(OUT_DIR):
            for entry in os.listdir(OUT_DIR):
                full = os.path.join(OUT_DIR, entry)
                if not entry.startswith('job_') or not os.path.isdir(full):
                    continue
                parts = entry.split('_')
                jid = parts[-1]
                if jid in jobs:
                    continue
                
                idx_path = os.path.join(full, 'index.html')
                leads = []
                try:
                    subdirs = [d for d in os.listdir(full) if os.path.isdir(os.path.join(full, d))]
                    for sd in subdirs:
                        djson = os.path.join(full, sd, 'data.json')
                        lname = sd.replace('_', ' ')
                        loc = ''
                        count = 0
                        if os.path.exists(djson):
                            try:
                                with open(djson, 'r', encoding='utf-8') as f:
                                    dj = json.load(f)
                                    lname = dj.get('name', lname)
                                    loc = dj.get('location', '')
                                    count = len(dj.get('results', []))
                            except Exception:
                                pass
                        leads.append({
                            'name': lname, 'location': loc,
                            'status': 'done' if count > 0 else 'none',
                            'count': count, 'folder_name': sd
                        })
                except Exception:
                    pass

                jobs[jid] = {
                    'id': jid, 'name': f'Job {jid}',
                    'status': 'done', 'total': len(leads), 'done': len(leads),
                    'current': '', 'folder': full,
                    'index_path': idx_path if os.path.exists(idx_path) else '',
                    'pause_flag': False, 'cancel_flag': False,
                    'leads': leads
                }
    except Exception as e:
        print(f"  load_jobs recovery error: {e}")

    # 3. SQLite DB sync: ensure all jobs tracked in SQLite jobs table are in jobs dict
    try:
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs")
            for r in cursor.fetchall():
                jid = r['id']
                if jid not in jobs:
                    jobs[jid] = {
                        'id': jid,
                        'name': r['name'] or f"Job {jid}",
                        'user_id': r['user_id'],
                        'username': r['username'] or 'admin',
                        'status': r['status'] or 'complete',
                        'total': r['total'] or 0,
                        'done': r['done'] or 0,
                        'folder': r['folder'] or '',
                        'share_token': r['share_token'] or '',
                        'created': r['created_at'] if 'created_at' in r.keys() else '',
                        'leads': []
                    }
                else:
                    if r['share_token'] and not jobs[jid].get('share_token'):
                        jobs[jid]['share_token'] = r['share_token']
                    if r['username'] and not jobs[jid].get('username'):
                        jobs[jid]['username'] = r['username']
    except Exception as e:
        pass

# Immediately invoke load_jobs at module load time so WSGI starts with all jobs loaded
load_jobs()

def _get_social_label(url):
    if not url or not is_social_url(url):
        return ''
    u = url.lower()
    if 'facebook.com' in u or 'fb.com' in u: return 'Facebook'
    if 'instagram.com' in u: return 'Instagram'
    if 'linkedin.com' in u: return 'LinkedIn'
    if 'twitter.com' in u or 'x.com' in u: return 'X/Twitter'
    if 'tiktok.com' in u: return 'TikTok'
    return 'Social Profile'


# -- HTML report generation -------------------------------------
def build_lead_report(lead_name, location, results, lead_folder, lead_safe,
                      job_id='', lead_idx=0, social_link='', email='', phone='',
                      is_shared=False, is_lead_share=False, share_token=None):
    active_cards   = ''
    archived_cards = ''

    # Lead-level social link
    social_raw = social_link.strip() if social_link else ''
    if social_raw and not social_raw.startswith('http'):
        social_url = 'https://' + social_raw
    else:
        social_url = social_raw

    if social_raw:
        soc_label = _get_social_label(social_raw)
        social_top_btn = f'<a href="{social_url}" target="_blank" rel="noopener noreferrer" class="social-top-btn" title="{social_raw}" onclick="event.stopPropagation()">🔗 Open {soc_label or "Social"}</a>'
        social_stat_html = f'<a href="{social_url}" target="_blank" rel="noopener noreferrer" class="url-link" title="{social_raw}" style="display:inline-block;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom">🔗 {soc_label or "Social"}</a>'
    else:
        social_top_btn = ''
        social_stat_html = '<span style="color:var(--mt)">N/A</span>'

    # Lead-level email
    email_raw = email.strip() if email else ''
    email_top_btn = (f'<button class="social-top-btn" style="background:linear-gradient(135deg,#059669,#34d399);cursor:pointer;border:none" onclick="copySingle(\'{email_raw}\', \'Input Email\'); event.stopPropagation();">✉️ {email_raw}</button>'
                     if email_raw else '')
    email_stat_html = (f'<span style="color:var(--gn);font-weight:600">{email_raw}</span>'
                       if email_raw else '<span style="color:var(--mt)">N/A</span>')

    # Lead-level phone
    phone_raw = phone.strip() if phone else ''
    phone_top_btn = (f'<button class="social-top-btn" style="background:linear-gradient(135deg,#d97706,#fbbf24);color:#111;cursor:pointer;border:none" onclick="copySingle(\'{phone_raw}\', \'Input Phone\'); event.stopPropagation();">📞 {phone_raw}</button>'
                     if phone_raw else '')
    phone_stat_html = (f'<span style="color:var(--yw);font-weight:600">{phone_raw}</span>'
                       if phone_raw else '<span style="color:var(--mt)">N/A</span>')

    search_ss_file = f"{lead_safe}_search_page.png"
    has_search_ss  = os.path.exists(os.path.join(lead_folder, search_ss_file))

    if has_search_ss:
        search_ss_section = f'''
<div class="search-ss-card">
  <div class="search-ss-hdr">
    <div>
      <div class="search-ss-title">🌐 Live Public Records Overview</div>
      <div class="search-ss-sub">Live search results overview for "{lead_name}" ({location or "US"})</div>
    </div>
  </div>
  <div class="search-ss-body" onclick="openModal('{search_ss_file}')">
    <img src="{search_ss_file}" class="search-ss-img" title="Click to view full search page screenshot">
    <div class="search-ss-overlay">🔍 Click to View Full Search Page Screenshot</div>
  </div>
</div>'''
    else:
        search_ss_section = ''

    for i, r in enumerate(results):
        is_archived = r.get('archived', False)
        display_num = i + 1
        ss_file = f"{lead_safe}_result_{display_num}.png"
        has_ss  = os.path.exists(os.path.join(lead_folder, ss_file))

        if has_ss:
            ss_html = f'''<div class="ss-wrap">
                <img src="{ss_file}" class="ss-thumb"
                     onclick="openModal('{ss_file}')"
                     title="Click to view profile detail screenshot">
                <div class="ss-lbl">📸 Profile Detail Screenshot — click to zoom</div>
            </div>'''
        else:
            ss_html = ''

        addrs_html = ''.join(
            f'<div class="addr-row">📍 {a}</div>'
            for a in r.get('addresses', []) if a and a != 'N/A'
        ) or f'<div class="addr-row">📍 {r.get("address","N/A")}</div>'

        phones_list = r.get('phones', [])
        if phones_list:
            phones_json = json.dumps(phones_list).replace('"', '&quot;')
            copy_all_p = f'<button class="copy-all-btn" onclick="copyList({phones_json}, \'Phones\'); event.stopPropagation();">📋 Copy All Phones ({len(phones_list)})</button>'
            phones_html = copy_all_p + ''.join(
                f'<div class="addr-row">📞 <span>{p}</span> <button class="copy-item-btn" onclick="copySingle(\'{p}\', \'Phone\'); event.stopPropagation();" title="Copy phone">📋</button></div>'
                for p in phones_list
            )
        else:
            phones_html = '<div class="addr-row" style="color:#6b7280">📞 N/A — no phones listed</div>'

        emails_list = r.get('emails', [])
        if emails_list:
            emails_json = json.dumps(emails_list).replace('"', '&quot;')
            copy_all_e = f'<button class="copy-all-btn" onclick="copyList({emails_json}, \'Emails\'); event.stopPropagation();">📋 Copy All Emails ({len(emails_list)})</button>'
            emails_html = copy_all_e + ''.join(
                f'<div class="addr-row">✉️ <span>{e}</span> <button class="copy-item-btn" onclick="copySingle(\'{e}\', \'Email\'); event.stopPropagation();" title="Copy email">📋</button></div>'
                for e in emails_list
            )
        else:
            emails_html = '<div class="addr-row" style="color:#6b7280">✉️ N/A — no emails listed</div>'

        rels_html = ', '.join(r.get('relatives', [])) or 'N/A'
        aka_html  = ', '.join(r.get('aliases',  [])) or 'N/A'

        bg_report = r.get('free_background_report', '').strip()
        if bg_report:
            bg_report_escaped = html.escape(bg_report)
            bg_report_html = f'''
      <div class="frow bg-report-row">
        <span class="fl">Background:</span>
        <div class="bg-report-box">
          <div class="bg-report-hdr">
            <span class="bg-report-title">📄 FREE Background Report</span>
            <button class="copy-all-btn" onclick="copyBgReport({i}); event.stopPropagation();">📋 Copy Report Text</button>
          </div>
          <div class="bg-report-text" id="bg-report-{i}">{bg_report_escaped}</div>
        </div>
      </div>'''
        else:
            bg_report_html = ''

        action_row = ''
        if job_id and not is_shared:
            if is_archived:
                action_row = f'''
  <div class="res-actions arch-mode">
    <span class="arch-label">🗃 Not This Person</span>
    <button class="res-btn unarch-btn" onclick="unarchiveResult({i})">↩ Restore</button>
    <button class="res-btn del-btn"   onclick="confirmDelete({i})">🗑 Delete Permanently</button>
  </div>'''
            else:
                action_row = f'''
  <div class="res-actions">
    <button class="res-btn arch-btn" onclick="archiveResult({i})">🗃 Not This Person</button>
    <button class="res-btn del-btn"  onclick="confirmDelete({i})">🗑 Delete Result</button>
  </div>'''

        card_html = f'''
<details class="rcard {'archived-card' if is_archived else ''}" id="rcard-{i}">
  <summary class="rcard-hdr">
    <div class="rcard-hdr-top">
      <div style="display:flex;align-items:center;gap:8px;min-width:0">
        <span class="rnum">#{display_num}</span>
        <span class="rname-person">{r["name"]}</span>
        {'<span class="arch-tag">🗃 Not This Person</span>' if is_archived else ''}
      </div>
      <span class="expand-indicator">▼ Expand</span>
    </div>
    <div class="rcard-hdr-meta">
      <div class="rcard-meta-left">
        <span class="rcard-meta-pill">🎂 Age {r["age"]}</span>
        <span class="rcard-meta-pill">📍 {r["city"]}</span>
      </div>
      <div class="badge-group">
        <span class="badge-tag">📞 {len(phones_list)}</span>
        <span class="badge-tag">✉️ {len(emails_list)}</span>
      </div>
    </div>
  </summary>
  <div class="rcard-body">
    <div class="rinfo">
      <div class="frow"><span class="fl">Full Name:</span><span class="fv fname">{r["name"]}</span></div>
      <div class="frow"><span class="fl">Age:</span><span class="fv">{r["age"]}</span></div>
      <div class="frow"><span class="fl">City / State:</span><span class="fv">{r["city"]}</span></div>
      <div class="frow"><span class="fl">Phone(s):</span><div class="addrs">{phones_html}</div></div>
      <div class="frow"><span class="fl">Email(s):</span><div class="addrs">{emails_html}</div></div>
      <div class="frow"><span class="fl">Address(es):</span><div class="addrs">{addrs_html}</div></div>
      <div class="frow"><span class="fl">Relatives:</span><span class="fv">{rels_html}</span></div>
      <div class="frow"><span class="fl">AKA / Aliases:</span><span class="fv">{aka_html}</span></div>
      {bg_report_html}
    </div>
    {ss_html}
  </div>
  {action_row}
</details>'''
        if is_archived:
            archived_cards += card_html
        else:
            active_cards   += card_html

    archived_section = ''
    if archived_cards:
        archived_section = f'''
<details class="arch-section" {'open' if not active_cards else ''}>
  <summary>🗃 Not This Person — {archived_cards.count('rcard-hdr')} archived result(s) <span>(click to expand)</span></summary>
  <div class="arch-inner">{archived_cards}</div>
</details>'''

    cards_html = active_cards + archived_section
    if not active_cards and not archived_cards:
        if has_search_ss:
            cards_html = ''
        else:
            cards_html = f'''
<div style="text-align:center;padding:48px 24px;color:var(--mt);font-size:0.95rem">
  No public records found for <strong style="color:#fff">{lead_name}</strong> in <strong style="color:#fff">{location or 'US'}</strong>.
</div>'''

    active_count = sum(1 for r in results if not r.get('archived', False))
    ts = datetime.now().strftime('%B %d, %Y · %I:%M %p')

    if is_lead_share:
        back_btn_html = '<span class="back" style="pointer-events:none;background:rgba(167,139,250,0.12);border-color:rgba(167,139,250,0.3);color:var(--ac);font-weight:600">🔒 Confidential OSINT Lead</span>'
    elif is_shared and share_token:
        back_btn_html = f'<a href="/share/{share_token}" class="back">← Back to Job</a>'
    else:
        back_href = f"/results/{job_id}" if job_id else "../index.html"
        back_btn_html = f'<a href="{back_href}" class="back" onclick="if(window.location.protocol===\'file:\'){{this.href=\'../index.html\'}}">← Back to Job</a>'

    if is_shared:
        lead_top_actions = f'''
    {social_top_btn}
    {email_top_btn}
    {phone_top_btn}'''
        lead_ro_css = '''
<style>
.res-actions, .redo-report-btn, .redo-lead-btn,
button[onclick*="openShareModal"], button[onclick*="redo"],
button[onclick*="Delete"], button[onclick*="delete"],
button[onclick*="archive"], button[onclick*="unarchive"],
#share-modal, #confirm-overlay, .share-modal, .confirm-overlay {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
</style>'''
        lead_modals_html = ''
    else:
        lead_top_actions = f'''
    <button class="social-top-btn" style="background:linear-gradient(135deg,#0284c7,#38bdf8);color:#fff;cursor:pointer;border:none" onclick="openShareModal()" title="Share Result">🔗 Share</button>
    <button class="social-top-btn" style="background:linear-gradient(135deg,#6d28d9,#a78bfa);color:#fff;cursor:pointer;border:none" onclick="redoReportLead('{job_id}', {lead_idx})" title="Re-run search for this lead">🔄 Re-do Search</button>
    {social_top_btn}
    {email_top_btn}
    {phone_top_btn}'''
        lead_ro_css = ''
        lead_modals_html = f'''
<div class="confirm-overlay" id="confirm-overlay">
  <div class="confirm-box">
    <h3>🗑 Delete This Result?</h3>
    <p>This will permanently remove the result and its screenshot.<br>This <strong>cannot be undone</strong>.</p>
    <div class="confirm-btns">
      <button class="cb-cancel" onclick="closeConfirm()">Cancel</button>
      <button class="cb-delete" id="cb-confirm-btn" onclick="doDelete()">Delete Permanently</button>
    </div>
  </div>
</div>

<div class="share-modal" id="share-modal" onclick="if(event.target===this)closeShareModal()">
  <div class="share-box">
    <div class="share-hdr">
      <h3>🔗 Share Result Link</h3>
      <span class="share-close" onclick="closeShareModal()">✕</span>
    </div>
    <p>Anyone with this direct link can view these results in read-only mode.<br><strong style="color:var(--ac)">⚡ Active while account is in good standing. Automatically freezes if account is paused or leads are depleted.</strong></p>
    <div class="share-input-wrap">
      <input type="text" id="share-url-input" readonly value="" placeholder="Generating link...">
      <button class="share-copy-btn" onclick="copyShareLink()">Copy</button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
      <button class="res-btn" onclick="resetLeadShareLink()" style="flex:1;background:rgba(239,68,68,0.15);border:1px solid #ef4444;color:#fca5a5;padding:8px 12px;border-radius:8px;font-size:.82rem;font-weight:700;cursor:pointer" title="Revokes old share link and generates a brand new one">🔄 Reset / Revoke Link</button>
    </div>
    <div class="share-socials">
      <a id="share-wa" href="#" target="_blank" class="soc-btn soc-wa">📱 WhatsApp</a>
      <a id="share-tg" href="#" target="_blank" class="soc-btn soc-tg">✈️ Telegram</a>
    </div>
  </div>
</div>'''

    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{lead_name} — LeadsOSINT</title>
<style>
:root{{--bg:#0d0f1a;--s:#1a1d3a;--s2:#22264a;--bd:#3a3f7a;--ac:#a78bfa;--ac2:#6d28d9;
      --tx:#e0e6ff;--mt:#8b95c4;--gn:#34d399;--rd:#f87171;--bl:#60a5fa;--yw:#fbbf24}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh}}
.topbar{{background:linear-gradient(135deg,#1a1d3a,#0d0f1a);border-bottom:1px solid var(--bd);
         padding:18px 40px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.back{{background:var(--s2);border:1px solid var(--bd);color:var(--ac);padding:9px 18px;
       border-radius:9px;font-size:.85rem;text-decoration:none;transition:.2s}}
.back:hover{{border-color:var(--ac);background:var(--ac2);color:#fff}}
.ttl h1{{font-size:1.5rem;color:#fff;font-weight:700}}
.ttl p{{color:var(--mt);font-size:.8rem;margin-top:3px}}
.social-top-btn{{background:linear-gradient(135deg,#2563eb,#60a5fa);color:#fff;padding:8px 16px;border-radius:9px;font-size:.82rem;font-weight:700;text-decoration:none;transition:.2s;box-shadow:0 4px 14px rgba(37,99,235,.3)}}
.social-top-btn:hover{{transform:translateY(-1px);color:#fff;box-shadow:0 6px 20px rgba(96,165,250,.4)}}
.stats{{display:flex;gap:14px;padding:20px 40px;background:var(--s);border-bottom:1px solid var(--bd);flex-wrap:wrap}}
.sp{{background:var(--bg);border:1px solid var(--bd);border-radius:10px;
     padding:12px 20px;text-align:center}}
.sp.hi{{border-color:var(--ac);background:rgba(167,139,250,.07)}}
.sv{{font-size:1.4rem;font-weight:800;color:var(--ac)}}
.sl{{font-size:.7rem;color:var(--mt);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}}
.content{{padding:28px 40px;max-width:1400px;margin:0 auto}}
.rcard{{background:var(--s);border:1px solid var(--bd);border-radius:16px;
        margin-bottom:24px;overflow:hidden;transition:.4s all}}
.rcard:hover{{border-color:var(--ac);transform:translateY(-2px);
              box-shadow:0 10px 36px rgba(109,40,217,.2)}}
.rcard.removing{{opacity:0;transform:translateY(-12px) scale(.97);pointer-events:none}}
.archived-card{{opacity:.55;border-style:dashed;filter:grayscale(.3)}}
.rcard-hdr{{background:linear-gradient(135deg,var(--s2),var(--s));padding:16px 24px;
            display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--bd);flex-wrap:wrap;cursor:pointer;list-style:none}}
.rcard-hdr::-webkit-details-marker{{display:none}}
.rnum{{background:linear-gradient(135deg,var(--ac2),var(--ac));color:#fff;
       font-size:.78rem;font-weight:700;padding:4px 12px;border-radius:16px;flex-shrink:0}}
.rname{{font-size:1.15rem;font-weight:700;color:#fff;flex:1}}
.rcard-hdr-top{{display:flex;align-items:center;justify-content:space-between;width:100%;gap:10px}}
.rname-person{{font-size:1.15rem;font-weight:800;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.rcard-hdr-meta{{display:flex;align-items:center;justify-content:space-between;width:100%;gap:8px;flex-wrap:wrap}}
.rcard-meta-left{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.rcard-meta-pill{{font-size:.78rem;color:var(--mt);font-weight:600;display:inline-flex;align-items:center;gap:4px}}
.badge-group{{display:flex;gap:6px;align-items:center}}
.badge-tag{{background:rgba(167,139,250,.15);border:1px solid rgba(167,139,250,.3);color:var(--ac);font-size:.75rem;padding:3px 8px;border-radius:6px;font-weight:600}}
.expand-indicator{{color:var(--ac);font-size:.8rem;font-weight:700;margin-left:8px}}
.arch-tag{{background:rgba(251,191,36,.15);border:1px solid rgba(251,191,36,.3);
           color:var(--yw);font-size:.72rem;padding:3px 10px;border-radius:10px;flex-shrink:0}}
.profile-btn{{background:linear-gradient(135deg,#4c3d8f,var(--ac2));color:#fff;
              padding:8px 16px;border-radius:9px;font-size:.8rem;
              font-weight:600;text-decoration:none;transition:.2s;flex-shrink:0}}
.profile-btn:hover{{background:linear-gradient(135deg,var(--ac2),var(--ac));
                    transform:translateY(-1px);color:#fff}}
.copy-all-btn{{background:linear-gradient(135deg,var(--ac2),var(--ac3));color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:.75rem;font-weight:600;cursor:pointer;margin-bottom:6px;display:inline-block}}
.copy-all-btn:hover{{background:var(--ac2)}}
.copy-item-btn{{background:transparent;border:none;color:var(--mt);cursor:pointer;font-size:.8rem;padding:0 4px;margin-left:auto}}
.copy-item-btn:hover{{color:var(--ac)}}
.addr-row{{color:#c4caf0;font-size:.88rem;padding:6px 12px;
           background:rgba(255,255,255,.03);border-radius:7px;border:1px solid var(--bd);display:flex;align-items:center;gap:8px}}
.url-link{{color:var(--bl);font-size:.82rem;word-break:break-all;text-decoration:underline}}
.url-link:hover{{color:var(--ac)}}
.rcard-body{{padding:24px 28px;display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}}
.rinfo{{flex:1;min-width:320px;display:flex;flex-direction:column;gap:14px}}
.frow{{display:grid;grid-template-columns:140px 1fr;gap:12px;align-items:start;font-size:.92rem}}
.fl{{font-weight:700;color:var(--mt);font-size:.85rem;letter-spacing:.3px;padding-top:4px}}
.fv{{color:#fff;font-weight:600;line-height:1.5}}
.fname{{font-size:1.15rem;color:var(--ac);font-weight:700}}
.bg-report-row{{align-items:start}}
.bg-report-box{{background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:10px}}
.bg-report-hdr{{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}}
.bg-report-title{{font-weight:700;color:var(--ac);font-size:.88rem;display:flex;align-items:center;gap:6px}}
.bg-report-text{{color:var(--tx);font-size:.86rem;line-height:1.6;user-select:text;background:rgba(13,15,26,0.6);padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);word-break:break-word}}
.ss-wrap{{flex:0 0 320px;display:flex;flex-direction:column;align-items:center}}
.ss-thumb{{width:100%;border-radius:10px;border:2px solid var(--bd);cursor:pointer;
           transition:.2s;display:block}}
.ss-thumb:hover{{border-color:var(--ac);transform:scale(1.02);
                 box-shadow:0 6px 24px rgba(167,139,250,.3)}}
.ss-lbl{{color:var(--mt);font-size:.78rem;margin-top:8px;text-align:center}}
.ss-missing{{color:var(--mt);font-size:.82rem;padding:20px;text-align:center;
             background:var(--s2);border-radius:10px;border:1px dashed var(--bd)}}
.res-actions{{padding:14px 24px;border-top:1px solid var(--bd);
              display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.res-actions.arch-mode{{background:rgba(251,191,36,.04)}}
.res-btn{{padding:8px 16px;border-radius:8px;font-size:.8rem;font-weight:600;
          cursor:pointer;transition:.2s;border:1px solid;background:transparent}}
.arch-btn{{border-color:rgba(251,191,36,.5);color:var(--yw);}}
.arch-btn:hover{{background:rgba(251,191,36,.1)}}
.del-btn{{border-color:rgba(248,113,113,.5);color:var(--rd);}}
.del-btn:hover{{background:rgba(248,113,113,.1)}}
.unarch-btn{{border-color:rgba(96,165,250,.5);color:var(--bl);}}
.unarch-btn:hover{{background:rgba(96,165,250,.1)}}
.arch-label{{font-size:.8rem;color:var(--yw);flex:1}}
.arch-section{{margin-top:10px;border-radius:14px;border:1px dashed var(--bd);overflow:hidden}}
.arch-section summary{{padding:14px 20px;cursor:pointer;color:var(--mt);font-size:.9rem;
                       font-weight:600;list-style:none;background:var(--s2);
                       display:flex;align-items:center;gap:8px}}
.arch-section summary:hover{{color:var(--tx)}}
.arch-section summary span{{font-size:.75rem;font-weight:400;margin-left:auto;color:var(--mt)}}
.arch-inner{{padding:16px}}
.empty{{background:var(--s);border:2px dashed var(--bd);border-radius:14px;
        padding:50px;text-align:center;color:var(--mt);font-size:1rem}}
.search-ss-card{{background:var(--s);border:1px solid var(--bd);border-radius:16px;margin-bottom:28px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.3)}}
.search-ss-hdr{{background:linear-gradient(135deg,var(--s2),var(--s));padding:16px 24px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}}
.search-ss-title{{font-weight:700;color:#fff;font-size:1.05rem}}
.search-ss-sub{{font-size:.78rem;color:var(--mt);margin-top:2px}}
.search-ss-body{{position:relative;cursor:pointer;max-height:380px;overflow:hidden;background:#0d0f1a}}
.search-ss-img{{width:100%;display:block;opacity:.88;transition:.3s all}}
.search-ss-body:hover .search-ss-img{{opacity:1;transform:scale(1.005)}}
.search-ss-overlay{{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);background:rgba(13,15,26,.88);border:1px solid var(--ac);color:var(--ac);padding:8px 20px;border-radius:20px;font-size:.8rem;font-weight:700;backdrop-filter:blur(6px);pointer-events:none;box-shadow:0 4px 14px rgba(109,40,217,.3)}}
.toast{{position:fixed;bottom:24px;right:24px;background:var(--s);
        border:1px solid var(--bd);border-radius:12px;padding:12px 20px;
        font-size:.85rem;z-index:999;transform:translateY(60px);opacity:0;
        transition:.3s;max-width:280px}}
.toast.show{{transform:translateY(0);opacity:1}}
.toast.ok{{border-color:rgba(52,211,153,.4);color:var(--gn)}}
.toast.err{{border-color:rgba(248,113,113,.4);color:var(--rd)}}
.modal{{display:none;position:fixed;inset:0;background:#060813;z-index:99999;
        overflow-y:auto;overflow-x:hidden;padding:70px 20px 40px 20px;-webkit-overflow-scrolling:touch}}
.modal.open{{display:block}}
.modal-bar{{position:fixed;top:0;left:0;right:0;height:56px;background:rgba(19,23,46,0.96);border-bottom:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between;padding:0 24px;z-index:100000}}
.modal-bar-ttl{{font-size:.92rem;font-weight:700;color:#fff;display:flex;align-items:center;gap:8px}}
.modal-bar-actions{{display:flex;align-items:center;gap:12px}}
.modal-bar-btn{{background:var(--s2);border:1px solid var(--bd);color:var(--tx);padding:7px 16px;border-radius:7px;font-size:.82rem;font-weight:600;cursor:pointer;text-decoration:none;transition:.2s;display:inline-flex;align-items:center;gap:6px}}
.modal-bar-btn:hover{{background:var(--ac2);color:#fff;border-color:var(--ac)}}
.modal-wrap{{max-width:1040px;margin:10px auto 40px auto;text-align:center;position:relative}}
.modal-img{{width:100%;max-width:1040px;height:auto;margin:0 auto;display:none;border-radius:8px;border:1px solid var(--bd);box-shadow:0 12px 48px rgba(0,0,0,0.9);background:#fff}}
.modal-loading{{display:none;padding:40px 20px;color:var(--ac);font-weight:700;font-size:1rem}}
.confirm-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);
                  z-index:8888;justify-content:center;align-items:center}}
.confirm-overlay.open{{display:flex}}
.confirm-box{{background:var(--s);border:1px solid var(--rd);border-radius:18px;
              padding:32px 36px;max-width:380px;text-align:center}}
.confirm-box h3{{color:#fff;margin-bottom:10px;font-size:1.1rem}}
.confirm-box p{{color:var(--mt);font-size:.88rem;margin-bottom:24px;line-height:1.6}}
.confirm-btns{{display:flex;gap:12px;justify-content:center}}
.cb-cancel{{padding:10px 24px;border-radius:9px;border:1px solid var(--bd);
            background:var(--s2);color:var(--tx);cursor:pointer;font-size:.9rem}}
.cb-delete{{padding:10px 24px;border-radius:9px;border:none;
            background:linear-gradient(135deg,#b91c1c,var(--rd));color:#fff;
            cursor:pointer;font-size:.9rem;font-weight:700}}
.collapse-toolbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px;flex-wrap:wrap;background:var(--s);padding:12px 20px;border-radius:12px;border:1px solid var(--bd)}}
.tool-btn{{background:var(--s2);border:1px solid var(--bd);color:var(--ac);padding:7px 15px;border-radius:8px;font-size:.82rem;font-weight:700;cursor:pointer;transition:.2s}}
.tool-btn:hover{{background:var(--ac2);color:#fff;border-color:var(--ac)}}
.view-pref{{display:flex;align-items:center;gap:12px;font-size:.82rem;color:var(--mt)}}
.view-pref label{{display:inline-flex;align-items:center;gap:6px;cursor:pointer;color:var(--tx);font-weight:600}}
.view-pref input[type="radio"]{{accent-color:var(--ac);cursor:pointer}}
.back-to-top{{position:fixed;bottom:28px;right:28px;z-index:999;background:linear-gradient(135deg,var(--ac2),var(--ac));color:#fff;border:none;padding:11px 18px;border-radius:30px;font-size:.85rem;font-weight:700;cursor:pointer;box-shadow:0 6px 20px rgba(109,40,217,.4);transition:all .3s ease;opacity:0;pointer-events:none;display:flex;align-items:center;gap:6px}}
.back-to-top.visible{{opacity:1;pointer-events:auto;transform:translateY(0)}}
.back-to-top:hover{{transform:translateY(-3px);box-shadow:0 10px 25px rgba(109,40,217,.6)}}
.share-modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;justify-content:center;align-items:center;padding:20px;backdrop-filter:blur(6px)}}
.share-modal.open{{display:flex}}
.share-box{{background:var(--s);border:1px solid var(--bd);border-radius:18px;padding:26px;max-width:480px;width:100%;box-shadow:0 10px 30px rgba(0,0,0,.5)}}
.share-hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}}
.share-hdr h3{{color:#fff;font-size:1.15rem}}
.share-close{{color:var(--mt);font-size:1.4rem;cursor:pointer}}
.share-close:hover{{color:#fff}}
.share-box p{{color:var(--mt);font-size:.85rem;margin-bottom:18px;line-height:1.5}}
.share-input-wrap{{display:flex;gap:8px;margin-bottom:20px}}
.share-input-wrap input{{flex:1;background:var(--s2);border:1px solid var(--bd);border-radius:8px;padding:10px 14px;color:#fff;font-size:.85rem;outline:none}}
.share-copy-btn{{background:linear-gradient(135deg,var(--ac2),var(--ac));color:#fff;border:none;border-radius:8px;padding:0 18px;font-weight:700;cursor:pointer;font-size:.85rem}}
.share-socials{{display:flex;gap:10px;flex-wrap:wrap}}
.soc-btn{{flex:1;min-width:110px;text-align:center;padding:10px;border-radius:8px;font-size:.82rem;font-weight:700;color:#fff;text-decoration:none;transition:.2s}}
.soc-wa{{background:#16a34a}}
.soc-tg{{background:#0284c7}}
.soc-x{{background:#0f172a;border:1px solid var(--bd)}}
.soc-btn:hover{{opacity:.9;transform:translateY(-1px)}}
@media (max-width:768px){{
  .topbar{{flex-direction:column;align-items:stretch;gap:12px;padding:14px 16px}}
  .topbar > div:last-child{{width:100%;justify-content:flex-start;display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px}}
  .social-top-btn{{width:100%;text-align:center;justify-content:center;padding:7px 10px;font-size:.78rem}}
  /* Compact & beautiful stats bar on mobile */
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:6px;padding:10px 12px}}
  .sp{{padding:8px 10px}}
  .sv{{font-size:1.15rem}}
  .sl{{font-size:.65rem}}
  .content{{padding:14px 10px}}
  .search-ss-hdr{{padding:12px 14px}}
  .search-ss-title{{font-size:.92rem}}
  .search-ss-body{{max-height:180px}}
  .search-ss-overlay{{font-size:.72rem;padding:6px 12px;width:90%;text-align:center}}
  .rcard{{margin-bottom:14px;border-radius:12px}}
  .rcard-hdr{{padding:12px 14px;gap:8px;flex-direction:column;align-items:stretch}}
  .rname-person{{font-size:1.05rem}}
  .rcard-meta-pill{{font-size:.74rem}}
  .badge-tag{{font-size:.7rem;padding:2px 6px}}
  .expand-indicator{{font-size:.75rem}}
  .rcard-body{{flex-direction:column;padding:14px 12px;gap:14px}}
  .rinfo{{min-width:100%}}
  .frow{{grid-template-columns:1fr;gap:4px}}
  .fl{{font-size:.76rem}}
  .fv{{font-size:.85rem}}
  .ss-wrap{{width:100%;flex:1 1 100%}}
  .modal{{padding:54px 8px 24px 8px}}
  .modal-bar{{padding:0 10px;height:48px}}
  .modal-bar-ttl span{{display:none}}
  .modal-bar-btn{{padding:6px 8px;font-size:.72rem}}
  .modal-wrap{{max-width:100%;margin:4px auto 16px auto}}
  .modal-img{{width:100%;max-width:100%}}
}}
{lead_ro_css}
</style></head><body>
<div class="topbar">
  {back_btn_html}
  <div class="ttl"><h1>🔍 {lead_name}</h1>
    <p>Location: {location or "Not specified"} · {ts}</p></div>
  <div style="display:flex;gap:8px;margin-left:auto;flex-wrap:wrap">
    {lead_top_actions}
  </div>
</div>
<div class="stats">
  <div class="sp hi"><div class="sv" id="active-count">{active_count}</div><div class="sl">Active Results</div></div>
  <div class="sp"><div class="sv" style="color:{'var(--gn)' if results else 'var(--rd)'}">
    {'✓ Found' if results else '✗ None'}</div><div class="sl">Status</div></div>
  <div class="sp"><div class="sv" style="font-size:.9rem">{location or 'N/A'}</div>
    <div class="sl">Location</div></div>
  <div class="sp"><div class="sv" style="font-size:.85rem">{social_stat_html}</div>
    <div class="sl">Social Link</div></div>
  <div class="sp"><div class="sv" style="font-size:.85rem">{email_stat_html}</div>
    <div class="sl">Input Email</div></div>
  <div class="sp"><div class="sv" style="font-size:.85rem">{phone_stat_html}</div>
    <div class="sl">Input Phone</div></div>
</div>
<div class="content">
{search_ss_section}
{f"""<div class="collapse-toolbar">
  <div style="display:flex;align-items:center;gap:10px">
    <button class="tool-btn" onclick="setAllCards(false)">▸ Collapse All</button>
    <button class="tool-btn" onclick="setAllCards(true)">▾ Expand All</button>
  </div>
  <div class="view-pref">
    <span>Default View:</span>
    <label><input type="radio" name="default_view_pref" value="collapsed" id="pref-collapsed" onchange="setDefaultPref('collapsed')"> Collapsed</label>
    <label><input type="radio" name="default_view_pref" value="expanded" id="pref-expanded" onchange="setDefaultPref('expanded')"> Expanded</label>
  </div>
</div>""" if results else ""}
{cards_html}
</div>
<div class="toast" id="toast"></div>
<div class="modal" id="modal" onclick="if(event.target===this||event.target.classList.contains('modal-wrap'))closeModal()">
  <div class="modal-bar">
    <div class="modal-bar-ttl">📸 <span>Verified Public Record Intelligence Screenshot</span></div>
    <div class="modal-bar-actions">
      <a id="modal-dl-btn" href="#" download="screenshot.png" class="modal-bar-btn" target="_blank">⬇ Download Original</a>
      <button class="modal-bar-btn" onclick="closeModal()" style="background:#dc2626;border-color:#ef4444;color:#fff">✕ Close</button>
    </div>
  </div>
  <div class="modal-wrap">
    <div id="modal-loading" class="modal-loading">⏳ Loading authentic screenshot...</div>
    <img id="modal-img" src="" class="modal-img" onclick="event.stopPropagation()">
  </div>
</div>
{lead_modals_html}

<script>
const JOB_ID   = '{job_id}';
const LEAD_IDX = {lead_idx};
const API      = (window.location.protocol.startsWith('http') ? window.location.origin : 'http://localhost:{PORT}');
let _pendingDeleteIdx = null;

window.addEventListener('scroll', () => {{
  const b = document.getElementById('back-to-top-btn');
  if (b) {{
    if (window.scrollY > 280) b.classList.add('visible');
    else b.classList.remove('visible');
  }}
}});

let _reportShareToken = '{share_token or ""}';

async function openShareModal() {{
  document.getElementById('share-modal').classList.add('open');
  updateLeadShareLink();
  const inp = document.getElementById('share-url-input');
  if (!_reportShareToken) {{
    inp.value = 'Generating secure share link...';
    try {{
      const r = await fetch(API + '/api/jobs/' + JOB_ID + '/share', {{method: 'POST'}});
      const d = await r.json();
      if (d.share_token) {{
        _reportShareToken = d.share_token;
        updateLeadShareLink();
      }}
    }} catch(e) {{}}
  }}
}}

function updateLeadShareLink() {{
  const inp = document.getElementById('share-url-input');
  let url = window.location.href;
  if (_reportShareToken) {{
    const folder = '{lead_safe}';
    url = window.location.origin + '/share/lead/' + _reportShareToken + '/' + folder + '/report.html';
  }}
  inp.value = url;
  const encodedUrl = encodeURIComponent(url);
  const text = encodeURIComponent('LeadsOSINT Report: {lead_name}');
  document.getElementById('share-wa').href = 'https://api.whatsapp.com/send?text=' + text + '%20' + encodedUrl;
  document.getElementById('share-tg').href = 'https://t.me/share/url?url=' + encodedUrl + '&text=' + text;
}}

async function resetLeadShareLink() {{
  if (!confirm('Are you sure you want to reset this share link?\\n\\n⚠️ Anyone with the old share link will immediately lose access (404). A brand new link will be generated.')) return;
  const inp = document.getElementById('share-url-input');
  inp.value = 'Revoking & generating new link...';
  try {{
    const r = await fetch(API + '/api/jobs/' + JOB_ID + '/share/reset', {{method: 'POST'}});
    const d = await r.json();
    if (d.share_token) {{
      _reportShareToken = d.share_token;
      updateLeadShareLink();
      showToast('Old share link revoked! New secure link active.', 'ok');
    }} else {{
      showToast(d.error || 'Failed to reset link', 'err');
      updateLeadShareLink();
    }}
  }} catch(e) {{
    showToast('Network error resetting link', 'err');
    updateLeadShareLink();
  }}
}}
function closeShareModal() {{
  document.getElementById('share-modal').classList.remove('open');
}}
function copyShareLink() {{
  const input = document.getElementById('share-url-input');
  copySingle(input.value, 'Share Link');
}}

function copySingle(val, label) {{
  navigator.clipboard.writeText(val).then(() => {{
    showToast(label + ' copied to clipboard!', 'ok');
  }}).catch(() => {{
    const ta = document.createElement('textarea');
    ta.value = val;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast(label + ' copied!', 'ok');
  }});
}}

function copyList(arr, label) {{
  if (!arr || !arr.length) return;
  const text = arr.join('\\\\n');
  navigator.clipboard.writeText(text).then(() => {{
    showToast(arr.length + ' ' + label + ' copied to clipboard!', 'ok');
  }}).catch(() => {{
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast(arr.length + ' ' + label + ' copied!', 'ok');
  }});
}}

function copyBgReport(idx) {{
  const el = document.getElementById('bg-report-' + idx);
  if (el) {{
    copySingle(el.innerText || el.textContent, 'Free Background Report');
  }}
}}

function openModal(src){{
  const m = document.getElementById('modal');
  const img = document.getElementById('modal-img');
  const loader = document.getElementById('modal-loading');
  const dl = document.getElementById('modal-dl-btn');
  
  if (dl) dl.href = src;
  loader.textContent = '⏳ Loading authentic screenshot...';
  loader.style.display = 'block';
  img.style.display = 'none';
  m.classList.add('open');
  document.body.style.overflow = 'hidden';
  
  img.onload = () => {{
    loader.style.display = 'none';
    img.style.display = 'block';
  }};
  img.onerror = () => {{
    loader.textContent = '⚠️ Screenshot could not be loaded.';
  }};
  img.src = src;
}}

function closeModal(){{
  const m = document.getElementById('modal');
  if (m) m.classList.remove('open');
  document.body.style.overflow = '';
}}

document.addEventListener('keydown',e=>{{
  if(e.key==='Escape'){{
    closeModal();
    closeConfirm();
  }}
}});

function showToast(msg, type='ok'){{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(()=>t.classList.remove('show'), 3500);
}}

function confirmDelete(idx){{
  _pendingDeleteIdx = idx;
  document.getElementById('confirm-overlay').classList.add('open');
}}
function closeConfirm(){{
  document.getElementById('confirm-overlay').classList.remove('open');
  _pendingDeleteIdx = null;
}}
async function doDelete(){{
  const idx = _pendingDeleteIdx;
  closeConfirm();
  if (idx === null || !JOB_ID) return;
  await deleteResult(idx);
}}
async function deleteResult(idx){{
  if (!JOB_ID) {{ showToast('No job ID — open via dashboard', 'err'); return; }}
  const card = document.getElementById('rcard-' + idx);
  if (card) card.classList.add('removing');
  try {{
    const r = await fetch(`${{API}}/api/jobs/${{JOB_ID}}/leads/${{LEAD_IDX}}/results/${{idx}}/delete`,
                          {{method:'POST'}});
    const d = await r.json();
    if (r.ok) {{
      setTimeout(()=>{{ if(card) card.remove(); updateCount(-1); }}, 250);
      showToast('Result deleted permanently', 'ok');
    }} else {{
      if (card) card.classList.remove('removing');
      showToast(d.error || 'Delete failed', 'err');
    }}
  }} catch(e) {{
    if (card) card.classList.remove('removing');
    showToast('Network error: ' + (e.message || e), 'err');
  }}
}}
async function archiveResult(idx){{
  if (!JOB_ID) {{ showToast('No job ID — open via dashboard', 'err'); return; }}
  const card = document.getElementById('rcard-' + idx);
  if (card) {{
    card.style.transition = '0.25s all';
    card.style.opacity = '0.3';
    card.style.transform = 'scale(0.98)';
  }}
  showToast('Updating status...', 'ok');
  try {{
    const r = await fetch(`${{API}}/api/jobs/${{JOB_ID}}/leads/${{LEAD_IDX}}/results/${{idx}}/archive`,
                          {{method:'POST'}});
    const d = await r.json();
    if (r.ok) {{
      showToast('Marked as Not This Person', 'ok');
      setTimeout(()=>{{
        const u = new URL(window.location.href);
        u.searchParams.set('_t', Date.now());
        window.location.replace(u.href);
      }}, 300);
    }} else {{
      if (card) {{ card.style.opacity = '1'; card.style.transform = 'none'; }}
      showToast(d.error || 'Archive failed', 'err');
    }}
  }} catch(e) {{
    if (card) {{ card.style.opacity = '1'; card.style.transform = 'none'; }}
    showToast('Network error: ' + (e.message || e), 'err');
  }}
}}
async function unarchiveResult(idx){{
  if (!JOB_ID) return;
  const card = document.getElementById('rcard-' + idx);
  if (card) {{
    card.style.transition = '0.25s all';
    card.style.opacity = '0.3';
  }}
  showToast('Restoring result...', 'ok');
  try {{
    const r = await fetch(`${{API}}/api/jobs/${{JOB_ID}}/leads/${{LEAD_IDX}}/results/${{idx}}/unarchive`,
                          {{method:'POST'}});
    const d = await r.json();
    if (r.ok) {{
      showToast('Result restored', 'ok');
      setTimeout(()=>{{
        const u = new URL(window.location.href);
        u.searchParams.set('_t', Date.now());
        window.location.replace(u.href);
      }}, 300);
    }} else {{
      if (card) {{ card.style.opacity = '1'; card.style.transform = 'none'; }}
      showToast(d.error || 'Restore failed', 'err');
    }}
  }} catch(e) {{
    if (card) {{ card.style.opacity = '1'; card.style.transform = 'none'; }}
    showToast('Network error: ' + (e.message || e), 'err');
  }}
}}
function setAllCards(expanded) {{
  document.querySelectorAll('details.rcard:not(.archived-card)').forEach(d => d.open = expanded);
}}
function setDefaultPref(pref) {{
  localStorage.setItem('leadsosint_default_view', pref);
  showToast('Default view saved: ' + (pref === 'expanded' ? 'Expanded' : 'Collapsed'), 'ok');
  setAllCards(pref === 'expanded');
}}
(function() {{
  const pref = localStorage.getItem('leadsosint_default_view') || 'collapsed';
  if (pref === 'expanded') {{
    const el = document.getElementById('pref-expanded');
    if (el) el.checked = true;
    setAllCards(true);
  }} else {{
    const el = document.getElementById('pref-collapsed');
    if (el) el.checked = true;
    setAllCards(false);
  }}
}})();
function updateCount(delta){{
  const el = document.getElementById('active-count');
  if (el) el.textContent = Math.max(0, parseInt(el.textContent||'0') + delta);
}}
async function redoReportLead(jobId, idx){{
  if (!confirm('Re-run search for this lead now?')) return;
  try {{
    const r = await fetch(`${{API}}/api/jobs/${{jobId}}/leads/${{idx}}/retry`, {{method:'POST'}});
    if (r.ok) {{
      showToast('Re-starting search...', 'ok');
      setTimeout(()=>location.reload(), 2000);
    }} else {{
      const d = await r.json().catch(()=>({{}}));
      showToast(d.error || 'Retry error', 'err');
    }}
  }} catch(e) {{
    showToast('Network error: ' + (e.message || e), 'err');
  }}
}}
window.addEventListener('scroll', () => {{
  const b = document.getElementById('btt-btn');
  if (b) b.style.display = (window.scrollY > 200) ? 'inline-flex' : 'none';
}});
</script>
<button id="btt-btn" style="position:fixed;bottom:24px;right:24px;z-index:999;background:rgba(30,41,59,.92);border:1px solid var(--ac);color:#fff;padding:9px 16px;border-radius:30px;font-size:.8rem;font-weight:700;display:none;align-items:center;gap:6px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.6);backdrop-filter:blur(8px);transition:.2s" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="Back to top">↑ Back to Top</button>
</body></html>'''


def build_job_index(job, is_shared=False, share_token=None):
    if not is_shared:
        if not job.get('share_token'):
            try:
                job['share_token'] = database.get_or_create_share_token(
                    job['id'], job.get('user_id', 1), job.get('username', 'admin'),
                    job.get('name', job['id']), job.get('status', 'complete'),
                    job.get('total', 0), job.get('done', 0), job.get('folder', '')
                )
            except Exception:
                pass
    cards = ''
    for idx, lead in enumerate(job.get('leads', [])):
        status  = lead.get('status', 'queued')
        count   = lead.get('count', 0)
        folder  = lead.get('folder_name', '')
        social  = lead.get('social_link', '')
        icon    = {'done': '✅', 'none': '⚪', 'failed': '❌', 'running': '⚙️',
                   'cancelled': '✕', 'queued': '⏳'}.get(status, '⏳')
        cls     = 'found' if (status == 'done' and count > 0) else ('none' if status != 'running' else 'running')
        if is_shared and share_token:
            link = f'/share/{share_token}/{folder}/report.html' if folder else '#'
        else:
            link = f'/results/{job["id"]}/{folder}/report.html' if folder else '#'

        soc_lbl = _get_social_label(social)
        soc_tag = f'<div style="font-size:.75rem;color:var(--ac);margin-top:4px">🔗 {soc_lbl}</div>' if soc_lbl else ''

        # In shared mode: STRICTLY NO action buttons (no Re-do, no edit/update)
        redo_btn = ''
        if not is_shared:
            redo_btn = f'<button class="redo-lead-btn" onclick="redoLead(\'{job["id"]}\', {idx})" title="Re-run search for this lead">🔄 Re-do</button>'

        cards  += f'''
<div class="lcard {cls}">
  <a href="{link}" style="display:flex;align-items:center;gap:16px;flex:1;text-decoration:none;color:inherit;min-width:0" {"" if link != "#" else 'onclick="return false"'}>
    <div class="lc-icon">{icon}</div>
    <div class="lc-info">
      <div class="lc-name">{lead["name"]}</div>
      <div class="lc-loc">{lead.get("location") or "No location"}</div>
      {soc_tag}
    </div>
    <div class="lc-count">
      <div class="lc-num">{count}</div>
      <div class="lc-lbl">results</div>
    </div>
  </a>
  {redo_btn}
</div>'''

    total       = len(job.get('leads', []))
    done_count  = sum(1 for l in job.get('leads', []) if l.get('status') == 'done')
    fail_count  = sum(1 for l in job.get('leads', []) if l.get('status') == 'failed')
    total_res   = sum(l.get('count', 0) for l in job.get('leads', []))
    job_name    = job.get('name', job['id'])
    ts          = datetime.now().strftime('%B %d, %Y · %I:%M %p')

    if is_shared:
        top_nav = '<span class="back" style="pointer-events:none;background:rgba(167,139,250,0.12);border-color:rgba(167,139,250,0.3);color:var(--ac);font-weight:600">⚡ Read-Only Dossier</span>'
        redo_script = ''
        redo_css = ''
        share_modal_html = ''
    else:
        top_nav = f'''<div class="hero-actions-bar" style="display:flex;align-items:center;gap:10px;margin-left:auto;flex-wrap:wrap">
          <button class="share-report-btn" onclick="openReportShareModal()" title="Share Dossier Report">🔗 Share Report</button>
          <a href="/" class="back">← Dashboard</a>
        </div>'''
        redo_css = '''.redo-lead-btn{background:var(--s2);border:1px solid var(--bd);color:var(--ac);padding:6px 12px;
                border-radius:8px;font-size:.78rem;font-weight:700;cursor:pointer;transition:.2s;flex-shrink:0}
.redo-lead-btn:hover{background:var(--ac2);color:#fff;border-color:var(--ac)}'''
        share_modal_html = f'''
<div class="share-modal-overlay" id="report-share-modal" onclick="if(event.target===this)closeReportShareModal()">
  <div class="share-modal-box">
    <div class="share-modal-hdr">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:1.3rem">🔗</span>
        <h3 style="font-size:1.15rem;font-weight:700">Share Public Dossier</h3>
      </div>
      <span class="share-modal-close" onclick="closeReportShareModal()">✕</span>
    </div>
    <div class="share-modal-body">
      <p style="color:var(--mt);font-size:.85rem;line-height:1.5;margin-bottom:14px">
        Anyone with this link can view this dossier in <strong>read-only mode</strong>.<br>
        <span style="color:var(--ac);font-weight:600">⚡ Active while account is in good standing.</span>
      </p>
      
      <div class="share-input-row" style="display:flex;gap:8px;margin-bottom:12px">
        <input type="text" id="report-share-input" readonly value="" placeholder="Generating link..." style="flex:1;background:var(--s2);border:1px solid var(--bd);border-radius:8px;padding:9px 12px;color:var(--tx);font-size:.85rem">
        <button class="modal-btn-act" onclick="copyReportShareLink()" style="background:var(--ac2);border:1px solid var(--ac);color:#fff;padding:9px 16px;border-radius:8px;font-weight:700;cursor:pointer">Copy</button>
      </div>

      <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
        <button class="modal-btn-act" onclick="resetReportShareLink()" style="flex:1;min-width:140px;background:rgba(239,68,68,0.15);border:1px solid #ef4444;color:#fca5a5;padding:8px 12px;border-radius:8px;font-size:.82rem;font-weight:700;cursor:pointer" title="Revokes old share link and generates a brand new one">🔄 Reset / Revoke Link</button>
      </div>

      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <a id="rep-sh-wa" href="#" target="_blank" class="modal-btn-act" style="flex:1;text-align:center;text-decoration:none;background:#16a34a;color:#fff;padding:9px 14px;border-radius:8px;font-size:.85rem;font-weight:700">📱 WhatsApp</a>
        <a id="rep-sh-tg" href="#" target="_blank" class="modal-btn-act" style="flex:1;text-align:center;text-decoration:none;background:#0284c7;color:#fff;padding:9px 14px;border-radius:8px;font-size:.85rem;font-weight:700">✈️ Telegram</a>
      </div>
    </div>
  </div>
</div>'''
        redo_script = f'''
const JOB_ID = \'{job["id"]}\';
let currentShareToken = \'{job.get("share_token", "")}\';

function openReportShareModal() {{
  const modal = document.getElementById('report-share-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  modal.classList.add('open');
  updateShareLinks();
  if (!currentShareToken) {{
    const inp = document.getElementById('report-share-input');
    if (inp) inp.value = 'Generating share link...';
    fetch('/api/jobs/' + JOB_ID + '/share', {{method: 'POST'}})
      .then(r => r.json())
      .then(d => {{
        if (d.share_token) {{
          currentShareToken = d.share_token;
          updateShareLinks();
        }}
      }}).catch(() => {{}});
  }}
}}

function updateShareLinks() {{
  const inp = document.getElementById('report-share-input');
  const url = window.location.origin + '/share/' + currentShareToken;
  inp.value = url;
  const enc = encodeURIComponent(url);
  const txt = encodeURIComponent('LeadsOSINT Dossier: {job_name}');
  const wa = document.getElementById('rep-sh-wa');
  const tg = document.getElementById('rep-sh-tg');
  if (wa) wa.href = 'https://api.whatsapp.com/send?text=' + txt + '%20' + enc;
  if (tg) tg.href = 'https://t.me/share/url?url=' + enc + '&text=' + txt;
}}

function closeReportShareModal() {{
  const m = document.getElementById('report-share-modal');
  if (m) {{
    m.style.display = 'none';
    m.classList.remove('open');
  }}
}}

function copyReportShareLink() {{
  const inp = document.getElementById('report-share-input');
  navigator.clipboard.writeText(inp.value).then(() => {{
    alert('Share link copied to clipboard!');
  }}).catch(() => {{
    inp.select();
    document.execCommand('copy');
    alert('Share link copied!');
  }});
}}

async function resetReportShareLink() {{
  const msg = 'Are you sure you want to reset this share link? Anyone with the old link will lose access.';
  if (!confirm(msg)) return;
  const inp = document.getElementById('report-share-input');
  inp.value = 'Revoking old link & generating new...';
  try {{
    const r = await fetch('/api/jobs/' + JOB_ID + '/share/reset', {{method: 'POST'}});
    const d = await r.json();
    if (d.share_token) {{
      currentShareToken = d.share_token;
      updateShareLinks();
      alert('Old share link revoked! New secure link generated.');
    }} else {{
      alert(d.error || 'Failed to reset share link');
      updateShareLinks();
    }}
  }} catch(e) {{
    alert('Network error resetting share link');
    updateShareLinks();
  }}
}}

async function redoLead(jobId, idx) {{
  if (!confirm('Re-run search for this single lead now? (Uses 1 lead credit)')) return;
  const api = (window.location.protocol.startsWith('http') ? window.location.origin : 'http://localhost:{PORT}');
  try {{
    const r = await fetch(api + '/api/jobs/' + jobId + '/leads/' + idx + '/retry', {{method: 'POST'}});
    if (r.ok) {{
      alert('Re-starting search for lead... Page will refresh.');
      setTimeout(() => location.reload(), 1500);
    }} else {{
      const d = await r.json().catch(()=>({{}}));
      alert(d.error || 'Error triggering retry');
    }}
  }} catch(e) {{
    alert('Network error triggering retry');
  }}
}}
'''

    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{job_name} — LeadsOSINT</title>
<style>
:root{{--bg:#0d0f1a;--s:#1a1d3a;--s2:#22264a;--bd:#3a3f7a;--ac:#a78bfa;
      --ac2:#6d28d9;--tx:#e0e6ff;--mt:#8b95c4;--gn:#34d399}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh}}
.hero{{background:linear-gradient(135deg,#1a1d3a,#0d0f1a);border-bottom:1px solid var(--bd);
       padding:40px 50px}}
.htop{{display:flex;align-items:center;gap:16px;margin-bottom:24px}}
.logo{{font-size:2rem}}
h1{{font-size:2rem;font-weight:800;background:linear-gradient(135deg,var(--ac),#60a5fa);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent}}
p{{color:var(--mt);font-size:.85rem;margin-top:5px}}
.back{{background:var(--s2);border:1px solid var(--bd);color:var(--ac);padding:9px 18px;
       border-radius:9px;font-size:.85rem;text-decoration:none;display:inline-flex;align-items:center}}
.back:hover{{border-color:var(--ac);background:var(--ac2);color:#fff}}
.share-report-btn{{background:linear-gradient(135deg,#0284c7,#38bdf8);border:1px solid rgba(56,189,248,0.4);
       color:#fff;padding:9px 18px;border-radius:9px;font-size:.85rem;font-weight:700;cursor:pointer;
       display:inline-flex;align-items:center;gap:6px;transition:all .2s ease;white-space:nowrap}}
.share-report-btn:hover{{background:linear-gradient(135deg,#0369a1,#0284c7);box-shadow:0 4px 14px rgba(2,132,199,0.4);transform:translateY(-1px)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;max-width:700px}}
.st{{background:rgba(255,255,255,.04);border:1px solid var(--bd);border-radius:12px;
     padding:18px 22px;text-align:center;transition:.2s}}
.st:hover{{border-color:var(--ac)}}
.sv{{font-size:1.8rem;font-weight:800;color:var(--ac)}}
.sl{{font-size:.72rem;color:var(--mt);text-transform:uppercase;letter-spacing:.5px;margin-top:5px}}
.grid{{padding:36px 50px;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
@media (max-width:768px){{
  .hero{{padding:24px 16px}}
  .htop{{flex-direction:column;align-items:flex-start;gap:12px}}
  h1{{font-size:1.35rem;word-break:break-word}}
  .hero-actions-bar{{width:100%;margin-left:0 !important;display:flex;gap:8px}}
  .share-report-btn, .back{{flex:1;text-align:center;justify-content:center;margin-left:0 !important;padding:10px 12px;font-size:.82rem}}
  .stats{{grid-template-columns:repeat(2,1fr);gap:8px;width:100%}}
  .st{{padding:12px 14px}}
  .sv{{font-size:1.4rem}}
  .grid{{padding:16px 12px;grid-template-columns:1fr;gap:10px}}
  .lcard{{padding:14px 14px;flex-wrap:wrap}}
  .lc-info{{min-width:130px}}
  .redo-lead-btn{{margin-left:auto}}
}}
.lcard{{background:var(--s);border:1px solid var(--bd);border-radius:14px;padding:16px 20px;
        display:flex;align-items:center;gap:14px;color:inherit;transition:.25s;position:relative}}
.lcard:hover{{transform:translateY(-3px);box-shadow:0 12px 40px rgba(109,40,217,.2);background:var(--s2)}}
.lcard.found{{border-left:4px solid var(--ac)}}
.lcard.none{{border-left:4px solid var(--bd);opacity:.75}}
.lcard.running{{border-left:4px solid var(--gn);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{box-shadow:0 0 0 0 rgba(52,211,153,.2)}}
                  50%{{box-shadow:0 0 0 6px rgba(52,211,153,.0)}}}}
.lc-icon{{font-size:1.7rem;flex-shrink:0}}
.lc-info{{flex:1;min-width:0}}
.lc-name{{font-size:1rem;font-weight:700;color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.lc-loc{{font-size:.78rem;color:var(--mt);margin-top:4px}}
.lc-count{{text-align:center;flex-shrink:0;margin-right:8px}}
.lc-num{{font-size:1.6rem;font-weight:800;color:var(--ac)}}
.lc-lbl{{font-size:.68rem;color:var(--mt);text-transform:uppercase;letter-spacing:.5px}}
{redo_css}
.footer{{text-align:center;padding:36px;color:var(--mt);font-size:.82rem;border-top:1px solid var(--bd)}}
.share-modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(4px);z-index:9999;align-items:center;justify-content:center;padding:16px}}
.share-modal-overlay.open{{display:flex}}
.share-modal-box{{background:var(--s);border:1px solid var(--bd);border-radius:16px;max-width:480px;width:100%;padding:24px;box-shadow:0 20px 40px rgba(0,0,0,0.5);animation:fadeInModal .2s ease}}
.share-modal-hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}}
.share-modal-close{{cursor:pointer;color:var(--mt);font-size:1.2rem;padding:4px 8px;border-radius:6px}}
.share-modal-close:hover{{color:#fff;background:var(--s2)}}
@keyframes fadeInModal{{from{{opacity:0;transform:scale(.95)}}to{{opacity:1;transform:scale(1)}}}}
</style></head><body>
<div class="hero">
  <div class="htop">
    <div class="logo">🔍</div>
    <div><h1>{job_name}</h1><p>Job ID: {job["id"]} · Generated: {ts}</p></div>
    {top_nav}
  </div>
  <div class="stats">
    <div class="st"><div class="sv">{total}</div><div class="sl">Total Leads</div></div>
    <div class="st"><div class="sv">{done_count}</div><div class="sl">Found</div></div>
    <div class="st"><div class="sv">{fail_count}</div><div class="sl">Failed</div></div>
    <div class="st"><div class="sv">{total_res}</div><div class="sl">Total Results</div></div>
  </div>
</div>
<div class="grid">{cards}</div>
<div class="footer">LeadsOSINT · Public Records Intelligence Engine</div>
<button id="btt-btn" style="position:fixed;bottom:24px;right:24px;z-index:999;background:rgba(30,41,59,.92);border:1px solid var(--ac);color:#fff;padding:9px 16px;border-radius:30px;font-size:.8rem;font-weight:700;display:none;align-items:center;gap:6px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.6);backdrop-filter:blur(8px);transition:.2s" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="Back to top">↑ Back to Top</button>
{share_modal_html}
<script>
window.addEventListener('scroll', () => {{
  const b = document.getElementById('btt-btn');
  if (b) b.style.display = (window.scrollY > 200) ? 'inline-flex' : 'none';
}});
{redo_script}
window.openReportShareModal = typeof openReportShareModal !== 'undefined' ? openReportShareModal : null;
window.closeReportShareModal = typeof closeReportShareModal !== 'undefined' ? closeReportShareModal : null;
window.copyReportShareLink = typeof copyReportShareLink !== 'undefined' ? copyReportShareLink : null;
window.resetReportShareLink = typeof resetReportShareLink !== 'undefined' ? resetReportShareLink : null;
window.redoLead = typeof redoLead !== 'undefined' ? redoLead : null;
</script>
</body></html>'''

def regenerate_index(job_id):
    job = jobs.get(job_id)
    if not job:
        return
    if not job.get('folder') and os.path.exists(OUT_DIR):
        for entry in os.listdir(OUT_DIR):
            if job_id.upper() in entry.upper():
                job['folder'] = os.path.join(OUT_DIR, entry)
                break
    if not job.get('folder'):
        return
    jfolder = job.get('folder', '')
    for lead in job.get('leads', []):
        lfolder = lead.get('folder_name', '')
        if jfolder and lfolder:
            djson = os.path.join(jfolder, lfolder, 'data.json')
            if not os.path.exists(djson) and os.path.exists(OUT_DIR):
                for entry in os.listdir(OUT_DIR):
                    if job_id in entry:
                        c = os.path.join(OUT_DIR, entry, lfolder, 'data.json')
                        if os.path.exists(c):
                            djson = c
                            break
            if os.path.exists(djson):
                try:
                    with open(djson, 'r', encoding='utf-8') as f:
                        dj = json.load(f)
                        res_list = dj.get('results', [])
                        lead['count'] = len(res_list)
                        lead['status'] = 'done' if len(res_list) > 0 else 'none'
                except Exception:
                    pass
            elif os.path.exists(os.path.join(jfolder, lfolder, 'report.html')):
                if lead.get('status') in ('running', 'queued'):
                    lead['status'] = 'done' if lead.get('count', 0) > 0 else 'none'
    
    all_done = all(l.get('status') in ('done', 'none', 'failed', 'cancelled') for l in job.get('leads', []))
    if all_done and len(job.get('leads', [])) > 0:
        job['done'] = len(job['leads'])
        job['status'] = 'complete'

    html = build_job_index(job)
    idx  = os.path.join(job['folder'], 'index.html')
    try:
        with open(idx, 'w', encoding='utf-8') as f:
            f.write(html)
        job['index_path'] = idx
    except Exception as e:
        print(f"  regenerate_index error: {e}")
    save_jobs()

# -- Core lead processor -------------------------------------------------------
def process_lead(job_id, lead_idx):
    job  = jobs.get(job_id)
    if not job: return
    lead = job['leads'][lead_idx]
    lead['status']  = 'running'
    lead['error']   = ''
    lead['count']   = 0
    save_jobs()

    try:
        log_event(f"Starting processing for lead #{lead_idx+1}: {lead['name']} ({lead.get('location','')})")
        results = search_person(lead['name'], lead['location'], phone=lead.get('phone',''))
        lead['count'] = len(results)
        log_event(f"Found {len(results)} search result(s) for {lead['name']}")

        # Inject lead-level social_link into every result for the report
        for res in results:
            if not res.get('social_link'):
                res['social_link'] = lead.get('social_link', '')

        lead_safe   = f"{safe_name(lead['name'], lead['location'])}_{lead_idx+1}"
        lead_folder = os.path.join(job['folder'], lead_safe)
        os.makedirs(lead_folder, exist_ok=True)
        lead['folder_name'] = lead_safe

        # -- Phase 2: enrich with profile detail page (phones, emails, etc.) --
        from fsp_profile_parser import parse_fsp_profile as _parse_profile

        def _enrich_single_result(res):
            if lead.get('cancel_flag') or job.get('cancel_flag'):
                return
            purl = res.get('profile_url', '')
            if purl and '/name/' in purl:
                log_event(f"[P2] Resolving directory listing URL to detail profile: {purl}")
                s_html = bd_fetch(purl)
                if s_html:
                    parsed_cards = parse_fsp(s_html)
                    if parsed_cards:
                        best = parsed_cards[0]
                        if best.get('profile_url') and '/name/' not in best['profile_url']:
                            purl = best['profile_url']
                            res['profile_url'] = purl
                            if best.get('age') and res.get('age') == 'N/A': res['age'] = best['age']
                            if best.get('city') and res.get('city') == 'N/A': res['city'] = best['city']
                            if best.get('address') and res.get('address') == 'N/A': res['address'] = best['address']
                            if best.get('relatives'): res['relatives'] = best['relatives']

            if purl and '/name/' not in purl:
                log_event(f"[P2] Fetching detail profile HTML for {res['name']}: {purl}")
                phtml = bd_fetch_profile(purl)
                if phtml:
                    pdata = _parse_profile(phtml)
                    if pdata.get('phones'):     res['phones']     = pdata['phones']
                    if pdata.get('emails'):     res['emails']      = pdata['emails']
                    if pdata.get('associates'): res['associates']  = pdata['associates']
                    if pdata.get('employment'): res['employment']  = pdata['employment']
                    if pdata.get('free_background_report'): res['free_background_report'] = pdata['free_background_report']
                    if pdata.get('addresses') and len(pdata['addresses']) > len(res.get('addresses',[])):
                        res['addresses'] = pdata['addresses']
                    res['_profile_html'] = phtml
                    log_event(f"[P2] ✅ Profile enriched: {len(res.get('phones',[]))} phones, {len(res.get('emails',[]))} emails extracted")
                else:
                    log_event(f"[P2] BD profile failed — trying direct HTTP fallback for {res['name']}", "WARN")
                    try:
                        direct_r = HTTP_SESSION.get(purl, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.9',
                            'Referer': 'https://www.fastpeoplesearch.com/',
                        }, timeout=30, verify=False)
                        if direct_r.status_code == 200 and len(direct_r.text) > 5000 and not is_rejected_scrape_body(direct_r.text):
                            phtml_direct = direct_r.text
                            pdata = _parse_profile(phtml_direct)
                            if pdata.get('phones') or pdata.get('emails'):
                                if pdata.get('phones'):     res['phones']     = pdata['phones']
                                if pdata.get('emails'):     res['emails']      = pdata['emails']
                                if pdata.get('associates'): res['associates']  = pdata['associates']
                                if pdata.get('employment'): res['employment']  = pdata['employment']
                                if pdata.get('free_background_report'): res['free_background_report'] = pdata['free_background_report']
                                if pdata.get('addresses') and len(pdata['addresses']) > len(res.get('addresses',[])):
                                    res['addresses'] = pdata['addresses']
                                res['_profile_html'] = phtml_direct
                                log_event(f"[P2] ✅ Direct HTTP fallback enriched: {len(res.get('phones',[]))} phones, {len(res.get('emails',[]))} emails")
                            else:
                                log_event(f"[P2] Profile page unavailable via provider or direct — using search card fallback", "WARN")
                        else:
                            log_event(f"[P2] Direct HTTP fallback also failed (status={direct_r.status_code}) — using search card fallback", "WARN")
                    except Exception as direct_e:
                        log_event(f"[P2] Direct HTTP fallback error: {direct_e} — using search card fallback", "WARN")

        # Enrich ALL results with authentic detail profile HTML for 100% real full-page screenshots
        if len(results) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(results))) as enrich_pool:
                list(enrich_pool.map(_enrich_single_result, results))
        elif len(results) == 1:
            _enrich_single_result(results[0])

        # Save raw data (excluding large HTML blobs)
        with open(os.path.join(lead_folder, 'data.json'), 'w', encoding='utf-8') as f:
            save_results = [{k: v for k, v in r.items() if k not in ('_profile_html', '_search_html')} for r in results]
            json.dump({'name': lead['name'], 'location': lead['location'],
                       'results': save_results}, f, indent=2)

        # Screenshots
        # -- 1. Single Full Search Page Screenshot (1x per lead overview) ----------
        search_ss_file = f"{lead_safe}_search_page.png"
        search_ss_path = os.path.join(lead_folder, search_ss_file)
        search_html = next((r.get('_search_html') for r in results if r.get('_search_html')), None)
        if not search_html:
            search_html = _THREAD_SEARCH_HTML.pop(threading.get_ident(), None)
        else:
            _THREAD_SEARCH_HTML.pop(threading.get_ident(), None)

        if not search_html or is_rejected_scrape_body(search_html):
            # Guarantee authentic 0-results search page HTML
            search_html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Public Records Intelligence - 0 Results</title></head>
<body class="site-body">
<div class="container search-container" style="padding:30px 20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
  <div style="border-bottom:2px solid #e2e8f0;padding-bottom:14px;margin-bottom:20px">
    <h1 style="font-size:1.5rem;color:#1e293b;font-weight:700;margin-bottom:4px">0 Public Records Found</h1>
    <p style="color:#64748b;font-size:0.9rem">Search overview for <strong style="color:#0f172a">{lead['name']}</strong> ({lead.get('location') or 'US'})</p>
  </div>
  <div style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;padding:24px;max-width:700px">
    <h2 style="font-size:1.1rem;color:#334155;margin-bottom:8px;font-weight:600">We are sorry, but no results were found for "{lead['name']}"</h2>
    <p style="color:#64748b;font-size:0.88rem;line-height:1.5;margin-bottom:14px">Public Records Intelligence could not locate an active directory profile matching this exact query.</p>
    <div style="font-size:0.82rem;color:#475569">
      <strong>Search suggestions:</strong>
      <ul style="margin:6px 0 0 18px;line-height:1.5">
        <li>Try searching by phone number or physical address.</li>
        <li>Check for alternate spellings or middle initials.</li>
      </ul>
    </div>
  </div>
</div></body></html>'''

        log_event(f"📸 Capturing 1x Full Search Page screenshot for {lead['name']} ({len(results)} records)")
        target_res = results[0] if results else {'name': lead['name'], 'city': lead.get('location', '')}
        _screenshot_profile_html(search_html, search_ss_path, target_res)

        # -- 2. Profile Detail Page Screenshots (per individual result card) ------
        for j, res in enumerate(results, 1):
            if lead.get('cancel_flag') or job.get('cancel_flag'):
                break
            ss_name = f"{lead_safe}_result_{j}.png"
            ss_path = os.path.join(lead_folder, ss_name)
            phtml   = res.pop('_profile_html', None)
            res.pop('_search_html', None)
            
            # If phtml is missing, fetch real profile HTML so every result gets an authentic screenshot
            if not phtml:
                purl = res.get('profile_url', '')
                if purl:
                    log_event(f"  📸 Fetching real profile HTML for screenshot {j}/{len(results)}: {res['name']}")
                    phtml = bd_fetch_profile(purl) if '/name/' not in purl else bd_fetch(purl)

            if phtml and not is_rejected_scrape_body(phtml):
                log_event(f"  📸 Capturing authentic profile screenshot {j}/{len(results)}: {res['name']}")
                _screenshot_profile_html(phtml, ss_path, res)
            else:
                log_event(f"  ⚠️ No real HTML for {res['name']} - skipping screenshot (no fake cards)", "WARN")
            time.sleep(0.4)

        # HTML report (pass job_id + lead_idx so delete/archive buttons work)
        try:
            report = build_lead_report(lead['name'], lead['location'],
                                       results, lead_folder, lead_safe,
                                       job_id=job_id, lead_idx=lead_idx,
                                       social_link=lead.get('social_link',''), email=lead.get('email',''), phone=lead.get('phone',''))
            with open(os.path.join(lead_folder, 'report.html'), 'w', encoding='utf-8') as f:
                f.write(report)
        except Exception as rpt_e:
            log_event(f"Report generation warning: {rpt_e}", "WARN")

        # Commit status NOW — before screenshots — so a screenshot crash doesn't erase results
        if results:
            lead['status'] = 'done'
        else:
            lead['status'] = 'none'
            lead['error']  = 'No public records found'
        save_jobs()

    except Exception as e:
        lead['status'] = 'failed'
        lead['error']  = str(e)
        print(f"  ❌ Lead error: {e}")
        # Fair Credit Policy: Technical failures do NOT count against user's quota
        if job.get('user_id') and not lead.get('refunded'):
            proceed_despite_warning = job.get('proceed_with_poor_network', False)
            is_net_err = any(kw in str(e).lower() for kw in ('network', 'connection', 'timeout', 'socket', 'disconnected'))
            if not (proceed_despite_warning and is_net_err):
                database.refund_user_usage(job['user_id'], 1)
                lead['refunded'] = True
                log_event(f"ℹ️ Technical failure for lead #{lead_idx+1}: 1 lead credit refunded to user {job.get('username')}")

    save_jobs()
    regenerate_index(job_id)

from concurrent.futures import ThreadPoolExecutor

def run_job_bg(job_id, lead_indices=None):
    """Multi-threaded high-throughput job runner with live ETA calculation."""
    job = jobs.get(job_id)
    if not job: return

    job['status']       = 'running'
    job['cancel_flag']  = False
    job['pause_flag']   = False
    job['start_time']   = time.time()

    indices = list(lead_indices if lead_indices is not None else range(len(job['leads'])))
    to_process = [i for i in indices if job['leads'][i]['status'] not in ('done', 'none', 'failed', 'cancelled')]

    if not to_process:
        job['status'] = 'complete'
        save_jobs()
        return

    total_count = len(job['leads'])
    concurrency = min(8, max(1, len(to_process)))

    log_event(f"🚀 Starting Job {job_id}: processing {len(to_process)} leads with {concurrency} worker threads")

    def _worker(idx):
        if job.get('cancel_flag'):
            job['leads'][idx]['status'] = 'cancelled'
            return

        while job.get('pause_flag') and not job.get('cancel_flag'):
            job['status'] = 'paused'
            time.sleep(0.5)

        if job.get('cancel_flag'):
            job['leads'][idx]['status'] = 'cancelled'
            return

        lead = job['leads'][idx]
        job['status']  = 'running'
        job['current'] = f"[{idx+1}/{total_count}] {lead['name']}"

        process_lead(job_id, idx)

        done = sum(1 for l in job['leads'] if l['status'] in ('done', 'none', 'failed', 'cancelled'))
        job['done'] = done

        elapsed = time.time() - job.get('start_time', time.time())
        if done > 0 and elapsed > 0:
            avg_per_lead = elapsed / done
            remaining = total_count - done
            eta_sec = int((remaining * avg_per_lead) / concurrency)
            mins, secs = divmod(eta_sec, 60)
            hrs, mins  = divmod(mins, 60)
            if hrs > 0:
                job['eta'] = f"{hrs}h {mins}m remaining"
            elif mins > 0:
                job['eta'] = f"{mins}m {secs}s remaining"
            else:
                job['eta'] = f"{secs}s remaining"

            job['speed'] = f"{avg_per_lead:.1f}s / lead"
        else:
            job['eta']   = "Calculating..."
            job['speed'] = "—"

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_worker, idx) for idx in to_process]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                log_event(f"Worker thread error: {e}", "ERROR")

    close_shared_selenium_driver()
    job['done'] = sum(1 for l in job['leads'] if l['status'] in ('done', 'none', 'failed', 'cancelled'))
    all_done    = all(l['status'] in ('done', 'none', 'failed', 'cancelled') for l in job['leads'])
    
    if job.get('cancel_flag'):
        job['status'] = 'cancelled'
        job['eta']    = 'Cancelled'
    elif job.get('pause_flag'):
        job['status'] = 'paused'
        job['eta']    = 'Paused'
    elif all_done:
        job['status']  = 'complete'
        job['current'] = f"Done: {job['done']}/{total_count} leads processed"
        job['eta']     = "Completed"
    save_jobs()
    regenerate_index(job_id)
    log_event(f"✅ Job {job_id} finished with status '{job['status']}' ({job['done']}/{total_count} leads processed)")

# -- Flask API -----------------------------------------------------------------
# -- Flask API & Auth ----------------------------------------------------------
@app.route('/favicon.ico')
def favicon():
    ico_file = os.path.join(os.path.dirname(__file__), 'favicon.ico')
    if os.path.exists(ico_file):
        return send_file(ico_file, mimetype='image/x-icon')
    svg_file = os.path.join(os.path.dirname(__file__), 'favicon.svg')
    if os.path.exists(svg_file):
        return send_file(svg_file, mimetype='image/svg+xml')
    return ('', 204)

@app.route('/login')
def login_page():
    user = get_current_user()
    if user and user['status'] == 'active':
        return redirect('/')
    return render_template('login.html')

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    
    user = database.get_user_by_username(username)
    if not user or not database.verify_pw(password, user['password_hash']):
        return jsonify({'error': 'Invalid username or password'}), 401
    
    if user['status'] == 'paused':
        return jsonify({'error': 'Your account is currently paused. Please contact administrator.'}), 403
    if user['status'] == 'terminated':
        return jsonify({'error': 'Your account has been terminated.'}), 403

    token = database.create_session(user)
    resp = make_response(jsonify({'success': True, 'redirect': '/', 'role': user['role'], 'username': user['username']}))
    resp.set_cookie('leads_session', token, max_age=86400 * 7, httponly=True, samesite='Lax')
    return resp

@app.route('/api/auth/logout', methods=['POST', 'GET'])
def api_logout():
    token = request.cookies.get('leads_session')
    if token:
        database.destroy_session(token)
    resp = make_response(redirect('/login'))
    resp.delete_cookie('leads_session')
    return resp

@app.route('/api/auth/me', methods=['GET'])
@login_required
def api_me():
    user = request.current_user
    
    _, _, fresh_user, is_frozen = database.check_user_quota_and_status(user['id'], 0)
    user = fresh_user or user
    
    total_allocated = user.get('plan_total_limit', 50)
    total_usage = user.get('total_usage', 0)
    leads_remaining = max(0, total_allocated - total_usage)
    
    # Approaching limit when remaining <= 10 or <= 15% of total allocation
    is_approaching_limit = (0 < leads_remaining <= 10 or (total_allocated > 10 and leads_remaining <= 0.15 * total_allocated)) and user['role'] != 'admin'

    return jsonify({
        'id': user['id'],
        'username': user['username'],
        'role': user['role'],
        'plan': user['plan'],
        'status': user['status'],
        'total_allocated': total_allocated,
        'total_usage': total_usage,
        'leads_remaining': leads_remaining,
        'is_frozen': is_frozen,
        'is_approaching_limit': is_approaching_limit,
        'whatsapp_url': database.get_support_settings().get('whatsapp_url') or database.WHATSAPP_SUPPORT_URL
    })

# -- Admin User Management -----------------------------------------------------
@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_list_users():
    return jsonify(database.list_all_users())

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def api_admin_create_user():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    leads_allocated = data.get('leads_allocated') or data.get('leads') or 50
    role = data.get('role', 'user')
    plan = data.get('plan')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    try:
        leads_allocated = int(leads_allocated)
        if leads_allocated <= 0:
            leads_allocated = 50
    except (ValueError, TypeError):
        leads_allocated = 50
    uid, err = database.create_user(username, password, leads_allocated=leads_allocated, role=role, plan=plan)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'success': True, 'user_id': uid})

@app.route('/api/admin/users/<int:uid>/add-leads', methods=['POST'])
@admin_required
def api_admin_add_leads(uid):
    data = request.get_json() or {}
    leads = data.get('leads', 50)
    try:
        leads = int(leads)
        if leads <= 0:
            return jsonify({'error': 'Number of leads to add must be greater than 0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid number of leads'}), 400
    updated = database.add_user_leads(uid, leads)
    if not updated:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'success': True, 'new_total': updated['plan_total_limit']})

@app.route('/api/admin/users/<int:uid>/status', methods=['POST'])
@admin_required
def api_admin_update_status(uid):
    data = request.get_json() or {}
    new_status = data.get('status', 'active')
    ok, err = database.update_user_status(uid, new_status)
    if not ok:
        return jsonify({'error': err}), 400
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@admin_required
def api_admin_delete_user(uid):
    database.delete_user(uid)
    return jsonify({'success': True})

# -- In-App Messaging ----------------------------------------------------------
@app.route('/api/messages', methods=['GET'])
@login_required
def api_get_messages():
    user = request.current_user
    msgs = database.get_messages_for_user(user['id'], user['role'])
    return jsonify(msgs)

@app.route('/api/messages', methods=['POST'])
@login_required
def api_post_message():
    user = request.current_user
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    receiver_id = data.get('receiver_id')
    receiver_username = data.get('receiver_username', '')
    if not content:
        return jsonify({'error': 'Message cannot be empty'}), 400
    if user['role'] != 'admin':
        receiver_id = 1
        receiver_username = 'admin'
    mid = database.send_message(user['id'], user['username'], receiver_id, content, receiver_username)
    return jsonify({'success': True, 'message_id': mid})

# -- Sharing -------------------------------------------------------------------
@app.route('/api/jobs/<job_id>/share', methods=['POST'])
def api_share_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    token = database.get_or_create_share_token(
        job_id, job.get('user_id', 1), job.get('username', 'admin'),
        job.get('name', job_id), job.get('status', 'complete'),
        job.get('total', 0), job.get('done', 0), job.get('folder', '')
    )
    job['share_token'] = token
    save_jobs()
    share_url = f"{request.host_url}share/{token}"
    return jsonify({'success': True, 'share_token': token, 'share_url': share_url})

@app.route('/api/jobs/<job_id>/share/reset', methods=['POST'])
@login_required
def api_reset_share_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    user = getattr(request, 'current_user', None)
    if user and user.get('role') != 'admin' and job.get('user_id') != user.get('id'):
        return jsonify({'error': 'Unauthorized to modify share settings for this job'}), 403
    
    new_token = database.reset_share_token(
        job_id, job.get('user_id', 1), job.get('username', 'admin'),
        job.get('name', job_id), job.get('folder', '')
    )
    job['share_token'] = new_token
    save_jobs()
    try:
        regenerate_index(job_id)
    except Exception:
        pass
    share_url = f"{request.host_url}share/{new_token}"
    return jsonify({'success': True, 'share_token': new_token, 'share_url': share_url})

@app.route('/api/jobs/<job_id>/share/revoke', methods=['POST'])
@login_required
def api_revoke_share_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    user = getattr(request, 'current_user', None)
    if user and user.get('role') != 'admin' and job.get('user_id') != user.get('id'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    database.revoke_share_token(job_id)
    job['share_token'] = ''
    save_jobs()
    return jsonify({'success': True, 'message': 'Sharing revoked successfully.'})

@app.route('/api/settings/guide-video', methods=['GET'])
def api_get_guide_video():
    url = database.get_setting('guide_video_url', '')
    return jsonify({'guide_video_url': url})

@app.route('/api/admin/settings/guide-video', methods=['POST'])
@admin_required
def api_set_guide_video():
    data = request.get_json() or {}
    url = data.get('guide_video_url', '').strip()
    database.set_setting('guide_video_url', url)
    log_event(f"⚙️ Admin updated Walkthrough Video URL")
    return jsonify({'success': True, 'guide_video_url': url})


FROZEN_SHARE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dossier Temporarily Unavailable — LeadsOSINT</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #07090e; --surface: #0e121a; --border: #1e2535;
    --text: #e2e8f0; --sub: #64748b; --warn: #38bdf8; --prim: #6366f1;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text); font-family: 'Space Grotesk', sans-serif;
    min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px;
  }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
    padding: 40px; max-width: 480px; width: 100%; text-align: center;
    box-shadow: 0 20px 40px rgba(0,0,0,0.5);
  }
  .icon { font-size: 3.2rem; margin-bottom: 16px; animation: pulse 2.5s infinite ease-in-out; }
  h1 { font-size: 1.55rem; font-weight: 700; margin-bottom: 12px; }
  p { color: var(--sub); line-height: 1.6; margin-bottom: 24px; font-size: 0.95rem; }
  .badge {
    display: inline-block; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.3);
    color: var(--warn); padding: 5px 14px; border-radius: 20px; font-size: 0.8rem; font-family: 'JetBrains Mono', monospace;
    font-weight: 600; margin-bottom: 20px;
  }
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    background: #25d366; color: #fff; font-weight: 600; text-decoration: none;
    padding: 12px 24px; border-radius: 10px; font-size: 0.95rem; transition: 0.2s ease;
  }
  .btn:hover { background: #22bf5b; transform: translateY(-2px); }
  @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.75; transform: scale(0.96); } }
</style>
</head>
<body>
  <div class="card">
    <div class="icon">❄️</div>
    <div class="badge">ACCESS STATUS: ACCOUNT INACTIVE / FROZEN</div>
    <h1>Dossier Temporarily Unavailable</h1>
    <p>This public records intelligence report is temporarily unavailable because the owner's account has been paused, frozen, or has depleted its active quota.<br><br>Public dossier access will automatically restore as soon as the account is reactivated.</p>
    <a href="{{ whatsapp_url }}" target="_blank" class="btn">
      💬 Contact Admin via WhatsApp
    </a>
  </div>
</body>
</html>
"""

@app.route('/share/<share_token>')
def view_shared_job(share_token):
    job_rec, status = database.get_job_by_share_token(share_token)
    if status == 'frozen':
        return render_template_string(FROZEN_SHARE_TEMPLATE, whatsapp_url=database.WHATSAPP_SUPPORT_URL), 403
    if not job_rec or status != 'valid':
        return abort(404)

    job = jobs.get(job_rec['id'])
    if not job:
        job_folder = job_rec.get('folder', '')
        leads = []
        if os.path.isdir(job_folder):
            for item in sorted(os.listdir(job_folder)):
                item_path = os.path.join(job_folder, item)
                if os.path.isdir(item_path):
                    data_file = os.path.join(item_path, 'data.json')
                    if os.path.exists(data_file):
                        try:
                            with open(data_file, 'r', encoding='utf-8') as df:
                                d = json.load(df)
                                results = [r for r in d.get('results', []) if not r.get('archived')]
                                leads.append({
                                    'name': d.get('name', item),
                                    'location': d.get('location', ''),
                                    'status': 'done' if results else 'none',
                                    'count': len(results),
                                    'folder_name': item
                                })
                        except Exception:
                            pass
        job = {
            'id': job_rec['id'],
            'name': job_rec.get('name', job_rec['id']),
            'folder': job_folder,
            'total': job_rec.get('total', len(leads)),
            'done': job_rec.get('done', len(leads)),
            'status': job_rec.get('status', 'complete'),
            'leads': leads
        }
    return build_job_index(job, is_shared=True, share_token=share_token)

def _resolve_job_and_folder(job_rec):
    job = jobs.get(job_rec['id'])
    job_folder = job.get('folder') if (job and job.get('folder')) else job_rec.get('folder', '')
    if not job_folder or not os.path.exists(job_folder):
        if os.path.exists(OUT_DIR):
            for entry in os.listdir(OUT_DIR):
                if job_rec['id'].upper() in entry.upper():
                    job_folder = os.path.join(OUT_DIR, entry)
                    break
    return job, os.path.abspath(job_folder) if job_folder else ''

@app.route('/share/<share_token>/<path:subpath>')
def serve_shared_subpath(share_token, subpath):
    job_rec, status = database.get_job_by_share_token(share_token)
    if status == 'frozen':
        return render_template_string(FROZEN_SHARE_TEMPLATE, whatsapp_url=database.WHATSAPP_SUPPORT_URL), 403
    if not job_rec or status != 'valid':
        return abort(404)

    job, job_folder = _resolve_job_and_folder(job_rec)
    safe_subpath = subpath.replace('..', '').lstrip('/').lstrip('\\')

    # Image asset handling
    if safe_subpath.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif')):
        if job_folder:
            cand = os.path.join(job_folder, safe_subpath)
            if os.path.exists(cand):
                return send_file(cand)
            if os.path.isdir(job_folder):
                for sub in os.listdir(job_folder):
                    cand2 = os.path.join(job_folder, sub, safe_subpath)
                    if os.path.isfile(cand2):
                        return send_file(cand2)
        cand_out = os.path.join(OUT_DIR, safe_subpath)
        if os.path.exists(cand_out):
            return send_file(cand_out)
        return abort(404)

    # Lead report HTML in Job Share (has ← Back to Job button)
    folder_part = safe_subpath.split('/')[0] if '/' in safe_subpath else safe_subpath
    if folder_part.endswith('.html'):
        folder_part = ''
    
    lead_found = None
    lead_idx = 0
    if job and job.get('leads'):
        for idx, l in enumerate(job['leads']):
            lf = l.get('folder_name', '')
            lname = safe_name(l.get('name', ''), l.get('location', '')) if l.get('name') else ''
            if lf == folder_part or (lf and folder_part in lf) or (lf and lf in folder_part) or (lname and lname in folder_part):
                lead_found = l
                lead_idx = idx
                break

    lead_dir = os.path.join(job_folder, folder_part) if (job_folder and folder_part) else ''
    djson = os.path.join(lead_dir, 'data.json') if lead_dir else ''
    results = []
    if djson and os.path.exists(djson):
        try:
            with open(djson, 'r', encoding='utf-8') as df:
                dj = json.load(df)
                results = dj.get('results', [])
        except Exception:
            pass
    
    if lead_found or (djson and os.path.exists(djson)):
        lname = lead_found.get('name', folder_part) if lead_found else folder_part
        loc = lead_found.get('location', '') if lead_found else ''
        soc = lead_found.get('social_link', '') if lead_found else ''
        em = lead_found.get('email', '') if lead_found else ''
        ph = lead_found.get('phone', '') if lead_found else ''
        html = build_lead_report(
            lname, loc, results, lead_dir or '', folder_part,
            job_id=job_rec['id'], lead_idx=lead_idx,
            social_link=soc, email=em, phone=ph,
            is_shared=True, is_lead_share=False, share_token=share_token
        )
        resp = make_response(html)
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp

    target_path = os.path.join(job_folder, safe_subpath) if job_folder else ''
    if target_path and os.path.exists(target_path):
        if target_path.endswith('.html'):
            with open(target_path, 'r', encoding='utf-8') as f:
                html = f.read()
            html = re.sub(r'<a\s+[^>]*class="back"[^>]*>.*?</a>', f'<a href="/share/{share_token}" class="back">← Back to Job</a>', html, flags=re.DOTALL)
            html = re.sub(r'<button[^>]*redoReportLead[^>]*>.*?</button>', '', html, flags=re.DOTALL)
            html = re.sub(r'<button[^>]*openShareModal[^>]*>.*?</button>', '', html, flags=re.DOTALL)
            html = re.sub(r'<div\s+class="share-modal"[^>]*>.*?</div>\s*(?=</body>|\Z)', '', html, flags=re.DOTALL)
            html = re.sub(r'<div class="res-actions[^"]*">.*?</div>\s*(?=</details>|\Z)', '', html, flags=re.DOTALL)
            html = re.sub(r'<button[^>]*(?:archiveResult|unarchiveResult|confirmDelete|deleteResult)[^>]*>.*?</button>', '', html, flags=re.DOTALL)
            resp = make_response(html)
            resp.headers['Content-Type'] = 'text/html; charset=utf-8'
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return resp
        return send_file(target_path)
    return abort(404)

@app.route('/share/lead/<share_token>/<path:subpath>')
def serve_shared_single_lead(share_token, subpath):
    job_rec, status = database.get_job_by_share_token(share_token)
    if status == 'frozen':
        return render_template_string(FROZEN_SHARE_TEMPLATE, whatsapp_url=database.WHATSAPP_SUPPORT_URL), 403
    if not job_rec or status != 'valid':
        return abort(404)

    job, job_folder = _resolve_job_and_folder(job_rec)
    safe_subpath = subpath.replace('..', '').lstrip('/').lstrip('\\')

    # Image asset handling
    if safe_subpath.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif')):
        if job_folder:
            cand = os.path.join(job_folder, safe_subpath)
            if os.path.exists(cand):
                return send_file(cand)
            if os.path.isdir(job_folder):
                for sub in os.listdir(job_folder):
                    cand2 = os.path.join(job_folder, sub, safe_subpath)
                    if os.path.isfile(cand2):
                        return send_file(cand2)
        cand_out = os.path.join(OUT_DIR, safe_subpath)
        if os.path.exists(cand_out):
            return send_file(cand_out)
        return abort(404)

    # Single Lead Share HTML: strictly NO Back to Job button and zero action buttons
    folder_part = safe_subpath.split('/')[0] if '/' in safe_subpath else safe_subpath
    if folder_part.endswith('.html'):
        folder_part = ''
    
    lead_found = None
    lead_idx = 0
    if job and job.get('leads'):
        for idx, l in enumerate(job['leads']):
            lf = l.get('folder_name', '')
            lname = safe_name(l.get('name', ''), l.get('location', '')) if l.get('name') else ''
            if lf == folder_part or (lf and folder_part in lf) or (lf and lf in folder_part) or (lname and lname in folder_part):
                lead_found = l
                lead_idx = idx
                break

    lead_dir = os.path.join(job_folder, folder_part) if (job_folder and folder_part) else ''
    djson = os.path.join(lead_dir, 'data.json') if lead_dir else ''
    results = []
    if djson and os.path.exists(djson):
        try:
            with open(djson, 'r', encoding='utf-8') as df:
                dj = json.load(df)
                results = dj.get('results', [])
        except Exception:
            pass
    
    if lead_found or (djson and os.path.exists(djson)):
        lname = lead_found.get('name', folder_part) if lead_found else folder_part
        loc = lead_found.get('location', '') if lead_found else ''
        soc = lead_found.get('social_link', '') if lead_found else ''
        em = lead_found.get('email', '') if lead_found else ''
        ph = lead_found.get('phone', '') if lead_found else ''
        html = build_lead_report(
            lname, loc, results, lead_dir or '', folder_part,
            job_id=job_rec['id'], lead_idx=lead_idx,
            social_link=soc, email=em, phone=ph,
            is_shared=True, is_lead_share=True, share_token=share_token
        )
        resp = make_response(html)
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp

    target_path = os.path.join(job_folder, safe_subpath) if job_folder else ''
    if target_path and os.path.exists(target_path):
        if target_path.endswith('.html'):
            with open(target_path, 'r', encoding='utf-8') as f:
                html = f.read()
            html = re.sub(r'<a\s+[^>]*class="back"[^>]*>.*?</a>', '<span class="back" style="pointer-events:none;background:rgba(167,139,250,0.12);border-color:rgba(167,139,250,0.3);color:var(--ac);font-weight:600">🔒 Confidential OSINT Lead</span>', html, flags=re.DOTALL)
            html = re.sub(r'<button[^>]*redoReportLead[^>]*>.*?</button>', '', html, flags=re.DOTALL)
            html = re.sub(r'<button[^>]*openShareModal[^>]*>.*?</button>', '', html, flags=re.DOTALL)
            html = re.sub(r'<div\s+class="share-modal"[^>]*>.*?</div>\s*(?=</body>|\Z)', '', html, flags=re.DOTALL)
            html = re.sub(r'<div class="res-actions[^"]*">.*?</div>\s*(?=</details>|\Z)', '', html, flags=re.DOTALL)
            html = re.sub(r'<button[^>]*(?:archiveResult|unarchiveResult|confirmDelete|deleteResult)[^>]*>.*?</button>', '', html, flags=re.DOTALL)
            resp = make_response(html)
            resp.headers['Content-Type'] = 'text/html; charset=utf-8'
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return resp
        return send_file(target_path)
    return abort(404)

# -- Network Status Health Check ------------------------------------------------
@app.route('/api/network-status', methods=['GET'])
def api_network_status():
    import socket
    hosts = [("1.1.1.1", 53), ("8.8.8.8", 53)]
    successes = 0
    latencies = []
    for host, port in hosts:
        try:
            t0 = time.time()
            s = socket.create_connection((host, port), timeout=2.5)
            latencies.append((time.time() - t0) * 1000)
            s.close()
            successes += 1
        except Exception:
            pass
    if successes == 0:
        try:
            r = HTTP_SESSION.get("https://www.google.com", timeout=3.5)
            if r.status_code == 200:
                return jsonify({'status': 'online', 'latency_ms': 120})
        except Exception:
            pass
        return jsonify({'status': 'offline', 'error': 'No internet connection detected'})
    avg_latency = sum(latencies) / len(latencies)
    if successes == 1 or avg_latency > 1500:
        return jsonify({'status': 'unstable', 'latency_ms': round(avg_latency)})
    return jsonify({'status': 'online', 'latency_ms': round(avg_latency)})

# -- User / Admin Credentials Update -------------------------------------------
@app.route('/api/auth/change-credentials', methods=['POST'])
@login_required
def api_change_credentials():
    user = request.current_user
    data = request.get_json() or {}
    current_pw = data.get('current_password', '').strip()
    new_username = data.get('new_username', '').strip()
    new_pw = data.get('new_password', '').strip()
    if not current_pw:
        return jsonify({'error': 'Current password is required to verify identity'}), 400
    if not new_username and not new_pw:
        return jsonify({'error': 'Please provide a new username or new password to update'}), 400
    ok, err = database.update_credentials(user['id'], current_pw, new_username=new_username or None, new_password=new_pw or None)
    if not ok:
        return jsonify({'error': err}), 400
    log_event(f"🔐 User '{user['username']}' updated account credentials successfully")
    return jsonify({'success': True, 'message': 'Credentials updated successfully'})

# -- Messaging: Mark as Read & Unread Count -------------------------------------
@app.route('/api/messages/<int:mid>/read', methods=['POST'])
@login_required
def api_mark_message_read(mid):
    user = request.current_user
    database.mark_message_read(mid, user['id'], user['role'])
    return jsonify({'success': True})

@app.route('/api/messages/mark-all-read', methods=['POST'])
@login_required
def api_mark_all_messages_read():
    user = request.current_user
    database.mark_all_messages_read(user['id'], user['role'])
    return jsonify({'success': True})

@app.route('/api/messages/unread-count', methods=['GET'])
@login_required
def api_unread_message_count():
    user = request.current_user
    count = database.get_unread_message_count(user['id'], user['role'])
    return jsonify({'unread_count': count})

# -- Customer Support Settings --------------------------------------------------
@app.route('/api/settings/support', methods=['GET'])
def api_get_support_settings():
    settings = database.get_support_settings()
    return jsonify(settings)

@app.route('/api/admin/settings/support', methods=['POST'])
@admin_required
def api_save_support_settings():
    data = request.get_json() or {}
    if 'whatsapp_enabled' in data:
        database.set_setting('whatsapp_enabled', '1' if data['whatsapp_enabled'] else '0')
    if 'whatsapp_number' in data:
        database.set_setting('whatsapp_number', data['whatsapp_number'].strip())
    if 'whatsapp_url' in data:
        database.set_setting('whatsapp_url', data['whatsapp_url'].strip())
    log_event("⚙️ Admin updated Customer Support channel settings")
    return jsonify({'success': True, 'settings': database.get_support_settings()})

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/logs', methods=['GET'])
@admin_required
def get_logs_api():
    with LOG_LOCK:
        return jsonify(list(LOG_BUFFER))

@app.route('/api/jobs', methods=['GET'])
@login_required
def list_jobs_api():
    load_jobs()
    user = request.current_user
    result = []
    for jid, job in jobs.items():
        if user['role'] != 'admin' and job.get('user_id') != user['id']:
            continue
        result.append({
            'id':          job['id'],
            'user_id':     job.get('user_id', 1),
            'username':    job.get('username', 'admin'),
            'share_token': job.get('share_token', ''),
            'name':        job.get('name', job['id']),
            'status':      job.get('status', 'unknown'),
            'total':       job.get('total', 0),
            'done':        job.get('done', 0),
            'created':     job.get('created', ''),
            'current':     job.get('current', ''),
        })
    result.sort(key=lambda x: x.get('created', ''), reverse=True)
    return jsonify(result)

MAX_BATCH_LEADS_PER_JOB = 500

def _create_job_from_leads(leads, name='', autostart=True, user=None, auto_trim_batch=False):
    name = (name or '').strip()
    if not name:
        return jsonify({'error': 'Job Name is required. Please provide a name for this search batch.'}), 400

    if not user:
        user = getattr(request, 'current_user', None) or get_current_user()

    user_role = user.get('role', '') if isinstance(user, dict) else getattr(user, 'role', '')

    # -- Maximum Batch Input Limit (500 Leads / Job) ---------------------------
    if len(leads) > MAX_BATCH_LEADS_PER_JOB and user_role != 'admin':
        if auto_trim_batch:
            leads = leads[:MAX_BATCH_LEADS_PER_JOB]
        else:
            return jsonify({
                'error': f'Batch limit exceeded: Maximum {MAX_BATCH_LEADS_PER_JOB} leads allowed per single job run. You submitted {len(leads)} leads. Please split your list into batches of {MAX_BATCH_LEADS_PER_JOB} or fewer, or auto-trim to the first 500 leads.',
                'max_batch_limit': MAX_BATCH_LEADS_PER_JOB,
                'leads_requested': len(leads),
                'can_trim_batch': True
            }), 400

    if user:
        allowed, err_msg, _, is_frozen = database.check_user_quota_and_status(user['id'], len(leads))
        if not allowed:
            user_data = database.get_user_by_id(user['id']) or {}
            total_allocated = user_data.get('plan_total_limit', 50)
            total_usage = user_data.get('total_usage', 0)
            remaining = max(0, total_allocated - total_usage)
            return jsonify({
                'error': err_msg,
                'is_frozen': is_frozen,
                'leads_requested': len(leads),
                'leads_remaining': remaining,
                'can_trim': (remaining > 0 and len(leads) > remaining),
                'whatsapp_url': database.get_support_settings().get('whatsapp_url') or database.WHATSAPP_SUPPORT_URL
            }), 403
        database.record_user_usage(user['id'], len(leads))
        user_id = user['id']
        username = user['username']
    else:
        user_id = 1
        username = 'admin'

    job_id     = str(uuid.uuid4())[:8].upper()
    ts         = datetime.now()
    job_folder = os.path.join(OUT_DIR, f"job_{ts.strftime('%Y%m%d_%H%M%S')}_{job_id}")
    os.makedirs(job_folder, exist_ok=True)
    
    token = database.get_or_create_share_token(job_id, user_id, username, name or f'Job {job_id}', 'queued', len(leads), 0, job_folder)
    
    job = {
        'id': job_id, 'name': name or f'Job {job_id}',
        'user_id': user_id, 'username': username,
        'share_token': token,
        'status': 'queued', 'total': len(leads), 'done': 0,
        'current': '', 'folder': job_folder,
        'created': ts.isoformat(), 'index_path': '',
        'pause_flag': False, 'cancel_flag': False,
        'leads': [{'name': l['name'], 'location': l.get('location',''),
                   'social_link': l.get('social_link',''), 'email': l.get('email',''), 'phone': l.get('phone',''),
                   'status': 'queued', 'count': 0, 'error': '',
                   'folder_name': '', 'cancel_flag': False} for l in leads],
    }
    jobs[job_id] = job
    regenerate_index(job_id)
    save_jobs()
    if autostart:
        threading.Thread(target=run_job_bg, args=(job_id,), daemon=True).start()
    return jsonify({'id': job_id, 'total': len(leads), 'share_token': token})

@app.route('/api/jobs', methods=['POST'])
@login_required
def create_job_api():
    data   = request.get_json() or {}
    leads  = []

    if data.get('leads_text'):
        leads = parse_text_leads(data['leads_text'])
    elif data.get('leads_csv'):
        leads = parse_csv_leads(data['leads_csv'], is_content=True)

    if not leads:
        return jsonify({'error': 'No valid leads. Check format.'}), 400

    auto_trim_batch = bool(data.get('auto_trim_batch'))
    return _create_job_from_leads(leads, data.get('name', ''), data.get('autostart', True), user=request.current_user, auto_trim_batch=auto_trim_batch)

@app.route('/api/jobs/upload', methods=['POST'])
@login_required
def upload_job_api():
    name  = request.form.get('name', '')
    leads = []

    if 'file' in request.files and request.files['file'].filename:
        f   = request.files['file']
        raw = f.read()
        for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
            try: content = raw.decode(enc); break
            except: continue
        else: return jsonify({'error': 'Cannot decode file'}), 400
        leads = parse_csv_leads(content, is_content=True)
    elif request.form.get('leads_text', '').strip():
        leads = parse_text_leads(request.form.get('leads_text', ''))

    if not leads:
        return jsonify({'error': 'No valid leads found in file. Ensure your CSV contains Name and Location or Phone/Email.'}), 400
    autostart = request.form.get('autostart', 'true').lower() == 'true'
    auto_trim_batch = request.form.get('auto_trim_batch', 'false').lower() == 'true'
    return _create_job_from_leads(leads, name, autostart, user=request.current_user, auto_trim_batch=auto_trim_batch)

@app.route('/api/jobs/create', methods=['POST'])
def create_job_form():
    name  = request.form.get('name', '')
    leads = []
    if 'file' in request.files and request.files['file'].filename:
        f = request.files['file']
        raw = f.read()
        for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
            try: content = raw.decode(enc); break
            except: continue
        else:
            return jsonify({'error': 'Cannot decode file'}), 400
        leads = parse_csv_leads(content, is_content=True)
    elif request.form.get('leads_text', '').strip():
        leads = parse_text_leads(request.form['leads_text'])
    if not leads:
        return jsonify({'error': 'No valid leads'}), 400
    autostart = request.form.get('autostart', 'true').lower() == 'true'
    return _create_job_from_leads(leads, name, autostart)

@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job_api(job_id):
    job = jobs.get(job_id)
    if not job:
        load_jobs(force=True)
        job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    d = _job_to_dict(job)
    # Include folder basename for frontend path resolution
    d['folder_base'] = os.path.basename(job.get('folder', ''))
    return jsonify(d)

@app.route('/api/jobs/<job_id>', methods=['PUT'])
def update_job_api(job_id):
    job  = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    data = request.get_json() or {}
    if 'name' in data:
        job['name'] = data['name']
        regenerate_index(job_id)
    save_jobs()
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job_api(job_id):
    import shutil
    load_jobs()
    job = jobs.pop(job_id, None)
    if not job: return jsonify({'error': 'Not found'}), 404
    job['cancel_flag'] = True

    # 1. Write jobs_registry.json WITHOUT the deleted job (bypass save_jobs merge-back)
    try:
        with jobs_lock:
            if os.path.exists(JOBS_FILE):
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    disk_data = json.load(f)
                disk_data.pop(job_id, None)
                with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(disk_data, f, indent=2)
    except Exception as e:
        print(f'  delete_job registry error: {e}')

    # 2. Remove from SQLite DB so load_jobs() can't re-add it
    try:
        with database.get_db() as conn:
            conn.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
    except Exception as e:
        print(f'  delete_job DB error: {e}')

    # 3. Delete job folder from disk so auto-recovery can't resurrect it
    job_folder = job.get('folder', '')
    if job_folder and os.path.isdir(job_folder):
        try:
            shutil.rmtree(job_folder)
        except Exception as e:
            print(f'  delete_job folder error: {e}')

    log_event(f'🗑 Job {job_id} permanently deleted')
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>/pause', methods=['POST'])
def pause_job_api(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    job['pause_flag'] = True
    job['status'] = 'paused'
    save_jobs()
    log_event(f"⏸ Job {job_id} paused by user")
    return jsonify({'ok': True, 'status': 'paused'})

@app.route('/api/jobs/<job_id>/resume', methods=['POST'])
def resume_job_api(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    job['pause_flag']  = False
    job['cancel_flag'] = False
    job['status']      = 'running'
    save_jobs()
    log_event(f"▶ Job {job_id} resumed by user")
    threading.Thread(target=run_job_bg, args=(job_id,), daemon=True).start()
    return jsonify({'ok': True, 'status': 'running'})

@app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job_api(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    job['cancel_flag'] = True
    job['pause_flag']  = False
    job['status']      = 'cancelled'
    unrun_count = 0
    for l in job.get('leads', []):
        if l.get('status') in ('running', 'queued'):
            l['status'] = 'cancelled'
            l['cancel_flag'] = True
            if not l.get('refunded'):
                l['refunded'] = True
                unrun_count += 1
    if job.get('user_id') and unrun_count > 0:
        database.refund_user_usage(job['user_id'], unrun_count)
        log_event(f"ℹ️ Job {job_id} cancelled: {unrun_count} un-run lead credit(s) refunded to user {job.get('username')}")
    close_shared_selenium_driver()
    save_jobs()
    log_event(f"✕ Job {job_id} cancelled by user")
    return jsonify({'ok': True, 'status': 'cancelled', 'refunded': unrun_count})

@app.route('/api/jobs/<job_id>/status', methods=['GET'])
def job_status_api(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    pct   = int(job['done'] / job['total'] * 100) if job.get('total') else 0
    leads = [{'name': l['name'], 'location': l.get('location',''),
              'social_link': l.get('social_link',''), 'email': l.get('email',''), 'phone': l.get('phone',''),
              'status': l['status'], 'count': l['count'], 'error': l.get('error',''),
              'folder_name': l.get('folder_name','')} for l in job.get('leads',[])]
    return jsonify({
        'id': job_id, 'name': job.get('name', job_id),
        'status': job['status'], 'total': job.get('total',0),
        'done': job.get('done',0), 'percent': pct,
        'current': job.get('current',''), 'leads': leads,
        'eta': job.get('eta', 'Calculating...'),
        'speed': job.get('speed', '—'),
    })


@app.route('/api/jobs/<job_id>/retry-failed', methods=['POST'])
def retry_failed_api(job_id):
    """Retry only the failed leads in a job."""
    job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    failed = [i for i, l in enumerate(job['leads']) if l['status'] == 'failed']
    if not failed:
        return jsonify({'error': 'No failed leads to retry'}), 400
    user_id = job.get('user_id', 1)
    allowed, err_msg, _, _ = database.check_user_quota_and_status(user_id, len(failed))
    if not allowed:
        return jsonify({'error': err_msg or f'Insufficient lead credits ({len(failed)} needed).'}), 403
    database.record_user_usage(user_id, len(failed))
    for idx in failed:
        job['leads'][idx]['status']      = 'queued'
        job['leads'][idx]['error']       = ''
        job['leads'][idx]['cancel_flag'] = False
    job['cancel_flag'] = False
    job['pause_flag']  = False
    job['status']      = 'running'
    threading.Thread(target=run_job_bg, args=(job_id, failed), daemon=True).start()
    save_jobs()
    return jsonify({'ok': True, 'retrying': len(failed)})


@app.route('/api/jobs/<job_id>/redo-all', methods=['POST'])
def redo_all_api(job_id):
    """Re-run ALL leads from scratch."""
    job = jobs.get(job_id)
    if not job: return jsonify({'error': 'Not found'}), 404
    user_id = job.get('user_id', 1)
    count = len(job['leads'])
    allowed, err_msg, _, _ = database.check_user_quota_and_status(user_id, count)
    if not allowed:
        return jsonify({'error': err_msg or f'Insufficient lead credits ({count} needed).'}), 403
    database.record_user_usage(user_id, count)
    for lead in job['leads']:
        lead['status']      = 'queued'
        lead['error']       = ''
        lead['cancel_flag'] = False
        lead['count']       = 0
    job['done']        = 0
    job['cancel_flag'] = False
    job['pause_flag']  = False
    job['status']      = 'running'
    threading.Thread(target=run_job_bg, args=(job_id,), daemon=True).start()
    save_jobs()
    return jsonify({'ok': True, 'total': len(job['leads'])})

@app.route('/api/jobs/<job_id>/leads/<int:idx>/start', methods=['POST'])
def start_lead_api(job_id, idx):
    job = jobs.get(job_id)
    if not job or idx >= len(job['leads']): return jsonify({'error': 'Not found'}), 404
    lead = job['leads'][idx]
    if lead['status'] == 'running': return jsonify({'error': 'Already running'}), 400
    lead['status']      = 'queued'
    lead['cancel_flag'] = False
    os.makedirs(job.get('folder', OUT_DIR), exist_ok=True)
    t = threading.Thread(target=process_lead, args=(job_id, idx), daemon=True)
    t.start()
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>/leads/<int:idx>/retry', methods=['POST'])
def retry_lead_api(job_id, idx):
    if job_id not in jobs:
        load_jobs(force=True)
    job = jobs.get(job_id)
    if not job or idx >= len(job.get('leads', [])):
        return jsonify({'error': 'Not found'}), 404

    user_id = job.get('user_id', 1)
    # Admin has unlimited leads, only deduct credits for customer accounts
    if job.get('username') != 'admin' and user_id != 1:
        allowed, err_msg, _, _ = database.check_user_quota_and_status(user_id, 1)
        if not allowed:
            return jsonify({'error': err_msg or 'Insufficient lead credits to re-run lead.'}), 403
        database.record_user_usage(user_id, 1)

    lead = job['leads'][idx]
    lead['status']      = 'queued'
    lead['cancel_flag'] = False
    lead['error']       = ''
    job['status']       = 'running'
    job['cancel_flag']  = False
    job['pause_flag']   = False
    save_jobs()

    t = threading.Thread(target=process_lead, args=(job_id, idx), daemon=True)
    t.start()
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>/leads/<int:idx>/cancel', methods=['POST'])
def cancel_lead_api(job_id, idx):
    job = jobs.get(job_id)
    if not job or idx >= len(job['leads']): return jsonify({'error': 'Not found'}), 404
    job['leads'][idx]['cancel_flag'] = True
    job['leads'][idx]['status']      = 'cancelled'
    save_jobs()
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>/leads/<int:lead_idx>/results/<int:result_idx>/delete', methods=['POST'])
def delete_result_api(job_id, lead_idx, result_idx):
    """Permanently delete a result and its screenshot, rebuild report."""
    job = jobs.get(job_id)
    if not job or lead_idx >= len(job['leads']):
        return jsonify({'error': 'Not found'}), 404
    lead        = job['leads'][lead_idx]
    folder_name = lead.get('folder_name', '')
    if not folder_name:
        return jsonify({'error': 'Lead not yet processed'}), 400
    lead_folder = os.path.join(job['folder'], folder_name)
    data_file   = os.path.join(lead_folder, 'data.json')
    try:
        with open(data_file, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({'error': f'Cannot read data: {e}'}), 500
    results = data.get('results', [])
    if result_idx >= len(results):
        return jsonify({'error': 'Result index out of range'}), 404
    # Delete screenshot
    ss_name = f"{folder_name}_result_{result_idx + 1}.png"
    ss_path = os.path.join(lead_folder, ss_name)
    if os.path.exists(ss_path):
        os.remove(ss_path)
    # Remove result
    results.pop(result_idx)
    # Rename remaining screenshots to fill the gap
    for i in range(result_idx, len(results)):
        old_ss = os.path.join(lead_folder, f"{folder_name}_result_{i + 2}.png")
        new_ss = os.path.join(lead_folder, f"{folder_name}_result_{i + 1}.png")
        if os.path.exists(old_ss):
            os.rename(old_ss, new_ss)
    data['results']  = results
    lead['count']    = len([r for r in results if not r.get('archived')])
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    # Rebuild HTML report
    report = build_lead_report(lead['name'], lead.get('location', ''),
                               results, lead_folder, folder_name,
                               job_id=job_id, lead_idx=lead_idx,
                               social_link=lead.get('social_link', ''),
                               email=lead.get('email', ''),
                               phone=lead.get('phone', ''))
    with open(os.path.join(lead_folder, 'report.html'), 'w', encoding='utf-8') as f:
        f.write(report)
    regenerate_index(job_id)
    save_jobs()
    return jsonify({'ok': True, 'remaining': len(results)})

@app.route('/api/jobs/<job_id>/leads/<int:lead_idx>/results/<int:result_idx>/archive', methods=['POST'])
def archive_result_api(job_id, lead_idx, result_idx):
    """Mark a result as 'Not This Person' (archived) — keeps data, hides from active list."""
    job = jobs.get(job_id)
    if not job or lead_idx >= len(job['leads']):
        return jsonify({'error': 'Not found'}), 404
    lead        = job['leads'][lead_idx]
    folder_name = lead.get('folder_name', '')
    if not folder_name:
        return jsonify({'error': 'Lead not yet processed'}), 400
    lead_folder = os.path.join(job['folder'], folder_name)
    data_file   = os.path.join(lead_folder, 'data.json')
    try:
        with open(data_file, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({'error': f'Cannot read data: {e}'}), 500
    results = data.get('results', [])
    if result_idx >= len(results):
        return jsonify({'error': 'Result index out of range'}), 404
    results[result_idx]['archived'] = True
    data['results']  = results
    lead['count']    = len([r for r in results if not r.get('archived')])
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    report = build_lead_report(lead['name'], lead.get('location', ''),
                               results, lead_folder, folder_name,
                               job_id=job_id, lead_idx=lead_idx,
                               social_link=lead.get('social_link', ''),
                               email=lead.get('email', ''),
                               phone=lead.get('phone', ''))
    with open(os.path.join(lead_folder, 'report.html'), 'w', encoding='utf-8') as f:
        f.write(report)
    regenerate_index(job_id)
    save_jobs()
    return jsonify({'ok': True})

@app.route('/api/jobs/<job_id>/leads/<int:lead_idx>/results/<int:result_idx>/unarchive', methods=['POST'])
def unarchive_result_api(job_id, lead_idx, result_idx):
    """Restore an archived result back to the active list."""
    job = jobs.get(job_id)
    if not job or lead_idx >= len(job['leads']):
        return jsonify({'error': 'Not found'}), 404
    lead        = job['leads'][lead_idx]
    folder_name = lead.get('folder_name', '')
    if not folder_name:
        return jsonify({'error': 'Lead not yet processed'}), 400
    lead_folder = os.path.join(job['folder'], folder_name)
    data_file   = os.path.join(lead_folder, 'data.json')
    try:
        with open(data_file, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({'error': f'Cannot read data: {e}'}), 500
    results = data.get('results', [])
    if result_idx >= len(results):
        return jsonify({'error': 'Result index out of range'}), 404
    results[result_idx]['archived'] = False
    data['results']  = results
    lead['count']    = len([r for r in results if not r.get('archived')])
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    report = build_lead_report(lead['name'], lead.get('location', ''),
                               results, lead_folder, folder_name,
                               job_id=job_id, lead_idx=lead_idx,
                               social_link=lead.get('social_link', ''),
                               email=lead.get('email', ''),
                               phone=lead.get('phone', ''))
    with open(os.path.join(lead_folder, 'report.html'), 'w', encoding='utf-8') as f:
        f.write(report)
    regenerate_index(job_id)
    save_jobs()
    return jsonify({'ok': True})

@app.route('/results/<job_id>')
@app.route('/results/<job_id>/')
def results_page(job_id):
    load_jobs()
    job = jobs.get(job_id)
    if not job and os.path.exists(OUT_DIR):
        for entry in os.listdir(OUT_DIR):
            if job_id.upper() in entry.upper():
                cand = os.path.join(OUT_DIR, entry)
                if os.path.isdir(cand):
                    load_jobs()
                    job = jobs.get(job_id)
                    break
    if not job:
        return 'Job not found', 404

    if not job.get('share_token'):
        try:
            job['share_token'] = database.get_or_create_share_token(
                job['id'], job.get('user_id', 1), job.get('username', 'admin'),
                job.get('name', job['id']), job.get('status', 'complete'),
                job.get('total', 0), job.get('done', 0), job.get('folder', '')
            )
        except Exception:
            pass

    html_content = build_job_index(job, is_shared=False)
    resp = make_response(html_content)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/results/<job_id>/<path:subpath>')
def results_subpath(job_id, subpath):
    safe = subpath.replace('..', '').lstrip('/').lstrip('\\')
    def _deliver_file(path_to_deliver):
        resp = make_response(send_file(path_to_deliver))
        if path_to_deliver.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif')):
            resp.headers['Cache-Control'] = 'public, max-age=86400, immutable'
        return resp
    if job_id not in jobs:
        load_jobs(force=True)
    job = jobs.get(job_id)
    if not job and os.path.exists(OUT_DIR):
        for entry in os.listdir(OUT_DIR):
            if job_id.upper() in entry.upper():
                load_jobs(force=True)
                job = jobs.get(job_id)
                break

    # Dynamic render of lead report HTML
    if safe.endswith('.html'):
        folder_part = safe.split('/')[0] if '/' in safe else ''
        if folder_part and job:
            matched_lead = None
            matched_idx = 0
            for idx, lead in enumerate(job.get('leads', [])):
                lf = lead.get('folder_name', '')
                lname = safe_name(lead.get('name', ''), lead.get('location', '')) if lead.get('name') else ''
                if lf == folder_part or (lf and folder_part in lf) or (lf and lf in folder_part) or (lname and lname in folder_part):
                    matched_lead = lead
                    matched_idx = idx
                    break

            if matched_lead or (job and job.get('leads')):
                lead = matched_lead or job['leads'][0]
                idx = matched_idx
                jfolder = job.get('folder', '')
                lfolder = os.path.join(jfolder, folder_part) if jfolder else ''
                results = []
                djson = os.path.join(lfolder, 'data.json') if lfolder else ''
                if djson and os.path.exists(djson):
                    try:
                        with open(djson, 'r', encoding='utf-8') as df:
                            dj = json.load(df)
                            results = dj.get('results', [])
                    except Exception:
                        pass
                if not job.get('share_token'):
                    try:
                        job['share_token'] = database.get_or_create_share_token(
                            job['id'], job.get('user_id', 1), job.get('username', 'admin'),
                            job.get('name', job['id']), job.get('status', 'complete'),
                            job.get('total', 0), job.get('done', 0), job.get('folder', '')
                        )
                    except Exception:
                        pass
                html = build_lead_report(
                    lead['name'], lead.get('location', ''), results, lfolder or '', folder_part,
                    job_id=job['id'], lead_idx=idx,
                    social_link=lead.get('social_link', ''),
                    email=lead.get('email', ''),
                    phone=lead.get('phone', ''),
                    is_shared=False,
                    share_token=job.get('share_token', '')
                )
                resp = make_response(html)
                resp.headers['Content-Type'] = 'text/html; charset=utf-8'
                resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                return resp
    if job and job.get('folder'):
        c1 = os.path.join(job['folder'], safe)
        if os.path.exists(c1):
            return _deliver_file(c1)
        # Search inside lead subfolders if image/asset was requested relative to job root
        if os.path.isdir(job['folder']):
            for sub in os.listdir(job['folder']):
                cand = os.path.join(job['folder'], sub, safe)
                if os.path.isfile(cand):
                    return _deliver_file(cand)

    # Direct filesystem check in OUT_DIR
    if os.path.exists(OUT_DIR):
        for entry in os.listdir(OUT_DIR):
            if job_id.upper() in entry.upper():
                c = os.path.join(OUT_DIR, entry, safe)
                if os.path.exists(c):
                    return _deliver_file(c)

    # Check newest jobs first for subpaths
    for j in reversed(list(jobs.values())):
        jfolder = j.get('folder', '')
        c1 = os.path.join(jfolder, safe)
        if os.path.exists(c1):
            return _deliver_file(c1)
        c2 = os.path.join(jfolder, job_id, safe)
        if os.path.exists(c2):
            return _deliver_file(c2)

    full = os.path.join(OUT_DIR, safe)
    if os.path.exists(full):
        return _deliver_file(full)

    return 'File not found', 404

@app.route('/reports/<path:filepath>')
def serve_report(filepath):
    # Sanitize path — no traversal
    safe = filepath.replace('..', '').lstrip('/').lstrip('\\')
    full = os.path.join(OUT_DIR, safe)
    if os.path.exists(full):
        return send_file(full)
    # Also try treating filepath as relative to a job folder
    for jid, job in jobs.items():
        candidate = os.path.join(job.get('folder',''), safe)
        if os.path.exists(candidate):
            return send_file(candidate)
    return 'Not found', 404

# -- CLI mode ------------------------------------------------------------------
def cli_run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bulk', help='CSV file')
    parser.add_argument('--name', help='Single name')
    parser.add_argument('--location', default='')
    args = parser.parse_args()

    leads = []
    if args.bulk:
        leads = parse_csv_leads(args.bulk)
        print(f"Loaded {len(leads)} leads from {args.bulk}")
    elif args.name:
        leads = [{'name': args.name, 'location': args.location}]
    else:
        print("Usage: python app.py --bulk leads.csv")
        print("   or: python app.py --name 'John Smith' --location TX")
        return

    job_id = str(uuid.uuid4())[:8].upper()
    ts     = datetime.now()
    folder = os.path.join(OUT_DIR, f"job_{ts.strftime('%Y%m%d_%H%M%S')}_{job_id}")
    os.makedirs(folder, exist_ok=True)

    jobs[job_id] = {
        'id': job_id, 'name': f'CLI Job {job_id}',
        'status': 'queued', 'total': len(leads), 'done': 0,
        'current': '', 'folder': folder, 'created': ts.isoformat(),
        'index_path': '', 'pause_flag': False, 'cancel_flag': False,
        'leads': [{'name': l['name'], 'location': l.get('location',''),
                   'status': 'queued', 'count': 0, 'error': '',
                   'folder_name': '', 'cancel_flag': False} for l in leads],
    }
    run_job_bg(job_id)
    idx = jobs[job_id].get('index_path', '')
    if idx and os.path.exists(idx):
        print(f"\nOpening: {idx}")
        webbrowser.open(f"file:///{idx.replace(os.sep, '/')}")

if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    load_jobs()
    if '--bulk' in sys.argv or '--name' in sys.argv:
        cli_run()
    else:
        log_event(f"LeadsOSINT server running on http://127.0.0.1:{PORT}")
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

@app.route('/api/diagnostics')
def api_diagnostics():
    """Admin-only: tests BrightData connectivity and shows system info + recent logs."""
    user = get_current_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': 'Admin only'}), 403
    import platform, socket
    result = {
        'system': platform.system(),
        'python': platform.python_version(),
        'hostname': socket.gethostname(),
        'bd_api_key': (BD_API_KEY[:8] + '...') if BD_API_KEY else 'NOT SET',
        'bd_zone': BD_ZONE,
        'out_dir': OUT_DIR,
        'db_path': DB_PATH,
        'out_dir_exists': os.path.exists(OUT_DIR),
        'brightdata_test': None,
        'brightdata_error': None,
        'recent_logs': list(LOG_BUFFER)[-50:]
    }
    try:
        test_r = BD_SESSION.post(
            'https://api.brightdata.com/request',
            json={'zone': BD_ZONE, 'url': 'https://www.fastpeoplesearch.com/', 'format': 'raw', 'country': 'us'},
            headers={'Authorization': f'Bearer {BD_API_KEY}', 'Content-Type': 'application/json'},
            verify=False, timeout=20
        )
        brd_err = test_r.headers.get('x-brd-err-msg') or test_r.headers.get('x-brd-error', '')
        result['brightdata_test'] = {
            'http_status': test_r.status_code,
            'response_len': len(test_r.text),
            'brd_error': brd_err or None,
            'preview': test_r.text[:300]
        }
        result['brightdata_error'] = brd_err or (None if test_r.status_code == 200 else f'HTTP {test_r.status_code}')
    except Exception as e:
        result['brightdata_error'] = str(e)
    return jsonify(result)

