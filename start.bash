#!/usr/bin/env bash
# stop script on error
set -e

# Check for python 3
if ! python3 --version &> /dev/null; then
  printf "\nERROR: python3 must be installed.\n"
  exit 1
fi

# Check to see if root CA file exists, download if not
if [ ! -f $HOME/.iot_kit/root-CA.crt ]; then
  printf "\nDownloading AWS IoT Root CA certificate from AWS...\n"
  curl https://www.amazontrust.com/repository/AmazonRootCA1.pem > $HOME/.iot_kit/root-CA.crt
fi

# Clone or pull the latest changes from Extend-Robotics/er_iot_manager repository
if [ ! -d $HOME/er_iot_manager ]; then
  printf "\nCloning the Extend-Robotics er_iot_manager repository...\n"
  git clone https://github.com/Extend-Robotics/er_iot_manager.git $HOME/er_iot_manager --recursive
else
  printf "\nPulling the latest changes from the er_iot_manager repository...\n"
  cd $HOME/er_iot_manager
  git pull origin master
  cd $HOME
fi

# Run the setup script to install required dependencies using setup.py
printf "\nRunning setup.py to install dependencies for er_iot_manager...\n"
python3 -m pip install $HOME/er_iot_manager

source $HOME/.iot_kit/device.env

# RUn the connection and jobs python scripts
printf "\nRunning IoT manager application...\n"
python3 $HOME/er_iot_manager/connection.py \
        --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com \
        --key $HOME/.iot_kit/$thingName.private.key \
        --cert $HOME/.iot_kit/$thingName.cert.pem \
        --thing_name $thingName \
        --ca_file $HOME/.iot_kit/root-CA.crt > $HOME/.iot_kit/connection.log 2>&1 &

python3 $HOME/er_iot_manager/jobs.py \
        --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com \
        --key $HOME/.iot_kit/$thingName.private.key \
        --cert $HOME/.iot_kit/$thingName.cert.pem \
        --thing_name $thingName \
        --ca_file $HOME/.iot_kit/root-CA.crt > $HOME/.iot_kit/jobs.log 2>&1 &

wait
