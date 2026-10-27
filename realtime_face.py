import cv2
import face_recognition
import pickle
import numpy as np

# Load known face encodings
with open("encodings.pkl", "rb") as f:
    known_data = pickle.load(f)

known_encodings = [person["encoding"] for person in known_data]
known_names = [person["name"] for person in known_data]
known_ages = [person["age"] for person in known_data]
known_genders = [person["gender"] for person in known_data]

# Start webcam
video_capture = cv2.VideoCapture(0)

print("🎥 Starting real-time face recognition. Press 'q' to quit.")

while True:
    ret, frame = video_capture.read()
    if not ret:
        print("❌ Failed to capture frame.")
        break

    # Resize for faster processing
    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    # Detect faces
    face_locations = face_recognition.face_locations(rgb_small_frame)
    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
        matches = face_recognition.compare_faces(known_encodings, face_encoding)
        face_distances = face_recognition.face_distance(known_encodings, face_encoding)

        name = "Unknown"
        age = ""
        gender = ""

        if True in matches:
            best_match_index = np.argmin(face_distances)
            if matches[best_match_index]:
                name = known_names[best_match_index]
                age = known_ages[best_match_index]
                gender = known_genders[best_match_index]

        # Scale back up face locations since we used a smaller frame
        top *= 4
        right *= 4
        bottom *= 4
        left *= 4

        # Draw rectangle and label
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
        label = f"{name} | Age: {age} | Gender: {gender}"
        cv2.putText(frame, label, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # Show the result
    cv2.imshow("Face Recognition", frame)

    # Quit on 'q' key
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

video_capture.release()
cv2.destroyAllWindows()
