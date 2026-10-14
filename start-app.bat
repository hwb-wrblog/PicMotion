@echo off
rem PicMotion (极简画影) -- desktop launcher
rem   1) make sure the local service is running (hidden, no console window)
rem   2) open it as a standalone app window: own profile => own window, no tabs, no address bar
setlocal
set HERE=%~dp0

rem --- port: written by serve.py into port.txt; falls back to 8899 ---
set PORT=8899
if exist "%HERE%port.txt" set /p PORT=<"%HERE%port.txt"
set URL=http://127.0.0.1:%PORT%/
set PROFILE=%HERE%app-profile

rem --- find a python: python.txt (written by serve.py) first, then common portable layouts ---
set PYW=
if exist "%HERE%python.txt" set /p PYW=<"%HERE%python.txt"
if not defined PYW (
  for %%P in (
    "%HERE%..\ComfyUI-aki-v3.2\python\pythonw.exe"
    "%HERE%..\..\ComfyUI-aki-v3.2\python\pythonw.exe"
    "%HERE%..\ComfyUI\python\pythonw.exe"
    "%HERE%..\..\python\pythonw.exe"
    "%HERE%..\python_embeded\pythonw.exe"
    "%HERE%..\..\python_embeded\pythonw.exe"
  ) do if not defined PYW if exist %%P set PYW=%%~fP
)
rem if we only found python.exe, prefer pythonw.exe next to it (no console window)
if defined PYW if /i "%PYW:~-10%"=="python.exe" if exist "%PYW:~0,-10%pythonw.exe" set PYW=%PYW:~0,-10%pythonw.exe

if not defined PYW (
  echo [ERROR] 找不到 ComfyUI 自带的 python。
  echo   办法一：在 %HERE%python.txt 里写一行 pythonw.exe 的完整路径
  echo   办法二：把本目录放进 ComfyUI 整合包根目录的下一层
  echo   办法三：在本目录建 config.json 写明 comfy_root
  pause
  exit /b 1
)

rem 1) service up?
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  start "" "%PYW%" "%HERE%serve.py"
  timeout /t 3 /nobreak >nul
)

rem 2) open as an app window (dedicated profile keeps it independent from normal browsing)
set EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE%" set EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe
set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe

if exist "%EDGE%" (
  start "" "%EDGE%" --app=%URL% --user-data-dir=%PROFILE% --no-first-run --no-default-browser-check --window-size=1320,920
) else if exist "%CHROME%" (
  start "" "%CHROME%" --app=%URL% --user-data-dir=%PROFILE% --no-first-run --no-default-browser-check --window-size=1320,920
) else (
  start "" %URL%
)
exit /b 0
