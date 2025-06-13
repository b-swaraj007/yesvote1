from firebase_admin import auth
from firebase_config import db
from flask import session
import json

SUPERADMIN_EMAIL = 'swarajbhosle437@gmail.com'
SUPERADMIN_PASSWORD = '87654321'
SUPERADMIN_ROLE = 'superadmin'

# Ensure superadmin exists in Firebase Auth and Firestore
def ensure_superadmin():
    try:
        user = auth.get_user_by_email(SUPERADMIN_EMAIL)
    except auth.UserNotFoundError:
        user = auth.create_user(
            email=SUPERADMIN_EMAIL,
            password=SUPERADMIN_PASSWORD
        )
    # Ensure Firestore user document exists and is set as superadmin
    db.collection('users').document(user.uid).set({
        'email': SUPERADMIN_EMAIL,
        'role': SUPERADMIN_ROLE,
        'name': 'Superadmin',
        'approved': True
    }, merge=True)
    return user.uid

# Call this at app startup
# ensure_superadmin()

def create_user(email, password, role, user_data):
    try:
        # If superadmin, skip creation (already exists)
        if email == SUPERADMIN_EMAIL:
            return ensure_superadmin()
        # Create Firebase Auth user
        user = auth.create_user(
            email=email,
            password=password
        )
        # Store additional data in Firestore, including password (for testing only)
        db.collection('users').document(user.uid).set({
            'email': email,
            'role': role,
            'approved': False,
            'registration_complete': False,
            'has_voted': False,
            'password': password,  # For testing only
            **user_data
        })
        return user.uid
    except Exception as e:
        print(f"Error creating user: {str(e)}")
        return None

def verify_user(email, password):
    try:
        # If superadmin, check password and return role
        if email == SUPERADMIN_EMAIL:
            if password == SUPERADMIN_PASSWORD:
                # Get superadmin user
                user = auth.get_user_by_email(email)
                return {
                    'uid': user.uid,
                    'email': email,
                    'role': SUPERADMIN_ROLE,
                    'name': 'Superadmin'
                }
            else:
                return None
        # For other users, check Firestore
        user_doc = db.collection('users').where('email', '==', email).limit(1).get()
        if not user_doc:
            return {'error': 'not_found'}
        user_data = user_doc[0].to_dict()
        # Check password (for testing only)
        if user_data.get('password') != password:
            return None
        user = auth.get_user_by_email(email)
        return {
            'uid': user.uid,
            'email': email,
            'role': user_data.get('role', 'voter'),
            'name': user_data.get('name', '')
        }
    except auth.UserNotFoundError:
        return {'error': 'not_found'}
    except Exception as e:
        print(f"Error verifying user: {str(e)}")
        return None

def get_user_data(user_id):
    try:
        user_data = db.collection('users').document(user_id).get()
        if user_data.exists:
            return user_data.to_dict()
        return None
    except Exception as e:
        print(f"Error getting user data: {str(e)}")
        return None

def update_user_data(user_id, data):
    try:
        db.collection('users').document(user_id).update(data)
        return True
    except Exception as e:
        print(f"Error updating user data: {str(e)}")
        return False 