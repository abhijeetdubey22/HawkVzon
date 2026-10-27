# Let's assume you already have a variable with the recognized person's name
# For example, this might come from your face recognition system
name = "vijay" # Replace 'detected_name' with your actual variable

if name == "Unknown":
    print("Unidentified person detected!")
    # Send WhatsApp alert using pywhatkit
    import pywhatkit
    pywhatkit.sendwhatmsg_instantly("+911234567890", "⚠ Unidentified person detected at the camera!")
else:
    print(f"Recognized person: {name}")
