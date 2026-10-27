from keras.models import Sequential
from keras.layers import Dense
from keras import Input

# Create dummy model (adjust according to your actual input and output if needed)
model = Sequential([
    Input(shape=(48,)),  # Dummy input shape
    Dense(10, activation='relu'),
    Dense(7, activation='softmax')  # 7 emotions
])

# Save model
model.save(r"C:\Users\HP\Desktop\Download\Download\python\my_model.keras")
print("✅ Model saved at C:\\Users\\HP\\Desktop\\Download\\Download\\python\\my_model.keras")
