import cv2
import numpy as np
from face_embedder import extract_face, get_embedding
from firebase_config import db

def verify_voter_face():
    cap = None
    try:
        # Load known embeddings from Firestore
        voters_ref = db.collection('voters')
        docs = voters_ref.stream()

        known_faces = []
        voter_ids = []

        for doc in docs:
            data = doc.to_dict()
            if 'embedding' in data:
                known_faces.append(np.array(data['embedding']))
                voter_ids.append(doc.id)

        # Capture face from webcam
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Could not open camera")
            return None

        print("Look at the camera...")

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Could not read frame")
                break

            try:
                face = extract_face(frame)
                if face is not None:
                    embedding = get_embedding(face)

                    # Compare with known embeddings
                    min_dist = float('inf')
                    matched_voter_id = None

                    for idx, known_embedding in enumerate(known_faces):
                        dist = np.linalg.norm(embedding - known_embedding)
                        if dist < min_dist:
                            min_dist = dist
                            matched_voter_id = voter_ids[idx]
                    
                    if min_dist < 0.6:
                        print(f"\n✅ Identity verified: {matched_voter_id}")
                        return matched_voter_id
                    else:
                        print("\n❌ No match found. Identity cannot be verified.")
                        return None

                cv2.imshow("Camera", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            except Exception as e:
                print(f"Error processing frame: {str(e)}")
                break

    except Exception as e:
        print(f"Error during face verification: {str(e)}")
        return None

    finally:
        if cap is not None:
            cap.release()
            cv2.destroyAllWindows()

    return None

if __name__ == "__main__":
    verify_voter_face() 