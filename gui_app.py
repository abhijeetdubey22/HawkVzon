import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk
import subprocess
import threading
import cv2
import os
import sys
import csv
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(BASE_DIR, "face_emotion_combined.py")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "recognized_faces.csv")
FACES_DIR = os.path.join(BASE_DIR, "faces")
os.makedirs(FACES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Globals
camera_on = False
cap = None
current_frame = None

def stop_camera():
    global camera_on, cap
    camera_on = False
    if cap is not None:
        try:
            cap.release()
        except Exception:
            pass
        cap = None
    cam_label.config(image="")

def start_camera():
    global camera_on, cap
    if camera_on:
        return
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        messagebox.showerror("Camera Error", "Failed to open camera (Device 0).")
        return
    camera_on = True
    update_camera_frame()

def update_camera_frame():
    global current_frame
    if not camera_on or cap is None:
        return

    ret, frame = cap.read()
    if not ret or frame is None:
        root.after(50, update_camera_frame)
        return

    current_frame = frame.copy()
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb_frame)
    img = img.resize((360, 270))
    imgtk = ImageTk.PhotoImage(image=img)
    cam_label.imgtk = imgtk
    cam_label.config(image=imgtk)
    root.after(30, update_camera_frame)

def start_recognition():
    if not os.path.exists(SCRIPT_PATH):
        messagebox.showerror("Error", f"Script '{SCRIPT_PATH}' not found.")
        return

    # Release GUI camera first to prevent device conflict
    stop_camera()

    def run():
        try:
            python_bin = sys.executable if sys.executable else "python"
            subprocess.run([python_bin, SCRIPT_PATH], check=True)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Execution Error", str(e))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    threading.Thread(target=run, daemon=True).start()

def register_face():
    name = entry_name.get().strip()
    age = entry_age.get().strip()

    if not name:
        messagebox.showwarning("Input Required", "Please enter a Name.")
        return
    if not age:
        age = "Unknown"

    # Make sure camera is running to capture
    if not camera_on or current_frame is None:
        start_camera()
        messagebox.showinfo("Camera Started", "Please look directly at the camera, then click 'Register Face' again.")
        return

    try:
        import face_recognition
        rgb = cv2.cvtColor(current_frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb)
        if not locations:
            messagebox.showwarning("No Face Detected", "No face was detected in the frame. Please align your face and try again.")
            return

        encodings = face_recognition.face_encodings(rgb, locations)
        if not encodings:
            messagebox.showwarning("Encoding Error", "Failed to compute face embedding. Try again.")
            return

        # Save individual face encoding
        filename = f"{name}_{age}.npy"
        np.save(os.path.join(FACES_DIR, filename), encodings[0])

        # Automatically rebuild unified database
        rebuild_known_database()

        messagebox.showinfo("Success", f"Successfully registered face for '{name}' (Age: {age})!\nDatabase updated.")
        entry_name.delete(0, tk.END)
        entry_age.delete(0, tk.END)

    except ImportError:
        messagebox.showerror("Library Missing", "face_recognition library is required for registration.")
    except Exception as e:
        messagebox.showerror("Registration Error", f"An error occurred: {e}")

def rebuild_known_database():
    """Rebuilds known_face_encodings.npy, known_face_names.npy, and known_face_ages.npy from faces/"""
    encoding_list = []
    name_list = []
    age_list = []

    for file in os.listdir(FACES_DIR):
        if file.endswith(".npy"):
            try:
                data = np.load(os.path.join(FACES_DIR, file), allow_pickle=True)
                encoding_list.append(data)
                parts = file[:-4].split("_")
                if len(parts) >= 2:
                    face_name = " ".join(parts[:-1])
                    face_age = parts[-1]
                else:
                    face_name = parts[0]
                    face_age = "-"
                name_list.append(face_name)
                age_list.append(face_age)
            except Exception:
                pass

    if encoding_list:
        np.save(os.path.join(BASE_DIR, "known_face_encodings.npy"), encoding_list)
        np.save(os.path.join(BASE_DIR, "known_face_names.npy"), name_list)
        np.save(os.path.join(BASE_DIR, "known_face_ages.npy"), age_list)

def open_logs():
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    os.startfile(LOGS_DIR)

