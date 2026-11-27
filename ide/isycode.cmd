@echo off
setlocal
chcp 65001 >nul 2>nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\isycode.exe" (
  "%~dp0.venv\Scripts\isycode.exe" %*
  exit /b %ERRORLEVEL%
)

python -m isyvm %*
exit /b %ERRORLEVEL%
