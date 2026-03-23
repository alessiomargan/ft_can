SHELL := /usr/bin/env bash

#######
# Help
#######

.DEFAULT_GOAL := help
.PHONY: help mk-conda-env rm-conda-env up-conda-env run run-broker run-pub run-sub run-dash run-loader test clean monitor log setup-can0 kill kill-dash kill-sub kill-pub kill-broker debug-memory debug-clear-memory sim-on sim-off
# Supervised start/stop helpers
.PHONY: start-supervised stop-supervised status-supervised

debug-memory:  ## Check the status of shared memory buffers
	@echo "Checking shared memory status..."
	$(CONDA_RUN) python debug_shared_memory.py

debug-clear-memory:  ## Periodically clear shared memory to test synchronization
	@echo "WARNING: This will clear all data buffers periodically"
	$(CONDA_RUN) python debug_clear_memory.py
	
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
# Use conda run to avoid shell activation issues in multiline/background recipes.
CONDA_RUN = conda run --no-capture-output --name $(CONDA_ENV_NAME)

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
# - zmq_broker.py: ZMQ forwarder between publishers and subscribers
###################

run: kill  ## Run complete system (broker, publisher, backend, dashboard)
	@echo "Starting complete CAN system..."
	$(CONDA_RUN) python zmq_broker.py & \
	sleep 1 && \
	$(CONDA_RUN) python async_pub.py & \
	sleep 2 && \
	$(CONDA_RUN) python async_sub.py & \
	sleep 2 && \
	$(CONDA_RUN) python dashboard.py

run-broker: kill-broker ## Run the ZMQ broker (start this before other components)
	@echo "Starting ZMQ broker..."
	$(CONDA_RUN) python zmq_broker.py

run-pub: kill-pub  ## Run the CAN publisher service with RTR handling
	@echo "Starting CAN publisher service with RTR handling..."
	$(CONDA_RUN) python async_pub.py

run-sub: kill-sub  ## Run the CAN data collection backend
	@echo "Starting CAN data collection backend..."
	$(CONDA_RUN) python async_sub.py

run-dash: kill-dash  ## Run the CAN bus dashboard application only (run after run-pub)
	@echo "Starting CAN bus dashboard application..."
	$(CONDA_RUN) python dashboard.py

run-loader:  ## Run CAN bootloader host (usage: make run-loader FILE=path/to/fw.bin [SLOT=0 CHANNEL=can0 interface=socketcan BITRATE=250000])
	@if [ -z "$(FILE)" ]; then \
		echo "Error: FILE is required"; \
		echo "Usage: make run-loader FILE=path/to/fw.bin [SLOT=0 CHANNEL=can0 INTERFACE=socketcan BITRATE=250000]"; \
		exit 1; \
	fi
	@echo "Running CAN loader for $(FILE)..."
	$(CONDA_RUN) python can_loader.py "$(FILE)" --slot $${SLOT:-0} --channel $${CHANNEL:-can0} --interface $${INTERFACE:-socketcan} --bitrate $${BITRATE:-250000}

test:  ## Test the modular architecture
	@echo "Testing modular architecture..."
	$(CONDA_RUN) python test_architecture.py

monitor:  ## Monitor CAN bus traffic directly
	@echo "Monitoring CAN bus traffic..."
	$(CONDA_RUN) candump -td $(shell grep can_interface config.yaml | cut -d: -f2 | tr -d ' ')

log:  ## Log CAN bus data to csv file
	@echo "Logging CAN bus data..."
	$(CONDA_RUN) candump -td $(shell grep can_interface config.yaml | cut -d: -f2 | tr -d ' ') > can_data_log_$(shell date +%Y%m%d_%H%M%S).csv

###################
# Utility
###################

clean:  ## Clean generated files and logs
	@echo "Cleaning generated files..."
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete

kill:  ## Kill all running instances of the app
	@echo "Killing all running instances..."
	-pkill -f "python.*zmq_broker.py" || true
	-pkill -f "python.*async_pub.py" || true
	-pkill -f "python.*async_sub.py" || true
	-pkill -f "python.*dashboard.py" || true
	@echo "Done killing all processes"

start-supervised:  ## Start broker, publisher, backend and dashboard under pidfile/log supervision (use FORCE=1 to ignore pidfiles)
	@echo "Starting supervised services (logs -> logs/*.log, pids -> run/*.pid)"
	@mkdir -p logs run scripts || true
	@echo "Note: to ignore stale pidfiles run: make start-supervised FORCE=1"
	CONDA_ENV_NAME=$(CONDA_ENV_NAME) FORCE=$${FORCE:-0} bash scripts/start_services.sh

stop-supervised:  ## Stop supervised services started by start-supervised
	@echo "Stopping supervised services (using run/*.pid)..."
	bash scripts/stop_services.sh || true

status-supervised:  ## Show status of supervised services
	@printf "%-8s %-8s %s\n" "SERVICE" "PID" "LOG"
	@if [ -d run ]; then for f in run/*.pid 2>/dev/null || true; do svc=$$(basename $$f .pid); pid=$$(cat $$f 2>/dev/null || echo ""); log="logs/$$svc.log"; printf "%-8s %-8s %s\n" $$svc $$pid $$log; done; fi

kill-dash:  ## Kill only the dashboard app
	@echo "Killing dashboard app instances..."
	-pkill -f "python.*dashboard.py" || true
	@echo "Done killing dashboard processes"

kill-sub:  ## Kill only the data collection backend
	@echo "Killing backend instances..."
	-pkill -f "python.*async_sub.py" || true
	@echo "Done killing backend processes"

kill-pub:  ## Kill only the publisher
	@echo "Killing publisher instances..."
	-pkill -f "python.*async_pub.py" || true
	@echo "Done killing publisher processes"

kill-broker:  ## Kill only the ZMQ broker
	@echo "Killing ZMQ broker..."
	-pkill -f "python.*zmq_broker.py" || true
	@echo "Done killing broker"
