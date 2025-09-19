#! /usr/bin/env python

import asyncio
import zmq
import zmq.asyncio
import json
import sys
import time
import threading

# Import utilities and shared data
from utils import get_address, get_config_address, parse_hex_id
from shared_data import (
    config, can_interface, bitrate, rtr_configs, data_buffers, timestamps,
    enabled_ids, enabled_ids_lock, sensor_data, set_config_publisher,
    init_csv_log, log_to_csv
)

# Force ZMQ socket cleanup for the config port
try:
    config_address = get_config_address()
    port = int(config_address.split(':')[-1])
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.setsockopt(zmq.LINGER, 0)
    socket.close()
    context.term()
    print(f"Cleaned up any lingering ZMQ sockets on port {port}")
except Exception as e:
    print(f"Note: ZMQ socket cleanup attempt: {e}")

# Setup ZMQ publisher for sending configuration updates
def setup_config_publisher(max_retries=3, retry_delay=0.5):
    """Set up the config publisher with retries"""
    for attempt in range(max_retries):
        try:
            context = zmq.Context()
            config_publisher = context.socket(zmq.PUB)
            # Set socket options
            config_publisher.setsockopt(zmq.LINGER, 0)
            config_publisher.setsockopt(zmq.RCVTIMEO, 1000)
            config_publisher.setsockopt(zmq.SNDTIMEO, 1000)
            
            config_address = get_config_address()
            print(f"Attempt {attempt+1}/{max_retries}: Binding config publisher to {config_address}")
            config_publisher.bind(config_address)
            print(f"Successfully bound config publisher to {config_address}")
            return config_publisher
        except zmq.error.ZMQError as e:
            print(f"Attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("All binding attempts failed.")
                raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

# Initialize the backend
def initialize_backend():
    """Initialize the backend with config publisher and CSV logging"""
    try:
        config_publisher = setup_config_publisher()
        set_config_publisher(config_publisher)
        print("Config publisher initialized successfully")
    except Exception as e:
        print(f"ERROR: Could not bind config publisher: {e}")
        print("Please ensure no other instances of the application are running.")
        print("Exiting due to port binding failure.")
        sys.exit(1)
    
    # Initialize CSV logging
    init_csv_log()
    print("CSV logging initialized")

async def main():
    """Main async function for data collection"""
    # Initialize backend components
    initialize_backend()
    
    # Setup ZMQ subscriber
    subscriber = zmq.asyncio.Context().socket(zmq.SUB)
    subscriber.connect(get_address())
    
    # Subscribe to all topics
    subscriber.subscribe(b"")  
    
    print(f"ZMQ subscriber connected to {get_address()}")
    print("Starting CAN data collection...")
    
    while True:
        try:
            # Receive message with topic
            topic, data = await subscriber.recv_multipart()
            topic_str = topic.decode('utf8')
            
            # Parse JSON data
            received_data = json.loads(data.decode('utf8'))
            
            # Process data based on topic
            if topic_str.startswith("CAN_"):
                # Extract CAN ID from topic (format: "CAN_XXX" where XXX is hex)
                can_id_hex = topic_str.split("_")[1]
                can_id = int(can_id_hex, 16)
                
                # Check if this ID is enabled for display
                with enabled_ids_lock:
                    if can_id not in enabled_ids:
                        continue
                
                # Find the corresponding RTR config
                rtr_config = None
                for rtr in rtr_configs:
                    if parse_hex_id(rtr['id']) == can_id:
                        rtr_config = rtr
                        break
                
                if rtr_config:
                    # Add timestamp
                    current_time = time.time()
                    timestamps[can_id].append(current_time)
                    
                    # Process each variable
                    for var_name, value in received_data.items():
                        # Store the value in the buffer
                        data_buffers[can_id][var_name].append(value)
                        
                        # Log to CSV
                        log_to_csv(current_time, can_id, var_name, value)
                        
                    # Optional: Print received data (can be disabled for production)
                    print(f"CAN ID 0x{can_id:X}: {received_data}")
                    
            elif topic_str == "SENSORS":
                # This topic contains all accumulated sensor data
                print("\n--- All Sensor Data ---")
                for key, value in received_data.items():
                    print(f"{key}: {value}")
            else:
                # Unknown topic
                print(f"\n--- Message from {topic_str} ---")
                for key, value in received_data.items():
                    print(f"{key}: {value}")
                    
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("ZMQ subscription interrupted")
            break
        except Exception as e:
            print(f"Error processing ZMQ message: {e}")
            await asyncio.sleep(0.1)

def run_as_backend():
    """Run as a complete backend service"""
    print("Starting CAN data collection backend...")
    print("Data is being collected and stored for dashboard access.")
    print("You can now run dashboard.py to view the data.")
    print("Press Ctrl+C to stop data collection.")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down data collection...")
        sys.exit(0)

if __name__ == '__main__':
    # Check if we should run as backend or simple subscriber
    if len(sys.argv) > 1 and sys.argv[1] == '--simple':
        # Original simple subscriber mode
        print("Running in simple subscriber mode (display only)")
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("Program terminated by user")
    else:
        # Full backend mode (default)
        run_as_backend()