import cv2
import face_recognition
import numpy as np
import os
from datetime import datetime
import threading
import queue
import pygame  # for mp3 playback

# -----------------------------
# Initialize pygame mixer for MP3
# -----------------------------
pygame.mixer.init()
alert_file = r"C:\Users\HP\Downloads\o-pols-aa-gayi-pols-police-saman-samun-ghat-lutya-karo-baba-hai-made-with-Voicemod.mp3"  # ✅ Change this to your MP3 file path

# -----------------------------
# Safe voice speaking queue
# -----------------------------
import pyttsx3
speak_queue = queue.Queue()

def speak_worker():
    engine = pyttsx3.init()
    engine.setProperty('rate', 160)
    while True:
        text = speak_queue.get()
        if text is None:  # stop signal
            break
        engine.say(text)
        engine.runAndWait()
        speak_queue.task_done()

threading.Thread(target=speak_worker, daemon=True).start()

def speak_async(text):
    speak_queue.put(text)

# Play MP3 alert
def play_alert_sound():
    pygame.mixer.music.load(alert_file)
    pygame.mixer.music.play()

# Greeting based on time
def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good Morning"
    elif 12 <= hour < 17:
        return "Good Afternoon"
    else:
        return "Good Evening"

# -----------------------------
# Load Known Faces
# -----------------------------
base_dir = os.path.dirname(os.path.abspath(__file__))
faces_folder = os.path.join(base_dir, "faces")

known_encodings = []
known_names = []
known_ages = []

if not os.path.exists(faces_folder):
    os.makedirs(faces_folder)

for file in os.listdir(faces_folder):
    if file.endswith(".npy"):
        path = os.path.join(faces_folder, file)
        encoding = np.load(path)
        try:
            name, age = file.replace(".npy", "").split("_")
        except ValueError:
            print(f"⚠️ Skipping file with wrong format: {file}")
            continue
        known_encodings.append(encoding)
        known_names.append(name)
        known_ages.append(age)

if not known_encodings:
    print(f"⚠️ No registered faces found in: {faces_folder}")
    exit()

print("🔍 Press 'q' to quit recognition.")

video_capture = cv2.VideoCapture(0)

last_spoken = {}
unknown_face_count = 0  # counter for unknown detections

while True:
    ret, frame = video_capture.read()
    if not ret:
        print("⚠️ Camera not detected.")
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame)
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
        distances = face_recognition.face_distance(known_encodings, face_encoding)

        if len(distances) > 0:
            best_match_index = np.argmin(distances)
            match_score = (1 - distances[best_match_index]) * 100

            if distances[best_match_index] < 0.45:
                name = known_names[best_match_index]
                age = known_ages[best_match_index]
                greeting = f"{get_greeting()} {name}, Age {age}"
                label = f"{greeting} ({match_score:.2f}%)"

                now = datetime.now().timestamp()
                if name not in last_spoken or (now - last_spoken[name]) > 5:
                    speak_async(greeting)
                    last_spoken[name] = now

            else:
                label = "Unknown Face ❌"
                unknown_face_count += 1

                if unknown_face_count == 10:
                    play_alert_sound()  # 🔊 Play MP3
                    unknown_face_count = 0

        else:
            label = "Unknown Face ❌"
            unknown_face_count += 1

            if unknown_face_count == 10:
                play_alert_sound()
                unknown_face_count = 0

        cv2.rectangle(frame, (left, top), (right, bottom), (255, 0, 0), 2)
        cv2.putText(frame, label, (left, top - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    cv2.imshow("Recognize Face", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

video_capture.release()
cv2.destroyAllWindows()

# Stop speaking thread
speak_queue.put(None)
