#!/usr/bin/env python3
"""
Runner script for the CAN Bus monitoring application.
This script provides options to run the data collection, dashboard, or both.
"""

import subprocess
import sys
import argparse
import threading
import time

def run_data_collection():
    """Run the data collection backend"""
    print("Starting data collection...")
    subprocess.run([sys.executable, "async_sub.py"])

def run_dashboard():
    """Run the dashboard frontend"""
    print("Starting dashboard...")
    subprocess.run([sys.executable, "dashboard.py"])

def run_both():
    """Run both data collection and dashboard"""
    print("Starting both data collection and dashboard...")
    
    # Start data collection in a thread
    data_thread = threading.Thread(target=run_data_collection, daemon=True)
    data_thread.start()
    
    # Wait a moment for data collection to initialize
    time.sleep(2)
    
    # Start dashboard in main thread
    run_dashboard()

def main():
    parser = argparse.ArgumentParser(description="CAN Bus Monitoring Application")
    parser.add_argument(
        "mode", 
        choices=["data", "dashboard", "both"],
        help="What to run: 'data' (data collection only), 'dashboard' (dashboard only), or 'both'"
    )
    
    args = parser.parse_args()
    
    if args.mode == "data":
        run_data_collection()
    elif args.mode == "dashboard":
        run_dashboard()
    elif args.mode == "both":
        run_both()

if __name__ == "__main__":
    main()