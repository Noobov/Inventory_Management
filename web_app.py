from flask import Flask, render_template, Response, jsonify, request, send_file
import cv2
import pandas as pd
import threading
import torch
from datetime import datetime
import serial
import requests
import time

app = Flask(__name__)

# Global variables to store detected objects and control video capture
detected_objects = []
video_capture = None
inventory = []  # List to hold inventory items

# Serial communication setup
arduino_port = 'COM3'  # Replace with your port (e.g., 'COM9')
baud_rate = 9600  # This must match the baud rate in the Arduino code

previous_state = None

# Mode: 1 for adding items, 0 for deleting items
mode = 1

# Load YOLOv5 model once at startup
model = torch.hub.load('ultralytics/yolov5', 'yolov5l', pretrained=True)

def generate_frames():
    """Generate video frames for streaming with object detection."""
    global detected_objects, video_capture

    cap = cv2.VideoCapture(1)

    while video_capture:
        success, frame = cap.read()
        if not success:
            break

        # Object detection logic (YOLOv5)
        results = model(frame)
        detections = results.xyxy[0]  # Get detections as [x1, y1, x2, y2, confidence, class]

        detected_objects.clear()  # Clear previous detections

        for *box, conf, cls in detections:
            label = results.names[int(cls)]
            detected_objects.append({
                'name': label,
                'box': box,
                'confidence': conf.item(),
                'area': (box[2] - box[0]) * (box[3] - box[1])  # Calculate area of bounding box
            })

            # Draw bounding box on the frame
            cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 0, 0), 2)
            cv2.putText(frame, f'{label} {conf:.2f}', (int(box[0]), int(box[1] - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

        # Encode the frame in JPEG format
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route."""
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_video')
def start_video():
    """Start video capture in a separate thread."""
    global video_capture
    video_capture = True
    threading.Thread(target=generate_frames).start()
    return jsonify(success=True)

@app.route('/stop_video')
def stop_video():
    """Stop video capture."""
    global video_capture
    video_capture = False
    return jsonify(success=True)

@app.route('/set_mode', methods=['POST'])
def set_mode():
    global mode

    # Get JSON data from the request
    data = request.json

    # Check if 'mode' key exists in the incoming data
    if 'mode' not in data:
        return jsonify(success=False, message="Missing 'mode' key"), 400

    mode = data['mode']
    
    return jsonify(success=True)

@app.route('/get_detected_objects')
def get_detected_objects():
    """Return the list of detected objects."""
    return jsonify(detected_objects)

@app.route('/add_to_inventory', methods=['POST'])
def add_to_inventory():
    """Add detected objects to the inventory."""
    
    global inventory
    
    if mode == 1:  # Only add if mode is for adding items
        for obj in detected_objects:
            item = {
                'id': len(inventory) + 1,
                'object_name': obj['name'],
                'count': 1,
                'date_added': datetime.now().strftime("%Y-%m-%d"),
                'time_added': datetime.now().strftime("%H:%M:%S"),
                'accuracy': float(obj['confidence']),  # Convert tensor to float
                'area': float(obj['area'])  # Ensure area is also a float
            }
            inventory.append(item)
    
    return jsonify(inventory)

@app.route('/get_inventory')
def get_inventory():
    """Return current inventory."""
    return jsonify(inventory)

@app.route('/update_inventory', methods=['POST'])
def update_inventory():
    """Update an existing inventory item."""
    
    global inventory
    
    data = request.json
    
    for item in inventory:
        if item['id'] == data['id']:
            item['object_name'] = data.get('object_name', item['object_name'])
            item['count'] = data.get('count', item['count'])
            item['accuracy'] = data.get('accuracy', item['accuracy'])
            
            return jsonify(inventory)  # Return updated inventory
    
    return jsonify({"error": "Item not found"}), 404

@app.route('/delete_scan_item', methods=['DELETE'])
def delete_scan_item():
    """Delete Scan item based on detected objects."""
    
    global inventory
    
    if mode == 0:  # Delete mode activated
        print('Detected objects:', detected_objects)

        for detected in detected_objects:
            # Find and remove only one instance of the detected object
            for item in inventory:
                if item['object_name'] == detected['name']:
                    inventory.remove(item)
                    print(f'Removed: {item}')
                    break  # Exit after removing one instance

        print('Updated inventory:', inventory)
        return jsonify(success=True)

@app.route('/export_csv')
def export_csv():
    """Export inventory to CSV."""
    
    df = pd.DataFrame(inventory)
    
    csv_file_path = "inventory.csv"
    
    df.to_csv(csv_file_path, index=False)
    
    return send_file(csv_file_path, as_attachment=True)

@app.route('/export_xlsx')
def export_xlsx():
    """Export inventory to XLSX."""
    
    df = pd.DataFrame(inventory)
    
    xlsx_file_path = "inventory.xlsx"
    
    df.to_excel(xlsx_file_path, index=False)
    
    return send_file(xlsx_file_path, as_attachment=True)

def read_serial_data():
    """Read data from Arduino via serial connection."""
    
    global previous_state
    
    add_to_inventory_endpoint = 'http://127.0.0.1:5000/add_to_inventory'
    
    delete_scan_item_endpoint = 'http://127.0.0.1:5000/delete_scan_item'
    
    try:
        ser = serial.Serial(arduino_port, baud_rate, timeout=1)
        
        print("Connected to Arduino at port:", arduino_port)
        
        time.sleep(2)  # Wait for Arduino to reset
        
        while True:
            if ser.in_waiting > 0:
                sensor_data = ser.readline().decode('utf-8').strip()  # Read and decode the data
                
                try:
                    current_state = int(sensor_data)  # Convert the sensor data to an integer
                    
                    if previous_state != current_state:  # State has changed

                        print(f"Previous state: {previous_state}, Current state: {current_state}")

                        if current_state == 1:  # Object detected (HIGH)
                            print("Object detected")
                            print('Current mode:', mode) 

                            if mode == 1:
                                response = requests.post(add_to_inventory_endpoint)
                                if response.status_code == 200:
                                    print('Successfully added to inventory:', response.json())
                                else:
                                    print('Failed to add to inventory:', response.status_code, response.text)

                        elif current_state == 0:  
                            response = requests.delete(delete_scan_item_endpoint)
                            if response.status_code == 200:
                                print('Successfully deleted from inventory:', response.json())
                            else:
                                print('Failed to delete from inventory:', response.status_code, response.text)

                        previous_state = current_state
                
                except ValueError as ve:
                    print(f"Received non-integer data: {sensor_data}. Error: {ve}")

                except serial.SerialException as e:
                    print(f"Error connecting to serial port: {e}")

                except Exception as e:
                    print(f"An unexpected error occurred: {e}")

    except Exception as e:
        print(f"Failed to initialize serial communication: {e}")

if __name__ == '__main__':
    threading.Thread(target=read_serial_data).start()  # Start reading from serial in a new thread
    app.run(debug=True)