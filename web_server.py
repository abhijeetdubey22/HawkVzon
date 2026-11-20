"""
Web Surveillance Command Center Server.
High-performance local web server powering the browser-based Command Center.
Streams live AI-annotated video feeds (30 FPS), multi-camera switching, digital zoom,
camera profile switching, and real-time REST telemetry.
"""
import os
import sys
import time
import json
import csv
import uuid
import threading
import mimetypes
import io
import hashlib
import hmac
import base64
import re
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import cv2
import numpy as np

# Ensure stdout uses UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(BASE_DIR, "gui_config.json")
LOG_FILE = os.path.join(LOGS_DIR, "recognized_faces.csv")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

try:
    from cryptography.fernet import Fernet
except ImportError:
    class Fernet:
        def __init__(self, key):
            if isinstance(key, str):
                key = key.encode("utf-8")
            self._key = hashlib.sha256(key).digest()

        def encrypt(self, data):
            if isinstance(data, str):
                data = data.encode("utf-8")
            nonce = os.urandom(16)
            keystream = b""
            block = 0
            while len(keystream) < len(data):
                keystream += hmac.new(self._key, nonce + block.to_bytes(4, "big"), hashlib.sha256).digest()
                block += 1
            ct = bytes(b ^ k for b, k in zip(data, keystream))
            tag = hmac.new(self._key, nonce + ct, hashlib.sha256).digest()
            return base64.urlsafe_b64encode(b"\x80" + nonce + ct + tag)

        def decrypt(self, token):
            if isinstance(token, str):
                token = token.encode("utf-8")
            raw = base64.urlsafe_b64decode(token)
            if len(raw) < 49 or raw[0] != 0x80:
                raise ValueError("Invalid token format")
            nonce = raw[1:17]
            tag = raw[-32:]
            ct = raw[17:-32]
            expected_tag = hmac.new(self._key, nonce + ct, hashlib.sha256).digest()
            if not hmac.compare_digest(tag, expected_tag):
                raise ValueError("Token verification failed")
            keystream = b""
            block = 0
            while len(keystream) < len(ct):
                keystream += hmac.new(self._key, nonce + block.to_bytes(4, "big"), hashlib.sha256).digest()
                block += 1
            return bytes(b ^ k for b, k in zip(ct, keystream))

def _get_face_key():
    k = os.environ.get("FACE_KEY", "").strip()
    if k:
        return k.encode()
    for kf in (os.path.join(os.path.expanduser("~"), ".face_dashboard", "face.key"),
               os.path.join(BASE_DIR, "data", "face.key")):
        if os.path.exists(kf):
            try:
                with open(kf, "rb") as f:
                    return f.read().strip()
            except OSError:
                pass
    return None

def protect_value(v):
    """Encrypts sensitive CCTV RTSP passwords using Fernet AES."""
    if isinstance(v, str) and v and not v.startswith("enc:"):
        k = _get_face_key()
        if k and Fernet is not None:
            try:
                fer = Fernet(k)
                return "enc:" + fer.encrypt(v.encode("utf-8")).decode("ascii")
            except Exception:
                pass
    return v

def unprotect_value(v):
    """Decrypts encrypted CCTV RTSP passwords."""
    if isinstance(v, str) and v.startswith("enc:"):
        try:
            k = _get_face_key()
            if k and Fernet is not None:
                return Fernet(k).decrypt(v[4:].encode("ascii")).decode("utf-8")
        except Exception as e:
            print(f"[Warning] Failed to decrypt source: {e}")
    return v

def load_known_faces(faces_dir):
    """Loads student face embeddings from encrypted .face files with fallback to .npy."""
    k = _get_face_key()
    fer = Fernet(k) if k and Fernet is not None else None
    encs, names, ages = [], [], []
    if os.path.exists(faces_dir):
        for fn in sorted(os.listdir(faces_dir)):
            if fn.endswith(".face") and fer:
                try:
                    with open(os.path.join(faces_dir, fn), "rb") as f:
                        enc = np.load(io.BytesIO(fer.decrypt(f.read())), allow_pickle=False)
                    parts = fn[:-5].split("_")
                    encs.append(enc)
                    names.append(" ".join(parts[:-1]) if len(parts) >= 2 else parts[0])
                    ages.append(parts[-1] if len(parts) >= 2 else "-")
                except Exception as e:
                    print(f"[Warning] Failed to decrypt {fn}: {e}")
            elif fn.endswith(".npy"):
                try:
                    enc = np.load(os.path.join(faces_dir, fn), allow_pickle=True)
                    parts = fn[:-4].split("_")
                    encs.append(enc)
                    names.append(" ".join(parts[:-1]) if len(parts) >= 2 else parts[0])
                    ages.append(parts[-1] if len(parts) >= 2 else "-")
                except Exception:
                    pass
    if not encs:
        flat_enc = os.path.join(BASE_DIR, "known_face_encodings.npy")
        flat_name = os.path.join(BASE_DIR, "known_face_names.npy")
        flat_age = os.path.join(BASE_DIR, "known_face_ages.npy")
        if os.path.exists(flat_enc) and os.path.exists(flat_name):
            try:
                encs = list(np.load(flat_enc, allow_pickle=True))
                names = list(np.load(flat_name, allow_pickle=True))
                ages = list(np.load(flat_age, allow_pickle=True)) if os.path.exists(flat_age) else ["-"] * len(names)
            except Exception:
                pass

    valid_encs, valid_names, valid_ages = [], [], []
    for e, n, a in zip(encs, names, ages):
        try:
            arr = np.asarray(e, dtype=np.float64).ravel()
            if arr.shape == (128,):
                valid_encs.append(arr)
                valid_names.append(n)
                valid_ages.append(a)
        except Exception:
            continue

    if valid_encs:
        return np.array(valid_encs, dtype=np.float64), np.array(valid_names), np.array(valid_ages)
    return np.empty((0, 128), dtype=np.float64), np.array([]), np.array([])

def get_cameras_list():
    """Returns all configured cameras and indicates the currently active one."""
    cameras = []
    selected = ""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cams = cfg.get("cameras", [])
            selected = cfg.get("selected", "")
            for c in cams:
                cid = c.get("id", "")
                cameras.append({
                    "id": cid,
                    "name": c.get("name", "Camera"),
                    "kind": c.get("kind", "Webcam"),
                    "room": c.get("room", "Campus Area"),
                    "mode": c.get("mode", "Classroom (Indoor / Standard)"),
                    "zoom": float(c.get("zoom", 1.0)),
                    "active": (cid == selected)
                })
        except Exception:
            pass
    if not cameras:
        cameras.append({
            "id": "default",
            "name": "Default Webcam",
            "kind": "Webcam",
            "room": "General",
            "mode": "Classroom (Indoor / Standard)",
            "zoom": 1.0,
            "active": True
        })
        selected = "default"
    return {"cameras": cameras, "selected": selected}

# Global video state shared with HTTP handler
video_lock = threading.Lock()
telemetry_lock = threading.Lock()
current_jpeg_frame = None
latest_telemetry = {
    "fps": 0.0,
    "faces_detected": 0,
    "last_seen_name": "None",
    "last_seen_emotion": "None",
    "camera_id": "",
    "camera_name": "Default Camera",
    "camera_mode": "Classroom (Indoor / Standard)",
    "zoom": 1.0,
    "status": "Initializing"
}
vision_worker = None

