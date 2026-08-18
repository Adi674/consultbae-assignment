# Scaling the Audio App (Task 5 Stretch)

If we are launching the Flask audio app to 5,000 gig workers over a single weekend, the current local-SQLite + local-storage architecture will break under the load. 

Here is what breaks first and how to re-architect it before launch:

## 1. What Breaks First?
1. **Local File System Storage**: 
   - 5,000 audio files (averaging 5MB each) is 25GB of storage. A basic Render/Railway free tier instance has ephemeral file systems (files are lost on restart) or very limited persistent disk space. The disk will fill up, causing `500 Internal Server Error`s on upload.
2. **Synchronous Audio Processing**: 
   - `pydub` loads the entire file into memory to calculate loudness and duration. If 50 workers submit concurrently, Flask (running synchronous workers) will consume gigabytes of RAM, block the event loop, and cause timeouts (`502 Bad Gateway` or `504 Gateway Timeout`) for other users trying to load the page.
3. **Database Locks**:
   - SQLite uses file-level locking for writes. Concurrent inserts from multiple Flask threads/processes will result in `database is locked` errors, failing the submissions.

## 2. Re-Architecting Before Launch

### Storage & Uploads: Direct-to-S3
- **Change**: Stop saving files to `app/static/uploads/`.
- **Implementation**: Implement **Presigned URLs**. The Flask backend generates a short-lived AWS S3 (or Cloudflare R2) upload URL. The browser uploads the audio file *directly* to the bucket. 
- **Benefit**: Zero disk I/O and zero bandwidth bottlenecks on the web server. Cloudflare R2 has zero egress fees.

### Processing Failures: Asynchronous Queues
- **Change**: Stop running `pydub` synchronously in the Flask route.
- **Implementation**: Once the S3 upload finishes, send a message to a queue (e.g., AWS SQS, Redis + Celery, or simply an n8n webhook trigger). A separate worker process pulls the file, extracts the metadata, and updates the database.
- **Benefit**: The web app responds instantly ("Submitted!"). If processing fails (e.g., corrupted file), it can be retried automatically by the queue without failing the user's web request.

### Database: Migrate to PostgreSQL
- **Change**: Swap SQLite for managed PostgreSQL (e.g., Supabase, Neon, AWS RDS).
- **Benefit**: True concurrent writes without locking issues. Supabase/Neon offer generous free tiers that easily handle 5,000 rows.

### Handling Duplicates
- **Change**: Implement idempotency.
- **Implementation**: Hash the audio file (MD5) on the frontend or backend. If the exact same file is submitted twice, ignore it. Alternatively, enforce a "one active submission per phone number" constraint in Postgres using `UNIQUE(phone)` or `UPSERT` logic.

## 3. Estimated Cost (Weekend Burst)
- **Web App Hosting**: Render/Railway standard tier ($5/mo).
- **Storage**: Cloudflare R2 (10GB free, negligible cost for 25GB).
- **Database**: Supabase Free Tier (500MB DB space is plenty for 5,000 rows of metadata).
- **Total**: Under $10 to confidently handle the spike without downtime.
