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
import numpy as np
from scipy import signal
import pandas as pd

from utils import load_config, parse_hex_id

# Load configuration
config = load_config()
can_interface = config['can_interface']
bitrate = config['bitrate']
rtr_configs = config['rtr_ids']

# Buffers for each variable per RTR ID - calculate buffer size based on sampling rate and time window
SAMPLE_RATE = 20  # Hz (from your RTR configuration)
DISPLAY_WINDOW = 5 * 60  # 5 minutes in seconds
BUFFER_SIZE = SAMPLE_RATE * DISPLAY_WINDOW  # Points to keep in buffer

# Create data buffers with calculated size
data_buffers = defaultdict(lambda: defaultdict(lambda: deque(maxlen=BUFFER_SIZE)))
timestamps = defaultdict(lambda: deque(maxlen=BUFFER_SIZE))

# Define locks and global variables
csv_log_lock = threading.Lock()
csv_log_file = 'can_data_log.csv'
enabled_ids_lock = threading.Lock()
enabled_ids = set(parse_hex_id(rtr['id']) for rtr in rtr_configs)  # Initialize with all RTR IDs

# Global data dictionary to store sensor values
sensor_data = {}

# Global variable to store the config publisher (will be set by app.py)
config_publisher = None

def set_config_publisher(publisher):
    """Set the config publisher from app.py"""
    global config_publisher
    config_publisher = publisher

def get_config_publisher():
    """Get the config publisher"""
    return config_publisher

def init_csv_log():
    """Initialize the CSV log file"""
    with csv_log_lock:
        with open(csv_log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            # Header: timestamp, rtr_id, variable, value
            writer.writerow(['timestamp', 'rtr_id', 'variable', 'value'])

def log_to_csv(timestamp, rtr_id, variable, value):
    """Log data to CSV file"""
    with csv_log_lock:
        with open(csv_log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, f"0x{rtr_id:X}", variable, value])

def apply_smoothing(x_values, y_values, method, window_size):
    """Apply different smoothing methods to the data"""
    if len(y_values) < window_size:
        return x_values, y_values  # Not enough data points for smoothing
    
    if method == 'none':
        return x_values, y_values  # No smoothing
    
    # Convert to numpy arrays for processing
    x_array = np.array(x_values)
    y_array = np.array(y_values)
    
    # Sort by x values to ensure time order
    sort_idx = np.argsort(x_array)
    x_sorted = x_array[sort_idx]
    y_sorted = y_array[sort_idx]
    
    # Apply selected smoothing method
    try:
        if method == 'moving_avg':
            # Simple moving average
            kernel = np.ones(window_size) / window_size
            y_smooth = np.convolve(y_sorted, kernel, mode='same')
            
            # Fix edge effects
            half_window = window_size // 2
            y_smooth[:half_window] = y_sorted[:half_window]
            y_smooth[-half_window:] = y_sorted[-half_window:]
            
        elif method == 'savgol':
            # Savitzky-Golay filter (polynomial smoothing)
            polyorder = min(3, window_size - 1)  # Order of polynomial
            y_smooth = signal.savgol_filter(y_sorted, window_size, polyorder)
            
        elif method == 'exponential':
            # Exponential moving average
            alpha = 2 / (window_size + 1)  # Smoothing factor
            y_smooth = pd.Series(y_sorted).ewm(alpha=alpha).mean().values
        
        else:
            return x_sorted, y_sorted  # Unknown method
        
        return x_sorted, y_smooth
    
    except Exception as e:
        print(f"Error applying smoothing: {e}")
        return x_sorted, y_sorted  # Return original data on error