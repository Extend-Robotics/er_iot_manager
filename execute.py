import subprocess
import assumeRole
import time
import os
import boto3
from enum import Enum

ECR_REGION = "eu-west-2"
ECR_REPO = f"031532483464.dkr.ecr.{ECR_REGION}.amazonaws.com"
DOCKER_IMAGE = "extend/cortex"
BUCKET_NAME = "er-command-center"


class Actions(Enum):
    UPDATE_FIRMWARE = 'UPDATE_FIRMWARE'
    ADD_CONFIGS = 'ADD_CONFIGS'
    RUN_COMMAND = 'RUN_COMMAND'


def update_device_env(new_version):
    try:
        # Dictionary to store environment variables
        env_vars = {}
        
        # Get the file path
        base_dir = os.path.expanduser("~")
        file_path = os.path.join(base_dir, ".iot_kit", "device.env")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"device.env file not found in {file_path}")

        # Read the file and update the firmwareVersion
        with open(file_path, 'r') as file:
            for line in file:
                # Strip whitespace and newline characters
                line = line.strip()
                if line.startswith("export ") and '=' in line:
                    # Remove 'export ' and split into key-value
                    key, value = line.replace("export ", "").split('=', 1)
                    # Check if the key is the firmwareVersion and update it
                    if key == "firmwareVersion":
                        env_vars[key] = new_version
                    else:
                        env_vars[key] = value

        # Write the updated environment variables back to the file
        with open(file_path, 'w') as file:
            for key, value in env_vars.items():
                file.write(f"export {key}={value}\n")

        return True

    except Exception as e:
        print(f"Error setting device.env file: {e}")
        return False


def handle_update_firmware(version, ecr_region, ecr_repo, docker_image):
    """Handles the firmware update action."""
    if not version:
        print("Firmware version not specified.")
        return False

    # Get temporary credentials and configure AWS CLI
    credentials = assumeRole.get_temporary_credentials()
    if not credentials:
        print("Failed to retrieve temporary credentials. Aborting job.")
        return False

    # Authenticate Docker to ECR
    login_command = (
        f"aws ecr get-login-password --region {ecr_region} | "
        f"docker login --username AWS --password-stdin {ecr_repo}"
    )
    login_result = subprocess.run(login_command, shell=True, capture_output=True, text=True)
    if login_result.returncode != 0:
        print(f"Failed to log in to ECR: {login_result.stderr}")
        return False

    # Pull the Docker image
    image_tag = f"{ecr_repo}/{docker_image}:{version}"
    print(f"Pulling Docker image: {image_tag}")
    pull_command = f"docker pull {image_tag}"
    pull_result = subprocess.run(pull_command, shell=True, capture_output=True, text=True)
    if pull_result.returncode != 0:
        print(f"Failed to pull Docker image: {pull_result.stderr}")
        return False

    # Verify the Docker image
    if subprocess.run(f"docker images -q {docker_image}:{version}", shell=True).returncode != 0:
        print(f"Error: Docker image {docker_image}:{version} not found after pull.")
        return False
    
    # Update the device.env
    update_device_env(version)

    # Cleanup: remove old images
    cleanup_command = (
        f"docker images --format '{{{{.ID}}}} {{{{.Repository}}}}:{{{{.Tag}}}}' | "
        f"grep -v '{docker_image}:{version}' | awk '{{print $1}}' | xargs -r docker rmi -f"
    )
    subprocess.run(cleanup_command, shell=True)
    print("Old Docker images removed.")

    # Logout from ECR for security
    logout_command = f"docker logout {ecr_repo}"
    subprocess.run(logout_command, shell=True)
    print("Logged out of ECR.")

    print("Firmware update completed successfully.")
    return True
   

def download_file_from_s3(s3_client, file_key, local_path):
    """Downloads a file from S3 and saves it to the specified local path."""
    try:
        s3_client.download_file(BUCKET_NAME, file_key, local_path)
        print(f"Downloaded {file_key} to {local_path}")
    except Exception as e:
        print(f"Failed to download {file_key} from S3: {e}")


