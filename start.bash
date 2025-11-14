#!/usr/bin/env bash
# stop script on error
set -e

LOG_FILE="/tmp/extend_iot_start.log"

# Redirect stdout and stderr through tee to log file and terminal
exec > >(tee -a "$LOG_FILE") 2>&1

# Wait for network to be available
printf "\nWaiting for network to be available...\n"
while ! ping -c 1 -W 1 8.8.8.8 &> /dev/null; do
  sleep 2
done
printf "\nNetwork is available. Proceeding...\n"

if ping -q -c1 -W1 google.com >/dev/null && command -v chronyc >/dev/null 2>&1; then
    while true; do
        refid=$(chronyc tracking | grep "Reference ID" | awk '{print $5}')
        leap=$(chronyc tracking | grep "Leap status" | awk '{print $4}')
        
        if [ "$refid" != "()" ] && [ "$leap" = "Normal" ]; then
            echo "Chrony is synchronized."
            break
        else
            echo "Waiting for chrony to synchronize..."
            sleep 0.5
        fi
    done
fi

# Check for python 3
if ! python3 --version &> /dev/null; then
  printf "\nERROR: python3 must be installed.\n"
  exit 1
fi

# Check for pip, install if missing (with version-specific bootstrap)
if ! python3 -m pip --version &> /dev/null; then
  PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  printf "\nInstalling pip for Python $PYTHON_VERSION...\n"
  
  if [ "$PYTHON_VERSION" = "3.8" ]; then
    curl -s https://bootstrap.pypa.io/pip/3.8/get-pip.py -o /tmp/get-pip.py
  else
    curl -s https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  fi
  
  python3 /tmp/get-pip.py --user
fi

# Install virtualenv to user directory if not already installed
if ! python3 -m pip show virtualenv &> /dev/null; then
    echo "Installing virtualenv..."
    python3 -m pip install virtualenv --user
else
    echo "virtualenv already installed."
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$HOME/.iot_kit/iot_manager_env" ]; then
    echo "Creating virtual environment..."
    python3 -m virtualenv $HOME/.iot_kit/iot_manager_env -p python3
else
    echo "Virtual environment already exists."
fi

# Activate it
echo "Activating virtual environment..."
source $HOME/.iot_kit/iot_manager_env/bin/activate

echo "Virtual environment ready!"

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
  git pull origin main
  git checkout main
  cd $HOME
fi

# Run the setup script to install required dependencies using setup.py
printf "\nRunning setup.py to install dependencies for er_iot_manager...\n"
pip install $HOME/er_iot_manager  # Uses venv's pip since it's activated

source $HOME/.iot_kit/device.env

# Run the connection and jobs python scripts
printf "\nRunning IoT manager application...\n"

# Define the base directory and connection script path
CONNECTION_SCRIPT_DIR="$HOME/er_iot_manager"
CONNECTION_SCRIPT="$CONNECTION_SCRIPT_DIR/connection.py"
CONNECTION_SCRIPT_PYC="$CONNECTION_SCRIPT_DIR/connection.pyc"

# Choose the correct script (source or compiled)
if [ -f "$CONNECTION_SCRIPT" ]; then
  SCRIPT_TO_RUN="$CONNECTION_SCRIPT"
else
  SCRIPT_TO_RUN="$CONNECTION_SCRIPT_PYC"
fi

# Run the chosen script
python3 "$SCRIPT_TO_RUN" \
  --endpoint a34wwkbw0n00uf-ats.iot.eu-west-2.amazonaws.com \
  --key "$HOME/.iot_kit/$thingName.private.key" \
  --cert "$HOME/.iot_kit/$thingName.cert.pem" \
  --thing_name "$thingName" \
  --ca_file "$HOME/.iot_kit/root-CA.crt"
