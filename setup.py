from setuptools import setup, find_packages

setup(
    name="iot-device-setup",
    version="0.1",
    description="IoT device setup with AWS IoT SDK and boto3",
    packages=find_packages(),
    install_requires=[
        "boto3",
        "awsiotsdk"
    ],
    python_requires='>=3.6',
)
