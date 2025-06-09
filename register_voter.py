import cv2
import numpy as np
from face_embedder import generate_embedding
from firebase_config import db, bucket
import os
import tempfile
from datetime import datetime

def register_voter_face(user_id, name):
    """
    Register a voter by capturing their face and storing the photo and embedding.
    Returns True if successful, False otherwise.
    """
    cap = None
    try:
        # Initialize camera
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Could not open camera")
            return False

        # Create a window for the camera feed
        cv2.namedWindow("Face Registration", cv2.WINDOW_NORMAL)

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Could not read frame")
                return False

            # Display the frame
            cv2.imshow("Face Registration", frame)

            # Wait for 'c' key to capture
            key = cv2.waitKey(1) & 0xFF
            if key == ord('c'):
                # Generate face embedding
                embedding = generate_embedding(frame)
                if embedding is None:
                    print("Error: No face detected in the frame")
                    continue

                # Save the photo to a temporary file
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                    temp_path = temp_file.name
                    cv2.imwrite(temp_path, frame)

                # Upload photo to Firebase Storage
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                blob = bucket.blob(f'voter_photos/{user_id}_{timestamp}.jpg')
                blob.upload_from_filename(temp_path)
                photo_url = blob.public_url

                # Store user data in Firestore
                user_data = {
                    'name': name,
                    'photo_url': photo_url,
                    'embedding': embedding.tolist(),
                    'registration_date': datetime.now(),
                    'approved': False
                }
                db.collection('users').document(user_id).set(user_data)

                # Clean up temporary file
                os.unlink(temp_path)
                
                print("Registration successful!")
                return True

            # Press 'q' to quit
            elif key == ord('q'):
                print("Registration cancelled")
                return False

    except Exception as e:
        print(f"Error during registration: {str(e)}")
        return False

    finally:
        if cap is not None:
            cap.release()
            cv2.destroyAllWindows()

# Initialize Firebase if running directly
if __name__ == "__main__":
    # Get voter name and ID
    voter_id = input("Enter unique voter ID: ")
    name = input("Enter voter's full name: ")
    register_voter_face(voter_id, name) 