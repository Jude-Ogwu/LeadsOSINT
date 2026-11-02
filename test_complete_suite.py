import sys
import os
import json

sys.path.append(r'C:\Users\JUDE\LeadsOSINT')
workspace_dir = r"c:\Users\JUDE\Documents\antigravity\excited-hypatia"
os.environ["DB_DIR"] = workspace_dir
test_out_dir = os.path.join(workspace_dir, "test_output")
os.makedirs(test_out_dir, exist_ok=True)
os.environ["OUT_DIR"] = test_out_dir

import database
import app as leads_app

leads_app.OUT_DIR = test_out_dir

test_client = leads_app.app.test_client()

print("=" * 60)
print("RUNNING COMPREHENSIVE END-TO-END AUTOMATED TEST SUITE")
print("=" * 60)

passed = 0
failed = 0

def test(name, condition, extra=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name} {extra}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {extra}")

# ── 1. Admin Authentication ───────────────────────────────────────────────────
print("\n--- 1. Testing Admin Authentication ---")
login_res = test_client.post('/api/auth/login', json={'username': 'admin', 'password': 'AdminOSINT2026!'})
test("Admin Login (200 OK)", login_res.status_code == 200)

admin_cookie = None
for header in login_res.headers.getlist('Set-Cookie'):
    if 'leads_session=' in header:
        admin_cookie = header.split('leads_session=')[1].split(';')[0]
        break

test("Admin Session Cookie set", bool(admin_cookie))

me_res = test_client.get('/api/auth/me')
me_data = me_res.get_json() or {}
test("Admin /api/auth/me Role == 'admin'", me_data.get('role') == 'admin')

# ── 2. Admin Credentials Update & Verification ────────────────────────────────
print("\n--- 2. Testing Admin Credentials Update ---")
# Try incorrect password
bad_pw_res = test_client.post('/api/auth/change-credentials', json={
    'current_password': 'WrongPassword123!',
    'new_password': 'NewAdminPassword2026!'
})
test("Reject wrong current password (400)", bad_pw_res.status_code == 400)

# Change password
change_pw_res = test_client.post('/api/auth/change-credentials', json={
    'current_password': 'AdminOSINT2026!',
    'new_password': 'TempAdminPassword2026!'
})
test("Accept valid credentials update (200)", change_pw_res.status_code == 200)

# Verify login with new password
new_login = test_client.post('/api/auth/login', json={'username': 'admin', 'password': 'TempAdminPassword2026!'})
test("Login with new credentials succeeds", new_login.status_code == 200)

# Restore original Admin credentials
restore_res = test_client.post('/api/auth/change-credentials', json={
    'current_password': 'TempAdminPassword2026!',
    'new_password': 'AdminOSINT2026!'
})
test("Restore default Admin credentials (200)", restore_res.status_code == 200)

# Re-login as Admin
test_client.post('/api/auth/login', json={'username': 'admin', 'password': 'AdminOSINT2026!'})

# ── 3. Customer Support Settings (WhatsApp Toggle & URL) ──────────────────────
print("\n--- 3. Testing Customer Support Settings ---")
supp_res = test_client.get('/api/settings/support')
test("Get support settings (200)", supp_res.status_code == 200)
supp_data = supp_res.get_json() or {}
test("Support settings has whatsapp_enabled", 'whatsapp_enabled' in supp_data)

# Admin toggles WhatsApp to OFF
toggle_off = test_client.post('/api/admin/settings/support', json={
    'whatsapp_enabled': False,
    'whatsapp_number': '+15551234567'
})
test("Admin toggles WhatsApp OFF (200)", toggle_off.status_code == 200)
check_off = test_client.get('/api/settings/support').get_json()
test("WhatsApp support is now disabled (False)", check_off.get('whatsapp_enabled') is False)

# Admin toggles WhatsApp back ON with number
toggle_on = test_client.post('/api/admin/settings/support', json={
    'whatsapp_enabled': True,
    'whatsapp_number': '+15559876543'
})
test("Admin toggles WhatsApp ON (200)", toggle_on.status_code == 200)
check_on = test_client.get('/api/settings/support').get_json()
test("WhatsApp support is now enabled (True)", check_on.get('whatsapp_enabled') is True)
test("WhatsApp URL generated with custom number", '15559876543' in check_on.get('whatsapp_url', ''))

# ── 4. Customer User Creation & Quota Management ──────────────────────────────
print("\n--- 4. Testing User Lifecycle & Quota Tracking ---")
# Clean up any previous test user
old_u = database.get_user_by_username('test_client_qa')
if old_u:
    database.delete_user(old_u['id'])

test_user_res = test_client.post('/api/admin/users', json={
    'username': 'test_client_qa',
    'password': 'ClientPassword2026!',
    'leads_allocated': 10
})
test("Create Customer User 'test_client_qa' (200)", test_user_res.status_code in (200, 201))

