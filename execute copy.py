import subprocess
import assumeRole
import time
import os
import boto3
from enum import Enum

DOCKER_IMAGE = "extend/cortex"
BUCKET_NAME = "er-command-center"
# device.env file path
base_dir = os.path.expanduser("~")
file_path = os.path.join(base_dir, ".iot_kit", "device.env")


class Actions(Enum):
    UPDATE_FIRMWARE = 'UPDATE_FIRMWARE'
    ADD_CONFIGS = 'ADD_CONFIGS'
    RUN_COMMAND = 'RUN_COMMAND'


def load_env_vars():
    """Loads environment variables from device.env."""
    try:
        # Dictionary to store environment variables
        env_vars = {}
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"device.env file not found in {file_path}")

        # Read the file and load variables into a dictionary
        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line.startswith("export ") and '=' in line:
                    key, value = line.replace("export ", "").split('=', 1)
                    env_vars[key] = value

        return env_vars

    except FileNotFoundError as e:
        print(f"Error loading device.env file: {e}")
    except Exception as e:
        print(f"Unexpected error while loading device.env file: {e}")
    return {}


def update_device_env(new_version):
    try:
        # Load the current environment variables from device.env
        env_vars = load_env_vars()

        # Update the firmwareVersion variable
        env_vars["firmwareVersion"] = new_version

        # Write the updated environment variables back to the file
        with open(file_path, 'w') as file:
            for key, value in env_vars.items():
                file.write(f"export {key}={value}\n")

        return True

    except FileNotFoundError as e:
        print(f"Error setting device.env file: {e}")
    except Exception as e:
        print(f"Unexpected error while setting device.env file: {e}")
    return False


def handle_update_firmware(version, deleteOldImages):
    """Handles the firmware update action."""
    if not version:
        print("Firmware version not specified.")
        return False

    # Load region and accountId from device.env
    env_vars = load_env_vars()
    ecr_region = env_vars.get("region")
    account_id = env_vars.get("accountId")

    if not ecr_region or not account_id:
        print("Error: 'region' or 'accountId' not found in device.env. Aborting job.")
        return False

    ecr_repo = f"{account_id}.dkr.ecr.{ecr_region}.amazonaws.com"

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
    image_tag = f"{ecr_repo}/{DOCKER_IMAGE}:{version}"
    print(f"Pulling Docker image: {image_tag}")
    pull_command = f"docker pull {image_tag}"
    pull_result = subprocess.run(pull_command, shell=True, capture_output=True, text=True)
    if pull_result.returncode != 0:
        print(f"Failed to pull Docker image: {pull_result.stderr}")
        return False

    # Verify the Docker image
    verify_command = f"docker images -q {DOCKER_IMAGE}:{version}"
    verify_result = subprocess.run(verify_command, shell=True, capture_output=True, text=True)
    if not verify_result.stdout.strip():
        print(f"Error: Docker image {DOCKER_IMAGE}:{version} not found after pull.")
        return False
    
    # Update the device.env
    if not update_device_env(version):
        print("Failed to update device.env with new firmware version.")
        return False
    
    if deleteOldImages:
        # Cleanup: remove old images
        cleanup_command = (
            "docker images --format '{{.ID}} {{.Repository}}:{{.Tag}}' | "
            f"grep -v \"$(printf '%s:%s' '{DOCKER_IMAGE}' '{version}')\" | "
            "awk '{print $1}' | "
            "xargs --no-run-if-empty docker rmi -f"
        )

        cleanup_result = subprocess.run(cleanup_command, shell=True, capture_output=True, text=True)
        if cleanup_result.returncode != 0:
            print(f"Failed to remove old Docker images: {cleanup_result.stderr}")
        else:
            print("Old Docker images removed.")

    # Logout from ECR for security
    logout_command = f"docker logout {ecr_repo}"
    logout_result = subprocess.run(logout_command, shell=True, capture_output=True, text=True)
    if logout_result.returncode != 0:
        print(f"Failed to log out of ECR: {logout_result.stderr}")
    else:
        print("Logged out of ECR.")

    print("Firmware update completed successfully.")
    return True
   

def download_file_from_s3(s3_client, file_key, local_path):
    """Downloads a file from S3 and saves it to the specified local path."""
    try:
        s3_client.download_file(BUCKET_NAME, file_key, local_path)
        print(f"Downloaded {file_key} to {local_path}")
        return True
    except s3_client.exceptions.NoSuchKey:
        print(f"Error: The object {file_key} does not exist in bucket {BUCKET_NAME}.")
    except Exception as e:
        print(f"Failed to download {file_key} from S3: {e}")
    return False


