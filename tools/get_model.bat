@echo off
REM One-time: download DINOv2-small (Apache-2.0) and convert it to ONNX for KeepFrame.
REM Needs internet (~300 MB). Uses a separate environment so torch is never bundled into the app.
REM Everything is also written to tools\get_model.log.
setlocal
cd /d "%~dp0\.."
set LOG=tools\get_model.log
echo KeepFrame model setup %DATE% %TIME% > %LOG%

where python >nul 2>nul || (echo Python 3.10+ is required & pause & exit /b 1)

if not exist .venv-model (
    echo [1/3] Creating environment...
    python -m venv .venv-model >> %LOG% 2>&1 || goto :fail
)
call .venv-model\Scripts\activate.bat

echo [2/3] Installing PyTorch (CPU) and tools - this can take a few minutes...
python -m pip install --upgrade pip >> %LOG% 2>&1
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu >> %LOG% 2>&1 || goto :fail
python -m pip install "transformers>=4.40" onnx onnxscript onnxruntime numpy >> %LOG% 2>&1 || goto :fail

echo [3/3] Downloading and converting the model...
python tools\export_dinov2_onnx.py >> %LOG% 2>&1 || goto :fail

echo.
echo MODEL READY. Restart KeepFrame - the status bar should say "AI model ready".
echo.
pause
endlocal
exit /b 0

:fail
echo.
echo FAILED. Last lines of %LOG%:
echo ----------------------------------------
powershell -NoProfile -Command "Get-Content -Tail 25 '%LOG%'"
echo ----------------------------------------
pause
endlocal
exit /b 1
