import cv2
import numpy as np
from keras.models import load_model

# ✅ Load the emotion detection model
model_path = r"C:\Users\HP\Desktop\Download\Download\python\my_model.keras"
emotion_model = load_model(model_path)

# ✅ Define emotion labels (update if your model uses different labels)
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# ✅ Load a test image (or use webcam later)
img_path = r"C:\Users\HP\Desktop\Download\Download\python\faces\test.jpg"
image = cv2.imread(img_path)

if image is None:
    print("❌ Image not found!")
    exit()

# ✅ Convert to grayscale if needed (some models require grayscale input)
gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

# ✅ Resize to 48x48 as expected by model
resized = cv2.resize(gray, (48, 48))
normalized = resized / 255.0
reshaped = np.reshape(normalized, (1, 48, 48, 1))

# ✅ Predict emotion
predictions = emotion_model.predict(reshaped)
max_index = int(np.argmax(predictions))
emotion = emotion_labels[max_index]
confidence = float(predictions[0][max_index]) * 100

# ✅ Show result
print(f"Predicted Emotion: {emotion} ({confidence:.2f}%)")

# ✅ Show image with emotion label
cv2.putText(image, f"{emotion} ({confidence:.2f}%)", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
cv2.imshow("Emotion Detection", image)
cv2.waitKey(0)
cv2.destroyAllWindows()
