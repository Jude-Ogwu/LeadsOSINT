import requests, time, json

API = "http://127.0.0.1:5050"

payload = {
    "name": "Verification Job - 3 Leads",
    "leads_text": "Janet Leider, Simi Valley CA\nHarold Kowalski, New Haven MI\nPatricia Miller, Chicago IL",
    "autostart": True
}

r = requests.post(f"{API}/api/jobs", json=payload)
print("Create Job Response:", r.status_code, r.json())
job_id = r.json()["id"]

print(f"Monitoring Job {job_id}...")
for _ in range(90):
    time.sleep(3)
    res = requests.get(f"{API}/api/jobs").json()
    j = next((item for item in res if item["id"] == job_id), None)
    if j:
        print(f"Status: {j['status']} | Done: {j['done']}/{j['total']} | Current: {j['current']}")
        if j['status'] in ('complete', 'failed'):
            break

print("Finished monitoring job.")
