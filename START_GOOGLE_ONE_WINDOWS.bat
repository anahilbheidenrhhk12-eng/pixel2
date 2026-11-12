@echo off
setlocal
cd /d "%~dp0"
echo.
echo Google One native Android test for Windows
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_google_one_windows.ps1"
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" echo Test launcher ended with error code %CODE%.
echo Press any key to close this window.
pause >nul
exit /b %CODE%
