# ConsultBae AI Automation Assignment

This repository contains the end-to-end solution for the ConsultBae Take-Home Assignment covering all 5 tasks: data merge, no-code automation, audio web app, data issues report, and a scaling writeup.

---

## 📁 Repo Structure

```
consultbae-assignment/
├── data/               # raw CSVs
├── db/                 # schema.sql + merged.sqlite + ingest.log
├── ingest/             # merge + dedup script
├── automation/         # n8n flow JSON
├── app/                # Flask audio app
│   ├── app.py
│   ├── templates/
│   └── static/
├── stretch_scale.md    # Task 5 — scale writeup
├── README.md
└── requirements.txt
```

---

## 🚀 Setup & Execution

### Prerequisites
- Python 3.12+ (no system ffmpeg needed — we use `tinytag` as a pure-Python fallback)
- Node.js + npx (for running n8n locally)
- n8n Cloud account OR local n8n via `npx n8n` (for Task 2)
- ngrok (for exposing local Flask to n8n Cloud — see Task 2 section)

### 1. Environment Setup
```bash
python -m venv venv

# On Windows:
.\venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Run Data Merge (Task 1)
```bash
python ingest/merge.py
```
This reads the 3 messy CSVs, deduplicates records using Email → Phone → Fuzzy Name + City matching, and generates `db/merged.sqlite`. Every merge decision is logged to `db/ingest.log` and the `merge_log` table.

### 3. Start Audio App (Task 3)
```bash
python app/app.py
```
Visit `http://127.0.0.1:5000` to record or upload audio.
Visit `http://127.0.0.1:5000/submissions` to see the full table with extracted metadata.

### 4. Import n8n Automation (Task 2)

We built a **Duplicate Detection Alert Flow** (no API keys required):

**Using n8n Cloud + ngrok (recommended):**
1. Start the Flask app (`python app/app.py`).
2. In a separate terminal, expose it with ngrok:
   ```bash
   npx localtunnel --port 5000
   # or: ngrok http 5000 (if ngrok desktop is installed)
   ```
