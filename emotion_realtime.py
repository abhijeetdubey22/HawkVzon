import cv2
import numpy as np
from keras.models import load_model

# Load the pre-trained emotion model
emotion_model = load_model("C:/Users/HP/Desktop/Download/Download/python/emotion_model.hdf5")

# Common FER-2013 emotion labels
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# Haar Cascade face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Start webcam
cap = cv2.VideoCapture(0)

print("🔍 Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)

    for (x, y, w, h) in faces:
        if w < 48 or h < 48:
            continue  # skip tiny faces

        roi_gray = gray[y:y + h, x:x + w]
        roi_resized = cv2.resize(roi_gray, (48, 48))
        roi_normalized = roi_resized / 255.0
        roi_reshaped = np.expand_dims(roi_normalized, axis=(0, -1))  # (1, 48, 48, 1)

        # Predict
        prediction = emotion_model.predict(roi_reshaped, verbose=0)
        emotion_idx = np.argmax(prediction[0])
        confidence = float(np.max(prediction[0]))

        if emotion_idx < len(emotion_labels):
            emotion_text = f"{emotion_labels[emotion_idx]} ({confidence*100:.1f}%)"
        else:
            emotion_text = "Unknown"

        # Draw box and label
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(frame, emotion_text, (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 0), 2)

    cv2.imshow("Emotion Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
