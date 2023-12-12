from flask import Flask, render_template, request, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
import numpy as np
import pandas as pd
from twilio.rest import Client
from datetime import datetime
import time
import sys
import Adafruit_DHT
import RPi.GPIO as GPIO
from gpiozero import LightSensor
import atexit
import tensorflow as tf
from picamera import PiCamera
from PIL import Image
import io

app = Flask(__name__)
atexit.register(cleanup_function)
# Load the CSV file into a DataFrame
plants_df = pd.read_csv('plants.csv')
selected_plant = None
phone_number = "+96176804837"
last_watered = None
ldr = LightSensor(16)
servo_state = 0

def cleanup_function():
    GPIO.cleanup()
def get_humidity_and_temperature():
    humidity, temperature = Adafruit_DHT.read_retry(11, 4)
    return humidity, temperature

def is_soil_dry():
    pin_value = GPIO.input(37)
    time.sleep(1)
    is_dry = pin_value == 0
    return is_dry

def water_the_plant():
    print("Pin 40 set to high (1)")
    time.sleep(15)
    GPIO.output(OUTPUT_PIN, GPIO.LOW)
    return int(time.time())  # Return Unix timestamp

def rotate_camera():
    global servo_state
    pwm = GPIO.PWM(12, 50)
    if servo_state == 0:
        pwm.ChangeDutyCycle(7.5)
        time.sleep(1)
        servo_state = 1
        pwm.stop()
    elif servo_state == 1:
        pwm.ChangeDutyCycle(8.33)
        time.sleep(1)
        servo_state = 2
        pwm.stop()
    else:
        pwm.ChangeDutyCycle(10.83)
        time.sleep(1)
        servo_state = 0
        pwm.stop()

def check_for_yellow_leaves():
    # Load the model
    model = tf.keras.models.load_model(best_model.h5)

    # Initialize the camera
    camera = PiCamera()
    
    # Capture an image
    image_stream = io.BytesIO()
    camera.capture(image_stream, format='jpeg')
    image_stream.seek(0)  # Go to the beginning of the IO stream

    # Open the image and preprocess it for the model
    image = Image.open(image_stream)
    image = image.resize((224, 224))  # Example resize, adjust to your model's input size
    image_array = np.array(image)
    image_array = np.expand_dims(image_array, axis=0)  # Model expects a batch of images

    # Run the model on the image
    predictions = model.predict(image_array)

    # Clean up resources
    del model
    camera.close()
    del image_stream

    return predictions

def check_low_light_during_day():
    global ldr
    light_level = ldr.value

    if is_daylight() and light_level < 0.2:
        return True
    else:
        return False


def is_daylight():
    """Check if current time is during daylight hours."""
    current_hour = datetime.now().hour
    return 6 <= current_hour < 18

def human_readable_time_diff(timestamp):
    if timestamp is None:
        return "Not watered yet"

    now = datetime.now()
    diff = now - datetime.fromtimestamp(timestamp)
    
    seconds = diff.total_seconds()
    if seconds < 60:
        return "less than a minute ago"
    elif seconds < 3600:  # less than 1 hour
        minutes = int(seconds / 60)
        return f"{minutes} mins ago"
    elif seconds < 86400:  # less than 1 day
        hours = int(seconds / 3600)
        return f"{hours} hours ago"
    else:
        days = int(seconds / 86400)
        return f"{days} days ago"

def send_alert(phone, input_message):
    account_sid = 'ACd33a125fa90ccdd924634e482348387c'
    auth_token = '5c7b69d0d228ad4276fd3d9a2faac6fb'
    client = Client(account_sid, auth_token)
    to_string = 'whatsapp:'+phone
    message = client.messages.create(
    from_='whatsapp:+14155238886',
    body=input_message,
    to=to_string
    )

def check_conditions():
    global selected_plant, phone_number, last_watered
    if selected_plant:
        plant_data = plants_df[plants_df['plant_name'] == selected_plant].iloc[0]
        humidity, temperature = get_humidity_and_temperature()

        # Check humidity conditions
        if humidity < plant_data['min_humidity']:
            send_alert(phone_number, f"Humidity is too low: {humidity}%, increase it.")
        elif humidity > plant_data['max_humidity']:
            send_alert(phone_number, f"Humidity is too high: {humidity}%, decrease it.")
        
        # Check temperature conditions
        if temperature < plant_data['min_temp']:
            send_alert(phone_number, f"Temperature is too low: {temperature}°C, increase it.")
        elif temperature > plant_data['max_temp']:
            send_alert(phone_number, f"Temperature is too high: {temperature}°C, decrease it.")
        if is_soil_dry():
            last_watered = water_the_plant()
            send_alert(phone_number, f"Plant watered on Unix timestamp: {last_watered}")
        if check_for_yellow_leaves()==1:
            send_alert(phone_number, "s")
        if check_low_light_during_day():
            send_alert("Your plant is not receiving enough light during the day. Please check")    

@app.route('/')
def index():
    humidity, temperature = get_humidity_and_temperature()
    return render_template('index.html', plant=selected_plant, last_watered=human_readable_time_diff(LAST_WATERED), temp=temperature, humidity=humidity)

@app.route('/form', methods=['GET', 'POST'])
def form():
    global selected_plant
    global phone_number
    if request.method == 'POST':
        selected_plant = request.form.get('plant')
        phone_number = request.form.get('phone')
        check_conditions()
        return redirect(url_for('index'))

    return render_template('form.html', plants=plants_df['plant_name'].tolist())

@app.route('/check')
def check():
    check_conditions()
    return redirect(url_for('index'))

@app.route('/rotate')
def rotate():
    rotate_camera()
    return redirect(url_for('index'))

if __name__ == '__main__':
    GPIO.setup(37, GPIO.IN)
    GPIO.setup(40, GPIO.OUT)
    GPIO.setup(12, GPIO.OUT) #servo
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_conditions, trigger="interval", minutes=30)
    scheduler.add_job(func=rotate_camera, trigger="interval", minutes=15)
    scheduler.start()
    app.run(debug=True, use_reloader=False)
