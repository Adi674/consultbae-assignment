"""
ConsultBae — Data Merge & Deduplication Pipeline
Task 1: Ingest 3 CSV sources into one SQLite database.

Matching strategy (in priority order):
  1. Email exact match (case-insensitive)
  2. Phone exact match (normalized digits only)
  3. Fuzzy name match (score >= 85) + same city
  4. No match → new record

Run: python ingest/merge.py
"""

import sqlite3
import csv
import json
import re
import os
import logging
from datetime import datetime
from rapidfuzz import fuzz

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH     = os.path.join(BASE_DIR, "db", "merged.sqlite")
SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")
DATA_DIR    = os.path.join(BASE_DIR, "data")

FUZZY_THRESHOLD = 85   # minimum name similarity score (0-100)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(BASE_DIR, "db", "ingest.log"), mode="w"),
    ]
)
log = logging.getLogger(__name__)


# ── Normalisation helpers ────────────────────────────────────────────────────

def normalise_phone(raw) -> str | None:
    """
    Strip everything except digits.
    Reject:
      - negative numbers (planted bug in S3: -9000000040)
      - scientific notation blobs that Excel mangles (9.19E+11 → garbage)
      - anything shorter than 7 digits after stripping
    """
    if raw is None:
        return None
    raw_str = str(raw).strip()

    # Catch scientific notation from Excel (e.g. "9.19E+11")
    if re.search(r'[eE]\+', raw_str):
        log.warning(f"  ⚠ Scientific notation phone rejected: {raw_str!r}")
        return None

    # Catch negative numbers (planted bug)
    if raw_str.startswith('-'):
        log.warning(f"  ⚠ Negative phone number rejected: {raw_str!r}")
        return None

    digits = re.sub(r'\D', '', raw_str)

    # Indian numbers: strip leading 91 country code if 12 digits
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]

    if len(digits) < 7:
        log.warning(f"  ⚠ Phone too short after normalisation, rejected: {raw_str!r}")
        return None

    return digits


def normalise_email(raw) -> str | None:
    if raw is None:
        return None
    cleaned = str(raw).strip().lower()
    # Basic sanity check
    return cleaned if '@' in cleaned else None


def normalise_name(raw) -> str:
    """Title-case, strip extra whitespace."""
    if not raw:
        return ""
    return " ".join(str(raw).strip().title().split())


def normalise_city(raw) -> str | None:
    if not raw:
        return None
    city_map = {
        "delhi ncr": "Delhi",
        "new delhi": "Delhi",
        "noida": "Noida",
        "gurgaon": "Gurgaon",
        "gurugram": "Gurgaon",
        "pune": "Pune",
        "bengaluru": "Bengaluru",
        "bangalore": "Bengaluru",
    }
    cleaned = str(raw).strip().lower().rstrip()
    return city_map.get(cleaned, str(raw).strip().title())


def normalise_verified(raw) -> int | None:
    if raw is None:
        return None
    val = str(raw).strip().lower()
    if val in ('y', 'yes', '1', 'true'):
        return 1
    if val in ('n', 'no', '0', 'false'):
        return 0
    return None


def normalise_status(raw) -> str | None:
    if not raw:
        return None
    return str(raw).strip().lower()


def normalise_date(raw) -> str | None:
    """Parse multiple date formats → ISO YYYY-MM-DD."""
    if not raw:
        return None
    raw = str(raw).strip()
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d-%b-%y", "%d/%m/%y",              # 07-Jul-26
        "%d-%b-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    log.warning(f"  ⚠ Could not parse date: {raw!r} — stored as-is")
    return raw


def normalise_rate(raw) -> tuple[str, float | None]:
    """
    Returns (raw_string, rate_per_hour_float_or_None).
    Handles: "1415/hr", "15k/month", "440/hr"
    """
    if not raw:
        return (raw, None)
    raw_str = str(raw).strip()
    # per hour
    m = re.match(r'^(\d+(?:\.\d+)?)/hr$', raw_str, re.IGNORECASE)
    if m:
        return (raw_str, float(m.group(1)))
    # k/month → convert to hourly (÷ 160 working hours)
    m = re.match(r'^(\d+(?:\.\d+)?)k/month$', raw_str, re.IGNORECASE)
    if m:
        monthly = float(m.group(1)) * 1000
        return (raw_str, round(monthly / 160, 2))
    return (raw_str, None)


