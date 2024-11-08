import requests
import subprocess
import os

# Replace with your endpoint, role alias, and certificate paths
credential_provider_endpoint = "https://c1yqqljqzvtfa.credentials.iot.eu-west-2.amazonaws.com"
role_alias = "ClientDevicesRoleAlias"

# Construct the URL to get temporary credentials
url = f"{credential_provider_endpoint}/role-aliases/{role_alias}/credentials"

def get_temporary_credentials():
    """Retrieves temporary credentials from AWS IoT Credential Provider and configures AWS CLI."""
    try:
        cert_path = os.getenv('CERT_FILE_PATH')
        key_path = os.getenv('PRIVATE_KEY_PATH')
        root_ca_path = os.getenv('ROOT_CA_PATH')

        response = requests.get(
            url,
            cert=(cert_path, key_path),
            verify=root_ca_path
        )
        
        if response.status_code == 200:
            credentials = response.json()["credentials"]
            
            # Configure AWS CLI with temporary credentials
            aws_access_key = credentials["accessKeyId"]
            aws_secret_key = credentials["secretAccessKey"]
            aws_session_token = credentials["sessionToken"]
            
            subprocess.run(f"aws configure set aws_access_key_id {aws_access_key}", shell=True)
            subprocess.run(f"aws configure set aws_secret_access_key {aws_secret_key}", shell=True)
            subprocess.run(f"aws configure set aws_session_token {aws_session_token}", shell=True)
            
            print("AWS CLI configured with temporary credentials.")
            
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

def clean_temporary_credentials():
    """Clean up AWS CLI credentials to avoid leaving them on the system"""
    try:
        subprocess.run("aws configure set aws_access_key_id ''", shell=True)
        subprocess.run("aws configure set aws_secret_access_key ''", shell=True)
        subprocess.run("aws configure set aws_session_token ''", shell=True)
    except Exception as e:
        print(f"Error cleaning credentials: {e}")
        return None
