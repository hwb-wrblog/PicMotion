@echo off
rem PicMotion - desktop launcher
rem   1) make sure the local UI service is running (hidden, no console window)
rem   2) open it as a standalone app window (own profile: no tabs, no address bar)
rem
rem NOTE: keep this file ASCII-only and avoid parenthesised if-blocks around
rem       paths. %ProgramFiles(x86)% expands to a path containing ")", which
rem       breaks cmd's block parsing; non-ASCII text is decoded with the OEM
rem       code page and can be executed as garbage commands.
setlocal
set HERE=%~dp0

rem --- port: written by serve.py into port.txt; fallback 8899 ---
set PORT=8899
if exist "%HERE%port.txt" set /p PORT=<"%HERE%port.txt"
set URL=http://127.0.0.1:%PORT%/
set PROFILE=%HERE%app-profile

rem --- locate a python: python.txt (written by serve.py) first, then common layouts ---
set PYW=
if exist "%HERE%python.txt" set /p PYW=<"%HERE%python.txt"
if defined PYW goto have_python
for %%P in (
  "%HERE%..\ComfyUI-aki-v3.2\python\pythonw.exe"
  "%HERE%..\..\ComfyUI-aki-v3.2\python\pythonw.exe"
  "%HERE%..\ComfyUI\python\pythonw.exe"
  "%HERE%..\..\python\pythonw.exe"
  "%HERE%..\python_embeded\pythonw.exe"
  "%HERE%..\..\python_embeded\pythonw.exe"
) do if not defined PYW if exist %%P set PYW=%%~fP
if defined PYW goto have_python

echo [ERROR] Cannot find the Python bundled with ComfyUI.
echo   1^) write the full path of pythonw.exe into: %HERE%python.txt
echo   2^) or place this folder directly under your ComfyUI folder
echo   3^) or create config.json here with the key "comfy_root"
pause
exit /b 1

:have_python
rem prefer pythonw.exe (no console window) if we only found python.exe
if /i not "%PYW:~-10%"=="python.exe" goto service
if not exist "%PYW:~0,-10%pythonw.exe" goto service
set PYW=%PYW:~0,-10%pythonw.exe

:service
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto open_window
start "" "%PYW%" "%HERE%serve.py"
timeout /t 3 /nobreak >nul

:open_window
rem SystemDrive is used instead of %ProgramFiles(x86)% on purpose (see note above)
set EDGE=%SystemDrive%\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
if exist "%EDGE%" goto run_edge
set EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe
if exist "%EDGE%" goto run_edge
set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if exist "%CHROME%" goto run_chrome
set CHROME=%SystemDrive%\Program Files (x86)\Google\Chrome\Application\chrome.exe
if exist "%CHROME%" goto run_chrome
start "" %URL%
exit /b 0

:run_edge
start "" "%EDGE%" --app=%URL% --user-data-dir=%PROFILE% --no-first-run --no-default-browser-check --window-size=1320,920
exit /b 0

:run_chrome
start "" "%CHROME%" --app=%URL% --user-data-dir=%PROFILE% --no-first-run --no-default-browser-check --window-size=1320,920
exit /b 0
