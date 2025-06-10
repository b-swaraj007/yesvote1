from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, flash
import os
from dotenv import load_dotenv
from verify_voter import verify_voter_face
from register_voter import register_voter_face
from firebase_config import db, bucket
from firebase_admin import firestore, auth as firebase_auth
from auth import create_user, verify_user, get_user_data, update_user_data
from admin_routes import admin_bp
from werkzeug.utils import secure_filename
import tempfile
from datetime import datetime
from utils.id_generator import generate_ballot_id, generate_receipt_id, generate_voter_id, generate_id
from PIL import Image
import io
from functools import wraps
import base64
import urllib.parse
from face_embedder import generate_embedding
import numpy as np
import cv2
from dateutil import parser  # You may need to install python-dateutil

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Register admin blueprint
app.register_blueprint(admin_bp, url_prefix='/admin')

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    team_members_ref = db.collection('superadmin').document('team_members').collection('members').order_by('order').stream()
    team_members = [dict(doc.to_dict(), id=doc.id) for doc in team_members_ref]
    return render_template('index.html', team_members=team_members)

@app.route('/register', methods=['GET'])
def register_page():
    return render_template('register.html')

@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')

@app.route('/verify-token', methods=['POST'])
def verify_token():
    try:
        # Get the ID token from the request
        id_token = request.json.get('idToken')
        if not id_token:
            return jsonify({'error': 'No token provided'}), 400

        # Verify the ID token
        decoded_token = firebase_auth.verify_id_token(id_token)
        uid = decoded_token['uid']

        # Get user data from Firestore
        user_doc = db.collection('users').document(uid).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404

        user_data = user_doc.to_dict()
        
        # Set session data
        session['user_id'] = uid
        session['role'] = user_data.get('role', 'voter')

        return jsonify({
            'message': 'Login successful',
            'role': user_data.get('role', 'voter')
        })

    except Exception as e:
        print(f"Token verification error: {str(e)}")
        return jsonify({'error': 'Invalid token'}), 401

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['fullName', 'email', 'mobile', 'aadhar', 'password', 'photo']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Validate mobile number (10 digits)
        if not data['mobile'].isdigit() or len(data['mobile']) != 10:
            return jsonify({'error': 'Invalid mobile number'}), 400
        
        # Validate Aadhar number (12 digits)
        if not data['aadhar'].isdigit() or len(data['aadhar']) != 12:
            return jsonify({'error': 'Invalid Aadhar number'}), 400
        
        # Check if email already exists
        email_query = db.collection('users').where('email', '==', data['email']).limit(1).get()
        if len(email_query) > 0:
            return jsonify({'error': 'Email already registered'}), 400
        
        # Check if Aadhar already exists
        aadhar_query = db.collection('users').where('aadhar', '==', data['aadhar']).limit(1).get()
        if len(aadhar_query) > 0:
            return jsonify({'error': 'Aadhar number already registered'}), 400
        
        # Create user in Firebase Auth
        user = firebase_auth.create_user(
            email=data['email'],
            password=data['password'],
            display_name=data['fullName']
        )
        
        try:
            # Upload photo to Firebase Storage
            photo_data = data['photo'].split(',')[1]  # Remove data URL prefix
            photo_bytes = base64.b64decode(photo_data)
            
            # Create a temporary file
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_path = temp_file.name
                temp_file.write(photo_bytes)
            
            # Upload to Firebase Storage
            blob = bucket.blob(f'user_photos/{user.uid}.jpg')
            blob.upload_from_filename(temp_path)
            blob.make_public()
            photo_url = blob.public_url
            
            # Read image from bytes for embedding
            nparr = np.frombuffer(photo_bytes, np.uint8)
            img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            embedding = generate_embedding(img_np)
            if embedding is None:
                # Clean up
                os.unlink(temp_path)
                firebase_auth.delete_user(user.uid)
                flash('no face detected please place your face in camera frame', 'error')
                return jsonify({'error': 'no face detected please place your face in camera frame'}), 400
            embedding_list = embedding.tolist()

            # After embedding is generated, check for duplicate faces
            users_ref = db.collection('users').stream()
            for user_doc in users_ref:
                existing = user_doc.to_dict()
                if 'embedding' in existing:
                    existing_emb = np.array(existing['embedding'])
                    dist = np.linalg.norm(np.array(embedding_list) - existing_emb)
                    if dist < 0.6:
                        os.unlink(temp_path)
                        firebase_auth.delete_user(user.uid)
                        flash('This face is already registered with another account.', 'error')
                        return jsonify({'error': 'This face is already registered with another account.'}), 400
            os.unlink(temp_path)
        except Exception as e:
            firebase_auth.delete_user(user.uid)
            print(f"Photo upload or embedding error: {str(e)}")
            return jsonify({'error': 'Failed to upload photo or extract face embedding. Please try again.'}), 500
        
        # Store user data in Firestore
        voter_id = generate_voter_id()
        user_data = {
            'name': data['fullName'],
            'email': data['email'],
            'mobile': data['mobile'],
            'aadhar': data['aadhar'],
            'voter_id': voter_id,
            'photo_url': photo_url,
            'embedding': embedding_list,
            'role': 'voter',
            'created_at': datetime.now(),
            'approved': False  # Requires admin approval
        }
        db.collection('users').document(user.uid).set(user_data)
        return jsonify({'message': 'Registration successful', 'voter_id': voter_id}), 200
    except Exception as e:
        print(f"Registration error: {str(e)}")
        return jsonify({'error': 'Registration failed. Please try again.'}), 500

