SHELL := /usr/bin/env bash

#######
# Help
#######

.DEFAULT_GOAL := help
.PHONY: help mk-conda-env rm-conda-env up-conda-env run run-app run-backend run-pub run-sub run-both run-app-pub test clean monitor log setup-can0 kill kill-app kill-backend kill-pub debug-memory debug-clear-memory sim-on sim-off
# Supervised start/stop helpers
.PHONY: start-supervised stop-supervised status-supervised

debug-memory:  ## Check the status of shared memory buffers
	@echo "Checking shared memory status..."
	$(CONDA_ACTIVATE) && python debug_shared_memory.py

debug-clear-memory:  ## Periodically clear shared memory to test synchronization
	@echo "WARNING: This will clear all data buffers periodically"
	$(CONDA_ACTIVATE) && python debug_clear_memory.py
	
sim-on:  ## Enable simulation mode (no hardware needed)
	@echo "Enabling simulation mode..."
	@sed -i 's/simulation_mode:.*/simulation_mode: true  # Set to true to simulate CAN data without hardware, false for real hardware/g' config.yaml
	@echo "Simulation mode is now ON. Run your application to see simulated data."

sim-off:  ## Disable simulation mode (use real hardware)
	@echo "Disabling simulation mode..."
	@sed -i 's/simulation_mode:.*/simulation_mode: false  # Set to true to simulate CAN data without hardware, false for real hardware/g' config.yaml
	@echo "Simulation mode is now OFF. Real CAN hardware will be used."

setup-can0:  ## Set the `can0` network interface to 250 kbps (requires sudo)
	@echo "Configuring can0 interface to 250 kbps..."
	@sudo ip link set can0 down || true
	@sudo ip link set can0 type can bitrate 250000
	@sudo ip link set can0 up
	@echo "can0 is up at 250 kbps"

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

###################
# Conda Environment
###################

CONDA_ENV_NAME ?= ft-can  # Matched with conda_env.yml
CONDA_YAML = conda_env.yml
# Use source to activate conda environment for better output visibility
CONDA_ACTIVATE = source $$(conda info --base)/etc/profile.d/conda.sh && conda activate $(CONDA_ENV_NAME)

mk-conda-env: $(CONDA_ENV_NAME)  ## Build the conda environment
$(CONDA_ENV_NAME):
	conda env create --quiet --file $(CONDA_YAML)
	@echo "Environment created: $(CONDA_ENV_NAME)"

rm-conda-env:  ## Remove the conda environment and the relevant file
	conda remove --name $(CONDA_ENV_NAME) --all

up-conda-env:  ## Update the conda environment with any changes in the yml file
	conda env update --file $(CONDA_YAML) --prune
	@echo "Environment updated: $(CONDA_ENV_NAME)"

###################
# Application
# 
# New Modular Architecture:
# - async_pub.py: CAN publisher (sends RTR requests)
# - async_sub.py: Data collection backend (receives & stores data)
# - dashboard.py: Web frontend (visualization)
# - run.py: Unified runner script
###################

run: kill  ## Run complete system: publisher + backend + dashboard (recommended)
	@echo "Starting complete CAN system..."
	@echo "1. Starting ZMQ broker..."
	$(CONDA_ACTIVATE) && python zmq_broker.py & \
	sleep 1 && \
	@echo "2. Starting publisher (for RTR requests)..." && \
	$(CONDA_ACTIVATE) && python async_pub.py & \
	sleep 2 && \
	@echo "3. Starting data collection backend..." && \
	python async_sub.py & \
	sleep 2 && \
	@echo "4. Starting dashboard (for visualization and RTR frequency control)..." && \
	python dashboard.py

run-backend: kill-backend  ## Run the CAN data collection backend
	@echo "Starting CAN data collection backend..."
	$(CONDA_ACTIVATE) && python async_sub.py

run-app: kill-app  ## Run the CAN bus dashboard application only (run after run-pub)
	@echo "Starting CAN bus dashboard application..."
	@echo "NOTE: Make sure async_pub.py is already running for RTR controls to work"
	$(CONDA_ACTIVATE) && python dashboard.py

run-pub: kill-pub  ## Run the CAN publisher service with RTR handling
	@echo "Starting CAN publisher service with RTR handling..."
	$(CONDA_ACTIVATE) && python async_pub.py

