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

*(Fill this out before recording your video! Describe 2-3 places you got genuinely stuck and how you fixed them, including what AI told you that you rejected.)*

1. **Getting `pydub` to read `.webm` browser recordings**:
   - *Problem*: ...
   - *How I fixed it*: ...
   - *AI interaction*: ...
2. **Handling the negative phone numbers without crashing**:
   - *Problem*: ...
   - *How I fixed it*: ...
3. **[Your 3rd Stuck Log item here]**:
   - *Problem*: ...

---

## 📈 Stretch Goal (Task 5)
See [`stretch_scale.md`](stretch_scale.md) for the 1-page writeup on how to scale the audio app to 5,000 gig workers over a weekend.
