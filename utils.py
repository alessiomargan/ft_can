import yaml
import socket
import sys

def load_config(config_path="config.yaml"):
    """Load configuration from YAML file"""
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    return config

def get_address():
    """Get the data ZMQ address from config"""
    config = load_config()
    protocol = "tcp"
    address = "127.0.0.1"
    port = config.get('zmq', {}).get('data_port', 10101)
    return f"{protocol}://{address}:{port}"

def get_config_address():
    """Get the config ZMQ address from config"""
    config = load_config()
    protocol = "tcp"
    address = "127.0.0.1"
    port = config.get('zmq', {}).get('config_port', 10102)
    return f"{protocol}://{address}:{port}"

def get_data_pub_input():
    """Get the data publisher input address (where publishers should connect)
    This is the broker-facing input port (data_port + 10 by default)."""
    config = load_config()
    protocol = "tcp"
    address = "127.0.0.1"
    base = config.get('zmq', {}).get('data_port', 10101)
    return f"{protocol}://{address}:{base + 10}"

def get_config_pub_input():
    """Get the config publisher input address (where dashboards should connect)
    This is the broker-facing input port (config_port + 10 by default)."""
    config = load_config()
    protocol = "tcp"
    address = "127.0.0.1"
    base = config.get('zmq', {}).get('config_port', 10102)
    return f"{protocol}://{address}:{base + 10}"

def is_port_in_use(port):
    """Check if a port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def parse_hex_id(id_str):
    """
    Parse CAN ID in various formats to integer
    - If string starts with "0x", parse as hex
    - If integer, return as is
    """
    if isinstance(id_str, str):
        if id_str.startswith("0x"):
            return int(id_str, 16)
        # Try to parse as hex anyway if it's a string but doesn't have 0x prefix
        try:
            # Only attempt hex parsing if the string looks like it might be hexadecimal
            if all(c in '0123456789ABCDEFabcdef' for c in id_str):
                return int(id_str, 16)
        except ValueError:
            pass
    
    # If integer or failed to parse as hex, return as is
    return id_str