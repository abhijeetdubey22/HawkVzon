import face_recognition
import cv2
import pickle
import os

# Load encodings
known_encodings = []
known_ids = []

with open("encodings.pkl", "rb") as f:
    try:
        while True:
            record = pickle.load(f)
            known_encodings.append(record["encoding"])
            known_ids.append(f'{record["id"]} - {record["name"]}')
    except EOFError:
        pass

# Start webcam
cap = cv2.VideoCapture(0)

print("✅ Recognition system started. Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    # Resize and convert
    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small = small_frame[:, :, ::-1]

    # Detect faces
    face_locations = face_recognition.face_locations(rgb_small)
    face_encodings = face_recognition.face_encodings(rgb_small, face_locations)

    for encoding, location in zip(face_encodings, face_locations):
        matches = face_recognition.compare_faces(known_encodings, encoding)
        name = "Unknown"

        if True in matches:
            match_index = matches.index(True)
            name = known_ids[match_index]

        top, right, bottom, left = [v * 4 for v in location]
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.putText(frame, name, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

    cv2.imshow("Face Recognition", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
