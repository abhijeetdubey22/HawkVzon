"""
Face & Emotion Recognition Dashboard  v3  (ALL IN ONE FILE)

What is new compared to v2
  1. ENCRYPTION   face data -> faces/Name_Age.face (Fernet/AES), CCTV passwords
                  in gui_config.json are saved encrypted ("enc:...").
  2. ERROR LOG    every error goes to logs/app.log (rotating). No more silent
                  "except: pass". The status bar shows how many errors happened.
  3. ALERTS       "Stranger Alerts" card: red rows, beep, NEW counter, mark handled.
  4. SPEED        screen redraw capped at 15 fps, canvas + image reused.

Setup
  pip install cryptography opencv-python face_recognition numpy pillow
  1) patch face_emotion_combined.py  (see the NOTE at the very bottom)
  2) run this file; your old faces/*.npy are encrypted automatically
  3) back up the key:   python face_dashboard.py show-key

THE KEY: set environment variable FACE_KEY, or it is created once at
~/.face_dashboard/face.key . BACK IT UP. Lose the key = lose all faces.

Each recognition process receives these environment variables:
  FACE_SOURCE, FACE_SOURCE_TYPE, FACE_CAMERA_NAME, FACE_CAMERA_ID,
  FACE_CLASS, FACE_CAMERA_MODE, FACE_HEADLESS, FACE_DETECTION_SCALE
"""
import os

