@echo off
rem simple-ui -- stop the local UI service (the process listening on port 8899).
setlocal enabledelayedexpansion
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8899" ^| findstr "LISTENING"') do (
  taskkill /f /pid %%p >nul 2>&1
  set FOUND=1
)
if "!FOUND!"=="1" ( echo simple-ui stopped. ) else ( echo simple-ui is not running. )
timeout /t 2 /nobreak >nul
