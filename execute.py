import subprocess
import assumeRole
import time
import os
import boto3
import logging
from pathlib import Path
from enum import Enum

# Constants for frequently used paths and configuration values
DOCKER_IMAGE = "extend/cortex"
BUCKET_NAME = "er-command-center"
BASE_DIR = Path.home()
FIRMWARE_CONFIG_DIR = BASE_DIR / "firmware_configs"
EXTEND_AUTOSTART_DIR = BASE_DIR / "extend_autostart"
IOT_KIT_DIR = BASE_DIR / ".iot_kit"
DEVICE_ENV_FILE = IOT_KIT_DIR / "device.env"
JOBS_LOG_FILE = IOT_KIT_DIR / "jobs.log"

# Enum for different job actions to make action type handling more readable
class Actions(Enum):
    UPDATE_FIRMWARE = 'UPDATE_FIRMWARE'
    ADD_CONFIGS = 'ADD_CONFIGS'
    RUN_COMMAND = 'RUN_COMMAND'

# Configure logging to output to a file with detailed information, including timestamps
logging.basicConfig(
    filename=JOBS_LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

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
def run_command(command_list, description=""):
    try:
        result = subprocess.run(command_list, capture_output=True, text=True, check=True)
        logging.info(f"{description} - Command output: {result.stdout.strip()}")
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"{description} - Command failed with error: {e.stderr.strip()}")
        return False, e.stderr.strip()

# Function to handle the firmware update process, including Docker operations
# This includes logging in to Docker, pulling images, and cleaning up old images if necessary
def handle_update_firmware(version, deleteOldImages):
    if not version:
        return False, "Firmware version not specified."

    # Load necessary environment variables
    env_vars = load_env_vars()
    ecr_region = env_vars.get("region")
    account_id = env_vars.get("accountId")

    if not ecr_region or not account_id:
        return False, "'region' or 'accountId' not found in device.env. Aborting job."

    ecr_repo = f"{account_id}.dkr.ecr.{ecr_region}.amazonaws.com"

    # Get temporary credentials for AWS ECR access
    credentials = assumeRole.get_temporary_credentials()
    if not credentials:
        return False, "Failed to retrieve temporary credentials. Aborting job."

    # Authenticate Docker with AWS ECR by piping the AWS login password to Docker login
    try:
        # Step 1: Get the Docker login password from AWS ECR
        login_password_command = [
            "aws", "ecr", "get-login-password", "--region", ecr_region
        ]
        login_password_process = subprocess.run(login_password_command, capture_output=True, text=True, check=True)
        login_password = login_password_process.stdout.strip()

        # Step 2: Use the retrieved password to log in to Docker
        docker_login_command = [
            "docker", "login", "--username", "AWS", "--password-stdin", ecr_repo
        ]
        login_process = subprocess.Popen(docker_login_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = login_process.communicate(input=login_password)
        if login_process.returncode != 0:
            logging.error(f"Failed to log in to ECR: {stderr.strip()}")
            return False, f"Failed to log in to ECR: {stderr.strip()}"
        else:
            logging.info(f"Successfully logged in to ECR: {ecr_repo}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Error getting Docker login password: {e.stderr.strip()}")
        return False, f"Error getting Docker login password: {e.stderr.strip()}"
    except Exception as e:
        logging.error(f"Error during Docker login: {e}")
        return False, f"Error during Docker login: {e}"
    
    # Pull the Docker image from the ECR repository
    pull_command = [
        "docker", "pull", f"{ecr_repo}/{DOCKER_IMAGE}:{version}"
    ]
    pull_success, pull_output = run_command(pull_command, "Pull Docker image")
    if not pull_success:
        return False, f"Failed to pull Docker image: {pull_output}"

    # Verify that the Docker image has been successfully pulled
    verify_command = [
        "docker", "images", "-q", f"{DOCKER_IMAGE}:{version}"
    ]
    verify_success, verify_output = run_command(verify_command, "Verify Docker image")
    if not verify_output.strip():
        return False, f"Error: Docker image {DOCKER_IMAGE}:{version} not found after pull."

    # Update the device.env file with the new firmware version
    env_update_success, env_update_message = update_device_env(version)
    if not env_update_success:
        return False, env_update_message

    # Optionally remove old Docker images to free up space
    if deleteOldImages:
        cleanup_command = [
            "docker", "images", "--format", "{{.ID}} {{.Repository}}:{{.Tag}}"
        ]
        cleanup_success, cleanup_output = run_command(cleanup_command, "List Docker images")
        if cleanup_success:
            images = [line.split()[0] for line in cleanup_output.splitlines() if f"{DOCKER_IMAGE}:{version}" not in line]
            if images:
                remove_command = ["docker", "rmi", "-f"] + images
                remove_success, remove_output = run_command(remove_command, "Remove old Docker images")
                if not remove_success:
                    logging.error(f"Failed to remove old Docker images: {remove_output}")
                else:
                    logging.info("Old Docker images removed.")

    # Logout from AWS ECR to end the session
    logout_command = ["docker", "logout", ecr_repo]
    logout_success, logout_output = run_command(logout_command, "Logout from ECR")
    if not logout_success:
        logging.error(f"Failed to log out of ECR: {logout_output}")
    else:
        logging.info("Logged out of ECR.")

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
    credentials = assumeRole.get_temporary_credentials()
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
            launcher_file.write("\n\n".join(launcher_commands) + "\n")
        (EXTEND_AUTOSTART_DIR / "firmware_launcher.bash").chmod(0o755)
        logging.info("firmware_launcher.bash has been updated and made executable.")
    except Exception as e:
        logging.error(f"Failed to update firmware_launcher.bash: {e}")
        return False, "Failed to update firmware_launcher.bash."

    return True, "Configurations added successfully."

# Function to handle running a command provided in the job document
def handle_run_command(command):
    if command:
        run_success, run_output = run_command(command.split(), "Executing provided command")
        if run_success:
            return True, "Command executed successfully."
        else:
            return False, f"Command failed: {run_output}"
    else:
        return False, "No command specified."

# Main function to execute a job, which may consist of multiple steps
def run_job(job_id, job_document):
    try:
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
