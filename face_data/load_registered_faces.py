import os
import pickle

def load_registered_faces(folder="faces"):
    if not os.path.exists(folder):
        os.makedirs(folder)  # ✅ Automatically create if not exists
    faces = []
    for file in os.listdir(folder):
        if file.endswith("_face.pkl"):
            with open(os.path.join(folder, file), "rb") as f:
                data = pickle.load(f)
                faces.append(data)
    return faces
