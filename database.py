"""
SQLite Database and Multi-Tenant User Management for LeadsOSINT.
Handles user accounts, admin authentication, plan quotas, expiration countdowns,
in-app messaging, job ownership, account-bound shareable dossiers,
and plaintext access_key retention for administrative support.
"""
import sqlite3
import os
import hashlib
import uuid
from datetime import datetime, timedelta

DB_DIR = os.environ.get("DB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "leadsosint.db")

WHATSAPP_SUPPORT_URL = os.environ.get(
    "WHATSAPP_SUPPORT",
    "https://api.whatsapp.com/send?text=Hi%20Admin,%20I%20would%20like%20to%20purchase/top-up%20more%20leads%20for%20my%20LeadsOSINT%20account"
)

PLAN_CONFIGS = {
    'free': {
        'duration_hours': 5,
        'daily_limit': 50,
        'per_job_limit': 10,
        'total_limit': 50,
        'label': 'Free Trial (5h · Max 50 Total · Max 10/Job)'
    },
    'daily': {
        'duration_hours': 24,
        'daily_limit': 500,
        'per_job_limit': 50,
        'total_limit': 500,
        'label': 'Daily Plan (24h · Max 500/Day · Max 50/Job)'
    },
    'weekly': {
        'duration_hours': 24 * 7,
        'daily_limit': 2000,
        'per_job_limit': 500,
        'total_limit': 14000,
        'label': 'Weekly Plan (7d · Max 2,000/Day · Max 14,000 Total · Max 500/Job)'
    },
    'monthly': {
        'duration_hours': 24 * 30,
        'daily_limit': 5000,
        'per_job_limit': 1000,
        'total_limit': 150000,
        'label': 'Monthly Plan (30d · Max 5,000/Day · Max 150,000 Total · Max 1,000/Job)'
    }
}

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return conn

def hash_pw(password, salt=None):
    if not salt:
        salt = uuid.uuid4().hex[:16]
    hashed = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}${hashed}"

def verify_pw(password, stored_hash):
    if not stored_hash or '$' not in stored_hash:
        return False
    salt, hash_val = stored_hash.split('$', 1)
    test_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return test_hash == hash_val