run-app-pub: kill-app kill-pub  ## Run both publisher and dashboard (most common use case)
	@echo "Step 1: Cleaning up any existing ZMQ sockets..."
	-$(CONDA_ACTIVATE) && python -c "import zmq; ctx=zmq.Context(); ctx.term()" 2>/dev/null || true
	@echo "Step 1: Cleaning up any existing ZMQ sockets..."
	-$(CONDA_ACTIVATE) && python -c "import zmq; ctx=zmq.Context(); ctx.term()" 2>/dev/null || true
	@echo "Step 2: Starting ZMQ broker..."
	$(CONDA_ACTIVATE) && python zmq_broker.py & \
	sleep 1 && \
	@echo "Step 3: Starting CAN publisher service with RTR handling..." && \
	$(CONDA_ACTIVATE) && python async_pub.py & \
	sleep 3 && \
	echo "Step 4: Starting CAN bus dashboard application (controls RTR frequencies)..." && \
	$(CONDA_ACTIVATE) && python dashboard.py

run-both: kill  ## Run using the unified run.py script (backend + dashboard)
	@echo "Starting CAN system using run.py..."
	$(CONDA_ACTIVATE) && python async_pub.py & \
	sleep 2 && \
	python run.py both

test:  ## Test the modular architecture
	@echo "Testing modular architecture..."
	$(CONDA_ACTIVATE) && python test_architecture.py

run-sub:  ## Run the CAN subscriber for simple monitoring (display only)
	@echo "Starting CAN subscriber for simple monitoring..."
	$(CONDA_ACTIVATE) && python async_sub.py --simple

monitor:  ## Monitor CAN bus traffic directly
	@echo "Monitoring CAN bus traffic..."
	$(CONDA_ACTIVATE) && candump -td $(shell grep can_interface config.yaml | cut -d: -f2 | tr -d ' ')

log:  ## Log CAN bus data to csv file
	@echo "Logging CAN bus data..."
	$(CONDA_ACTIVATE) && candump -td $(shell grep can_interface config.yaml | cut -d: -f2 | tr -d ' ') > can_data_log_$(shell date +%Y%m%d_%H%M%S).csv

###################
# Utility
###################

clean:  ## Clean generated files and logs
	@echo "Cleaning generated files..."
	rm -rf __pycache__
	rm -f *.pyc
	rm -f app_deprecated.py app_old_backup.py 2>/dev/null || true
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete

kill:  ## Kill all running instances of the app
	@echo "Killing all running instances..."
	-pkill -f "python.*async_pub.py" || true
	-pkill -f "python.*async_sub.py" || true
	-pkill -f "python.*dashboard.py" || true
	@echo "Done killing all processes"

start-supervised:  ## Start broker, publisher, backend and dashboard under pidfile/log supervision
	@echo "Starting supervised services (logs -> logs/*.log, pids -> run/*.pid)"
	@mkdir -p logs run scripts || true
	$(CONDA_ACTIVATE) && bash scripts/start_services.sh

stop-supervised:  ## Stop supervised services started by start-supervised
	@echo "Stopping supervised services (using run/*.pid)..."
	bash scripts/stop_services.sh || true

status-supervised:  ## Show status of supervised services
	@printf "%-8s %-8s %s\n" "SERVICE" "PID" "LOG"
	@if [ -d run ]; then for f in run/*.pid 2>/dev/null || true; do svc=$$(basename $$f .pid); pid=$$(cat $$f 2>/dev/null || echo ""); log="logs/$$svc.log"; printf "%-8s %-8s %s\n" $$svc $$pid $$log; done; fi

kill-app:  ## Kill only the dashboard app
	@echo "Killing dashboard app instances..."
	-pkill -f "python.*dashboard.py" || true
	@echo "Done killing dashboard processes"

kill-backend:  ## Kill only the data collection backend
	@echo "Killing backend instances..."
	-pkill -f "python.*async_sub.py" || true
	@echo "Done killing backend processes"

kill-pub:  ## Kill only the publisher
	@echo "Killing publisher instances..."
	-pkill -f "python.*async_pub.py" || true
	@echo "Done killing publisher processes"

