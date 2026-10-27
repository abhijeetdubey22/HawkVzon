import cv2
import face_recognition
import numpy as np
from keras.models import load_model
from keras.preprocessing.image import img_to_array
import os

# Load face data
known_faces = np.load("known_faces.npy")
known_names = np.load("known_names.npy", allow_pickle=True)
known_ages = np.load("known_ages.npy", allow_pickle=True)

# Load emotion model
emotion_model = load_model("emotion_model.hdf5")
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# Initialize webcam
cap = cv2.VideoCapture(0)

print("🔍 Press 'q' to quit recognition.")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Resize for faster processing
    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    face_locations = face_recognition.face_locations(rgb_small_frame)
    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
        # Face recognition
        matches = face_recognition.compare_faces(known_faces, face_encoding)
        face_distances = face_recognition.face_distance(known_faces, face_encoding)

        name = "Unknown"
        age = "-"
        confidence = 0

        if len(face_distances) > 0:
            best_match_index = np.argmin(face_distances)
            confidence = 1 - face_distances[best_match_index]  # Match accuracy

            if matches[best_match_index]:
                name = known_names[best_match_index]
                age = known_ages[best_match_index]

        # Emotion detection
        face_img = frame[top*4:bottom*4, left*4:right*4]
        if face_img.size > 0:
            gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, (48, 48))
            roi = resized.astype("float") / 255.0
            roi = img_to_array(roi)
            roi = np.expand_dims(roi, axis=0)

            prediction = emotion_model.predict(roi)[0]
            emotion = emotion_labels[np.argmax(prediction)]
            emotion_conf = np.max(prediction) * 100
        else:
            emotion = "N/A"
            emotion_conf = 0

        # Scale back to original size
        top *= 4
        right *= 4
        bottom *= 4
        left *= 4

        # Draw rectangle
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

        # Text info
        label = f"{name}, Age: {age}, Match: {confidence*100:.2f}%"
        emotion_text = f"Emotion: {emotion} ({emotion_conf:.1f}%)"

        cv2.putText(frame, label, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, emotion_text, (left, bottom + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 255, 255), 2)

    # Display result
    cv2.imshow("Face Recognition + Emotion Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