def init_db():
    """Initializes tables and seeds default admin account."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            access_key TEXT DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user',
            plan TEXT NOT NULL DEFAULT 'free',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            daily_limit INTEGER NOT NULL DEFAULT 50,
            per_job_limit INTEGER NOT NULL DEFAULT 10,
            plan_total_limit INTEGER NOT NULL DEFAULT 50,
            total_usage INTEGER NOT NULL DEFAULT 0,
            today_usage INTEGER NOT NULL DEFAULT 0,
            last_usage_date TEXT NOT NULL
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            total INTEGER NOT NULL,
            done INTEGER NOT NULL,
            folder TEXT NOT NULL,
            created_at TEXT NOT NULL,
            share_token TEXT UNIQUE,
            share_token_expires_at TEXT DEFAULT ''
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            sender_username TEXT NOT NULL,
            receiver_id INTEGER,
            receiver_username TEXT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        ''')
        conn.commit()

        # Migrations: ensure new columns exist in existing database
        cursor.execute("PRAGMA table_info(users)")
        cols = [row[1] for row in cursor.fetchall()]
        if 'access_key' not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN access_key TEXT DEFAULT ''")
        if 'total_usage' not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN total_usage INTEGER DEFAULT 0")
        if 'plan_total_limit' not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN plan_total_limit INTEGER DEFAULT 50")

        cursor.execute("PRAGMA table_info(jobs)")
        jcols = [row[1] for row in cursor.fetchall()]
        if 'share_token_expires_at' not in jcols:
            cursor.execute("ALTER TABLE jobs ADD COLUMN share_token_expires_at TEXT DEFAULT ''")
        conn.commit()

        # Seed default Admin account if not present
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            now_iso = datetime.now().isoformat()
            exp_iso = (datetime.now() + timedelta(days=3650)).isoformat()
            cursor.execute('''
                INSERT INTO users (username, password_hash, access_key, role, plan, status, created_at, expires_at, daily_limit, per_job_limit, plan_total_limit, total_usage, today_usage, last_usage_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            ''', ('admin', hash_pw('AdminOSINT2026!'), 'AdminOSINT2026!', 'admin', 'monthly', 'active', now_iso, exp_iso, 999999, 999999, 99999999, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
        else:
            # Ensure admin has access_key populated
            cursor.execute("UPDATE users SET access_key = 'AdminOSINT2026!' WHERE username = 'admin' AND (access_key IS NULL OR access_key = '')")
            conn.commit()

        # Seed beta/tester users from beta_users.json if present
        beta_seed_path = os.path.join(os.path.dirname(__file__), 'beta_users.json')
        if os.path.exists(beta_seed_path):
            import json as _json
            try:
                with open(beta_seed_path, 'r') as _f:
                    beta_users = _json.load(_f)
                for bu in beta_users:
                    _uname = bu.get('username', '').strip()
                    _pw    = bu.get('password', '').strip()
                    _leads = int(bu.get('leads', 50))
                    _role  = bu.get('role', 'user')
                    _plan  = bu.get('plan', f'{_leads} Leads')
                    if not _uname or not _pw:
                        continue
                    cursor.execute("SELECT id FROM users WHERE username = ?", (_uname,))
                    if cursor.fetchone():
                        continue  # already exists, skip
                    _now = datetime.now()
                    _exp = (_now + timedelta(days=3650)).isoformat()
                    cursor.execute('''
                        INSERT INTO users (username, password_hash, access_key, role, plan, status, created_at, expires_at,
                                           daily_limit, per_job_limit, plan_total_limit, total_usage, today_usage, last_usage_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    ''', (_uname, hash_pw(_pw), _pw, _role, _plan, 'active',
                          _now.isoformat(), _exp, _leads, _leads, _leads,
                          _now.strftime('%Y-%m-%d')))
                conn.commit()
            except Exception:
                pass  # never crash startup due to bad seed file

def create_user(username, password, leads_allocated=50, role='user', plan=None):
    """Admin function to create a new user with a specific lead allowance."""
    leads = int(leads_allocated) if leads_allocated else 50
    plan_name = plan if plan else f"{leads} Leads"
    now = datetime.now()
    exp = (now + timedelta(days=3650)).isoformat()
    
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, access_key, role, plan, status, created_at, expires_at, daily_limit, per_job_limit, plan_total_limit, total_usage, today_usage, last_usage_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            ''', (username.strip(), hash_pw(password), password.strip(), role, plan_name, 'active', now.isoformat(), exp,
                  leads, leads, leads, now.strftime('%Y-%m-%d')))
            conn.commit()
            return cursor.lastrowid, None
        except sqlite3.IntegrityError:
            return None, f"User '{username}' already exists"
        except Exception as e:
            return None, str(e)

def add_user_leads(user_id, leads_to_add):
    """Admin function to top-up / add more leads to an existing user."""
    leads = int(leads_to_add)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET plan_total_limit = plan_total_limit + ?,
                status = CASE WHEN status = 'frozen' THEN 'active' ELSE status END
            WHERE id = ?
        """, (leads, user_id))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_user_by_id(user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        u = dict(row)
        if u['role'] != 'admin' and u['status'] == 'active':
            allocated = u.get('plan_total_limit') or 50
            used = u.get('total_usage') or 0
            if (allocated - used) <= 0:
                cursor.execute("UPDATE users SET status = 'frozen' WHERE id = ?", (user_id,))
                conn.commit()
                u['status'] = 'frozen'
        return u

def get_user_by_username(username):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None

def list_all_users():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, access_key, role, plan, status, created_at, expires_at, daily_limit, per_job_limit, plan_total_limit, total_usage, today_usage, last_usage_date FROM users ORDER BY id DESC")
        users = [dict(r) for r in cursor.fetchall()]
        for u in users:
            allocated = u.get('plan_total_limit') or 50
            used = u.get('total_usage') or 0
            rem = max(0, allocated - used)
            u['remaining'] = rem
            if u['role'] != 'admin':
                if rem <= 0 and u['status'] != 'terminated':
                    u['status'] = 'frozen'
        return users

def update_user_status(user_id, new_status):
    """Update status to active, paused, frozen, or terminated."""
    if new_status not in ('active', 'paused', 'frozen', 'terminated'):
        return False, "Invalid status"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))
        conn.commit()
        return True, None

