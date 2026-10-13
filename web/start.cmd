@echo off
rem Double-click this file to run Chorus on Windows.
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is not installed.
  echo Install the LTS version from https://nodejs.org, then double-click start.cmd again.
  echo.
  echo Or skip installing anything and use the online version:
  echo   https://av1452.github.io/harmonyforge/
  pause
  exit /b 1
)
node serve.mjs %*
pause
