@echo off
rem simple-ui launcher -- starts the local UI service (no console window) and opens the browser.
setlocal
set HERE=%~dp0
set PYW=%HERE%..\ComfyUI-aki-v3.2\python\pythonw.exe
set PYC=%HERE%..\ComfyUI-aki-v3.2\python\python.exe

if not exist "%PYC%" (
  echo [ERROR] ComfyUI python not found:
  echo   %PYC%
  echo.
  echo Keep this "simple-ui" folder inside the same folder as ComfyUI-aki-v3.2.
  pause
  exit /b 1
)

start "" "%PYW%" "%HERE%serve.py"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8899/
exit /b 0