def refresh_attendance():
    for item in tree.get_children():
        tree.delete(item)
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as file:
                reader = csv.reader(file)
                rows = list(reader)[1:]
                for row in rows[-8:]:
                    tree.insert("", "end", values=row)
        except Exception:
            pass
    # Auto-schedule refresh every 4 seconds
    root.after(4000, refresh_attendance)

# GUI Setup
root = tk.Tk()
root.title("Face & Emotion Recognition Dashboard")
root.geometry("820x680")
root.configure(bg="#f3f4f6")

# Header
header = tk.Label(root, text="👤 Face & Emotion Recognition Dashboard", font=("Segoe UI", 16, "bold"), bg="#f3f4f6", fg="#1f2937")
header.pack(pady=12)

# Main Container
main_frame = tk.Frame(root, bg="#f3f4f6")
main_frame.pack(fill="both", expand=True, padx=20)

# Left Column (Camera Preview)
cam_container = tk.LabelFrame(main_frame, text="Live Camera Feed", font=("Segoe UI", 11, "bold"), bg="#ffffff", padx=10, pady=10)
cam_container.pack(side="left", padx=10, pady=5)

cam_label = tk.Label(cam_container, bg="#111827", width=50, height=18)
cam_label.pack()

cam_ctrl_frame = tk.Frame(cam_container, bg="#ffffff")
cam_ctrl_frame.pack(pady=8)

btn_camera_on = tk.Button(cam_ctrl_frame, text="Start Preview", command=start_camera, bg="#2563eb", fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=4, relief="flat")
btn_camera_on.pack(side="left", padx=5)

btn_camera_off = tk.Button(cam_ctrl_frame, text="Stop Preview", command=stop_camera, bg="#6b7280", fg="white", font=("Segoe UI", 9, "bold"), padx=10, pady=4, relief="flat")
btn_camera_off.pack(side="left", padx=5)

# Right Column (Controls & Enrollment)
ctrl_container = tk.LabelFrame(main_frame, text="Face Registration & Actions", font=("Segoe UI", 11, "bold"), bg="#ffffff", padx=15, pady=10)
ctrl_container.pack(side="right", fill="both", expand=True, padx=10, pady=5)

tk.Label(ctrl_container, text="Name:", font=("Segoe UI", 10), bg="#ffffff").pack(anchor="w", pady=(5, 0))
entry_name = tk.Entry(ctrl_container, font=("Segoe UI", 11), width=24)
entry_name.pack(fill="x", pady=2)

tk.Label(ctrl_container, text="Age:", font=("Segoe UI", 10), bg="#ffffff").pack(anchor="w", pady=(5, 0))
entry_age = tk.Entry(ctrl_container, font=("Segoe UI", 11), width=24)
entry_age.pack(fill="x", pady=2)

btn_register = tk.Button(ctrl_container, text="➕ Register Current Face", bg="#059669", fg="white", font=("Segoe UI", 10, "bold"), pady=6, relief="flat", command=register_face)
btn_register.pack(fill="x", pady=(15, 6))

btn_start = tk.Button(ctrl_container, text="🚀 Launch Recognition (Live)", bg="#7c3aed", fg="white", font=("Segoe UI", 10, "bold"), pady=6, relief="flat", command=start_recognition)
btn_start.pack(fill="x", pady=6)

btn_logs = tk.Button(ctrl_container, text="📁 Open Logs & Snapshots", font=("Segoe UI", 9), pady=4, command=open_logs)
btn_logs.pack(fill="x", pady=6)

# Bottom Section: Attendance Log
att_container = tk.LabelFrame(root, text="📋 Recent Attendance & Recognition Logs", font=("Segoe UI", 11, "bold"), bg="#ffffff", padx=10, pady=10)
att_container.pack(fill="both", expand=True, padx=30, pady=10)

columns = ("Name", "Age", "Match %", "Emotion", "Timestamp")
tree = ttk.Treeview(att_container, columns=columns, show="headings", height=5)
for col in columns:
    tree.heading(col, text=col)
    tree.column(col, width=140, anchor="center")
tree.pack(fill="both", expand=True)

# Start periodic table refresh
refresh_attendance()

# Footer Exit Button
quit_button = tk.Button(root, text="Exit Application", font=("Segoe UI", 9, "bold"), command=root.destroy, bg="#dc2626", fg="white", pady=4, relief="flat")
quit_button.pack(pady=8)

root.protocol("WM_DELETE_WINDOW", lambda: (stop_camera(), root.destroy()))
root.mainloop()
