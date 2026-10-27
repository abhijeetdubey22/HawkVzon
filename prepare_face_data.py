import os
import sys
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
folder_path = os.path.join(BASE_DIR, "faces")
os.makedirs(folder_path, exist_ok=True)
encoding_list = []
name_list = []
age_list = []

for file in sorted(os.listdir(folder_path)):
    if file.endswith(".npy"):
        try:
            data = np.load(os.path.join(folder_path, file), allow_pickle=True)
            encoding_list.append(data)

            parts = file[:-4].split("_")  # Remove .npy and split
            if len(parts) >= 2:
                name = " ".join(parts[:-1])  # name can have spaces
                age = parts[-1]
            else:
                name = parts[0]
                age = "Unknown"

            name_list.append(name)
            age_list.append(age)
        except Exception as e:
            print(f"[Warning] Could not load {file}: {e}")

np.save(os.path.join(BASE_DIR, "known_face_encodings.npy"), encoding_list)
np.save(os.path.join(BASE_DIR, "known_face_names.npy"), name_list)
np.save(os.path.join(BASE_DIR, "known_face_ages.npy"), age_list)

print("[SUCCESS] Face data compiled:")
print(f"Total Enrolled Faces: {len(name_list)}")
for n, a in zip(name_list, age_list):
    print(f" - {n} (Age: {a})")