@app.route('/voter/dashboard')
@login_required
def voter_dashboard():
    if session.get('role') != 'voter':
        return redirect(url_for('login_page'))
    user_id = session['user_id']
    # Get user data from Firestore
    user_doc = db.collection('users').document(user_id).get()
    if not user_doc.exists:
        return redirect(url_for('login_page'))
    user_data = user_doc.to_dict()

    voter_id = user_data.get('voter_id')
    # Get events the user has joined (exists in event's voters subcollection)
    events_ref = db.collection('events').stream()
    joined_events = []
    for event in events_ref:
        event_data = event.to_dict()
        event_id = event.id
        voter_ref = db.collection('events').document(event_id).collection('voters').where('voter_id', '==', voter_id).limit(1)
        voter_docs = list(voter_ref.stream())
        if voter_docs:
            voter_doc = voter_docs[0]
            voter_status = voter_doc.to_dict().get('status', 'pending')
            approved = voter_doc.to_dict().get('approved', False)
            has_voted = voter_doc.to_dict().get('has_voted', False)
            # Voting window
            start_time = event_data.get('start_time')
            end_time = event_data.get('end_time')
            # Convert to datetime if string
            if isinstance(start_time, str):
                try:
                    start_time = parser.parse(start_time)
                except Exception:
                    start_time = None
            if isinstance(end_time, str):
                try:
                    end_time = parser.parse(end_time)
                except Exception:
                    end_time = None
            joined_events.append({
                'event_id': event_id,
                'event_name': event_data.get('event_name'),
                'event_description': event_data.get('event_description'),
                'start_time': start_time,
                'end_time': end_time,
                'status': voter_status,
                'approved': approved,
                'has_voted': has_voted,
                'candidates': event_data.get('candidates', []),
            })

    # Get past votes (optional, keep as before)
    votes_ref = db.collection('votes').where('voter_id', '==', voter_id).stream()
    past_votes = []
    for vote in votes_ref:
        vote_data = vote.to_dict()
        event_ref = db.collection('events').document(vote_data['event_id']).get()
        if event_ref.exists:
            event_data = event_ref.to_dict()
            vote_data['event_name'] = event_data.get('event_name', 'Unknown Event')
            vote_data['date'] = event_data.get('date', 'N/A')
            vote_data['status'] = 'Voted'
            past_votes.append(vote_data)

    return render_template('voter/dashboard.html', 
                         user=user_data,
                         joined_events=joined_events,
                         past_votes=past_votes,
                         now=datetime.now())

