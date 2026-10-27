import cv2

# 1. Load Haar cascade
cascade = cv2.CascadeClassifier("haarcascade_frontalface_default.xml")
if cascade.empty():
    print("⚠️  Could not load cascade XML")
    exit()

# 2. Auto‑detect a working camera index
for cam_idx in (0, 1, 2, 3):
    cap = cv2.VideoCapture(cam_idx)
    if cap.isOpened():
        print(f"✅ Opened camera index {cam_idx}")
        video_capture = cap
        break
    cap.release()
else:
    print("⚠️ Could not open any camera.")
    exit()

print("📸 Webcam opened. Press 'Q' to quit.")

while True:
    ret, frame = video_capture.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30,30))

    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0,255,0), 2)

    cv2.imshow("Real‑Time Face Detection", frame)
    if cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q')):
        break

video_capture.release()
cv2.destroyAllWindows()
print("🛑 Webcam closed.")
