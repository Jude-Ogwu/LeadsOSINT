# 🔍 LeadsOSINT v2 — Complete User Guide

> **Tool**: Bulk People Search · **Source**: FastPeopleSearch via Bright Data  
> **Access**: Web UI at `http://localhost:5050` or command line  
> **Author**: Built with Antigravity

---

## Table of Contents

1. [What This Tool Does](#1-what-this-tool-does)
2. [Prerequisites & Installation](#2-prerequisites--installation)
3. [Starting the Tool](#3-starting-the-tool)
4. [Web UI — Full Walkthrough](#4-web-ui--full-walkthrough)
   - [4.1 Dashboard Layout](#41-dashboard-layout)
   - [4.2 Creating a New Job](#42-creating-a-new-job)
   - [4.3 Pasting Leads](#43-pasting-leads)
   - [4.4 Uploading a CSV File](#44-uploading-a-csv-file)
   - [4.5 Monitoring a Running Job](#45-monitoring-a-running-job)
   - [4.6 Per-Lead Controls](#46-per-lead-controls)
   - [4.7 Job-Level Controls](#47-job-level-controls)
   - [4.8 Renaming a Job](#48-renaming-a-job)
   - [4.9 Deleting a Job](#49-deleting-a-job)
   - [4.10 Viewing Results](#410-viewing-results)
5. [CLI — Full Walkthrough](#5-cli--full-walkthrough)
   - [5.1 Single Person Search](#51-single-person-search)
   - [5.2 Bulk CSV Search](#52-bulk-csv-search)
6. [Input Formatting Rules](#6-input-formatting-rules)
7. [Output — What Gets Created](#7-output--what-gets-created)
8. [Reading Your Results](#8-reading-your-results)
9. [Troubleshooting](#9-troubleshooting)
10. [Tips for Best Results](#10-tips-for-best-results)
11. [Quick Reference Card](#11-quick-reference-card)

---

## 1. What This Tool Does

LeadsOSINT takes a list of people (leads) and automatically:

1. Searches **FastPeopleSearch** for each name + location
2. Collects the **first page of results only** (no pagination — just what FSP shows first)
3. For each result found, extracts:
   - ✅ Full Name
   - ✅ Age
   - ✅ City / State
   - ✅ Address(es)
   - ✅ Clickable Profile URL
4. Takes a **full-page screenshot** of each result's FSP profile (using Bright Data to bypass blocks)
5. Saves everything into **per-lead folders** with an HTML report and screenshot images
6. Names each screenshot after the **lead name** (e.g. `John_Smith_TX_result_1.png`)
7. Generates a **master job index** you can browse in your browser

> **Bright Data Web Unlocker** is the engine — it routes requests through US IPs so FastPeopleSearch never blocks us.

---

## 2. Prerequisites & Installation

### What You Need Installed
| Tool | Check | Install If Missing |
|------|-------|-------------------|
| Python 3.9+ | `python --version` | [python.org](https://python.org) |
| pip | `pip --version` | comes with Python |
| Playwright browsers | `playwright install chromium` | see below |

### One-Time Setup (run these once)
Open PowerShell and run:

```powershell
# 1. Install Python packages
pip install flask requests beautifulsoup4 playwright

# 2. Install Playwright browser (Chromium)
playwright install chromium

# 3. Confirm your Bright Data key is set in app.py
# Open C:\Users\JUDE\LeadsOSINT\app.py and verify:
# BD_API_KEY = "88c5b773-fbd9-4602-abcc-3772d16891cb"
# BD_ZONE    = "web_unlocker1"
```

### Folder Locations
| File | Location |
|------|----------|
| Main app | `C:\Users\JUDE\LeadsOSINT\app.py` |
| Web UI template | `C:\Users\JUDE\LeadsOSINT\templates\index.html` |
| All output reports | `C:\Users\JUDE\OSINT_Reports\` |
| Job registry (saved jobs) | `C:\Users\JUDE\OSINT_Reports\jobs_registry.json` |

---

## 3. Starting the Tool

### Web UI Mode (recommended)
Open PowerShell, then:

```powershell
python C:\Users\JUDE\LeadsOSINT\app.py
```

The browser will **automatically open** to `http://localhost:5050`.

You'll see:
```
================================================
  LeadsOSINT v2 — http://localhost:5050
================================================
 * Running on http://127.0.0.1:5050
```

> **Keep this PowerShell window open** while using the tool. Closing it stops the server.

### CLI Mode (no browser needed)
```powershell
# Single person
python C:\Users\JUDE\LeadsOSINT\app.py --name "John Smith" --location TX

# Bulk CSV
python C:\Users\JUDE\LeadsOSINT\app.py --bulk C:\Users\JUDE\my_leads.csv
```

> Results open automatically in your browser when done.

---

## 4. Web UI — Full Walkthrough

### 4.1 Dashboard Layout

When you open `http://localhost:5050`, you see two sections:

```
┌─ HEADER ─────────────────────────────────────────────────────┐
│  🔍 LeadsOSINT                              [+ New Job]       │
├─ SIDEBAR ──────┬─ MAIN AREA ───────────────────────────────── │
│                │                                              │
│  JOBS          │  [Create New Job Form]                       │
│  ─────         │  OR                                          │
│  ● Job 1       │  [Selected Job's Lead List]                  │
│  ✓ Job 2       │                                              │
│                │                                              │
└────────────────┴──────────────────────────────────────────────┘
```

- **Left sidebar**: Lists all your jobs (current + past). Colour dot = status
- **Main area**: Shows either the "Create New Job" form or your selected job's details
- **Header**: `+ New Job` button always available

**Sidebar dot colours:**
| Colour | Meaning |
|--------|---------|
| 🟢 Green blinking | Currently running |
| 🟣 Purple | Complete |
| 🟡 Yellow | Queued (not started) |
| 🔵 Blue | Paused |
| 🔴 Red | Failed |

---

### 4.2 Creating a New Job

Click **`+ New Job`** in the top-right (or it's already shown if no job is selected).

**Steps:**
1. **Job Name** *(optional)* — type a label like `"Batch 1 - Texas Leads"`. If you leave it blank, it auto-names itself.
2. Choose your input method: **Paste Leads** tab or **Upload CSV** tab
3. Enter your leads (see sections 4.3 and 4.4 below)
4. Click **🚀 Create Job & Start Processing**

The job immediately appears in the left sidebar with a blinking green dot and processing begins automatically.

---

### 4.3 Pasting Leads

Click the **📋 Paste Leads** tab. Type or paste your leads into the text box.

**Rules — one lead per line:**

```
John Smith, Houston TX          ← Name, City State
Jane Doe, New York NY           ← Name, City State
Michael Brown, TX               ← Name, State only (works)
Sarah Johnson, California       ← Name, full state name (works)
Bob Wilson                      ← Name only, no location (still searched, wider results)
David Lee, Atlanta Georgia      ← Name, City spelled-out state
```

**What the tool accepts:**
- `Name, City ST` — most precise (e.g. `John Smith, Dallas TX`)
- `Name, ST` — state only (e.g. `John Smith, TX`)
- `Name, Full State` — (e.g. `John Smith, Texas`)
- `Name` — no location (broadest search, most results)
- `Name ST` — no comma, just space before 2-letter state code

**What to avoid:**
- Initials only (`J. Smith` — needs at least first + last name)
- Numbers or symbols in the name
- Lines starting with `#` are treated as comments and skipped

---

### 4.4 Uploading a CSV File

Click the **📂 Upload CSV** tab.

**Either:**
- Drag and drop your `.csv` or `.txt` file onto the box
- Or click the box to browse and select the file

**CSV format rules:**

```csv
Name,Location
John Smith,Houston TX
Jane Doe,New York NY
Michael Johnson,TX
Bob Wilson,
```

> - Header row (`Name,Location`) is **optional** — the tool auto-detects it
> - Location column is **optional** — you can leave it blank (empty cell)
> - The file can be saved as `.csv` or `.txt`
> - Encoding: UTF-8, Latin-1, or Windows (cp1252) — all handled automatically

**Minimal CSV (name only):**
```csv
John Smith
Jane Doe
Michael Johnson
```

---

### 4.5 Monitoring a Running Job

After creating a job, click it in the left sidebar to open it. You'll see:

```
┌─ JOB HEADER ────────────────────────────────────────────┐
│  My Texas Leads  [▶ Start All] [⏸ Pause] [✕ Cancel]    │
│  [📊 Open Report] [🗑 Delete]                            │
│  Status: RUNNING · Leads: 10 · Done: 3                  │
├─ PROGRESS BAR ──────────────────────────────────────────┤
│  ████████░░░░░░░░░░  35%        3 / 10                  │
│  Currently: [2/10] Jane Doe                              │
├─ LEADS LIST ────────────────────────────────────────────┤
│  #1  John Smith, TX       ✅ DONE    10 results  [📄]   │
│  #2  Jane Doe, NY         ⚙️ RUNNING  ...         [✕]   │
│  #3  Michael Johnson      ⏳ QUEUED   —            [▶][✕]│
│  #4  Sarah Brown, FL      ⏳ QUEUED   —            [▶][✕]│
└─────────────────────────────────────────────────────────┘
```

The page **auto-updates every 2 seconds** — no need to refresh.

**Lead status badges:**
| Badge | What It Means |
|-------|--------------|
| ✅ DONE | Search complete, results saved |
| ⚙️ RUNNING | This lead is being processed right now |
| ⏳ QUEUED | Waiting its turn |
| ❌ FAILED | Error occurred (see error message below the name) |
| ✕ CANCELLED | Manually cancelled |
| ⏸ PAUSED | Job paused between leads |

---

### 4.6 Per-Lead Controls

Each lead in the list has its own buttons on the right side:

| Button | When It Appears | What It Does |
|--------|----------------|-------------|
| **▶ Start** | Lead is Queued/Cancelled | Runs just this one lead immediately |
| **🔄 Retry** | Lead Failed | Re-runs the search for this lead |
| **✕ Cancel** | Lead is Queued or Running | Stops this lead (marks as cancelled) |
| **📄 Report** | Lead is Done | Opens the full HTML report for this lead |

> **▶ Start** lets you run individual leads without starting the whole job. Useful when you want to test one lead first, or re-run a specific person.

---

### 4.7 Job-Level Controls

These buttons appear at the top of the job panel:

| Button | What It Does |
|--------|-------------|
| **▶ Start All** | Begins processing all queued/unstarted leads |
| **⏸ Pause** | Pauses the job after the current lead finishes (won't interrupt mid-search) |
| **▶ Resume** | (appears when paused) Continues from where it stopped |
| **✕ Cancel** | Stops the job entirely, marks remaining leads as cancelled |
| **📊 Open Report** | Opens the master job index in a new browser tab |
| **🗑 Delete** | Permanently removes the job from the dashboard (files on disk stay) |

> **Pause** is clean — it finishes the current lead's screenshots first, then stops. Won't leave half-processed data.

---

### 4.8 Renaming a Job

Click directly on the **job name** (the big title text at the top of the job panel). It turns into an editable field. Type the new name and click anywhere else — it saves automatically.

The name also updates in the sidebar immediately.

---

### 4.9 Deleting a Job

Click **🗑 Delete** in the job panel header. Confirm the prompt.

> **Note**: Deleting a job removes it from the dashboard and stops any active processing. The **report files on disk** (`C:\Users\JUDE\OSINT_Reports\`) are **not deleted** — your data stays safe. You can still browse the HTML files directly.

---

### 4.10 Viewing Results

**Job-level report** (all leads together):
- Click **📊 Open Report** in the job panel
- Or go to: `http://localhost:5050/results/{JOB_ID}`

**Individual lead report**:
- Click **📄 Report** next to a completed lead in the list
- Or open the file directly: `C:\Users\JUDE\OSINT_Reports\{job_folder}\{lead_folder}\report.html`

**What the lead report shows:**
- Stats: number of results, status, location
- One card per result found, showing:
  - Full Name
  - Age
  - City / State
  - All addresses found
  - Clickable FSP profile URL (`🔗 View Profile`)
  - Full-page screenshot thumbnail (click to zoom in a lightbox)

**Screenshots:**
- Saved as `{LeadName}_{Location}_result_1.png`, `result_2.png`, etc.
- Each screenshot is the **actual FSP profile page** rendered via Bright Data (no bot-blocked X)
- Click any screenshot thumbnail → opens fullscreen lightbox
- Press `Escape` to close the lightbox

---

### 4.11 Filtering Results — Delete & Archive

Once a lead completes and you open its report (`📄 Report`), you'll see every result FSP returned.
If a lead returned 8 results but you've tracked down that only result #3 is the exact person you're looking for, you can clean up the rest:

#### 🗃 "Not This Person" (Archive)
Click **`🗃 Not This Person`** on any result card.

- The result **slides into a collapsed section** at the bottom of the report: *"Not This Person — N archived result(s)"*
- The data and screenshot are **kept on disk** — nothing is deleted
- The active results count at the top decreases
- Click the collapsed section to expand and see archived results
- Each archived card has a **↩ Restore** button to bring it back to the active list

**Use this when:** You want to mark results as "not them" while keeping the data just in case.

#### 🗑 Delete Result (Permanent)
Click **`🗑 Delete Result`** on any result card.

- A **confirmation dialog** pops up: *"Delete This Result? This cannot be undone."*
- Click **Delete Permanently** to confirm — the card fades out and disappears
- The **screenshot PNG file is deleted** from disk
- The `data.json` is updated and remaining screenshots are renumbered
- The `report.html` is automatically regenerated

**Use this when:** You're 100% certain a result is wrong and want it gone permanently.

#### Workflow Example
You searched `Jane Doe, TX` and got 6 results:

```
#1 Jane M Doe, 32, Austin TX    ← probably not her
#2 Janelle Doe, 45, Dallas TX   ← definitely not
#3 Jane E Doe, 28, Houston TX   ← THIS IS HER ✓
#4 Jane Doe, 71, Waco TX        ← probably not
#5 Janet Doe, 38, San Antonio   ← different name
#6 Jane Doe, 55, El Paso TX     ← probably not
```

1. Click **🗃 Not This Person** on #1 — moves to archived (recoverable)
2. Click **🗑 Delete Result** on #2 — permanent delete (you're sure)
3. Leave #3 as-is — this is your confirmed match
4. Click **🗑 Delete Result** on #4, #5, #6 — clean up the rest

Result: Report now shows only Jane E Doe, Houston TX as the active result.

> **Note:** These buttons only appear when the report is opened **through the dashboard** (`📄 Report` button or `📊 Open Report`). If you open the HTML file directly from Windows Explorer (double-click), the buttons will show but will call `http://localhost:5050` — so the server must be running for them to work.

---

## 5. CLI — Full Walkthrough

Use the CLI when you don't need the browser dashboard and just want to run and get results.

### 5.1 Single Person Search

```powershell
python C:\Users\JUDE\LeadsOSINT\app.py --name "John Smith" --location TX
```

```powershell
# With full state name
python C:\Users\JUDE\LeadsOSINT\app.py --name "Jane Doe" --location "New York"

# City + state
python C:\Users\JUDE\LeadsOSINT\app.py --name "Bob Wilson" --location "Houston TX"

# No location (broader search)
python C:\Users\JUDE\LeadsOSINT\app.py --name "Michael Johnson"
```

**What happens:**
1. Console shows progress in real-time
2. When done, results folder opens automatically in your browser
3. Output saved to `C:\Users\JUDE\OSINT_Reports\job_YYYYMMDD_HHMMSS_XXXXXXXX\`

**Example console output:**
```
[1/1] John Smith | TX
  Fetching: https://www.fastpeoplesearch.com/name/john-smith_TX/
  → 5 result(s)
  📸 Screenshot 1/5: John Smith
    Fetching profile for screenshot...
    ✅ Screenshot saved
  📸 Screenshot 2/5: John A Smith
    ✅ Screenshot saved
  ...

✅ Job A1B2C3D4 done
Opening results in browser...
```

---

### 5.2 Bulk CSV Search

```powershell
python C:\Users\JUDE\LeadsOSINT\app.py --bulk C:\Users\JUDE\my_leads.csv
```

```powershell
# Full path example
python C:\Users\JUDE\LeadsOSINT\app.py --bulk "C:\Users\JUDE\Documents\leads_batch_1.csv"
```

**Console shows:**
```
Loaded 25 leads from C:\Users\JUDE\my_leads.csv

[1/25] John Smith | TX
  Fetching: https://www.fastpeoplesearch.com/name/john-smith_TX/
  → 8 result(s)
  📸 Screenshot 1/8: John Smith
    ✅ Screenshot saved
  ...

[2/25] Jane Doe | NY
  Fetching: https://www.fastpeoplesearch.com/name/jane-doe_NY/
  → 3 result(s)
  ...

✅ Job complete → C:\Users\JUDE\OSINT_Reports\job_20261001_103045_E8DDFF6B\index.html
```

> The results open in your browser when all leads are done. You can also open the index.html file directly from the path shown.

---

## 6. Input Formatting Rules

### Lead Name Rules
- Must have **at least a first name and last name** (two words minimum)
- Works with: `John Smith`, `Mary Jane Watson`, `Dr. Robert Jones`
- Hyphenated names: `Mary-Jane Smith` ✅
- Middle names are fine: `John Michael Smith` ✅

### Location Rules
The tool accepts all of these for location:

| Input | Interpreted As |
|-------|---------------|
| `TX` | Texas |
| `Texas` | Texas |
| `New York` | New York |
| `NY` | New York |
| `Houston TX` | Texas (city used for context) |
| `Atlanta, Georgia` | Georgia |
| `NYC` | New York |
| `LA` | California |
| `DC` or `Washington DC` | District of Columbia |
| *(empty)* | No state filter — broader search |

### CSV Column Order
```
Column 1: Name (required)
Column 2: Location (optional)
```

---

## 7. Output — What Gets Created

Every job creates this folder structure:

```
C:\Users\JUDE\OSINT_Reports\
└── job_20261001_103045_E8DDFF6B\          ← Job folder (date + ID)
    ├── index.html                          ← Master job report (open this!)
    ├── John_Smith_TX\                      ← Per-lead folder
    │   ├── report.html                     ← Lead report with all results
    │   ├── data.json                       ← Raw data (machine-readable)
    │   ├── John_Smith_TX_result_1.png      ← Screenshot of result #1
    │   ├── John_Smith_TX_result_2.png      ← Screenshot of result #2
    │   └── John_Smith_TX_result_3.png      ← etc.
    ├── Jane_Doe_New_York_NY\
    │   ├── report.html
    │   ├── data.json
    │   ├── Jane_Doe_New_York_NY_result_1.png
    │   └── ...
    └── ...
```

> Jobs registry is saved at `C:\Users\JUDE\OSINT_Reports\jobs_registry.json` — this means **your jobs survive server restarts**. Past jobs always reappear in the sidebar.

---

## 8. Reading Your Results

### Job Index Page (`index.html`)
Shows all leads at a glance:
- ✅ Green left border = found results
- ❌ Dimmed = no results
- Click any lead card → opens that lead's full report

### Lead Report Page (`report.html`)
Each result card shows:

```
┌─────────────────────────────────────────────────────┐
│  #1  John Michael Smith              🔗 View Profile │
├─────────────────────────────────────────────────────┤
│  Full Name:   John Michael Smith                    │
│  Age:         54                                    │
│  City/State:  Houston, TX                           │
│  Address(es): 📍 123 Main St · Houston, TX          │
│               📍 456 Oak Ave · Spring, TX           │
│  Profile URL: https://www.fastpeoplesearch.com/...  │
│                                                     │
│  [Screenshot thumbnail — click to zoom]             │
└─────────────────────────────────────────────────────┘
```

- **🔗 View Profile** — opens the actual FSP page in a new tab
- **Screenshot** — click it to open fullscreen, press Escape to close
- **🗃 Not This Person** — archives the result (recoverable, moves to collapsed section)
- **🗑 Delete Result** — permanently removes the result + screenshot (with confirmation)
- **↩ Restore** — (appears on archived cards) moves result back to active list

---

## 9. Troubleshooting

### "No results found" for a lead
- The name might not exist on FSP, or the location filtered it out too much
- Try removing the location (leave it blank) for a broader search
- Try alternate spellings (`Bob` vs `Robert`)

### Age / City showing "N/A"
- FSP sometimes doesn't show age/city for certain profiles
- The data wasn't present on the page — this is not a tool bug

### Screenshot shows broken/missing image
- Screenshot capture failed but the data (name, age, address, URL) is still correct
- The tool falls back to a data-card screenshot — if even that fails, the image is blank
- The profile URL still works — click 🔗 View Profile to see the page manually

### "Could not decode file" error on CSV upload
- Save your CSV as **UTF-8** encoding from Excel:
  - File → Save As → Tools → Web Options → Encoding → Unicode (UTF-8)
  - Or use Notepad++: Encoding → Convert to UTF-8

### Server won't start (port already in use)
```powershell
# Kill whatever is using port 5050
netstat -ano | findstr :5050
# Note the PID shown, then:
taskkill /PID <pid> /F
# Then start again
python C:\Users\JUDE\LeadsOSINT\app.py
```

### Job disappears after server restart
- Jobs load from disk automatically. If a job is missing, the `jobs_registry.json` may have been deleted.
- The report **files on disk** are always safe regardless.

### Playwright browser error
```powershell
# Re-install Playwright browser
playwright install chromium
```

---

## 10. Tips for Best Results

1. **Always include state** — `John Smith, TX` gets far better results than `John Smith` alone. Without a state, FSP returns results from all 50 states.

2. **Use exact names** — if you know a middle initial or middle name, include it: `John A Smith` narrows results significantly.

3. **Batch sizing** — process 10–20 leads per job for cleaner tracking. You can run multiple jobs simultaneously.

4. **Rate limits** — the tool waits ~2 seconds between leads and ~1.2 seconds between screenshots to respect Bright Data's rate limits and avoid account flags. Do not modify these delays.

5. **Screenshot timing** — each lead with 10 results = ~1–2 minutes (search + 10 profile fetches + 10 screenshots). Plan accordingly for large batches.

6. **Pause is your friend** — if you need to stop temporarily, hit **⏸ Pause** instead of Cancel. The job will finish its current lead cleanly and stop, letting you **▶ Resume** later.

7. **Retry failed leads** — if a lead fails (network timeout, BD error), click **🔄 Retry** to try again without re-running the whole job.

---

## 11. Quick Reference Card

### Web UI Shortcuts
| Action | How |
|--------|-----|
| Open UI | `http://localhost:5050` in browser |
| New job | Click `+ New Job` (top right) |
| Select job | Click job name in left sidebar |
| Rename job | Click job title text → type → click away |
| Start all leads | `▶ Start All` button in job header |
| Pause processing | `⏸ Pause` button |
| Resume | `▶ Resume` button (appears when paused) |
| Cancel everything | `✕ Cancel` button |
| Open full report | `📊 Open Report` button |
| Run one lead | `▶ Start` next to that lead |
| Retry a failed lead | `🔄 Retry` next to that lead |
| Cancel one lead | `✕ Cancel` next to that lead |
| View lead report | `📄 Report` next to completed lead |
| Delete job | `🗑 Delete` button → confirm |
| **Mark result as wrong** | `🗃 Not This Person` in lead report |
| **Restore archived result** | `↩ Restore` in archived section |
| **Permanently delete result** | `🗑 Delete Result` → confirm in lead report |

### CLI Commands
```powershell
# Start web server
python C:\Users\JUDE\LeadsOSINT\app.py

# Search single person
python C:\Users\JUDE\LeadsOSINT\app.py --name "John Smith" --location TX

# Bulk from CSV
python C:\Users\JUDE\LeadsOSINT\app.py --bulk leads.csv

# Help
python C:\Users\JUDE\LeadsOSINT\app.py --help
```

### File Locations
```
App:         C:\Users\JUDE\LeadsOSINT\app.py
Reports:     C:\Users\JUDE\OSINT_Reports\
Job registry C:\Users\JUDE\OSINT_Reports\jobs_registry.json
```

---

*LeadsOSINT v2 · Built with Flask + Playwright + Bright Data Web Unlocker*
