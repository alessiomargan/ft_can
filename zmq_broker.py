#!/usr/bin/env python3
"""
Simple ZMQ forwarder broker for ft_can

This broker provides two forwarder devices:
- Data forwarder: XSUB binds on data_pub_input (publishers connect here)
  and XPUB binds on data_port (subscribers connect here).
- Config forwarder: XSUB binds on config_pub_input (dashboards connect here)
  and XPUB binds on config_port (subscribers -- async_pub -- connect here).

Using this broker decouples bind/connect ordering and lets multiple
publishers/subscribers join dynamically.
"""
import zmq
import zmq.devices
import threading
from utils import load_config


def _start_proxy(xsub_addr, xpub_addr):
    ctx = zmq.Context()
    xsub = ctx.socket(zmq.XSUB)
    xpub = ctx.socket(zmq.XPUB)
    xsub.bind(xsub_addr)
    xpub.bind(xpub_addr)
    print(f"Broker proxy started: XSUB bound to {xsub_addr}, XPUB bound to {xpub_addr}")
    try:
        zmq.proxy(xsub, xpub)
    except Exception as e:
        print(f"Broker proxy terminated: {e}")
    finally:
        xsub.close()
        xpub.close()


def main():
    cfg = load_config()
    data_port = cfg.get('zmq', {}).get('data_port', 10101)
    config_port = cfg.get('zmq', {}).get('config_port', 10102)

    # Publisher input ports (where publishers will connect)
    data_pub_input = data_port + 10  # 10111
    config_pub_input = config_port + 10  # 10112

    data_xsub = f"tcp://127.0.0.1:{data_pub_input}"
    data_xpub = f"tcp://127.0.0.1:{data_port}"

    config_xsub = f"tcp://127.0.0.1:{config_pub_input}"
    config_xpub = f"tcp://127.0.0.1:{config_port}"

    # Start proxies in background threads
    t1 = threading.Thread(target=_start_proxy, args=(data_xsub, data_xpub), daemon=True)
    t2 = threading.Thread(target=_start_proxy, args=(config_xsub, config_xpub), daemon=True)
    t1.start()
    t2.start()

    print("ZMQ broker running. Press Ctrl+C to exit.")
    try:
        while True:
            t1.join(1)
            t2.join(1)
    except KeyboardInterrupt:
        print("Broker shutting down")


if __name__ == '__main__':
    main()