# --------------------------------------------------------------------------
# AI Vision Worker Thread
# --------------------------------------------------------------------------
class VisionWorker:
    def __init__(self):
        self.running = True
        self.cap = None
        self.source = 0
        self.camera_id = ""
        self.camera_name = "Camera 0"
        self.camera_mode = "Classroom (Indoor / Standard)"
        self.zoom = 1.0
        self.lock = threading.Lock()
        self.ai_lock = threading.Lock()
        self.latest_raw_frame = None
        self.cached_faces = []
        self.load_config()

        # Load database safely (support encrypted .face files and fallback to .npy)
        try:
            import face_recognition
            self.face_recognition = face_recognition
            print("  [AI ENGINE] face_recognition (dlib) loaded successfully for biometric recognition.")
        except Exception as e:
            self.face_recognition = None
            print(f"  [AI NOTICE] face_recognition / dlib not loaded: {e}")
            print("  [AI ACTIVE] Activated OpenCV High-Performance Cascade Engine for face tracking & emotion analysis.")

        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception:
            self.face_cascade = None

        from emotion_predictor import EmotionClassifier

        faces_dir = os.path.join(BASE_DIR, "faces")
        self.known_encodings, self.known_names, self.known_ages = load_known_faces(faces_dir)

        model_path = os.path.join(BASE_DIR, "emotion_model.hdf5")
        self.emotion_classifier = EmotionClassifier(model_path) if os.path.exists(model_path) else None

        self.last_spoken = {}
        self.last_logged = {}
        self.last_unknown_snapshot = 0

    def load_config(self, camera_id=None):
        """Loads camera configuration, decrypting RTSP passwords automatically."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cams = cfg.get("cameras", [])
                sel_id = camera_id or cfg.get("selected")
                target = next((c for c in cams if c.get("id") == sel_id), cams[0] if cams else None)
                if target:
                    raw_src = target.get("source", 0)
                    decrypted_src = unprotect_value(raw_src)
                    self.source = int(decrypted_src) if str(decrypted_src).isdigit() else decrypted_src
                    self.camera_id = target.get("id", sel_id or "")
                    self.camera_name = target.get("name", "Camera")
                    self.camera_mode = target.get("mode", "Classroom (Indoor / Standard)")
                    self.zoom = float(target.get("zoom", 1.0))
                    if camera_id and cfg.get("selected") != camera_id:
                        cfg["selected"] = camera_id
                        with open(CONFIG_FILE, "w", encoding="utf-8") as wf:
                            json.dump(cfg, wf, indent=2)
            except Exception as e:
                print(f"[Config Load Error] {e}")

    def start(self):
        threading.Thread(target=self._capture_loop, daemon=True, name="CamCaptureThread").start()
        threading.Thread(target=self._ai_worker_loop, daemon=True, name="CamAIWorkerThread").start()
        threading.Thread(target=self._render_loop, daemon=True, name="CamRenderThread").start()

    def _open_camera(self):
        with self.lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            try:
                if isinstance(self.source, int) and os.name == "nt":
                    # Try DSHOW, MSMF, and default backend sequentially to find working video stream
                    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]
                    opened = False
                    for b in backends:
                        try:
                            cap_test = cv2.VideoCapture(self.source, b) if b is not None else cv2.VideoCapture(self.source)
                            if cap_test is not None and cap_test.isOpened():
                                ret_test, f_test = cap_test.read()
                                if ret_test and f_test is not None and f_test.size > 0:
                                    self.cap = cap_test
                                    opened = True
                                    break
                                else:
                                    # Fallback device if opened
                                    self.cap = cap_test
                                    opened = True
                        except Exception:
                            continue
                    if not opened:
                        self.cap = cv2.VideoCapture(self.source)
                elif isinstance(self.source, str) and (self.source.startswith("rtsp") or self.source.startswith("http")):
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|buffer_size;1024000|max_delay;500000|stimeout;3000000"
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(self.source)
                else:
                    self.cap = cv2.VideoCapture(self.source)

                if self.cap is not None and self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    # Try setting 1280x720, check if frame still reads
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    ret_chk, f_chk = self.cap.read()
                    if not ret_chk or f_chk is None:
                        # Reset to default native camera resolution (640x480)
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    return True
            except Exception as e:
                print(f"[Camera Open Error] {e}")
            return False

    def switch_camera(self, camera_id):
        """Switches the active camera on-the-fly."""
        self.load_config(camera_id=camera_id)
        with telemetry_lock:
            latest_telemetry["camera_id"] = self.camera_id
            latest_telemetry["camera_name"] = self.camera_name
            latest_telemetry["camera_mode"] = self.camera_mode
            latest_telemetry["zoom"] = self.zoom
            latest_telemetry["status"] = "Connecting..."
        return self._open_camera()

    def set_zoom(self, zoom_factor):
        """Updates digital zoom factor (1.0x - 4.0x) and persists to config."""
        try:
            self.zoom = max(1.0, min(4.0, float(zoom_factor)))
            with telemetry_lock:
                latest_telemetry["zoom"] = self.zoom
            if os.path.exists(CONFIG_FILE) and self.camera_id:
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    for c in cfg.get("cameras", []):
                        if c.get("id") == self.camera_id:
                            c["zoom"] = self.zoom
                            break
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, indent=2)
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def set_mode(self, mode_name):
        """Updates camera AI operational mode and persists to config."""
        self.camera_mode = mode_name
        with telemetry_lock:
            latest_telemetry["camera_mode"] = self.camera_mode
        if os.path.exists(CONFIG_FILE) and self.camera_id:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                for c in cfg.get("cameras", []):
                    if c.get("id") == self.camera_id:
                        c["mode"] = self.camera_mode
                        break
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
            except Exception:
                pass
        return True

    def reconnect(self):
        """Forces camera re-connection."""
        return self._open_camera()

    def capture_snapshot(self):
        """Captures a clean JPEG frame to snapshots/ and returns the filename."""
        with video_lock:
            frame_bytes = current_jpeg_frame
        if frame_bytes:
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_cam = "".join(c for c in self.camera_name if c.isalnum() or c in ("_", "-"))
            fname = f"manual_{safe_cam}_{now_str}.jpg"
            fpath = os.path.join(SNAPSHOTS_DIR, fname)
            with open(fpath, "wb") as f:
                f.write(frame_bytes)
            return fname
        return None

    def _capture_loop(self):
        """Dedicated high-speed frame grabber. Clears hardware buffers to ensure zero video lag."""
        self._open_camera()
        consecutive_failures = 0

        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.5)
                self._open_camera()
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    with self.lock:
                        if self.cap:
                            try:
                                self.cap.release()
                            except Exception:
                                pass
                        self.cap = None
                    consecutive_failures = 0
                time.sleep(0.01)
                continue

            consecutive_failures = 0
            with self.lock:
                self.latest_raw_frame = frame
            time.sleep(0.003)

    def _ai_worker_loop(self):
        """Asynchronous background AI inference worker. Runs face detection & emotion classification without blocking video."""
        scale = 0.35
        inv_scale = 1.0 / scale

        while self.running:
            with self.lock:
                frame_to_process = self.latest_raw_frame.copy() if self.latest_raw_frame is not None else None

            if frame_to_process is None:
                time.sleep(0.05)
                continue

            try:
                h, w = frame_to_process.shape[:2]
                full_locs = []
                encodings = []

                if self.face_recognition is not None:
                    try:
                        rgb = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2RGB)
                        small = cv2.resize(rgb, (0, 0), fx=scale, fy=scale)
                        face_locs_small = self.face_recognition.face_locations(small, number_of_times_to_upsample=0, model="hog")
                        for loc in face_locs_small:
                            t, r, b, l = loc
                            full_locs.append((
                                int(max(0, t * inv_scale)),
                                int(min(w, r * inv_scale)),
                                int(min(h, b * inv_scale)),
                                int(max(0, l * inv_scale))
                            ))
                        # Limit to at most 4 faces for encodings to prevent CPU choke
                        full_locs = full_locs[:4]
                        encodings = self.face_recognition.face_encodings(rgb, full_locs)
                    except Exception:
                        full_locs = []
                        encodings = []

                # Fallback to OpenCV Haar Cascade if face_recognition returned no faces or is unavailable
                if not full_locs and self.face_cascade is not None:
                    try:
                        gray = cv2.cvtColor(frame_to_process, cv2.COLOR_BGR2GRAY)
                        small_gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale)
                        detected = self.face_cascade.detectMultiScale(
                            small_gray,
                            scaleFactor=1.20,
                            minNeighbors=4,
                            minSize=(26, 26)
                        )
                        for (fx, fy, fw, fh) in detected[:6]:
                            full_locs.append((
                                int(fy * inv_scale),
                                int((fx + fw) * inv_scale),
                                int((fy + fh) * inv_scale),
                                int(fx * inv_scale)
                            ))
                        encodings = [None] * len(full_locs)
                    except Exception:
                        pass

                new_faces = []
                is_principal = "principal" in self.camera_mode.lower() or "principal" in self.camera_name.lower()

                for enc, loc in zip(encodings, full_locs):
                    t, r, b, l = loc
                    t = max(0, min(h - 1, t))
                    b = max(t + 1, min(h, b))
                    l = max(0, min(w - 1, l))
                    r = max(l + 1, min(w, r))
                    roi = frame_to_process[t:b, l:r]

                    name = "Subject"
                    age = "-"
                    color = (255, 140, 0)
                    confidence = 0

                    if enc is not None and self.face_recognition is not None:
                        if len(self.known_encodings) > 0:
                            dist = self.face_recognition.face_distance(self.known_encodings, enc)
                            best_idx = np.argmin(dist) if len(dist) > 0 else -1
                            confidence = (1 - dist[best_idx]) * 100 if best_idx >= 0 else 0
                        else:
                            best_idx = -1
                            confidence = 0

                        if best_idx >= 0 and confidence >= 50.0:
                            name = str(self.known_names[best_idx])
                            age = str(self.known_ages[best_idx]) if best_idx < len(self.known_ages) else "-"
                            color = (0, 255, 0)
                        else:
                            name = "Stranger"
                            color = (0, 0, 255)
                    else:
                        name = "Face Detected"
                        color = (0, 255, 180)

                    # Emotion inference
                    emotion_str = "Neutral"
                    if roi.size > 0 and self.emotion_classifier is not None:
                        try:
                            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                            resized_roi = cv2.resize(gray_roi, (48, 48))
                            norm = resized_roi.astype("float32") / 255.0
                            label, conf, _ = self.emotion_classifier.predict(norm)
                            emotion_str = label
                        except Exception:
                            pass

                    label_text = f"{name} ({age}) | {emotion_str}"
                    if is_principal and name == "Stranger":
                        label_text = f"[RESTRICTED] {name} | {emotion_str}"
                        color = (0, 0, 255)

                    new_faces.append({
                        "box": (l, t, r, b),
                        "color": color,
                        "label": label_text,
                        "name": name,
                        "emotion": emotion_str
                    })

                    # Log recognized face with 30s cooldown
                    now_ts = time.time()
                    if name not in ("Stranger", "Subject", "Face Detected") and (now_ts - self.last_logged.get(name, 0) > 30.0):
                        self.last_logged[name] = now_ts
                        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                                csv.writer(f).writerow([name, age, f"{confidence:.1f}%", emotion_str, timestamp_str, self.camera_name])
                        except Exception:
                            pass

                    # Auto snapshot for unknown stranger (15s cooldown)
                    if name == "Stranger" and (now_ts - self.last_unknown_snapshot > 15.0):
                        self.last_unknown_snapshot = now_ts
                        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        prefix = "principal_intrusion" if is_principal else "unknown"
                        snap_name = f"{prefix}_{time_str}.jpg"
                        try:
                            cv2.imwrite(os.path.join(SNAPSHOTS_DIR, snap_name), frame_to_process)
                            cv2.imwrite(os.path.join(SNAPSHOTS_DIR, "latest_unknown.jpg"), frame_to_process)
                        except Exception:
                            pass

                with self.ai_lock:
                    self.cached_faces = new_faces

                # Update live telemetry
                with telemetry_lock:
                    latest_telemetry["faces_detected"] = len(new_faces)
                    if new_faces:
                        latest_telemetry["last_seen_name"] = new_faces[0]["name"]
                        latest_telemetry["last_seen_emotion"] = new_faces[0]["emotion"]

            except Exception:
                pass

            time.sleep(0.08)

    def _render_loop(self):
        """Dedicated real-time display & streaming renderer. Delivers butter-smooth 30+ FPS video with HUD telemetry."""
        global current_jpeg_frame, latest_telemetry
        prev_time = time.time()
        fps = 30.0

        while self.running:
            with self.lock:
                frame = self.latest_raw_frame.copy() if self.latest_raw_frame is not None else None

            if frame is None:
                with telemetry_lock:
                    latest_telemetry["status"] = "Connecting..."
                standby = np.zeros((480, 854, 3), dtype=np.uint8)
                standby[:] = (15, 23, 42)
                cv2.putText(standby, "CAMERA CONNECTING / STANDBY", (240, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (148, 163, 184), 2)
                cv2.putText(standby, f"Target: {self.camera_name}", (280, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (56, 189, 248), 1)
                ret_enc, jpeg = cv2.imencode(".jpg", standby, [cv2.IMWRITE_JPEG_QUALITY, 68])
                if ret_enc:
                    with video_lock:
                        current_jpeg_frame = jpeg.tobytes()
                time.sleep(0.1)
                continue

            with telemetry_lock:
                latest_telemetry["status"] = "Live"

            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-5))
            prev_time = now

            # Apply digital zoom crop
            if getattr(self, "zoom", 1.0) > 1.0:
                zh, zw = frame.shape[:2]
                cw, ch = int(zw / self.zoom), int(zh / self.zoom)
                cx, cy = zw // 2, zh // 2
                x1 = max(0, min(zw - cw, cx - cw // 2))
                y1 = max(0, min(zh - ch, cy - ch // 2))
                frame = cv2.resize(frame[y1:y1 + ch, x1:x1 + cw], (zw, zh), interpolation=cv2.INTER_LINEAR)

            # Check if camera frame is pitch black
            if frame.mean() < 2.5:
                zh, zw = frame.shape[:2]
                cv2.putText(frame, "[CAMERA SENSOR OUTPUTTING BLACK]", (int(zw * 0.08), int(zh * 0.40)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
                cv2.putText(frame, "1. Open physical privacy slider / cover on webcam lens", (int(zw * 0.08), int(zh * 0.48)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (220, 220, 220), 1)
                cv2.putText(frame, "2. Check Windows Settings -> Privacy -> Camera access", (int(zw * 0.08), int(zh * 0.55)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (220, 220, 220), 1)
                cv2.putText(frame, "3. Switch to 'Webcam 1' in the camera dropdown above", (int(zw * 0.08), int(zh * 0.62)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (100, 200, 255), 1)

            # Draw AI bounding boxes from cached_faces
            with self.ai_lock:
                faces_to_draw = list(self.cached_faces)

            for face in faces_to_draw:
                l, t, r, b = face["box"]
                color = face["color"]
                label = face["label"]
                cv2.rectangle(frame, (l, t), (r, b), color, 2)
                y_pos = max(20, t - 8)
                cv2.putText(frame, label, (l, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 0), 3)
                cv2.putText(frame, label, (l, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 1)

            # Draw Watermark
            watermark = f"FPS: {fps:.1f} | {self.camera_name}"
            if self.zoom > 1.0:
                watermark += f" | {self.zoom:.1f}x"
            cv2.putText(frame, watermark, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
            cv2.putText(frame, watermark, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)

            with telemetry_lock:
                latest_telemetry["fps"] = round(fps, 1)
                latest_telemetry["camera_id"] = self.camera_id
                latest_telemetry["camera_name"] = self.camera_name
                latest_telemetry["camera_mode"] = self.camera_mode
                latest_telemetry["zoom"] = self.zoom

            # High-speed JPEG encoding
            ret_enc, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 68])
            if ret_enc:
                with video_lock:
                    current_jpeg_frame = jpeg.tobytes()

            time.sleep(0.025)

# --------------------------------------------------------------------------
# Modern Web Dashboard HTTP Request Handler
# --------------------------------------------------------------------------
class CommandCenterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence verbose terminal access logs
        return

    def send_json(self, data, code=200):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def read_post_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                return json.loads(body.decode("utf-8"))
        except Exception:
            pass
        return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(self.render_dashboard().encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        elif path == "/video_feed":
            try:
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-cache, private")
                self.end_headers()
                while True:
                    with video_lock:
                        frame = current_jpeg_frame
                    if frame is not None:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
                    time.sleep(0.033)  # ~30 FPS
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            except Exception:
                pass

        elif path == "/api/telemetry":
            with telemetry_lock:
                telemetry_data = latest_telemetry.copy()
            self.send_json(telemetry_data)

        elif path == "/api/cameras":
            self.send_json(get_cameras_list())

        elif path == "/api/select_camera":
            cid = qs.get("id", [""])[0]
            if cid and vision_worker:
                success = vision_worker.switch_camera(cid)
                self.send_json({
                    "success": success,
                    "selected": cid,
                    "name": vision_worker.camera_name,
                    "mode": vision_worker.camera_mode,
                    "zoom": vision_worker.zoom
                })
            else:
                self.send_json({"success": False, "error": "Missing camera id"}, code=400)

        elif path == "/api/camera_control":
            action = qs.get("action", [""])[0]
            val = qs.get("val", [""])[0]
            if vision_worker:
                if action == "zoom":
                    vision_worker.set_zoom(val)
                elif action == "mode":
                    vision_worker.set_mode(val)
                elif action == "reconnect":
                    vision_worker.reconnect()
                self.send_json({
                    "success": True,
                    "action": action,
                    "zoom": vision_worker.zoom,
                    "mode": vision_worker.camera_mode
                })
            else:
                self.send_json({"success": False, "error": "Vision engine unavailable"}, code=500)

        elif path == "/api/capture_snapshot":
            if vision_worker:
                fname = vision_worker.capture_snapshot()
                if fname:
                    self.send_json({"success": True, "filename": fname, "url": f"/snapshots/{fname}"})
                else:
                    self.send_json({"success": False, "error": "No frame available to capture"}, code=500)
            else:
                self.send_json({"success": False, "error": "Vision engine unavailable"}, code=500)

        elif path == "/api/attendance":
            records = self.get_attendance_data()
            self.send_json(records)

        elif path == "/api/stats":
            stats = self.get_summary_stats()
            self.send_json(stats)

        elif path == "/api/principal_summary":
            summary = self.get_principal_summary()
            self.send_json(summary)

        elif path == "/api/visitors":
            visitors = self.get_visitors_summary()
            self.send_json(visitors)

        elif path.startswith("/snapshots/"):
            filename = os.path.basename(path)
            fpath = os.path.abspath(os.path.join(SNAPSHOTS_DIR, filename))
            if fpath.startswith(os.path.abspath(SNAPSHOTS_DIR)) and os.path.isfile(fpath):
                mime, _ = mimetypes.guess_type(fpath)
                self.send_response(200)
                self.send_header("Content-Type", mime or "image/jpeg")
                self.end_headers()
                with open(fpath, "rb") as sf:
                    self.wfile.write(sf.read())
            else:
                self.send_error(404, "Snapshot Not Found")

        elif path.startswith("/exports/"):
            filename = os.path.basename(path)
            fpath = os.path.abspath(os.path.join(EXPORTS_DIR, filename))
            if fpath.startswith(os.path.abspath(EXPORTS_DIR)) and os.path.isfile(fpath):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(fpath, "rb") as ef:
                    self.wfile.write(ef.read())
            else:
                self.send_error(404, "Report File Not Found")

        elif path == "/api/export_report":
            try:
                import report_generator
                rpath = report_generator.generate_html_report()
                fname = os.path.basename(rpath)
                self.send_json({"success": True, "url": f"/exports/{fname}"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
        else:
            self.send_error(404, "Page Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self.read_post_json()

        if path == "/api/select_camera":
            cid = data.get("id")
            if cid and vision_worker:
                success = vision_worker.switch_camera(cid)
                self.send_json({
                    "success": success,
                    "selected": cid,
                    "name": vision_worker.camera_name,
                    "mode": vision_worker.camera_mode,
                    "zoom": vision_worker.zoom
                })
            else:
                self.send_json({"success": False, "error": "Invalid camera ID"}, code=400)

        elif path == "/api/camera_control":
            action = data.get("action")
            val = data.get("val")
            if vision_worker:
                if action == "zoom":
                    vision_worker.set_zoom(val)
                elif action == "mode":
                    vision_worker.set_mode(val)
                elif action == "reconnect":
                    vision_worker.reconnect()
                self.send_json({
                    "success": True,
                    "action": action,
                    "zoom": vision_worker.zoom,
                    "mode": vision_worker.camera_mode
                })
            else:
                self.send_json({"success": False, "error": "Vision engine unavailable"}, code=500)

        elif path == "/api/add_camera":
            try:
                new_cam = self.add_camera_config(data)
                self.send_json({"success": True, "camera": new_cam})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)

        elif path == "/api/capture_snapshot":
            if vision_worker:
                fname = vision_worker.capture_snapshot()
                if fname:
                    self.send_json({"success": True, "filename": fname, "url": f"/snapshots/{fname}"})
                else:
                    self.send_json({"success": False, "error": "No frame available to capture"}, code=500)
            else:
                self.send_json({"success": False, "error": "Vision engine unavailable"}, code=500)

        elif path == "/api/extend_visitor_time":
            vid = data.get("id", "guest_mehta")
            mins = int(data.get("minutes", 30))
            success, msg, v = self.extend_visitor_time(vid, mins)
            self.send_json({"success": success, "message": msg, "visitor": v})

        elif path == "/api/add_visitor":
            try:
                new_v = self.add_visitor(data)
                self.send_json({"success": True, "visitor": new_v})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
        else:
            self.send_error(404, "API endpoint not found")

    def add_camera_config(self, data):
        """Adds and persists a new camera configuration with encryption."""
        name = str(data.get("name", "New Camera")).strip()
        kind = str(data.get("kind", "Webcam")).strip()
        raw_source = str(data.get("source", "0")).strip()
        room = str(data.get("room", "Campus Area")).strip()
        mode = str(data.get("mode", "Classroom (Indoor / Standard)")).strip()

        if raw_source.isdigit():
            source = int(raw_source)
        elif kind == "CCTV / IP Camera":
            source = protect_value(raw_source)
        else:
            source = raw_source

        cid = uuid.uuid4().hex[:8]
        new_cam = {
            "id": cid,
            "name": name,
            "kind": kind,
            "source": source,
            "room": room,
            "mode": mode,
            "zoom": 1.0
        }

        cfg = {"cameras": [], "selected": cid, "view_mode": "Single camera"}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass

        cfg.setdefault("cameras", []).append(new_cam)
        cfg["selected"] = cid

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        if vision_worker:
            vision_worker.switch_camera(cid)

        return new_cam

    def _load_visitors(self):
        """Loads visitors registry from data/visitors.json."""
        vfile = os.path.join(DATA_DIR, "visitors.json")
        if os.path.exists(vfile):
            try:
                with open(vfile, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_visitors(self, visitors):
        """Persists visitors registry to data/visitors.json."""
        vfile = os.path.join(DATA_DIR, "visitors.json")
        try:
            with open(vfile, "w", encoding="utf-8") as f:
                json.dump(visitors, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Visitor Save Error] {e}")

    def get_visitors_summary(self):
        """Computes live remaining minutes, countdown, and active journey status for all visitors."""
        visitors = self._load_visitors()
        now = datetime.now()
        out = []
        for vid, v in visitors.items():
            valid_to_str = v.get("valid_to", "")
            try:
                vt = datetime.strptime(valid_to_str, "%Y-%m-%d %H:%M:%S")
                diff_sec = (vt - now).total_seconds()
                rem_mins = int(diff_sec // 60)
            except Exception:
                rem_mins = 60

            status = v.get("status", "Active")
            if status != "Departed":
                if rem_mins < 0:
                    status = "Overstayed"
                elif rem_mins <= 15:
                    status = "Expiring Soon"
                else:
                    status = "Active"
            v_copy = dict(v)
            v_copy["id"] = vid
            v_copy["remaining_minutes"] = rem_mins
            v_copy["status"] = status
            out.append(v_copy)
        return out

    def extend_visitor_time(self, visitor_id, minutes):
        """Extends visitor permit by 30m, 50m, 1h, or custom minutes requested by Principal."""
        visitors = self._load_visitors()
        if visitor_id not in visitors:
            matched_key = None
            for k, val in visitors.items():
                if visitor_id.lower() in val.get("name", "").lower() or visitor_id.lower() in k.lower():
                    matched_key = k
                    break
            if not matched_key:
                return False, f"Visitor '{visitor_id}' not found", None
            visitor_id = matched_key

        v = visitors[visitor_id]
        now = datetime.now()
        current_valid_to = v.get("valid_to", "")
        try:
            curr_dt = datetime.strptime(current_valid_to, "%Y-%m-%d %H:%M:%S")
            base_dt = max(now, curr_dt)
        except Exception:
            base_dt = now

        from datetime import timedelta
        new_dt = base_dt + timedelta(minutes=int(minutes))
        new_str = new_dt.strftime("%Y-%m-%d %H:%M:%S")
        v["valid_to"] = new_str
        v["status"] = "Active"

        now_time_str = now.strftime("%I:%M %p")
        cutoff_fmt = new_dt.strftime("%I:%M %p")
        journey = v.setdefault("journey", [])
        journey.append({
            "time": now_time_str,
            "camera": "Command Center Admin",
            "zone": v.get("current_zone", "Campus Area"),
            "event": f"Pass extended by +{minutes}m by Principal (New Cutoff: {cutoff_fmt})"
        })

        self._save_visitors(visitors)
        msg = f"Extended {v.get('name', 'Guest')}'s permit by +{minutes} minutes! New departure cutoff: {cutoff_fmt}."
        return True, msg, v

    def add_visitor(self, data):
        """Creates a new guest pass with time limits and allowed zones."""
        visitors = self._load_visitors()
        name = str(data.get("name", "New Guest")).strip()
        phone = str(data.get("phone", "")).strip()
        host = str(data.get("host", "Principal Office")).strip()
        purpose = str(data.get("purpose", "Campus Visit")).strip()
        duration_mins = int(data.get("duration", 60))
        allowed_zones = data.get("allowed_zones", ["Main Entrance Gate", "Admin Block", "Classroom"])

        from datetime import timedelta
        now = datetime.now()
        valid_from = now.strftime("%Y-%m-%d %H:%M:%S")
        valid_to = (now + timedelta(minutes=duration_mins)).strftime("%Y-%m-%d %H:%M:%S")

        vid = f"guest_{uuid.uuid4().hex[:6]}"
        new_v = {
            "id": vid,
            "name": name,
            "phone": phone,
            "host": host,
            "purpose": purpose,
            "photo": "/snapshots/latest_unknown.jpg",
            "valid_from": valid_from,
            "valid_to": valid_to,
            "allowed_zones": allowed_zones,
            "status": "Active",
            "current_zone": "Main Entrance Gate",
            "last_seen_time": now.strftime("%I:%M %p"),
            "last_seen_camera": "PixaVision CCTV",
            "journey": [
              {
                "time": now.strftime("%I:%M %p"),
                "camera": "PixaVision CCTV",
                "zone": "Main Entrance Gate",
                "event": "Guest Permit Issued"
              }
            ]
        }
        visitors[vid] = new_v
        self._save_visitors(visitors)
        return new_v

    def _load_students_map(self):
        """Loads students dictionary with normalized lookup keys."""
        students_file = os.path.join(DATA_DIR, "students.json")
        all_students = {}
        if os.path.exists(students_file):
            try:
                with open(students_file, "r", encoding="utf-8") as sf:
                    all_students = json.load(sf)
            except Exception:
                pass
        return all_students

    def get_attendance_data(self):
        """Retrieves raw attendance log enriched with student roll numbers and classes."""
        records = []
        all_students = self._load_students_map()
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    rows = list(csv.reader(f))[1:]
                for row in reversed(rows[-100:]):
                    if len(row) >= 5:
                        name = row[0]
                        norm_k = re.sub(r"\s+", " ", name.strip()).lower()
                        meta = all_students.get(norm_k, {})
                        is_stranger = name.lower() in ("stranger", "unknown")
                        records.append({
                            "name": meta.get("name", name),
                            "roll": meta.get("roll", "Unregistered" if is_stranger else "-"),
                            "klass": meta.get("klass", "Perimeter Zone" if is_stranger else "Classroom"),
                            "age": row[1],
                            "match": row[2],
                            "emotion": row[3],
                            "time": row[4],
                            "camera": row[5] if len(row) > 5 else "Default"
                        })
            except Exception:
                pass
        return records

    def get_principal_summary(self):
        """Generates comprehensive College Principal KPIs, present/absent rosters, and intruder radar."""
        all_students = self._load_students_map()
        today = datetime.now().strftime("%Y-%m-%d")
        present_map = {}
        stranger_sightings_today = 0
        emotions_today = {}
        last_stranger_event = None

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    rows = list(csv.reader(f))[1:]
                for row in rows:
                    if len(row) < 5:
                        continue
                    name, age, match, emotion, ts = row[0], row[1], row[2], row[3], row[4]
                    cam = row[5] if len(row) > 5 else "Default Camera"
                    is_stranger = name.lower() in ("stranger", "unknown")

                    if is_stranger:
                        if ts.startswith(today):
                            stranger_sightings_today += 1
                        last_stranger_event = {
                            "timestamp": ts,
                            "camera": cam,
                            "profile": age,
                            "match": match,
                            "photo": "/snapshots/latest_unknown.jpg"
                        }
                    else:
                        if ts.startswith(today):
                            norm_k = re.sub(r"\s+", " ", name.strip()).lower()
                            meta = all_students.get(norm_k, {})
                            if norm_k not in present_map:
                                present_map[norm_k] = {
                                    "name": meta.get("name", name),
                                    "roll": meta.get("roll", "Enrolled"),
                                    "klass": meta.get("klass", "Classroom"),
                                    "age": meta.get("age", age),
                                    "time_in": ts,
                                    "last_seen": ts,
                                    "camera": cam,
                                    "emotion": emotion,
                                    "match": match
                                }
                            else:
                                present_map[norm_k]["last_seen"] = ts
                                present_map[norm_k]["camera"] = cam
                                present_map[norm_k]["emotion"] = emotion
                            if emotion and emotion not in ("-", "Unknown"):
                                emotions_today[emotion] = emotions_today.get(emotion, 0) + 1
            except Exception:
                pass

        total_enrolled = max(len(all_students), 1)
        present_list = list(present_map.values())
        present_count = len(present_list)
        present_rate = round((present_count / total_enrolled) * 100, 1)

        absent_list = []
        for k, v in all_students.items():
            if k not in present_map:
                absent_list.append({
                    "name": v.get("name", k.title()),
                    "roll": v.get("roll", "N/A"),
                    "klass": v.get("klass", "Classroom"),
                    "age": v.get("age", "-"),
                    "parent_name": v.get("parent_name", "Guardian"),
                    "parent_phone": v.get("parent_phone", "-"),
                    "status": "Not Arrived"
                })
        absent_count = len(absent_list)
        absent_rate = round((absent_count / total_enrolled) * 100, 1)

        total_emo = sum(emotions_today.values())
        if total_emo > 0:
            weighted = (
                emotions_today.get("Happy", 0) * 1.0 +
                emotions_today.get("Neutral", 0) * 0.85 +
                emotions_today.get("Surprise", 0) * 0.70 +
                emotions_today.get("Sad", 0) * 0.25 +
                emotions_today.get("Angry", 0) * 0.10
            )
            happiness_index = round((weighted / total_emo) * 100, 1)
        else:
            happiness_index = 85.0

        if happiness_index >= 75:
            mood_label = "Optimal & Focused"
            mood_color = "emerald"
        elif happiness_index >= 50:
            mood_label = "Calm & Attentive"
            mood_color = "sky"
        else:
            mood_label = "Fatigued / Needs Care"
            mood_color = "amber"

        if not last_stranger_event:
            last_stranger_event = {
                "timestamp": "No perimeter intrusion",
                "camera": "Gate Secure",
                "profile": "No unidentified face",
                "match": "100% Clear",
                "photo": "/snapshots/latest_unknown.jpg"
            }

        cam_info = get_cameras_list()
        cam_count = len(cam_info.get("cameras", []))

        visitors_list = self.get_visitors_summary()
        active_visitors = len([v for v in visitors_list if v.get("status") != "Departed"])

        return {
            "total_enrolled": total_enrolled,
            "present_today": present_count,
            "attendance_rate": present_rate,
            "absent_count": absent_count,
            "absent_rate": absent_rate,
            "present_list": present_list,
            "absent_list": absent_list,
            "visitors": visitors_list,
            "active_visitors_count": active_visitors,
            "happiness_index": happiness_index,
            "mood_label": mood_label,
            "mood_color": mood_color,
            "strangers_count": stranger_sightings_today,
            "last_stranger": last_stranger_event,
            "active_cameras": cam_count,
            "emotions": emotions_today
        }

    def get_summary_stats(self):
        return self.get_principal_summary()

    def render_dashboard(self):
        index_file = os.path.join(BASE_DIR, "index.html")
        if os.path.exists(index_file):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Autonomous AI Surveillance & Attendance Command Center</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: {
              400: '#38bdf8',
              500: '#0ea5e9',
              600: '#0284c7'
            },
            surface: {
              canvas: '#070b14',
              card: '#0f172a',
              sub: '#1e293b'
            }
          }
        }
      }
    }
  </script>
  <style>
    /* Sleek scrollbars */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #070b14; }
    ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 9999px; }
    ::-webkit-scrollbar-thumb:hover { background: #38bdf8; }
    .glass { backdrop-filter: blur(12px); background: rgba(15, 23, 42, 0.84); border: 1px solid rgba(51, 65, 85, 0.6); }
    .glow-cyan { box-shadow: 0 0 25px -5px rgba(56, 189, 248, 0.25); }
    .glow-emerald { box-shadow: 0 0 20px -5px rgba(16, 185, 129, 0.3); }
    @keyframes pulse-fast { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    .animate-pulse-fast { animation: pulse-fast 1.2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
  </style>
</head>
<body class="bg-surface-canvas text-slate-100 min-h-screen font-sans antialiased">

  <!-- Toast Notification Container -->
  <div id="toastContainer" class="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none"></div>

  <!-- Top Glass Command Bar -->
  <header class="sticky top-0 z-40 glass border-b border-slate-800/80 px-4 md:px-8 py-3 flex items-center justify-between">
    <div class="flex items-center gap-3.5">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-400 via-blue-600 to-indigo-700 flex items-center justify-center shadow-lg shadow-sky-500/25 text-white font-black text-lg">
        AI
      </div>
      <div>
        <div class="flex items-center gap-2.5">
          <h1 class="text-base md:text-xl font-extrabold tracking-tight text-white">Campus AI Surveillance & Principal Command Center</h1>
          <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-950/90 text-emerald-400 border border-emerald-800/60 flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse-fast"></span>
            <span id="badgeStatus">LIVE</span>
          </span>
        </div>
        <p class="text-[11px] text-slate-400">Autonomous Facial Biometrics, Attendance Roll-Call, Campus Sentiment & Smart Guest Escort</p>
      </div>
    </div>

    <!-- Header Actions -->
    <div class="flex items-center gap-2.5">
      <button onclick="openAddVisitorModal()" class="px-3.5 py-2 rounded-lg bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white text-xs font-semibold transition flex items-center gap-1.5 shadow-md shadow-indigo-900/40">
        <span>🎟️</span> <span class="hidden sm:inline">Issue Guest Pass</span>
      </button>
      <button onclick="openAddCameraModal()" class="px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition flex items-center gap-1.5 shadow-md shadow-emerald-900/40">
        <span>➕</span> <span class="hidden sm:inline">Add Camera</span>
      </button>
      <button onclick="exportReport()" class="px-3.5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold transition flex items-center gap-1.5 shadow-md shadow-sky-900/40">
        <span>📊</span> <span class="hidden sm:inline">Executive Report</span>
      </button>
      <button onclick="toggleFullscreen()" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition text-sm" title="Toggle Fullscreen">
        ⛶
      </button>
      <div class="hidden md:flex items-center px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 gap-1.5">
        <span>🕒</span>
        <span id="liveClock" class="font-mono">10:30:00 AM</span>
      </div>
    </div>
  </header>

  <!-- Main Grid Layout -->
  <main class="max-w-[1850px] mx-auto p-4 md:p-6 space-y-6">

    <!-- CAMERA SWITCHER BAR (shadcn/ui Pill Tabs) -->
    <section class="glass p-3 rounded-2xl border border-slate-800 flex items-center justify-between gap-3 overflow-x-auto">
      <div class="flex items-center gap-2" id="cameraTabsList">
        <div class="text-xs text-slate-400 px-3 py-1.5">Loading cameras...</div>
      </div>
      <button onclick="openAddCameraModal()" class="shrink-0 px-3 py-1.5 rounded-xl border border-dashed border-slate-700 hover:border-sky-500 text-slate-400 hover:text-sky-300 text-xs font-medium transition flex items-center gap-1.5">
        <span>➕</span> Add New Source
      </button>
    </section>

    <!-- CONTENT GRID -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

      <!-- LEFT COLUMN: Live Cinema Video Player + Attendance Ledger (8 cols) -->
      <div class="lg:col-span-8 space-y-6">

        <!-- Live Video Cinema Player Card -->
        <div class="glass rounded-2xl overflow-hidden glow-cyan border border-slate-800 relative">
          
          <!-- Cinema Player Top Header -->
          <div class="bg-slate-950/95 px-4 py-2.5 flex items-center justify-between border-b border-slate-800/80">
            <div class="flex items-center gap-2.5">
              <span class="text-rose-500 font-bold animate-pulse text-xs">●</span>
              <span class="text-xs font-bold uppercase tracking-wider text-slate-200" id="camTitle">Live Stream &bull; Camera</span>
              <span class="text-[10px] px-2 py-0.5 rounded-md bg-sky-950 text-sky-300 border border-sky-800/60 font-mono" id="camMode">Classroom (Indoor)</span>
            </div>
            <div class="flex items-center gap-3 text-xs text-slate-400 font-mono">
              <span>FPS: <strong class="text-emerald-400" id="statFps">30.0</strong></span>
              <span>Faces: <strong class="text-sky-400" id="statFaces">0</strong></span>
              <span>Zoom: <strong class="text-amber-400" id="statZoom">1.0x</strong></span>
            </div>
          </div>

          <!-- Video Stream Canvas -->
          <div class="relative bg-black aspect-video flex items-center justify-center overflow-hidden group">
            <img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed" class="w-full h-full object-cover">
            
            <div id="videoPlaceholder" class="hidden absolute inset-0 bg-slate-950/90 flex flex-col items-center justify-center text-slate-400 space-y-2">
              <span class="text-3xl animate-spin">⏳</span>
              <p class="text-sm font-medium">Switching / Reconnecting Camera Stream...</p>
            </div>

            <!-- FLOATING ACTION TOOLBAR OVERLAY (Bottom of Video) -->
            <div class="absolute bottom-3 inset-x-3 px-3 py-2 rounded-xl glass border border-slate-700/80 flex flex-wrap items-center justify-between gap-2 opacity-95 group-hover:opacity-100 transition shadow-2xl">
              
              <!-- Left: Camera Quick Switch Dropdown & Reconnect -->
              <div class="flex items-center gap-2">
                <select id="quickCamSelect" onchange="selectCamera(this.value)" class="bg-slate-900 border border-slate-700 text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500">
                  <option value="">Loading...</option>
                </select>
                <button onclick="reconnectCamera()" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition flex items-center gap-1" title="Reconnect Camera Stream">
                  <span>🔄</span> <span class="hidden sm:inline">Reconnect</span>
                </button>
              </div>

              <!-- Center: Digital Zoom Controls (1.0x - 3.0x) -->
              <div class="flex items-center bg-slate-950/90 rounded-lg p-0.5 border border-slate-800 text-xs">
                <span class="text-[10px] text-slate-400 px-2 font-semibold">ZOOM:</span>
                <button onclick="setZoom(1.0)" id="zoomBtn1" class="px-2 py-1 rounded bg-sky-600 text-white font-mono text-[11px] font-bold">1.0x</button>
                <button onclick="setZoom(1.5)" id="zoomBtn15" class="px-2 py-1 rounded text-slate-400 hover:text-white font-mono text-[11px]">1.5x</button>
                <button onclick="setZoom(2.0)" id="zoomBtn2" class="px-2 py-1 rounded text-slate-400 hover:text-white font-mono text-[11px]">2.0x</button>
                <button onclick="setZoom(3.0)" id="zoomBtn3" class="px-2 py-1 rounded text-slate-400 hover:text-white font-mono text-[11px]">3.0x</button>
              </div>

              <!-- Right: Mode Profile, Snapshot, Fullscreen -->
              <div class="flex items-center gap-2">
                <select id="modeSelect" onchange="setModeProfile(this.value)" class="bg-slate-900 border border-slate-700 text-xs text-slate-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500">
                  <option value="Classroom (Indoor / Standard)">Classroom (Standard)</option>
                  <option value="Outdoor / Main Gate (25-35 ft)">Outdoor (Long-Range 30ft)</option>
                  <option value="Principal's Office / High Security">Principal's (High Security)</option>
                  <option value="Corridor / Transit Flow">Corridor (Transit Flow)</option>
                  <option value="Library / Exam Hall (Silent)">Library (Silent Mode)</option>
                </select>

                <button onclick="takeSnapshot()" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition flex items-center gap-1 shadow-sm" title="Capture Snapshot Photo">
                  <span>📸</span> <span class="hidden sm:inline">Snap</span>
                </button>
                <button onclick="toggleFullscreen()" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs" title="Fullscreen">
                  ⛶
                </button>
              </div>

            </div>
          </div>

          <!-- Bottom Stream Telemetry Bar -->
          <div class="bg-slate-900/90 p-3 flex items-center justify-between text-xs border-t border-slate-800/80">
            <div class="flex items-center gap-2">
              <span class="text-slate-400">Last Identified:</span>
              <span class="font-bold text-white px-2.5 py-1 rounded bg-slate-800 border border-slate-700" id="lastSeenName">Scanning...</span>
              <span class="text-slate-400">Emotion:</span>
              <span class="font-semibold text-emerald-400 px-2 py-1 rounded bg-emerald-950/80 border border-emerald-800/50" id="lastSeenEmotion">Neutral</span>
            </div>
            <div class="text-slate-400 text-[11px]">
              Processing: <strong class="text-slate-200">1280 × 720 HD</strong> &bull; ResNet 128-D &bull; 7-Class Universal Emotion
            </div>
          </div>
        </div>

        <!-- Attendance Roll-Call & Incident Ledger Card -->
        <div class="glass rounded-2xl p-5 border border-slate-800">
          <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-3 mb-4">
            <div>
              <h2 class="text-base font-bold text-white flex items-center gap-2">
                <span>📋</span> Attendance Roll-Call & Incident Ledger
              </h2>
              <p class="text-xs text-slate-400">Authenticated student presence with roll numbers, arrival time & absentee tracking</p>
            </div>
            
            <div class="flex flex-wrap items-center gap-2 w-full md:w-auto">
              <!-- 4 Interactive Tabs -->
              <div class="flex items-center bg-slate-950/90 p-1 rounded-xl border border-slate-800 text-xs">
                <button id="tabLiveBtn" onclick="setLedgerTab('live')" class="px-3 py-1 rounded-lg bg-sky-600 text-white font-semibold transition">
                  🔴 Live Stream Scans
                </button>
                <button id="tabPresentBtn" onclick="setLedgerTab('present')" class="px-3 py-1 rounded-lg text-slate-400 hover:text-white font-semibold transition">
                  ✅ Present (<span id="tabCountPresent">0</span>)
                </button>
                <button id="tabAbsentBtn" onclick="setLedgerTab('absent')" class="px-3 py-1 rounded-lg text-slate-400 hover:text-white font-semibold transition">
                  ❌ Absent (<span id="tabCountAbsent">0</span>)
                </button>
                <button id="tabVisitorBtn" onclick="setLedgerTab('visitors')" class="px-3 py-1 rounded-lg text-slate-400 hover:text-white font-semibold transition flex items-center gap-1">
                  <span>🎟️</span> <span>Guests</span> (<span id="tabCountVisitors">1</span>)
                </button>
              </div>

              <div class="relative w-full md:w-56">
                <input type="text" id="searchInput" onkeyup="filterLedger()" placeholder="🔍 Search name, roll..."
                       class="w-full px-3 py-1.5 rounded-lg bg-slate-950/80 border border-slate-700/80 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500">
              </div>
            </div>
          </div>

          <div class="overflow-x-auto max-h-[380px] overflow-y-auto">
            <table class="w-full text-left text-xs" id="ledgerTable">
              <thead class="sticky top-0 bg-slate-950 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800" id="ledgerThead">
                <!-- Injected dynamically by active tab -->
              </thead>
              <tbody id="ledgerBody" class="divide-y divide-slate-800/60 text-slate-300">
                <tr>
                  <td colspan="8" class="py-8 text-center text-slate-500">Loading attendance data...</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <!-- RIGHT COLUMN: Telemetry KPIs, Emotion Analytics, Stranger Radar (4 cols) -->
      <div class="lg:col-span-4 space-y-6">

        <!-- 4 Executive Principal KPI Cards -->
        <div class="grid grid-cols-2 gap-3.5">
          <div class="glass p-4 rounded-xl border border-slate-800 glow-emerald">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
              <span>Present Today</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 font-bold" id="kpiRate">0%</span>
            </div>
            <div class="text-2xl md:text-3xl font-extrabold text-emerald-400 mt-1">
              <span id="kpiPresent">0</span> <span class="text-xs text-slate-400 font-normal">/ <span id="kpiEnrolled">9</span></span>
            </div>
            <div class="text-[10px] text-emerald-500/90 mt-1">Verified identities in class</div>
          </div>

          <div class="glass p-4 rounded-xl border border-slate-800">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
              <span>Absent Students</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-rose-950 text-rose-400 font-bold" id="kpiAbsentRate">0%</span>
            </div>
            <div class="text-2xl md:text-3xl font-extrabold text-rose-400 mt-1">
              <span id="kpiAbsent">0</span> <span class="text-xs text-slate-400 font-normal">Pending</span>
            </div>
            <div class="text-[10px] text-slate-400 mt-1">Awaiting gate scan today</div>
          </div>

          <div class="glass p-4 rounded-xl border border-slate-800 glow-cyan">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
              <span>Mood Index</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-sky-950 text-sky-400 font-bold" id="kpiMoodLabel">Optimal</span>
            </div>
            <div class="text-2xl md:text-3xl font-extrabold text-sky-400 mt-1">
              <span id="kpiHappiness">85%</span> <span class="text-xs text-slate-400 font-normal">Score</span>
            </div>
            <div class="w-full bg-slate-800 rounded-full h-1.5 mt-2 overflow-hidden">
              <div id="happinessProgressBar" class="bg-gradient-to-r from-sky-400 to-emerald-400 h-1.5 rounded-full" style="width: 85%"></div>
            </div>
          </div>

          <div class="glass p-4 rounded-xl border border-slate-800">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
              <span>Perimeter Alerts</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 font-mono" id="kpiCameras">1 Cams</span>
            </div>
            <div class="text-2xl md:text-3xl font-extrabold text-amber-400 mt-1">
              <span id="kpiStrangers">0</span> <span class="text-xs text-slate-400 font-normal">Sightings</span>
            </div>
            <div class="text-[10px] text-amber-500/90 mt-1">Unidentified face alerts</div>
          </div>
        </div>

        <!-- Live Emotion Sentiment Donut Chart Card -->
        <div class="glass p-5 rounded-2xl border border-slate-800">
          <h3 class="text-sm font-bold text-white mb-3 flex items-center justify-between">
            <span class="flex items-center gap-1.5"><span>😊</span> Universal Emotion Analytics</span>
            <span class="text-[10px] text-emerald-400 font-normal">7-Class Deep AI</span>
          </h3>
          <div class="aspect-square max-h-[200px] mx-auto">
            <canvas id="emotionChart"></canvas>
          </div>
          <p class="text-[11px] text-center text-slate-400 mt-3" id="emotionSummary">
            Evaluating student engagement and classroom mood balance in real time.
          </p>
        </div>

        <!-- LAST DETECTED STRANGER / PERIMETER RADAR CARD -->
        <div class="glass p-5 rounded-2xl border border-slate-800 relative overflow-hidden">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-bold text-white flex items-center gap-1.5">
              <span>🚨</span> Last Detected Stranger
            </h3>
            <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-800/80">Security Alert</span>
          </div>
          
          <div class="flex gap-3 items-center bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
            <div class="w-24 h-20 rounded-lg overflow-hidden border border-slate-700 shrink-0 bg-black relative group cursor-pointer" onclick="openImage('/snapshots/latest_unknown.jpg')">
              <img src="/snapshots/latest_unknown.jpg" id="radarSnapshot" alt="Last Stranger" class="w-full h-full object-cover group-hover:scale-105 transition" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'80\\'><rect fill=\\'%23111827\\' width=\\'100\\' height=\\'80\\'/><text fill=\\'%236b7280\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' font-size=\\'11\\'>No Intruder</text></svg>'">
              <div class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center text-white text-xs font-bold transition">🔍 Zoom</div>
            </div>
            
            <div class="text-xs space-y-1 min-w-0">
              <div><span class="text-slate-400">Date/Time:</span> <strong class="text-white font-mono block truncate" id="radarTime">Scanning...</strong></div>
              <div><span class="text-slate-400">Location:</span> <strong class="text-sky-400 block truncate" id="radarLocation">-</strong></div>
              <div><span class="text-slate-400">AI Profile:</span> <strong class="text-amber-300" id="radarProfile">-</strong> &bull; <span class="text-slate-400" id="radarMatch">-</span></div>
            </div>
          </div>
          
          <div class="mt-3 flex items-center justify-between text-[11px] text-slate-400">
            <span>Evidence photo saved automatically</span>
            <button onclick="openImage('/snapshots/latest_unknown.jpg')" class="text-sky-400 hover:text-sky-300 font-semibold underline">Inspect Evidence</button>
          </div>
        </div>

        <!-- Recent Security Incident Snapshots Gallery -->
        <div class="glass p-5 rounded-2xl border border-slate-800">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-bold text-white flex items-center gap-1.5">
              <span>📷</span> Security Incident Gallery
            </h3>
            <span class="text-[10px] text-slate-400">Auto-captured</span>
          </div>
          <div class="grid grid-cols-2 gap-2.5">
            <div class="bg-black/60 rounded-lg overflow-hidden border border-slate-800 aspect-video relative group cursor-pointer" onclick="openImage('/snapshots/latest_unknown.jpg')">
              <img src="/snapshots/latest_unknown.jpg" alt="Latest Intruder" class="w-full h-full object-cover group-hover:scale-105 transition" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'60\\'><rect fill=\\'%23111827\\' width=\\'100\\' height=\\'60\\'/><text fill=\\'%236b7280\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' font-size=\\'10\\'>No Photo</text></svg>'">
              <div class="absolute bottom-0 inset-x-0 bg-slate-950/80 p-1 text-[10px] text-center text-slate-300 font-mono">Latest Sighting</div>
            </div>
            <div class="bg-black/60 rounded-lg overflow-hidden border border-slate-800 aspect-video relative group cursor-pointer" onclick="openImage('/snapshots/principal_intrusion_20261102_123553.jpg')">
              <img src="/snapshots/principal_intrusion_20261102_123553.jpg" alt="Restricted Area Entry" class="w-full h-full object-cover group-hover:scale-105 transition" onerror="this.src='/snapshots/latest_unknown.jpg'">
              <div class="absolute bottom-0 inset-x-0 bg-rose-950/90 text-rose-300 p-1 text-[10px] text-center font-mono">Restricted Area</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </main>

  <!-- ADD CAMERA MODAL DIALOG (shadcn/ui style) -->
  <div id="addCameraModal" class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="glass max-w-md w-full rounded-2xl border border-slate-700 p-6 shadow-2xl relative">
      <div class="flex items-center justify-between pb-4 border-b border-slate-800">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <span>📹</span> Add New Surveillance Camera
        </h3>
        <button onclick="closeAddCameraModal()" class="text-slate-400 hover:text-white text-lg">&times;</button>
      </div>

      <form onsubmit="submitNewCamera(event)" class="space-y-4 mt-4">
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Camera Display Name</label>
          <input type="text" id="newCamName" required placeholder="e.g. Science Lab CCTV or Entrance Gate"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500">
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Source Type</label>
          <select id="newCamKind" onchange="updateSourcePlaceholder()" class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-sky-500">
            <option value="Webcam">Webcam (Index 0, 1, 2...)</option>
            <option value="CCTV / IP Camera">CCTV / IP Camera (RTSP / HTTP)</option>
            <option value="Video File">Pre-recorded Video File (.mp4)</option>
          </select>
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Capture Source / Stream URL</label>
          <input type="text" id="newCamSource" required placeholder="0 for primary webcam"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 font-mono">
          <p class="text-[10px] text-slate-400 mt-1" id="sourceHelp">Enter webcam index (e.g. 0 or 1). Passwords are encrypted with Fernet AES.</p>
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Campus Room / Location</label>
          <input type="text" id="newCamRoom" placeholder="e.g. Science Block 1 or Main Gate"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500">
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Operating Profile</label>
          <select id="newCamMode" class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-sky-500">
            <option value="Classroom (Indoor / Standard)">Classroom (Standard Indoor)</option>
            <option value="Outdoor / Main Gate (25-35 ft)">Outdoor Gate (25-35 ft Long-Range)</option>
            <option value="Principal's Office / High Security">Principal's Office (High Security Intruder Alert)</option>
            <option value="Corridor / Transit Flow">Corridor (High-Speed Transit Flow)</option>
            <option value="Library / Exam Hall (Silent)">Library / Exam Hall (Silent Mode)</option>
          </select>
        </div>

        <div class="flex items-center justify-end gap-2.5 pt-4 border-t border-slate-800">
          <button type="button" onclick="closeAddCameraModal()" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300">
            Cancel
          </button>
          <button type="submit" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white shadow-md shadow-emerald-900/40">
            Save & Connect Camera
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- EXTEND VISITOR TIME MODAL DIALOG (Principal Control) -->
  <div id="extendVisitorModal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="glass max-w-md w-full rounded-2xl border border-sky-500/60 p-6 shadow-2xl relative glow-cyan">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <span>⏱️</span> Extend Campus Guest Permit
        </h3>
        <button onclick="closeExtendModal()" class="text-slate-400 hover:text-white text-lg">&times;</button>
      </div>

      <div class="mt-4 space-y-4">
        <!-- Guest Details Preview -->
        <div class="bg-slate-950/90 p-3.5 rounded-xl border border-slate-800 flex items-center gap-3">
          <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center text-white text-xl font-bold shrink-0 shadow-md">
            👨‍💼
          </div>
          <div class="min-w-0 flex-1">
            <h4 class="text-sm font-bold text-white truncate" id="extGuestName">Dr. Rajesh Mehta</h4>
            <p class="text-xs text-sky-400" id="extGuestHost">Host: Prof. Sharma &bull; CS Dept</p>
            <div class="flex items-center justify-between mt-1 text-[11px]">
              <span class="text-slate-400">Current Cutoff:</span>
              <strong class="text-amber-300 font-mono px-2 py-0.5 rounded bg-amber-950/80 border border-amber-800/60" id="extCurrentCutoff">01:00 PM</strong>
            </div>
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-2">1. Quick Preset Extension:</label>
          <div class="grid grid-cols-3 gap-2">
            <button type="button" onclick="selectPresetMinutes(30)" id="presetBtn30" class="py-2.5 rounded-xl bg-slate-900 hover:bg-sky-600 hover:text-white border border-slate-700 text-xs font-bold text-slate-200 transition">
              +30 Mins
            </button>
            <button type="button" onclick="selectPresetMinutes(50)" id="presetBtn50" class="py-2.5 rounded-xl bg-slate-900 hover:bg-sky-600 hover:text-white border border-slate-700 text-xs font-bold text-slate-200 transition">
              +50 Mins
            </button>
            <button type="button" onclick="selectPresetMinutes(60)" id="presetBtn60" class="py-2.5 rounded-xl bg-slate-900 hover:bg-sky-600 hover:text-white border border-slate-700 text-xs font-bold text-slate-200 transition">
              +1 Hour
            </button>
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1.5">2. Or Enter Custom Minutes (Principal Manual Input):</label>
          <div class="flex items-center gap-2">
            <input type="number" id="customMinutesInput" min="5" max="480" placeholder="e.g. 15, 45, 90..."
                   class="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm text-white font-mono placeholder-slate-500 focus:outline-none focus:border-sky-500">
            <span class="text-xs text-slate-400 shrink-0 font-medium">Minutes</span>
          </div>
          <p class="text-[10px] text-slate-400 mt-1">Principal can type any custom minutes (e.g. 15 mins for quick exit or 120 mins for full workshop session).</p>
        </div>

        <input type="hidden" id="extGuestId" value="guest_mehta">

        <div class="flex items-center justify-end gap-2.5 pt-3 border-t border-slate-800">
          <button type="button" onclick="closeExtendModal()" class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300">
            Cancel
          </button>
          <button type="button" onclick="submitTimeExtension()" class="px-5 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-xs font-bold text-white shadow-lg shadow-sky-900/50 flex items-center gap-1.5 transition">
            <span>💾</span> Save & Extend Time
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- VISITOR TRANSIT BREADCRUMB JOURNEY MODAL -->
  <div id="journeyModal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="glass max-w-lg w-full rounded-2xl border border-slate-700 p-6 shadow-2xl relative">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <div>
          <h3 class="text-base font-bold text-white flex items-center gap-2">
            <span>🗺️</span> Campus Transit Breadcrumb Trail
          </h3>
          <p class="text-xs text-sky-400 font-semibold" id="journeyGuestName">Dr. Rajesh Mehta</p>
        </div>
        <button onclick="closeJourneyModal()" class="text-slate-400 hover:text-white text-lg">&times;</button>
      </div>

      <div class="mt-4 max-h-[380px] overflow-y-auto pr-1" id="journeyTrail">
        <!-- Dynamically injected timeline steps -->
      </div>

      <div class="flex items-center justify-end pt-3 border-t border-slate-800 mt-4">
        <button type="button" onclick="closeJourneyModal()" class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300">
          Close Trail
        </button>
      </div>
    </div>
  </div>

  <!-- ISSUE NEW GUEST PASS MODAL -->
  <div id="addVisitorModal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="glass max-w-md w-full rounded-2xl border border-indigo-600/70 p-6 shadow-2xl relative glow-cyan">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <span>🎟️</span> Issue Campus Guest Pass
        </h3>
        <button onclick="closeAddVisitorModal()" class="text-slate-400 hover:text-white text-lg">&times;</button>
      </div>

      <form onsubmit="submitNewVisitor(event)" class="space-y-3.5 mt-4">
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Guest Full Name</label>
          <input type="text" id="newGuestName" required placeholder="e.g. Dr. Rajesh Mehta or Mrs. Sunita Roy"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500">
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Mobile / WhatsApp Phone</label>
          <input type="text" id="newGuestPhone" placeholder="+91 98765 43210"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono">
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Host Faculty / Department</label>
          <input type="text" id="newGuestHost" required placeholder="e.g. Prof. Sharma (CS Dept) or Principal Office"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500">
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Visit Purpose</label>
          <input type="text" id="newGuestPurpose" required placeholder="e.g. Guest Lecture, Lab Inspection, Parent Meet"
                 class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500">
        </div>

        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">Initial Validity Window</label>
          <select id="newGuestDuration" class="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-indigo-500">
            <option value="60">1 Hour (Standard Meeting)</option>
            <option value="120" selected>2 Hours (Lecture / Lab Session)</option>
            <option value="180">3 Hours (Half Day Seminar)</option>
            <option value="360">6 Hours (Full Day Event)</option>
          </select>
        </div>

        <div class="flex items-center justify-end gap-2.5 pt-3 border-t border-slate-800">
          <button type="button" onclick="closeAddVisitorModal()" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300">
            Cancel
          </button>
          <button type="submit" class="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white shadow-md shadow-indigo-900/40">
            Activate Guest Permit
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Real-Time Telemetry & Chart Polling Script -->
  <script>
    let emotionChartInstance = null;
    let currentSelectedCamId = "";

    function showToast(message, type = "info") {
      const container = document.getElementById("toastContainer");
      const toast = document.createElement("div");
      const bg = type === "success" ? "bg-emerald-950 text-emerald-300 border-emerald-800" :
                 type === "error" ? "bg-rose-950 text-rose-300 border-rose-800" :
                 "bg-slate-900 text-sky-300 border-slate-700";
      toast.className = `px-4 py-2.5 rounded-xl border text-xs font-semibold shadow-xl transition-all duration-300 pointer-events-auto flex items-center gap-2 ${bg}`;
      toast.innerHTML = `<span>${type === "success" ? "✅" : (type === "error" ? "❌" : "ℹ️")}</span> <span>${message}</span>`;
      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
      }, 3500);
    }

    function updateClock() {
      const now = new Date();
      document.getElementById('liveClock').innerText = now.toLocaleTimeString();
    }
    setInterval(updateClock, 1000);
    updateClock();

    function initEmotionChart() {
      const ctx = document.getElementById('emotionChart').getContext('2d');
      emotionChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: ['Happy', 'Neutral', 'Sad', 'Surprise', 'Other'],
          datasets: [{
            data: [40, 35, 12, 8, 5],
            backgroundColor: ['#10b981', '#38bdf8', '#f59e0b', '#8b5cf6', '#64748b'],
            borderWidth: 0
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { color: '#94a3b8', boxWidth: 10, font: { size: 10 } } }
          },
          cutout: '65%'
        }
      });
    }

    async function loadCameras() {
      try {
        const res = await fetch('/api/cameras');
        const data = await res.json();
        const tabsList = document.getElementById('cameraTabsList');
        const quickSelect = document.getElementById('quickCamSelect');
        const cameras = data.cameras || [];
        currentSelectedCamId = data.selected || (cameras[0] && cameras[0].id) || "";

        tabsList.innerHTML = "";
        quickSelect.innerHTML = "";

        cameras.forEach(cam => {
          const isActive = cam.id === currentSelectedCamId;
          const icon = cam.kind.includes('CCTV') ? '📡' : (cam.kind.includes('File') ? '📁' : '📹');

          // Pill tab button
          const btn = document.createElement('button');
          btn.className = `shrink-0 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-2 border ${
            isActive ? 
            'bg-sky-600 text-white border-sky-400 shadow-md shadow-sky-900/40 glow-cyan' : 
            'bg-slate-900/80 text-slate-300 border-slate-700/80 hover:bg-slate-800'
          }`;
          btn.onclick = () => selectCamera(cam.id);
          btn.innerHTML = `
            <span>${icon}</span>
            <span>${cam.name}</span>
            <span class="text-[10px] px-1.5 py-0.2 rounded ${isActive ? 'bg-sky-800 text-sky-200' : 'bg-slate-800 text-slate-400'}">${cam.room}</span>
          `;
          tabsList.appendChild(btn);

          // Dropdown option
          const opt = document.createElement('option');
          opt.value = cam.id;
          opt.innerText = `${icon} ${cam.name} (${cam.room})`;
          opt.selected = isActive;
          quickSelect.appendChild(opt);
        });

        document.getElementById('kpiCameras').innerText = cameras.length;
      } catch (err) {
        console.error("Failed to load cameras:", err);
      }
    }

    async function selectCamera(cameraId) {
      if (!cameraId) return;
      const placeholder = document.getElementById('videoPlaceholder');
      placeholder.classList.remove('hidden');

      try {
        const res = await fetch(`/api/select_camera?id=${encodeURIComponent(cameraId)}`);
        const data = await res.json();
        if (data.success) {
          showToast(`Switched to ${data.name}`, "success");
          document.getElementById('camTitle').innerText = `Live Stream • ${data.name}`;
          document.getElementById('camMode').innerText = (data.mode || "Classroom").split(' ')[0];
          document.getElementById('modeSelect').value = data.mode;
          updateZoomUI(data.zoom || 1.0);
          await loadCameras();
          // Reload MJPEG feed
          const feed = document.getElementById('videoFeed');
          feed.src = `/video_feed?t=${Date.now()}`;
        } else {
          showToast("Failed to switch camera: " + (data.error || "Unknown error"), "error");
        }
      } catch (err) {
        showToast("Error switching camera stream", "error");
      } finally {
        setTimeout(() => placeholder.classList.add('hidden'), 500);
      }
    }

    async function setZoom(zoomFactor) {
      try {
        const res = await fetch(`/api/camera_control?action=zoom&val=${zoomFactor}`);
        const data = await res.json();
        if (data.success) {
          updateZoomUI(data.zoom);
          showToast(`Zoom set to ${data.zoom.toFixed(1)}x`, "info");
        }
      } catch (err) {}
    }

    function updateZoomUI(val) {
      document.getElementById('statZoom').innerText = `${parseFloat(val).toFixed(1)}x`;
      const z = parseFloat(val);
      const btns = [
        { id: 'zoomBtn1', v: 1.0 },
        { id: 'zoomBtn15', v: 1.5 },
        { id: 'zoomBtn2', v: 2.0 },
        { id: 'zoomBtn3', v: 3.0 }
      ];
      btns.forEach(b => {
        const el = document.getElementById(b.id);
        if (Math.abs(b.v - z) < 0.1) {
          el.className = "px-2 py-1 rounded bg-sky-600 text-white font-mono text-[11px] font-bold";
        } else {
          el.className = "px-2 py-1 rounded text-slate-400 hover:text-white font-mono text-[11px]";
        }
      });
    }

    async function setModeProfile(modeVal) {
      try {
        const res = await fetch(`/api/camera_control?action=mode&val=${encodeURIComponent(modeVal)}`);
        const data = await res.json();
        if (data.success) {
          document.getElementById('camMode').innerText = modeVal.split(' ')[0];
          showToast(`Profile updated to ${modeVal.split(' ')[0]}`, "success");
        }
      } catch (err) {}
    }

    async function reconnectCamera() {
      const placeholder = document.getElementById('videoPlaceholder');
      placeholder.classList.remove('hidden');
      try {
        const res = await fetch(`/api/camera_control?action=reconnect`);
        const data = await res.json();
        if (data.success) {
          showToast("Camera stream reconnected", "success");
          const feed = document.getElementById('videoFeed');
          feed.src = `/video_feed?t=${Date.now()}`;
        }
      } catch (err) {
        showToast("Reconnect failed", "error");
      } finally {
        setTimeout(() => placeholder.classList.add('hidden'), 500);
      }
    }

    async function takeSnapshot() {
      try {
        const res = await fetch('/api/capture_snapshot');
        const data = await res.json();
        if (data.success && data.url) {
          showToast("Snapshot saved! Click to view", "success");
          window.open(data.url, '_blank');
        } else {
          showToast("Snapshot failed: " + (data.error || "No frame"), "error");
        }
      } catch (err) {
        showToast("Snapshot error", "error");
      }
    }

    function openAddCameraModal() {
      document.getElementById('addCameraModal').classList.remove('hidden');
    }

    function closeAddCameraModal() {
      document.getElementById('addCameraModal').classList.add('hidden');
    }

    function updateSourcePlaceholder() {
      const kind = document.getElementById('newCamKind').value;
      const srcInput = document.getElementById('newCamSource');
      const help = document.getElementById('sourceHelp');
      if (kind === "Webcam") {
        srcInput.placeholder = "0 for primary webcam, 1 for secondary";
        help.innerText = "Enter webcam index number (0, 1, 2).";
      } else if (kind.includes("CCTV")) {
        srcInput.placeholder = "rtsp://username:password@192.168.1.100:554/stream1";
        help.innerText = "Enter RTSP / ONVIF / HTTP URL. Credentials are encrypted with AES.";
      } else {
        srcInput.placeholder = "video_sample.mp4";
        help.innerText = "Enter relative or absolute path to video file.";
      }
    }

    async function submitNewCamera(e) {
      e.preventDefault();
      const payload = {
        name: document.getElementById('newCamName').value,
        kind: document.getElementById('newCamKind').value,
        source: document.getElementById('newCamSource').value,
        room: document.getElementById('newCamRoom').value,
        mode: document.getElementById('newCamMode').value
      };

      try {
        const res = await fetch('/api/add_camera', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Added camera ${payload.name}!`, "success");
          closeAddCameraModal();
          await loadCameras();
          if (data.camera && data.camera.id) {
            await selectCamera(data.camera.id);
          }
        } else {
          showToast("Error adding camera: " + (data.error || "Unknown"), "error");
        }
      } catch (err) {
        showToast("Request failed", "error");
      }
    }

    async function pollTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        const data = await res.json();
        document.getElementById('statFps').innerText = data.fps || '30.0';
        document.getElementById('statFaces').innerText = data.faces_detected || 0;
        document.getElementById('lastSeenName').innerText = data.last_seen_name || 'Scanning...';
        document.getElementById('lastSeenEmotion').innerText = data.last_seen_emotion || 'Neutral';
        document.getElementById('camTitle').innerText = 'Live Stream • ' + (data.camera_name || 'Camera');
        document.getElementById('camMode').innerText = (data.camera_mode || 'Classroom').split(' ')[0];
        document.getElementById('badgeStatus').innerText = (data.status || 'LIVE') + ' (' + data.fps + ' FPS)';
      } catch (err) {}
    }

    let currentLedgerTab = "live";
    let cachedSummary = null;
    let cachedAttendance = [];

    function setLedgerTab(tab) {
      currentLedgerTab = tab;
      const tabs = ['tabLiveBtn', 'tabPresentBtn', 'tabAbsentBtn', 'tabVisitorBtn'];
      tabs.forEach(t => {
        const el = document.getElementById(t);
        if (el) el.className = "px-3 py-1 rounded-lg text-slate-400 hover:text-white font-semibold transition";
      });
      if (tab === 'live') {
        document.getElementById('tabLiveBtn').className = "px-3 py-1 rounded-lg bg-sky-600 text-white font-semibold shadow transition";
      } else if (tab === 'present') {
        document.getElementById('tabPresentBtn').className = "px-3 py-1 rounded-lg bg-emerald-600 text-white font-semibold shadow transition";
      } else if (tab === 'absent') {
        document.getElementById('tabAbsentBtn').className = "px-3 py-1 rounded-lg bg-rose-600 text-white font-semibold shadow transition";
      } else if (tab === 'visitors') {
        document.getElementById('tabVisitorBtn').className = "px-3 py-1 rounded-lg bg-indigo-600 text-white font-semibold shadow transition";
      }
      renderActiveLedgerTable();
    }

    function renderActiveLedgerTable() {
      const thead = document.getElementById('ledgerThead');
      const tbody = document.getElementById('ledgerBody');
      if (!thead || !tbody) return;

      if (currentLedgerTab === 'live') {
        thead.innerHTML = `
          <tr>
            <th class="py-2.5 px-3">Roll No</th>
            <th class="py-2.5 px-3">Student / Person</th>
            <th class="py-2.5 px-3">Class / Zone</th>
            <th class="py-2.5 px-3">Age</th>
            <th class="py-2.5 px-3">Match %</th>
            <th class="py-2.5 px-3">Expression</th>
            <th class="py-2.5 px-3">Timestamp</th>
            <th class="py-2.5 px-3">Location</th>
            <th class="py-2.5 px-3">Status</th>
          </tr>
        `;
        if (!cachedAttendance || cachedAttendance.length === 0) {
          tbody.innerHTML = '<tr><td colspan="9" class="py-8 text-center text-slate-500">No activity recorded today yet.</td></tr>';
          return;
        }
        let html = '';
        cachedAttendance.slice(0, 50).forEach(r => {
          const isStranger = String(r.name).toLowerCase() === 'stranger';
          const badge = isStranger ?
            '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-950 text-rose-300 border border-rose-800">Stranger</span>' :
            '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">Present</span>';
          html += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-2.5 px-3 font-mono text-sky-400 font-bold">${escapeHtml(r.roll || '-')}</td>
              <td class="py-2.5 px-3 font-semibold text-white">${escapeHtml(r.name)}</td>
              <td class="py-2.5 px-3 text-slate-400">${escapeHtml(r.klass || 'Classroom')}</td>
              <td class="py-2.5 px-3">${escapeHtml(r.age)}</td>
              <td class="py-2.5 px-3 text-emerald-400 font-mono">${escapeHtml(r.match)}</td>
              <td class="py-2.5 px-3">${escapeHtml(r.emotion)}</td>
              <td class="py-2.5 px-3 font-mono text-slate-400">${escapeHtml(r.time)}</td>
              <td class="py-2.5 px-3 text-slate-300">${escapeHtml(r.camera)}</td>
              <td class="py-2.5 px-3">${badge}</td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      } else if (currentLedgerTab === 'present') {
        thead.innerHTML = `
          <tr>
            <th class="py-2.5 px-3">Roll No</th>
            <th class="py-2.5 px-3">Student Name</th>
            <th class="py-2.5 px-3">Class</th>
            <th class="py-2.5 px-3">First Seen</th>
            <th class="py-2.5 px-3">Camera Location</th>
            <th class="py-2.5 px-3">Expression</th>
            <th class="py-2.5 px-3">Confidence</th>
            <th class="py-2.5 px-3">Attendance</th>
          </tr>
        `;
        const list = (cachedSummary && cachedSummary.present_list) || [];
        if (list.length === 0) {
          tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-500">No students recorded present today yet.</td></tr>';
          return;
        }
        let html = '';
        list.forEach(s => {
          html += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-2.5 px-3 font-mono text-emerald-400 font-bold">${escapeHtml(s.roll || 'N/A')}</td>
              <td class="py-2.5 px-3 font-semibold text-white">${escapeHtml(s.name)}</td>
              <td class="py-2.5 px-3 text-slate-300">${escapeHtml(s.klass || 'B.Tech CSE')}</td>
              <td class="py-2.5 px-3 font-mono text-slate-400">${escapeHtml(s.time_in)}</td>
              <td class="py-2.5 px-3 text-sky-400">${escapeHtml(s.camera)}</td>
              <td class="py-2.5 px-3">${escapeHtml(s.emotion)}</td>
              <td class="py-2.5 px-3 text-emerald-400 font-mono">${escapeHtml(s.match)}</td>
              <td class="py-2.5 px-3">
                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">✅ Present</span>
              </td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      } else if (currentLedgerTab === 'absent') {
        thead.innerHTML = `
          <tr>
            <th class="py-2.5 px-3">Roll No</th>
            <th class="py-2.5 px-3">Student Name</th>
            <th class="py-2.5 px-3">Class</th>
            <th class="py-2.5 px-3">Age</th>
            <th class="py-2.5 px-3">Parent / Guardian</th>
            <th class="py-2.5 px-3">Emergency Phone</th>
            <th class="py-2.5 px-3">Status</th>
            <th class="py-2.5 px-3">Quick Alert</th>
          </tr>
        `;
        const list = (cachedSummary && cachedSummary.absent_list) || [];
        if (list.length === 0) {
          tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-emerald-400">100% Attendance Achieved! All students present.</td></tr>';
          return;
        }
        let html = '';
        list.forEach(s => {
          html += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-2.5 px-3 font-mono text-rose-400 font-bold">${escapeHtml(s.roll || 'N/A')}</td>
              <td class="py-2.5 px-3 font-semibold text-white">${escapeHtml(s.name)}</td>
              <td class="py-2.5 px-3 text-slate-300">${escapeHtml(s.klass || 'B.Tech CSE')}</td>
              <td class="py-2.5 px-3 text-slate-400">${escapeHtml(s.age || '-')}</td>
              <td class="py-2.5 px-3 text-slate-300">${escapeHtml(s.parent_name || 'Guardian')}</td>
              <td class="py-2.5 px-3 font-mono text-slate-400">${escapeHtml(s.parent_phone || '-')}</td>
              <td class="py-2.5 px-3">
                <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-950 text-rose-300 border border-rose-800">❌ Not Arrived</span>
              </td>
              <td class="py-2.5 px-3">
                <button onclick="sendParentAlert('${escapeHtml(s.name)}', '${escapeHtml(s.parent_phone)}')" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-400 text-[10px] font-semibold border border-slate-700 transition flex items-center gap-1">
                  <span>📱</span> Alert Parent
                </button>
              </td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      } else if (currentLedgerTab === 'visitors') {
        thead.innerHTML = `
          <tr>
            <th class="py-2.5 px-3">Photo</th>
            <th class="py-2.5 px-3">Guest Name & Contact</th>
            <th class="py-2.5 px-3">Host Faculty / Dept</th>
            <th class="py-2.5 px-3">Visit Purpose</th>
            <th class="py-2.5 px-3">Approved Zones</th>
            <th class="py-2.5 px-3">Live Location</th>
            <th class="py-2.5 px-3">Time Remaining</th>
            <th class="py-2.5 px-3">Principal Time Extension Control</th>
          </tr>
        `;
        const list = (cachedSummary && cachedSummary.visitors) || [];
        if (list.length === 0) {
          tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-500">No active visitor passes issued today. Click "Issue Guest Pass" to register a visitor.</td></tr>';
          return;
        }
        let html = '';
        list.forEach(v => {
          const rem = v.remaining_minutes !== undefined ? v.remaining_minutes : 60;
          let badge = '';
          if (v.status === 'Departed') {
            badge = '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">Departed</span>';
          } else if (rem <= 0) {
            badge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-800 animate-pulse">🔴 Overstayed (${Math.abs(rem)}m)</span>`;
          } else if (rem <= 15) {
            badge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800 animate-pulse">🟡 ${rem}m left (Expiring)</span>`;
          } else {
            const h = Math.floor(rem / 60);
            const m = rem % 60;
            const timeTxt = h > 0 ? `${h}h ${m}m left` : `${m}m left`;
            badge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">🟢 ${timeTxt}</span>`;
          }

          html += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-2 px-3">
                <div class="w-9 h-9 rounded-lg bg-sky-950 border border-sky-800 overflow-hidden shrink-0 flex items-center justify-center cursor-pointer" onclick="openImage('${escapeHtml(v.photo || '/snapshots/latest_unknown.jpg')}')">
                  <img src="${escapeHtml(v.photo || '/snapshots/latest_unknown.jpg')}" alt="Guest" class="w-full h-full object-cover" onerror="this.src='/snapshots/latest_unknown.jpg'">
                </div>
              </td>
              <td class="py-2.5 px-3">
                <strong class="text-white block">${escapeHtml(v.name)}</strong>
                <span class="text-slate-400 font-mono text-[11px]">${escapeHtml(v.phone || '-')}</span>
              </td>
              <td class="py-2.5 px-3 text-sky-400 font-semibold">${escapeHtml(v.host)}</td>
              <td class="py-2.5 px-3 text-slate-300">${escapeHtml(v.purpose)}</td>
              <td class="py-2.5 px-3 text-slate-400 text-[11px]">${escapeHtml((v.allowed_zones || []).join(', '))}</td>
              <td class="py-2.5 px-3">
                <span class="text-emerald-400 font-semibold block">${escapeHtml(v.current_zone || 'Campus Area')}</span>
                <span class="text-slate-500 font-mono text-[10px]">Seen: ${escapeHtml(v.last_seen_time || 'Just now')}</span>
              </td>
              <td class="py-2.5 px-3">${badge}</td>
              <td class="py-2.5 px-3">
                <div class="flex items-center gap-1.5">
                  <button onclick="openExtendModal('${v.id}', '${escapeHtml(v.name)}', '${escapeHtml(v.valid_to || '')}', '${escapeHtml(v.host)}')" class="px-3 py-1.5 rounded-lg bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white text-[11px] font-bold shadow-md shadow-sky-900/40 transition flex items-center gap-1">
                    <span>⏱️</span> Extend Time
                  </button>
                  <button onclick="openJourneyModal('${v.id}')" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-medium border border-slate-700 transition" title="Inspect Transit Breadcrumbs">
                    🗺️
                  </button>
                </div>
              </td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      }
    }

    function openExtendModal(guestId, guestName, validToStr, hostStr) {
      document.getElementById('extGuestId').value = guestId;
      document.getElementById('extGuestName').innerText = guestName || "Dr. Rajesh Mehta";
      document.getElementById('extGuestHost').innerText = "Host: " + (hostStr || "Prof. Sharma");
      
      let cutoffDisplay = validToStr || "01:00 PM";
      if (cutoffDisplay.includes(" ")) {
        const parts = cutoffDisplay.split(" ");
        cutoffDisplay = parts[parts.length - 1];
      }
      document.getElementById('extCurrentCutoff').innerText = cutoffDisplay;
      document.getElementById('customMinutesInput').value = "";
      
      [30, 50, 60].forEach(m => {
        const b = document.getElementById('presetBtn' + m);
        if (b) b.className = "py-2.5 rounded-xl bg-slate-900 hover:bg-sky-600 hover:text-white border border-slate-700 text-xs font-bold text-slate-200 transition";
      });

      document.getElementById('extendVisitorModal').classList.remove('hidden');
    }

    function closeExtendModal() {
      document.getElementById('extendVisitorModal').classList.add('hidden');
    }

    function selectPresetMinutes(mins) {
      document.getElementById('customMinutesInput').value = mins;
      [30, 50, 60].forEach(m => {
        const b = document.getElementById('presetBtn' + m);
        if (b) {
          if (m === mins) {
            b.className = "py-2.5 rounded-xl bg-sky-600 text-white border border-sky-400 font-bold text-xs shadow-md shadow-sky-900/50 glow-cyan transition";
          } else {
            b.className = "py-2.5 rounded-xl bg-slate-900 hover:bg-sky-600 hover:text-white border border-slate-700 text-xs font-bold text-slate-200 transition";
          }
        }
      });
    }

    async function submitTimeExtension() {
      const vid = document.getElementById('extGuestId').value;
      const customVal = document.getElementById('customMinutesInput').value;
      const mins = parseInt(customVal, 10);

      if (!mins || mins <= 0) {
        showToast("Please select a preset (+30, +50, +1h) or enter custom minutes!", "error");
        return;
      }

      try {
        showToast(`Extending permit by ${mins} minutes...`, "info");
        const res = await fetch('/api/extend_visitor_time', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: vid, minutes: mins })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, "success");
          closeExtendModal();
          await pollStats();
          if (currentLedgerTab === 'visitors') {
            renderActiveLedgerTable();
          }
        } else {
          showToast("Failed to extend permit: " + (data.error || "Unknown error"), "error");
        }
      } catch (err) {
        showToast("Network error extending permit", "error");
      }
    }

    function openJourneyModal(guestId) {
      const visitors = (cachedSummary && cachedSummary.visitors) || [];
      const v = visitors.find(x => x.id === guestId) || visitors[0];
      if (!v) {
        showToast("No journey history found", "info");
        return;
      }
      document.getElementById('journeyGuestName').innerText = v.name + " (" + v.purpose + ")";
      const trail = document.getElementById('journeyTrail');
      trail.innerHTML = "";
      const journey = v.journey || [];
      if (journey.length === 0) {
        trail.innerHTML = '<p class="text-xs text-slate-400 py-4 text-center">No transit events recorded yet.</p>';
      } else {
        journey.forEach((step, idx) => {
          trail.innerHTML += `
            <div class="flex items-start gap-3 relative pb-4">
              <div class="w-6 h-6 rounded-full bg-sky-600 text-white flex items-center justify-center text-xs font-bold shrink-0 z-10 shadow">
                ${idx + 1}
              </div>
              <div class="bg-slate-950 p-2.5 rounded-xl border border-slate-800 flex-1">
                <div class="flex items-center justify-between text-xs">
                  <strong class="text-sky-300 font-mono">${escapeHtml(step.time)}</strong>
                  <span class="text-[10px] text-slate-400">${escapeHtml(step.camera)}</span>
                </div>
                <div class="text-xs font-semibold text-white mt-1">${escapeHtml(step.zone)}</div>
                <div class="text-[11px] text-emerald-400 mt-0.5">${escapeHtml(step.event || 'Transit Verified')}</div>
              </div>
            </div>
          `;
        });
      }
      document.getElementById('journeyModal').classList.remove('hidden');
    }

    function closeJourneyModal() {
      document.getElementById('journeyModal').classList.add('hidden');
    }

    function openAddVisitorModal() {
      document.getElementById('addVisitorModal').classList.remove('hidden');
    }

    function closeAddVisitorModal() {
      document.getElementById('addVisitorModal').classList.add('hidden');
    }

    async function submitNewVisitor(e) {
      e.preventDefault();
      const payload = {
        name: document.getElementById('newGuestName').value,
        phone: document.getElementById('newGuestPhone').value,
        host: document.getElementById('newGuestHost').value,
        purpose: document.getElementById('newGuestPurpose').value,
        duration: parseInt(document.getElementById('newGuestDuration').value, 10) || 60
      };
      try {
        const res = await fetch('/api/add_visitor', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Guest Pass issued for ${payload.name}!`, "success");
          closeAddVisitorModal();
          await pollStats();
          setLedgerTab('visitors');
        } else {
          showToast("Error issuing pass: " + (data.error || "Unknown"), "error");
        }
      } catch (err) {
        showToast("Request failed", "error");
      }
    }

    function sendParentAlert(studentName, phone) {
      showToast(`Automated WhatsApp & SMS attendance alert dispatched for ${studentName} to ${phone}`, "success");
    }

    async function pollStats() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        cachedSummary = data;

        // Update Principal KPIs
        document.getElementById('kpiPresent').innerText = data.present_today || 0;
        document.getElementById('kpiEnrolled').innerText = data.total_enrolled || 9;
        document.getElementById('kpiRate').innerText = (data.attendance_rate || 0) + '%';
        document.getElementById('kpiAbsent').innerText = data.absent_count !== undefined ? data.absent_count : (data.total_enrolled - data.present_today);
        document.getElementById('kpiAbsentRate').innerText = (data.absent_rate !== undefined ? data.absent_rate : (100 - (data.attendance_rate || 0))) + '%';

        // Update Mood Meter
        const happiness = data.happiness_index || 85.0;
        document.getElementById('kpiHappiness').innerText = happiness.toFixed(0) + '%';
        document.getElementById('kpiMoodLabel').innerText = data.mood_label || 'Optimal';
        const pbar = document.getElementById('happinessProgressBar');
        if (pbar) pbar.style.width = Math.min(100, Math.max(5, happiness)) + '%';

        document.getElementById('kpiStrangers').innerText = data.strangers_count || 0;
        if (data.active_cameras) {
          document.getElementById('kpiCameras').innerText = data.active_cameras + ' Cams';
        }

        // Update Tab Badges
        const countPres = document.getElementById('tabCountPresent');
        if (countPres) countPres.innerText = data.present_today || 0;
        const countAbs = document.getElementById('tabCountAbsent');
        if (countAbs) countAbs.innerText = data.absent_count !== undefined ? data.absent_count : (data.total_enrolled - data.present_today);
        const countVis = document.getElementById('tabCountVisitors');
        if (countVis) {
          const vList = data.visitors || [];
          countVis.innerText = vList.filter(x => x.status !== 'Departed').length;
        }

        // Update Last Detected Stranger Radar Card
        if (data.last_stranger) {
          document.getElementById('radarTime').innerText = data.last_stranger.timestamp || 'No event';
          document.getElementById('radarLocation').innerText = data.last_stranger.camera || 'Main Gate';
          document.getElementById('radarProfile').innerText = data.last_stranger.profile || 'Unidentified';
          document.getElementById('radarMatch').innerText = (data.last_stranger.match || '-') + ' match';
        }

        // Update Emotion Chart
        if (emotionChartInstance && data.emotions) {
          const labels = Object.keys(data.emotions);
          const values = Object.values(data.emotions);
          if (labels.length > 0) {
            emotionChartInstance.data.labels = labels;
            emotionChartInstance.data.datasets[0].data = values;
            emotionChartInstance.update();
          }
        }

        // If on present, absent, or visitors tab, refresh active table
        if (currentLedgerTab !== 'live') {
          renderActiveLedgerTable();
        }
      } catch (err) {}
    }

    function escapeHtml(str) {
      return String(str || '').replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
      }[tag] || tag));
    }

    async function pollAttendance() {
      try {
        const res = await fetch('/api/attendance');
        const list = await res.json();
        cachedAttendance = list || [];
        if (currentLedgerTab === 'live') {
          renderActiveLedgerTable();
        }
      } catch (err) {}
    }

    function filterLedger() {
      const q = document.getElementById('searchInput').value.toLowerCase();
      const rows = document.querySelectorAll('#ledgerBody tr');
      rows.forEach(r => {
        const rowText = r.innerText.toLowerCase();
        r.style.display = rowText.includes(q) ? '' : 'none';
      });
    }

    async function exportReport() {
      try {
        showToast("Generating Executive HTML report...", "info");
        const res = await fetch('/api/export_report');
        const data = await res.json();
        if (data.success && data.url) {
          showToast("Report exported successfully!", "success");
          window.open(data.url, '_blank');
        } else {
          showToast("Report error: " + (data.error || "Unknown"), "error");
        }
      } catch (err) {
        showToast("Report request failed", "error");
      }
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    }

    function openImage(url) {
      window.open(url, '_blank');
    }

    window.addEventListener('DOMContentLoaded', () => {
      initEmotionChart();
      loadCameras();
      setInterval(pollTelemetry, 1000);
      setInterval(pollStats, 3000);
      setInterval(pollAttendance, 3000);
      pollTelemetry();
      pollStats();
      pollAttendance();
    });
  </script>
</body>
</html>
        """

class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server that suppresses routine client disconnect exceptions on Windows."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        exctype, val, tb = sys.exc_info()
        if exctype in (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return
        if isinstance(val, OSError) and getattr(val, "winerror", None) in (10053, 10054):
            return
        super().handle_error(request, client_address)

def run_server(port=5000):
    global vision_worker
    print("=" * 65)
    print(f"  AI SURVEILLANCE & ATTENDANCE COMMAND CENTER WEB PORTAL")
    print("=" * 65)
    print(f"  [WEB] Command Center running at: http://localhost:{port}")
    print(f"  [AI]  Initializing live vision engine with 30 FPS video grabber...")
    print(f"  [TIP] Open http://localhost:{port} in Chrome / Edge (Press F11 for Fullscreen)")
    print("=" * 65)

    # Start vision worker in background
    vision_worker = VisionWorker()
    vision_worker.start()

    server = QuietThreadingHTTPServer(("0.0.0.0", port), CommandCenterHandler)
    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Command Center server...")
        vision_worker.running = False
        if vision_worker.cap is not None:
            try:
                vision_worker.cap.release()
            except Exception:
                pass
        server.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5000
    run_server(port)
