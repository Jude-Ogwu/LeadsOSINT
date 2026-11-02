import requests, time, os, json

text_input = "Harold Kowalski, New Haven MI"

print("🚀 Creating test job for report HTML inspection...")
r = requests.post('http://127.0.0.1:5050/api/jobs', json={
    'name': 'Clean HTML Verification Job',
    'autostart': True,
    'leads_text': text_input
})

job_id = r.json()['id']
print("Job ID:", job_id)

for _ in range(30):
    time.sleep(2)
    st = requests.get(f'http://127.0.0.1:5050/api/jobs/{job_id}/status').json()
    print("Job status:", st['status'], "done:", st['done'])
    if st['status'] in ('complete', 'cancelled', 'failed'):
        break

# Fetch job details to get folder name
job_data = requests.get(f'http://127.0.0.1:5050/api/jobs/{job_id}').json()
folder = job_data['folder']
lead_folder_name = job_data['leads'][0]['folder_name']
lead_folder = os.path.join(folder, lead_folder_name)
report_path = os.path.join(lead_folder, 'report.html')

print("Reading generated report.html:", report_path)
with open(report_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Check for duplicates or raw CSS text leaks
topbar_count = html.count('class="topbar"')
stats_count  = html.count('class="stats"')
has_raw_css  = 'padding:32px 36px;max-width:380px' in html

print(f"\nRESULTS:")
print(f"  ✅ Topbar Count: {topbar_count} (Expected: 1)")
print(f"  ✅ Stats Banner Count: {stats_count} (Expected: 1)")
print(f"  ✅ Raw CSS Leaked: {has_raw_css} (Expected: False)")
