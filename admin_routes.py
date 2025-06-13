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
from dateutil import parser
import sys

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/dashboard')
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))

    from datetime import datetime
    admin_name = user_data.get('name', 'Admin')
    admin_email = user_data.get('email', '')
    admin_initials = ''.join([x[0] for x in admin_name.split()][:2]).upper() if admin_name else 'AD'
    admin_first_name = admin_name.split()[0] if admin_name else 'Admin'
    today_date = datetime.now().strftime("%B %d, %Y")
    notifications = []

    # Fetch events created by this admin
    events_query = db.collection('events').where('admin_id', '==', session['user_id']).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
    events = [e.to_dict() for e in events_query]
    events_created = len(events)
    events_created_growth = f"{events_created} events"

    # Stat cards (across all events)
    total_voters = 0
    approved_voters = 0
    pending_approvals = 0
    votes_cast = 0
    for event in events:
        event_id = event.get('event_id')
        voters_ref = db.collection('events').document(event_id).collection('voters').stream()
        voters = [v.to_dict() for v in voters_ref]
        total_voters += len(voters)
        approved_voters += sum(1 for v in voters if v.get('approved'))
        pending_approvals += sum(1 for v in voters if not v.get('approved'))
        votes_cast += sum(1 for v in voters if v.get('has_voted'))
    voter_turnout = round((votes_cast / approved_voters * 100), 1) if approved_voters > 0 else 0.0
    # Growth values are placeholders
    total_voters_growth = 0
    approved_voters_growth = 0
    pending_approvals_growth = 0
    voter_turnout_growth = 0

    # Chart events (last 5 events)
    chart_events = [{"value": e.get('event_id'), "label": e.get('event_name', 'Event')} for e in events[:5]]
    # Votes per candidate for the most recent event
    votes_chart_option = {"animation": False, "series": []}
    turnout_chart_option = {"animation": False, "series": []}
    if events:
        event = events[0]
        event_id = event.get('event_id')
        candidates = event.get('candidates', [])
        # Use ballots subcollection for vote counts
        ballots_ref = db.collection('events').document(event_id).collection('ballots').stream()
        ballots = [b.to_dict() for b in ballots_ref]
        candidate_names = [c.get('name') for c in candidates]
        candidate_votes = [sum(1 for b in ballots if b.get('candidate_id') == c.get('candidate_id')) for c in candidates]
        votes_chart_option = {
            "animation": False,
            "tooltip": {"trigger": "axis", "backgroundColor": "rgba(255, 255, 255, 0.8)", "textStyle": {"color": "#1f2937"}},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": candidate_names, "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}}, "axisLabel": {"color": "rgba(255, 255, 255, 0.7)", "rotate": 45}},
            "yAxis": {"type": "value", "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}}, "splitLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.1)"}}, "axisLabel": {"color": "rgba(255, 255, 255, 0.7)"}},
            "series": [{"name": "Votes", "type": "bar", "data": candidate_votes, "itemStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "rgba(87, 181, 231, 0.8)"}, {"offset": 1, "color": "rgba(87, 181, 231, 0.3)"}]}, "borderRadius": [5, 5, 0, 0]}, "emphasis": {"itemStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "rgba(87, 181, 231, 1)"}, {"offset": 1, "color": "rgba(87, 181, 231, 0.5)"}]}}}}]
        }
        voters_ref = db.collection('events').document(event_id).collection('voters').stream()
        voters = [v.to_dict() for v in voters_ref]
        voted = sum(1 for v in voters if v.get('has_voted'))
        not_voted = len(voters) - voted
        turnout_chart_option = {
            "animation": False,
            "tooltip": {"trigger": "item", "backgroundColor": "rgba(255, 255, 255, 0.8)", "textStyle": {"color": "#1f2937"}},
            "legend": {"top": "bottom", "left": "center", "textStyle": {"color": "#fff"}},
            "series": [{"name": "Voter Turnout", "type": "pie", "radius": ["40%", "70%"], "avoidLabelOverlap": False, "itemStyle": {"borderRadius": 10, "borderColor": "rgba(0, 0, 0, 0.1)", "borderWidth": 2}, "label": {"show": False}, "emphasis": {"label": {"show": True, "fontSize": "14", "fontWeight": "bold", "color": "#fff"}}, "labelLine": {"show": False}, "data": [{"value": voted, "name": "Voted", "itemStyle": {"color": "rgba(87, 181, 231, 1)"}}, {"value": not_voted, "name": "Not Voted", "itemStyle": {"color": "rgba(252, 141, 98, 1)"}}]}]
        }

    # Action cards (static for now)
    action_cards = [
        {"bg": "bg-green-500 bg-opacity-20", "icon": "ri-add-circle-line", "icon_color": "text-green-500", "title": "Create New Voting Event", "description": "Set up a new election or poll", "button_bg": "bg-green-500 bg-opacity-20", "button_text": "text-green-400", "button_label": "Create Event"},
        {"bg": "bg-blue-500 bg-opacity-20", "icon": "ri-user-follow-line", "icon_color": "text-blue-500", "title": "Pending Voter Approvals", "description": f"{pending_approvals} voters awaiting approval", "button_bg": "bg-blue-500 bg-opacity-20", "button_text": "text-blue-400", "button_label": "Review"},
        {"bg": "bg-purple-500 bg-opacity-20", "icon": "ri-team-line", "icon_color": "text-purple-500", "title": "View Registered Voters", "description": "Manage all voter accounts", "button_bg": "bg-purple-500 bg-opacity-20", "button_text": "text-purple-400", "button_label": "View List"},
        {"bg": "bg-yellow-500 bg-opacity-20", "icon": "ri-bar-chart-2-line", "icon_color": "text-yellow-500", "title": "View and Publish Results", "description": "Manage election results", "button_bg": "bg-yellow-500 bg-opacity-20", "button_text": "text-yellow-400", "button_label": "View Results"},
        {"bg": "bg-red-500 bg-opacity-20", "icon": "ri-shield-check-line", "icon_color": "text-red-500", "title": "Access Audit Logs", "description": "Review system activity", "button_bg": "bg-red-500 bg-opacity-20", "button_text": "text-red-400", "button_label": "View Logs"},
        {"bg": "bg-indigo-500 bg-opacity-20", "icon": "ri-notification-4-line", "icon_color": "text-indigo-500", "title": "Send Reminder to Non-voters", "description": f"{total_voters - votes_cast} voters haven't voted", "button_bg": "bg-indigo-500 bg-opacity-20", "button_text": "text-indigo-400", "button_label": "Send Reminder"},
    ]

    # Audit logs (latest 5 from all events)
    audit_logs = []
    for event in events:
        event_id = event.get('event_id')
        logs_ref = db.collection('events').document(event_id).collection('audit_logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(5).stream()
        for log in logs_ref:
            log_data = log.to_dict()
            audit_logs.append({
                "voter_id": log_data.get('voter_id', '-'),
                "full_name": log_data.get('full_name', '-'),
                "email": log_data.get('email', '-'),
                "status_bg": "bg-green-500 bg-opacity-20" if log_data.get('vote_status') == 'Vote Cast' else "bg-red-500 bg-opacity-20",
                "status_text": "text-green-400" if log_data.get('vote_status') == 'Vote Cast' else "text-red-400",
                "vote_status": log_data.get('vote_status', '-'),
                "time_of_vote": log_data.get('time_of_vote', '-'),
                "event_name": event.get('event_name', '-'),
                "action_bg": "bg-blue-500 bg-opacity-20",
                "action_icon": "ri-eye-line",
                "action_icon_color": "text-blue-400"
            })
    audit_logs = audit_logs[:5]
    audit_logs_total = len(audit_logs)
    audit_logs_pages = [
        {"number": 1, "active": True, "icon": None},
        {"number": 2, "active": False, "icon": None},
        {"number": 3, "active": False, "icon": None},
        {"number": None, "active": False, "icon": "ri-arrow-right-s-line"},
    ]
    audit_log_events = chart_events

    # Result events (show status and turnout for each event)
    result_events = []
    for event in events[:2]:
        event_id = event.get('event_id')
        voters_ref = db.collection('events').document(event_id).collection('voters').stream()
        voters = [v.to_dict() for v in voters_ref]
        approved = sum(1 for v in voters if v.get('approved'))
        voted = sum(1 for v in voters if v.get('has_voted'))
        turnout = round((voted / approved * 100), 1) if approved > 0 else 0.0
        result_events.append({
            "name": event.get('event_name', '-'),
            "status_bg": "bg-yellow-500 bg-opacity-20" if event.get('status') == 'active' else "bg-blue-500 bg-opacity-20",
            "status_text": "text-yellow-400" if event.get('status') == 'active' else "text-blue-400",
            "status": "Pending" if event.get('status') == 'active' else "Completed",
            "voting_label": "Voting ends in:" if event.get('status') == 'active' else "Voting ended:",
            "voting_value": "-",  # You can calculate time left if needed
            "turnout_label": "Current turnout:" if event.get('status') == 'active' else "Final turnout:",
            "turnout_value": f"{turnout}% ({voted} of {approved})",
            "button_bg": "bg-yellow-500 bg-opacity-20" if event.get('status') == 'active' else "bg-primary bg-opacity-20",
            "button_text": "text-yellow-400" if event.get('status') == 'active' else "text-primary",
            "button_icon": "ri-eye-line" if event.get('status') == 'active' else "ri-send-plane-line",
            "button_label": "Preview Results" if event.get('status') == 'active' else "Publish Results"
        })

    # Build all_chart_data for the last 5 events
    all_chart_data = {}
    for e in events[:5]:
        event_id = e.get('event_id')
        candidates = e.get('candidates', [])
        # Use ballots subcollection for vote counts
        ballots_ref = db.collection('events').document(event_id).collection('ballots').stream()
        ballots = [b.to_dict() for b in ballots_ref]
        candidate_names = [c.get('name') for c in candidates]
        candidate_votes = [sum(1 for b in ballots if b.get('candidate_id') == c.get('candidate_id')) for c in candidates]
        votes_chart_option = {
            "animation": False,
            "tooltip": {"trigger": "axis", "backgroundColor": "rgba(255, 255, 255, 0.8)", "textStyle": {"color": "#1f2937"}},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": candidate_names, "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}}, "axisLabel": {"color": "rgba(255, 255, 255, 0.7)", "rotate": 45}},
            "yAxis": {"type": "value", "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}}, "splitLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.1)"}}, "axisLabel": {"color": "rgba(255, 255, 255, 0.7)"}},
            "series": [{"name": "Votes", "type": "bar", "data": candidate_votes, "itemStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "rgba(87, 181, 231, 0.8)"}, {"offset": 1, "color": "rgba(87, 181, 231, 0.3)"}]}, "borderRadius": [5, 5, 0, 0]}, "emphasis": {"itemStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "rgba(87, 181, 231, 1)"}, {"offset": 1, "color": "rgba(87, 181, 231, 0.5)"}]}}}}]
        }
        voters_ref = db.collection('events').document(event_id).collection('voters').stream()
        voters = [v.to_dict() for v in voters_ref]
        voted = sum(1 for v in voters if v.get('has_voted'))
        not_voted = len(voters) - voted
        turnout_chart_option = {
            "animation": False,
            "tooltip": {"trigger": "item", "backgroundColor": "rgba(255, 255, 255, 0.8)", "textStyle": {"color": "#1f2937"}},
            "legend": {"top": "bottom", "left": "center", "textStyle": {"color": "#fff"}},
            "series": [{"name": "Voter Turnout", "type": "pie", "radius": ["40%", "70%"], "avoidLabelOverlap": False, "itemStyle": {"borderRadius": 10, "borderColor": "rgba(0, 0, 0, 0.1)", "borderWidth": 2}, "label": {"show": False}, "emphasis": {"label": {"show": True, "fontSize": "14", "fontWeight": "bold", "color": "#fff"}}, "labelLine": {"show": False}, "data": [{"value": voted, "name": "Voted", "itemStyle": {"color": "rgba(87, 181, 231, 1)"}}, {"value": not_voted, "name": "Not Voted", "itemStyle": {"color": "rgba(252, 141, 98, 1)"}}]}]
        }
        all_chart_data[event_id] = {
            'votes_chart_option': votes_chart_option,
            'turnout_chart_option': turnout_chart_option
        }

    return render_template(
        'admin/dashboard.html',
        admin_name=admin_name,
        admin_email=admin_email,
        admin_initials=admin_initials,
        admin_first_name=admin_first_name,
        today_date=today_date,
        notifications=notifications,
        total_voters=total_voters,
        total_voters_growth=total_voters_growth,
        approved_voters=approved_voters,
        approved_voters_growth=approved_voters_growth,
        pending_approvals=pending_approvals,
        pending_approvals_growth=pending_approvals_growth,
        events_created=events_created,
        events_created_growth=events_created_growth,
        voter_turnout=voter_turnout,
        voter_turnout_growth=voter_turnout_growth,
        chart_events=chart_events,
        votes_chart_option=votes_chart_option,
        turnout_chart_option=turnout_chart_option,
        action_cards=action_cards,
        audit_logs=audit_logs,
        audit_logs_total=audit_logs_total,
        audit_logs_pages=audit_logs_pages,
        audit_log_events=audit_log_events,
        result_events=result_events,
        all_chart_data=all_chart_data
    )

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
    user_id = session['user_id']
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'newest')
    per_page = 10  # Number of events per page
    # Fetch all events created by this admin
    events_query = db.collection('events').where('admin_id', '==', user_id).stream()
    events = []
    for event in events_query:
        event_data = event.to_dict()
        event_id = event.id
        # Get approved voters count
        voters_ref = db.collection('events').document(event_id).collection('voters').where('approved', '==', True)
        approved_voters = list(voters_ref.stream())
        event_data['event_id'] = event_id
        event_data['approved_voter_count'] = len(approved_voters)
        events.append(event_data)
    # Sort events
    if sort == 'newest':
        events.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    elif sort == 'oldest':
        events.sort(key=lambda x: x.get('created_at', ''))
    elif sort == 'name-asc':
        events.sort(key=lambda x: x.get('event_name', ''))
    elif sort == 'name-desc':
        events.sort(key=lambda x: x.get('event_name', ''), reverse=True)
    # Paginate events
    total_events = len(events)
    total_pages = (total_events + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_events = events[start_idx:end_idx]
    return render_template('admin/manage-events.html', events=paginated_events, active_page='manage_events', page=page, total_pages=total_pages, sort=sort)

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

@admin_bp.route('/event/<event_id>/audit-logs')
def event_audit_logs(event_id):
    print(f'Accessing audit logs for event_id: {event_id}', file=sys.stderr)
    if not session.get('user_id'):
        print('No user_id in session', file=sys.stderr)
        return redirect(url_for('login_page'))
    try:
        event_doc = db.collection('events').document(event_id).get()
        print(f'event_doc.exists: {event_doc.exists}', file=sys.stderr)
        if not event_doc.exists:
            print('Event does not exist', file=sys.stderr)
            flash('Event not found.', 'error')
            return redirect(url_for('admin.dashboard'))
        event_name = event_doc.to_dict().get('event_name', 'Unknown Event')
        logs_ref = db.collection('events').document(event_id).collection('audit_logs').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
        audit_logs = []
        for log in logs_ref:
            log_data = log.to_dict()
            user_id = log_data.get('user_id')
            user_info = {}
            if user_id:
                user_doc = db.collection('users').document(user_id).get()
                if user_doc.exists:
                    user_info = {
                        'name': user_doc.to_dict().get('name'),
                        'email': user_doc.to_dict().get('email'),
                        'voter_id': user_doc.to_dict().get('voter_id')
                    }
            log_data['user_info'] = user_info
            audit_logs.append(log_data)
        print(f'Fetched {len(audit_logs)} audit logs', file=sys.stderr)
        return render_template('admin/audit-logs.html', logs=audit_logs, event_id=event_id, event_name=event_name, now=datetime.now)
    except Exception as e:
        print(f'Exception in event_audit_logs: {e}', file=sys.stderr)
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/approve-voter/<voter_id>', methods=['POST'])
def approve_voter(voter_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get voter data
        voter_ref = db.collection('users').document(voter_id)
        voter_doc = voter_ref.get()
        if not voter_doc.exists:
            flash('Voter not found', 'error')
            return redirect(url_for('admin.pending_voters'))
        voter_data = voter_doc.to_dict()
        voter_name = voter_data.get('name', 'Unknown')
        # Update voter status to approved
        voter_ref.update({'approved': True})
        flash(f'{voter_name}, {voter_id} has been approved', 'success')
    except Exception as e:
        flash(f'Error approving voter: {str(e)}', 'error')
    return redirect(url_for('admin.pending_voters'))

@admin_bp.route('/reject-voter/<voter_id>', methods=['POST'])
def reject_voter(voter_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get voter data
        voter_ref = db.collection('users').document(voter_id)
        voter_doc = voter_ref.get()
        if not voter_doc.exists:
            flash('Voter not found', 'error')
            return redirect(url_for('admin.pending_voters'))
        voter_data = voter_doc.to_dict()
        voter_name = voter_data.get('name', 'Unknown')
        # Delete voter
        voter_ref.delete()
        flash(f'{voter_name}, {voter_id} has been rejected', 'success')
    except Exception as e:
        flash(f'Error rejecting voter: {str(e)}', 'error')
    return redirect(url_for('admin.pending_voters'))

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
        flash('Not authenticated', 'error')
        return redirect(url_for('admin.event_pending_voters', event_id=event_id))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        flash('Not authorized', 'error')
        return redirect(url_for('admin.event_pending_voters', event_id=event_id))
    try:
        # Get voter data
        voter_ref = db.collection('events').document(event_id).collection('voters').document(voter_id)
        voter_data = voter_ref.get().to_dict()
        if not voter_data:
            flash('Voter not found', 'error')
            return redirect(url_for('admin.event_pending_voters', event_id=event_id))
        # Check for valid photo_url
        photo_url = voter_data.get('photo_url')
        if not photo_url or not photo_url.startswith('http'):
            flash('Voter photo is missing or invalid.', 'error')
            return redirect(url_for('admin.event_pending_voters', event_id=event_id))
        # Approve voter (no embedding generation)
        voter_data.update({
            'status': 'approved',
            'approved': True,
            'approved_at': datetime.now(),
            'approved_by': session['user_id']
        })
        voter_ref.set(voter_data)
        flash('Voter approved successfully', 'success')
        return redirect(url_for('admin.event_pending_voters', event_id=event_id))
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin.event_pending_voters', event_id=event_id))

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
        pending_voters = []
        for voter in voters_ref:
            voter_dict = voter.to_dict()
            voter_dict['user_id'] = voter.id
            pending_voters.append(voter_dict)
        return render_template('admin/pending-voters.html', voters=pending_voters, event_id=event_id)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin.dashboard'))

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
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/admin/event/<event_id>/results')
def event_results_firestore(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get event details
        event_ref = db.collection('events').document(event_id)
        event_doc = event_ref.get()
        if not event_doc.exists:
            return redirect(url_for('admin.dashboard'))
        event_data = event_doc.to_dict()
        candidates = event_data.get('candidates', [])

        # Parse start_time and end_time as datetime if they are strings
        for time_key in ['start_time', 'end_time']:
            if event_data.get(time_key) and isinstance(event_data[time_key], str):
                try:
                    event_data[time_key] = parser.parse(event_data[time_key])
                except Exception:
                    pass

        # Get results for this specific event
        results_ref = event_ref.collection('results').stream()
        results = {doc.id: doc.to_dict() for doc in results_ref}

        # Prepare candidate results
        candidate_results = []
        total_votes = 0
        for cand in candidates:
            cand_id = cand.get('candidate_id')
            votes = results.get(cand_id, {}).get('votes', 0)
            total_votes += votes
            candidate_results.append({
                'candidate_id': cand_id,
                'name': cand.get('name'),
                'party': cand.get('party'),
                'slogan': cand.get('slogan'),
                'photo_url': cand.get('photo_url'),
                'votes': votes
            })
        # Calculate percentages and find winner(s)
        max_votes = max([c['votes'] for c in candidate_results], default=0)
        for c in candidate_results:
            c['percentage'] = round((c['votes'] / total_votes * 100), 1) if total_votes > 0 else 0.0
            c['is_winner'] = c['votes'] == max_votes and max_votes > 0
        winners = [c for c in candidate_results if c['is_winner']]

        # Get approved voters and turnout
        voters_ref = event_ref.collection('voters').stream()
        total_voters = 0
        votes_cast = 0
        for v in voters_ref:
            vdata = v.to_dict()
            if vdata.get('approved'):
                total_voters += 1
                if vdata.get('has_voted'):
                    votes_cast += 1
        turnout = round((votes_cast / total_voters * 100), 1) if total_voters > 0 else 0.0

        return render_template('admin/results.html',
                              event=event_data,
                              candidate_results=candidate_results,
                              total_votes=total_votes,
                              winners=winners,
                              total_voters=total_voters,
                              votes_cast=votes_cast,
                              turnout=turnout)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin.dashboard'))

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
        return redirect(url_for('admin.event_pending_voters', event_id=event_id))
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('admin.event_pending_voters', event_id=event_id))

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

@admin_bp.route('/event/<event_id>/edit', methods=['POST'])
def edit_event(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    try:
        # Get form data
        event_description = request.form.get('event_description')
        event_slogan = request.form.get('event_slogan')
        if not event_description or not event_slogan:
            flash('Missing required fields', 'error')
            return redirect(url_for('admin.manage_events'))
        # Update event document
        event_ref = db.collection('events').document(event_id)
        event_ref.update({
            'event_description': event_description
        })
        # Update first candidate's slogan
        event_data = event_ref.get().to_dict()
        if event_data and 'candidates' in event_data and event_data['candidates']:
            candidates = event_data['candidates']
            candidates[0]['slogan'] = event_slogan
            event_ref.update({'candidates': candidates})
        flash('Event updated successfully', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('admin.manage_events'))

@admin_bp.route('/api/dashboard-data')
def api_dashboard_data():
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    # 1. Get last 5 events for this admin
    events_query = db.collection('events').where('admin_id', '==', user_id).order_by('created_at', direction=firestore.Query.DESCENDING).limit(5).stream()
    events = []
    for event_doc in events_query:
        event = event_doc.to_dict()
        event['event_id'] = event_doc.id
        events.append(event)
    # 2. Stat cards (overall or for most recent event)
    total_voters = 0
    approved_voters = 0
    pending_approvals = 0
    voter_turnout = 0.0
    if events:
        selected_event = events[0]
        event_id = selected_event['event_id']
        voters_ref = db.collection('events').document(event_id).collection('voters').stream()
        voters = [v.to_dict() for v in voters_ref]
        total_voters = len(voters)
        approved_voters = sum(1 for v in voters if v.get('approved'))
        pending_approvals = sum(1 for v in voters if not v.get('approved'))
        votes_cast = sum(1 for v in voters if v.get('has_voted'))
        voter_turnout = round((votes_cast / approved_voters * 100), 1) if approved_voters > 0 else 0.0
    # 3. Chart data for each event
    chart_data = []
    for event in events:
        event_id = event['event_id']
        candidates = event.get('candidates', [])
        # Use ballots subcollection for vote counts
        ballots_ref = db.collection('events').document(event_id).collection('ballots').stream()
        ballots = [b.to_dict() for b in ballots_ref]
        votes_per_candidate = []
        for cand in candidates:
            cand_id = cand.get('candidate_id')
            cand_name = cand.get('name')
            vote_count = sum(1 for b in ballots if b.get('candidate_id') == cand_id)
            votes_per_candidate.append({'name': cand_name, 'votes': vote_count})
        # Voter turnout for this event
        voters_ref = db.collection('events').document(event_id).collection('voters').stream()
        voters = [v.to_dict() for v in voters_ref]
        approved = sum(1 for v in voters if v.get('approved'))
        voted = sum(1 for v in voters if v.get('has_voted'))
        turnout = round((voted / approved * 100), 1) if approved > 0 else 0.0
        chart_data.append({
            'event_id': event_id,
            'event_name': event.get('event_name'),
            'votes_per_candidate': votes_per_candidate,
            'turnout': turnout,
            'voted': voted,
            'not_voted': approved - voted,
        })
    # 4. Recent audit logs from all events
    audit_logs = []
    for event in events:
        event_id = event['event_id']
        logs_ref = db.collection('events').document(event_id).collection('audit_logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(5).stream()
        for log in logs_ref:
            log_data = log.to_dict()
            log_data['event_id'] = event_id
            log_data['event_name'] = event.get('event_name')
            audit_logs.append(log_data)
    # Sort all logs by timestamp (latest first)
    audit_logs.sort(key=lambda x: x.get('timestamp'), reverse=True)
    audit_logs = audit_logs[:20]  # Limit to 20 logs
    return jsonify({
        'stat_cards': {
            'total_voters': total_voters,
            'approved_voters': approved_voters,
            'pending_approvals': pending_approvals,
            'events_created': len(events),
            'voter_turnout': voter_turnout
        },
        'events': events,
        'chart_data': chart_data,
        'audit_logs': audit_logs
    })

# --- DEMO ROUTE FOR STATIC DESIGN WITH DYNAMIC DATA ---
@admin_bp.route('/dashboard-demo')
def dashboard_demo():
    # Mock data for demo
    from datetime import datetime
    admin_name = "Jonathan Davis"
    admin_email = "jonathan@university.edu"
    admin_initials = "JD"
    admin_first_name = "Jonathan"
    today_date = datetime.now().strftime("%B %d, %Y")
    notifications = [
        {"title": "New voter registration", "time": "5 minutes ago", "icon": "ri-user-add-line", "icon_color": "text-blue-400", "bg": "bg-blue-500 bg-opacity-20"},
        {"title": "Event 'Student Council' ending soon", "time": "1 hour ago", "icon": "ri-alarm-warning-line", "icon_color": "text-yellow-400", "bg": "bg-yellow-500 bg-opacity-20"},
        {"title": "Failed login attempt detected", "time": "2 hours ago", "icon": "ri-error-warning-line", "icon_color": "text-red-400", "bg": "bg-red-500 bg-opacity-20"},
    ]
    total_voters = 8742
    total_voters_growth = 12.5
    approved_voters = 7519
    approved_voters_growth = 8.3
    pending_approvals = 124
    pending_approvals_growth = 23.8
    events_created = 24
    events_created_growth = "4 events"
    voter_turnout = 85.7
    voter_turnout_growth = 3.2
    chart_events = [
        {"value": "student-council", "label": "Student Council Election"},
        {"value": "faculty-senate", "label": "Faculty Senate Election"},
        {"value": "department-chair", "label": "Department Chair Selection"},
    ]
    votes_chart_option = {
        "animation": False,
        "tooltip": {"trigger": "axis", "backgroundColor": "rgba(255, 255, 255, 0.8)", "textStyle": {"color": "#1f2937"}},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "category", "data": ["Sarah Johnson", "Michael Lee", "Emily Davis", "David Wilson", "Jessica Brown", "James Miller", "Rachel Taylor", "Thomas Anderson"], "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}}, "axisLabel": {"color": "rgba(255, 255, 255, 0.7)", "rotate": 45}},
        "yAxis": {"type": "value", "axisLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.2)"}}, "splitLine": {"lineStyle": {"color": "rgba(255, 255, 255, 0.1)"}}, "axisLabel": {"color": "rgba(255, 255, 255, 0.7)"}},
        "series": [{"name": "Votes", "type": "bar", "data": [648, 521, 489, 432, 387, 345, 302, 278], "itemStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "rgba(87, 181, 231, 0.8)"}, {"offset": 1, "color": "rgba(87, 181, 231, 0.3)"}]}, "borderRadius": [5, 5, 0, 0]}, "emphasis": {"itemStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [{"offset": 0, "color": "rgba(87, 181, 231, 1)"}, {"offset": 1, "color": "rgba(87, 181, 231, 0.5)"}]}}}}]
    }
    turnout_chart_option = {
        "animation": False,
        "tooltip": {"trigger": "item", "backgroundColor": "rgba(255, 255, 255, 0.8)", "textStyle": {"color": "#1f2937"}},
        "legend": {"top": "bottom", "left": "center", "textStyle": {"color": "#fff"}},
        "series": [{"name": "Voter Turnout", "type": "pie", "radius": ["40%", "70%"], "avoidLabelOverlap": False, "itemStyle": {"borderRadius": 10, "borderColor": "rgba(0, 0, 0, 0.1)", "borderWidth": 2}, "label": {"show": False}, "emphasis": {"label": {"show": True, "fontSize": "14", "fontWeight": "bold", "color": "#fff"}}, "labelLine": {"show": False}, "data": [{"value": 2217, "name": "Voted", "itemStyle": {"color": "rgba(87, 181, 231, 1)"}}, {"value": 1024, "name": "Not Voted", "itemStyle": {"color": "rgba(252, 141, 98, 1)"}}]}]
    }
    action_cards = [
        {"bg": "bg-green-500 bg-opacity-20", "icon": "ri-add-circle-line", "icon_color": "text-green-500", "title": "Create New Voting Event", "description": "Set up a new election or poll", "button_bg": "bg-green-500 bg-opacity-20", "button_text": "text-green-400", "button_label": "Create Event"},
        {"bg": "bg-blue-500 bg-opacity-20", "icon": "ri-user-follow-line", "icon_color": "text-blue-500", "title": "Pending Voter Approvals", "description": "124 voters awaiting approval", "button_bg": "bg-blue-500 bg-opacity-20", "button_text": "text-blue-400", "button_label": "Review"},
        {"bg": "bg-purple-500 bg-opacity-20", "icon": "ri-team-line", "icon_color": "text-purple-500", "title": "View Registered Voters", "description": "Manage all voter accounts", "button_bg": "bg-purple-500 bg-opacity-20", "button_text": "text-purple-400", "button_label": "View List"},
        {"bg": "bg-yellow-500 bg-opacity-20", "icon": "ri-bar-chart-2-line", "icon_color": "text-yellow-500", "title": "View and Publish Results", "description": "Manage election results", "button_bg": "bg-yellow-500 bg-opacity-20", "button_text": "text-yellow-400", "button_label": "View Results"},
        {"bg": "bg-red-500 bg-opacity-20", "icon": "ri-shield-check-line", "icon_color": "text-red-500", "title": "Access Audit Logs", "description": "Review system activity", "button_bg": "bg-red-500 bg-opacity-20", "button_text": "text-red-400", "button_label": "View Logs"},
        {"bg": "bg-indigo-500 bg-opacity-20", "icon": "ri-notification-4-line", "icon_color": "text-indigo-500", "title": "Send Reminder to Non-voters", "description": "1,223 voters haven't voted", "button_bg": "bg-indigo-500 bg-opacity-20", "button_text": "text-indigo-400", "button_label": "Send Reminder"},
    ]
    audit_logs = [
        {"voter_id": "STU-2025-1458", "full_name": "Emily Richardson", "email": "emily.r@university.edu", "status_bg": "bg-green-500 bg-opacity-20", "status_text": "text-green-400", "vote_status": "Vote Cast", "time_of_vote": "Jun 8, 2025 09:45 AM", "event_name": "Student Council Election", "action_bg": "bg-blue-500 bg-opacity-20", "action_icon": "ri-eye-line", "action_icon_color": "text-blue-400"},
        {"voter_id": "STU-2025-2367", "full_name": "Michael Thompson", "email": "m.thompson@university.edu", "status_bg": "bg-green-500 bg-opacity-20", "status_text": "text-green-400", "vote_status": "Vote Cast", "time_of_vote": "Jun 8, 2025 10:12 AM", "event_name": "Student Council Election", "action_bg": "bg-blue-500 bg-opacity-20", "action_icon": "ri-eye-line", "action_icon_color": "text-blue-400"},
        {"voter_id": "FAC-2025-0142", "full_name": "Dr. Sarah Williams", "email": "s.williams@university.edu", "status_bg": "bg-green-500 bg-opacity-20", "status_text": "text-green-400", "vote_status": "Vote Cast", "time_of_vote": "Jun 8, 2025 08:30 AM", "event_name": "Faculty Senate Election", "action_bg": "bg-blue-500 bg-opacity-20", "action_icon": "ri-eye-line", "action_icon_color": "text-blue-400"},
        {"voter_id": "STU-2025-3891", "full_name": "James Rodriguez", "email": "j.rodriguez@university.edu", "status_bg": "bg-red-500 bg-opacity-20", "status_text": "text-red-400", "vote_status": "Not Voted", "time_of_vote": "-", "event_name": "Student Council Election", "action_bg": "bg-indigo-500 bg-opacity-20", "action_icon": "ri-notification-3-line", "action_icon_color": "text-indigo-400"},
        {"voter_id": "STU-2025-4102", "full_name": "Sophia Chen", "email": "s.chen@university.edu", "status_bg": "bg-red-500 bg-opacity-20", "status_text": "text-red-400", "vote_status": "Not Voted", "time_of_vote": "-", "event_name": "Student Council Election", "action_bg": "bg-indigo-500 bg-opacity-20", "action_icon": "ri-notification-3-line", "action_icon_color": "text-indigo-400"},
    ]
    audit_logs_total = 1245
    audit_logs_pages = [
        {"number": 1, "active": True, "icon": None},
        {"number": 2, "active": False, "icon": None},
        {"number": 3, "active": False, "icon": None},
        {"number": None, "active": False, "icon": "ri-arrow-right-s-line"},
    ]
    audit_log_events = [
        {"value": "student-council", "label": "Student Council Election"},
        {"value": "faculty-senate", "label": "Faculty Senate Election"},
    ]
    result_events = [
        {"name": "Student Council Election", "status_bg": "bg-yellow-500 bg-opacity-20", "status_text": "text-yellow-400", "status": "Pending", "voting_label": "Voting ends in:", "voting_value": "3 days, 14 hours", "turnout_label": "Current turnout:", "turnout_value": "68.4% (2,217 of 3,241)", "button_bg": "bg-yellow-500 bg-opacity-20", "button_text": "text-yellow-400", "button_icon": "ri-eye-line", "button_label": "Preview Results"},
        {"name": "Faculty Senate Election", "status_bg": "bg-blue-500 bg-opacity-20", "status_text": "text-blue-400", "status": "Completed", "voting_label": "Voting ended:", "voting_value": "June 1, 2025", "turnout_label": "Final turnout:", "turnout_value": "92.3% (395 of 428)", "button_bg": "bg-primary bg-opacity-20", "button_text": "text-primary", "button_icon": "ri-send-plane-line", "button_label": "Publish Results"},
    ]
    return render_template(
        'admin/dashboard.html',
        admin_name=admin_name,
        admin_email=admin_email,
        admin_initials=admin_initials,
        admin_first_name=admin_first_name,
        today_date=today_date,
        notifications=notifications,
        total_voters=total_voters,
        total_voters_growth=total_voters_growth,
        approved_voters=approved_voters,
        approved_voters_growth=approved_voters_growth,
        pending_approvals=pending_approvals,
        pending_approvals_growth=pending_approvals_growth,
        events_created=events_created,
        events_created_growth=events_created_growth,
        voter_turnout=voter_turnout,
        voter_turnout_growth=voter_turnout_growth,
        chart_events=chart_events,
        votes_chart_option=votes_chart_option,
        turnout_chart_option=turnout_chart_option,
        action_cards=action_cards,
        audit_logs=audit_logs,
        audit_logs_total=audit_logs_total,
        audit_logs_pages=audit_logs_pages,
        audit_log_events=audit_log_events,
        result_events=result_events
    )

