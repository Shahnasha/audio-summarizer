"""blueprints/admin_bp.py — user management, invite codes."""
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from src.auth import require_role, current_user
from src.users import (get_all_users, get_pending_users, create_user, update_user,
                        delete_user, set_status, get_user_by_id)
from src.invites import (create_invite_code, get_all_invite_codes,
                          revoke_invite_code, delete_invite_code)
from src.audit import log as audit_log

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/api/admin')
def _cu(): return current_user()
def _ip(): return request.headers.get('X-Forwarded-For', request.remote_addr or '')


def _guard_super(target_id, acting_user):
    target = get_user_by_id(target_id)
    if not target:
        return None, None
    if target.get('role') == 'admin' and acting_user.get('is_scoped_to_dept'):
        return target, 'Only a full admin can modify another admin account'
    return target, None


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@require_role('admin')
def list_users():
    return jsonify({'users': get_all_users() or []})


@admin_bp.route('/users/pending')
@require_role('admin')
def pending_users():
    return jsonify({'users': get_pending_users() or []})


@admin_bp.route('/users/<int:uid>', methods=['GET'])
@require_role('admin')
def get_user(uid):
    user = get_user_by_id(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(dict(user))


@admin_bp.route('/users/<int:uid>/approve', methods=['POST'])
@require_role('admin')
def approve_user(uid):
    cu = _cu()
    set_status(uid, 'active')
    audit_log('approve_user', user_id=cu['id'], username=cu['username'],
              resource_type='user', resource_id=uid, ip_address=_ip())
    return jsonify({'status': 'approved'})


@admin_bp.route('/users/<int:uid>/reject', methods=['POST'])
@require_role('admin')
def reject_user(uid):
    cu = _cu()
    set_status(uid, 'rejected')
    audit_log('reject_user', user_id=cu['id'], username=cu['username'],
              resource_type='user', resource_id=uid, ip_address=_ip())
    return jsonify({'status': 'rejected'})


@admin_bp.route('/users', methods=['POST'])
@require_role('admin')
def create_user_route():
    cu   = _cu()
    data = request.get_json(force=True, silent=True) or {}
    team = cu.get('team', '') if cu.get('is_scoped_to_dept') else data.get('team', '')
    try:
        uid = create_user(
            username=data.get('username', ''),
            email=data.get('email', ''),
            password_hash=generate_password_hash(data.get('password', 'changeme')),
            role=data.get('role', 'employee'), team=team, status='active',
            is_scoped_to_dept=int(bool(data.get('is_scoped_to_dept', False))),
        )
        audit_log('create_user', user_id=cu['id'], username=cu['username'],
                  resource_type='user', resource_id=uid,
                  detail=data.get('username', ''), ip_address=_ip())
        return jsonify({'id': uid, 'status': 'created'}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@admin_bp.route('/users/<int:uid>', methods=['PATCH', 'PUT'])
@require_role('admin')
def update_user_route(uid):
    cu = _cu()
    target, err = _guard_super(uid, cu)
    if err:
        return jsonify({'error': err}), 403
    data     = request.get_json(force=True) or {}
    new_role = data.get('role', 'employee')
    if cu.get('is_scoped_to_dept') and new_role == 'admin':
        return jsonify({'error': 'Scoped admin cannot promote users to admin'}), 403
    try:
        update_user(
            uid, role=new_role, team=data.get('team', ''),
            email=data.get('email') or None,
            username=data.get('username') or None,
            is_scoped_to_dept=int(bool(data.get('is_scoped_to_dept', False))),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    # Handle status update too
    if 'status' in data:
        set_status(uid, data['status'])
    audit_log('update_user', user_id=cu['id'], username=cu['username'],
              resource_type='user', resource_id=uid,
              detail=f"role={new_role}", ip_address=_ip())
    return jsonify({'status': 'updated'})


@admin_bp.route('/users/<int:uid>', methods=['DELETE'])
@require_role('admin')
def delete_user_route(uid):
    cu = _cu()
    if uid == cu['id']:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    _, err = _guard_super(uid, cu)
    if err:
        return jsonify({'error': err}), 403
    delete_user(uid)
    audit_log('delete_user', user_id=cu['id'], username=cu['username'],
              resource_type='user', resource_id=uid, ip_address=_ip())
    return jsonify({'status': 'deleted'})


# ── Invite codes ──────────────────────────────────────────────────────────────

@admin_bp.route('/invites')
@require_role('admin')
def list_invites():
    codes = get_all_invite_codes() or []
    # Return active code prominently
    active = next((c for c in codes if c.get('is_active')), None)
    return jsonify({'codes': codes, 'active_code': active['code'] if active else None})


@admin_bp.route('/invites', methods=['POST'])
@require_role('admin')
def create_invite():
    cu   = _cu()
    data = request.get_json(force=True, silent=True) or {}
    code = create_invite_code(created_by=cu['id'], label=data.get('label', ''),
                               expires_at=data.get('expires_at') or None,
                               max_uses=data.get('max_uses') or None)
    audit_log('create_invite_code', user_id=cu['id'], username=cu['username'],
              resource_type='invite_code', resource_id=code['id'],
              detail=f"code={code['code']}", ip_address=_ip())
    return jsonify(code), 201


@admin_bp.route('/invites/revoke', methods=['POST'])
@require_role('admin')
def revoke_active_invite():
    """Revoke the currently active invite code."""
    cu    = _cu()
    codes = get_all_invite_codes() or []
    active = next((c for c in codes if c.get('is_active')), None)
    if active:
        revoke_invite_code(active['id'])
        audit_log('revoke_invite_code', user_id=cu['id'], username=cu['username'],
                  resource_type='invite_code', resource_id=active['id'], ip_address=_ip())
    return jsonify({'status': 'revoked'})


@admin_bp.route('/invites/<int:cid>/revoke', methods=['POST'])
@require_role('admin')
def revoke_invite(cid):
    cu = _cu()
    revoke_invite_code(cid)
    audit_log('revoke_invite_code', user_id=cu['id'], username=cu['username'],
              resource_type='invite_code', resource_id=cid, ip_address=_ip())
    return jsonify({'status': 'revoked'})


@admin_bp.route('/invites/<int:cid>', methods=['DELETE'])
@require_role('admin')
def delete_invite(cid):
    cu = _cu()
    delete_invite_code(cid)
    audit_log('delete_invite_code', user_id=cu['id'], username=cu['username'],
              resource_type='invite_code', resource_id=cid, ip_address=_ip())
    return jsonify({'status': 'deleted'})
