import firebase_admin
from firebase_admin import credentials, firestore, storage

# Initialize Firebase Admin SDK
cred = credentials.Certificate('firebase-adminsdk.json')
firebase_admin.initialize_app(cred, {
    'storageBucket': 'lets-vote-c3a70.firebasestorage.app'  # Replace with your Firebase storage bucket
})

# Get Firestore database instance
db = firestore.client()

# Get Storage bucket instance
bucket = storage.bucket() 