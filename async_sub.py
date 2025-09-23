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
    can_data_manager,  # Use the new class instance
    init_csv_log, log_to_csv  # Use the compatibility functions
)

class CANSubscriber:
    """Class to manage CAN bus data subscription and processing"""
    
    def __init__(self, config_path="config.yaml"):
        """Initialize the CAN subscriber with configuration"""
        # Store a reference to the data manager
        self.data_manager = can_data_manager
        
        # ZMQ subscriber for data
        self.subscriber = None
        
        # Track last values for display
        self.last_values = {}
        
        # Flag for overwrite mode
        self.overwrite_mode = True
    
    def initialize_backend(self):
        """Initialize the backend with CSV logging"""
        # Initialize CSV logging
        init_csv_log()
        print("CSV logging initialized")
    
    def setup_zmq_subscriber(self):
        """Set up the ZMQ subscriber for data"""
        self.subscriber = zmq.asyncio.Context().socket(zmq.SUB)
        self.subscriber.connect(get_address())
        
        # Subscribe to all topics
        self.subscriber.subscribe(b"")
        
        print(f"ZMQ subscriber connected to {get_address()}")
    
    async def process_data(self):
        """Process data received from the ZMQ subscriber"""
        while True:
            try:
                # Receive message with topic
                topic, data = await self.subscriber.recv_multipart()
                topic_str = topic.decode('utf8')
                
                # Parse JSON data
                received_data = json.loads(data.decode('utf8'))
                
                # Process data based on topic
                if topic_str.startswith("CAN_"):
                    # Extract CAN ID from topic (format: "CAN_XXX" where XXX is hex)
                    can_id_hex = topic_str.split("_")[1]
                    can_id = int(can_id_hex, 16)  # Always parse as hex for consistency
                    
                    # Check if this ID is enabled for display
                    with self.data_manager.enabled_ids_lock:
                        if can_id not in self.data_manager.enabled_ids:
                            continue
                    
                    # Find the corresponding RTR config
                    rtr_config = None
                    for rtr in self.data_manager.rtr_configs:
                        if parse_hex_id(rtr['id']) == can_id:
                            rtr_config = rtr
                            break
                    
                    if rtr_config:
                        # Add timestamp
                        current_time = time.time()
                        self.data_manager.timestamps[can_id].append(current_time)
                        
                        # Process each variable
                        for var_name, value in received_data.items():
                            # Store the value in the buffer
                            self.data_manager.data_buffers[can_id][var_name].append(value)
                            
                            # Store the last value for status display
                            if can_id not in self.last_values:
                                self.last_values[can_id] = {}
                            self.last_values[can_id][var_name] = value
                        
                        # Log to CSV (using last value for simplicity)
                        log_to_csv(current_time, can_id, var_name, value)
                            
                    # Print in overwrite mode
                    if self.overwrite_mode:
                        # Create a status display of all values
                        display = f"\r\033[KReceived: CAN ID 0x{can_id:X} | "
                        for var_name, value in received_data.items():
                            display += f"{var_name}={value} "
                        sys.stdout.write(display + "\n")  # Add newline to prevent overwriting
                        sys.stdout.flush()
                    else:
                        # Only print data occasionally to reduce verbosity
                        if time.time() % 5 < 0.1:  # Print approximately every 5 seconds
                            print(f"CAN ID 0x{can_id:X}: {received_data}")
                        
                elif topic_str == "SENSORS":
                    # This topic contains all accumulated sensor data
                    # Store last values
                    for key, value in received_data.items():
                        if "SENSORS" not in self.last_values:
                            self.last_values["SENSORS"] = {}
                        self.last_values["SENSORS"][key] = value
                    
                    # Always print summary in overwrite mode
                    if self.overwrite_mode:
                        # Create a summary in overwrite mode
                        summary = "\r\033[K--- Sensor Data Summary --- "
                        summary += f"Sensors: {len(received_data)} | "
                        # Add a few key values if they exist
                        key_sensors = ["temperature", "adc_ch1", "adc_ch3", "status_flags"]
                        for key in key_sensors:
                            if key in received_data:
                                summary += f"{key}: {received_data[key]} | "
                        sys.stdout.write(summary + "\n")  # Add newline to prevent overwriting
                        sys.stdout.flush()
                    else:
                        print("\n--- Sensor Data Summary ---")
                        print(f"Number of sensors: {len(received_data)}")
                        # Print a few key values if they exist
                        key_sensors = ["temperature", "adc_ch1", "adc_ch3", "status_flags"]
                        for key in key_sensors:
                            if key in received_data:
                                print(f"{key}: {received_data[key]}")
                else:
                    # Unknown topic - always print in overwrite mode
                    if self.overwrite_mode:
                        sys.stdout.write(f"\r\033[KMessage from {topic_str}: {len(received_data)} values\n")
                        sys.stdout.flush()
                    else:
                        print(f"Message from {topic_str}: {len(received_data)} values")
                        
            except (asyncio.CancelledError, KeyboardInterrupt):
                print("ZMQ subscription interrupted")
                break
            except Exception as e:
                print(f"Error processing ZMQ message: {e}")
                await asyncio.sleep(0.1)
    
    def display_status_screen(self):
        """Display a full-screen status of all CAN values"""
        if not self.last_values:
            return
            
        # Clear screen
        sys.stdout.write("\033[2J\033[H")  # Clear screen and move cursor to home
        
        # Create header with timestamp
        sys.stdout.write(f"=== CAN Bus Status Dashboard === (Updated: {time.strftime('%H:%M:%S')})\n\n")
        
        # Display each CAN ID and its values
        for key, values in sorted(self.last_values.items()):
            if key == "SENSORS":
                sys.stdout.write("--- Sensor Summary ---\n")
            else:
                sys.stdout.write(f"CAN ID 0x{key:X}:\n")
                
            for var_name, value in values.items():
                sys.stdout.write(f"  {var_name}: {value}\n")
            sys.stdout.write("\n")
            
        sys.stdout.flush()
        
        # Schedule next update (more frequent updates - every 0.2 seconds)
        timer = threading.Timer(0.2, self.display_status_screen)
        timer.daemon = True
        timer.start()
    
    async def run(self, dashboard_mode=False):
        """Run the CAN subscriber"""
        # Initialize backend components
        self.initialize_backend()
        
        # Setup ZMQ subscriber
        self.setup_zmq_subscriber()
        
        print("Starting CAN data collection...")
        
        # Start status display if in dashboard mode
        if dashboard_mode:
            self.display_status_screen()
        
        # Process data
        await self.process_data()
    
    def shutdown(self):
        """Clean up resources"""
        if self.subscriber:
            self.subscriber.close()
        print("CAN subscriber shut down")

def run_as_backend():
    """Run as a complete backend service"""
    print("Starting CAN data collection backend...")
    print("Data is being collected and stored for dashboard access.")
    print("You can now run dashboard.py to view the data.")
    print("NOTE: Make sure async_pub.py is running for RTR message handling")
    print("      and dashboard.py is running for frequency control.")
    print("Press Ctrl+C to stop data collection.")
    
    subscriber = CANSubscriber()
    
    try:
        asyncio.run(subscriber.run())
    except KeyboardInterrupt:
        print("\nShutting down data collection...")
        subscriber.shutdown()
        sys.exit(0)

if __name__ == '__main__':
    # Check for command-line arguments
    simple_mode = '--simple' in sys.argv
    dashboard_mode = '--dashboard' in sys.argv
    
    if simple_mode or dashboard_mode:
        # User mode
        mode_str = "simple subscriber mode" if simple_mode else "dashboard mode"
        print(f"Running in {mode_str} (display only)")
        subscriber = CANSubscriber()
        try:
            asyncio.run(subscriber.run(dashboard_mode=dashboard_mode))
        except KeyboardInterrupt:
            print("Program terminated by user")
            subscriber.shutdown()
    else:
        # Full backend mode (default)
        run_as_backend()