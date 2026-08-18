import os
import sqlite3
import random
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from datetime import datetime
from pydub import AudioSegment

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db", "merged.sqlite")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")

app = Flask(__name__)
app.secret_key = "super_secret_consultbae"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def extract_audio_properties(file_path):
    """Extract audio properties using pydub. Fallback gracefully if ffmpeg is missing."""
    try:
        audio = AudioSegment.from_file(file_path)
        duration_sec = round(len(audio) / 1000.0, 2)
        sample_rate = audio.frame_rate / 1000.0 # in kHz
        
        # Calculate loudness (dBFS)
        loudness = round(audio.dBFS, 2)
        
        # Approximate bitrate if available, else derive it
        bitrate = int((os.path.getsize(file_path) * 8) / (len(audio) / 1000.0) / 1000) if len(audio) > 0 else 0
        
        # Bonus: rough noise/quality estimate
        # A very simplistic heuristic: if it's too quiet (<-40 dBFS) or too loud (> -5 dBFS), quality is lower.
        # Also could measure SNR if we had a noise floor segment, but we'll use a basic metric.
        if loudness < -45:
            quality = "Poor (Too quiet)"
        elif loudness > -5:
            quality = "Poor (Clipping/Loud)"
        else:
            quality = "Good"

        return {
            "duration": duration_sec,
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "loudness": loudness,
            "quality": quality
        }
    except Exception as e:
        print(f"Error processing audio: {e}")
        return {
            "duration": 0.0,
            "sample_rate": 0,
            "bitrate": 0,
            "loudness": 0.0,
            "quality": f"Unknown (Error: {str(e)[:20]})"
        }

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        audio_file = request.files.get('audio')
        
        if not name or not phone or not audio_file:
            flash("All fields are required.")
            return redirect(url_for('index'))
            
        # Try to find person in DB
        conn = get_db_connection()
        person = conn.execute("SELECT id FROM persons WHERE phone = ?", (phone,)).fetchone()
        
        if person:
            person_id = person['id']
        else:
            # Create a new person if not found
            cur = conn.execute("INSERT INTO persons (full_name, phone, sources) VALUES (?, ?, '[\"app\"]')", (name, phone))
            person_id = cur.lastrowid
            conn.commit()
            
        filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{audio_file.filename or 'recorded.webm'}")
        if not filename.endswith(('.webm', '.mp3', '.wav', '.ogg', '.m4a')):
            filename += '.webm' # default for mediarecorder
            
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(file_path)
        
        # Extract properties
        props = extract_audio_properties(file_path)
        
        relative_path = f"uploads/{filename}"
        
        conn.execute("""
            INSERT INTO audio_submissions (person_id, name, phone, file_path, duration, sample_rate, bitrate, loudness, noise_quality_estimate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (person_id, name, phone, relative_path, props['duration'], props['sample_rate'], props['bitrate'], props['loudness'], props['quality']))
        conn.commit()
        conn.close()
        
        flash("Audio submitted successfully!")
        return redirect(url_for('submissions'))
        
    return render_template('index.html')

@app.route('/submissions')
def submissions():
    conn = get_db_connection()
    subs = conn.execute("SELECT * FROM audio_submissions ORDER BY submitted_at DESC").fetchall()
    conn.close()
    return render_template('submissions.html', submissions=subs)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
