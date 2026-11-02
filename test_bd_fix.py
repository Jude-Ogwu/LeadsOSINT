import requests, urllib3
urllib3.disable_warnings()

BD_API_KEY = "88c5b773-fbd9-4602-abcc-3772d16891cb"
url = "https://www.fastpeoplesearch.com/name/harold-kowalski_mi/"

payload = {
    "zone": "web_unlocker1",
    "url": url,
    "format": "raw",
    "country": "us"
}

headers = {
    "Authorization": f"Bearer {BD_API_KEY}",
    "Content-Type": "application/json"
}

print("Sending BD US Unlocker request...")
r = requests.post("https://api.brightdata.com/request", json=payload, headers=headers, verify=False, timeout=45)
print(f"Status Code: {r.status_code}")
print(f"Body Length: {len(r.text):,} bytes")
has_card = 'class="card"' in r.text
print("Contains card element:", has_card)
