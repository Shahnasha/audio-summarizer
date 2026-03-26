"""blueprints/workflows_bp.py — dashboard, audit, standup, weekly, projects, escalations."""
import io, datetime as dt
from flask import Blueprint, request, jsonify, send_file
from src.auth import login_required, require_role, current_user
from src.workflows import (get_dashboard_stats, get_weekly_report,
                            get_standup, get_projects, get_escalations)
from src.audit import get_log

workflows_bp = Blueprint('workflows_bp', __name__, url_prefix='/api/workflows')
def _cu(): return current_user()
def _ip(): return request.headers.get('X-Forwarded-For', request.remote_addr or '')


@workflows_bp.route('/dashboard')
@login_required
def dashboard():
    cu   = _cu()
    raw  = get_dashboard_stats(cu) or {}

    # Normalise to shape frontend expects
    action_total = raw.get('action_total', 0)
    action_done  = raw.get('action_done',  0)
    completion   = round(action_done / action_total * 100) if action_total else 0
    kpis = {
        'total_meetings':  raw.get('total_meetings',  0),
        'total_hours':     raw.get('total_hours',     0),
        'total_words':     raw.get('total_words',     0),
        'completion_rate': completion,
        'meetings_week':   raw.get('meetings_week',   0),
        'open_actions':    raw.get('open_actions',    action_total - action_done),
        'overdue_actions': raw.get('overdue_actions', 0),
    }

    # weekly_counts: list of {label, count} — raw data uses {day, cnt}
    weekly_counts = raw.get('weekly_counts') or raw.get('daily') or []
    if weekly_counts and isinstance(weekly_counts[0], dict):
        date_key  = next((k for k in ('date', 'day', 'label') if k in weekly_counts[0]), None)
        count_key = next((k for k in ('count', 'cnt') if k in weekly_counts[0]), None)
        if date_key and count_key:
            weekly_counts = [{'label': r[date_key], 'count': r.get(count_key, 0)} for r in weekly_counts]

    # dept_breakdown: list of {name, count}
    dept_breakdown = raw.get('dept_breakdown') or []

    # recent_activity from audit
    recent = raw.get('recent_audit') or raw.get('recent_activity') or []
    activity = []
    for e in recent[:15]:
        activity.append({
            'action': e.get('action', ''),
            'user':   e.get('username', ''),
            'ts':     e.get('created_at', e.get('ts', '')),
        })

    # top keywords
    top_keywords = raw.get('top_keywords', [])
    # confidentiality breakdown
    conf_raw = raw.get('confidentiality', [])
    conf_breakdown = [{'name': r.get('confidentiality','internal'), 'count': r.get('cnt',0)} for r in conf_raw]
    # assignees
    assignees = [{'assignee': r.get('assignee',''), 'total': r.get('total',0), 'done': r.get('done',0)}
                 for r in raw.get('assignees', [])]

    return jsonify({
        'kpis':           kpis,
        'weekly_counts':  weekly_counts,
        'dept_breakdown': dept_breakdown,
        'recent_activity': activity,
        'top_keywords':   top_keywords,
        'conf_breakdown': conf_breakdown,
        'assignees':      assignees,
    })


@workflows_bp.route('/audit')
@login_required
def audit_log_route():
    cu = _cu()
    if cu['role'] == 'admin':
        team_filter = request.args.get('team', '').strip()
        if cu.get('is_scoped_to_dept'):
            logs = get_log(200, team=cu.get('team', ''))
        else:
            logs = get_log(300, team=team_filter) if team_filter else get_log(300)
    elif cu['role'] == 'manager':
        logs = get_log(200, team=cu.get('team', ''))
    else:
        logs = get_log(100, user_id=cu['id'])

    # Normalise
    entries = []
    for e in (logs or []):
        entries.append({
            'action':   e.get('action', ''),
            'username': e.get('username', ''),
            'ts':       e.get('created_at', e.get('ts', '')),
            'target_desc': e.get('detail', '') or f"{e.get('resource_type','')} #{e.get('resource_id','')}",
        })
    return jsonify({'log': entries})


@workflows_bp.route('/standup')
@login_required
def workflow_standup():
    cu  = _cu()
    raw = get_standup(cu) or {}

    # Normalise: today=open actions, yesterday=done actions, blockers=overdue
    today     = raw.get('incomplete', raw.get('today',     []))
    yesterday = raw.get('done',       raw.get('yesterday', []))
    blockers  = raw.get('overdue',    raw.get('blockers',  []))
    this_week = raw.get('this_week',  [])

    return jsonify({'today': today, 'yesterday': yesterday, 'blockers': blockers, 'this_week': this_week})


@workflows_bp.route('/weekly')
@require_role('admin', 'manager')
def workflow_weekly():
    cu  = _cu()
    raw = get_weekly_report(cu) or {}

    this_ai  = raw.get('this_ai', {})
    done_n   = this_ai.get('done', 0)
    total_n  = this_ai.get('total', 0)
    rate     = round(done_n / total_n * 100) if total_n else 0

    # Build open action items list
    from src.kanban import get_kanban_board
    board      = get_kanban_board(cu)
    open_items = board.get('todo', []) + board.get('inprogress', [])

    # Return themes as word list so frontend renders them as tags
    kw = raw.get('top_keywords') or []
    themes = [k['word'] for k in kw[:8]] if kw else []

    return jsonify({
        'meetings_count':       raw.get('this_count', 0),
        'last_meetings_count':  raw.get('last_count', 0),
        'action_items_count':   total_n,
        'last_action_count':    raw.get('last_ai', {}).get('total', 0),
        'completed_count':      done_n,
        'last_completed_count': raw.get('last_ai', {}).get('done', 0),
        'completion_rate':      rate,
        'themes':               themes,
        'open_actions':         open_items,
        'week_start':           raw.get('week_start', ''),
        'this_meetings':        raw.get('this_meetings', []),
        'teams':                [dict(t) for t in raw.get('teams', [])],
    })


