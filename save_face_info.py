import cv2
import face_recognition
import pickle
import os
import numpy as np
import time

# Create folder
if not os.path.exists("face_data"):
    os.makedirs("face_data")

# Load or initialize data
encodings_path = os.path.join("face_data", "encodings.pkl")
if os.path.exists(encodings_path):
    with open(encodings_path, "rb") as f:
        known_data = pickle.load(f)
else:
    known_data = []

# Start webcam
video_capture = cv2.VideoCapture(0)
if not video_capture.isOpened():
    print("❌ ERROR: Webcam not accessible.")
    exit()

num_people = int(input("How many people to register? "))

for _ in range(num_people):
    uid = input("Enter unique ID: ")
    name = input("Name: ")
    age = input("Age: ")
    gender = input("Gender (M/F/O): ")

    print(f"📸 Please look at the camera. Capturing face for {name}...")

    while True:
        ret, frame = video_capture.read()

        if not ret or frame is None:
            print("❌ Frame not captured. Trying again...")
            continue

        print(f"✅ Captured Frame: shape={frame.shape}, dtype={frame.dtype}")

        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception as e:
            print(f"❌ cvtColor failed: {e}")
            continue

        if rgb_frame is None:
            print("❌ RGB frame is None after conversion.")
            continue
        if rgb_frame.dtype != np.uint8:
            print(f"❌ Invalid dtype: {rgb_frame.dtype}")
            continue
        if rgb_frame.ndim != 3 or rgb_frame.shape[2] != 3:
            print(f"❌ Invalid shape: {rgb_frame.shape}")
            continue

        try:
            face_locations = face_recognition.face_locations(rgb_frame)
        except Exception as e:
            print(f"❌ face_locations error: {e}")
            continue

        if not face_locations:
            print("⚠️ No face detected. Adjust position.")
            time.sleep(1)
            continue

        encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        if encodings:
            face_encoding = encodings[0]
            user_data = {
                "id": uid,
                "name": name,
                "age": age,
                "gender": gender,
                "encoding": face_encoding
            }
            known_data.append(user_data)
            print(f"✅ Face for {name} saved.")
            break
        else:
            print("⚠️ Face not encoded. Try again.")
            time.sleep(1)

# Save to file
with open(encodings_path, "wb") as f:
    pickle.dump(known_data, f)

video_capture.release()
cv2.destroyAllWindows()

print("✅ All face data saved successfully!")