3. Copy the public URL (e.g. `https://abc.loca.lt`).
4. Log into [cloud.n8n.io](https://cloud.n8n.io), go to **Workflows → Import from File**.
5. Import `automation/duplicate_alert_flow.json`.
6. Double-click the **Flask App (Check DB)** node and replace `http://127.0.0.1:5000` with your ngrok/localtunnel URL.
7. Click **Execute Workflow** — all 4 nodes will turn green.

**Using n8n locally (alternative, no ngrok needed):**
```powershell
$env:N8N_SSRF_DEFAULT_POLICY="allow"
npx n8n
```
Open `http://localhost:5678`, import the flow, and run it directly against `http://127.0.0.1:5000`.

---

## 🐞 Data Issues Report (Task 4)

All intentional data problems planted in the 3 CSVs and how the ingestion script handles them:

1. **Scientific Notation Phones (`9.19E+11`)**:
   - Found in Source 1 and Source 3. Excel corrupts large phone numbers into scientific notation.
   - *Fix*: `normalise_phone` detects `E+` via regex and rejects the value, falling back to name/email matching.

2. **Negative Phone Numbers (`-9000000040`)**:
   - Found in Source 3. A deliberately planted bug.
   - *Fix*: Any raw phone string starting with `-` is rejected outright before digit stripping.

3. **Inconsistent Date Formats**:
   - Found in Source 1 (`24/07/2026` vs `07-Jul-26`).
   - *Fix*: `normalise_date` tries multiple `strptime` format strings in sequence and converts everything to ISO `YYYY-MM-DD`.

4. **Name Casing & Trailing Spaces**:
   - Found across all sources (`RITU SHARMA`, `Noida ` with trailing space).
   - *Fix*: `.title()` + `.strip()` on all name and city fields. A city alias map also normalizes `New Delhi` → `Delhi`, `Delhi NCR` → `Delhi`, `Gurugram` → `Gurgaon`.

5. **Mixed Rate Formats (`1415/hr` vs `15k/month`)**:
   - Found in Source 2. Not directly comparable without normalisation.
   - *Fix*: Regex parses both formats. `k/month` is converted to hourly (×1000 ÷ 160 working hours/month) and stored in a separate `rate_per_hour` column alongside the raw string.

6. **False-Positive Fuzzy Name Matches**:
   - e.g. `Priya Saxena` (Source 3) vs `Priya Singh` (Source 1).
   - *Fix*: A fuzzy name match (RapidFuzz token_sort_ratio ≥ 85) alone is insufficient. The city must also fuzzy-match (≥ 80) before merging. This prevents merging distinct people who share a common first name.

7. **Mixed Status Casing (`Active`, `ACTIVE`, `active`)**:
   - Found in Source 2.
   - *Fix*: `normalise_status` lowercases all values before storing.

8. **Mixed Verified Field (`Y`, `yes`, `No`)**:
   - Found in Source 3.
   - *Fix*: `normalise_verified` maps all truthy strings to `1` and falsy strings to `0` (SQLite integer boolean).

---

## 🧗 Stuck Log

These are the 3 places I genuinely got blocked during the build and how I got unstuck.

1. **Audio metadata showing `0.0` for everything after submission**:
   - *Problem*: After submitting a browser recording, the submissions table showed `0.0` for all metadata fields. Flask terminal showed `RuntimeWarning: Couldn't find ffmpeg or avconv` and `[WinError 2] The system cannot find the file specified`. The `.webm` file was saved correctly but `pydub` silently caught the exception and returned zeros because `ffmpeg` was not installed as a system binary on Windows.
   - *How I fixed it*: Replaced the `pydub`-only implementation with a 4-layer fallback chain. (1) `tinytag` — pure-Python audio header parser, no system dependency needed. (2) Python's built-in `wave` module for `.wav` files. (3) `pydub` if ffmpeg is present. (4) File-size-based heuristics as a last resort so the table never shows blank metadata.
   - *What AI suggested that I rejected*: Install ffmpeg via Chocolatey (`choco install ffmpeg`). I rejected this because it adds an OS-level dependency that breaks setup on machines without Chocolatey. Keeping everything in `requirements.txt` is the right call for a portable project.

2. **n8n Cloud blocking requests to `127.0.0.1` (SSRF protection)**:
   - *Problem*: Using n8n Cloud at cloud.n8n.io, the HTTP Request node to `http://127.0.0.1:5000/api/check_duplicate` failed with `The request was blocked because it resolves to a restricted IP address`. n8n Cloud has SSRF protection that blocks loopback addresses — `127.0.0.1` on the cloud means n8n's own server, not my laptop.
   - *How I fixed it*: Used `npx localtunnel --port 5000` to create a public tunnel URL and pointed the n8n HTTP node at that URL instead of `127.0.0.1`. This lets n8n Cloud reach our local Flask API over the public internet. Also kept the local n8n option (`$env:N8N_SSRF_DEFAULT_POLICY="allow"`) documented as an alternative.
   - *What AI suggested that I rejected*: Switch entirely to local n8n and bypass the cloud. I wanted to keep using n8n Cloud because that's closer to a real production setup, so I used localtunnel instead of abandoning the cloud approach.

3. **Deduplication false positives — merging `Priya Saxena` with `Priya Singh`**:
   - *Problem*: During testing, `Priya Saxena` from CBNexus was being flagged as a potential merge with `Priya Singh` from Naukri. They share a first name and general region but are clearly different people. Fuzzy name matching alone was too aggressive with common Indian name patterns.
   - *How I fixed it*: Added a mandatory secondary city check. A name match only confirms the merge if city similarity is also ≥ 80. Additionally, every match decision is logged to the `merge_log` table with the method and score, so any false merge can be identified and reversed without re-running the entire pipeline.

---

## 📈 Stretch Goal (Task 5)

See [`stretch_scale.md`](stretch_scale.md) for the 1-page writeup covering:
- What breaks first at 5,000 gig workers (local storage, synchronous pydub, SQLite write locks)
- Fix: Direct-to-S3 presigned uploads, async queue (Celery/SQS), PostgreSQL swap
- Cost estimate: under $10 for a weekend burst on Cloudflare R2 + Supabase free tier
