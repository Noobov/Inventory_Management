@echo off
REM Step 1: Create a Python virtual environment named "myenv"
python -m venv myenv

REM Step 2: Activate the virtual environment
call myenv\Scripts\activate

REM Step 3: Install required Python packages from 'requirements.txt'
pip install -r requirements.txt

REM Step 4: Run the Python file 'web_app.py'
python web_app.py