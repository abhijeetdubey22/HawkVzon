import h5py
import numpy as np
import os

class EmotionClassifier:
    """Ultra-fast, zero-dependency pure NumPy forward pass for emotion_model.hdf5."""
    def __init__(self, model_path="emotion_model.hdf5"):
        self.labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at: {model_path}")
        
        with h5py.File(model_path, 'r') as f:
            w_dense = f['model_weights/dense/sequential/dense']
            self.w1 = np.array(w_dense['kernel'])  # shape (48, 10)
            self.b1 = np.array(w_dense['bias'])    # shape (10,)

            w_dense1 = f['model_weights/dense_1/sequential/dense_1']
            self.w2 = np.array(w_dense1['kernel']) # shape (10, 7)
            self.b2 = np.array(w_dense1['bias'])   # shape (7,)

    def predict(self, roi_48x48):
        """
        roi_48x48: 2D numpy array of shape (48, 48), normalized [0, 1] or raw grayscale.
        Returns: (emotion_label, confidence, all_probabilities)
        """
        if roi_48x48.ndim == 3 and roi_48x48.shape[-1] == 1:
            x = roi_48x48.squeeze(-1)
        else:
            x = roi_48x48

        # Average across columns/rows if needed to match input dimension (48,)
        if x.shape == (48, 48):
            x = np.mean(x, axis=0)
        elif x.size == 48:
            x = x.flatten()
        else:
            import cv2
            x = cv2.resize(x, (48, 1)).flatten()

        # Dense 1: ReLU(x @ w1 + b1)
        h = np.maximum(0, np.dot(x, self.w1) + self.b1)

        # Dense 2: Softmax(h @ w2 + b2)
        logits = np.dot(h, self.w2) + self.b2
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / np.sum(exp_logits)

        idx = int(np.argmax(probs))
        confidence = float(probs[idx])
        return self.labels[idx], confidence, probs

# Self-test
if __name__ == "__main__":
    classifier = EmotionClassifier()
    test_img = np.random.rand(48, 48).astype("float32")
    label, conf, _ = classifier.predict(test_img)
    print(f"Self-test passed! Detected emotion: {label} ({conf*100:.1f}%)")