# --- JINJA2 FILTER FOR NUMBER FORMATTING ---
def number_format(value):
    return "{:,}".format(value)

def init_app(app):
    app.jinja_env.filters['number_format'] = number_format 

@admin_bp.route('/settings', methods=['GET', 'POST'])
def admin_settings():
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    admin_ref = db.collection('users').document(session['user_id'])
    if request.method == 'POST':
        first = request.form.get('firstName', '').strip()
        last = request.form.get('lastName', '').strip()
        mobile = request.form.get('phone', '').strip()
        bio = request.form.get('bio', '').strip()
        name = f"{first} {last}".strip()
        try:
            admin_ref.update({
                'name': name,
                'mobile': mobile,
                'bio': bio
            })
            flash('Profile updated successfully!', 'success')
            user_data['name'] = name
            user_data['mobile'] = mobile
            user_data['bio'] = bio
        except Exception as e:
            flash('Failed to update profile. Please try again.', 'error')
    # Compose admin dict for template
    admin = {
        'name': user_data.get('name', ''),
        'email': user_data.get('email', ''),
        'mobile': user_data.get('mobile', ''),
        'bio': user_data.get('bio', ''),
        'photo_url': user_data.get('photo_url', ''),
        'password_last_changed': user_data.get('password_last_changed', 'N/A'),
        'two_factor_enabled': user_data.get('two_factor_enabled', False)
    }
    return render_template('admin/settings.html', admin=admin)

@admin_bp.route('/event/<event_id>/publish-results', methods=['POST'])
def publish_results(event_id):
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user_data = get_user_data(session['user_id'])
    if not user_data or user_data.get('role') != 'admin':
        return redirect(url_for('login_page'))
    try:
        db.collection('events').document(event_id).update({'results_published': True})
        flash('Results published successfully!', 'success')
    except Exception as e:
        flash(f'Failed to publish results: {str(e)}', 'error')
    return redirect(url_for('admin.dashboard')) 