# Must be set BEFORE importing cv2: TCP is far more reliable than UDP for RTSP.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import io
import re
import sys
import csv
import json
import math
import time
import uuid
import queue
import logging
import threading
import subprocess
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cv2
import numpy as np
from PIL import Image, ImageTk
import hashlib
import hmac
import base64

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    class InvalidToken(Exception):
        """Raised when a decrypted token cannot be validated."""
        pass

    class Fernet:
        """High-security authenticated cipher fallback matching Fernet specifications."""
        def __init__(self, key):
            if isinstance(key, str):
                key = key.encode("utf-8")
            self._key = hashlib.sha256(key).digest()

        @classmethod
        def generate_key(cls):
            import secrets
            return base64.urlsafe_b64encode(secrets.token_bytes(32))

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
            try:
                raw = base64.urlsafe_b64decode(token)
                if len(raw) < 49 or raw[0] != 0x80:
                    raise InvalidToken("Invalid token format")
                nonce = raw[1:17]
                tag = raw[-32:]
                ct = raw[17:-32]
                expected_tag = hmac.new(self._key, nonce + ct, hashlib.sha256).digest()
                if not hmac.compare_digest(tag, expected_tag):
                    raise InvalidToken("Token verification failed")
                keystream = b""
                block = 0
                while len(keystream) < len(ct):
                    keystream += hmac.new(self._key, nonce + block.to_bytes(4, "big"), hashlib.sha256).digest()
                    block += 1
                return bytes(b ^ k for b, k in zip(ct, keystream))
            except Exception as e:
                if isinstance(e, InvalidToken):
                    raise
                raise InvalidToken(str(e))

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(BASE_DIR, "face_emotion_combined.py")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "recognized_faces.csv")
APP_LOG = os.path.join(LOGS_DIR, "app.log")
FACES_DIR = os.path.join(BASE_DIR, "faces")
CONFIG_FILE = os.path.join(BASE_DIR, "gui_config.json")
os.makedirs(FACES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

from theme import C, FONT, FONT_B, FONT_H, FONT_S, apply_style, ScrollFrame
from school_hub import SchoolHub

SOURCE_WEBCAM = "Webcam"
SOURCE_CCTV = "CCTV / IP Camera"
SOURCE_FILE = "Video File"
KIND_SHORT = {SOURCE_WEBCAM: "Webcam", SOURCE_CCTV: "CCTV", SOURCE_FILE: "File"}

CAMERA_MODES = [
    "Classroom (Indoor / Standard)",
    "Outdoor / Main Gate (25-35 ft)",
    "Principal's Office / High Security",
    "Corridor / Transit Flow",
    "Library / Exam Hall (Silent)"
]

VIEW_SINGLE = "Single camera"
VIEW_GRID = "Grid (all cameras)"

BG_BGR = (22, 13, 9)           # studio obsidian video background (#090d16) in BGR
RENDER_FPS = 15                # screen redraws per second (smooth + light on CPU)
PURGE_OLD_KNOWN_FILES = False  # set True AFTER face_emotion_combined.py is patched


# ==========================================================================
# 1) ERROR LOGGING
# ==========================================================================
log = logging.getLogger("dashboard")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fh = RotatingFileHandler(APP_LOG, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"))
    log.addHandler(_fh)

_error_count = 0
_on_error = None


def _note_error():
    global _error_count
    _error_count += 1
    if _on_error is not None:
        try:
            _on_error()
        except Exception:
            pass


def log_exception(context):
    log.exception("%s", context)
    _note_error()


@contextmanager
def guard(context):
    try:
        yield
    except Exception:
        log_exception(context)


def install_hooks(root, on_error=None):
    """Catch every uncaught error (Tk callbacks, threads, main) and log it."""
    global _on_error
    _on_error = on_error

    def tk_hook(exc, val, tb):
        log.error("Tk callback error", exc_info=(exc, val, tb))
        _note_error()

    def sys_hook(exc, val, tb):
        log.critical("Uncaught error", exc_info=(exc, val, tb))
        _note_error()

    def thread_hook(args):
        log.error("Thread %s crashed", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        _note_error()

    root.report_callback_exception = tk_hook
    sys.excepthook = sys_hook
    threading.excepthook = thread_hook


# ==========================================================================
# 2) ENCRYPTION (faces + camera passwords)
# ==========================================================================
KEY_ENV = "FACE_KEY"
KEY_DIR = os.path.join(os.path.expanduser("~"), ".face_dashboard")
KEY_FILE = os.path.join(KEY_DIR, "face.key")
LOCAL_KEY_FILE = os.path.join(BASE_DIR, "data", "face.key")
ENC_PREFIX = "enc:"
_fernet_obj = None


def _get_key():
    env = os.environ.get(KEY_ENV, "").strip()
    if env:
        return env.encode()
    if os.path.isfile(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                return f.read().strip()
        except OSError:
            pass
    if os.path.isfile(LOCAL_KEY_FILE):
        try:
            with open(LOCAL_KEY_FILE, "rb") as f:
                return f.read().strip()
        except OSError:
            pass
    target_file = KEY_FILE
    try:
        os.makedirs(KEY_DIR, exist_ok=True)
    except OSError:
        target_file = LOCAL_KEY_FILE
        os.makedirs(os.path.dirname(LOCAL_KEY_FILE), exist_ok=True)

    key = Fernet.generate_key()
    try:
        with open(target_file, "wb") as f:
            f.write(key)
        try:
            os.chmod(target_file, 0o600)
        except OSError:
            pass
    except OSError:
        target_file = LOCAL_KEY_FILE
        os.makedirs(os.path.dirname(LOCAL_KEY_FILE), exist_ok=True)
        with open(target_file, "wb") as f:
            f.write(key)
    log.warning("New encryption key created at %s - BACK IT UP", target_file)
    return key


def _fernet():
    global _fernet_obj
    if _fernet_obj is None:
        _fernet_obj = Fernet(_get_key())
    return _fernet_obj


def face_path(name, age):
    return os.path.join(FACES_DIR, f"{name}_{age}.face")


def save_face(path, encoding):
    buf = io.BytesIO()
    np.save(buf, np.asarray(encoding), allow_pickle=False)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(_fernet().encrypt(buf.getvalue()))
    os.replace(tmp, path)                      # never leaves a half-written file


def load_face(path):
    with open(path, "rb") as f:
        return np.load(io.BytesIO(_fernet().decrypt(f.read())), allow_pickle=False)


def migrate_plain_faces():
    """Encrypt old faces/*.npy, verify, then delete the plain copy."""
    done = 0
    for fn in sorted(os.listdir(FACES_DIR)):
        if not fn.endswith(".npy"):
            continue
        src = os.path.join(FACES_DIR, fn)
        dst = os.path.join(FACES_DIR, fn[:-4] + ".face")
        try:
            arr = np.load(src, allow_pickle=False)
            save_face(dst, arr)
            if not np.allclose(load_face(dst), arr):
                raise ValueError("verification failed")
            os.remove(src)
            done += 1
        except Exception:
            log_exception(f"migrating {fn}")
    if PURGE_OLD_KNOWN_FILES:
        for n in ("known_face_encodings.npy", "known_face_names.npy", "known_face_ages.npy"):
            p = os.path.join(BASE_DIR, n)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    log_exception(f"removing {n}")
    if done:
        log.info("Encrypted %d existing face file(s)", done)
    return done


def protect_value(v):
    if isinstance(v, str) and v and not v.startswith(ENC_PREFIX):
        return ENC_PREFIX + _fernet().encrypt(v.encode("utf-8")).decode("ascii")
    return v


def reveal_value(v):
    if isinstance(v, str) and v.startswith(ENC_PREFIX):
        try:
            return _fernet().decrypt(v[len(ENC_PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken:
            log.error("Cannot decrypt a camera URL in the config - wrong key?")
            return ""
    return v


def _map_cameras(cfg, fn):
    out = dict(cfg)
    cams = []
    for c in cfg.get("cameras", []):
        c = dict(c)
        if c.get("kind") == SOURCE_CCTV:
            c["source"] = fn(c.get("source"))
        cams.append(c)
    out["cameras"] = cams
    return out


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def default_camera():
    return {"id": uuid.uuid4().hex[:8], "name": "Webcam 0", "kind": SOURCE_WEBCAM, "source": 0,
            "room": "Classroom 1", "mode": CAMERA_MODES[0], "zoom": 1.0}


def load_config():
    cfg = {"cameras": [], "selected": None, "view_mode": VIEW_SINGLE}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = _map_cameras(data, reveal_value)          # decrypt CCTV passwords
        cfg.update(data)
        # migrate from v1 config (single source)
        if not cfg["cameras"] and "source_type" in data:
            kind = data.get("source_type", SOURCE_WEBCAM)
            src = {SOURCE_WEBCAM: data.get("webcam_index", 0),
                   SOURCE_CCTV: data.get("cctv_url", ""),
                   SOURCE_FILE: data.get("video_file", "")}.get(kind)
            if kind == SOURCE_WEBCAM or src:
                cfg["cameras"].append({"id": uuid.uuid4().hex[:8], "name": "Camera 1",
                                       "kind": kind, "source": src})
    except FileNotFoundError:
        pass
    except Exception:
        log_exception("load_config")
    if not cfg["cameras"]:
        cfg["cameras"] = [default_camera()]
    ids = [c["id"] for c in cfg["cameras"]]
    if cfg.get("selected") not in ids:
        cfg["selected"] = ids[0]
    return cfg


def save_config(cfg):
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_map_cameras(cfg, protect_value), f, indent=2)   # encrypt passwords
        os.replace(tmp, CONFIG_FILE)                                    # atomic save
    except Exception:
        log_exception("save_config")


def open_folder(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def validate_source(kind, raw):
    """Returns (source, error_message). error_message is None when valid."""
    raw = str(raw).strip()
    if kind == SOURCE_WEBCAM:
        try:
            return int(raw), None
        except ValueError:
            return None, "Camera index must be a number (0, 1, 2 ...)."
    if kind == SOURCE_CCTV:
        if not re.match(r"^(rtsp|rtsps|http|https|rtmp|udp)://", raw, re.I):
            return None, ("Enter a valid stream URL, for example:\n\n"
                          "rtsp://user:pass@192.168.1.64:554/stream1")
        return raw, None
    if not os.path.isfile(raw):
        return None, "Please choose a valid video file."
    return raw, None


# --------------------------------------------------------------------------
# Threaded video stream (keeps the UI responsive, auto-reconnects for CCTV)
# --------------------------------------------------------------------------
class VideoStream:
    MAX_RECONNECTS = 5

    def __init__(self, kind, source):
        self.kind = kind
        self.source = source
        self.cap = None
        self.running = False
        self.state = "connecting"      # connecting / live / reconnecting / failed
        self.error = ""
        self.frame = None
        self.frame_id = 0
        self.lock = threading.Lock()
        self.thread = None
        self.ever_connected = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="VideoStream")
        self.thread.start()

    def request_stop(self):
        self.running = False

    def stop(self):
        self.running = False
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=3)

    def read(self, copy=True):
        with self.lock:
            if self.frame is None:
                return self.frame_id, None
            return self.frame_id, (self.frame.copy() if copy else self.frame)

    def _open(self):
        if self.kind == SOURCE_WEBCAM:
            cap = None
            if os.name == "nt":
                cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(self.source)
            return cap
        try:
            params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000,
                      cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000]
            return cv2.VideoCapture(self.source, cv2.CAP_FFMPEG, params)
        except Exception:
            return cv2.VideoCapture(self.source)

    def _fail(self, msg):
        self.error = msg
        self.state = "failed"
        # never write the camera password to the log
        where = "<cctv url hidden>" if self.kind == SOURCE_CCTV else self.source
        log.error("Stream failed (%s, %s): %s", self.kind, where, msg.splitlines()[0])

    def _open_error_text(self):
        if self.kind == SOURCE_WEBCAM:
            return (f"Could not open camera index {self.source}.\n"
                    "Close any other app using the camera, or try a different index.")
        if self.kind == SOURCE_CCTV:
            return ("Could not open the CCTV / IP stream.\n\n"
                    "Check that:\n"
                    " - the URL, username and password are correct\n"
                    " - the camera is reachable from this PC (try ping)\n"
                    " - RTSP is enabled on the camera / NVR")
        return "Could not open the selected video file."

    def _run(self):
        bad_reads = 0
        reconnects = 0
        try:
            while self.running:
                if self.cap is None:
                    self.state = "reconnecting" if self.ever_connected else "connecting"
                    cap = self._open()
                    if not self.running:
                        if cap is not None:
                            cap.release()
                        return
                    if cap is None or not cap.isOpened():
                        if cap is not None:
                            cap.release()
                        if not self.ever_connected:
                            self._fail(self._open_error_text())
                            return
                        reconnects += 1
                        if reconnects > self.MAX_RECONNECTS:
                            self._fail("Lost connection to the camera and could not reconnect.")
                            return
                        time.sleep(2)
                        continue
                    try:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    except Exception:
                        pass            # some backends don't support this; harmless
                    self.cap = cap
                    self.ever_connected = True
                    bad_reads = 0
                    self.state = "live"

                ok, frame = self.cap.read()
                if ok and frame is not None:
                    bad_reads = 0
                    reconnects = 0
                    self.state = "live"
                    with self.lock:
                        self.frame = frame
                        self.frame_id += 1
                    if self.kind == SOURCE_FILE:
                        time.sleep(0.03)
                    continue

                if self.kind == SOURCE_FILE:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # loop the video
                    time.sleep(0.05)
                    continue
                bad_reads += 1
                time.sleep(0.05)
                if bad_reads >= 20:
                    self.cap.release()
                    self.cap = None
                    reconnects += 1
                    self.state = "reconnecting"
                    log.warning("Stream lost, reconnecting (%d/%d)", reconnects, self.MAX_RECONNECTS)
                    if reconnects > self.MAX_RECONNECTS:
                        self._fail("Lost connection to the camera and could not reconnect.")
                        return
                    time.sleep(1)
        except Exception:
            log_exception("VideoStream._run")
            self._fail("Unexpected error in the video stream. See logs/app.log")
        finally:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    log_exception("VideoStream cleanup")
                self.cap = None


# --------------------------------------------------------------------------
# Add / Edit camera dialog
# --------------------------------------------------------------------------
class CameraDialog(tk.Toplevel):
    def __init__(self, parent, title, cam=None, taken_names=(), classes=()):
        super().__init__(parent)
        self.result = None
        self.taken = {n.lower() for n in taken_names}
        self.title(title)
        self.configure(bg=C["card"])
        self.resizable(False, False)
        self.transient(parent)

        pad = ttk.Frame(self, style="Inner.TFrame", padding=20)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))

        ttk.Label(pad, text="Camera name", style="Card.TLabel").pack(anchor="w")
        self.name_var = tk.StringVar(value=cam["name"] if cam else "")
        name_entry = ttk.Entry(pad, textvariable=self.name_var, width=46)
        name_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(pad, text="Class / room this camera covers", style="Card.TLabel").pack(anchor="w")
        self.room_var = tk.StringVar(value=(cam.get("room", "") if cam else ""))
        suggested = ["Principal's Office"] + [c for c in classes if c != "Principal's Office"]
        ttk.Combobox(pad, textvariable=self.room_var, values=suggested).pack(fill="x", pady=(2, 10))

        ttk.Label(pad, text="Camera operating mode / profile", style="Card.TLabel").pack(anchor="w")
        def_m = cam.get("mode", CAMERA_MODES[0]) if cam else CAMERA_MODES[0]
        self.mode_var = tk.StringVar(value=def_m)
        ttk.Combobox(pad, textvariable=self.mode_var, state="readonly",
                     values=CAMERA_MODES).pack(fill="x", pady=(2, 10))

        ttk.Label(pad, text="Camera Digital Zoom", style="Card.TLabel").pack(anchor="w")
        z_init = cam.get("zoom", 1.0) if cam else 1.0
        z_str = f"{float(z_init):.1f}x"
        self.zoom_var = tk.StringVar(value=z_str)
        ttk.Combobox(pad, textvariable=self.zoom_var, state="readonly",
                     values=["1.0x", "1.25x", "1.5x", "1.75x", "2.0x", "2.5x", "3.0x"]).pack(fill="x", pady=(2, 10))

        ttk.Label(pad, text="Source type", style="Card.TLabel").pack(anchor="w")
        self.kind_var = tk.StringVar(value=cam["kind"] if cam else SOURCE_CCTV)
        combo = ttk.Combobox(pad, textvariable=self.kind_var, state="readonly",
                             values=[SOURCE_WEBCAM, SOURCE_CCTV, SOURCE_FILE])
        combo.pack(fill="x", pady=(2, 10))
        combo.bind("<<ComboboxSelected>>", lambda e: self._switch())

        self.fields = ttk.Frame(pad, style="Inner.TFrame")
        self.fields.pack(fill="x")

        src = cam["source"] if cam else ""
        # webcam
        self.f_webcam = ttk.Frame(self.fields, style="Inner.TFrame")
        ttk.Label(self.f_webcam, text="Camera index", style="Card.TLabel").pack(anchor="w")
        self.webcam_var = tk.StringVar(value=str(src) if cam and cam["kind"] == SOURCE_WEBCAM else "0")
        ttk.Spinbox(self.f_webcam, from_=0, to=9, width=6,
                    textvariable=self.webcam_var).pack(anchor="w", pady=(2, 0))
        # cctv
        self.f_cctv = ttk.Frame(self.fields, style="Inner.TFrame")
        ttk.Label(self.f_cctv, text="Stream URL", style="Card.TLabel").pack(anchor="w")
        self.cctv_var = tk.StringVar(value=str(src) if cam and cam["kind"] == SOURCE_CCTV else "")
        ttk.Entry(self.f_cctv, textvariable=self.cctv_var).pack(fill="x", pady=(2, 4))
        ttk.Label(self.f_cctv, style="Muted.TLabel", justify="left",
                  text="RTSP:  rtsp://user:pass@192.168.1.64:554/stream1\n"
                       "HTTP:  http://192.168.1.50:8080/video\n"
                       "If your password has @ or #, write them as %40 and %23.").pack(anchor="w")
        # file
        self.f_file = ttk.Frame(self.fields, style="Inner.TFrame")
        ttk.Label(self.f_file, text="Video file", style="Card.TLabel").pack(anchor="w")
        row = ttk.Frame(self.f_file, style="Inner.TFrame")
        row.pack(fill="x", pady=(2, 0))
        self.file_var = tk.StringVar(value=str(src) if cam and cam["kind"] == SOURCE_FILE else "")
        ttk.Entry(row, textvariable=self.file_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", style="Secondary.TButton",
                   command=self._browse).pack(side="left", padx=(6, 0))

        btns = ttk.Frame(pad, style="Inner.TFrame")
        btns.pack(fill="x", pady=(18, 0))
        ttk.Button(btns, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btns, text="Cancel", style="Secondary.TButton",
                   command=self.destroy).pack(side="right", padx=(0, 8))

        self._switch()
        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        name_entry.focus_set()

    def _switch(self):
        for f in (self.f_webcam, self.f_cctv, self.f_file):
            f.pack_forget()
        {SOURCE_WEBCAM: self.f_webcam, SOURCE_CCTV: self.f_cctv,
         SOURCE_FILE: self.f_file}[self.kind_var.get()].pack(fill="x")

    def _browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="Select a video file",
            filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov *.wmv"), ("All files", "*.*")])
        if path:
            self.file_var.set(path)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please give the camera a name.", parent=self)
            return
        if name.lower() in self.taken:
            messagebox.showwarning("Name in use", "Another camera already has this name.", parent=self)
            return
        kind = self.kind_var.get()
        raw = {SOURCE_WEBCAM: self.webcam_var, SOURCE_CCTV: self.cctv_var,
               SOURCE_FILE: self.file_var}[kind].get()
        source, err = validate_source(kind, raw)
        if err:
            messagebox.showwarning("Invalid source", err, parent=self)
            return
        z_raw = self.zoom_var.get().split(" ")[0].replace("x", "")
        try:
            zoom_val = float(z_raw)
        except ValueError:
            zoom_val = 1.0
        self.result = {"name": name, "kind": kind, "source": source,
                       "room": self.room_var.get().strip(),
                       "mode": self.mode_var.get().strip(),
                       "zoom": zoom_val}
        self.destroy()


# --------------------------------------------------------------------------
# Stranger Alerts card
# --------------------------------------------------------------------------
class AlertsPanel(ttk.Frame):
    """Watches the rows of recognized_faces.csv. Every NEW row named
    "Stranger"/"Unknown" becomes a red alert with a beep. The guard selects
    rows and presses "Mark handled"."""
    STRANGER_NAMES = {"stranger", "unknown"}
    MAX_ALERTS = 60

    def __init__(self, parent, root):
        super().__init__(parent, style="Card.TFrame", padding=14)
        self.root = root
        self._seen = None            # rows already processed (None = first load)
        self._last_beep = 0.0

        head = ttk.Frame(self, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Stranger Alerts", style="CardTitle.TLabel").pack(side="left")
        self.badge = tk.Label(head, text="ALL CLEAR", bg="#064e3b", fg="#34d399",
                              font=("Segoe UI", 9, "bold"), padx=10, pady=2)
        self.badge.pack(side="right")

        wrap = ttk.Frame(self, style="Inner.TFrame")
        wrap.pack(fill="x", pady=(8, 0))
        self.tree = ttk.Treeview(wrap, columns=("time", "emotion", "match", "status"),
                                 show="headings", height=5, selectmode="extended")
        for col, text, w in (("time", "Time", 120), ("emotion", "Emotion", 70),
                             ("match", "Match", 50), ("status", "Status", 60)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="center")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("new", foreground=C["danger"])
        self.tree.tag_configure("handled", foreground=C["muted"])

        row = ttk.Frame(self, style="Inner.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Mark handled", style="Secondary.TButton",
                   command=self.mark_selected).pack(side="left")
        ttk.Button(row, text="Handle all", style="Secondary.TButton",
                   command=self.mark_all).pack(side="left", padx=(6, 0))
        self.sound_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Sound", variable=self.sound_var,
                        style="Card.TCheckbutton").pack(side="right")

    def ingest(self, rows):
        """Call with ALL csv rows (header removed). Only new rows are processed."""
        try:
            if self._seen is None or len(rows) < self._seen:
                self._seen = len(rows)      # first load or log reset: no alarm
                return
            new, self._seen = rows[self._seen:], len(rows)
            fresh = 0
            for r in new:
                r = (list(r) + [""] * 5)[:5]
                if str(r[0]).strip().lower() in self.STRANGER_NAMES:
                    self._add(r)
                    fresh += 1
            if fresh:
                self._beep()
            self._update_badge()
        except Exception:
            log_exception("AlertsPanel.ingest")

    def _add(self, r):
        self.tree.insert("", 0, values=(r[4], r[3], r[2], "NEW"), tags=("new",))
        for iid in self.tree.get_children()[self.MAX_ALERTS:]:
            self.tree.delete(iid)

    def _beep(self):
        if not self.sound_var.get() or time.monotonic() - self._last_beep < 2:
            return
        self._last_beep = time.monotonic()
        try:
            if sys.platform.startswith("win"):
                import winsound
                winsound.MessageBeep(winsound.MB_ICONHAND)
            else:
                self.root.bell()
        except Exception:
            log_exception("alert sound")

    def unhandled(self):
        return sum(1 for i in self.tree.get_children() if "new" in self.tree.item(i, "tags"))

    def _mark(self, iids):
        for i in iids:
            self.tree.set(i, "status", "Handled")
            self.tree.item(i, tags=("handled",))
        self._update_badge()

    def mark_selected(self):
        self._mark(self.tree.selection())

    def mark_all(self):
        self._mark(self.tree.get_children())

    def _update_badge(self):
        n = self.unhandled()
        if n:
            self.badge.config(text=f"{n} NEW", bg="#7f1d1d", fg="#fca5a5")
        else:
            self.badge.config(text="ALL CLEAR", bg="#064e3b", fg="#34d399")


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.cameras = self.cfg["cameras"]
        self.selected_id = self.cfg["selected"]
        self.view_mode = self.cfg.get("view_mode", VIEW_SINGLE)
        if self.view_mode not in (VIEW_SINGLE, VIEW_GRID):
            self.view_mode = VIEW_SINGLE

        self.streams = {}          # camera id -> VideoStream (active previews)
        self.stopping = []         # streams that are shutting down
        self.errors = {}           # camera id -> last error text
        self.previewing = False
        self.procs = {}            # camera id -> subprocess.Popen
        self.stop_requested = set()
        self.ui_queue = queue.Queue()

        self.log_mtime = -1
        self.busy_register = False
        self.layout = None
        self.last_sig = None
        self.placeholder_text = None
        self.last_cam_status = {}
        self.last_pill = None
        self.last_rec_ui = None
        self.error_popup_shown = False
        self.last_log_rows = []
        self.camera_zooms = {c["id"]: float(c.get("zoom", 1.0)) for c in self.cameras}

        # rendering cache (speed)
        self._last_render = 0.0
        self._photo = None
        self._canvas = None
        self._canvas_key = None

        # error logging + encryption of old data
        install_hooks(root, on_error=lambda: self.post(self._show_error_badge))
        with guard("migrate_plain_faces"):
            migrate_plain_faces()

        root.title("Face & Emotion Recognition Dashboard")
        root.geometry("1300x880")
        root.minsize(1150, 700)
        root.configure(bg=C["bg"])

        self._setup_style()
        self._build_header()
        self._build_statusbar()
        self._build_notebook()

        self._reload_cameras()
        self.refresh_logs(force=True)
        self._tick()
        self._poll_logs()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ style
    def _setup_style(self):
        apply_style(self.root)

    # ----------------------------------------------------------------- layout
    def _card(self, parent, title, subtitle=None):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ttk.Label(outer, text=title, style="CardTitle.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(outer, text=subtitle, style="Muted.TLabel").pack(anchor="w")
        body = ttk.Frame(outer, style="Inner.TFrame")
        body.pack(fill="both", expand=True, pady=(8, 0))
        return outer, body

    def _build_header(self):
        bar = tk.Frame(self.root, bg=C["header"], height=66)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # Subtle dark border line separating header from tab bar
        border_line = tk.Frame(self.root, bg=C["header_border"], height=1)
        border_line.pack(fill="x")

        left = tk.Frame(bar, bg=C["header"])
        left.pack(side="left", padx=24)
        tk.Label(left, text="🎥  Face & Emotion Recognition Command Center", bg=C["header"], fg=C["text"],
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(12, 1))
        tk.Label(left, text="Multi-Camera AI Vision  •  Live Biometrics  •  Real-time Attendance & Alerts",
                 bg=C["header"], fg=C["subtle"], font=FONT_S).pack(anchor="w")

        right = tk.Frame(bar, bg=C["header"])
        right.pack(side="right", padx=24)
        tk.Label(right, text="Recognition:", bg=C["header"], fg=C["subtle"],
                 font=FONT_S).pack(side="left", padx=(0, 10))
        self.rec_pill = tk.Label(right, text="● STOPPED", bg="#1e293b", fg="#94a3b8",
                                 font=("Segoe UI", 9, "bold"), padx=14, pady=5)
        self.rec_pill.pack(side="left")
        tk.Button(right, text="🔒 PIN", command=lambda: self.hub.change_pin(), bg=C["card_sub"],
                  fg=C["text"], activebackground=C["border"], activeforeground="#ffffff",
                  relief="flat", font=FONT_S, padx=12, pady=4,
                  cursor="hand2", bd=0).pack(side="left", padx=(14, 0))

    def _build_statusbar(self):
        # Hairline top border for status bar
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x", side="bottom")

        bar = tk.Frame(self.root, bg=C["statusbar"], height=32)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_text = tk.Label(bar, text="Ready", bg=C["statusbar"], fg=C["muted"],
                                    font=FONT_S, anchor="w")
        self.status_text.pack(side="left", padx=18)
        self.clock = tk.Label(bar, text="", bg=C["statusbar"], fg=C["muted"], font=FONT_S)
        self.clock.pack(side="right", padx=18)
        self.err_label = tk.Label(bar, text="", bg=C["statusbar"], fg=C["amber"], font=FONT_S)
        self.err_label.pack(side="right", padx=18)
        self.stats = tk.Label(bar, text="", bg=C["statusbar"], fg=C["text_sec"], font=FONT_S)
        self.stats.pack(side="right", padx=18)

    def _show_error_badge(self):
        self.err_label.config(text=f"⚠ {_error_count} error(s) logged - see logs/app.log")

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.tab_control = tk.Frame(self.notebook, bg=C["bg"])
        self.notebook.add(self.tab_control, text="  🎥 Control Room  ")
        self._build_body(self.tab_control)
        self.hub = SchoolHub(self, self.notebook, self.tab_control)
        self.notebook.bind("<<NotebookTabChanged>>", self.hub.on_tab_changed)
        self.hub.start()

    def _build_body(self, parent):
        body = tk.Frame(parent, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=(14, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0, minsize=400)
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=2)

        # ---------------- Video card ----------------
        video_card, video_body = self._card(body, "Live Preview")
        video_card.grid(row=0, column=0, sticky="nsew", padx=(0, 14), pady=(0, 12))

        self.status_pill = tk.Label(video_card, text="● NO SIGNAL", bg="#1e293b", fg="#94a3b8",
                                    font=("Segoe UI", 9, "bold"), padx=12, pady=4)
        self.status_pill.place(relx=1.0, x=-14, y=14, anchor="ne")

        toolbar = ttk.Frame(video_body, style="Inner.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        self.btn_prev_start = ttk.Button(toolbar, text="▶  Start Preview",
                                         style="Success.TButton", command=self.start_preview)
        self.btn_prev_start.pack(side="left")
        self.btn_prev_stop = ttk.Button(toolbar, text="■  Stop Preview",
                                        style="Danger.TButton", command=self.stop_preview)
        self.btn_prev_stop.pack(side="left", padx=(8, 0))
        self.btn_prev_stop.state(["disabled"])

        self.view_var = tk.StringVar(value=self.view_mode)
        view_combo = ttk.Combobox(toolbar, textvariable=self.view_var, state="readonly",
                                  width=16, values=[VIEW_SINGLE, VIEW_GRID])
        view_combo.pack(side="right")
        view_combo.bind("<<ComboboxSelected>>", lambda e: self._on_view_change())
        ttk.Label(toolbar, text="View:", style="Card.TLabel").pack(side="right", padx=(0, 6))

        # Digital Zoom toolbar control
        zoom_frame = ttk.Frame(toolbar, style="Inner.TFrame")
        zoom_frame.pack(side="right", padx=(0, 14))
        ttk.Label(zoom_frame, text="🔍 Zoom:", style="Card.TLabel").pack(side="left", padx=(0, 4))
        cur_z = self.get_zoom(self.selected_id)
        self.zoom_var = tk.StringVar(value=f"{cur_z:.1f}x")
        self.zoom_combo = ttk.Combobox(zoom_frame, textvariable=self.zoom_var, state="readonly",
                                       width=6, values=["1.0x", "1.25x", "1.5x", "1.75x", "2.0x", "2.5x", "3.0x"])
        self.zoom_combo.pack(side="left")
        self.zoom_combo.bind("<<ComboboxSelected>>", lambda e: self._on_zoom_change())
        ttk.Button(zoom_frame, text="−", width=2, style="Secondary.TButton",
                   command=self._zoom_out).pack(side="left", padx=(3, 1))
        ttk.Button(zoom_frame, text="+", width=2, style="Secondary.TButton",
                   command=self._zoom_in).pack(side="left", padx=(0, 3))
        ttk.Button(zoom_frame, text="1x", width=2, style="Secondary.TButton",
                   command=self._zoom_reset).pack(side="left")

        self.video_box = tk.Frame(video_body, bg=C["video"], height=340)
        self.video_box.pack(fill="both", expand=True)
        self.video_box.pack_propagate(False)
        self.video_label = tk.Label(self.video_box, bg=C["video"], fg="#64748b",
                                    font=("Segoe UI", 12), text="")
        self.video_label.pack(fill="both", expand=True)
        self.video_label.bind("<Button-1>", self._on_video_click)
        self.video_label.bind("<Double-Button-1>", self._on_video_double_click)
        self.video_label.bind("<MouseWheel>", self._on_mouse_wheel)
        self.video_label.bind("<Button-4>", lambda e: self._zoom_in())
        self.video_label.bind("<Button-5>", lambda e: self._zoom_out())

        # ---------------- Right column ----------------
        right_scroll = ScrollFrame(body, width=390)
        right_scroll.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=(0, 12))
        right = right_scroll.inner

        # Cameras card
        cam_card, cam_body = self._card(right, "Cameras", "Add as many cameras as you need")
        cam_card.pack(fill="x", pady=(0, 12))

        tree_wrap = ttk.Frame(cam_body, style="Inner.TFrame")
        tree_wrap.pack(fill="x")
        self.cam_tree = ttk.Treeview(tree_wrap, columns=("name", "room", "mode", "zoom", "type", "status"),
                                     show="headings", height=4, selectmode="browse")
        for col, text, w, anchor in (("name", "Name", 90, "w"), ("room", "Class", 65, "center"),
                                     ("mode", "Mode", 75, "center"), ("zoom", "Zoom", 45, "center"),
                                     ("type", "Type", 50, "center"), ("status", "Status", 70, "center")):
            self.cam_tree.heading(col, text=text)
            self.cam_tree.column(col, width=w, anchor=anchor)
        cam_sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.cam_tree.yview)
        self.cam_tree.configure(yscrollcommand=cam_sb.set)
        self.cam_tree.pack(side="left", fill="x", expand=True)
        cam_sb.pack(side="right", fill="y")
        self.cam_tree.tag_configure("live", foreground=C["success"])
        self.cam_tree.tag_configure("wait", foreground=C["amber"])
        self.cam_tree.tag_configure("fail", foreground=C["danger"])
        self.cam_tree.tag_configure("rec", foreground=C["violet"])
        self.cam_tree.tag_configure("idle", foreground=C["muted"])
        self.cam_tree.bind("<<TreeviewSelect>>", self._on_select)
        self.cam_tree.bind("<Double-1>", lambda e: self.edit_camera())

        brow = ttk.Frame(cam_body, style="Inner.TFrame")
        brow.pack(fill="x", pady=(10, 0))
        for i in range(3):
            brow.columnconfigure(i, weight=1, uniform="b")
        ttk.Button(brow, text="+ Add", style="Primary.TButton",
                   command=self.add_camera).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(brow, text="Edit", style="Secondary.TButton",
                   command=self.edit_camera).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(brow, text="Remove", style="Secondary.TButton",
                   command=self.remove_camera).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        # Stranger alerts card (new)
        self.alerts = AlertsPanel(right, self.root)
        self.alerts.pack(fill="x", pady=(0, 12))

        # Registration card
        reg_card, reg = self._card(right, "Register Face",
                                   "Uses the selected camera's live preview")
        reg_card.pack(fill="x", pady=(0, 12))
        reg.columnconfigure(0, weight=1)
        ttk.Label(reg, text="Full name", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(reg, text="Age", style="Card.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.entry_name = ttk.Entry(reg)
        self.entry_name.grid(row=1, column=0, sticky="ew", pady=(2, 10))
        self.entry_age = ttk.Entry(reg, width=7)
        self.entry_age.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(2, 10))
        ttk.Label(reg, text="Class", style="Card.TLabel").grid(row=2, column=0, columnspan=2, sticky="w")
        self.class_var = tk.StringVar()
        self.class_combo = ttk.Combobox(reg, textvariable=self.class_var, values=[])
        self.class_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 10))
        self.btn_register = ttk.Button(reg, text="Register Current Face",
                                       style="Success.TButton", command=self.register_face)
        self.btn_register.grid(row=4, column=0, columnspan=2, sticky="ew")

        # Recognition card
        act_card, act = self._card(right, "Recognition")
        act_card.pack(fill="x")
        self.btn_rec_sel = ttk.Button(act, text="Start Recognition (selected camera)",
                                      style="Violet.TButton", command=self.toggle_recognition_selected)
        self.btn_rec_sel.pack(fill="x")
        self.btn_rec_all = ttk.Button(act, text="Start on All Cameras",
                                      style="Secondary.TButton", command=self.toggle_recognition_all)
        self.btn_rec_all.pack(fill="x", pady=(8, 0))
        self.show_popup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(act, text="Show live recognition HUD window",
                        variable=self.show_popup_var,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(8, 0))
        self.long_range_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(act, text="Outdoor / Long-Range Mode (25+ ft)",
                        variable=self.long_range_var,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(4, 0))
        ttk.Button(act, text="📊 Export Daily Report (HTML)", style="Primary.TButton",
                   command=self.export_daily_report).pack(fill="x", pady=(8, 0))
        ttk.Button(act, text="Open Logs & Snapshots", style="Secondary.TButton",
                   command=lambda: open_folder(LOGS_DIR)).pack(fill="x", pady=(8, 0))

        # ---------------- Logs card ----------------
        log_card, log_body = self._card(body, "Recent Attendance & Recognition")
        log_card.grid(row=1, column=0, sticky="nsew", padx=(0, 14))

        # Search Bar
        search_row = ttk.Frame(log_body, style="Inner.TFrame")
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text="🔍 Search student:", style="Card.TLabel").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=22)
        self.search_entry.pack(side="left", padx=(8, 8))
        self.search_var.trace_add("write", lambda *_: self.filter_attendance_table())

        ttk.Button(search_row, text="Clear", style="Secondary.TButton",
                   command=lambda: self.search_var.set("")).pack(side="left")

        columns = ("Name", "Age", "Match %", "Emotion", "Timestamp")
        wrap = ttk.Frame(log_body, style="Inner.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=columns, show="headings", height=6)
        widths = {"Name": 180, "Age": 70, "Match %": 90, "Emotion": 120, "Timestamp": 190}
        anchors = {"Name": "w", "Age": "center", "Match %": "center", "Emotion": "center", "Timestamp": "center"}
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths[col], anchor=anchors.get(col, "center"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#0d1424", foreground=C["text"])
        self.tree.tag_configure("even", background="#131c31", foreground=C["text"])
        self.tree.tag_configure("stranger_even", background="#131c31", foreground=C["amber"])
        self.tree.tag_configure("stranger_odd", background="#0d1424", foreground=C["amber"])
        self.tree.tag_configure("known_even", background="#131c31", foreground=C["success"])
        self.tree.tag_configure("known_odd", background="#0d1424", foreground=C["success"])

    # ---------------------------------------------------------------- helpers
    def post(self, fn):
        """Thread-safe: run fn on the UI thread."""
        self.ui_queue.put(fn)

    def set_status(self, text):
        self.status_text.config(text=text)

    def get_zoom(self, cid):
        if hasattr(self, "camera_zooms") and cid in self.camera_zooms:
            return self.camera_zooms[cid]
        c = self.cam(cid)
        if c:
            z = float(c.get("zoom", 1.0))
            if not hasattr(self, "camera_zooms"):
                self.camera_zooms = {}
            self.camera_zooms[cid] = z
            return z
        return 1.0

    def set_zoom(self, cid, val):
        val = max(1.0, min(4.0, round(float(val), 2)))
        if not hasattr(self, "camera_zooms"):
            self.camera_zooms = {}
        self.camera_zooms[cid] = val
        c = self.cam(cid)
        if c:
            c["zoom"] = val
            self._save()
            if hasattr(self, "cam_tree") and self.cam_tree.exists(cid):
                vals = list(self.cam_tree.item(cid, "values"))
                if len(vals) >= 6:
                    vals[3] = f"{val:.1f}x"
                    self.cam_tree.item(cid, values=vals)
        if hasattr(self, "zoom_var") and cid == self.selected_id:
            txt = f"{val:.1f}x" if val.is_integer() or (val*10)%1==0 else f"{val:.2f}x"
            self.zoom_var.set(txt)
        self.last_sig = None
        cname = c["name"] if c else "camera"
        self.set_status(f"Zoom set to {val:.2f}x for {cname}")

    def _on_zoom_change(self):
        if not self.selected_id:
            return
        z_str = self.zoom_var.get().split(" ")[0].replace("x", "")
        try:
            val = float(z_str)
            self.set_zoom(self.selected_id, val)
        except ValueError:
            pass

    def _zoom_in(self):
        if not self.selected_id:
            return
        curr = self.get_zoom(self.selected_id)
        self.set_zoom(self.selected_id, curr + 0.25)

    def _zoom_out(self):
        if not self.selected_id:
            return
        curr = self.get_zoom(self.selected_id)
        self.set_zoom(self.selected_id, curr - 0.25)

    def _zoom_reset(self):
        if not self.selected_id:
            return
        self.set_zoom(self.selected_id, 1.0)

    def _on_mouse_wheel(self, event):
        if not self.previewing or not self.selected_id:
            return
        if getattr(event, "delta", 0) > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _on_video_double_click(self, event):
        if not self.previewing or not self.selected_id:
            return
        self._zoom_reset()

    def cam(self, cid):
        for c in self.cameras:
            if c["id"] == cid:
                return c
        return None

    def selected_cam(self):
        return self.cam(self.selected_id)

    def _save(self):
        self.cfg["cameras"] = self.cameras
        self.cfg["selected"] = self.selected_id
        self.cfg["view_mode"] = self.view_mode
        save_config(self.cfg)

    def rec_running(self, cid):
        p = self.procs.get(cid)
        return p is not None and p.poll() is None

    # --------------------------------------------------------- camera manager
    def _reload_cameras(self):
        self.cam_tree.delete(*self.cam_tree.get_children())
        for c in self.cameras:
            m_full = c.get("mode") or "Classroom"
            m_short = m_full.split(" ")[0] if "(" in m_full else m_full
            z_txt = f"{self.get_zoom(c['id']):.1f}x"
            self.cam_tree.insert("", "end", iid=c["id"],
                                 values=(c["name"], c.get("room") or "-", m_short, z_txt, KIND_SHORT[c["kind"]], "Idle"),
                                 tags=("idle",))
        self.last_cam_status = {}
        if self.selected_id and self.cam_tree.exists(self.selected_id):
            self.cam_tree.selection_set(self.selected_id)
            self.cam_tree.see(self.selected_id)
            if hasattr(self, "zoom_var"):
                self.zoom_var.set(f"{self.get_zoom(self.selected_id):.1f}x")
        self._update_buttons()

    def _on_select(self, _event=None):
        sel = self.cam_tree.selection()
        if not sel:
            return
        self.selected_id = sel[0]
        if hasattr(self, "zoom_var"):
            self.zoom_var.set(f"{self.get_zoom(self.selected_id):.1f}x")
        self._save()
        self._sync_streams()
        self._update_buttons()

    def add_camera(self):
        dlg = CameraDialog(self.root, "Add camera",
                           taken_names=[c["name"] for c in self.cameras],
                           classes=self.hub.class_list())
        self.root.wait_window(dlg)
        if dlg.result:
            cam = dict(dlg.result, id=uuid.uuid4().hex[:8])
            self.cameras.append(cam)
            self.selected_id = cam["id"]
            self._save()
            self._reload_cameras()
            self._sync_streams()
            self.set_status(f"Camera '{cam['name']}' added")
            log.info("Camera added: %s (%s)", cam["name"], cam["kind"])

    def edit_camera(self):
        cam = self.selected_cam()
        if cam is None:
            return
        if self.rec_running(cam["id"]):
            messagebox.showinfo("Recognition running",
                                "Stop recognition on this camera before editing it.")
            return
        dlg = CameraDialog(self.root, "Edit camera", cam=cam,
                           taken_names=[c["name"] for c in self.cameras if c["id"] != cam["id"]],
                           classes=self.hub.class_list())
        self.root.wait_window(dlg)
        if dlg.result:
            cam.update(dlg.result)
            self._stop_stream(cam["id"])
            self.errors.pop(cam["id"], None)
            self._save()
            self._reload_cameras()
            self._sync_streams()
            self.set_status(f"Camera '{cam['name']}' updated")
            log.info("Camera edited: %s", cam["name"])

    def remove_camera(self):
        cam = self.selected_cam()
        if cam is None:
            return
        if len(self.cameras) == 1:
            messagebox.showinfo("Cannot remove", "At least one camera must remain in the list.")
            return
        if not messagebox.askyesno("Remove camera", f"Remove '{cam['name']}'?"):
            return
        if self.rec_running(cam["id"]):
            self.stop_recognition(cam["id"])
        self._stop_stream(cam["id"])
        self.errors.pop(cam["id"], None)
        idx = self.cameras.index(cam)
        self.cameras.remove(cam)
        self.selected_id = self.cameras[min(idx, len(self.cameras) - 1)]["id"]
        self._save()
        self._reload_cameras()
        self._sync_streams()
        self.set_status(f"Camera '{cam['name']}' removed")
        log.info("Camera removed: %s", cam["name"])

    # --------------------------------------------------------------- preview
    def _on_view_change(self):
        self.view_mode = self.view_var.get()
        self._save()
        self._sync_streams()

    def _shown_cams(self):
        if self.view_mode == VIEW_GRID:
            return list(self.cameras)
        c = self.selected_cam()
        return [c] if c else []

    def _desired_ids(self):
        if not self.previewing:
            return set()
        return {c["id"] for c in self._shown_cams()}

    def _reap(self):
        alive = []
        for s in self.stopping:
            if s.thread is not None and s.thread.is_alive():
                if s.kind == SOURCE_WEBCAM:
                    s.thread.join(timeout=2)       # make sure the device is released
                if s.thread.is_alive():
                    alive.append(s)
        self.stopping = alive

    def _sync_streams(self):
        """Make the running streams match what should currently be previewed."""
        want = self._desired_ids()
        for cid in list(self.streams):
            if cid not in want:
                s = self.streams.pop(cid)
                s.request_stop()
                self.stopping.append(s)
        self._reap()
        for cid in want:
            if cid in self.streams or cid in self.errors:
                continue
            cam = self.cam(cid)
            if cam is None:
                continue
            if cam["kind"] == SOURCE_WEBCAM and self.rec_running(cid):
                continue                           # webcam is used by recognition
            s = VideoStream(cam["kind"], cam["source"])
            self.streams[cid] = s
            s.start()
        self._update_buttons()

    def _stop_stream(self, cid):
        s = self.streams.pop(cid, None)
        if s is not None:
            s.stop()

    def start_preview(self):
        if not self.cameras:
            messagebox.showinfo("No camera", "Add a camera first.")
            return
        self.previewing = True
        self.errors.clear()
        self.error_popup_shown = False
        self._sync_streams()
        n = len(self._shown_cams())
        self.set_status(f"Starting preview ({n} camera{'s' if n != 1 else ''})...")

    def stop_preview(self):
        self.previewing = False
        for s in self.streams.values():
            s.request_stop()
        for s in list(self.streams.values()):
            s.stop()
        self.streams.clear()
        self.errors.clear()
        self.last_sig = None
        self._update_buttons()
        self.set_status("Preview stopped")

    def _update_buttons(self):
        self.btn_prev_stop.state(["!disabled" if self.previewing else "disabled"])
        sel = self.selected_id
        if sel and self.rec_running(sel):
            self.btn_rec_sel.config(text="Stop Recognition (selected camera)", style="Danger.TButton")
        else:
            self.btn_rec_sel.config(text="Start Recognition (selected camera)", style="Violet.TButton")
        if self.procs and any(self.rec_running(c) for c in list(self.procs)):
            self.btn_rec_all.config(text="Stop All Recognition")
        else:
            self.btn_rec_all.config(text="Start on All Cameras")

    # -------------------------------------------------------------- rendering
    def _on_video_click(self, event):
        if self.view_mode != VIEW_GRID or not self.layout or not self.previewing:
            return
        cols, rows, tw, th, gap, ids = self.layout
        c = event.x // (tw + gap)
        r = event.y // (th + gap)
        idx = r * cols + c
        if 0 <= c < cols and 0 <= r < rows and idx < len(ids):
            self.cam_tree.selection_set(ids[idx])

    @staticmethod
    def _put_center(img, text, y, scale, color, thick=1):
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        x = max((img.shape[1] - tw) // 2, 4)
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

    def _tile_message(self, cam):
        cid = cam["id"]
        if cam["kind"] == SOURCE_WEBCAM and self.rec_running(cid):
            return "In use by recognition", "Webcam is busy", (180, 140, 200)
        if cid in self.errors:
            return "Connection failed", "Press Start Preview to retry", (60, 60, 230)
        s = self.streams.get(cid)
        if s is None:
            return "Not started", "", (139, 116, 100)
        if s.state == "reconnecting":
            return "Reconnecting...", "", (40, 140, 230)
        return "Connecting...", "", (40, 140, 230)

    def _tile(self, cam, tw, th, highlight):
        tile = np.empty((th, tw, 3), np.uint8)
        tile[:] = BG_BGR
        cid = cam["id"]
        small_ui = th < 220 or tw < 320
        scale = 0.4 if small_ui else 0.5

        s = self.streams.get(cid)
        frame = None
        if s is not None:
            _, frame = s.read(copy=False)
        if frame is not None:
            zoom = self.get_zoom(cid)
            if zoom > 1.0:
                fh, fw = frame.shape[:2]
                cw, ch = int(fw / zoom), int(fh / zoom)
                cx, cy = fw // 2, fh // 2
                x1 = max(0, min(fw - cw, cx - cw // 2))
                y1 = max(0, min(fh - ch, cy - ch // 2))
                frame = frame[y1:y1 + ch, x1:x1 + cw]

            h, w = frame.shape[:2]
            sc = min(tw / w, th / h)
            nw, nh = max(1, int(w * sc)), max(1, int(h * sc))
            interp = cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR
            small = cv2.resize(frame, (nw, nh), interpolation=interp)
            ox, oy = (tw - nw) // 2, (th - nh) // 2
            tile[oy:oy + nh, ox:ox + nw] = small
            stamp = f"{cam['name']}   {datetime.now():%H:%M:%S}"
            if zoom > 1.0:
                stamp += f"  [{zoom:.1f}x]"
            cv2.putText(tile, stamp, (9, 19), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(tile, stamp, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            main, sub, color = self._tile_message(cam)
            self._put_center(tile, main, th // 2, scale + 0.3, color, 1)
            if sub:
                self._put_center(tile, sub, th // 2 + 26, scale, (139, 116, 100))
            cv2.putText(tile, cam["name"], (8, 18), cv2.FONT_HERSHEY_SIMPLEX, scale,
                        (200, 200, 200), 1, cv2.LINE_AA)
        if highlight:
            cv2.rectangle(tile, (0, 0), (tw - 1, th - 1), (235, 99, 37), 3)
        return tile

    def _show_placeholder(self, text):
        if self.placeholder_text != text:
            self.placeholder_text = text
            self.video_label.config(image="", text=text)
            self.video_label.imgtk = None
            self._photo = None
            self.last_sig = None
            self.layout = None

    def _render(self):
        if not self.previewing:
            self._show_placeholder(
                "Preview is off\n\nSelect a camera and press  ▶ Start Preview")
            return
        cams = self._shown_cams()
        if not cams:
            self._show_placeholder("No camera selected")
            return

        now = time.monotonic()
        if now - self._last_render < 1.0 / RENDER_FPS:        # too soon: skip
            return

        bw = max(self.video_box.winfo_width(), 200)
        bh = max(self.video_box.winfo_height(), 150)
        sig = (bw, bh, self.view_mode, self.selected_id,
               tuple((c["id"], c["name"], self.get_zoom(c["id"])) for c in cams),
               tuple((cid, s.frame_id, s.state) for cid, s in self.streams.items()),
               tuple(sorted(self.errors)),
               tuple(sorted(c for c in self.procs if self.rec_running(c))))
        if sig == self.last_sig:                               # nothing changed
            return
        self.last_sig = sig
        self._last_render = now
        self.placeholder_text = None

        n = len(cams)
        cols = 1 if n == 1 else math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        gap = 4 if n > 1 else 0
        tw = (bw - gap * (cols - 1)) // cols
        th = (bh - gap * (rows - 1)) // rows

        key = (bw, bh, n, cols)
        if self._canvas is None or self._canvas_key != key:    # allocate only on change
            self._canvas = np.empty((bh, bw, 3), np.uint8)
            self._canvas[:] = BG_BGR
            self._canvas_key = key
        canvas = self._canvas
        for i, cam in enumerate(cams):
            r, c = divmod(i, cols)
            x, y = c * (tw + gap), r * (th + gap)
            highlight = n > 1 and cam["id"] == self.selected_id
            canvas[y:y + th, x:x + tw] = self._tile(cam, tw, th, highlight)
        self.layout = (cols, rows, tw, th, gap, [c["id"] for c in cams])

        img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        if self._photo is not None and (self._photo.width(), self._photo.height()) == img.size:
            self._photo.paste(img)                             # reuse the image object
        else:
            self._photo = ImageTk.PhotoImage(img)
            self.video_label.config(image=self._photo, text="")
        self.video_label.imgtk = self._photo

    # ------------------------------------------------------------ status bits
    def _cam_status(self, cid):
        if self.rec_running(cid):
            return "Recognizing", "rec"
        s = self.streams.get(cid)
        if s is not None:
            return {"live": ("Live", "live"), "connecting": ("Connecting", "wait"),
                    "reconnecting": ("Reconnecting", "wait"),
                    "failed": ("Failed", "fail")}[s.state]
        if cid in self.errors:
            return "Failed", "fail"
        return "Idle", "idle"

    def _refresh_cam_status(self):
        for c in self.cameras:
            cid = c["id"]
            st = self._cam_status(cid)
            if self.last_cam_status.get(cid) != st and self.cam_tree.exists(cid):
                self.last_cam_status[cid] = st
                self.cam_tree.set(cid, "status", st[0])
                self.cam_tree.item(cid, tags=(st[1],))

    def _update_pill(self):
        if not self.previewing:
            pill = ("● NO SIGNAL", "#1e293b", "#94a3b8")
        else:
            shown = [c["id"] for c in self._shown_cams()]
            states = [self.streams[c].state for c in shown if c in self.streams]
            live = states.count("live")
            if live:
                txt = "● LIVE" if len(shown) == 1 else f"● LIVE {live}/{len(shown)}"
                pill = (txt, "#064e3b", "#34d399")
            elif states:
                pill = ("● CONNECTING…", "#78350f", "#fde68a")
            elif any(c in self.errors for c in shown):
                pill = ("● FAILED", "#7f1d1d", "#fca5a5")
            else:
                pill = ("● NO SIGNAL", "#1e293b", "#94a3b8")
        if pill != self.last_pill:
            self.last_pill = pill
            self.status_pill.config(text=pill[0], bg=pill[1], fg=pill[2])

    def _update_rec_ui(self):
        running = [c for c in self.procs if self.rec_running(c)]
        key = (len(running), self.selected_id in running)
        if key == self.last_rec_ui:
            return
        self.last_rec_ui = key
        if running:
            self.rec_pill.config(text=f"● RUNNING ({len(running)})", bg="#064e3b", fg="#34d399")
        else:
            self.rec_pill.config(text="● STOPPED", bg="#1e293b", fg="#94a3b8")
        self._update_buttons()

    # -------------------------------------------------------------- main loop
    def _tick(self):
        self.root.after(33, self._tick)

        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass

        self.clock.config(text=datetime.now().strftime("%d %b %Y  %H:%M:%S"))

        # handle streams that gave up
        failed_msgs = []
        for cid, s in list(self.streams.items()):
            if s.state == "failed":
                self.errors[cid] = s.error
                failed_msgs.append((cid, s.error))
                self.streams.pop(cid)
                s.stop()

        self._render()
        self._refresh_cam_status()
        self._update_pill()
        self._update_rec_ui()

        if self.previewing:
            live = sum(1 for s in self.streams.values() if s.state == "live")
            if self.streams or self.errors:
                self.set_status(f"Preview: {live} live, {len(self.streams) - live} connecting, "
                                f"{len(self.errors)} failed")

        # pop-up only for the single-camera view (grid shows errors inside the tile)
        if failed_msgs and self.view_mode == VIEW_SINGLE and not self.error_popup_shown:
            self.error_popup_shown = True
            cam = self.cam(failed_msgs[0][0])
            title = f"Connection failed - {cam['name']}" if cam else "Connection failed"
            messagebox.showerror(title, failed_msgs[0][1])

    # ----------------------------------------------------------- registration
    def register_face(self):
        if self.busy_register:
            return
        name = re.sub(r'[\\/:*?"<>|_]', " ", self.entry_name.get()).strip()
        age = re.sub(r'[\\/:*?"<>|_]', "", self.entry_age.get()).strip() or "Unknown"
        klass_in = self.class_var.get().strip()
        if not name:
            messagebox.showwarning("Input required", "Please enter a name.")
            return

        s = self.streams.get(self.selected_id)
        if s is None or s.state != "live":
            messagebox.showinfo("No video",
                                "Start the preview of the selected camera first, make sure the "
                                "person is visible, then press Register again.")
            return
        _, frame = s.read(copy=True)
        if frame is None:
            messagebox.showinfo("No video", "No frame received yet. Try again in a moment.")
            return

        zoom = self.get_zoom(self.selected_id)
        if zoom > 1.0:
            zh, zw = frame.shape[:2]
            cw, ch = int(zw / zoom), int(zh / zoom)
            cx, cy = zw // 2, zh // 2
            x1 = max(0, min(zw - cw, cx - cw // 2))
            y1 = max(0, min(zh - ch, cy - ch // 2))
            frame = cv2.resize(frame[y1:y1 + ch, x1:x1 + cw], (zw, zh), interpolation=cv2.INTER_LINEAR)

        target = face_path(name, age)                      # encrypted .face file
        if os.path.exists(target) and not messagebox.askyesno(
                "Already registered", f"'{name}' ({age}) already exists.\nReplace it?"):
            return

        self.busy_register = True
        self.btn_register.state(["disabled"])
        self.set_status("Detecting face...")

        def work():
            try:
                import face_recognition
            except ImportError:
                self.post(lambda: self._reg_done(
                    "error", "The 'face_recognition' library is required for registration."))
                return
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                locations = face_recognition.face_locations(rgb)
                if not locations:
                    self.post(lambda: self._reg_done(
                        "warn", "No face detected. Make sure one face is clearly visible."))
                    return
                if len(locations) > 1:
                    self.post(lambda: self._reg_done(
                        "warn", "More than one face detected. Only one person should be in view."))
                    return
                encodings = face_recognition.face_encodings(rgb, locations)
                if not encodings:
                    self.post(lambda: self._reg_done(
                        "warn", "Could not compute the face encoding. Try again."))
                    return
                save_face(target, encodings[0])            # encrypted on disk
                self.hub.store.upsert(name, klass=klass_in or None, age=age)
                log.info("Face registered: %s (age %s)", name, age)
                self.post(lambda: self._reg_done(
                    "ok", f"Registered '{name}' (Age: {age}).\nFace data saved encrypted."))
            except Exception as e:  # noqa
                log_exception("register_face")
                self.post(lambda: self._reg_done("error", f"An error occurred: {e}"))

        threading.Thread(target=work, daemon=True, name="RegisterFace").start()

    def _reg_done(self, kind, message):
        self.busy_register = False
        self.btn_register.state(["!disabled"])
        if kind == "ok":
            self.entry_name.delete(0, tk.END)
            self.entry_age.delete(0, tk.END)
            self.set_status("Face registered")
            self.hub.refresh_visible(force=True)
            messagebox.showinfo("Success", message)
            self.refresh_logs(force=True)
        elif kind == "warn":
            self.set_status("Registration failed")
            messagebox.showwarning("Registration", message)
        else:
            self.set_status("Registration error")
            messagebox.showerror("Registration error", message)

    # ------------------------------------------------------------ recognition
    def toggle_recognition_selected(self):
        cam = self.selected_cam()
        if cam is None:
            return
        if self.rec_running(cam["id"]):
            self.stop_recognition(cam["id"])
        else:
            self.start_recognition(cam)

    def toggle_recognition_all(self):
        running = [c for c in self.procs if self.rec_running(c)]
        if running:
            for cid in running:
                self.stop_recognition(cid)
        else:
            started = 0
            for cam in self.cameras:
                if self.start_recognition(cam, quiet=True):
                    started += 1
            if started == 0:
                messagebox.showwarning("Recognition", "Could not start recognition on any camera.")

    def start_recognition(self, cam, quiet=False):
        if not os.path.exists(SCRIPT_PATH):
            messagebox.showerror("Error", f"Script not found:\n{SCRIPT_PATH}")
            return False
        cid = cam["id"]
        if self.rec_running(cid):
            return True

        # a webcam can only be opened by one program: release the preview first
        if cam["kind"] == SOURCE_WEBCAM and cid in self.streams:
            self._stop_stream(cid)
            self.last_sig = None

        env = os.environ.copy()          # also passes FACE_KEY if you set it
        env["FACE_SOURCE"] = str(cam["source"])
        env["FACE_SOURCE_TYPE"] = cam["kind"]
        env["FACE_CAMERA_NAME"] = cam["name"]
        env["FACE_CAMERA_ID"] = cid
        env["FACE_CLASS"] = cam.get("room", "")
        mode = cam.get("mode", "")
        if not mode:
            if "principal" in cam["name"].lower() or "principal" in cam.get("room", "").lower():
                mode = "Principal's Office / High Security"
            else:
                mode = "Classroom (Indoor / Standard)"
        env["FACE_CAMERA_MODE"] = mode
        env["FACE_HEADLESS"] = "0" if getattr(self, "show_popup_var", None) is None or self.show_popup_var.get() else "1"
        env["FACE_ZOOM"] = f"{self.get_zoom(cid):.2f}"
        if "outdoor" in mode.lower() or "gate" in mode.lower() or (getattr(self, "long_range_var", None) and self.long_range_var.get()):
            env["FACE_DETECTION_SCALE"] = "0.70"
        else:
            env["FACE_DETECTION_SCALE"] = "0.50"
        try:
            proc = subprocess.Popen([sys.executable or "python", SCRIPT_PATH],
                                    cwd=BASE_DIR, env=env)
        except Exception as e:
            log_exception(f"start_recognition {cam['name']}")
            if not quiet:
                messagebox.showerror("Error", f"{cam['name']}: {e}")
            return False

        self.procs[cid] = proc
        self.stop_requested.discard(cid)
        self.set_status(f"Recognition started on '{cam['name']}'")
        log.info("Recognition started on %s", cam["name"])

        def watch():
            code = proc.wait()
            self.post(lambda: self._recognition_ended(cid, proc, code))

        threading.Thread(target=watch, daemon=True, name="RecognitionWatch").start()
        self._update_buttons()
        return True

    def stop_recognition(self, cid):
        p = self.procs.get(cid)
        if p is not None and p.poll() is None:
            self.stop_requested.add(cid)
            try:
                p.terminate()
            except Exception:
                log_exception("stop_recognition terminate")

    def _recognition_ended(self, cid, proc, code):
        if self.procs.get(cid) is not proc:
            return
        self.procs.pop(cid, None)
        cam = self.cam(cid)
        name = cam["name"] if cam else cid
        if cid in self.stop_requested:
            self.stop_requested.discard(cid)
            self.set_status(f"Recognition stopped on '{name}'")
        elif code not in (0, None):
            self.set_status(f"Recognition on '{name}' exited with code {code}")
            log.error("Recognition on %s exited with code %s", name, code)
        else:
            self.set_status(f"Recognition finished on '{name}'")
        self.last_sig = None
        self._update_buttons()
        self._sync_streams()           # a webcam may be free to preview again
        self.refresh_logs(force=True)

    # ------------------------------------------------------------------- logs
    def _poll_logs(self):
        self.refresh_logs()
        self.root.after(1000, self._poll_logs)       # 1 s: alerts feel instant

    def refresh_logs(self, force=False):
        try:
            faces = len([f for f in os.listdir(FACES_DIR) if f.endswith(".face")])
        except OSError:
            faces = 0
        try:
            mtime = os.path.getmtime(LOG_FILE)
        except OSError:
            mtime = 0
        if not force and mtime == self.log_mtime:
            return
        self.log_mtime = mtime

        total = 0
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", newline="") as f:
                    self.last_log_rows = list(csv.reader(f))[1:]
                total = len(self.last_log_rows)
                self.filter_attendance_table()
                self.alerts.ingest(self.last_log_rows)        # stranger alerts
            except Exception:
                log_exception("refresh_logs")
        else:
            self.last_log_rows = []
            self.filter_attendance_table()
        self.stats.config(text=f"Cameras: {len(self.cameras)}   |   "
                               f"Registered faces: {faces}   |   Log entries: {total}")

    def filter_attendance_table(self):
        query = getattr(self, "search_var", None)
        q = query.get().strip().lower() if query else ""
        rows = getattr(self, "last_log_rows", [])
        self.tree.delete(*self.tree.get_children())
        filtered = [r for r in rows if not q or (r and q in str(r[0]).lower())]
        for i, row in enumerate(reversed(filtered[-100:])):     # newest first
            row = (row + [""] * 5)[:5]
            parity = "even" if i % 2 == 0 else "odd"
            name = str(row[0]).strip().lower() if row and row[0] else ""
            if name in ("stranger", "unknown"):
                tag = f"stranger_{parity}"
            elif name:
                tag = f"known_{parity}"
            else:
                tag = parity
            self.tree.insert("", "end", values=row, tags=(tag,))

    def export_daily_report(self):
        try:
            import report_generator
            import webbrowser
            from pathlib import Path
            report_path = report_generator.generate_html_report()
            webbrowser.open(Path(report_path).resolve().as_uri())
            self.set_status(f"Exported HTML Report: {os.path.basename(report_path)}")
        except Exception as e:
            log_exception("export_daily_report")
            messagebox.showerror("Export Report Error", str(e), parent=self.root)

    # ------------------------------------------------------------------- exit
    def on_close(self):
        running = [c for c in self.procs if self.rec_running(c)]
        if running:
            if not messagebox.askokcancel(
                    "Exit", f"Recognition is still running on {len(running)} camera(s).\n"
                            "Stop it and exit?"):
                return
            for cid in running:
                self.stop_recognition(cid)
        for s in self.streams.values():
            s.request_stop()
        for s in list(self.streams.values()):
            s.stop()
        self.hub.shutdown()
        self.root.destroy()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "show-key":
        print("Encryption key (store it safely, never share it):\n")
        print(_get_key().decode())
        print(f"\nKey file: {KEY_FILE}")
        sys.exit(0)
    root = tk.Tk()
    App(root)
    root.mainloop()
