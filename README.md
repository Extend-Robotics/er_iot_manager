<div align="center">
  <img src="https://static.wixstatic.com/media/93e6e0_ce911b86bbb34e35ae42e8259ad0c389~mv2.png/v1/fill/w_351,h_133,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/White%20on%20Transparent.png" alt="Logo" />
</div>

# ER IoT Manager

The ER IoT Manager is a Python-based host device management solution leveraging AWS IoT Core for seamless communication with Cortex devices and the ER Command Center. It provides an integrated environment to monitor, configure, and manage device settings using HTTP requests and MQTT messaging. This module is essential for maintaining device configurations and executing various jobs such as running commands, updating firmware, and adding configurations.

## Features

- Real-time Communication: Utilizes MQTT messaging for instant updates and actions.
- Flexible Configuration Management: Enables dynamic updates to Cortex devices via customizable job templates.
- Comprehensive Monitoring: Continuously observes the state of devices and the Command Center.
- Integration with AWS IoT Core: Simplifies device connection and management through robust cloud capabilities.

## Prerequisites

- Python 3.8+
- AWS IoT Certificates & Keys
- Install dependencies listed in setup.py.

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Extend-Robotics/er_iot_manager.git
cd Extend-Robotics-er_iot_manager
```
2. Configure .iot_kit/device.env with your device-specific credentials and AWS IoT Core details.
3. Run the application
```bash
./start.bash
```
## Contributing

Feel free to submit issues or pull requests for improvements and fixes. Make sure to follow the project's coding standards and run tests before submitting changes.
