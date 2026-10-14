@echo off
rem PicMotion - stop the local UI service (the process listening on the UI port)
rem Keep this file ASCII-only (see the note in start-app.bat).
setlocal enabledelayedexpansion
set HERE=%~dp0

set PORT=8899
if exist "%HERE%port.txt" set /p PORT=<"%HERE%port.txt"

set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
  taskkill /f /pid %%p >nul 2>&1
  set FOUND=1
)
if "!FOUND!"=="1" goto stopped
echo PicMotion service is not running on port %PORT%.
goto end

:stopped
echo PicMotion service stopped ^(port %PORT%^).

:end
timeout /t 2 /nobreak >nul
exit /b 0
