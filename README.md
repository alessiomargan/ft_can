# FT-CAN Project

A Python-based application for CAN bus data acquisition and visualization using ZMQ messaging.

## Features

- Sends Remote Transmission Request (RTR) messages to CAN bus devices
- Processes and publishes CAN data using ZMQ
- Real-time visualization dashboard with Dash/Plotly
- Configurable data smoothing options
- Dynamic RTR frequency control

## Architecture

The application has been modularized into separate components:

### Core Components

- `async_sub.py`: Data collection backend - handles ZMQ subscription, data buffering, and CSV logging
- `dashboard.py`: Web-based visualization frontend with Dash/Plotly
- `shared_data.py`: Shared data structures and configuration between components
- `async_pub.py`: CAN bus RTR message publisher using asyncio and ZMQ
- `utils.py`: Shared utility functions
- `config.yaml`: Configuration for CAN IDs and RTR messages
- `run.py`: Runner script to start components individually or together

### Support Files

- `Makefile`: Build and run commands
- `conda_env.yml`: Conda environment specification

## Usage

### Quick Start (Recommended)

```bash
# Set up the conda environment
make env

# Run both data collection and dashboard together
python run.py both
```

### Individual Components

```bash
# Run only data collection (useful for headless data logging)
python run.py data

# Run only the dashboard (if data collection is already running)
python run.py dashboard

# Or run components manually:
python async_sub.py    # Data collection backend
python dashboard.py    # Web dashboard

# For simple testing/debugging (display messages only):
python async_sub.py --simple
```

### Traditional Make Commands

```bash
# Run the CAN data publisher
make run-pub

# Run the data collection backend
python async_sub.py

# Run the visualization dashboard
python dashboard.py
```

## Architecture Benefits

- **Separation of Concerns**: Data collection and visualization are independent
- **Scalability**: Can run data collection on one machine and dashboard on another
- **Modularity**: Easy to add new frontends or modify existing components
- **Shared State**: Clean interface for data sharing between components
- **Unified Backend**: `async_sub.py` serves as both a simple subscriber and full backend

## Migration Notes

- **`app.py` is deprecated**: Use `async_sub.py` instead for data collection
- **Backward compatibility**: Old `app.py` has been moved to `app_deprecated.py` for reference
- **Enhanced functionality**: `async_sub.py` now includes all backend features (data buffering, CSV logging, config publishing)

## Created

Initial version created on September 17, 2025.
Modularized architecture implemented on September 19, 2025.
