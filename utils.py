import yaml

def get_address():
    protocol = "tcp"
    address = "127.0.0.1"
    port = 10101
    return f"{protocol}://{address}:{port}"

def load_config(config_path="config.yaml"):
    """Load configuration from YAML file"""
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    return config

def parse_hex_id(id_str):
    """Parse hex string into integer"""
    if isinstance(id_str, str) and id_str.startswith("0x"):
        return int(id_str, 16)
    return id_str