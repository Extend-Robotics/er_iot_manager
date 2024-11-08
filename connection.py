from awscrt import mqtt
from awsiot import mqtt_connection_builder
import requests
from utils.command_line_utils import CommandLineUtils

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

# Backend URL for notifying connection status
backend_url = "http://192.168.0.43:8080/devices/status"
connection_status = "Disconnected"

def notify_backend(status):
    try:
        response = requests.post(backend_url, json={"status": status})
        response.raise_for_status()
        print(f"Status updated to {status}")
    except requests.exceptions.RequestException as e:
        print(f"Failed to update status: {e}")

# Callback for connection interruptions
def on_connection_interrupted(connection, error, **kwargs):
    global connection_status
    print("Connection interrupted. Error:", error)
    connection_status = "Disconnected"
    notify_backend(connection_status)

# Callback for connection resumptions
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    global connection_status
    print("Connection resumed. Return code:", return_code)
    connection_status = "Connected" if return_code == mqtt.ConnectReturnCode.ACCEPTED else "Disconnected"
    notify_backend(connection_status)

# Connect to AWS IoT Core
print(f"Connecting to {cmdData.input_endpoint} with client ID {cmdData.input_clientId}...")
connect_future = mqtt_connection.connect()
connect_future.result()
connection_status = "Connected"
notify_backend(connection_status)
print("Connected!")

try:
    while True:
        pass  # Keep the script running to allow the connection callbacks to work
except KeyboardInterrupt:
    print("Disconnecting...")
finally:
    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()
    notify_backend("Disconnected")
    print("Disconnected!")
