"""blueprints/meetings_bp.py — audio processing, meetings CRUD, PDF export."""
import io, json, os, re, tempfile, uuid
from collections import Counter
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from src.auth import login_required, current_user
from src.meetings import (save_meeting, get_all_meetings, get_meeting,
                           toggle_action_item, delete_meeting, get_all_tags,
                           update_meeting, allowed_confidentiality)
from src.pdf_generator import generate_pdf
from src.audit import log as audit_log

meetings_bp = Blueprint('meetings_bp', __name__, url_prefix='/api')

UPLOAD_FOLDER   = 'uploads'
ALLOWED_EXT     = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.webm'}
VOSK_MODEL_PATH = os.path.join('models', 'vosk-model')
STOP_WORDS = set("""a about above after again against all am an and any are as at be
because been before being below between both but by cannot could did do does doing
down during each few for from further get got had has have having he her here hers
him his how i if in into is it its itself let me more most my myself no nor not of
off on once only or other our ours out over own same she should so some such than
that the their theirs them then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your
yours yourself yourselves just also like well really going know think right yeah yes
one two much way thing things gonna actually even still kind sort""".split())

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _cu():   return current_user()
def _ip():   return request.headers.get('X-Forwarded-For', request.remote_addr or '')
def _allowed(fn): _, ext = os.path.splitext(fn.lower()); return ext in ALLOWED_EXT

def _keywords(text, top_n=12):
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    filtered = [w for w in words if w not in STOP_WORDS]
    return [{'word': w, 'count': c} for w, c in Counter(filtered).most_common(top_n)]

def _stats(transcript, segments):
    words = transcript.split()
    dur   = segments[-1].get('end', 0) if segments and 'end' in segments[-1] else 0
    return {'word_count': len(words), 'duration_sec': round(dur, 1),
            'sentence_count': len(re.findall(r'[.!?]+', transcript)) or 1}


# ── Audio processing ─────────────────────────────────────────────────────────

@meetings_bp.route('/meetings/asr_status')
@login_required
def asr_status():
    from src.asr_vosk import VOSK_AVAILABLE
    model_ok = os.path.isdir(VOSK_MODEL_PATH)
    return jsonify({
        'vosk_installed': VOSK_AVAILABLE,
        'model_found':    model_ok,
        'ready':          VOSK_AVAILABLE and model_ok,
    })


