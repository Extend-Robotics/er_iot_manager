import subprocess
import time
import os
import docker
import boto3
import base64
import logging
import requests
from pathlib import Path
from enum import Enum
from datetime import datetime

# Constants for frequently used paths and configuration values
DOCKER_IMAGE = "extend/cortex"
BUCKET_NAME = "er-command-center"
BASE_DIR = Path.home()
FIRMWARE_CONFIG_DIR = BASE_DIR / "firmware_configs"
EXTEND_AUTOSTART_DIR = BASE_DIR / "extend_autostart"
IOT_KIT_DIR = BASE_DIR / ".iot_kit"
IOT_LOGS_DIR = IOT_KIT_DIR / "logs"
DEVICE_ENV_FILE = IOT_KIT_DIR / "device.env"
JOBS_LOG_FILE = IOT_LOGS_DIR / "jobs.log"
CREDENTIAL_PROVIDER_ENDPOINT = "https://c1yqqljqzvtfa.credentials.iot.eu-west-2.amazonaws.com"
DEVICE_ROLE_ALIAS = "ClientDevicesRoleAlias"
CREDENTIAL_URL = f"{CREDENTIAL_PROVIDER_ENDPOINT}/role-aliases/{DEVICE_ROLE_ALIAS}/credentials"
MAX_LOG_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_BACKUP_LOG_FILES = 5  # Limit to 5 backup log files

# Enum for different job actions to make action type handling more readable
class Actions(Enum):
    UPDATE_FIRMWARE = 'UPDATE_FIRMWARE'
    ADD_CONFIGS = 'ADD_CONFIGS'
    RUN_COMMAND = 'RUN_COMMAND'

# Ensure the log directory exists
if not IOT_LOGS_DIR.exists():
    IOT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Ensure the log file exists
if not JOBS_LOG_FILE.exists():
    with open(JOBS_LOG_FILE, 'w'):  # Create the log file if it doesn't exist
        logging.info(f"Log file created: {JOBS_LOG_FILE}")

