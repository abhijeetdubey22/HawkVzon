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
import json
import math

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

# Load school settings and match threshold
settings_path = os.path.join(BASE_DIR, "data", "school_settings.json")
min_match_thresh = 50.0
if os.path.exists(settings_path):
    try:
        with open(settings_path, "r", encoding="utf-8") as sf:
            s_data = json.load(sf)
            parsed_thresh = float(s_data.get("min_match", 50.0))
            if math.isfinite(parsed_thresh) and 1.0 <= parsed_thresh <= 99.0:
                min_match_thresh = parsed_thresh
    except Exception:
        min_match_thresh = 50.0

# Load emotion model
model_path = os.path.join(BASE_DIR, "emotion_model.hdf5")
emotion_classifier = EmotionClassifier(model_path)

# Load age and gender models for unknown person profiling
age_proto = os.path.join(BASE_DIR, "age_deploy.prototxt")
age_weights = os.path.join(BASE_DIR, "age_net.caffemodel")
gender_proto = os.path.join(BASE_DIR, "deploy_gender.prototxt")
gender_weights = os.path.join(BASE_DIR, "gender_net.caffemodel")

age_net = None
gender_net = None
if os.path.exists(age_proto) and os.path.exists(age_weights):
    try:
        age_net = cv2.dnn.readNetFromCaffe(age_proto, age_weights)
        print(" [AI Engine] Age estimation neural network loaded.")
    except Exception as e:
        print(f"[Warning] Could not load age model: {e}")

if os.path.exists(gender_proto) and os.path.exists(gender_weights):
    try:
        gender_net = cv2.dnn.readNetFromCaffe(gender_proto, gender_weights)
        print(" [AI Engine] Gender estimation neural network loaded.")
    except Exception as e:
        print(f"[Warning] Could not load gender model: {e}")

AGE_BUCKETS = ['(0-2)', '(4-6)', '(8-12)', '(15-20)', '(25-32)', '(38-43)', '(48-53)', '(60-100)']
GENDER_LIST = ['Male', 'Female']

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
HEADLESS = os.environ.get("FACE_HEADLESS", "0") == "1" or "--headless" in sys.argv

class ThreadedStream:
    """High-performance threaded stream reader. Always discards queued frames to eliminate RTSP lag."""
    def __init__(self, source, name="Camera"):
        self.source = source
        self.name = name
        self.cap = None
        self.frame = None
        self.ret = False
        self.seq = 0
        self.lock = threading.Lock()
        self.running = True
        self.last_grab = time.time()
        self._open()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _open(self):
        try:
            if isinstance(self.source, int) and os.name == "nt":
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.source)
            elif isinstance(self.source, str) and self.source.startswith("rtsp"):
                # Ultra-low latency RTSP configuration
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|buffer_size;1024000|max_delay;500000"
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            else:
                self.cap = cv2.VideoCapture(self.source)

            if self.cap is not None and self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        except Exception as e:
            print(f"[Stream Open Error] {e}")

    def _worker(self):
        drops = 0
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(1.0)
                if not self.running:
                    break
                self._open()
                if not self.running:
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    break
                continue
            ret, frame = self.cap.read()
            if ret and frame is not None:
                drops = 0
                with self.lock:
                    self.ret = ret
                    self.frame = frame
                    self.seq += 1
                    self.last_grab = time.time()
            else:
                drops += 1
                if drops > 25:
                    print(f"⚠️ Video stream lost on '{self.name}'. Auto-reconnecting...")
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    time.sleep(1.5)
                    if not self.running:
                        break
                    self._open()
                    drops = 0
                else:
                    time.sleep(0.01)

    def read(self):
        with self.lock:
            if not self.ret or self.frame is None:
                return False, None, 0
            # Do not return frames older than 4 seconds
            if time.time() - self.last_grab > 4.0:
                return False, None, 0
            return True, self.frame.copy(), self.seq

    def release(self):
        self.running = False
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=3.0)
        worker_stopped = not (hasattr(self, "thread") and self.thread.is_alive())
        if worker_stopped and self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

stream = ThreadedStream(src, cam_name)

mode_str = "Headless Background Mode" if HEADLESS else "HUD Window Mode"
print(f"🔍 Face & Emotion Recognition running on '{cam_name}' ({mode_str}). Press 'q' to quit.")

prev_time = time.time()
fps = 0.0

cached_faces = []
last_demographics = {}
frame_count = 0
PROCESS_EVERY_N_FRAMES = 3  # High-speed interleaving: runs AI on every 3rd new frame, renders at 30 FPS

# Wait up to 5 seconds for first valid frame; exit if stream is dead/unavailable
has_initial_frame = False
for _ in range(50):
    ret, frame, seq = stream.read()
    if ret and frame is not None:
        has_initial_frame = True
        break
    time.sleep(0.1)

if not has_initial_frame:
    print(f"❌ Error: Camera '{cam_name}' failed to supply a video frame within startup deadline. Check connection/URL.")
    stream.release()
    sys.exit(1)

last_processed_seq = -1

