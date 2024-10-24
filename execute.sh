#!/bin/bash

# Step 1: Create a Python virtual environment named "myenv"
python -m venv myenv

# Step 2: Activate the virtual environment
source myenv/Scripts/activate

# Step 3: Install required Python packages from 'requirements.txt'
pip install -r requirements.txt

# Step 4: Run the Python file 'web_app.py'
python web_app.py