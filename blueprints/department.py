"""blueprints/departments_bp.py"""
from flask import Blueprint, request, jsonify
from src.auth import login_required, require_role, current_user
from src.departments import (create_department, get_department, update_department,
                               delete_department, get_all_departments, get_department_tree,
                               add_member, remove_member, get_department_members,
                               get_user_departments)
from src.audit import log as audit_log

departments_bp = Blueprint('departments_bp', __name__, url_prefix='/api')
def _cu(): return current_user()
def _ip(): return request.headers.get('X-Forwarded-For', request.remote_addr or '')


@departments_bp.route('/departments')
@login_required
def list_departments():
    tree = get_department_tree()
    # Flatten for simpler frontend usage; also return as {departments: [...]}
    flat = get_all_departments() or []
    return jsonify({'departments': flat, 'tree': tree or []})


@departments_bp.route('/departments', methods=['POST'])
@require_role('admin', 'manager')
def create_dept():
    cu        = _cu()
    data      = request.get_json(force=True) or {}
    parent_id = data.get('parent_id') or None
    if cu['role'] == 'manager':
        if not parent_id:
            return jsonify({'error': 'Managers can only create sub-departments'}), 403
        parent = get_department(parent_id)
        if not parent or parent.get('manager_id') != cu['id']:
            return jsonify({'error': 'Not authorised for this department'}), 403
    if cu.get('is_scoped_to_dept') and not parent_id:
        return jsonify({'error': 'Scoped admin must specify a parent department'}), 403
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Department name required'}), 400
    did = create_department(
        name=name, description=data.get('description', ''),
        parent_id=parent_id, manager_id=data.get('manager_id') or None,
    )
    audit_log('create_department', user_id=cu['id'], username=cu['username'],
              resource_type='department', resource_id=did,
              detail=name, ip_address=_ip())
    return jsonify({'id': did, 'parent_id': parent_id, 'status': 'created'}), 201


@departments_bp.route('/departments/<int:did>', methods=['PUT', 'PATCH'])
@require_role('admin')
def update_dept(did):
    cu = _cu()
    if cu.get('is_scoped_to_dept'):
        dept = get_department(did)
        if not dept or dept.get('manager_id') != cu['id']:
            return jsonify({'error': 'Scoped admin can only edit their own departments'}), 403
    data = request.get_json(force=True) or {}
    update_department(did, name=data.get('name'), description=data.get('description'),
                      parent_id=data.get('parent_id'), manager_id=data.get('manager_id'))
    audit_log('update_department', user_id=cu['id'], username=cu['username'],
              resource_type='department', resource_id=did, ip_address=_ip())
    return jsonify({'status': 'updated'})


@departments_bp.route('/departments/<int:did>', methods=['DELETE'])
@require_role('admin')
def delete_dept(did):
    cu = _cu()
    if cu.get('is_scoped_to_dept'):
        dept = get_department(did)
        if not dept or dept.get('manager_id') != cu['id']:
            return jsonify({'error': 'Scoped admin can only delete their own departments'}), 403
    delete_department(did)
    audit_log('delete_department', user_id=cu['id'], username=cu['username'],
              resource_type='department', resource_id=did, ip_address=_ip())
    return jsonify({'status': 'deleted'})


@departments_bp.route('/departments/<int:did>/members')
@login_required
def dept_members(did):
    members = get_department_members(did)
    return jsonify({'members': members or []})


@departments_bp.route('/departments/<int:did>/members', methods=['POST'])
@require_role('admin', 'manager')
def add_dept_member(did):
    cu = _cu()
    if cu['role'] == 'manager':
        dept = get_department(did)
        if not dept or dept.get('manager_id') != cu['id']:
            return jsonify({'error': 'Not authorised to manage this department'}), 403
    data = request.get_json(force=True) or {}
    uid  = data.get('user_id')
    if not uid:
        return jsonify({'error': 'user_id required'}), 400
    add_member(did, uid)
    audit_log('add_dept_member', user_id=cu['id'], username=cu['username'],
              resource_type='department', resource_id=did,
              detail=f'user_id={uid}', ip_address=_ip())
    return jsonify({'status': 'added'})


@departments_bp.route('/departments/<int:did>/members/<int:uid>', methods=['DELETE'])
@require_role('admin', 'manager')
def remove_dept_member(did, uid):
    cu = _cu()
    if cu['role'] == 'manager':
        dept = get_department(did)
        if not dept or dept.get('manager_id') != cu['id']:
            return jsonify({'error': 'Not authorised to manage this department'}), 403
    remove_member(did, uid)
    audit_log('remove_dept_member', user_id=cu['id'], username=cu['username'],
              resource_type='department', resource_id=did,
              detail=f'user_id={uid}', ip_address=_ip())
    return jsonify({'status': 'removed'})
