import cv2
import numpy as np

# Load Haar cascade for face detection
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# Load pre-trained age and gender models
age_net = cv2.dnn.readNetFromCaffe("age_deploy.prototxt", "age_net.caffemodel")
gender_net = cv2.dnn.readNetFromCaffe("deploy_gender.prototxt", "gender_net.caffemodel")


# Age and gender prediction labels
AGE_BUCKETS = ['(0-2)', '(4-6)', '(8-12)', '(15-20)', '(25-32)', '(38-43)', '(48-53)', '(60-100)']
GENDER_LIST = ['Male', 'Female']

# Start webcam
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("❌ Could not access the webcam.")
    exit()

print("📷 Age & Gender Detection Started. Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("⚠️ Failed to grab frame.")
        break

    # Convert to grayscale for face detection
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

    for (x, y, w, h) in faces:
        # Extract face ROI and preprocess
        face_img = frame[y:y+h, x:x+w].copy()
        if face_img.size == 0:
            continue  # skip empty detections
        blob = cv2.dnn.blobFromImage(face_img, 1.0, (227, 227),
                                     (78.4263377603, 87.7689143744, 114.895847746),
                                     swapRB=False)

        # Predict gender
        gender_net.setInput(blob)
        gender_preds = gender_net.forward()
        gender = GENDER_LIST[gender_preds[0].argmax()]

        # Predict age
        age_net.setInput(blob)
        age_preds = age_net.forward()
        age = AGE_BUCKETS[age_preds[0].argmax()]

        label = f"{gender}, {age}"
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(frame, label, (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # Display the frame
    cv2.imshow("🧠 Age & Gender Detection", frame)

    # Exit on 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        print("👋 Quitting...")
        break

# Release resources
cap.release()
cv2.destroyAllWindows()
