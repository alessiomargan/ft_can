"""
Debug tool to periodically clear shared memory buffers.
This helps diagnose if there are multiple copies of the shared data.
"""

import time
import sys
from shared_data import data_buffers, timestamps

def clear_and_report():
    """Clear all buffers and report status"""
    print("\n=== CLEARING SHARED MEMORY ===")
    
    # Report before clearing
    print(f"Before clearing - Data buffers keys: {list(data_buffers.keys())}")
    for can_id in data_buffers:
        print(f"CAN ID 0x{can_id:X} variables: {list(data_buffers[can_id].keys())}")
        for var_name in data_buffers[can_id]:
            print(f"  {var_name}: {len(data_buffers[can_id][var_name])} data points")
    
    # Clear all data
    for can_id in list(data_buffers.keys()):
        for var_name in list(data_buffers[can_id].keys()):
            data_buffers[can_id][var_name].clear()
        timestamps[can_id].clear()
    
    # Report after clearing
    print(f"\nAfter clearing - Data buffers keys: {list(data_buffers.keys())}")
    for can_id in data_buffers:
        print(f"CAN ID 0x{can_id:X} variables: {list(data_buffers[can_id].keys())}")
        for var_name in data_buffers[can_id]:
            print(f"  {var_name}: {len(data_buffers[can_id][var_name])} data points")
    
    print("==============================\n")

if __name__ == "__main__":
    print("WARNING: This tool will clear all shared memory buffers every 10 seconds.")
    print("Run this while both async_sub.py and dashboard.py are running.")
    print("If data reappears in both, shared memory is working correctly.")
    print("Press Ctrl+C to exit")
    
    try:
        while True:
            time.sleep(10)  # Wait 10 seconds
            clear_and_report()
    except KeyboardInterrupt:
        print("\nExiting memory clearer")
        sys.exit(0)