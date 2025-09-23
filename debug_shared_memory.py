"""
Debug tool to check shared memory buffers between components.
Run this script to see if data is being properly shared between processes.
"""

import time
import sys
from shared_data import data_buffers, timestamps, enabled_ids

def print_shared_memory_status():
    """Print the status of shared memory buffers"""
    print("\n=== SHARED MEMORY STATUS ===")
    print(f"Data buffers keys: {list(data_buffers.keys())}")
    if not data_buffers:
        print("WARNING: No data in data_buffers!")
    
    for can_id in data_buffers:
        print(f"CAN ID 0x{can_id:X} variables: {list(data_buffers[can_id].keys())}")
        for var_name in data_buffers[can_id]:
            data_points = len(data_buffers[can_id][var_name])
            print(f"  {var_name}: {data_points} data points")
            if data_points > 0:
                print(f"    Last value: {list(data_buffers[can_id][var_name])[-1]}")
    
    print(f"\nTimestamps:")
    for can_id in timestamps:
        print(f"CAN ID 0x{can_id:X}: {len(timestamps[can_id])} timestamps")
        if len(timestamps[can_id]) > 0:
            last_time = list(timestamps[can_id])[-1]
            time_ago = time.time() - last_time
            print(f"  Last timestamp: {time_ago:.2f} seconds ago")
    
    print(f"\nEnabled IDs: {[f'0x{id:X}' for id in enabled_ids]}")
    print("==============================\n")

if __name__ == "__main__":
    print("Monitoring shared memory status...")
    print("Press Ctrl+C to exit")
    
    try:
        while True:
            print_shared_memory_status()
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nExiting memory monitor")
        sys.exit(0)