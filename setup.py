from setuptools import setup, find_packages

setup(
    name="er_iot_manager",
    version="3.9.2",
    description="IoT device setup with AWS IoT SDK and boto3",
    packages=find_packages(),
    install_requires=[
        "urllib3>=1.26.0,<1.27",
        "pyyaml",
        "boto3",
        # Pin awsiotsdk: 1.30.0 bumped its awscrt dependency to 0.34.1, and awscrt >=0.34 dropped
        # the cp38 glibc (manylinux) aarch64 wheel — leaving only musllinux. On Python 3.8 that
        # forces awscrt to compile from source (needs python3-dev + a toolchain clean Cortex
        # devices lack), which is why `start.bash` broke on a clean machine. 1.29.0 pins awscrt
        # 0.32.1, which still ships a cp38 aarch64 wheel (and a cp310 one, so this is safe on
        # JetPack 6 too). Unpin once the device runtime has moved to Python 3.10+.
        "awsiotsdk==1.29.0",
        "python-dotenv",
        "docker",
        "cryptography>=41.0.0",
        "pyopenssl>=22.0.0",
    ],
    extras_require={
        "dev": [
            "black",
        ],
    },
    python_requires=">=3.8.10,<3.11",
)
