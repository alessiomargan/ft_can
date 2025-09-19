SHELL := /usr/bin/env bash

#######
# Help
#######

.DEFAULT_GOAL := help
.PHONY: help mk-conda-env rm-conda-env up-conda-env run run-app run-backend run-pub run-sub run-both test clean monitor log kill kill-app kill-backend kill-pub

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
	@echo "Starting complete CAN system (publisher, data collection, then dashboard)..."
	$(CONDA_ACTIVATE) && python async_pub.py & \
	sleep 2 && \
	python async_sub.py & \
	sleep 2 && \
	python dashboard.py

run-backend: kill-backend  ## Run the CAN data collection backend
	@echo "Starting CAN data collection backend..."
	$(CONDA_ACTIVATE) && python async_sub.py

run-app: kill-app  ## Run the CAN bus dashboard application only
	@echo "Starting CAN bus dashboard application..."
	$(CONDA_ACTIVATE) && python dashboard.py

run-pub: kill-pub  ## Run the CAN publisher service with RTR handling
	@echo "Starting CAN publisher service with RTR handling..."
	$(CONDA_ACTIVATE) && python async_pub.py

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

