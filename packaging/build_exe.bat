@echo off
REM Builds dist\KeepFrame\KeepFrame.exe (and the installer if Inno Setup is installed).
REM Run from anywhere: packaging\build_exe.bat
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul || (echo Python 3.10+ is required: https://www.python.org/downloads/ & exit /b 1)

if not exist .venv-build (
    echo [1/4] Creating build environment...
    python -m venv .venv-build || exit /b 1
)
call .venv-build\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -e ".[gui,ai,raw,win,build]" || exit /b 1

if not exist src\keepframe\models\dinov2_vits14.onnx (
    echo.
    echo NOTE: AI model not found. The EXE will work in quick mode only.
    echo       To include the model run tools\get_model.bat first, then build again.
    echo.
)

echo [3/4] Building KeepFrame.exe ...
pyinstaller packaging\keepframe.spec --noconfirm --clean || exit /b 1

echo [4/4] Installer...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% packaging\installer.iss
) else (
    echo Inno Setup 6 not found - skipping installer. Portable app is in dist\KeepFrame\
)

echo.
echo Done:  dist\KeepFrame\KeepFrame.exe
endlocal
