CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    city TEXT,
    experience_years REAL,
    current_ctc INTEGER,
    applied_date TEXT,
    skills TEXT,
    sources TEXT,
    match_log TEXT,
    rate_raw TEXT,
    rate_per_hour REAL,
    worker_status TEXT,
    verified INTEGER,
    projects_completed INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS merge_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    source TEXT NOT NULL,
    source_name TEXT,
    source_email TEXT,
    source_phone TEXT,
    matched_person_id INTEGER,
    match_method TEXT,
    match_score REAL,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audio_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration REAL,
    sample_rate INTEGER,
    bitrate INTEGER,
    loudness REAL,
    noise_quality_estimate TEXT,
    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(person_id) REFERENCES persons(id)
);
