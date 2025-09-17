# FT-CAN Project

A Python-based application for CAN bus data acquisition and visualization using ZMQ messaging.

## Features

- Sends Remote Transmission Request (RTR) messages to CAN bus devices
- Processes and publishes CAN data using ZMQ
- Real-time visualization dashboard with Dash/Plotly
- Configurable data smoothing options
- Dynamic RTR frequency control

## Components

- `app.py`: Data visualization dashboard with Dash/Plotly
- `async_pub.py`: CAN bus RTR message publisher using asyncio and ZMQ
- `async_sub.py`: Simple ZMQ subscriber for testing
- `utils.py`: Shared utility functions
- `config.yaml`: Configuration for CAN IDs and RTR messages
- `Makefile`: Build and run commands

## Usage

```bash
# Set up the conda environment
make env

# Run the CAN data publisher
make run-pub

# Run the visualization dashboard
make run-app
```

## Created

Initial version created on September 17, 2025.