# Customer client
cust_client = leads_app.app.test_client()
cust_login = cust_client.post('/api/auth/login', json={'username': 'test_client_qa', 'password': 'ClientPassword2026!'})
test("Customer User Login (200)", cust_login.status_code == 200)

cust_me = cust_client.get('/api/auth/me').get_json()
test("Customer initial remaining leads == 10", cust_me.get('leads_remaining') == 10)

# Customer creates a job with 2 leads
job_res = cust_client.post('/api/jobs', json={
    'name': 'Test Quota Deduction Job',
    'leads_text': 'John Doe, Miami FL\nJane Smith, Tampa FL',
    'autostart': False
})
test("Customer submits 2 leads (200)", job_res.status_code in (200, 201))
job_data = job_res.get_json() or {}
test_job_id = job_data.get('id', '')
test("Job ID returned", bool(test_job_id))

# Verify quota deducted from 10 to 8
cust_me_after = cust_client.get('/api/auth/me').get_json()
test("Remaining quota reduced to 8 after 2 leads submitted", cust_me_after.get('leads_remaining') == 8)

# ── 5. Fair Credit Policy: Un-run / Cancelled Leads Refund ────────────────────
print("\n--- 5. Testing Fair Credit Policy (Refunds on Cancel & Technical Failures) ---")
# Customer cancels the job with unrun leads
cancel_res = cust_client.post(f'/api/jobs/{test_job_id}/cancel')
test("Cancel job endpoint (200)", cancel_res.status_code == 200)
cancel_data = cancel_res.get_json() or {}
test("Cancelled leads refunded counter > 0", cancel_data.get('refunded', 0) > 0)

# Verify remaining quota restored back to 10
cust_me_restored = cust_client.get('/api/auth/me').get_json()
test("Quota refunded back to 10 on job cancellation", cust_me_restored.get('leads_remaining') == 10)

# ── 6. In-App Messaging System ────────────────────────────────────────────────
print("\n--- 6. Testing In-App Messaging System ---")
# Customer sends message to Admin
send_msg_res = cust_client.post('/api/messages', json={
    'content': 'Hello Admin, I would like to inquire about enterprise bulk search options.'
})
test("Customer sends message to Admin (200)", send_msg_res.status_code == 200)
msg_id = send_msg_res.get_json().get('message_id')
test("Message ID generated", bool(msg_id))

# Admin checks unread messages count
unread_res = test_client.get('/api/messages/unread-count')
test("Admin gets unread count (200)", unread_res.status_code == 200)
unread_cnt = unread_res.get_json().get('unread_count', 0)
test("Unread message count >= 1 for Admin", unread_cnt >= 1)

# Admin marks single message as read
mark_read_res = test_client.post(f'/api/messages/{msg_id}/read')
test("Admin marks message as read (200)", mark_read_res.status_code == 200)

# Admin marks all messages as read
mark_all_res = test_client.post('/api/messages/mark-all-read')
test("Admin marks all messages read (200)", mark_all_res.status_code == 200)
unread_cnt_after = test_client.get('/api/messages/unread-count').get_json().get('unread_count')
test("Unread count is 0 after mark-all-read", unread_cnt_after == 0)

# ── 7. Network Health Check API ───────────────────────────────────────────────
print("\n--- 7. Testing Network Health Check API ---")
net_res = test_client.get('/api/network-status')
test("GET /api/network-status (200)", net_res.status_code == 200)
net_data = net_res.get_json() or {}
test("Network status is valid ('online', 'unstable', or 'offline')", net_data.get('status') in ('online', 'unstable', 'offline'))

# ── 8. FastBackgroundCheck Fallback Engine ─────────────────────────────────────
print("\n--- 8. Testing FastBackgroundCheck Fallback Integration ---")
fbc_func_exists = hasattr(leads_app, 'search_fastbackgroundcheck')
test("search_fastbackgroundcheck function exists in app.py", fbc_func_exists)
if fbc_func_exists:
    res = leads_app.search_fastbackgroundcheck("Jane", "Denver CO")
    test("FastBackgroundCheck safely handles queries without crashing", isinstance(res, list))

# ── 9. Report Routing Verification ────────────────────────────────────────────
print("\n--- 9. Testing Report Routing ---")
overview_res = test_client.get(f'/results/{test_job_id}')
test("GET /results/<job_id> serves Job Overview Dossier (200)", overview_res.status_code == 200)
test("Page contains Job Overview title or LeadsOSINT", b'LeadsOSINT' in overview_res.data or b'Job' in overview_res.data)

# Cleanup test user
cust_user = database.get_user_by_username('test_client_qa')
if cust_user:
    database.delete_user(cust_user['id'])

print("\n" + "=" * 60)
print(f"TEST SUITE SUMMARY: {passed} PASSED, {failed} FAILED")
print("=" * 60)

if failed == 0:
    print("ALL TESTS PASSED WITH 100% SUCCESS!")
    sys.exit(0)
else:
    print(f"FAILED: {failed} tests failed.")
    sys.exit(1)