@app.route('/vote/<event_id>', methods=['POST'])
def vote(event_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    try:
        # Get voter data from event's voters subcollection
        voter_ref = db.collection('events').document(event_id).collection('voters').document(session['user_id'])
        voter_data = voter_ref.get().to_dict()
        if not voter_data or voter_data.get('status') != 'approved':
            return jsonify({'error': 'Voter not approved for this event'}), 403
        if voter_data.get('has_voted'):
            return jsonify({'error': 'You have already voted in this event'}), 400

        # Generate ballot ID and receipt ID
        ballot_id = generate_ballot_id()
        receipt_id = generate_receipt_id()
        candidate_id = request.form.get('candidate_id')

        # Store vote in event's ballots subcollection
        vote_data = {
            'voter_id': session['user_id'],
            'candidate_id': candidate_id,
            'timestamp': datetime.now(),
            'status': 'cast',
            'receipt_id': receipt_id
        }
        db.collection('events').document(event_id).collection('ballots').document(ballot_id).set(vote_data)

        # Update voter's voting status
        voter_ref.update({
            'has_voted': True,
            'ballot_id': ballot_id,
            'receipt_id': receipt_id,
            'voted_at': datetime.now()
        })

        # Add to audit log
        audit_data = {
            'action': 'vote_cast',
            'user_id': session['user_id'],
            'timestamp': datetime.now(),
            'details': {
                'ballot_id': ballot_id,
                'candidate_id': candidate_id
            }
        }
        db.collection('events').document(event_id).collection('audit_logs').add(audit_data)

        # Update results
        results_ref = db.collection('events').document(event_id).collection('results').document(candidate_id)
        results_doc = results_ref.get()
        if results_doc.exists:
            current_votes = results_doc.to_dict().get('votes', 0)
            results_ref.update({
                'votes': current_votes + 1,
                'last_updated': datetime.now()
            })
        else:
            results_ref.set({
                'votes': 1,
                'last_updated': datetime.now()
            })

        return jsonify({
            'message': 'Vote cast successfully',
            'ballot_id': ballot_id,
            'receipt_id': receipt_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/voter/join-event', methods=['GET', 'POST'])
def join_event():
    if not session.get('user_id') or session.get('role') != 'voter':
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        event_id = request.form.get('event_id')
        event_doc = db.collection('events').document(event_id).get()
        if event_doc.exists:
            return redirect(url_for('voter_register', event_id=event_id))
        else:
            error = 'Event not found. Please check the Event ID.'
    return render_template('voter/join_event.html', error=error)

@app.route('/voter/register/<event_id>', methods=['GET', 'POST'])
def voter_register(event_id):
    if not session.get('user_id') or session.get('role') != 'voter':
        return redirect(url_for('login'))
    event_doc = db.collection('events').document(event_id).get()
    if not event_doc.exists:
        return redirect(url_for('join_event'))
    return render_template('voter/register_event.html', event=event_doc.to_dict())

@app.route('/voter/waiting-approval')
def waiting_approval():
    if not session.get('user_id') or session.get('role') != 'voter':
        return redirect(url_for('login'))
    return render_template('voter/waiting_approval.html')

@app.route('/how-voting-works')
def how_voting_works():
    return render_template('how-voting-works.html')

@app.route('/superadmin/dashboard')
def superadmin_dashboard():
    if not session.get('user_id') or session.get('role') != 'superadmin':
        return redirect(url_for('login_page'))
    return render_template('superadmin/dashboard.html')

@app.route('/superadmin/manage-landing', methods=['GET'])
def manage_landing_page():
    if not session.get('user_id') or session.get('role') != 'superadmin':
        return redirect(url_for('login_page'))
    team_members_ref = db.collection('superadmin').document('team_members').collection('members').order_by('order').stream()
    team_members = [dict(doc.to_dict(), id=doc.id) for doc in team_members_ref]
    return render_template('superadmin/manage_landing.html', team_members=team_members)

@app.route('/superadmin/manage-landing/upload', methods=['POST'])
def upload_team_images():
    for member_id in request.form.getlist('member_id'):
        photo = request.files.get(f'photo_{member_id}')
        if photo and photo.filename:
            blob = bucket.blob(f'team_members/{member_id}.jpg')
            blob.upload_from_file(photo, content_type=photo.mimetype)
            # Always use the correct public URL format
            photo_url = f"https://firebasestorage.googleapis.com/v0/b/lets-vote-c3a70.firebasestorage.app/o/{urllib.parse.quote(blob.name)}?alt=media"
            db.collection('superadmin').document('team_members').collection('members').document(member_id).update({
                'photo_url': photo_url
            })
    flash('Team images updated successfully!', 'success')
    return redirect(url_for('manage_landing_page'))

@app.route('/superadmin/team-members', methods=['GET'])
def get_team_members():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get team members
        team_ref = db.collection('superadmin').document('team_members').collection('members')
        team_members = [doc.to_dict() for doc in team_ref.stream()]
        return render_template('superadmin/team-members.html', team_members=team_members)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('login_page'))

@app.route('/superadmin/add-team-member', methods=['POST'])
def add_team_member():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get form data
        name = request.form.get('name')
        role = request.form.get('role')
        bio = request.form.get('bio')
        photo = request.files.get('photo')

        if not all([name, role, photo]):
            flash('Missing required fields', 'error')
            return redirect(url_for('get_team_members'))

        # Upload photo
        photo_path = f'team_members/{generate_id()}.jpg'
        blob = bucket.blob(photo_path)
        blob.upload_from_file(photo)
        photo_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{urllib.parse.quote(blob.name)}?alt=media"

        # Add team member
        member_data = {
            'name': name,
            'role': role,
            'bio': bio,
            'photo_url': photo_url,
            'added_at': datetime.now(),
            'added_by': session['user_id']
        }
        db.collection('superadmin').document('team_members').collection('members').add(member_data)

        # Add to audit log
        audit_data = {
            'action': 'add_team_member',
            'user_id': session['user_id'],
            'timestamp': datetime.now(),
            'details': {
                'member_name': name,
                'role': role
            }
        }
        db.collection('superadmin').document('audit_logs').collection('logs').add(audit_data)

        flash('Team member added successfully', 'success')
        return redirect(url_for('get_team_members'))
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('get_team_members'))

@app.route('/superadmin/update-settings', methods=['POST'])
def update_superadmin_settings():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Check if user is superadmin
        user_ref = db.collection('users').document(session['user_id'])
        user_data = user_ref.get().to_dict()
        if not user_data or user_data.get('role') != 'superadmin':
            return redirect(url_for('login_page'))

        # Get form data
        maintenance_mode = request.form.get('maintenance_mode') == 'true'
        registration_enabled = request.form.get('registration_enabled') == 'true'

        # Update settings
        settings_data = {
            'maintenance_mode': maintenance_mode,
            'registration_enabled': registration_enabled,
            'last_updated': datetime.now(),
            'updated_by': session['user_id']
        }
        db.collection('superadmin').document('settings').set(settings_data)

        # Add to audit log
        audit_data = {
            'action': 'update_settings',
            'user_id': session['user_id'],
            'timestamp': datetime.now(),
            'details': {
                'maintenance_mode': maintenance_mode,
                'registration_enabled': registration_enabled
            }
        }
        db.collection('superadmin').document('audit_logs').collection('logs').add(audit_data)

        flash('Settings updated successfully', 'success')
        return redirect(url_for('superadmin_dashboard'))
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('superadmin_dashboard'))

