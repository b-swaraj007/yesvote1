from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from firebase_config import db, bucket
from auth import get_user_data
from datetime import datetime
import os
import tempfile
from utils.id_generator import generate_event_id, generate_voter_id
from face_embedder import generate_embedding
from google.cloud import firestore
import base64

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    
    # Fetch all events created by this admin
    events_query = db.collection('events').where('admin_id', '==', session['user_id']).stream()
    events = []
    for event_doc in events_query:
        event = event_doc.to_dict()
        event_id = event['event_id']
        # Fetch candidates
        candidates = event.get('candidates', [])
        # Fetch voters by status
        voters_ref = db.collection('events').document(event_id).collection('voters')
        voters = [v.to_dict() for v in voters_ref.stream()]
        pending_voters = [v for v in voters if v['status'] == 'pending']
        approved_voters = [v for v in voters if v['status'] == 'approved']
        rejected_voters = [v for v in voters if v['status'] == 'rejected']
        # Fetch ballots and calculate results
        ballots_ref = db.collection('events').document(event_id).collection('ballots')
        ballots = [b.to_dict() for b in ballots_ref.stream()]
        results = {}
        for cand in candidates:
            cand_id = cand['candidate_id']
            results[cand_id] = sum(1 for b in ballots if b['candidate_id'] == cand_id)
        event['candidates'] = candidates
        event['pending_voters'] = pending_voters
        event['approved_voters'] = approved_voters
        event['rejected_voters'] = rejected_voters
        event['results'] = results
        events.append(event)
    
    return render_template('admin/dashboard.html', events=events, user=user_data)

@admin_bp.route('/pending-voters')
def pending_voters():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    
    # Get all pending voters
    pending_voters = []
    users_ref = db.collection('users').where('approved', '==', False).stream()
    for user in users_ref:
        user_data = user.to_dict()
        user_data['id'] = user.id
        pending_voters.append(user_data)
    
    return render_template('admin/pending-voters.html', voters=pending_voters)

@admin_bp.route('/approved-voters')
def approved_voters():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    
    # Get all approved voters
    approved_voters = []
    users_ref = db.collection('users').where('approved', '==', True).stream()
    for user in users_ref:
        user_data = user.to_dict()
        user_data['id'] = user.id
        approved_voters.append(user_data)
    
    return render_template('admin/approved-voters.html', voters=approved_voters)

@admin_bp.route('/create-event', methods=['GET', 'POST'])
def create_event():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        try:
            title = request.form.get('title')
            description = request.form.get('description')
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            event_id = generate_event_id()
            candidates = []
            candidate_names = request.form.getlist('candidate_name')
            candidate_photos = request.files.getlist('candidate_photo')
            for i, name in enumerate(candidate_names):
                photo_file = candidate_photos[i]
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                    temp_path = temp_file.name
                    photo_file.save(temp_path)
                blob = bucket.blob(f'event_candidates/{event_id}_{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg')
                blob.upload_from_filename(temp_path)
                photo_url = blob.public_url
                os.unlink(temp_path)
                candidates.append({
                    'candidate_id': f'{event_id}_cand_{i+1}',
                    'name': name,
                    'photo_url': photo_url
                })
            event_data = {
                'event_id': event_id,
                'event_name': title,
                'event_description': description,
                'start_time': start_date,
                'end_time': end_date,
                'admin_id': session['user_id'],
                'candidates': candidates,
                'status': 'active',
                'created_at': datetime.now().isoformat()
            }
            db.collection('events').document(event_id).set(event_data)
            return redirect(url_for('admin.dashboard'))
        except Exception as e:
            return render_template('admin/dashboard.html', error=str(e))
    return render_template('admin/create-event.html')

@admin_bp.route('/manage-events')
def manage_events():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    
    # Get all events for this admin
    events = []
    events_ref = db.collection('events').where('admin_id', '==', session['user_id']).stream()
    for event in events_ref:
        event_data = event.to_dict()
        event_data['id'] = event.id
        events.append(event_data)
    
    return render_template('admin/manage-events.html', events=events)

