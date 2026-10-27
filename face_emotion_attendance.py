import cv2
import face_recognition
import numpy as np
from keras.models import load_model
import pyttsx3
import csv
from datetime import datetime

# Load known data
known_face_encodings = np.load("known_face_encodings.npy", allow_pickle=True)
known_face_names = np.load("known_face_names.npy", allow_pickle=True)
known_face_ages = np.load("known_face_ages.npy", allow_pickle=True)

# Load emotion model
emotion_model = load_model("emotion_model.hdf5")
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# Text-to-speech (optional)
engine = pyttsx3.init()

# Attendance Logger
def log_attendance(name, age, emotion, match_percent):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("attendance_log.csv", mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([timestamp, name, age, match_percent, emotion])

# Open webcam
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("❌ Could not open webcam.")
    exit()

print("🔍 Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ Failed to capture frame.")
        break

    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    face_locations = face_recognition.face_locations(rgb_small_frame)
    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
        matches = face_recognition.compare_faces(known_face_encodings, face_encoding)
        face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_match_index = np.argmin(face_distances)

        if matches[best_match_index]:
            name = known_face_names[best_match_index]
            age = known_face_ages[best_match_index]
            match_percent = (1 - face_distances[best_match_index]) * 100

            # Emotion detection
            top *= 4; right *= 4; bottom *= 4; left *= 4
            face_img = frame[top:bottom, left:right]
            gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
            roi = cv2.resize(gray, (48, 48))
            roi = roi.astype("float32") / 255.0
            roi = np.expand_dims(roi, axis=0)
            roi = np.expand_dims(roi, axis=-1)

            prediction = emotion_model.predict(roi, verbose=0)
            emotion_idx = np.argmax(prediction[0])
            confidence = prediction[0][emotion_idx]
            emotion = emotion_labels[emotion_idx]

            label = f"{name}, Age: {age}, {emotion} ({confidence*100:.1f}%), Match: {match_percent:.1f}%"
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
            cv2.putText(frame, label, (left, top - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            # Log attendance
            log_attendance(name, age, emotion, f"{match_percent:.1f}%")

            # Optional TTS
            # engine.say(f"{name} is {emotion}")
            # engine.runAndWait()
        else:
            print("🚫 Unknown face")

    cv2.imshow("Face + Emotion + Attendance", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
