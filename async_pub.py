#! /usr/bin/env python

import asyncio
import can
import zmq
import zmq.asyncio
import struct
import json
import random
import time
from typing import Dict, List, Any

from utils import get_address, load_config, parse_hex_id

# Global dictionary to store dynamic RTR frequencies
rtr_frequencies = {}

# Global data dictionary to store sensor values
sensor_data: Dict[str, Any] = {}

def process_rtr_response(can_msg):
    """Process a response to an RTR message"""
    data_dict = {}
    
    if can_msg.arbitration_id == 0x100:
        # Interpret the data based on the message format we're receiving
        # First 4 bytes for adc_ch1 (00 00 09 99) -> 2457 in decimal
        # Last 4 bytes for adc_ch2 (00 00 00 14) -> 20 in decimal
        
        # Data format seems to be big-endian based on your example
        data_dict["adc_ch1"] = struct.unpack('>i', can_msg.data[0:4])[0]
        data_dict["adc_ch2"] = struct.unpack('>i', can_msg.data[4:8])[0]
        
        # Print raw bytes for debugging
        print(f"Raw data: {' '.join([f'{b:02X}' for b in can_msg.data])}")
        print(f"adc_ch1 value: {data_dict['adc_ch1']} (hex: {data_dict['adc_ch1']:08X})")
        print(f"adc_ch2 value: {data_dict['adc_ch2']} (hex: {data_dict['adc_ch2']:08X})")
        
    # Add processing for other RTR IDs here as needed
    
    return data_dict

def create_rtr_message(rtr_config):
    """Create an RTR message based on configuration"""
    can_id = parse_hex_id(rtr_config["id"])
    
    # Create an RTR message (Remote Transmission Request)
    # RTR messages have no data but request data from a node
    message = can.Message(
        arbitration_id=can_id,
        is_remote_frame=True,
        is_extended_id=False
    )
    
    return message

def simulate_rtr_response(rtr_config):
    """Simulate a response to an RTR message for testing without hardware"""
    can_id = parse_hex_id(rtr_config["id"])
    
    # For simulation purposes, create random data based on variable types
    data_bytes = bytearray()
    
    for var in rtr_config.get("variables", []):
        if var["type"] == "int32":
            # Random value for an ADC channel (e.g., 0-4095 for 12-bit ADC)
            value = random.randint(0, 4095)
            data_bytes.extend(struct.pack('i', value))
        # Add other data types as needed
    
    # Create a CAN message with the simulated data
    message = can.Message(
        arbitration_id=can_id,
        data=data_bytes,
        is_remote_frame=False,
        is_extended_id=False
    )
    
    return message

async def send_rtr_messages(bus, rtr_configs):
    """Send RTR messages at specified frequencies"""
    # Track when each RTR message was last sent
    last_sent = {parse_hex_id(cfg["id"]): 0 for cfg in rtr_configs}
    
    # Initialize the frequency dictionary from config
    for config in rtr_configs:
        can_id = parse_hex_id(config["id"])
        rtr_frequencies[can_id] = config.get("freq", 1.0)
    
    while True:
        current_time = time.time()
        
        for config in rtr_configs:
            can_id = parse_hex_id(config["id"])
            
            # Get frequency from dynamic dictionary or fallback to config
            frequency = rtr_frequencies.get(can_id, config.get("freq", 1.0))
            period = 1.0 / frequency
            
            # Check if it's time to send this RTR message
            if current_time - last_sent[can_id] >= period:
                try:
                    # Create and send the RTR message
                    message = create_rtr_message(config)
                    bus.send(message)
                    last_sent[can_id] = current_time
                    print(f"Sent RTR request for ID: 0x{can_id:X} at {frequency}Hz")
                except Exception as e:
                    print(f"Error sending RTR message for ID 0x{can_id:X}: {e}")
        
        # Short sleep to prevent busy-waiting
        await asyncio.sleep(0.01)

