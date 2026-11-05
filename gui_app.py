"""
Face & Emotion Recognition Dashboard  v2
  - Multiple cameras (Webcam / CCTV-IP camera / Video file) - add, edit, remove
  - Start Preview / Stop Preview
  - Single-camera view or Grid view (all cameras at once)
  - Run recognition on the selected camera or on all cameras

Each recognition process receives these environment variables:
  FACE_SOURCE        webcam index, stream URL or file path
  FACE_SOURCE_TYPE   "Webcam" / "CCTV / IP Camera" / "Video File"
  FACE_CAMERA_NAME   the camera name you gave it
  FACE_CAMERA_ID     internal id
(see the note at the bottom of this file for the 3-line change in your script)
"""
import os

# Must be set BEFORE importing cv2: TCP is far more reliable than UDP for RTSP.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import re
import sys
import csv
import json
import math
import time
import uuid
import queue
import threading
import subprocess
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cv2
import numpy as np
from PIL import Image, ImageTk

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(BASE_DIR, "face_emotion_combined.py")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "recognized_faces.csv")
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


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def default_camera():
    return {"id": uuid.uuid4().hex[:8], "name": "Webcam 0", "kind": SOURCE_WEBCAM, "source": 0,
            "room": "Classroom 1", "mode": CAMERA_MODES[0]}


