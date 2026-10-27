from keras.models import Sequential
from keras.layers import Dense
from keras.models import load_model

# Dummy model for testing
model = Sequential([
    Dense(10, activation='relu', input_shape=(48, 48)),
    Dense(7, activation='softmax')  # Assuming 7 emotions
])

model.save("test_emotion_model.hdf5")
print("✅ Dummy model saved successfully!")

# Now try to load it
model = load_model("test_emotion_model.hdf5")
print("✅ Dummy model loaded successfully!")
print(model.summary())
