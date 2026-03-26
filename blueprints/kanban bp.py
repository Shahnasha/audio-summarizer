"""blueprints/kanban_bp.py"""
from flask import Blueprint, request, jsonify
from src.auth import login_required, current_user
from src.kanban import (get_kanban_board, get_board_stats, get_single_item,
                         move_item, set_priority, update_details)
from src.audit import log as audit_log
from src.db import get_conn

kanban_bp = Blueprint('kanban_bp', __name__, url_prefix='/api')
def _cu(): return current_user()
def _ip(): return request.headers.get('X-Forwarded-For', request.remote_addr or '')


@kanban_bp.route('/kanban/board')
@login_required
def kanban_board():
    cu    = _cu()
    board = get_kanban_board(cu)
    stats = get_board_stats(cu)
    return jsonify({
        'todo':       board.get('todo', []),
        'inprogress': board.get('inprogress', []),
        'done':       board.get('done', []),
        'stats':      stats,
        'overdue':    stats.get('overdue', 0),
    })


@kanban_bp.route('/kanban/import/<int:mid>', methods=['POST'])
@login_required
def kanban_import(mid):
    """Import action items from a meeting into the kanban board."""
    cu = _cu()
    from src.meetings import get_meeting
    meeting = get_meeting(mid, user=cu)
    if not meeting:
        return jsonify({'error': 'Meeting not found or access denied'}), 404
    imported = 0
    with get_conn() as conn:
        items = conn.execute(
            'SELECT * FROM action_items WHERE meeting_id=?', (mid,)
        ).fetchall()
        for item in items:
            if not item['kanban_status']:
                status = 'done' if item['done'] else 'todo'
                conn.execute(
                    "UPDATE action_items SET kanban_status=? WHERE id=?",
                    (status, item['id'])
                )
                imported += 1
    audit_log('kanban_import', user_id=cu['id'], username=cu['username'],
              resource_type='meeting', resource_id=mid,
              detail=f'{imported} items', ip_address=_ip())
    return jsonify({'ok': True, 'imported': imported})


@kanban_bp.route('/kanban/card/<int:iid>/move', methods=['POST'])
@login_required
def kanban_move(iid):
    cu   = _cu()
    data = request.get_json(force=True) or {}
    status = data.get('status', '')
    if status not in {'todo', 'inprogress', 'done'}:
        return jsonify({'error': f'Invalid status: {status}'}), 400
    if not move_item(iid, status, cu):
        return jsonify({'error': 'Access denied or item not found'}), 403
    audit_log('kanban_move', user_id=cu['id'], username=cu['username'],
              resource_type='action_item', resource_id=iid,
              detail=f'→ {status}', ip_address=_ip())
    return jsonify({'ok': True, 'status': status})


@kanban_bp.route('/kanban/card/<int:iid>', methods=['GET'])
@login_required
def kanban_card_get(iid):
    item = get_single_item(iid, _cu())
    if not item:
        return jsonify({'error': 'Not found or access denied'}), 404
    return jsonify(item)


@kanban_bp.route('/kanban/card/<int:iid>', methods=['PATCH'])
@login_required
def kanban_card_patch(iid):
    cu   = _cu()
    data = request.get_json(force=True) or {}
    # Handle priority separately
    if 'priority' in data:
        set_priority(iid, data['priority'], cu)
    update_details(iid, cu,
                   assignee=data.get('assignee'),
                   deadline=data.get('deadline'),
                   notes=data.get('notes'))
    return jsonify({'ok': True})