@admin_bp.route('/results')
def results():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    
    # Get all events and their results
    events = []
    events_ref = db.collection('events').where('admin_id', '==', session['user_id']).stream()
    for event in events_ref:
        event_data = event.to_dict()
        # Get votes for this event
        votes_ref = db.collection('votes').where('event_id', '==', event.id).stream()
        vote_counts = {}
        for vote in votes_ref:
            vote_data = vote.to_dict()
            candidate = vote_data.get('candidate_name')
            if candidate:
                vote_counts[candidate] = vote_counts.get(candidate, 0) + 1
        event_data['results'] = vote_counts
        events.append(event_data)
    
    return render_template('admin/results.html', events=events)

@admin_bp.route('/audit-logs')
def audit_logs():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    
    # Get audit logs for this admin's events
    logs = []
    events_ref = db.collection('events').where('admin_id', '==', session['user_id']).stream()
    for event in events_ref:
        event_id = event.id
        # Get all votes for this event
        votes_ref = db.collection('votes').where('event_id', '==', event_id).stream()
        for vote in votes_ref:
            vote_data = vote.to_dict()
            vote_data['event_id'] = event_id
            vote_data['event_name'] = event.get('event_name', 'Unknown Event')
            logs.append(vote_data)
    
    return render_template('admin/audit-logs.html', logs=logs)

