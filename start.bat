@echo off
setlocal

cd /d "%~dp0"
title AUTOPIXEL

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "ENV_FILE=%~dp0.env"
set "ENV_EXAMPLE=%~dp0.env.example"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment Python not found:
    echo         "%PYTHON_EXE%"
    echo.
    echo Create it first with:
    echo   python -m venv .venv
    echo   .\.venv\Scripts\python.exe -m pip install --upgrade pip
    echo   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%ENV_FILE%" (
    if exist "%ENV_EXAMPLE%" (
        copy /y "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
        echo [INFO] .env was missing, so it was created from .env.example
        echo.
    ) else (
        echo [WARNING] .env not found and .env.example is also missing.
        echo.
    )
)

echo [INFO] Starting AUTOPIXEL...
echo.
"%PYTHON_EXE%" "%~dp0main.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] AUTOPIXEL stopped with exit code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