def handle_add_configs(robokits, sensekits):
    """Creates environment configuration files for each robokit and sensekit, downloads required scripts, and updates firmware_launcher.bash."""

    # Retrieve temporary credentials
    credentials = assumeRole.get_temporary_credentials()
    if not credentials:
        print("Failed to retrieve temporary credentials. Aborting.")
        return False

    # Initialize S3 client with temporary credentials
    s3_client = boto3.client(
        's3',
        region_name=ECR_REGION,
        aws_access_key_id=credentials["aws_access_key_id"],
        aws_secret_access_key=credentials["aws_secret_access_key"],
        aws_session_token=credentials["aws_session_token"]
    )

    # Set base directories for testing and actual implementation
    # Uncomment the following line for actual implementation
    base_dir = os.path.expanduser("~")  # Use $HOME directory
    # base_dir = "."  # Current directory for testing

    # Ensure base directories exist
    os.makedirs(f"{base_dir}/firmware_configs/robokit", exist_ok=True)
    os.makedirs(f"{base_dir}/firmware_configs/sensekit", exist_ok=True)
    os.makedirs(f"{base_dir}/extend_autostart/robokit", exist_ok=True)
    os.makedirs(f"{base_dir}/extend_autostart/sensekit", exist_ok=True)

    # Download terminal_roscore.bash and firmware_launcher.bash
    download_file_from_s3(s3_client, "customer/terminal_roscore.bash", f"{base_dir}/extend_autostart/terminal_roscore.bash")
    download_file_from_s3(s3_client, "customer/firmware_launcher.bash", f"{base_dir}/extend_autostart/firmware_launcher.bash")

    # Keep track of downloaded types to avoid redundant downloads
    downloaded_types = set()

    # Helper function to write environment files
    def write_env_file(directory, filename, data, deviceType):
        file_path = os.path.join(directory, filename)
        with open(file_path, 'w') as file:
            file.write(f"export deviceType={deviceType}\n")
            for key, value in data.items():
                file.write(f"export {key}={value if value is not None else ''}\n")
        print(f"Configuration written to {file_path}")

    # Prepare lines to append to firmware_launcher.bash
    launcher_commands = []

    # Process each robokit
    for robokit in robokits:
        ros_port = robokit.get("rosPort")
        if ros_port is None:
            print("Error: rosPort is required for robokit configuration")
            continue

        # Generate the environment file for each robokit
        filename = f"{ros_port}.env"
        write_env_file(f"{base_dir}/firmware_configs/robokit", filename, robokit, 'robokit')

        # Download the terminal script for this robokit type
        robokit_type = robokit.get("robokitType")
        if robokit_type and robokit_type not in downloaded_types:
            # Define S3 file key and local path
            s3_key = f"customer/terminal_{robokit_type}.bash"
            local_path = f"{base_dir}/extend_autostart/robokit/terminal_{robokit_type.lower()}.bash"

            # Download from S3
            download_file_from_s3(s3_client, s3_key, local_path)
            downloaded_types.add(robokit_type)  # Mark this type as downloaded

        # Append the launcher command for this robokit to firmware_launcher.bash
        launcher_commands.append(
            f"(source ${{HOME}}/firmware_configs/robokit/{ros_port}.env && bash /home/extend/extend_autostart/robokit/terminal_{robokit_type.lower()}.bash)&"
        )

    # Process each sensekit
    for sensekit in sensekits:
        ros_port = sensekit.get("rosPort")
        if ros_port is None:
            print("Error: rosPort is required for sensekit configuration")
            continue

        # Generate the environment file for each sensekit
        filename = f"{ros_port}.env"
        write_env_file(f"{base_dir}/firmware_configs/sensekit", filename, sensekit, 'sensekit')

        # Download the terminal script for this sensekit type
        sensekit_type = sensekit.get("sensekitType")
        if sensekit_type and sensekit_type not in downloaded_types:
            # Define S3 file key and local path
            s3_key = f"customer/terminal_{sensekit_type}.bash"
            local_path = f"{base_dir}/extend_autostart/sensekit/terminal_{sensekit_type.lower()}.bash"

            # Download from S3
            download_file_from_s3(s3_client, s3_key, local_path)
            downloaded_types.add(sensekit_type)  # Mark this type as downloaded

        # Append the launcher command for this sensekit to firmware_launcher.bash
        launcher_commands.append(
            f"(source ${{HOME}}/firmware_configs/sensekit/{ros_port}.env && bash /home/extend/extend_autostart/sensekit/terminal_{sensekit_type.lower()}.bash)&"
        )

    # Append commands to firmware_launcher.bash
    with open(f"{base_dir}/extend_autostart/firmware_launcher.bash", "a") as launcher_file:
        launcher_file.write("\n\n".join(launcher_commands) + "\n")

    # Make firmware_launcher.bash executable
    os.chmod(f"{base_dir}/extend_autostart/firmware_launcher.bash", 0o755)
    print("firmware_launcher.bash has been updated and made executable.")

    return True


def handle_run_command(command):
    """Handles the runCommand action."""
    if command:
        print(f"Executing command: {command}")
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Command failed with error: {result.stderr}")
            return False
        print("Command executed successfully.")
        return True
    else:
        print("No command specified.")
        return False


def run_job(job_id, job_document):
    """Executes job actions based on job document steps."""
    try:
        print(f"Executing job {job_id} with document: {job_document}")
        
        # Extract parameters from the job document
        steps = job_document.get("steps", [])
        reboot_after_job = job_document.get("rebootAfter", False)

        for step in steps:
            action = step.get("action")

            if action == Actions.UPDATE_FIRMWARE.value:
                version = step.get("parameters", {}).get("firmwareVersion")
                if not handle_update_firmware(version, ECR_REGION, ECR_REPO, DOCKER_IMAGE):
                    return False
                
            elif action == Actions.ADD_CONFIGS.value:
                # Extract robokits and sensekits from parameters in the step
                parameters = step.get("parameters", {})
                robokits = parameters.get("robokits", [])
                sensekits = parameters.get("sensekits", [])
                
                # Call add_configs with robokits and sensekits
                if not handle_add_configs(robokits, sensekits):
                    return False
                
            elif action == Actions.RUN_COMMAND.value:
                command = step.get("parameters", {}).get("command")
                if not handle_run_command(command):
                    return False
                
            else:
                print(f"Unknown action: {action}")
                return False

        # Schedule a reboot if rebootAfter is set to true
        if reboot_after_job:
            print("Job complete. Scheduling device to restart in 15 seconds.")
            subprocess.Popen("nohup shutdown -r +0.25 &", shell=True)
            time.sleep(1)  # Optional: wait a moment for scheduling to ensure stability

    except Exception as e:
        print(f"Job execution failed: {e}")
        return False
    
    return True
