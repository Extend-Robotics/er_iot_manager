import requests
import boto3

# Replace with your endpoint, role alias, and certificate paths
credential_provider_endpoint = "https://c1yqqljqzvtfa.credentials.iot.eu-west-2.amazonaws.com"
role_alias = "ClientDevicesRoleAlias"
cert_path = "CortexQA.cert.pem"
key_path = "CortexQA.private.key"
root_ca_path = "root-CA.crt"

# Construct the URL to get temporary credentials
url = f"{credential_provider_endpoint}/role-aliases/{role_alias}/credentials"

# Step 1: Retrieve temporary credentials from AWS IoT Credential Provider
def get_temporary_credentials():
    try:
        response = requests.get(
            url,
            cert=(cert_path, key_path),
            verify=root_ca_path
        )
        
        if response.status_code == 200:
            credentials = response.json()["credentials"]
            return {
                "aws_access_key_id": credentials["accessKeyId"],
                "aws_secret_access_key": credentials["secretAccessKey"],
                "aws_session_token": credentials["sessionToken"]
            }
        else:
            print("Failed to retrieve credentials:", response.text)
            return None
    except Exception as e:
        print(f"Error getting credentials: {e}")
        return None

# Step 2: Use the retrieved credentials to initialize boto3
def main():
    credentials = get_temporary_credentials()
    if credentials:
        print("Temporary credentials retrieved successfully.")
        print(credentials)
        
        # Step 3: Initialize boto3 client with temporary credentials
        client = boto3.client(
            's3',  # Example AWS service
            aws_access_key_id=credentials['aws_access_key_id'],
            aws_secret_access_key=credentials['aws_secret_access_key'],
            aws_session_token=credentials['aws_session_token'],
            region_name='us-west-2'  # Update to your preferred region
        )
        
        # Example boto3 operation
        response = client.list_buckets()
        print("S3 Buckets:", response.get('Buckets', []))
        
        # Optional: Save credentials to a file for reuse
        with open("aws_credentials.txt", "w") as f:
            f.write(f"AWS_ACCESS_KEY_ID={credentials['aws_access_key_id']}\n")
            f.write(f"AWS_SECRET_ACCESS_KEY={credentials['aws_secret_access_key']}\n")
            f.write(f"AWS_SESSION_TOKEN={credentials['aws_session_token']}\n")
        
        print("Credentials saved to aws_credentials.txt")
    else:
        print("Could not retrieve credentials.")

if __name__ == "__main__":
    main()