while True:
    ret, frame, seq = stream.read()
    if not ret or frame is None:
        if not HEADLESS:
            if cv2.waitKey(20) & 0xFF == ord('q'):
                break
        else:
            time.sleep(0.02)
        continue

    is_new_frame = (seq != last_processed_seq)
    if not is_new_frame:
        time.sleep(0.005)

    if is_new_frame:
        last_processed_seq = seq
        frame_count += 1
        current_time = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(current_time - prev_time, 1e-5))
        prev_time = current_time

    # Run heavy AI processing only on every Nth new captured frame (reduces CPU load by 67%)
    if is_new_frame and (frame_count % PROCESS_EVERY_N_FRAMES == 0):
        # Long-range outdoor & indoor detection engine
        # Detection scale factor: 0.50 retains 4x higher resolution for distant faces up to 25-30 ft
        # Can be set higher (e.g. 0.65) via FACE_DETECTION_SCALE for outdoor testing
        try:
            raw_scale = float(os.environ.get("FACE_DETECTION_SCALE", "0.50"))
            detection_scale = max(0.1, min(1.0, raw_scale)) if math.isfinite(raw_scale) else 0.50
        except Exception:
            detection_scale = 0.50
        inv_scale = 1.0 / detection_scale

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if detection_scale < 1.0:
            small_frame = cv2.resize(rgb_frame, (0, 0), fx=detection_scale, fy=detection_scale)
        else:
            small_frame = rgb_frame

        # Run face detector with 1-level pyramid upsampling to catch distant small faces (15-30 ft)
        face_locations_small = face_recognition.face_locations(small_frame, number_of_times_to_upsample=1, model="hog")

        # Map bounding boxes accurately back to full-resolution coordinates
        full_face_locations = []
        for loc in face_locations_small:
            t, r, b, l = loc
            full_face_locations.append((
                int(max(0, t * inv_scale)),
                int(min(rgb_frame.shape[1], r * inv_scale)),
                int(min(rgb_frame.shape[0], b * inv_scale)),
                int(max(0, l * inv_scale))
            ))

        # CRITICAL: Compute 128-D embeddings on the crisp FULL-RESOLUTION frame, NOT the blurry thumbnail!
        # This dramatically raises recognition accuracy for distant faces and turns red stranger boxes into green student matches
        face_encodings = face_recognition.face_encodings(rgb_frame, full_face_locations)

        new_cached_faces = []
        for face_encoding, face_location in zip(face_encodings, full_face_locations):
            distances = face_recognition.face_distance(known_face_encodings, face_encoding)
            best_match_index = np.argmin(distances) if len(distances) > 0 else -1
            match_percent = (1 - distances[best_match_index]) * 100 if best_match_index >= 0 else 0

            # Face bounding box coordinates on original frame
            top, right, bottom, left = face_location
            face_roi = frame[top:bottom, left:right]

            name = "Stranger"
            age = "-"
            color = (0, 0, 255)

            if best_match_index >= 0 and match_percent >= min_match_thresh:
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
                # Predict Age & Gender for Stranger (Cached for 3 seconds per face to avoid CPU spikes)
                cache_key = f"{left // 80}_{top // 80}"
                cached_demo = last_demographics.get(cache_key)
                if cached_demo and (current_time - cached_demo["time"] < 3.0):
                    age = cached_demo["age"]
                elif face_roi.size > 0 and (gender_net is not None or age_net is not None):
                    try:
                        blob = cv2.dnn.blobFromImage(
                            face_roi, 1.0, (227, 227),
                            (78.4263377603, 87.7689143744, 114.895847746),
                            swapRB=False
                        )
                        det_gender = ""
                        det_age = ""
                        if gender_net is not None:
                            gender_net.setInput(blob)
                            g_preds = gender_net.forward()
                            det_gender = GENDER_LIST[g_preds[0].argmax()]

                        if age_net is not None:
                            age_net.setInput(blob)
                            a_preds = age_net.forward()
                            det_age = AGE_BUCKETS[a_preds[0].argmax()]

                        if det_gender and det_age:
                            age = f"{det_gender}, {det_age}"
                        elif det_age:
                            age = det_age
                        elif det_gender:
                            age = det_gender
                        last_demographics[cache_key] = {"age": age, "time": current_time}
                    except Exception:
                        pass

                # Unknown stranger handling with cooldown
                if current_time - last_unknown_snapshot > UNKNOWN_COOLDOWN:
                    last_unknown_snapshot = current_time
                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    prefix = "principal_intrusion" if is_principal_office else "unknown"
                    snap_path = os.path.join(snapshots_dir, f"{prefix}_{timestamp_str}.jpg")
                    cv2.imwrite(snap_path, frame)
                    cv2.imwrite(os.path.join(snapshots_dir, "latest_unknown.jpg"), frame)
                    if is_principal_office:
                        speak_async(f"Warning! Restricted area. Unauthorized entry detected!")
                    else:
                        speak_async("Unknown person detected!")

            # Emotion detection on face ROI
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
                label = f"[RESTRICTED AREA] {name} ({age}) | {emotion_str}"
                color = (0, 0, 255)
            else:
                label = f"{name} ({age}) | {match_percent:.0f}% | {emotion_str}"

            new_cached_faces.append({
                "box": (left, top, right, bottom),
                "color": color,
                "label": label
            })

            # Save to CSV with cooldown per person
            if current_time - last_logged.get(name, 0) > LOG_COOLDOWN:
                last_logged[name] = current_time
                with open(log_file, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([name, age, f"{match_percent:.1f}%", detected_emotion_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cam_name])

        cached_faces = new_cached_faces

    # Render bounding boxes and HUD labels on EVERY frame (silky smooth 30 FPS!)
    for face in cached_faces:
        left, top, right, bottom = face["box"]
        color = face["color"]
        label = face["label"]
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, label, (left, max(20, top - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    # Display FPS and active system info
    if not HEADLESS:
        cv2.putText(frame, f"FPS: {fps:.1f}", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow(window_title, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    else:
        # In headless mode, keep CPU usage low
        time.sleep(0.01)

stream.release()
cv2.destroyAllWindows()
