#!/usr/bin/env python

import dash
import sys
import zmq
import json
from dash import dcc, html
from dash.dependencies import Output, Input
import plotly.graph_objs as go
import threading
import time
from collections import deque, defaultdict

# Import utilities
from utils import load_config, parse_hex_id, get_address, get_config_address

# Global variables
config = load_config()
can_interface = config['can_interface']
bitrate = config['bitrate']
rtr_configs = config['rtr_ids']

# Buffer settings
SAMPLE_RATE = 20  # Hz (max expected sampling rate)
DISPLAY_WINDOW = 5 * 60  # 5 minutes in seconds
BUFFER_SIZE = SAMPLE_RATE * DISPLAY_WINDOW  # Points to keep in buffer

# Data buffers
data_buffers = {}
timestamps = {}

# Initialize data structures for each RTR ID
for rtr in rtr_configs:
    rtr_id = parse_hex_id(rtr['id'])
    data_buffers[rtr_id] = {}
    timestamps[rtr_id] = deque(maxlen=BUFFER_SIZE)
    
    for var in rtr.get('variables', []):
        data_buffers[rtr_id][var['name']] = deque(maxlen=BUFFER_SIZE)

# ZMQ setup
context = zmq.Context()

# Publisher for config updates
config_publisher = context.socket(zmq.PUB)
config_publisher.setsockopt(zmq.LINGER, 0)
config_address = get_config_address()
try:
    config_publisher.bind(config_address)
    print(f"Config publisher bound to {config_address}")
except Exception as e:
    print(f"ERROR: Failed to bind config publisher: {e}")
    config_publisher = None

# Subscriber for data
data_subscriber = context.socket(zmq.SUB)
data_subscriber.setsockopt(zmq.LINGER, 0)
data_subscriber.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout
data_address = get_address()
try:
    data_subscriber.connect(data_address)
    data_subscriber.subscribe(b"CAN_")
    print(f"Data subscriber connected to {data_address}")
except Exception as e:
    print(f"ERROR: Failed to connect data subscriber: {e}")
    data_subscriber = None

# Data reception thread
def receive_data():
    if not data_subscriber:
        print("WARNING: Data subscriber not available")
        return
    
    print("Starting data reception thread")
    connection_check_time = time.time()
    data_received = False
    
    while True:
        try:
            # Try to receive a message with timeout
            topic, data = data_subscriber.recv_multipart()
            topic_str = topic.decode('utf8')
            
            # Process data
            if topic_str.startswith("CAN_"):
                # Extract CAN ID from topic (format: "CAN_XXX" where XXX is hex)
                can_id_hex = topic_str.split("_")[1]
                can_id = int(can_id_hex, 16)
                
                if can_id in data_buffers:
                    received_data = json.loads(data.decode('utf8'))
                    
                    # Add timestamp
                    current_time = time.time()
                    timestamps[can_id].append(current_time)
                    
                    # Process each variable
                    for var_name, value in received_data.items():
                        if var_name in data_buffers[can_id]:
                            data_buffers[can_id][var_name].append(value)
                    
                    if not data_received:
                        print(f"Dashboard received first data packet for CAN ID 0x{can_id:X}: {received_data}")
                        data_received = True
                    else:
                        # Only print occasional updates
                        if time.time() - connection_check_time > 10:
                            print(f"Dashboard is receiving data: CAN ID 0x{can_id:X} latest value: {received_data}")
                            connection_check_time = time.time()
        
        except zmq.error.Again:
            # Timeout occurred, check connection status periodically
            current_time = time.time()
            if current_time - connection_check_time > 10:
                if data_received:
                    print("Data reception is active but no data received in the last 10 seconds")
                else:
                    print("No data has been received yet - is async_pub.py running?")
                connection_check_time = current_time
        except Exception as e:
            print(f"Error in data reception thread: {e}")
            time.sleep(0.1)

# Start the data reception thread
data_thread = threading.Thread(target=receive_data, daemon=True)
data_thread.start()

# Create the Dash app
app = dash.Dash(__name__)
app.layout = html.Div([
    html.H2("CAN Bus Data Dashboard"),
    
    # RTR Configuration Controls
    html.Div([
        html.H4("RTR Settings"),
        html.Div([
            html.Div([
                html.Label(f"ID: 0x{parse_hex_id(rtr['id']):X}"),
                html.Div([
                    html.Label("Frequency (Hz):"),
                    dcc.Slider(
                        id=f'freq-{rtr["id"]}',
                        min=0,
                        max=50,
                        step=1,
                        value=float(rtr.get('freq', 10)),
                        marks={i: str(i) for i in range(0, 51, 10)}
                    ),
                    html.Div(id=f'freq-value-{rtr["id"]}'),
                ]),
                html.Div([
                    dcc.Checklist(
                        id=f'enable-{rtr["id"]}',
                        options=[{'label': 'Enable', 'value': 'enabled'}],
                        value=['enabled']
                    )
                ])
            ], style={'border': '1px solid #ddd', 'padding': '10px', 'margin': '5px', 'borderRadius': '5px'})
            for rtr in rtr_configs
        ], style={'display': 'flex', 'flexWrap': 'wrap'})
    ]),
    
    # Graph
    dcc.Graph(id='can-graph'),
    
    # Display Settings
    html.Div([
        html.Div([
            html.Label("Update Interval (ms):"),
            dcc.Slider(
                id='update-interval',
                min=100,
                max=2000,
                step=100,
                value=500,
                marks={i: str(i) for i in range(100, 2001, 500)}
            )
        ], style={'width': '48%', 'display': 'inline-block'}),
        
        html.Div([
            html.Label("Display Window (seconds):"),
            dcc.Slider(
                id='display-window',
                min=10,
                max=300,
                step=10,
                value=60,
                marks={i: str(i) for i in range(0, 301, 60)}
            )
        ], style={'width': '48%', 'display': 'inline-block'})
    ]),
    
    # Update interval component
    dcc.Interval(
        id='interval-component',
        interval=500,
        n_intervals=0
    )
])

