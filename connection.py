from awscrt import mqtt
from awsiot import mqtt_connection_builder
import requests
from utils.command_line_utils import CommandLineUtils
import time

# Parse command-line arguments
cmdData = CommandLineUtils.parse_sample_input_jobs()

# AWS IoT Core connection parameters from command-line arguments
mqtt_connection = mqtt_connection_builder.mtls_from_path(
    endpoint=cmdData.input_endpoint,
    port=cmdData.input_port,
    cert_filepath=cmdData.input_cert,
    pri_key_filepath=cmdData.input_key,
    ca_filepath=cmdData.input_ca,
    client_id=cmdData.input_clientId,
    clean_session=False,
    keep_alive_secs=30
)

device_id = cmdData.input_thing_name  # Unique identifier for the device, e.g., the thing_name or client_id
backend_url = "http://192.168.0.43:8080/devices/status"  # Backend URL for notifying connection status
connection_status = "Disconnected"

def notify_backend(status, retries=5, backoff_factor=1):
    attempt = 0
    payload = {"device_id": device_id, "status": status}
    while attempt < retries:
        try:
            response = requests.post(backend_url, json=payload)
            response.raise_for_status()
            print(f"Status updated to {status} for device {device_id}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Failed to update status: {e}")
            attempt += 1
            time.sleep(backoff_factor * (2 ** attempt))  # Exponential backoff
    print(f"Failed to update status after {retries} attempts for device {device_id}.")
    return False

# Callback for connection interruptions (e.g., internet outage)
def on_connection_interrupted(connection, error, **kwargs):
    global connection_status
    if connection_status != "Disconnected":
        print(f"Connection interrupted for device {device_id}. Error:", error)
        connection_status = "Disconnected"
        notify_backend(connection_status)

# Callback for connection resumptions
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    global connection_status
    if return_code == mqtt.ConnectReturnCode.ACCEPTED and connection_status != "Connected":
        print(f"Connection resumed for for device {device_id}")
        connection_status = "Connected"
        notify_backend(connection_status)

# Connect to AWS IoT Core
print(f"Connecting to {cmdData.input_endpoint} with client ID {device_id}...")
connect_future = mqtt_connection.connect()
connect_future.result()
connection_status = "Connected"
notify_backend(connection_status)
print("Connected!")

# Send heartbeat every 5 seconds
try:
    while True:
        if connection_status == "Connected":
            if not notify_backend("Connected"):
                # If unable to notify backend, assume disconnected and retry
                connection_status = "Disconnected"
        time.sleep(5)
except KeyboardInterrupt:
    print("Disconnecting...")
finally:
    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()
    notify_backend("Disconnected")
    print("Disconnected!")