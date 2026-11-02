import os

app_path = r"C:\Users\JUDE\LeadsOSINT\app.py"
with open(app_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

clean_report_func = '''def build_lead_report(lead_name, location, results, lead_folder, lead_safe,
                      job_id='', lead_idx=0, social_link='', email='', phone=''):
    active_cards   = ''
    archived_cards = ''

    # Lead-level social link
    social_raw = social_link.strip() if social_link else ''
    if social_raw and not social_raw.startswith('http'):
        social_url = 'https://' + social_raw
    else:
        social_url = social_raw

    social_top_btn = (f'<a href="{social_url}" target="_blank" class="social-top-btn" onclick="event.stopPropagation()">🔗 Social: {social_raw}</a>'
                      if social_raw else '')
    social_stat_html = (f'<a href="{social_url}" target="_blank" class="url-link">{social_raw}</a>'
                        if social_raw else '<span style="color:var(--mt)">N/A</span>')

    # Lead-level email
    email_raw = email.strip() if email else ''
    email_top_btn = (f'<button class="social-top-btn" style="background:linear-gradient(135deg,#059669,#34d399);cursor:pointer;border:none" onclick="copySingle(\\'{email_raw}\\', \\'Input Email\\'); event.stopPropagation();">✉️ {email_raw}</button>'
                     if email_raw else '')
    email_stat_html = (f'<span style="color:var(--gn);font-weight:600">{email_raw}</span>'
                       if email_raw else '<span style="color:var(--mt)">N/A</span>')

    # Lead-level phone
    phone_raw = phone.strip() if phone else ''
    phone_top_btn = (f'<button class="social-top-btn" style="background:linear-gradient(135deg,#d97706,#fbbf24);color:#111;cursor:pointer;border:none" onclick="copySingle(\\'{phone_raw}\\', \\'Input Phone\\'); event.stopPropagation();">📞 {phone_raw}</button>'
                     if phone_raw else '')
    phone_stat_html = (f'<span style="color:var(--yw);font-weight:600">{phone_raw}</span>'
                       if phone_raw else '<span style="color:var(--mt)">N/A</span>')

    search_ss_file = f"{lead_safe}_search_page.png"
    has_search_ss  = os.path.exists(os.path.join(lead_folder, search_ss_file))

    if has_search_ss:
        search_ss_section = f\'\'\'
<div class="search-ss-card">
  <div class="search-ss-hdr">
    <div>
      <div class="search-ss-title">🌐 FastPeopleSearch — Full Search Page Overview</div>
      <div class="search-ss-sub">Live search results overview for "{lead_name}" ({location or "US"})</div>
    </div>
  </div>
  <div class="search-ss-body" onclick="openModal(\'{search_ss_file}\')">
    <img src="{search_ss_file}" class="search-ss-img" title="Click to view full search page screenshot">
    <div class="search-ss-overlay">🔍 Click to View Full Search Page Screenshot</div>
  </div>
</div>\'\'\'
    else:
        search_ss_section = ''

    for i, r in enumerate(results):
        is_archived = r.get('archived', False)
        display_num = i + 1
        ss_file = f"{lead_safe}_result_{display_num}.png"
        has_ss  = os.path.exists(os.path.join(lead_folder, ss_file))

        if has_ss:
            ss_html = f\'\'\'<div class="ss-wrap">
                <img src="{ss_file}" class="ss-thumb"
                     onclick="openModal(\'{ss_file}\')"
                     title="Click to view profile detail screenshot">
                <div class="ss-lbl">📸 Profile Detail Screenshot — click to zoom</div>
            </div>\'\'\'
        else:
            ss_html = ''

        addrs_html = ''.join(
            f'<div class="addr-row">📍 {a}</div>'
            for a in r.get('addresses', []) if a and a != 'N/A'
        ) or f'<div class="addr-row">📍 {r.get("address","N/A")}</div>'

        phones_list = r.get('phones', [])
        if phones_list:
            phones_json = json.dumps(phones_list).replace('"', '&quot;')
            copy_all_p = f'<button class="copy-all-btn" onclick="copyList({phones_json}, \\'Phones\\'); event.stopPropagation();">📋 Copy All Phones ({len(phones_list)})</button>'
            phones_html = copy_all_p + ''.join(
                f'<div class="addr-row">📞 <span>{p}</span> <button class="copy-item-btn" onclick="copySingle(\\'{p}\\', \\'Phone\\'); event.stopPropagation();" title="Copy phone">📋</button></div>'
                for p in phones_list
            )
        else:
            phones_html = '<div class="addr-row" style="color:#6b7280">📞 N/A — no phones listed</div>'

        emails_list = r.get('emails', [])
        if emails_list:
            emails_json = json.dumps(emails_list).replace('"', '&quot;')
            copy_all_e = f'<button class="copy-all-btn" onclick="copyList({emails_json}, \\'Emails\\'); event.stopPropagation();">📋 Copy All Emails ({len(emails_list)})</button>'
            emails_html = copy_all_e + ''.join(
                f'<div class="addr-row">✉️ <span>{e}</span> <button class="copy-item-btn" onclick="copySingle(\\'{e}\\', \\'Email\\'); event.stopPropagation();" title="Copy email">📋</button></div>'
                for e in emails_list
            )
        else:
            emails_html = '<div class="addr-row" style="color:#6b7280">✉️ N/A — no emails listed</div>'

        rels_html = ', '.join(r.get('relatives', [])) or 'N/A'
        aka_html  = ', '.join(r.get('aliases',  [])) or 'N/A'

        action_row = ''
        if job_id:
            if is_archived:
                action_row = f\'\'\'
  <div class="res-actions arch-mode">
    <span class="arch-label">🗃 Not This Person</span>
    <button class="res-btn unarch-btn" onclick="unarchiveResult({i})">↩ Restore</button>
    <button class="res-btn del-btn"   onclick="confirmDelete({i})">🗑 Delete Permanently</button>
  </div>\'\'\'
            else:
                action_row = f\'\'\'
  <div class="res-actions">
    <button class="res-btn arch-btn" onclick="archiveResult({i})">🗃 Not This Person</button>
    <button class="res-btn del-btn"  onclick="confirmDelete({i})">🗑 Delete Result</button>
  </div>\'\'\'

        card_html = f\'\'\'
<details class="rcard {\'archived-card\' if is_archived else \'\'}" id="rcard-{i}" open>
  <summary class="rcard-hdr">
    <span class="rnum">#{display_num}</span>
    <span class="rname">{r["name"]} · Age {r["age"]} · {r["city"]}</span>
    <span class="badge-group">
      <span class="badge-tag">📞 {len(phones_list)}</span>
      <span class="badge-tag">✉️ {len(emails_list)}</span>
    </span>
    {\'<span class="arch-tag">🗃 Not This Person</span>\' if is_archived else \'\'}
    <a href="{r["profile_url"]}" target="_blank" class="profile-btn" onclick="event.stopPropagation()">🔗 View Profile</a>
    <span class="expand-indicator">▼ Expand</span>
  </summary>
  <div class="rcard-body">
    <div class="rinfo">
      <div class="frow"><span class="fl">Full Name:</span><span class="fv fname">{r["name"]}</span></div>
      <div class="frow"><span class="fl">Age:</span><span class="fv">{r["age"]}</span></div>
      <div class="frow"><span class="fl">City / State:</span><span class="fv">{r["city"]}</span></div>
      <div class="frow"><span class="fl">Phone(s):</span><div class="addrs">{phones_html}</div></div>
      <div class="frow"><span class="fl">Email(s):</span><div class="addrs">{emails_html}</div></div>
      <div class="frow"><span class="fl">Address(es):</span><div class="addrs">{addrs_html}</div></div>
      <div class="frow"><span class="fl">Relatives:</span><span class="fv">{rels_html}</span></div>
      <div class="frow"><span class="fl">AKA / Aliases:</span><span class="fv">{aka_html}</span></div>
      <div class="frow"><span class="fl">Profile URL:</span>
        <a href="{r["profile_url"]}" target="_blank" class="url-link">{r["profile_url"]}</a></div>
    </div>
    {ss_html}
  </div>
  {action_row}
</details>\'\'\'
        if is_archived:
            archived_cards += card_html
        else:
            active_cards   += card_html

    archived_section = ''
    if archived_cards:
        archived_section = f\'\'\'
<details class="arch-section" {\'open\' if not active_cards else \'\'}>
  <summary>🗃 Not This Person — {archived_cards.count(\'rcard-hdr\')} archived result(s) <span>(click to expand)</span></summary>
  <div class="arch-inner">{archived_cards}</div>
</details>\'\'\'

    cards_html = active_cards + archived_section
    if not active_cards and not archived_cards:
        cards_html = \'<div class="empty">No results found for this lead.</div>\'

    active_count = sum(1 for r in results if not r.get(\'archived\', False))
    ts = datetime.now().strftime(\'%B %d, %Y · %I:%M %p\')

    back_href = f"/results/{job_id}" if job_id else "../index.html"

    return f\'\'\'<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{lead_name} — LeadsOSINT</title>
<style>
:root{{--bg:#0d0f1a;--s:#1a1d3a;--s2:#22264a;--bd:#3a3f7a;--ac:#a78bfa;--ac2:#6d28d9;
      --tx:#e0e6ff;--mt:#8b95c4;--gn:#34d399;--rd:#f87171;--bl:#60a5fa;--yw:#fbbf24}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh}}
.topbar{{background:linear-gradient(135deg,#1a1d3a,#0d0f1a);border-bottom:1px solid var(--bd);
         padding:18px 40px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.back{{background:var(--s2);border:1px solid var(--bd);color:var(--ac);padding:9px 18px;
       border-radius:9px;font-size:.85rem;text-decoration:none;transition:.2s}}
.back:hover{{border-color:var(--ac);background:var(--ac2);color:#fff}}
.ttl h1{{font-size:1.5rem;color:#fff;font-weight:700}}
.ttl p{{color:var(--mt);font-size:.8rem;margin-top:3px}}
.social-top-btn{{background:linear-gradient(135deg,#2563eb,#60a5fa);color:#fff;padding:8px 16px;border-radius:9px;font-size:.82rem;font-weight:700;text-decoration:none;transition:.2s;box-shadow:0 4px 14px rgba(37,99,235,.3)}}
.social-top-btn:hover{{transform:translateY(-1px);color:#fff;box-shadow:0 6px 20px rgba(96,165,250,.4)}}
.stats{{display:flex;gap:14px;padding:20px 40px;background:var(--s);border-bottom:1px solid var(--bd);flex-wrap:wrap}}
.sp{{background:var(--bg);border:1px solid var(--bd);border-radius:10px;
     padding:12px 20px;text-align:center}}
.sp.hi{{border-color:var(--ac);background:rgba(167,139,250,.07)}}
.sv{{font-size:1.4rem;font-weight:800;color:var(--ac)}}
.sl{{font-size:.7rem;color:var(--mt);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}}
.content{{padding:28px 40px;max-width:1400px;margin:0 auto}}
.rcard{{background:var(--s);border:1px solid var(--bd);border-radius:16px;
        margin-bottom:24px;overflow:hidden;transition:.4s all}}
.rcard:hover{{border-color:var(--ac);transform:translateY(-2px);
              box-shadow:0 10px 36px rgba(109,40,217,.2)}}
.rcard.removing{{opacity:0;transform:translateY(-12px) scale(.97);pointer-events:none}}
.archived-card{{opacity:.55;border-style:dashed;filter:grayscale(.3)}}
.rcard-hdr{{background:linear-gradient(135deg,var(--s2),var(--s));padding:16px 24px;
            display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--bd);flex-wrap:wrap;cursor:pointer;list-style:none}}
.rcard-hdr::-webkit-details-marker{{display:none}}
.rnum{{background:linear-gradient(135deg,var(--ac2),var(--ac));color:#fff;
       font-size:.78rem;font-weight:700;padding:4px 12px;border-radius:16px;flex-shrink:0}}
.rname{{font-size:1.15rem;font-weight:700;color:#fff;flex:1}}
.badge-group{{display:flex;gap:6px;align-items:center}}
.badge-tag{{background:rgba(167,139,250,.15);border:1px solid rgba(167,139,250,.3);color:var(--ac);font-size:.75rem;padding:3px 8px;border-radius:6px;font-weight:600}}
.expand-indicator{{color:var(--ac);font-size:.8rem;font-weight:700;margin-left:8px}}
.arch-tag{{background:rgba(251,191,36,.15);border:1px solid rgba(251,191,36,.3);
           color:var(--yw);font-size:.72rem;padding:3px 10px;border-radius:10px;flex-shrink:0}}
.profile-btn{{background:linear-gradient(135deg,#4c3d8f,var(--ac2));color:#fff;
              padding:8px 16px;border-radius:9px;font-size:.8rem;
              font-weight:600;text-decoration:none;transition:.2s;flex-shrink:0}}
.profile-btn:hover{{background:linear-gradient(135deg,var(--ac2),var(--ac));
                    transform:translateY(-1px);color:#fff}}
.copy-all-btn{{background:linear-gradient(135deg,var(--ac2),var(--ac3));color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:.75rem;font-weight:600;cursor:pointer;margin-bottom:6px;display:inline-block}}
.copy-all-btn:hover{{background:var(--ac2)}}
.copy-item-btn{{background:transparent;border:none;color:var(--mt);cursor:pointer;font-size:.8rem;padding:0 4px;margin-left:auto}}
.copy-item-btn:hover{{color:var(--ac)}}
.addr-row{{color:#c4caf0;font-size:.88rem;padding:6px 12px;
           background:rgba(255,255,255,.03);border-radius:7px;border:1px solid var(--bd);display:flex;align-items:center;gap:8px}}
.url-link{{color:var(--bl);font-size:.82rem;word-break:break-all;text-decoration:underline}}
.url-link:hover{{color:var(--ac)}}
.rcard-body{{padding:24px 28px;display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}}
.rinfo{{flex:1;min-width:320px;display:flex;flex-direction:column;gap:14px}}
.frow{{display:grid;grid-template-columns:140px 1fr;gap:12px;align-items:start;font-size:.92rem}}
.fl{{font-weight:700;color:var(--mt);font-size:.85rem;letter-spacing:.3px;padding-top:4px}}
.fv{{color:#fff;font-weight:600;line-height:1.5}}
.fname{{font-size:1.15rem;color:var(--ac);font-weight:700}}
.ss-wrap{{flex:0 0 320px;display:flex;flex-direction:column;align-items:center}}
.ss-thumb{{width:100%;border-radius:10px;border:2px solid var(--bd);cursor:pointer;
           transition:.2s;display:block}}
.ss-thumb:hover{{border-color:var(--ac);transform:scale(1.02);
                 box-shadow:0 6px 24px rgba(167,139,250,.3)}}
.ss-lbl{{color:var(--mt);font-size:.78rem;margin-top:8px;text-align:center}}
.ss-missing{{color:var(--mt);font-size:.82rem;padding:20px;text-align:center;
             background:var(--s2);border-radius:10px;border:1px dashed var(--bd)}}
.res-actions{{padding:14px 24px;border-top:1px solid var(--bd);
              display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.res-actions.arch-mode{{background:rgba(251,191,36,.04)}}
.res-btn{{padding:8px 16px;border-radius:8px;font-size:.8rem;font-weight:600;
          cursor:pointer;transition:.2s;border:1px solid;background:transparent}}
.arch-btn{{border-color:rgba(251,191,36,.5);color:var(--yw);}}
.arch-btn:hover{{background:rgba(251,191,36,.1)}}
.del-btn{{border-color:rgba(248,113,113,.5);color:var(--rd);}}
.del-btn:hover{{background:rgba(248,113,113,.1)}}
.unarch-btn{{border-color:rgba(96,165,250,.5);color:var(--bl);}}
.unarch-btn:hover{{background:rgba(96,165,250,.1)}}
.arch-label{{font-size:.8rem;color:var(--yw);flex:1}}
.arch-section{{margin-top:10px;border-radius:14px;border:1px dashed var(--bd);overflow:hidden}}
.arch-section summary{{padding:14px 20px;cursor:pointer;color:var(--mt);font-size:.9rem;
                       font-weight:600;list-style:none;background:var(--s2);
                       display:flex;align-items:center;gap:8px}}
.arch-section summary:hover{{color:var(--tx)}}
.arch-section summary span{{font-size:.75rem;font-weight:400;margin-left:auto;color:var(--mt)}}
.arch-inner{{padding:16px}}
.empty{{background:var(--s);border:2px dashed var(--bd);border-radius:14px;
        padding:50px;text-align:center;color:var(--mt);font-size:1rem}}
.search-ss-card{{background:var(--s);border:1px solid var(--bd);border-radius:16px;margin-bottom:28px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.3)}}
.search-ss-hdr{{background:linear-gradient(135deg,var(--s2),var(--s));padding:16px 24px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}}
.search-ss-title{{font-weight:700;color:#fff;font-size:1.05rem}}
.search-ss-sub{{font-size:.78rem;color:var(--mt);margin-top:2px}}
.search-ss-body{{position:relative;cursor:pointer;max-height:380px;overflow:hidden;background:#0d0f1a}}
.search-ss-img{{width:100%;display:block;opacity:.88;transition:.3s all}}
.search-ss-body:hover .search-ss-img{{opacity:1;transform:scale(1.005)}}
.search-ss-overlay{{position:absolute;bottom:16px;left:50%;transform:translateX(-50%);background:rgba(13,15,26,.88);border:1px solid var(--ac);color:var(--ac);padding:8px 20px;border-radius:20px;font-size:.8rem;font-weight:700;backdrop-filter:blur(6px);pointer-events:none;box-shadow:0 4px 14px rgba(109,40,217,.3)}}
.toast{{position:fixed;bottom:24px;right:24px;background:var(--s);
        border:1px solid var(--bd);border-radius:12px;padding:12px 20px;
        font-size:.85rem;z-index:999;transform:translateY(60px);opacity:0;
        transition:.3s;max-width:280px}}
.toast.show{{transform:translateY(0);opacity:1}}
.toast.ok{{border-color:rgba(52,211,153,.4);color:var(--gn)}}
.toast.err{{border-color:rgba(248,113,113,.4);color:var(--rd)}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.96);z-index:9999;
        justify-content:center;align-items:center;padding:20px}}
.modal.open{{display:flex}}
.modal-img{{max-width:95vw;max-height:90vh;border-radius:12px;border:2px solid var(--ac)}}
.modal-x{{position:fixed;top:18px;right:28px;color:var(--ac);font-size:2.2rem;
          cursor:pointer;z-index:10000;transition:.2s}}
.modal-x:hover{{color:#fff;transform:scale(1.1)}}
.confirm-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);
                  z-index:8888;justify-content:center;align-items:center}}
.confirm-overlay.open{{display:flex}}
.confirm-box{{background:var(--s);border:1px solid var(--rd);border-radius:18px;
              padding:32px 36px;max-width:380px;text-align:center}}
.confirm-box h3{{color:#fff;margin-bottom:10px;font-size:1.1rem}}
.confirm-box p{{color:var(--mt);font-size:.88rem;margin-bottom:24px;line-height:1.6}}
.confirm-btns{{display:flex;gap:12px;justify-content:center}}
.cb-cancel{{padding:10px 24px;border-radius:9px;border:1px solid var(--bd);
            background:var(--s2);color:var(--tx);cursor:pointer;font-size:.9rem}}
.cb-delete{{padding:10px 24px;border-radius:9px;border:none;
            background:linear-gradient(135deg,#b91c1c,var(--rd));color:#fff;
            cursor:pointer;font-size:.9rem;font-weight:700}}
</style></head><body>
<div class="topbar">
  <a href="{back_href}" class="back" onclick="if(window.location.protocol===\\'file:\\'){{this.href=\\'../index.html\\'}}">← Back to Job</a>
  <div class="ttl"><h1>🔍 {lead_name}</h1>
    <p>Location: {location or "Not specified"} · {ts}</p></div>
  <div style="display:flex;gap:8px;margin-left:auto;flex-wrap:wrap">
    {social_top_btn}
    {email_top_btn}
    {phone_top_btn}
  </div>
</div>
<div class="stats">
  <div class="sp hi"><div class="sv" id="active-count">{active_count}</div><div class="sl">Active Results</div></div>
  <div class="sp"><div class="sv" style="color:{\'var(--gn)\' if results else \'var(--rd)\'}">
    {\'✓ Found\' if results else \'✗ None\'}</div><div class="sl">Status</div></div>
  <div class="sp"><div class="sv" style="font-size:.9rem">{location or \'N/A\'}</div>
    <div class="sl">Location</div></div>
  <div class="sp"><div class="sv" style="font-size:.85rem">{social_stat_html}</div>
    <div class="sl">Social Link</div></div>
  <div class="sp"><div class="sv" style="font-size:.85rem">{email_stat_html}</div>
    <div class="sl">Input Email</div></div>
  <div class="sp"><div class="sv" style="font-size:.85rem">{phone_stat_html}</div>
    <div class="sl">Input Phone</div></div>
</div>
<div class="content">
{search_ss_section}
{cards_html}
</div>
<div class="toast" id="toast"></div>
<div class="modal" id="modal" onclick="if(event.target===this)this.classList.remove(\'open\')">
  <span class="modal-x" onclick="document.getElementById(\'modal\').classList.remove(\'open\')">✕</span>
  <img id="modal-img" src="" class="modal-img" onclick="event.stopPropagation()">
</div>
<div class="confirm-overlay" id="confirm-overlay">
  <div class="confirm-box">
    <h3>🗑 Delete This Result?</h3>
    <p>This will permanently remove the result and its screenshot.<br>This <strong>cannot be undone</strong>.</p>
    <div class="confirm-btns">
      <button class="cb-cancel" onclick="closeConfirm()">Cancel</button>
      <button class="cb-delete" id="cb-confirm-btn" onclick="doDelete()">Delete Permanently</button>
    </div>
  </div>
</div>
<script>
const JOB_ID   = \'{job_id}\';
const LEAD_IDX = {lead_idx};
const API      = \'http://localhost:{PORT}\';
let _pendingDeleteIdx = null;

function copySingle(val, label) {{
  navigator.clipboard.writeText(val).then(() => {{
    showToast(label + \' copied to clipboard!\', \'ok\');
  }}).catch(() => {{
    const ta = document.createElement(\'textarea\');
    ta.value = val;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand(\'copy\');
    document.body.removeChild(ta);
    showToast(label + \' copied!\', \'ok\');
  }});
}}

function copyList(arr, label) {{
  if (!arr || !arr.length) return;
  const text = arr.join(\'\\\\\\\\n\');
  navigator.clipboard.writeText(text).then(() => {{
    showToast(arr.length + \' \' + label + \' copied to clipboard!\', \'ok\');
  }}).catch(() => {{
    const ta = document.createElement(\'textarea\');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand(\'copy\');
    document.body.removeChild(ta);
    showToast(arr.length + \' \' + label + \' copied!\', \'ok\');
  }});
}}

function openModal(src){{
  document.getElementById(\'modal-img\').src=src;
  document.getElementById(\'modal\').classList.add(\'open\');
}}
document.addEventListener(\'keydown\',e=>{{
  if(e.key===\'Escape\'){{
    document.getElementById(\'modal\').classList.remove(\'open\');
    closeConfirm();
  }}
}});

function showToast(msg, type=\'ok\'){{
  const t = document.getElementById(\'toast\');
  t.textContent = msg;
  t.className = \'toast \' + type + \' show\';
  setTimeout(()=>t.classList.remove(\'show\'), 3000);
}}

function confirmDelete(idx){{
  _pendingDeleteIdx = idx;
  document.getElementById(\'confirm-overlay\').classList.add(\'open\');
}}
function closeConfirm(){{
  document.getElementById(\'confirm-overlay\').classList.remove(\'open\');
  _pendingDeleteIdx = null;
}}
async function doDelete(){{
  closeConfirm();
  if (_pendingDeleteIdx === null || !JOB_ID) return;
  await deleteResult(_pendingDeleteIdx);
}}
async function deleteResult(idx){{
  if (!JOB_ID) {{ showToast(\'No job ID — open via dashboard\', \'err\'); return; }}
  const card = document.getElementById(\'rcard-\' + idx);
  if (card) card.classList.add(\'removing\');
  try {{
    const r = await fetch(`${{API}}/api/jobs/${{JOB_ID}}/leads/${{LEAD_IDX}}/results/${{idx}}/delete`,
                          {{method:\'POST\'}});
    const d = await r.json();
    if (r.ok) {{
      setTimeout(()=>{{ if(card) card.remove(); updateCount(-1); }}, 400);
      showToast(\'Result deleted permanently\', \'ok\');
    }} else {{
      if (card) card.classList.remove(\'removing\');
      showToast(d.error || \'Delete failed\', \'err\');
    }}
  }} catch(e) {{
    if (card) card.classList.remove(\'removing\');
    showToast(\'Network error\', \'err\');
  }}
}}
async function archiveResult(idx){{
  if (!JOB_ID) {{ showToast(\'No job ID — open via dashboard\', \'err\'); return; }}
  const r = await fetch(`${{API}}/api/jobs/${{JOB_ID}}/leads/${{LEAD_IDX}}/results/${{idx}}/archive`,
                        {{method:\'POST\'}});
  if (r.ok) {{
    showToast(\'Marked as Not This Person\', \'ok\');
    setTimeout(()=>location.reload(), 800);
  }} else {{
    const d = await r.json();
    showToast(d.error || \'Archive failed\', \'err\');
  }}
}}
async function unarchiveResult(idx){{
  if (!JOB_ID) return;
  const r = await fetch(`${{API}}/api/jobs/${{JOB_ID}}/leads/${{LEAD_IDX}}/results/${{idx}}/unarchive`,
                        {{method:\'POST\'}});
  if (r.ok) {{
    showToast(\'Result restored\', \'ok\');
    setTimeout(()=>location.reload(), 800);
  }}
}}
function updateCount(delta){{
  const el = document.getElementById(\'active-count\');
  if (el) el.textContent = Math.max(0, parseInt(el.textContent||\'0\') + delta);
}}
</script>
</body></html>\'\'\'
'''

# Find build_lead_report start and end
start_pos = content.find("def build_lead_report")
end_pos = content.find("def build_job_index")

if start_pos != -1 and end_pos != -1:
    content = content[:start_pos] + clean_report_func + "\n\n" + content[end_pos:]
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("build_lead_report cleaned and updated successfully!")
else:
    print("Error: Could not find build_lead_report boundaries!")