def delete_user(user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return True

def create_session(user):
    token = uuid.uuid4().hex
    now = datetime.now()
    exp = now + timedelta(days=7)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (token, user_id, username, role, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (token, user['id'], user['username'], user['role'], now.isoformat(), exp.isoformat()))
        conn.commit()
    return token

def get_session(token):
    if not token:
        return None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            return None
        sess = dict(row)
        if datetime.fromisoformat(sess['expires_at']) < datetime.now():
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return sess

def destroy_session(token):
    if not token:
        return
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()

def check_user_quota_and_status(user_id, lead_count):
    """
    Validates if user has enough allocated leads to submit a job with lead_count leads.
    Returns (allowed: bool, reason: str, user_dict: dict, is_frozen: bool)
    """
    user = get_user_by_id(user_id)
    if not user:
        return False, "User not found", None, False
        
    if user['status'] == 'paused':
        return False, "Your account is paused. Please contact Admin via WhatsApp to resume.", user, True
    if user['status'] == 'frozen':
        return False, "Your account is frozen (0 leads remaining). Please contact Admin via WhatsApp to top up.", user, True
    if user['status'] == 'terminated':
        return False, "Your account has been terminated. Please contact Admin.", user, True

    if user['role'] == 'admin':
        return True, None, user, False

    total_allocated = user.get('plan_total_limit', 50)
    total_usage = user.get('total_usage', 0)
    remaining = max(0, total_allocated - total_usage)

    # If user has 0 leads remaining, their account is frozen
    if remaining <= 0:
        return False, f"All allocated leads used ({total_usage}/{total_allocated}). Please contact Admin on WhatsApp to top up your leads.", user, True

    # Check if job requires more leads than remaining balance
    if lead_count > remaining:
        return False, f"Insufficient lead credits! You have {remaining} leads remaining, but this job requires {lead_count}. Please reduce batch size or contact Admin to top up.", user, False

    return True, None, user, False

def record_user_usage(user_id, count):
    """Increments the user's daily and total usage counters and auto-freezes if depleted."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET today_usage = today_usage + ?, total_usage = total_usage + ? WHERE id = ?", (count, count, user_id))
        cursor.execute("""
            UPDATE users 
            SET status = 'frozen' 
            WHERE id = ? AND role != 'admin' AND status = 'active' AND total_usage >= plan_total_limit
        """, (user_id,))
        conn.commit()

# ── In-App Messaging ──────────────────────────────────────────────────────────
def send_message(sender_id, sender_username, receiver_id, content, receiver_username=''):
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (sender_id, sender_username, receiver_id, receiver_username, content, created_at, is_read)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (sender_id, sender_username, receiver_id, receiver_username, content.strip(), now_iso))
        conn.commit()
        return cursor.lastrowid

def get_messages_for_user(user_id, role='user'):
    with get_db() as conn:
        cursor = conn.cursor()
        if role == 'admin':
            cursor.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 100")
        else:
            cursor.execute('''
                SELECT * FROM messages 
                WHERE receiver_id = ? OR receiver_id = 0 OR receiver_id IS NULL OR sender_id = ?
                ORDER BY id DESC LIMIT 50
            ''', (user_id, user_id))
        return [dict(r) for r in cursor.fetchall()]

# ── Share Tokens (Account-Bound Status) ─────────────────────────────────────────
def get_or_create_share_token(job_id, user_id, username, name, status, total, done, folder):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT share_token FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        
        # If token exists, return it permanently
        if row and row['share_token']:
            return row['share_token']
        
        # Generate new token bound to job & user account
        token = uuid.uuid4().hex[:12]
        now_iso = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO jobs (id, user_id, username, name, status, total, done, folder, created_at, share_token, share_token_expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
        ''', (job_id, user_id, username, name, status, total, done, folder, now_iso, token))
        conn.commit()
        return token

def get_job_by_share_token(token):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE share_token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            return None, "not_found"
        
        job = dict(row)
        user_id = job.get('user_id')
        if user_id:
            user = get_user_by_id(user_id)
            if not user:
                return job, "frozen"
            if user.get('status') in ('frozen', 'paused', 'terminated'):
                return job, "frozen"
            if user.get('role') != 'admin':
                total_allocated = user.get('plan_total_limit', 50)
                total_usage = user.get('total_usage', 0)
                remaining = max(0, total_allocated - total_usage)
                if remaining <= 0:
                    return job, "frozen"
        return job, "valid"


def reset_share_token(job_id, user_id=None, username=None, name=None, folder=None):
    """
    Revokes the current share token and generates a brand new one.
    All previous share links become invalid (404) immediately.
    Returns the new token.
    """
    new_token = uuid.uuid4().hex[:12]
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
        if cursor.fetchone():
            cursor.execute("UPDATE jobs SET share_token = ? WHERE id = ?", (new_token, job_id))
        else:
            now_iso = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO jobs (id, user_id, username, name, status, total, done, folder, created_at, share_token, share_token_expires_at)
                VALUES (?, ?, ?, ?, 'complete', 0, 0, ?, ?, ?, '')
            """, (job_id, user_id or 1, username or 'admin', name or job_id, folder or '', now_iso, new_token))
        conn.commit()
    return new_token

