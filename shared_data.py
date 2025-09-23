"""
Shared data module for CAN bus monitoring application.
This module contains all shared data structures and configuration
that need to be accessed by both the data collection (app.py) 
and dashboard (dashboard.py) components.
"""

import threading
import time
import csv
from collections import deque, defaultdict

from utils import load_config, parse_hex_id

class CANDataManager:
    """Class to manage shared CAN data structures and configuration"""
    
    # Class-level constants
    SAMPLE_RATE = 20  # Hz (from your RTR configuration)
    DISPLAY_WINDOW = 5 * 60  # 5 minutes in seconds
    DEFAULT_CSV_FILE = 'can_data_log.csv'
    
    def __init__(self, config_path="config.yaml"):
        """Initialize the CAN data manager with configuration"""
        # Load configuration
        self.config = load_config(config_path)
        self.can_interface = self.config['can_interface']
        self.bitrate = self.config['bitrate']
        self.rtr_configs = self.config['rtr_ids']
        
        # Calculate buffer size based on sampling rate and time window
        self.buffer_size = self.SAMPLE_RATE * self.DISPLAY_WINDOW  # Points to keep in buffer
        
        # Create data buffers with calculated size
        self.data_buffers = defaultdict(lambda: defaultdict(lambda: deque(maxlen=self.buffer_size)))
        self.timestamps = defaultdict(lambda: deque(maxlen=self.buffer_size))
        
        # Define locks and instance variables
        self.csv_log_lock = threading.Lock()
        self.csv_log_file = self.DEFAULT_CSV_FILE
        self.enabled_ids_lock = threading.Lock()
        
        # Initialize with all RTR IDs
        self.enabled_ids = set(parse_hex_id(rtr['id']) for rtr in self.rtr_configs)
        
        # Data dictionary to store sensor values
        self.sensor_data = {}
        
        # Variable to store the config publisher (will be set by app.py)
        self.config_publisher = None
    
    def set_config_publisher(self, publisher):
        """Set the config publisher from app.py"""
        self.config_publisher = publisher
    
    def get_config_publisher(self):
        """Get the config publisher"""
        return self.config_publisher
    
    def init_csv_log(self, log_file=None):
        """Initialize the CSV log file"""
        if log_file:
            self.csv_log_file = log_file
            
        with self.csv_log_lock:
            with open(self.csv_log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                # Header: timestamp, rtr_id, variable, value
                writer.writerow(['timestamp', 'rtr_id', 'variable', 'value'])
    
    def log_to_csv(self, timestamp, rtr_id, variable, value):
        """Log data to CSV file"""
        with self.csv_log_lock:
            with open(self.csv_log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, f"0x{rtr_id:X}", variable, value])
    
    def enable_id(self, can_id):
        """Enable a CAN ID for data collection"""
        with self.enabled_ids_lock:
            self.enabled_ids.add(can_id)
    
    def disable_id(self, can_id):
        """Disable a CAN ID for data collection"""
        with self.enabled_ids_lock:
            if can_id in self.enabled_ids:
                self.enabled_ids.remove(can_id)
    
    def is_id_enabled(self, can_id):
        """Check if a CAN ID is enabled for data collection"""
        with self.enabled_ids_lock:
            return can_id in self.enabled_ids
    
    def get_enabled_ids(self):
        """Get the set of enabled CAN IDs"""
        with self.enabled_ids_lock:
            return self.enabled_ids.copy()

# Create a global instance for backward compatibility
can_data_manager = CANDataManager()

# For backward compatibility with existing code
config = can_data_manager.config
can_interface = can_data_manager.can_interface
bitrate = can_data_manager.bitrate
rtr_configs = can_data_manager.rtr_configs
data_buffers = can_data_manager.data_buffers
timestamps = can_data_manager.timestamps
csv_log_lock = can_data_manager.csv_log_lock
csv_log_file = can_data_manager.csv_log_file
enabled_ids_lock = can_data_manager.enabled_ids_lock
enabled_ids = can_data_manager.enabled_ids
sensor_data = can_data_manager.sensor_data
config_publisher = can_data_manager.config_publisher

# Backward compatibility functions
def set_config_publisher(publisher):
    """Set the config publisher from app.py"""
    can_data_manager.set_config_publisher(publisher)
    global config_publisher
    config_publisher = publisher

def get_config_publisher():
    """Get the config publisher"""
    return can_data_manager.get_config_publisher()

def init_csv_log(log_file=None):
    """Initialize the CSV log file"""
    can_data_manager.init_csv_log(log_file)

def log_to_csv(timestamp, rtr_id, variable, value):
    """Log data to CSV file"""
    can_data_manager.log_to_csv(timestamp, rtr_id, variable, value)