"""
Full FSP profile detail page parser with Cloudflare email decoding.
Extracts ALL available fields from the profile page HTML.
"""
from bs4 import BeautifulSoup
import re


def decode_cf_email(cfemail):
    """Decode Cloudflare obfuscated email string."""
    try:
        r = int(cfemail[:2], 16)
        return ''.join([chr(int(cfemail[i:i+2], 16) ^ r) for i in range(2, len(cfemail), 2)])
    except Exception:
        return ''


def unobfuscate_html_emails(html):
    """Replace all Cloudflare protected email tags with actual decoded email text."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(attrs={'data-cfemail': True}):
        decoded = decode_cf_email(tag['data-cfemail'])
        if decoded:
            new_tag = soup.new_tag('span')
            new_tag.string = decoded
            tag.replace_with(new_tag)
    return str(soup)


def parse_fsp_profile(html):
    """
    Parse a FastPeopleSearch PROFILE DETAIL page.
    Returns a dict with all available fields including decoded emails.
    """
    # 1. Un-obfuscate Cloudflare emails first
    html_clean = unobfuscate_html_emails(html)
    soup = BeautifulSoup(html_clean, 'html.parser')
    text = soup.get_text(' ', strip=True)
    result = {}

    # ── Name ──────────────────────────────────────────────────────────────────
    name_el = (
        soup.find('h1') or
        soup.find('span', {'itemprop': 'name'}) or
        soup.find('div', class_=re.compile(r'profile.*name|name.*profile|person.*name', re.I))
    )
    result['name'] = name_el.get_text(strip=True) if name_el else ''

    # ── Age ───────────────────────────────────────────────────────────────────
    age_m = re.search(r'\bAge\s+(\d{1,3})\b', text, re.I)
    result['age'] = age_m.group(1) if age_m else 'N/A'

    # ── City ──────────────────────────────────────────────────────────────────
    city_m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+([A-Z]{2})\b', text)
    result['city'] = f"{city_m.group(1)}, {city_m.group(2)}" if city_m else 'N/A'

    # ── Phone Numbers ─────────────────────────────────────────────────────────
    raw_phones = re.findall(r'\(?\d{3}\)?[\s\.\-]\d{3}[\s\.\-]\d{4}', text)
    phones = []
    seen_p = set()
    for p in raw_phones:
        digits = re.sub(r'\D', '', p)
        if digits not in seen_p and len(digits) == 10:
            seen_p.add(digits)
            phones.append(f"({digits[:3]}) {digits[3:6]}-{digits[6:]}")
    result['phones'] = phones[:12]

    # ── Email Addresses ───────────────────────────────────────────────────────
    raw_emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
    skip = {'fastpeoplesearch', 'example', 'pixel', 'track', 'spam', 'noreply',
            'privacy', 'contact', 'support', 'info@', 'tim.it'}
    emails = list(dict.fromkeys(
        e for e in raw_emails
        if not any(s in e.lower() for s in skip)
    ))
    result['emails'] = emails[:10]

    # ── Full Addresses ────────────────────────────────────────────────────────
    addrs = []
    for a in soup.find_all('a', href=re.compile(r'^/address/')):
        href = a['href'].replace('/address/', '')
        parts = href.split('_')
        street = parts[0].replace('-', ' ').title() if parts else ''
        loc = ''
        if len(parts) > 1:
            raw_loc = re.sub(r'-\d{5}.*$', '', parts[1])
            loc_p = raw_loc.rsplit('-', 1)
            if len(loc_p) == 2 and len(loc_p[1]) == 2:
                loc = f"{loc_p[0].replace('-', ' ').title()}, {loc_p[1].upper()}"
            else:
                loc = raw_loc.replace('-', ' ').upper()
        addrs.append(f"{street} · {loc}" if loc else street)
    result['addresses'] = list(dict.fromkeys(addrs))[:10]

    # ── Relatives ─────────────────────────────────────────────────────────────
    relatives = []
    for a in soup.find_all('a', href=re.compile(r'^/name/')):
        t = a.get_text(strip=True)
        if t and 3 < len(t) < 50 and not t.startswith('View'):
            relatives.append(t)
    result['relatives'] = list(dict.fromkeys(relatives))[:10]

    # ── AKA / Aliases ─────────────────────────────────────────────────────────
    aka_m = re.search(r'AKA[:\s]+(.*?)(?:\n|Phone|Email|Address|Relative|\Z)',
                      text, re.I | re.S)
    if aka_m:
        aka_raw = aka_m.group(1)[:300]
        result['aliases'] = [a.strip() for a in re.split(r'[•|,]', aka_raw) if a.strip()][:6]
    else:
        result['aliases'] = []

    # ── Possible Associates ───────────────────────────────────────────────────
    assoc_m = re.search(r'(?:Possible Associate|Associated)[:\s]+(.*?)(?:\n\n|Phone|Email|\Z)',
                        text, re.I | re.S)
    result['associates'] = assoc_m.group(1)[:300].strip() if assoc_m else ''

    # ── Employment / Work ─────────────────────────────────────────────────────
    work_m = re.search(r'(?:Employm|Workplace|Work Hist|Business)[:\s]+(.*?)(?:\n\n|\Z)',
                       text, re.I | re.S)
    result['employment'] = work_m.group(1)[:300].strip() if work_m else ''

    # ── FREE Background Report Narrative ─────────────────────────────────────
    bg_report = ''
    for h in soup.find_all(re.compile(r'h[1-4]')):
        if 'free background report' in h.get_text().lower():
            parent = h.parent
            if parent:
                clone = BeautifulSoup(str(parent), 'html.parser')
                h_el = clone.find(re.compile(r'h[1-4]'))
                if h_el:
                    h_el.decompose()
                raw_bg = clone.get_text(' ', strip=True)
                bg_report = re.sub(r'\s+', ' ', raw_bg).strip()
            break
    result['free_background_report'] = bg_report

    # ── Source ────────────────────────────────────────────────────────────────
    result['source'] = 'bd_profile'

    return result

