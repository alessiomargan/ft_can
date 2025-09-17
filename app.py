import asyncio
import dash
from dash import dcc, html
from dash.dependencies import Output, Input, State
import plotly.graph_objs as go
from collections import deque, defaultdict
import threading
import time
import yaml
import json
import csv
import zmq
import zmq.asyncio
import numpy as np
from scipy import signal
import pandas as pd

# Import utilities
from utils import get_address, load_config, parse_hex_id

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

# Define smoothing functions
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

# Global data dictionary to store sensor values
sensor_data = {}

# Setup ZMQ publisher for sending configuration updates
config_publisher = zmq.Context().socket(zmq.PUB)
config_publisher.bind("tcp://127.0.0.1:10102")  # Use a different port for config

# Define locks and global variables
csv_log_lock = threading.Lock()
csv_log_file = 'can_data_log.csv'
enabled_ids_lock = threading.Lock()
enabled_ids = set(parse_hex_id(rtr['id']) for rtr in rtr_configs)  # Initialize with all RTR IDs

# Create data buffers with calculated size
def init_csv_log():
    with csv_log_lock:
        with open(csv_log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            # Header: timestamp, rtr_id, variable, value
            writer.writerow(['timestamp', 'rtr_id', 'variable', 'value'])

init_csv_log()

# Async ZMQ subscriber to receive CAN data
async def subscribe_to_can_data():
    # Create ZMQ subscriber
    ctx = zmq.asyncio.Context()
    subscriber = ctx.socket(zmq.SUB)
    subscriber.connect(get_address())
    
    # Subscribe to all topics
    subscriber.subscribe(b"")
    
    print(f"ZMQ subscriber connected to {get_address()}")
    
    while True:
        try:
            # Receive message with topic
            topic, data = await subscriber.recv_multipart()
            topic_str = topic.decode('utf8')
            
            # Parse the JSON data
            received_data = json.loads(data.decode('utf8'))
            
            # Process data based on topic
            if topic_str.startswith("CAN_"):
                # Extract CAN ID from topic (format: "CAN_XXX" where XXX is hex)
                can_id_hex = topic_str.split("_")[1]
                can_id = int(can_id_hex, 16)
                
                # Check if this ID is enabled for display
                with enabled_ids_lock:
                    if can_id not in enabled_ids:
                        continue
                
                # Find the corresponding RTR config
                rtr_config = None
                for rtr in rtr_configs:
                    if parse_hex_id(rtr['id']) == can_id:
                        rtr_config = rtr
                        break
                
                if rtr_config:
                    # Add timestamp
                    current_time = time.time()
                    timestamps[can_id].append(current_time)
                    
                    # Process each variable
                    for var_name, value in received_data.items():
                        # Store the value in the buffer
                        data_buffers[can_id][var_name].append(value)
                        
                        # Log to CSV
                        with csv_log_lock:
                            with open(csv_log_file, 'a', newline='') as f:
                                writer = csv.writer(f)
                                writer.writerow([
                                    current_time,
                                    f"0x{can_id:X}",
                                    var_name,
                                    value
                                ])
            
            elif topic_str == "SENSORS":
                # This topic contains all accumulated sensor data
                # We can use this for a global view if needed
                pass
                
        except (asyncio.CancelledError, KeyboardInterrupt):
            print("ZMQ subscription interrupted")
            break
        except Exception as e:
            print(f"Error processing ZMQ message: {e}")
            await asyncio.sleep(0.1)

# Start asyncio loop in background thread
def start_async_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(subscribe_to_can_data())

threading.Thread(target=start_async_loop, daemon=True).start()

# Dash app
app = dash.Dash(__name__)
app.layout = html.Div([
    html.H2("Real-Time CAN Data via ZMQ"),
    
    html.Div([
        html.Div([
            html.H4("CAN Configuration"),
            html.Div([
                html.Div([
                    html.Label(f"RTR ID: {rtr['id']}"),
                    html.Div([
                        html.Label(f"Frequency (Hz):"),
                        dcc.Slider(
                            id=f'freq-slider-{rtr["id"]}',
                            min=1,
                            max=50,
                            step=1,
                            value=float(rtr.get('freq', 10)),  # Default from config or 10Hz
                            marks={
                                1: '1',
                                10: '10',
                                20: '20',
                                30: '30',
                                40: '40',
                                50: '50'
                            }
                        ),
                    ]),
                    dcc.Checklist(
                        id=f'enable-{rtr["id"]}',
                        options=[{'label': 'Enable', 'value': 'enabled'}],
                        value=['enabled'],
                        inline=True
                    )
                ], style={'marginBottom': '15px', 'padding': '10px', 'border': '1px solid #ddd', 'borderRadius': '5px'})
            for rtr in rtr_configs
            ])
        ], style={'width': '100%', 'marginBottom': '20px'}),
    ]),
    dcc.Graph(id='can-graph'),
    html.Div([
        html.Div([
            html.Label("Update Interval: "),
            dcc.Slider(
                id='update-interval-slider',
                min=100,
                max=2000,
                step=100,
                value=500,
                marks={
                    100: '100ms',
                    500: '500ms',
                    1000: '1s',
                    2000: '2s'
                }
            )
        ], style={'width': '48%', 'display': 'inline-block'}),
        
        html.Div([
            html.Label("Display Window (seconds): "),
            dcc.Slider(
                id='display-window-slider',
                min=30,
                max=DISPLAY_WINDOW,
                step=30,
                value=60,  # Default to 1 minute
                marks={
                    30: '30s',
                    60: '1m',
                    300: '5m',
                    DISPLAY_WINDOW: f'{DISPLAY_WINDOW//60}m'
                }
            )
        ], style={'width': '48%', 'display': 'inline-block'})
    ], style={'margin-top': '20px', 'margin-bottom': '20px'}),
    
    html.Div([
        html.Div([
            html.Label("Smoothing Method:"),
            dcc.RadioItems(
                id='smoothing-method',
                options=[
                    {'label': 'None', 'value': 'none'},
                    {'label': 'Moving Average', 'value': 'moving_avg'},
                    {'label': 'Savitzky-Golay', 'value': 'savgol'},
                    {'label': 'Exponential', 'value': 'exponential'}
                ],
                value='none',
                labelStyle={'display': 'inline-block', 'margin-right': '10px'}
            )
        ], style={'width': '48%', 'display': 'inline-block'}),
        
        html.Div([
            html.Label("Smoothing Window Size:"),
            dcc.Slider(
                id='smoothing-window-slider',
                min=3,
                max=51,
                step=2,  # Only odd numbers for window size
                value=11,
                marks={
                    3: '3',
                    11: '11',
                    21: '21',
                    31: '31',
                    51: '51'
                }
            )
        ], style={'width': '48%', 'display': 'inline-block'})
    ], style={'margin-bottom': '20px'}),
    
    html.Div([
        html.Div([
            html.Label("Data Resolution:"),
            dcc.RadioItems(
                id='data-resolution',
                options=[
                    {'label': 'Optimized (Downsampled)', 'value': 'downsampled'},
                    {'label': 'Full Resolution', 'value': 'full'}
                ],
                value='downsampled',
                labelStyle={'display': 'inline-block', 'margin-right': '10px'}
            )
        ], style={'width': '48%', 'display': 'inline-block'}),
        
        html.Div([
            html.Label("Maximum Points (if downsampling):"),
            dcc.Slider(
                id='max-points-slider',
                min=500,
                max=10000,
                step=500,
                value=1000,
                marks={
                    500: '500',
                    1000: '1k',
                    2500: '2.5k',
                    5000: '5k',
                    10000: '10k'
                }
            )
        ], style={'width': '48%', 'display': 'inline-block'})
    ], style={'margin-bottom': '20px'}),
    dcc.Interval(id='interval-component', interval=500, n_intervals=0)
])

# Dynamically create State for each checklist
output_states = [State(f'enable-{rtr["id"]}', 'value') for rtr in rtr_configs]

# Create dynamic callbacks for each RTR frequency slider
for rtr in rtr_configs:
    rtr_id = rtr['id']
    
    @app.callback(
        Output('interval-component', 'disabled'),  # Dummy output, not actually used
        Input(f'freq-slider-{rtr_id}', 'value'),
        State(f'enable-{rtr_id}', 'value'),
        prevent_initial_call=True  # Prevent callback on initial load
    )
    def update_rtr_frequency(frequency, enabled, rtr_id=rtr_id):
        if 'enabled' in enabled:
            # Send updated frequency to async_pub via ZMQ
            update_data = {
                'type': 'rtr_frequency_update',
                'id': rtr_id,
                'frequency': frequency
            }
            # Send the configuration update
            config_publisher.send_multipart([
                b"CONFIG", 
                json.dumps(update_data).encode("utf8")
            ])
            print(f"Updated frequency for {rtr_id} to {frequency}Hz")
        
        # Return False to keep the interval component enabled
        return False

@app.callback(
    Output('interval-component', 'interval'),
    Input('update-interval-slider', 'value')
)
def update_interval(value):
    return value

@app.callback(
    Output('can-graph', 'figure'),
    Input('interval-component', 'n_intervals'),
    Input('display-window-slider', 'value'),
    Input('smoothing-method', 'value'),
    Input('smoothing-window-slider', 'value'),
    Input('data-resolution', 'value'),
    Input('max-points-slider', 'value'),
    *output_states
)
def update_graph(n, display_window_seconds, smoothing_method, smoothing_window, 
                 data_resolution, max_points, *enabled_lists):
    new_enabled_ids = set()
    for idx, enabled in enumerate(enabled_lists):
        if 'enabled' in enabled:
            new_enabled_ids.add(parse_hex_id(rtr_configs[idx]['id']))
    
    # Update global enabled_ids for filtering
    with enabled_ids_lock:
        enabled_ids.clear()
        enabled_ids.update(new_enabled_ids)
    
    traces = []
    current_time = time.time()
    time_cutoff = current_time - display_window_seconds
    
    for rtr in rtr_configs:
        rtr_id = parse_hex_id(rtr['id'])
        if rtr_id not in new_enabled_ids:
            continue
        
        for var in rtr['variables']:
            name = var['name']
            # Check if we have data for this variable
            if name in data_buffers[rtr_id] and len(data_buffers[rtr_id][name]) > 0:
                # Filter data points based on the selected time window
                times = list(timestamps[rtr_id])
                values = list(data_buffers[rtr_id][name])
                
                # Only keep points within the selected time window
                filtered_data = [(t, v) for t, v in zip(times, values) if t >= time_cutoff]
                
                if filtered_data:
                    filtered_times, filtered_values = zip(*filtered_data)
                    
                    # Apply downsampling if selected and needed
                    if data_resolution == 'downsampled' and len(filtered_times) > max_points:
                        # Calculate the downsampling factor
                        downsample_factor = len(filtered_times) // max_points
                        # Ensure factor is at least 1
                        downsample_factor = max(1, downsample_factor)
                        
                        # Apply downsampling
                        filtered_times = filtered_times[::downsample_factor]
                        filtered_values = filtered_values[::downsample_factor]
                        
                        print(f"Downsampled from {len(filtered_data)} to {len(filtered_times)} points")
                    elif data_resolution == 'full' and len(filtered_times) > 10000:
                        # Warning for very large datasets
                        print(f"Plotting {len(filtered_times)} points at full resolution - may affect performance")
                    
                    # Apply smoothing if selected
                    smoothed_times, smoothed_values = apply_smoothing(
                        filtered_times, 
                        filtered_values, 
                        smoothing_method, 
                        smoothing_window
                    )
                    
                    # Create the trace
                    trace = go.Scatter(
                        x=smoothed_times,
                        y=smoothed_values,
                        mode='lines',  # Changed from 'lines+markers' for smoother appearance
                        name=f'0x{rtr_id:X} {name}',
                        line=dict(
                            shape='spline',  # Use spline interpolation for smoother curves
                            smoothing=1.3 if smoothing_method != 'none' else 0.5  # Adjust curve smoothness
                        )
                    )
                    
                    # If not using smoothing, add the original points as markers
                    if smoothing_method == 'none':
                        # Add original points as markers
                        marker_trace = go.Scatter(
                            x=smoothed_times,
                            y=smoothed_values,
                            mode='markers',
                            marker=dict(size=3),
                            name=f'0x{rtr_id:X} {name} (points)',
                            showlegend=False
                        )
                        traces.append(marker_trace)
                    
                    traces.append(trace)
    
    # Create the figure layout
    layout = go.Layout(
        title='CAN Variables over Time', 
        xaxis={
            'title': 'Time',
            'type': 'date',
            'range': [time_cutoff, current_time]
        }, 
        yaxis={'title': 'Value'},
        legend={'title': 'Variables'},
        hovermode='closest',
        margin=dict(l=50, r=20, t=50, b=50),
        plot_bgcolor='rgb(250, 250, 250)',
        paper_bgcolor='white'
    )
    
    # Return the complete figure
    return {'data': traces, 'layout': layout}

if __name__ == '__main__':
    app.run(debug=True)