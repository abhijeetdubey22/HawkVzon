"""
School layer for the Face & Emotion Recognition dashboard.

Adds three dashboards (tabs) next to the Control Room:
  - Students : class-wise camera/stream status + live attendance
  - Parents  : parent contact details (Gmail, phone, class) + automatic alert system
  - Staff    : college-wide overview, absentees, CSV reports

Data files (created automatically):
  data/students.json         students, their class and parent contact details
  data/school_settings.json  alert settings (Gmail app password is stored here - keep private)
  data/alerts_state.json     which alerts were already sent today (prevents duplicates)
  logs/alerts_log.csv        history of every alert sent
  exports/                   attendance reports exported by staff
"""
import os
import re
import csv
import json
import time
import ssl
import base64
import socket
import hashlib
import smtplib
import subprocess
import sys
import threading
import traceback
import queue
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, time as dtime
from email.message import EmailMessage

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from theme import (C, FONT, FONT_B, FONT_S, FONT_T, Kpi, make_card, make_tree,
                   fill_tree, ScrollFrame)

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
FACES_DIR = os.path.join(BASE_DIR, "faces")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")
LOG_FILE = os.path.join(LOGS_DIR, "recognized_faces.csv")
ALERT_LOG = os.path.join(LOGS_DIR, "alerts_log.csv")
STUDENTS_FILE = os.path.join(DATA_DIR, "students.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "school_settings.json")
STATE_FILE = os.path.join(DATA_DIR, "alerts_state.json")
for _d in (DATA_DIR, LOGS_DIR, FACES_DIR, EXPORT_DIR, SNAPSHOTS_DIR):
    os.makedirs(_d, exist_ok=True)

UNASSIGNED = "Unassigned"
ONLINE = {"Recognizing", "Live", "Online"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STATUS_TAG = {"Present": "present", "Late": "late", "Absent": "absent",
              "Not arrived": "idle", "No class": "idle"}

DEFAULT_SETTINGS = {
    "school_name": "My College",
    "late_time": "09:15",
    "absent_cutoff": "10:00",
    "min_match": 50,
    "working_days": [0, 1, 2, 3, 4, 5],
    "auto_alerts": False,
    "alert_arrival": True,
    "alert_late": True,
    "alert_absent": True,
    "use_email": False,
    "use_sms": False,
    "use_whatsapp": True,
    "alert_unknown": True,
    "gmail_user": "",
    "gmail_password": "",
    "twilio_sid": "",
    "twilio_token": "",
    "twilio_from": "whatsapp:+14155238886",
    "callmebot_key": "",
    "default_country_code": "+91",
    "pin_salt": "",
    "pin_hash": "",
    "staff_email": "",
    "staff_phone": "",
    "whatsapp_staff": "",
    "alert_principal": True,
    "authorized_principal": "Principal, Director, Admin",
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def norm_class(s):
    return norm(s) or norm(UNASSIGNED)


def hhmm(text, default):
    try:
        h, m = str(text).strip().split(":")[:2]
        return dtime(int(h), int(m))
    except Exception:
        return default


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        traceback.print_exc()


def fmt_time(dt):
    return dt.strftime("%I:%M %p").lstrip("0") if dt else "-"


def normalize_phone(raw, cc="+91"):
    s = re.sub(r"[^\d+]", "", str(raw or ""))
    if not s:
        return ""
    if s.startswith("+"):
        return s if len(s) >= 11 else ""
    if s.startswith("00"):
        return "+" + s[2:]
    if len(s) == 11 and s.startswith("0"):
        s = s[1:]
    if len(s) == 10:
        return cc + s
    return ("+" + s) if len(s) > 10 else ""


def get_latest_snapshot(prefix=None):
    """Finds the newest image snapshot in the snapshots directory."""
    try:
        if not os.path.exists(SNAPSHOTS_DIR):
            return None
        files = [os.path.join(SNAPSHOTS_DIR, f) for f in os.listdir(SNAPSHOTS_DIR)
                 if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        if prefix:
            matching = [f for f in files if prefix.lower() in os.path.basename(f).lower()]
            if matching:
                files = matching
        if files:
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return files[0]
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
class Settings:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = dict(DEFAULT_SETTINGS)
        self.data.update(read_json(SETTINGS_FILE, {}))

    def get(self, key, default=None):
        with self.lock:
            val = self.data.get(key)
            if val is not None:
                return val
            if key in DEFAULT_SETTINGS and DEFAULT_SETTINGS[key] is not None:
                return DEFAULT_SETTINGS[key]
            return default

    def update(self, **kw):
        with self.lock:
            self.data.update(kw)
            write_json(SETTINGS_FILE, self.data)


# --------------------------------------------------------------------------
# Students store
# --------------------------------------------------------------------------
class StudentStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.students = read_json(STUDENTS_FILE, {})

    @staticmethod
    def key(name):
        return norm(name)

    def _save(self):
        write_json(STUDENTS_FILE, self.students)

    def sync_from_faces(self):
        """Create a record for every registered face that has none yet."""
        try:
            files = sorted(os.listdir(FACES_DIR))
        except OSError:
            return
        for file in files:
            if not file.endswith(".npy"):
                continue
            parts = file[:-4].split("_")
            name = " ".join(parts[:-1]) if len(parts) >= 2 else parts[0]
            age = parts[-1] if len(parts) >= 2 else ""
            if self.key(name) not in self.students:
                self.upsert(name, age=age)

    def upsert(self, name, **fields):
        name = re.sub(r"\s+", " ", str(name).strip())
        if not name:
            return None
        key = self.key(name)
        with self.lock:
            rec = self.students.get(key)
            if rec is None:
                rec = {"name": name, "klass": UNASSIGNED, "roll": "", "age": "",
                       "parent_name": "", "parent_email": "", "parent_phone": "",
                       "alerts": True}
                self.students[key] = rec
            for k, v in fields.items():
                if v is None:
                    continue
                if k == "klass" and not str(v).strip():
                    continue
                rec[k] = v
            self._save()
        return key

    def delete(self, key):
        with self.lock:
            self.students.pop(key, None)
            self._save()

    def get(self, key, default=None):
        with self.lock:
            rec = self.students.get(key)
            return dict(rec) if rec else default

    def all(self):
        with self.lock:
            rows = [dict(v) for v in self.students.values()]
        rows.sort(key=lambda r: (norm_class(r["klass"]) == norm(UNASSIGNED),
                                 norm(r["klass"]), norm(r["name"])))
        return rows


# --------------------------------------------------------------------------
# Attendance (reads logs/recognized_faces.csv)
# --------------------------------------------------------------------------
TS_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S",
              "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S",
              "%Y-%m-%d_%H-%M-%S", "%Y%m%d_%H%M%S", "%d-%m-%Y %I:%M:%S %p",
              "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"]


def parse_ts(text):
    text = str(text).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class AttendanceReader:
    def __init__(self):
        self.cache = {}

    def records(self, day, min_match):
        """{student_key: {first, last, emotion, camera, count}} for that day."""
        try:
            st = os.stat(LOG_FILE)
            fsig = (st.st_mtime, st.st_size)
        except OSError:
            return {}
        ckey = (day, min_match)
        hit = self.cache.get(ckey)
        if hit and hit[0] == fsig:
            return hit[1]

        out = {}
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace", newline="") as f:
                for row in csv.reader(f):
                    if len(row) < 5:
                        continue
                    name = row[0].strip()
                    if norm(name) in ("name", "student", "person", "", "unknown", "unrecognized"):
                        continue
                    ts = parse_ts(row[4])
                    if ts is None or ts.date() != day:
                        continue
                    try:
                        match = float(str(row[2]).replace("%", "").strip())
                    except ValueError:
                        match = None
                    if match is not None and min_match and match < float(min_match):
                        continue
                    key = StudentStore.key(name)
                    rec = out.get(key)
                    emotion = row[3].strip()
                    camera = row[5].strip() if len(row) > 5 else ""
                    if rec is None:
                        out[key] = {"first": ts, "last": ts, "emotion": emotion,
                                    "camera": camera, "count": 1}
                    else:
                        rec["count"] += 1
                        if ts < rec["first"]:
                            rec["first"] = ts
                        if ts >= rec["last"]:
                            rec["last"], rec["emotion"] = ts, emotion
                            if camera:
                                rec["camera"] = camera
        except OSError:
            return {}
        if len(self.cache) > 6:
            self.cache.clear()
        self.cache[ckey] = (fsig, out)
        return out


def compute_status(rec, day, now, late_t, cutoff_t, working):
    if rec:
        return "Late" if rec["first"].time() > late_t else "Present"
    if not working:
        return "No class"
    if day < now.date():
        return "Absent"
    if day == now.date() and now.time() >= cutoff_t:
        return "Absent"
    return "Not arrived"


# --------------------------------------------------------------------------
# Messages, sending
# --------------------------------------------------------------------------
def compose(kind, st, rec, day, school):
    parent = st.get("parent_name") or "Parent / Guardian"
    name, klass = st["name"], st["klass"]
    when = fmt_time(rec["first"]) if rec else ""
    ds = day.strftime("%d %b %Y")
    sign = f"\n\nRegards,\n{school}"
    if kind == "arrival":
        subj = f"[{school}] {name} has arrived"
        body = f"Dear {parent},\n\n{name} ({klass}) was marked present on {ds} at {when}.{sign}"
        sms = f"{school}: {name} ({klass}) arrived at {when} on {ds}."
    elif kind == "late":
        subj = f"[{school}] {name} arrived late"
        body = f"Dear {parent},\n\n{name} ({klass}) arrived late on {ds} at {when}.{sign}"
        sms = f"{school}: {name} ({klass}) arrived late at {when} on {ds}."
    elif kind == "absent":
        subj = f"[{school}] {name} is absent today"
        body = (f"Dear {parent},\n\n{name} ({klass}) has not been marked present on {ds}.\n"
                "If you already informed the college you can ignore this message, "
                f"otherwise please contact the college office.{sign}")
        sms = f"{school}: {name} ({klass}) is absent on {ds}. Please contact the college if unexpected."
    elif kind == "security":
        cam_info = (rec.get("camera") if rec else "") or "Principal's Office"
        emotion = (rec.get("emotion") if rec else "") or "Unknown"
        subj = f"[SECURITY ALERT] [{school}] Unauthorized Entry in Principal's Office"
        body = (f"URGENT SECURITY ALERT\n\n"
                f"An unauthorized individual entered or was detected in the Principal's Office without permission.\n\n"
                f"  • Individual: {name}\n"
                f"  • Location: Principal's Office\n"
                f"  • Camera: {cam_info}\n"
                f"  • Time: {when or datetime.now().strftime('%I:%M %p')}\n"
                f"  • Date: {ds}\n"
                f"  • Detected Emotion: {emotion}\n\n"
                f"Please verify security camera feed and investigate immediately.{sign}")
        sms = (f"🚨 *[{school}] PRINCIPAL OFFICE INTRUSION*\n"
               f"Unauthorized entry detected!\n"
               f"👤 Individual: {name}\n"
               f"📍 Location: Principal's Office ({cam_info})\n"
               f"🕒 Time: {when or datetime.now().strftime('%I:%M %p')} on {ds}\n"
               f"📸 Snapshot attached below.")
    elif kind == "unknown":
        cam_info = (rec.get("camera") if rec else "") or "CCTV Camera"
        emotion = (rec.get("emotion") if rec else "") or "Unknown"
        subj = f"[SECURITY ALERT] [{school}] Unknown Person Detected"
        body = (f"SECURITY ALERT - UNKNOWN PERSON DETECTED\n\n"
                f"An unrecognized individual was captured by the security system.\n\n"
                f"  • Status: Unknown Person / Stranger\n"
                f"  • Camera: {cam_info}\n"
                f"  • Time: {when or datetime.now().strftime('%I:%M %p')}\n"
                f"  • Date: {ds}\n"
                f"  • Detected Emotion: {emotion}\n\n"
                f"A snapshot has been captured and attached.{sign}")
        sms = (f"🚨 *[{school}] UNKNOWN PERSON DETECTED*\n"
               f"Unrecognized person detected!\n"
               f"📍 Camera: {cam_info}\n"
               f"🕒 Time: {when or datetime.now().strftime('%I:%M %p')} on {ds}\n"
               f"🎭 Emotion: {emotion}\n"
               f"📸 Snapshot attached below.")
    else:
        subj = f"[{school}] Test message"
        body = f"This is a test message from the {school} attendance system.{sign}"
        sms = f"{school}: test message from the attendance system."
    return subj, body, sms


class Notifier:
    def __init__(self, settings):
        self.s = settings

    def send_email(self, to, subject, body):
        user = str(self.s.get("gmail_user")).strip()
        pw = str(self.s.get("gmail_password")).replace(" ", "")
        if not user or not pw:
            raise RuntimeError("Gmail address / app password not set (Parents tab > Gmail & SMS settings)")
        msg = EmailMessage()
        msg["From"] = f"{self.s.get('school_name')} <{user}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        ctx = ssl.create_default_context()
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25, context=ctx) as srv:
                srv.login(user, pw)
                srv.send_message(msg)
        except smtplib.SMTPAuthenticationError:
            raise RuntimeError("Gmail login failed - use a Google App Password (not your normal password)")

    def send_sms(self, to, body):
        sid = str(self.s.get("twilio_sid")).strip()
        token = str(self.s.get("twilio_token")).strip()
        frm = str(self.s.get("twilio_from")).strip()
        if not (sid and token and frm):
            raise RuntimeError("SMS (Twilio) settings are incomplete")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        data = urllib.parse.urlencode({"To": to, "From": frm, "Body": body}).encode()
        req = urllib.request.Request(url, data=data)
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req.add_header("Authorization", "Basic " + auth)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"SMS provider error {e.code}")

    def send_whatsapp(self, to, body, media_path=None):
        """Sends WhatsApp alert with snapshot attachment via Twilio or CallMeBot."""
        sid = str(self.s.get("twilio_sid", "")).strip()
        token = str(self.s.get("twilio_token", "")).strip()
        frm = str(self.s.get("twilio_from", "")).strip()
        cb_key = str(self.s.get("callmebot_key", "")).strip()

        target = re.sub(r"[^\d+]", "", str(to or ""))
        if not target:
            raise RuntimeError("WhatsApp recipient number not configured")

        # 1. Twilio WhatsApp API
        if sid and token:
            from_wa = frm if frm.startswith("whatsapp:") else f"whatsapp:{frm or '+14155238886'}"
            to_wa = target if target.startswith("whatsapp:") else f"whatsapp:{target}"
            payload = {"To": to_wa, "From": from_wa, "Body": body}

            if media_path and os.path.exists(media_path):
                img_url = self._upload_image_catbox(media_path)
                if img_url:
                    payload["MediaUrl"] = img_url
                    payload["Body"] = f"{body}\n\n📷 Snapshot link: {img_url}"

            url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
            req.add_header("Authorization", "Basic " + auth)
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    r.read()
                return
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"Twilio WhatsApp error {e.code}: {err[:120]}")

        # 2. CallMeBot WhatsApp API (Free alternative gateway)
        if cb_key:
            cb_phone = target.lstrip("+")
            msg_text = body
            if media_path and os.path.exists(media_path):
                img_url = self._upload_image_catbox(media_path)
                if img_url:
                    msg_text += f"\n\n📷 Snapshot: {img_url}"
            cb_url = f"https://api.callmebot.com/whatsapp.php?phone={cb_phone}&text={urllib.parse.quote_plus(msg_text)}&apikey={cb_key}"
            req = urllib.request.Request(cb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                r.read()
            return

        raise RuntimeError("WhatsApp settings incomplete. Enter Twilio SID/Token or CallMeBot API Key in Settings.")

    def _upload_image_catbox(self, path):
        """Uploads a snapshot to obtain a direct HTTPS media URL for WhatsApp."""
        try:
            if not os.path.exists(path):
                return None
            boundary = "----WebKitFormBoundary" + hashlib.md5(str(time.time()).encode()).hexdigest()
            fn = os.path.basename(path)
            with open(path, "rb") as f:
                img_bytes = f.read()
            body = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"reqtype\"\r\n\r\nfileupload\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"fileToUpload\"; filename=\"{fn}\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n"
            ).encode("latin1") + img_bytes + f"\r\n--{boundary}--\r\n".encode("latin1")
            req = urllib.request.Request("https://catbox.moe/user/api.php", data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                                  "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                res = r.read().decode("utf-8", errors="ignore").strip()
                if res.startswith("http"):
                    return res
        except Exception as e:
            print(f"[Snapshot Upload Note] {e}")
        return None


class AlertState:
    """Remembers which alerts were already sent today."""

    def __init__(self):
        self.lock = threading.Lock()
        self.day = str(date.today())
        self.sent = set()
        data = read_json(STATE_FILE, {})
        if data.get("day") == self.day:
            self.sent = set(data.get("sent", []))

    def _roll(self):
        today = str(date.today())
        if self.day != today:
            self.day, self.sent = today, set()

    def was_sent(self, key):
        with self.lock:
            self._roll()
            return key in self.sent

    def mark(self, key):
        with self.lock:
            self._roll()
            self.sent.add(key)
            write_json(STATE_FILE, {"day": self.day, "sent": sorted(self.sent)})

    def kinds_for(self, day, skey):
        with self.lock:
            return {k.split("|")[2] for k in self.sent
                    if k.startswith(f"{day}|{skey}|")}


class AlertService:
    """Background sender: one worker thread, so the UI never freezes."""

    def __init__(self, hub):
        self.hub = hub
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.notifier = Notifier(hub.settings)
        threading.Thread(target=self._worker, daemon=True).start()

    def enqueue(self, job):
        self.q.put(job)

    def stop(self):
        self.q.put(None)

    def _worker(self):
        while True:
            job = self.q.get()
            if job is None:
                return
            try:
                if job["channel"] == "email":
                    self.notifier.send_email(job["to"], job["subject"], job["body"])
                elif job["channel"] == "whatsapp":
                    self.notifier.send_whatsapp(job["to"], job["body"], job.get("media_path"))
                else:
                    self.notifier.send_sms(job["to"], job["body"])
                status = "Sent"
            except Exception as e:  # noqa
                status = ("Failed: " + str(e))[:140]
            self._log(job, status)
            self.hub.app.post(self.hub.on_alert_result)
            time.sleep(0.4)           # be gentle with Gmail rate limits

    def _log(self, job, status):
        with self.lock:
            new = not os.path.exists(ALERT_LOG)
            try:
                with open(ALERT_LOG, "a", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["Timestamp", "Student", "Class", "Type", "Channel", "To", "Status"])
                    w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job["student"],
                                job["klass"], job["kind"], job["channel"], job["to"], status])
            except OSError:
                pass


