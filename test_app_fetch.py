import requests, json

BD_API_KEY = "88c5b773-fbd9-4602-abcc-3772d16891cb"

def bd_fetch(url):
    try:
        r = requests.post(
            "https://api.brightdata.com/request",
            json={"zone": "web_unlocker1", "url": url, "format": "raw", "country": "us"},
            headers={"Authorization": f"Bearer {BD_API_KEY}", "Content-Type": "application/json"},
            verify=False, timeout=45
        )
        return r.status_code, len(r.text)
    except Exception as e:
        return 0, str(e)

test_urls = {
    'FPS Name (Harold Kowalski)': 'https://www.fastpeoplesearch.com/name/harold-kowalski_new-haven-mi/',
    'FPS Phone (312-555-0199)': 'https://www.fastpeoplesearch.com/312-555-0199',
    'TPS Name (Harold Kowalski)': 'https://www.truepeoplesearch.com/results?name=Harold%20Kowalski&citystatezip=New%20Haven%20MI',
    'TPS Phone (3125550199)': 'https://www.truepeoplesearch.com/results?phoneno=3125550199',
}

for label, url in test_urls.items():
    code, length = bd_fetch(url)
    print(f"{label} -> Code: {code}, Bytes: {length}")
