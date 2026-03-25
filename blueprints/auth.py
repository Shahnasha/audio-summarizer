"""blueprints/auth_bp.py — login, logout, signup, profile."""
from flask import Blueprint, request, jsonify, redirect, url_for, render_template
from werkzeug.security import generate_password_hash
from src.auth import (login_user, logout_user, current_user, is_logged_in,
                      verify_password, hash_password)
from src.users import (get_user_by_username, get_user_by_id, create_user,
                       update_user, update_password)
from src.invites import validate_invite_code, consume_invite_code
from src.audit import log as audit_log

auth_bp = Blueprint('auth_bp', __name__)


def _ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '')


@auth_bp.route('/login')
def login_page():
    if is_logged_in():
        return redirect(url_for('main_index'))
    return render_template('login.html')


@auth_bp.route('/login', methods=['POST'])
def do_login():
    data = request.get_json(force=True) or {}
    user = get_user_by_username(data.get('username', '').strip())
    if not user or not verify_password(data.get('password', ''), user['password_hash']):
        return jsonify({'error': 'Invalid username or password'}), 401
    status = user.get('status', 'active')
    if status == 'pending':
        return jsonify({'error': 'Your account is awaiting admin approval'}), 403
    if status == 'rejected':
        return jsonify({'error': 'Your account registration was not approved'}), 403
    login_user(user)
    audit_log('login', user_id=user['id'], username=user['username'],
              resource_type='auth', ip_address=_ip())
    return jsonify({
        'ok': True, 'role': user['role'],
        'is_scoped_to_dept': bool(user.get('is_scoped_to_dept')),
        'username': user['username'],
    })


@auth_bp.route('/logout', methods=['POST'])
def do_logout():
    cu = current_user()
    if cu:
        audit_log('logout', user_id=cu['id'], username=cu['username'],
                  resource_type='auth', ip_address=_ip())
    logout_user()
    return jsonify({'ok': True})


@auth_bp.route('/me')
def me():
    cu = current_user()
    if not cu:
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify({'logged_in': True, **cu})


@auth_bp.route('/signup')
def signup_page():
    if is_logged_in():
        return redirect(url_for('main_index'))
    return render_template('signup.html')


@auth_bp.route('/signup', methods=['POST'])
def do_signup():
    data       = request.get_json(force=True) or {}
    username   = data.get('username', '').strip()
    email      = data.get('email', '').strip().lower()
    password   = data.get('password', '')
    ws_type    = data.get('workspace_type', 'join')   # create | join
    ws_name    = data.get('workspace_name', '').strip()
    ws_invite  = data.get('workspace_invite', '').strip()
    department = data.get('department', 'General').strip()
    raw_role   = data.get('role', 'employee').lower()

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    if not email:
        email = username + '@vox.local'
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    final_role = 'admin' if ws_type == 'create' else ('manager' if raw_role == 'manager' else 'employee')

    if ws_type == 'create':
        status = 'active'
    elif ws_invite:
        valid, reason = validate_invite_code(ws_invite)
        if not valid:
            return jsonify({'error': reason}), 400
        status = 'active'
    else:
        status = 'pending'

    try:
        uid = create_user(
            username=username, email=email,
            password_hash=generate_password_hash(password),
            role=final_role,
            team=ws_name or department if ws_type == 'create' else department,
            status=status,
            is_scoped_to_dept=0,
        )
        audit_log('signup', user_id=uid, username=username, resource_type='auth',
                  detail=f'{ws_type} / {status}', ip_address=_ip())
        if ws_type == 'join' and ws_invite and status == 'active':
            consume_invite_code(ws_invite)
        if status == 'active':
            login_user(get_user_by_id(uid))
            return jsonify({'ok': True})
        return jsonify({'ok': True, 'pending': True,
                        'message': 'Account created — awaiting admin approval.'})
    except ValueError:
        return jsonify({'error': 'Username or email already taken'}), 400


@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    cu = current_user()
    if not cu:
        return jsonify({'error': 'Authentication required'}), 401
    data   = request.get_json(force=True) or {}
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')
    if len(new_pw) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    user = get_user_by_id(cu['id'])
    if not user or not verify_password(old_pw, user['password_hash']):
        return jsonify({'error': 'Current password is incorrect'}), 400
    update_password(cu['id'], hash_password(new_pw))
    audit_log('change_password', user_id=cu['id'], username=cu['username'],
              resource_type='auth', ip_address=_ip())
    logout_user()
    return jsonify({'ok': True, 'message': 'Password changed. Please log in again.'})


@auth_bp.route('/api/user/profile', methods=['PUT'])
def update_profile():
    cu = current_user()
    if not cu:
        return jsonify({'error': 'Authentication required'}), 401
    data    = request.get_json(force=True) or {}
    db_user = get_user_by_id(cu['id'])
    if not db_user:
        return jsonify({'error': 'User not found'}), 404
    try:
        update_user(
            user_id=cu['id'],
            role=db_user['role'],
            team=data.get('department', '').strip() or db_user['team'],
            username=data.get('username', '').strip() or None,
            is_scoped_to_dept=db_user.get('is_scoped_to_dept', 0),
        )
        login_user(get_user_by_id(cu['id']))
        audit_log('update_profile', user_id=cu['id'], username=cu['username'],
                  resource_type='user', ip_address=_ip())
        return jsonify({'ok': True})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@auth_bp.route('/api/invite-codes/validate', methods=['POST'])
def validate_invite():
    data = request.get_json(force=True) or {}
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'valid': False, 'reason': 'No code provided'}), 400
    valid, reason = validate_invite_code(code)
    return jsonify({'valid': valid} if valid else {'valid': False, 'reason': reason})
