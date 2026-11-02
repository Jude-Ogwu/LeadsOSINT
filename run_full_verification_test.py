import requests, time, json

API = "http://127.0.0.1:5050"

payload = {
    "name": "Full Verification Job - Clean UI + Multi-threaded + Social Links",
    "leads_text": "Janet Leider, Simi Valley CA, facebook.com/janet.leider.ca\nHarold Kowalski, New Haven MI, linkedin.com/in/harold-kowalski-mi\nPatricia Miller, Chicago IL, twitter.com/patricia_miller_chi",
    "autostart": True
}

r = requests.post(f"{API}/api/jobs", json=payload)
print("Create Job Response:", r.status_code, r.json())
job_id = r.json()["id"]

print(f"Monitoring Job {job_id}...")
for _ in range(60):
    time.sleep(2)
    j = requests.get(f"{API}/api/jobs/{job_id}/status").json()
    if j and 'status' in j:
        print(f"Status: {j['status']} | Done: {j['done']}/{j['total']} | Speed: {j.get('speed','—')} | ETA: {j.get('eta','—')} | Current: {j['current']}")
        if j['status'] in ('complete', 'failed'):
            break

print("Finished monitoring job.")
