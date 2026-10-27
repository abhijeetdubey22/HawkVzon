import cv2

# 1. Load image
image = cv2.imread("face.jpg")
if image is None:
    print("⚠️  Could not load face.jpg")
    exit()

# 2. Convert to grayscale (required by Haar cascade)
gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

# 3. Load Haar cascade (make sure this file exists!)
cascade = cv2.CascadeClassifier("haarcascade_frontalface_default.xml")
if cascade.empty():
    print("⚠️  Failed to load cascade XML")
    exit()

# 4. Detect faces
faces = cascade.detectMultiScale(
    gray,
    scaleFactor=1.1,
    minNeighbors=5,
    minSize=(30, 30)
)

print(f"🎯 Detected {len(faces)} face(s)")

# 5. Draw rectangles
for (x, y, w, h) in faces:
    cv2.rectangle(image, (x, y), (x + w, y + h), (255,0, 0), 2)

# 6. Show & save results
cv2.imshow("Faces Found", image)
cv2.waitKey(0)
cv2.destroyAllWindows()
cv2.imwrite("faces_detected.jpg", image)
print("📸 Saved output as faces_detected.jpg")
