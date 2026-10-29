# face_emotion_combined.py
import cv2
import face_recognition
import numpy as np
import os
import time
from emotion_predictor import EmotionClassifier
import pyttsx3
import csv
from datetime import datetime
import threading
import queue
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Asynchronous, non-blocking TTS engine
speech_queue = queue.Queue()

def tts_worker():
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 160)
        while True:
            text = speech_queue.get()
            if text is None:
                break
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"[TTS Error] {e}")
            speech_queue.task_done()
    except Exception as e:
        print(f"[TTS Init Error] {e}")

threading.Thread(target=tts_worker, daemon=True).start()

def speak_async(text):
    """Queue speech without blocking video processing, dropping stale audio."""
    if speech_queue.qsize() < 2:
        speech_queue.put(text)

# Cooldown trackers to prevent flooding
last_spoken = {}
last_logged = {}
last_unknown_snapshot = 0
SPEECH_COOLDOWN = 15.0     # seconds before repeating greeting for same person
LOG_COOLDOWN = 30.0        # seconds before logging attendance again for same person
UNKNOWN_COOLDOWN = 10.0    # seconds between unknown snapshots / alerts

# Load known face data
encodings_path = os.path.join(BASE_DIR, "known_face_encodings.npy")
names_path = os.path.join(BASE_DIR, "known_face_names.npy")
ages_path = os.path.join(BASE_DIR, "known_face_ages.npy")

known_face_encodings = np.load(encodings_path, allow_pickle=True)
known_face_names = np.load(names_path, allow_pickle=True)
known_face_ages = np.load(ages_path, allow_pickle=True) if os.path.exists(ages_path) else ["-"] * len(known_face_names)

# Load emotion model
model_path = os.path.join(BASE_DIR, "emotion_model.hdf5")
emotion_classifier = EmotionClassifier(model_path)

# Create folders
logs_dir = os.path.join(BASE_DIR, "logs")
snapshots_dir = os.path.join(BASE_DIR, "snapshots")
os.makedirs(logs_dir, exist_ok=True)
os.makedirs(snapshots_dir, exist_ok=True)
log_file = os.path.join(logs_dir, "recognized_faces.csv")

# CSV header
if not os.path.exists(log_file):
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Age", "Match %", "Emotion", "Timestamp", "Camera"])

# Initialize camera backend with environment variable support from dashboard
src = os.environ.get("FACE_SOURCE", "0")
src = int(src) if str(src).isdigit() else src
cam_name = os.environ.get("FACE_CAMERA_NAME", "Camera 0")
cam_room = os.environ.get("FACE_CLASS", "")
is_principal_office = "principal" in cam_name.lower() or "principal" in cam_room.lower()
window_title = f"Face & Emotion Recognition - {cam_name}"

if isinstance(src, int) and os.name == "nt":
    cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(src)
else:
    cap = cv2.VideoCapture(src)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("🔍 Face & Emotion Recognition running. Press 'q' to quit.")

prev_time = time.time()
fps = 0.0

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to capture frame from camera.")
        break

    current_time = time.time()
    fps = 0.9 * fps + 0.1 * (1.0 / max(current_time - prev_time, 1e-5))
    prev_time = current_time

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    small_frame = cv2.resize(rgb_frame, (0, 0), fx=0.25, fy=0.25)
    face_locations = face_recognition.face_locations(small_frame)
    face_encodings = face_recognition.face_encodings(small_frame, face_locations)

    for face_encoding, face_location in zip(face_encodings, face_locations):
        distances = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_match_index = np.argmin(distances) if len(distances) > 0 else -1
        match_percent = (1 - distances[best_match_index]) * 100 if best_match_index >= 0 else 0

        name = "Stranger"
        age = "-"
        color = (0, 0, 255)

        if best_match_index >= 0 and match_percent > 60:
            name = str(known_face_names[best_match_index])
            age = str(known_face_ages[best_match_index]) if best_match_index < len(known_face_ages) else "-"
            color = (0, 255, 0)

            # Audio greeting with cooldown
            if current_time - last_spoken.get(name, 0) > SPEECH_COOLDOWN:
                last_spoken[name] = current_time
                if is_principal_office:
                    speak_async(f"Principal's Office entry logged for {name}")
                else:
                    speak_async(f"Hello, {name}")
        else:
            # Unknown stranger handling with cooldown
            if current_time - last_unknown_snapshot > UNKNOWN_COOLDOWN:
                last_unknown_snapshot = current_time
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                prefix = "principal_intrusion" if is_principal_office else "unknown"
                cv2.imwrite(os.path.join(snapshots_dir, f"{prefix}_{timestamp_str}.jpg"), frame)
                if is_principal_office:
                    speak_async("Warning! Restricted area. Unauthorized entry detected!")
                else:
                    speak_async("Unknown person detected!")

        # Emotion detection on face ROI
        top, right, bottom, left = [v * 4 for v in face_location]
        top = max(0, top)
        left = max(0, left)
        bottom = min(frame.shape[0], bottom)
        right = min(frame.shape[1], right)

        face_roi = frame[top:bottom, left:right]
        emotion_str = "Unknown"
        detected_emotion_name = "-"

        if face_roi.size > 0:
            try:
                gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
                roi_resized = cv2.resize(gray, (48, 48))
                roi_normalized = roi_resized.astype("float32") / 255.0
                detected_emotion_name, confidence, _ = emotion_classifier.predict(roi_normalized)
                emotion_str = f"{detected_emotion_name} ({confidence*100:.1f}%)"
            except Exception:
                emotion_str = "Unknown"

        if is_principal_office and name == "Stranger":
            label = f"[RESTRICTED AREA] {name} | {emotion_str}"
            color = (0, 0, 255)
        else:
            label = f"{name} ({age}) | {match_percent:.0f}% | {emotion_str}"
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, label, (left, max(20, top - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # Save to CSV with cooldown per person
        if current_time - last_logged.get(name, 0) > LOG_COOLDOWN:
            last_logged[name] = current_time
            with open(log_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([name, age, f"{match_percent:.1f}%", detected_emotion_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cam_name])

    # Display FPS and active system info
    cv2.putText(frame, f"FPS: {fps:.1f}", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imshow(window_title, frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
