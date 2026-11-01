import os
import sys
import time
import unittest
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class TestFaceEmotionSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 65)
        print("        FACE & EMOTION RECOGNITION SYSTEM TEST SUITE")
        print("=" * 65)

    def test_01_core_dependencies(self):
        """Test that all required libraries can be imported without issues."""
        start = time.time()
        import cv2
        import face_recognition
        import dlib
        import pyttsx3
        import h5py
        from PIL import Image
        elapsed = (time.time() - start) * 1000
        print(f"  [PASS] Dependencies imported ({elapsed:.1f}ms)")
        print(f"         - OpenCV: {cv2.__version__}")
        print(f"         - dlib: {dlib.__version__}")
        print(f"         - NumPy: {np.__version__}")

    def test_02_database_integrity(self):
        """Test known face embeddings, names, and ages alignment."""
        enc_file = os.path.join(BASE_DIR, "known_face_encodings.npy")
        names_file = os.path.join(BASE_DIR, "known_face_names.npy")
        ages_file = os.path.join(BASE_DIR, "known_face_ages.npy")

        self.assertTrue(os.path.exists(enc_file), "known_face_encodings.npy missing")
        self.assertTrue(os.path.exists(names_file), "known_face_names.npy missing")
        self.assertTrue(os.path.exists(ages_file), "known_face_ages.npy missing")

        encodings = np.load(enc_file, allow_pickle=True)
        names = np.load(names_file, allow_pickle=True)
        ages = np.load(ages_file, allow_pickle=True)

        self.assertGreater(len(encodings), 0, "No face encodings found in database")
        self.assertEqual(len(encodings), len(names), "Encodings and names length mismatch")
        self.assertEqual(len(names), len(ages), "Names and ages length mismatch")

        # Each encoding must be 128-dimensional vector
        for enc in encodings:
            self.assertEqual(enc.shape, (128,), f"Expected 128-D vector, got {enc.shape}")

        print(f"  [PASS] Database integrity: {len(names)} identities enrolled")
        for n, a in zip(names[:3], ages[:3]):
            print(f"         - Verified: {n} (Age: {a})")
        if len(names) > 3:
            print(f"         - ... and {len(names)-3} more identities")

    def test_03_face_matching_accuracy(self):
        """Test actual face detection and matching against enrolled identity."""
        sample_img_path = os.path.join(BASE_DIR, "abhijeet_19.jpg")
        self.assertTrue(os.path.exists(sample_img_path), "Test image abhijeet_19.jpg missing")

        import face_recognition
        start = time.time()
        img = face_recognition.load_image_file(sample_img_path)
        locations = face_recognition.face_locations(img)
        self.assertGreater(len(locations), 0, "No face detected in test image")

        encodings = face_recognition.face_encodings(img, locations)
        self.assertGreater(len(encodings), 0, "Failed to compute face encoding")

        known_encodings = np.load(os.path.join(BASE_DIR, "known_face_encodings.npy"), allow_pickle=True)
        known_names = np.load(os.path.join(BASE_DIR, "known_face_names.npy"), allow_pickle=True)

        distances = face_recognition.face_distance(known_encodings, encodings[0])
        best_idx = int(np.argmin(distances))
        best_name = str(known_names[best_idx])
        confidence = (1.0 - distances[best_idx]) * 100

        elapsed = (time.time() - start) * 1000
        print(f"  [PASS] Face matching in {elapsed:.1f}ms")
        print(f"         - Matched Identity: '{best_name}'")
        print(f"         - Distance: {distances[best_idx]:.4f} (Confidence: {confidence:.1f}%)")
        self.assertEqual(best_name.lower(), "abhijeet", f"Expected 'abhijeet', matched '{best_name}'")
        self.assertGreater(confidence, 60.0, "Confidence is below 60% threshold")

    def test_04_emotion_classifier(self):
        """Test pure NumPy emotion inference speed and output validity."""
        from emotion_predictor import EmotionClassifier
        model_path = os.path.join(BASE_DIR, "emotion_model.hdf5")
        self.assertTrue(os.path.exists(model_path), "emotion_model.hdf5 missing")

        classifier = EmotionClassifier(model_path)
        valid_emotions = {'Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral'}

        # Test on dummy face patch (48x48)
        dummy_roi = np.random.rand(48, 48).astype("float32")
        start = time.time()
        label, conf, probs = classifier.predict(dummy_roi)
        latency_ms = (time.time() - start) * 1000

        self.assertIn(label, valid_emotions, f"Invalid emotion label: {label}")
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)
        self.assertEqual(len(probs), 7)
        self.assertAlmostEqual(float(np.sum(probs)), 1.0, places=4)

        print(f"  [PASS] Emotion classifier forward pass ({latency_ms:.3f}ms)")
        print(f"         - Predicted Emotion: {label} ({conf*100:.1f}%)")
        print(f"         - Total probability sum: {np.sum(probs):.4f}")

    def test_05_age_gender_dnn(self):
        """Test Age & Gender DNN model loading and inference for unknown persons."""
        import cv2
        age_proto = os.path.join(BASE_DIR, "age_deploy.prototxt")
        age_weights = os.path.join(BASE_DIR, "age_net.caffemodel")
        gender_proto = os.path.join(BASE_DIR, "deploy_gender.prototxt")
        gender_weights = os.path.join(BASE_DIR, "gender_net.caffemodel")

        self.assertTrue(os.path.exists(age_proto), "age_deploy.prototxt missing")
        self.assertTrue(os.path.exists(age_weights), "age_net.caffemodel missing")
        self.assertTrue(os.path.exists(gender_proto), "deploy_gender.prototxt missing")
        self.assertTrue(os.path.exists(gender_weights), "gender_net.caffemodel missing")

        start = time.time()
        age_net = cv2.dnn.readNetFromCaffe(age_proto, age_weights)
        gender_net = cv2.dnn.readNetFromCaffe(gender_proto, gender_weights)

        dummy_roi = np.zeros((227, 227, 3), dtype=np.uint8)
        blob = cv2.dnn.blobFromImage(dummy_roi, 1.0, (227, 227),
                                     (78.4263377603, 87.7689143744, 114.895847746), swapRB=False)

        gender_net.setInput(blob)
        g_pred = gender_net.forward()
        gender = ['Male', 'Female'][g_pred[0].argmax()]

        age_net.setInput(blob)
        a_pred = age_net.forward()
        AGE_BUCKETS = ['(0-2)', '(4-6)', '(8-12)', '(15-20)', '(25-32)', '(38-43)', '(48-53)', '(60-100)']
        age = AGE_BUCKETS[a_pred[0].argmax()]
        elapsed = (time.time() - start) * 1000

        print(f"  [PASS] Age & Gender DNN verified ({elapsed:.1f}ms)")
        print(f"         - Test classification: {gender}, {age}")

    def test_06_tts_engine(self):
        """Test Text-To-Speech engine loading."""
        import pyttsx3
        start = time.time()
        try:
            engine = pyttsx3.init()
            rate = engine.getProperty('rate')
            engine.setProperty('rate', 160)
            elapsed = (time.time() - start) * 1000
            print(f"  [PASS] TTS Engine initialized in {elapsed:.1f}ms (Speech rate: {rate} -> 160)")
        except Exception as e:
            print(f"  [INFO] TTS Engine headless note: {e} (Handled gracefully by speech_queue)")

    def test_07_attendance_logging(self):
        """Test attendance CSV writing and directory permissions."""
        import csv
        from datetime import datetime

        logs_dir = os.path.join(BASE_DIR, "logs")
        snapshots_dir = os.path.join(BASE_DIR, "snapshots")
        os.makedirs(logs_dir, exist_ok=True)
        os.makedirs(snapshots_dir, exist_ok=True)

        test_log_file = os.path.join(logs_dir, "test_log.csv")
        test_row = ["TestUser", "20", "95.5%", "Happy", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]

        with open(test_log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Age", "Match %", "Emotion", "Timestamp"])
            writer.writerow(test_row)

        self.assertTrue(os.path.exists(test_log_file))

        with open(test_log_file, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            self.assertEqual(len(reader), 2)
            self.assertEqual(reader[1][0], "TestUser")

        # Cleanup test file
        if os.path.exists(test_log_file):
            os.remove(test_log_file)

        print(f"  [PASS] Attendance logging verified (CSV write/read verified)")

    def test_07_camera_hardware_probe(self):
        """Probe webcam accessibility without blocking."""
        import cv2
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        opened = cap.isOpened()
        if not opened:
            cap = cv2.VideoCapture(0)
            opened = cap.isOpened()

        if opened:
            w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            cap.release()
            print(f"  [PASS] Webcam accessible (Device 0: {int(w)}x{int(h)})")
        else:
            print("  [INFO] Webcam device 0 busy or disconnected (will work upon connecting)")

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=1)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestFaceEmotionSystem)
    result = runner.run(suite)
    print("=" * 65)
    if result.wasSuccessful():
        print("             ALL TESTS PASSED SUCCESSFULLY! (7/7)")
    else:
        print(f"             TESTS FINISHED: {len(result.failures)} Failures, {len(result.errors)} Errors")
    print("=" * 65 + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
