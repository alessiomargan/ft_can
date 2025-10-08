#! /usr/bin/env python

import asyncio
import can
import zmq
import zmq.asyncio
import struct
import json
import random
import time
import sys
from typing import Dict, List, Any

from utils import get_address, get_config_address, load_config, parse_hex_id


class CANBusManager:
    """Class to manage CAN bus communication with configuration handling"""
    
    def __init__(self, config_path="config.yaml"):
        """Initialize the CAN bus manager with configuration"""
        # Load configuration
        self.config = load_config(config_path)
        
        # Dictionary to store dynamic RTR frequencies
        self.rtr_frequencies = {}
        
        # Dictionary to store sensor values
        self.sensor_data = {}

        # Active RTR tasks keyed by CAN ID
        self.active_tasks = {}

        # Get simulation mode setting from config
        self.simulation_mode = self.config.get("simulation_mode", False)
        
        # ZMQ publisher for data
        self.data_publisher = None
        
        # CAN bus interface
        self.bus = None
        
        # Initialize RTR frequencies from config
        self._initialize_rtr_frequencies()
        
        # Print simulation mode status
        if self.simulation_mode:
            print("⚠️  SIMULATION MODE IS ENABLED - Using simulated CAN data")
        else:
            print("💻 SIMULATION MODE IS DISABLED - Using real CAN hardware")
    
    def _initialize_rtr_frequencies(self):
        """Initialize RTR frequencies from config"""
        for rtr_config in self.config.get("rtr_ids", []):
            can_id = parse_hex_id(rtr_config["id"])
            frequency = float(rtr_config.get("freq", 0.0))
            self.rtr_frequencies[can_id] = frequency
            print(f"Initialized RTR frequency for ID 0x{can_id:X} to {frequency}Hz from config")
    
    def setup_can_bus(self):
        """Set up the CAN bus interface"""
        # Get CAN interface from config
        can_interface = self.config.get("can_interface", "can0")
        
        # Set up CAN filters for RTR IDs
        rtr_configs = self.config.get("rtr_ids", [])
        filters = []
        
        for rtr_config in rtr_configs:
            can_id = parse_hex_id(rtr_config["id"])
            filters.append({"can_id": can_id, "can_mask": 0x7FF})
        
        try:
            # Set up the CAN bus interface
            if self.simulation_mode:
                # In simulation mode, create a Bus object with any channel (won't be used)
                print("Creating simulated CAN bus interface")
                # Setup happens in __main__ section with SimulatedBus class
                self.bus = can.interface.Bus(channel='vcan0', can_filters=filters)
            else:
                # Normal hardware mode
                self.bus = can.interface.Bus(channel=can_interface, interface='socketcan', can_filters=filters)
            
            return True
        except Exception as e:
            print(f"Error setting up CAN bus: {e}")
            return False
    
    def setup_zmq_publisher(self):
        """Set up the ZMQ publisher for data"""
        try:
            self.data_publisher = zmq.asyncio.Context().socket(zmq.PUB)
            # Connect to broker publisher input so broker can forward to subscribers
            from utils import get_data_pub_input
            data_pub_input = get_data_pub_input()
            self.data_publisher.connect(data_pub_input)
            print(f"Publisher connected to broker input at {data_pub_input}")
            # Also create a config publisher so we can send CONFIG_ACK messages
            try:
                self.config_publisher = zmq.asyncio.Context().socket(zmq.PUB)
                from utils import get_config_pub_input
                config_pub_input = get_config_pub_input()
                self.config_publisher.connect(config_pub_input)
                print(f"Config publisher (ACK) connected to broker input at {config_pub_input}")
            except Exception as e:
                print(f"Warning: failed to create config publisher for ACKs: {e}")
            return True
        except zmq.error.ZMQError as e:
            print(f"ERROR: Failed to bind data publisher to {get_address()}")
            print(f"Error details: {e}")
            print("Please ensure no other instances of the application are running.")
            return False
    
    def create_rtr_message(self, rtr_config):
        """Create an RTR message based on configuration"""
        can_id = parse_hex_id(rtr_config["id"])
        
        # Create an RTR message (Remote Transmission Request)
        message = can.Message(
            arbitration_id=can_id,
            is_remote_frame=True,
            is_extended_id=False
        )
        
        return message
    
    def process_rtr_response(self, can_msg):
        """Process a response to an RTR message"""
        data_dict = {}
        
        # Find the matching RTR configuration for this CAN ID
        matching_config = None
        for rtr_config in self.config.get("rtr_ids", []):
            if parse_hex_id(rtr_config["id"]) == can_msg.arbitration_id:
                matching_config = rtr_config
                break
        
        if matching_config:
            # Process the message using the configuration
            current_offset = 0
            for var in matching_config.get("variables", []):
                var_name = var["name"]
                var_format = var.get("format", ">i")  # Default to big-endian int32
                
                # Calculate size of this variable based on format
                format_size = struct.calcsize(var_format)
                
                # Extract and unpack the data
                try:
                    if hasattr(can_msg, 'data') and current_offset + format_size <= len(can_msg.data):
                        data_dict[var_name] = struct.unpack(
                            var_format, 
                            can_msg.data[current_offset:current_offset+format_size]
                        )[0]
                        
                        # Move offset for next variable
                        current_offset += format_size
                    else:
                        print(f"Warning: Not enough data in message to unpack {var_name} " 
                              f"(need {format_size} bytes, have {len(can_msg.data) - current_offset} bytes)")
                except struct.error as e:
                    print(f"Error unpacking {var_name} with format {var_format}: {e}")
                except Exception as e:
                    print(f"Unexpected error processing {var_name}: {e}")
        else:
            print(f"Warning: Received CAN message with ID 0x{can_msg.arbitration_id:X} but no matching configuration found")
        
        return data_dict
    
    async def send_rtr_requests(self):
        """Send RTR requests using event-driven scheduling for precise timing"""
        print("Starting event-driven RTR request sender")
        async def send_periodic_rtr(can_id):
            """Send RTR requests for a specific CAN ID reading frequency dynamically"""
            print(f"Started periodic RTR task for ID 0x{can_id:X}")
            try:
                while True:
                    # Always read current frequency from the shared dict
                    current_frequency = self.rtr_frequencies.get(can_id, 0)
                    if current_frequency <= 0:
                        print(f"Stopping RTR requests for ID 0x{can_id:X} (frequency: {current_frequency})")
                        break

                    interval = 1.0 / current_frequency

                    # Send RTR message
                    try:
                        rtr_msg = self.create_rtr_message({"id": f"0x{can_id:X}"})
                        self.bus.send(rtr_msg)
                        print(f"Sent RTR request for ID: 0x{can_id:X} at {current_frequency}Hz")
                    except Exception as e:
                        print(f"Error sending RTR for ID 0x{can_id:X}: {e}")

                    # Sleep for the interval (cancellable)
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                print(f"RTR task for ID 0x{can_id:X} was cancelled")

        # Start initial tasks for all configured RTR IDs
        for can_id, frequency in self.rtr_frequencies.items():
            if frequency > 0 and can_id not in self.active_tasks:
                task = asyncio.create_task(send_periodic_rtr(can_id))
                self.active_tasks[can_id] = task
                print(f"Created RTR task for ID 0x{can_id:X} with frequency {frequency}Hz")

        # Monitor for frequency changes and manage tasks
        while True:
            try:
                # Start or cancel tasks based on current rtr_frequencies
                for can_id, frequency in list(self.rtr_frequencies.items()):
                    if can_id not in self.active_tasks and frequency > 0:
                        print(f"Starting new RTR task for ID 0x{can_id:X} at {frequency}Hz")
                        task = asyncio.create_task(send_periodic_rtr(can_id))
                        self.active_tasks[can_id] = task
                    elif can_id in self.active_tasks and frequency <= 0:
                        print(f"Cancelling RTR task for ID 0x{can_id:X} (frequency set to {frequency})")
                        self.active_tasks[can_id].cancel()
                        del self.active_tasks[can_id]

                # Clean up completed tasks
                completed_tasks = []
                for can_id, task in list(self.active_tasks.items()):
                    if task.done():
                        completed_tasks.append(can_id)
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            print(f"RTR task for ID 0x{can_id:X} completed with error: {e}")

                for can_id in completed_tasks:
                    if can_id in self.active_tasks:
                        del self.active_tasks[can_id]
                        print(f"Cleaned up completed RTR task for ID 0x{can_id:X}")

                await asyncio.sleep(0.5)  # Check for changes twice per second

            except asyncio.CancelledError:
                print("RTR request sender was cancelled")
                for task in list(self.active_tasks.values()):
                    task.cancel()
                break
            except Exception as e:
                print(f"Error in RTR request manager: {e}")
                await asyncio.sleep(0.5)
    
    async def receive_config_updates(self):
        """Receive configuration updates from the dashboard"""
        print("Starting configuration update receiver...")
        
        # Create ZMQ subscriber for configuration updates
        ctx = zmq.asyncio.Context()
        config_subscriber = ctx.socket(zmq.SUB)
        
        # Connect to the config publisher using the fixed address from config
        config_address = get_config_address()
        try:
            config_subscriber.connect(config_address)
            print(f"Connected to config publisher at {config_address}")
        except Exception as e:
            print(f"ERROR: Failed to connect to config publisher at {config_address}")
            print(f"Error details: {e}")
            print("Configuration updates will not work!")
        
        # Subscribe to the CONFIG topic
        config_subscriber.subscribe(b"CONFIG")
        print(f"Subscribed to CONFIG topic")
        print(f"Initial RTR frequencies: {self.rtr_frequencies}")
        
        # Periodically print a heartbeat to show we're still listening
        last_heartbeat = time.time()
        
        while True:
            try:
                # Receive message with topic and timeout
                message = await asyncio.wait_for(
                    config_subscriber.recv_multipart(),
                    timeout=5.0  # 5 second timeout
                )
                
                if message:
                    topic, data = message
                    print(f"★★★ Received config update on topic: {topic.decode('utf8')} ★★★")
                    print(f"Raw data: {data.decode('utf8')}")
                    
                    # Parse the JSON data
                    config_update = json.loads(data.decode('utf8'))
                    
                    # Process configuration update
                    if config_update.get('type') == 'rtr_frequency_update':
                        rtr_id_str = config_update.get('id')
                        frequency = config_update.get('frequency')

                        # Accept frequency=0 (falsy), so check for None specifically
                        if rtr_id_str is not None and frequency is not None:
                            # Parse the ID (supports hex strings like '0x101')
                            rtr_id = parse_hex_id(rtr_id_str)
                            # Get old frequency for comparison
                            old_freq = self.rtr_frequencies.get(rtr_id, "not set")

                            # Update the frequency in our dictionary
                            self.rtr_frequencies[rtr_id] = frequency

                            print(f"Received CONFIG update raw id={rtr_id_str}, parsed id=0x{rtr_id:X}, frequency={frequency}")
                            print(f"Updated RTR frequency for {rtr_id_str} (ID: 0x{rtr_id:X}) from {old_freq} to {frequency}Hz")
                            print(f"Updated frequencies dict: {self.rtr_frequencies}")
                            # Send an ACK back on CONFIG_ACK topic so dashboards can confirm
                            try:
                                if hasattr(self, 'config_publisher') and self.config_publisher:
                                    ack = {
                                        'type': 'rtr_frequency_applied',
                                        'id': f"0x{rtr_id:X}",
                                        'frequency': frequency
                                    }
                                    await self.config_publisher.send_multipart([
                                        b"CONFIG_ACK",
                                        json.dumps(ack).encode('utf8')
                                    ])
                                    print(f"Sent CONFIG_ACK for 0x{rtr_id:X}: {ack}")
                            except Exception as e:
                                print(f"Error sending CONFIG_ACK: {e}")
            
            except asyncio.TimeoutError:
                # Always print a heartbeat message
                print("Config receiver still listening... (heartbeat)")
                print(f"Current RTR frequencies: {self.rtr_frequencies}")
                continue
                
            except (asyncio.CancelledError, KeyboardInterrupt):
                print("Configuration update reception interrupted")
                break
                
            except Exception as e:
                print(f"Error processing configuration update: {e}")
                await asyncio.sleep(0.1)
    
    async def receive_can_messages(self):
        """Receive and process CAN messages with event-driven approach"""
        print("Starting event-driven CAN message receiver")
        message_count = 0
        
        while True:
            try:
                # Use asyncio.to_thread for non-blocking CAN message reception
                can_msg = await asyncio.to_thread(self.bus.recv, 0.01)  # Short timeout
                
                if can_msg is None:
                    # No message received, yield control to other tasks
                    await asyncio.sleep(0)  # Yield to event loop
                    continue
                
                message_count += 1
                print(f"Received CAN message #{message_count}: ID=0x{can_msg.arbitration_id:X} (len={len(getattr(can_msg,'data',b''))})")
                try:
                    raw_hex = can_msg.data.hex() if hasattr(can_msg, 'data') else ''
                except Exception:
                    raw_hex = ''
                if raw_hex:
                    print(f"Raw CAN data: 0x{raw_hex}")
                    
                # Process the received message (non-RTR frames only)
                if not can_msg.is_remote_frame:
                    # Process message immediately without any delays
                    received_data = await self.process_can_message(can_msg)
                    
                    if received_data:
                        # Update sensor data and publish immediately
                        self.sensor_data.update(received_data)
                        
                        # Publish via ZMQ without delay
                        await self.data_publisher.send_multipart([
                            f"CAN_{can_msg.arbitration_id:X}".encode(),
                            json.dumps(received_data).encode("utf8")
                        ])
                        
                        await self.data_publisher.send_multipart([
                            b"SENSORS",
                            json.dumps(self.sensor_data).encode("utf8")
                        ])
                        
                        print(f"Data for ID 0x{can_msg.arbitration_id:X}: {received_data}")
                    else:
                        print(f"Warning: Received CAN message for ID 0x{can_msg.arbitration_id:X} but no data was extracted")
                    
            except asyncio.CancelledError:
                print("CAN message reception was cancelled")
                break
            except Exception as e:
                print(f"Error processing CAN message: {e}")
                import traceback
                traceback.print_exc()
                # Brief pause on error, but not arbitrary
                await asyncio.sleep(0.01)

    async def process_can_message(self, can_msg):
        """Process CAN message data asynchronously"""
        # Find matching configuration
        matching_config = None
        for rtr_config in self.config.get("rtr_ids", []):
            if parse_hex_id(rtr_config["id"]) == can_msg.arbitration_id:
                matching_config = rtr_config
                break
        
        if not matching_config:
            return {}
        
        # Process data using configuration
        received_data = {}
        current_offset = 0
        
        for var in matching_config.get("variables", []):
            var_name = var["name"]
            var_format = var.get("format", ">i")  # Default to big-endian int32
            format_size = struct.calcsize(var_format)
            
            try:
                if current_offset + format_size <= len(can_msg.data):
                    value = struct.unpack(
                        var_format,
                        can_msg.data[current_offset:current_offset+format_size]
                    )[0]
                    received_data[var_name] = value
                    current_offset += format_size
                else:
                    print(f"Not enough data for {var_name}: need {format_size} bytes, have {len(can_msg.data) - current_offset}")
            except struct.error as e:
                print(f"Error unpacking {var_name} with format {var_format}: {e}")
            except Exception as e:
                print(f"Unexpected error processing {var_name}: {e}")
        
        return received_data
    
    async def run(self):
        """Run the CAN bus manager with all its tasks"""
        # Setup CAN bus
        if not self.setup_can_bus():
            print("Failed to set up CAN bus. Exiting.")
            return
        
        # Setup ZMQ publisher
        if not self.setup_zmq_publisher():
            print("Failed to set up ZMQ publisher. Exiting.")
            return
        
        try:
            # Create tasks for configuration updates, sending RTR messages, and receiving responses
            tasks = [
                asyncio.create_task(self.receive_config_updates()),
                asyncio.create_task(self.send_rtr_requests()),
                asyncio.create_task(self.receive_can_messages())
            ]
            
            # Run the tasks concurrently
            await asyncio.gather(*tasks)
            
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Program interrupted: {e}")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            # Clean up
            try:
                self.bus.shutdown()
                self.data_publisher.close()
            except:
                pass