# Configure logging to output to a file with detailed information, including timestamps
logging.basicConfig(
    filename=JOBS_LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_temporary_credentials():
    """Retrieves temporary credentials from AWS IoT Credential Provider and configures AWS CLI."""
    try:
        cert_path = os.getenv('CERT_FILE_PATH')
        key_path = os.getenv('PRIVATE_KEY_PATH')
        root_ca_path = os.getenv('ROOT_CA_PATH')

        response = requests.get(
            CREDENTIAL_URL,
            cert=(cert_path, key_path),
            verify=root_ca_path
        )
        
        if response.status_code == 200:
            credentials = response.json()["credentials"]
            
            # Configure AWS CLI with temporary credentials
            aws_access_key = credentials["accessKeyId"]
            aws_secret_key = credentials["secretAccessKey"]
            aws_session_token = credentials["sessionToken"]
                        
            return {
                "aws_access_key_id": aws_access_key,
                "aws_secret_access_key": aws_secret_key,
                "aws_session_token": aws_session_token
            }
        else:
            print("Failed to retrieve credentials:", response.text)
            return None
    except Exception as e:
        print(f"Error getting credentials: {e}")
        return None

# Function to manage log file size and rotate if necessary
def manage_log_file():
    try:
        # Rotate the log if it exceeds the maximum file size
        if JOBS_LOG_FILE.exists() and JOBS_LOG_FILE.stat().st_size > MAX_LOG_FILE_SIZE:
            # Rotate the log by renaming the current log file to a backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_log_file = IOT_LOGS_DIR / f"jobs_{timestamp}.log"
            JOBS_LOG_FILE.rename(backup_log_file)
            logging.info(f"Log file rotated. Old log saved as {backup_log_file}")

            # Clean up old log files if the number of backups exceeds the limit
            backup_logs = sorted(IOT_LOGS_DIR.glob("jobs_*.log"), key=os.path.getmtime, reverse=True)
            if len(backup_logs) > MAX_BACKUP_LOG_FILES:
                for old_log in backup_logs[MAX_BACKUP_LOG_FILES:]:
                    try:
                        old_log.unlink()
                        logging.info(f"Deleted old log file: {old_log}")
                    except Exception as e:
                        logging.error(f"Failed to delete old log file {old_log}: {e}")
    except Exception as e:
        logging.error(f"Failed to manage log file: {e}")

# Function to load environment variables from device.env
# If the file doesn't exist or an error occurs, it will log the issue and return an empty dictionary
def load_env_vars():
    """Loads environment variables from device.env."""
    try:
        env_vars = {}
        if not DEVICE_ENV_FILE.exists():
            raise FileNotFoundError(f"device.env file not found in {DEVICE_ENV_FILE}")

        with DEVICE_ENV_FILE.open('r') as file:
            for line in file:
                line = line.strip()
                if line.startswith("export ") and '=' in line:
                    key, value = line.replace("export ", "").split('=', 1)
                    env_vars[key] = value

        return env_vars

    except FileNotFoundError as e:
        logging.error(f"Error loading device.env file: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while loading device.env file: {e}")
    return {}

# Function to update the firmware version in the device.env file
# This function will overwrite the device.env file with the updated version number
def update_device_env(new_version):
    try:
        env_vars = load_env_vars()
        env_vars["firmwareVersion"] = new_version

        with DEVICE_ENV_FILE.open('w') as file:
            for key, value in env_vars.items():
                file.write(f"export {key}={value}\n")

        return True, "Device environment updated successfully."

    except FileNotFoundError as e:
        logging.error(f"Error setting device.env file: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while setting device.env file: {e}")
    return False, "Failed to update device environment."

# Utility function to run shell commands and handle errors
# Instead of using shell=True, we pass the command as a list for security and reliability
def run_command(command_list, use_shell=False):
    try:
        # Determine if shell should be used
        if use_shell:
            result = subprocess.run(" ".join(command_list), shell=True, check=True, capture_output=True, text=True)
        else:
            result = subprocess.run(command_list, check=True, capture_output=True, text=True)
        
        logging.info(f"Command output: {result.stdout.strip()}")
        return True, f"Command output: {result.stdout.strip()}"
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error: {e.stderr.strip()}")
        return False, f"Command failed with error: {e.stderr.strip()}"
    except Exception as e:
        logging.error(f"Command failed with error: {e.stderr.strip()}")
        return False, f"Command failed with error: {e.stderr.strip()}"


# Function to handle the firmware update process, including Docker operations
# This includes logging in to Docker, pulling images, and cleaning up old images if necessary
def handle_update_firmware(version, deleteOldImages):
    if not version:
        logging.error("Firmware version not specified.")
        return False, "Firmware version not specified."

    # Load necessary environment variables
    env_vars = load_env_vars()
    ecr_region = env_vars.get("region")
    account_id = env_vars.get("accountId")

    if not ecr_region or not account_id:
        logging.error("'region' or 'accountId' not found in device.env. Aborting job.")
        return False, "'region' or 'accountId' not found in device.env. Aborting job."

    ecr_repo = f"{account_id}.dkr.ecr.{ecr_region}.amazonaws.com"
    image_name = f"{ecr_repo}/{DOCKER_IMAGE}:{version}"

    # Get temporary credentials for AWS ECR access
    credentials = get_temporary_credentials()
    if not credentials:
        logging.error("Failed to retrieve temporary credentials. Aborting job.")
        return False, "Failed to retrieve temporary credentials. Aborting job."

    # Initialize boto3 client to interact with ECR
    try:
        ecr_client = boto3.client(
            'ecr',
            region_name=ecr_region,
            aws_access_key_id=credentials['aws_access_key_id'],
            aws_secret_access_key=credentials['aws_secret_access_key'],
            aws_session_token=credentials['aws_session_token']
        )
        logging.info("Successfully initialized ECR client.")
        
        # Get the ECR authorization token
        response = ecr_client.get_authorization_token()
        auth_data = response['authorizationData'][0]
        token = base64.b64decode(auth_data['authorizationToken']).decode('utf-8')
        username, password = token.split(':')

    except Exception as e:
        logging.error(f"Failed to obtain Docker login credentials from ECR: {e}")
        return False, f"Failed to obtain Docker login credentials from ECR: {e}"

    # Initialize Docker client
    client = docker.from_env()

    # Authenticate Docker with AWS ECR using Docker SDK
    try:
        client.login(username=username, password=password, registry=ecr_repo)
        logging.info(f"Successfully logged in to ECR: {ecr_repo}")
    except docker.errors.APIError as e:
        logging.error(f"Failed to log in to ECR: {str(e)}")
        return False, f"Failed to log in to ECR: {str(e)}"

    # Pull the Docker image from the ECR repository
    try:
        client.images.pull(image_name)
        logging.info(f"Successfully pulled Docker image {image_name}")

        # Retag the Docker image from the ECR repository
        image = client.images.get(image_name)
        image.tag(f"{DOCKER_IMAGE}:{version}")
        logging.info(f"Successfully retagged Docker image {image_name}")
    except docker.errors.APIError as e:
        logging.error(f"Failed to pull Docker image: {str(e)}")
        return False, f"Failed to pull Docker image: {str(e)}"
    except docker.errors.ImageNotFound as e:
        logging.error(f"Image {image_name} not found: {str(e)}")
        return False, f"Image {image_name} not found: {str(e)}"

    # Verify that the Docker image has been successfully pulled or already exists
    try:
        client.images.get(f"{DOCKER_IMAGE}:{version}")
        logging.info(f"Docker image {DOCKER_IMAGE}:{version} already exists locally or has been updated successfully.")
    except docker.errors.ImageNotFound:
        logging.error(f"Error: Docker image {DOCKER_IMAGE}:{version} not found after pull.")
        return False, f"Error: Docker image {DOCKER_IMAGE}:{version} not found after pull."

    # Update the device.env file with the new firmware version
    env_update_success, env_update_message = update_device_env(version)
    if not env_update_success:
        logging.error(f"Failed to update device environment: {env_update_message}")
        return False, env_update_message

    # Optionally remove old Docker images to free up space
    if deleteOldImages:
        try:
            images = client.images.list()
            for img in images:
                if DOCKER_IMAGE in img.tags and f":{version}" not in img.tags[0]:
                    client.images.remove(image=img.id, force=True)
                    logging.info(f"Old Docker image {img.tags[0]} removed.")
        except docker.errors.APIError as e:
            logging.error(f"Failed to remove old Docker images: {str(e)}")

    return True, "Firmware update completed successfully."

# Function to download a file from an S3 bucket
# Uses boto3 to download files and handles potential errors explicitly
def download_file_from_s3(s3_client, file_key, local_path):
    try:
        s3_client.download_file(BUCKET_NAME, file_key, str(local_path))
        logging.info(f"Downloaded {file_key} to {local_path}")
        return True
    except s3_client.exceptions.NoSuchKey:
        logging.error(f"Error: The object {file_key} does not exist in bucket {BUCKET_NAME}.")
    except Exception as e:
        logging.error(f"Failed to download {file_key} from S3: {e}")
    return False

# Function to handle adding configurations, including downloading necessary files and generating environment configs
def handle_add_configs(robokits, sensekits):
    credentials = get_temporary_credentials()
    if not credentials:
        return False, "Failed to retrieve temporary credentials. Aborting."
    
    # Load environment variables and create an S3 client
    env_vars = load_env_vars()
    ecr_region = env_vars.get("region")

    try:
        s3_client = boto3.client(
            's3',
            region_name=ecr_region,
            aws_access_key_id=credentials["aws_access_key_id"],
            aws_secret_access_key=credentials["aws_secret_access_key"],
            aws_session_token=credentials["aws_session_token"]
        )
    except Exception as e:
        logging.error(f"Failed to initialize S3 client: {e}")
        return False, "Failed to initialize S3 client."

    # Ensure required directories exist
    for directory in [FIRMWARE_CONFIG_DIR / "robokit", FIRMWARE_CONFIG_DIR / "sensekit", EXTEND_AUTOSTART_DIR / "robokit", EXTEND_AUTOSTART_DIR / "sensekit"]:
        directory.mkdir(parents=True, exist_ok=True)

    # Download critical scripts required for configuration
    if not download_file_from_s3(s3_client, "customer/terminal_roscore.bash", EXTEND_AUTOSTART_DIR / "terminal_roscore.bash"):
        return False, "Failed to download terminal_roscore.bash."
    if not download_file_from_s3(s3_client, "customer/firmware_launcher.bash", EXTEND_AUTOSTART_DIR / "firmware_launcher.bash"):
        return False, "Failed to download firmware_launcher.bash."

    downloaded_types = set()  # Track already downloaded types to avoid redundant downloads
    launcher_commands = []  # Commands to be added to firmware_launcher.bash

    # Function to write environment variables to a file for a given device
    def write_env_file(directory, filename, data, device_type):
        file_path = directory / filename
        try:
            with file_path.open('w') as file:
                file.write(f"export deviceType={device_type}\n")
                for key, value in data.items():
                    file.write(f"export {key}={value if value is not None else ''}\n")
            logging.info(f"Configuration written to {file_path}")
        except Exception as e:
            logging.error(f"Failed to write environment file {file_path}: {e}")
            return False
        return True

    # Function to process configuration for either robokit or sensekit
    def process_kit(kit, kit_type):
        try:
            ros_port = kit.get("rosPort")
            if ros_port is None:
                logging.error(f"Error: rosPort is required for {kit_type} configuration")
                return False

            # Generate environment file for the given kit
            filename = f"{ros_port}.env"
            if not write_env_file(FIRMWARE_CONFIG_DIR / kit_type, filename, kit, kit_type):
                return False

            # Download specific terminal script if not already downloaded
            kit_specific_type = kit.get(f"{kit_type}Type")
            if kit_specific_type and kit_specific_type not in downloaded_types:
                s3_key = f"customer/terminal_{kit_specific_type.lower()}.bash"
                local_path = EXTEND_AUTOSTART_DIR / kit_type / f"terminal_{kit_specific_type.lower()}.bash"
                if not download_file_from_s3(s3_client, s3_key, local_path):
                    return False
                downloaded_types.add(kit_specific_type)

                # Special handling for Universal Robots
                if kit_type == "robokit" and "ur" not in downloaded_types and kit_specific_type.lower().startswith("ur"):
                    ur_key = "customer/terminal_ur.bash"
                    ur_local_path = EXTEND_AUTOSTART_DIR / kit_type / "terminal_ur.bash"
                    if not download_file_from_s3(s3_client, ur_key, ur_local_path):
                        return False
                    downloaded_types.add("ur")

            # Append the necessary command to launcher_commands
            launcher_commands.append(
                f"(source ${{HOME}}/firmware_configs/{kit_type}/{ros_port}.env && bash /home/extend/extend_autostart/{kit_type}/terminal_{kit_specific_type.lower()}.bash)&"
            )
        except Exception as e:
            logging.error(f"Failed to process {kit_type} configuration: {e}")
            return False
        return True

    # Process configurations for all robokits and sensekits
    for robokit in robokits:
        if not process_kit(robokit, 'robokit'):
            return False, f"Failed to process robokit configuration."

    for sensekit in sensekits:
        if not process_kit(sensekit, 'sensekit'):
            return False, f"Failed to process sensekit configuration."

    # Append generated commands to firmware_launcher.bash
    try:
        with (EXTEND_AUTOSTART_DIR / "firmware_launcher.bash").open("a") as launcher_file:
            launcher_file.write("\n\n" + "\n\n".join(launcher_commands) + "\n")
        (EXTEND_AUTOSTART_DIR / "firmware_launcher.bash").chmod(0o755)
        logging.info("firmware_launcher.bash has been updated and made executable.")
    except Exception as e:
        logging.error(f"Failed to update firmware_launcher.bash: {e}")
        return False, "Failed to update firmware_launcher.bash."

    return True, "Configurations added successfully."

# Function to handle running a command provided in the job document
def handle_run_command(command):
    if command:
        # Pass command to `run_command` and specify that shell should be used for redirection
        run_success, run_output = run_command(command.split(), use_shell=True)
        if run_success:
            return True, "Command executed successfully."
        else:
            return False, f"Command failed: {run_output}"
    else:
        logging.error("No command specified.")
        return False, "No command specified."

# Main function to execute a job, which may consist of multiple steps
def run_job(job_id, job_document):
    try:
        # Manage the log file size before starting the job
        manage_log_file()

        logging.info(f"Executing job {job_id} with document: {job_document}")
        steps = job_document.get("steps", [])
        reboot_after_job = job_document.get("rebootAfter", False)

        # Iterate through each step in the job document
        for step in steps:
            action = step.get("action")

            if action == Actions.UPDATE_FIRMWARE.value:
                version = step.get("parameters", {}).get("firmwareVersion")
                deleteOldImages = step.get("parameters", {}).get("deleteOldImages")
                success, message = handle_update_firmware(version, deleteOldImages)
                if not success:
                    return False, message

            elif action == Actions.ADD_CONFIGS.value:
                # Extract robokits and sensekits from parameters in the step
                parameters = step.get("parameters", {})
                robokits = parameters.get("robokits", [])
                sensekits = parameters.get("sensekits", [])
                # Call add_configs with robokits and sensekits
                success, message = handle_add_configs(robokits, sensekits)
                if not success:
                    return False, message

            elif action == Actions.RUN_COMMAND.value:
                command = step.get("parameters", {}).get("command")
                success, message = handle_run_command(command)
                if not success:
                    return False, message

            else:
                return False, f"Unknown action: {action}"

        # Schedule a reboot if specified in the job document
        if reboot_after_job:
            logging.info("Job complete. Scheduling device to restart in 15 seconds.")
            subprocess.Popen(["nohup", "sh", "-c", "'sleep 15; shutdown -r now'"], shell=False)
            time.sleep(1)
            return True, f"Job executed successfully. {message}. Your device will reboot in the next 30 seconds."


    except Exception as e:
        logging.error(f"Job execution failed: {e}")
        return False, f"Job execution failed: {e}"
    
    return True, f"Job executed successfully. {message}. You may require a reboot to see changes."
