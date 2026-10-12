@echo off
REM Double-click to start KeepFrame from source (first start installs dependencies).
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (
    echo First start: setting up KeepFrame, this takes a minute...
    python -m venv .venv || (pause & exit /b 1)
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip >nul
    python -m pip install -e ".[gui,ai,raw,win]" || (pause & exit /b 1)
) else (
    call .venv\Scripts\activate.bat
    python -c "import keepframe, PySide6" 2>nul || python -m pip install -e ".[gui,ai,raw,win]" || (pause & exit /b 1)
)
start "" pythonw -m keepframe
endlocal
