from keras_facenet import FaceNet
import numpy as np
import cv2
from mtcnn import MTCNN

embedder = FaceNet()
detector = MTCNN()

def extract_face(img, required_size=(160, 160)):
    results = detector.detect_faces(img)
    if len(results) == 0:
        return None
    x1, y1, width, height = results[0]['box']
    x1, y1 = abs(x1), abs(y1)
    face = img[y1:y1+height, x1:x1+width]
    face = cv2.resize(face, required_size)
    return face

def get_embedding(face_pixels):
    face_pixels = np.asarray(face_pixels)
    embeddings = embedder.embeddings([face_pixels])
    return embeddings[0]

def generate_embedding(img):
    """
    Generate face embedding from an image.
    Returns None if no face is detected.
    """
    # Extract face
    face = extract_face(img)
    if face is None:
        return None
    
    # Generate embedding
    embedding = get_embedding(face)
    return embedding
