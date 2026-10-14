@echo off
rem PicMotion - start the local UI service (no console window) and open the browser
rem Keep this file ASCII-only (see the note in start-app.bat).
setlocal
set HERE=%~dp0

set PORT=8899
if exist "%HERE%port.txt" set /p PORT=<"%HERE%port.txt"

set PYW=
if exist "%HERE%python.txt" set /p PYW=<"%HERE%python.txt"
if defined PYW goto go
for %%P in (
  "%HERE%..\ComfyUI-aki-v3.2\python\pythonw.exe"
  "%HERE%..\..\ComfyUI-aki-v3.2\python\pythonw.exe"
  "%HERE%..\ComfyUI\python\pythonw.exe"
  "%HERE%..\..\python\pythonw.exe"
  "%HERE%..\python_embeded\pythonw.exe"
) do if not defined PYW if exist %%P set PYW=%%~fP
if defined PYW goto go

echo [ERROR] Cannot find the Python bundled with ComfyUI.
echo   Put the full path of pythonw.exe into %HERE%python.txt, or place this
echo   folder directly under your ComfyUI folder. See README.md for details.
pause
exit /b 1

:go
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto open
start "" "%PYW%" "%HERE%serve.py"
timeout /t 3 /nobreak >nul

:open
start "" http://127.0.0.1:%PORT%/
exit /b 0