@admin_bp.route('/approve/<user_id>', methods=['POST'])
def approve_voter(user_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        # Update user approval status
        db.collection('users').document(user_id).update({
            'approved': True,
            'approved_by': session['user_id'],
            'approved_at': datetime.now()
        })
        return jsonify({'message': 'Voter approved successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/reject/<user_id>', methods=['POST'])
def reject_voter(user_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        # Get user data
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
        
        user_data = user_doc.to_dict()
        
        # Delete user's photo from storage
        if 'photo_url' in user_data:
            photo_path = user_data['photo_url'].split('/')[-1]
            blob = bucket.blob(f'voter_photos/{photo_path}')
            blob.delete()
        
        # Delete user document
        db.collection('users').document(user_id).delete()
        
        return jsonify({'message': 'Voter rejected successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/event/<event_id>/results')
def admin_event_results(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login'))
    
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login'))
    
    try:
        # Get event data
        event_doc = db.collection('events').document(event_id).get()
        if not event_doc.exists:
            return redirect(url_for('admin.dashboard'))
        
        event_data = event_doc.to_dict()
        
        # Get votes for this event
        votes = db.collection('votes')\
            .where('event_id', '==', event_id)\
            .stream()
        
        vote_counts = {}
        for vote in votes:
            vote_data = vote.to_dict()
            candidate = vote_data.get('candidate_name')
            if candidate:
                vote_counts[candidate] = vote_counts.get(candidate, 0) + 1
        
        return render_template('admin/results.html',
                             event=event_data,
                             vote_counts=vote_counts)
    except Exception as e:
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/event/<event_id>/approve-voter/<voter_id>', methods=['POST'])
def approve_event_voter(event_id, voter_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        # Get voter data
        voter_ref = db.collection('events').document(event_id).collection('voters').document(voter_id)
        voter_data = voter_ref.get().to_dict()
        
        if not voter_data:
            return jsonify({'error': 'Voter not found'}), 404
        
        # Generate voter ID
        new_voter_id = generate_voter_id()
        
        # Generate face embedding
        photo_url = voter_data['photo_url']
        embedding = generate_embedding(photo_url)
        
        if embedding is None:
            return jsonify({'error': 'Could not generate face embedding'}), 400
        
        # Update voter data with new ID and embedding
        voter_data.update({
            'status': 'approved',
            'voter_id': new_voter_id,
            'embedding': embedding.tolist(),
            'approved_at': datetime.now(),
            'approved_by': session['user_id']
        })
        
        # Update voter document
        voter_ref.set(voter_data)
        
        return jsonify({
            'message': 'Voter approved successfully',
            'voter_id': new_voter_id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/event/<event_id>/reject-voter/<voter_id>', methods=['POST'])
def reject_event_voter(event_id, voter_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        # Get voter data
        voter_ref = db.collection('events').document(event_id).collection('voters').document(voter_id)
        voter_data = voter_ref.get().to_dict()
        
        if not voter_data:
            return jsonify({'error': 'Voter not found'}), 404
        
        # Delete photo from storage
        if 'photo_url' in voter_data:
            photo_path = voter_data['photo_url'].split('/')[-1]
            blob = bucket.blob(f'event_voters/{photo_path}')
            blob.delete()
        
        # Delete voter document
        voter_ref.delete()
        
        return jsonify({'message': 'Voter rejected successfully'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/event/<event_id>/pending-voters')
def event_pending_voters(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get pending voters for this specific event
        voters_ref = db.collection('events').document(event_id).collection('voters').where('status', '==', 'pending').stream()
        pending_voters = [voter.to_dict() for voter in voters_ref]
        return render_template('admin/pending-voters.html', voters=pending_voters, event_id=event_id)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@admin_bp.route('/event/<event_id>/approved-voters')
def event_approved_voters(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get approved voters for this specific event
        voters_ref = db.collection('events').document(event_id).collection('voters').where('status', '==', 'approved').stream()
        approved_voters = [voter.to_dict() for voter in voters_ref]
        return render_template('admin/approved-voters.html', voters=approved_voters, event_id=event_id)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@admin_bp.route('/admin/event/<event_id>/results')
def event_results_firestore(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get results for this specific event
        results_ref = db.collection('events').document(event_id).collection('results').stream()
        results = {doc.id: doc.to_dict() for doc in results_ref}
        
        # Get event details
        event_ref = db.collection('events').document(event_id)
        event_data = event_ref.get().to_dict()
        
        return render_template('admin/results.html', results=results, event=event_data)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@admin_bp.route('/admin/event/<event_id>/audit-logs')
def event_audit_logs(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get audit logs for this specific event
        logs_ref = db.collection('events').document(event_id).collection('audit_logs').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
        audit_logs = [log.to_dict() for log in logs_ref]
        return render_template('admin/audit-logs.html', logs=audit_logs, event_id=event_id)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@admin_bp.route('/admin/event/<event_id>/approve-voter/<voter_id>', methods=['POST'])
def approve_event_voter_firestore(event_id, voter_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Update voter status in event's voters subcollection
        voter_ref = db.collection('events').document(event_id).collection('voters').document(voter_id)
        voter_ref.update({
            'status': 'approved',
            'approved_at': datetime.now(),
            'approved_by': session['user_id']
        })

        # Add to audit log
        audit_data = {
            'action': 'voter_approved',
            'user_id': session['user_id'],
            'timestamp': datetime.now(),
            'details': {
                'voter_id': voter_id
            }
        }
        db.collection('events').document(event_id).collection('audit_logs').add(audit_data)

        flash('Voter approved successfully', 'success')
        return redirect(url_for('event_pending_voters', event_id=event_id))
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('event_pending_voters', event_id=event_id))

@admin_bp.route('/api/create-event', methods=['POST'])
def api_create_event():
    if not session.get('user_id') or get_user_data(session['user_id']).get('role') != 'admin':
        return jsonify({'error': 'Not authorized'}), 403
    try:
        data = request.get_json()
        title = data.get('title')
        description = data.get('description')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        candidates = data.get('candidates', [])
        if not (title and description and start_date and end_date and candidates):
            return jsonify({'error': 'Missing required fields'}), 400
        event_id = generate_event_id()
        candidate_objs = []
        for i, cand in enumerate(candidates):
            name = cand.get('name')
            party = cand.get('party')
            slogan = cand.get('slogan')
            photo_b64 = cand.get('photo')
            if not (name and party and slogan and photo_b64):
                return jsonify({'error': f'Missing candidate info for candidate {i+1}'}), 400
            # Save candidate photo to Firebase Storage
            photo_data = photo_b64.split(',')[1] if ',' in photo_b64 else photo_b64
            photo_bytes = base64.b64decode(photo_data)
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_path = temp_file.name
                temp_file.write(photo_bytes)
            blob = bucket.blob(f'event_candidates/{event_id}_{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg')
            blob.upload_from_filename(temp_path)
            blob.make_public()
            photo_url = blob.public_url
            os.unlink(temp_path)
            candidate_objs.append({
                'candidate_id': f'{event_id}_cand_{i+1}',
                'name': name,
                'party': party,
                'slogan': slogan,
                'photo_url': photo_url
            })
        event_data = {
            'event_id': event_id,
            'event_name': title,
            'event_description': description,
            'start_time': start_date,
            'end_time': end_date,
            'admin_id': session['user_id'],
            'candidates': candidate_objs,
            'status': 'active',
            'created_at': datetime.now().isoformat()
        }
        db.collection('events').document(event_id).set(event_data)
        return jsonify({'message': 'Event created successfully!', 'event_id': event_id}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500 