async def receive_config_updates():
    """Receive configuration updates from the dashboard"""
    # Create ZMQ subscriber for configuration updates
    ctx = zmq.asyncio.Context()
    config_subscriber = ctx.socket(zmq.SUB)
    config_subscriber.connect("tcp://127.0.0.1:10102")
    config_subscriber.subscribe(b"CONFIG")
    
    print("Listening for configuration updates...")
    
    while True:
        try:
            # Receive message with topic
            topic, data = await config_subscriber.recv_multipart()
            
            # Parse the JSON data
            config_update = json.loads(data.decode('utf8'))
            
            # Process configuration update
            if config_update.get('type') == 'rtr_frequency_update':
                rtr_id = config_update.get('id')
                frequency = config_update.get('frequency')
                
                if rtr_id and frequency:
                    # Update the frequency in our global dictionary
                    rtr_frequencies[parse_hex_id(rtr_id)] = frequency
                    print(f"Updated RTR frequency for {rtr_id} to {frequency}Hz")
            
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("Configuration update reception interrupted")
            break
        except Exception as e:
            print(f"Error processing configuration update: {e}")
            await asyncio.sleep(0.1)

async def receive_can_messages(bus, publisher):
    """Receive and process CAN messages"""
    global sensor_data
    
    while True:
        try:
            # Receive CAN message
            can_msg = bus.recv(timeout=0.1)
            
            if can_msg is None:
                await asyncio.sleep(0.01)
                continue
                
            # Process the received message
            if not can_msg.is_remote_frame:  # Process only data frames, not RTR requests
                # Update sensor data with the processed values
                received_data = process_rtr_response(can_msg)
                if received_data:
                    sensor_data.update(received_data)
                    
                    # Send the updated data via ZMQ
                    await publisher.send_multipart([
                        f"CAN_{can_msg.arbitration_id:X}".encode(),  # Topic
                        json.dumps(received_data).encode("utf8")     # Data
                    ])
                    
                    # Also send all accumulated sensor data
                    await publisher.send_multipart([
                        b"SENSORS",  # Topic for all sensor data
                        json.dumps(sensor_data).encode("utf8")
                    ])
                    
                    print(f"Received data for ID 0x{can_msg.arbitration_id:X}: {received_data}")
                
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Message reception interrupted: {e}")
            raise
        except Exception as e:
            print(f"Error processing CAN message: {e}")
            await asyncio.sleep(0.1)

async def main():
    # Load configuration
    config = load_config()
    
    # Setup ZMQ publisher
    publisher = zmq.asyncio.Context().socket(zmq.PUB)
    publisher.bind(get_address())
    print(f"Publisher bound to {get_address()}")
    
    # Get CAN interface from config
    can_interface = config.get("can_interface", "can0")
    
    # Set up CAN filters for RTR IDs
    rtr_configs = config.get("rtr_ids", [])
    filters = []
    
    for rtr_config in rtr_configs:
        can_id = parse_hex_id(rtr_config["id"])
        filters.append({"can_id": can_id, "can_mask": 0x7FF})
    
    try:
        # Set up the CAN bus interface
        bus = can.interface.Bus(channel=can_interface, interface='socketcan', can_filters=filters)
        
        # Create tasks for configuration updates, sending RTR messages, and receiving responses
        tasks = [
            asyncio.create_task(receive_config_updates()),
            asyncio.create_task(send_rtr_messages(bus, rtr_configs)),
            asyncio.create_task(receive_can_messages(bus, publisher))
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
            bus.shutdown()
            publisher.close()
        except:
            pass

if __name__ == '__main__':
    # Enable simulation mode for testing without actual CAN hardware
    SIMULATION_MODE = False
    
    if SIMULATION_MODE:
        # Monkey patch the can.Bus.recv method to simulate responses
        original_send = can.interface.Bus.send
        
        def mock_send(self, msg, *args, **kwargs):
            print(f"Sending RTR message: ID=0x{msg.arbitration_id:X}")
            if msg.is_remote_frame:
                # Find matching config for this RTR
                config = None
                for cfg in load_config().get("rtr_ids", []):
                    if parse_hex_id(cfg["id"]) == msg.arbitration_id:
                        config = cfg
                        break
                
                if config:
                    # Create a simulated response
                    response = simulate_rtr_response(config)
                    # Add to the receive buffer
                    self._recv_buffer.append(response)
            
            return original_send(self, msg, *args, **kwargs)
        
        # Apply the monkey patch
        can.interface.Bus.send = mock_send
    
    asyncio.run(main())