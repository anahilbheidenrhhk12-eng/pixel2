@echo off
cd /d "%~dp0"
if not exist "DigiPixelServer.exe" (
 echo DigiPixelServer.exe is missing. Extract the ZIP before starting.
 pause
 exit /b 1
)
start "" "DigiPixelServer.exe"
