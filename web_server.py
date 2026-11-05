"""
Web Surveillance Command Center Server.
High-performance local web server powering the browser-based Command Center.
Streams live AI-annotated video feeds (30 FPS) and provides real-time REST telemetry.
"""
import os
import sys
import time
import json
import csv
import threading
import mimetypes
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

# Global video state shared with HTTP handler
video_lock = threading.Lock()
telemetry_lock = threading.Lock()
current_jpeg_frame = None
latest_telemetry = {
    "fps": 0.0,
    "faces_detected": 0,
    "last_seen_name": "None",
    "last_seen_emotion": "None",
    "camera_name": "Default Camera",
    "camera_mode": "Classroom (Indoor / Standard)",
    "status": "Initializing"
}

# --------------------------------------------------------------------------
# AI Vision Worker Thread
# --------------------------------------------------------------------------
class VisionWorker:
    def __init__(self):
        self.running = True
        self.cap = None
        self.source = 0
        self.camera_name = "Camera 0"
        self.camera_mode = "Classroom (Indoor / Standard)"
        self.load_config()

        # Load database safely
        import face_recognition
        from emotion_predictor import EmotionClassifier
        self.face_recognition = face_recognition
        
        enc_path = os.path.join(BASE_DIR, "known_face_encodings.npy")
        names_path = os.path.join(BASE_DIR, "known_face_names.npy")
        ages_path = os.path.join(BASE_DIR, "known_face_ages.npy")

        self.known_encodings = np.load(enc_path, allow_pickle=True) if os.path.exists(enc_path) else np.empty((0, 128))
        self.known_names = np.load(names_path, allow_pickle=True) if os.path.exists(names_path) else np.array([])
        self.known_ages = np.load(ages_path, allow_pickle=True) if os.path.exists(ages_path) else ["-"] * len(self.known_names)
        
        model_path = os.path.join(BASE_DIR, "emotion_model.hdf5")
        self.emotion_classifier = EmotionClassifier(model_path) if os.path.exists(model_path) else None
        
        self.last_spoken = {}
        self.last_logged = {}
        self.last_unknown_snapshot = 0

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    cams = cfg.get("cameras", [])
                    sel_id = cfg.get("selected")
                    target = next((c for c in cams if c.get("id") == sel_id), cams[0] if cams else None)
                    if target:
                        src = target.get("source", 0)
                        self.source = int(src) if str(src).isdigit() else src
                        self.camera_name = target.get("name", "Camera")
                        self.camera_mode = target.get("mode", "Classroom (Indoor / Standard)")
                        self.zoom = float(target.get("zoom", 1.0))
            except Exception:
                pass

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _open_camera(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        try:
            if isinstance(self.source, int) and os.name == "nt":
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.source)
            elif isinstance(self.source, str) and self.source.startswith("rtsp"):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|buffer_size;1024000|max_delay;500000"
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
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
                standby[:] = (15, 23, 42) # Slate 900 background
                cv2.putText(standby, "CAMERA CONNECTING / STANDBY", (390, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (148, 163, 184), 2)
                cv2.putText(standby, f"Active Profile: {self.camera_mode}", (420, 385), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (56, 189, 248), 1)
                cv2.putText(standby, "Waiting for camera capture index 0 or RTSP stream...", (410, 425), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 116, 139), 1)
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
                    dist = self.face_recognition.face_distance(self.known_encodings, enc)
                    best_idx = np.argmin(dist) if len(dist) > 0 else -1
                    confidence = (1 - dist[best_idx]) * 100 if best_idx >= 0 else 0

                    t, r, b, l = loc
                    roi = frame[t:b, l:r]
                    name = "Stranger"
                    age = "-"
                    color = (0, 0, 255) # Red

                    if best_idx >= 0 and confidence >= 50.0:
                        name = str(self.known_names[best_idx])
                        age = str(self.known_ages[best_idx]) if best_idx < len(self.known_ages) else "-"
                        color = (0, 255, 0) # Green

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

                    # Log to CSV with cooldown
                    if now - self.last_logged.get(name, 0) > 30.0:
                        self.last_logged[name] = now
                        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                            csv.writer(f).writerow([name, age, f"{confidence:.1f}%", emotion_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self.camera_name])

                    # Snapshot stranger with cooldown
                    if name == "Stranger" and (now - self.last_unknown_snapshot > 12.0):
                        self.last_unknown_snapshot = now
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        prefix = "principal_intrusion" if is_principal else "unknown"
                        cv2.imwrite(os.path.join(SNAPSHOTS_DIR, f"{prefix}_{ts}.jpg"), frame)
                        cv2.imwrite(os.path.join(SNAPSHOTS_DIR, "latest_unknown.jpg"), frame)

                    with telemetry_lock:
                        latest_telemetry["last_seen_name"] = name
                        latest_telemetry["last_seen_emotion"] = emotion_str

                cached_faces = new_faces
                with telemetry_lock:
                    latest_telemetry["faces_detected"] = len(cached_faces)

            # Draw 2-Pass High-Contrast Overlays
            for face in cached_faces:
                l, t, r, b = face["box"]
                color = face["color"]
                label = face["label"]
                cv2.rectangle(frame, (l, t), (r, b), color, 2)
                y_pos = max(24, t - 10)
                # 2-pass black stroke for outdoor readability
                cv2.putText(frame, label, (l, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
                cv2.putText(frame, label, (l, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # Draw FPS & Mode Watermark
            watermark = f"FPS: {fps:.1f} | {self.camera_name} [{self.camera_mode.split(' ')[0]}]"
            cv2.putText(frame, watermark, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4)
            cv2.putText(frame, watermark, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

            with telemetry_lock:
                latest_telemetry["fps"] = round(fps, 1)
                latest_telemetry["camera_name"] = self.camera_name
                latest_telemetry["camera_mode"] = self.camera_mode

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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

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
                    time.sleep(0.033) # ~30 FPS
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif path == "/api/telemetry":
            with telemetry_lock:
                telemetry_data = latest_telemetry.copy()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(telemetry_data).encode("utf-8"))

        elif path == "/api/attendance":
            records = self.get_attendance_data()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(records).encode("utf-8"))

        elif path == "/api/stats":
            stats = self.get_summary_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))

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
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "url": f"/exports/{fname}"}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        else:
            self.send_error(404, "Page Not Found")

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

        return {
            "total_enrolled": enrolled_count,
            "present_today": len(present_names),
            "attendance_rate": round(len(present_names) / max(enrolled_count, 1) * 100, 1),
            "strangers_count": stranger_sightings,
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
    .glass { backdrop-filter: blur(12px); background: rgba(15, 23, 42, 0.82); border: 1px solid rgba(51, 65, 85, 0.6); }
    .glow-cyan { box-shadow: 0 0 25px -5px rgba(56, 189, 248, 0.25); }
    .glow-emerald { box-shadow: 0 0 20px -5px rgba(16, 185, 129, 0.3); }
  </style>
</head>
<body class="bg-surface-canvas text-slate-100 min-h-screen font-sans antialiased">

  <!-- Top Glass Command Bar -->
  <header class="sticky top-0 z-50 glass border-b border-slate-800/80 px-6 py-3.5 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-400 to-blue-600 flex items-center justify-center shadow-lg shadow-sky-500/20 text-white font-black text-lg">
        AI
      </div>
      <div>
        <div class="flex items-center gap-2.5">
          <h1 class="text-lg md:text-xl font-bold tracking-tight text-white">Campus AI Surveillance Command Center</h1>
          <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-950/90 text-emerald-400 border border-emerald-800/60 flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span id="badgeStatus">LIVE 30 FPS</span>
          </span>
        </div>
        <p class="text-xs text-slate-400">Autonomous Facial Recognition, Emotion Analytics & Campus Security Hub</p>
      </div>
    </div>

    <!-- Right Controls -->
    <div class="flex items-center gap-3">
      <div class="hidden md:flex items-center px-3.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 gap-2">
        <span>🕒</span>
        <span id="liveClock" class="font-mono">10:30:00 AM</span>
      </div>
      <button onclick="exportReport()" class="px-3.5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold transition flex items-center gap-1.5 shadow-md shadow-sky-900/40">
        <span>📊</span> Executive Report
      </button>
      <button onclick="toggleFullscreen()" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition text-sm">
        ⛶
      </button>
    </div>
  </header>

  <!-- Main Grid Layout -->
  <main class="max-w-[1800px] mx-auto p-4 md:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- LEFT COLUMN: Live Cinema Video Stream + Attendance Ledger (8 cols) -->
    <div class="lg:col-span-8 space-y-6">

      <!-- Live Video Cinema Player Card -->
      <div class="glass rounded-2xl overflow-hidden glow-cyan border border-slate-800">
        <div class="bg-slate-950/90 px-4 py-3 flex items-center justify-between border-b border-slate-800/80">
          <div class="flex items-center gap-2">
            <span class="text-rose-500 font-bold animate-ping text-xs">●</span>
            <span class="text-xs font-semibold uppercase tracking-wider text-slate-300" id="camTitle">Live Stream &bull; Camera 0</span>
            <span class="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-sky-400 font-mono" id="camMode">Classroom (Indoor)</span>
          </div>
          <div class="flex items-center gap-3 text-xs text-slate-400 font-mono">
            <span>FPS: <strong class="text-emerald-400" id="statFps">30.0</strong></span>
            <span>Faces: <strong class="text-sky-400" id="statFaces">0</strong></span>
          </div>
        </div>

        <!-- Video Canvas Stream -->
        <div class="relative bg-black aspect-video flex items-center justify-center overflow-hidden">
          <img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed" class="w-full h-full object-cover">
          <div id="videoPlaceholder" class="hidden absolute inset-0 bg-slate-950/90 flex flex-col items-center justify-center text-slate-400 space-y-2">
            <span class="text-3xl animate-spin">⏳</span>
            <p class="text-sm font-medium">Connecting to Camera Stream...</p>
          </div>
        </div>

        <!-- Bottom Stream Toolbar -->
        <div class="bg-slate-900/90 p-3.5 flex items-center justify-between text-xs border-t border-slate-800/80">
          <div class="flex items-center gap-2">
            <span class="text-slate-400">Last Identified:</span>
            <span class="font-bold text-white px-2.5 py-1 rounded bg-slate-800" id="lastSeenName">Scanning...</span>
            <span class="text-slate-400">Emotion:</span>
            <span class="font-semibold text-emerald-400 px-2 py-1 rounded bg-emerald-950/60 border border-emerald-800/40" id="lastSeenEmotion">Neutral</span>
          </div>
          <div class="text-slate-400 text-[11px]">
            Resolution: <strong class="text-slate-200">1280 × 720 HD</strong> &bull; HOG/ResNet 128-D
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
            <p class="text-xs text-slate-400">Live student recognitions authenticated automatically</p>
          </div>
          <div class="relative w-full md:w-64">
            <input type="text" id="searchInput" onkeyup="filterLedger()" placeholder="🔍 Search student name..."
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
                <th class="py-2.5 px-3">Location</th>
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
          <div class="text-2xl md:text-3xl font-extrabold text-amber-400 mt-1">1 / 1</div>
          <div class="text-[10px] text-amber-500 mt-1">Zero latency mode</div>
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
          <div class="bg-black/60 rounded-lg overflow-hidden border border-slate-800 aspect-video relative group">
            <img src="/snapshots/latest_unknown.jpg" alt="Latest Intruder" class="w-full h-full object-cover" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'60\\'><rect fill=\\'%23111827\\' width=\\'100\\' height=\\'60\\'/><text fill=\\'%236b7280\\' x=\\'50%\\' y=\\'50%\\' text-anchor=\\'middle\\' font-size=\\'10\\'>No Photo</text></svg>'">
            <div class="absolute bottom-0 inset-x-0 bg-slate-950/80 p-1 text-[10px] text-center text-slate-300 font-mono">Latest Sighting</div>
          </div>
          <div class="bg-black/60 rounded-lg overflow-hidden border border-slate-800 aspect-video relative group">
            <img src="/snapshots/principal_intrusion_20261102_123553.jpg" alt="Restricted Area Entry" class="w-full h-full object-cover" onerror="this.src='/snapshots/latest_unknown.jpg'">
            <div class="absolute bottom-0 inset-x-0 bg-rose-950/90 text-rose-300 p-1 text-[10px] text-center font-mono">Restricted Area</div>
          </div>
        </div>
      </div>

    </div>
  </main>

  <!-- Real-Time Telemetry & Chart Polling Script -->
  <script>
    let emotionChartInstance = null;

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
        const res = await fetch('/api/export_report');
        const data = await res.json();
        if (data.success && data.url) {
          window.open(data.url, '_blank');
        } else {
          alert('Report generation failed: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Report generation request failed.');
      }
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    }

    window.addEventListener('DOMContentLoaded', () => {
      initEmotionChart();
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
    print("=" * 65)
    print(f"  AI SURVEILLANCE & ATTENDANCE COMMAND CENTER WEB PORTAL")
    print("=" * 65)
    print(f"  [WEB] Command Center running at: http://localhost:{port}")
    print(f"  [AI]  Initializing live vision engine with 30 FPS video grabber...")
    print(f"  [TIP] Open http://localhost:{port} in Chrome / Edge (Press F11 for Fullscreen)")
    print("=" * 65)

    # Start vision worker in background
    worker = VisionWorker()
    worker.start()

    server = ThreadingHTTPServer(("0.0.0.0", port), CommandCenterHandler)
    try:
        # Open browser automatically
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Command Center server...")
        worker.running = False
        if worker.cap is not None:
            try:
                worker.cap.release()
            except Exception:
                pass
        server.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5000
    run_server(port)
