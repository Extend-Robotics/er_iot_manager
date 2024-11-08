#!/usr/bin/env bash
# stop script on error
set -e

# Check for python 3
if ! python3 --version &> /dev/null; then
  printf "\nERROR: python3 must be installed.\n"
  exit 1
fi

# Check to see if root CA file exists, download if not
if [ ! -f ./root-CA.crt ]; then
  printf "\nDownloading AWS IoT Root CA certificate from AWS...\n"
  curl https://www.amazontrust.com/repository/AmazonRootCA1.pem > root-CA.crt
fi

# Clone or pull the latest changes from Extend-Robotics/er_iot_manager repository
if [ ! -d ./er_iot_manager ]; then
  printf "\nCloning the Extend-Robotics er_iot_manager repository...\n"
  git clone https://github.com/Extend-Robotics/er_iot_manager.git --recursive
else
  printf "\nPulling the latest changes from the er_iot_manager repository...\n"
  cd er_iot_manager
  git pull origin master
  cd ..
fi

# Run the setup script to install required dependencies using setup.py
printf "\nRunning setup.py to install dependencies for er_iot_manager...\n"
python3 -m pip install ./er_iot_manager

# run pub/sub sample app using certificates downloaded in package
printf "\nRunning IoT manager application...\n"
python3 er_iot_manager/connection.py \
        --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com \
        --key CortexQA.private.key \
        --cert CortexQA.cert.pem \
        --thing_name CortexQA \
        --ca_file root-CA.crt &

python3 er_iot_manager/jobs.py \
        --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com \
        --key CortexQA.private.key \
        --cert CortexQA.cert.pem \
        --thing_name CortexQA \
        --ca_file root-CA.crt &