def merge_skills(*skill_strings) -> str:
    """Combine skill strings from multiple sources, deduplicate, sort."""
    seen = set()
    result = []
    for s in skill_strings:
        if not s:
            continue
        for skill in str(s).split(','):
            norm = skill.strip().lower()
            if norm and norm not in seen:
                seen.add(norm)
                result.append(skill.strip().lower())
    result.sort()
    return json.dumps(result)


# ── DB helpers ───────────────────────────────────────────────────────────────

def init_db(conn):
    with open(SCHEMA_PATH, 'r') as f:
        conn.executescript(f.read())
    conn.commit()
    log.info("Database schema initialised.")


def load_all_persons(conn) -> list[dict]:
    """Load current persons table into memory for matching."""
    cur = conn.execute(
        "SELECT id, full_name, email, phone, city FROM persons"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def log_merge(conn, action, source, name, email, phone,
              matched_id, method, score, notes):
    conn.execute(
        """INSERT INTO merge_log
           (action, source, source_name, source_email, source_phone,
            matched_person_id, match_method, match_score, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (action, source, name, email, phone,
         matched_id, method, score, notes)
    )


# ── Matching engine ───────────────────────────────────────────────────────────

def find_match(persons: list[dict], name: str, email: str | None,
               phone: str | None, city: str | None) -> tuple[dict | None, str, float]:
    """
    Returns (matched_person_or_None, method, score).
    Priority: email > phone > fuzzy_name+city
    """
    # 1. Email exact match
    if email:
        for p in persons:
            if p['email'] and p['email'].lower() == email.lower():
                return p, 'email_exact', 100.0

    # 2. Phone exact match
    if phone:
        for p in persons:
            if p['phone'] and p['phone'] == phone:
                return p, 'phone_exact', 100.0

    # 3. Fuzzy name — only run if we have a city to reduce false positives
    #    "Priya Saxena" vs "Priya Singh" should NOT match (names too different)
    if name and city:
        best_score = 0
        best_person = None
        for p in persons:
            score = fuzz.token_sort_ratio(name.lower(), p['full_name'].lower())
            if score >= FUZZY_THRESHOLD:
                # Also check city similarity
                city_match = (
                    p['city'] and
                    fuzz.ratio(city.lower(), p['city'].lower()) >= 80
                )
                if city_match and score > best_score:
                    best_score = score
                    best_person = p
        if best_person:
            return best_person, 'fuzzy_name+city', float(best_score)

    return None, 'no_match', 0.0


# ── Source 1: Naukri Applicants ───────────────────────────────────────────────

def ingest_source1(conn, persons: list[dict]):
    log.info("═══ Ingesting Source 1: Naukri Applicants ═══")
    path = os.path.join(DATA_DIR, "source1_naukri_applicants.csv")

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name  = normalise_name(row.get('Full Name'))
            email = normalise_email(row.get('Email'))
            phone = normalise_phone(row.get('Phone'))
            city  = normalise_city(row.get('City'))
            skills = row.get('Skills', '')
            date   = normalise_date(row.get('Applied Date'))

            try:
                exp = float(row.get('Experience (Years)', '') or 0)
            except ValueError:
                exp = None
            try:
                ctc = int(str(row.get('Current CTC', '') or '').replace(',', '') or 0)
            except ValueError:
                ctc = None

            log.info(f"  Processing: {name} | {email} | {phone}")

            match, method, score = find_match(persons, name, email, phone, city)

            if match:
                # Merge into existing record
                existing_skills = conn.execute(
                    "SELECT skills FROM persons WHERE id=?", (match['id'],)
                ).fetchone()[0]
                merged_skills = merge_skills(existing_skills, skills)

                conn.execute("""
                    UPDATE persons SET
                        email            = COALESCE(email, ?),
                        phone            = COALESCE(phone, ?),
                        experience_years = COALESCE(experience_years, ?),
                        current_ctc      = COALESCE(current_ctc, ?),
                        applied_date     = COALESCE(applied_date, ?),
                        skills           = ?,
                        sources          = json_insert(
                                            CASE WHEN json_valid(sources) THEN sources
                                                 ELSE json_array() END,
                                            '$[#]', 's1'),
                        match_log        = match_log || ' | S1:' || ?,
                        updated_at       = datetime('now')
                    WHERE id = ?
                """, (email, phone, exp, ctc, date,
                      merged_skills, method, match['id']))

                log.info(f"    ✓ MERGED into person_id={match['id']} via {method} (score={score})")
                log_merge(conn, 'merged_into', 's1', name, email, phone,
                          match['id'], method, score, '')
            else:
                # New record
                cur = conn.execute("""
                    INSERT INTO persons
                        (full_name, email, phone, city, experience_years,
                         current_ctc, applied_date, skills, sources, match_log)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (name, email, phone, city, exp, ctc, date,
                      merge_skills(skills),
                      json.dumps(['s1']),
                      f'S1:new_record'))
                new_id = cur.lastrowid
                persons.append({'id': new_id, 'full_name': name,
                                 'email': email, 'phone': phone, 'city': city})
                log.info(f"    + NEW record created: person_id={new_id}")
                log_merge(conn, 'new_record', 's1', name, email, phone,
                          new_id, 'n/a', 0, '')

    conn.commit()
    log.info(f"  Source 1 done. Total persons: {len(persons)}\n")


# ── Source 2: Gig Workers ─────────────────────────────────────────────────────

def ingest_source2(conn, persons: list[dict]):
    log.info("═══ Ingesting Source 2: Gig Workers ═══")
    path = os.path.join(DATA_DIR, "source2_gig_workers.csv")

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email  = normalise_email(row.get('email_id'))
            name   = normalise_name(row.get('worker_name'))
            city   = normalise_city(row.get('location'))
            status = normalise_status(row.get('status'))
            skills = row.get('skill_tags', '')
            rate_raw, rate_hr = normalise_rate(row.get('rate'))

            log.info(f"  Processing: {name} | {email}")

            match, method, score = find_match(persons, name, email, None, city)

            if match:
                existing_skills = conn.execute(
                    "SELECT skills FROM persons WHERE id=?", (match['id'],)
                ).fetchone()[0]
                merged_skills = merge_skills(existing_skills, skills)

                conn.execute("""
                    UPDATE persons SET
                        email         = COALESCE(email, ?),
                        city          = COALESCE(city, ?),
                        rate_raw      = COALESCE(rate_raw, ?),
                        rate_per_hour = COALESCE(rate_per_hour, ?),
                        worker_status = COALESCE(worker_status, ?),
                        skills        = ?,
                        sources       = json_insert(
                                         CASE WHEN json_valid(sources) THEN sources
                                              ELSE json_array() END,
                                         '$[#]', 's2'),
                        match_log     = match_log || ' | S2:' || ?,
                        updated_at    = datetime('now')
                    WHERE id = ?
                """, (email, city, rate_raw, rate_hr, status,
                      merged_skills, method, match['id']))

                log.info(f"    ✓ MERGED into person_id={match['id']} via {method} (score={score})")
                log_merge(conn, 'merged_into', 's2', name, email, None,
                          match['id'], method, score, '')
            else:
                cur = conn.execute("""
                    INSERT INTO persons
                        (full_name, email, city, rate_raw, rate_per_hour,
                         worker_status, skills, sources, match_log)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (name, email, city, rate_raw, rate_hr, status,
                      merge_skills(skills),
                      json.dumps(['s2']),
                      'S2:new_record'))
                new_id = cur.lastrowid
                persons.append({'id': new_id, 'full_name': name,
                                 'email': email, 'phone': None, 'city': city})
                log.info(f"    + NEW record created: person_id={new_id}")
                log_merge(conn, 'new_record', 's2', name, email, None,
                          new_id, 'n/a', 0, '')

    conn.commit()
    log.info(f"  Source 2 done. Total persons: {len(persons)}\n")


# ── Source 3: CBNexus Contacts ────────────────────────────────────────────────

def ingest_source3(conn, persons: list[dict]):
    log.info("═══ Ingesting Source 3: CBNexus Contacts ═══")
    path = os.path.join(DATA_DIR, "source3_cbnexus_contacts.csv")

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name     = normalise_name(row.get('Name'))
            phone    = normalise_phone(row.get('Phone Number'))   # catches negatives + sci notation
            city     = normalise_city(row.get('City'))
            verified = normalise_verified(row.get('Verified'))
            try:
                projects = int(row.get('Projects Completed') or 0)
            except ValueError:
                projects = None

            log.info(f"  Processing: {name} | phone_raw={row.get('Phone Number')!r} → normalised={phone!r}")

            if phone is None:
                # Still try to insert the record — just can't match on phone
                log.warning(f"    ⚠ Phone unusable for {name}, will attempt name+city match only")

            match, method, score = find_match(persons, name, None, phone, city)

            if match:
                conn.execute("""
                    UPDATE persons SET
                        phone              = COALESCE(phone, ?),
                        city               = COALESCE(city, ?),
                        verified           = COALESCE(verified, ?),
                        projects_completed = COALESCE(projects_completed, ?),
                        sources            = json_insert(
                                              CASE WHEN json_valid(sources) THEN sources
                                                   ELSE json_array() END,
                                              '$[#]', 's3'),
                        match_log          = match_log || ' | S3:' || ?,
                        updated_at         = datetime('now')
                    WHERE id = ?
                """, (phone, city, verified, projects, method, match['id']))

                log.info(f"    ✓ MERGED into person_id={match['id']} via {method} (score={score})")
                log_merge(conn, 'merged_into', 's3', name, None, phone,
                          match['id'], method, score, '')
            else:
                cur = conn.execute("""
                    INSERT INTO persons
                        (full_name, phone, city, verified, projects_completed,
                         sources, match_log)
                    VALUES (?,?,?,?,?,?,?)
                """, (name, phone, city, verified, projects,
                      json.dumps(['s3']),
                      f'S3:new_record (phone_rejected={phone is None})'))
                new_id = cur.lastrowid
                persons.append({'id': new_id, 'full_name': name,
                                 'email': None, 'phone': phone, 'city': city})
                log.info(f"    + NEW record created: person_id={new_id}")
                log_merge(conn, 'new_record', 's3', name, None, phone,
                          new_id, 'n/a', 0,
                          'phone_rejected=True' if phone is None else '')

    conn.commit()
    log.info(f"  Source 3 done. Total persons: {len(persons)}\n")


# ── Summary report ────────────────────────────────────────────────────────────

def print_summary(conn):
    log.info("═══ MERGE SUMMARY ═══")

    total = conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
    log.info(f"  Total unique persons: {total}")

    multi_source = conn.execute("""
        SELECT COUNT(*) FROM persons
        WHERE json_array_length(sources) > 1
    """).fetchone()[0]
    log.info(f"  Persons from multiple sources (merged): {multi_source}")

    actions = conn.execute("""
        SELECT action, COUNT(*) as n FROM merge_log GROUP BY action
    """).fetchall()
    for action, n in actions:
        log.info(f"  merge_log action '{action}': {n}")

    log.info("\n  Per-source breakdown:")
    for src in ['s1', 's2', 's3']:
        n = conn.execute("""
            SELECT COUNT(*) FROM persons WHERE sources LIKE ?
        """, (f'%"{src}"%',)).fetchone()[0]
        log.info(f"    {src}: {n} persons")

    log.info("\n  Sample records:")
    rows = conn.execute("""
        SELECT id, full_name, email, phone, city, sources, match_log
        FROM persons ORDER BY id LIMIT 20
    """).fetchall()
    for r in rows:
        log.info(f"    {r}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    log.info("ConsultBae Data Merge Pipeline starting...")

    # Fresh DB each run (idempotent)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        log.info("Removed existing DB for fresh run.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    init_db(conn)

    persons = []  # in-memory index for matching

    ingest_source1(conn, persons)
    ingest_source2(conn, persons)
    ingest_source3(conn, persons)

    print_summary(conn)

    conn.close()
    log.info(f"\nDone. Database at: {DB_PATH}")
    log.info(f"Log at: db/ingest.log")


if __name__ == "__main__":
    main()