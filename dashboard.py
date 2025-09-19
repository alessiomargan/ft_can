import dash
import sys
from dash import dcc, html
from dash.dependencies import Output, Input, State
import plotly.graph_objs as go
import threading
import time
import json
import zmq

# Import utilities and shared data
from utils import parse_hex_id
from shared_data import (
    data_buffers, timestamps, enabled_ids, enabled_ids_lock, 
    rtr_configs, get_config_publisher, BUFFER_SIZE, DISPLAY_WINDOW
)

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
            
            try:
                # Send the configuration update
                config_pub = get_config_publisher()
                if config_pub:
                    config_pub.send_multipart([
                        b"CONFIG", 
                        json.dumps(update_data).encode("utf8")
                    ])
                    print(f"Dashboard sent frequency update for {rtr_id} to {frequency}Hz")
                else:
                    print("Config publisher not available")
            except Exception as e:
                print(f"Error sending frequency update: {e}")
        
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
    Input('data-resolution', 'value'),
    Input('max-points-slider', 'value'),
    *output_states
)
def update_graph(n, display_window_seconds, data_resolution, max_points, *enabled_lists):
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
                    
                    # Create the trace
                    trace = go.Scatter(
                        x=filtered_times,
                        y=filtered_values,
                        mode='lines+markers',
                        name=f'0x{rtr_id:X} {name}',
                        line=dict(
                            shape='linear'
                        ),
                        marker=dict(size=3)
                    )
                    
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

def run_dashboard():
    """Function to run the dashboard"""
    print("Starting Dash dashboard without debug mode to prevent port conflicts")
    app.run(debug=False, host='0.0.0.0', port=8050)

if __name__ == '__main__':
    run_dashboard()