#! /usr/bin/env python

import asyncio
import zmq
import zmq.asyncio
import json
from utils import get_address

async def main():
    # Setup ZMQ subscriber
    subscriber = zmq.asyncio.Context().socket(zmq.SUB)
    subscriber.connect(get_address())
    
    # Subscribe to all topics
    subscriber.subscribe(b"")  
    
    print(f"Subscriber connected to {get_address()}")
    print("Waiting for messages...")
    
    while True:
        try:
            # Receive message with topic
            topic, data = await subscriber.recv_multipart()
            
            # Parse JSON data
            parsed_data = json.loads(data.decode('utf8'))
            
            # Display the received data based on the topic
            topic_str = topic.decode('utf8')
            
            if topic_str == "SENSORS":
                print("\n--- All Sensor Data ---")
                for key, value in parsed_data.items():
                    print(f"{key}: {value}")
            else:
                print(f"\n--- Message from {topic_str} ---")
                for key, value in parsed_data.items():
                    print(f"{key}: {value}")
                    
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("Subscriber shutting down...")
            break
        except Exception as e:
            print(f"Error receiving data: {e}")
            await asyncio.sleep(0.1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program terminated by user")