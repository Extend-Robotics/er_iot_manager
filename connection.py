import sys
import signal
import requests
import time
import threading
import subprocess
import os
from pathlib import Path
from awscrt import mqtt
from awsiot import mqtt_connection_builder
from utils.command_line_utils import CommandLineUtils

BASE_DIR = Path.home()
IOT_MANAGER_DIR = BASE_DIR / "er_iot_manager"
JOBS_SCRIPT_FILE = IOT_MANAGER_DIR / "jobs.py"
BACKEND_URL = "https://api.extendrobotics.com"  # Backend URL for notifying connection status

# Set the backend URL environment variable (e.g., set to production or development URL)
os.environ['BACKEND_URL'] = BACKEND_URL  # Change as needed

# Parse command-line arguments
# cmdData will hold parsed values for various required inputs (e.g., endpoint, certs, keys, etc.)
cmdData = CommandLineUtils.parse_sample_input_jobs()
print("Parsed command line arguments.")  # Debugging log

# AWS IoT Core connection parameters from command-line arguments
# Creating an MQTT connection using the provided certificate and key paths, endpoint, client ID, etc.
print("Creating MQTT connection...")  # Debugging log
mqtt_connection = mqtt_connection_builder.mtls_from_path(
    endpoint=cmdData.input_endpoint,  # The AWS IoT endpoint
    port=cmdData.input_port,  # Port for MQTT connection (usually 8883 for secure MQTT)
    cert_filepath=cmdData.input_cert,  # Path to the client certificate
    pri_key_filepath=cmdData.input_key,  # Path to the private key
    ca_filepath=cmdData.input_ca,  # Path to the CA certificate
    client_id=cmdData.input_clientId,  # Client ID used for connecting (must be unique per device)
    clean_session=False,  # Set to False to persist session across multiple connections
    keep_alive_secs=30  # Keep-alive interval for MQTT connection
)
print("MQTT connection created.")  # Debugging log

# The unique identifier for the device; this is typically the "thing name" in AWS IoT
thing_name = cmdData.input_thing_name
# Default connection status
connection_status = "Disconnected"

# Function to notify backend of device connection status
def notify_backend(status):
    payload = {"thingName": thing_name, "status": status}  # Payload to send to backend
    start_time = time.time()  # Record the start time
    while True:
        try:
            print(f"Attempting to notify backend with status: {status}")  # Debugging log
            response = requests.post(f"{BACKEND_URL}/devices/status", json=payload)  # Send status update to backend
            response.raise_for_status()  # Raise an error if the response contains an HTTP error status code
            # Status update was successful
            print("Successfully notified backend.")  # Debugging log
            return True
        except requests.exceptions.RequestException as e:
            # Log the failure and retry every 10 seconds until 24 hours have passed
            print(f"Failed to update status: {e}")
            if time.time() - start_time > 86400:  # 86400 seconds = 24 hours
                print("Failed to update status for 24 hours. Giving up.")
                return False
            print("Retrying to notify backend in 10 seconds...")  # Debugging log
            time.sleep(10)  # Retry every 10 seconds

# Callback for connection interruptions (e.g., internet outage)
def on_connection_interrupted(connection, error, **kwargs):
    global connection_status
    if connection_status != "Disconnected":
        # Log the connection interruption and notify backend
        print(f"Connection interrupted for device {thing_name}. Error: {error}")  # Debugging log
        connection_status = "Disconnected"
        notify_backend(connection_status)

# Callback for connection resumptions
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    global connection_status
    # If the connection was successfully resumed, update the connection status
    if return_code == mqtt.ConnectReturnCode.ACCEPTED and connection_status != "Connected":
        print(f"Connection resumed for device {thing_name}")  # Debugging log
        connection_status = "Connected"
        notify_backend(connection_status)

# Function to handle termination signals (e.g., SIGTERM)
def handle_termination(signum, frame):
    print("Termination signal received. Cleaning up...")  # Debugging log
    # Disconnect MQTT connection gracefully
    disconnect_future = mqtt_connection.disconnect()
    print("Waiting for MQTT disconnection to complete...")  # Debugging log
    disconnect_future.result()  # Wait for the disconnect to complete
    # Notify backend that the device is disconnected
    notify_backend("Disconnected")
    print("Disconnected!")  # Debugging log
    sys.exit(0)

# Register the signal handler for termination
signal.signal(signal.SIGTERM, handle_termination)

# Function to run jobs script
def run_external_script():
    print("Starting jobs script...")  # Debugging log
    # Run the external Python script asynchronously with the same parameters
    subprocess.Popen(["python3", JOBS_SCRIPT_FILE, \
                      "--endpoint", cmdData.input_endpoint, \
                      "--key", cmdData.input_key, \
                      "--cert", cmdData.input_cert, \
                      "--thing_name", thing_name, \
                      "--ca_file", cmdData.input_ca])  

# Start the external script in a separate thread
external_script_thread = threading.Thread(target=run_external_script)
external_script_thread.start()

# Connect to AWS IoT Core
print(f"Connecting to {cmdData.input_endpoint} with client ID {thing_name}...")  # Debugging log
connect_future = mqtt_connection.connect()  # Initiate the connection
print("Waiting for MQTT connection to complete...")  # Debugging log
connect_future.result()  # Wait for the connection to complete
connection_status = "Connected"
print("Successfully connected to AWS IoT Core.")  # Debugging log
notify_backend(connection_status)  # Notify backend that the device is now connected
print("Connected!")  # Debugging log

# Send heartbeat every 5 seconds to notify backend of connection status
try:
    while True:
        if connection_status == "Connected":
            print("Sending heartbeat to backend...")  # Debugging log
            if not notify_backend("Connected"):
                # If unable to notify backend after 24 hours, assume disconnected and stop trying
                print("Failed to notify backend after 24 hours. Assuming disconnected.")  # Debugging log
                connection_status = "Disconnected"
        time.sleep(5)  # Wait for 5 seconds before sending the next heartbeat
except KeyboardInterrupt:
    # Handle user interruption (e.g., Ctrl+C)
    print("Keyboard interrupt received. Disconnecting...")  # Debugging log
finally:
    # Ensure the MQTT connection is disconnected gracefully
    print("Ensuring graceful MQTT disconnection...")  # Debugging log
    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()  # Wait for the disconnect to complete
    notify_backend("Disconnected")  # Notify backend of disconnection
    print("Disconnected!")  # Debugging log
