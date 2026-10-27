import cv2
import numpy as np

# Load model files (use your confirmed paths)
model_path = r"C:\Users\HP\Desktop\Download\Download\python\gender_net.caffemodel"
config_path = r"C:\Users\HP\Desktop\Download\Download\python\gender_deploy.prototxt"

# Load pre-trained gender detection model
net = cv2.dnn.readNetFromCaffe(config_path, model_path)

# Gender labels
GENDERS = ["Male", "Female"]

# Load an image (change the filename if needed)
image = cv2.imread("face.jpg")  # Place 'face.jpg' in the same folder
if image is None:
    print("❌ Image not found. Make sure 'face.jpg' exists.")
    exit()

# Prepare face image for the model
blob = cv2.dnn.blobFromImage(image, 1.0, (227, 227), (78.426337, 87.768914, 114.895847), swapRB=False)

# Predict gender
net.setInput(blob)
gender_preds = net.forward()
gender = GENDERS[gender_preds[0].argmax()]
confidence = gender_preds[0].max()

# Show result
label = f"{gender} ({confidence * 100:.1f}%)"
cv2.putText(image, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
cv2.imshow("Gender Detection", image)
cv2.waitKey(0)
cv2.destroyAllWindows()