@workflows_bp.route('/projects')
@login_required
def workflow_projects():
    cu   = _cu()
    raw  = get_projects(cu)
    # raw can be a list or dict
    if isinstance(raw, list):
        projects = raw
    else:
        projects = raw.get('projects', [])

    normalized = []
    for p in projects:
        name = p.get('name', p.get('tag', ''))
        if not name:
            continue
        ai    = p.get('ai', {})
        total = ai.get('total', p.get('action_count', 0))
        done  = ai.get('done',  0)
        rate  = round(done / total * 100) if total else p.get('completion_rate', p.get('done_pct', 0))
        normalized.append({
            'name':            name,
            'action_count':    total,
            'meeting_count':   p.get('meeting_count', p.get('count', 0)),
            'completion_rate': int(rate),
        })
    return jsonify({'projects': normalized})


@workflows_bp.route('/projects/<path:name>')
@login_required
def workflow_project_detail(name):
    cu      = _cu()
    raw     = get_projects(cu)
    projects = raw if isinstance(raw, list) else (raw.get('projects') or [])

    project = next(
        (p for p in projects if (p.get('name') or p.get('tag', '')).lower() == name.lower()),
        None
    )
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    # Return actions for this project (items tagged with this keyword)
    from src.kanban import get_kanban_board
    board    = get_kanban_board(cu)
    all_items = board.get('todo', []) + board.get('inprogress', []) + board.get('done', [])
    # Filter items whose task or meeting title contains the project name
    name_lower = name.lower()
    matching = [
        i for i in all_items
        if name_lower in (i.get('task') or '').lower()
        or name_lower in (i.get('meeting_title') or '').lower()
    ]
    return jsonify({'name': name, 'actions': matching, **project})


@workflows_bp.route('/escalations')
@require_role('admin', 'manager')
def workflow_escalations():
    cu  = _cu()
    raw = get_escalations(cu) or {}

    by_assignee = raw.get('by_assignee', [])
    normalized  = []
    for person in by_assignee:
        normalized.append({
            'assignee': person.get('assignee', ''),
            'items': [{
                'task':         item.get('task', ''),
                'days_overdue': item.get('days_overdue', 0),
                'deadline':     item.get('deadline', ''),
            } for item in (person.get('items') or [])],
        })
    return jsonify({'escalations': normalized})


@workflows_bp.route('/weekly/pdf')
@require_role('admin', 'manager')
def workflow_weekly_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)

    cu   = _cu()
    data = get_weekly_report(cu)
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=20*mm, rightMargin=20*mm,
                              topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    DARK  = colors.HexColor('#040412')
    BLUE  = colors.HexColor('#4FACFE')
    GREY  = colors.HexColor('#9090C0')
    RED   = colors.HexColor('#F472B6')
    h1    = ParagraphStyle('h1', fontSize=24, fontName='Helvetica-Bold', textColor=DARK, spaceAfter=4)
    h2    = ParagraphStyle('h2', fontSize=14, fontName='Helvetica-Bold', textColor=DARK, spaceBefore=14, spaceAfter=4)
    sub   = ParagraphStyle('sub', fontSize=9, fontName='Helvetica', textColor=GREY, spaceAfter=12)
    bod   = ParagraphStyle('bod', fontSize=10, fontName='Helvetica', textColor=DARK, spaceAfter=4, leading=15)
    cod   = ParagraphStyle('cod', fontSize=8, fontName='Courier', textColor=GREY)

    this_ai = data.get('this_ai', {})
    story = [
        Paragraph('VOX — Weekly Review Report', h1),
        Paragraph(f"Week of {data.get('week_start','—')} · {cu['username']} · {dt.date.today()}", sub),
        HRFlowable(width='100%', thickness=1, color=BLUE, spaceAfter=14),
    ]
    kpi = Table(
        [['Meetings', 'Last Week', 'Hours', 'Tasks Done', 'Overdue'],
         [str(data.get('this_count',0)), str(data.get('last_count',0)),
          str(data.get('this_hours',0)),
          f"{this_ai.get('done',0)}/{this_ai.get('total',0)}",
          str(len(data.get('overdue',[])))]], colWidths=[34*mm]*5)
    kpi.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE),('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,0),9),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME',(0,1),(-1,1),'Helvetica-Bold'),('FONTSIZE',(0,1),(-1,1),18),
        ('TEXTCOLOR',(0,1),(-1,1),DARK),
        ('BOX',(0,0),(-1,-1),1,colors.HexColor('#E0E0F0')),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
    ]))
    story += [kpi, Spacer(1,14)]

    story += [
        Spacer(1,20), HRFlowable(width='100%',thickness=0.5,color=GREY),
        Paragraph(f'VOX AI Meeting Intelligence · {dt.datetime.now().strftime("%Y-%m-%d %H:%M")}', cod),
    ]
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f"vox_weekly_{data.get('week_start','report')}.pdf")
