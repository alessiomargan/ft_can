SHELL := /usr/bin/env bash

#######
# Help
#######

.DEFAULT_GOAL := help
.PHONY: help mk-conda-env rm-conda-env up-conda-env run run-app run-pub run-sub clean monitor log kill

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
###################

run: run-pub run-app  ## Run both publisher and dashboard app

run-app: kill  ## Run the CAN bus dashboard application
	@echo "Starting CAN bus dashboard application..."
	$(CONDA_ACTIVATE) && python app.py

run-pub: kill  ## Run the CAN publisher service with RTR handling
	@echo "Starting CAN publisher service with RTR handling..."
	$(CONDA_ACTIVATE) && python async_pub.py

run-sub:  ## Run the CAN subscriber to monitor messages
	@echo "Starting CAN subscriber to monitor messages..."
	$(CONDA_ACTIVATE) && python async_sub.py

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
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete

kill:  ## Kill any running instances of the app
	@echo "Killing any running instances..."
	-pkill -f "python.*async_pub.py" || true
	-pkill -f "python.*app.py" || true
	@echo "Done killing processes"