class SimulatedBus(can.BusABC):
    """Simulated CAN Bus class for testing without hardware"""
    
    def __init__(self, channel=None, *args, **kwargs):
        super().__init__(channel=channel, *args, **kwargs)
        self._recv_buffer = []
        print("Created SimulatedBus instance")
        
    def send(self, msg, timeout=None):
        # Only print RTR messages - these are the explicit requests
        if msg.is_remote_frame:
            print(f"Sending RTR request: ID=0x{msg.arbitration_id:X}")
            # Find matching config for this RTR
            matching_config = None
            for cfg in load_config().get("rtr_ids", []):
                if parse_hex_id(cfg["id"]) == msg.arbitration_id:
                    matching_config = cfg
                    break
            
            if matching_config:
                # Create a simulated response
                can_id = parse_hex_id(matching_config["id"])
                data_bytes = bytearray()
                
                for var in matching_config.get("variables", []):
                    var_format = var.get("format", ">i")  # Default to big-endian int32
                    var_type = var.get("type", "int32")
                    
                    # Generate random value based on variable type
                    if var_type == "int32":
                        value = random.randint(0, 4095)
                    elif var_type == "float32":
                        value = random.uniform(0, 100)
                    elif var_type == "uint16":
                        value = random.randint(0, 65535)
                    elif var_type == "uint8":
                        value = random.randint(0, 255)
                    else:
                        value = random.randint(0, 4095)
                    
                    # Pack using the specified format
                    try:
                        data_bytes.extend(struct.pack(var_format, value))
                    except struct.error as e:
                        print(f"Error packing {var['name']} with format {var_format}: {e}")
                        data_bytes.extend(struct.pack(">i", 0))
                
                # Create a mock message for the response
                response = can.Message(
                    arbitration_id=can_id,
                    data=data_bytes,
                    is_remote_frame=False,
                    is_extended_id=False
                )
                
                # Add to the receive buffer
                self._recv_buffer.append(response)
        
        return True
            
    def _recv_internal(self, timeout=None):
        if self._recv_buffer:
            msg = self._recv_buffer.pop(0)
            # Return a tuple of (message, is_filtered) as expected by can.BusABC implementation
            return msg, False
        return None, None
    
    def shutdown(self):
        print("Shutting down SimulatedBus")
        pass


if __name__ == '__main__':
    # Create an instance of CANBusManager
    manager = CANBusManager()
    
    # If in simulation mode, override the Bus class with our simulated version
    if manager.simulation_mode:
        print("RUNNING IN SIMULATION MODE - No actual CAN hardware needed")
        # Override the Bus class with our simulated version
        can.interface.Bus = SimulatedBus
    
    # Run the manager
    asyncio.run(manager.run())