# --------------------------------------------------------------------------
# Dialog: Gmail / SMS settings
# --------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.s = settings
        self.title("WhatsApp & Security Alert Settings")
        self.configure(bg=C["card"])
        self.resizable(False, False)
        self.transient(parent)
        pad = ttk.Frame(self, style="Inner.TFrame", padding=20)
        pad.pack(fill="both", expand=True)
        pad.columnconfigure(1, weight=1)

        def row(r, label, key, show=None, hint=None):
            ttk.Label(pad, text=label, style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=str(self.s.get(key, "")))
            ttk.Entry(pad, textvariable=var, show=show, width=40).grid(
                row=r, column=1, sticky="ew", padx=(12, 0), pady=4)
            if hint:
                ttk.Label(pad, text=hint, style="Muted.TLabel").grid(
                    row=r + 1, column=1, sticky="w", padx=(12, 0))
            return var

        ttk.Label(pad, text="WhatsApp Alerts (WhatsApp Only)", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.v_school = row(1, "College / Campus name", "school_name")
        self.v_wa_phone = row(2, "Staff WhatsApp Number", "whatsapp_staff",
                              hint="e.g. +919876543210 (receives instant alerts with snapshot photo)")
        self.v_use_wa = tk.BooleanVar(value=bool(self.s.get("use_whatsapp", True)))
        ttk.Checkbutton(pad, text="Send Alerts via WhatsApp ONLY (Disable Email & SMS)",
                        variable=self.v_use_wa, style="Card.TCheckbutton").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 4))

        self.v_alert_unknown = tk.BooleanVar(value=bool(self.s.get("alert_unknown", True)))
        ttk.Checkbutton(pad, text="Alert on Unknown Person Detection (with Snapshot Photo)",
                        variable=self.v_alert_unknown, style="Card.TCheckbutton").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(2, 6))

        ttk.Label(pad, text="WhatsApp Gateway / API Provider", style="CardTitle.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(12, 4))
        self.v_sid = row(7, "Twilio Account SID", "twilio_sid", hint="From twilio.com/console")
        self.v_tok = row(9, "Twilio Auth Token", "twilio_token", show="*")
        self.v_from = row(11, "Twilio WhatsApp Sender", "twilio_from",
                          hint="e.g. whatsapp:+14155238886 (Twilio WhatsApp sandbox number)")
        self.v_cb_key = row(13, "CallMeBot API Key (Free Alternative)", "callmebot_key",
                            hint="Optional free bot key: message +34 941 07 20 00 on WhatsApp")
        self.v_cc = row(15, "Default Country Code", "default_country_code")

        ttk.Label(pad, text="Principal's Office Intrusion Rules", style="CardTitle.TLabel").grid(
            row=17, column=0, columnspan=2, sticky="w", pady=(12, 4))
        self.v_auth = row(18, "Authorized Personnel", "authorized_principal",
                          hint="Comma-separated names (e.g. Principal, Admin). Others trigger alert.")
        self.v_alert_principal = tk.BooleanVar(value=bool(self.s.get("alert_principal", True)))
        ttk.Checkbutton(pad, text="Enable Principal's Office Intrusion Alert",
                        variable=self.v_alert_principal, style="Card.TCheckbutton").grid(
            row=20, column=0, columnspan=2, sticky="w", pady=(4, 6))

        ttk.Label(pad, style="Muted.TLabel", justify="left",
                  text="Configuration is stored securely on this computer in data/school_settings.json.").grid(
            row=21, column=0, columnspan=2, sticky="w", pady=(10, 0))
        btns = ttk.Frame(pad, style="Inner.TFrame")
        btns.grid(row=22, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", style="Secondary.TButton",
                   command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Save Settings", style="Success.TButton",
                   command=self._save).pack(side="left")

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + 40
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    def _save(self):
        wa_num = self.v_wa_phone.get().strip()
        use_wa = bool(self.v_use_wa.get())
        self.s.update(
            school_name=self.v_school.get().strip() or "My College",
            whatsapp_staff=wa_num,
            staff_phone=wa_num,
            use_whatsapp=use_wa,
            alert_unknown=bool(self.v_alert_unknown.get()),
            use_email=False if use_wa else bool(self.s.get("use_email")),
            use_sms=False if use_wa else bool(self.s.get("use_sms")),
            twilio_sid=self.v_sid.get().strip(),
            twilio_token=self.v_tok.get().strip(),
            twilio_from=self.v_from.get().strip() or "whatsapp:+14155238886",
            callmebot_key=self.v_cb_key.get().strip(),
            default_country_code=self.v_cc.get().strip() or "+91",
            authorized_principal=self.v_auth.get().strip() or "Principal, Director, Admin",
            alert_principal=bool(self.v_alert_principal.get()))
        self.destroy()


# --------------------------------------------------------------------------
# Dashboard 1: Students (class-wise stream status + attendance)
# --------------------------------------------------------------------------
class StudentsTab(tk.Frame):
    STATUS_FILTERS = ["All", "Present", "Late", "Absent", "Not arrived"]

    def __init__(self, parent, hub):
        super().__init__(parent, bg=C["bg"])
        self.hub = hub
        self.sigs = {}
        self.cur_class = "__all__"
        self.groups = {}
        self.all_rows = []

        pad = tk.Frame(self, bg=C["bg"])
        pad.pack(fill="both", expand=True, padx=20, pady=(10, 8))
        pad.columnconfigure(0, weight=3, uniform="c")
        pad.columnconfigure(1, weight=2, uniform="c")
        pad.rowconfigure(2, weight=1)
        pad.rowconfigure(3, weight=2)

        tb = tk.Frame(pad, bg=C["bg"])
        tb.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        tk.Label(tb, text="Class-wise Streams & Attendance", font=FONT_T,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        self.date_lbl = tk.Label(tb, text="", font=FONT, bg=C["bg"], fg=C["muted"])
        self.date_lbl.pack(side="left", padx=14)
        ttk.Button(tb, text="Refresh", style="Secondary.TButton",
                   command=lambda: hub.refresh_visible(force=True)).pack(side="right")
        self.status_var = tk.StringVar(value="All")
        sc = ttk.Combobox(tb, textvariable=self.status_var, state="readonly", width=12,
                          values=self.STATUS_FILTERS)
        sc.pack(side="right", padx=8)
        sc.bind("<<ComboboxSelected>>", lambda e: self.render_details())
        ttk.Label(tb, text="Status:").pack(side="right")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.render_details())
        ttk.Entry(tb, textvariable=self.search_var, width=22).pack(side="right", padx=(0, 14))
        ttk.Label(tb, text="Search:").pack(side="right", padx=(0, 4))

        kp = tk.Frame(pad, bg=C["bg"])
        kp.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.kpis = {}
        for i, (key, title, color) in enumerate((
                ("total", "Total Students", C["primary"]), ("present", "Present", C["success"]),
                ("late", "Late Arrival", C["amber"]), ("absent", "Absent", C["danger"]),
                ("notyet", "Not Arrived", C["grey"]))):
            kp.columnconfigure(i, weight=1, uniform="k")
            k = Kpi(kp, title, color)
            k.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.kpis[key] = k

        c1, b1 = make_card(pad, "Classes & Stream Status",
                           "Select a class to see its cameras and students")
        c1.grid(row=2, column=0, sticky="nsew", padx=(0, 14), pady=(0, 12))
        self.class_tree = make_tree(
            b1, ("class", "cams", "stream", "present", "late", "absent", "total"),
            ("Class", "Cameras", "Stream", "Present", "Late", "Absent", "Total"),
            (170, 70, 110, 70, 60, 70, 60), height=5,
            anchors=("w", "center", "center", "center", "center", "center", "center"))
        self.class_tree.bind("<<TreeviewSelect>>", self._on_class)

        c2, b2 = make_card(pad, "Cameras in selected class")
        c2.grid(row=2, column=1, sticky="nsew", pady=(0, 12))
        self.cam_tree = make_tree(b2, ("camera", "class", "type", "status"),
                                  ("Camera", "Class", "Type", "Status"),
                                  (120, 90, 60, 100), height=5,
                                  anchors=("w", "center", "center", "center"))

        c3, b3 = make_card(pad, "Students")
        c3.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.stu_tree = make_tree(
            b3, ("name", "class", "status", "first", "last", "emotion", "camera"),
            ("Student", "Class", "Status", "First seen", "Last seen", "Last emotion", "Camera"),
            (200, 120, 110, 100, 100, 110, 130), height=7,
            anchors=("w", "center", "center", "center", "center", "center", "center"))

    def _on_class(self, _e=None):
        sel = self.class_tree.selection()
        if sel and sel[0] != self.cur_class:
            self.cur_class = sel[0]
            self.render_details()

    def refresh(self, report):
        self.date_lbl.config(text=datetime.now().strftime("%A, %d %B %Y"))
        self.groups = {g["norm"]: g for g in self.hub.class_groups(report)}
        self.all_rows = report
        hub = self.hub

        rows = []
        all_cams = list(hub.app.cameras)
        txt, tag, _ = hub.stream_summary(all_cams)
        rows.append(("__all__", ("All classes", len(all_cams), txt,
                                 sum(r["status"] == "Present" for r in report),
                                 sum(r["status"] == "Late" for r in report),
                                 sum(r["status"] == "Absent" for r in report),
                                 len(report)), (tag,)))
        for g in self.groups.values():
            txt, tag, _ = hub.stream_summary(g["cams"])
            rr = g["rows"]
            rows.append((g["norm"], (g["name"], len(g["cams"]), txt,
                                     sum(r["status"] == "Present" for r in rr),
                                     sum(r["status"] == "Late" for r in rr),
                                     sum(r["status"] == "Absent" for r in rr),
                                     len(rr)), (tag,)))
        if fill_tree(self.class_tree, rows, self.sigs, "classes"):
            if self.cur_class not in {r[0] for r in rows}:
                self.cur_class = "__all__"
            if self.class_tree.exists(self.cur_class):
                self.class_tree.selection_set(self.cur_class)
        elif not self.class_tree.selection() and self.class_tree.exists(self.cur_class):
            self.class_tree.selection_set(self.cur_class)
        self.render_details()

    def render_details(self):
        hub = self.hub
        if self.cur_class == "__all__" or self.cur_class not in self.groups:
            scope_rows = self.all_rows
            scope_cams = list(hub.app.cameras)
        else:
            g = self.groups[self.cur_class]
            scope_rows, scope_cams = g["rows"], g["cams"]

        # KPIs
        self.kpis["total"].set(len(scope_rows))
        for key, status in (("present", "Present"), ("late", "Late"),
                            ("absent", "Absent"), ("notyet", "Not arrived")):
            self.kpis[key].set(sum(r["status"] == status for r in scope_rows))

        # cameras
        cam_rows = []
        for c in scope_cams:
            st = hub.camera_status(c)
            tag = ("ok" if st in ONLINE else "bad" if st == "Offline"
                   else "warn" if st in ("Connecting", "Reconnecting") else "idle")
            cam_rows.append((c["id"], (c["name"], c.get("room") or "-",
                                       {"Webcam": "Webcam", "CCTV / IP Camera": "CCTV",
                                        "Video File": "File"}.get(c["kind"], c["kind"]), st),
                             (tag,)))
        fill_tree(self.cam_tree, cam_rows, self.sigs, "cams")

        # students
        want = self.status_var.get()
        q = norm(self.search_var.get())
        stu_rows = []
        for r in scope_rows:
            if want != "All" and r["status"] != want:
                continue
            if q and q not in norm(r["student"]["name"]):
                continue
            stu_rows.append((r["key"], (r["student"]["name"], r["klass"], r["status"],
                                        fmt_time(r["first"]), fmt_time(r["last"]),
                                        r["emotion"] or "-", r["camera"] or "-"),
                             (STATUS_TAG.get(r["status"], "idle"),)))
        fill_tree(self.stu_tree, stu_rows, self.sigs, "students")


# --------------------------------------------------------------------------
# Dashboard 2: Parents (contacts + alert system)
# --------------------------------------------------------------------------
class ParentsTab(tk.Frame):
    def __init__(self, parent, hub):
        super().__init__(parent, bg=C["bg"])
        self.hub = hub
        self.sigs = {}
        self.loaded_key = None
        self.new_mode = False

        pad = tk.Frame(self, bg=C["bg"])
        pad.pack(fill="both", expand=True, padx=20, pady=(10, 8))
        pad.columnconfigure(0, weight=1)
        pad.columnconfigure(1, weight=0, minsize=430)
        pad.rowconfigure(0, weight=3)
        pad.rowconfigure(1, weight=2)

        # ----- contacts -----
        card, body = make_card(pad, "Parents & Contact Details",
                               "Select a student, edit the parent's email / phone and press Save")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 14), pady=(0, 12))
        tools = ttk.Frame(body, style="Inner.TFrame")
        tools.pack(fill="x", pady=(0, 8))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh())
        ttk.Entry(tools, textvariable=self.search_var, width=24).pack(side="left")
        self.filter_var = tk.StringVar(value="All classes")
        self.filter_combo = ttk.Combobox(tools, textvariable=self.filter_var, state="readonly",
                                         width=18, values=["All classes"])
        self.filter_combo.pack(side="left", padx=8)
        self.filter_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(tools, text="Delete", style="Secondary.TButton",
                   command=self.delete_student).pack(side="right")
        ttk.Button(tools, text="+ Add student", style="Primary.TButton",
                   command=self.new_student).pack(side="right", padx=(0, 8))
        self.tree = make_tree(
            body, ("student", "class", "parent", "email", "phone", "alerts"),
            ("Student", "Class", "Parent", "Email", "Phone", "Alerts"),
            (150, 100, 140, 190, 120, 60), height=8,
            anchors=("w", "center", "w", "w", "center", "center"))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ----- alert history -----
        hcard, hbody = make_card(pad, "Alert History", "Every email / SMS sent to parents")
        hcard.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        self.hist = make_tree(
            hbody, ("time", "student", "class", "type", "channel", "to", "status"),
            ("Time", "Student", "Class", "Type", "Via", "To", "Status"),
            (140, 120, 80, 65, 55, 170, 170), height=5,
            anchors=("w", "w", "center", "center", "center", "w", "w"))

        # ----- right column (scrollable) -----
        sf = ScrollFrame(pad, width=410)
        sf.grid(row=0, column=1, rowspan=2, sticky="nsew")
        right = sf.inner

        form_card, form = make_card(right, "Contact Details")
        form_card.pack(fill="x", pady=(0, 12))
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        def field(r, c, label, var, span=1, **kw):
            ttk.Label(form, text=label, style="Card.TLabel").grid(
                row=r, column=c, columnspan=span, sticky="w",
                padx=((0, 8) if c == 0 and span == 1 else (0, 0)))
            w = (ttk.Combobox if kw.pop("combo", False) else ttk.Entry)(form, textvariable=var, **kw)
            w.grid(row=r + 1, column=c, columnspan=span, sticky="ew",
                   padx=((0, 8) if c == 0 and span == 1 else (0, 0)), pady=(2, 8))
            return w

        self.v_name = tk.StringVar()
        self.v_class = tk.StringVar()
        self.v_roll = tk.StringVar()
        self.v_pname = tk.StringVar()
        self.v_email = tk.StringVar()
        self.v_phone = tk.StringVar()
        self.v_alerts = tk.BooleanVar(value=True)
        self.name_entry = field(0, 0, "Student name", self.v_name, span=2)
        self.class_combo = field(2, 0, "Class", self.v_class, combo=True, values=[])
        field(2, 1, "Roll no.", self.v_roll)
        field(4, 0, "Parent / guardian name", self.v_pname, span=2)
        field(6, 0, "Parent Gmail / email", self.v_email, span=2)
        field(8, 0, "Parent phone number", self.v_phone, span=2)
        ttk.Checkbutton(form, text="Send alerts to this parent", variable=self.v_alerts,
                        style="Card.TCheckbutton").grid(row=10, column=0, columnspan=2,
                                                        sticky="w", pady=(0, 8))
        self.btn_save = ttk.Button(form, text="Save contact", style="Success.TButton",
                                   command=self.save_student)
        self.btn_save.grid(row=11, column=0, columnspan=2, sticky="ew")

        # alert system
        acard, ab = make_card(right, "Alert System",
                              "Automatic email / SMS to parents")
        acard.pack(fill="x", pady=(0, 12))
        s = hub.settings
        self.a_auto = tk.BooleanVar(value=bool(s.get("auto_alerts")))
        self.a_arrival = tk.BooleanVar(value=bool(s.get("alert_arrival")))
        self.a_late = tk.BooleanVar(value=bool(s.get("alert_late")))
        self.a_absent = tk.BooleanVar(value=bool(s.get("alert_absent")))
        self.a_email = tk.BooleanVar(value=bool(s.get("use_email")))
        self.a_sms = tk.BooleanVar(value=bool(s.get("use_sms")))
        self.a_late_t = tk.StringVar(value=str(s.get("late_time")))
        self.a_cut_t = tk.StringVar(value=str(s.get("absent_cutoff")))
        self.a_match = tk.StringVar(value=str(s.get("min_match")))
        self.a_days = [tk.BooleanVar(value=i in s.get("working_days")) for i in range(7)]

        ttk.Checkbutton(ab, text="Enable automatic alerts", variable=self.a_auto,
                        style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(ab, text="OFF by default. Send a test email first.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(ab, text="Send alert when the student is:", style="Card.TLabel").pack(anchor="w")
        r1 = ttk.Frame(ab, style="Inner.TFrame")
        r1.pack(fill="x", pady=(2, 6))
        for txt, var in (("On time", self.a_arrival), ("Late", self.a_late), ("Absent", self.a_absent)):
            ttk.Checkbutton(r1, text=txt, variable=var, style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
        ttk.Label(ab, text="Send through:", style="Card.TLabel").pack(anchor="w")
        r2 = ttk.Frame(ab, style="Inner.TFrame")
        r2.pack(fill="x", pady=(2, 6))
        ttk.Checkbutton(r2, text="Email (Gmail)", variable=self.a_email,
                        style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r2, text="SMS", variable=self.a_sms,
                        style="Card.TCheckbutton").pack(side="left")

        r3 = ttk.Frame(ab, style="Inner.TFrame")
        r3.pack(fill="x", pady=(2, 6))
        for i, (lab, var, w) in enumerate((("Late after (HH:MM)", self.a_late_t, 7),
                                           ("Absent after (HH:MM)", self.a_cut_t, 7),
                                           ("Min match %", self.a_match, 5))):
            col = ttk.Frame(r3, style="Inner.TFrame")
            col.pack(side="left", padx=(0, 10))
            ttk.Label(col, text=lab, style="Muted.TLabel").pack(anchor="w")
            ttk.Entry(col, textvariable=var, width=w).pack(anchor="w")

        ttk.Label(ab, text="Working days (alerts are only sent on these days):",
                  style="Card.TLabel").pack(anchor="w", pady=(4, 0))
        r4 = ttk.Frame(ab, style="Inner.TFrame")
        r4.pack(fill="x", pady=(2, 8))
        for i, name in enumerate(DAY_NAMES):
            ttk.Checkbutton(r4, text=name, variable=self.a_days[i],
                            style="Card.TCheckbutton").pack(side="left", padx=(0, 4))

        ttk.Button(ab, text="Gmail & SMS settings...", style="Secondary.TButton",
                   command=lambda: self._open_settings()).pack(fill="x")
        ttk.Button(ab, text="Save alert settings", style="Primary.TButton",
                   command=self.save_settings).pack(fill="x", pady=(8, 0))
        ttk.Button(ab, text="Send test email", style="Secondary.TButton",
                   command=self.send_test).pack(fill="x", pady=(8, 0))
        ttk.Button(ab, text="Send absent alerts now", style="Violet.TButton",
                   command=hub.send_absent_now).pack(fill="x", pady=(8, 0))

    # -- helpers --
    def _open_settings(self):
        dlg = SettingsDialog(self.winfo_toplevel(), self.hub.settings)
        self.winfo_toplevel().wait_window(dlg)

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel or sel[0] == self.loaded_key:
            return
        rec = self.hub.store.get(sel[0])
        if rec:
            self._load(sel[0], rec)

    def _load(self, key, rec):
        self.loaded_key = key
        self.new_mode = False
        self.v_name.set(rec["name"])
        self.v_class.set("" if rec["klass"] == UNASSIGNED else rec["klass"])
        self.v_roll.set(rec.get("roll", ""))
        self.v_pname.set(rec.get("parent_name", ""))
        self.v_email.set(rec.get("parent_email", ""))
        self.v_phone.set(rec.get("parent_phone", ""))
        self.v_alerts.set(bool(rec.get("alerts", True)))
        self.name_entry.state(["readonly"])

    def new_student(self):
        self.loaded_key = None
        self.new_mode = True
        for v in (self.v_name, self.v_class, self.v_roll, self.v_pname, self.v_email, self.v_phone):
            v.set("")
        self.v_alerts.set(True)
        self.name_entry.state(["!readonly"])
        self.tree.selection_remove(self.tree.selection())
        self.name_entry.focus_set()

    def save_student(self):
        name = self.v_name.get().strip()
        email = self.v_email.get().strip()
        phone = self.v_phone.get().strip()
        if not name:
            messagebox.showwarning("Student", "Please enter the student's name.")
            return
        if email and not EMAIL_RE.match(email):
            messagebox.showwarning("Email", "That email address does not look valid.")
            return
        if phone and not normalize_phone(phone, self.hub.settings.get("default_country_code")):
            messagebox.showwarning("Phone", "Enter a valid phone number (10 digits, or with country code).")
            return
        if self.new_mode and self.hub.store.get(self.hub.store.key(name)):
            messagebox.showwarning("Student", "A student with this name already exists.")
            return
        key = self.hub.store.upsert(
            name, klass=self.v_class.get().strip(), roll=self.v_roll.get().strip(),
            parent_name=self.v_pname.get().strip(), parent_email=email,
            parent_phone=phone, alerts=bool(self.v_alerts.get()))
        self.loaded_key = key
        self.new_mode = False
        self.name_entry.state(["readonly"])
        self.hub.refresh_visible(force=True)
        if self.tree.exists(key):
            self.tree.selection_set(key)
        self.hub.app.set_status(f"Saved contact details for {name}")
        if self.new_mode is False and not self.hub.has_face(name):
            self.hub.app.set_status(
                f"Saved {name}. Register their face in the Control Room so they can be recognised.")

    def delete_student(self):
        key = self.loaded_key
        rec = self.hub.store.get(key) if key else None
        if not rec:
            messagebox.showinfo("Delete", "Select a student first.")
            return
        if not messagebox.askyesno(
                "Delete student",
                f"Remove '{rec['name']}' from the student list AND delete their registered face data?\n\n"
                "This cannot be undone."):
            return
        self.hub.delete_student(key, rec["name"])
        self.new_student()
        self.loaded_key = None

    def save_settings(self):
        pat = re.compile(r"^\d{1,2}:\d{2}$")
        if not pat.match(self.a_late_t.get().strip()) or not pat.match(self.a_cut_t.get().strip()):
            messagebox.showwarning("Time", "Enter times as HH:MM, for example 09:15")
            return
        try:
            mm = float(self.a_match.get().strip())
            if not 0 <= mm <= 100:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Match %", "Minimum match % must be a number between 0 and 100.")
            return
        days = [i for i, v in enumerate(self.a_days) if v.get()]
        self.hub.settings.update(
            auto_alerts=bool(self.a_auto.get()), alert_arrival=bool(self.a_arrival.get()),
            alert_late=bool(self.a_late.get()), alert_absent=bool(self.a_absent.get()),
            use_email=bool(self.a_email.get()), use_sms=bool(self.a_sms.get()),
            late_time=self.a_late_t.get().strip(), absent_cutoff=self.a_cut_t.get().strip(),
            min_match=mm, working_days=days)
        self.hub.refresh_visible(force=True)
        if self.a_auto.get() and not self.hub.settings.get("gmail_user"):
            messagebox.showinfo("Saved", "Settings saved.\n\nAutomatic alerts are ON but Gmail is not "
                                         "configured yet - open 'Gmail & SMS settings...'.")
        else:
            messagebox.showinfo("Saved", "Alert settings saved.")

    def send_test(self):
        to = simpledialog.askstring("Test email", "Send a test email to which address?",
                                    initialvalue=self.v_email.get().strip() or
                                    self.hub.settings.get("gmail_user"),
                                    parent=self.winfo_toplevel())
        if not to:
            return
        to = to.strip()
        if not EMAIL_RE.match(to):
            messagebox.showwarning("Email", "That email address does not look valid.")
            return
        if not self.hub.settings.get("gmail_user"):
            messagebox.showwarning("Gmail", "Set your Gmail address and app password first "
                                            "('Gmail & SMS settings...').")
            return
        subj, body, _ = compose("test", {"name": "-", "klass": "-"}, None, date.today(),
                                self.hub.settings.get("school_name"))
        self.hub.alerts.enqueue({"channel": "email", "to": to, "subject": subj, "body": body,
                                 "student": "(test)", "klass": "-", "kind": "test"})
        self.hub.app.set_status(f"Test email queued for {to} - see Alert History")

    # -- refresh --
    def refresh(self):
        hub = self.hub
        classes = ["All classes"] + hub.class_list()
        if any(norm_class(s["klass"]) == norm(UNASSIGNED) for s in hub.store.all()):
            classes.append(UNASSIGNED)
        if list(self.filter_combo.cget("values")) != classes:
            self.filter_combo.configure(values=classes)
        self.class_combo.configure(values=hub.class_list())

        want = self.filter_var.get()
        q = norm(self.search_var.get())
        rows = []
        for st in hub.store.all():
            if want != "All classes" and norm_class(st["klass"]) != norm_class(want):
                continue
            if q and q not in norm(st["name"]) and q not in norm(st.get("parent_name", "")):
                continue
            missing = not (st.get("parent_email") or st.get("parent_phone"))
            rows.append((hub.store.key(st["name"]),
                         (st["name"], st["klass"], st.get("parent_name") or "-",
                          st.get("parent_email") or "-", st.get("parent_phone") or "-",
                          "On" if st.get("alerts", True) else "Off"),
                         ("warn",) if missing else ()))
        fill_tree(self.tree, rows, self.sigs, "students")

        hist = []
        for i, row in enumerate(reversed(hub.read_alert_log()[-100:])):
            row = (row + [""] * 7)[:7]
            hist.append((f"h{i}", tuple(row), ("ok",) if row[6] == "Sent" else ("bad",)))
        fill_tree(self.hist, hist, self.sigs, "hist")


# --------------------------------------------------------------------------
# Dashboard 3: Staff (overview, absentees, reports)
# --------------------------------------------------------------------------
class StaffTab(tk.Frame):
    def __init__(self, parent, hub):
        super().__init__(parent, bg=C["bg"])
        self.hub = hub
        self.sigs = {}
        self.day = date.today()
        self.groups = []

        pad = tk.Frame(self, bg=C["bg"])
        pad.pack(fill="both", expand=True, padx=20, pady=(10, 8))
        pad.columnconfigure(0, weight=3, uniform="s")
        pad.columnconfigure(1, weight=2, uniform="s")
        pad.rowconfigure(2, weight=1)

        tb = tk.Frame(pad, bg=C["bg"])
        tb.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        tk.Label(tb, text="Staff Overview", font=FONT_T,
                 bg=C["bg"], fg=C["text"]).pack(side="left")
        ttk.Button(tb, text="Open exports folder", style="Secondary.TButton",
                   command=lambda: hub.open_folder(EXPORT_DIR)).pack(side="right")
        ttk.Button(tb, text="Export CSV", style="Primary.TButton",
                   command=self.export_csv).pack(side="right", padx=8)
        self.class_var = tk.StringVar(value="All classes")
        self.class_combo = ttk.Combobox(tb, textvariable=self.class_var, state="readonly",
                                        width=16, values=["All classes"])
        self.class_combo.pack(side="right")
        self.class_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Label(tb, text="Class:").pack(side="right", padx=(14, 4))
        ttk.Button(tb, text="Today", style="Secondary.TButton",
                   command=self.go_today).pack(side="right", padx=(6, 0))
        ttk.Button(tb, text="Load", style="Secondary.TButton",
                   command=self.load_day).pack(side="right", padx=(6, 0))
        self.date_var = tk.StringVar(value=str(self.day))
        de = ttk.Entry(tb, textvariable=self.date_var, width=12)
        de.pack(side="right")
        de.bind("<Return>", lambda e: self.load_day())
        ttk.Label(tb, text="Date:").pack(side="right", padx=(14, 4))

        kp = tk.Frame(pad, bg=C["bg"])
        kp.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.kpis = {}
        for i, (key, title, color) in enumerate((
                ("total", "Total Students", C["primary"]), ("present", "Present", C["success"]),
                ("late", "Late Arrival", C["amber"]), ("absent", "Absent", C["danger"]),
                ("pct", "Attendance Rate", C["violet"]), ("cams", "Cameras Online", C["success"]),
                ("alerts", "Alerts Sent", C["amber"]))):
            kp.columnconfigure(i, weight=1, uniform="sk")
            k = Kpi(kp, title, color)
            k.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.kpis[key] = k

        c1, b1 = make_card(pad, "Class-wise Attendance")
        c1.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        legend = ttk.Frame(b1, style="Inner.TFrame")
        legend.pack(fill="x", pady=(0, 6))
        for txt, color in (("Present", C["success"]), ("Late", C["amber"]),
                           ("Absent", C["danger"]), ("Not arrived", "#cbd5e1")):
            tk.Label(legend, text="   ", bg=color, font=("Segoe UI", 4)).pack(side="left", padx=(0, 4))
            ttk.Label(legend, text=txt + "     ", style="Muted.TLabel").pack(side="left")
        wrap = ttk.Frame(b1, style="Inner.TFrame")
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg="white", highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._redraw_job = None
        self.canvas.bind("<Configure>", lambda e: self._schedule_redraw())

        c2, b2 = make_card(pad, "Needs Attention", "Late and absent students")
        c2.grid(row=2, column=1, sticky="nsew")
        self.tree = make_tree(b2, ("name", "class", "status", "arrived", "alerted"),
                              ("Student", "Class", "Status", "Arrived", "Alerted"),
                              (150, 90, 80, 80, 100), height=7,
                              anchors=("w", "center", "center", "center", "center"))
        sec_box = ttk.Frame(b2, style="Inner.TFrame")
        sec_box.pack(fill="x", pady=(10, 0))
        self.sec_lbl = ttk.Label(sec_box, text="", style="Muted.TLabel")
        self.sec_lbl.pack(side="left")
        ttk.Button(sec_box, text="Staff Alert Settings...", style="Secondary.TButton",
                   command=self._open_staff_settings).pack(side="right")
        ttk.Button(sec_box, text="Test Staff Alert", style="Violet.TButton",
                   command=hub.send_test_staff_alert).pack(side="right", padx=(0, 6))

    def _open_staff_settings(self):
        dlg = SettingsDialog(self.winfo_toplevel(), self.hub.settings)
        self.winfo_toplevel().wait_window(dlg)
        self.refresh()

    def go_today(self):
        self.day = date.today()
        self.date_var.set(str(self.day))
        self.sigs.clear()
        self.refresh()

    def load_day(self):
        try:
            self.day = datetime.strptime(self.date_var.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            messagebox.showwarning("Date", "Enter the date as YYYY-MM-DD, for example 2026-10-29")
            return
        self.sigs.clear()
        self.refresh()

    def _report(self):
        if self.day == date.today() and self.hub.report is not None:
            return self.hub.report
        return self.hub.build_report(self.day)

    def refresh(self):
        hub = self.hub
        report = self._report()
        classes = ["All classes"] + hub.class_list()
        if any(norm_class(r["klass"]) == norm(UNASSIGNED) for r in report):
            classes.append(UNASSIGNED)
        if list(self.class_combo.cget("values")) != classes:
            self.class_combo.configure(values=classes)

        present = sum(r["status"] == "Present" for r in report)
        late = sum(r["status"] == "Late" for r in report)
        absent = sum(r["status"] == "Absent" for r in report)
        total = len(report)
        self.kpis["total"].set(total)
        self.kpis["present"].set(present)
        self.kpis["late"].set(late)
        self.kpis["absent"].set(absent)
        self.kpis["pct"].set(f"{round((present + late) * 100 / total)}%" if total else "-")
        cams = hub.app.cameras
        self.kpis["cams"].set(f"{sum(hub.camera_status(c) in ONLINE for c in cams)}/{len(cams)}")
        today = str(date.today())
        self.kpis["alerts"].set(sum(1 for r in hub.read_alert_log()
                                    if r and r[0].startswith(today) and len(r) > 6 and r[6] == "Sent"))

        # chart data
        groups = []
        for g in hub.class_groups(report):
            rr = g["rows"]
            groups.append((g["name"],
                           sum(r["status"] == "Present" for r in rr),
                           sum(r["status"] == "Late" for r in rr),
                           sum(r["status"] == "Absent" for r in rr),
                           sum(r["status"] in ("Not arrived", "No class") for r in rr),
                           len(rr)))
        if groups != self.groups:
            self.groups = groups
            self._schedule_redraw()

        # attention table
        want = self.class_var.get()
        rows = []
        for r in report:
            if r["status"] not in ("Late", "Absent"):
                continue
            if want != "All classes" and norm_class(r["klass"]) != norm_class(want):
                continue
            if self.day == date.today():
                alerted = "Yes" if r["status"].lower() in hub.state.kinds_for(self.day, r["key"]) else "No"
            else:
                alerted = "-"
            rows.append((r["key"], (r["student"]["name"], r["klass"], r["status"],
                                    fmt_time(r["first"]), alerted),
                         (STATUS_TAG[r["status"]],)))
        fill_tree(self.tree, rows, self.sigs, "attention")

        staff_em = hub.settings.get("staff_email", "")
        staff_ph = hub.settings.get("staff_phone", "")
        has_cam = any("principal" in (c.get("room") or "").lower() or "principal" in c.get("name", "").lower() for c in hub.app.cameras)
        if not hub.settings.get("alert_principal", True):
            st_text = "🛡️ Principal Office Alert: Disabled"
        elif not (staff_em or staff_ph):
            st_text = "⚠️ Principal Office Alert: Staff Gmail/Phone needed"
        elif not has_cam:
            st_text = "ℹ️ Principal Office: Set a camera room to 'Principal\\'s Office'"
        else:
            st_text = f"🛡️ Office Alert Active ({staff_em or staff_ph})"
        self.sec_lbl.config(text=st_text)

    def _schedule_redraw(self):
        if self._redraw_job is None:
            self._redraw_job = self.after(60, self._draw)

    def _draw(self):
        self._redraw_job = None
        cv = self.canvas
        cv.delete("all")
        w = max(cv.winfo_width(), 420)
        row_h, left, right = 36, 130, 120
        y = 10
        if not self.groups:
            cv.create_text(w // 2, 40, text="No classes yet", fill=C["muted"], font=FONT)
        for name, p, l, a, n, t in self.groups:
            cv.create_text(10, y + row_h / 2 - 2, text=name, anchor="w", font=FONT, fill=C["text"])
            bw = max(w - left - right, 50)
            x = left
            # Subtle background progress track
            cv.create_rectangle(left, y + 8, left + bw, y + row_h - 10, fill="#f1f5f9", outline="")
            if t:
                for val, color in ((p, C["success"]), (l, C["amber"]), (a, C["danger"]), (n, "#cbd5e1")):
                    seg = bw * val / t
                    if seg > 0:
                        cv.create_rectangle(x, y + 8, x + seg, y + row_h - 10, fill=color, outline="")
                        x += seg
            pct = f"{round((p + l) * 100 / t)}%  ({p + l}/{t})" if t else "-"
            cv.create_text(w - 10, y + row_h / 2 - 2, text=pct, anchor="e", font=FONT_B, fill=C["primary"])
            y += row_h
        cv.configure(scrollregion=(0, 0, w, y + 10))

    def export_csv(self):
        report = self._report()
        want = self.class_var.get()
        rows = [r for r in report
                if want == "All classes" or norm_class(r["klass"]) == norm_class(want)]
        if not rows:
            messagebox.showinfo("Export", "There are no students to export.")
            return
        suffix = "" if want == "All classes" else "_" + re.sub(r"[^\w]+", "-", want)
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), title="Save attendance report",
            initialdir=EXPORT_DIR, initialfile=f"attendance_{self.day}{suffix}.csv",
            defaultextension=".csv", filetypes=[("CSV file", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Date", "Class", "Roll no", "Student", "Status", "First seen",
                            "Last seen", "Last emotion", "Camera"])
                for r in rows:
                    w.writerow([self.day, r["klass"], r["student"].get("roll", ""),
                                r["student"]["name"], r["status"], fmt_time(r["first"]),
                                fmt_time(r["last"]), r["emotion"], r["camera"]])
            self.hub.app.set_status(f"Report saved: {path}")
            messagebox.showinfo("Export", f"Saved {len(rows)} rows to:\n{path}")
        except OSError as e:
            messagebox.showerror("Export", str(e))


# --------------------------------------------------------------------------
# Hub: owns data + engine, creates the tabs
# --------------------------------------------------------------------------
class SchoolHub:
    def __init__(self, app, notebook, control_tab):
        self.app = app
        self.notebook = notebook
        self.control_tab = control_tab
        self.settings = Settings()
        self.store = StudentStore()
        self.attendance = AttendanceReader()
        self.state = AlertState()
        self.alerts = AlertService(self)
        self.probe = {}
        self.report = None
        self.unlocked = False
        self.stop_flag = False
        self.n = 0
        self._last_classes = None
        self._alert_log_cache = (None, [])
        self._last_sec_alerts = {}
        self.store.sync_from_faces()

        self.students_tab = StudentsTab(notebook, self)
        self.parents_tab = ParentsTab(notebook, self)
        self.staff_tab = StaffTab(notebook, self)
        notebook.add(self.students_tab, text="  Students  ")
        notebook.add(self.parents_tab, text="  Parents & Alerts  ")
        notebook.add(self.staff_tab, text="  College Staff  ")
        self.protected = {str(control_tab), str(self.parents_tab), str(self.staff_tab)}

    # -- lifecycle --
    def start(self):
        if self.has_pin():
            self.notebook.select(self.students_tab)
        threading.Thread(target=self._probe_loop, daemon=True).start()
        self.refresh_visible(force=True)
        self.app.root.after(2000, self.tick)

    def shutdown(self):
        self.stop_flag = True
        self.alerts.stop()

    def tick(self):
        self.app.root.after(2000, self.tick)
        self.n += 1
        self.refresh_visible()
        self.check_security_alerts()
        if self.n % 10 == 0 and self.settings.get("auto_alerts"):
            try:
                self.run_alert_rules()
            except Exception:
                traceback.print_exc()

    def refresh_visible(self, force=False):
        try:
            if force:
                for t in (self.students_tab, self.parents_tab, self.staff_tab):
                    t.sigs.clear()
            self.report = self.build_report(date.today())
            classes = self.class_list()
            if classes != self._last_classes:
                self._last_classes = classes
                self.app.class_combo.configure(values=classes)
            tab = self.notebook.select()
            if tab == str(self.students_tab):
                self.students_tab.refresh(self.report)
            elif tab == str(self.parents_tab):
                self.parents_tab.refresh()
            elif tab == str(self.staff_tab):
                self.staff_tab.refresh()
        except Exception:
            traceback.print_exc()

    def on_alert_result(self):
        self.parents_tab.sigs.pop("hist", None)
        self.staff_tab.sigs.clear()
        self.refresh_visible()

    # -- PIN lock --
    def has_pin(self):
        return bool(self.settings.get("pin_hash"))

    @staticmethod
    def _hash(pin, salt):
        return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120000).hex()

    def verify_pin(self, pin):
        return self._hash(pin, self.settings.get("pin_salt")) == self.settings.get("pin_hash")

    def ask_pin(self):
        pin = simpledialog.askstring("Locked", "Enter PIN to open this dashboard:",
                                     show="*", parent=self.app.root)
        if pin is None:
            return False
        if self.verify_pin(pin):
            self.unlocked = True
            return True
        messagebox.showerror("Locked", "Wrong PIN.")
        return False

    def change_pin(self):
        root = self.app.root
        if self.has_pin() and not self.unlocked and not self.ask_pin():
            return
        new = simpledialog.askstring(
            "Set PIN", "New PIN (min 4 characters).\nLeave empty to remove the PIN:",
            show="*", parent=root)
        if new is None:
            return
        if new == "":
            self.settings.update(pin_hash="", pin_salt="")
            messagebox.showinfo("PIN", "PIN removed. All dashboards are open.")
            return
        if len(new) < 4:
            messagebox.showwarning("PIN", "PIN must be at least 4 characters.")
            return
        again = simpledialog.askstring("Set PIN", "Type the PIN again:", show="*", parent=root)
        if again != new:
            messagebox.showwarning("PIN", "The PINs did not match.")
            return
        salt = os.urandom(16).hex()
        self.settings.update(pin_salt=salt, pin_hash=self._hash(new, salt))
        self.unlocked = True
        messagebox.showinfo("PIN", "PIN saved. Control Room, Parents & Alerts and College Staff "
                                   "now ask for it when the app starts.")

    def on_tab_changed(self, _event=None):
        tab = self.notebook.select()
        if tab in self.protected and self.has_pin() and not self.unlocked:
            if not self.ask_pin():
                self.notebook.select(self.students_tab)
                return
        self.refresh_visible(force=True)

    # -- data --
    @staticmethod
    def open_folder(path):
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def has_face(self, name):
        try:
            for f in os.listdir(FACES_DIR):
                if f.endswith(".npy") and norm(" ".join(f[:-4].split("_")[:-1])) == norm(name):
                    return True
        except OSError:
            pass
        return False

    def delete_student(self, key, name):
        removed = 0
        try:
            for f in os.listdir(FACES_DIR):
                if f.endswith(".npy"):
                    parts = f[:-4].split("_")
                    fname = " ".join(parts[:-1]) if len(parts) >= 2 else parts[0]
                    if norm(fname) == norm(name):
                        os.remove(os.path.join(FACES_DIR, f))
                        removed += 1
        except OSError:
            pass
        self.store.delete(key)
        if removed:
            self.app.rebuild_known_database()
            # if that was the last face, clear the combined database too
            if not any(f.endswith(".npy") for f in os.listdir(FACES_DIR)):
                for n in ("known_face_encodings.npy", "known_face_names.npy", "known_face_ages.npy"):
                    try:
                        os.remove(os.path.join(BASE_DIR, n))
                    except OSError:
                        pass
        self.refresh_visible(force=True)
        self.app.set_status(f"Deleted {name}")

    def build_report(self, day):
        recs = self.attendance.records(day, self.settings.get("min_match"))
        now = datetime.now()
        late_t = hhmm(self.settings.get("late_time"), dtime(9, 15))
        cut_t = hhmm(self.settings.get("absent_cutoff"), dtime(10, 0))
        working = day.weekday() in self.settings.get("working_days")
        rows = []
        for st in self.store.all():
            key = StudentStore.key(st["name"])
            rec = recs.get(key)
            rows.append({
                "student": st, "key": key, "klass": st["klass"] or UNASSIGNED, "rec": rec,
                "status": compute_status(rec, day, now, late_t, cut_t, working),
                "first": rec["first"] if rec else None, "last": rec["last"] if rec else None,
                "emotion": rec["emotion"] if rec else "", "camera": rec["camera"] if rec else "",
            })
        return rows

    def class_list(self):
        names = {}
        for st in self.store.all():
            if norm_class(st["klass"]) != norm(UNASSIGNED):
                names.setdefault(norm(st["klass"]), st["klass"])
        for c in self.app.cameras:
            room = (c.get("room") or "").strip()
            if room:
                names.setdefault(norm(room), room)
        return sorted(names.values(), key=str.lower)

    def class_groups(self, report):
        names = {}
        for r in report:
            names.setdefault(norm_class(r["klass"]), r["klass"] or UNASSIGNED)
        for c in self.app.cameras:
            room = (c.get("room") or "").strip() or UNASSIGNED
            names.setdefault(norm_class(room), room)
        groups = {n: {"name": d, "norm": n, "rows": [], "cams": []} for n, d in names.items()}
        for r in report:
            groups[norm_class(r["klass"])]["rows"].append(r)
        for c in self.app.cameras:
            groups[norm_class(c.get("room"))]["cams"].append(c)
        return sorted(groups.values(),
                      key=lambda g: (g["norm"] == norm(UNASSIGNED), g["name"].lower()))

    # -- camera / stream status --
    def camera_status(self, cam):
        app, cid = self.app, cam["id"]
        if app.rec_running(cid):
            return "Recognizing"
        s = app.streams.get(cid)
        if s is not None:
            return {"live": "Live", "connecting": "Connecting",
                    "reconnecting": "Reconnecting", "failed": "Offline"}.get(s.state, "Idle")
        if cid in app.errors:
            return "Offline"
        p = self.probe.get(cid)
        if p is True:
            return "Online"
        if p is False:
            return "Offline"
        return "Idle" if cam["kind"] == "Webcam" else "Checking"

    def stream_summary(self, cams):
        if not cams:
            return "No camera", "idle", 0
        sts = [self.camera_status(c) for c in cams]
        on = sum(1 for s in sts if s in ONLINE)
        if on == len(cams):
            return "Online", "ok", on
        if on:
            return f"{on}/{len(cams)} online", "warn", on
        if any(s == "Offline" for s in sts):
            return "Offline", "bad", 0
        return "Idle", "idle", 0

    def _probe_loop(self):
        """Cheap reachability check (no video decoding) so offline cameras are spotted."""
        ports = {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443, "rtmp": 1935}
        while not self.stop_flag:
            for cam in list(self.app.cameras):
                res = None
                try:
                    if cam["kind"] == "CCTV / IP Camera":
                        u = urllib.parse.urlparse(str(cam["source"]))
                        if u.hostname and u.scheme in ports:
                            with socket.create_connection((u.hostname, u.port or ports[u.scheme]),
                                                          timeout=2):
                                res = True
                    elif cam["kind"] == "Video File":
                        res = os.path.isfile(str(cam["source"]))
                except OSError:
                    res = False
                except Exception:
                    res = None
                self.probe[cam["id"]] = res
            for _ in range(15):
                if self.stop_flag:
                    return
                time.sleep(1)

    # -- alerts --
    def read_alert_log(self):
        try:
            mt = os.path.getmtime(ALERT_LOG)
        except OSError:
            return []
        if self._alert_log_cache[0] == mt:
            return self._alert_log_cache[1]
        try:
            with open(ALERT_LOG, "r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))[1:]
        except OSError:
            rows = []
        self._alert_log_cache = (mt, rows)
        return rows

    def queue_alerts(self, st, rec, kind, day):
        s = self.settings
        subj, body, sms = compose(kind, st, rec, day, s.get("school_name"))
        n = 0
        base = {"student": st["name"], "klass": st["klass"], "kind": kind}
        email = st.get("parent_email", "").strip()
        phone = normalize_phone(st.get("parent_phone", ""), s.get("default_country_code"))
        if s.get("use_email") and EMAIL_RE.match(email):
            self.alerts.enqueue(dict(base, channel="email", to=email, subject=subj, body=body))
            n += 1
        if s.get("use_sms") and phone:
            self.alerts.enqueue(dict(base, channel="sms", to=phone, subject="", body=sms))
            n += 1
        return n

    def pending_alerts(self, only_kind=None):
        """Alerts that the rules say should go out now (and were not sent yet)."""
        now = datetime.now()
        day = now.date()
        if day.weekday() not in self.settings.get("working_days"):
            return []
        report = self.build_report(day)
        with_detections = {norm_class(r["klass"]) for r in report if r["rec"]}
        out = []
        for r in report:
            st = r["student"]
            if not st.get("alerts", True):
                continue
            if not (st.get("parent_email") or st.get("parent_phone")):
                continue
            kind = {"Present": "arrival", "Late": "late", "Absent": "absent"}.get(r["status"])
            if not kind or (only_kind and kind != only_kind):
                continue
            if not only_kind and not self.settings.get("alert_" + kind):
                continue
            # safety: never send "absent" for a class where nobody was seen (camera may be down)
            if kind == "absent" and norm_class(r["klass"]) not in with_detections:
                continue
            key = f"{day}|{r['key']}|{kind}"
            if self.state.was_sent(key):
                continue
            out.append((key, st, r["rec"], kind, day))
        return out

    def run_alert_rules(self):
        cfg_ok = (self.settings.get("use_email") and self.settings.get("gmail_user")) or \
                 (self.settings.get("use_sms") and self.settings.get("twilio_sid"))
        if not cfg_ok:
            return 0
        total = 0
        for key, st, rec, kind, day in self.pending_alerts():
            self.state.mark(key)
            total += self.queue_alerts(st, rec, kind, day)
        if total:
            self.app.set_status(f"{total} parent alert(s) queued")
        return total

    def send_absent_now(self):
        if not (self.settings.get("gmail_user") or self.settings.get("twilio_sid")):
            messagebox.showwarning("Alerts", "Set up Gmail (or SMS) first in "
                                             "'Gmail & SMS settings...'.")
            return
        pending = self.pending_alerts(only_kind="absent")
        if not pending:
            messagebox.showinfo("Absent alerts",
                                "Nothing to send.\n\nEither nobody is absent, the alerts were already "
                                "sent today, parents have no contact details, or it is not a working day.\n"
                                "(Classes where nobody was detected today are skipped, in case the "
                                "camera was off.)")
            return
        names = ", ".join(p[1]["name"] for p in pending[:8])
        more = f" and {len(pending) - 8} more" if len(pending) > 8 else ""
        if not messagebox.askyesno("Send absent alerts",
                                   f"Send an absent alert to the parents of {len(pending)} student(s)?\n\n"
                                   f"{names}{more}"):
            return
        total = 0
        for key, st, rec, kind, day in pending:
            self.state.mark(key)
            total += self.queue_alerts(st, rec, kind, day)
        self.app.set_status(f"{total} absent alert(s) queued - see Alert History")

    # -- staff security alerts (principal's office) --
    def check_security_alerts(self):
        """Scans recent detections on Principal's Office cameras and alerts staff if unauthorized."""
        if not self.settings.get("alert_principal", True):
            return
        staff_email = str(self.settings.get("staff_email", "")).strip()
        staff_phone = normalize_phone(self.settings.get("staff_phone", ""), self.settings.get("default_country_code"))
        if not (staff_email or staff_phone):
            return

        principal_cams = set()
        for c in self.app.cameras:
            room = (c.get("room") or "").lower()
            name = (c.get("name") or "").lower()
            if "principal" in room or "principal" in name:
                principal_cams.add(norm(c.get("name")))
                if c.get("room"):
                    principal_cams.add(norm(c.get("room")))

        if not principal_cams:
            return

        now = datetime.now()
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace", newline="") as f:
                rows = list(csv.reader(f))
        except OSError:
            return

        if len(rows) <= 1:
            return

        raw_auth = str(self.settings.get("authorized_principal", "Principal")).split(",")
        auth_set = {norm(a) for a in raw_auth if norm(a)}

        for row in reversed(rows[-25:]):
            if len(row) < 5:
                continue
            name = row[0].strip()
            if norm(name) in ("name", "student", "person", ""):
                continue
            ts = parse_ts(row[4])
            if ts is None:
                continue
            if (now - ts).total_seconds() > 15:
                break

            camera = row[5].strip() if len(row) > 5 else ""
            if not (norm(camera) in principal_cams or any(pc in norm(camera) for pc in principal_cams)):
                continue

            if norm(name) in auth_set:
                continue

            cooldown_key = f"{norm(name)}_{norm(camera)}"
            last_time = self._last_sec_alerts.get(cooldown_key, 0)
            if time.time() - last_time < 60:
                continue

            self._last_sec_alerts[cooldown_key] = time.time()

            subj, body, sms = compose("security", {"name": name, "klass": "Principal's Office"},
                                      {"first": ts, "camera": camera, "emotion": row[3] if len(row) > 3 else ""},
                                      ts.date(), self.settings.get("school_name"))
            base = {"student": f"🚨 {name}", "klass": "Principal Office", "kind": "Security"}
            if staff_email and EMAIL_RE.match(staff_email) and self.settings.get("gmail_user"):
                self.alerts.enqueue(dict(base, channel="email", to=staff_email, subject=subj, body=body))
            if staff_phone and self.settings.get("twilio_sid"):
                self.alerts.enqueue(dict(base, channel="sms", to=staff_phone, subject="", body=sms))

            self.app.set_status(f"🚨 SECURITY ALERT: Unauthorized entry in Principal's Office by '{name}'! Alert queued for staff.")

    def send_test_staff_alert(self):
        staff_email = str(self.settings.get("staff_email", "")).strip()
        staff_phone = normalize_phone(self.settings.get("staff_phone", ""), self.settings.get("default_country_code"))
        if not (staff_email or staff_phone):
            messagebox.showwarning("Staff Alert",
                                   "Please set the Staff Gmail address or Phone number first in Settings.",
                                   parent=self.app.root)
            return
        now = datetime.now()
        subj, body, sms = compose("security", {"name": "Test Simulation", "klass": "Principal's Office"},
                                  {"first": now, "camera": "Principal Office Cam", "emotion": "Surprise"},
                                  now.date(), self.settings.get("school_name"))
        base = {"student": "🚨 Test Simulation", "klass": "Principal Office", "kind": "Test Security"}
        queued = 0
        if staff_email and EMAIL_RE.match(staff_email):
            if not self.settings.get("gmail_user"):
                messagebox.showwarning("Gmail", "Configure your Gmail address and App Password in Settings to send emails.", parent=self.app.root)
            else:
                self.alerts.enqueue(dict(base, channel="email", to=staff_email, subject=subj, body=body))
                queued += 1
        if staff_phone:
            if not self.settings.get("twilio_sid"):
                messagebox.showwarning("SMS", "Configure your Twilio SMS settings to send SMS alerts.", parent=self.app.root)
            else:
                self.alerts.enqueue(dict(base, channel="sms", to=staff_phone, subject="", body=sms))
                queued += 1
        if queued:
            messagebox.showinfo("Staff Alert",
                                f"Test security alert queued for staff!\n\nEmail: {staff_email or 'None'}\nPhone: {staff_phone or 'None'}",
                                parent=self.app.root)
            self.app.set_status("Test security alert queued for staff - see Alert History")


