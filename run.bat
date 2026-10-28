@echo off
REM One-click runner for Windows. Creates a virtual env on first use.
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)
if not exist .env (
    echo.
    echo [!] .env not found. Copy .env.example to .env and add your GEMINI_API_KEY, then run again.
    pause
    exit /b 1
)
if not exist profile.json (
    echo.
    echo [!] profile.json not found. Copy profile.example.json to profile.json and fill it in, then run again.
    pause
    exit /b 1
)
python main.py %*
pause
