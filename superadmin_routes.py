from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from firebase_config import db, bucket
from datetime import datetime
from utils.id_generator import generate_id

superadmin_bp = Blueprint('superadmin', __name__)

@superadmin_bp.route('/superadmin/dashboard')
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get settings
        settings_ref = db.collection('superadmin').document('settings')
        settings = settings_ref.get().to_dict() or {}

        # Get recent audit logs
        logs_ref = db.collection('superadmin').document('audit_logs').collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10)
        recent_logs = [log.to_dict() for log in logs_ref.stream()]

        return render_template('superadmin/dashboard.html', settings=settings, recent_logs=recent_logs)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('login_page'))

@superadmin_bp.route('/superadmin/audit-logs')
def audit_logs():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get all audit logs
        logs_ref = db.collection('superadmin').document('audit_logs').collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING)
        logs = [log.to_dict() for log in logs_ref.stream()]

        return render_template('superadmin/audit-logs.html', logs=logs)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@superadmin_bp.route('/superadmin/manage-admins')
def manage_admins():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get all admins
        admins_ref = db.collection('users').where('role', '==', 'admin').stream()
        admins = [admin.to_dict() for admin in admins_ref]

        return render_template('superadmin/manage-admins.html', admins=admins)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@superadmin_bp.route('/superadmin/add-admin', methods=['POST'])
def add_admin():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get form data
        email = request.form.get('email')
        name = request.form.get('name')
        mobile = request.form.get('mobile')

        if not all([email, name, mobile]):
            flash('Missing required fields', 'error')
            return redirect(url_for('manage_admins'))

        # Create admin user
        admin_data = {
            'email': email,
            'name': name,
            'mobile': mobile,
            'role': 'admin',
            'created_at': datetime.now(),
            'created_by': session['user_id']
        }
        db.collection('users').add(admin_data)

        # Add to audit log
        audit_data = {
            'action': 'add_admin',
            'user_id': session['user_id'],
            'timestamp': datetime.now(),
            'details': {
                'admin_email': email,
                'admin_name': name
            }
        }
        db.collection('superadmin').document('audit_logs').collection('logs').add(audit_data)

        flash('Admin added successfully', 'success')
        return redirect(url_for('manage_admins'))
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('manage_admins')) 