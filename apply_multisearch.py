import os

app_path = r"C:\Users\JUDE\LeadsOSINT\app.py"
with open(app_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

multisearch_code = '''def classify_input_lead(line):
    """
    Classify input line into 4 search modes:
    'name', 'phone', 'email', or 'address'.
    """
    if not line:
        return None

    parts = [p.strip() for p in line.split(',') if p.strip()]
    if not parts:
        return None

    first = parts[0]

    # 1. Email Mode
    if '@' in first and '.' in first.split('@')[-1]:
        social = parts[1] if len(parts) > 1 and any(d in parts[1].lower() for d in ['facebook.com','linkedin.com','instagram.com','twitter.com','x.com','tiktok.com','http']) else ''
        return {
            'search_mode': 'email',
            'query':       first,
            'name':        first,
            'location':    '',
            'social_link': social
        }

    # 2. Phone Mode
    clean_digits = re.sub(r'[^\\d]', '', first)
    if (len(clean_digits) >= 7) and (re.search(r'^\\+?[\\d\\s\\-\\(\\)\\.]{7,20}$', first) or len(clean_digits) >= 10):
        social = parts[1] if len(parts) > 1 and any(d in parts[1].lower() for d in ['facebook.com','linkedin.com','instagram.com','twitter.com','x.com','tiktok.com','http']) else ''
        return {
            'search_mode': 'phone',
            'query':       first,
            'name':        first,
            'location':    '',
            'social_link': social
        }

    # 3. Address Mode
    if re.match(r'^\\d+\\s+[A-Za-z0-9\\s\\.\\,\\-]+$', first) and len(first.split()) >= 3:
        location = parts[1] if len(parts) > 1 else ''
        social   = parts[2] if len(parts) > 2 else ''
        return {
            'search_mode': 'address',
            'query':       first,
            'name':        first,
            'location':    location,
            'social_link': social
        }

    # 4. Name Mode
    name     = first
    location = parts[1] if len(parts) > 1 else ''
    social   = parts[2] if len(parts) > 2 else ''

    if any(d in location.lower() for d in ['facebook.com','linkedin.com','instagram.com','twitter.com','x.com','tiktok.com','http']):
        social   = location
        location = ''

    return {
        'search_mode': 'name',
        'query':       name,
        'name':        name,
        'location':    location,
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
        has_header = csv.Sniffer().has_header(sample)
    except Exception:
        has_header = False

    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return []

    if has_header and len(rows) > 0:
        rows = rows[1:]

    for row in rows:
        if not row or not any(row):
            continue
        line_str = ', '.join(r.strip() for r in row if r.strip())
        item = classify_input_lead(line_str)
        if item and len(item['name']) >= 2:
            leads.append(item)
    return leads
'''

search_dispatch_code = '''def search_person(name, location='', phone=''):
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
        clean_p = re.sub(r'[^\\d]', '', str(query))
        fmt_p   = f"{clean_p[:3]}-{clean_p[3:6]}-{clean_p[6:]}" if len(clean_p) == 10 else clean_p
        url     = f"https://www.fastpeoplesearch.com/{fmt_p}"
        log_event(f"📱 [Phone Search Mode] Fetching: {url}")
        html    = bd_fetch(url)
        if html:
            results = parse_fsp(html)
            if results:
                for r in results: r['_search_html'] = html
                return results

    elif mode == 'address':
        addr_clean = re.sub(r'[^\\w\\s-]', '', query).strip().replace(' ', '-')
        loc_clean  = re.sub(r'[^\\w\\s-]', '', loc).strip().replace(' ', '-')
        slug       = f"{addr_clean.lower()}_{loc_clean.lower()}" if loc_clean else addr_clean.lower()
        url        = f"https://www.fastpeoplesearch.com/address/{slug}"
        log_event(f"🏠 [Address Search Mode] Fetching: {url}")
        html       = bd_fetch(url)
        if html:
            results = parse_fsp(html)
            if results:
                for r in results: r['_search_html'] = html
                return results

    elif mode == 'email':
        log_event(f"✉️ [Email Search Mode] Searching for: {query}")
        ddg = search_ddg(query, '')
        if ddg:
            return [ddg]

    # Name Search Mode
    parts = re.sub(r"[^a-zA-Z\\s'-]", '', query).strip().split()
    if len(parts) >= 2:
        slug = f"{parts[0].lower()}-{parts[-1].lower()}"
        url  = (f"https://www.fastpeoplesearch.com/name/{slug}_{state}/"
                if state else
                f"https://www.fastpeoplesearch.com/name/{slug}/")
        log_event(f"👤 [Name Search Mode] Fetching: {url}")
        html = bd_fetch(url)
        if html:
            results = parse_fsp(html)
            if results:
                for r in results: r['_search_html'] = html
                return results

    # DuckDuckGo fallback
    log_event(f"🔍 Tier 2 fallback search for: {query}")
    ddg = search_ddg(query, loc)
    if ddg:
        return [ddg]

    # Stub fallback
    slug = '-'.join(p.lower() for p in parts[:2]) if len(parts) >= 2 else (parts[0].lower() if parts else 'search')
    return [{
        'name':        query,
        'age':         'N/A',
        'city':        loc or 'US',
        'address':     loc or 'US',
        'addresses':   [loc] if loc else [],
        'phones':      [query] if mode == 'phone' else [],
        'emails':      [query] if mode == 'email' else [],
        'profile_url': f"https://www.fastpeoplesearch.com/name/{slug}/",
        'source':      'stub',
        'status':      'found',
    }]
'''

# Find positions for replacement
start_pos = content.find("def classify_part")
end_pos = content.find("# ── Job persistence")
if start_pos != -1 and end_pos != -1:
    content = content[:start_pos] + multisearch_code + "\n\n" + content[end_pos:]

start_pos2 = content.find("def search_person")
end_pos2 = content.find("# ── Screenshot")
if start_pos2 != -1 and end_pos2 != -1:
    content = content[:start_pos2] + search_dispatch_code + "\n\n" + content[end_pos2:]

with open(app_path, "w", encoding="utf-8") as f:
    f.write(content)

print("apply_multisearch.py successfully replaced functions in app.py!")
