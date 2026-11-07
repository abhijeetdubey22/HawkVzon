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
        self.load_config()

        # Load database safely (support encrypted .face files and fallback to .npy)
        import face_recognition
        from emotion_predictor import EmotionClassifier
        self.face_recognition = face_recognition

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
        threading.Thread(target=self._run, daemon=True, name="VisionWorkerThread").start()

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
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(self.source)
                elif isinstance(self.source, str) and (self.source.startswith("rtsp") or self.source.startswith("http")):
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|buffer_size;1024000|max_delay;500000"
                    self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(self.source)
                else:
                    self.cap = cv2.VideoCapture(self.source)

                if self.cap is not None and self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
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

    def _run(self):
        global current_jpeg_frame, latest_telemetry
        self._open_camera()

        prev_time = time.time()
        fps = 0.0
        cached_faces = []
        frame_idx = 0
        consecutive_failures = 0

        while self.running:
            if self.cap is None or not self.cap.isOpened():
                with telemetry_lock:
                    latest_telemetry["status"] = "Connecting..."
                standby = np.zeros((720, 1280, 3), dtype=np.uint8)
                standby[:] = (15, 23, 42)  # Slate 900 background
                cv2.putText(standby, "CAMERA CONNECTING / STANDBY", (370, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (148, 163, 184), 2)
                cv2.putText(standby, f"Target: {self.camera_name} [{self.camera_mode}]", (350, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (56, 189, 248), 1)
                cv2.putText(standby, "Select another camera or click Reconnect if offline...", (360, 420), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 116, 139), 1)
                ret_enc, jpeg = cv2.imencode(".jpg", standby, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ret_enc:
                    with video_lock:
                        current_jpeg_frame = jpeg.tobytes()
                time.sleep(1.0)
                self._open_camera()
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    with telemetry_lock:
                        latest_telemetry["status"] = "Signal Lost (Reconnecting)"
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    consecutive_failures = 0
                time.sleep(0.05)
                continue

            consecutive_failures = 0
            with telemetry_lock:
                latest_telemetry["status"] = "Live"

            # Apply digital zoom crop
            if getattr(self, "zoom", 1.0) > 1.0:
                zh, zw = frame.shape[:2]
                cw, ch = int(zw / self.zoom), int(zh / self.zoom)
                cx, cy = zw // 2, zh // 2
                x1 = max(0, min(zw - cw, cx - cw // 2))
                y1 = max(0, min(zh - ch, cy - ch // 2))
                frame = cv2.resize(frame[y1:y1 + ch, x1:x1 + cw], (zw, zh), interpolation=cv2.INTER_LINEAR)

            frame_idx += 1
            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - prev_time, 1e-5))
            prev_time = now

            # Determine mode scale
            is_outdoor = "outdoor" in self.camera_mode.lower() or "gate" in self.camera_mode.lower()
            is_corridor = "corridor" in self.camera_mode.lower() or "transit" in self.camera_mode.lower()
            is_principal = "principal" in self.camera_mode.lower() or "principal" in self.camera_name.lower()

            process_interval = 2 if is_corridor else 3
            detection_scale = 0.70 if is_outdoor else 0.50
            inv_scale = 1.0 / detection_scale

            # Run heavy AI detection on interval
            if frame_idx % process_interval == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                small = cv2.resize(rgb, (0, 0), fx=detection_scale, fy=detection_scale)
                face_locs_small = self.face_recognition.face_locations(small, number_of_times_to_upsample=1, model="hog")

                full_locs = []
                for loc in face_locs_small:
                    t, r, b, l = loc
                    full_locs.append((
                        int(max(0, t * inv_scale)),
                        int(min(rgb.shape[1], r * inv_scale)),
                        int(min(rgb.shape[0], b * inv_scale)),
                        int(max(0, l * inv_scale))
                    ))

                # Compute encodings on full resolution
                encodings = self.face_recognition.face_encodings(rgb, full_locs)
                new_faces = []

                for enc, loc in zip(encodings, full_locs):
                    if len(self.known_encodings) > 0:
                        dist = self.face_recognition.face_distance(self.known_encodings, enc)
                        best_idx = np.argmin(dist) if len(dist) > 0 else -1
                        confidence = (1 - dist[best_idx]) * 100 if best_idx >= 0 else 0
                    else:
                        dist = np.empty((0,))
                        best_idx = -1
                        confidence = 0

                    t, r, b, l = loc
                    roi = frame[t:b, l:r]
                    name = "Stranger"
                    age = "-"
                    color = (0, 0, 255)  # Red

                    if best_idx >= 0 and confidence >= 50.0:
                        name = str(self.known_names[best_idx])
                        age = str(self.known_ages[best_idx]) if best_idx < len(self.known_ages) else "-"
                        color = (0, 255, 0)  # Green

                    # Emotion inference
                    emotion_str = "Neutral"
                    if roi.size > 0 and self.emotion_classifier is not None:
                        try:
                            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                            resized = cv2.resize(gray, (48, 48))
                            norm = resized.astype("float32") / 255.0
                            label, conf, _ = self.emotion_classifier.predict(norm)
                            emotion_str = label
                        except Exception:
                            pass

                    # Bounding Box label
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
                    if name != "Stranger" and (now_ts - self.last_logged.get(name, 0) > 30.0):
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
                            cv2.imwrite(os.path.join(SNAPSHOTS_DIR, snap_name), frame)
                            cv2.imwrite(os.path.join(SNAPSHOTS_DIR, "latest_unknown.jpg"), frame)
                        except Exception:
                            pass

                cached_faces = new_faces

                # Update live telemetry
                with telemetry_lock:
                    latest_telemetry["faces_detected"] = len(cached_faces)
                    if cached_faces:
                        latest_telemetry["last_seen_name"] = cached_faces[0]["name"]
                        latest_telemetry["last_seen_emotion"] = cached_faces[0]["emotion"]

            # Draw AI bounding boxes with high-contrast 2-pass outline
            for face in cached_faces:
                l, t, r, b = face["box"]
                color = face["color"]
                label = face["label"]
                cv2.rectangle(frame, (l, t), (r, b), color, 2)
                y_pos = max(24, t - 10)
                # 2-pass black stroke for readability
                cv2.putText(frame, label, (l, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
                cv2.putText(frame, label, (l, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # Draw FPS, Zoom, & Mode Watermark
            watermark = f"FPS: {fps:.1f} | {self.camera_name} [{self.camera_mode.split(' ')[0]}]"
            if self.zoom > 1.0:
                watermark += f" | {self.zoom:.1f}x Zoom"
            cv2.putText(frame, watermark, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4)
            cv2.putText(frame, watermark, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

            with telemetry_lock:
                latest_telemetry["fps"] = round(fps, 1)
                latest_telemetry["camera_id"] = self.camera_id
                latest_telemetry["camera_name"] = self.camera_name
                latest_telemetry["camera_mode"] = self.camera_mode
                latest_telemetry["zoom"] = self.zoom

            # Encode frame to JPEG
            ret_enc, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if ret_enc:
                with video_lock:
                    current_jpeg_frame = jpeg.tobytes()

            time.sleep(0.005)

# --------------------------------------------------------------------------
# Modern Web Dashboard HTTP Request Handler
# --------------------------------------------------------------------------
class CommandCenterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence verbose terminal access logs
        return

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

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
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.render_dashboard().encode("utf-8"))

        elif path == "/video_feed":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, private")
            self.end_headers()
            try:
                while True:
                    with video_lock:
                        frame = current_jpeg_frame
                    if frame is not None:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
                    time.sleep(0.033)  # ~30 FPS
            except (BrokenPipeError, ConnectionResetError):
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

    def get_attendance_data(self):
        records = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    rows = list(csv.reader(f))[1:]
                for row in reversed(rows[-100:]):
                    if len(row) >= 5:
                        records.append({
                            "name": row[0],
                            "age": row[1],
                            "match": row[2],
                            "emotion": row[3],
                            "time": row[4],
                            "camera": row[5] if len(row) > 5 else "Default"
                        })
            except Exception:
                pass
        return records

    def get_summary_stats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        present_names = set()
        stranger_sightings = 0
        emotions = {}

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    for row in reader:
                        if len(row) >= 5 and row[4].startswith(today):
                            name = row[0]
                            emotion = row[3]
                            if name.lower() in ("stranger", "unknown"):
                                stranger_sightings += 1
                            else:
                                present_names.add(name)
                            if emotion and emotion not in ("-", "Unknown"):
                                emotions[emotion] = emotions.get(emotion, 0) + 1
            except Exception:
                pass

        # Enrolled count
        students_file = os.path.join(DATA_DIR, "students.json")
        enrolled_count = 9
        if os.path.exists(students_file):
            try:
                with open(students_file, "r", encoding="utf-8") as sf:
                    enrolled_count = len(json.load(sf))
            except Exception:
                pass

        # Camera count
        cam_info = get_cameras_list()
        cam_count = len(cam_info.get("cameras", []))

        return {
            "total_enrolled": enrolled_count,
            "present_today": len(present_names),
            "attendance_rate": round(len(present_names) / max(enrolled_count, 1) * 100, 1),
            "strangers_count": stranger_sightings,
            "active_cameras": cam_count,
            "emotions": emotions
        }

    def render_dashboard(self):
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
          <h1 class="text-base md:text-xl font-extrabold tracking-tight text-white">Campus AI Surveillance Command Center</h1>
          <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-950/90 text-emerald-400 border border-emerald-800/60 flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse-fast"></span>
            <span id="badgeStatus">LIVE</span>
          </span>
        </div>
        <p class="text-[11px] text-slate-400">Autonomous Facial Recognition, Emotion Analytics & Campus Security Hub</p>
      </div>
    </div>

    <!-- Header Actions -->
    <div class="flex items-center gap-2.5">
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

        <!-- Real-Time Attendance Ledger Card -->
        <div class="glass rounded-2xl p-5 border border-slate-800">
          <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-3 mb-4">
            <div>
              <h2 class="text-base font-bold text-white flex items-center gap-2">
                <span>📋</span> Real-Time Attendance Ledger
              </h2>
              <p class="text-xs text-slate-400">Automated student detections authenticated via biometric face landmarks</p>
            </div>
            <div class="relative w-full md:w-64">
              <input type="text" id="searchInput" onkeyup="filterLedger()" placeholder="🔍 Quick search student name..."
                     class="w-full px-3.5 py-2 rounded-lg bg-slate-950/80 border border-slate-700/80 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500">
            </div>
          </div>

          <div class="overflow-x-auto max-h-[360px] overflow-y-auto">
            <table class="w-full text-left text-xs" id="ledgerTable">
              <thead class="sticky top-0 bg-slate-950 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
                <tr>
                  <th class="py-2.5 px-3">Student Name</th>
                  <th class="py-2.5 px-3">Age</th>
                  <th class="py-2.5 px-3">Confidence</th>
                  <th class="py-2.5 px-3">Expression</th>
                  <th class="py-2.5 px-3">Timestamp</th>
                  <th class="py-2.5 px-3">Camera / Location</th>
                  <th class="py-2.5 px-3">Status</th>
                </tr>
              </thead>
              <tbody id="ledgerBody" class="divide-y divide-slate-800/60 text-slate-300">
                <tr>
                  <td colspan="7" class="py-8 text-center text-slate-500">Loading attendance data...</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <!-- RIGHT COLUMN: Telemetry KPIs, Emotion Donut, & Stranger Snapshots (4 cols) -->
      <div class="lg:col-span-4 space-y-6">

        <!-- 4 Quick Telemetry Cards -->
        <div class="grid grid-cols-2 gap-3.5">
          <div class="glass p-4 rounded-xl border border-slate-800 glow-emerald">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Present Today</div>
            <div class="text-2xl md:text-3xl font-extrabold text-emerald-400 mt-1" id="kpiPresent">0</div>
            <div class="text-[10px] text-emerald-500/90 mt-1" id="kpiRate">0% Rate</div>
          </div>
          <div class="glass p-4 rounded-xl border border-slate-800">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Enrolled</div>
            <div class="text-2xl md:text-3xl font-extrabold text-white mt-1" id="kpiEnrolled">9</div>
            <div class="text-[10px] text-slate-500 mt-1">Verified identities</div>
          </div>
          <div class="glass p-4 rounded-xl border border-slate-800">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Unknown Strangers</div>
            <div class="text-2xl md:text-3xl font-extrabold text-sky-400 mt-1" id="kpiStrangers">0</div>
            <div class="text-[10px] text-sky-500/90 mt-1">Perimeter sightings</div>
          </div>
          <div class="glass p-4 rounded-xl border border-slate-800">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Active Cameras</div>
            <div class="text-2xl md:text-3xl font-extrabold text-amber-400 mt-1" id="kpiCameras">1</div>
            <div class="text-[10px] text-amber-500 mt-1">Multi-stream ready</div>
          </div>
        </div>

        <!-- Live Emotion Sentiment Donut Chart Card -->
        <div class="glass p-5 rounded-2xl border border-slate-800">
          <h3 class="text-sm font-bold text-white mb-3 flex items-center justify-between">
            <span class="flex items-center gap-1.5"><span>😊</span> Universal Emotion Analytics</span>
            <span class="text-[10px] text-emerald-400 font-normal">7-Class Deep AI</span>
          </h3>
          <div class="aspect-square max-h-[220px] mx-auto">
            <canvas id="emotionChart"></canvas>
          </div>
          <p class="text-[11px] text-center text-slate-400 mt-3" id="emotionSummary">
            Evaluating student engagement and classroom mood balance in real time.
          </p>
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

    async function pollStats() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('kpiPresent').innerText = data.present_today || 0;
        document.getElementById('kpiEnrolled').innerText = data.total_enrolled || 9;
        document.getElementById('kpiRate').innerText = (data.attendance_rate || 0) + '% Rate';
        document.getElementById('kpiStrangers').innerText = data.strangers_count || 0;
        if (data.active_cameras) {
          document.getElementById('kpiCameras').innerText = data.active_cameras;
        }

        if (emotionChartInstance && data.emotions) {
          const labels = Object.keys(data.emotions);
          const values = Object.values(data.emotions);
          if (labels.length > 0) {
            emotionChartInstance.data.labels = labels;
            emotionChartInstance.data.datasets[0].data = values;
            emotionChartInstance.update();
          }
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
        const tbody = document.getElementById('ledgerBody');
        if (!list || list.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" class="py-8 text-center text-slate-500">No attendance entries recorded today yet.</td></tr>';
          return;
        }
        let html = '';
        list.slice(0, 50).forEach(r => {
          const isStranger = String(r.name).toLowerCase() === 'stranger';
          const badge = isStranger ? 
            '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-950 text-rose-300 border border-rose-800">Stranger</span>' : 
            '<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">Present</span>';
          html += `
            <tr class="hover:bg-slate-800/40 transition">
              <td class="py-2.5 px-3 font-semibold text-white">${escapeHtml(r.name)}</td>
              <td class="py-2.5 px-3">${escapeHtml(r.age)}</td>
              <td class="py-2.5 px-3 text-emerald-400 font-mono">${escapeHtml(r.match)}</td>
              <td class="py-2.5 px-3">${escapeHtml(r.emotion)}</td>
              <td class="py-2.5 px-3 font-mono text-slate-400">${escapeHtml(r.time)}</td>
              <td class="py-2.5 px-3">${escapeHtml(r.camera)}</td>
              <td class="py-2.5 px-3">${badge}</td>
            </tr>
          `;
        });
        tbody.innerHTML = html;
      } catch (err) {}
    }

    function filterLedger() {
      const q = document.getElementById('searchInput').value.toLowerCase();
      const rows = document.querySelectorAll('#ledgerBody tr');
      rows.forEach(r => {
        const name = r.children[0]?.innerText.toLowerCase() || '';
        r.style.display = name.includes(q) ? '' : 'none';
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

    server = ThreadingHTTPServer(("0.0.0.0", port), CommandCenterHandler)
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
