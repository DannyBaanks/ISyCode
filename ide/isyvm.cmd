@echo off
setlocal
chcp 65001 >nul 2>nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if "%~1"=="" (
  "%PY%" -m engine.bootstrap whoami
  echo.
  "%PY%" -m engine.bootstrap
  exit /b 0
)

:: Agent subcommand: strip leading "agent"
if "%~1"=="agent" (
  shift
  "%PY%" -m isyvm.agent_cli %*
  exit /b %ERRORLEVEL%
)

"%PY%" -m engine.bootstrap %*
exit /b %ERRORLEVEL%