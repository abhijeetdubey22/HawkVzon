import cv2
import face_recognition
import numpy as np
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
faces_folder = os.path.join(BASE_DIR, "faces")
os.makedirs(faces_folder, exist_ok=True)

def rebuild_database():
    encoding_list, name_list, age_list = [], [], []
    for file in sorted(os.listdir(faces_folder)):
        if file.endswith(".npy"):
            try:
                data = np.load(os.path.join(faces_folder, file), allow_pickle=True)
                encoding_list.append(data)
                parts = file[:-4].split("_")
                name_list.append(" ".join(parts[:-1]) if len(parts) >= 2 else parts[0])
                age_list.append(parts[-1] if len(parts) >= 2 else "Unknown")
            except Exception:
                pass
    np.save(os.path.join(BASE_DIR, "known_face_encodings.npy"), encoding_list)
    np.save(os.path.join(BASE_DIR, "known_face_names.npy"), name_list)
    np.save(os.path.join(BASE_DIR, "known_face_ages.npy"), age_list)
    print(f"[INFO] Face database updated. Total enrolled: {len(name_list)}")

# Ask for details
name = input("Enter your name: ").strip()
if not name:
    print("[ERROR] Name cannot be empty.")
    sys.exit(1)

age = input("Enter your age: ").strip() or "Unknown"

video_capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if not video_capture.isOpened():
    video_capture = cv2.VideoCapture(0)

print("[INFO] Look at the camera — press 'C' to capture your face, 'Q' to quit.")

captured = False

while True:
    ret, frame = video_capture.read()
    if not ret:
        print("[WARNING] Camera frame not received.")
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame)

    for (top, right, bottom, left) in face_locations:
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.putText(frame, f"{name} ({age})", (left, max(20, top - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    cv2.imshow("Register Face", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('c') or key == ord('C'):
        if face_locations:
            face_encoding = face_recognition.face_encodings(rgb_frame, face_locations)[0]
            save_path = os.path.join(faces_folder, f"{name}_{age}.npy")
            np.save(save_path, face_encoding)
            print(f"[SUCCESS] Face registered for '{name}' (Age: {age})")
            rebuild_database()
            captured = True
            break
        else:
            print("[WARNING] No face detected. Look directly at camera and press 'C'.")
    elif key == ord('q') or key == ord('Q'):
        break

video_capture.release()
cv2.destroyAllWindows()

if not captured:
    print("[INFO] Face registration cancelled.")