def load_config():
    cfg = {"cameras": [], "selected": None, "view_mode": VIEW_SINGLE}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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
    except Exception:
        pass
    if not cfg["cameras"]:
        cfg["cameras"] = [default_camera()]
    ids = [c["id"] for c in cfg["cameras"]]
    if cfg.get("selected") not in ids:
        cfg["selected"] = ids[0]
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


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
        self.thread = threading.Thread(target=self._run, daemon=True)
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
                        pass
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
                    if reconnects > self.MAX_RECONNECTS:
                        self._fail("Lost connection to the camera and could not reconnect.")
                        return
                    time.sleep(1)
        finally:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
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
        self.result = {"name": name, "kind": kind, "source": source,
                       "room": self.room_var.get().strip()}
        self.destroy()


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
        self.stats = tk.Label(bar, text="", bg=C["statusbar"], fg=C["text_sec"], font=FONT_S)
        self.stats.pack(side="right", padx=18)

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
                                  width=20, values=[VIEW_SINGLE, VIEW_GRID])
        view_combo.pack(side="right")
        view_combo.bind("<<ComboboxSelected>>", lambda e: self._on_view_change())
        ttk.Label(toolbar, text="View:", style="Card.TLabel").pack(side="right", padx=(0, 6))

        self.video_box = tk.Frame(video_body, bg=C["video"], height=340)
        self.video_box.pack(fill="both", expand=True)
        self.video_box.pack_propagate(False)
        self.video_label = tk.Label(self.video_box, bg=C["video"], fg="#64748b",
                                    font=("Segoe UI", 12), text="")
        self.video_label.pack(fill="both", expand=True)
        self.video_label.bind("<Button-1>", self._on_video_click)

        # ---------------- Right column ----------------
        right_scroll = ScrollFrame(body, width=390)
        right_scroll.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=(0, 12))
        right = right_scroll.inner

        # Cameras card
        cam_card, cam_body = self._card(right, "Cameras", "Add as many cameras as you need")
        cam_card.pack(fill="x", pady=(0, 12))

        tree_wrap = ttk.Frame(cam_body, style="Inner.TFrame")
        tree_wrap.pack(fill="x")
        self.cam_tree = ttk.Treeview(tree_wrap, columns=("name", "room", "type", "status"),
                                     show="headings", height=4, selectmode="browse")
        for col, text, w, anchor in (("name", "Name", 100, "w"), ("room", "Class", 75, "center"),
                                     ("type", "Type", 65, "center"), ("status", "Status", 85, "center")):
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
        ttk.Button(act, text="Open Logs & Snapshots", style="Secondary.TButton",
                   command=lambda: open_folder(LOGS_DIR)).pack(fill="x", pady=(8, 0))

        # ---------------- Logs card ----------------
        log_card, log_body = self._card(body, "Recent Attendance & Recognition")
        log_card.grid(row=1, column=0, sticky="nsew", padx=(0, 14))

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
            self.cam_tree.insert("", "end", iid=c["id"],
                                 values=(c["name"], c.get("room") or "-", KIND_SHORT[c["kind"]], "Idle"),
                                 tags=("idle",))
        self.last_cam_status = {}
        if self.selected_id and self.cam_tree.exists(self.selected_id):
            self.cam_tree.selection_set(self.selected_id)
            self.cam_tree.see(self.selected_id)
        self._update_buttons()

    def _on_select(self, _event=None):
        sel = self.cam_tree.selection()
        if not sel:
            return
        self.selected_id = sel[0]
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
            h, w = frame.shape[:2]
            sc = min(tw / w, th / h)
            nw, nh = max(1, int(w * sc)), max(1, int(h * sc))
            interp = cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR
            small = cv2.resize(frame, (nw, nh), interpolation=interp)
            ox, oy = (tw - nw) // 2, (th - nh) // 2
            tile[oy:oy + nh, ox:ox + nw] = small
            stamp = f"{cam['name']}   {datetime.now():%H:%M:%S}"
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

        bw = max(self.video_box.winfo_width(), 200)
        bh = max(self.video_box.winfo_height(), 150)
        sig = (bw, bh, self.view_mode, self.selected_id,
               tuple((c["id"], c["name"]) for c in cams),
               tuple((cid, s.frame_id, s.state) for cid, s in self.streams.items()),
               tuple(sorted(self.errors)),
               tuple(sorted(c for c in self.procs if self.rec_running(c))))
        if sig == self.last_sig:
            return
        self.last_sig = sig
        self.placeholder_text = None

        n = len(cams)
        cols = 1 if n == 1 else math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        gap = 4 if n > 1 else 0
        tw = (bw - gap * (cols - 1)) // cols
        th = (bh - gap * (rows - 1)) // rows

        canvas = np.empty((bh, bw, 3), np.uint8)
        canvas[:] = BG_BGR
        for i, cam in enumerate(cams):
            r, c = divmod(i, cols)
            x, y = c * (tw + gap), r * (th + gap)
            highlight = n > 1 and cam["id"] == self.selected_id
            canvas[y:y + th, x:x + tw] = self._tile(cam, tw, th, highlight)
        self.layout = (cols, rows, tw, th, gap, [c["id"] for c in cams])

        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.video_label.config(image=imgtk, text="")
        self.video_label.imgtk = imgtk

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

        target = os.path.join(FACES_DIR, f"{name}_{age}.npy")
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
                np.save(target, encodings[0])
                self.rebuild_known_database()
                self.hub.store.upsert(name, klass=klass_in or None, age=age)
                self.post(lambda: self._reg_done(
                    "ok", f"Registered '{name}' (Age: {age}).\nDatabase updated."))
            except Exception as e:  # noqa
                self.post(lambda: self._reg_done("error", f"An error occurred: {e}"))

        threading.Thread(target=work, daemon=True).start()

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

    @staticmethod
    def rebuild_known_database():
        """Rebuild known_face_*.npy files from faces/*.npy"""
        encodings, names, ages = [], [], []
        for file in sorted(os.listdir(FACES_DIR)):
            if not file.endswith(".npy"):
                continue
            try:
                data = np.load(os.path.join(FACES_DIR, file), allow_pickle=True)
                parts = file[:-4].split("_")
                if len(parts) >= 2:
                    face_name, face_age = " ".join(parts[:-1]), parts[-1]
                else:
                    face_name, face_age = parts[0], "-"
                encodings.append(data)
                names.append(face_name)
                ages.append(face_age)
            except Exception:
                pass
        if encodings:
            np.save(os.path.join(BASE_DIR, "known_face_encodings.npy"), encodings)
            np.save(os.path.join(BASE_DIR, "known_face_names.npy"), names)
            np.save(os.path.join(BASE_DIR, "known_face_ages.npy"), ages)

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

        env = os.environ.copy()
        env["FACE_SOURCE"] = str(cam["source"])
        env["FACE_SOURCE_TYPE"] = cam["kind"]
        env["FACE_CAMERA_NAME"] = cam["name"]
        env["FACE_CAMERA_ID"] = cid
        env["FACE_CLASS"] = cam.get("room", "")
        env["FACE_HEADLESS"] = "0" if getattr(self, "show_popup_var", None) is None or self.show_popup_var.get() else "1"
        env["FACE_DETECTION_SCALE"] = "0.65" if getattr(self, "long_range_var", None) and self.long_range_var.get() else "0.50"
        try:
            proc = subprocess.Popen([sys.executable or "python", SCRIPT_PATH],
                                    cwd=BASE_DIR, env=env)
        except Exception as e:
            if not quiet:
                messagebox.showerror("Error", f"{cam['name']}: {e}")
            return False

        self.procs[cid] = proc
        self.stop_requested.discard(cid)
        self.set_status(f"Recognition started on '{cam['name']}'")

        def watch():
            code = proc.wait()
            self.post(lambda: self._recognition_ended(cid, proc, code))

        threading.Thread(target=watch, daemon=True).start()
        self._update_buttons()
        return True

    def stop_recognition(self, cid):
        p = self.procs.get(cid)
        if p is not None and p.poll() is None:
            self.stop_requested.add(cid)
            try:
                p.terminate()
            except Exception:
                pass

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
        else:
            self.set_status(f"Recognition finished on '{name}'")
        self.last_sig = None
        self._update_buttons()
        self._sync_streams()           # a webcam may be free to preview again
        self.refresh_logs(force=True)

    # ------------------------------------------------------------------- logs
    def _poll_logs(self):
        self.refresh_logs()
        self.root.after(3000, self._poll_logs)

    def refresh_logs(self, force=False):
        try:
            faces = len([f for f in os.listdir(FACES_DIR) if f.endswith(".npy")])
        except OSError:
            faces = 0
        try:
            mtime = os.path.getmtime(LOG_FILE)
        except OSError:
            mtime = 0
        if not force and mtime == self.log_mtime:
            return
        self.log_mtime = mtime

        self.tree.delete(*self.tree.get_children())
        total = 0
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", newline="") as f:
                    rows = list(csv.reader(f))[1:]
                total = len(rows)
                for i, row in enumerate(reversed(rows[-100:])):     # newest first
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
            except Exception:
                pass
        self.stats.config(text=f"Cameras: {len(self.cameras)}   |   "
                               f"Registered faces: {faces}   |   Log entries: {total}")

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
    root = tk.Tk()
    App(root)
    root.mainloop()

# ---------------------------------------------------------------------------
# NOTE - make face_emotion_combined.py use the camera chosen in the dashboard.
# Replace your existing   cap = cv2.VideoCapture(0)   with:
#
#   import os
#   src = os.environ.get("FACE_SOURCE", "0")
#   src = int(src) if src.isdigit() else src
#   cap = cv2.VideoCapture(src)
#
# And give every recognition window its own title (needed when running on
# several cameras), e.g.:
#
#   cam_name = os.environ.get("FACE_CAMERA_NAME", "Camera")
#   cv2.imshow(f"Recognition - {cam_name}", frame)
#
# (use the same title in cv2.waitKey / destroyWindow calls if you have them)
# ---------------------------------------------------------------------------
