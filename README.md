# ConsultBae AI Automation Assignment

This repository contains the end-to-end solution for the ConsultBae Take-Home Assignment.

## 🚀 Setup & Execution

### Prerequisites
- Python 3.10+
- `ffmpeg` installed on your system PATH (required by `pydub` to process audio files like `.webm` and extract metadata).
- n8n (Local or Cloud) for the Task 2 automation.

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
This will read the messy CSVs, deduplicate records based on Email -> Phone -> Fuzzy Name + City, and generate `db/merged.sqlite`.

### 3. Start Audio App (Task 3)
```bash
python app/app.py
```
Visit `http://127.0.0.1:5000` to interact with the audio submission app.

### 4. Import n8n Automation (Task 2)
1. Open n8n.
2. Go to Workflows -> Import from File.
3. Select `automation/skill_tagging_flow.json`.
4. This flow expects a CSV payload, parses it, calls the OpenAI node to tag technical skills, and runs a SQLite node to update `merged.sqlite`.

---

## 🐞 Data Issues Report (Task 4)

Here is a comprehensive list of the intentional data problems planted in the 3 CSVs and how they were handled by the ingestion script (`merge.py`):

1. **Scientific Notation Phones (`9.19E+11`)**: 
   - Found in Source 1 and Source 3. Excel often corrupts large numbers. 
   - *Fix*: The `normalise_phone` regex spots `E+` and rejects it outright rather than converting it to a nonsense string, falling back to name/email matching.
2. **Negative Phone Numbers (`-9000000040`)**:
   - Found in Source 3. A planted bug.
   - *Fix*: Caught by the script checking for leading `-`. Rejected outright.
3. **Inconsistent Date Formats**:
   - Found in Source 1 (`24/07/2026`, `07-Jul-26`).
   - *Fix*: `normalise_date` loops through a list of acceptable `strptime` formats and converts everything to ISO `YYYY-MM-DD`.
4. **Name Casing & Trailing Spaces**:
   - Found across all sources (e.g., `RITU SHARMA`, `Noida `).
   - *Fix*: `normalise_name` and `normalise_city` apply `.title()` and `.strip()` to ensure `PUNE`, `pune`, and `Pune ` all match. City mapping also normalizes `New Delhi` vs `Delhi NCR`.
5. **Mixed Rate Formats (`1415/hr` vs `15k/month`)**:
   - Found in Source 2.
   - *Fix*: Regex extraction. `k/month` is converted to hourly by multiplying by 1000 and dividing by a standard 160-hour working month.
6. **False-Positive Fuzzy Names**:
   - e.g., `Priya Saxena` vs `Priya Singh`.
   - *Fix*: Standard `fuzz.ratio` will score similar names high. We require *both* a fuzzy name score >= 85 AND an exact/fuzzy match on the `City` column to prevent merging two different Priyas from different cities.

---

## 🧗 Stuck Log (Required)

These are the 3 places I genuinely got blocked during the build and how I got unstuck.

1. **Audio metadata showing `0.0` for everything after submission**:
   - *Problem*: After submitting an audio recording from the browser, the submissions table showed `0.0` for duration, sample rate, bitrate, and loudness. The Flask terminal showed `RuntimeWarning: Couldn't find ffmpeg or avconv` and then `[WinError 2] The system cannot find the file specified`. The `.webm` file was being saved correctly, but `pydub` silently swallowed the exception and returned zero for everything because `ffmpeg` was not installed as a system binary.
   - *How I fixed it*: I replaced the `pydub`-only implementation with a 4-layer fallback chain. First I tried `tinytag` (a pure-Python library that reads audio metadata directly from file headers — no system dependency needed). Second, for WAV files I used Python's built-in `wave` module. Third I still attempt `pydub` in case ffmpeg is present. Fourth, if all three fail, I calculate an estimated duration from the raw file size and bitrate heuristics so the table always shows meaningful numbers.
   - *What AI suggested that I rejected*: The first suggestion was to just install ffmpeg via Chocolatey (`choco install ffmpeg`). I rejected this because it adds a hard system dependency that would break the setup on any machine without Chocolatey, and the assignment says to keep things simple to deploy. Using tinytag keeps the entire stack in `requirements.txt` with no OS-level installs.

2. **n8n Cloud blocking requests to `127.0.0.1` (SSRF error)**:
   - *Problem*: I was running n8n on their cloud at cloud.n8n.io, and when the HTTP Request node tried to call our Flask API at `http://127.0.0.1:5000`, it returned `The request was blocked because it resolves to a restricted IP address`. The reason is that n8n Cloud has Server-Side Request Forgery (SSRF) protection enabled by default, and `127.0.0.1` refers to n8n's own cloud server — not my laptop.
   - *How I fixed it*: I switched from n8n Cloud to running n8n locally with `npx n8n` and set the environment variable `$env:N8N_SSRF_DEFAULT_POLICY="allow"` before starting it. This allows outbound HTTP calls to localhost, so the workflow could talk to our Flask app running on the same machine.
   - *What AI suggested that I rejected*: Using `ngrok` to expose the local Flask app to the internet so n8n Cloud could reach it. I tried `npx ngrok http 5000` but it threw `The system cannot execute the specified program` because ngrok requires a separately installed Windows binary, not just an npm package. The local n8n approach was cleaner and didn't require any external account setup.

3. **Deduplication false positives — merging `Priya Saxena` with `Priya Singh`**:
   - *Problem*: While building the fuzzy matching logic, I ran a test and noticed `Priya Saxena` from CBNexus was being merged with `Priya Singh` from Naukri. The `fuzz.token_sort_ratio` function scores `Priya Saxena` vs `Priya Singh` at ~74, which is under my 85 threshold — but when I tested other name pairs like `Rahul Malhotra`, scores were occasionally crossing the threshold for unrelated people with common Indian surnames.
   - *How I fixed it*: I added a mandatory secondary city check. Fuzzy name matching alone only flags a potential merge — it only confirms the merge if the cities also match (city similarity >= 80 using `fuzz.ratio`). This means two people named `Arjun Mehta` will only be merged if they are also in the same city. I also logged every match decision including the score and method (`email_exact`, `phone_exact`, `fuzzy_name+city`) into a `merge_log` table in SQLite so every deduplication decision can be audited and reversed if needed.

---

## 📈 Stretch Goal (Task 5)
See [`stretch_scale.md`](stretch_scale.md) for the 1-page writeup on how to scale the audio app to 5,000 gig workers over a weekend.
