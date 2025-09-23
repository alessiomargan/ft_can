# FT-CAN Project

A Python-based application for CAN bus data acquisition and visualization using ZMQ messaging.

## Features

- Sends Remote Transmission Request (RTR) messages to CAN bus devices
- Processes and publishes CAN data using ZMQ
- Real-time visualization dashboard with Dash/Plotly
- Configurable data smoothing options
- Dynamic RTR frequency control
- Flexible data format configuration via YAML

## Architecture

The application has been modularized into separate components:

### Core Components

- `async_sub.py`: Data collection backend - handles ZMQ subscription, data buffering, and CSV logging
- `dashboard.py`: Web-based visualization frontend with Dash/Plotly
- `shared_data.py`: Shared data structures and configuration between components
- `async_pub.py`: CAN bus RTR message publisher using asyncio and ZMQ
- `utils.py`: Shared utility functions
- `config.yaml`: Configuration for CAN IDs, RTR messages, and data formats
- `run.py`: Runner script to start components individually or together

### Support Files

- `Makefile`: Build and run commands
- `conda_env.yml`: Conda environment specification

## Usage

### Environment Setup

```bash
# Set up the conda environment
make mk-conda-env
```

### Simulation Mode

You can enable simulation mode in the `config.yaml` file to test the system without actual CAN hardware:

```yaml
simulation_mode: true  # Set to true for simulation, false for real hardware
```

In simulation mode, the system will generate random data for all configured CAN IDs.

You can easily toggle simulation mode with the following commands:

```bash
# Enable simulation mode (no hardware needed)
make sim-on

# Disable simulation mode (use real hardware)
make sim-off
```

### Recommended Usage

```bash
# Option 1: Run both publisher and dashboard (most common use case)
make run-app-pub

# Option 2: Run complete system (publisher, data collector, dashboard)
make run
```

### Individual Components

```bash
# Start the publisher first (required for RTR controls to work)
make run-pub

# Then run the dashboard in a separate terminal
make run-app

# For data logging, run the backend
make run-backend

# Or use the run.py script:
python run.py both        # Run both data collection and dashboard
python run.py data        # Run only data collection
python run.py dashboard   # Run only the dashboard
```

### Traditional Make Commands

```bash
# Create conda environment
make mk-conda-env

# Run the complete system (publisher, backend, and dashboard)
make run

# Run just the publisher (for RTR requests)
make run-pub

# Run just the dashboard (after running the publisher)
make run-app

# Run both publisher and dashboard (most common use case)
make run-app-pub

# Run the data collection backend
make run-backend

# Kill specific components
make kill-pub   # Kill publisher
make kill-app   # Kill dashboard
make kill       # Kill everything
```

## Architecture Benefits

- **Separation of Concerns**: Data collection and visualization are independent
- **Scalability**: Can run data collection on one machine and dashboard on another
- **Modularity**: Easy to add new frontends or modify existing components
- **Shared State**: Clean interface for data sharing between components
- **Unified Backend**: `async_sub.py` serves as both a simple subscriber and full backend

## Troubleshooting

### No Data in Dashboard

If the dashboard is not displaying data:

1. **Check Component Status**:

   ```bash
   # Run in a separate terminal while system is running
   make debug-memory
   ```

   This will show if data is being stored in the shared buffers.

2. **Test Shared Memory**:

   ```bash
   # This will clear the data buffers every 10 seconds
   make debug-clear-memory
   ```

   If data reappears in both components after clearing, shared memory is working correctly.

3. **Ensure Correct Order**:
   - Start async_pub.py first
   - Then start dashboard.py

4. **Direct Connection**:
   The dashboard now attempts to connect directly to the data publisher,
   which should resolve shared memory issues.

5. **Check Logs**:
   Look for error messages in the console output of each component.

### RTR Frequency Controls Not Working

- Only dashboard.py should bind to the config publisher port
- Make sure async_pub.py is running and connected to the dashboard

## Migration Notes

- **`app.py` is deprecated**: Use `async_sub.py` instead for data collection
- **Backward compatibility**: Old `app.py` has been moved to `app_deprecated.py` for reference
- **Enhanced functionality**: `async_sub.py` now includes all backend features (data buffering, CSV logging, config publishing)

## Configuration

The system uses a YAML configuration file (`config.yaml`) to define CAN bus settings, ZMQ ports, and RTR message formats.

### System Configuration

The top-level configuration settings control the system behavior:

```yaml
can_interface: can0   # CAN interface name
bitrate: 500000       # CAN bus bitrate
simulation_mode: true # Enable/disable simulation mode (no hardware needed)
```

### Data Format Configuration

The configuration system allows you to define the format of each variable in the CAN messages:

```yaml
rtr_ids:
  - id: 0x100
    freq: 20.0  # Frequency in Hz
    variables:
      - name: adc_ch1
        type: int32
        format: ">i"  # Big-endian (>) 4-byte signed integer (i)
      - name: adc_ch2
        type: int32
        format: ">i"  # Big-endian (>) 4-byte signed integer (i)
```

The `format` field uses Python's struct module format characters:

- `>` = Big-endian (network byte order)
- `<` = Little-endian
- `i` = 4-byte signed integer (int32)
- `I` = 4-byte unsigned integer (uint32)
- `h` = 2-byte signed integer (int16)
- `H` = 2-byte unsigned integer (uint16)
- `b` = 1-byte signed integer (int8)
- `B` = 1-byte unsigned integer (uint8)
- `f` = 4-byte float (float32)
- `d` = 8-byte float (float64)

Variables are automatically unpacked in the order they appear in the configuration, with offsets calculated based on the data type sizes.

## Created

Initial version created on September 17, 2025.
Modularized architecture implemented on September 19, 2025.
Configurable data format system added on September 23, 2025.
Configurable simulation mode added on September 23, 2025.
