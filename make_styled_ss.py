import sys, os, re
sys.path.append(r'C:\Users\JUDE\LeadsOSINT')
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from fsp_profile_parser import unobfuscate_html_emails

with open(r'C:\Users\JUDE\OSINT_Reports\_p2_hildegard-kowalski.html', 'r', encoding='utf-8') as f:
    html = f.read()

clean = unobfuscate_html_emails(html)
clean = re.sub(r'<script[^>]*>.*?</script>', '', clean, flags=re.S | re.I)
clean = re.sub(r'<iframe[^>]*>.*?</iframe>', '', clean, flags=re.S | re.I)

fsp_css = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
* { box-sizing: border-box; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important; background-color: #f4f6f9 !important; color: #212529 !important; line-height: 1.5; margin: 0; padding: 0; }
a { color: #0066cc !important; text-decoration: none !important; }
a:hover { text-decoration: underline !important; }

/* Header Navbar */
header, .navbar, .hdr, [class*="nav"], [class*="header"] { background: #1d2438 !important; color: #fff !important; padding: 12px 24px !important; }
.navbar-brand, .brand { color: #fff !important; font-weight: 800; font-size: 1.25rem; }

/* Container & Sections */
.container, .container-fluid, .site-content { max-width: 1080px !important; margin: 0 auto !important; padding: 20px 15px !important; }
.detail-box, .card, .person-content-block, [class*="detail"], [class*="card"] { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 8px !important; padding: 24px !important; margin-bottom: 20px !important; box-shadow: 0 2px 4px rgba(0,0,0,0.04) !important; }

/* Headings */
h1, h2, h3, h4, .h1, .h2, .h3, .h4 { font-weight: 700 !important; color: #0f172a !important; margin-top: 0 !important; }
h1 { font-size: 1.75rem !important; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; margin-bottom: 16px; }
h2, h3 { font-size: 1.25rem !important; margin-bottom: 14px; }

/* List items & details */
ul { list-style: none !important; padding-left: 0 !important; }
li { padding: 8px 0 !important; border-bottom: 1px solid #f1f5f9; }
li:last-child { border-bottom: none; }

/* Badges & Buttons */
.badge, .btn-success, [class*="btn"] { font-weight: 600 !important; border-radius: 4px !important; }
.btn-success { background-color: #10b981 !important; color: #fff !important; border: none !important; padding: 8px 16px !important; display: inline-block !important; }

/* Footer */
footer, .ftr { background: #1d2438 !important; color: #94a3b8 !important; padding: 30px 15px !important; margin-top: 40px !important; font-size: 0.85rem !important; text-align: center; }
</style>"""

clean = fsp_css + clean
tmp_html = r'C:\Users\JUDE\OSINT_Reports\_tmp_styled.html'
with open(tmp_html, 'w', encoding='utf-8') as f:
    f.write(clean)

out_png = r'C:\Users\JUDE\OSINT_Reports\_styled_profile.png'
tmp_uri = 'file:///' + tmp_html.replace('\\', '/')

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
    page    = browser.new_page(viewport={'width': 1200, 'height': 900})
    page.goto(tmp_uri, wait_until='domcontentloaded', timeout=20000)
    page.wait_for_timeout(1000)
    page.screenshot(path=out_png, full_page=True)
    browser.close()

print('SUCCESS: Created styled profile screenshot at:', out_png)
