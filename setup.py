from setuptools import setup, find_packages

setup(
    name="er_iot_manager",
    version="2.2.0",
    description="IoT device setup with AWS IoT SDK and boto3",
    packages=find_packages(),
    install_requires=[
        "urllib3>=1.26.0,<1.27",
        "pyyaml",
        "boto3",
        "awsiotsdk",
        "python-dotenv",
        "docker",
        "cryptography>=41.0.0",
    ],
    extras_require={
        "dev": [
            "black",
        ],
    },
    python_requires=">=3.8.10,<=3.10.18",
)
