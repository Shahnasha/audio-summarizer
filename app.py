import os
import re
import tempfile
import uuid
from collections import Counter
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from src.preprocess import save_wav_mono_16k
from src.asr_vosk import transcribe_file
from src.summarizer_extractive import summarize_extract

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXT = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.webm'}
VOSK_MODEL_PATH = os.path.join('models', 'vosk-model')

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('models', exist_ok=True)

# Verify Vosk model exists
if not os.path.exists(VOSK_MODEL_PATH):
    print("=" * 70)
    print("ERROR: Vosk model not found!")
    print(f"Expected location: {VOSK_MODEL_PATH}")
    print("\nPlease download a model from: https://alphacephei.com/vosk/models")
    print("Recommended: vosk-model-small-en-us-0.15 (40MB)")
    print("Extract it to the 'models' folder and rename to 'vosk-model'")
    print("=" * 70)
    exit(1)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB limit


# ── Stop words for keyword extraction ──────────────────────────────────
STOP_WORDS = set("""
a about above after again against all am an and any are aren't as at be
because been before being below between both but by can't cannot could
couldn't did didn't do does doesn't doing don't down during each few for
from further get got had hadn't has hasn't have haven't having he he'd
he'll he's her here here's hers herself him himself his how how's i i'd
i'll i'm i've if in into is isn't it it's its itself let's me more most
mustn't my myself no nor not of off on once only or other ought our ours
ourselves out over own same shan't she she'd she'll she's should
shouldn't so some such than that that's the their theirs them themselves
then there there's these they they'd they'll they're they've this those
through to too under until up very was wasn't we we'd we'll we're we've
were weren't what what's when when's where where's which while who who's
whom why why's will with won't would wouldn't you you'd you'll you're
you've your yours yourself yourselves just also like well really going
know think right yeah yes one two get got much way thing things going
gonna actually even still kind sort actually gonna know like really well
""".split())


def allowed_file(filename):
    """Check if file extension is allowed"""
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXT


def extract_keywords(text, top_n=12):
    """Extract top keywords from text using simple frequency analysis."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    filtered = [w for w in words if w not in STOP_WORDS]
    counter = Counter(filtered)
    return [{"word": word, "count": count} for word, count in counter.most_common(top_n)]


def compute_stats(transcript, segments):
    """Compute useful stats about the transcript."""
    words = transcript.split()
    word_count = len(words)
    sentence_count = len(re.findall(r'[.!?]+', transcript)) or 1
    char_count = len(transcript)

    # Estimate duration from segments
    duration_sec = 0
    if segments:
        last_seg = segments[-1]
        if 'end' in last_seg:
            duration_sec = last_seg['end']

    # Reading time (~200 wpm)
    reading_time_min = max(1, round(word_count / 200))

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "char_count": char_count,
        "duration_sec": round(duration_sec, 1),
        "reading_time_min": reading_time_min,
    }


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/process', methods=['POST'])
def process():
    """Process uploaded audio and return JSON results."""
    tmp_in = None
    wav_path = None

    try:
        # Validate file upload
        if 'audio' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        f = request.files['audio']
        if f.filename == '':
            return jsonify({"error": "No file selected"}), 400

        if not allowed_file(f.filename):
            return jsonify({
                "error": f"Invalid file type. Allowed: {', '.join(sorted(ALLOWED_EXT))}"
            }), 400

        # Save uploaded file with unique name to prevent concurrent overwrites
        fname = secure_filename(f.filename)
        if not fname:
            # secure_filename can return '' for all-special-char filenames
            fname = 'upload'
        # Prepend UUID to guarantee uniqueness
        _, ext = os.path.splitext(fname)
        unique_fname = f"{uuid.uuid4().hex}{ext}"
        tmp_in = os.path.join(app.config['UPLOAD_FOLDER'], unique_fname)
        f.save(tmp_in)

        # Verify file is not empty
        file_size = os.path.getsize(tmp_in)
        if file_size == 0:
            return jsonify({"error": "Uploaded file is empty"}), 400

        # Convert to 16kHz mono WAV for Vosk
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:
            wav_path = tmp_wav.name

        save_wav_mono_16k(tmp_in, wav_path)

        # Run offline ASR (Vosk)
        transcript, segments = transcribe_file(wav_path, VOSK_MODEL_PATH)

        # Validate transcript
        if not transcript or not transcript.strip():
            return jsonify({"error": "No speech detected in audio file"}), 400

        # Generate extractive summary
        summary, top_sentences = summarize_extract(transcript, top_k=5)

        # Extract keywords
        keywords = extract_keywords(transcript)

        # Compute stats
        stats = compute_stats(transcript, segments)
        stats["file_size_mb"] = round(file_size / (1024 * 1024), 2)

        return jsonify({
            "transcript": transcript,
            "summary": summary,
            "highlights": top_sentences,
            "keywords": keywords,
            "stats": stats,
            "segments": segments[:50],  # Limit segments sent to client
        })

    except ValueError as e:
        return jsonify({"error": f"Audio format error: {str(e)}"}), 400

    except Exception as e:
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500

    finally:
        # Cleanup temporary files
        for path in [tmp_in, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    print(f"Warning: Could not delete {path}: {e}")


@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error"""
    return jsonify({"error": "File too large. Maximum size is 100MB"}), 413


if __name__ == '__main__':
    app.run(debug=True)