@app.route('/superadmin/fix-photo-urls')
def fix_photo_urls():
    bucket_name = "lets-vote-c3a70.firebasestorage.app"
    members_ref = db.collection('superadmin').document('team_members').collection('members').stream()
    for doc in members_ref:
        member_id = doc.id
        filename = f"{member_id}.jpg"
        photo_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/team_members%2F{filename}?alt=media"
        db.collection('superadmin').document('team_members').collection('members').document(member_id).update({
            'photo_url': photo_url
        })
    return 'All photo_url fields updated to the correct format.'

@app.route('/voter/settings', methods=['GET', 'POST'])
def voter_settings():
    if not session.get('user_id') or session.get('role') != 'voter':
        return redirect(url_for('login'))
    user_id = session['user_id']
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        return redirect(url_for('login'))
    user = user_doc.to_dict()

    if request.method == 'POST':
        name = request.form.get('firstName', '').strip() + ' ' + request.form.get('lastName', '').strip()
        mobile = request.form.get('phone', '').strip()
        bio = request.form.get('bio', '').strip()
        update_data = {
            'name': name or user.get('name', ''),
            'mobile': mobile or user.get('mobile', ''),
            'bio': bio or user.get('bio', ''),
        }
        try:
            user_ref.update(update_data)
            flash('Profile updated successfully!', 'success')
            # Refresh user data
            user = user_ref.get().to_dict()
        except Exception as e:
            flash('Failed to update profile: ' + str(e), 'error')
    return render_template('voter/settings.html', user=user)

@app.route('/voter/api/join-event', methods=['POST'])
def voter_api_join_event():
    if not session.get('user_id') or session.get('role') != 'voter':
        return jsonify({'error': 'Not authorized'}), 403
    data = request.get_json()
    event_id = data.get('event_id')
    if not event_id:
        return jsonify({'error': 'Event ID is required'}), 400
    event_ref = db.collection('events').document(event_id)
    event_doc = event_ref.get()
    if not event_doc.exists:
        return jsonify({'error': 'Event not found'}), 404
    event_data = event_doc.to_dict()
    user_id = session['user_id']
    voter_ref = event_ref.collection('voters').document(user_id)
    voter_doc = voter_ref.get()
    if voter_doc.exists:
        voter_status = voter_doc.to_dict().get('status', 'pending')
        return jsonify({'event': event_data, 'status': voter_status}), 200
    # Copy user data from global users
    user_doc = db.collection('users').document(user_id).get()
    if not user_doc.exists:
        return jsonify({'error': 'User not found'}), 404
    user_data = user_doc.to_dict()
    event_voter_data = {
        'user_id': user_id,
        'voter_id': user_data.get('voter_id'),
        'name': user_data.get('name'),
        'email': user_data.get('email'),
        'mobile': user_data.get('mobile'),
        'photo_url': user_data.get('photo_url'),
        'embedding': user_data.get('embedding'),
        'status': 'pending',
        'approved': False,
        'has_voted': False,
        'joined_at': datetime.now(),
    }
    voter_ref.set(event_voter_data)
    return jsonify({'event': event_data, 'status': 'pending'}), 200

if __name__ == '__main__':
    app.run(debug=True) 