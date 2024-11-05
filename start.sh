#!/usr/bin/env bash
# stop script on error
set -e

# Check to see if root CA file exists, download if not
if [ ! -f ./root-CA.crt ]; then
  printf "\nDownloading AWS IoT Root CA certificate from AWS...\n"
  curl https://www.amazontrust.com/repository/AmazonRootCA1.pem > root-CA.crt
fi

CWD=`pwd`

# install AWS Device SDK for NodeJS if not already installed + pubsub sample
if [ ! -d ./aws-iot-device-sdk-js-v2 ]; then
  printf "\nInstalling AWS SDK...\n"
  git clone https://github.com/aws/aws-iot-device-sdk-js-v2.git --recursive
  cd aws-iot-device-sdk-js-v2
  npm install
  # samples require their own install
  cd samples/node/pub_sub
  npm install
  cd $CWD
fi

# run pub/sub sample app using certificates downloaded in package
printf "\nRunning pub/sub sample application...\n"
#node aws-iot-device-sdk-js-v2/samples/node/pub_sub/dist/index.js --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com --key CortexQA.private.key --cert CortexQA.cert.pem --ca_file root-CA.crt --client_id sdk-nodejs-v2 --topic sdk/test/js
node er_iot_manager-main/dist/jobs/index.js --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com --key CortexQA.private.key --cert CortexQA.cert.pem --thing_name CortexQA --ca_file root-CA.crt