def handle_add_configs(robokits, sensekits):
    """Creates environment configuration files for each robokit and sensekit, downloads required scripts, and updates firmware_launcher.bash."""

    # Retrieve temporary credentials
    credentials = assumeRole.get_temporary_credentials()
    if not credentials:
        print("Failed to retrieve temporary credentials. Aborting.")
        return False
    
    env_vars = load_env_vars()
    ecr_region = env_vars.get("region")

    # Initialize S3 client with temporary credentials
    try:
        s3_client = boto3.client(
            's3',
            region_name=ecr_region,
            aws_access_key_id=credentials["aws_access_key_id"],
            aws_secret_access_key=credentials["aws_secret_access_key"],
            aws_session_token=credentials["aws_session_token"]
        )
    except Exception as e:
        print(f"Failed to initialize S3 client: {e}")
        return False

    try:
        os.makedirs(f"{base_dir}/firmware_configs/robokit", exist_ok=True)
        os.makedirs(f"{base_dir}/firmware_configs/sensekit", exist_ok=True)
        os.makedirs(f"{base_dir}/extend_autostart/robokit", exist_ok=True)
        os.makedirs(f"{base_dir}/extend_autostart/sensekit", exist_ok=True)
    except Exception as e:
        print(f"Failed to create required directories: {e}")
        return False

    # Download terminal_roscore.bash and firmware_launcher.bash
    if not download_file_from_s3(s3_client, "customer/terminal_roscore.bash", f"{base_dir}/extend_autostart/terminal_roscore.bash"):
        return False
    if not download_file_from_s3(s3_client, "customer/firmware_launcher.bash", f"{base_dir}/extend_autostart/firmware_launcher.bash"):
        return False

    # Keep track of downloaded types to avoid redundant downloads
    downloaded_types = set()

    # Helper function to write environment files
    def write_env_file(directory, filename, data, deviceType):
        file_path = os.path.join(directory, filename)
        try:
            with open(file_path, 'w') as file:
                file.write(f"export deviceType={deviceType}\n")
                for key, value in data.items():
                    file.write(f"export {key}={value if value is not None else ''}\n")
            print(f"Configuration written to {file_path}")
        except Exception as e:
            print(f"Failed to write environment file {file_path}: {e}")

    # Prepare lines to append to firmware_launcher.bash
    launcher_commands = []

    # # Process each robokit
    # for robokit in robokits:
    #     ros_port = robokit.get("rosPort")
    #     if ros_port is None:
    #         print("Error: rosPort is required for robokit configuration")
    #         continue

    #     # Generate the environment file for each robokit
    #     filename = f"{ros_port}.env"
    #     write_env_file(f"{base_dir}/firmware_configs/robokit", filename, robokit, 'robokit')

    #     # Download the terminal script for this robokit type
    #     robokit_type = robokit.get("robokitType")
    #     if robokit_type and robokit_type not in downloaded_types:
    #         # Define S3 file key and local path
    #         s3_key = f"customer/terminal_{robokit_type}.bash"
    #         local_path = f"{base_dir}/extend_autostart/robokit/terminal_{robokit_type.lower()}.bash"

    #         # Download from S3
    #         download_file_from_s3(s3_client, s3_key, local_path)
    #         downloaded_types.add(robokit_type)  # Mark this type as downloaded

    #         ### SPECIFIC ROBOKIT SETTINGS ###
    #         # Universal Robots
    #         if "ur" not in downloaded_types and robokit_type.lower().startswith("ur"):
    #             # Define S3 file key and local path
    #             s3_key = f"customer/terminal_ur.bash"
    #             local_path = f"{base_dir}/extend_autostart/robokit/terminal_ur.bash"

    #             # Download from S3
    #             download_file_from_s3(s3_client, s3_key, local_path)
    #             downloaded_types.add("ur")  # Mark this type as downloaded

    #     # Append the launcher command for this robokit to firmware_launcher.bash
    #     launcher_commands.append(
    #         f"(source ${{HOME}}/firmware_configs/robokit/{ros_port}.env && bash /home/extend/extend_autostart/robokit/terminal_{robokit_type.lower()}.bash)&"
    #     )

    # # Process each sensekit
    # for sensekit in sensekits:
    #     ros_port = sensekit.get("rosPort")
    #     if ros_port is None:
    #         print("Error: rosPort is required for sensekit configuration")
    #         continue

    #     # Generate the environment file for each sensekit
    #     filename = f"{ros_port}.env"
    #     write_env_file(f"{base_dir}/firmware_configs/sensekit", filename, sensekit, 'sensekit')

    #     # Download the terminal script for this sensekit type
    #     sensekit_type = sensekit.get("sensekitType")
    #     if sensekit_type and sensekit_type not in downloaded_types:
    #         # Define S3 file key and local path
    #         s3_key = f"customer/terminal_{sensekit_type}.bash"
    #         local_path = f"{base_dir}/extend_autostart/sensekit/terminal_{sensekit_type.lower()}.bash"

    #         # Download from S3
    #         download_file_from_s3(s3_client, s3_key, local_path)
    #         downloaded_types.add(sensekit_type)  # Mark this type as downloaded

    #     # Append the launcher command for this sensekit to firmware_launcher.bash
    #     launcher_commands.append(
    #         f"(source ${{HOME}}/firmware_configs/sensekit/{ros_port}.env && bash /home/extend/extend_autostart/sensekit/terminal_{sensekit_type.lower()}.bash)&"
    #     )

    def process_kit(kit, kit_type):
        """
        Processes each kit (either robokit or sensekit), generating environment files, downloading terminal scripts,
        and appending the launcher commands.
        """
        try:
            ros_port = kit.get("rosPort")
            if ros_port is None:
                print(f"Error: rosPort is required for {kit_type} configuration")
                return

            # Generate the environment file for this kit
            filename = f"{ros_port}.env"
            write_env_file(f"{base_dir}/firmware_configs/{kit_type}", filename, kit, kit_type)

            # Download the terminal script for this kit type
            kit_specific_type = kit.get(f"{kit_type}Type")
            if kit_specific_type and kit_specific_type not in downloaded_types:
                # Define S3 file key and local path for the specific kit type
                s3_key = f"customer/terminal_{kit_specific_type}.bash"
                local_path = f"{base_dir}/extend_autostart/{kit_type}/{kit_specific_type.lower()}.bash"
                
                # Download from S3
                if not download_file_from_s3(s3_client, s3_key, local_path):
                    return False
                downloaded_types.add(kit_specific_type)  # Mark this type as downloaded

                # Universal Robots special handling
                if (kit_type == "robokit") and ("ur" not in downloaded_types) and (kit_specific_type.lower().startswith("ur")):
                    s3_key = f"customer/terminal_ur.bash"
                    local_path = f"{base_dir}/extend_autostart/{kit_type}/terminal_ur.bash"
                    if not download_file_from_s3(s3_client, s3_key, local_path):
                        return False
                    downloaded_types.add("ur")  # Mark UR type as downloaded

            # Append the launcher command for this kit
            launcher_commands.append(
                f"(source ${{HOME}}/firmware_configs/{kit_type}/{ros_port}.env && bash /home/extend/extend_autostart/{kit_type}/terminal_{kit_specific_type.lower()}.bash)&"
            )
        except Exception as e:
            print(f"Failed to process {kit_type} configuration: {e}")
            return False

    # Process each robokit
    for robokit in robokits:
        if not process_kit(robokit, 'robokit'):
            return False

    # Process each sensekit
    for sensekit in sensekits:
        if not process_kit(sensekit, 'sensekit'):
            return False

    # Append commands to firmware_launcher.bash
    try:
        with open(f"{base_dir}/extend_autostart/firmware_launcher.bash", "a") as launcher_file:
            launcher_file.write("\n\n".join(launcher_commands) + "\n")
        # Make firmware_launcher.bash executable
        os.chmod(f"{base_dir}/extend_autostart/firmware_launcher.bash", 0o755)
        print("firmware_launcher.bash has been updated and made executable.")
    except Exception as e:
        print(f"Failed to update firmware_launcher.bash: {e}")
        return False

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
                deleteOldImages = step.get("parameters", {}).get("deleteOldImages")
                if not handle_update_firmware(version, deleteOldImages):
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
            subprocess.Popen("nohup sh -c 'sleep 15; shutdown -r now' &", shell=True)
            time.sleep(1)  # Optional: wait a moment for scheduling to ensure stability

    except Exception as e:
        print(f"Job execution failed: {e}")
        return False
    
    return True