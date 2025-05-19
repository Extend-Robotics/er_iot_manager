from setuptools import setup, find_packages

setup(
    name="er_iot_manager",
    version="2.1.12",
    description="IoT device setup with AWS IoT SDK and boto3",
    packages=find_packages(),
    install_requires=[
        "urllib3>=1.26.0,<1.27",
        "pyyaml",
        "boto3",
        "awsiotsdk",
        "python-dotenv",
        "docker",
    ],
    python_requires="==3.8.10",
)
