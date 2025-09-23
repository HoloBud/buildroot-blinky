#!/bin/sh

echo "Create a virtual environment in .venv"
cd ../app
python3 -m venv .venv

# Check if it was created successfully
if [ ! -f .venv/bin/activate ]; then
    echo "Error: Could not create virtual environment"
    exit 1
fi

echo "Upgrade pip and setuptools"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --upgrade setuptools

echo "Install the current package in editable mode"
.venv/bin/python -m pip install -e .

echo "Activate the virtual environment"
source .venv/bin/activate

# Final output
echo "============================"
echo "Virtual environment ready"
echo "Activated: .venv"
echo "Dependencies installed from setup.py"
echo "============================"