def revoke_share_token(job_id):
    """Completely revokes public sharing for a job."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET share_token = '' WHERE id = ?", (job_id,))
        conn.commit()


def refund_user_usage(user_id, count=1):
    """Refunds usage count back to user (e.g. if lead failed due to technical error)."""
    if count <= 0 or not user_id:
        return
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET today_usage = MAX(0, today_usage - ?),
                total_usage = MAX(0, total_usage - ?),
                status = CASE WHEN status = 'frozen' THEN 'active' ELSE status END
            WHERE id = ? AND role != 'admin'
        """, (count, count, user_id))
        conn.commit()

def get_setting(key, default=None):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default

def set_setting(key, value):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()

def get_support_settings():
    enabled = get_setting('whatsapp_enabled', '1') == '1'
    number = get_setting('whatsapp_number', '')
    custom_url = get_setting('whatsapp_url', '')
    if not custom_url:
        if number:
            clean_num = ''.join(c for c in number if c.isdigit() or c == '+')
            custom_url = f"https://api.whatsapp.com/send?phone={clean_num.replace('+', '')}&text=Hi%20Admin,%20I%20need%20support%20with%20LeadsOSINT"
        else:
            custom_url = WHATSAPP_SUPPORT_URL
    return {
        'whatsapp_enabled': enabled,
        'whatsapp_number': number,
        'whatsapp_url': custom_url,
        'in_app_enabled': True
    }

def mark_message_read(message_id, user_id=None, role='user'):
    with get_db() as conn:
        cursor = conn.cursor()
        if role == 'admin':
            cursor.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
        else:
            cursor.execute("UPDATE messages SET is_read = 1 WHERE id = ? AND (receiver_id = ? OR receiver_id = 0 OR receiver_id IS NULL)", (message_id, user_id))
        conn.commit()
        return True

def mark_all_messages_read(user_id, role='user'):
    with get_db() as conn:
        cursor = conn.cursor()
        if role == 'admin':
            cursor.execute("UPDATE messages SET is_read = 1 WHERE is_read = 0")
        else:
            cursor.execute("UPDATE messages SET is_read = 1 WHERE is_read = 0 AND (receiver_id = ? OR receiver_id = 0 OR receiver_id IS NULL)", (user_id,))
        conn.commit()
        return True

def get_unread_message_count(user_id, role='user'):
    with get_db() as conn:
        cursor = conn.cursor()
        if role == 'admin':
            cursor.execute("SELECT COUNT(*) AS cnt FROM messages WHERE is_read = 0 AND (receiver_id = 1 OR receiver_id = 0 OR receiver_id IS NULL)")
        else:
            cursor.execute("SELECT COUNT(*) AS cnt FROM messages WHERE is_read = 0 AND (receiver_id = ? OR receiver_id = 0 OR receiver_id IS NULL)", (user_id,))
        row = cursor.fetchone()
        return row['cnt'] if row else 0

def update_credentials(user_id, current_password, new_username=None, new_password=None):
    """Allows user or admin to change their username and/or password with current password verification."""
    user = get_user_by_id(user_id)
    if not user:
        return False, "User not found"
    if not verify_pw(current_password, user['password_hash']):
        return False, "Incorrect current password"
    
    new_username = (new_username or user['username']).strip()
    if not new_username:
        return False, "Username cannot be empty"
    
    pw_hash = hash_pw(new_password) if new_password else user['password_hash']
    access_key = new_password if new_password else user.get('access_key', '')
    
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE users 
                SET username = ?, password_hash = ?, access_key = ?
                WHERE id = ?
            """, (new_username, pw_hash, access_key, user_id))
            cursor.execute("UPDATE sessions SET username = ? WHERE user_id = ?", (new_username, user_id))
            conn.commit()
            return True, None
        except sqlite3.IntegrityError:
            return False, f"Username '{new_username}' is already in use"
        except Exception as e:
            return False, str(e)

# Initialize on import
init_db()
