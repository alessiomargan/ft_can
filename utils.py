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

def is_port_in_use(port):
    """Check if a port is in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def parse_hex_id(id_str):
    """Parse hex string into integer"""
    if isinstance(id_str, str) and id_str.startswith("0x"):
        return int(id_str, 16)
    return id_str