# Create frequency slider callbacks with a function factory
def create_freq_callback(rtr_id):
    @app.callback(
        Output(f'freq-value-{rtr_id}', 'children'),
        Input(f'freq-{rtr_id}', 'value')
    )
    def update_freq_value(value):
        return f"Current frequency: {value} Hz"
    
    return update_freq_value

# Register callbacks for each RTR ID
for rtr in rtr_configs:
    rtr_id = rtr['id']
    create_freq_callback(rtr_id)

# Update interval callback
@app.callback(
    Output('interval-component', 'interval'),
    Input('update-interval', 'value')
)
def update_interval(value):
    return value

# Main graph update callback
@app.callback(
    Output('can-graph', 'figure'),
    [Input('interval-component', 'n_intervals'),
     Input('display-window', 'value')] +
    [Input(f'freq-{rtr["id"]}', 'value') for rtr in rtr_configs] +
    [Input(f'enable-{rtr["id"]}', 'value') for rtr in rtr_configs]
)
def update_graph(n_intervals, display_window, *args):
    # Process all inputs: first half are frequencies, second half are enabled states
    n_rtrs = len(rtr_configs)
    
    # Safety check for argument count
    if len(args) < n_rtrs * 2:
        print(f"Warning: Not enough arguments to update_graph. Expected {n_rtrs*2}, got {len(args)}")
        # Return empty figure if we don't have enough data
        return {
            'data': [], 
            'layout': go.Layout(
                title='CAN Bus Data (Waiting for inputs...)',
                xaxis={'title': 'Time'},
                yaxis={'title': 'Value'}
            )
        }
        
    frequencies = args[:n_rtrs]
    enabled_states = args[n_rtrs:]
    
    # Update RTR frequencies via ZMQ
    for i, rtr in enumerate(rtr_configs):
        if i >= len(frequencies) or i >= len(enabled_states):
            continue  # Skip if index out of range
            
        rtr_id = rtr['id']
        frequency = frequencies[i]
        enabled = enabled_states[i]
        
        # Send frequency update if enabled
        # Check if enabled is a list and contains 'enabled'
        is_enabled = enabled and isinstance(enabled, list) and 'enabled' in enabled
        
        if is_enabled and config_publisher:
            update_data = {
                'type': 'rtr_frequency_update',
                'id': rtr_id,
                'frequency': frequency
            }
            try:
                config_publisher.send_multipart([
                    b"CONFIG", 
                    json.dumps(update_data).encode("utf8")
                ])
            except Exception as e:
                print(f"Error sending frequency update: {e}")
    
    # Generate graph
    traces = []
    current_time = time.time()
    time_cutoff = current_time - display_window
    
    # Collect enabled RTR IDs
    enabled_rtr_ids = set()
    for i, rtr in enumerate(rtr_configs):
        if i < len(enabled_states) and enabled_states[i] and isinstance(enabled_states[i], list) and 'enabled' in enabled_states[i]:
            enabled_rtr_ids.add(parse_hex_id(rtr['id']))
    
    # Generate traces for each enabled RTR ID and variable
    for rtr in rtr_configs:
        rtr_id = parse_hex_id(rtr['id'])
        if rtr_id not in enabled_rtr_ids:
            continue
        
        for var in rtr.get('variables', []):
            var_name = var['name']
            
            # Check if we have data
            if var_name in data_buffers[rtr_id] and len(data_buffers[rtr_id][var_name]) > 0:
                # Get times and values
                times = list(timestamps[rtr_id])
                values = list(data_buffers[rtr_id][var_name])
                
                # Ensure we have matching times and values
                min_len = min(len(times), len(values))
                if min_len == 0:
                    continue
                    
                times = times[:min_len]
                values = values[:min_len]
                
                # Filter by time window
                filtered_data = [(t, v) for t, v in zip(times, values) if t >= time_cutoff]
                
                if filtered_data:
                    # Unzip filtered data
                    x_values, y_values = zip(*filtered_data)
                    
                    # Create trace
                    trace = go.Scatter(
                        x=x_values,
                        y=y_values,
                        mode='lines',
                        name=f"0x{rtr_id:X} - {var_name}"
                    )
                    traces.append(trace)
    
    # Create layout
    layout = go.Layout(
        title='CAN Bus Data',
        xaxis={
            'title': 'Time',
            'type': 'date'
        },
        yaxis={'title': 'Value'},
        margin={'l': 50, 'r': 20, 't': 50, 'b': 50}
    )
    
    return {'data': traces, 'layout': layout}

if __name__ == '__main__':
    print("Starting CAN bus dashboard")
    print("Make sure async_pub.py is running to provide data")
    app.run(debug=False, host='0.0.0.0', port=8050)