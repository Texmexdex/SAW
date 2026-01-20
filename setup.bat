@echo off
echo Setting up Pole Saw Builder/Flasher Environment...

REM Check for Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed. Please install Python 3.10+
    pause
    exit /b
)

REM Create Virtual Environment
if not exist "venv" (
    echo Creating Virtual Environment...
    python -m venv venv
)

REM Install Dependencies
echo Installing PlatformIO Core (This handles compilation)...
call venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Setup Complete.
pause