@meetings_bp.route('/meetings/process', methods=['POST'])
@login_required
def process():
    from src.summarizer_extractive import summarize_extract
    from src.action_items import extract_action_items, extract_decisions

    cu = _cu()
    tmp_in = wav_path = None

    # Check for manual transcript (text-only mode)
    manual_transcript = (request.form.get('transcript') or '').strip()

    try:
        if manual_transcript:
            # ── Text-only path ─────────────────────────────────────────────
            transcript = manual_transcript
            segments   = []
            stats      = _stats(transcript, segments)
        else:
            # ── Audio path ─────────────────────────────────────────────────
            from src.preprocess import save_wav_mono_16k
            from src.asr_vosk import transcribe_file, VOSK_AVAILABLE

            if not VOSK_AVAILABLE:
                return jsonify({
                    'error': 'asr_unavailable',
                    'message': (
                        'Vosk ASR is not installed. '
                        'Run: pip install vosk  then download a model from '
                        'https://alphacephei.com/vosk/models and place it at models/vosk-model'
                    )
                }), 503

            if 'audio' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400
            f = request.files['audio']
            if not f.filename or not _allowed(f.filename):
                return jsonify({'error': 'Invalid or missing audio file type'}), 400

            _, ext = os.path.splitext(secure_filename(f.filename) or 'upload')
            tmp_in = os.path.join(UPLOAD_FOLDER, f'{uuid.uuid4().hex}{ext}')
            f.save(tmp_in)
            if os.path.getsize(tmp_in) == 0:
                return jsonify({'error': 'Uploaded file is empty'}), 400

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tw:
                wav_path = tw.name
            save_wav_mono_16k(tmp_in, wav_path)
            transcript, segments = transcribe_file(wav_path, VOSK_MODEL_PATH)
            if not transcript or not transcript.strip():
                return jsonify({'error': 'No speech detected in audio'}), 400
            stats = _stats(transcript, segments)
            if tmp_in:
                stats['file_size_mb'] = round(os.path.getsize(tmp_in) / (1024 * 1024), 2)

        # ── NLP pipeline (shared) ───────────────────────────────────────────
        summary, highlights = summarize_extract(transcript, top_k=5)
        keywords     = _keywords(transcript)
        action_items = extract_action_items(transcript)
        decisions    = extract_decisions(transcript)

        # Parse tags
        tags_raw = request.form.get('tags', '')
        tags = []
        for t in re.split(r'[,\s]+', tags_raw):
            t = t.strip().lstrip('#')
            if t:
                tags.append(t)

        conf = request.form.get('visibility') or request.form.get('confidentiality', 'internal')
        if not allowed_confidentiality(cu, conf):
            conf = 'internal'
        conf_pw = request.form.get('conf_password')
        conf_pw_hash = generate_password_hash(conf_pw) if conf == 'confidential' and conf_pw else None

        mid = save_meeting(
            title       = request.form.get('title', 'Untitled Meeting').strip() or 'Untitled Meeting',
            transcript  = transcript,
            summary     = summary,
            keywords    = keywords,
            highlights  = highlights,
            stats       = stats,
            action_items= action_items,
            decisions   = decisions,
            owner_id    = cu['id'],
            owner_name  = cu['username'],
            team        = cu.get('team', ''),
            tags        = tags,
            confidentiality = conf,
            conf_pw_hash    = conf_pw_hash,
        )
        audit_log('process_audio', user_id=cu['id'], username=cu['username'],
                  resource_type='meeting', resource_id=mid, ip_address=_ip())

        dur_s = stats.get('duration_sec', 0)
        return jsonify({
            'meeting_id':   mid,
            'transcript':   transcript,
            'summary':      summary,
            'highlights':   highlights,
            'keywords':     keywords,
            'word_count':   stats['word_count'],
            'sentence_count': stats.get('sentence_count', 0),
            'duration':     f"{int(dur_s//60)}m {int(dur_s%60)}s" if dur_s else '—',
            'duration_sec': dur_s,
            'action_items': action_items,
            'decisions':    decisions,
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': f'Processing failed: {e}'}), 500
    finally:
        for p in [tmp_in, wav_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass



# ── Meetings list / create ────────────────────────────────────────────────────

@meetings_bp.route('/meetings')
@login_required
def list_meetings():
    cu  = _cu()
    tag = request.args.get('tag', '').strip()
    q   = request.args.get('q',   '').strip()
    meetings = get_all_meetings(user=cu, tag_filter=tag or None, q=q or None)
    all_tags = [t['name'] for t in (get_all_tags() or [])]
    return jsonify({'meetings': meetings or [], 'tags': all_tags})


@meetings_bp.route('/meetings/search')
@login_required
def search_meetings():
    cu = _cu()
    q  = request.args.get('q', '').strip()
    if not q:
        return jsonify({'meetings': []})
    meetings = get_all_meetings(user=cu, q=q)
    return jsonify({'meetings': meetings or []})


@meetings_bp.route('/meetings', methods=['POST'])
@login_required
def create_meeting():
    cu   = _cu()
    data = request.get_json(force=True) or {}
    conf = data.get('visibility') or data.get('confidentiality', 'internal')
    if not allowed_confidentiality(cu, conf):
        return jsonify({'error': f'Your role cannot set confidentiality to "{conf}"'}), 403
    conf_pw_hash = (generate_password_hash(data['conf_password'])
                    if conf == 'confidential' and data.get('conf_password') else None)
    tags = data.get('tags', [])
    if isinstance(tags, str):
        # Handle JSON-encoded arrays like '["tag1","tag2"]'
        try:
            parsed = json.loads(tags)
            tags = [str(t).strip() for t in parsed] if isinstance(parsed, list) else [tags.strip()]
        except Exception:
            tags = [t.strip() for t in tags.split(',') if t.strip()]
    mid = save_meeting(
        title=data.get('title') or 'Untitled Meeting',
        transcript=data.get('transcript', ''), summary=data.get('summary', ''),
        keywords=data.get('keywords', []), highlights=data.get('highlights', []),
        stats=data.get('stats', {}), action_items=data.get('action_items', []),
        decisions=data.get('decisions', []),
        owner_id=cu['id'], owner_name=cu['username'], team=cu.get('team', ''),
        tags=tags, confidentiality=conf, conf_pw_hash=conf_pw_hash,
    )
    audit_log('save_meeting', user_id=cu['id'], username=cu['username'],
              resource_type='meeting', resource_id=mid,
              detail=data.get('title', 'Untitled'), ip_address=_ip())
    return jsonify({'id': mid, 'meeting_id': mid, 'status': 'saved'}), 201


@meetings_bp.route('/meetings/<int:mid>')
@login_required
def get_meeting_detail(mid):
    cu      = _cu()
    meeting = get_meeting(mid, user=cu)
    if not meeting:
        return jsonify({'error': 'Not found or access denied'}), 404
    audit_log('view_meeting', user_id=cu['id'], username=cu['username'],
              resource_type='meeting', resource_id=mid, ip_address=_ip())
    return jsonify(meeting)


@meetings_bp.route('/meetings/<int:mid>', methods=['PATCH'])
@login_required
def edit_meeting(mid):
    cu   = _cu()
    data = request.get_json(force=True) or {}
    ok, reason = update_meeting(
        mid, cu, title=data.get('title'), tags=data.get('tags'),
        confidentiality=data.get('confidentiality') or data.get('visibility'),
    )
    if not ok:
        codes = {'not_found': 404, 'forbidden': 403, 'downgrade_denied': 403, 'conf_not_allowed': 403}
        msgs  = {'not_found': 'Meeting not found', 'forbidden': 'Access denied',
                 'downgrade_denied': 'Only admins can downgrade a confidential meeting',
                 'conf_not_allowed': 'Your role cannot set that confidentiality level'}
        return jsonify({'error': msgs.get(reason, 'Error')}), codes.get(reason, 400)
    audit_log('edit_meeting', user_id=cu['id'], username=cu['username'],
              resource_type='meeting', resource_id=mid,
              detail=data.get('title', ''), ip_address=_ip())
    return jsonify({'status': 'updated'})


@meetings_bp.route('/meetings/<int:mid>', methods=['DELETE'])
@login_required
def delete_meeting_route(mid):
    cu      = _cu()
    meeting = get_meeting(mid, user=cu)
    if not meeting:
        return jsonify({'error': 'Not found or access denied'}), 404
    if cu['role'] != 'admin' and meeting.get('owner_id') != cu['id']:
        return jsonify({'error': "Cannot delete another user's meeting"}), 403
    delete_meeting(mid)
    audit_log('delete_meeting', user_id=cu['id'], username=cu['username'],
              resource_type='meeting', resource_id=mid,
              detail=meeting.get('title', ''), ip_address=_ip())
    return jsonify({'status': 'deleted'})


@meetings_bp.route('/meetings/<int:mid>/pdf', methods=['GET', 'POST'])
@login_required
def export_pdf(mid):
    cu      = _cu()
    meeting = get_meeting(mid, user=cu)
    if not meeting:
        return jsonify({'error': 'Not found or access denied'}), 404
    if meeting.get('confidentiality') == 'confidential' and meeting.get('conf_pw_hash'):
        provided = ((request.get_json(force=True) or {}).get('password', '')
                    if request.method == 'POST' else request.args.get('password', ''))
        if not provided or not check_password_hash(meeting['conf_pw_hash'], provided):
            return jsonify({'error': 'Password required for confidential PDF'}), 403
    pdf_bytes = generate_pdf(meeting)
    safe = re.sub(r'\s+', '_', re.sub(r'[^\w\s-]', '', meeting.get('title', 'minutes'))).strip() or 'minutes'
    audit_log('export_pdf', user_id=cu['id'], username=cu['username'],
              resource_type='meeting', resource_id=mid, ip_address=_ip())
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=f'{safe}.pdf')


@meetings_bp.route('/meetings/<int:mid>/tags', methods=['POST'])
@login_required
def add_meeting_tag(mid):
    cu   = _cu()
    data = request.get_json(force=True) or {}
    # Accept both {tag: "x"} and {tags: ["x","y"]}
    new_tags = []
    if data.get('tags'):
        raw = data['tags']
        new_tags = [raw] if isinstance(raw, str) else list(raw)
    elif data.get('tag'):
        new_tags = [data['tag']]
    new_tags = [t.strip().lower() for t in new_tags if t.strip()]
    if not new_tags:
        return jsonify({'error': 'tag required'}), 400
    meeting = get_meeting(mid, user=cu)
    if not meeting:
        return jsonify({'error': 'Not found or access denied'}), 404
    existing = [t.lower() for t in (meeting.get('tags') or [])]
    merged   = existing + [t for t in new_tags if t not in existing]
    update_meeting(mid, cu, tags=merged)
    return jsonify({'status': 'added', 'tags': merged})


@meetings_bp.route('/meetings/action/<int:iid>/toggle', methods=['POST'])
@login_required
def toggle_item(iid):
    cu       = _cu()
    new_done = toggle_action_item(iid, username=cu['username'])
    if new_done is None:
        return jsonify({'error': 'Item not found'}), 404
    audit_log('toggle_action_item', user_id=cu['id'], username=cu['username'],
              resource_type='action_item', resource_id=iid,
              detail='done' if new_done else 'undone', ip_address=_ip())
    return jsonify({'id': iid, 'done': bool(new_done)})


@meetings_bp.route('/user/profile', methods=['POST', 'PATCH'])
@login_required
def update_profile():
    from src.users import update_user
    cu   = _cu()
    data = request.get_json(force=True, silent=True) or {}
    team = (data.get('team') or '').strip()
    try:
        update_user(cu['id'], team=team or cu.get('team', ''),
                    role=cu.get('role', 'employee'),
                    is_scoped_to_dept=cu.get('is_scoped_to_dept', 0))
    except Exception:
        pass
    return jsonify({'status': 'updated'})

